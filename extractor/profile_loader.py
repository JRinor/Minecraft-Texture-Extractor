"""Chargement et validation des profils JSON depuis le dossier profiles/."""

from __future__ import annotations

import json
import logging
from pathlib import Path

from .models import Candidate, ItemProfile, ProfileType

logger = logging.getLogger(__name__)


class ProfileError(Exception):
    pass


def load_profile_file(path: Path) -> ItemProfile:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ProfileError(f"JSON invalide dans {path}: {exc}") from exc

    try:
        profile_id = data["id"]
        ptype = ProfileType(data["type"])
        display_name = data.get("display_name", profile_id)
        output_prefix = data.get("output_prefix", profile_id)
        pack_description = data.get("pack_description", display_name)
    except KeyError as exc:
        raise ProfileError(f"Champ manquant dans {path}: {exc}") from exc
    except ValueError as exc:
        raise ProfileError(f"'type' invalide dans {path}: {exc}") from exc

    candidates = tuple(
        Candidate(filename=c) for c in data.get("candidates", [])
    )
    companions = tuple(
        Candidate(filename=c) for c in data.get("companions", [])
    )
    path_hints = tuple(data.get("path_hints", []))
    anchor_glob = data.get("anchor_glob")
    reference_keys = tuple(data.get("reference_keys", []))

    profile = ItemProfile(
        id=profile_id,
        type=ptype,
        display_name=display_name,
        candidates=candidates,
        companions=companions,
        path_hints=path_hints,
        anchor_glob=anchor_glob,
        reference_keys=reference_keys,
        output_prefix=output_prefix,
        pack_description=pack_description,
    )

    if profile.is_simple() and not profile.candidates:
        raise ProfileError(
            f"Profil 'simple' {profile_id} sans 'candidates' dans {path}"
        )
    if profile.is_set() and not profile.candidates:
        raise ProfileError(
            f"Profil 'set' {profile_id} sans 'candidates' (fichier ancre) dans {path}"
        )
    if profile.is_group() and not profile.anchor_glob:
        raise ProfileError(
            f"Profil 'group' {profile_id} sans 'anchor_glob' dans {path}"
        )
    if profile.is_group() and not profile.reference_keys:
        raise ProfileError(
            f"Profil 'group' {profile_id} sans 'reference_keys' dans {path}"
        )

    return profile


def load_profiles(profiles_dir: Path, wanted_ids: list[str] | None = None) -> dict[str, ItemProfile]:
    """Charge tous les profils *.json d'un dossier.

    Si `wanted_ids` est fourni, seuls ces profils sont chargés/retournés
    (erreur si l'un d'eux est introuvable).
    """
    if not profiles_dir.is_dir():
        raise ProfileError(f"Dossier de profils introuvable : {profiles_dir}")

    profiles: dict[str, ItemProfile] = {}
    for json_file in sorted(profiles_dir.glob("*.json")):
        if json_file.name.startswith("_"):
            continue  # fichiers utilitaires (ex: _schema.json), pas des profils
        profile = load_profile_file(json_file)
        if profile.id in profiles:
            raise ProfileError(f"Profil dupliqué : {profile.id} ({json_file})")
        profiles[profile.id] = profile
        logger.debug("Profil chargé : %s (%s)", profile.id, profile.type.value)

    if wanted_ids:
        missing = [pid for pid in wanted_ids if pid not in profiles]
        if missing:
            raise ProfileError(
                f"Profil(s) introuvable(s) dans {profiles_dir} : {', '.join(missing)} "
                f"(disponibles : {', '.join(sorted(profiles)) or 'aucun'})"
            )
        profiles = {pid: profiles[pid] for pid in wanted_ids}

    return profiles
