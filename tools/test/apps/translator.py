"""translator: one method per tool of the app. Deterministic: the state may hold a `dictionary`
[{text, to_lang, translation}]; a text found there (compared after lower-case, diacritics and punctuation removed) returns
its translation, any other text comes back unchanged together with the requested to_lang."""
from __future__ import annotations

from ..utils import _fold
from .base import App, read


def _key(s):
    return " ".join("".join(ch if ch.isalnum() else " " for ch in (_fold(s) or "")).split())


class Translator(App):
    name = "translator"

    @read
    def translate(self, text=None, to_lang=None, from_lang=None, **_):
        lang = str(to_lang or "").strip().lower()
        out = text
        for e in self.state.get("dictionary", []) or []:
            if isinstance(e, dict) and str(e.get("to_lang", "")).lower() == lang and _key(e.get("text")) == _key(text):
                out = e.get("translation", text)
                break
        return {"ok": True, "text": text, "from_lang": from_lang, "to_lang": lang, "translation": out, "translated": out}
