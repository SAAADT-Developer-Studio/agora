"""Export recently published articles as an INSERT-only SQL file for dev.

Loads the repo-root .env and reads SOURCE_DATABASE_URL, falling back to
DATABASE_URL, in a read-only, repeatable-read transaction. The file contains only
INSERT statements for publishers and articles. Dev assigns article IDs; existing
URLs are refreshed. Cluster data and source article IDs are never exported.
"""

import argparse
from datetime import datetime, timedelta, timezone
from itertools import islice
import os
from pathlib import Path
import sys
from time import monotonic
from uuid import uuid4

import psycopg2
from psycopg2 import extensions, sql
from psycopg2.extras import wait_select
from dotenv import load_dotenv


REPO_ROOT = Path(__file__).resolve().parents[2]


TABLES = (
    ("news_provider", "key"),
    ("article", "id"),
)
BATCH_SIZE = 500


def batches(values):
    iterator = iter(sorted(values))
    while batch := list(islice(iterator, BATCH_SIZE)):
        yield batch


def select_keys(cursor, bounds, report):
    """Select by publication time without consulting any cluster tables."""
    keys = {table: set() for table, _ in TABLES}
    report("Selecting articles by publication time...")
    cursor.execute(
        "SELECT id, news_provider_key FROM public.article "
        "WHERE published_at >= %(since)s AND published_at <= %(through)s", bounds,
    )
    for article_id, provider_key in cursor.fetchall():
        keys["article"].add(article_id)
        keys["news_provider"].add(provider_key)
    report(f"Selected {len(keys['article']):,} articles and {len(keys['news_provider']):,} publishers")
    return keys


def export_articles(source_url: str, output: Path, days: int = 5, *, query_timeout: int = 60) -> dict[str, int]:
    if days < 1:
        raise ValueError("days must be positive")
    if query_timeout < 1:
        raise ValueError("query_timeout must be positive")
    started = monotonic()

    def report(message):
        print(f"[{monotonic() - started:6.1f}s] {message}", file=sys.stderr, flush=True)

    # Exclusive creation prevents replacing an earlier sample. No URL is written
    # into the dump. Remove an incomplete export if any database/file step fails.
    fd = os.open(output, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    counts: dict[str, int] = {}
    previous_wait_callback = extensions.get_wait_callback()
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as stream:
            report(f"Output: {output.resolve()}")
            report("Connecting to source database (15s timeout)...")
            connection = psycopg2.connect(source_url, connect_timeout=15, application_name="article_sample_export")
            try:
                # Register after connecting so libpq's connect_timeout still
                # applies. wait_select lets Ctrl-C cancel an in-flight query.
                extensions.set_wait_callback(wait_select)
                connection.set_session(isolation_level="REPEATABLE READ", readonly=True)
                report(f"Connected; query timeout {query_timeout}s, lock timeout 5s")
                with connection, connection.cursor() as cursor:
                    cursor.execute("SET LOCAL statement_timeout = %s", (query_timeout * 1000,))
                    cursor.execute("SET LOCAL lock_timeout = '5s'")
                    cursor.execute("SET LOCAL TIME ZONE 'UTC'")
                    cursor.execute("SET LOCAL DateStyle = 'ISO, YMD'")
                    cursor.execute("SET LOCAL extra_float_digits = 3")
                    cursor.execute("SELECT CURRENT_TIMESTAMP")
                    through = cursor.fetchone()[0]
                    bounds = {"since": through - timedelta(days=days), "through": through}
                    keys = select_keys(cursor, bounds, report)
                    for table, primary_key in TABLES:
                        total = len(keys[table])
                        counts[table] = 0
                        report(f"Exporting {table}: {total:,} rows...")
                        if not total:
                            continue
                        # Read the source's actual columns: production may not yet
                        # have nullable ranking columns introduced in this branch.
                        cursor.execute(
                            "SELECT attname FROM pg_attribute "
                            "WHERE attrelid = %s::regclass AND attnum > 0 "
                            "AND NOT attisdropped AND attgenerated = '' ORDER BY attnum",
                            (f"public.{table}",),
                        )
                        columns = [row[0] for row in cursor.fetchall()]
                        if table == "article":
                            columns = [name for name in columns if name != "id"]
                        if not columns:
                            raise ValueError(f"No columns found for public.{table}")
                        relation = sql.Identifier("public", table)
                        # PostgreSQL quotes its own textual values, preserving
                        # arrays, JSON, Unicode, NULLs, and escaped article text.
                        # The destination column supplies each literal's type.
                        selection = sql.SQL("SELECT {columns} FROM {table} t WHERE {key} = ANY(%s) ORDER BY {key}").format(
                            columns=sql.SQL(", ").join(
                                # Legacy cluster references must not cross databases.
                                sql.SQL("'NULL'") if table == "article" and name == "cluster_id"
                                else sql.SQL("quote_nullable({}::text)").format(sql.Identifier("t", name))
                                for name in columns
                            ),
                            table=relation,
                            key=sql.Identifier("t", primary_key),
                        )
                        insert_header = sql.SQL("INSERT INTO {} ({}) VALUES (").format(
                            relation, sql.SQL(", ").join(map(sql.Identifier, columns)),
                        ).as_string(connection)
                        if table == "news_provider":
                            insert_tail = ') ON CONFLICT ("key") DO NOTHING;\n'
                        else:
                            # Refresh by URL while keeping the existing dev ID.
                            assignments = sql.SQL(", ").join(
                                sql.SQL("{} = EXCLUDED.{}").format(sql.Identifier(name), sql.Identifier(name))
                                for name in columns if name != "url"
                            )
                            insert_tail = sql.SQL(') ON CONFLICT ("url") DO UPDATE SET {};\n').format(assignments).as_string(connection)
                        last_report = monotonic()
                        for batch in batches(keys[table]):
                            cursor.execute(selection, (batch,))
                            for row in cursor.fetchall():
                                stream.write(insert_header + ", ".join(row) + insert_tail)
                                counts[table] += 1
                            stream.flush()
                            if monotonic() - last_report >= 2 or counts[table] == total:
                                report(f"{table}: {counts[table]:,}/{total:,} rows written")
                                last_report = monotonic()
            finally:
                connection.close()
    except BaseException:
        output.unlink(missing_ok=True)
        raise
    finally:
        extensions.set_wait_callback(previous_wait_callback)
    return counts


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--days", type=int, default=5, help="Article publication window (default: 5 days)")
    parser.add_argument("--output", type=Path, help="SQL file, relative to the repo root (default: unique filename in /tmp); existing files are never overwritten")
    parser.add_argument("--query-timeout", type=int, default=60, help="Maximum seconds per database query (default: 60)")
    args = parser.parse_args(argv)
    if args.days < 1:
        parser.error("--days must be positive")
    if args.query_timeout < 1:
        parser.error("--query-timeout must be positive")
    load_dotenv(REPO_ROOT / ".env")
    source_url = os.getenv("SOURCE_DATABASE_URL") or os.getenv("DATABASE_URL")
    if not source_url:
        parser.error("Set SOURCE_DATABASE_URL or DATABASE_URL in the environment or repo-root .env")
    if args.output is None:
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        output = Path("/tmp") / f"vidik-articles-{args.days}d-{timestamp}-{uuid4().hex[:8]}.sql"
    else:
        output = args.output if args.output.is_absolute() else REPO_ROOT / args.output
    try:
        counts = export_articles(source_url, output, args.days, query_timeout=args.query_timeout)
    except FileExistsError:
        parser.exit(2, f"Output file already exists: {output}\nChoose another OUTPUT path, or omit OUTPUT to generate a unique filename.\n")
    except KeyboardInterrupt:
        parser.exit(130, "Export interrupted; incomplete SQL file removed.\n")
    except psycopg2.Error as error:
        # Server diagnostics omit the DSN; connection errors may include it.
        message = error.diag.message_primary or type(error).__name__
        parser.exit(2, f"Database error: {message}\nExport failed; incomplete SQL file removed. The last progress line identifies the failing step.\n")
    for table, count in counts.items():
        print(f"{table}: {count} rows", file=sys.stderr)
    print(f"Wrote {output.resolve()}", file=sys.stderr)


if __name__ == "__main__":
    main()
