# NorthStar Petroleum  -  AI Operations Assistant

Hackathon build : 8-team collaboration.
A complete enterprise stack for an oil & gas company plus 10 chat-AI architectures
benchmarked against it. The **winning architecture** (Chain-of-Agents with Validator
Gate) ships as a runnable web app.

```
Aiwrapper/
├── database/
│   ├── schema.sql              51 tables (auth, RBAC, approvals, ops, finance, HSE, docs)
│   ├── seed_data.py            generates 3 years of realistic data
│   ├── ingest_documents.py     extracts text docs into FTS5 + chunks
│   └── oilgas.db               (created on first seed run)
├── documents/                  9 sample policies / SOPs / contracts (.txt)
├── ai_architectures/
│   ├── RESEARCH.md             ~2k-line architecture research report
│   ├── arch_01..10_*.py        10 architecture variants, same `run(question)` API
│   ├── benchmark.py            harness comparing all 10
│   └── BENCHMARK_RESULTS.json  most recent run
├── winning_architecture/       PRODUCTION : Chain-of-Agents with Validator Gate
│   ├── engine.py               the orchestrator
│   ├── schema_catalog.py       Schema-RAG retriever
│   ├── examples.py             Vanna-style example bank
│   ├── db.py                   read-only SQL sandbox + FTS search
│   ├── server.py               FastAPI backend (SSE streaming)
│   └── frontend/               chat UI (HTML / CSS / vanilla JS)
├── scripts/
│   └── run_all.ps1             seed -> ingest -> serve in one go
└── requirements.txt
```

## Quick start

```powershell
# 1. install deps (python 3.11+ recommended; tested on 3.14)
pip install -r requirements.txt

# 2. build the database (3 years of data, ~12 MB)
python database/seed_data.py

# 3. ingest text documents (HSE policy, SOPs, contracts...)
python database/ingest_documents.py

# 4. provide an API key (either provider works; auto-detected)
#    OPTION A - .env file (recommended; gitignored):
#      OPENAI_API_KEY=sk-...           OPENAI_MODEL=gpt-4o
#      or
#      ANTHROPIC_API_KEY=sk-ant-...    CHAT_MODEL=claude-opus-4-7
#    OPTION B - shell env var:
#      $env:OPENAI_API_KEY = "sk-..."

# 5. start the chat assistant
python -m uvicorn winning_architecture.server:app --port 8000
# -> open http://localhost:8000
```

**Provider auto-detection**: if `OPENAI_API_KEY` is set the engine uses OpenAI
(default `gpt-4o`); otherwise it tries Anthropic (`claude-opus-4-7`); otherwise it
falls back to **offline mode** (deterministic example-bank SQL + rule-based summary)
so the UI is still demonstrable without a key. Force a provider with `LLM_PROVIDER=openai`
or `LLM_PROVIDER=anthropic`.

**Security**: the `.env` file is gitignored. Never paste API keys into chat or commit
them. Rotate any leaked key immediately at the provider's dashboard.

## What's in the database

51 tables, 80,000+ rows, 3 years (2023-05 -> 2026-04):

| Section | Tables |
|---|---|
| Identity / Auth / RBAC | users, roles, permissions, role_permissions, user_roles, user_sessions, login_audit, mfa_devices |
| Org | departments, employees, delegations |
| Approval chain | approval_workflows, approval_steps, approval_requests, approval_actions |
| Counterparties | customers, customer_contacts, vendors, contracts |
| Upstream | fields, reservoirs, wells, well_completions, well_tests, drilling_rigs, drilling_operations, daily_production |
| Mid/Downstream | pipelines, pipeline_segments, storage_tanks, refineries, products, crude_assays, shipments |
| Equipment / Maint | equipment, work_orders, inspections |
| HSE | incidents, environmental_readings |
| Finance | cost_centers, exchange_rates, invoices, invoice_items, payments, purchase_orders, po_items |
| Compliance | permits |
| External / Docs / Audit | external_links, document_references, document_extracts, document_chunks (+ FTS5), audit_log, notifications |

Approval chain implements **creator -> validator -> approver** (and CFO / CEO sign-off
above thresholds) with full action history. Login audit, sessions, MFA devices, and
delegations are all populated. Daily production has a realistic exponential decline
curve per well.

## The 10 architectures (TL;DR)

| # | Architecture | Strength | Complexity |
|---|---|---|---|
| 01 | Naive Text-to-SQL | simplest baseline | 1 |
| 02 | Schema-RAG NL2SQL | scales to many tables | 2 |
| 03 | Self-correcting SQL loop | recovers from errors | 2 |
| 04 | Few-shot example bank (Vanna-style) | high accuracy on covered patterns | 2 |
| 05 | ReAct / tool-using agent | adapts via exploration | 4 |
| 06 | DIN-SQL (decomposed) | strong on hard joins | 4 |
| 07 | DAIL-SQL / C3-SQL (skeleton retrieval) | best example matching | 4 |
| 08 | Router + multi-agent | mixed data + policy questions | 3 |
| 09 | GraphRAG over schema FK graph | minimal context, max signal | 4 |
| 10 | **Chain-of-Agents + Validator Gate (WINNER)** | accuracy + audit trail + safety | 5 |

See `ai_architectures/RESEARCH.md` for the full report (origins, citations, oil & gas
fit notes).

### Why pattern #10 wins for this use case

- **Auditability.** Every stage emits a trace event the UI shows live; finance and HSE
  buyers need to see *why* the model answered the way it did.
- **Safety.** Validator gate + read-only SQL sandbox prevent destructive queries even
  if the model goes off the rails.
- **Recovery.** Self-correct loop catches typos and wrong joins on the first retry.
- **Hybrid.** Same UI answers both data questions ("which wells produced most last
  quarter?") and policy questions ("what's the AFE approval policy?") **and** mixed
  ones ("how does our actual incident closure time compare to the policy target?").
- **Schema-aware.** Schema-RAG keeps prompts small even though the schema has 51 tables.
- **Memory.** History-aware router + history-injected prompts let users pivot between
  uploaded files and DB queries within one conversation. The benchmark shows this is
  worth 4 extra grade points out of 9 on multi-turn alone (7/9 vs 3/9).

### Run the benchmark

```powershell
python -m ai_architectures.benchmark
```

Writes `ai_architectures/BENCHMARK_RESULTS.json`.

#### Two benchmarks:

**A. SQL-only Q-set (`benchmark.py`)** - 8 questions × 10 archs, GPT-4o:
all variants score 8/8 because the Q-set is close to the example bank. Latency
ranges 1.25 s (Schema-RAG) to 4.89 s (Chain-of-Agents winner).

**B. Doc-aware + multi-turn Q-set (`benchmark_doc.py`)** - 20 grade points across
4 suites: `DB_ONLY`, `DOC_ONLY`, `MIXED` (DB+doc), `MULTI_TURN` (3 convos × 3 turns).
This benchmark is the one that exposes real differentiation:

| Architecture | DB | DOC | MIX | MULTI | Total | **Score** |
|---|---:|---:|---:|---:|---:|---:|
| 01 Naive Text-to-SQL | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| 02 Schema-RAG | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| 03 Self-correct | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| 04 Few-shot bank | 3/4 | 0/4 | 1/3 | 3/9 | 7/20 | 35% |
| 05 ReAct agent | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| 06 DIN-SQL | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| 07 DAIL/C3 | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| 08 Router multi-agent | 2/4 | 0/4 | 0/3 | 3/9 | 5/20 | 25% |
| 09 GraphRAG | 3/4 | 0/4 | 0/3 | 3/9 | 6/20 | 30% |
| **10 Chain-of-Agents (winner)** | **4/4** | **3/4** | **1/3** | **7/9** | **15/20** | **75%** |

The winner is the only architecture that handles all four suites. Patterns 01-07
and 09 are SQL-only — they cannot answer document questions at all. Pattern 08
has a doc path but no memory, so it fails follow-ups like "what about that file
again?". Only pattern 10 has both `(SQL + doc) × (memory)`.

Run either with:
```powershell
python -m ai_architectures.benchmark         # SQL-only suite
python -m ai_architectures.benchmark_doc     # full 4-suite, the one that matters
```

## File uploads

The chat UI accepts text-document uploads. Drop a `.txt`, `.md`, `.log`, or `.csv`
on the page (or click the *Upload* button) and the file is:

1. Saved to `documents/uploads/`
2. Extracted, summarized, keyword-tagged
3. Chunked (sliding window, 800 chars, 120 overlap) into `document_chunks`
4. Indexed into FTS5 (`document_chunks_fts`)
5. Linked into `external_links` and catalogued in `document_references`
6. **Recorded in your session** so follow-up questions know which file you uploaded

All in one synchronous request. Limits: 5 MB per file, text MIME only.

## Conversation memory

The chat keeps per-session history (last 6 turns) so you can:

1. Upload a file -> ask about it ("what does that policy say about X?")
2. Pivot to a DB question ("now show me Q4 production")
3. Pivot **back** to the file ("what about that file again - X?")
4. Reference *both* in one question ("compare that target with our actual numbers")

The router is history-aware: short follow-ups inherit the prior intent, vague
references like *"the file"* / *"that procedure"* re-trigger the document path,
and the LLM gets the recent conversation injected into every prompt for proper
co-reference resolution.

Session lives in-process on the server (1-hour idle TTL, capped at 12 messages).
The frontend persists `session_id` in `sessionStorage`, so a page refresh keeps
the same conversation. Click **Clear** in the top bar to start fresh.

### API surface

| Method | Path | Purpose |
|---|---|---|
| GET  | `/healthz` | provider/model status |
| GET  | `/api/schema` | catalog (table -> desc, columns) |
| GET  | `/api/sample-questions` | seed UI |
| POST | `/api/chat` | one-shot, body: `{question, session_id?}` |
| GET  | `/api/chat/stream?question=...&session_id=...` | SSE stream |
| POST | `/api/upload?session_id=...` | multipart `file=` |
| GET  | `/api/documents` | list indexed docs |
| GET  | `/api/session/{id}` | inspect session history |
| POST | `/api/session/{id}/clear` | wipe session memory |

## API reference (winning architecture)

| Method | Path | Purpose |
|---|---|---|
| GET | `/healthz` | model + key status |
| GET | `/api/schema` | catalog (table -> desc, columns) |
| GET | `/api/sample-questions` | seed UI |
| POST | `/api/chat` | one-shot, returns full PipelineResult JSON |
| GET | `/api/chat/stream?question=...` | SSE stream of trace events + final result |

## Notes for reviewers

- All AI architecture code is **read-only against the database**. SQL is regex-filtered
  for forbidden tokens (INSERT/UPDATE/DELETE/DROP/ALTER/PRAGMA/etc.) before execution.
  The connection itself is opened in `mode=ro`.
- The seeder is deterministic (`SEED = 20260501`) so you get the same data on every run.
- The schema is intentionally close to a real upstream operator's data model: AFE,
  daily production with reporter / validator / approver chains, NACE-compliant materials
  on sour wells, NACE inspection severity, BIRD-style approval thresholds.

## Future work

- Replace the keyword-overlap retriever with embedding search (Voyage / OpenAI).
- Add a row-level RBAC layer that filters `daily_production` and `invoices` by the
  caller's role (the data is already there in `user_roles` + `role_permissions`).
- Persist conversation history per user_id for multi-turn context.
- Push the validator agent harder: parse the candidate SQL with `sqlglot` and check the
  set of referenced tables/columns against the question's NER output.
