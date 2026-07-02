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
    python run.py --source "D:/packs" --combo "sword_bow=sword,bow"
    python run.py --source "D:/packs" --profiles sword --combo "pvp=sword,bow,potion" --combo-require-all

Les profils disponibles sont les fichiers .json du dossier profiles/.
"""

from __future__ import annotations

import argparse
import logging
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from .contact_sheet import build_contact_sheet
from .dedupe import DedupeStore, compute_unit_hash
from .matcher import find_matches
from .models import ItemProfile, MatchUnit, ProfileType
from .pack_discovery import SourceMeta, discover_packs_for_entry
from .packager import package_unit
from .profile_loader import ProfileError, load_profiles
from .reporter import ReportRow, Reporter

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


class Counter:
    def __init__(self):
        self._n = 0
        self._lock = threading.Lock()

    def next(self) -> int:
        with self._lock:
            self._n += 1
            return self._n

    def value(self) -> int:
        with self._lock:
            return self._n


@dataclass
class Options:
    dry_run: bool = False
    keep_original: bool = False


@dataclass
class ComboSpec:
    name: str
    profile: ItemProfile          # profil synthétique (id = name)
    members: list[str]            # ids des profils membres
    require_all: bool = False


@dataclass
class RunContext:
    all_profiles: dict[str, ItemProfile]
    separate_profiles: dict[str, ItemProfile]
    combos: list[ComboSpec]
    needed_ids: set[str]
    dedupe: DedupeStore
    reporter: Reporter
    dest_dirs: dict[str, Path]
    counters: dict[str, Counter]
    options: Options
    packs_counter: Counter = field(default_factory=Counter)


def _apply_meta(unit: MatchUnit, meta: SourceMeta, options: Options) -> None:
    unit.pack_format = meta.pack_format
    if options.keep_original:
        unit.source_icon_data = meta.icon_data
        unit.source_description = meta.description


def _handle_unit(unit: MatchUnit, ctx: RunContext) -> None:
    pid = unit.profile.id
    content_hash = compute_unit_hash(unit)

    if ctx.dedupe.is_duplicate(pid, content_hash):
        logger.info("Doublon ignoré (%s) depuis %s", pid, unit.source_pack_label)
        ctx.reporter.add(ReportRow(pid, unit.source_pack_label, "duplicate", "", content_hash))
        return

    if ctx.options.dry_run:
        logger.info("[Aperçu] %s serait exporté depuis %s", pid, unit.source_pack_label)
        ctx.reporter.add(ReportRow(pid, unit.source_pack_label, "exported", "(dry-run)", content_hash))
        return

    counter = ctx.counters[pid].next()
    try:
        zip_path = package_unit(unit, counter, ctx.dest_dirs[pid], keep_original=ctx.options.keep_original)
    except Exception as exc:
        logger.error("Échec de packaging (%s) depuis %s : %s", pid, unit.source_pack_label, exc)
        ctx.reporter.add(ReportRow(pid, unit.source_pack_label, "error", "", content_hash, str(exc)))
        return

    logger.info("Exporté %s <- %s", zip_path.name, unit.source_pack_label)
    ctx.reporter.add(ReportRow(pid, unit.source_pack_label, "exported", str(zip_path), content_hash))


def _process_combo(combo: ComboSpec, matches: dict[str, list[MatchUnit]],
                   pack, meta: SourceMeta, ctx: RunContext) -> None:
    combined_files = {}  # rel_path -> FoundFile (dédoublonne les chemins)
    icon = None
    present: dict[str, bool] = {}

    for mid in combo.members:
        units = matches.get(mid, [])
        present[mid] = bool(units)
        for unit in units:
            for f in unit.files:
                combined_files.setdefault(f.rel_path, f)
            if icon is None:
                icon = unit.icon_file

    if not combined_files:
        return
    if combo.require_all and not all(present.values()):
        missing = [m for m, ok in present.items() if not ok]
        logger.info("Combo '%s' incomplet ignoré pour %s (manque : %s)",
                    combo.name, pack.label, ", ".join(missing))
        return

    bundle = MatchUnit(
        profile=combo.profile,
        source_pack_label=pack.label,
        files=list(combined_files.values()),
        icon_file=icon,
    )
    _apply_meta(bundle, meta, ctx.options)
    _handle_unit(bundle, ctx)


def process_entry(entry: Path, ctx: RunContext) -> None:
    for pack in discover_packs_for_entry(entry):
        try:
            ctx.packs_counter.next()
            meta = pack.source_meta()

            # Matching calculé une seule fois par profil nécessaire (un profil
            # peut être à la fois en sortie séparée et membre d'un combo).
            matches: dict[str, list[MatchUnit]] = {}
            for pid in ctx.needed_ids:
                try:
                    matches[pid] = find_matches(ctx.all_profiles[pid], pack)
                except Exception as exc:
                    logger.error("Erreur de matching (%s) sur %s : %s", pid, pack.label, exc)
                    ctx.reporter.add(ReportRow(pid, pack.label, "error", "", "", str(exc)))
                    matches[pid] = []

            # Sorties séparées (un pack par item)
            for pid in ctx.separate_profiles:
                for unit in matches.get(pid, []):
                    _apply_meta(unit, meta, ctx.options)
                    _handle_unit(unit, ctx)

            # Combos (un pack fusionné par combo)
            for combo in ctx.combos:
                _process_combo(combo, matches, pack, meta, ctx)
        finally:
            pack.close()


def parse_combo_arg(raw: str) -> tuple[str, list[str]]:
    """Parse 'name=p1,p2' (ou 'name:p1,p2') -> ('name', ['p1','p2'])."""
    sep = "=" if "=" in raw else (":" if ":" in raw else None)
    if sep is None:
        raise ValueError(f"Combo invalide '{raw}' (format attendu : nom=profil1,profil2)")
    name, members_raw = raw.split(sep, 1)
    name = name.strip()
    members = [m.strip() for m in members_raw.split(",") if m.strip()]
    if not name or not members:
        raise ValueError(f"Combo invalide '{raw}' (nom ou membres manquants)")
    return name, members


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Extrait des items de masse depuis une collection de texture packs Minecraft.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("--source", required=True, type=Path, help="Dossier contenant les texture packs à scanner.")
    parser.add_argument("--profiles", nargs="*", default=[],
                        help="Profils à extraire séparément (un pack par item), ex: sword sky.")
    parser.add_argument("--combo", action="append", default=[], metavar="NOM=p1,p2",
                        help="Combo : fusionne plusieurs profils en un seul pack. Répétable. Ex: --combo \"sword_bow=sword,bow\".")
    parser.add_argument("--combo-require-all", action="store_true",
                        help="Pour les combos : ne produire un pack que si TOUS les profils du combo sont présents dans le pack source.")
    parser.add_argument("--profiles-dir", type=Path,
                        default=Path(__file__).resolve().parent.parent / "profiles",
                        help="Dossier des profils JSON (défaut : profiles/ à la racine du repo).")
    parser.add_argument("--dest-root", type=Path, default=None,
                        help="Dossier racine de sortie (défaut : à côté de --source).")
    parser.add_argument("--report", type=Path, default=None, help="Chemin du rapport CSV (défaut : <dest-root>/report.csv).")
    parser.add_argument("--log-file", type=Path, default=None, help="Fichier de log (en plus de la console).")
    parser.add_argument("--workers", type=int, default=8, help="Nombre de threads (défaut : 8).")
    parser.add_argument("-v", "--verbose", action="store_true", help="Logs détaillés (DEBUG).")
    parser.add_argument("--dry-run", action="store_true",
                        help="Aperçu : compte ce qui serait extrait sans rien écrire.")
    parser.add_argument("--keep-original", action="store_true",
                        help="Conserver le pack.png et la description d'origine du pack source au lieu de les générer.")
    parser.add_argument("--contact-sheet", action="store_true",
                        help="Générer une planche-contact (montage PNG) des icônes par dossier de sortie.")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    setup_logging(args.log_file, args.verbose)

    if not args.source.is_dir():
        logger.error("Le dossier source n'existe pas : %s", args.source)
        return 1

    # Parse les combos
    combos_parsed: list[tuple[str, list[str]]] = []
    for raw in args.combo:
        try:
            combos_parsed.append(parse_combo_arg(raw))
        except ValueError as exc:
            logger.error(str(exc))
            return 1

    if not args.profiles and not combos_parsed:
        logger.error("Rien à faire : précise --profiles et/ou --combo.")
        return 1

    # Union de tous les profils nécessaires (séparés + membres de combos)
    needed_ids = set(args.profiles)
    for _, members in combos_parsed:
        needed_ids.update(members)

    try:
        all_profiles = load_profiles(args.profiles_dir, wanted_ids=sorted(needed_ids))
    except ProfileError as exc:
        logger.error(str(exc))
        return 1

    separate_profiles = {pid: all_profiles[pid] for pid in args.profiles}

    # Construit les specs de combos (profil synthétique par combo)
    combos: list[ComboSpec] = []
    output_ids: set[str] = set(separate_profiles)
    for name, members in combos_parsed:
        if name in output_ids:
            logger.error("Nom de sortie en conflit : '%s' est déjà utilisé.", name)
            return 1
        output_ids.add(name)
        combo_profile = ItemProfile(
            id=name,
            type=ProfileType.SIMPLE,
            display_name=name,
            output_prefix=name,
            pack_description="Combo: " + " + ".join(members),
        )
        combos.append(ComboSpec(name=name, profile=combo_profile, members=members,
                                require_all=args.combo_require_all))

    dest_root = args.dest_root or args.source.parent
    dest_dirs = {oid: dest_root / f"pack_folder_{oid}" for oid in output_ids}
    if not args.dry_run:
        for d in dest_dirs.values():
            d.mkdir(parents=True, exist_ok=True)

    report_path = args.report or (dest_root / "report.csv")

    ctx = RunContext(
        all_profiles=all_profiles,
        separate_profiles=separate_profiles,
        combos=combos,
        needed_ids=needed_ids,
        dedupe=DedupeStore(),
        reporter=Reporter(),
        dest_dirs=dest_dirs,
        counters={oid: Counter() for oid in output_ids},
        options=Options(dry_run=args.dry_run, keep_original=args.keep_original),
    )

    top_level_entries = sorted(args.source.iterdir())
    if not top_level_entries:
        logger.warning("Le dossier source est vide : %s", args.source)

    combo_desc = ", ".join(c.name for c in combos) or "aucun"
    logger.info(
        "Démarrage : %d entrée(s) dans %s | séparés=%s | combos=%s | workers=%d%s%s",
        len(top_level_entries), args.source,
        ", ".join(separate_profiles) or "aucun", combo_desc, args.workers,
        " | DRY-RUN" if args.dry_run else "",
        " | keep-original" if args.keep_original else "",
    )

    total = len(top_level_entries)
    done = 0
    print(f"[PROGRESS] 0/{total}", flush=True)

    start = time.time()
    with ThreadPoolExecutor(max_workers=args.workers) as executor:
        futures = {executor.submit(process_entry, entry, ctx): entry for entry in top_level_entries}
        for future in as_completed(futures):
            entry = futures[future]
            try:
                future.result()
            except Exception:
                logger.exception("Erreur fatale en traitant %s", entry)
            done += 1
            print(f"[PROGRESS] {done}/{total}|{entry.name}", flush=True)

    if not args.dry_run:
        ctx.reporter.write_csv(report_path)
    else:
        logger.info("(dry-run : aucun fichier écrit, rapport non généré)")

    # Planche-contact (#10)
    if args.contact_sheet and not args.dry_run:
        for oid, d in dest_dirs.items():
            try:
                build_contact_sheet(d)
            except Exception as exc:
                logger.warning("Planche-contact impossible pour %s : %s", oid, exc)

    elapsed = time.time() - start
    print(f"[PACKS] {ctx.packs_counter.value()}", flush=True)
    logger.info("Terminé en %.1fs. %d pack(s) source analysé(s).", elapsed, ctx.packs_counter.value())
    if not args.dry_run:
        logger.info("Rapport : %s", report_path)
    for output_id, stats in ctx.reporter.summary().items():
        logger.info(
            "  %-16s exportés=%d  doublons=%d  erreurs=%d",
            output_id, stats.get("exported", 0), stats.get("duplicate", 0), stats.get("error", 0),
        )

    return 0


if __name__ == "__main__":
    sys.exit(main())
