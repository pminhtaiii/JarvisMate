"""Offline native Qwen Next-Action SFT tooling (fine-tune-llm/specs.md v1.3).

Importing this package or its model-free modules never imports Torch,
Transformers, PEFT, bitsandbytes or LMFE and never starts a job. Each CLI
invocation runs exactly one explicitly requested phase.
"""
