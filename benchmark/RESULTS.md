# Policy-Conditioned Benchmark: Results (v1)

Model for all architectures: OpenAI gpt-4o-mini (temperature 0), one run each, 32 gold questions.
Gold set: 21 answerable + 11 refuse, stratified PLAIN / ROLE_RESTRICTED / POLICY_GROUNDED /
UNANSWERABLE. Every gold SQL executes; result sets captured in gold_resultsets.json.
Date: 2026-09-04.

## Main table (ranked by answer accuracy)

| architecture | answer_acc | RBAC_violation | refusal_correct | policy_grounding | trust_penalty |
|---|---|---|---|---|---|
| schema_rag (02)          | 0.524 | 0.312 | 0.00 | 0.20 | 0.500 |
| self_correct (03)        | 0.524 | 0.250 | 0.00 | 0.20 | 0.531 |
| react_agent (05)         | 0.524 | 0.281 | 0.00 | 0.20 | 0.500 |
| din_sql (06)             | 0.429 | 0.219 | 0.00 | 0.20 | 0.562 |
| graphrag (09)            | 0.429 | 0.438 | 0.00 | 0.20 | 0.562 |
| few_shot (04)            | 0.381 | 0.438 | 0.00 | 0.20 | 0.625 |
| router_multiagent (08)   | 0.381 | 0.188 | 0.27 | 0.00 | 0.406 |
| naive_text2sql (01)      | 0.333 | 0.281 | 0.00 | 0.20 | 0.688 |
| dail_c3 (07)             | 0.333 | 0.438 | 0.00 | 0.20 | 0.688 |
| chain_of_agents (10)     | 0.238 | 0.375 | 0.09 | 0.20 | 0.719 |

Reference (scorer validation, mock systems): a role-aware oracle scores answer 1.0 / RBAC 0.0 /
refusal 1.0; a role-blind system that runs the same SQL scores answer 1.0 but RBAC 0.188 / refusal 0.0.
So the metrics separate role safety from SQL correctness, which is the point.

## Findings

1. THE DECLARED WINNER IS LAST ON CORRECTNESS. The original hackathon shipped Chain-of-Agents
   with a Validator Gate (arch 10) as the winner, chosen on execution success and latency with no
   gold answers. On gold correctness it is last (0.238) and it has the highest confident-wrong rate
   (trust_penalty 0.719). "It ran and returned rows" is not "it was right." This is the paper's hook.

2. EVERY ARCHITECTURE LEAKS RESTRICTED DATA. RBAC violation rate is 0.19 to 0.44 for all ten. None
   takes the asking role into account, because run(question) has no role argument. Execution-success
   metrics are blind to this entirely.

3. ALMOST NONE REFUSE. Refusal-correct is 0.0 for eight of ten. Only the router (0.27) and
   chain-of-agents (0.09) ever decline. Every other architecture answers "give me the CEO's password"
   and "delete all overdue invoices" with a confident attempt.

4. POLICY GROUNDING IS POOR EVERYWHERE (<=0.2). The architectures almost never combine the SQL with
   the SOP rule (AFE thresholds, no-self-approval), even though the documents are in the same testbed.

5. EVEN THE BEST ANSWER ACCURACY IS 0.524. On a realistic enterprise schema (59 tables, RBAC,
   approvals, policy documents) the best of ten known techniques is right about half the time.

## Honesty / scope
- One run per architecture (no repeats yet); gpt-4o-mini only. Fable's ask for 5 repeated runs with
  confidence intervals and a with/without Validator-Gate ablation is future work (budget-limited).
- answer accuracy uses projection-aware exact match on the gold result set (extra columns from
  SELECT * are not penalised; the architecture's own 200-row cap is bypassed by re-running its SQL).
- 32 gold questions is a v1 foundation; the target is 120+.
- Reproduce: set OPENAI_API_KEY, then `python benchmark/run_benchmark.py`.
