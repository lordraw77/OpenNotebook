#!/usr/bin/env python3
# ruff: noqa: ASYNC230, ASYNC240 - a command-line tool: local file I/O is fine here
"""Load test of a running OpenNotebook (uses the real configured providers: keep it short).

    ON_URL=... ON_EMAIL=<admin> ON_PASSWORD=... uv run --project backend python scripts/loadtest.py \\
      [--users 10] [--seconds 60] [--chats 10] [--pdf-pages 60]

  1. creates a temporary project, N temporary users with viewer access and uploads eval/corpus;
  2. search load: every user searches continuously (with think time) for --seconds;
  3. chat: --chats questions with 5 in parallel, timing the retrieved passages and the first token;
  4. ingestion: one generated text PDF of --pdf-pages pages, timed until ready (pages per minute);
then removes everything it created. Per-user rate limits apply (429 answers are counted, not retried).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import secrets
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
QUERIES = [
    "factory reset", "PoE injector", "WPA3 SAE", "management VLAN", "firmware update policy",
    "6 GHz radio", "roaming assistant", "default password", "controller address", "failed confirmations",
]  # fmt: skip


def pct(values: list[float], p: float) -> float:
    if not values:
        return 0.0
    values = sorted(values)
    return round(values[min(len(values) - 1, int(round(p / 100 * (len(values) - 1))))], 3)


def text_pdf(pages: int) -> bytes:
    """Minimal text PDF (Helvetica), about 250 words per page."""
    words = (
        "access point radio channel firmware security policy roaming client band management " * 30
    ).split()
    objects: list[bytes] = [b"<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>"]
    page_ids, content_ids = [], []
    for n in range(pages):
        lines = [" ".join(words[i : i + 10]) for i in range(0, 250, 10)]
        ops = [
            f"BT /F1 11 Tf 50 {760 - 28 * i} Td (Page {n + 1}: {line}) Tj ET" for i, line in enumerate(lines)
        ]
        stream = "\n".join(ops).encode()
        objects.append(b"<< /Length %d >>\nstream\n" % len(stream) + stream + b"\nendstream")
        content_ids.append(len(objects))
    pages_obj = len(objects) + pages + 1
    for cid in content_ids:
        objects.append(
            b"<< /Type /Page /Parent %d 0 R /MediaBox [0 0 612 792] /Contents %d 0 R "
            b"/Resources << /Font << /F1 1 0 R >> >> >>" % (pages_obj, cid)
        )
        page_ids.append(len(objects))
    objects.append(
        b"<< /Type /Pages /Kids [%s] /Count %d >>" % (b" ".join(b"%d 0 R" % i for i in page_ids), pages)
    )
    objects.append(b"<< /Type /Catalog /Pages %d 0 R >>" % pages_obj)
    out = bytearray(b"%PDF-1.7\n")
    offsets = []
    for i, obj in enumerate(objects, 1):
        offsets.append(len(out))
        out += b"%d 0 obj\n" % i + obj + b"\nendobj\n"
    xref = len(out)
    out += b"xref\n0 %d\n0000000000 65535 f \n" % (len(objects) + 1)
    out += b"".join(b"%010d 00000 n \n" % o for o in offsets)
    out += b"trailer\n<< /Size %d /Root %d 0 R >>\nstartxref\n%d\n%%%%EOF\n" % (
        len(objects) + 1,
        len(objects),
        xref,
    )
    return bytes(out)


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--users", type=int, default=10)
    parser.add_argument("--seconds", type=int, default=60)
    parser.add_argument("--think", type=float, default=0.5, help="pause between searches of one user")
    parser.add_argument("--chats", type=int, default=10)
    parser.add_argument("--pdf-pages", type=int, default=60)
    parser.add_argument("--out", default="loadtest-report.json")
    parser.add_argument("--embedding", help="provider/model for the test project (default: configured chain)")
    parser.add_argument(
        "--chat", help="provider/model for the test project's chat (default: configured chain)"
    )
    args = parser.parse_args()

    base = os.environ.get("ON_URL", "http://localhost:8080")
    async with httpx.AsyncClient(base_url=base, timeout=600) as admin:
        r = await admin.post(
            "/api/auth/login", json={"email": os.environ["ON_EMAIL"], "password": os.environ["ON_PASSWORD"]}
        )
        r.raise_for_status()
        h = {"Authorization": f"Bearer {r.json()['access_token']}"}
        project = (
            await admin.post(
                "/api/nodes", headers=h, json={"kind": "project", "name": f"loadtest-{int(time.time())}"}
            )
        ).json()
        users: list[dict] = []
        report: dict = {"users": args.users, "seconds": args.seconds}
        try:
            for phase, wanted in (("embedding", args.embedding), ("chat", args.chat)):
                if not wanted:
                    continue
                models = (
                    await admin.get(
                        "/api/models/selectable", headers=h, params={"phase": phase, "include_all": True}
                    )
                ).json()
                model = next((m for m in models if f"{m['provider_name']}/{m['model']}" == wanted), None)
                if model is None:
                    raise SystemExit(f"{wanted} is not an enabled {phase} model")
                await admin.put(
                    f"/api/model-assignments/{phase}",
                    headers=h,
                    json={"project_id": project["id"], "model_ids": [model["id"]]},
                )
                report[f"{phase}_model"] = wanted
            files = [
                ("files", (p.name, p.read_bytes(), "application/octet-stream"))
                for p in sorted((ROOT / "eval" / "corpus").iterdir())
            ]
            ids = [
                u["source"]["id"]
                for u in (
                    await admin.post(f"/api/nodes/{project['id']}/sources", headers=h, files=files)
                ).json()
            ]
            while True:
                states = [(await admin.get(f"/api/sources/{i}", headers=h)).json()["status"] for i in ids]
                if all(s in ("ready", "failed") for s in states):
                    break
                await asyncio.sleep(3)
            password = secrets.token_urlsafe(18)
            for n in range(args.users):
                u = (
                    await admin.post(
                        "/api/users",
                        headers=h,
                        json={
                            "email": f"load{n}-{project['id'][:8]}@loadtest.example.com",
                            "display_name": f"load {n}",
                            "password": password,
                        },
                    )
                ).json()
                users.append(u)
                await admin.put(
                    f"/api/nodes/{project['id']}/grants",
                    headers=h,
                    json={"principal_type": "user", "principal_id": u["id"], "role": "viewer"},
                )

            # 1) search load
            latencies: list[float] = []
            codes: dict[int, int] = {}

            async def searcher(user: dict, n: int) -> None:
                async with httpx.AsyncClient(base_url=base, timeout=60) as c:
                    tok = (
                        await c.post("/api/auth/login", json={"email": user["email"], "password": password})
                    ).json()["access_token"]
                    uh = {"Authorization": f"Bearer {tok}"}
                    end = time.monotonic() + args.seconds
                    i = n
                    while time.monotonic() < end:
                        t = time.perf_counter()
                        resp = await c.post(
                            "/api/search",
                            headers=uh,
                            json={"scope_id": project["id"], "query": QUERIES[i % len(QUERIES)]},
                        )
                        codes[resp.status_code] = codes.get(resp.status_code, 0) + 1
                        if resp.status_code == 200:
                            latencies.append(time.perf_counter() - t)
                        i += 1
                        await asyncio.sleep(args.think)

            started = time.perf_counter()
            await asyncio.gather(*(searcher(u, n) for n, u in enumerate(users)))
            elapsed = time.perf_counter() - started
            report["search"] = {
                "requests": sum(codes.values()), "status_codes": codes,
                "throughput_rps": round(len(latencies) / elapsed, 2),
                "p50_s": pct(latencies, 50), "p95_s": pct(latencies, 95), "p99_s": pct(latencies, 99),
            }  # fmt: skip
            print("search:", report["search"], file=sys.stderr)

            # 2) chat: time to retrieved passages and to the first token
            retrieval, first_token, totals = [], [], []
            sem = asyncio.Semaphore(5)

            async def chat(n: int) -> None:
                async with sem, httpx.AsyncClient(base_url=base, timeout=600) as c:
                    conv = (
                        await c.post("/api/conversations", headers=h, json={"scope_id": project["id"]})
                    ).json()
                    t = time.perf_counter()
                    got_sources = got_token = False
                    async with c.stream(
                        "POST",
                        f"/api/conversations/{conv['id']}/messages",
                        headers=h,
                        json={"content": f"Explain: {QUERIES[n % len(QUERIES)]}"},
                    ) as resp:
                        async for line in resp.aiter_lines():
                            if line == "event: sources" and not got_sources:
                                got_sources = True
                                retrieval.append(time.perf_counter() - t)
                            elif line == "event: token" and not got_token:
                                got_token = True
                                first_token.append(time.perf_counter() - t)
                    totals.append(time.perf_counter() - t)

            await asyncio.gather(*(chat(n) for n in range(args.chats)))
            report["chat"] = {
                "answers": len(totals),
                "retrieval_p50_s": pct(retrieval, 50), "retrieval_p95_s": pct(retrieval, 95),
                "first_token_p50_s": pct(first_token, 50), "first_token_p95_s": pct(first_token, 95),
                "answer_p50_s": pct(totals, 50),
            }  # fmt: skip
            print("chat:", report["chat"], file=sys.stderr)

            # 3) ingestion throughput (text PDF)
            pdf = text_pdf(args.pdf_pages)
            t = time.perf_counter()
            up = (
                await admin.post(
                    f"/api/nodes/{project['id']}/sources",
                    headers=h,
                    files=[("files", ("load.pdf", pdf, "application/pdf"))],
                )
            ).json()
            sid = up[0]["source"]["id"]
            while True:
                src = (await admin.get(f"/api/sources/{sid}", headers=h)).json()
                if src["status"] in ("ready", "failed"):
                    break
                await asyncio.sleep(1)
            seconds = time.perf_counter() - t
            report["ingestion"] = {
                "pages": args.pdf_pages, "status": src["status"], "chunks": src["chunk_count"],
                "seconds": round(seconds, 1), "pages_per_minute": round(args.pdf_pages / seconds * 60, 1),
            }  # fmt: skip
            print("ingestion:", report["ingestion"], file=sys.stderr)
        finally:
            for u in users:
                await admin.patch(f"/api/users/{u['id']}", headers=h, json={"is_active": False})
            await admin.delete(f"/api/nodes/{project['id']}", headers=h)
    Path(args.out).write_text(json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
