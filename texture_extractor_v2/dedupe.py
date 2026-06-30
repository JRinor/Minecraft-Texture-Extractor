"""Dédoublonnage thread-safe basé sur un hash SHA-256 du contenu complet
d'une unité (un seul fichier pour un profil simple, plusieurs fichiers
concaténés pour un profil groupe)."""

from __future__ import annotations

import hashlib
import threading

from models import MatchUnit


def compute_unit_hash(unit: MatchUnit) -> str:
    sha256 = hashlib.sha256()
    # Trié par rel_path pour un hash déterministe peu importe l'ordre de
    # lecture des fichiers référencés.
    for found in sorted(unit.files, key=lambda f: f.rel_path):
        sha256.update(found.rel_path.encode("utf-8", errors="ignore"))
        sha256.update(b"\0")
        sha256.update(found.data)
        sha256.update(b"\0")
    return sha256.hexdigest()


class DedupeStore:
    """Un ensemble de hashes déjà vus, par identifiant de profil."""

    def __init__(self):
        self._lock = threading.Lock()
        self._seen: dict[str, set[str]] = {}

    def is_duplicate(self, profile_id: str, content_hash: str) -> bool:
        """Retourne True si déjà vu (et ne l'enregistre pas).
        Sinon l'enregistre et retourne False."""
        with self._lock:
            bucket = self._seen.setdefault(profile_id, set())
            if content_hash in bucket:
                return True
            bucket.add(content_hash)
            return False

    def count(self, profile_id: str) -> int:
        with self._lock:
            return len(self._seen.get(profile_id, set()))
