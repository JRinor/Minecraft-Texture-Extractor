#!/usr/bin/env python3
"""Interface graphique pour le Texture Pack Extractor V2.

Lance `texture_extractor_v2/run.py` en sous-processus avec les options
choisies dans la fenêtre, et affiche les logs en direct.

Démarrage :
    python gui.py
(ou double-clic sur lancer_gui.bat)

Aucune dépendance supplémentaire : Tkinter est inclus avec Python.
"""

from __future__ import annotations

import json
import os
import queue
import subprocess
import sys
import threading
from pathlib import Path

import tkinter as tk
from tkinter import filedialog, messagebox, ttk
from tkinter.scrolledtext import ScrolledText

ROOT = Path(__file__).resolve().parent
RUN_PY = ROOT / "texture_extractor_v2" / "run.py"
PROFILES_DIR = ROOT / "profiles"
DEFAULT_SOURCE = ROOT / "packs_source"
DEFAULT_DEST = ROOT / "packs_generes"


def load_profile_list() -> list[tuple[str, str]]:
    """Retourne [(id, display_name), ...] trié par id, lu depuis profiles/."""
    profiles: list[tuple[str, str]] = []
    if PROFILES_DIR.is_dir():
        for jf in sorted(PROFILES_DIR.glob("*.json")):
            try:
                data = json.loads(jf.read_text(encoding="utf-8"))
                pid = data["id"]
                name = data.get("display_name", pid)
                profiles.append((pid, name))
            except Exception:
                # Profil illisible : on l'ignore silencieusement dans la liste.
                continue
    return profiles


class ExtractorGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("Minecraft Texture Extractor")
        self.geometry("860x720")
        self.minsize(720, 600)

        self.proc: subprocess.Popen | None = None
        self.log_queue: queue.Queue[str] = queue.Queue()
        self.profile_vars: dict[str, tk.BooleanVar] = {}

        self._build_ui()
        self.after(100, self._poll_log)
        self.protocol("WM_DELETE_WINDOW", self._on_close)

    # ---------- Construction de l'interface ----------
    def _build_ui(self) -> None:
        pad = {"padx": 8, "pady": 4}

        # --- Dossiers ---
        folders = ttk.LabelFrame(self, text="Dossiers")
        folders.pack(fill="x", **pad)

        ttk.Label(folders, text="Packs source :").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.source_var = tk.StringVar(value=str(DEFAULT_SOURCE))
        ttk.Entry(folders, textvariable=self.source_var).grid(row=0, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(folders, text="Parcourir…", command=self._pick_source).grid(row=0, column=2, padx=6, pady=4)

        ttk.Label(folders, text="Dossier de sortie :").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.dest_var = tk.StringVar(value=str(DEFAULT_DEST))
        ttk.Entry(folders, textvariable=self.dest_var).grid(row=1, column=1, sticky="ew", padx=6, pady=4)
        ttk.Button(folders, text="Parcourir…", command=self._pick_dest).grid(row=1, column=2, padx=6, pady=4)

        folders.columnconfigure(1, weight=1)

        # --- Profils ---
        prof_frame = ttk.LabelFrame(self, text="Items à extraire (profils)")
        prof_frame.pack(fill="x", **pad)

        btns = ttk.Frame(prof_frame)
        btns.pack(fill="x", padx=6, pady=(6, 0))
        ttk.Button(btns, text="Tout cocher", command=lambda: self._set_all(True)).pack(side="left", padx=(0, 6))
        ttk.Button(btns, text="Tout décocher", command=lambda: self._set_all(False)).pack(side="left")

        grid = ttk.Frame(prof_frame)
        grid.pack(fill="x", padx=6, pady=6)

        profiles = load_profile_list()
        if not profiles:
            ttk.Label(grid, text="Aucun profil trouvé dans profiles/").grid(row=0, column=0, sticky="w")
        cols = 3
        for i, (pid, name) in enumerate(profiles):
            var = tk.BooleanVar(value=True)
            self.profile_vars[pid] = var
            cb = ttk.Checkbutton(grid, text=f"{name}  ({pid})", variable=var)
            cb.grid(row=i // cols, column=i % cols, sticky="w", padx=6, pady=2)
        for c in range(cols):
            grid.columnconfigure(c, weight=1)

        # --- Options ---
        opts = ttk.LabelFrame(self, text="Options")
        opts.pack(fill="x", **pad)

        ttk.Label(opts, text="Threads (workers) :").grid(row=0, column=0, sticky="w", padx=6, pady=4)
        self.workers_var = tk.IntVar(value=8)
        ttk.Spinbox(opts, from_=1, to=64, textvariable=self.workers_var, width=6).grid(row=0, column=1, sticky="w", padx=6, pady=4)

        self.verbose_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(opts, text="Logs détaillés (verbose)", variable=self.verbose_var).grid(row=0, column=2, sticky="w", padx=20, pady=4)

        # --- Mode combiné ---
        combo = ttk.LabelFrame(self, text="Mode combiné")
        combo.pack(fill="x", padx=8, pady=4)

        self.combine_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(
            combo,
            text="Réunir les items cochés dans UN seul pack (ex: épée + arc ensemble)",
            variable=self.combine_var,
            command=self._toggle_combine,
        ).grid(row=0, column=0, columnspan=4, sticky="w", padx=6, pady=4)

        ttk.Label(combo, text="Nom du combo :").grid(row=1, column=0, sticky="w", padx=6, pady=4)
        self.combine_name_var = tk.StringVar(value="combo")
        self.combine_name_entry = ttk.Entry(combo, textvariable=self.combine_name_var, width=24, state="disabled")
        self.combine_name_entry.grid(row=1, column=1, sticky="w", padx=6, pady=4)

        self.require_all_var = tk.BooleanVar(value=False)
        self.require_all_cb = ttk.Checkbutton(
            combo,
            text="Uniquement si TOUS les items cochés sont présents dans le pack",
            variable=self.require_all_var,
            state="disabled",
        )
        self.require_all_cb.grid(row=1, column=2, sticky="w", padx=20, pady=4)

        # --- Actions ---
        actions = ttk.Frame(self)
        actions.pack(fill="x", **pad)
        self.run_btn = ttk.Button(actions, text="▶  Lancer l'extraction", command=self._start)
        self.run_btn.pack(side="left")
        self.stop_btn = ttk.Button(actions, text="■  Arrêter", command=self._stop, state="disabled")
        self.stop_btn.pack(side="left", padx=8)
        ttk.Button(actions, text="📂  Ouvrir le dossier de sortie", command=self._open_dest).pack(side="left", padx=8)
        ttk.Button(actions, text="Effacer les logs", command=self._clear_log).pack(side="right")

        # --- Logs ---
        log_frame = ttk.LabelFrame(self, text="Journal")
        log_frame.pack(fill="both", expand=True, **pad)
        self.log = ScrolledText(log_frame, height=16, wrap="word", state="disabled",
                                font=("Consolas", 9))
        self.log.pack(fill="both", expand=True, padx=6, pady=6)

        self.status_var = tk.StringVar(value="Prêt.")
        ttk.Label(self, textvariable=self.status_var, relief="sunken", anchor="w").pack(fill="x", side="bottom")

    # ---------- Sélecteurs de dossier ----------
    def _pick_source(self) -> None:
        d = filedialog.askdirectory(title="Choisir le dossier des packs source",
                                    initialdir=self.source_var.get() or str(ROOT))
        if d:
            self.source_var.set(d)

    def _pick_dest(self) -> None:
        d = filedialog.askdirectory(title="Choisir le dossier de sortie",
                                    initialdir=self.dest_var.get() or str(ROOT))
        if d:
            self.dest_var.set(d)

    def _set_all(self, value: bool) -> None:
        for var in self.profile_vars.values():
            var.set(value)

    def _toggle_combine(self) -> None:
        state = "normal" if self.combine_var.get() else "disabled"
        self.combine_name_entry.config(state=state)
        self.require_all_cb.config(state=state)

    def _open_dest(self) -> None:
        dest = self.dest_var.get()
        if not dest or not os.path.isdir(dest):
            messagebox.showwarning("Dossier introuvable", "Le dossier de sortie n'existe pas encore.")
            return
        try:
            os.startfile(dest)  # Windows
        except AttributeError:
            subprocess.Popen(["xdg-open", dest])

    # ---------- Lancement ----------
    def _start(self) -> None:
        if self.proc is not None:
            return

        source = self.source_var.get().strip()
        dest = self.dest_var.get().strip()
        selected = [pid for pid, var in self.profile_vars.items() if var.get()]

        if not source or not os.path.isdir(source):
            messagebox.showerror("Erreur", "Le dossier des packs source n'existe pas.")
            return
        if not selected:
            messagebox.showerror("Erreur", "Sélectionne au moins un item à extraire.")
            return
        if not RUN_PY.is_file():
            messagebox.showerror("Erreur", f"Script introuvable : {RUN_PY}")
            return

        Path(dest).mkdir(parents=True, exist_ok=True)

        cmd = [
            sys.executable, "-u", str(RUN_PY),
            "--source", source,
            "--dest-root", dest,
            "--workers", str(self.workers_var.get()),
            "--profiles", *selected,
        ]
        if self.verbose_var.get():
            cmd.append("-v")
        if self.combine_var.get():
            combo_name = self.combine_name_var.get().strip() or "combo"
            cmd += ["--combine", "--combine-name", combo_name]
            if self.require_all_var.get():
                cmd.append("--combine-require-all")

        self._append(f"$ {' '.join(cmd)}\n\n")
        self.run_btn.config(state="disabled")
        self.stop_btn.config(state="normal")
        self.status_var.set("Extraction en cours…")

        threading.Thread(target=self._run_worker, args=(cmd,), daemon=True).start()

    def _run_worker(self, cmd: list[str]) -> None:
        env = dict(os.environ)
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            self.proc = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                cwd=str(ROOT),
                env=env,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
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
        code = self.proc.returncode
        self.log_queue.put(f"\n=== Terminé (code {code}) ===\n")
        self.log_queue.put("__DONE__")

    def _stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            self._append("\n[Arrêt demandé]\n")

    # ---------- Journal ----------
    def _poll_log(self) -> None:
        try:
            while True:
                line = self.log_queue.get_nowait()
                if line == "__DONE__":
                    self._on_finished()
                else:
                    self._append(line)
        except queue.Empty:
            pass
        self.after(100, self._poll_log)

    def _on_finished(self) -> None:
        self.proc = None
        self.run_btn.config(state="normal")
        self.stop_btn.config(state="disabled")
        self.status_var.set("Prêt.")

    def _append(self, text: str) -> None:
        self.log.config(state="normal")
        self.log.insert("end", text)
        self.log.see("end")
        self.log.config(state="disabled")

    def _clear_log(self) -> None:
        self.log.config(state="normal")
        self.log.delete("1.0", "end")
        self.log.config(state="disabled")

    def _on_close(self) -> None:
        if self.proc and self.proc.poll() is None:
            if not messagebox.askyesno("Quitter", "Une extraction est en cours. Quitter quand même ?"):
                return
            self.proc.terminate()
        self.destroy()


if __name__ == "__main__":
    ExtractorGUI().mainloop()
