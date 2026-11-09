"""Deep research mode (CHT-05): plan sub-questions, retrieve for each, read what was found and search again
for what is missing (up to RESEARCH_MAX_ROUNDS rounds), then write a cited report.

Every retrieval step goes through the same scoped, ACL-filtered retrieval as the chat (hybrid search, rerank,
graph expansion), so the report can only cite passages the user may read in the selected scope.
"""

from __future__ import annotations

import json
import re
import uuid
from dataclasses import dataclass, field

from sqlalchemy.ext.asyncio import AsyncSession

from opennotebook.chat.retrieval import retrieve
from opennotebook.config import get_settings
from opennotebook.ingestion.search import SearchHit
from opennotebook.ingestion.vectors import VectorIndex
from opennotebook.models import ModelPhase, Node, User
from opennotebook.providers.gateway import GatewayError, ModelGateway

PLAN_PROMPT = """You plan research over a document collection. Split the question below into {n} or fewer
specific search questions that together cover everything needed to answer it (aspects, entities,
comparisons, conditions). Reply with JSON only: {{"sub_questions": ["...", "..."]}}
Write them in the language of the question. Do not answer the question.

Question: {question}"""

REFLECT_PROMPT = """You are reviewing research over a document collection.

Question: {question}

Search questions already asked:
{asked}

Passages found so far (document: start of the passage):
{found}

Decide whether these passages are enough to answer the question completely. If something needed is missing or
only hinted at - an entity named in a passage but never explained, a comparison with only one side, a
condition, a number, a cause - write up to {n} new, specific search questions that would find it, using the
names and terms that appear in the passages. Do not repeat the questions already asked. Reply with JSON only:
{{"enough": true, "follow_up_questions": []}} or {{"enough": false, "follow_up_questions": ["...", "..."]}}"""

REPORT_INSTRUCTIONS = (
    "Write a structured research report in Markdown that answers the question: start with a short summary, "
    "then one '## ' section per aspect, then '## Conclusion'. End every sentence that states a fact with its "
    "source marker. Say explicitly which parts of the question the sources do not cover."
)


@dataclass
class Research:
    sub_questions: list[str]
    hits: list[SearchHit]
    via_graph: set[uuid.UUID] = field(default_factory=set)
    steps: list[list[SearchHit]] = field(default_factory=list)  # hits of every search question, in order
    embedding_model: str = ""
    rerank_model: str | None = None
    warnings: list[str] = field(default_factory=list)


def parse_plan(reply: str, question: str, limit: int) -> list[str]:
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    subs: list[str] = []
    if match:
        try:
            subs = [str(s).strip()[:300] for s in json.loads(match.group(0)).get("sub_questions") or []]
        except (ValueError, AttributeError):
            subs = []
    subs = [s for s in dict.fromkeys(subs) if s and s.casefold() != question.casefold()]
    return subs[:limit]


async def plan(
    gateway: ModelGateway, question: str, project_id: uuid.UUID, model_id: uuid.UUID | None
) -> tuple[list[str], str | None]:
    """Sub-questions (possibly empty when planning fails) and the model used."""
    limit = get_settings().research_max_sub_questions
    try:
        result = await gateway.complete(
            ModelPhase.chat,
            [{"role": "user", "content": PLAN_PROMPT.format(n=limit, question=question)}],
            project_id,
            selected_model_id=model_id,
            max_tokens=1024,
        )
    except GatewayError:
        return [], None
    return parse_plan(result.value.choices[0].message.content or "", question, limit), result.used.label


def merge(lists: list[list[SearchHit]], limit: int) -> list[SearchHit]:
    """Round-robin across steps, without duplicates: every aspect gets passages."""
    merged: list[SearchHit] = []
    seen: set[uuid.UUID] = set()
    queues = [list(hits) for hits in lists]
    while len(merged) < limit and any(queues):
        for queue in queues:
            while queue:
                hit = queue.pop(0)
                if hit.chunk.id not in seen:
                    seen.add(hit.chunk.id)
                    merged.append(hit)
                    break
            if len(merged) >= limit:
                break
    return merged


def parse_follow_ups(reply: str, asked: list[str], limit: int) -> list[str]:
    """New search questions from a reflection reply; empty when the research is judged sufficient."""
    match = re.search(r"\{.*\}", reply, re.DOTALL)
    if not match:
        return []
    try:
        data = json.loads(match.group(0))
    except ValueError:
        return []
    if not isinstance(data, dict) or data.get("enough") is True:
        return []
    known = {q.casefold() for q in asked}
    out: list[str] = []
    for item in data.get("follow_up_questions") or []:
        text = str(item).strip()[:300]
        if text and text.casefold() not in known and text.casefold() not in {o.casefold() for o in out}:
            out.append(text)
    return out[:limit]


async def reflect(
    gateway: ModelGateway,
    question: str,
    research: Research,
    project_id: uuid.UUID,
    model_id: uuid.UUID | None,
) -> list[str]:
    """Read what was found and ask for what is still missing (empty list = enough, or the model failed)."""
    limit = get_settings().research_max_sub_questions
    found = "\n".join(
        f"- {h.source.title}: {' '.join(h.chunk.text.split())[:180]}" for h in research.hits[:24]
    )
    asked = "\n".join(f"- {q}" for q in research.sub_questions)
    try:
        result = await gateway.complete(
            ModelPhase.chat,
            [
                {
                    "role": "user",
                    "content": REFLECT_PROMPT.format(
                        question=question, asked=asked, found=found or "- (nothing yet)", n=limit
                    ),
                }
            ],
            project_id,
            selected_model_id=model_id,
            max_tokens=1024,
        )
    except GatewayError:
        return []
    try:
        reply = result.value.choices[0].message.content or ""
    except (AttributeError, IndexError, TypeError):
        return []
    return parse_follow_ups(reply, research.sub_questions, limit)


async def gather(
    session: AsyncSession, index: VectorIndex, user: User, scope: Node, queries: list[str]
) -> Research:
    research = Research(sub_questions=[], hits=[])
    await extend(session, index, user, scope, research, queries)
    return research


async def extend(
    session: AsyncSession,
    index: VectorIndex,
    user: User,
    scope: Node,
    research: Research,
    queries: list[str],
) -> None:
    """Search each new question and merge its passages with those already found (round robin per question)."""
    for query in queries:
        step = await retrieve(session, index, user, scope, query)
        research.sub_questions.append(query)
        research.steps.append(step.hits)
        research.via_graph |= step.via_graph
        research.embedding_model = step.embedding_model
        research.rerank_model = research.rerank_model or step.rerank_model
        research.warnings += [w for w in step.warnings if w not in research.warnings]
    research.hits = merge(research.steps, get_settings().research_max_passages)
    research.via_graph &= {h.chunk.id for h in research.hits}
