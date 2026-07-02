# Minecraft Texture Extractor

Outil pour extraire en masse des items depuis une collection de texture packs Minecraft (épées, arcs, armures, overlays de ciel, etc.) et générer un mini resource pack autonome par item trouvé, prêt à être distribué (ex: "pack folder" de 1000+ overlays d'épées pour une vidéo YouTube).

## 🚀 Quick start

**Le plus simple (sans rien installer)** : télécharge `MinecraftTextureExtractor.exe` depuis la page [Releases](https://github.com/JRinor/Minecraft-Texture-Extractor/releases), double-clique, choisis ton dossier de packs, coche les items, clique **Extraire**.

**Avec Python** :

```
pip install -r requirements-gui.txt
python gui.py
```

Ou en ligne de commande :

```
pip install -r requirements.txt
python -m extractor.run --source "chemin/vers/tes/packs" --profiles sword bow
```

## Organisation du dépôt

| Élément | Rôle |
|---|---|
| `gui.py` | Interface graphique (lance le moteur, éditeur de profils). |
| `extractor/` | Le moteur (package Python). Point d'entrée : `python -m extractor.run`. |
| `profiles/` | Profils JSON décrivant les items extractibles (+ `_schema.json`). |
| `scripts/` | `lancer_gui.bat` (lancer la GUI), `build_exe.bat` (générer l'.exe). |
| `tests/` | Tests unitaires (`pytest`). |
| `legacy/` | Ancienne version mono-fichier (épée diamant codée en dur), conservée telle quelle. |

## Moteur (`extractor/`)

### Installation

```
pip install -r requirements.txt
```

- `Pillow` est obligatoire (génération du `pack.png`).
- `rarfile` est nécessaire pour lire les archives `.rar` — il faut en plus avoir l'utilitaire `unrar` (ou `unar`) installé sur la machine.
- `py7zr` est nécessaire pour lire les archives `.7z`.

Si `rarfile` ou `py7zr` ne sont pas installés, le script continue de fonctionner normalement mais ignore (avec un avertissement) les archives du format correspondant.

### Interface graphique (le plus simple)

Pour ne pas taper de commandes, lance l'application :

```
python gui.py
```

(ou double-clic sur **`scripts/lancer_gui.bat`** sous Windows)

L'interface est organisée en **3 étapes** : 1) dossier des packs, 2) items à cocher (rangés par catégorie, noms en français), 3) bouton **Extraire**. Elle propose notamment :

- **glisser-déposer** d'un dossier sur le champ source, **compteur d'éléments** détectés en direct, bouton pour ouvrir le dossier source ;
- des **presets** en un clic (`Items PvP`, `Outils`, `Armures`) et tout cocher / décocher ;
- un bouton **🔎 Analyser** : compte les packs et les items présents **sans rien créer** ;
- des **combos** (plusieurs items réunis dans un seul pack), plusieurs possibles ;
- des options claires : planche-contact, garder l'icône/nom d'origine, **vider le dossier avant**, **ouvrir le dossier à la fin**, mode test (dry-run), vitesse ;
- **progression** (barre + nom du pack en cours) et **récapitulatif** (créés / doublons / erreurs par item) ;
- ouverture du dossier de sortie, du **rapport CSV**, ou **aperçu des icônes** (planche-contact) ;
- **raccourcis** : `Ctrl+Entrée` pour lancer, `Échap` pour arrêter ;
- vérification au démarrage : si **Pillow** manque, l'app propose de l'installer.

L'onglet **Profils (avancé)** permet de créer / modifier / supprimer des profils, soit via un **formulaire guidé**, soit en éditant le JSON. Les réglages (y compris la taille de fenêtre) sont **mémorisés** entre deux lancements (`gui_config.json`).

Dépendances : Tkinter est inclus avec Python ; Pillow est déjà requis par l'extracteur. Le **glisser-déposer** utilise `tkinterdnd2` (optionnel — sans lui, tout fonctionne sauf le drag & drop) :

```
pip install tkinterdnd2
```

### Exécutable autonome (.exe, sans Python)

Pour lancer/partager l'app **sans installer Python ni taper de commande**, génère un exécutable :

```
pip install -r requirements-dev.txt
scripts\build_exe.bat
```

L'exécutable est créé dans `dist\MinecraftTextureExtractor.exe` (double-clic pour lancer). Les profils sont copiés à côté de l'exe au premier lancement et restent **modifiables** (onglet Profils).

### Utilisation en ligne de commande

```
python -m extractor.run --source "chemin/vers/tes/packs" --profiles sword sky
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
| `--combo` | **Combo** : fusionne plusieurs profils en un seul pack. Format `nom=profil1,profil2`. Répétable (plusieurs combos). |
| `--combo-require-all` | Pour les combos : ne produit un pack que si TOUS les profils du combo sont présents dans le pack source. |
| `--dry-run` | Aperçu : compte ce qui serait extrait sans rien écrire sur le disque. |
| `--keep-original` | Conserve le `pack.png` et la description d'origine du pack source au lieu de les générer. |
| `--contact-sheet` | Génère une planche-contact (`contact_sheet.png`) des icônes dans chaque dossier de sortie. |

### Combos (plusieurs items dans un seul pack)

Par défaut, chaque profil produit son propre dossier (`pack_folder_sword/`, `pack_folder_bow/`…) avec un zip par item. Un **combo** réunit au contraire plusieurs items dans un **seul** resource pack par pack source — par exemple l'épée *et* l'arc d'un même pack ensemble. On peut définir **plusieurs combos** en un seul lancement, et les combiner avec des profils séparés :

```
python -m extractor.run --source "packs_source" \
  --profiles sky \
  --combo "sword_bow=sword,bow" \
  --combo "pvp=sword,bow,potion,golden_apple" \
  --dest-root "packs_generes"
```

Chaque combo produit `pack_folder_<nom>/<nom>_1.zip`, `<nom>_2.zip`… contenant tous les items du combo trouvés dans le pack source. Le dédoublonnage se fait sur le **contenu combiné** (deux packs sources donnant exactement le même contenu ne sont exportés qu'une fois). Ajoute `--combo-require-all` pour ne garder que les packs qui possèdent **tous** les items du combo.

### Ce que ça produit

Pour chaque profil demandé, un dossier `pack_folder_<id>/` est créé contenant un `.zip` par item unique trouvé (ex: `sword_1.zip`, `sword_2.zip`...). Chaque zip est un resource pack autonome :

```
pack.mcmeta                        <- pack_format repris du pack source, description du profil (ou d'origine avec --keep-original)
pack.png                          <- icône générée à partir de l'item (64x64), ou pack.png d'origine avec --keep-original
assets/minecraft/...               <- le(s) fichier(s) de l'item + leurs .mcmeta d'animation, au chemin d'origine du pack source
```

Les fichiers d'animation `.mcmeta` voisins d'une texture (ex: `potion_overlay.png.mcmeta`) sont **automatiquement inclus** pour ne pas casser les textures animées. Le `pack_format` est lu dans le `pack.mcmeta` du pack source pour rester compatible avec la bonne version de Minecraft. Avec `--contact-sheet`, un `contact_sheet.png` (montage de toutes les icônes) est ajouté dans chaque dossier de sortie.

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

### Architecture du code (`extractor/`)

| Fichier | Rôle |
|---|---|
| `models.py` | Dataclasses (`ItemProfile`, `FoundFile`, `MatchUnit`...). |
| `profile_loader.py` | Chargement/validation des profils JSON. |
| `pack_discovery.py` | Détection des packs (dossiers, zip, rar, 7z, archives imbriquées) derrière une interface unifiée (`PackHandle`) ; lit aussi les métadonnées du pack source (`pack_format`, description, `pack.png`). |
| `matcher.py` | Recherche des items dans un pack (profils `simple`, `set`, `group`) et ajoute les `.mcmeta` d'animation voisins. |
| `dedupe.py` | Hash et détection de doublons, thread-safe. |
| `packager.py` | Construction du zip de sortie (pack.mcmeta, pack.png, fichiers). |
| `contact_sheet.py` | Génération de la planche-contact (montage PNG des icônes) d'un dossier de sortie. |
| `reporter.py` | Rapport CSV. |
| `run.py` | CLI, orchestration, parallélisation (profils séparés + combos, dry-run, keep-original, planche-contact). |

L'application graphique [`gui.py`](gui.py) (racine du repo) pilote `run.py` et ajoute la mémorisation des réglages, la progression, le récapitulatif et un éditeur de profils.

Un "pack" est détecté n'importe où dans l'arborescence source (dossier ou archive) dès qu'il contient un dossier `assets/` ou un `pack.mcmeta` — peu importe la profondeur d'imbrication (ex: une archive `.rar` qui contient elle-même plusieurs `.zip`, chacun étant un pack distinct).
