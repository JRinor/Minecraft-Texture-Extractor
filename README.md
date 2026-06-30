# Minecraft Texture Extractor

Outils pour extraire en masse des items depuis une collection de texture packs Minecraft (épées, overlays de ciel, etc.) et générer un mini resource pack autonome par item trouvé, prêt à être distribué (ex: "pack folder" de 1000+ overlays d'épées pour une vidéo YouTube).

Le repo contient deux scripts :

- `ancienne version/Minecraft-Texture-Extractor.py` — ancienne version, conservée telle quelle, ne pas modifier. Ne traite que les épées en diamant, codée en dur.
- `texture_extractor_v2/` — nouvelle version, à utiliser pour tout nouveau travail. Générique, basée sur des profils JSON, gère beaucoup plus de formats et de cas.

## texture_extractor_v2

### Installation

```
pip install -r texture_extractor_v2/requirements.txt
```

- `Pillow` est obligatoire (génération du `pack.png`).
- `rarfile` est nécessaire pour lire les archives `.rar` — il faut en plus avoir l'utilitaire `unrar` (ou `unar`) installé sur la machine.
- `py7zr` est nécessaire pour lire les archives `.7z`.

Si `rarfile` ou `py7zr` ne sont pas installés, le script continue de fonctionner normalement mais ignore (avec un avertissement) les archives du format correspondant.

### Utilisation

```
python texture_extractor_v2/run.py --source "chemin/vers/tes/packs" --profiles sword sky
```

Arguments principaux :

| Argument | Description |
|---|---|
| `--source` | Dossier contenant les texture packs à scanner (dossiers déjà extraits, `.zip`, `.rar`, `.7z`, y compris imbriqués). |
| `--profiles` | Un ou plusieurs identifiants de profils à extraire (ex: `sword sky bow`). Doivent correspondre à des fichiers `profiles/<id>.json`. |
| `--profiles-dir` | Dossier contenant les profils JSON (défaut : `profiles/` à la racine du repo). |
| `--dest-root` | Dossier racine où créer un sous-dossier `pack_folder_<id>` par profil (défaut : à côté de `--source`). |
| `--report` | Chemin du rapport CSV (défaut : `<dest-root>/report.csv`). |
| `--workers` | Nombre de threads pour traiter plusieurs packs en parallèle (défaut : 8). |
| `-v` / `--verbose` | Logs détaillés. |
| `--log-file` | Écrit aussi les logs dans un fichier. |

### Ce que ça produit

Pour chaque profil demandé, un dossier `pack_folder_<id>/` est créé contenant un `.zip` par item unique trouvé (ex: `sword_1.zip`, `sword_2.zip`...). Chaque zip est un resource pack autonome :

```
pack.mcmeta
pack.png                          <- icône générée à partir de l'item (64x64)
assets/minecraft/...               <- le(s) fichier(s) de l'item, au chemin d'origine du pack source
```

Un `report.csv` liste, pour chaque item rencontré : le pack source, le statut (`exported` / `duplicate` / `error`), le zip de sortie et le hash de contenu.

### Dédoublonnage

Chaque item est hashé (SHA-256 du contenu binaire complet). Si le même contenu a déjà été exporté pour un profil donné (même venant d'un pack source différent), il est ignoré et compté comme `duplicate` dans le rapport. Le dédoublonnage est indépendant par profil (un doublon de `sword` n'affecte pas `sky`).

### Profils

Un profil décrit un type d'item à extraire. Il y a trois familles :

**`simple`** — un seul fichier cible, identifié par une liste d'alias de noms de fichiers (insensible à la casse/underscores/tirets/espaces). Exemple (`profiles/sword.json`) :

```json
{
  "id": "sword",
  "type": "simple",
  "display_name": "Diamond Sword",
  "output_prefix": "sword",
  "pack_description": "Diamond Sword overlay",
  "candidates": ["diamond_sword.png"],
  "path_hints": ["item"]
}
```

- `candidates` : noms de fichiers acceptés (alias multiples possibles).
- `path_hints` (optionnel) : le chemin du fichier trouvé doit contenir au moins un de ces sous-textes (évite les faux positifs).

**`set`** — un item composé de plusieurs textures liées qui doivent être copiées ensemble pour fonctionner en jeu, toutes situées dans le **même dossier** (ex: un arc = `bow_standby.png` + `bow_pulling_0/1/2.png` pour les états de tir). Exemple (`profiles/bow.json`) :

```json
{
  "id": "bow",
  "type": "set",
  "display_name": "Bow",
  "output_prefix": "bow",
  "pack_description": "Bow overlay (standby + pulling)",
  "candidates": ["bow_standby.png", "bow.png"],
  "companions": ["bow_pulling_0.png", "bow_pulling_1.png", "bow_pulling_2.png"],
  "path_hints": ["item"]
}
```

- `candidates` : le fichier "ancre" qui déclenche le match et sert d'icône (alias multiples possibles, comme pour `simple`).
- `companions` : fichiers compagnons à récupérer **s'ils sont présents** (optionnels : un pack qui n'a que l'ancre produit quand même une unité). Deux formes possibles :
  - un **simple nom de fichier** (ex: `bow_pulling_0.png`) → cherché dans le **même dossier** que l'ancre ;
  - un **chemin/glob relatif à `assets/`** (contenant un `/`, ex: `minecraft/textures/models/armor/diamond_layer_*.png`) → cherché **n'importe où** dans le pack. Utile quand les fichiers liés sont dans un autre dossier (ex: une armure = icônes dans `items/` + couches portées dans `models/armor/`).
- `path_hints` (optionnel) : même rôle que pour `simple`, appliqué à l'ancre.

Comme le dédoublonnage hashe l'ensemble des fichiers de l'unité, deux items `set` ne sont considérés comme doublons que si **toutes** leurs textures sont identiques.

**`group`** — un fichier "ancre" qui référence d'autres fichiers devant être copiés ensemble (ex: les overlays de ciel Optifine/MCPatcher : un `.properties` qui référence une texture via `source=./xxx.png`). Exemple (`profiles/sky.json`) :

```json
{
  "id": "sky",
  "type": "group",
  "display_name": "Sky Overlay",
  "output_prefix": "sky",
  "pack_description": "Sky overlay (Optifine/MCPatcher)",
  "anchor_glob": "minecraft/mcpatcher/sky/world*/*.properties",
  "reference_keys": ["source"]
}
```

- `anchor_glob` : motif glob (relatif à `assets/`) pour trouver le fichier ancre. Chaque fichier ancre trouvé produit un item séparé.
- `reference_keys` : clés à chercher dans le fichier ancre pour trouver les fichiers référencés (matche `source=`, `source0=`, `source1=`...).

Pour ajouter un nouveau type d'item, il suffit d'ajouter un fichier `<id>.json` dans `profiles/` — aucune modification de code n'est nécessaire.

### Profils disponibles

| Profil (`--profiles`) | Type | Contenu |
|---|---|---|
| `sword` | simple | Épée diamant |
| `pickaxe` / `axe` / `shovel` / `hoe` | simple | Outils, tous matériaux (diamant, fer, or, pierre, bois, netherite) |
| `bow` | set | Arc : `bow_standby` + `bow_pulling_0/1/2` |
| `arrow` | simple | Flèche |
| `fishing_rod` | set | Canne à pêche : `uncast` + `cast` |
| `armor_diamond` / `armor_iron` / `armor_gold` / `armor_chainmail` / `armor_leather` | set | Armure par matériau : icônes d'inventaire + couches portées (`models/armor/`) |
| `golden_apple` | set | Pomme dorée (normale + enchantée si présente) |
| `potion` | set | Potions : tous les types de fioles + overlay |
| `obsidian` | simple | Bloc d'obsidienne |
| `ender_pearl` | simple | Perle de l'Ender |
| `gui` | set | HUD : `icons.png` (cœurs/faim/armure/viseur) + `widgets.png` (hotbar) |
| `sky` | group | Overlays de ciel (Optifine/MCPatcher) |

Les noms de fichiers couvrent les conventions 1.8 (`items/`, `gold_`, `wood_`, `apple_golden`) et modernes (`item/`, `golden_`, `wooden_`) via des alias multiples.

### Architecture du code (`texture_extractor_v2/`)

| Fichier | Rôle |
|---|---|
| `models.py` | Dataclasses (`ItemProfile`, `FoundFile`, `MatchUnit`...). |
| `profile_loader.py` | Chargement/validation des profils JSON. |
| `pack_discovery.py` | Détection des packs dans le dossier source (dossiers, zip, rar, 7z, archives imbriquées) derrière une interface unifiée (`PackHandle`). |
| `matcher.py` | Recherche des items dans un pack, pour les profils `simple`, `set` et `group`. |
| `dedupe.py` | Hash et détection de doublons, thread-safe. |
| `packager.py` | Construction du zip de sortie (pack.mcmeta, pack.png, fichiers). |
| `reporter.py` | Rapport CSV. |
| `run.py` | CLI, orchestration, parallélisation. |

Un "pack" est détecté n'importe où dans l'arborescence source (dossier ou archive) dès qu'il contient un dossier `assets/` ou un `pack.mcmeta` — peu importe la profondeur d'imbrication (ex: une archive `.rar` qui contient elle-même plusieurs `.zip`, chacun étant un pack distinct).
