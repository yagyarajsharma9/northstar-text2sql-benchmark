# Paper submission bundle

Paper: "It Ran Is Not It Was Right: A Policy-Conditioned Benchmark of Ten Text-to-SQL Architectures on
an Enterprise Database."

## Files
- main_proof.pdf   <- READ THIS. Compiled 3-page (two-column) short paper.
- main_proof.tex   - source (article class, compiles anywhere).
- DRAFT.md         - the same paper in markdown (easy to edit).
- (results + code live in ../benchmark/)

## The novelty (one line)
Enterprise text-to-SQL is usually scored by "did the SQL run." We show that on a realistic company
database this is misleading, and introduce policy-conditioned correctness: score answer correctness vs
gold, data leakage vs the asker's role, policy grounding, and refusal. Under it, the execution-success
"winner" is near the bottom, all ten architectures leak restricted data, and almost none refuse.

## Venue (Fable-recommended, realistic for a methods/benchmark short paper)
1. KDD Enterprise AI Agents Workshop (next edition).
2. VLDB NOVAS Workshop (accepted an enterprise text-to-SQL ablation before).
3. SURGeLLM (ACL workshop; lists text-to-SQL + evaluation + enterprise data).
Post to arXiv on submission.

## Before submission (to make it stronger; some need more API budget)
- 5 repeated runs per architecture with confidence intervals; add a with/without Validator-Gate
  ablation (isolate whether the gate helps correctness/refusal).
- Grow the gold set from 94 to 120+.
- Add a second model (not only gpt-4o-mini) so the comparison is not model-specific.
- Verify the [verify authors] references and move the content into the venue's LaTeX template.
- Release: publish the repo (currently private) and/or a Zenodo archive of the testbed + gold set;
  commit the seeded DB (or pin the seed) so gold answers are reproducible.

## Honesty kept in the paper
One run per architecture, single model, synthetic data (so absolute accuracies would differ on a real
DB; the between-architecture comparison and the leak/refusal findings are what we rely on). All numbers
are from real runs in ../benchmark/benchmark_scores.json.
