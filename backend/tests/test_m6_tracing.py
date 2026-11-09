"""M6 tracing: database spans carry only the operation and table, nested under the current span."""

from __future__ import annotations

import pytest
from opentelemetry import trace
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import SimpleSpanProcessor
from opentelemetry.sdk.trace.export.in_memory_span_exporter import InMemorySpanExporter
from sqlalchemy import select, text
from sqlalchemy.exc import ProgrammingError

from opennotebook.models import User
from opennotebook.tracing import instrument_database, statement_summary


@pytest.fixture(scope="module")
def exporter() -> InMemorySpanExporter:
    memory = InMemorySpanExporter()
    provider = TracerProvider()
    provider.add_span_processor(SimpleSpanProcessor(memory))
    trace.set_tracer_provider(provider)
    instrument_database()
    instrument_database()  # idempotent
    return memory


def test_statement_summary_has_no_literals() -> None:
    assert statement_summary("SELECT users.id FROM users WHERE email = 'a@b.c'") == ("SELECT", "users")
    assert statement_summary('INSERT INTO "chunks" (id) VALUES (%(id)s)') == ("INSERT", "chunks")
    assert statement_summary("WITH t AS (SELECT 1 FROM nodes) SELECT * FROM t") == ("SELECT", "nodes")
    assert statement_summary("SET search_path TO secret") == ("SET", None)


async def test_database_spans_nest_and_hide_parameters(session, exporter: InMemorySpanExporter) -> None:
    exporter.clear()
    tracer = trace.get_tracer("test")
    with tracer.start_as_current_span("request") as parent:
        await session.execute(select(User).where(User.email == "secret@example.com"))
        with pytest.raises(ProgrammingError):
            await session.execute(text("SELECT * FROM missing_table_xyz"))
        await session.rollback()
    spans = {s.name: s for s in exporter.get_finished_spans()}
    ok = spans["SELECT users"]
    assert ok.parent is not None and ok.parent.span_id == parent.get_span_context().span_id
    assert ok.attributes["db.system.name"] == "postgresql"
    assert ok.attributes["db.collection.name"] == "users"
    failed = spans["SELECT missing_table_xyz"]
    assert failed.status.status_code == trace.StatusCode.ERROR
    assert failed.attributes["error.type"]
    for span in exporter.get_finished_spans():
        assert "secret@example.com" not in str(dict(span.attributes or {}))
        assert not any("statement" in key or "query.text" in key for key in (span.attributes or {}))


def test_wait_migrations(monkeypatch, capsys) -> None:  # type: ignore[no-untyped-def]
    """The init-container helper returns at once on a migrated database and times out otherwise."""
    import argparse

    from alembic.script import ScriptDirectory

    from opennotebook import cli

    assert cli.cmd_wait_migrations(argparse.Namespace(timeout=5, interval=0.1)) == 0
    assert "database schema at" in capsys.readouterr().out
    monkeypatch.setattr(ScriptDirectory, "get_current_head", lambda self: "future-revision")
    assert cli.cmd_wait_migrations(argparse.Namespace(timeout=0.3, interval=0.1)) == 1
    assert "expected future-revision" in capsys.readouterr().err
