#!/usr/bin/env python3
"""RAG quality evaluation against a running OpenNotebook (fixed corpus and questions in eval/).

    ON_URL=http://localhost:8080 ON_EMAIL=... ON_PASSWORD=... \\
      uv run --project backend python scripts/rag_eval.py [--set base|graph] [--mode chat|research] \\
      [--out report.json] [--keep]

It creates a temporary project, uploads the corpus of the set (`base`: eval/corpus + eval/questions.json;
`graph`: eval/graph/), waits for indexing and graph extraction, then asks every question. Metrics:
  - retrieval recall@5 (fact questions): an expected source is among the top 5 search results;
  - multi-hop coverage@10: share of the expected sources found in the top 10;
  - answer accuracy: every expected term appears in the answer;
  - citation accuracy: the answer cites at least one expected source;
  - citation precision: share of cited sources that are expected;
  - abstention (out-of-domain): the assistant says it could not find the information;
  - false abstention (in-domain): it abstains although the corpus answers;
  - context coverage: share of the expected sources in the chat context, from search alone (`via=search`) and
    with the knowledge-graph expansion (`via=graph`) - the gain is what graph expansion adds;
  - bridge in context / via graph (multi-hop questions with `bridge_sources`): the passage linking the hops,
    which shares no words with the question, reaches the context (through the graph).
Every call goes through the real configured providers, so results depend on the models assigned.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
SETS = {"base": ROOT / "eval", "graph": ROOT / "eval" / "graph"}


def sse_events(text: str) -> list[tuple[str, dict]]:
    out = []
    for block in text.strip().split("\n\n"):
        lines = dict(line.split(": ", 1) for line in block.splitlines() if ": " in line)
        if "event" in lines and "data" in lines:
            out.append((lines["event"], json.loads(lines["data"])))
    return out


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--set", choices=sorted(SETS), default="base", help="evaluation corpus and questions")
    parser.add_argument("--mode", choices=["chat", "research"], default="chat")
    parser.add_argument("--out", default="rag-eval-report.json")
    parser.add_argument("--keep", action="store_true", help="keep the evaluation project")
    parser.add_argument(
        "--delay", type=float, default=2.0, help="seconds between questions (provider limits)"
    )
    parser.add_argument("--timeout", type=int, default=900, help="seconds to wait for indexing")
    parser.add_argument("--embedding", help="provider/model for the evaluation project (default: configured)")
    parser.add_argument(
        "--chat", help="provider/model for the evaluation project's chat (default: configured)"
    )
    args = parser.parse_args()

    client = httpx.Client(base_url=os.environ.get("ON_URL", "http://localhost:8080"), timeout=600)
    login = client.post(
        "/api/auth/login", json={"email": os.environ["ON_EMAIL"], "password": os.environ["ON_PASSWORD"]}
    )
    login.raise_for_status()
    h = {"Authorization": f"Bearer {login.json()['access_token']}"}
    folder = SETS[args.set]
    questions = json.loads((folder / "questions.json").read_text())["questions"]

    stamp = time.strftime("%Y%m%d-%H%M%S")
    project = client.post(
        "/api/nodes", headers=h, json={"kind": "project", "name": f"rag-eval-{args.set}-{stamp}"}
    ).json()
    try:
        for phase, wanted in (("embedding", args.embedding), ("chat", args.chat)):
            if wanted:
                models = client.get(
                    "/api/models/selectable", headers=h, params={"phase": phase, "include_all": True}
                ).json()
                model = next(m for m in models if f"{m['provider_name']}/{m['model']}" == wanted)
                client.put(
                    f"/api/model-assignments/{phase}",
                    headers=h,
                    json={"project_id": project["id"], "model_ids": [model["id"]]},
                ).raise_for_status()
        files = [
            ("files", (p.name, p.read_bytes(), "application/octet-stream"))
            for p in sorted((folder / "corpus").iterdir())
        ]
        uploaded = client.post(f"/api/nodes/{project['id']}/sources", headers=h, files=files).json()
        ids = [u["source"]["id"] for u in uploaded if u.get("source")]
        start = time.time()
        while time.time() - start < args.timeout:
            sources = [client.get(f"/api/sources/{i}", headers=h).json() for i in ids]
            busy = [
                s
                for s in sources
                if s["status"] not in ("ready", "failed") or s.get("graph_status") == "pending"
            ]
            if not busy:
                break
            time.sleep(5)
        indexing_s = round(time.time() - start)
        failed = [s["title"] for s in sources if s["status"] == "failed"]
        print(
            f"corpus indexed in {indexing_s}s ({len(ids)} sources, failed: {failed or 'none'})",
            file=sys.stderr,
        )

        results = []
        for q in questions:
            expected = set(q["expected_sources"])
            limit = 10 if q["type"] == "multi_hop" else 5
            hits = (
                client.post(
                    "/api/search",
                    headers=h,
                    json={"scope_id": project["id"], "query": q["question"], "limit": limit},
                )
                .json()
                .get("hits", [])
            )
            found = {x["source_title"] for x in hits}
            conv = client.post("/api/conversations", headers=h, json={"scope_id": project["id"]}).json()
            started = time.time()
            r = client.post(
                f"/api/conversations/{conv['id']}/messages",
                headers=h,
                json={"content": q["question"], "mode": args.mode if q["type"] == "multi_hop" else "chat"},
            )
            events = sse_events(r.text)
            done = next((d for k, d in events if k == "done"), {})
            cited = {c["source_title"] for c in done.get("citations", [])}
            context = done.get("context", [])
            via_search = {c["source_title"] for c in context if c.get("via", "search") == "search"}
            via_graph = {c["source_title"] for c in context if c.get("via") == "graph"}
            answer = done.get("content", "")
            row = {
                "id": q["id"],
                "type": q["type"],
                "seconds": round(time.time() - started, 1),
                "status": done.get("status"),
                "model": done.get("model_label"),
                "abstained": bool(done.get("checks", {}).get("abstained")),
                "cited": sorted(cited),
                "graph_passages": sum(1 for c in context if c.get("via") == "graph"),
            }
            if expected:
                row["recall"] = len(expected & found) / len(expected)
                row["retrieved_any"] = bool(expected & found)
                row["answer_ok"] = all(t.lower() in answer.lower() for t in q.get("expected_terms", []))
                row["citation_ok"] = bool(expected & cited)
                row["citation_precision"] = len(cited & expected) / len(cited) if cited else 0.0
                row["context_search"] = len(expected & via_search) / len(expected)
                row["context_total"] = len(expected & (via_search | via_graph)) / len(expected)
                bridges = set(q.get("bridge_sources", []))
                if bridges:
                    row["bridge_in_context"] = bool(bridges & (via_search | via_graph))
                    row["bridge_via_graph"] = bool(bridges & (via_graph - via_search))
            results.append(row)
            print(
                f"{q['id']:>3} {q['type']:<13} {row['seconds']:>5}s abstained={row['abstained']!s:<5} "
                f"answer_ok={row.get('answer_ok', '-')!s:<5} ctx={row.get('context_search', '-')}"
                f"->{row.get('context_total', '-')} cited={sorted(cited)}",
                file=sys.stderr,
            )
            time.sleep(args.delay)
    finally:
        if not args.keep:
            client.delete(f"/api/nodes/{project['id']}", headers=h)

    def mean(values):  # type: ignore[no-untyped-def]
        values = list(values)
        return round(sum(values) / len(values), 3) if values else None

    facts = [r for r in results if r["type"] == "fact"]
    multi = [r for r in results if r["type"] == "multi_hop"]
    inside = facts + multi
    ood = [r for r in results if r["type"] == "out_of_domain"]
    bridged = [r for r in multi if "bridge_in_context" in r]
    summary = {
        "set": args.set,
        "mode": args.mode,
        "indexing_seconds": indexing_s,
        "retrieval_recall_at_5": mean(r["retrieved_any"] for r in facts),
        "multi_hop_coverage_at_10": mean(r["recall"] for r in multi),
        "answer_accuracy": mean(r["answer_ok"] for r in inside),
        "citation_accuracy": mean(r["citation_ok"] for r in inside),
        "citation_precision": mean(r["citation_precision"] for r in inside),
        "abstention_rate_out_of_domain": mean(r["abstained"] for r in ood),
        "false_abstention_rate": mean(r["abstained"] for r in inside),
        "context_coverage_search_only": mean(r["context_search"] for r in inside),
        "context_coverage_with_graph": mean(r["context_total"] for r in inside),
        "multi_hop_answer_accuracy": mean(r["answer_ok"] for r in multi),
        "bridge_in_context_rate": mean(r["bridge_in_context"] for r in bridged),
        "bridge_via_graph_rate": mean(r["bridge_via_graph"] for r in bridged),
        "graph_passages_per_answer": mean(r["graph_passages"] for r in results),
        "median_answer_seconds": sorted(r["seconds"] for r in results)[len(results) // 2],
        "models": sorted({r["model"] for r in results if r["model"]}),
    }
    Path(args.out).write_text(json.dumps({"summary": summary, "results": results}, indent=2))
    print("\n| metric | value |\n|---|---|")
    for key, value in summary.items():
        print(f"| {key} | {value} |")
    return 0


if __name__ == "__main__":
    sys.exit(main())
