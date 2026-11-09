# RAG Evaluation

A fixed, fictional evaluation set lives in `eval/`: a small corpus (`eval/corpus`: an access-point manual, a
security policy, a C source file and an Italian installation guide) and 18 questions
(`eval/questions.json`): 10 fact questions (one source), 4 multi-hop questions (two or three sources) and
4 out-of-domain questions (the corpus has no answer: the assistant must abstain).

```bash
ON_URL=http://<host>:8080 ON_EMAIL=<admin> ON_PASSWORD=... \
  uv run --project backend python scripts/rag_eval.py [--mode research] [--embedding p/m] [--chat p/m] [--out report.json]
```

It creates a temporary project, indexes the corpus with the configured (or given) models, asks every question
and deletes the project. Run it after changing models, prompts or retrieval settings.

| Metric | Definition |
|---|---|
| retrieval recall@5 | fact questions whose expected source is in the top 5 search results |
| multi-hop coverage@10 | share of the expected sources of multi-hop questions in the top 10 |
| answer accuracy | answers containing every expected term |
| citation accuracy | answers citing at least one expected source |
| citation precision | share of cited sources that are expected |
| abstention (out-of-domain) | out-of-domain questions answered with "I could not find this information…" |
| false abstention | in-domain questions where the assistant abstained |

## Baseline (2026-11-09, version 0.5.1)

Embeddings `ollama/bge-m3` (global default of the test instance), chat NVIDIA `nemotron-3-ultra`, rerank
none, graph expansion 4 passages.

| Metric | Value |
|---|---|
| retrieval recall@5 | 1.00 |
| multi-hop coverage@10 | 1.00 |
| answer accuracy | 1.00 |
| citation accuracy | 1.00 |
| citation precision | 0.94 |
| abstention (out-of-domain) | 1.00 |
| false abstention | 0.00 |
| median answer time | 5.8 s |

## Graph set (2026-11-09)

`--set graph` indexes `eval/graph` (24 fictional documents: for each of 8 chains a project page, a team profile
and a system page) and asks 16 questions, 12 of them multi-hop: "In which data centre is the data of Project X
hosted?" needs the project (names the lead), the team profile (the bridge: names the lead and the system) and
the system page (names the data centre). It also reports how much of the expected context comes from search
alone and with the knowledge-graph expansion.

Same models as the baseline. Result with 4 graph passages per answer:

| Metric | Value |
|---|---|
| multi-hop coverage@10 (search) | 0.69 |
| context coverage, search only / with graph | 0.76 / 0.76 |
| bridge passage in context / via graph | 0.25 / 0.00 |
| multi-hop answer accuracy | 0.17 |
| false abstention | 0.60 |
| citation precision | 0.53 |

Finding: on this set graph expansion adds **no** useful passage (the graph passages are other documents, never
the bridge) and multi-hop answers mostly abstain. The rank-weighted scoring of expansion candidates was tried
(unit-tested) and did not change the numbers. Next step is to inspect the extracted graph for these documents
(entities of the team profiles may not link the lead to the system), then iterate on extraction prompts or the
expansion algorithm and re-run the set. Until then the M4 exit criterion (graph expansion improves multi-hop
questions) is not demonstrated.

Limits of the base set: it is small and the hybrid search alone already finds every multi-hop source, so it cannot
show the benefit of graph expansion (the M4 exit criterion); a larger corpus with indirect references is needed
for that. Answer accuracy is a term match, not a judgement of the whole answer.
