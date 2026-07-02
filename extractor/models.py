"""
Modèles de données pour le Texture Pack Extractor V2.

Un "profil" décrit un type d'item à extraire (ex: diamond_sword, sky overlay...).
Il existe deux familles de profils :

- "simple"  : un seul fichier cible, identifié par une liste d'alias de noms
              de fichiers (ex: diamond_sword.png).
- "group"   : un fichier "ancre" (souvent un .properties Optifine/MCPatcher)
              qui référence un ou plusieurs fichiers liés (ex: sky*.properties
              -> source=./starfield.png). Tout le groupe doit être copié
              ensemble pour que l'overlay fonctionne.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import PurePosixPath
from typing import Optional


class ProfileType(str, Enum):
    SIMPLE = "simple"
    GROUP = "group"
    SET = "set"


@dataclass(frozen=True)
class Candidate:
    """Un alias possible de nom de fichier pour un profil 'simple'."""

    # Nom de fichier (sans dossier), ex: "diamond_sword.png"
    filename: str

    def normalized(self) -> str:
        return normalize_name(self.filename)


@dataclass(frozen=True)
class ItemProfile:
    """Définition d'un type d'item à extraire (chargée depuis un JSON)."""

    id: str
    type: ProfileType
    display_name: str

    # --- Profils "simple" ---
    candidates: tuple[Candidate, ...] = field(default_factory=tuple)
    # Si non vide, le chemin du fichier candidat doit contenir au moins un de
    # ces sous-textes (insensible à la casse). Utile pour éviter les faux
    # positifs (ex: ne matcher "clock.png" que sous .../textures/item(s)/).
    path_hints: tuple[str, ...] = field(default_factory=tuple)

    # --- Profils "group" ---
    # Motif glob (relatif à la racine "assets/") pour trouver le fichier
    # ancre, ex: "minecraft/mcpatcher/sky/world*/*.properties"
    anchor_glob: Optional[str] = None
    # Clés à chercher dans le fichier ancre pour trouver les fichiers
    # référencés, ex: ["source"] matche "source=", "source0=", "source1=".
    reference_keys: tuple[str, ...] = field(default_factory=tuple)

    # --- Profils "set" ---
    # Fichiers "compagnons" à récupérer dans le MÊME dossier que le fichier
    # ancre (un des `candidates`), s'ils sont présents. Ex: pour un arc,
    # ancre = bow_standby.png, compagnons = bow_pulling_0/1/2.png.
    # Les compagnons sont optionnels : un pack qui n'en a aucun produit
    # quand même une unité avec juste l'ancre.
    companions: tuple[Candidate, ...] = field(default_factory=tuple)

    # --- Sortie ---
    # Préfixe utilisé pour nommer les zips de sortie, ex: "sword", "sky".
    output_prefix: str = ""
    # Description utilisée dans le pack.mcmeta généré.
    pack_description: str = ""

    def is_simple(self) -> bool:
        return self.type == ProfileType.SIMPLE

    def is_group(self) -> bool:
        return self.type == ProfileType.GROUP

    def is_set(self) -> bool:
        return self.type == ProfileType.SET


@dataclass
class FoundFile:
    """Un fichier localisé à l'intérieur d'un pack source."""

    # Chemin relatif à la racine "assets/" du pack (ex: "minecraft/textures/items/diamond_sword.png")
    rel_path: str
    data: bytes

    @property
    def basename(self) -> str:
        return PurePosixPath(self.rel_path).name


@dataclass
class MatchUnit:
    """Un item complet trouvé dans un pack source, prêt à être packagé.

    Pour un profil 'simple', `files` contient un seul FoundFile.
    Pour un profil 'group', `files` contient le fichier ancre + les fichiers
    référencés.
    """

    profile: ItemProfile
    source_pack_label: str
    files: list[FoundFile]
    # Fichier à utiliser comme base du pack.png (icône).
    icon_file: FoundFile
    # --- Métadonnées du pack source (renseignées par l'orchestrateur) ---
    # pack_format lu dans le pack.mcmeta du pack source (None si introuvable).
    pack_format: Optional[int] = None
    # pack.png d'origine du pack source (bytes), si on veut le conserver.
    source_icon_data: Optional[bytes] = None
    # Description d'origine lue dans le pack.mcmeta du pack source.
    source_description: Optional[str] = None


def normalize_name(name: str) -> str:
    """Normalise un nom de fichier pour comparaison souple entre packs.

    Insensible à la casse, aux underscores/tirets/espaces. Ex:
    "Diamond_Sword.PNG" -> "diamondsword.png"
    """
    base = name.strip().lower()
    for ch in ("_", "-", " "):
        base = base.replace(ch, "")
    return base
