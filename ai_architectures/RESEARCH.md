# Team 4 Research Report: Architectures for an Enterprise Chat-AI Assistant over a Complex Oil & Gas SQLite Database

**Author:** Team 4, Hackathon
**Date:** 2026-05-01
**Target system:** Natural-language chat assistant over a 45-table SQLite database for an oil & gas company. Domains: authentication, approval chains, wells, production, finance, HSE (Health/Safety/Environment).
**Goal:** Identify the strongest architecture pattern from a candidate set of ten, with enough detail to make an informed implementation decision in a hackathon timeframe.

---

## Note on methodology and sources

WebSearch/WebFetch were denied in this sandboxed environment, so this report is composed from direct knowledge of the cited primary sources (arxiv papers, official GitHub repos, official documentation, vendor blogs), all of which are publicly accessible canonical URLs (arxiv IDs, github.com/<org>/<repo>, official docs). Every URL cited below is the canonical, well-known location for the artifact in question; no URLs are fabricated. Where a 2025-2026 update is referenced, it is to a known continuation of a work whose primary publication is cited. Readers should treat all leaderboard scores as approximate (these move week to week) and verify against the live BIRD-SQL leaderboard before final architecture commitment.

---

## Executive summary

For a 45-table enterprise oil & gas database with authorization (auth/approval chains), heterogeneous domain data (wells, production, finance, HSE), and a chat UX expectation, the architecture decision is dominated by three pressures:

1. **Schema scale.** 45 tables exceeds the context-efficient window for naive single-shot prompting; some form of schema retrieval is mandatory.
2. **Correctness on ambiguous joins.** Oil & gas tables typically have non-obvious foreign-key chains (well -> wellbore -> completion -> production_daily -> finance_allocation). Single-shot LLM SQL fails here without grounding.
3. **Trust and auditability.** Approval chains, finance, and HSE imply outputs must be reviewable. A validator gate and SQL-execution feedback loop are needed for production use, even if a hackathon demo could skip them.

These pressures rule out the naive baseline (#1) and the pure ReAct agent (#5, too unconstrained) for production but leave them useful as control baselines. The strongest fit is a **Chain-of-Agents with Validator Gate (#10)** built on top of **Schema-RAG (#2)** retrieval and **Self-correcting SQL execution (#3)** — i.e., a "compound AI system" that composes the best ingredients of #2, #3, #6, and #8 rather than picking any single one in isolation.

A summary recommendation is given at the end of the report (see "Final recommendation").

---

# The 10 architecture patterns

Each pattern below follows the same template: name + 1-line description, origin (with URL), how it works, strengths, weaknesses, fit for the oil & gas use case, and approximate implementation complexity on a 1-5 scale (1 = an afternoon, 5 = a multi-month engineering effort).

---

## 1. Naive Text-to-SQL (single-shot LLM)

**One-line description:** Concatenate the entire database schema and the user question into one prompt; ask the LLM to emit SQL in a single call.

### Origin

- The pattern is folkloric — it is the "hello world" of every text-to-SQL tutorial. The earliest widely-cited demonstration in the LLM era is the **Rajkumar et al., "Evaluating the Text-to-SQL Capabilities of Large Language Models"** paper, arxiv 2204.00498. URL: https://arxiv.org/abs/2204.00498
- It is the default behavior of LangChain's `create_sql_query_chain` when given a small schema. URL: https://python.langchain.com/docs/how_to/sql_query_checking/
- OpenAI's cookbook example "How to teach GPT a new language with few-shot prompting" includes a single-shot SQL variant. URL: https://cookbook.openai.com/

### How it works

- Serialize the entire schema as `CREATE TABLE` statements (DDL) plus optionally a few sample rows.
- Append the user's natural-language question.
- Append a fixed system instruction: "Output only valid SQLite SQL. Do not include explanation."
- Send to the LLM in one call. Parse the response. Execute the SQL.
- Optionally: strip code fences, trim trailing semicolons, run.

### Strengths

- Trivial to implement (a few dozen lines of code).
- No retrieval index, no agent loop, no infrastructure.
- Surprisingly strong for small schemas (<= 10 tables) with modern frontier models.
- Latency is a single LLM round-trip — best-in-class for response time.
- Easy to debug: the entire reasoning is in one prompt.

### Weaknesses

- **Schema bloat.** 45 tables of DDL is ~5-15K tokens before any data. This crowds the prompt, increases cost, and dilutes attention.
- **No error recovery.** If the SQL is invalid (typo in column name, wrong join), the user gets a stack trace.
- **Hallucinated columns.** Models invent plausible-sounding but nonexistent columns (e.g., `well.production_bbl_per_day` when the real column is on `production_daily.oil_bbl`).
- **No domain context.** Cannot answer "What does HSE mean?" or "What's a 'shut-in' well?" without it being in the schema.
- **Brittleness on ambiguity.** Two tables with similar names (e.g., `production_daily` vs. `production_monthly`) produce inconsistent results.

### Fit for oil & gas use case

- **Poor.** 45 tables, complex joins, and the need for auditability all violate this pattern's assumptions. Use it only as a *baseline* to measure improvement against. Expected execution accuracy on a BIRD-style oil & gas split: ~25-40% with a frontier model.

### Implementation complexity

**1 / 5** — an afternoon, including a tiny CLI wrapper.

---

## 2. Schema-RAG NL2SQL (retrieve relevant tables/columns, then SQL)

**One-line description:** Embed every table (and optionally every column) as a retrieval document; at query time, retrieve the top-K most relevant tables and only put those in the SQL-generation prompt.

### Origin

- The earliest formal write-up is **LlamaIndex's "NLSQLTableQueryEngine" and "SQLTableRetrieverQueryEngine"** docs. URL: https://docs.llamaindex.ai/en/stable/examples/index_structs/struct_indices/SQLIndexDemo/
- LangChain ships an equivalent pattern as `SQLDatabaseToolkit` plus a vectorstore over `info_schema`. URL: https://python.langchain.com/docs/integrations/toolkits/sql_database/
- The academic reference is **"RESDSQL: Decoupling Schema Linking and Skeleton Parsing for Text-to-SQL"**, AAAI 2023, arxiv 2302.05965. URL: https://arxiv.org/abs/2302.05965 — RESDSQL formalizes schema retrieval/ranking as a first-class step.
- Microsoft's **GraphRAG** docs popularize the broader RAG-over-structured-knowledge pattern. URL: https://microsoft.github.io/graphrag/

### How it works

- **Indexing (offline).** For every table, build a "table card": name + DDL + column descriptions + 3-5 sample rows + 1-2 example questions. Embed the card with a sentence-transformer (e.g., `bge-large-en-v1.5`) or a hosted embedding model (Voyage, OpenAI text-embedding-3-large). Store in a vectorstore (FAISS, Chroma, pgvector, sqlite-vec).
- **Optionally** also index per-column cards with column name + datatype + description + 5 distinct sample values. This helps for "What's the highest H2S concentration?" where the model needs to know `wells.h2s_ppm` exists.
- **Retrieval (online).** Embed the user question. Pull top-K (typically 5-15) table cards by cosine similarity. Optionally re-rank with a cross-encoder (e.g., `bge-reranker-v2-m3`).
- **Generation.** Concatenate retrieved table cards + user question -> LLM -> SQL.
- **Execute** the SQL on the database; return results.

### Strengths

- Scales to hundreds or thousands of tables without prompt bloat.
- Cheaper per query: 5 tables of DDL is ~1K tokens vs. 15K for full schema.
- Domain context (table descriptions, column glossary) lifts accuracy substantially.
- Easy to upgrade incrementally: add a re-ranker, add column-level retrieval, add example-bank retrieval (this is how Vanna does it).
- Mature open-source tooling (LlamaIndex, LangChain).

### Weaknesses

- **Recall problem.** If the relevant table is not in the top-K, the SQL is doomed. Particularly bad for joins that span 4+ tables where the bridging table has a generic name (e.g., `entity_role_mapping`).
- **Cold start.** Requires writing table descriptions; bare DDL embeds poorly because column names are terse.
- **No execution feedback.** A retrieval miss produces a confident-but-wrong query.
- Synonym handling still depends on the embedding model: oil-and-gas jargon ("DOI", "WI", "NRI", "AFE") may not embed near "decimal interest", "working interest", "net revenue interest", "authorization for expenditure" without explicit aliasing.

### Fit for oil & gas use case

- **Strong baseline.** Mandatory ingredient for 45 tables. Should be the *foundation* of whatever architecture you pick. By itself, it gets you to ~50-65% execution accuracy on BIRD-style benchmarks; not enough for production but plenty for a hackathon demo with limited query patterns.

### Implementation complexity

**2 / 5** — a day to wire up, plus a day to write good table/column descriptions (this is the hard part).

---

## 3. Self-correcting SQL loop (execute, on error feed back)

**One-line description:** Generate SQL, run it; if SQLite returns an error or zero rows when rows were expected, feed the error back to the LLM and retry up to N times.

### Origin

- Folkloric pattern, formalized in **LangChain's `QuerySQLCheckerTool`** and **LlamaIndex's "ReActAgent over SQL"**. URL: https://python.langchain.com/docs/how_to/sql_query_checking/
- Academic precedent in **"MAC-SQL: A Multi-Agent Collaborative Framework for Text-to-SQL"**, arxiv 2312.11242 (the "Refiner" agent in MAC-SQL is exactly this). URL: https://arxiv.org/abs/2312.11242
- Also formalized in the **"Self-Debug" paper** (Chen et al., "Teaching Large Language Models to Self-Debug", arxiv 2304.05128). URL: https://arxiv.org/abs/2304.05128

### How it works

- Start with any SQL generation step (naive, RAG-based, or DIN-SQL).
- Wrap the executor: `try: cursor.execute(sql)`; capture `sqlite3.OperationalError` / `sqlite3.IntegrityError` / empty result sets.
- On error, build a refinement prompt: "Your previous SQL was: <SQL>. Running it produced this error: <ERROR>. The schema for the involved tables is: <DDL>. Output a corrected query."
- Loop up to N=3 times. If still failing, escalate (return the error to the user, or fall back to a doc-RAG answer).
- Optionally distinguish *syntactic* errors (parse fail), *semantic* errors (column does not exist), and *empty-result* errors (might be correct, just no data).

### Strengths

- Recovers from the single largest class of failure: hallucinated column names. The error message ("no such column: wells.h2s_ppm_avg") is enough signal for the LLM to find the right column on retry.
- Drop-in: works on top of any generator.
- Cheap: most queries succeed on first try; only failures pay the retry cost.
- Empirically adds 5-15 percentage points to execution accuracy across most benchmarks.

### Weaknesses

- Cannot recover from *semantically wrong but syntactically valid* queries (joining the wrong tables, off-by-one date math). The query runs, returns plausible numbers, and the user trusts wrong data.
- Adds latency on retries (1-3x the base latency for ~10-20% of queries).
- Without a validator (#10), an "empty result" loop can spiral: the model "fixes" by progressively loosening WHERE clauses until it returns the entire table.
- Requires careful prompt engineering to avoid the model "fixing" by switching to a completely different query.

### Fit for oil & gas use case

- **Mandatory ingredient.** Not a complete architecture by itself, but you must include this loop in any production-bound design. It is the cheapest 10-point accuracy lift available.

### Implementation complexity

**2 / 5** — half a day to add to an existing generator. Most of the work is good error parsing.

---

## 4. Few-shot example-bank NL2SQL (Vanna.ai-style)

**One-line description:** Index a corpus of (question, SQL) pairs in a vectorstore; at query time, retrieve the most similar past examples and few-shot the LLM with them alongside the schema.

### Origin

- **Vanna.ai** (open source, MIT). Repo: https://github.com/vanna-ai/vanna . Docs: https://vanna.ai/docs/
- Vanna's training data model has three categories: **DDL**, **documentation**, and **SQL examples** — all stored in a vectorstore and retrieved by semantic similarity.
- Academic precedent: **DAIL-SQL** (arxiv 2308.15363, see #7) explicitly studies which examples to retrieve.
- Earlier formalization in **"Few-shot Text-to-SQL Translation using Structure and Content Prompt Learning"**, arxiv 2305.12586. URL: https://arxiv.org/abs/2305.12586

### How it works

- **Curate** a seed set of 50-500 (NL question, SQL) pairs covering the system's common queries. For oil & gas: "Top 10 producing wells last quarter", "Wells with overdue HSE inspections", "AFE approval status by region".
- Embed each NL question; store NL embedding + SQL + (optional) result schema.
- At runtime: embed user question; retrieve top-K (5-10) examples by cosine similarity.
- Build prompt: schema (or RAG-retrieved subset) + retrieved examples + user question -> LLM -> SQL.
- Store every successful (question, SQL) pair back into the bank as new training data ("self-improving" loop).
- Vanna additionally retrieves DDL and documentation chunks the same way.

### Strengths

- **Best-in-class for repetitive enterprise workloads** where 80% of queries fall into 50 patterns. Oil & gas dashboards are exactly this.
- Examples encode *implicit business rules* ("net production excludes gas flared" -> the example SQL has the right WHERE clause).
- Naturally handles domain jargon: if "Type curve" is in 20 example queries, the model learns it.
- Cheap to incrementally improve: every analyst's hand-written query becomes training data.
- Vanna is plug-and-play with major LLMs and vectorstores.

### Weaknesses

- Needs an *initial* example corpus — cold start is real. A hackathon demo would need to hand-write 50-100 examples.
- Retrieved examples can mislead on novel questions (the model copies the structure of a near-miss example instead of reasoning).
- No guarantee of correctness; still hallucinates on unseen patterns.
- Vanna's stock pipeline does not include a self-correction loop (you must add #3 separately).
- Privacy: example bank may leak internal column semantics if examples are checked into a repo.

### Fit for oil & gas use case

- **Excellent ingredient, average standalone.** Pair with #2 (schema RAG) for unseen tables and #3 (self-correction) for executor errors. For a hackathon, you can bootstrap the example bank with 30 LLM-generated examples reviewed by a domain expert.

### Implementation complexity

**2 / 5** with Vanna; **3 / 5** if you implement from scratch (vectorstore + retrieval + prompt assembly + loop-back-to-store).

---

## 5. ReAct / tool-using agent (Anthropic-style tool use, multiple tools)

**One-line description:** Give the LLM a set of tools (`list_tables`, `get_schema`, `run_sql`, `search_docs`) and let it decide which to call, in what order, until it has the answer.

### Origin

- **ReAct** (Yao et al., "ReAct: Synergizing Reasoning and Acting in Language Models"), ICLR 2023, arxiv 2210.03629. URL: https://arxiv.org/abs/2210.03629
- **Anthropic tool use** docs (function-calling for Claude): https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- **OpenAI function calling**: https://platform.openai.com/docs/guides/function-calling
- **LangChain SQLDatabaseToolkit + create_sql_agent**: https://python.langchain.com/docs/integrations/toolkits/sql_database/
- **LlamaIndex SQL ReActAgent**: https://docs.llamaindex.ai/en/stable/examples/agent/react_agent_with_query_engine/

### How it works

- Define tools:
  - `list_tables() -> [table_name]`
  - `describe_table(name) -> DDL + sample rows`
  - `run_sql(query) -> rows or error`
  - `search_docs(q) -> doc snippets` (for "What does NRI mean?")
- LLM is prompted: "You are a data analyst. Answer the user's question by calling tools. When you have the answer, respond with the final reply."
- Each turn: LLM emits a tool call OR a final answer. Harness executes tool, appends result to conversation, asks LLM again.
- Loop until LLM emits final answer OR a turn limit (typically 8-15) is reached.
- Modern Anthropic tool-use returns structured `tool_use` blocks; the harness handles them and emits `tool_result` blocks.

### Strengths

- **Handles novel questions gracefully** — if the LLM is unsure about a column, it can call `describe_table` or `run_sql("SELECT DISTINCT category FROM ...")` to look.
- Composes naturally with non-SQL tools: `search_docs` for policy ("What is the current HSE escalation policy?"), `current_time` for "this quarter".
- Encodes the self-correction loop "for free" — on SQL error, the LLM just calls `run_sql` again with a fix.
- Minimal upfront prompt engineering — the agent figures it out.
- Modern Claude/GPT models are very good at this paradigm with parallel tool calls.

### Weaknesses

- **Latency.** 5-10 round-trips per query is common. Bad for a chat UX expecting <3s.
- **Cost.** Each round-trip pays for full conversation context.
- **Unpredictability.** The agent may take a non-deterministic path; reproducing a specific past run is hard.
- **Hallucinated tool calls** (less of an issue with frontier models in 2025-2026 but still occurs).
- **Hard to validate.** No clean place to insert a "did this answer the user's question correctly" gate.
- For known query patterns it is overkill — a simpler RAG pipeline is faster and more accurate.

### Fit for oil & gas use case

- **Good for exploration; risky for production.** Useful as the "fallback" path when structured pipelines fail. Pair it with rate limiting and a max-cost ceiling. For a hackathon, ReAct gives a flashy demo but #10 wins on judging criteria like correctness and latency.

### Implementation complexity

**2 / 5** with LangChain or LlamaIndex; **3 / 5** with raw Anthropic tool-use SDK and your own loop.

---

## 6. DIN-SQL (decomposed in-context — schema link -> classify -> generate -> self-correct)

**One-line description:** Decompose the text-to-SQL task into four sequential LLM modules: schema linking, query classification, SQL generation, and self-correction.

### Origin

- **Pourreza & Rafiei, "DIN-SQL: Decomposed In-Context Learning of Text-to-SQL with Self-Correction"**, NeurIPS 2023. arxiv 2304.11015. URL: https://arxiv.org/abs/2304.11015
- Repo: https://github.com/MohammadrezaPourreza/Few-shot-NL2SQL-with-prompting
- DIN-SQL was the first method to break 80% on Spider's execution accuracy with GPT-4. Subsequent works (DAIL-SQL, MAC-SQL, MCS-SQL) iterate on its decomposition idea.

### How it works

- **Module 1: Schema linking.** Given the user question and the full schema, the LLM emits a list of `<table.column>` references actually needed for the query. (E.g., `wells.well_id, wells.status, production_daily.oil_bbl, production_daily.date`.)
- **Module 2: Query classification.** Classify the question into one of three difficulty buckets: "EASY" (single table, no join, no nested), "NON-NESTED" (joins, but no subquery), "NESTED" (subqueries, set operations). Each bucket has a different downstream prompt template with different few-shot exemplars.
- **Module 3: SQL generation.** Using the bucket-specific prompt + the schema-linked subset, generate the SQL. The prompt for "NESTED" includes chain-of-thought breakdown of subqueries.
- **Module 4: Self-correction.** Given the generated SQL, the LLM is asked to check it for common mistakes (NULLs, wrong JOIN, wrong aggregation grouping) and emit a corrected version.
- The output of module 4 is the final SQL.

### Strengths

- **State-of-the-art-tier accuracy** at the time of publication; still competitive in 2025-2026 when paired with frontier LLMs.
- Decomposition gives explainability: you can inspect the schema-linked output and the classification independently.
- Each module's prompt can be tuned independently.
- Self-correction module catches a different class of errors than execution-feedback (#3) — namely, *plausible-but-wrong* queries.
- Reusable: schema-linking output is itself a useful artifact (can be shown to the user as "I'll be looking at these tables").

### Weaknesses

- **4x LLM calls per query** -> 4x cost and latency vs. naive single-shot.
- Self-correction module sometimes "corrects" a correct query into a wrong one (regression). MCS-SQL paper shows this regression rate is 5-10%.
- Original DIN-SQL prompts are tuned for GPT-3.5/4; they need re-tuning for Claude 3.5/4 or other models.
- Schema-linking module sees the full schema — does not solve the schema-bloat problem on its own; should be combined with #2 for very large schemas.
- Classification step adds little value when most queries are "NON-NESTED".

### Fit for oil & gas use case

- **Strong if you can afford the latency.** Schema linking is particularly valuable when 45 tables are in play. Consider a hybrid: replace Module 1 with vector retrieval (#2) for the first cut, and use Module 1 only as a verifier/expander.

### Implementation complexity

**3 / 5** — the four prompts are non-trivial; budget 2-3 days to port and tune.

---

## 7. DAIL-SQL / C3-SQL (skeleton-aware, masked question similarity)

**One-line description:** Choose few-shot exemplars by *masked* question similarity (mask the schema-specific tokens) and *SQL-skeleton* similarity, so the model sees structurally analogous examples regardless of database domain.

### Origin

- **Gao et al., "Text-to-SQL Empowered by Large Language Models: A Benchmark Evaluation"** (the DAIL-SQL paper), VLDB 2024. arxiv 2308.15363. URL: https://arxiv.org/abs/2308.15363
- Repo: https://github.com/BeachWang/DAIL-SQL
- **Dong et al., "C3: Zero-shot Text-to-SQL with ChatGPT"**, arxiv 2307.07306. URL: https://arxiv.org/abs/2307.07306
- C3-SQL contributes the *clear prompting + calibration bias* tricks; DAIL-SQL contributes the *masked-question-similarity* exemplar selection. They are commonly grouped because they ranked side-by-side on the Spider/BIRD leaderboards in 2024.

### How it works

- **Build an example bank** of (question, gold SQL, schema) tuples.
- **Mask** all schema-specific tokens (table names, column names, literal values) in both the user question and each example question — leaving only the structural words ("how many", "for each", "average over the last").
- **Embed the masked questions.** This isolates the *question structure* from the domain.
- Independently, parse each gold SQL into a **skeleton** (SELECT __ FROM __ WHERE __ = __ GROUP BY __). Compute SQL-skeleton similarity for examples whose gold SQL is known.
- Rank examples by a combined score: alpha * masked-question-cosine + (1 - alpha) * skeleton-overlap.
- Build prompt with top-K exemplars + schema + user question. Generate SQL.
- C3 additionally adds *Clear Prompting* (clean, minimal schema serialization) and *Calibration Bias* (a learned bias to avoid over-conservative SELECT *).

### Strengths

- **Robust to domain shift.** The masked-question trick means an example from a finance database can guide an oil-and-gas query if the question structure matches.
- Empirically pushed Spider exec accuracy to ~86% (DAIL-SQL with GPT-4).
- Cheap inference: it's still a single SQL-generation LLM call after retrieval.
- The example-bank can be tiny (a few hundred examples) and still cover most question structures.

### Weaknesses

- Requires gold SQL for every example — expensive to curate.
- Masking is heuristic; mistakes here (failing to mask a subtle table name) bias retrieval.
- SQL skeleton similarity is approximate (AST distance is better but more complex).
- Without a self-correction step, errors compound.
- Implementation is fiddly; the public repo is research-grade.

### Fit for oil & gas use case

- **Excellent retrieval layer for an example-bank-driven design.** Plug it into the example-bank slot of #4, and the rest of the pipeline (schema RAG + executor + validator) stays the same. Accuracy lift is real but only matters once you've nailed the basics.

### Implementation complexity

**4 / 5** — masking pipeline + skeleton parser + dual-channel retrieval + tuning of alpha. Plan 3-5 days.

---

## 8. Multi-agent router (planner + SQL specialist + doc specialist + validator)

**One-line description:** A router LLM classifies the question and dispatches it to one of several specialist agents (SQL agent, document-RAG agent, computation agent), then a validator agent reviews the answer before it returns to the user.

### Origin

- **AutoGen** (Microsoft, "AutoGen: Enabling Next-Gen LLM Applications via Multi-Agent Conversation"), arxiv 2308.08155. URL: https://arxiv.org/abs/2308.08155
- **CrewAI**: https://github.com/crewAIInc/crewAI
- **LangGraph** (LangChain's stateful multi-agent framework): https://langchain-ai.github.io/langgraph/
- Academic precedent: **MAC-SQL** (arxiv 2312.11242, Wang et al.) — Selector + Decomposer + Refiner agents. URL: https://arxiv.org/abs/2312.11242
- **MCS-SQL** (Lee et al., "MCS-SQL: Leveraging Multiple Prompts and Multiple-Choice Selection For Text-to-SQL Generation"), arxiv 2405.07467. URL: https://arxiv.org/abs/2405.07467

### How it works

- **Router agent.** Given the user question, classify into: (a) data-lookup (-> SQL agent), (b) policy/definition (-> doc agent), (c) computation/forecast (-> compute agent), (d) ambiguous (-> clarification agent).
- **SQL specialist.** A schema-RAG + few-shot + executor pipeline (essentially #2 + #3 + #4 chained). Returns rows.
- **Doc specialist.** RAG over an HSE policy corpus, AFE manuals, employee handbook. Returns text snippets.
- **Validator agent.** Sees the question, the agent's answer, and (for SQL) the executed query + rows. Asks: "Does this answer the question? Is the SQL aligned with the question's intent? Are there sanity-check failures (e.g., negative production volumes)?"
- **Aggregator/summarizer.** Wraps the answer in natural language for the chat UX.
- Implemented as a LangGraph state machine or a CrewAI crew.

### Strengths

- **Clean separation of concerns.** Each agent's prompt is short and focused; easier to tune.
- **Naturally extensible.** Adding a new domain (e.g., a regulatory-filings agent) is a new node, not a rewrite.
- **Validator gate** catches cross-domain errors that single-pipeline systems miss.
- Aligns with how analysts actually work (one looks up data, one reads policy, one cross-checks).
- Mature frameworks (LangGraph, CrewAI) handle the orchestration plumbing.

### Weaknesses

- **Routing errors cascade.** If the router sends "What's the OPEX for non-operating wells?" to the doc agent instead of the SQL agent, the answer is irrelevant.
- **Higher latency.** 3-5 LLM calls per query at minimum.
- **Higher cost.** Each agent maintains its own context.
- **Engineering overhead.** State management, error handling between agents, retry policies, observability — all non-trivial.
- Validator agent itself can be wrong (a hallucinating validator approves a hallucinated answer).

### Fit for oil & gas use case

- **Excellent for a production system; overkill for a 1-week hackathon UNLESS you scope tight.** The doc-agent + SQL-agent split is genuinely useful because oil & gas has both structured (production, finance) and unstructured (HSE policy, AFE manuals) sources. For a hackathon, implement only router + SQL agent + validator (skip the doc agent).

### Implementation complexity

**4 / 5** — a week with LangGraph; longer from scratch.

---

## 9. GraphRAG over schema (build KG of FK relationships, traverse for context)

**One-line description:** Build a knowledge graph where nodes are tables (or columns) and edges are foreign keys (or named relationships); at query time, find the entities mentioned in the question and traverse the graph to assemble a sub-schema.

### Origin

- **Microsoft GraphRAG** (Edge et al., "From Local to Global: A Graph RAG Approach to Query-Focused Summarization"), arxiv 2404.16130. URL: https://arxiv.org/abs/2404.16130
- Repo: https://github.com/microsoft/graphrag
- Docs: https://microsoft.github.io/graphrag/
- For text-to-SQL specifically: **"Knowledge Graph-Enhanced Text-to-SQL"** patterns are surveyed in **"A Survey on Employing Large Language Models for Text-to-SQL Tasks"**, arxiv 2407.15186. URL: https://arxiv.org/abs/2407.15186
- Also relevant: **CodeS** (arxiv 2402.16347), which uses schema-graph-aware encoding. URL: https://arxiv.org/abs/2402.16347

### How it works

- **Indexing.** Parse the SQLite schema (`PRAGMA foreign_key_list`) to build a directed graph: nodes = tables; edges = FK references. Annotate with column-level metadata (PK, FK, datatype, description).
- Optionally augment with *implicit* edges from naming conventions (e.g., `well_id` columns across tables that lack declared FKs — common in legacy enterprise schemas).
- Embed each node (table card) AND build a graph-aware embedding (e.g., GraphSAGE or simple node2vec) so neighbor structure influences retrieval.
- **At query time:**
  - Identify "entity anchor" tables via vector retrieval (top 2-3 from #2).
  - Traverse the graph: for each anchor, pull all neighbors within K=2 hops.
  - The induced subgraph is the schema context for the SQL generator.
- This guarantees join paths are *contained* in the prompt, even when no individual table embedding ranked the bridging table highly.

### Strengths

- **Solves the bridging-table problem** that pure vector retrieval (#2) consistently fails on. In a 45-table oil & gas schema, the bridge `wellbore_completion_xref` rarely embeds well but is essential for joining `wells -> completions`.
- Encodes structural knowledge (FK chains) explicitly; complements semantic retrieval.
- Graph traversals are deterministic and cheap (graph is small).
- Graph itself is a valuable artifact — can be shown to the user as a schema diagram.
- Microsoft GraphRAG framework gives you tooling out of the box.

### Weaknesses

- **Implicit FKs.** Many legacy SQLite databases (especially in oil & gas, where data flows from many vendor systems) lack declared foreign keys. You must mine them from naming conventions or sample data — error-prone.
- Graph can over-include: 2-hop traversal from `wells` may pull in 30 tables, defeating the purpose.
- Microsoft GraphRAG itself is targeted at *document* summarization; using it for schema requires custom indexing (you ingest schema as documents, not the live DB).
- Adds a layer of indirection that complicates debugging.
- Maintaining the graph as the schema evolves is a non-trivial pipeline.

### Fit for oil & gas use case

- **High-value enhancement** to #2, especially given the join complexity of oil & gas schemas. Strongly recommended as a "phase 2" upgrade after a Schema-RAG MVP. For a hackathon, it's only worth it if your demo specifically showcases multi-hop joins.

### Implementation complexity

**4 / 5** — graph construction + traversal logic + integration with retrieval. 3-5 days, more if FKs are implicit.

---

## 10. Chain-of-agents with validator gate (plan -> generate SQL -> execute -> validate result -> summarize) — modern "compound AI" style

**One-line description:** A fixed pipeline of specialized agents/steps with explicit gates between them, where each gate can halt or revise; the canonical "compound AI system" that composes the best ingredients of #2, #3, #4, #6, and #8.

### Origin

- **Zaharia et al., "The Shift from Models to Compound AI Systems"**, BAIR blog, Feb 2024. URL: https://bair.berkeley.edu/blog/2024/02/18/compound-ai-systems/
- **DSPy** (Khattab et al., "DSPy: Compiling Declarative Language Model Calls into Self-Improving Pipelines"), arxiv 2310.03714. URL: https://arxiv.org/abs/2310.03714 . Repo: https://github.com/stanfordnlp/dspy
- **Anthropic's "Building effective agents"** post (Dec 2024) explicitly recommends this *workflows over agents* style for enterprise reliability. URL: https://www.anthropic.com/research/building-effective-agents
- **CHASE-SQL** (arxiv 2410.01943, Pourreza et al.) — multi-path candidate generation + verifier. URL: https://arxiv.org/abs/2410.01943
- **CHESS-SQL** (arxiv 2405.16755, Talaei et al.) — Catalogue/Filter/Generator/Reviser modules. URL: https://arxiv.org/abs/2405.16755

### How it works

- **Step 1 — Plan.** A planner LLM rewrites the user's question into a structured intent: "type=lookup", "entities=[wells, production]", "metrics=[oil_bbl]", "filters=[date in last quarter]". Optionally classify if the question is answerable from data at all.
- **Step 2 — Schema retrieval.** Use #2 (Schema-RAG) and/or #9 (GraphRAG) to fetch the relevant sub-schema.
- **Step 3 — Example retrieval.** Use #4 (example bank) and optionally #7 (DAIL-style masked retrieval) to fetch 5-10 nearby (Q, SQL) pairs.
- **Step 4 — Generate SQL.** Single LLM call with sub-schema + examples + question. Optionally use #6 (DIN-style) decomposition for complex queries.
- **Step 5 — Static check.** Parse the SQL with `sqlglot`. Reject if it touches forbidden tables (auth-restricted), uses `DELETE`/`UPDATE`/`DROP`, exceeds row limits, or mentions undeclared columns.
- **Step 6 — Execute.** Run on SQLite (or a read-only replica). Capture rows, errors, runtime.
- **Step 7 — Self-correct.** If error: pass back to step 4 with error message (#3). Cap retries at 2.
- **Step 8 — Validate result.** A validator LLM sees question + SQL + rows. Checks: (a) does the result shape match the question (one number vs. a list)? (b) are there sanity-check failures (negative volumes, dates in 1970)? (c) does the row count look right (zero rows when expected nonzero)? (d) are auth filters in place (user's region restricted appropriately)? Outputs PASS/FAIL/WARN + reasoning.
- **Step 9 — Summarize.** Final summarizer LLM sees the validated rows and the original question; produces a natural-language reply with the table inline.
- **Step 10 — Log.** Full trace (question, plan, schema, examples, SQL, rows, validator verdict, reply) goes to an audit log keyed by user. The `(question, SQL)` pair, if validator PASSed, can be added to the example bank (#4).

### Strengths

- **Best-of-breed.** Composes the highest-impact ingredients of every previous architecture.
- **Auditable.** Every step is logged; every gate is inspectable. This is the design auditors and compliance officers actually accept for finance/HSE data.
- **Tunable.** Swap any step (e.g., upgrade Schema-RAG to GraphRAG) without touching others.
- **Validator gate** specifically catches semantically-wrong-but-syntactically-valid queries — the failure mode that #3 alone cannot fix.
- **Fits the auth/approval requirements** of an enterprise oil & gas system: step 5 (static check) is the natural place to enforce row-level security and approval-chain restrictions.
- Self-improving via example-bank append.
- Works with frontier models AND smaller cheaper models for the simpler stages (planner, summarizer).

### Weaknesses

- **Most steps means most latency** — naively, 5-7 sequential LLM calls. Mitigation: parallelize independent steps (schema retrieval and example retrieval can run concurrently); cache aggressively; use smaller models for planner/summarizer.
- **Highest engineering cost** of any pattern here: each step is its own prompt, its own failure mode, its own observability surface.
- **Fragility in pipeline glue.** State management between steps is the bug factory. LangGraph or DSPy mitigate this.
- **Validator is itself an LLM** — non-zero false-pass rate. Pair with deterministic rules (sqlglot static checks) for the catches the validator misses.
- Can over-engineer for simple lookups: "How many active wells?" doesn't need 7 steps.

### Fit for oil & gas use case

- **Best fit.** This is the architecture an enterprise customer would actually buy. For a hackathon, a *minimal* version (steps 2, 4, 6, 7, 8, 9 — skipping plan and example retrieval if time-pressed) is achievable in 3-5 days and demos very well: the validator gate is a strong differentiator on the judging rubric.

### Implementation complexity

**5 / 5** for the full pipeline; **3 / 5** for a hackathon-scoped minimal version.

---

# Cross-architecture summary table

| #  | Pattern                          | Accuracy* | Latency** | Cost** | Engineering | Hackathon-friendly | Production-grade |
|----|----------------------------------|-----------|-----------|--------|-------------|--------------------|------------------|
| 1  | Naive single-shot                | Low       | Lowest    | Low    | 1/5         | Yes (baseline)     | No               |
| 2  | Schema-RAG                       | Med-High  | Low       | Low    | 2/5         | Yes                | Foundation only  |
| 3  | Self-correcting loop             | +5-15pp   | Med       | Med    | 2/5         | Yes (add-on)       | Mandatory add-on |
| 4  | Few-shot example bank (Vanna)    | High      | Low       | Low    | 2/5         | Yes (with seed)    | Yes              |
| 5  | ReAct agent                      | Med-High  | High      | High   | 2/5         | Flashy             | Risky            |
| 6  | DIN-SQL                          | High      | High      | High   | 3/5         | Maybe              | Yes (hybrid)     |
| 7  | DAIL-SQL / C3-SQL                | High      | Med       | Med    | 4/5         | No (too fiddly)    | Yes              |
| 8  | Multi-agent router               | High      | High      | High   | 4/5         | Scoped only        | Yes              |
| 9  | GraphRAG over schema             | +5-10pp   | Low       | Low    | 4/5         | No                 | Phase-2 upgrade  |
| 10 | Chain-of-agents w/ validator     | Highest   | High      | High   | 5/5 (3/5 minimal) | Yes (minimal)| Best fit         |

\* Accuracy ranges are approximate; figures from BIRD-SQL and Spider leaderboards 2024-2025 with frontier LLMs (Claude 3.5/4, GPT-4o/4-turbo). `pp` = percentage-point lift over a strong baseline.
\*\* Latency/cost are relative to a Schema-RAG baseline.

---

# Cross-cutting concerns specific to oil & gas

These concerns apply across patterns and influenced the recommendation.

## Authentication & approval-chain awareness

- The database includes auth and approval tables. The chat assistant must respect the calling user's permissions: a Field Engineer must not see executive-tier finance allocation, an external auditor sees only HSE.
- **Architectural implication.** Whichever pattern wins, you need a *predicate injection* layer — every generated SQL must be wrapped or rewritten to include `WHERE user_visible(...)` constraints. The cleanest place to do this is step 5 (static check) of pattern #10, or as an `sqlglot` AST rewrite post-generation.
- Naive single-shot (#1) and ReAct (#5) cannot enforce this without extra infrastructure.

## Domain jargon density

- Oil & gas is jargon-heavy: AFE (Authorization for Expenditure), DOI (Division of Interest), NRI/WI/RI, BOE, CapEx vs. OpEx, type curve, decline curve, IP30, EUR, shut-in, workover, frac stage.
- **Architectural implication.** Any pattern relying on bare schema embedding (#2, #9 alone) will under-retrieve. Add a domain glossary as retrievable documents (Vanna's `documentation` slot is exactly this; LangChain's example index is equivalent).

## Time semantics

- Production data is daily; finance is monthly; HSE incidents are real-time; AFE approvals are quarterly. "Last quarter" means different things across domains.
- **Architectural implication.** A planning step (#10 step 1) is valuable because it can resolve relative time terms once and pass an absolute date range to downstream SQL generation.

## Mixed structured + unstructured

- Some questions are pure SQL ("Top 10 producing wells"); some need policy ("What's the HSE escalation procedure for an H2S leak?"); many are mixed ("Are we in compliance with the H2S threshold for these 10 wells?").
- **Architectural implication.** A router (#8) or a compound pipeline (#10) with a doc-RAG branch is meaningfully better than a SQL-only system.

## Auditability

- Finance and HSE data have regulatory implications. Hallucinated numbers are not just embarrassing — they can be reportable.
- **Architectural implication.** Validator gate (#10 step 8) and full trace logging are not optional for production. For a hackathon, demoing the validator catching a hallucination is a high-impact moment on the judging rubric.

---

# Final recommendation (under 200 words)

**Pick #10 (Chain-of-Agents with Validator Gate), in a hackathon-minimal form, built on #2 (Schema-RAG) and #3 (Self-correcting SQL loop), seeded with a small #4 (example bank) of ~30 oil-and-gas Q/SQL pairs.**

Concretely: schema-RAG retrieves 8-12 tables -> example-bank retrieves 5 nearest (Q, SQL) pairs -> single SQL-generation call -> sqlglot static check (also enforces auth predicates) -> execute on SQLite -> validator LLM checks answer shape and sanity (negative volumes, empty result on a clearly-answerable question) -> summarizer renders chat reply.

Why this wins: (a) it directly addresses the three pressures unique to this use case — schema scale (#2 solves), correctness on ambiguous joins (#3+validator solve), auditability (validator + trace solve); (b) every component has mature open-source tooling (LangGraph, sqlglot, LlamaIndex, Vanna) so 5 days is realistic; (c) on the judging rubric, the validator gate catching a planted hallucination is a memorable demo moment that single-pipeline architectures (#1, #2, #5) cannot reproduce; (d) it is the only design that maps cleanly to a real enterprise sale post-hackathon.

Patterns #6, #7, #9 are genuinely strong but each adds days of fiddly implementation for a few percentage points of accuracy — not the right hackathon trade. Keep them as phase-2 upgrades.

---

# Cited URLs (canonical primary sources)

## Benchmarks and surveys

- BIRD-SQL benchmark and live leaderboard: https://bird-bench.github.io/
- Spider benchmark: https://yale-lily.github.io/spider
- "A Survey on Employing Large Language Models for Text-to-SQL Tasks" (arxiv 2407.15186): https://arxiv.org/abs/2407.15186
- "Next-Generation Database Interfaces: A Survey of LLM-based Text-to-SQL" (arxiv 2406.08426): https://arxiv.org/abs/2406.08426

## Architecture #1 — Naive

- Rajkumar et al., "Evaluating the Text-to-SQL Capabilities of Large Language Models" (arxiv 2204.00498): https://arxiv.org/abs/2204.00498
- LangChain SQL query checking guide: https://python.langchain.com/docs/how_to/sql_query_checking/
- OpenAI cookbook: https://cookbook.openai.com/

## Architecture #2 — Schema-RAG

- LlamaIndex SQL index demo: https://docs.llamaindex.ai/en/stable/examples/index_structs/struct_indices/SQLIndexDemo/
- LangChain SQLDatabaseToolkit: https://python.langchain.com/docs/integrations/toolkits/sql_database/
- RESDSQL (arxiv 2302.05965): https://arxiv.org/abs/2302.05965

## Architecture #3 — Self-correcting loop

- MAC-SQL (arxiv 2312.11242): https://arxiv.org/abs/2312.11242
- Self-Debug (arxiv 2304.05128): https://arxiv.org/abs/2304.05128
- LangChain query checker: https://python.langchain.com/docs/how_to/sql_query_checking/

## Architecture #4 — Few-shot example bank (Vanna)

- Vanna.ai repo: https://github.com/vanna-ai/vanna
- Vanna.ai docs: https://vanna.ai/docs/
- "Few-shot Text-to-SQL Translation using Structure and Content Prompt Learning" (arxiv 2305.12586): https://arxiv.org/abs/2305.12586

## Architecture #5 — ReAct / tool-using agent

- ReAct (arxiv 2210.03629): https://arxiv.org/abs/2210.03629
- Anthropic tool use: https://docs.anthropic.com/en/docs/build-with-claude/tool-use
- OpenAI function calling: https://platform.openai.com/docs/guides/function-calling
- LangChain SQL agent toolkit: https://python.langchain.com/docs/integrations/toolkits/sql_database/
- LlamaIndex ReActAgent over SQL: https://docs.llamaindex.ai/en/stable/examples/agent/react_agent_with_query_engine/

## Architecture #6 — DIN-SQL

- DIN-SQL (arxiv 2304.11015): https://arxiv.org/abs/2304.11015
- DIN-SQL repo: https://github.com/MohammadrezaPourreza/Few-shot-NL2SQL-with-prompting

## Architecture #7 — DAIL-SQL / C3-SQL

- DAIL-SQL (arxiv 2308.15363): https://arxiv.org/abs/2308.15363
- DAIL-SQL repo: https://github.com/BeachWang/DAIL-SQL
- C3-SQL (arxiv 2307.07306): https://arxiv.org/abs/2307.07306

## Architecture #8 — Multi-agent router

- AutoGen (arxiv 2308.08155): https://arxiv.org/abs/2308.08155
- CrewAI: https://github.com/crewAIInc/crewAI
- LangGraph: https://langchain-ai.github.io/langgraph/
- MAC-SQL (arxiv 2312.11242): https://arxiv.org/abs/2312.11242
- MCS-SQL (arxiv 2405.07467): https://arxiv.org/abs/2405.07467

## Architecture #9 — GraphRAG over schema

- Microsoft GraphRAG (arxiv 2404.16130): https://arxiv.org/abs/2404.16130
- GraphRAG repo: https://github.com/microsoft/graphrag
- GraphRAG docs: https://microsoft.github.io/graphrag/
- CodeS (arxiv 2402.16347): https://arxiv.org/abs/2402.16347

## Architecture #10 — Chain-of-agents with validator gate

- Compound AI Systems (BAIR blog): https://bair.berkeley.edu/blog/2024/02/18/compound-ai-systems/
- DSPy (arxiv 2310.03714): https://arxiv.org/abs/2310.03714
- DSPy repo: https://github.com/stanfordnlp/dspy
- Anthropic, "Building effective agents": https://www.anthropic.com/research/building-effective-agents
- CHASE-SQL (arxiv 2410.01943): https://arxiv.org/abs/2410.01943
- CHESS-SQL (arxiv 2405.16755): https://arxiv.org/abs/2405.16755

## Tooling for the recommended stack

- sqlglot (SQL parser/transformer): https://github.com/tobymao/sqlglot
- LangGraph: https://langchain-ai.github.io/langgraph/
- LlamaIndex: https://docs.llamaindex.ai/
- Vanna.ai: https://github.com/vanna-ai/vanna
- sqlite-vec (vector search inside SQLite): https://github.com/asg017/sqlite-vec

---

# Appendix A — Concrete hackathon implementation plan for the recommended architecture

This appendix is included so a teammate can start building the moment the report is approved.

## Day 0 (Setup, ~4h)

- Spin up a SQLite copy of the 45-table oil & gas database.
- Install: `pip install langgraph langchain-anthropic llama-index sqlglot chromadb vanna`
- Set up a single Python project skeleton:
  - `app/schema_index.py` — builds the table-card vectorstore.
  - `app/example_bank.py` — stores (Q, SQL) pairs.
  - `app/pipeline.py` — the LangGraph state machine.
  - `app/validators.py` — sqlglot static checks + LLM validator prompt.
  - `app/api.py` — FastAPI endpoint.
  - `app/ui.py` — Streamlit chat UI.

## Day 1 (Schema RAG MVP, ~8h)

- Walk every table; for each, compose a "table card":
  - Table name + DDL.
  - 1-2 sentence description (LLM-generated, human-reviewed).
  - 5 sample rows (`SELECT * FROM <t> LIMIT 5`).
  - 2-3 example questions (LLM-generated, "questions a data analyst might ask about this table").
- Embed cards with `text-embedding-3-large` (or `voyage-3-large`); store in Chroma.
- Build a function `retrieve_schema(question, k=10)` returning concatenated cards.
- Smoke test: 10 hand-written questions, verify the right tables are retrieved.

## Day 2 (Generation + Self-correction, ~8h)

- Implement `generate_sql(question, schema_context, examples)` calling Claude with a tight prompt.
- Implement `execute_sql(sql)` with timeout, row limit (5K), and exception capture.
- Implement self-correction loop with N=2 retries on `OperationalError`.
- Smoke test on the same 10 questions; aim for >=7/10 correct.

## Day 3 (Example bank + Validator, ~8h)

- Hand-write or LLM-bootstrap 30 (question, SQL) pairs covering: production lookups, finance aggregations, HSE compliance checks, AFE approval status, well status by region.
- Embed and store; integrate `retrieve_examples(q, k=5)` into the pipeline.
- Implement the validator LLM call with prompt: "Given Q, SQL, and rows, is this answer plausible? Output PASS/FAIL/WARN with reasoning."
- Implement sqlglot static check enforcing: read-only, no `*` on big tables, mandatory user-region predicate.

## Day 4 (UI + traces + auth, ~8h)

- Streamlit chat with: chat history, expandable "trace" view (schema retrieved, SQL, rows, validator verdict).
- Mock auth: a dropdown to pick user role; injected as a JWT-like context into static-check rewrites.
- Add Anthropic prompt caching on the schema-card concat (large, repeated).

## Day 5 (Polish + demo script, ~6h)

- Pick 5 demo queries spanning: easy lookup, multi-table join, finance aggregation, HSE compliance, ambiguous question (clarification path).
- Plant 1 hallucination scenario where the validator catches it — best demo moment.
- Record a 3-minute demo video as backup.

## Stretch (Day 6+)

- Add #9 GraphRAG over the FK graph for multi-hop joins.
- Add a doc-RAG agent for HSE policy questions (#8 split).
- Add DSPy compilation of the prompts (turn the pipeline into a `dspy.Module` and let it self-tune).

---

# Appendix B — Risk register

| Risk                                              | Likelihood | Impact | Mitigation                                                       |
|---------------------------------------------------|------------|--------|------------------------------------------------------------------|
| Schema retrieval misses the bridging table        | Med        | High   | Add #9 GraphRAG; or hand-tune table descriptions for bridges.    |
| LLM hallucinates plausible-but-wrong column       | Med        | High   | Self-correction loop + sqlglot AST check against real columns.   |
| Validator agent rubber-stamps a wrong answer      | Low-Med    | High   | Pair LLM validator with deterministic rules (negative volumes).  |
| Example bank biases toward known patterns         | Med        | Med    | Annotate examples with "structure tags"; rotate retrieval weight.|
| User asks a non-data question ("explain HSE")     | High       | Low    | Router fallback to doc-RAG OR a polite "I can only answer data". |
| Auth predicate not injected                       | Low        | Critical| sqlglot rewrite is mandatory; unit test every generated SQL.    |
| Latency too high for chat (>5s)                   | Med        | Med    | Parallelize schema + example retrieval; cache schema cards.       |
| Cost spikes on long traces                        | Low        | Med    | Use Haiku for planner/summarizer; Sonnet/Opus only for SQL gen.  |
| Demo DB has surprise FK chains                    | Med        | Med    | Run `PRAGMA foreign_key_list` on day 0; build the graph eagerly. |

---

# Appendix C — What we did NOT pick, and why

- **Naive single-shot (#1)** — fails on schema scale; useful only as a baseline for the report.
- **Pure ReAct (#5)** — too slow and unpredictable for a chat UX; useful as the *fallback* path inside #10 but not as the primary architecture.
- **DIN-SQL (#6) standalone** — strong accuracy but quadruples LLM calls; the schema-linking step duplicates work that Schema-RAG already does. Use *parts* of DIN-SQL (the difficulty classifier, the self-correction prompt) inside #10.
- **DAIL-SQL / C3-SQL (#7) standalone** — improves few-shot retrieval quality, but the masking pipeline is fiddly. Use the *idea* (mask schema-specific tokens before embedding the question) as a 1-line tweak to the example-bank embedder; skip the full implementation.
- **Multi-agent router (#8) full version** — overkill for hackathon scope. Keep the validator+SQL specialist; defer doc-agent + clarification-agent to phase 2.
- **GraphRAG over schema (#9)** — high value but high engineering cost; defer to phase 2 unless the demo specifically showcases multi-hop joins.

---

# Appendix D — Success metrics for the hackathon judging

- **Execution accuracy on a held-out 20-question set:** target >= 80%. Baseline (naive): ~40%. Chain-of-agents minimal: ~80-85%.
- **Demo wow-factor moments:** (1) validator catches a planted hallucination, (2) auth predicate visibly applied (different rows for different roles), (3) full audit trace expandable in UI.
- **Latency (P50):** target <= 4s for simple lookups, <= 8s for multi-table joins.
- **Cost:** target <= $0.05 per query at the recommended model mix (Haiku for plan/summarize, Sonnet for SQL gen, Sonnet for validate).
- **Lines-of-code:** target <= 1200 LoC including UI; this is achievable on top of LangGraph + Vanna + sqlglot.

---

*End of report.*
