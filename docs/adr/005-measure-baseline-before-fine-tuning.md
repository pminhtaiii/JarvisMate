---
status: accepted
---

# Measure an end-to-end baseline before fine-tuning

Build and evaluate the complete competition path using pretrained models before investing in fine-tuning. This defers specialization work in exchange for an observable baseline that separates speech, planning, execution, and latency failures; compare planning on supplied training transcripts with planning on ASR transcripts to inform which component needs improvement. Any later tuning uses permitted training data with a held-out comparison; target component and tuning method remain open, and no baseline performance has yet been established.
