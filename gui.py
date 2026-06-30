#!/usr/bin/env python3
"""Interface graphique du Texture Pack Extractor V2.

Simple : 1) choisir le dossier des packs, 2) cocher les items, 3) « Extraire ».
Fonctionne aussi en exécutable autonome (PyInstaller) : lancé avec
``--extract-cli`` il se comporte comme le moteur en ligne de commande.

Démarrage :
    python gui.py        (ou double-clic sur lancer_gui.bat / l'.exe)
"""

from __future__ import annotations

import json
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

# ---- Chemins (compatibles exécutable figé PyInstaller) ----
FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    APP_DIR = Path(sys.executable).resolve().parent
    BUNDLE_DIR = Path(getattr(sys, "_MEIPASS", APP_DIR))
else:
    APP_DIR = Path(__file__).resolve().parent
    BUNDLE_DIR = APP_DIR

ROOT = APP_DIR
RUN_PY = APP_DIR / "texture_extractor_v2" / "run.py"
PROFILES_DIR = APP_DIR / "profiles"
DEFAULT_SOURCE = APP_DIR / "packs_source"
DEFAULT_DEST = APP_DIR / "packs_generes"
CONFIG_PATH = APP_DIR / "gui_config.json"

# Rend les modules du moteur importables (dev + figé)
sys.path.insert(0, str(APP_DIR / "texture_extractor_v2"))
if FROZEN:
    sys.path.insert(0, str(BUNDLE_DIR))

# ---- Glisser-déposer (optionnel) ----
try:
    from tkinterdnd2 import DND_FILES, TkinterDnD
    _DND = True
    _Base = TkinterDnD.Tk
except Exception:
    _DND = False
    _Base = tk.Tk

FRENCH_NAMES = {
    "sword": "⚔️ Épée (diamant)", "bow": "🏹 Arc", "arrow": "➶ Flèche",
    "fishing_rod": "🎣 Canne à pêche",
    "pickaxe": "⛏️ Pioche", "axe": "🪓 Hache", "shovel": "🥄 Pelle", "hoe": "🌾 Houe",
    "armor_diamond": "🛡️ Armure diamant", "armor_iron": "🛡️ Armure fer",
    "armor_gold": "🛡️ Armure or", "armor_chainmail": "🛡️ Armure mailles",
    "armor_leather": "🛡️ Armure cuir",
    "golden_apple": "🍎 Pomme dorée", "potion": "🧪 Potions",
    "obsidian": "🟪 Obsidienne", "ender_pearl": "🔮 Perle de l'Ender",
    "gui": "🖥️ Interface (barres de vie, hotbar…)", "sky": "🌌 Ciel (overlays)",
}

CATEGORIES = [
    ("⚔️ Armes", ["sword", "bow", "arrow"]),
    ("⛏️ Outils", ["pickaxe", "axe", "shovel", "hoe", "fishing_rod"]),
    ("🛡️ Armures", ["armor_diamond", "armor_iron", "armor_gold", "armor_chainmail", "armor_leather"]),
    ("🍎 Nourriture & objets", ["golden_apple", "potion", "ender_pearl", "obsidian"]),
    ("🖥️ Interface & ciel", ["gui", "sky"]),
]

PRESETS = {
    "🗡️ Items PvP": ["sword", "bow", "arrow", "fishing_rod", "armor_diamond", "potion",
                     "golden_apple", "ender_pearl", "gui"],
    "⛏️ Outils": ["pickaxe", "axe", "shovel", "hoe"],
    "🛡️ Armures": ["armor_diamond", "armor_iron", "armor_gold", "armor_chainmail", "armor_leather"],
}

PROGRESS_RE = re.compile(r"\[PROGRESS\]\s+(\d+)/(\d+)(?:\|(.*))?")
PACKS_RE = re.compile(r"\[PACKS\]\s+(\d+)")
SUMMARY_RE = re.compile(r"(\S+)\s+export\w+=(\d+)\s+doublons=(\d+)\s+erreurs=(\d+)")


def ensure_profiles_dir() -> None:
    """En exécutable figé, copie les profils par défaut à côté de l'.exe au
    premier lancement (pour qu'ils soient éditables)."""
    if PROFILES_DIR.is_dir() and any(PROFILES_DIR.glob("*.json")):
        return
    src = BUNDLE_DIR / "profiles"
    if src.is_dir():
        PROFILES_DIR.mkdir(parents=True, exist_ok=True)
        for f in src.glob("*.json"):
            try:
                shutil.copy(f, PROFILES_DIR / f.name)
            except Exception:
                pass


def load_profiles_meta() -> dict[str, str]:
    out: dict[str, str] = {}
    if PROFILES_DIR.is_dir():
        for jf in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                out[data["id"]] = data.get("display_name", data["id"])
            except Exception:
                continue
    return out


def nice_name(pid: str, display_name: str) -> str:
    return FRENCH_NAMES.get(pid, f"📦 {display_name}")


class Tooltip:
    def __init__(self, widget, text: str):
        self.widget, self.text, self.tip = widget, text, None
        widget.bind("<Enter>", self._show)
        widget.bind("<Leave>", self._hide)

    def _show(self, _e=None):
        if self.tip or not self.text:
            return
        x = self.widget.winfo_rootx() + 20
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        tk.Label(self.tip, text=self.text, justify="left", background="#ffffe0",
                 relief="solid", borderwidth=1, padx=6, pady=4, wraplength=360,
                 font=("Segoe UI", 9)).pack()

    def _hide(self, _e=None):
        if self.tip:
            self.tip.destroy()
            self.tip = None


class Collapsible(ttk.Frame):
    def __init__(self, parent, title: str, opened: bool = False):
        super().__init__(parent)
        self._title, self._open = title, opened
        self.header = ttk.Button(self, text="", command=self.toggle)
        self.header.pack(fill="x")
        self.body = ttk.Frame(self)
        self._render()

    def _render(self):
        self.header.config(text=f"{'▾' if self._open else '▸'}  {self._title}")
        (self.body.pack(fill="x", pady=(4, 0)) if self._open else self.body.forget())

    def toggle(self):
        self._open = not self._open
        self._render()


class ExtractorGUI(_Base):
    def __init__(self):
        super().__init__()
        self.title("Minecraft Texture Extractor")
        self.geometry("900x880")
        self.minsize(820, 720)

        self.proc: subprocess.Popen | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.profile_vars: dict[str, tk.BooleanVar] = {}
        self.combos: list[dict] = []
        self._analyze_mode = False
        self._last_packs = 0

        ensure_profiles_dir()
        self._build_ui()
        self._load_config()
        self._bind_shortcuts()
        self._update_count()
        self.after(100, self._poll_log)
        self.after(300, self._check_deps)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ================= UI =================
    def _build_ui(self) -> None:
        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True)
        self.tab_run = ttk.Frame(nb)
        self.tab_profiles = ttk.Frame(nb)
        nb.add(self.tab_run, text="  Extraction  ")
        nb.add(self.tab_profiles, text="  Profils (avancé)  ")
        self._build_run_tab(self.tab_run)
        self._build_profiles_tab(self.tab_profiles)

    def _build_run_tab(self, parent) -> None:
        ttk.Label(parent,
                  text="Place tes texture packs dans le dossier source (ou glisse-le ici), coche ce que tu veux, puis « Extraire ».",
                  font=("Segoe UI", 10), foreground="#444", wraplength=860, justify="left").pack(fill="x", padx=12, pady=(10, 4))

        # ---------- Étape 1 ----------
        step1 = ttk.LabelFrame(parent, text=" 1 · Où sont tes texture packs ? ")
        step1.pack(fill="x", padx=12, pady=6)
        row = ttk.Frame(step1)
        row.pack(fill="x")
        self.source_var = tk.StringVar(value=str(DEFAULT_SOURCE))
        self.source_var.trace_add("write", lambda *a: self._schedule_count())
        self.source_entry = ttk.Entry(row, textvariable=self.source_var)
        self.source_entry.pack(side="left", fill="x", expand=True, padx=8, pady=8)
        ttk.Button(row, text="Choisir…", command=self._pick_source).pack(side="left", padx=4, pady=8)
        ttk.Button(row, text="📂 Ouvrir", command=self._open_source).pack(side="left", padx=4, pady=8)
        self.count_var = tk.StringVar(value="")
        ttk.Label(step1, textvariable=self.count_var, foreground="#0a5").pack(anchor="w", padx=10, pady=(0, 6))
        if _DND:
            try:
                self.source_entry.drop_target_register(DND_FILES)
                self.source_entry.dnd_bind("<<Drop>>", self._on_drop)
            except Exception:
                pass

        # ---------- Étape 2 ----------
        step2 = ttk.LabelFrame(parent, text=" 2 · Que veux-tu extraire ? ")
        step2.pack(fill="both", expand=True, padx=12, pady=6)
        quick = ttk.Frame(step2)
        quick.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Button(quick, text="Tout cocher", command=lambda: self._set_all(True)).pack(side="left")
        ttk.Button(quick, text="Tout décocher", command=lambda: self._set_all(False)).pack(side="left", padx=(6, 14))
        ttk.Label(quick, text="Sélections rapides :").pack(side="left", padx=(0, 6))
        for label in PRESETS:
            pb = ttk.Button(quick, text=label, command=lambda l=label: self._apply_preset(l))
            pb.pack(side="left", padx=3)
            Tooltip(pb, "Coche : " + ", ".join(PRESETS[label]))
        self.cats_frame = ttk.Frame(step2)
        self.cats_frame.pack(fill="both", expand=True, padx=8, pady=6)
        self._populate_categories()

        # ---------- Étape 3 ----------
        step3 = ttk.LabelFrame(parent, text=" 3 · Créer les packs ")
        step3.pack(fill="x", padx=12, pady=6)
        outrow = ttk.Frame(step3)
        outrow.pack(fill="x", padx=8, pady=(8, 2))
        ttk.Label(outrow, text="Les packs créés iront dans :").pack(side="left")
        self.dest_var = tk.StringVar(value=str(DEFAULT_DEST))
        ttk.Label(outrow, textvariable=self.dest_var, foreground="#0a5").pack(side="left", padx=6)
        ttk.Button(outrow, text="Modifier…", command=self._pick_dest).pack(side="left", padx=6)

        runrow = ttk.Frame(step3)
        runrow.pack(fill="x", padx=8, pady=8)
        self.run_btn = tk.Button(runrow, text="▶   Extraire les textures", command=self._start,
                                 bg="#2e7d32", fg="white", activebackground="#256628",
                                 activeforeground="white", font=("Segoe UI", 12, "bold"),
                                 relief="flat", padx=18, pady=8, cursor="hand2")
        self.run_btn.pack(side="left")
        ab = ttk.Button(runrow, text="🔎 Analyser", command=self._analyze)
        ab.pack(side="left", padx=10)
        Tooltip(ab, "Compte ce que contiennent tes packs (sans rien créer).")
        self.stop_btn = ttk.Button(runrow, text="Arrêter", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=4)
        ttk.Button(runrow, text="📂 Voir les packs", command=self._open_dest).pack(side="left", padx=4)
        ttk.Button(runrow, text="🖼 Icônes", command=self._preview_icons).pack(side="left", padx=4)
        ttk.Button(runrow, text="📄 Rapport", command=self._open_csv).pack(side="left", padx=4)

        self.progress = ttk.Progressbar(step3, mode="determinate")
        self.progress.pack(fill="x", padx=8, pady=(0, 4))
        self.status_var = tk.StringVar(value="Prêt.")
        ttk.Label(step3, textvariable=self.status_var, foreground="#555").pack(anchor="w", padx=8, pady=(0, 6))

        # ---------- Avancé ----------
        adv = Collapsible(parent, "Options avancées (combos, sortie, réglages)", opened=False)
        adv.pack(fill="x", padx=12, pady=6)
        self._build_advanced(adv.body)

        det = Collapsible(parent, "Détails de l'exécution (journal + récapitulatif)", opened=False)
        det.pack(fill="both", padx=12, pady=(0, 10))
        self._build_details(det.body)

    def _build_advanced(self, parent) -> None:
        opts = ttk.Frame(parent)
        opts.pack(fill="x", pady=4)
        self.contact_sheet_var = tk.BooleanVar(value=True)
        self.keep_original_var = tk.BooleanVar(value=False)
        self.dry_run_var = tk.BooleanVar(value=False)
        self.verbose_var = tk.BooleanVar(value=False)
        self.clean_before_var = tk.BooleanVar(value=False)
        self.open_after_var = tk.BooleanVar(value=True)

        defs = [
            ("Créer une image d'aperçu de tous les items (recommandé)", self.contact_sheet_var,
             "Ajoute un contact_sheet.png (mosaïque des icônes) dans chaque dossier créé."),
            ("Garder l'icône et le nom d'origine du pack source", self.keep_original_var,
             "Utilise le pack.png et la description d'origine au lieu d'en générer."),
            ("Vider le dossier de sortie avant (repartir propre)", self.clean_before_var,
             "Supprime les anciens dossiers pack_folder_* et report.csv avant de relancer."),
            ("Ouvrir le dossier de sortie à la fin", self.open_after_var, ""),
            ("Mode test : ne crée aucun fichier (juste un aperçu)", self.dry_run_var,
             "Compte ce qui serait extrait sans rien écrire."),
            ("Afficher les détails techniques dans le journal", self.verbose_var, ""),
        ]
        for i, (text, var, tip) in enumerate(defs):
            cb = ttk.Checkbutton(opts, text=text, variable=var)
            cb.grid(row=i, column=0, sticky="w", padx=4, pady=2)
            if tip:
                Tooltip(cb, tip)

        speed = ttk.Frame(opts)
        speed.grid(row=len(defs), column=0, sticky="w", padx=4, pady=4)
        ttk.Label(speed, text="Vitesse (tâches en parallèle) :").pack(side="left")
        self.workers_var = tk.IntVar(value=8)
        ttk.Spinbox(speed, from_=1, to=64, textvariable=self.workers_var, width=5).pack(side="left", padx=6)

        combo_box = ttk.LabelFrame(parent, text=" Combos : réunir plusieurs items dans un même pack ")
        combo_box.pack(fill="x", pady=6)
        ttk.Label(combo_box, text="Exemple : un combo « épée + arc » crée des packs contenant les deux ensemble.",
                  foreground="#555").pack(anchor="w", padx=6, pady=(6, 2))
        top = ttk.Frame(combo_box)
        top.pack(fill="x", padx=6, pady=2)
        ttk.Button(top, text="+ Créer un combo", command=self._add_combo_dialog).pack(side="left")
        ttk.Button(top, text="Supprimer le combo choisi", command=self._remove_combo).pack(side="left", padx=6)
        self.require_all_var = tk.BooleanVar(value=False)
        ra = ttk.Checkbutton(top, text="Seulement si tous les items du combo sont présents", variable=self.require_all_var)
        ra.pack(side="left", padx=12)
        Tooltip(ra, "Ignore un pack source s'il lui manque un des items du combo.")
        self.combo_list = tk.Listbox(combo_box, height=3)
        self.combo_list.pack(fill="x", padx=6, pady=(2, 8))

    def _build_details(self, parent) -> None:
        split = ttk.Panedwindow(parent, orient="horizontal")
        split.pack(fill="both", expand=True)
        log_frame = ttk.LabelFrame(split, text="Journal")
        bar = ttk.Frame(log_frame)
        bar.pack(fill="x")
        ttk.Button(bar, text="Effacer", command=self._clear_log).pack(side="right", padx=4, pady=2)
        self.log = ScrolledText(log_frame, height=10, wrap="word", state="disabled", font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=6, pady=6)
        split.add(log_frame, weight=3)
        recap_frame = ttk.LabelFrame(split, text="Récapitulatif")
        self.recap = ttk.Treeview(recap_frame, columns=("exp", "dup", "err"), show="tree headings", height=10)
        self.recap.heading("#0", text="Item")
        self.recap.heading("exp", text="Créés")
        self.recap.heading("dup", text="Doublons")
        self.recap.heading("err", text="Erreurs")
        self.recap.column("#0", width=140)
        for c in ("exp", "dup", "err"):
            self.recap.column(c, width=70, anchor="e")
        self.recap.pack(fill="both", expand=True, padx=6, pady=6)
        split.add(recap_frame, weight=2)

    def _populate_categories(self) -> None:
        for w in self.cats_frame.winfo_children():
            w.destroy()
        self.profile_vars.clear()
        meta = load_profiles_meta()
        if not meta:
            ttk.Label(self.cats_frame, text="Aucun profil dans profiles/.").pack(anchor="w")
            return
        assigned, groups = set(), []
        for cat_name, ids in CATEGORIES:
            present = [pid for pid in ids if pid in meta]
            if present:
                groups.append((cat_name, present))
                assigned.update(present)
        others = [pid for pid in meta if pid not in assigned]
        if others:
            groups.append(("📦 Autres", sorted(others)))
        for idx, (cat_name, ids) in enumerate(groups):
            box = ttk.LabelFrame(self.cats_frame, text=f" {cat_name} ")
            box.grid(row=idx // 2, column=idx % 2, sticky="nsew", padx=6, pady=6)
            for pid in ids:
                var = tk.BooleanVar(value=True)
                self.profile_vars[pid] = var
                ttk.Checkbutton(box, text=nice_name(pid, meta[pid]), variable=var).pack(anchor="w", padx=8, pady=1)
        self.cats_frame.columnconfigure(0, weight=1)
        self.cats_frame.columnconfigure(1, weight=1)

    # ================= Onglet Profils =================
    def _build_profiles_tab(self, parent) -> None:
        ttk.Label(parent, text="Crée ou modifie les types d'items extractibles.", foreground="#444").pack(anchor="w", padx=10, pady=(10, 4))
        body = ttk.Frame(parent)
        body.pack(fill="both", expand=True)
        left = ttk.Frame(body)
        left.pack(side="left", fill="y", padx=8, pady=8)
        self.editor_list = tk.Listbox(left, width=24, height=24, exportselection=False)
        self.editor_list.pack(fill="y", expand=True)
        self.editor_list.bind("<<ListboxSelect>>", self._editor_load_selected)
        lb = ttk.Frame(left)
        lb.pack(fill="x", pady=6)
        ttk.Button(lb, text="Formulaire", command=self._editor_form).pack(side="left")
        ttk.Button(lb, text="Supprimer", command=self._editor_delete).pack(side="left", padx=4)
        ttk.Button(lb, text="Recharger", command=self._editor_refresh).pack(side="left")

        right = ttk.Frame(body)
        right.pack(side="left", fill="both", expand=True, padx=8, pady=8)
        ttk.Label(right, text="Contenu JSON (édition avancée) :").pack(anchor="w")
        self.editor_text = ScrolledText(right, wrap="none", font=("Consolas", 10))
        self.editor_text.pack(fill="both", expand=True, pady=(2, 6))
        ttk.Button(right, text="💾  Enregistrer ce profil", command=self._editor_save).pack(anchor="w")
        self.editor_status = ttk.Label(right, text="", anchor="w")
        self.editor_status.pack(fill="x", pady=4)
        self._editor_refresh()

    def _editor_refresh(self) -> None:
        self.editor_list.delete(0, "end")
        for jf in sorted(PROFILES_DIR.glob("*.json")):
            self.editor_list.insert("end", jf.stem)

    def _editor_load_selected(self, _e=None) -> None:
        sel = self.editor_list.curselection()
        if not sel:
            return
        path = PROFILES_DIR / f"{self.editor_list.get(sel[0])}.json"
        try:
            content = path.read_text(encoding="utf-8")
        except Exception as exc:
            content = ""
            self._editor_set_status(f"Lecture impossible : {exc}", error=True)
        self.editor_text.delete("1.0", "end")
        self.editor_text.insert("1.0", content)

    def _editor_form(self) -> None:
        """Formulaire guidé pour créer un profil sans écrire de JSON (#5)."""
        dlg = tk.Toplevel(self)
        dlg.title("Créer un profil (formulaire)")
        dlg.transient(self)
        dlg.grab_set()
        pad = {"padx": 8, "pady": 4}

        fields = {}
        def add_row(r, label):
            ttk.Label(dlg, text=label).grid(row=r, column=0, sticky="w", **pad)
            v = tk.StringVar()
            ttk.Entry(dlg, textvariable=v, width=46).grid(row=r, column=1, sticky="ew", **pad)
            return v

        fields["id"] = add_row(0, "Identifiant (sans espace) :")
        fields["display_name"] = add_row(1, "Nom affiché :")
        ttk.Label(dlg, text="Type :").grid(row=2, column=0, sticky="w", **pad)
        type_var = tk.StringVar(value="simple")
        ttk.Combobox(dlg, textvariable=type_var, values=["simple", "set", "group"], state="readonly", width=12).grid(row=2, column=1, sticky="w", **pad)
        fields["candidates"] = add_row(3, "Fichiers à chercher (séparés par virgule) :")
        fields["companions"] = add_row(4, "Fichiers compagnons (type set, optionnel) :")
        fields["anchor_glob"] = add_row(5, "Motif ancre (type group, ex: minecraft/.../*.properties) :")
        fields["reference_keys"] = add_row(6, "Clés de référence (type group, ex: source) :")
        fields["path_hints"] = add_row(7, "Indices de chemin (ex: item) :")
        fields["path_hints"].set("item")
        fields["pack_description"] = add_row(8, "Description du pack :")
        dlg.columnconfigure(1, weight=1)

        def save():
            pid = fields["id"].get().strip()
            if not re.fullmatch(r"[A-Za-z0-9_-]+", pid or ""):
                messagebox.showerror("Profil", "Identifiant invalide.", parent=dlg)
                return
            t = type_var.get()
            data = {
                "id": pid, "type": t,
                "display_name": fields["display_name"].get().strip() or pid,
                "output_prefix": pid,
                "pack_description": fields["pack_description"].get().strip() or fields["display_name"].get().strip() or pid,
            }
            def split(s):
                return [x.strip() for x in s.split(",") if x.strip()]
            hints = split(fields["path_hints"].get())
            if hints:
                data["path_hints"] = hints
            if t in ("simple", "set"):
                cand = split(fields["candidates"].get())
                if not cand:
                    messagebox.showerror("Profil", "Indique au moins un fichier à chercher.", parent=dlg)
                    return
                data["candidates"] = cand
                if t == "set":
                    comp = split(fields["companions"].get())
                    if comp:
                        data["companions"] = comp
            else:  # group
                ag = fields["anchor_glob"].get().strip()
                rk = split(fields["reference_keys"].get())
                if not ag or not rk:
                    messagebox.showerror("Profil", "Type group : 'motif ancre' et 'clés de référence' sont requis.", parent=dlg)
                    return
                data["anchor_glob"] = ag
                data["reference_keys"] = rk
            self.editor_text.delete("1.0", "end")
            self.editor_text.insert("1.0", json.dumps(data, ensure_ascii=False, indent=2))
            dlg.destroy()
            self._editor_save()

        bf = ttk.Frame(dlg)
        bf.grid(row=9, column=0, columnspan=2, pady=10)
        ttk.Button(bf, text="Créer", command=save).pack(side="left", padx=6)
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")

    def _editor_save(self) -> None:
        raw = self.editor_text.get("1.0", "end").strip()
        try:
            data = json.loads(raw)
        except json.JSONDecodeError as exc:
            self._editor_set_status(f"JSON invalide : {exc}", error=True)
            return
        pid = data.get("id")
        if not pid or not re.fullmatch(r"[A-Za-z0-9_-]+", pid):
            self._editor_set_status("'id' manquant ou invalide.", error=True)
            return
        path = PROFILES_DIR / f"{pid}.json"
        try:
            path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
            from profile_loader import load_profile_file
            load_profile_file(path)
        except Exception as exc:
            self._editor_set_status(f"Profil refusé : {exc}", error=True)
            return
        self._editor_set_status(f"Enregistré : {pid}.json")
        self._editor_refresh()
        self._populate_categories()

    def _editor_delete(self) -> None:
        sel = self.editor_list.curselection()
        if not sel:
            return
        name = self.editor_list.get(sel[0])
        if not messagebox.askyesno("Supprimer", f"Supprimer le profil '{name}' ?"):
            return
        try:
            (PROFILES_DIR / f"{name}.json").unlink()
        except Exception as exc:
            self._editor_set_status(f"Suppression impossible : {exc}", error=True)
            return
        self.editor_text.delete("1.0", "end")
        self._editor_set_status(f"Supprimé : {name}.json")
        self._editor_refresh()
        self._populate_categories()

    def _editor_set_status(self, text: str, error: bool = False) -> None:
        self.editor_status.config(text=text, foreground="red" if error else "green")

    # ================= Source : compteur / dnd =================
    def _schedule_count(self) -> None:
        if getattr(self, "_count_after", None):
            try:
                self.after_cancel(self._count_after)
            except Exception:
                pass
        self._count_after = self.after(400, self._update_count)

    def _update_count(self) -> None:
        src = self.source_var.get().strip()
        p = Path(src) if src else None
        if not p or not p.is_dir():
            self.count_var.set("⚠️ Dossier introuvable")
            return
        try:
            n = sum(1 for _ in p.iterdir())
        except Exception:
            self.count_var.set("⚠️ Lecture impossible")
            return
        self.count_var.set(f"📦 {n} élément(s) à scanner" if n else "⚠️ Dossier vide — ajoute tes packs")

    def _on_drop(self, event) -> None:
        data = event.data
        if data.startswith("{") and "}" in data:
            path = data[1:data.index("}")]
        else:
            path = data.split()[0]
        p = Path(path)
        if p.is_file():
            p = p.parent
        if p.is_dir():
            self.source_var.set(str(p))

    def _open_source(self) -> None:
        src = self.source_var.get()
        if src and os.path.isdir(src):
            self._open_path(src)
        else:
            messagebox.showwarning("Dossier introuvable", "Choisis d'abord un dossier source valide.")

    # ================= Sélecteurs / presets =================
    def _pick_source(self) -> None:
        d = filedialog.askdirectory(title="Dossier des packs source", initialdir=self.source_var.get() or str(ROOT))
        if d:
            self.source_var.set(d)

    def _pick_dest(self) -> None:
        d = filedialog.askdirectory(title="Dossier de sortie", initialdir=self.dest_var.get() or str(ROOT))
        if d:
            self.dest_var.set(d)

    def _set_all(self, value: bool) -> None:
        for var in self.profile_vars.values():
            var.set(value)

    def _apply_preset(self, label: str) -> None:
        self._set_all(False)
        for pid in PRESETS.get(label, []):
            if pid in self.profile_vars:
                self.profile_vars[pid].set(True)

    # ================= Combos =================
    def _refresh_combo_list(self) -> None:
        self.combo_list.delete(0, "end")
        for c in self.combos:
            self.combo_list.insert("end", f"{c['name']}  =  {', '.join(c['members'])}")

    def _add_combo_dialog(self) -> None:
        meta = load_profiles_meta()
        if not meta:
            messagebox.showwarning("Combos", "Aucun profil disponible.")
            return
        dlg = tk.Toplevel(self)
        dlg.title("Nouveau combo")
        dlg.transient(self)
        dlg.grab_set()
        ttk.Label(dlg, text="Nom du combo (ex: epee_arc) :").grid(row=0, column=0, sticky="w", padx=8, pady=6)
        name_var = tk.StringVar(value="combo")
        ttk.Entry(dlg, textvariable=name_var, width=24).grid(row=0, column=1, sticky="w", padx=8, pady=6)
        ttk.Label(dlg, text="Items à réunir :").grid(row=1, column=0, columnspan=2, sticky="w", padx=8)
        frame = ttk.Frame(dlg)
        frame.grid(row=2, column=0, columnspan=2, padx=8, pady=4)
        member_vars: dict[str, tk.BooleanVar] = {}
        for i, pid in enumerate(meta):
            v = tk.BooleanVar(value=False)
            member_vars[pid] = v
            ttk.Checkbutton(frame, text=nice_name(pid, meta[pid]), variable=v).grid(row=i // 3, column=i % 3, sticky="w", padx=4, pady=2)

        def ok():
            name = name_var.get().strip()
            members = [pid for pid, v in member_vars.items() if v.get()]
            if not re.fullmatch(r"[A-Za-z0-9_-]+", name or ""):
                messagebox.showerror("Combo", "Nom invalide.", parent=dlg)
                return
            if len(members) < 2:
                messagebox.showerror("Combo", "Choisis au moins 2 items.", parent=dlg)
                return
            if any(c["name"] == name for c in self.combos) or name in self.profile_vars:
                messagebox.showerror("Combo", f"Le nom '{name}' est déjà utilisé.", parent=dlg)
                return
            self.combos.append({"name": name, "members": members})
            self._refresh_combo_list()
            dlg.destroy()

        bf = ttk.Frame(dlg)
        bf.grid(row=3, column=0, columnspan=2, pady=8)
        ttk.Button(bf, text="Ajouter", command=ok).pack(side="left", padx=6)
        ttk.Button(bf, text="Annuler", command=dlg.destroy).pack(side="left")

    def _remove_combo(self) -> None:
        sel = self.combo_list.curselection()
        if not sel:
            return
        del self.combos[sel[0]]
        self._refresh_combo_list()

    # ================= Lancement =================
    def _start(self) -> None:
        self._launch(analyze=False)

    def _analyze(self) -> None:
        self._launch(analyze=True)

    def _launch(self, analyze: bool) -> None:
        if self.proc is not None:
            return
        source = self.source_var.get().strip()
        dest = self.dest_var.get().strip()
        selected = [pid for pid, var in self.profile_vars.items() if var.get()]

        if not source or not os.path.isdir(source):
            messagebox.showerror("Dossier manquant", "Choisis d'abord le dossier de tes texture packs (étape 1).")
            return
        if not selected and not self.combos:
            messagebox.showerror("Rien à extraire", "Coche au moins un item (étape 2), ou crée un combo.")
            return

        dry = analyze or self.dry_run_var.get()
        self._analyze_mode = analyze

        if not dry:
            if self.clean_before_var.get():
                self._clean_dest(dest)
            Path(dest).mkdir(parents=True, exist_ok=True)

        if FROZEN:
            cmd = [sys.executable, "--extract-cli"]
        else:
            cmd = [sys.executable, "-u", str(RUN_PY)]
        cmd += ["--source", source, "--dest-root", dest, "--profiles-dir", str(PROFILES_DIR),
                "--workers", str(self.workers_var.get())]
        if selected:
            cmd += ["--profiles", *selected]
        for c in self.combos:
            cmd += ["--combo", f"{c['name']}={','.join(c['members'])}"]
        if self.combos and self.require_all_var.get():
            cmd.append("--combo-require-all")
        if self.verbose_var.get():
            cmd.append("-v")
        if dry:
            cmd.append("--dry-run")
        if self.keep_original_var.get():
            cmd.append("--keep-original")
        if self.contact_sheet_var.get():
            cmd.append("--contact-sheet")

        self._save_config()
        for item in self.recap.get_children():
            self.recap.delete(item)
        self._last_packs = 0
        self.progress.config(value=0, maximum=1)
        self._append(f"$ {' '.join(cmd)}\n\n")
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("🔎 Analyse en cours…" if analyze else "⏳ Extraction en cours…")
        threading.Thread(target=self._run_worker, args=(cmd,), daemon=True).start()

    def _clean_dest(self, dest: str) -> None:
        p = Path(dest)
        if not p.is_dir():
            return
        for d in p.glob("pack_folder_*"):
            shutil.rmtree(d, ignore_errors=True)
        try:
            (p / "report.csv").unlink()
        except FileNotFoundError:
            pass
        except Exception:
            pass

    def _run_worker(self, cmd: list[str]) -> None:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self.proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, cwd=str(ROOT),
                env=env, text=True, encoding="utf-8", errors="replace", bufsize=1,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
        except Exception as exc:
            self.log_queue.put(f"\n[Erreur de lancement] {exc}\n")
            self.log_queue.put("__DONE__")
            return
        assert self.proc.stdout is not None
        for line in self.proc.stdout:
            self.log_queue.put(line)
        self.proc.wait()
        self.log_queue.put(f"\n=== Terminé (code {self.proc.returncode}) ===\n")
        self.log_queue.put("__DONE__")

    def _stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._append("\n[Arrêt demandé]\n")

    # ================= Journal / progression =================
    def _poll_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__DONE__":
                    self._on_finished()
                else:
                    self._handle_line(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _handle_line(self, line: str) -> None:
        m = PROGRESS_RE.search(line)
        if m:
            done, total = int(m.group(1)), int(m.group(2))
            name = (m.group(3) or "").strip()
            self.progress.config(maximum=max(total, 1), value=done)
            tail = f" — {name}" if name else ""
            self.status_var.set(f"⏳ {done}/{total}{tail}")
            return
        pk = PACKS_RE.search(line)
        if pk:
            self._last_packs = int(pk.group(1))
            return
        s = SUMMARY_RE.search(line)
        if s:
            self.recap.insert("", "end", text=s.group(1), values=(s.group(2), s.group(3), s.group(4)))
        self._append(line)

    def _on_finished(self) -> None:
        self.proc = None
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        rows = self.recap.get_children()
        total_created = sum(int(self.recap.item(i, "values")[0]) for i in rows)
        total_dup = sum(int(self.recap.item(i, "values")[1]) for i in rows)
        if self._analyze_mode:
            lines = [f"{self.recap.item(i, 'text')} : {self.recap.item(i, 'values')[0]} unique(s)"
                     f", {self.recap.item(i, 'values')[1]} doublon(s)" for i in rows]
            self.status_var.set(f"🔎 Analyse terminée — {self._last_packs} pack(s) source.")
            messagebox.showinfo(
                "Analyse",
                f"{self._last_packs} pack(s) source détecté(s).\n\n" + ("\n".join(lines) or "Aucun item trouvé."),
            )
        else:
            self.status_var.set(f"✅ Terminé — {total_created} pack(s) créé(s), {total_dup} doublon(s) ignoré(s).")
            if self.open_after_var.get() and not self.dry_run_var.get() and total_created:
                self._open_dest()

    def _append(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    # ================= Dépendances (#4) =================
    def _check_deps(self) -> None:
        try:
            import PIL  # noqa: F401
            return
        except Exception:
            pass
        if messagebox.askyesno(
            "Dépendance manquante",
            "Le module 'Pillow' (génération des icônes) est requis mais introuvable.\n\nL'installer maintenant ?",
        ):
            self._append("Installation de Pillow…\n")
            threading.Thread(target=self._pip_install, args=(["Pillow"],), daemon=True).start()

    def _pip_install(self, packages: list[str]) -> None:
        cmd = [sys.executable, "-m", "pip", "install", *packages]
        try:
            proc = subprocess.run(cmd, capture_output=True, text=True,
                                  creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0))
            self.log_queue.put(proc.stdout + proc.stderr + "\n")
            self.log_queue.put("Installation terminée. Relance l'application si besoin.\n")
        except Exception as exc:
            self.log_queue.put(f"Échec de l'installation : {exc}\n")

    # ================= Ouvrir / aperçu =================
    def _open_path(self, path: str) -> None:
        try:
            os.startfile(path)
        except AttributeError:
            subprocess.Popen(["xdg-open", path])

    def _open_dest(self) -> None:
        dest = self.dest_var.get()
        if not dest or not os.path.isdir(dest):
            messagebox.showwarning("Dossier introuvable", "Le dossier de sortie n'existe pas encore.")
            return
        self._open_path(dest)

    def _open_csv(self) -> None:
        csv_path = Path(self.dest_var.get()) / "report.csv"
        if not csv_path.is_file():
            messagebox.showwarning("Rapport introuvable", "Aucun rapport pour l'instant.")
            return
        self._open_path(str(csv_path))

    def _preview_icons(self) -> None:
        dest = self.dest_var.get()
        folder = filedialog.askdirectory(title="Choisir un dossier d'items (pack_folder_…)", initialdir=dest or str(ROOT))
        if not folder:
            return
        folder_path = Path(folder)
        sheet = folder_path / "contact_sheet.png"
        if not sheet.is_file():
            try:
                from contact_sheet import build_contact_sheet
                if build_contact_sheet(folder_path) is None:
                    messagebox.showinfo("Aperçu", "Aucune icône trouvée dans ce dossier.")
                    return
            except Exception as exc:
                messagebox.showerror("Aperçu", f"Génération impossible : {exc}")
                return
        self._show_image(sheet)

    def _show_image(self, path: Path) -> None:
        try:
            from PIL import Image, ImageTk
        except Exception:
            self._open_path(str(path))
            return
        win = tk.Toplevel(self)
        win.title(path.name)
        img = Image.open(path)
        if max(img.size) > 900:
            ratio = 900 / max(img.size)
            img = img.resize((int(img.width * ratio), int(img.height * ratio)), Image.NEAREST)
        photo = ImageTk.PhotoImage(img)
        lbl = ttk.Label(win, image=photo)
        lbl.image = photo
        lbl.pack()

    # ================= Raccourcis (#10) =================
    def _bind_shortcuts(self) -> None:
        self.bind("<Control-Return>", lambda e: self._start())
        self.bind("<Escape>", lambda e: self._stop())

    # ================= Config (#4 + #9) =================
    def _save_config(self) -> None:
        cfg = {
            "geometry": self.geometry(),
            "source": self.source_var.get(), "dest": self.dest_var.get(),
            "selected": [pid for pid, v in self.profile_vars.items() if v.get()],
            "workers": self.workers_var.get(), "verbose": self.verbose_var.get(),
            "dry_run": self.dry_run_var.get(), "keep_original": self.keep_original_var.get(),
            "contact_sheet": self.contact_sheet_var.get(), "require_all": self.require_all_var.get(),
            "clean_before": self.clean_before_var.get(), "open_after": self.open_after_var.get(),
            "combos": self.combos,
        }
        try:
            CONFIG_PATH.write_text(json.dumps(cfg, ensure_ascii=False, indent=2), encoding="utf-8")
        except Exception:
            pass

    def _load_config(self) -> None:
        if not CONFIG_PATH.is_file():
            return
        try:
            cfg = json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
        except Exception:
            return
        if cfg.get("geometry"):
            try:
                self.geometry(cfg["geometry"])
            except Exception:
                pass
        self.source_var.set(cfg.get("source", self.source_var.get()))
        self.dest_var.set(cfg.get("dest", self.dest_var.get()))
        self.workers_var.set(cfg.get("workers", 8))
        self.verbose_var.set(cfg.get("verbose", False))
        self.dry_run_var.set(cfg.get("dry_run", False))
        self.keep_original_var.set(cfg.get("keep_original", False))
        self.contact_sheet_var.set(cfg.get("contact_sheet", True))
        self.require_all_var.set(cfg.get("require_all", False))
        self.clean_before_var.set(cfg.get("clean_before", False))
        self.open_after_var.set(cfg.get("open_after", True))
        self.combos = cfg.get("combos", [])
        self._refresh_combo_list()
        selected = cfg.get("selected")
        if selected is not None:
            sel = set(selected)
            for pid, v in self.profile_vars.items():
                v.set(pid in sel)

    def _on_close(self) -> None:
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Quitter", "Une extraction est en cours. Quitter quand même ?"):
                return
            self.proc.terminate()
        self._save_config()
        self.destroy()


def _maybe_run_cli() -> bool:
    """Si lancé avec --extract-cli (cas de l'exécutable figé), agit comme le
    moteur en ligne de commande et retourne True."""
    if "--extract-cli" in sys.argv:
        sys.argv.remove("--extract-cli")
        from run import main as run_main
        sys.exit(run_main(sys.argv[1:]))
    return False


if __name__ == "__main__":
    if not _maybe_run_cli():
        ExtractorGUI().mainloop()
