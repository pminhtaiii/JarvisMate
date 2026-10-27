---
name: handoff
description: Compact the current conversation into a handoff document for another agent to pick up.
argument-hint: "What will the next session be used for?"
disable-model-invocation: true
---

Write a handoff document summarising the current conversation so a fresh agent can continue the work. Save it in the `handoffs` subfolder of the active managed session dump and give the next agent that exact path. Reuse the session path recorded for the current chat across resumptions. If the path is unknown, run `pnpm agent:work list` and reuse the active session matching this chat ID. If none exists, create one with `pnpm agent:work start --session <id>` from the Booking Systems checkout; stop and report if the checkout, helper, or chat ID is unavailable.

Include a "suggested skills" section in the document, naming which skills the next agent should call the Skill tool for.

Do not duplicate content already captured in other artifacts (specs, plans, ADRs, issues, commits, diffs). Reference them by path or URL instead.

Keep working notes and detailed evidence in the session dump. Preserve approved specs, the canonical task ledger, ADRs, and concise verification records at their project paths; promote any decision the next agent needs before marking the session finished. Do not migrate older handoffs.

Redact any sensitive information, such as API keys, passwords, or personally identifiable information.

If the user passed arguments, treat them as a description of what the next session will focus on and tailor the doc accordingly.
