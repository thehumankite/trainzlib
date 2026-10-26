"""English / Simplified Chinese for TrainzLib.

Source strings stay in English everywhere in the code. `tr(text)` returns the Chinese version when the language is
"zh" and the text unchanged otherwise, so adding a language is just another column in TABLE.

Strings that carry values use {name} placeholders, e.g. "Loaded {path}". tr() also matches *already formatted*
English text against those patterns, which lets messages produced by trainzlib.py ("Animation: 29 frames @ 24 fps
applied.") be translated for display without changing the library.

The technical model report from the "Info" action (bone / submesh dump) is left in English on purpose.
"""
import re
import sys

LANG = "en"

TABLE = [
    # ---- window / tabs / general
    ("TrainzLib: Trainz Model Converter", "TrainzLib：Trainz 模型转换器"),
    ("Inspect, preview and export Trainz models", "检查、预览并导出 Trainz 模型"),
    ("Choose a .trainzmesh or .im file to begin.", "请选择 .trainzmesh 或 .im 文件开始。"),
    ("Converter", "转换器"),
    ("3D Viewer", "3D 查看器"),
    ("Browse", "浏览"),
    ("Input files", "输入文件"),
    ("Model", "模型"),
    ("Anim. (.kin)", "动画 (.kin)"),
    ("Model selected.", "已选择模型。"),
    ("Working…", "处理中…"),
    ("Finished.", "已完成。"),
    ("Failed. See the activity log.", "失败，请查看活动日志。"),
    # ---- animation card
    ("Does this .im have animation?", "此模型是否带动画？"),
    ("A missing or mismatched .kin never causes an error.", "缺少或不匹配的 .kin 不会导致报错。"),
    ("Auto-detect", "自动检测"),
    ("Yes, it's animated", "是，带动画"),
    ("No, static model", "否，静态模型"),
    ("Uses a .kin you pick, or one with the same name beside the model. Otherwise exports static.",
     "使用你选择的 .kin，或模型旁同名的 .kin；否则按静态模型导出。"),
    ("Uses your .kin. If it's missing or doesn't fit the bones, falls back to static and says why.",
     "使用你的 .kin。若缺失或与骨骼不匹配，则退回静态导出并说明原因。"),
    ("Ignores any .kin and exports a static model with no animation track.",
     "忽略所有 .kin，导出不含动画轨道的静态模型。"),
    ("Choose a model to check it for animation.", "请选择模型以检查其是否带动画。"),
    ("That model file doesn't exist.", "该模型文件不存在。"),
    ("Couldn't read the model ({name}).", "无法读取模型（{name}）。"),
    ("Animation turned off: this will export as a static model.", "动画已关闭：将按静态模型导出。"),
    ("Check", "检查"),
    # ---- export card
    ("Export", "导出"),
    ("Info", "信息"),
    ("OBJ", "OBJ"),
    ("GLB", "GLB"),
    ("glTF empties", "glTF 空节点"),
    ("Print a report of the model, its skeleton and whether it has animation.", "输出模型、骨骼及是否带动画的报告。"),
    ("Wavefront OBJ. If there is an animation you can pose the model at a chosen frame.",
     "Wavefront OBJ。若有动画，可将模型摆成所选帧的姿态。"),
    ("Single-file glTF binary with a skin. Includes the animation when there is one.",
     "带蒙皮的单文件 glTF 二进制。若有动画则一并包含。"),
    ("glTF + .bin keeping the original bone hierarchy and attachment points as plain nodes.",
     "glTF + .bin，将原始骨骼层级和挂接点保留为普通节点。"),
    ("Pose frame", "姿态帧"),
    ("OBJ only, needs an animation", "仅 OBJ，需要动画"),
    ("Output", "输出"),
    ("Run", "运行"),
    ("Open in 3D viewer", "在 3D 查看器中打开"),
    ("Activity", "活动日志"),
    ("Clear", "清除"),
    # ---- file dialogs
    ("Select Trainz mesh/model", "选择 Trainz 网格/模型"),
    ("Trainz models", "Trainz 模型"),
    ("All files", "所有文件"),
    ("Select Trainz animation", "选择 Trainz 动画"),
    ("Trainz animation", "Trainz 动画"),
    ("Choose output file", "选择输出文件"),
    ("Wavefront OBJ", "Wavefront OBJ"),
    ("glTF JSON", "glTF JSON"),
    ("glTF binary", "glTF 二进制"),
    # ---- message boxes
    ("Missing input", "缺少输入"),
    ("Choose a .trainzmesh or .im file first.", "请先选择 .trainzmesh 或 .im 文件。"),
    ("File not found", "未找到文件"),
    ("The selected model file does not exist.", "所选模型文件不存在。"),
    ("Missing output", "缺少输出"),
    ("Choose an output file.", "请选择输出文件。"),
    ("Invalid frame", "帧无效"),
    ("Pose frame must be a number, such as 0 or 7.5.", "姿态帧必须是数字，例如 0 或 7.5。"),
    ("Operation failed", "操作失败"),
    ("Missing dependency", "缺少依赖项"),
    ("NumPy is required.\n\nInstall it with:\npython -m pip install numpy",
     "需要 NumPy。\n\n请使用以下命令安装：\npython -m pip install numpy"),
    # ---- results written to the log by the GUI worker
    ("Exported glTF with empty transform nodes: {path}", "已导出带空变换节点的 glTF：{path}"),
    ("Companion buffer: {path}", "配套缓冲文件：{path}"),
    ("Attachment empties: {n} ({names})", "挂接点空节点：{n} 个（{names}）"),
    ("Attachment empties: {n}", "挂接点空节点：{n} 个"),
    ("Hierarchy nodes: {a}; submeshes: {b}; triangles: {c}", "层级节点：{a}；子网格：{b}；三角形：{c}"),
    ("Bone names and hierarchy are kept as ordinary nodes; no skin or joints.",
     "骨骼名称和层级保留为普通节点；不含蒙皮或关节。"),
    ("Static export: no animation track written.", "静态导出：未写入动画轨道。"),
    ("Static export: pose frame ignored (no animation).", "静态导出：已忽略姿态帧（无动画）。"),
    ("Exported OBJ: {path}", "已导出 OBJ：{path}"),
    ("Exported GLB: {path}", "已导出 GLB：{path}"),
    ("Done.", "完成。"),
    # ---- messages produced by trainzlib.py
    ("Animation: off, exporting a static model.", "动画：已关闭，按静态模型导出。"),
    ("Animation: found matching file {f}", "动画：找到匹配文件 {f}"),
    ("Animation: no .kin supplied, exporting a static model.", "动画：未提供 .kin，按静态模型导出。"),
    ('Animation: marked "yes" but no .kin was chosen, exporting a static model instead.',
     "动画：已标记为“是”，但未选择 .kin，改为按静态模型导出。"),
    ("Animation: could not read {f} ({why}), continuing without animation.",
     "动画：无法读取 {f}（{why}），将不带动画继续。"),
    ("Animation: {f} does not match this model ({why}), continuing without animation.",
     "动画：{f} 与此模型不匹配（{why}），将不带动画继续。"),
    ("Animation: could not apply {f} ({why}), continuing without animation.",
     "动画：无法应用 {f}（{why}），将不带动画继续。"),
    ("Animation: {n} frames @ {fps} fps applied.", "动画：已应用 {n} 帧 @ {fps} fps。"),
    ("file not found", "文件不存在"),
    ("not a valid or supported .kin file", "不是有效或受支持的 .kin 文件"),
    ("the model has no skeleton", "模型没有骨骼"),
    ("the .kin has no frames", ".kin 没有帧"),
    (".kin has {a} bones, model has {b}", ".kin 有 {a} 根骨骼，模型有 {b} 根"),
    ("bone names differ (e.g. {names})", "骨骼名称不同（例如 {names}）"),
    ("bone hierarchy differs", "骨骼层级不同"),
    ("This model has animation chunks embedded in the file.", "此模型的文件中嵌入了动画数据块。"),
    ("No animation: this model has no skeleton, it is a static mesh.", "无动画：此模型没有骨骼，是静态网格。"),
    ("No embedded animation. The model has {n} bone(s) so it CAN be animated, but .im files carry no keyframes; "
     "those come from a separate .kin file.",
     "无嵌入动画。该模型有 {n} 根骨骼，可以制作动画，但 .im 文件不含关键帧；关键帧来自单独的 .kin 文件。"),
    ("Animated: {n} frames @ {fps} fps from the .kin, matching all {b} bones.",
     "带动画：来自 .kin 的 {n} 帧 @ {fps} fps，与全部 {b} 根骨骼匹配。"),
    ("The .kin does not fit this model ({why}); it will be ignored.", "该 .kin 与此模型不匹配（{why}），将被忽略。"),
    # ---- 3D viewer
    ("Load model", "加载模型"),
    ("Fit", "适应"),
    ("Solid", "实体"),
    ("Edges", "边线"),
    ("Wire", "线框"),
    ("Skeleton", "骨骼"),
    ("Names", "名称"),
    ("Grid", "网格"),
    ("Submesh", "子网格"),
    ("All submeshes", "全部子网格"),
    ("Animation", "动画"),
    ("No model loaded", "未加载模型"),
    ("Frame {n}", "帧 {n}"),
    ("▶  Play", "▶  播放"),
    ("⏸  Pause", "⏸  暂停"),
    ("Reset", "重置"),
    ("Loop", "循环"),
    ("Speed", "速度"),
    ("Drag: orbit  ·  Right-drag: pan\nWheel: zoom  ·  F: fit\nSpace: play  ·  W: wire  ·  B: bones",
     "拖动：旋转  ·  右键拖动：平移\n滚轮：缩放  ·  F：适应\n空格：播放  ·  W：线框  ·  B：骨骼"),
    ("Load a model to preview it.", "加载模型以预览。"),
    ("Failed to load model.", "加载模型失败。"),
    ("Loaded {path}", "已加载 {path}"),
    ("No model selected", "未选择模型"),
    ("Choose a .trainzmesh or .im file on the Converter tab first.", "请先在“转换器”标签页选择 .trainzmesh 或 .im 文件。"),
    ("Could not load model", "无法加载模型"),
    ("Animated · {n} frames", "带动画 · {n} 帧"),
    ("{fps} fps, {n} bones.", "{fps} fps，{n} 根骨骼。"),
    ("Static model", "静态模型"),
    ("This .im has no skeleton, so there is nothing to animate.", "此模型没有骨骼，无可动画内容。"),
    ("No animation loaded", "未加载动画"),
    ("The model has {n} bones and could be animated with a matching .kin.", "该模型有 {n} 根骨骼，可搭配匹配的 .kin 制作动画。"),
    ("File", "文件"),
    ("Vertices", "顶点"),
    ("Triangles", "三角形"),
    ("Submeshes", "子网格"),
    ("Bones", "骨骼"),
    ("Frames", "帧"),
    ("Pick a file on the Converter tab, then press Load model", "在“转换器”标签页选择文件，然后点击“加载模型”"),
    ("{n} triangles", "{n} 个三角形"),
    ("preview: {a} of {b} visible triangles", "预览：显示 {b} 个可见三角形中的 {a} 个"),
    ("draft", "草图质量"),
    ("frame {a} / {b}", "帧 {a} / {b}"),
]

_EXACT = {}
_PATTERNS = []
for _en, _zh in TABLE:
    if "{" in _en:
        rx = re.escape(_en)
        rx = re.sub(r"\\\{(\w+)\\\}", r"(?P<\1>.+?)", rx)
        _PATTERNS.append((re.compile(rx, re.S), _zh, len(re.sub(r"\{\w+\}", "", _en))))
    else:
        _EXACT[_en] = _zh

# Longest literal text first, so '{n} triangles' can never swallow 'preview: {a} of {b} visible triangles'.
_PATTERNS.sort(key=lambda p: -p[2])
_PATTERNS[:] = [(rx, zh) for rx, zh, _ in _PATTERNS]


def set_lang(lang):
    global LANG
    LANG = "zh" if lang == "zh" else "en"


def is_zh():
    return LANG == "zh"


def tr(text):
    """Translate `text` (an English string, or an English message already filled in with values)."""
    if LANG == "en" or not text or not isinstance(text, str):
        return text
    hit = _EXACT.get(text)
    if hit is not None:
        return hit
    if "\n" in text:
        return "\n".join(tr(line) for line in text.split("\n"))
    for rx, zh in _PATTERNS:
        m = rx.fullmatch(text)
        if m:
            return zh.format(**{k: tr(v) for k, v in m.groupdict().items()})
    return text


_PREFIXES = ("Animation: ", "动画：")


def strip_animation_prefix(text):
    for p in _PREFIXES:
        if text.startswith(p):
            return text[len(p):]
    return text


def lang_from_argv(argv=None):
    """--lang en|zh on the command line skips the startup question."""
    argv = sys.argv[1:] if argv is None else argv
    for i, a in enumerate(argv):
        if a.startswith("--lang="):
            return "zh" if a.split("=", 1)[1].lower().startswith("zh") else "en"
        if a == "--lang" and i + 1 < len(argv):
            return "zh" if argv[i + 1].lower().startswith("zh") else "en"
    return None


def choose_language():
    """Small themed window asking English / 中文. Returns 'en', 'zh', or None if the window was closed."""
    import tkinter as tk
    from tkinter import ttk
    import theme

    root = tk.Tk()
    root.title("TrainzLib")
    root.resizable(False, False)
    theme.apply_theme(root)
    theme.set_icon(root)
    result = {"lang": None}

    def pick(lang):
        result["lang"] = lang
        root.destroy()

    frame = ttk.Frame(root, padding=(34, 28, 34, 28))
    frame.pack()
    theme.logo(frame, 56).pack(pady=(0, 12))
    ttk.Label(frame, text="TrainzLib", style="Title.TLabel").pack()
    ttk.Label(frame, text="Choose your language  /  选择语言", style="Muted.TLabel").pack(pady=(4, 18))
    row = ttk.Frame(frame)
    row.pack()
    en = ttk.Button(row, text="English", style="Accent.TButton", command=lambda: pick("en"), width=12)
    zh = ttk.Button(row, text="中文", style="Accent.TButton", command=lambda: pick("zh"), width=12)
    en.pack(side="left", padx=(0, 10))
    zh.pack(side="left")
    for b, lang in ((en, "en"), (zh, "zh")):
        b.bind("<Return>", lambda _e, l=lang: pick(l))
    en.focus_set()
    root.bind("<Escape>", lambda _e: root.destroy())

    theme.enable_dark_titlebar(root)
    root.update_idletasks()
    w, h = root.winfo_reqwidth(), root.winfo_reqheight()
    root.geometry("+%d+%d" % ((root.winfo_screenwidth() - w) // 2, (root.winfo_screenheight() - h) // 3))
    root.mainloop()
    return result["lang"]
