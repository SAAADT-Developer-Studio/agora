from pathlib import Path

import pytest

from scripts import export_articles as exporter


@pytest.fixture
def isolated_source(monkeypatch):
    monkeypatch.setattr(exporter, "load_dotenv", lambda path: None)
    monkeypatch.delenv("SOURCE_DATABASE_URL", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://test.invalid/example")


def test_repeated_default_exports_choose_distinct_files(isolated_source, monkeypatch, capsys):
    outputs = []

    def capture_export(source, output, days, *, query_timeout):
        assert source == "postgresql://test.invalid/example"
        assert days == 7
        assert query_timeout == 60
        outputs.append(output)
        return {"article": 2}

    monkeypatch.setattr(exporter, "export_articles", capture_export)
    exporter.main(["--days", "7"])
    exporter.main(["--days", "7"])

    assert outputs[0] != outputs[1]
    for output in outputs:
        assert output.parent == Path("/tmp")
        assert output.name.startswith("vidik-articles-7d-")
        assert output.suffix == ".sql"
    messages = capsys.readouterr().err
    assert all(str(output.resolve()) in messages for output in outputs)


def test_existing_explicit_file_is_preserved_without_connecting(isolated_source, monkeypatch, tmp_path, capsys):
    output = tmp_path / "existing.sql"
    original = b"INSERT INTO example VALUES ('previous export');\n"
    output.write_bytes(original)

    def unexpected_connection(*args, **kwargs):
        pytest.fail("An existing output file must be rejected before connecting")

    monkeypatch.setattr(exporter.psycopg2, "connect", unexpected_connection)
    with pytest.raises(SystemExit) as error:
        exporter.main(["--output", str(output)])

    assert error.value.code == 2
    assert output.read_bytes() == original
    message = capsys.readouterr().err
    assert "Output file already exists" in message
    assert "omit OUTPUT" in message


@pytest.mark.parametrize("failure", [KeyboardInterrupt, exporter.psycopg2.OperationalError])
def test_failed_connection_removes_partial_file_and_reports_stage(
    isolated_source, monkeypatch, tmp_path, capsys, failure,
):
    output = tmp_path / "failed.sql"
    previous_callback = exporter.extensions.get_wait_callback()

    def failed_connection(*args, **kwargs):
        assert "Connecting to source database" in capsys.readouterr().err
        raise failure("secret connection details must not appear")

    monkeypatch.setattr(exporter.psycopg2, "connect", failed_connection)
    with pytest.raises(SystemExit) as error:
        exporter.main(["--output", str(output)])

    assert error.value.code == (130 if failure is KeyboardInterrupt else 2)
    assert not output.exists()
    assert exporter.extensions.get_wait_callback() is previous_callback
    message = capsys.readouterr().err
    assert "incomplete SQL file removed" in message
    assert "secret connection details" not in message


@pytest.mark.parametrize("timeout", ["0", "-1"])
def test_invalid_timeout_rejected_before_export(isolated_source, monkeypatch, timeout):
    monkeypatch.setattr(exporter, "export_articles", lambda *a, **kw: pytest.fail("must not export"))
    with pytest.raises(SystemExit) as error:
        exporter.main(["--query-timeout", timeout])
    assert error.value.code == 2
