"""
Internal lab : 10 chat-to-DB architectures, all sharing the same
interface  ``run(question: str) -> dict``  so the benchmark can swap
them in/out without touching call sites.

The "winner" (#10) lives in /winning_architecture for the production
build. The 9 stubs here exist for internal benchmarking, ablation, and
showing the evolution of complexity.
"""
