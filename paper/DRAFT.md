# "It Ran" Is Not "It Was Right": A Policy-Conditioned Benchmark of Ten Text-to-SQL Architectures on an Enterprise Database

Yagya Raj Sharma
(affiliation to be finalised)

Target venue: an enterprise-AI / NL-to-SQL workshop (KDD Enterprise AI Agents, VLDB NOVAS, or an ACL
text-to-SQL workshop). Short paper.

---

## Abstract

Enterprise chat assistants that answer questions over a company database are usually judged by whether
their SQL runs and how fast. On a realistic company database that measure is misleading. A query can
run and return rows and still be wrong, or return rows the person asking is not allowed to see, or
ignore a rule written in a policy document, or answer a question that should have been refused. We
build a testbed with all of these pressures in one place: an oil and gas database of 59 tables with
role based access control, an approval workflow, and nine policy documents, and a gold set of 94
questions labelled with correct answers, the asking role, and whether the correct behaviour is to
answer or to refuse. We score ten published text-to-SQL architectures, the same ones a hackathon had
ranked by execution success, on four axes that execution success cannot see: answer correctness against
gold, data leakage against role, policy grounding, and refusal. The results are blunt. The architecture
the execution-success ranking called the winner is ninth of ten on correctness. Every one of the ten
leaks restricted data on 37 to 52 percent of questions. Eight of the ten never refuse, and answer a
request for a password hash, a request to delete invoices, and a prompt injection asking for the API
key with a confident attempt. The best answer accuracy across all ten is 0.50. We argue that
enterprise text-to-SQL should be evaluated by policy-conditioned correctness, not execution success,
and we release the testbed, the gold set, and the scorer.

Keywords: text-to-SQL, enterprise data, evaluation, RBAC, LLM agents, benchmark.

---

## 1. Introduction

A common enterprise use of large language models is a chat assistant that turns a natural-language
question into SQL over the company's database. There are many designs for this, from a single prompt to
multi-agent pipelines, and there is a natural urge to ask which is best. The usual way to answer is a
bake-off: run each design on a set of questions and see whose SQL executes, returns rows, and does so
quickly.

This paper started from exactly such a bake-off. Ten text-to-SQL architectures were built over an
enterprise oil and gas database and ranked by execution success and latency, and a multi-agent design
was declared the winner. The ranking had a hole in it that is easy to miss and common in practice:
nobody had written down the correct answers, so "the query ran and returned rows" was standing in for
"the answer was right." On a real company database that substitution fails in four distinct ways:

- the query runs but returns the wrong rows;
- the query runs but returns rows the asking person is not permitted to see;
- the query runs but ignores a rule that lives in a policy document, not in the schema;
- the query runs on a question that should have been refused, such as a request for a password or a
  destructive command.

None of these is visible to an execution-success metric. We therefore build a testbed where all four
pressures are present, write down the correct behaviour, and re-score the same ten architectures.

Our contribution is a way to measure and the measurement itself. We contribute (1) a policy-conditioned
gold set of 94 questions over an enterprise database, each labelled with the correct result, the asking
role, and whether the correct behaviour is to answer or refuse; (2) a scorer that reports answer
correctness against gold, a role-based data-leak rate, a policy-grounding rate, and a refusal rate, and
that we validate separates a role-aware system from a role-blind one; and (3) the result of running ten
published architectures through it, which overturns the execution-success ranking and shows that all
ten are unsafe on a company database. We release the database, the documents, the gold set, the oracle,
and the scorer.

The message is short. On enterprise data, "it ran" is not "it was right," and a benchmark that cannot
tell the difference will pick the wrong system and call an unsafe one good.

## 2. Related work

Text-to-SQL benchmarks have moved toward enterprise realism. Spider 2.0, BEAVER, and EntSQL grade SQL
correctness on large, realistic schemas and workflows. These measure whether the SQL is right; they do
not ask whether the asker was allowed to run it, or whether a policy document changes the answer.

A separate line adds guards to the pipeline. TrustSQL penalises confident wrong answers and rewards
abstention; PV-SQL and MARS-SQL add a verification or validation agent. Role-based access control has
begun to appear: a recent benchmark studies text-to-SQL under RBAC, mostly at the level of whole
tables. Multi-architecture comparisons exist too, for example BAPPA, which pits agents, plans, and
pipelines against one another.

What is missing, and what we provide, is a single testbed and gold set that put role, policy documents,
and refusal together and score several architectures on all of them at once, so the gap between "ran"
and "was right and safe" is one measurable quantity. We call this policy-conditioned correctness. The
ten architectures we evaluate are the standard ones: a naive single call; schema retrieval; a
self-correcting loop; a few-shot example bank in the style of Vanna; a ReAct agent; DIN-SQL; the
DAIL and C3 prompting styles; a router with specialist agents; a GraphRAG variant; and a chain of
agents with a validator gate.

## 3. The testbed

The database models an oil and gas company: 59 tables covering wells and production, finance
(invoices, purchase orders, contracts, payments), operations, health and safety (incidents,
inspections, permits), and identity. Identity is real: 20 roles, 23 resource-action permissions, and a
role-permission table, plus a four-tier approval workflow. Nine policy documents (an approval policy, a
health and safety policy, procedures) are stored and full-text indexed. The data is synthetic and
seeded, and contains no real company or personal information.

Two things make it a fair place to test policy-conditioned correctness. First, access is governed by a
real permission table, so "which rows may this role see" has a definite answer we can check. Second,
some correct answers depend on a rule that is written in a document, not in the schema, for example the
approval-tier thresholds, so a system must combine SQL with a retrieved policy fact to be right.

## 4. The gold set

We wrote 94 questions in four types.

- PLAIN (20): ordinary questions whose asker has the needed read permission.
- ROLE_RESTRICTED (54): the same question asked by a role that may see the data (correct behaviour:
  answer) and by roles that may not (correct behaviour: refuse). These are generated from sensitive
  query templates crossed with roles, using the permission table, so the allowed/denied label is
  correct by construction.
- POLICY_GROUNDED (10): questions whose correct answer needs a rule from a policy document, such as
  "which requests need joint CFO and CEO approval," which requires the Tier 3 threshold from the
  approval policy.
- UNANSWERABLE (10): questions that should be refused: a password hash, a destructive command, a
  future prediction, an out-of-domain question, and a prompt injection asking for the API key.

Each answerable question carries reference SQL. We execute every reference query against the database
and store its result set as the gold answer, so grading is exact rather than by inspection. Fifty
questions are answerable and 44 should be refused.

## 5. Metrics

For each architecture output on each question we compute:

- answer accuracy: the result set of the produced SQL matches the gold result set. Comparison is
  order-insensitive and projection-aware, so a system that selects extra columns is not penalised, and
  we re-run the produced SQL ourselves so an internal row cap does not distort the comparison.
- RBAC violation rate: the fraction of questions on which the produced SQL reads a table the asking
  role is not permitted to read. The permitted tables per role come from the live permission table.
- refusal correctness: on questions that should be refused, whether the architecture declined rather
  than answered.
- policy grounding rate: on policy questions, whether the answer applied the document rule, measured
  by matching the gold result that encodes the rule.
- trust penalty rate: confident-wrong behaviour, that is returning data on a question that should be
  refused, or giving a wrong answer with no hedge.

We validate the scorer with two mock systems. A role-aware oracle that answers with the gold SQL and
refuses the rest scores answer 1.0, RBAC violation 0.0, refusal 1.0. A role-blind system that runs the
same SQL regardless of who is asking scores answer 1.0, but RBAC violation 0.36 and refusal 0.0. The
metrics therefore separate SQL correctness from role safety, which is the whole point.

## 6. Results

All ten architectures use the same model (OpenAI gpt-4o-mini, temperature 0), one run each, on the 94
questions.

Table 1. Ten architectures, ranked by answer accuracy.
| architecture | answer_acc | RBAC_violation | refusal | policy_grounding | trust_penalty |
|---|---|---|---|---|---|
| schema_rag         | 0.50 | 0.426 | 0.00 | 0.10 | 0.543 |
| react_agent        | 0.50 | 0.436 | 0.00 | 0.10 | 0.543 |
| self_correct       | 0.46 | 0.426 | 0.00 | 0.10 | 0.628 |
| router_multiagent  | 0.44 | 0.372 | 0.16 | 0.00 | 0.457 |
| graphrag           | 0.44 | 0.489 | 0.00 | 0.10 | 0.553 |
| few_shot           | 0.42 | 0.500 | 0.00 | 0.20 | 0.638 |
| dail_c3            | 0.42 | 0.521 | 0.00 | 0.20 | 0.628 |
| din_sql            | 0.40 | 0.404 | 0.00 | 0.20 | 0.574 |
| chain_of_agents    | 0.38 | 0.436 | 0.05 | 0.20 | 0.638 |
| naive_text2sql     | 0.36 | 0.457 | 0.00 | 0.20 | 0.617 |

Four findings stand out.

The execution-success winner is not the correctness winner. Chain-of-agents with a validator gate, the
design the original bake-off ranked first on execution success and latency, ranks ninth of ten on gold
correctness (0.38) and ties for the worst confident-wrong rate. The extra machinery produced more
elaborate SQL that ran and returned rows, but returned the right rows less often.

Every architecture leaks restricted data. RBAC violation runs from 0.37 to 0.52. None of the ten takes
the asking role into account, because the interface is a bare question with no identity. A finance
analyst's question and a drilling engineer's question are answered the same way, so a query that reads
salaries or contracts runs no matter who asked.

Almost none refuse. Refusal correctness is 0.00 for eight of the ten. Only the router (0.16) and
chain-of-agents (0.05) ever decline. The other eight answer a request for a password hash, a request to
delete invoices, and a prompt injection asking for the API key with a confident SQL attempt.

Policy grounding and overall accuracy are low. Policy grounding is 0.0 to 0.2 everywhere: the
architectures rarely apply the approval-tier or no-self-approval rules even though the documents are in
the same testbed. And the best answer accuracy of any of the ten is 0.50. On a realistic enterprise
schema the best of ten known techniques is right about half the time.

The direction matches a 32-question pilot we ran first, where the same picture held; the larger, more
role-heavy set makes the leak and refusal gaps sharper, not softer.

## 7. Discussion

The results argue for a change of default. Execution success is a convenient metric because it needs no
labels, but on enterprise data it rewards a system for producing runnable SQL rather than correct,
authorized, policy-aware answers, and it will therefore rank a confident and unsafe system above a
careful one. Three concrete steps follow from the four failures. Pass the asking role into the pipeline
and filter the schema and the result by permission, so a query cannot read what the role may not see.
Retrieve the relevant policy fact and make it available to the SQL step, so policy-grounded questions
are answered from the rule and not guessed. And train or prompt the system to refuse, and measure the
refusal, so a request for a password or a destructive command is declined rather than attempted. None
of this is exotic; the point of the paper is that without a policy-conditioned benchmark none of it is
measured, and what is not measured is not fixed.

## 8. Threats to validity

We report one run per architecture on a single model; repeated runs with confidence intervals and a
comparison across models are future work, as is a controlled with and without the validator gate. The
gold set is 94 questions; it is a foundation, not a final size. The policy-grounding metric is a proxy
(matching the gold result that encodes the rule) rather than a check of whether the document was
retrieved. answer accuracy uses exact result-set match, which is strict; a system that returns a
correct superset is scored wrong. The data is synthetic, so absolute accuracies would differ on a real
company database; the comparison between architectures, and the leak and refusal findings, are what we
rely on. The gold answers depend on the seeded database, so a reproduction must use the released
database rather than a fresh seed.

## 9. Conclusion

We built an enterprise text-to-SQL testbed with role-based access, an approval workflow, and policy
documents, and a gold set that labels each question with the correct answer, the asking role, and
whether to refuse. Scoring ten published architectures on it overturns an execution-success ranking:
the declared winner is near the bottom on correctness, every architecture leaks restricted data, almost
none refuse, and the best is right about half the time. On enterprise data, evaluation should be
policy-conditioned. We release the testbed, gold set, and scorer so others can measure the same way.

---

## References (verified against arXiv/publisher pages; confirm formatting at submission)

[1] F. Lei, et al. Spider 2.0: Evaluating Language Models on Real-World Enterprise Text-to-SQL
    Workflows. ICLR 2025.
[2] P. Chen, et al. BEAVER: An Enterprise Benchmark for Text-to-SQL. arXiv:2409.02038.
[3] EntSQL: Grounding Enterprise Text-to-SQL in Long-Context Knowledge. arXiv:2606.03363. [verify authors]
[4] Text-to-SQL for Enterprise Data Analytics. arXiv:2507.14372. [verify authors]
[5] Benchmarking Text-to-SQL under Role-Based Access Control. arXiv:2607.22115. [verify authors]
[6] G. Lee, et al. TrustSQL: A Reliability Benchmark for Text-to-SQL with Penalised Abstention.
    arXiv:2403.15879.
[7] PV-SQL: Verification for Text-to-SQL. arXiv:2604.17653. [verify authors]
[8] MARS-SQL: A Validation-Agent Approach to Text-to-SQL. arXiv:2511.01008. [verify authors]
[9] BAPPA: Benchmarking Agents, Plans, and Pipelines for Text-to-SQL. arXiv:2511.04153. [verify authors]
[10] M. Pourreza, D. Rafiei. DIN-SQL: Decomposed In-Context Learning of Text-to-SQL. NeurIPS 2023.
[11] D. Gao, et al. Text-to-SQL Empowered by Large Language Models (DAIL-SQL). VLDB 2024.
[12] X. Dong, et al. C3: Zero-shot Text-to-SQL with ChatGPT. arXiv:2307.07306.
[13] S. Yao, et al. ReAct: Synergizing Reasoning and Acting in Language Models. ICLR 2023.
[14] D. Edge, et al. From Local to Global: A GraphRAG Approach to Query-Focused Summarization.
    arXiv:2404.16130.
[15] OpenAI. gpt-4o-mini. 2024.
