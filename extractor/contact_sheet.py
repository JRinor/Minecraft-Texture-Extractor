"""Génère une planche-contact (montage PNG) des icônes d'un dossier de sortie.

Pour chaque dossier ``pack_folder_<id>``, lit le ``pack.png`` de chaque zip
généré et les dispose en grille dans un seul ``contact_sheet.png``. Pratique
pour avoir un aperçu de tous les items extraits (miniature/aperçu YouTube).
"""

from __future__ import annotations

import io
import logging
import math
import zipfile
from pathlib import Path

from PIL import Image

logger = logging.getLogger(__name__)

CELL = 64          # taille d'une icône dans la grille
PADDING = 4        # marge autour de chaque icône
BG = (30, 30, 30, 255)
MAX_COLS = 32      # largeur max de la grille en nombre d'icônes


def _read_zip_icon(zip_path: Path) -> Image.Image | None:
    try:
        with zipfile.ZipFile(zip_path, "r") as zf:
            if "pack.png" not in zf.namelist():
                return None
            data = zf.read("pack.png")
        img = Image.open(io.BytesIO(data)).convert("RGBA")
        return img.resize((CELL, CELL), Image.NEAREST)
    except Exception as exc:
        logger.warning("Icône illisible dans %s : %s", zip_path.name, exc)
        return None


def build_contact_sheet(dest_dir: Path, out_path: Path | None = None) -> Path | None:
    """Construit la planche-contact pour un dossier ``pack_folder_<id>``.
    Retourne le chemin de l'image générée, ou None si aucune icône."""
    zips = sorted(dest_dir.glob("*.zip"))
    icons = [img for img in (_read_zip_icon(z) for z in zips) if img is not None]
    if not icons:
        return None

    cols = min(MAX_COLS, max(1, int(math.ceil(math.sqrt(len(icons))))))
    cols = min(cols, len(icons))
    rows = int(math.ceil(len(icons) / cols))

    step = CELL + PADDING
    width = cols * step + PADDING
    height = rows * step + PADDING
    sheet = Image.new("RGBA", (width, height), BG)

    for i, icon in enumerate(icons):
        r, c = divmod(i, cols)
        x = PADDING + c * step
        y = PADDING + r * step
        sheet.paste(icon, (x, y), icon)

    out_path = out_path or (dest_dir / "contact_sheet.png")
    sheet.save(out_path, format="PNG")
    logger.info("Planche-contact : %s (%d icônes)", out_path, len(icons))
    return out_path
