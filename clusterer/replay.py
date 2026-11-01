"""Replay harness: run the clusterer over a frozen set of past articles.

    python -m clusterer.replay export --start 2026-10-19T00:00 --hours 24 --out NAME
    python -m clusterer.replay run NAME [--run RUN] [--max-usd 1] [--no-llm]
    python -m clusterer.replay story NAME RUN STORY_ID

``export`` reads (read-only) the articles published in the window plus the
three days before it. The earlier articles keep the story they have in the
database, with each story's summary as of the window start, so the replay
starts from the state production was in. Window articles are then replayed in
15-minute runs, each at the run production picked it up in, through
``pipeline.run_batch``: the same code as production, with an in-memory store.

LLM replies are cached on disk by model, response format and prompt, so a
rerun only pays for prompts that changed. ``--max-usd`` and ``--max-calls``
stop a run before it spends more. ``--no-llm`` skips the judge, merges and
summaries entirely: free, for tuning the cosine thresholds.

The report compares the replay with what production did for the same window
articles. Production is not ground truth, so read the lists of disagreements,
not just the scores.

Everything is written under ``clusterer/.replay/`` (git-ignored).
"""

import argparse
import gzip
import hashlib
import json
import logging
import math
import os
import urllib.error
from collections import Counter, defaultdict
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from functools import partial
from pathlib import Path

import numpy as np

from . import assign, llm
from .assign import COSINE, LLM, SEED, Assignment
from .judge import CHOICE_FORMAT, RELATION_FORMAT, choose_story, story_relation
from .pipeline import WINDOW_DAYS, MergeMemory, Models, load_index, run_batch
from .summary import RESPONSE_FORMAT as SUMMARY_FORMAT
from .summary import ArticleExcerpt, Brief, Bullet, refresh_brief
from .summary import _MAX_TOKENS as SUMMARY_MAX_TOKENS

ROOT = Path(__file__).resolve().parent / ".replay"
RUN_EVERY = timedelta(minutes=15)
# Story ids the replay creates start here, clear of production ids.
_FIRST_NEW_STORY_ID = 100_000_000
_ATTEMPTS = 3

logger = logging.getLogger(__name__)


# --- data -------------------------------------------------------------------


@dataclass
class Article:
    id: int
    title: str
    deck: str | None
    summary: str | None
    published_at: datetime
    embedding: list[float]
    # Production's story for it, merges followed, and when production assigned it.
    prod_story_id: int | None
    prod_method: str | None
    prod_assigned_at: datetime | None


@dataclass
class Dataset:
    start: datetime
    end: datetime
    context: list[Article]
    window: list[Article]
    # Production story summaries as of ``start``, for context stories.
    briefs: dict[int, Brief]
    prod_titles: dict[int, str]
    # First article of each context story, which may predate the context.
    # Empty in datasets exported before stories had a lifespan.
    story_started: dict[int, datetime] = field(default_factory=dict)


def _dt(value: str | None) -> datetime | None:
    return datetime.fromisoformat(value) if value else None


def _article_json(article: Article) -> dict:
    return {
        "id": article.id,
        "title": article.title,
        "deck": article.deck,
        "summary": article.summary,
        "published_at": article.published_at.isoformat(),
        "embedding": article.embedding,
        "prod_story_id": article.prod_story_id,
        "prod_method": article.prod_method,
        "prod_assigned_at": article.prod_assigned_at.isoformat()
        if article.prod_assigned_at
        else None,
    }


def _article(data: dict) -> Article:
    return Article(
        id=data["id"],
        title=data["title"],
        deck=data["deck"],
        summary=data["summary"],
        published_at=datetime.fromisoformat(data["published_at"]),
        embedding=data["embedding"],
        prod_story_id=data["prod_story_id"],
        prod_method=data["prod_method"],
        prod_assigned_at=_dt(data["prod_assigned_at"]),
    )


def _brief_json(brief: Brief) -> dict:
    return {
        "title": brief.title,
        "bullets": [{"text": b.text, "article_ids": list(b.article_ids)} for b in brief.bullets],
        "lead_article_id": brief.lead_article_id,
        "created_at": brief.created_at.isoformat() if brief.created_at else None,
        "lede": brief.lede,
    }


def _brief(data: dict) -> Brief:
    return Brief(
        title=data["title"],
        bullets=tuple(Bullet(b["text"], tuple(b["article_ids"])) for b in data["bullets"]),
        lead_article_id=data["lead_article_id"],
        created_at=_dt(data["created_at"]),
        lede=data.get("lede"),
    )


def dataset_path(name: str) -> Path:
    return ROOT / "datasets" / f"{name}.json.gz"


def save_dataset(dataset: Dataset, name: str) -> Path:
    path = dataset_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "start": dataset.start.isoformat(),
        "end": dataset.end.isoformat(),
        "context": [_article_json(a) for a in dataset.context],
        "window": [_article_json(a) for a in dataset.window],
        "briefs": {str(k): _brief_json(v) for k, v in dataset.briefs.items()},
        "prod_titles": {str(k): v for k, v in dataset.prod_titles.items()},
        "story_started": {str(k): v.isoformat() for k, v in dataset.story_started.items()},
    }
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        json.dump(payload, handle)
    return path


def load_dataset(name: str) -> Dataset:
    with gzip.open(dataset_path(name), "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    return Dataset(
        start=datetime.fromisoformat(payload["start"]),
        end=datetime.fromisoformat(payload["end"]),
        context=[_article(a) for a in payload["context"]],
        window=[_article(a) for a in payload["window"]],
        briefs={int(k): _brief(v) for k, v in payload["briefs"].items()},
        prod_titles={int(k): v for k, v in payload["prod_titles"].items()},
        story_started={
            int(k): datetime.fromisoformat(v)
            for k, v in payload.get("story_started", {}).items()
        },
    )


# --- export -----------------------------------------------------------------

_ARTICLES_SQL = """
select a.id, a.title, a.deck, a.summary, a.published_at, a.embedding,
       sa.story_id, sa.method, sa.assigned_at
from article a
left join story_article sa on sa.article_id = a.id
where a.published_at > :lo and a.published_at < :hi
  and a.embedding is not null
order by a.published_at, a.id
"""

_STORIES_SQL = "select id, title, merged_into_story_id from story where id = any(:ids)"

_BRIEFS_SQL = """
select distinct on (story_id) story_id, title, bullets, lead_article_id, created_at
from story_summary
where story_id = any(:ids) and created_at < :start
order by story_id, id desc
"""

_STARTED_SQL = """
select coalesce(s.merged_into_story_id, sa.story_id) story_id, min(a.published_at) started
from story_article sa
join article a on a.id = sa.article_id
join story s on s.id = sa.story_id
where coalesce(s.merged_into_story_id, sa.story_id) = any(:ids)
group by 1
"""


def export(database_url: str, start: datetime, end: datetime) -> Dataset:
    """Read the window and the three days before it. Never writes."""
    from sqlalchemy import create_engine, text

    engine = create_engine(
        database_url,
        connect_args={"options": "-c default_transaction_read_only=on"},
    )
    lo = start - timedelta(days=WINDOW_DAYS)
    with engine.connect() as conn:
        rows = conn.execute(text(_ARTICLES_SQL), {"lo": lo, "hi": end}).all()
        story_ids = sorted({row.story_id for row in rows if row.story_id is not None})
        merged_into: dict[int, int | None] = {}
        titles: dict[int, str] = {}
        pending = story_ids
        while pending:
            found = conn.execute(text(_STORIES_SQL), {"ids": pending}).all()
            for story in found:
                merged_into[story.id] = story.merged_into_story_id
                titles[story.id] = story.title
            pending = sorted(
                {s.merged_into_story_id for s in found if s.merged_into_story_id}
                - merged_into.keys()
            )

        def final(story_id: int | None) -> int | None:
            while story_id is not None and merged_into.get(story_id):
                story_id = merged_into[story_id]
            return story_id

        context: list[Article] = []
        window: list[Article] = []
        for row in rows:
            article = Article(
                id=row.id,
                title=row.title,
                deck=row.deck,
                summary=row.summary,
                published_at=row.published_at,
                embedding=list(row.embedding),
                prod_story_id=final(row.story_id),
                prod_method=row.method,
                prod_assigned_at=row.assigned_at,
            )
            if row.published_at >= start:
                window.append(article)
            elif article.prod_story_id is not None and (
                row.assigned_at is None or row.assigned_at < start
            ):
                context.append(article)
        context_stories = sorted({a.prod_story_id for a in context})
        briefs = {
            row.story_id: Brief(
                title=row.title,
                bullets=tuple(
                    Bullet(b["text"], tuple(b.get("article_ids") or ())) for b in row.bullets
                ),
                lead_article_id=row.lead_article_id,
                created_at=row.created_at,
            )
            for row in conn.execute(
                text(_BRIEFS_SQL), {"ids": context_stories, "start": start}
            ).all()
        }
        # Membership as of today, so a story's later articles do not count, but
        # one merged in later can make the start earlier than it was at ``start``.
        story_started = {
            row.story_id: row.started
            for row in conn.execute(text(_STARTED_SQL), {"ids": context_stories}).all()
        }
    final_ids = {final(s) for s in story_ids}
    return Dataset(
        start=start,
        end=end,
        context=context,
        window=window,
        briefs={k: v for k, v in briefs.items() if k in final_ids},
        prod_titles={s: titles.get(s, "") for s in final_ids if s is not None},
        story_started=story_started,
    )


# --- LLM cache and budget ----------------------------------------------------


class BudgetExceeded(BaseException):
    """Stops the replay. A BaseException so the judge's error handling can't swallow it."""


@dataclass
class Spend:
    max_usd: float
    max_calls: int
    usd: float = 0.0
    calls: int = 0
    cached: int = 0
    by_kind: Counter = field(default_factory=Counter)


class LLMCache:
    """Disk cache of replies, keyed by model, response format and prompt."""

    def __init__(self, path: Path, spend: Spend, *, offline: bool = False) -> None:
        self._path = path
        self._spend = spend
        self._offline = offline
        self._replies: dict[str, str] = {}
        if path.exists():
            with path.open(encoding="utf-8") as handle:
                for line in handle:
                    entry = json.loads(line)
                    self._replies[entry["key"]] = entry["content"]

    def completer(
        self, kind: str, response_format: dict, max_tokens: int | None = None
    ) -> llm.Complete:
        def complete(prompt: str) -> str:
            key = hashlib.sha256(
                json.dumps([llm.MODEL, response_format, max_tokens, prompt]).encode()
            ).hexdigest()
            if key in self._replies:
                self._spend.cached += 1
                return self._replies[key]
            if self._offline:
                raise llm.MissingKey()
            if self._spend.calls >= self._spend.max_calls or self._spend.usd >= self._spend.max_usd:
                raise BudgetExceeded(
                    f"stopped at {self._spend.calls} calls, ${self._spend.usd:.3f}"
                )
            # Production seeds on a timeout; a replay retries so runs stay comparable.
            for attempt in range(_ATTEMPTS):
                try:
                    reply = llm.chat(
                        prompt, response_format=response_format, max_tokens=max_tokens
                    )
                    break
                except (TimeoutError, urllib.error.URLError):
                    if attempt == _ATTEMPTS - 1:
                        raise
            self._spend.calls += 1
            self._spend.usd += reply.cost_usd
            self._spend.by_kind[kind] += 1
            self._replies[key] = reply.content
            self._path.parent.mkdir(parents=True, exist_ok=True)
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps({"key": key, "content": reply.content}) + "\n")
            return reply.content

        return complete


def cached_models(cache: LLMCache, *, summaries: bool = True) -> Models:
    """``summaries=False`` skips the summary step, most of the calls, for a faster run.

    The judge then sees only members, never a headline or bullets.
    """
    choice = cache.completer("judge", CHOICE_FORMAT)
    relation = cache.completer("merge", RELATION_FORMAT)
    brief = cache.completer("summary", SUMMARY_FORMAT, SUMMARY_MAX_TOKENS)
    return Models(
        judge=partial(choose_story, complete=choice),
        merge_relation=partial(story_relation, complete=relation),
        summarize=partial(refresh_brief, complete=brief)
        if summaries
        else lambda *_args, **_kwargs: None,
    )


def no_llm_models() -> Models:
    return Models(
        judge=lambda *_args: None,
        merge_relation=lambda *_args: None,
        summarize=lambda *_args, **_kwargs: None,
    )


# --- in-memory store ---------------------------------------------------------


@dataclass
class Membership:
    article_id: int
    story_id: int
    method: str
    similarity: float | None
    story_similarity: float | None
    relation: str | None
    run_at: datetime


class MemoryStore:
    def __init__(self, articles: dict[int, Article], now: list[datetime]) -> None:
        self.articles = articles
        self.members: dict[int, list[int]] = defaultdict(list)
        self.memberships: dict[int, Membership] = {}
        self.briefs: dict[int, list[Brief]] = defaultdict(list)
        self.titles: dict[int, str] = {}
        self.merged_into: dict[int, int] = {}
        self._next_id = _FIRST_NEW_STORY_ID
        self._now = now

    def seed_context(self, article: Article) -> None:
        story_id = article.prod_story_id
        assert story_id is not None
        self.members[story_id].append(article.id)
        self.memberships[article.id] = Membership(
            article.id, story_id, article.prod_method or SEED, None, None, None, self._now[0]
        )

    def create_story(self, article: Article) -> int:
        story_id = self._next_id
        self._next_id += 1
        self.titles[story_id] = article.title
        return story_id

    def add_membership(self, story_id: int, article: Article, assignment: Assignment) -> None:
        self.members[story_id].append(article.id)
        self.memberships[article.id] = Membership(
            article.id,
            story_id,
            assignment.method,
            assignment.similarity,
            assignment.story_similarity,
            assignment.relation,
            self._now[0],
        )

    def merge(self, drop_id: int, keep_id: int) -> None:
        for article_id in self.members.pop(drop_id, []):
            self.members[keep_id].append(article_id)
            self.memberships[article_id].story_id = keep_id
        self.merged_into[drop_id] = keep_id

    def excerpts(self, story_id: int) -> list[ArticleExcerpt]:
        return [
            ArticleExcerpt(
                article_id=a.id,
                title=a.title,
                deck=a.deck,
                summary=a.summary,
                published_at=a.published_at,
            )
            for a in sorted(
                (self.articles[i] for i in self.members[story_id]),
                key=lambda a: (a.published_at, a.id),
            )
        ]

    def started(self, story_id: int) -> datetime:
        return min(self.articles[i].published_at for i in self.members[story_id])

    def latest_brief(self, story_id: int) -> Brief | None:
        history = self.briefs.get(story_id)
        return history[-1] if history else None

    def save_brief(self, story_id: int, brief: Brief) -> None:
        self.briefs[story_id].append(brief)
        self.titles[story_id] = brief.title

    def set_title(self, story_id: int, title: str) -> None:
        self.titles[story_id] = title


@dataclass
class _Row:
    article_id: int
    story_id: int
    embedding: list[float]
    title: str
    summary: str | None
    published_at: datetime
    method: str


# --- replay -----------------------------------------------------------------


def _run_slot(at: datetime) -> datetime:
    epoch = at.timestamp()
    step = RUN_EVERY.total_seconds()
    return datetime.fromtimestamp(math.ceil(epoch / step) * step, tz=timezone.utc)


def replay(dataset: Dataset, models: Models) -> MemoryStore:
    articles = {a.id: a for a in [*dataset.context, *dataset.window]}
    clock = [dataset.start]
    store = MemoryStore(articles, clock)
    for article in dataset.context:
        store.seed_context(article)
    for story_id, brief in dataset.briefs.items():
        store.briefs[story_id].append(brief)
        store.titles[story_id] = brief.title
    for story_id, title in dataset.prod_titles.items():
        store.titles.setdefault(story_id, title)

    # Each article runs in the slot production picked it up in, so batches
    # and ingestion lag match what production saw.
    slots: dict[datetime, list[Article]] = defaultdict(list)
    for article in dataset.window:
        slots[_run_slot(article.prod_assigned_at or article.published_at)].append(article)
    memory = MergeMemory()
    pending: list[Article] = []
    for now in sorted(slots):
        clock[0] = now
        pending.extend(slots[now])
        since = now - timedelta(days=WINDOW_DAYS)
        batch = sorted(
            (a for a in pending if a.published_at > since), key=lambda a: (a.published_at, a.id)
        )
        pending = []
        if not batch:
            continue
        rows = [
            _Row(
                a.id,
                m.story_id,
                a.embedding,
                a.title,
                a.summary,
                a.published_at,
                m.method,
            )
            for m in store.memberships.values()
            if (a := articles[m.article_id]).published_at > since
        ]
        stories = {row.story_id for row in rows}
        briefs = {s: b for s in stories if (b := store.latest_brief(s)) is not None}
        started = {s: store.started(s) for s in stories}
        for s, at in dataset.story_started.items():
            if s in started:
                started[s] = min(started[s], at)
        index = load_index(rows, briefs, started)
        stats = run_batch(index, batch, store, models, now=now, memory=memory)
        logger.info(
            "%s: %d articles (%d seeded, %d cosine, %d llm), %d merged",
            now.strftime("%m-%d %H:%M"),
            len(batch),
            stats.seeded,
            stats.cosine,
            stats.llm,
            stats.merged,
        )
    return store


# --- report -----------------------------------------------------------------


def _bcubed(predicted: dict[int, int], reference: dict[int, int]) -> tuple[float, float]:
    """B-cubed precision and recall of one grouping against another."""
    by_pred: dict[int, set[int]] = defaultdict(set)
    by_ref: dict[int, set[int]] = defaultdict(set)
    for article, group in predicted.items():
        by_pred[group].add(article)
    for article, group in reference.items():
        by_ref[group].add(article)
    precision = recall = 0.0
    for article in predicted:
        mine = by_pred[predicted[article]]
        theirs = by_ref[reference[article]]
        overlap = len(mine & theirs)
        precision += overlap / len(mine)
        recall += overlap / len(theirs)
    n = len(predicted) or 1
    return precision / n, recall / n


def _unit(vectors: Sequence[Sequence[float]]) -> np.ndarray:
    matrix = np.asarray(vectors, dtype=np.float64)
    return matrix / np.linalg.norm(matrix, axis=1, keepdims=True)


def report(dataset: Dataset, store: MemoryStore, spend: Spend | None) -> str:
    window_ids = {a.id for a in dataset.window}
    articles = store.articles
    replay_story = {i: store.memberships[i].story_id for i in window_ids if i in store.memberships}
    prod_story = {a.id: a.prod_story_id for a in dataset.window if a.prod_story_id is not None}
    both = replay_story.keys() & prod_story.keys()

    def title(story_id: int) -> str:
        return store.titles.get(story_id) or dataset.prod_titles.get(story_id, "?")

    lines = [
        f"# Replay {dataset.start:%Y-%m-%d %H:%M} – {dataset.end:%Y-%m-%d %H:%M} UTC",
        "",
        f"{len(dataset.window)} window articles, {len(dataset.context)} context articles.",
    ]
    if spend is not None:
        lines.append(
            f"LLM: {spend.calls} new calls (${spend.usd:.3f}; "
            + ", ".join(f"{k} {v}" for k, v in sorted(spend.by_kind.items()))
            + f"), {spend.cached} from cache."
        )

    def summary_table(label: str, grouping: dict[int, int], methods: Counter) -> list[str]:
        sizes = Counter(grouping.values())
        hist = Counter(
            "1" if n == 1 else "2-3" if n <= 3 else "4-10" if n <= 10 else "11-30" if n <= 30
            else "30+"
            for n in sizes.values()
        )
        singletons = sum(1 for n in sizes.values() if n == 1)
        return [
            f"| {label} | {len(sizes)} | {singletons / max(len(grouping), 1):.0%} | "
            + " / ".join(str(hist[b]) for b in ("1", "2-3", "4-10", "11-30", "30+"))
            + f" | {methods[SEED]} / {methods[COSINE]} / {methods[LLM]} |"
        ]

    replay_methods = Counter(store.memberships[i].method for i in replay_story)
    prod_methods = Counter(a.prod_method for a in dataset.window if a.prod_method)
    lines += [
        "",
        "## Shape (window articles only)",
        "",
        "| | stories | singleton articles | stories by size 1 / 2-3 / 4-10 / 11-30 / 30+ "
        "| seed / cosine / llm |",
        "|---|---|---|---|---|",
        *summary_table("production", {i: prod_story[i] for i in both}, prod_methods),
        *summary_table("replay", {i: replay_story[i] for i in both}, replay_methods),
    ]
    precision, recall = _bcubed(
        {i: replay_story[i] for i in both}, {i: prod_story[i] for i in both}
    )

    def spans(grouping: dict[int, int]) -> list[float]:
        """Days from first to last article of each story, counting context articles too."""
        published: dict[int, list[datetime]] = defaultdict(list)
        for article_id, story_id in grouping.items():
            published[story_id].append(articles[article_id].published_at)
        return sorted(
            ((max(times) - min(times)).total_seconds() / 86400 for times in published.values()),
            reverse=True,
        )

    all_replay = {i: m.story_id for i, m in store.memberships.items()}
    all_prod = {a.id: a.prod_story_id for a in articles.values() if a.prod_story_id is not None}
    touched_replay = {all_replay[i] for i in replay_story}
    touched_prod = {prod_story[i] for i in prod_story}
    span_lines = []
    for label, grouping, touched in (
        ("production", all_prod, touched_prod),
        ("replay", all_replay, touched_replay),
    ):
        days = spans({i: s for i, s in grouping.items() if s in touched})
        span_lines.append(
            f"- {label}: {sum(d > 3 for d in days)} stories span over 3 days, "
            f"{sum(d > 5 for d in days)} over 5; longest "
            + ", ".join(f"{d:.1f}" for d in days[:5])
            + " days"
        )
    lines += [
        "",
        f"Agreement with production (B-cubed): precision {precision:.3f}, recall {recall:.3f}. "
        "Precision < 1: replay put together articles production kept apart. "
        "Recall < 1: replay split what production grouped.",
        "",
        f"Story spans, first to last article within the dataset (lifespan "
        f"{assign.STORY_SPAN.total_seconds() / 86400:g} days):",
        *span_lines,
    ]

    relations = Counter(
        (store.memberships[i].method, store.memberships[i].relation)
        for i in replay_story
        if store.memberships[i].relation
    )
    if relations:
        lines += ["", "Judge answers: " + ", ".join(
            f"{method}/{relation} {n}" for (method, relation), n in sorted(relations.items())
        )]

    # Stories that look like duplicates of each other, and loose members.
    groups: dict[int, list[int]] = defaultdict(list)
    for article_id in replay_story:
        groups[replay_story[article_id]].append(article_id)
    big = [s for s, members in groups.items() if len(members) >= 3]
    if len(big) >= 2:
        centroids = _unit(
            [np.mean(_unit([articles[i].embedding for i in groups[s]]), axis=0) for s in big]
        )
        sims = centroids @ centroids.T
        dupes = [
            (float(sims[i, j]), big[i], big[j])
            for i in range(len(big))
            for j in range(i + 1, len(big))
            if sims[i, j] >= 0.80
        ]
        lines += ["", f"## Replay story pairs with centroid cosine ≥ 0.80: {len(dupes)}", ""]
        for sim, a, b in sorted(dupes, reverse=True)[:15]:
            lines.append(
                f"- {sim:.2f} `{a}` ({len(groups[a])}) {title(a)[:60]} | "
                f"`{b}` ({len(groups[b])}) {title(b)[:60]}"
            )

    lines += ["", "## Largest replay stories", ""]
    for story_id, members in sorted(groups.items(), key=lambda kv: -len(kv[1]))[:15]:
        times = [articles[i].published_at for i in members]
        span = (max(times) - min(times)).total_seconds() / 3600
        lines.append(f"- `{story_id}` {len(members)} articles, {span:.0f}h: {title(story_id)[:90]}")

    # Where replay and production disagree most: read these.
    splits = []
    for prod_id in {prod_story[i] for i in both}:
        members = [i for i in both if prod_story[i] == prod_id]
        parts = Counter(replay_story[i] for i in members)
        if len(members) >= 4 and len(parts) >= 2:
            splits.append((len(members), prod_id, parts))
    lines += [
        "",
        "## Production stories the replay split",
        "",
        "Each with its replay stories as `id` (articles). Splits into one big part and "
        "a few singletons are usually opinion pieces and explainers dropping out.",
        "",
    ]
    for n, prod_id, parts in sorted(splits, key=lambda s: -s[0])[:20]:
        pieces = ", ".join(f"`{s}` ({c})" for s, c in parts.most_common(6))
        lines.append(f"- prod `{prod_id}` ({n}) {title(prod_id)[:70]} → {pieces}")

    joins = []
    for replay_id, members in groups.items():
        parts = Counter(prod_story[i] for i in members if i in prod_story)
        if len(parts) >= 2 and sum(c for c in parts.values() if c >= 2) >= 2:
            joins.append((len(members), replay_id, parts))
    lines += ["", "## Replay stories that combine several production stories", ""]
    for n, replay_id, parts in sorted(joins, key=lambda s: -s[0])[:20]:
        pieces = ", ".join(
            f"`{s}` ({c}) {title(s)[:40]}" for s, c in parts.most_common(4)
        )
        lines.append(f"- replay `{replay_id}` ({n}) {title(replay_id)[:60]} ← {pieces}")

    merges = [(d, k) for d, k in store.merged_into.items()]
    if merges:
        lines += ["", f"## Merges: {len(merges)}", ""]
        for drop, keep in merges:
            lines.append(f"- `{drop}` → `{keep}` {title(keep)[:80]}")
    return "\n".join(lines) + "\n"


def write_run(name: str, run: str, dataset: Dataset, store: MemoryStore, text: str) -> Path:
    out = ROOT / "runs" / name / run
    out.mkdir(parents=True, exist_ok=True)
    (out / "report.md").write_text(text, encoding="utf-8")
    window = {a.id for a in dataset.window}
    with (out / "assignments.jsonl").open("w", encoding="utf-8") as handle:
        for article_id in sorted(window & store.memberships.keys()):
            m = store.memberships[article_id]
            a = store.articles[article_id]
            handle.write(
                json.dumps(
                    {
                        "article_id": article_id,
                        "story_id": m.story_id,
                        "method": m.method,
                        "similarity": m.similarity,
                        "story_similarity": m.story_similarity,
                        "relation": m.relation,
                        "run_at": m.run_at.isoformat(),
                        "published_at": a.published_at.isoformat(),
                        "title": a.title,
                        "prod_story_id": a.prod_story_id,
                    },
                    ensure_ascii=False,
                )
                + "\n"
            )
    with (out / "stories.json").open("w", encoding="utf-8") as handle:
        json.dump(
            {
                str(s): {
                    "title": store.titles.get(s),
                    "brief": _brief_json(store.briefs[s][-1]) if store.briefs.get(s) else None,
                    "articles": len(m),
                }
                for s, m in store.members.items()
                if window & set(m)
            },
            handle,
            ensure_ascii=False,
            indent=1,
        )
    return out


def print_story(name: str, run: str, story_id: int) -> None:
    out = ROOT / "runs" / name / run
    stories = json.loads((out / "stories.json").read_text(encoding="utf-8"))
    info = stories.get(str(story_id))
    if info:
        print(f"# {info['title']}")
        if info["brief"]:
            for bullet in info["brief"]["bullets"]:
                print(f"  - {bullet['text']}")
    with (out / "assignments.jsonl").open(encoding="utf-8") as handle:
        rows = [json.loads(line) for line in handle]
    for row in sorted(rows, key=lambda r: r["published_at"]):
        if row["story_id"] != story_id and row["prod_story_id"] != story_id:
            continue
        mark = "" if row["story_id"] == story_id else f"  [replay → {row['story_id']}]"
        sim = f"{row['story_similarity']:.2f}" if row["story_similarity"] is not None else "    "
        print(
            f"{row['published_at'][5:16]} {row['method']:6} {sim} {row['relation'] or '':13} "
            f"prod={row['prod_story_id']} {row['title'][:80]}{mark}"
        )


# --- CLI --------------------------------------------------------------------


def main(argv: Sequence[str] | None = None) -> None:
    from dotenv import find_dotenv, load_dotenv

    load_dotenv(find_dotenv())
    logging.basicConfig(level=logging.INFO, format="%(message)s")
    for noisy in ("clusterer.pipeline", "httpx"):
        logging.getLogger(noisy).setLevel(logging.WARNING)

    parser = argparse.ArgumentParser(prog="python -m clusterer.replay")
    commands = parser.add_subparsers(dest="command", required=True)

    exp = commands.add_parser("export", help="freeze a window of articles (read-only)")
    exp.add_argument("--start", required=True, help="window start, UTC, e.g. 2026-10-19T00:00")
    exp.add_argument("--hours", type=float, default=24)
    exp.add_argument("--out", required=True, help="dataset name")
    exp.add_argument(
        "--database-url",
        default=os.getenv("REPLAY_DATABASE_URL"),
        help="defaults to $REPLAY_DATABASE_URL; the connection is read-only",
    )

    run = commands.add_parser("run", help="replay a dataset and write a report")
    run.add_argument("dataset")
    run.add_argument("--run", default=None, help="run name (default: timestamp)")
    run.add_argument("--max-usd", type=float, default=1.0)
    run.add_argument("--max-calls", type=int, default=3000)
    run.add_argument("--no-llm", action="store_true", help="cosine only; costs nothing")
    run.add_argument(
        "--cache-only", action="store_true", help="use cached replies only, never call the API"
    )
    run.add_argument(
        "--no-summaries",
        action="store_true",
        help="skip summaries (~60%% of calls); the judge sees no headlines",
    )
    run.add_argument(
        "--span-days",
        type=float,
        default=None,
        help=f"story lifespan to try (default {assign.STORY_SPAN.days} days)",
    )

    story = commands.add_parser("story", help="list one story's articles from a run")
    story.add_argument("dataset")
    story.add_argument("run")
    story.add_argument("story_id", type=int)

    args = parser.parse_args(argv)
    if args.command == "export":
        if not args.database_url:
            parser.error("--database-url or REPLAY_DATABASE_URL is required")
        start = datetime.fromisoformat(args.start).replace(tzinfo=timezone.utc)
        dataset = export(args.database_url, start, start + timedelta(hours=args.hours))
        path = save_dataset(dataset, args.out)
        print(
            f"{len(dataset.window)} window + {len(dataset.context)} context articles, "
            f"{len(dataset.briefs)} summaries -> {path}"
        )
    elif args.command == "run":
        dataset = load_dataset(args.dataset)
        if args.span_days is not None:
            assign.STORY_SPAN = timedelta(days=args.span_days)
        spend = Spend(max_usd=args.max_usd, max_calls=args.max_calls)
        if args.no_llm:
            models, spend_shown = no_llm_models(), None
        else:
            cache = LLMCache(ROOT / "llm_cache.jsonl", spend, offline=args.cache_only)
            models, spend_shown = cached_models(cache, summaries=not args.no_summaries), spend
        name = args.run or datetime.now().strftime("%Y%m%d-%H%M%S")
        try:
            store = replay(dataset, models)
        except BudgetExceeded as exc:
            raise SystemExit(f"Budget reached ({exc}); cached replies are kept, rerun to resume.")
        text = report(dataset, store, spend_shown)
        out = write_run(args.dataset, name, dataset, store, text)
        print(text)
        print(f"Written to {out}")
    else:
        print_story(args.dataset, args.run, args.story_id)


if __name__ == "__main__":
    main()
