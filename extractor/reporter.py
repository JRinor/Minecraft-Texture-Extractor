"""Rapport CSV des résultats d'extraction (un run = un fichier)."""

from __future__ import annotations

import csv
import threading
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class ReportRow:
    profile_id: str
    source_pack: str
    status: str  # "exported" | "duplicate" | "error"
    output_zip: str
    content_hash: str
    detail: str = ""


class Reporter:
    def __init__(self):
        self._lock = threading.Lock()
        self._rows: list[ReportRow] = []

    def add(self, row: ReportRow) -> None:
        with self._lock:
            self._rows.append(row)

    def summary(self) -> dict[str, dict[str, int]]:
        out: dict[str, dict[str, int]] = {}
        with self._lock:
            for row in self._rows:
                bucket = out.setdefault(row.profile_id, {"exported": 0, "duplicate": 0, "error": 0})
                bucket[row.status] = bucket.get(row.status, 0) + 1
        return out

    def write_csv(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with self._lock:
            rows = list(self._rows)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=["profile_id", "source_pack", "status", "output_zip", "content_hash", "detail"])
            writer.writeheader()
            for row in rows:
                writer.writerow(asdict(row))
