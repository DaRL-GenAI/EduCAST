import React from "react";
import { AbsoluteFill, cancelRender, continueRender, delayRender, Easing, interpolate, staticFile, useCurrentFrame, useVideoConfig } from "remotion";

export type StyleTokens = {
  palette?: { background?: string; primary?: string; secondary?: string; text?: string; muted?: string; danger?: string };
  typography?: { font_family?: string; base_size?: string; heading_scale?: number };
  layout?: { safe_padding?: string; width?: number; height?: number; title_ratio?: number; content_top_ratio?: number; content_bottom_ratio?: number };
};
export type Rect = { x: number; y: number; width: number; height: number };
export type TeachingBoard = { width: number; height: number; title: string; lecture_lines: string[]; takeaway: string; regions: { title: Rect; lecture: Rect; visual: Rect; main: Rect; result: Rect; footer: Rect }; font?: { title?: number; body?: number; small?: number } };
export type SceneBeatProps = {
  beat?: "title_card" | "bullets" | "formula" | "compare" | "steps" | "recap" | "stat_row";
  stats?: { value: string; unit?: string; name?: string }[];
  sceneLabel?: string; sceneIndex?: number; sceneTotal?: number; title: string; subtitle?: string;
  bullets?: string[]; formula?: string; highlights?: string[]; left_title?: string; left_items?: string[]; right_title?: string; right_items?: string[];
  steps?: string[]; accent_label?: string; character?: number; motion?: string; durationInSeconds?: number; style?: StyleTokens;
  lecture_lines?: string[]; takeaway?: string; visual_area?: string; result_area?: string; board?: TeachingBoard;
};

export const sceneBeatDefaultProps: SceneBeatProps = {
  beat: "bullets", title: "Teaching Scene", bullets: ["Point one", "Point two"], motion: "fade-up", durationInSeconds: 8,
  lecture_lines: ["State the idea", "Connect it to the example"], takeaway: "Remember the relationship.",
  style: { palette: { background: "#FAFBF8", primary: "#356B8F", secondary: "#16734A", text: "#17201B", muted: "#66706A", danger: "#B4423D" }, typography: { font_family: "Inter", base_size: "16px", heading_scale: 1.25 }, layout: { safe_padding: "40px", width: 1920, height: 1080, title_ratio: 0.14, content_top_ratio: 0.18, content_bottom_ratio: 0.84 } },
};

type Tokens = { bg: string; primary: string; secondary: string; text: string; muted: string; danger: string; font: string; base: number; heading: number; pad: number; w: number; h: number };
function tokens(style?: StyleTokens): Tokens {
  const p = style?.palette || {}; const ty = style?.typography || {}; const l = style?.layout || {};
  return { bg: p.background || "#FAFBF8", primary: p.primary || "#356B8F", secondary: p.secondary || "#16734A", text: p.text || "#17201B", muted: p.muted || "#66706A", danger: p.danger || "#B4423D", font: `"${ty.font_family || "Inter"}", Inter, "Liberation Sans", sans-serif`, base: Number.parseFloat(ty.base_size || "16") || 16, heading: Number(ty.heading_scale || 1.25), pad: Number.parseFloat(l.safe_padding || "40") || 40, w: Number(l.width) || 1920, h: Number(l.height) || 1080 };
}
function fallbackBoard(t: Tokens, props: SceneBeatProps): TeachingBoard {
  const safeW = t.w - 2 * t.pad; const lectureW = Math.round(safeW * 0.28); const gap = Math.round(safeW * 0.04); const top = Math.round(t.h * (props.style?.layout?.content_top_ratio || 0.18)); const bottom = Math.round(t.h * (props.style?.layout?.content_bottom_ratio || 0.84)); const visualX = t.pad + lectureW + gap; const visualW = safeW - lectureW - gap; const resultH = Math.round((bottom - top) * 0.23); const mainH = bottom - top - resultH - gap;
  return { width: t.w, height: t.h, title: props.title, lecture_lines: props.lecture_lines || [], takeaway: props.takeaway || "", regions: { title: { x: t.pad, y: t.pad, width: safeW, height: Math.round(t.h * (props.style?.layout?.title_ratio || 0.14)) }, lecture: { x: t.pad, y: top, width: lectureW, height: bottom - top }, visual: { x: visualX, y: top, width: visualW, height: bottom - top }, main: { x: visualX, y: top, width: visualW, height: mainH }, result: { x: visualX, y: top + mainH + gap, width: visualW, height: resultH }, footer: { x: t.pad, y: bottom, width: safeW, height: t.h - bottom - t.pad } } };
}
function useReveal(start: number, length: number): number { return interpolate(useCurrentFrame(), [start, start + length], [0, 1], { extrapolateLeft: "clamp", extrapolateRight: "clamp" }); }
// `highlights` names the tokens a scene promised to emphasise. It used to be
// declared here, filled by the model, and then dropped on the floor: no code
// path drew it, so any key element asking for a highlighted term could never be
// satisfied on a Remotion beat, however many repair rounds it was given.
function withHighlights(text: string | undefined, tokens: string[] | undefined, color: string): React.ReactNode {
  const wanted = (tokens || []).map((x) => String(x).trim()).filter(Boolean).sort((a, b) => b.length - a.length);
  if (!text || !wanted.length) return text;
  const pattern = wanted.map((x) => x.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")).join("|");
  const parts = text.split(new RegExp(`(${pattern})`, "g"));
  return parts.map((part, i) => (wanted.includes(part)
    ? <span key={i} style={{ color, fontWeight: 800 }}>{part}</span>
    : <React.Fragment key={i}>{part}</React.Fragment>));
}
function FitText({ t, text, box, size = 28, color, weight = 400, align = "left", revealText = true, highlight, highlightColor }: { t: Tokens; text?: string; box: Rect; size?: number; color?: string; weight?: number; align?: "left" | "center"; revealText?: boolean; highlight?: string[]; highlightColor?: string }) {
  const textRef = React.useRef<HTMLDivElement>(null);
  const [handle] = React.useState(() => delayRender("Fit teaching-board text"));
  const [fitted, setFitted] = React.useState(size);
  const reveal = revealText ? useReveal(0, 14) : 1;
  const padding = Math.min(t.base * 0.8, box.width * 0.05, box.height * 0.05);
  React.useLayoutEffect(() => {
    let disposed = false;
    const fit = async () => {
      await document.fonts.ready;
      if (disposed) return;
      const node = textRef.current;
      if (!node) { continueRender(handle); return; }
      const available = box.height - padding * 2;
      const fits = (fontSize: number) => {
        node.style.fontSize = `${fontSize}px`;
        return node.scrollHeight <= available + 0.5 && node.scrollWidth <= box.width - padding * 2 + 0.5;
      };
      const minimum = Math.min(size, Math.max(5, t.base * 0.75));
      if (!fits(minimum)) {
        throw new Error(`Teaching-board text cannot fit in ${box.width}x${box.height} pixels: ${text}`);
      }
      let low = minimum; let high = size;
      for (let i = 0; i < 12; i++) {
        const candidate = (low + high) / 2;
        if (fits(candidate)) low = candidate; else high = candidate;
      }
      node.style.fontSize = `${low}px`;
      setFitted(low);
      requestAnimationFrame(() => { if (!disposed) continueRender(handle); });
    };
    fit().catch(cancelRender);
    return () => { disposed = true; };
  }, [box.height, box.width, handle, padding, size, t.base, t.font, text, weight, (highlight || []).join("\u0001")]);
  return <div data-board-text style={{ position: "absolute", left: box.x, top: box.y, width: box.width, height: box.height, boxSizing: "border-box", padding, color: color || t.text, fontWeight: weight, textAlign: align, display: "flex", flexDirection: "column", justifyContent: "center", overflow: "hidden", opacity: reveal }}>
    <div ref={textRef} style={{ width: "100%", fontSize: fitted, lineHeight: 1.28, whiteSpace: "pre-wrap", overflowWrap: "anywhere", flexShrink: 0 }}>{withHighlights(text, highlight, highlightColor || t.secondary)}</div>
  </div>;
}
function Lecture({ t, box, lines }: { t: Tokens; box: Rect; lines: string[] }) {
  const clean = lines.filter((line) => line.trim()); if (!clean.length) return null; const text = clean.map((line, i) => `${i + 1}. ${line}`).join("\n");
  return <FitText t={t} text={text} box={box} size={t.base * 1.7} color={t.text} weight={500} />;
}
function Card({ t, children, box, color = t.primary }: { t: Tokens; children: React.ReactNode; box: Rect; color?: string }) {
  return <div style={{ position: "absolute", left: box.x, top: box.y, width: box.width, height: box.height, boxSizing: "border-box", padding: t.base * 1.2, border: `3px solid ${color}66`, borderRadius: 8, backgroundColor: t.bg, backgroundImage: `linear-gradient(${color}0b, ${color}0b)`, overflow: "hidden", zIndex: 1 }}>{children}</div>;
}
function MainVisual({ t, props, board }: { t: Tokens; props: SceneBeatProps; board: TeachingBoard }) {
  const box = board.regions.main; const beat = props.beat || "bullets"; const inset = t.base * 1.2; const inner: Rect = { x: inset, y: inset, width: box.width - inset * 2, height: box.height - inset * 2 };
  if (beat === "formula") return <Card t={t} box={box}><FitText t={t} text={props.formula} highlight={props.highlights} box={{ x: inner.x, y: inner.y, width: inner.width, height: inner.height * 0.44 }} size={t.base * 3.7} color={t.primary} weight={700} align="center" /><FitText t={t} text={(props.bullets || []).map((x) => `• ${x}`).join("\n")} box={{ x: inner.x, y: inner.y + inner.height * 0.44, width: inner.width, height: inner.height * 0.52 }} size={t.base * 1.55} color={t.text} /> </Card>;
  if (beat === "compare") {
    // A compare scene often carries the rule both sides are being measured against.
    // The field used to be filled and then dropped on the floor, so a brief that
    // required the formula could never be satisfied by this beat.
    const strip = props.formula ? inner.height * 0.22 : 0;
    const columns = inner.height - strip;
    return <Card t={t} box={box} color={t.secondary}>
      <FitText t={t} text={[props.left_title, ...(props.left_items || []).map((x) => `• ${x}`)].filter(Boolean).join("\n")} box={{ x: inner.x, y: inner.y, width: inner.width * 0.47, height: columns }} size={t.base * 1.45} color={t.danger} weight={600} />
      <FitText t={t} text={[props.right_title, ...(props.right_items || []).map((x) => `• ${x}`)].filter(Boolean).join("\n")} box={{ x: inner.x + inner.width * 0.51, y: inner.y, width: inner.width * 0.47, height: columns }} size={t.base * 1.45} color={t.secondary} weight={600} />
      {props.formula ? <FitText t={t} text={props.formula} highlight={props.highlights} box={{ x: inner.x, y: inner.y + columns, width: inner.width, height: strip }} size={t.base * 2.4} color={t.primary} weight={700} align="center" /> : null}
    </Card>;
  }
  if (beat === "steps") return <Card t={t} box={box}><FitText t={t} text={(props.steps || []).map((x, i) => `${i + 1}. ${x}`).join("\n")} box={inner} size={t.base * 1.7} color={t.text} weight={600} /></Card>;
  if (beat === "stat_row") {
    const stats = props.stats || []; const rows = Math.max(1, Math.ceil(stats.length / 2));
    const cellWidth = (inner.width - t.base) / 2; const cellHeight = (inner.height - (rows - 1) * t.base) / rows;
    return <>{stats.map((s, i) => <Card key={`${i}-${s.value}`} t={t} color={i % 2 ? t.secondary : t.primary} box={{ x: box.x + inner.x + (i % 2) * (cellWidth + t.base), y: box.y + inner.y + Math.floor(i / 2) * (cellHeight + t.base), width: cellWidth, height: cellHeight }}>
      <FitText t={t} text={[s.value, s.unit].filter((value) => value !== undefined && value !== "").join(" ")} box={{ x: 0, y: 0, width: cellWidth - 6, height: cellHeight * 0.63 }} size={t.base * 3} color={i % 2 ? t.secondary : t.primary} weight={700} align="center" />
      <FitText t={t} text={s.name || ""} box={{ x: 0, y: cellHeight * 0.63, width: cellWidth - 6, height: cellHeight * 0.34 }} size={t.base * 1.3} color={t.muted} align="center" />
    </Card>)}</>;
  }
  const text = beat === "title_card" ? [props.subtitle, props.accent_label].filter(Boolean).join("\n") : beat === "recap" ? [...(props.bullets || []).map((x) => `• ${x}`), props.formula].filter(Boolean).join("\n") : (props.bullets || []).map((x) => `• ${x}`).join("\n");
  return <Card t={t} box={box}><FitText t={t} text={text} highlight={beat === "title_card" ? undefined : props.highlights} box={inner} size={beat === "title_card" ? t.base * 2.2 : t.base * 1.8} color={t.text} weight={500} /></Card>;
}

// ---------------------------------------------------------------- title card
// The opener is deliberately NOT the teaching board: no title band, no lecture
// column, no result strip. It is one hard-coded stage — a cast leaning in from
// the two bottom corners while the title and subtitle surface in the middle.
const TITLE_CAST = { left: [1, 2], right: [4, 3] };
const CAST_HEIGHT_RATIO = 0.52;   // of the frame height
const CAST_ASPECT = 0.62;         // the character art is ~430x700
const CAST_SUBMERGE = 0.17;       // how much of each body stays below the frame
const CAST_HUG = 0.36;            // shoulder overlap: characters touch, no gaps
const CAST_CORNER_BITE = 0.2;     // how far the outermost one leans past the edge

function TitleCast({ t }: { t: Tokens }) {
  const frame = useCurrentFrame();
  const height = t.h * CAST_HEIGHT_RATIO;
  const width = height * CAST_ASPECT;
  const step = width * (1 - CAST_HUG);
  const bottom = -t.h * CAST_SUBMERGE;
  return <>{(["left", "right"] as const).flatMap((side) =>
    TITLE_CAST[side].map((character, index) => {
      // Each one climbs into frame a beat after the one before it.
      const start = 6 + index * 5;
      const rise = interpolate(frame, [start, start + 26], [height * 0.55, 0],
        { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.cubic) });
      const offset = index * step - width * CAST_CORNER_BITE;
      return <img
        key={`${side}-${character}`}
        src={staticFile(`characters/character-${character}.png`)}
        alt=""
        style={{
          position: "absolute", bottom, width, height, objectFit: "contain",
          objectPosition: "bottom center", pointerEvents: "none", zIndex: 1,
          transform: `translateY(${rise}px)`,
          ...(side === "left" ? { left: offset } : { right: offset }),
        }}
      />;
    }))}</>;
}

function TitleCard({ t, props }: { t: Tokens; props: SceneBeatProps }) {
  const frame = useCurrentFrame();
  // No trailing fade: a scene that dissolves to nothing ends on a flat frame, which
  // the blank-frame guard blocks (rightly — it cannot tell "designed" from "dead").
  // The player cuts between scenes, so hold the composition to the last frame.
  // Slow surfacing: ~1.5s for the title, the subtitle trailing it by half a second.
  const surface = (start: number, length: number) => interpolate(frame, [start, start + length], [0, 1],
    { extrapolateLeft: "clamp", extrapolateRight: "clamp", easing: Easing.out(Easing.ease) });
  const title = surface(8, 45);
  const subtitle = surface(30, 45);
  const label = surface(58, 40);
  const inset = t.pad * 2;
  const lift = (reveal: number, distance: number) => `translateY(${(1 - reveal) * distance}px)`;
  // Fade the content, never the ground: dropping the whole fill to opacity 0
  // reveals the composition's transparent background, which encodes as a flat
  // black frame and reads to the guards (rightly) as a dead scene.
  return <AbsoluteFill style={{ backgroundColor: t.bg, color: t.text, fontFamily: t.font, overflow: "hidden" }}>
   <AbsoluteFill>
    <div style={{ position: "absolute", left: 0, right: 0, top: t.h * 0.3, height: t.h * 0.42, zIndex: 2 }}>
      <div style={{ position: "absolute", left: inset, top: 0, width: t.w - inset * 2, height: t.h * 0.2, opacity: title, transform: lift(title, 28) }}>
        <FitText t={t} text={props.title} box={{ x: 0, y: 0, width: t.w - inset * 2, height: t.h * 0.2 }} size={t.base * t.heading * 4.2} color={t.primary} weight={700} align="center" revealText={false} />
      </div>
      <div style={{ position: "absolute", left: (t.w - t.w * 0.12) / 2, top: t.h * 0.225, width: t.w * 0.12, height: 7, background: t.secondary, opacity: title, transform: lift(title, 20) }} />
      <div style={{ position: "absolute", left: inset * 1.5, top: t.h * 0.27, width: t.w - inset * 3, height: t.h * 0.1, opacity: subtitle, transform: lift(subtitle, 22) }}>
        <FitText t={t} text={props.subtitle} box={{ x: 0, y: 0, width: t.w - inset * 3, height: t.h * 0.1 }} size={t.base * 1.9} color={t.text} weight={500} align="center" revealText={false} />
      </div>
      <div style={{ position: "absolute", left: inset, top: t.h * 0.38, width: t.w - inset * 2, height: t.h * 0.06, opacity: label, transform: lift(label, 16) }}>
        <FitText t={t} text={props.accent_label} box={{ x: 0, y: 0, width: t.w - inset * 2, height: t.h * 0.06 }} size={t.base * 1.1} color={t.muted} weight={600} align="center" revealText={false} />
      </div>
    </div>
    <TitleCast t={t} />
   </AbsoluteFill>
  </AbsoluteFill>;
}

function CharacterAccent({ t, props }: { t: Tokens; props: SceneBeatProps }) {
  const raw = Number(props.character || (((props.sceneIndex || 1) - 1) % 3) + 1);
  const character = Math.min(3, Math.max(1, Number.isFinite(raw) ? Math.round(raw) : 1));
  return <img
    src={staticFile(`characters/character-${character}.png`)}
    alt=""
    style={{ position: "absolute", right: t.pad, bottom: t.pad, width: t.w / 3, height: t.h / 3, objectFit: "contain", objectPosition: "right bottom", pointerEvents: "none", zIndex: 0 }}
  />;
}

export const SceneBeat: React.FC<SceneBeatProps> = (props) => {
  if (props.beat === "title_card") return <TitleCard t={tokens(props.style)} props={props} />;
  const t = tokens(props.style); const board = props.board || fallbackBoard(t, props); const r = board.regions; const frame = useCurrentFrame(); const lecture = props.lecture_lines?.length ? props.lecture_lines : board.lecture_lines; const takeaway = props.takeaway || board.takeaway;
  // The character sits in the bottom-right corner and is a third of the frame tall,
  // so it lands on the result strip: hand the takeaway the room left of it instead of
  // letting the last words disappear behind the art. The card itself also had to stop
  // being see-through -- a 4%-alpha fill let the art show straight through the result
  // card, which every reviewer read as "the character overlaps the takeaway card" and
  // scored as a blocking layout defect on otherwise clean recap scenes.
  const characterLeft = t.w - t.pad - t.w / 3;
  const resultTextWidth = Math.max(t.base * 6, Math.min(r.result.width - t.base * 0.6, characterLeft - r.result.x - t.base * 0.9));
  return <AbsoluteFill style={{ backgroundColor: t.bg, color: t.text, fontFamily: t.font, overflow: "hidden" }}><AbsoluteFill><div style={{ position: "absolute", inset: t.pad * 0.55, border: `1px solid ${t.primary}35`, boxSizing: "border-box" }} /><div style={{ position: "absolute", left: r.title.x, top: r.title.y + r.title.height - 8, width: 150, height: 7, background: t.secondary }} /><FitText t={t} text={props.title || board.title} box={r.title} size={board.font?.title || t.base * t.heading * 2.6} color={t.primary} weight={700} /><Lecture t={t} box={r.lecture} lines={lecture} /><MainVisual t={t} props={props} board={board} /><Card t={t} box={r.result} color={t.secondary}><FitText t={t} text={takeaway || props.formula} box={{ x: t.base * 0.3, y: t.base * 0.3, width: resultTextWidth, height: r.result.height - t.base * 0.6 }} size={board.font?.body || t.base * 1.8} color={t.secondary} weight={700} align="center" /></Card><CharacterAccent t={t} props={props} />{props.sceneTotal && props.sceneTotal > 1 ? <div style={{ position: "absolute", left: t.pad, bottom: t.pad * 0.55, width: (t.w - 2 * t.pad) * Math.min(1, ((props.sceneIndex || 0) + 1) / props.sceneTotal), height: 4, background: t.primary }} /> : null}</AbsoluteFill></AbsoluteFill>;
};
