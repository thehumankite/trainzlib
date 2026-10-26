#!/usr/bin/env python3
"""TrainzLib GUI: inspect, preview and export Trainz models (.trainzmesh / .im, optional .kin animation)."""
import contextlib
import io
import os
import queue
import threading
import traceback
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import trainzlib
import i18n
import theme
from i18n import tr
from model_viewer import ModelViewer
from theme import Card

ACTIONS = (
    ("info", "Info"),
    ("obj", "OBJ"),
    ("glb", "GLB"),
    ("im-preserve", "glTF empties"),
)
ACTION_HELP = {
    "info": "Print a report of the model, its skeleton and whether it has animation.",
    "obj": "Wavefront OBJ. If there is an animation you can pose the model at a chosen frame.",
    "glb": "Single-file glTF binary with a skin. Includes the animation when there is one.",
    "im-preserve": "glTF + .bin keeping the original bone hierarchy and attachment points as plain nodes.",
}
ANIM_CHOICES = (
    ("auto", "Auto-detect"),
    ("yes", "Yes, it's animated"),
    ("no", "No, static model"),
)
ANIM_HELP = {
    "auto": "Uses a .kin you pick, or one with the same name beside the model. Otherwise exports static.",
    "yes": "Uses your .kin. If it's missing or doesn't fit the bones, falls back to static and says why.",
    "no": "Ignores any .kin and exports a static model with no animation track.",
}


class TrainzLibGUI(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(tr("TrainzLib: Trainz Model Converter"))
        self.geometry("1180x860")
        self.minsize(920, 720)
        theme.apply_theme(self)
        theme.set_icon(self)

        self.mesh_path = tk.StringVar()
        self.kin_path = tk.StringVar()
        self.output_path = tk.StringVar()
        self.command = tk.StringVar(value="info")
        self.anim_mode = tk.StringVar(value="auto")
        self.frame = tk.StringVar(value="0")
        self.status = tk.StringVar(value=tr("Choose a .trainzmesh or .im file to begin."))
        self._events = queue.Queue()
        self._kin_widgets = []
        self._check_job = None

        self._build()
        self.after(60, self._poll)
        theme.enable_dark_titlebar(self)

    # ------------------------------------------------------------------ layout
    def _build(self):
        head = ttk.Frame(self, padding=(22, 14, 22, 8))
        head.pack(fill="x")
        theme.logo(head, 44).pack(side="left", padx=(0, 14))
        titles = ttk.Frame(head)
        titles.pack(side="left")
        ttk.Label(titles, text="TrainzLib", style="Title.TLabel").pack(anchor="w")
        ttk.Label(titles, text=tr("Inspect, preview and export Trainz models"), style="Muted.TLabel").pack(anchor="w")

        tk.Frame(self, background=theme.ACCENT, height=2).pack(fill="x", padx=22, pady=(0, 6))   # brass coachline
        ttk.Label(self, textvariable=self.status, style="Status.TLabel", padding=(24, 8, 24, 10)).pack(side="bottom", fill="x")
        self.tabs = ttk.Notebook(self)
        self.tabs.pack(fill="both", expand=True, padx=22, pady=(4, 0))
        converter = ttk.Frame(self.tabs, style="Card.TFrame")
        viewer_tab = ttk.Frame(self.tabs, style="Card.TFrame")
        self.tabs.add(converter, text=tr("Converter"))
        self.tabs.add(viewer_tab, text=tr("3D Viewer"))

        # ---- converter: left column (settings) + right column (log)
        converter.columnconfigure(0, weight=0, minsize=500)
        converter.columnconfigure(1, weight=1)
        converter.rowconfigure(0, weight=1)
        left = ttk.Frame(converter, style="Card.TFrame", padding=(14, 14, 7, 14))
        left.grid(row=0, column=0, sticky="nsew")
        right = ttk.Frame(converter, style="Card.TFrame", padding=(7, 14, 14, 14))
        right.grid(row=0, column=1, sticky="nsew")

        self._build_runbar(left)          # packed first, to the bottom, so Run is always visible
        self._build_inputs(left)
        self._build_animation(left)
        self._build_export(left)
        self._build_log(right)

        self.viewer = ModelViewer(viewer_tab, lambda: self.mesh_path.get(), lambda: self.kin_path.get(),
                                  lambda: self.anim_mode.get(), self.append_log)
        self.viewer.pack(fill="both", expand=True)

        self._on_anim_mode()
        self._on_action()

    def _file_row(self, parent, label, variable, command, store_kin=False):
        row = ttk.Frame(parent, style="Card.TFrame")
        row.pack(fill="x", pady=3)
        ttk.Label(row, text=tr(label), style="Key.TLabel", width=11).pack(side="left", anchor="w")
        entry = ttk.Entry(row, textvariable=variable)
        entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        btn = ttk.Button(row, text=tr("Browse"), command=command, padding=(12, 5))
        btn.pack(side="left")
        if store_kin:
            self._kin_widgets += [entry, btn]
        return entry

    def _build_inputs(self, parent):
        card = Card(parent, tr("Input files"))
        card.pack(fill="x", pady=(0, 10))
        self._file_row(card.body, "Model", self.mesh_path, self.pick_mesh)
        self._file_row(card.body, "Anim. (.kin)", self.kin_path, self.pick_kin, store_kin=True)
        self.mesh_path.trace_add("write", lambda *_: self._schedule_check())
        self.kin_path.trace_add("write", lambda *_: self._schedule_check())

    def _build_animation(self, parent):
        card = Card(parent, tr("Does this .im have animation?"),
                    tr("A missing or mismatched .kin never causes an error."))
        card.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(card.body, style="Card.TFrame")
        row.pack(fill="x")
        for value, label in ANIM_CHOICES:
            ttk.Radiobutton(row, text=tr(label), value=value, variable=self.anim_mode, style="Seg.Toolbutton",
                            command=self._on_anim_mode).pack(side="left", padx=(0, 2), ipadx=2)
        self.anim_help = ttk.Label(card.body, text="", style="CardMuted.TLabel", wraplength=440, justify="left")
        self.anim_help.pack(anchor="w", pady=(8, 8))
        result = tk.Frame(card.body, background=theme.FIELD, highlightthickness=1, highlightbackground=theme.BORDER)
        result.pack(fill="x")
        self.verdict_dot = tk.Label(result, text="●", background=theme.FIELD, foreground=theme.MUTED, font=(theme.family(), 12))
        self.verdict_dot.pack(side="left", padx=(10, 6), pady=8, anchor="n")
        self.verdict = tk.Label(result, text=tr("Choose a model to check it for animation."), background=theme.FIELD,
                                foreground=theme.FG, wraplength=355, justify="left", anchor="w", font=(theme.family(), 9))
        self.verdict.pack(side="left", fill="x", expand=True, pady=8)
        ttk.Button(result, text=tr("Check"), command=self.check_animation, padding=(10, 4)).pack(side="right", padx=8)

    def _build_export(self, parent):
        card = Card(parent, tr("Export"))
        card.pack(fill="x", pady=(0, 10))
        row = ttk.Frame(card.body, style="Card.TFrame")
        row.pack(fill="x")
        for value, label in ACTIONS:
            ttk.Radiobutton(row, text=tr(label), value=value, variable=self.command, style="Seg.Toolbutton",
                            command=self._on_action).pack(side="left", padx=(0, 2), ipadx=2)
        self.action_help = ttk.Label(card.body, text="", style="CardMuted.TLabel", wraplength=440, justify="left")
        self.action_help.pack(anchor="w", pady=(8, 6))
        rows = ttk.Frame(card.body, style="Card.TFrame")
        rows.pack(fill="x")
        rows.columnconfigure(0, weight=1)
        self.frame_row = ttk.Frame(rows, style="Card.TFrame")
        self.frame_row.grid(row=0, column=0, sticky="ew", pady=2)
        ttk.Label(self.frame_row, text=tr("Pose frame"), style="Key.TLabel", width=11).pack(side="left")
        self.frame_entry = ttk.Entry(self.frame_row, textvariable=self.frame, width=8)
        self.frame_entry.pack(side="left")
        ttk.Label(self.frame_row, text=tr("OBJ only, needs an animation"), style="CardMuted.TLabel").pack(side="left", padx=10)
        self.out_row = ttk.Frame(rows, style="Card.TFrame")
        self.out_row.grid(row=1, column=0, sticky="ew", pady=2)
        ttk.Label(self.out_row, text=tr("Output"), style="Key.TLabel", width=11).pack(side="left")
        self.out_entry = ttk.Entry(self.out_row, textvariable=self.output_path)
        self.out_entry.pack(side="left", fill="x", expand=True, padx=(0, 8))
        self.out_btn = ttk.Button(self.out_row, text=tr("Browse"), command=self.pick_output, padding=(12, 5))
        self.out_btn.pack(side="left")

    def _build_runbar(self, parent):
        foot = ttk.Frame(parent, style="Card.TFrame")
        foot.pack(side="bottom", fill="x")
        bar = ttk.Frame(foot, style="Card.TFrame")
        bar.pack(fill="x", pady=(2, 0))
        self.run_btn = ttk.Button(bar, text=tr("Run"), style="Accent.TButton", command=self.run)
        self.run_btn.pack(side="left")
        ttk.Button(bar, text=tr("Open in 3D viewer"), command=self.load_in_viewer).pack(side="left", padx=8)
        self.progress = ttk.Progressbar(foot, mode="indeterminate", style="Horizontal.TProgressbar")
        self.progress.pack(fill="x", pady=(12, 0))

    def _build_log(self, parent):
        card = Card(parent, tr("Activity"))
        card.pack(fill="both", expand=True)
        box = ttk.Frame(card.body, style="Card.TFrame")
        box.pack(fill="both", expand=True)
        self.log = tk.Text(box, wrap="word", state="disabled", font=(theme.mono(), 10), background=theme.FIELD,
                           foreground=theme.FG, insertbackground=theme.FG, relief="flat", padx=12, pady=10,
                           highlightthickness=1, highlightbackground=theme.BORDER, selectbackground=theme.ACCENT_DIM)
        sb = ttk.Scrollbar(box, orient="vertical", command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        self.log.pack(side="left", fill="both", expand=True)
        for tag, color in (("muted", theme.MUTED), ("ok", theme.GOOD), ("warn", theme.WARN), ("err", theme.BAD), ("cmd", theme.ACCENT_HOVER)):
            self.log.tag_configure(tag, foreground=color)
        ttk.Button(card.body, text=tr("Clear"), command=self.clear_log, padding=(12, 4)).pack(anchor="e", pady=(8, 0))

    # ------------------------------------------------------------------ reactions
    def _on_anim_mode(self):
        mode = self.anim_mode.get()
        self.anim_help.configure(text=tr(ANIM_HELP[mode]))
        for w in self._kin_widgets:
            w.configure(state="disabled" if mode == "no" else "normal")
        self._schedule_check()

    def _on_action(self):
        action = self.command.get()
        self.action_help.configure(text=tr(ACTION_HELP[action]))
        if action == "obj":
            self.frame_row.grid()
        else:
            self.frame_row.grid_remove()
        if action == "info":
            self.out_row.grid_remove()
        else:
            self.out_row.grid()
            self.suggest_output()

    def pick_mesh(self):
        path = filedialog.askopenfilename(title=tr("Select Trainz mesh/model"),
                                          filetypes=[(tr("Trainz models"), "*.trainzmesh *.im"), (tr("All files"), "*.*")])
        if path:
            self.mesh_path.set(path)
            self.status.set(tr("Model selected."))
            if self.command.get() != "info":
                self.suggest_output()

    def pick_kin(self):
        path = filedialog.askopenfilename(title=tr("Select Trainz animation"),
                                          filetypes=[(tr("Trainz animation"), "*.kin"), (tr("All files"), "*.*")])
        if path:
            self.kin_path.set(path)

    def suggest_output(self):
        mesh = self.mesh_path.get()
        if mesh:
            ext = {"obj": ".obj", "glb": ".glb", "im-preserve": ".gltf"}.get(self.command.get())
            if ext:
                self.output_path.set(os.path.splitext(mesh)[0] + ext)

    def pick_output(self):
        action = self.command.get()
        types, default = {
            "obj": ([(tr("Wavefront OBJ"), "*.obj")], ".obj"),
            "im-preserve": ([(tr("glTF JSON"), "*.gltf")], ".gltf"),
        }.get(action, ([(tr("glTF binary"), "*.glb")], ".glb"))
        path = filedialog.asksaveasfilename(title=tr("Choose output file"), defaultextension=default,
                                            filetypes=types + [(tr("All files"), "*.*")])
        if path:
            self.output_path.set(path)

    def load_in_viewer(self):
        self.tabs.select(1)
        self.viewer.load_model()

    # ------------------------------------------------------------------ animation check
    def _schedule_check(self):
        if self._check_job:
            self.after_cancel(self._check_job)
        self._check_job = self.after(350, lambda: self.check_animation(quiet=True))

    def check_animation(self, quiet=False):
        """Answer 'does this model have animation?' for the chosen model + mode; never raises."""
        self._check_job = None
        path, kin_path, mode = self.mesh_path.get().strip(), self.kin_path.get().strip(), self.anim_mode.get()
        if not path:
            return self._set_verdict("Choose a model to check it for animation.", theme.MUTED)
        if not os.path.isfile(path):
            return self._set_verdict("That model file doesn't exist.", theme.BAD)
        try:
            mesh = trainzlib.load_mesh(path)
        except Exception as exc:
            return self._set_verdict(f"Couldn't read the model ({type(exc).__name__}).", theme.BAD)
        kin, notes = trainzlib.resolve_animation(mesh, kin_path, mode, path)
        if mesh.get("src") != "im":
            text = notes[-1]
            colour = theme.GOOD if kin else theme.MUTED
        else:
            rep = trainzlib.im_animation_report(mesh, kin)
            text = rep["verdict"]
            problem = notes[-1] if any(w in notes[-1] for w in ("not match", "could not", "marked")) else ""
            if problem and not kin:
                text += "\n" + problem
            if mode == "no":
                text, colour = "Animation turned off: this will export as a static model.", theme.MUTED
            elif kin:
                colour = theme.GOOD
            elif not rep["has_skeleton"]:
                colour = theme.MUTED
            else:
                colour = theme.WARN
        self._set_verdict(text, colour)
        if not quiet:
            self.append_log(self._clean(text), "ok" if colour == theme.GOOD else "warn" if colour == theme.WARN else "muted")

    @staticmethod
    def _clean(text):
        """Translate for display and drop the 'Animation: ' prefix (English or Chinese) from each line."""
        return "\n".join(i18n.strip_animation_prefix(line) for line in tr(text).split("\n"))

    def _set_verdict(self, text, colour):
        self.verdict.configure(text=self._clean(text))
        self.verdict_dot.configure(foreground=colour)

    # ------------------------------------------------------------------ log
    def append_log(self, text, tag=None):
        if tag is None:
            t = text.strip()
            if t.startswith("Traceback") or "Error" in t[:40]:
                tag = "err"
            elif t.startswith("Animation:") and any(w in t for w in ("not match", "could not", "marked")):
                tag = "warn"
            elif t.startswith("Animation:") or t.startswith(">"):
                tag = "cmd" if t.startswith(">") else "muted"
            elif t.startswith("Done") or t.startswith("Exported"):
                tag = "ok"
        self.log.configure(state="normal")
        self.log.insert("end", tr(text.rstrip()) + "\n", tag or ())
        self.log.see("end")
        self.log.configure(state="disabled")

    def clear_log(self):
        self.log.configure(state="normal")
        self.log.delete("1.0", "end")
        self.log.configure(state="disabled")

    # ------------------------------------------------------------------ run
    def run(self):
        mesh_path = self.mesh_path.get().strip()
        kin_path = self.kin_path.get().strip()
        action = self.command.get()
        mode = self.anim_mode.get()
        output = self.output_path.get().strip()

        if not mesh_path:
            return messagebox.showerror(tr("Missing input"), tr("Choose a .trainzmesh or .im file first."))
        if not os.path.isfile(mesh_path):
            return messagebox.showerror(tr("File not found"), tr("The selected model file does not exist."))
        if action != "info" and not output:
            return messagebox.showerror(tr("Missing output"), tr("Choose an output file."))
        frame = 0.0
        if action == "obj" and self.frame.get().strip():
            try:
                frame = float(self.frame.get().strip())
            except ValueError:
                return messagebox.showerror(tr("Invalid frame"), tr("Pose frame must be a number, such as 0 or 7.5."))

        self.run_btn.configure(state="disabled")
        self.progress.configure(mode="indeterminate")
        self.progress.start(12)
        self.status.set(tr("Working…"))
        self.append_log(f"> {tr(dict(ACTIONS)[action])}   {os.path.basename(mesh_path)}")
        threading.Thread(target=self._worker, args=(action, mesh_path, kin_path, mode, output, frame), daemon=True).start()

    def _worker(self, action, mesh_path, kin_path, mode, output, frame):
        try:
            mesh = trainzlib.load_mesh(mesh_path)
            # Safe animation handling: missing / wrong / corrupt .kin becomes a static export, never an error.
            kin, notes = trainzlib.resolve_animation(mesh, kin_path, mode, mesh_path, localize=(action != "im-preserve"))
            for n in notes:
                self._events.put(("log", n, None))
            out = []
            if action == "im-preserve":
                trainzlib.write_gltf_empty_nodes(output, mesh, kin)
                out.append(f"Exported glTF with empty transform nodes: {output}")
                out.append(f"Companion buffer: {os.path.splitext(output)[0]}.bin")
                out.append(f"Attachment empties: {len(mesh.get('attachments', []))}"
                           + (" (" + ", ".join(a['name'] for a in mesh['attachments']) + ")" if mesh.get('attachments') else ""))
                out.append(f"Hierarchy nodes: {len(mesh['bones'])}; submeshes: {len(mesh['subs'])}; "
                           f"triangles: {sum(len(s['tris']) for s in mesh['subs'])}")
                out.append("Bone names and hierarchy are kept as ordinary nodes; no skin or joints."
                           if kin else "Static export: no animation track written.")
            elif action == "info":
                buf = io.StringIO()
                with contextlib.redirect_stdout(buf):
                    trainzlib.info(mesh, kin)
                out.append(buf.getvalue())
            elif action == "obj":
                P = N = None
                if kin:
                    names, parents, rec = trainzlib.bone_tables(mesh)
                    S = trainzlib.skin_mats(parents, rec, trainzlib.sample(kin, frame))
                    P, N = zip(*[trainzlib.skin_verts(s["v"], S) for s in mesh["subs"]])
                trainzlib.write_obj(output, mesh, P, N)
                out.append(f"Exported OBJ: {output}")
                if not kin:
                    out.append("Static export: pose frame ignored (no animation).")
            elif action == "glb":
                trainzlib.write_glb(output, mesh, kin)
                out.append(f"Exported GLB: {output}")
                if not kin:
                    out.append("Static export: no animation track written.")
            out.append("Done.")
            self._events.put(("done", True, "\n".join(out)))
        except Exception:
            self._events.put(("done", False, traceback.format_exc()))

    def _poll(self):
        try:
            while True:
                kind, a, b = self._events.get_nowait()
                if kind == "log":
                    self.append_log(a, b)
                else:
                    self._finish(a, b)
        except queue.Empty:
            pass
        self.after(60, self._poll)

    def _finish(self, success, output):
        self.progress.stop()
        self.progress.configure(mode="determinate", value=0)
        self.run_btn.configure(state="normal")
        self.append_log(output, None if success else "err")
        self.status.set(tr("Finished.") if success else tr("Failed. See the activity log."))
        if not success:
            messagebox.showerror(tr("Operation failed"), output.strip().splitlines()[-1])


if __name__ == "__main__":
    try:
        import numpy  # noqa: F401
    except ImportError:
        root = tk.Tk()
        root.withdraw()
        messagebox.showerror("Missing dependency", "NumPy is required.\n\nInstall it with:\npython -m pip install numpy")
        raise
    lang = i18n.lang_from_argv() or i18n.choose_language()      # asked on every start; --lang en|zh skips the question
    if lang is None:
        raise SystemExit(0)
    i18n.set_lang(lang)
    theme.reset_fonts()
    TrainzLibGUI().mainloop()
