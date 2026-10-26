"""Autocomplete index built from every article we store.

Three tries (authors, title terms, categories) are fed as articles are
cached, so suggestions cost zero arXiv calls. When a prefix matches nothing,
banded edit distance offers "did you mean" corrections.
"""
from __future__ import annotations

import re
from typing import Iterable, Literal

from .categories import CATEGORIES
from .dsa.edit_distance import within_distance
from .dsa.trie import Trie, normalize

Kind = Literal["author", "term", "category"]

_STOP = set(
    "a an and are as at be by for from has in into is it its of on or that the their this to "
    "via with we our using based towards toward new can not than over under via vs".split()
)
_TOKEN = re.compile(r"[a-z][a-z0-9\-]{2,}")


def title_terms(title: str) -> set[str]:
    return {t.strip("-") for t in _TOKEN.findall(normalize(title)) if t not in _STOP and len(t.strip("-")) > 2}


class SuggestIndex:
    def __init__(self, k_max: int = 10):
        self.tries: dict[str, Trie] = {"author": Trie(k_max), "term": Trie(k_max), "category": Trie(k_max)}
        self.labels: dict[str, str] = {}
        for archive, group in CATEGORIES.items():
            for code, name in group.items():
                self.labels[code] = name
                words = normalize(name).split()
                self.tries["category"].add(code, [code, normalize(name), *words], weight=0)
            self.tries["category"].add(archive, [archive], weight=0)
            self.labels.setdefault(archive, f"All of {archive}")

    def add_article(self, title: str, authors: Iterable[str], primary_category: str | None) -> None:
        for name in authors:
            if name:
                parts = normalize(name).split()
                # Reachable by full name and by surname: "yann lecun", "lecun".
                self.tries["author"].add(name, [" ".join(parts), parts[-1]] if parts else [name])
        for term in title_terms(title):
            self.tries["term"].add(term)
        if primary_category and primary_category in self.labels:
            self.tries["category"].add(primary_category)

    def suggest(self, kind: Kind, prefix: str, k: int = 8) -> dict:
        trie = self.tries[kind]
        hits = trie.top_k(prefix, k)
        out = {
            "suggestions": [self._item(kind, text, w) for text, w in hits],
            "did_you_mean": [],
        }
        p = normalize(prefix)
        if not hits and len(p) >= 4:
            out["did_you_mean"] = [self._item(kind, t, w) for t, w in self._fuzzy(trie, p, 3)]
        return out

    def _item(self, kind: str, text: str, weight: int) -> dict:
        item = {"text": text, "count": weight}
        if kind == "category":
            item["label"] = self.labels.get(text)
        return item

    @staticmethod
    def _fuzzy(trie: Trie, prefix: str, k: int) -> list[tuple[str, int]]:
        max_d = 1 if len(prefix) < 7 else 2
        best: dict[str, tuple[int, int]] = {}
        for display, keys in trie._keys.items():
            for key in keys:
                d = within_distance(prefix, key[: len(prefix)], max_d)
                if d is not None and (display not in best or d < best[display][0]):
                    best[display] = (d, trie.weight[display])
        ranked = sorted(best.items(), key=lambda kv: (kv[1][0], -kv[1][1], kv[0].lower()))
        return [(display, w) for display, (_, w) in ranked[:k]]

    def sizes(self) -> dict[str, int]:
        return {kind: len(t) for kind, t in self.tries.items()}
