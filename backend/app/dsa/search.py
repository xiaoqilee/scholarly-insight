"""Binary search over results sorted newest-first (LeetCode 35 variant).

Alerts and "what's new" ask: how many papers in this category were submitted
after my last visit? A browse window sorted by submittedDate descending
already holds the answer; binary search finds the cutoff in O(log n)
with zero extra arXiv calls.
"""
from __future__ import annotations

from typing import Sequence


def first_not_newer(desc: Sequence[float], since: float) -> int:
    """Index of the first value <= since in a descending sequence.

    Equivalently, the number of values strictly newer than `since`.
    Invariant: everything left of lo is > since; everything at or right of hi is <= since.
    """
    lo, hi = 0, len(desc)
    while lo < hi:
        mid = (lo + hi) // 2
        if desc[mid] > since:
            lo = mid + 1
        else:
            hi = mid
    return lo
