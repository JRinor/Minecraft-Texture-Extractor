"""Découverte des "packs" dans le dossier source et abstraction d'accès aux
fichiers, quel que soit le conteneur (dossier déjà extrait, zip, rar, 7z,
ou archive imbriquée dans une autre archive).

Un "pack" est défini comme une unité qui contient elle-même un resource pack
Minecraft valide (présence d'un dossier "assets/" ou d'un "pack.mcmeta"),
quel que soit le niveau d'imbrication où on le trouve. Un dossier ou une
archive qui ne contient que d'autres dossiers/archives (un simple
"conteneur") n'est pas un pack en lui-même : on continue de creuser dedans.
"""

from __future__ import annotations

import logging
import os
import tempfile
import zipfile
from abc import ABC, abstractmethod
from contextlib import ExitStack
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Iterator, Optional

logger = logging.getLogger(__name__)

ARCHIVE_EXTENSIONS = (".zip", ".rar", ".7z")

try:
    import rarfile

    HAS_RARFILE = True
except ImportError:
    HAS_RARFILE = False

try:
    import py7zr

    HAS_PY7ZR = True
except ImportError:
    HAS_PY7ZR = False


def _norm(path: str) -> str:
    return path.replace("\\", "/")


def find_assets_relpath(raw_path: str) -> Optional[str]:
    """Retourne le chemin à partir de (et incluant) "assets/", peu importe
    le préfixe (dossier d'emballage, casse, etc.). None si absent.
    """
    norm = _norm(raw_path)
    lower = norm.lower()
    idx = lower.find("assets/")
    if idx == -1:
        if lower == "assets" or lower.endswith("/assets"):
            return None
        return None
    return norm[idx:]


def has_pack_markers(names: list[str]) -> bool:
    for name in names:
        norm = _norm(name).lower()
        if norm.startswith("assets/") or "/assets/" in norm:
            return True
        if norm == "pack.mcmeta" or norm.endswith("/pack.mcmeta"):
            return True
    return False


def is_archive(path: str) -> bool:
    return path.lower().endswith(ARCHIVE_EXTENSIONS)


@dataclass
class RawEntry:
    """Une entrée brute dans un conteneur (nom complet, pas forcément un
    fichier 'assets/...')."""

    raw_path: str
    is_dir: bool


class ArchiveBackend(ABC):
    """Interface uniforme pour lire le contenu d'un conteneur de fichiers."""

    @abstractmethod
    def list_entries(self) -> list[RawEntry]:
        ...

    @abstractmethod
    def read(self, raw_path: str) -> bytes:
        ...

    def close(self) -> None:
        pass


class DirBackend(ArchiveBackend):
    def __init__(self, root: Path):
        self.root = root

    def list_entries(self) -> list[RawEntry]:
        entries = []
        for dirpath, _, filenames in os.walk(self.root):
            for filename in filenames:
                full = Path(dirpath) / filename
                rel = full.relative_to(self.root).as_posix()
                entries.append(RawEntry(raw_path=rel, is_dir=False))
        return entries

    def read(self, raw_path: str) -> bytes:
        return (self.root / raw_path).read_bytes()


class ZipBackend(ArchiveBackend):
    def __init__(self, file_path: Path):
        self._zf = zipfile.ZipFile(file_path, "r")

    def list_entries(self) -> list[RawEntry]:
        return [
            RawEntry(raw_path=info.filename, is_dir=info.is_dir())
            for info in self._zf.infolist()
        ]

    def read(self, raw_path: str) -> bytes:
        return self._zf.read(raw_path)

    def close(self) -> None:
        self._zf.close()


class RarBackend(ArchiveBackend):
    def __init__(self, file_path: Path):
        if not HAS_RARFILE:
            raise RuntimeError(
                "Le module 'rarfile' n'est pas installé (pip install rarfile)."
            )
        self._rf = rarfile.RarFile(file_path, "r")

    def list_entries(self) -> list[RawEntry]:
        return [
            RawEntry(raw_path=info.filename, is_dir=info.is_dir())
            for info in self._rf.infolist()
        ]

    def read(self, raw_path: str) -> bytes:
        with self._rf.open(raw_path) as f:
            return f.read()

    def close(self) -> None:
        self._rf.close()


class SevenZBackend(ArchiveBackend):
    def __init__(self, file_path: Path):
        if not HAS_PY7ZR:
            raise RuntimeError(
                "Le module 'py7zr' n'est pas installé (pip install py7zr)."
            )
        self._path = file_path
        with py7zr.SevenZipFile(file_path, "r") as archive:
            self._names = [n for n in archive.getnames()]

    def list_entries(self) -> list[RawEntry]:
        return [RawEntry(raw_path=n, is_dir=n.endswith("/")) for n in self._names]

    def read(self, raw_path: str) -> bytes:
        with py7zr.SevenZipFile(self._path, "r") as archive:
            extracted = archive.read([raw_path])
            return extracted[raw_path].read()


def open_backend(path: Path) -> ArchiveBackend:
    suffix = path.suffix.lower()
    if suffix == ".zip":
        return ZipBackend(path)
    if suffix == ".rar":
        return RarBackend(path)
    if suffix == ".7z":
        return SevenZBackend(path)
    raise ValueError(f"Format d'archive non supporté : {path}")


class PackHandle:
    """Vue unifiée d'un pack : accès aux fichiers par chemin relatif à
    "assets/" (le chemin retourné inclut le préfixe "assets/")."""

    def __init__(self, label: str, backend: ArchiveBackend, assets_files: dict[str, str]):
        self.label = label
        self._backend = backend
        # rel_path ("assets/minecraft/...") -> raw_path dans le backend
        self._assets_files = assets_files

    def list_rel_paths(self) -> list[str]:
        return list(self._assets_files.keys())

    def read(self, rel_path: str) -> bytes:
        raw_path = self._assets_files[rel_path]
        return self._backend.read(raw_path)

    def close(self) -> None:
        self._backend.close()

    def __enter__(self) -> "PackHandle":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        self.close()


def _build_pack_handle(label: str, backend: ArchiveBackend) -> PackHandle:
    entries = [e for e in backend.list_entries() if not e.is_dir]
    assets_files: dict[str, str] = {}
    for entry in entries:
        rel = find_assets_relpath(entry.raw_path)
        if rel is not None:
            assets_files[rel] = entry.raw_path
    return PackHandle(label=label, backend=backend, assets_files=assets_files)


def discover_packs(root: Path) -> Iterator[PackHandle]:
    """Parcourt récursivement `root` (dossier) et produit un PackHandle par
    pack trouvé, y compris dans des archives imbriquées.

    Le caller doit consommer/fermer chaque PackHandle avant de demander le
    suivant (boucle `for pack in discover_packs(...): ...`) : les archives
    imbriquées sont extraites dans des dossiers temporaires qui sont nettoyés
    juste après que tous leurs packs internes ont été traités.
    """
    yield from _walk_dir(root)


def _walk_dir(directory: Path) -> Iterator[PackHandle]:
    try:
        children = sorted(directory.iterdir())
    except OSError as exc:
        logger.error("Impossible de lire le dossier %s : %s", directory, exc)
        return

    for child in children:
        yield from discover_packs_for_entry(child)


def discover_packs_for_entry(entry: Path) -> Iterator[PackHandle]:
    """Découvre les packs contenus dans une seule entrée (fichier ou
    dossier). Permet de répartir le traitement de plusieurs entrées
    top-level sur plusieurs threads en toute indépendance."""
    if entry.is_dir():
        backend = DirBackend(entry)
        names = [e.raw_path for e in backend.list_entries()]
        if has_pack_markers(names):
            yield _build_pack_handle(label=str(entry), backend=backend)
        else:
            backend.close()
            yield from _walk_dir(entry)
    elif entry.is_file() and is_archive(entry.name):
        yield from _walk_archive_file(entry)


def _walk_archive_file(archive_path: Path) -> Iterator[PackHandle]:
    try:
        backend = open_backend(archive_path)
    except Exception as exc:
        logger.warning("Archive illisible/ignorée %s : %s", archive_path, exc)
        return

    try:
        entries = backend.list_entries()
    except Exception as exc:
        logger.warning("Archive illisible/ignorée %s : %s", archive_path, exc)
        backend.close()
        return

    names = [e.raw_path for e in entries if not e.is_dir]

    if has_pack_markers(names):
        yield _build_pack_handle(label=str(archive_path), backend=backend)
    else:
        backend.close()

    # Archives imbriquées : on les extrait dans un dossier temporaire et on
    # recurse, indépendamment du fait que l'archive externe soit elle-même
    # un pack ou un simple conteneur.
    nested = [e.raw_path for e in entries if not e.is_dir and is_archive(e.raw_path)]
    if not nested:
        return

    # Si l'archive externe était un pack, le backend a déjà été consommé via
    # _build_pack_handle (qui ne ferme pas le backend tout de suite : c'est
    # le PackHandle retourné qui le fermera). On rouvre un backend frais pour
    # lire les entrées imbriquées en toute sécurité.
    try:
        reread_backend = open_backend(archive_path)
    except Exception as exc:
        logger.warning("Impossible de relire %s pour les archives imbriquées : %s", archive_path, exc)
        return

    try:
        for nested_raw_path in nested:
            with tempfile.TemporaryDirectory(prefix="tex_extract_nested_") as tmp:
                suffix = PurePosixPath(nested_raw_path).suffix
                tmp_path = Path(tmp) / f"nested{suffix}"
                try:
                    data = reread_backend.read(nested_raw_path)
                except Exception as exc:
                    logger.warning(
                        "Lecture impossible de l'archive imbriquée %s dans %s : %s",
                        nested_raw_path, archive_path, exc,
                    )
                    continue
                tmp_path.write_bytes(data)
                yield from _walk_archive_file(tmp_path)
    finally:
        reread_backend.close()
