"""Paper-style pipeline figure for EduHarness (single figure, print-safe)."""
from pathlib import Path
from xml.sax.saxutils import escape

INK, LINE, TINT, SOFT, GROUND = "#17201B", "#2A332D", "#E4EDF2", "#F2F4F1", "#FFFFFF"
ACC, LOOP = "#356B8F", "#B4423D"
SANS = "Inter, Helvetica Neue, Arial, sans-serif"
o: list[str] = []


def T(x, y, t, s=11.5, fill=INK, op=1.0, w=400, anchor="start", ls=0, style=""):
    st = f' font-style="{style}"' if style else ""
    o.append(f'<text x="{x:.1f}" y="{y:.1f}" font-family="{SANS}" font-size="{s}" fill="{fill}" '
             f'fill-opacity="{op}" font-weight="{w}" text-anchor="{anchor}" letter-spacing="{ls}"{st}>'
             f'{escape(t)}</text>')


def stage(x, y, w, h, title, sub, *, fill=GROUND, accent=LINE, lw=1.3, num=None):
    o.append(f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="3" fill="{fill}" '
             f'stroke="{accent}" stroke-width="{lw}"/>')
    cx = x + w / 2
    if num:
        T(cx, y + 21, num, 9.5, ACC, 0.95, 700, "middle", 1.1)
        T(cx, y + 45, title, 15, INK, 1.0, 700, "middle")
        ty = y + 63
    else:
        T(cx, y + 34, title, 15, INK, 1.0, 700, "middle")
        ty = y + 54
    for i, line in enumerate(sub):
        T(cx, ty + i * 14.5, line, 10.8, INK, 0.72, 400, "middle")


def arw(d, color=LINE, width=1.4, dashed=False, mark="a"):
    dash = ' stroke-dasharray="4 3"' if dashed else ""
    o.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}"{dash} '
             f'marker-end="url(#{mark})"/>')


W, H = 1452, 430
M = 28
BW, GAP = 152, 46
x1, x2 = M, M + BW + GAP
cx_l, cw = 424, 600
x3, x4, x5 = 456, 654, 852
x6, x7 = 1070, 1268
BY, BH = 104, 84
MID = BY + BH / 2
SY, SH = 204, 68

# ---- container
o.append(f'<rect x="{cx_l}" y="58" width="{cw}" height="272" rx="4" fill="{SOFT}" '
         f'stroke="{LINE}" stroke-opacity="0.55" stroke-width="1.1" stroke-dasharray="6 4"/>')
T(cx_l + cw / 2, 80, "Stage 2  ·  per-scene loop, at most R review rounds", 11.8, INK, 0.66, 600, "middle", 0.4)

# ---- stages
stage(x1, BY, BW, BH, "Lesson request", ["topic · audience", "source material"])
stage(x2, BY, BW, BH, "Planner", ["one structured", "LLM call"], fill=TINT, accent=ACC, num="STAGE 1")
stage(x3, BY, BW, BH, "Prepare", ["tool specs, images,", "narration"], fill=TINT, accent=ACC)
stage(x4, BY, BW, BH, "Render", ["sandboxed,", "offline"])
stage(x5, BY, BW, BH, "Review", ["vision audit over", "sampled frames"], fill=TINT, accent=ACC)
stage(x6, BY, BW, BH, "EduBundle", ["manifest, media,", "interactive JSON"], num="STAGE 3")
stage(x7, BY, BW, BH, "Player", ["narrated video +", "practice nodes"])

# ---- support boxes
o.append(f'<rect x="{x3}" y="{SY}" width="{BW}" height="{SH}" rx="3" fill="{GROUND}" '
         f'stroke="{LINE}" stroke-opacity="0.55" stroke-width="1"/>')
T(x3 + BW / 2, SY + 19, "four scene types", 10.4, INK, 0.62, 600, "middle", 0.3)
for i, name in enumerate(["image · manim", "remotion · interactive"]):
    T(x3 + BW / 2, SY + 38 + i * 15, name, 11, INK, 0.85, 500, "middle")

o.append(f'<rect x="{x4}" y="{SY}" width="{BW}" height="{SH}" rx="3" fill="{GROUND}" '
         f'stroke="{LINE}" stroke-opacity="0.55" stroke-width="1"/>')
T(x4 + BW / 2, SY + 19, "deterministic guard", 10.4, INK, 0.62, 600, "middle", 0.3)
for i, name in enumerate(["measured overlap,", "clipping, blank frames"]):
    T(x4 + BW / 2, SY + 38 + i * 15, name, 11, INK, 0.85, 500, "middle")

# ---- arrows along the spine
arw(f"M {x1+BW} {MID} L {x2-6} {MID}")
arw(f"M {x2+BW} {MID} L {x3-6} {MID}")
T((x2 + BW + x3) / 2, MID - 10, "blueprint", 10.4, INK, 0.7, 600, "middle")
arw(f"M {x3+BW} {MID} L {x4-6} {MID}")
arw(f"M {x4+BW} {MID} L {x5-6} {MID}")
arw(f"M {x5+BW} {MID} L {x6-6} {MID}")
T((x5 + BW + x6) / 2, MID - 10, "pass", 10.4, INK, 0.75, 600, "middle")
arw(f"M {x6+BW} {MID} L {x7-6} {MID}")

# guard evidence -> review
arw(f"M {x4+BW} {SY+SH/2} L {x5+76+26} {SY+SH/2} L {x5+76+26} {BY+BH+6}", LINE, 1.2, True)
T(x5 + 76 + 34, SY + SH / 2 - 7, "evidence", 10.2, INK, 0.62, 500)

# repair loop
LOOPY, ENTRY = 302, BY + 66
arw(f"M {x5+62} {BY+BH} L {x5+62} {LOOPY} L 436 {LOOPY} L 436 {ENTRY} L {x3-6} {ENTRY}", LOOP, 1.4, mark="r")
T((436 + x5 + 62) / 2, LOOPY - 8, "fail  \u2192  repair: apply patch ops, else regenerate the scene",
  10.8, LOOP, 1.0, 600, "middle")

# ---- caption
cap = [
    "Figure 1:  The EduHarness pipeline.  A single planning call turns a lesson request into a scene-level blueprint "
    "(scenes, checkable key elements, narration and a pinned style board).",
    "Each scene is then prepared, rendered in a sandbox, and audited by a deterministic layout guard together with an "
    "independent vision reviewer that must account for every key element.",
    "A scene is packaged only once it clears both; otherwise it re-enters the loop as a targeted repair, at most R times.  "
    "Shaded stages are the only ones that call a model.",
]
for i, line in enumerate(cap):
    T(M, 364 + i * 17, line, 11.6, INK, 0.8, 400)

defs = ('<defs><marker id="a" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><polygon points="0,1 10,5 0,9" fill="{LINE}"/></marker>'
        '<marker id="r" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="7" markerHeight="7" '
        f'orient="auto-start-reverse"><polygon points="0,1 10,5 0,9" fill="{LOOP}"/></marker></defs>')
svg = (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" width="{W}" height="{H}" role="img" '
       f'aria-label="EduHarness pipeline: request, planner, per-scene prepare-render-review loop with repair, bundle, player">'
       f'{defs}<rect x="0" y="0" width="{W}" height="{H}" fill="#FFFFFF"/>' + "".join(o) + "</svg>")
svg = svg.replace('url(#a)" ', 'url(#a)" ')  # no-op
dst = Path("/data/chenqingyue/education_video/eduharness/docs/audit/fig-pipeline.svg")
dst.write_text(svg, encoding="utf-8")
print("wrote", dst, W, "x", H)
