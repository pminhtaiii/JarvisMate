"""recipes: one method per tool of the app. State: recipes[] (catalogue on device) and saved[] ({id, recipe_id})."""
from __future__ import annotations

from ._shop_match import match_items, positive_int
from .base import App, read, write


def _scaled(recipe, servings):
    """Copy of the recipe's ingredients scaled to `servings` (pure function of the stored recipe)."""
    base = recipe.get("servings") or 0
    out = []
    for ing in recipe.get("ingredients", []):
        ing = dict(ing)
        if positive_int(servings) and base and isinstance(ing.get("quantity"), (int, float)) and not isinstance(ing.get("quantity"), bool):
            q = ing["quantity"] * servings / base
            ing["quantity"] = int(q) if float(q).is_integer() else round(q, 1)
        out.append(ing)
    return out


class Recipes(App):
    name = "recipes"

    @read
    def search(self, query=None, servings=None, **_):
        hits = match_items(self.state.get("recipes", []), query, ("name", "tags"),
                           extra=lambda r: " ".join(str(i.get("name", "")) for i in r.get("ingredients", [])))
        out = []
        for r in hits:
            item = {k: v for k, v in r.items() if k not in ("steps", "ingredients")}
            item["ingredients"] = _scaled(r, servings)
            if positive_int(servings):
                item["servings"] = servings
            out.append(item)
        return {"ok": True, "recipes": out}

    @read
    def get(self, recipe_id=None, **_):
        r = self.find("recipes", recipe_id)
        if r is None:
            return self.noop("không tìm thấy recipe_id")
        return {"ok": True, "recipe": r, "saved": any(s.get("recipe_id") == recipe_id for s in self.state.get("saved", []))}

    @write
    def save(self, recipe_id=None, **_):
        r = self.find("recipes", recipe_id)
        if r is None:
            return self.noop("không tìm thấy recipe_id")
        for s in self.state.get("saved", []):
            if s.get("recipe_id") == recipe_id:
                return {"ok": True, "saved": s, "already_saved": True}
        res = self.create("saved", "sav", recipe_id=recipe_id)
        return {"ok": True, "saved": res["item"]}
