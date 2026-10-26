"""Banded edit distance for "did you mean" (LeetCode 72, preview of DP week).

dp[i][j] = edits to turn a[:i] into b[:j], with insert, delete, substitute,
and swap of two adjacent letters (the most common typo: "lecnu" -> "lecun").
That last case is the optimal-string-alignment extension of LeetCode 72.

We only care whether the distance is <= max_d, so we fill just the diagonal
band |i - j| <= max_d and stop as soon as a whole row exceeds max_d:
O(len * max_d) time and O(len) space (three rolling rows).
"""
from __future__ import annotations


def within_distance(a: str, b: str, max_d: int) -> int | None:
    """Edit distance (with adjacent swaps) if it is <= max_d, else None."""
    if abs(len(a) - len(b)) > max_d:
        return None
    big = max_d + 1
    prev2: list[int] | None = None
    prev = [j if j <= max_d else big for j in range(len(b) + 1)]
    for i in range(1, len(a) + 1):
        cur = [big] * (len(b) + 1)
        if i <= max_d:
            cur[0] = i
        lo, hi = max(1, i - max_d), min(len(b), i + max_d)
        for j in range(lo, hi + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            best = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if prev2 is not None and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                best = min(best, prev2[j - 2] + 1)  # swap of two adjacent letters
            cur[j] = min(best, big)
        if min(cur) > max_d:
            return None
        prev2, prev = prev, cur
    return prev[-1] if prev[-1] <= max_d else None
