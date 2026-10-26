"""Top-k with a size-k min-heap (LeetCode 347). O(n log k) instead of O(n log n).

The heap's root is the weakest of the current best k, so each new item is
compared against it once and replaces it only if stronger.
"""
from __future__ import annotations

import heapq
from typing import Hashable, Mapping


def top_k(counts: Mapping[Hashable, int], k: int) -> list[tuple[Hashable, int]]:
    if k <= 0:
        return []
    heap: list[tuple[int, str, Hashable]] = []  # (count, tiebreak, key)
    for key, c in counts.items():
        # Tiebreak inverted so equal counts prefer alphabetically smaller keys.
        entry = (c, _neg(str(key)), key)
        if len(heap) < k:
            heapq.heappush(heap, entry)
        elif entry > heap[0]:
            heapq.heapreplace(heap, entry)
    return [(key, c) for c, _, key in sorted(heap, reverse=True)]


def _neg(s: str) -> tuple[int, ...]:
    return tuple(-ord(ch) for ch in s) + (0,)
