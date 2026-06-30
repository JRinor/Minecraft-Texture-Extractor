#!/usr/bin/env python3
"""Texture Pack Extractor V2.

Parcourt un dossier contenant un grand nombre de texture packs Minecraft
(dossiers déjà extraits, .zip, .rar, .7z, y compris imbriqués), en extrait
les items demandés (définis par des profils JSON dans profiles/), élimine
les doublons (même contenu binaire), et génère pour chaque item trouvé un
mini resource pack autonome (pack.mcmeta + pack.png + l'item) prêt à être
distribué.

Exemples :

    python run.py --source "D:/packs" --profiles sword
    python run.py --source "D:/packs" --profiles sword sky --workers 8
    python run.py --source "D:/packs" --profiles sky --dest-root "D:/out"

Les profils disponibles sont les fichiers .json du dossier profiles/ (à côté
de ce script, ou indiqué via --profiles-dir). Voir profiles/sword.json et
profiles/sky.json pour le format.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

from dedupe import DedupeStore, compute_unit_hash
from matcher import find_matches
from models import ItemProfile, MatchUnit
from pack_discovery import discover_packs_for_entry
from packager import package_unit
from profile_loader import ProfileError, load_profiles
from reporter import ReportRow, Reporter

logger = logging.getLogger("texture_extractor")


def setup_logging(log_file: Path | None, verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    handlers: list[logging.Handler] = [logging.StreamHandler()]
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        handlers.append(logging.FileHandler(log_file, encoding="utf-8"))
    logging.basicConfig(
        level=level,
        format="%(asctime)s - %(levelname)s - %(name)s - %(message)s",
        handlers=handlers,
    )


def process_entry(
    entry: Path,
    profiles: dict[str, ItemProfile],
    dedupe: DedupeStore,
    reporter: Reporter,
    dest_dirs: dict[str, Path],
    counters: dict[str, "Counter"],
) -> None:
    for pack in discover_packs_for_entry(entry):
        try:
            for profile in profiles.values():
                try:
                    units = find_matches(profile, pack)
                except Exception as exc:
                    logger.error("Erreur de matching (%s) sur %s : %s", profile.id, pack.label, exc)
                    reporter.add(ReportRow(profile.id, pack.label, "error", "", "", str(exc)))
                    continue

                for unit in units:
                    _handle_unit(unit, dedupe, reporter, dest_dirs, counters)
        finally:
            pack.close()


def _handle_unit(
    unit: MatchUnit,
    dedupe: DedupeStore,
    reporter: Reporter,
    dest_dirs: dict[str, Path],
    counters: dict[str, "Counter"],
) -> None:
    profile_id = unit.profile.id
    content_hash = compute_unit_hash(unit)

    if dedupe.is_duplicate(profile_id, content_hash):
        logger.info("Doublon ignoré (%s) depuis %s", profile_id, unit.source_pack_label)
        reporter.add(ReportRow(profile_id, unit.source_pack_label, "duplicate", "", content_hash))
        return

    counter = counters[profile_id].next()
    try:
        zip_path = package_unit(unit, counter, dest_dirs[profile_id])
    except Exception as exc:
        logger.error("Échec de packaging (%s) depuis %s : %s", profile_id, unit.source_pack_label, exc)
        reporter.add(ReportRow(profile_id, unit.source_pack_label, "error", "", content_hash, str(exc)))
        return

    logger.info("Exporté %s <- %s", zip_path.name, unit.source_pack_label)
    reporter.add(ReportRow(profile_id, unit.source_pack_label, "exported", str(zip_path), content_hash))


class Counter:
    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrait des items de masse depuis une collection de texture packs Minecraft.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", required=True, type=Path, help="Dossier contenant les texture packs à scanner.")
    parser.add_argument(
        "--profiles",
        nargs="+",
        required=True,
        help="Identifiants des profils à extraire (ex: sword sky). Doivent correspondre à des fichiers <id>.json dans --profiles-dir.",
    )
    parser.add_argument(
        "--profiles-dir",
        type=Path,
        default=Path(__file__).resolve().parent.parent / "profiles",
        help="Dossier contenant les fichiers de profils JSON (défaut : profiles/ à côté du dossier du script).",
    )
    parser.add_argument(
        "--dest-root",
        type=Path,
        default=None,
        help="Dossier racine où créer un sous-dossier pack_folder_<profil> par profil (défaut : à côté de --source).",
    )
    parser.add_argument("--report", type=Path, default=None, help="Chemin du rapport CSV (défaut : <dest-root>/report.csv).")
    parser.add_argument("--log-file", type=Path, default=None, help="Fichier de log (en plus de la console).")
    parser.add_argument("--workers", type=int, default=8, help="Nombre de threads pour traiter les entrées en parallèle (défaut : 8).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logs détaillés (DEBUG).")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_file, args.verbose)

    if not args.source.is_dir():
        logger.error("Le dossier source n'existe pas : %s", args.source)
        return 1

    try:
        profiles = load_profiles(args.profiles_dir, wanted_ids=args.profiles)
    except ProfileError as exc:
        logger.error(str(exc))
        return 1

    dest_root = args.dest_root or args.source.parent
    dest_dirs = {pid: dest_root / f"pack_folder_{pid}" for pid in profiles}
    for d in dest_dirs.values():
        d.mkdir(parents=True, exist_ok=True)

    report_path = args.report or (dest_root / "report.csv")

    dedupe = DedupeStore()
    reporter = Reporter()
    counters = {pid: Counter() for pid in profiles}

    top_level_entries = sorted(args.source.iterdir())
    if not top_level_entries:
        logger.warning("Le dossier source est vide : %s", args.source)

    logger.info(
        "Démarrage : %d entrée(s) à la racine de %s, profils=%s, workers=%d",
        len(top_level_entries), args.source, ", ".join(profiles), args.workers,
    )

    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {
            executor.submit(process_entry, entry, profiles, dedupe, reporter, dest_dirs, counters): entry
            for entry in top_level_entries
        }
        for future in as_completed(futures):
            entry = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("Erreur fatale en traitant %s", entry)

    reporter.write_csv(report_path)

    elapsed = time.time() - start
    logger.info("Terminé en %.1fs. Rapport : %s", elapsed, report_path)
    for profile_id, stats in reporter.summary().items():
        logger.info(
            "  %-12s exportés=%d  doublons=%d  erreurs=%d",
            profile_id, stats.get("exported", 0), stats.get("duplicate", 0), stats.get("error", 0),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
