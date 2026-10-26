"""LRU cache: hash map + doubly linked list (LeetCode 146).

The hash map gives O(1) lookup of a node; the linked list keeps nodes in
recency order so moving a node to the front and evicting the tail are O(1).

    head <-> [most recent] <-> ... <-> [least recent] <-> tail
"""
from __future__ import annotations

from typing import Generic, Iterator, TypeVar

K = TypeVar("K")
V = TypeVar("V")


class _Node(Generic[K, V]):
    __slots__ = ("key", "val", "prev", "next")

    def __init__(self, key=None, val=None):
        self.key = key
        self.val = val
        self.prev: _Node | None = None
        self.next: _Node | None = None


class LRUCache(Generic[K, V]):
    def __init__(self, capacity: int):
        if capacity < 1:
            raise ValueError("capacity must be >= 1")
        self.capacity = capacity
        self._map: dict[K, _Node[K, V]] = {}
        self._head: _Node = _Node()  # sentinels remove edge cases
        self._tail: _Node = _Node()
        self._head.next, self._tail.prev = self._tail, self._head
        self.evictions = 0

    # -- list primitives, all O(1)
    def _unlink(self, node: _Node) -> None:
        node.prev.next, node.next.prev = node.next, node.prev

    def _push_front(self, node: _Node) -> None:
        node.prev, node.next = self._head, self._head.next
        self._head.next.prev = node
        self._head.next = node

    # -- public API
    def get(self, key: K) -> V | None:
        node = self._map.get(key)
        if node is None:
            return None
        self._unlink(node)
        self._push_front(node)
        return node.val

    def put(self, key: K, val: V) -> None:
        node = self._map.get(key)
        if node is not None:
            node.val = val
            self._unlink(node)
            self._push_front(node)
            return
        node = _Node(key, val)
        self._map[key] = node
        self._push_front(node)
        if len(self._map) > self.capacity:
            lru = self._tail.prev
            self._unlink(lru)
            del self._map[lru.key]
            self.evictions += 1

    def keys(self) -> Iterator[K]:
        """Most to least recently used."""
        node = self._head.next
        while node is not self._tail:
            yield node.key
            node = node.next

    def __len__(self) -> int:
        return len(self._map)

    def __contains__(self, key: K) -> bool:
        return key in self._map
