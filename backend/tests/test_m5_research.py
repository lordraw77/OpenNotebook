# ruff: noqa: F811 - fixtures imported from other test modules are redefined as parameters
"""Deep research mode: planning, per-step retrieval in scope, merged context, structured cited report."""

from __future__ import annotations

from types import SimpleNamespace

import litellm

from opennotebook.chat.research import merge, parse_plan
from opennotebook.ingestion.search import SearchHit
from tests.conftest import login, make_user
from tests.test_chat import chat, new_conversation  # noqa: F401 - fixtures
from tests.test_sources import embed_calls, jobs, world  # noqa: F401 - fixtures


def test_parse_plan_and_merge():
    assert parse_plan('{"sub_questions": ["A?", "a?", "B?", "Q"]}', "q", 5) == ["A?", "a?", "B?"]
    assert parse_plan("not json", "q", 5) == []
    hit = lambda cid: SearchHit(chunk=SimpleNamespace(id=cid), source=None, notebook=None, score=0)  # noqa: E731
    merged = merge([[hit(1), hit(2), hit(3)], [hit(2), hit(4)], [hit(5)]], 4)
    assert [h.chunk.id for h in merged] == [1, 2, 5, 3]


def install_fake(monkeypatch, plan_reply: str) -> list[dict]:
    calls: list[dict] = []

    async def fake(model, messages, stream=False, **kwargs):
        prompt = messages[-1]["content"]
        calls.append({"stream": stream, "prompt": prompt, "max_tokens": kwargs.get("max_tokens")})
        if not stream:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=plan_reply))])

        async def gen():
            text = "## Summary\nReset takes ten seconds [S1].\n## Conclusion\nDone [S2]."
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=None)

        return gen()

    monkeypatch.setattr(litellm, "acompletion", fake)
    return calls


async def test_research_mode_plans_retrieves_and_reports(client, admin_headers, world, chat, monkeypatch):
    calls = install_fake(
        monkeypatch, '{"sub_questions": ["How is the radio channel set?", "How is the device reset?"]}'
    )
    conv = await new_conversation(client, admin_headers, world.wifi["id"])
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        headers=admin_headers,
        json={"content": "Explain radio configuration and factory reset", "mode": "research"},
    )
    import json

    events = [
        (b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1])) for b in r.text.strip().split("\n\n")
    ]
    kinds = [k for k, _ in events]
    assert kinds.index("plan") < kinds.index("sources") < kinds.index("token")
    plan = next(d for k, d in events if k == "plan")["sub_questions"]
    assert plan == [
        "Explain radio configuration and factory reset",
        "How is the radio channel set?",
        "How is the device reset?",
    ]
    steps = [d for k, d in events if k == "status" and d["stage"] == "researching"]
    assert [s["step"] for s in steps] == [1, 2, 3]
    context = next(d for k, d in events if k == "sources")["context"]
    assert {c["source_title"] for c in context} == {"radio.md", "manual.pdf"}
    report_call = next(c for c in calls if c["stream"])
    assert "structured research report" in report_call["prompt"] and report_call["max_tokens"] == 4096
    done = next(d for k, d in events if k == "done")
    assert done["checks"]["mode"] == "research" and done["checks"]["plan"] == plan
    assert done["content"].startswith("## Summary") and [c["n"] for c in done["citations"]] == [1, 2]


async def test_research_mode_without_plan_and_with_acl(
    client, admin_headers, session, world, chat, monkeypatch
):
    install_fake(monkeypatch, "I cannot plan this.")
    bob = await make_user(session, "bob@example.com")
    bob_headers = await login(client, "bob@example.com")
    await client.put(
        f"/api/nodes/{world.docs['id']}/grants",
        headers=admin_headers,
        json={"principal_type": "user", "principal_id": str(bob.id), "role": "viewer"},
    )
    conv = await new_conversation(client, bob_headers, world.wifi["id"])
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        headers=bob_headers,
        json={"content": "radio driver channel transmit power and reset", "mode": "research"},
    )
    assert '"sub_questions": ["radio driver channel transmit power and reset"]' in r.text
    assert "radio.md" not in r.text.split("event: sources", 1)[1].split("event: ", 1)[0]
    assert "event: done" in r.text


def test_parse_follow_ups():
    from opennotebook.chat.research import parse_follow_ups

    asked = ["How is the radio channel set?"]
    assert parse_follow_ups('{"enough": true, "follow_up_questions": ["x?"]}', asked, 3) == []
    reply = (
        '{"enough": false, "follow_up_questions": ["What does WPA3 require?", '
        '"how is the radio channel set?", "What does wpa3 require?", "Q3?", "Q4?"]}'
    )
    assert parse_follow_ups(reply, asked, 3) == ["What does WPA3 require?", "Q3?", "Q4?"]
    assert parse_follow_ups("no json", asked, 3) == []


async def test_research_reads_the_results_and_searches_again(client, admin_headers, world, chat, monkeypatch):
    replies = iter(
        [
            '{"sub_questions": ["How is the radio channel set?"]}',  # plan
            '{"enough": false, "follow_up_questions": '
            '["How is the device reset?", "How is the radio channel set?"]}',
            '{"enough": true, "follow_up_questions": []}',  # second look: enough
        ]
    )
    calls = install_fake(monkeypatch, "")

    async def scripted(model, messages, stream=False, **kwargs):
        prompt = messages[-1]["content"]
        calls.append({"stream": stream, "prompt": prompt, "max_tokens": kwargs.get("max_tokens")})
        if not stream:
            return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(replies)))])

        async def gen():
            text = "## Summary\nReset takes ten seconds [S1].\n## Conclusion\nDone [S2]."
            yield SimpleNamespace(choices=[SimpleNamespace(delta=SimpleNamespace(content=text))], usage=None)

        return gen()

    monkeypatch.setattr(litellm, "acompletion", scripted)
    conv = await new_conversation(client, admin_headers, world.wifi["id"])
    r = await client.post(
        f"/api/conversations/{conv['id']}/messages",
        headers=admin_headers,
        json={"content": "Explain radio configuration and factory reset", "mode": "research"},
    )
    import json

    events = [
        (b.split("\n")[0][7:], json.loads(b.split("data: ", 1)[1])) for b in r.text.strip().split("\n\n")
    ]
    plans = [d for k, d in events if k == "plan"]
    assert len(plans) == 2 and plans[1]["round"] == 1
    # the repeated question is dropped; only the new one is added
    assert plans[1]["sub_questions"] == [
        "Explain radio configuration and factory reset",
        "How is the radio channel set?",
        "How is the device reset?",
    ]
    stages = [d["stage"] for k, d in events if k == "status"]
    assert stages.count("reflecting") == 2 and stages.count("researching") == 3
    reflect_prompts = [c["prompt"] for c in calls if not c["stream"] and "reviewing research" in c["prompt"]]
    assert len(reflect_prompts) == 2 and "radio.md" in reflect_prompts[0]
    done = next(d for k, d in events if k == "done")
    assert done["checks"]["plan"] == plans[1]["sub_questions"]
