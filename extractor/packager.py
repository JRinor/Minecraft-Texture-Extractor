"""Construction du resource pack de sortie (zip) pour une unité trouvée.

Tout se fait en mémoire (io.BytesIO) avant une seule écriture disque, pas de
dossier temporaire à nettoyer comme dans l'ancienne version du script.
"""

from __future__ import annotations

import io
import json
import logging
import zipfile
from pathlib import Path

from PIL import Image

from .models import MatchUnit

logger = logging.getLogger(__name__)

ICON_SIZE = (64, 64)
DEFAULT_PACK_FORMAT = 1  # 1.8 (utilisé si le pack source n'indique pas de format)


def _build_pack_png(icon_bytes: bytes) -> bytes | None:
    try:
        with Image.open(io.BytesIO(icon_bytes)) as img:
            img = img.convert("RGBA")
            img = img.resize(ICON_SIZE, Image.LANCZOS)
            out = io.BytesIO()
            img.save(out, format="PNG")
            return out.getvalue()
    except Exception as exc:
        logger.warning("Génération du pack.png impossible (%s), icône par défaut utilisée", exc)
        return None


def package_unit(unit: MatchUnit, counter: int, dest_dir: Path, keep_original: bool = False) -> Path:
    dest_dir.mkdir(parents=True, exist_ok=True)

    description = unit.profile.pack_description
    if keep_original and unit.source_description:
        description = unit.source_description

    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as zf:
        mcmeta = {
            "pack": {
                "pack_format": unit.pack_format or DEFAULT_PACK_FORMAT,
                "description": description,
            }
        }
        zf.writestr("pack.mcmeta", json.dumps(mcmeta, ensure_ascii=False, indent=2))

        # Icône : pack.png d'origine si demandé et disponible, sinon générée à
        # partir de l'item.
        icon_source = unit.source_icon_data if (keep_original and unit.source_icon_data) else unit.icon_file.data
        pack_png = _build_pack_png(icon_source)
        if pack_png is None and keep_original and unit.source_icon_data:
            pack_png = _build_pack_png(unit.icon_file.data)  # repli sur l'icône item
        if pack_png is not None:
            zf.writestr("pack.png", pack_png)

        for found in unit.files:
            zf.writestr(found.rel_path, found.data)

    zip_name = f"{unit.profile.output_prefix}_{counter}.zip"
    zip_path = dest_dir / zip_name
    zip_path.write_bytes(buffer.getvalue())
    return zip_path
