from __future__ import annotations

from dataclasses import dataclass
from datetime import time
from typing import Any


def to_minutes(value: time | str) -> int:
    """Mengonversi objek time atau string 'HH:MM' menjadi total menit sejak 00:00."""
    if isinstance(value, time):
        return value.hour * 60 + value.minute
    cleaned = str(value).strip()
    parts = cleaned.split(":")
    if len(parts) < 2:
        raise ValueError(f"Format waktu tidak valid: {value}")
    hour = int(parts[0])
    minute = int(parts[1])
    if not (0 <= hour <= 23 and 0 <= minute <= 59):
        raise ValueError(f"Jam/menit di luar rentang valid: {value}")
    return hour * 60 + minute


@dataclass(frozen=True)
class IntervalEntry:
    """Entri interval waktu [start, end) dalam satuan menit beserta payload-nya."""

    start: int
    end: int
    payload: Any
    seq: int = 0


@dataclass
class IntervalNode:
    """Node pada Augmented Interval Tree (BST berdasar start dengan max_end)."""

    entry: IntervalEntry
    max_end: int
    left: IntervalNode | None = None
    right: IntervalNode | None = None


class IntervalTree:
    """Interval Tree untuk pencarian irisan rentang jam secara efisien.

    Menggunakan interval half-open [start, end) sehingga jadwal bersebelahan
    seperti 08:00-10:00 dan 10:00-12:00 tidak dianggap bentrok.
    """

    def __init__(self) -> None:
        self._root: IntervalNode | None = None
        self._entries: list[IntervalEntry] = []

    def __len__(self) -> int:
        return len(self._entries)

    def insert(self, start: int, end: int, payload: Any) -> None:
        """Menambahkan interval [start, end) beserta payload ke dalam tree."""
        if start >= end:
            raise ValueError(f"Interval tidak valid: start ({start}) harus < end ({end})")

        entry = IntervalEntry(start=start, end=end, payload=payload, seq=len(self._entries))
        self._entries.append(entry)
        new_node = IntervalNode(entry=entry, max_end=end)

        if self._root is None:
            self._root = new_node
            return

        curr = self._root
        path: list[IntervalNode] = []
        while curr is not None:
            path.append(curr)
            if start < curr.entry.start:
                if curr.left is None:
                    curr.left = new_node
                    break
                curr = curr.left
            else:
                if curr.right is None:
                    curr.right = new_node
                    break
                curr = curr.right

        for ancestor in reversed(path):
            if end > ancestor.max_end:
                ancestor.max_end = end

    def _query_entries(self, start: int, end: int) -> list[IntervalEntry]:
        """Mengembalikan seluruh IntervalEntry yang beririsan dengan [start, end)."""
        if start >= end or self._root is None:
            return []

        matches: list[IntervalEntry] = []
        stack: list[IntervalNode] = [self._root]
        while stack:
            node = stack.pop()
            if node.max_end <= start:
                continue
            if node.right is not None and node.entry.start < end and node.right.max_end > start:
                stack.append(node.right)
            if node.entry.start < end and start < node.entry.end:
                matches.append(node.entry)
            if node.left is not None and node.left.max_end > start:
                stack.append(node.left)
        return matches

    def query_overlaps(self, start: int, end: int) -> list[Any]:
        """Mengembalikan semua payload yang jam-nya bertabrakan dengan [start, end)."""
        entries = self._query_entries(start, end)
        entries.sort(key=lambda e: e.seq)
        return [e.payload for e in entries]

    def find_all_overlapping_pairs(self) -> list[tuple[Any, Any]]:
        """Mencari seluruh pasangan unik interval yang saling bertabrakan."""
        pairs: list[tuple[Any, Any]] = []
        for entry_a in self._entries:
            overlaps = self._query_entries(entry_a.start, entry_a.end)
            overlaps.sort(key=lambda e: e.seq)
            for entry_b in overlaps:
                if entry_b.seq > entry_a.seq:
                    pairs.append((entry_a.payload, entry_b.payload))
        return pairs
