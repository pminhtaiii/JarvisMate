# Native P1 prompt versions

This folder carries exact system-prompt text files for transfer to another machine. The `.txt` files contain prompt content only: no title, wrapper, or trailing newline. `manifest.json` records each version and SHA-256 over NFC UTF-8 bytes.

- `native-p1-vi-v1.txt` matches the current runtime `SYSTEM` in `python/src/lifemate/prompting.py` and is the prompt to use with the existing L1 export.
- `native-p1-vi-v2.txt` preserves the v2 design in `fine-tune-llm/specs.md` §4.2. It is a reference version and is not selected by the current runtime. Do not substitute it for v1 when testing L1.

The spec currently names v2 as its selected design while the runtime has been restored to v1 to match the existing L1 export. Reconcile that contract before freezing another suite or treating a v2 run as comparable.