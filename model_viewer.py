"""Embedded software 3D viewer for TrainzLib meshes (Tkinter + NumPy only).

Highlights vs. the first version
  * Trainz is Z-up, so models are shown upright (the glTF export does the same Z-up -> Y-up swap).
  * Whole-mesh shading and depth sorting are vectorised with NumPy (no per-triangle Python shading loop).
  * Draft quality while you drag/zoom, full quality a moment after you let go.
  * Lit flat shading, floor grid, axis gizmo, Solid / Edges / Wire modes, bone names.
  * Works with static models: no .kin, a skeleton-less .im, or a .kin that doesn't fit all load fine.
"""
import math
import time
import tkinter as tk
from tkinter import messagebox, ttk

import numpy as np

import i18n
import theme
import trainzlib
from i18n import tr

DEFAULT_PALETTE = theme.MESH_PALETTE
LIGHT = np.array([-0.45, 0.70, 0.55])
LIGHT = LIGHT / np.linalg.norm(LIGHT)
MODES = (("solid", "Solid"), ("edges", "Edges"), ("wire", "Wire"))


def to_yup(p):
    """Trainz (x, y, z-up) -> viewer (x, z, -y)."""
    p = np.asarray(p, float)
    return np.stack((p[..., 0], p[..., 2], -p[..., 1]), axis=-1)


class ModelViewer(ttk.Frame):
    DRAFT_TRIS = 2500
    FULL_TRIS = 9000

    def __init__(self, parent, get_mesh_path, get_kin_path, get_anim_mode=None, log_callback=None):
        super().__init__(parent, style="Card.TFrame")
        self.get_mesh_path = get_mesh_path
        self.get_kin_path = get_kin_path
        self.get_anim_mode = get_anim_mode or (lambda: "auto")
        self.log_callback = log_callback or (lambda message, tag=None: None)

        self.mesh = None
        self.kin = None
        self.report = None
        self.frame_no = 0.0
        self.playing = False
        self.loop = tk.BooleanVar(value=True)
        self.speed = tk.DoubleVar(value=1.0)
        self.mode = tk.StringVar(value="solid")
        self.show_bones = tk.BooleanVar(value=False)
        self.show_grid = tk.BooleanVar(value=True)
        self.show_names = tk.BooleanVar(value=False)
        self.submesh_var = tk.StringVar(value=tr("All submeshes"))

        self.yaw, self.pitch, self.zoom = 0.7, 0.35, 1.0
        self.pan_x = self.pan_y = 0.0
        self.center = np.zeros(3)
        self.scale = 1.0
        self.floor_y = 0.0

        self._drag = None
        self._render_job = None
        self._quality_job = None
        self._interacting = False
        self._last_tick = 0.0
        self._setting_slider = False
        self._pose_key = None
        self._pose = None
        self._geo = None
        self._build()

    # ------------------------------------------------------------------ UI
    def _build(self):
        bar = ttk.Frame(self, style="Card.TFrame", padding=(10, 10, 10, 6))
        bar.pack(fill="x")
        ttk.Button(bar, text=tr("Load model"), style="Accent.TButton", padding=(14, 6), command=self.load_model).pack(side="left")
        ttk.Button(bar, text=tr("Fit"), command=self.fit_view, padding=(12, 6)).pack(side="left", padx=(6, 14))
        seg = ttk.Frame(bar, style="Card.TFrame")
        seg.pack(side="left")
        for key, label in MODES:
            ttk.Radiobutton(seg, text=tr(label), value=key, variable=self.mode, style="Seg.Toolbutton",
                            command=self.schedule_render).pack(side="left", padx=(0, 1))
        tog = ttk.Frame(bar, style="Card.TFrame")
        tog.pack(side="left", padx=(14, 0))
        for text, var in (("Skeleton", self.show_bones), ("Names", self.show_names), ("Grid", self.show_grid)):
            ttk.Checkbutton(tog, text=tr(text), variable=var, style="Tog.Toolbutton",
                            command=self.schedule_render).pack(side="left", padx=(0, 4))

        body = ttk.Frame(self, style="Card.TFrame")
        body.pack(fill="both", expand=True, padx=10, pady=(0, 6))
        self.canvas = tk.Canvas(body, background=theme.VIEWPORT, highlightthickness=1,
                                highlightbackground=theme.BORDER, cursor="fleur", takefocus=1)
        self.canvas.pack(side="left", fill="both", expand=True)

        side = ttk.Frame(body, style="Card.TFrame", width=250, padding=(14, 0, 2, 0))
        side.pack(side="right", fill="y")
        side.pack_propagate(False)

        ttk.Label(side, text=tr("Model"), style="Heading.TLabel").pack(anchor="w", pady=(2, 6))
        self.info_frame = ttk.Frame(side, style="Card.TFrame")
        self.info_frame.pack(fill="x")
        self._set_info([("File", "—")])

        ttk.Label(side, text=tr("Submesh"), style="Key.TLabel").pack(anchor="w", pady=(12, 3))
        self.submesh_combo = ttk.Combobox(side, textvariable=self.submesh_var, state="readonly", values=(tr("All submeshes"),))
        self.submesh_combo.pack(fill="x")
        self.submesh_combo.bind("<<ComboboxSelected>>", lambda _e: self.schedule_render())

        ttk.Separator(side).pack(fill="x", pady=14)
        ttk.Label(side, text=tr("Animation"), style="Heading.TLabel").pack(anchor="w")
        self.anim_badge = tk.Label(side, text="●  " + tr("No model loaded"), anchor="w", background=theme.SURFACE,
                                   foreground=theme.MUTED, font=(theme.family(), 10, "bold"))
        self.anim_badge.pack(fill="x", pady=(6, 2))
        self.anim_note = ttk.Label(side, text="", style="CardMuted.TLabel", wraplength=225, justify="left")
        self.anim_note.pack(anchor="w", fill="x")

        self.frame_label = ttk.Label(side, text=tr("Frame 0"), style="Key.TLabel")
        self.frame_label.pack(anchor="w", pady=(10, 0))
        self.frame_slider = ttk.Scale(side, from_=0, to=0, orient="horizontal", command=self._slider_moved)
        self.frame_slider.pack(fill="x", pady=(4, 6))
        row = ttk.Frame(side, style="Card.TFrame")
        row.pack(fill="x")
        self.play_btn = ttk.Button(row, text=tr("▶  Play"), command=self.toggle_play, padding=(12, 5))
        self.play_btn.pack(side="left")
        ttk.Button(row, text=tr("Reset"), command=self.reset_animation, padding=(10, 5)).pack(side="left", padx=6)
        self.loop_chk = ttk.Checkbutton(side, text=tr("Loop"), variable=self.loop, style="Card.TCheckbutton")
        self.loop_chk.pack(anchor="w", pady=(8, 0))
        srow = ttk.Frame(side, style="Card.TFrame")
        srow.pack(fill="x", pady=(4, 0))
        ttk.Label(srow, text=tr("Speed"), style="Key.TLabel").pack(side="left")
        self.speed_scale = ttk.Scale(srow, from_=0.1, to=3.0, variable=self.speed, orient="horizontal")
        self.speed_scale.pack(side="left", fill="x", expand=True, padx=8)
        self._set_anim_enabled(False)

        ttk.Label(side, text=tr("Drag: orbit  ·  Right-drag: pan\nWheel: zoom  ·  F: fit\nSpace: play  ·  W: wire  ·  B: bones"),
                  style="CardMuted.TLabel", justify="left").pack(side="bottom", anchor="w", pady=(10, 0))

        self.status = ttk.Label(self, text=tr("Load a model to preview it."), style="CardMuted.TLabel", padding=(12, 0, 12, 8))
        self.status.pack(fill="x")

        c = self.canvas
        c.bind("<Configure>", lambda _e: self.schedule_render())
        c.bind("<Enter>", lambda _e: c.focus_set())
        c.bind("<ButtonPress-1>", lambda e: self._press(e, "orbit"))
        c.bind("<B1-Motion>", self._motion)
        for b in (2, 3):
            c.bind("<ButtonPress-%d>" % b, lambda e: self._press(e, "pan"))
            c.bind("<B%d-Motion>" % b, self._motion)
        for b in (1, 2, 3):
            c.bind("<ButtonRelease-%d>" % b, self._release)
        c.bind("<Double-Button-1>", lambda _e: self.fit_view())
        c.bind("<MouseWheel>", lambda e: self._zoom_by(1.12 if e.delta > 0 else 1 / 1.12))
        c.bind("<Button-4>", lambda _e: self._zoom_by(1.12))
        c.bind("<Button-5>", lambda _e: self._zoom_by(1 / 1.12))
        c.bind("<KeyPress-f>", lambda _e: self.fit_view())
        c.bind("<KeyPress-w>", lambda _e: self._cycle_mode())
        c.bind("<KeyPress-b>", lambda _e: self._toggle(self.show_bones))
        c.bind("<KeyPress-g>", lambda _e: self._toggle(self.show_grid))
        c.bind("<space>", lambda _e: self.toggle_play())

    def _toggle(self, var):
        var.set(not var.get())
        self.schedule_render()

    def _cycle_mode(self):
        keys = [k for k, _ in MODES]
        self.mode.set(keys[(keys.index(self.mode.get()) + 1) % len(keys)])
        self.schedule_render()

    def _set_info(self, rows):
        for w in self.info_frame.winfo_children():
            w.destroy()
        for r, (k, v) in enumerate(rows):
            ttk.Label(self.info_frame, text=tr(k), style="Key.TLabel").grid(row=r, column=0, sticky="nw", pady=1)
            ttk.Label(self.info_frame, text=v, style="Val.TLabel", wraplength=150, justify="right").grid(
                row=r, column=1, sticky="ne", padx=(10, 0), pady=1)
        self.info_frame.columnconfigure(1, weight=1)

    def _set_anim_enabled(self, on):
        state = "normal" if on else "disabled"
        self.play_btn.configure(state=state)
        self.frame_slider.configure(state=state)
        self.speed_scale.configure(state=state)
        self.loop_chk.configure(state=state)

    def _badge(self, text, color, note=""):
        self.anim_badge.configure(text="●  " + tr(text), foreground=color)
        self.anim_note.configure(text=tr(note))

    # ------------------------------------------------------------------ loading
    def load_model(self):
        path = self.get_mesh_path().strip()
        if not path:
            messagebox.showerror(tr("No model selected"), tr("Choose a .trainzmesh or .im file on the Converter tab first."))
            return
        self.playing = False
        self.play_btn.configure(text=tr("▶  Play"))
        try:
            mesh = trainzlib.load_mesh(path)
        except Exception as exc:
            messagebox.showerror(tr("Could not load model"), f"{type(exc).__name__}: {exc}")
            self.status.configure(text=tr("Failed to load model."))
            return
        # animation is optional and can never block the preview
        kin, notes = trainzlib.resolve_animation(mesh, self.get_kin_path().strip(), self.get_anim_mode(), path)
        for n in notes:
            self.log_callback(n, "warn" if any(w in n for w in ("not match", "could not", "marked")) else None)
        report = trainzlib.im_animation_report(mesh, kin) if mesh.get("src") == "im" else None

        self.mesh, self.kin, self.report = mesh, kin, report
        self.frame_no = 0.0
        self._pose_key = self._pose = None
        self._build_geometry()
        names = [tr("All submeshes")] + [f"{i}: {s['material'].get('name', 'Material')}" for i, s in enumerate(mesh["subs"])]
        self.submesh_combo.configure(values=names)
        self.submesh_var.set(tr("All submeshes"))

        nframes = len(kin["frames"]) if kin else 0
        self._setting_slider = True
        self.frame_slider.configure(from_=0, to=max(1, nframes - 1))
        self.frame_slider.set(0)
        self._setting_slider = False
        self.frame_label.configure(text=tr("Frame 0"))
        self._set_anim_enabled(nframes > 1)
        last = i18n.strip_animation_prefix(tr(notes[-1])) if notes else ""
        if nframes > 1:
            self._badge(f"Animated · {nframes} frames", theme.GOOD, f"{kin['fps']} fps, {len(kin['names'])} bones.")
        elif report and report["bone_count"] == 0:
            self._badge("Static model", theme.MUTED, "This .im has no skeleton, so there is nothing to animate.")
        elif report and report["animatable"]:
            self._badge("No animation loaded", theme.WARN,
                        f"{last}  " + tr(f"The model has {report['bone_count']} bones and could be animated with a matching .kin."))
        else:
            self._badge("Static model", theme.MUTED, last)

        tris = sum(len(s["tris"]) for s in mesh["subs"])
        verts = sum(len(s["v"]) for s in mesh["subs"])
        rows = [("File", path.replace("\\", "/").split("/")[-1]), ("Vertices", f"{verts:,}"), ("Triangles", f"{tris:,}"),
                ("Submeshes", str(len(mesh["subs"]))),
                ("Bones", str(len(mesh["bones"]) if mesh.get("has_skeleton", True) else 0))]
        if kin:
            rows.append(("Frames", f"{nframes} @ {kin['fps']} fps"))
        self._set_info(rows)
        self.fit_view()
        self.status.configure(text=tr(f"Loaded {path}"))

    def _build_geometry(self):
        """Concatenate every submesh once so per-frame work is a handful of NumPy calls."""
        subs = self.mesh["subs"]
        tri_chunks, sub_ids, colors, off = [], [], [], 0
        for si, s in enumerate(subs):
            tri_chunks.append(np.asarray(s["tris"], np.int64).reshape(-1, 3) + off)
            sub_ids.append(np.full(len(s["tris"]), si, np.int64))
            off += len(s["v"])
            col = np.array(s["material"].get("color", (0, 0, 0, 1))[:3], float)
            washed = col.min() > 0.97
            if not np.isfinite(col).all() or col.max() < 0.06 or washed:
                col = np.array(DEFAULT_PALETTE[si % len(DEFAULT_PALETTE)])
            colors.append(np.clip(col, 0, 1) * 255)
        self._geo = dict(
            tris=np.concatenate(tri_chunks) if tri_chunks else np.zeros((0, 3), np.int64),
            sub=np.concatenate(sub_ids) if sub_ids else np.zeros(0, np.int64),
            colors=np.array(colors) if colors else np.zeros((0, 3)), nverts=off)

    # ------------------------------------------------------------------ pose
    def _posed(self):
        key = (id(self.mesh), round(self.frame_no, 2) if self.kin else None)
        if key == self._pose_key and self._pose is not None:
            return self._pose
        if self.kin:
            _n, parents, rec = trainzlib.bone_tables(self.mesh)
            skin = trainzlib.skin_mats(parents, rec, trainzlib.sample(self.kin, self.frame_no))
            parts = [trainzlib.skin_verts(s["v"], skin)[0] for s in self.mesh["subs"]]
        else:
            parts = [s["v"]["p"].astype(float) for s in self.mesh["subs"]]
        pts = to_yup(np.concatenate(parts, axis=0)) if parts else np.zeros((0, 3))
        self._pose_key, self._pose = key, pts
        return pts

    def fit_view(self):
        if not self.mesh or not self._geo or not self._geo["nverts"]:
            return
        # frame the rest pose (frame 0) so playing an animation doesn't move the camera
        saved, self.frame_no = self.frame_no, 0.0
        pts = self._posed()
        self.frame_no = saved
        self._pose_key = None
        lo, hi = pts.min(0), pts.max(0)
        self.center = (lo + hi) / 2
        extent = float((hi - lo).max())
        self.scale = 2.2 / extent if extent > 1e-9 else 1.0
        self.floor_y = float((lo[1] - self.center[1]) * self.scale)
        self.zoom, self.pan_x, self.pan_y = 1.0, 0.0, 0.0
        self.schedule_render()

    # ------------------------------------------------------------------ interaction
    def _press(self, e, kind):
        self.canvas.focus_set()
        base = (self.yaw, self.pitch) if kind == "orbit" else (self.pan_x, self.pan_y)
        self._drag = (kind, e.x, e.y, *base)
        self._interacting = True

    def _motion(self, e):
        if not self._drag:
            return
        kind, x, y, a, b = self._drag
        if kind == "orbit":
            self.yaw = a + (e.x - x) * 0.01
            self.pitch = max(-1.55, min(1.55, b + (e.y - y) * 0.01))
        else:
            self.pan_x, self.pan_y = a + e.x - x, b + e.y - y
        self.schedule_render()

    def _release(self, _e):
        self._drag = None
        self._settle()

    def _zoom_by(self, f):
        self.zoom = min(40.0, max(0.05, self.zoom * f))
        self._interacting = True
        self.schedule_render()
        self._settle()

    def _settle(self):
        """Re-render at full quality shortly after interaction stops."""
        if self._quality_job:
            self.after_cancel(self._quality_job)
        self._quality_job = self.after(150, self._full_quality)

    def _full_quality(self):
        self._quality_job = None
        if self._drag:
            return
        self._interacting = False
        self.schedule_render()

    # ------------------------------------------------------------------ animation
    def _slider_moved(self, value):
        if self._setting_slider:
            return
        self.frame_no = float(value)
        self.frame_label.configure(text=tr(f"Frame {self.frame_no:.1f}"))
        self.schedule_render()

    def _set_frame(self, value):
        self.frame_no = value
        self._setting_slider = True
        self.frame_slider.set(value)
        self._setting_slider = False
        self.frame_label.configure(text=tr(f"Frame {value:.1f}"))

    def toggle_play(self):
        if not self.kin or len(self.kin["frames"]) < 2:
            return
        self.playing = not self.playing
        self.play_btn.configure(text=tr("⏸  Pause") if self.playing else tr("▶  Play"))
        if self.playing:
            self._last_tick = time.perf_counter()
            self._animate()

    def _animate(self):
        if not self.winfo_exists() or not self.playing or not self.kin:
            return
        now = time.perf_counter()
        dt, self._last_tick = now - self._last_tick, now
        count = len(self.kin["frames"])
        nxt = self.frame_no + dt * max(1, self.kin["fps"]) * float(self.speed.get())
        if nxt >= count - 1 and not self.loop.get():
            nxt, self.playing = count - 1, False
            self.play_btn.configure(text="▶  Play")
        else:
            nxt %= count
        self._set_frame(nxt)
        self._render_now()
        if self.playing:
            self.after(16, self._animate)

    def reset_animation(self):
        self.playing = False
        self.play_btn.configure(text="▶  Play")
        self._set_frame(0.0)
        self.schedule_render()

    # ------------------------------------------------------------------ rendering
    def _camera(self, w, h):
        cy, sy, cx, sx = math.cos(self.yaw), math.sin(self.yaw), math.cos(self.pitch), math.sin(self.pitch)
        RY = np.array([[cy, 0, -sy], [0, 1, 0], [sy, 0, cy]])
        RX = np.array([[1, 0, 0], [0, cx, -sx], [0, sx, cx]])
        return RX @ RY, min(w, h) * 0.9 * self.zoom, 4.5

    def _project(self, pts_norm, R, focal, dist, w, h):
        v = pts_norm @ R.T
        depth = dist - v[:, 2]
        d = np.maximum(depth, 0.05)
        sx = w / 2 + self.pan_x + v[:, 0] * focal / d
        sy = h / 2 + self.pan_y - v[:, 1] * focal / d
        return v, np.column_stack((sx, sy)), depth

    def schedule_render(self):
        if not hasattr(self, "canvas") or self._render_job is not None:
            return
        self._render_job = self.after(14, self._render_now)

    def render(self):
        self.schedule_render()

    def _render_now(self):
        if self._render_job is not None:
            try:
                self.after_cancel(self._render_job)
            except Exception:
                pass
            self._render_job = None
        c = self.canvas
        c.delete("all")
        w, h = max(1, c.winfo_width()), max(1, c.winfo_height())
        if not self.mesh or not self._geo or not self._geo["nverts"]:
            c.create_text(w / 2, h / 2 - 10, fill=theme.MUTED, text=tr("No model loaded"), font=(theme.family(), 16, "bold"))
            c.create_text(w / 2, h / 2 + 18, fill=theme.MUTED, font=(theme.family(), 10),
                          text=tr("Pick a file on the Converter tab, then press Load model"))
            return
        R, focal, dist = self._camera(w, h)
        if self.show_grid.get():
            self._draw_grid(R, focal, dist, w, h)

        pts = (self._posed() - self.center) * self.scale
        v, xy, depth = self._project(pts, R, focal, dist, w, h)

        geo = self._geo
        sel = self.submesh_var.get()
        mask = np.ones(len(geo["tris"]), bool) if sel == tr("All submeshes") else geo["sub"] == int(sel.split(":")[0])
        idx = np.nonzero(mask)[0]
        tri = geo["tris"][idx]

        # cull triangles behind the camera or entirely off-screen *before* decimating,
        # so the triangle budget is spent only on what can actually be seen
        td = depth[tri]
        txy = xy[tri]
        vis = (td > 0.2).all(axis=1)
        vis &= ~((txy[:, :, 0] < 0).all(axis=1) | (txy[:, :, 0] > w).all(axis=1) |
                 (txy[:, :, 1] < 0).all(axis=1) | (txy[:, :, 1] > h).all(axis=1))
        idx, tri, td, txy = idx[vis], tri[vis], td[vis], txy[vis]
        total = len(idx)
        budget = self.DRAFT_TRIS if self._interacting else self.FULL_TRIS
        stride = max(1, math.ceil(total / budget))
        if stride > 1:
            idx, tri, td, txy = idx[::stride], tri[::stride], td[::stride], txy[::stride]

        tv = v[tri]
        n = np.cross(tv[:, 1] - tv[:, 0], tv[:, 2] - tv[:, 0])
        ln = np.linalg.norm(n, axis=1)
        n = n / np.maximum(ln, 1e-12)[:, None]
        shade = np.clip(0.30 + 0.58 * np.abs(n @ LIGHT) + 0.18 * np.abs(n[:, 2]), 0, 1.05)
        shade[ln < 1e-12] = 0.6
        rgb = np.clip(geo["colors"][geo["sub"][idx]] * shade[:, None], 0, 255).astype(int)
        order = np.argsort(-td.mean(axis=1))          # painter's algorithm, far -> near
        pxy, rgb = txy[order], rgb[order]

        # When triangles are skipped, fatten the ones we draw so they still cover the gaps
        # (otherwise dense meshes look like a cloud of dots).
        lw = 1
        if stride > 1 and len(pxy):
            edge_len = float(np.median(np.linalg.norm(pxy[:, 1] - pxy[:, 0], axis=1)))
            lw = int(min(12, max(2, round(edge_len * (math.sqrt(stride) - 1) * 1.0))))

        mode = self.mode.get()
        full = stride == 1
        for k in range(len(order)):
            (x0, y0), (x1, y1), (x2, y2) = pxy[k]
            col = "#%02x%02x%02x" % tuple(rgb[k])
            if mode == "wire":
                c.create_polygon(x0, y0, x1, y1, x2, y2, fill="", outline=col)
            elif mode == "edges" and full:
                c.create_polygon(x0, y0, x1, y1, x2, y2, fill=col, outline=theme.MESH_EDGE)
            else:
                c.create_polygon(x0, y0, x1, y1, x2, y2, fill=col, outline=col, width=lw, joinstyle="round")

        if self.show_bones.get() or self.show_names.get():
            self._draw_bones(R, focal, dist, w, h)
        self._draw_gizmo(R, h)

        f = theme.family()
        shown = len(order)
        note = tr(f"{total:,} triangles") if stride == 1 else tr(f"preview: {shown:,} of {total:,} visible triangles")
        if self._interacting and stride > 1:
            note += "  ·  " + tr("draft")
        c.create_text(w - 12, h - 10, anchor="se", fill=theme.MUTED, font=(f, 9), text=note)
        if self.kin:
            c.create_text(w - 12, 10, anchor="ne", fill=theme.MUTED, font=(f, 9),
                          text=tr(f"frame {self.frame_no:.1f} / {len(self.kin['frames']) - 1}"))

    def _draw_grid(self, R, focal, dist, w, h):
        r, y, n = 2.0, self.floor_y, 10
        t = np.linspace(-r, r, n + 1)
        a, b, mid = [], [], []
        for s in t:
            a += [(s, y, -r), (-r, y, s)]
            b += [(s, y, r), (r, y, s)]
            mid += [abs(s) < 1e-9] * 2
        _va, pa, da = self._project(np.array(a), R, focal, dist, w, h)
        _vb, pb, db = self._project(np.array(b), R, focal, dist, w, h)
        for i in range(len(a)):
            if da[i] < 0.4 or db[i] < 0.4:
                continue
            self.canvas.create_line(pa[i, 0], pa[i, 1], pb[i, 0], pb[i, 1], fill=theme.GRID_MID if mid[i] else theme.GRID)

    def _draw_gizmo(self, R, h):
        ox, oy, length = 46, h - 46, 26
        f = theme.family()
        # Trainz axes: X right, Y forward, Z up  ->  viewer (x, z, -y)
        for label, vec, col in (("X", (1, 0, 0), theme.AXIS_X), ("Y", (0, 0, -1), theme.AXIS_Y), ("Z", (0, 1, 0), theme.AXIS_Z)):
            v = R @ np.array(vec, float)
            ex, ey = ox + v[0] * length, oy - v[1] * length
            self.canvas.create_line(ox, oy, ex, ey, fill=col, width=2)
            self.canvas.create_text(ex + v[0] * 8, ey - v[1] * 8, text=label, fill=col, font=(f, 8, "bold"))

    def _draw_bones(self, R, focal, dist, w, h):
        if not self.mesh.get("has_skeleton", True):
            return                                   # the lone 'root' is synthetic, don't draw it as a real bone
        try:
            _n, parents, rec = trainzlib.bone_tables(self.mesh)
            if self.kin:
                rec = trainzlib.sample(self.kin, self.frame_no)
            world = trainzlib.world_mats(parents, rec)
            joints = (to_yup(np.array([m[:3, 3] for m in world])) - self.center) * self.scale
            _v, jp, _d = self._project(joints, R, focal, dist, w, h)
        except Exception:
            return
        c, f = self.canvas, theme.family()
        if self.show_bones.get():
            for i, par in enumerate(parents):
                if par >= 0:
                    c.create_line(jp[par, 0], jp[par, 1], jp[i, 0], jp[i, 1], fill=theme.WARN, width=2)
            for x, y in jp:
                c.create_oval(x - 3.5, y - 3.5, x + 3.5, y + 3.5, fill=theme.BONE_DOT, outline=theme.BONE_RING)
        if self.show_names.get():
            for b, (x, y) in zip(self.mesh["bones"], jp):
                c.create_text(x + 7, y - 7, anchor="sw", text=b["name"], fill=theme.LABEL, font=(f, 8))
