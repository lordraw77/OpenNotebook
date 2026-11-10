"""Demo backend for the user-guide screenshots (`make docs-screenshots`).

Runs the real API in one process against a disposable PostgreSQL database, with in-memory Qdrant, filesystem blobs and
scripted models (nothing leaves the machine, no provider key needed), seeds a small project in one language, then
serves it on 127.0.0.1:DEMO_PORT (default 8000, where `ng serve` proxies /api).

    cd backend && DEMO_LANG=it .venv/bin/python ../scripts/docs/demo_server.py

Environment: DEMO_LANG (en|it), DEMO_DB_URL (admin URL of a PostgreSQL server, default the test container on
127.0.0.1:55432), DEMO_REDIS_URL (default the test Redis, database 14), DEMO_PORT.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import io
import json
import math
import os
import re
import shutil
import sys
import tempfile
import uuid
import zipfile
from pathlib import Path
from types import SimpleNamespace

LANG = os.environ.get("DEMO_LANG", "en")
PORT = int(os.environ.get("DEMO_PORT", "8000"))
ADMIN_URL = os.environ.get("DEMO_DB_URL", "postgresql+psycopg://opennotebook:test@127.0.0.1:55432/postgres")
DB_NAME = f"opennotebook_demo_{LANG}"
BLOBS = Path(tempfile.gettempdir()) / f"opennotebook-demo-blobs-{LANG}"

os.environ.update(
    {
        "APP_ENV": "development",
        "DATABASE_URL": ADMIN_URL.rsplit("/", 1)[0] + "/" + DB_NAME,
        "APP_SECRET_KEY": "demo-secret-key-" + "x" * 48,
        "APP_ENCRYPTION_KEY": base64.b64encode(b"d" * 32).decode(),
        "REDIS_URL": os.environ.get("DEMO_REDIS_URL", "redis://127.0.0.1:56379/14"),
        "STORAGE_BACKEND": "filesystem",
        "FILESYSTEM_ROOT": str(BLOBS),
        "QDRANT_LOCATION": ":memory:",
        "LOG_LEVEL": "WARNING",
        "CHAT_RATE_LIMIT_PER_MINUTE": "0",
        "CORS_ORIGINS": "",
        "CHUNK_SIZE_TOKENS": "70",
        "CHUNK_OVERLAP_TOKENS": "10",
    }
)

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "backend"))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
import litellm  # noqa: E402
import uvicorn  # noqa: E402
from corpus import CORPUS, RADIO_C  # noqa: E402
from sqlalchemy import create_engine, text  # noqa: E402
from sqlalchemy.engine import make_url  # noqa: E402

C = CORPUS[LANG]
ADMIN_EMAIL, ADMIN_PASSWORD = "anna.rossi@example.com", "correct-horse-battery"
DIM = 256


# --- scripted models ------------------------------------------------------------------------------------


def vector(text_: str) -> list[float]:
    vec = [0.0] * DIM
    for word in re.findall(r"\w+", text_.lower()):
        vec[int(hashlib.md5(word.encode()).hexdigest(), 16) % DIM] += 1.0  # noqa: S324 - hashing only
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


async def fake_aembedding(model, input, **kwargs):  # noqa: A002
    return SimpleNamespace(data=[{"embedding": vector(t)} for t in input])


def _chunk(content: str):
    return SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=content))], usage=None)


def _first_sentence(body: str, limit: int = 230) -> str:
    body = re.sub(r"\s+", " ", re.sub(r"^#+\s.*$", "", body, flags=re.M)).strip()
    sentence = re.split(r"(?<=[.!?])\s", body)[0]
    return sentence[:limit].rstrip()


def _best_sentence(body: str, words: set[str]) -> tuple[int, str]:
    body = re.sub(r"\s+", " ", re.sub(r"^#+\s.*$", "", body, flags=re.M)).strip()
    best = (0, body[:220])
    for sentence in re.split(r"(?<=[.!?])\s", body):
        score = len(words & set(re.findall(r"\w+", sentence.lower())))
        if score > best[0]:
            best = (score, sentence[:260].rstrip())
    return best


def answer_from(messages: list[dict]) -> str:
    """A grounded answer assembled from the numbered passages the real prompt contains: for each of them the
    sentence that shares the most words with the question."""
    prompt = messages[-1]["content"]
    sources = re.findall(r'<source id="S(\d+)"[^>]*>(.*?)</source>', prompt, re.S)
    if not sources:
        return "I could not find this information in the selected sources."
    question = prompt.rsplit("Question:", 1)[-1].split("\n", 1)[0]
    words = {w for w in re.findall(r"\w+", question.lower()) if len(w) > 3}
    scored = sorted(((*_best_sentence(body, words), number) for number, body in sources), reverse=True)
    intro = "Secondo le fonti selezionate:" if LANG == "it" else "According to the selected sources:"
    lines, seen = [intro, ""], set()
    for score, sentence, number in scored[:3]:
        if score and sentence not in seen:
            seen.add(sentence)
            lines.append(f"- {sentence} [S{number}]")
    if len(lines) == 2:
        lines.append(f"- {_first_sentence(sources[0][1])} [S{sources[0][0]}]")
    return "\n".join(lines)


def graph_reply(prompt: str) -> str:
    entities, relations = [], []
    passages = re.findall(r'<passage id="(\d+)">(.*?)</passage>', prompt, re.S)
    for name, kind, description in C["entities"]:
        found = [int(i) for i, body in passages if name.lower() in body.lower()]
        if found and kind != "function":
            entities.append({"name": name, "type": kind, "description": description, "passages": found[:3]})
    names = {e["name"] for e in entities}
    for source, target, kind, description in C["relations"]:
        if source in names and target in names:
            relations.append(
                {"source": source, "target": target, "type": kind, "description": description, "passage": 1}
            )
    return json.dumps({"entities": entities, "relations": relations}, ensure_ascii=False)


async def fake_acompletion(model, messages, stream=False, **kwargs):
    content = messages[-1]["content"]
    if isinstance(content, list):  # vision / OCR transcription
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="NO TEXT"))])
    if stream:
        pieces = re.findall(r"\S+\s*", answer_from(messages))

        async def gen():
            for piece in pieces:
                await asyncio.sleep(0.004)
                yield _chunk(piece)
            yield SimpleNamespace(choices=[], usage=SimpleNamespace(prompt_tokens=900, completion_tokens=90))

        return gen()
    if "Extract a knowledge graph" in content:
        reply = graph_reply(content)
    elif "overview card" in content:
        reply = json.dumps({"summary": C["summary"], "questions": C["summary_questions"]}, ensure_ascii=False)
    elif "Rewrite the last question" in content:
        reply = content.rsplit("Last question:", 1)[1].strip()
    elif "You plan research" in content:
        reply = json.dumps({"sub_questions": C["questions"][:2]}, ensure_ascii=False)
    elif "reviewing research" in content:
        reply = '{"enough": true, "follow_up_questions": []}'
    else:
        reply = answer_from(messages)
    return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=reply))])


# --- background jobs, run in-process --------------------------------------------------------------------

PENDING: list[tuple[str, str, str]] = []


async def run_pending() -> None:
    from opennotebook.db import get_sessionmaker
    from opennotebook.ingestion.pipeline import ingest_source, purge_source, refresh_ancestors
    from opennotebook.ingestion.vectors import get_vector_index
    from opennotebook.storage import get_blob_store

    store, index = get_blob_store(), get_vector_index()
    async with get_sessionmaker()() as session:
        while PENDING:
            kind, ident, reason = PENDING.pop(0)
            sid = uuid.UUID(ident)
            if kind == "ingest":
                await ingest_source(session, sid, store=store, index=index, reason=reason)
            elif kind == "purge":
                await purge_source(session, sid, store=store, index=index)
            elif kind == "graph":
                from opennotebook.graph.extract import extract_source_graph

                await extract_source_graph(session, sid, store)
            elif kind == "summary":
                from opennotebook.ingestion.summary import summarize_source

                await summarize_source(session, sid)
            else:
                await refresh_ancestors(session, sid, index=index)
            session.expire_all()


def patch_everything() -> None:
    from opennotebook.ingestion import queue
    from opennotebook.models import ModelPhase
    from opennotebook.providers import service
    from opennotebook.providers.catalog import DiscoveredModel

    from opennotebook.api import health

    async def qdrant_ok() -> None:  # the demo keeps Qdrant in memory: there is no server to probe
        return None

    health._qdrant = qdrant_ok
    litellm.aembedding = fake_aembedding
    litellm.acompletion = fake_acompletion
    queue.enqueue_ingestion = lambda sid, reason="upload": PENDING.append(("ingest", str(sid), reason))
    queue.enqueue_purge = lambda sid: PENDING.append(("purge", str(sid), ""))
    queue.enqueue_refresh_ancestors = lambda nid: PENDING.append(("refresh", str(nid), ""))
    queue.enqueue_summary = lambda sid: PENDING.append(("summary", str(sid), ""))
    queue.enqueue_graph = lambda sid: PENDING.append(("graph", str(sid), ""))

    async def catalog(kind, **_):
        chat = {ModelPhase.chat, ModelPhase.summary, ModelPhase.graph_extraction}
        if str(kind).endswith("groq"):
            return [DiscoveredModel("llama-3.3-70b-versatile", capabilities=chat, source="provider")]
        return [
            DiscoveredModel("mistral-embed", capabilities={ModelPhase.embedding}, source="provider"),
            DiscoveredModel("mistral-large-latest", capabilities=chat, source="provider"),
            DiscoveredModel("pixtral-large-latest", capabilities={ModelPhase.vision}, source="provider"),
            DiscoveredModel("mistral-ocr-latest", capabilities={ModelPhase.ocr}, source="provider"),
        ]

    service.list_models = catalog


# --- seeding ---------------------------------------------------------------------------------------------


def make_manual_pdf() -> bytes:
    from tests.factories import make_pdf

    return make_pdf(C["manual_pdf"]).replace(
        b"/BaseFont /Helvetica >>", b"/BaseFont /Helvetica /Encoding /WinAnsiEncoding >>"
    )


def make_zip() -> bytes:
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as z:
        z.writestr("src/radio.c", RADIO_C)
        z.writestr("src/radio.h", "int radio_set_power(int dbm);\nint radio_set_channel(int channel);\n")
    return buf.getvalue()


def create_database() -> None:
    url = make_url(ADMIN_URL)
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'DROP DATABASE IF EXISTS "{DB_NAME}" WITH (FORCE)'))
        conn.execute(text(f'CREATE DATABASE "{DB_NAME}"'))
    admin.dispose()
    from opennotebook.cli import cmd_migrate

    cmd_migrate(None)  # type: ignore[arg-type]


async def seed() -> None:
    from opennotebook.db import get_sessionmaker
    from opennotebook.main import app
    from opennotebook.models import User
    from opennotebook.security import hash_password

    async with get_sessionmaker()() as session:
        for email, name, admin in ((ADMIN_EMAIL, "Anna Rossi", True), ("marco.bianchi@example.com", "Marco Bianchi", False)):
            session.add(
                User(
                    id=uuid.uuid4(),
                    email=email,
                    display_name=name,
                    password_hash=hash_password(ADMIN_PASSWORD),
                    is_admin=admin,
                )
            )
        await session.commit()

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://demo", timeout=60) as c:
        login = await c.post("/api/auth/login", json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD})
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}

        async def ok(resp):
            assert resp.status_code < 300, (resp.request.url, resp.status_code, resp.text)
            return resp.json() if resp.content else None

        # providers and models
        models = {}
        for kind, name in (("mistral", "mistral"), ("groq", "groq")):
            p = await ok(await c.post("/api/providers", headers=h, json={"kind": kind, "name": name, "api_key": "k" * 24}))
            await ok(await c.post(f"/api/providers/{p['id']}/sync", headers=h))
            for m in await ok(await c.get(f"/api/providers/{p['id']}/models", headers=h)):
                await ok(await c.patch(f"/api/provider-models/{m['id']}", headers=h, json={"enabled": True}))
                models[m["model"]] = m["id"]

        async def assign(phase: str, *names: str) -> None:
            await ok(await c.put(f"/api/model-assignments/{phase}", headers=h, json={"model_ids": [models[n] for n in names]}))

        await assign("embedding", "mistral-embed")
        await assign("chat", "mistral-large-latest", "llama-3.3-70b-versatile")
        await assign("summary", "mistral-large-latest")
        await assign("graph_extraction", "mistral-large-latest")
        await assign("vision", "pixtral-large-latest")
        await assign("ocr", "mistral-ocr-latest")

        async def node(kind: str, name: str, parent: str | None = None) -> dict:
            return await ok(await c.post("/api/nodes", headers=h, json={"kind": kind, "name": name, "parent_id": parent}))

        project = await node("project", C["project"])
        workspace = await node("workspace", C["workspace"], project["id"])
        manual_nb = await node("notebook", C["notebooks"][0], workspace["id"])
        firmware_nb = await node("notebook", C["notebooks"][1], project["id"])

        async def upload(nb: dict, name: str, data: bytes, mime: str) -> None:
            await ok(await c.post(f"/api/nodes/{nb['id']}/sources", headers=h, files=[("files", (name, data, mime))]))

        await upload(manual_nb, C["manual_name"], make_manual_pdf(), "application/pdf")
        await upload(manual_nb, C["quickstart_name"], C["quickstart"].encode(), "text/markdown")
        await upload(firmware_nb, C["zip_name"], make_zip(), "application/zip")
        for _ in range(4):  # ingestion, then summaries / graph / children queued by the previous round
            await run_pending()

        await ok(await c.post(f"/api/nodes/{manual_nb['id']}/notes", headers=h, json={"title": C["notes_title"], "content": C["note"]}))

        # a few real conversations (history page, chat panel)
        for question, scope in ((C["questions"][0], manual_nb), (C["questions"][1], manual_nb), (C["questions"][2], project)):
            conv = await ok(await c.post("/api/conversations", headers=h, json={"scope_id": scope["id"], "title": question[:60]}))
            async with c.stream("POST", f"/api/conversations/{conv['id']}/messages", headers=h, json={"content": question}) as r:
                async for _ in r.aiter_lines():
                    pass
        await run_pending()

    (Path(tempfile.gettempdir()) / f"opennotebook-demo-{LANG}.json").write_text(
        json.dumps({"project": project["id"], "manual": manual_nb["id"], "firmware": firmware_nb["id"]})
    )


async def main() -> None:
    shutil.rmtree(BLOBS, ignore_errors=True)
    create_database()
    patch_everything()
    await seed()
    from opennotebook.main import app

    # uploads made while the demo runs are processed in the background
    async def pump() -> None:
        while True:
            await asyncio.sleep(1)
            if PENDING:
                await run_pending()

    asyncio.get_running_loop().create_task(pump())
    print(f"demo ready: http://127.0.0.1:{PORT}  ({ADMIN_EMAIL} / {ADMIN_PASSWORD}, language {LANG})", flush=True)
    await uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=PORT, log_level="warning")).serve()


if __name__ == "__main__":
    asyncio.run(main())
