"""Autocomplete trie with per-node top-k (LeetCode 642 style).

Every node on a word's path keeps its K best completions, so a query is a
walk down the prefix and nothing else:

    insert: O(L * K log K)   (L = key length, K = suggestions kept per node)
    query:  O(P + k)         (P = prefix length), independent of index size

A display string ("Yann LeCun") can be reached from several keys
("yann lecun", "lecun"); its weight is counted once per display, not per key.
Weights only grow, so an entry that falls out of a node's top-K can never
need to come back without being re-inserted, which keeps the lists exact.
"""
from __future__ import annotations

import unicodedata


def normalize(s: str) -> str:
    """Lowercase, strip accents, collapse whitespace: 'Schrödinger ' -> 'schrodinger'."""
    s = unicodedata.normalize("NFKD", s)
    s = "".join(ch for ch in s if not unicodedata.combining(ch))
    return " ".join(s.lower().split())


class _Node:
    __slots__ = ("children", "top")

    def __init__(self):
        self.children: dict[str, _Node] = {}
        self.top: list[str] = []  # displays, best first


class Trie:
    def __init__(self, k_max: int = 10):
        self.k_max = k_max
        self.root = _Node()
        self.weight: dict[str, int] = {}  # display -> weight
        self._keys: dict[str, set[str]] = {}  # display -> keys it was inserted under

    def _rank(self, display: str) -> tuple[int, str]:
        return (-self.weight[display], display.lower())

    def _bubble(self, node: _Node, display: str) -> None:
        top = node.top
        if display not in top:
            if len(top) >= self.k_max and self._rank(display) >= self._rank(top[-1]):
                return  # cannot enter: worse than the current K-th
            top.append(display)
        top.sort(key=self._rank)
        del top[self.k_max:]

    def add(self, display: str, keys: list[str] | None = None, weight: int = 1) -> None:
        """Count `display` once more (by `weight`) and make it reachable from `keys`."""
        keys = [normalize(k) for k in (keys or [display])]
        self.weight[display] = self.weight.get(display, 0) + weight
        known = self._keys.setdefault(display, set())
        for key in {k for k in keys if k} | known:  # refresh every path it lives on
            known.add(key)
            node = self.root
            self._bubble(node, display)
            for ch in key:
                node = node.children.setdefault(ch, _Node())
                self._bubble(node, display)

    def top_k(self, prefix: str, k: int = 8) -> list[tuple[str, int]]:
        node = self.root
        for ch in normalize(prefix):
            node = node.children.get(ch)
            if node is None:
                return []
        return [(d, self.weight[d]) for d in node.top[:k]]

    def __len__(self) -> int:
        return len(self.weight)

    def items(self):
        return self.weight.items()
