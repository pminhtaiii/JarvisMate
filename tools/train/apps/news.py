"""news: one method per tool of the app. State: {articles: [{id, title, topic, source, published_at, summary}], saved: [{id, article_id}]}."""
from __future__ import annotations

from ..utils import _tokens
from .base import App, read, write


class News(App):
    name = "news"

    @read
    def headlines(self, topic=None, **_):
        return self.read("articles", eq={"topic": topic})

    @read
    def search(self, query=None, **_):
        """Keyword search: an article matches when ANY query token (after fold) is a word of its title, summary, source or topic;
        ranked by the number of matching tokens (ties keep the state order). An empty / '*' query lists every article."""
        q_toks = _tokens(query) - {"*"}
        ranked = []
        for i, a in enumerate(self.state.get("articles", [])):
            words = set()
            for k in ("title", "summary", "source", "topic", "category"):
                words |= _tokens(a.get(k))
            hits = len(q_toks & words)
            if q_toks and not hits:
                continue
            ranked.append((-hits, i, dict(a)))
        return {"ok": True, "articles": [a for _, _, a in sorted(ranked, key=lambda t: t[:2])]}

    @write
    def save(self, article_id=None, **_):
        art = self.find("articles", article_id)
        if art is None:
            return self.noop(f"không tìm thấy article_id={article_id!r}")
        for it in self.state.get("saved", []):  # saving twice keeps a single entry
            if it.get("article_id") == article_id:
                return {"ok": True, "id": it["id"], "item": it}
        return self.create("saved", "saved", article_id=article_id)
