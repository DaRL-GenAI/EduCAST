#!/usr/bin/env python3
"""Build the EduHarness audit deck with native, editable PowerPoint shapes.

Every box, arrow and label is a real pptx shape — no rasterised diagrams — so the
figures can be moved, recoloured and retyped in PowerPoint / WPS / Keynote.

    python3 build_deck.py            # writes eduharness-audit.pptx beside this file
"""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.oxml.ns import qn
from pptx.util import Emu, Inches, Pt

# Palette is the harness's own StyleConfig (schema.py:38-43), so the deck sits in
# the same colour world as the lessons it describes.
GROUND = RGBColor(0xFA, 0xFB, 0xF8)
SURFACE = RGBColor(0xF2, 0xF5, 0xF0)
SUNKEN = RGBColor(0xE7, 0xEC, 0xE6)
INK = RGBColor(0x17, 0x20, 0x1B)
MUTED = RGBColor(0x66, 0x70, 0x6A)
RULE = RGBColor(0xD4, 0xDB, 0xD3)
PRIMARY = RGBColor(0x35, 0x6B, 0x8F)
SECONDARY = RGBColor(0x16, 0x73, 0x4A)
DANGER = RGBColor(0xB4, 0x42, 0x3D)
AMBER = RGBColor(0x8A, 0x65, 0x16)

SANS = "Microsoft YaHei"   # falls back to PingFang SC on macOS
MONO = "Consolas"

prs = Presentation()
prs.slide_width = Inches(13.333)
prs.slide_height = Inches(7.5)
BLANK = prs.slide_layouts[6]


# --------------------------------------------------------------------- helpers
def slide():
    s = prs.slides.add_slide(BLANK)
    bg = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, 0, 0, prs.slide_width, prs.slide_height)
    bg.fill.solid()
    bg.fill.fore_color.rgb = GROUND
    bg.line.fill.background()
    bg.shadow.inherit = False
    return s


def text(s, x, y, w, h, runs, *, align=PP_ALIGN.LEFT, anchor=MSO_ANCHOR.TOP, spacing=1.0):
    """runs: list of (string, size_pt, bold, colour, font_name) or list of such lists
    (one inner list per paragraph)."""
    box = s.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = tf.margin_right = tf.margin_top = tf.margin_bottom = 0
    paragraphs = runs if runs and isinstance(runs[0], list) else [runs]
    for i, para_runs in enumerate(paragraphs):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.alignment = align
        p.line_spacing = spacing
        for content, size, bold, colour, font in para_runs:
            r = p.add_run()
            r.text = content
            r.font.size = Pt(size)
            r.font.bold = bold
            r.font.color.rgb = colour
            r.font.name = font
    return box


def box(s, x, y, w, h, *, fill=None, outline=INK, width=1.0, dashed=False, radius=None):
    shape = s.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE if radius else MSO_SHAPE.RECTANGLE,
        Inches(x), Inches(y), Inches(w), Inches(h),
    )
    if radius:
        shape.adjustments[0] = radius
    if fill is None:
        shape.fill.background()
    else:
        shape.fill.solid()
        shape.fill.fore_color.rgb = fill
    if outline is None:
        shape.line.fill.background()
    else:
        shape.line.color.rgb = outline
        shape.line.width = Pt(width)
        if dashed:
            shape.line.dash_style = None
            ln = shape.line._get_or_add_ln()
            for old in ln.findall(qn("a:prstDash")):
                ln.remove(old)
            ln.append(ln.makeelement(qn("a:prstDash"), {"val": "dash"}))
    shape.shadow.inherit = False
    shape.text_frame.word_wrap = True
    return shape


def _end(ln, tag, kind="triangle"):
    el = ln.makeelement(qn(f"a:{tag}"), {"type": kind, "w": "med", "len": "med"})
    ln.append(el)


def arrow(s, x1, y1, x2, y2, *, colour=INK, width=1.0, head=False, tail=True, dashed=False):
    """A straight connector. Chain several for an elbow path."""
    from pptx.enum.shapes import MSO_CONNECTOR

    c = s.shapes.add_connector(
        MSO_CONNECTOR.STRAIGHT, Inches(x1), Inches(y1), Inches(x2), Inches(y2)
    )
    c.line.color.rgb = colour
    c.line.width = Pt(width)
    ln = c.line._get_or_add_ln()
    if dashed:
        ln.append(ln.makeelement(qn("a:prstDash"), {"val": "dash"}))
    if head:
        _end(ln, "headEnd")
    if tail:
        _end(ln, "tailEnd")
    return c


def eyebrow(s, x, y, label):
    text(s, x, y, 8, 0.24, [(label, 10.5, False, MUTED, MONO)])


def heading(s, title, sub=None):
    eyebrow(s, 0.55, 0.34, "EDUHARNESS 机制审计")
    text(s, 0.5, 0.62, 12.4, 0.52, [(title, 26, True, INK, SANS)])
    if sub:
        text(s, 0.5, 1.16, 12.4, 0.3, [(sub, 12, False, MUTED, SANS)])


def stripe(s, x, y, w, h, colour):
    bar = s.shapes.add_shape(MSO_SHAPE.RECTANGLE, Inches(x), Inches(y), Inches(w), Inches(h))
    bar.fill.solid()
    bar.fill.fore_color.rgb = colour
    bar.line.fill.background()
    bar.shadow.inherit = False
    return bar


# ---------------------------------------------------------------- slide 1 title
s = slide()
stripe(s, 0.5, 2.55, 1.5, 0.035, SECONDARY)
text(s, 0.5, 2.05, 10, 0.3, [("education_video / eduharness · 2026-09-14", 11.5, False, MUTED, MONO)])
text(s, 0.5, 2.85, 11.5, 1.0, [("EduHarness 机制审计", 42, True, INK, SANS)])
text(s, 0.5, 3.95, 9.6, 1.0, [[
    ("通读 Stage 1 → Stage 3 全链路后的两张机制图，", 15, False, MUTED, SANS)],
    [("以及 5 条落在测试覆盖之外的逻辑问题。每条都给了文件行号；前两条能复现。", 15, False, MUTED, SANS)],
])
for i, (k, v) in enumerate([
    ("测试", "171 passed · 23 skipped"),
    ("代码量", "11,364 行 / 44 模块"),
    ("范围", "pipeline · stage2 · stage3"),
]):
    x = 0.5 + i * 3.5
    text(s, x, 5.6, 3.2, 0.24, [(k, 10.5, False, MUTED, MONO)])
    text(s, x, 5.88, 3.2, 0.3, [(v, 13, False, INK, MONO)])
stripe(s, 0.5, 5.45, 10.5, 0.012, RULE)


# ------------------------------------------------------- slide 2 主机制 diagram
s = slide()
heading(s, "主机制：两个 checkpoint 文件撑起三个幂等 pass",
        "Stage 2 不是流水线，是三个各自可重入的 pass；要不要重做由 fingerprint 决定")

# Stage 2 container
box(s, 2.75, 1.72, 7.35, 3.95, fill=None, outline=MUTED, width=0.75, dashed=True, radius=0.02)
text(s, 2.92, 1.86, 4, 0.24, [("STAGE 2 — 三个幂等 PASS", 10, False, MUTED, MONO)])

# Stage 1
box(s, 0.5, 2.25, 1.95, 1.0, fill=GROUND, outline=INK, width=1.1)
text(s, 0.66, 2.42, 1.7, 0.9, [
    [("STAGE 1", 9.5, False, MUTED, MONO)],
    [("Main Agent", 14, True, INK, SANS)],
    [("规划 scenes + style", 10, False, MUTED, SANS)],
], spacing=1.25)
arrow(s, 2.45, 2.75, 2.70, 2.75, colour=PRIMARY, width=1.2)

# three passes
passes = [
    (3.0, "prepare", ["tool spec · 配图", "旁白 TTS"], "API", PRIMARY),
    (5.35, "render", ["Manim / Remotion", "合成 · 混旁白"], "本地", SECONDARY),
    (7.7, "review", ["guard + VLM", "见下一页"], "API", PRIMARY),
]
for x, name, lines, badge, badge_c in passes:
    box(s, x, 2.25, 2.1, 1.0, fill=GROUND, outline=INK, width=1.1)
    text(s, x + 0.16, 2.40, 1.5, 0.85, [
        [(name, 14, True, INK, SANS)],
        [(lines[0], 9.5, False, MUTED, SANS)],
        [(lines[1], 9.5, False, MUTED, SANS)],
    ], spacing=1.2)
    text(s, x + 1.45, 2.40, 0.55, 0.22, [(badge, 9, False, badge_c, MONO)], align=PP_ALIGN.RIGHT)

arrow(s, 5.10, 2.75, 5.30, 2.75, colour=INK, width=1.2)
arrow(s, 7.45, 2.75, 7.65, 2.75, colour=INK, width=1.2)

# repair loop: review bottom → down → left → up into prepare
arrow(s, 8.75, 3.25, 8.75, 3.66, colour=PRIMARY, width=1.2, tail=False)
arrow(s, 8.75, 3.66, 4.05, 3.66, colour=PRIMARY, width=1.2, tail=False)
arrow(s, 4.05, 3.66, 4.05, 3.25, colour=PRIMARY, width=1.2)
text(s, 4.2, 3.74, 4.5, 0.24, [("未通过的 scene → repairs_by_id", 10.5, False, PRIMARY, MONO)], align=PP_ALIGN.CENTER)
text(s, 4.2, 4.00, 4.5, 0.24,
     [("每轮只重做失败的那几个 · 最多 3 轮", 10, False, MUTED, SANS)], align=PP_ALIGN.CENTER)

# checkpoints
for x in (4.05, 6.40, 8.75):
    arrow(s, x, 4.34, x, 4.62, colour=MUTED, width=0.9, dashed=True, head=True)
box(s, 3.0, 4.62, 6.8, 0.9, fill=SUNKEN, outline=RULE, width=0.9)
text(s, 3.2, 4.76, 4.4, 0.7, [
    [("prepared_scenes.json", 11.5, False, INK, MONO)],
    [("rendered_scenes.json", 11.5, False, INK, MONO)],
    [("scene 级单独落盘，附 prepare / render fingerprint", 9.5, False, MUTED, SANS)],
], spacing=1.15)
text(s, 7.5, 4.78, 2.15, 0.7, [
    [("fingerprint 判定", 12, True, SECONDARY, SANS)],
    [("复用，还是重做", 9.5, False, MUTED, SANS)],
    [("（含模块自身文件摘要）", 9.5, False, MUTED, SANS)],
], align=PP_ALIGN.RIGHT, spacing=1.15)

# Stage 3
arrow(s, 10.10, 2.75, 10.35, 2.75, colour=INK, width=1.2)
box(s, 10.4, 2.25, 1.95, 1.0, fill=GROUND, outline=INK, width=1.1)
text(s, 10.56, 2.42, 1.7, 0.9, [
    [("STAGE 3", 9.5, False, MUTED, MONO)],
    [("bundler", 14, True, INK, SANS)],
    [("结构性缺陷直接拦", 10, False, MUTED, SANS)],
], spacing=1.25)
text(s, 10.4, 3.35, 1.95, 0.5, [
    [("EduBundle", 10, False, MUTED, SANS)],
    [("manifest + 播放器", 10, False, MUTED, SANS)],
], align=PP_ALIGN.CENTER, spacing=1.2)

stripe(s, 0.5, 5.95, 12.33, 0.012, RULE)
text(s, 0.5, 6.12, 12.3, 0.9, [
    [("resume 时读回两个 checkpoint，保留已通过的 scene，只对预算内的失败项继续 —— 但预算算法有问题，见问题 ③。", 11, False, MUTED, SANS)],
    [("prepare 与 review 要 API key、render 纯本地：这条切线就是 Colab 混合流程（--stage 2-prepare / 2-render / 2-review）的分界。", 11, False, MUTED, SANS)],
], spacing=1.4)


# --------------------------------------------------- slide 3 review 机制 diagram
s = slide()
heading(s, "review 机制：三路证据汇进一个可以推翻 VLM 的判决点",
        "确定性测量对 VLM 有否决权 —— 问题出在第三路其实不是测量")

text(s, 0.5, 1.55, 3, 0.22, [("三路证据", 10, False, MUTED, MONO)])
evidence = [
    (1.80, "渲染期 guard", "每次 play()/wait() 量文字包围盒，运动按 0.25s 采样", "实测", SECONDARY, INK, 1.1),
    (2.82, "复审期检查", "空帧 · DOM 溢出 · 素材缺失；每轮从帧重算，不继承", "实测", SECONDARY, INK, 1.1),
    (3.84, "静态源码扫描", "正则扫 place_at_grid / place_in_area，找重叠格子 —— 没有时间概念", "猜测", DANGER, DANGER, 1.6),
]
for y, name, desc, badge, badge_c, border, bw in evidence:
    box(s, 0.5, y, 2.95, 0.92, fill=GROUND, outline=border, width=bw)
    text(s, 0.66, y + 0.11, 1.9, 0.24, [(name, 12.5, True, border if border == DANGER else INK, SANS)])
    text(s, 0.66, y + 0.40, 2.5, 0.5, [(desc, 9, False, MUTED, SANS)], spacing=1.15)
    text(s, 2.75, y + 0.11, 0.55, 0.22, [(badge, 9, False, badge_c, MONO)], align=PP_ALIGN.RIGHT)

# merge into GuardReport
arrow(s, 3.45, 2.26, 3.72, 2.26, colour=INK, width=1.0, tail=False)
arrow(s, 3.72, 2.26, 3.72, 3.28, colour=INK, width=1.0, tail=False)
arrow(s, 3.45, 4.30, 3.72, 4.30, colour=DANGER, width=1.4, tail=False)
arrow(s, 3.72, 4.30, 3.72, 3.28, colour=DANGER, width=1.4, tail=False)
arrow(s, 3.45, 3.28, 3.95, 3.28, colour=INK, width=1.0)

box(s, 4.0, 2.82, 2.0, 0.92, fill=SUNKEN, outline=RULE, width=0.9)
text(s, 4.16, 2.96, 1.8, 0.6, [
    [("GuardReport", 11.5, False, INK, MONO)],
    [("按 kind + subjects 去重", 9, False, MUTED, SANS)],
], spacing=1.2)

box(s, 4.0, 1.80, 2.0, 0.92, fill=GROUND, outline=INK, width=1.1)
text(s, 4.16, 1.94, 1.8, 0.6, [
    [("采样帧", 12.5, True, INK, SANS)],
    [("5 帧均匀 + guard 命中时刻", 9, False, MUTED, SANS)],
], spacing=1.2)

# into the VLM
arrow(s, 6.0, 2.26, 6.35, 2.26, colour=INK, width=1.0, tail=False)
arrow(s, 6.35, 2.26, 6.35, 2.60, colour=INK, width=1.0, tail=False)
arrow(s, 6.0, 3.28, 6.55, 3.28, colour=INK, width=1.0)
text(s, 6.08, 3.03, 1.9, 0.22, [("“实测，非猜测”", 9, False, MUTED, MONO)])

box(s, 6.6, 2.30, 3.0, 1.45, fill=GROUND, outline=INK, width=1.1)
text(s, 6.78, 2.44, 2.7, 1.2, [
    [("独立 VLM 审查", 14, True, INK, SANS)],
    [("一次结构化 vision 调用", 9.5, False, MUTED, SANS)],
    [("score · brief_adherence", 9.5, False, INK, MONO)],
    [("key_elements 必须分类", 9.5, False, INK, MONO)],
    [("blocking / minor / ops", 9.5, False, INK, MONO)],
], spacing=1.18)

arrow(s, 8.1, 3.75, 8.1, 4.34, colour=INK, width=1.0)

# _to_repair
box(s, 3.7, 4.38, 8.5, 1.45, fill=SURFACE, outline=INK, width=1.1)
text(s, 3.92, 4.50, 8.1, 1.25, [
    [("_to_repair() — 三条覆写规则，都只往 blocking_issues 里加", 11.5, False, INK, MONO)],
    [("① key element 没列全 → 未分类的按“缺失”算（fail closed）", 11, False, INK, SANS)],
    [("② minor / layout / temporal 里出现实观缺陷措辞 → 提升为 blocking", 11, False, INK, SANS)],
    [("③ guard 的 kind ∈ {text_overlap, text_occluded} → blocking，无视 severity", 11, False, DANGER, SANS)],
], spacing=1.28)

# the red annotation: static guess rides the measured channel
arrow(s, 1.97, 4.76, 1.97, 5.12, colour=DANGER, width=1.3, dashed=True, tail=False)
arrow(s, 1.97, 5.12, 3.66, 5.12, colour=DANGER, width=1.3, dashed=True)
text(s, 0.5, 5.18, 3.1, 0.24, [("静态猜测走了实测证据的通道", 10, False, DANGER, SANS)])

arrow(s, 8.1, 5.83, 8.1, 6.10, colour=INK, width=1.0)
box(s, 5.2, 6.14, 4.7, 0.62, fill=GROUND, outline=INK, width=1.1)
text(s, 5.4, 6.24, 4.4, 0.45, [
    [("finalize(pass_score = 7)", 11.5, False, INK, MONO)],
    [("passed = 没有任何 blocking，且 score ≥ 7", 10, False, MUTED, SANS)],
], spacing=1.2)

text(s, 0.5, 6.92, 12.3, 0.3, [[
    ("通过 → Stage 3　　", 11, False, SECONDARY, SANS),
    ("不通过 → repair_router：先按 ops 定点打补丁（只打一次）→ 再失败则整段重生成　　", 11, False, PRIMARY, SANS),
    ("reviewer 自己挂了 → 转人工，绝不放行", 11, False, MUTED, SANS),
]])


# ----------------------------------------------------------- slide 4 问题总览
s = slide()
heading(s, "5 个问题", "全部落在现有 194 个测试的覆盖之外；前两条已复现或路径可直接追")

rows = [
    ("高", DANGER, "静态网格检查会把提示词自己教的写法判死刑",
     "正则扫出的重叠共用了 text_overlap，被规则 ③ 当成实测证据 → 永远修不好，三轮烧完转人工",
     "reviewer.py:448 / 342 · manim.py:117"),
    ("高", DANGER, "guard 重试被否决后，磁盘上的 mp4 已经是被否决的那一版",
     "重试写同一个 out 路径；spec 回滚了，视频没回滚。fingerprint 判定“已最新”，之后永不重渲",
     "workflow.py:735 / 742"),
    ("中", AMBER, "resume 时新场景被老场景的 attempt 吃掉预算",
     "起始轮次取所有 target 的最大 attempt；新场景本该有 3 次机会，实际只拿到 1 次",
     "workflow.py:1181"),
    ("中", AMBER, "reviewer 挂掉时单场景单轮最多 4 次 vision",
     "两层重试嵌套相乘，外层还各 sleep 2 秒 —— 对一门课约 $1.66 的成本模型是个放大器",
     "workflow.py:1055 · reviewer.py:272"),
    ("低", MUTED, "静态网格 finding 渗进持久化的 guard 报告",
     "它是复审期算的却不在 REVIEW_TIME_GUARD_KINDS 里；源码猜测和实测几何混在一起",
     "workflow.py:1083"),
]
y = 1.72
for sev, colour, title, desc, where in rows:
    stripe(s, 0.5, y, 0.035, 0.88, colour)
    text(s, 0.72, y - 0.02, 0.5, 0.24, [(sev, 10, False, colour, MONO)])
    text(s, 1.35, y - 0.03, 7.6, 0.3, [(title, 14, True, INK, SANS)])
    text(s, 1.35, y + 0.28, 8.4, 0.28, [(desc, 10.5, False, MUTED, SANS)])
    text(s, 9.95, y + 0.01, 2.9, 0.5, [(where, 9.5, False, MUTED, MONO)], spacing=1.2)
    stripe(s, 0.5, y + 0.98, 12.33, 0.008, RULE)
    y += 1.12


# ------------------------------------------------------------- slide 5 问题 ①
s = slide()
heading(s, "问题 ①　静态网格检查会把提示词自己教的写法判死刑")

stripe(s, 0.5, 1.62, 0.035, 2.3, DANGER)
text(s, 0.85, 1.62, 7.1, 2.4, [
    [("_grid_layout_findings 用正则扫源码里的 place_in_area，发现两个对象占了同一格", 13, False, INK, SANS)],
    [("就报 kind=“text_overlap”。而 _to_repair 的规则 ③ 只看 kind、不看 severity，", 13, False, INK, SANS)],
    [("于是这条静态猜测直接变成 blocking。", 13, False, INK, SANS)],
    [(" ", 8, False, INK, SANS)],
    [("要命的是：Manim 的创作提示词明确教模型复用同一块区域 ——", 13, False, INK, SANS)],
    [("“show one, FadeOut its braces and labels, then show the next in the same place”。", 11.5, False, MUTED, MONO)],
    [("正则没有时间概念，看不出两个对象根本不同时存在，照样判重叠。", 13, False, INK, SANS)],
], spacing=1.34)

box(s, 0.85, 4.20, 7.1, 1.25, fill=SUNKEN, outline=RULE, width=0.9)
text(s, 1.05, 4.34, 6.8, 1.0, [
    [("VLM 打 9 分、零问题 → passed = False", 11, False, INK, MONO)],
    [("blocking: ['[layout guard] Code2Video grid anchors for", 11, False, INK, MONO)],
    [("           brace_a and brace_b share E1..E6; ...']", 11, False, INK, MONO)],
], spacing=1.25)
text(s, 0.85, 5.56, 7.1, 0.24, [("已复现", 10, False, DANGER, MONO)])

box(s, 8.35, 1.62, 4.48, 3.83, fill=SURFACE, outline=RULE, width=0.9)
text(s, 8.6, 1.80, 4.0, 0.24, [("怎么修", 10.5, False, SECONDARY, MONO)])
text(s, 8.6, 2.15, 4.0, 3.1, [
    [("给它一个自己的 kind，比如", 12, False, INK, SANS)],
    [("grid_anchor_overlap", 11.5, False, DANGER, MONO)],
    [("让 major 老老实实降级成 minor，把判断", 12, False, INK, SANS)],
    [("交还给看得见画面的 VLM。", 12, False, INK, SANS)],
    [(" ", 8, False, INK, SANS)],
    [("这正是它自己 docstring 写的意图：", 12, False, MUTED, SANS)],
    [("“A visual reviewer still decides whether", 10.5, False, MUTED, MONO)],
    [(" a deliberate shared panel is readable”", 10.5, False, MUTED, MONO)],
    [("—— 代码没兑现这句话。", 12, False, MUTED, SANS)],
    [(" ", 8, False, INK, SANS)],
    [("更彻底：让检查感知时间，只比较同时在场", 12, False, INK, SANS)],
    [("的对象。", 12, False, INK, SANS)],
], spacing=1.32)

text(s, 0.5, 5.95, 12.3, 0.3, [("reviewer.py:448　发出 text_overlap / major　·　reviewer.py:342　layout_blocker = finding.kind in {...}　·　manim.py:117　提示词教的顺序复用写法", 10, False, MUTED, MONO)])


# ------------------------------------------------------------- slide 6 问题 ②
s = slide()
heading(s, "问题 ②　guard 重试被否决后，磁盘上的 mp4 已经是被否决的那一版")

# before / after of the retry path — the difference is what the picture shows
text(s, 0.5, 1.62, 5.8, 0.24, [("现在的行为", 10.5, False, DANGER, MONO)])
box(s, 0.5, 1.95, 5.8, 3.4, fill=SURFACE, outline=DANGER, width=1.2)
steps_now = [
    ("① 第一次渲染", "→ media/<id>.mp4", INK),
    ("② guard 报 blocker，重试", "→ 写同一个 media/<id>.mp4", DANGER),
    ("③ 重试更差，代码回滚 spec", "→ spec 回到第一版", INK),
    ("④ 返回第一次的 RenderedScene", "→ 但 mp4 已经是第二版", DANGER),
    ("⑤ render_fingerprint 拿回滚后的 spec 算", "→ 判定“已最新”，永不重渲", DANGER),
]
yy = 2.15
for label, effect, colour in steps_now:
    text(s, 0.72, yy, 5.4, 0.26, [(label, 11.5, False, INK, SANS)])
    text(s, 0.95, yy + 0.28, 5.2, 0.24, [(effect, 10.5, False, colour, MONO)])
    yy += 0.63

text(s, 6.9, 1.62, 5.9, 0.24, [("应该的行为", 10.5, False, SECONDARY, MONO)])
box(s, 6.9, 1.95, 5.93, 3.4, fill=SURFACE, outline=SECONDARY, width=1.2)
steps_fix = [
    ("① 第一次渲染", "→ media/<id>.mp4", INK),
    ("② 重试渲到临时路径", "→ media/<id>.retry.mp4", SECONDARY),
    ("③ 比较 _guard_defect_score", "→ 只有真的降了才提升", SECONDARY),
    ("④ 否决则删掉临时文件", "→ 磁盘与 checkpoint 一致", SECONDARY),
    ("⑤ 跟这段代码已经对 spec 做的事保持一致", "", SECONDARY),
]
yy = 2.15
for label, effect, colour in steps_fix:
    text(s, 7.12, yy, 5.5, 0.26, [(label, 11.5, False, INK, SANS)])
    if effect:
        text(s, 7.35, yy + 0.28, 5.3, 0.24, [(effect, 10.5, False, colour, MONO)])
    yy += 0.63

text(s, 0.5, 5.62, 12.3, 0.85, [
    [("后果：rendered_scenes.json 记的是第一版的 guard 结果和 visual_seconds，磁盘上躺的是第二版的画面 ——", 12, False, INK, SANS)],
    [("正是那段代码注释想避免的不一致，只是方向反了。时长对不上会一路带到 bundle 的 timeline。", 12, False, INK, SANS)],
], spacing=1.35)
text(s, 0.5, 6.62, 12.3, 0.3, [("workflow.py:735　retried = _render_one(...) 写同一个 out 路径　·　workflow.py:742　回滚 spec，返回第一次的 result", 10, False, MUTED, MONO)])


out = Path(__file__).resolve().parent / "eduharness-audit.pptx"
prs.save(out)
print(f"wrote {out}  ({out.stat().st_size / 1024:.0f} KB, {len(prs.slides.__iter__.__self__._sldIdLst)} slides)")
