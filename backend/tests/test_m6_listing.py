# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""Paginated source listing and per-node counts, used by the lazy workbench tree."""

from __future__ import annotations

from sqlalchemy import text

from tests.test_m3 import RADIO_C, m3, make_zip  # noqa: F401 - fixtures
from tests.test_sources import embed_calls, jobs, run_jobs, upload  # noqa: F401 - fixtures


async def listing(client, headers, **params) -> tuple[list[dict], int]:  # type: ignore[no-untyped-def]
    r = await client.get("/api/sources", headers=headers, params=params)
    assert r.status_code == 200, r.text
    return r.json(), int(r.headers["X-Total-Count"])


async def test_lazy_listing_by_node_and_archive(client, admin_headers, alice_headers, session, m3, jobs):
    inner = make_zip({"lib/util.py": b"def helper():\n    return 42\n"})
    archive = make_zip(
        {"src/radio.c": RADIO_C, "docs/README.md": b"# Firmware\n\nFlash it.\n", "vendor/inner.zip": inner}
    )
    await upload(client, admin_headers, m3.nb["id"], [("firmware.zip", archive)])
    await upload(
        client, admin_headers, m3.other["id"], [("a.md", b"# A\n\nalpha\n"), ("b.md", b"# B\n\nbeta\n")]
    )

    counts = (await client.get("/api/sources/counts", headers=admin_headers)).json()
    assert counts["processing"] == 3 and counts["nodes"] == {m3.nb["id"]: 1, m3.other["id"]: 2}
    await run_jobs(session, jobs)
    counts = (await client.get("/api/sources/counts", headers=admin_headers)).json()
    # archive members are not top-level: the notebook still shows one source (the archive)
    assert counts == {"nodes": {m3.nb["id"]: 1, m3.other["id"]: 2}, "processing": 0}
    scoped = (
        await client.get("/api/sources/counts", headers=admin_headers, params={"scope_id": m3.other["id"]})
    ).json()
    assert scoped["nodes"] == {m3.other["id"]: 2}

    top, total = await listing(client, admin_headers, node_id=m3.nb["id"], top_level=True)
    assert total == 1 and top[0]["title"] == "firmware.zip" and top[0]["child_count"] == 3
    root = top[0]["id"]

    page1, total = await listing(client, admin_headers, parent_id=root, limit=2)
    page2, _ = await listing(client, admin_headers, parent_id=root, limit=2, offset=2)
    assert total == 3 and [s["title"] for s in page1 + page2] == [
        "docs/README.md",
        "src/radio.c",
        "vendor/inner.zip",
    ]
    nested = next(s for s in page2 if s["title"] == "vendor/inner.zip")
    assert nested["child_count"] == 1

    found, total = await listing(client, admin_headers, q="RADIO")
    assert total == 1 and found[0]["title"] == "src/radio.c"
    assert (await listing(client, admin_headers, q="%"))[1] == 0  # LIKE wildcards are literal
    by_id, _ = await listing(client, admin_headers, ids=[root, nested["id"]])
    assert {s["id"] for s in by_id} == {root, nested["id"]}

    # other users see nothing they cannot read, whatever the filters
    assert await listing(client, alice_headers, node_id=m3.nb["id"]) == ([], 0)
    assert await listing(client, alice_headers, parent_id=root) == ([], 0)
    assert (await client.get("/api/sources/counts", headers=alice_headers)).json() == {
        "nodes": {},
        "processing": 0,
    }


async def test_first_jobs_of_a_new_project_do_not_race(client, admin_headers, session, embed_calls) -> None:  # type: ignore[no-untyped-def]
    """Two ingestion jobs of a brand-new project create its settings row and serving model concurrently."""
    import asyncio
    import uuid

    from opennotebook.db import get_sessionmaker
    from opennotebook.ingestion import index_state
    from tests.test_sources import node, setup_embedding

    catalog = await setup_embedding(client, admin_headers)
    project = await node(client, admin_headers, "project", "race")
    pid = uuid.UUID(project["id"])
    await session.execute(text("DELETE FROM project_settings WHERE project_id = :p"), {"p": pid})
    await session.commit()
    models = [uuid.UUID(str(m)) for m in list(catalog.values())[:2]]
    models = models if len(models) == 2 else models * 2
    barrier = asyncio.Barrier(2)

    async def job(model: uuid.UUID) -> uuid.UUID | None:
        async with get_sessionmaker()() as s:
            await barrier.wait()
            serving = await index_state.serving_model_id(s, pid, default=model)
            await s.commit()
            return serving

    first, second = await asyncio.gather(job(models[0]), job(models[1]))
    assert first == second and first in models  # one winner, seen by both
