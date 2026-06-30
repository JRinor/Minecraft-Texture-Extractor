"""Moteur de matching : trouve les items d'un profil donné dans un pack.

Deux stratégies :
- match_simple : un seul fichier cible, comparé par nom normalisé (alias).
- match_group  : un fichier ancre (ex: sky*.properties) qui référence
  d'autres fichiers (ex: source=./starfield.png) ; tout le groupe est
  retourné comme une seule unité.
"""

from __future__ import annotations

import fnmatch
import logging
import posixpath
import re
from typing import Optional

from models import FoundFile, ItemProfile, MatchUnit, normalize_name
from pack_discovery import PackHandle

logger = logging.getLogger(__name__)

ASSETS_PREFIX = "assets/"


def match_simple(profile: ItemProfile, pack: PackHandle) -> list[MatchUnit]:
    units: list[MatchUnit] = []
    candidate_names = {c.normalized() for c in profile.candidates}
    hints = tuple(h.lower() for h in profile.path_hints)

    for rel_path in pack.list_rel_paths():
        basename = rel_path.rsplit("/", 1)[-1]
        if normalize_name(basename) not in candidate_names:
            continue
        if hints and not any(h in rel_path.lower() for h in hints):
            continue

        try:
            data = pack.read(rel_path)
        except Exception as exc:
            logger.warning("Lecture impossible de %s dans %s : %s", rel_path, pack.label, exc)
            continue

        found = FoundFile(rel_path=rel_path, data=data)
        units.append(
            MatchUnit(
                profile=profile,
                source_pack_label=pack.label,
                files=[found],
                icon_file=found,
            )
        )

    return units


def match_set(profile: ItemProfile, pack: PackHandle) -> list[MatchUnit]:
    """Profil 'set' : un fichier ancre (un des `candidates`) plus ses fichiers
    compagnons. Les compagnons sont optionnels (un pack qui n'a que l'ancre
    produit quand même une unité).

    Un compagnon peut être :
    - un simple nom de fichier (ex: "bow_pulling_0.png") : cherché dans le
      MÊME dossier que l'ancre.
    - un chemin/glob relatif à "assets/" (contenant un "/", ex:
      "minecraft/textures/models/armor/diamond_layer_1.png") : cherché
      n'importe où dans le pack. Utile quand les fichiers liés sont dans un
      autre dossier (ex: armure = icônes dans items/ + couches dans
      models/armor/)."""
    units: list[MatchUnit] = []
    candidate_names = {c.normalized() for c in profile.candidates}
    hints = tuple(h.lower() for h in profile.path_hints)

    # Sépare les compagnons "même dossier" (nom simple) des compagnons
    # "ailleurs dans le pack" (chemin/glob contenant un "/").
    same_dir_companions = {c.normalized() for c in profile.companions if "/" not in c.filename}
    glob_companions = [c.filename for c in profile.companions if "/" in c.filename]

    rel_paths = pack.list_rel_paths()

    # Index dossier -> {nom_de_fichier_normalisé: rel_path}, pour retrouver
    # rapidement les compagnons situés dans le même dossier que l'ancre.
    dir_index: dict[str, dict[str, str]] = {}
    for p in rel_paths:
        directory, _, basename = p.rpartition("/")
        dir_index.setdefault(directory, {})[normalize_name(basename)] = p

    # Résout une fois pour toutes les compagnons par chemin/glob (communs à
    # toutes les ancres du pack).
    glob_companion_paths: list[str] = []
    for pattern in glob_companions:
        full = (ASSETS_PREFIX + pattern).lower()
        for p in rel_paths:
            if fnmatch.fnmatch(p.lower(), full) and p not in glob_companion_paths:
                glob_companion_paths.append(p)

    for rel_path in rel_paths:
        basename = rel_path.rsplit("/", 1)[-1]
        if normalize_name(basename) not in candidate_names:
            continue
        if hints and not any(h in rel_path.lower() for h in hints):
            continue

        directory = rel_path.rpartition("/")[0]
        companion_paths = [
            dir_index[directory][cn]
            for cn in same_dir_companions
            if cn in dir_index[directory] and dir_index[directory][cn] != rel_path
        ]
        companion_paths.extend(p for p in glob_companion_paths if p != rel_path)

        try:
            anchor_found = FoundFile(rel_path=rel_path, data=pack.read(rel_path))
            companion_found = [
                FoundFile(rel_path=p, data=pack.read(p)) for p in sorted(set(companion_paths))
            ]
        except Exception as exc:
            logger.warning("Lecture impossible du set de %s dans %s : %s", rel_path, pack.label, exc)
            continue

        units.append(
            MatchUnit(
                profile=profile,
                source_pack_label=pack.label,
                files=[anchor_found, *companion_found],
                icon_file=anchor_found,
            )
        )

    return units


_REFERENCE_LINE_RE_CACHE: dict[str, re.Pattern] = {}


def _reference_line_re(key: str) -> re.Pattern:
    if key not in _REFERENCE_LINE_RE_CACHE:
        _REFERENCE_LINE_RE_CACHE[key] = re.compile(
            rf"^\s*{re.escape(key)}\d*\s*=\s*(.+?)\s*$",
            re.IGNORECASE | re.MULTILINE,
        )
    return _REFERENCE_LINE_RE_CACHE[key]


def _strip_inline_comment(value: str) -> str:
    # Les .properties mcpatcher n'ont normalement pas de commentaire en fin
    # de ligne sur les valeurs, mais on retire un éventuel "#..." de sécurité.
    if "#" in value:
        value = value.split("#", 1)[0]
    return value.strip()


def _resolve_reference(anchor_rel_path: str, raw_value: str) -> str:
    anchor_dir = posixpath.dirname(anchor_rel_path)
    joined = posixpath.normpath(posixpath.join(anchor_dir, raw_value))
    return joined.replace("\\", "/")


def match_group(profile: ItemProfile, pack: PackHandle) -> list[MatchUnit]:
    if not profile.anchor_glob:
        return []

    units: list[MatchUnit] = []
    anchor_glob_full = ASSETS_PREFIX + profile.anchor_glob

    rel_paths = pack.list_rel_paths()
    lower_lookup = {p.lower(): p for p in rel_paths}

    anchors = [p for p in rel_paths if fnmatch.fnmatch(p.lower(), anchor_glob_full.lower())]

    for anchor_rel_path in sorted(anchors):
        try:
            raw_bytes = pack.read(anchor_rel_path)
        except Exception as exc:
            logger.warning("Lecture impossible de %s dans %s : %s", anchor_rel_path, pack.label, exc)
            continue

        text = raw_bytes.decode("utf-8", errors="ignore")

        referenced_rel_paths: list[str] = []
        broken_reference = False
        for key in profile.reference_keys:
            for match in _reference_line_re(key).finditer(text):
                raw_value = _strip_inline_comment(match.group(1))
                if not raw_value:
                    continue
                resolved = _resolve_reference(anchor_rel_path, raw_value)
                actual = lower_lookup.get(resolved.lower())
                if actual is None:
                    logger.warning(
                        "%s : '%s' référence '%s' (%s) introuvable, item ignoré",
                        pack.label, anchor_rel_path, raw_value, resolved,
                    )
                    broken_reference = True
                    continue
                if actual not in referenced_rel_paths:
                    referenced_rel_paths.append(actual)

        if broken_reference or not referenced_rel_paths:
            continue

        try:
            anchor_found = FoundFile(rel_path=anchor_rel_path, data=raw_bytes)
            referenced_found = [
                FoundFile(rel_path=p, data=pack.read(p)) for p in referenced_rel_paths
            ]
        except Exception as exc:
            logger.warning("Lecture impossible des fichiers référencés par %s : %s", anchor_rel_path, exc)
            continue

        units.append(
            MatchUnit(
                profile=profile,
                source_pack_label=pack.label,
                files=[anchor_found, *referenced_found],
                icon_file=referenced_found[0],
            )
        )

    return units


def _attach_sidecar_mcmeta(units: list[MatchUnit], pack: PackHandle) -> None:
    """Ajoute, pour chaque fichier d'une unité, son fichier ``.mcmeta`` voisin
    s'il existe (ex: ``potion_overlay.png`` -> ``potion_overlay.png.mcmeta``).
    Indispensable aux textures animées : sans leur ``.mcmeta``, l'animation
    est perdue en jeu."""
    if not units:
        return
    lookup = {p.lower(): p for p in pack.list_rel_paths()}
    for unit in units:
        existing = {f.rel_path for f in unit.files}
        extra: list[FoundFile] = []
        for found in list(unit.files):
            if found.rel_path.lower().endswith(".mcmeta"):
                continue
            actual = lookup.get((found.rel_path + ".mcmeta").lower())
            if actual and actual not in existing:
                try:
                    extra.append(FoundFile(rel_path=actual, data=pack.read(actual)))
                    existing.add(actual)
                except Exception as exc:
                    logger.warning("Lecture impossible de %s dans %s : %s", actual, pack.label, exc)
        unit.files.extend(extra)


def find_matches(profile: ItemProfile, pack: PackHandle) -> list[MatchUnit]:
    if profile.is_simple():
        units = match_simple(profile, pack)
    elif profile.is_set():
        units = match_set(profile, pack)
    elif profile.is_group():
        units = match_group(profile, pack)
    else:
        raise ValueError(f"Type de profil inconnu : {profile.type}")

    _attach_sidecar_mcmeta(units, pack)
    return units
