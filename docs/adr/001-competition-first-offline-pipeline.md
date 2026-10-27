---
status: accepted
---

# Prioritize an offline competition pipeline

LifeMate will first process benchmark-provided audio through a fully offline pipeline; a phone or browser voice interface is deferred. The supplied competition brief requires offline Docker inference, so the original Wispr Flow proposal is replaced by locally runnable ASR experiments. This concentrates development on scored tool behavior and reproducible execution; model candidates live in [the technology stack](../../context/tech_stack.md), and submission constraints live in [benchmark rules](../../context/benchmark.md).
