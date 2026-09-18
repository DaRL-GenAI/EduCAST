/*
 * EduHarness trusted interactive runtime (zero dependencies).
 *
 * Every template is hand-written and parameter-driven: the model only supplies
 * numbers and short strings, which are always inserted as text nodes (never
 * HTML). Styling comes from the style_config CSS variables set by the player.
 */
(function (global) {
  "use strict";

  const SVG_NS = "http://www.w3.org/2000/svg";

  // ------------------------------------------------------------------ helpers
  function el(tag, attrs, children) {
    const node = document.createElement(tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "className") node.className = String(value);
      else if (key === "text") node.textContent = String(value);
      else if (key.startsWith("on") && typeof value === "function") {
        node.addEventListener(key.slice(2).toLowerCase(), value);
      } else if (value !== undefined && value !== null) {
        node.setAttribute(key, String(value));
      }
    });
    (Array.isArray(children) ? children : [children]).forEach((child) => {
      if (child == null) return;
      node.appendChild(typeof child === "string" ? document.createTextNode(child) : child);
    });
    return node;
  }

  function svg(tag, attrs, children) {
    const node = document.createElementNS(SVG_NS, tag);
    Object.entries(attrs || {}).forEach(([key, value]) => {
      if (key === "text") node.textContent = String(value);
      else if (value !== undefined && value !== null) node.setAttribute(key, String(value));
    });
    (Array.isArray(children) ? children : [children]).forEach((child) => {
      if (child != null) node.appendChild(child);
    });
    return node;
  }

  function appendAll(node, children) {
    children.forEach((child) => { if (child != null) node.appendChild(child); });
    return node;
  }

  function finite(value, fallback) {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : fallback;
  }

  function clamp(v, lo, hi) {
    return Math.min(hi, Math.max(lo, v));
  }

  function fmt(v, digits) {
    const d = digits == null ? 1 : digits;
    const n = Number(v);
    return Number.isInteger(n) ? String(n) : n.toFixed(d);
  }

  const STYLE_ID = "eh-runtime-style";
  const CSS = `
  .eh, .eh-board { --eh-primary: var(--primary, #3B82F6); --eh-secondary: var(--secondary, #10B981);
        --eh-text: var(--text, #F3F4F6); --eh-muted: var(--muted, #9CA3AF);
        --eh-danger: var(--danger, #EF4444); --eh-bg: var(--bg, #121214);
        --eh-base: var(--base-size, 16px); --eh-hs: var(--heading-scale, 1.25);
        --eh-line: color-mix(in srgb, var(--eh-muted) 32%, transparent);
        --eh-soft: color-mix(in srgb, var(--eh-primary) 15%, transparent);
        --eh-ok-soft: color-mix(in srgb, var(--eh-secondary) 16%, transparent);
        --eh-bad-soft: color-mix(in srgb, var(--eh-danger) 16%, transparent);
        --eh-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
        color: var(--eh-text); font-size: calc(var(--eh-base) * 1.05); line-height: 1.5; }
  .eh { display: flex; flex-direction: column; justify-content: safe center;
        gap: calc(var(--eh-base) * .9);
        width: 100%; height: 100%; max-width: 100%; margin: 0 auto; }
  /* Map the shared design coordinates without reparenting template children:
     event handlers retain their original root and footer references. */
  .eh-board { position: relative; width: 100%; height: 100%; min-width: 0; min-height: 0;
              overflow: hidden; container-type: size; container-name: teaching-board; }
  .eh-board, .eh-board * { box-sizing: border-box; }
  .eh-board .eh *, .eh-board { letter-spacing: 0; }
  .eh-has-board { padding: 0 !important; overflow: hidden !important; }
  .eh-board-region { position: absolute; min-width: 0; min-height: 0; overflow: hidden; }
  .eh-board-title { display: flex; align-items: flex-start; overflow: auto; }
  .eh-board-title h1 { margin: 0; max-width: 100%; color: var(--eh-primary); font-size: var(--eh-board-title-size, 48px);
                       line-height: 1.15; font-weight: 750; text-wrap: balance; overflow-wrap: anywhere; }
  .eh-board-notes { overflow: auto; overscroll-behavior: contain; }
  .eh-board-notes p { margin: 0 0 .7em; color: var(--eh-text); font-size: var(--eh-board-body-size, 30px);
                      line-height: 1.45; overflow-wrap: anywhere; }
  .eh-board-notes p:last-child { margin-bottom: 0; }
  .eh-board-visual { overflow: auto; overscroll-behavior: contain; scrollbar-gutter: stable; }
  .eh-board-visual > .eh { width: 100%; min-width: 0; min-height: 100%; height: auto; margin: 0;
                            justify-content: flex-start; overflow-wrap: anywhere; }
  .eh-board .eh > * { min-width: 0; flex-shrink: 0; }
  .eh-board .eh .eh-controls { grid-template-columns: repeat(auto-fit, minmax(min(100%, 190px), 1fr)); }
  .eh-board .eh .eh-row > *, .eh-board .eh .eh-choice > span { min-width: 0; max-width: 100%; }
  .eh-board .eh input[type=text] { min-width: 0; max-width: 100%; }
  .eh-board .eh-sentence input[type=text] { max-width: calc(100% - 12px); }
  .eh-board .eh .eh-chip { gap: 6px; padding: 8px; }
  .eh-board .eh .eh-chip .eh-grow { flex-basis: 0; }
  .eh-board .eh .eh-chip button { flex: 0 0 26px; padding: 0; }
  .eh-board .eh .eh-stage { flex: 0 0 auto; min-height: 110px; }
  .eh-board .eh svg.eh-svg { width: 100%; height: auto; }
  .eh-board-footer { display: flex; align-items: flex-end; overflow: auto; }
  .eh-board-footer p { margin: 0; color: var(--eh-muted); font-size: var(--eh-board-small-size, 19px);
                       line-height: 1.35; overflow-wrap: anywhere; }
  @container teaching-board (max-width: 1100px) {
    .eh-board-title h1 { font-size: 28px; }
    .eh-board-notes p { font-size: 17px; }
    .eh-board-footer p { font-size: 15px; }
  }
  @container teaching-board (max-width: 700px) {
    .eh-board-title h1 { font-size: 18px; }
    .eh-board-notes p { font-size: 13px; }
    .eh-board-footer p { font-size: 12px; }
    .eh-board .eh .eh-controls { grid-template-columns: minmax(0, 1fr); }
    .eh-board .eh h2 { font-size: 16px; }
    .eh-board .eh h2 .eh-badge { display: none; }
    .eh-board .eh .eh-choice, .eh-board .eh .eh-chip { padding: 7px; gap: 6px; }
  }
  /* prompt: dashboard badge pill above, task at a readable measure */
  .eh h2 { margin: 0; max-width: 48ch; color: var(--eh-text); font-weight: 650;
           font-size: clamp(18px, calc(var(--eh-base) * var(--eh-hs) * .95), 23px);
           line-height: 1.35; text-wrap: balance; }
  .eh h2 .eh-badge { display: flex; width: fit-content; align-items: center; margin: 0 0 12px;
           padding: 3.5px 8px; border-radius: 10px; background: var(--eh-soft);
           color: var(--eh-primary); font-size: 10.5px; font-weight: 700;
           letter-spacing: .04em; text-transform: uppercase; }
  .eh .eh-sub { margin: -6px 0 0; color: var(--eh-muted); font-size: calc(var(--eh-base) * .82);
           font-weight: 600; }
  .eh .eh-row { display: flex; gap: 10px; align-items: center; flex-wrap: wrap; }
  .eh .eh-grow { flex: 1 1 auto; min-height: 0; }
  .eh .eh-stage { width: 100%; flex: 1 1 0; min-height: 170px; display: flex;
           align-items: center; justify-content: center; }
  .eh svg.eh-svg { width: auto; height: 100%; max-width: 100%; display: block; }
  .eh .eh-readout { margin: 0; font-family: var(--eh-mono); font-size: calc(var(--eh-base) * .82);
           font-weight: 600; font-variant-numeric: tabular-nums; color: var(--eh-muted); }
  /* controls: one hairline, dashboard-style micro labels */
  .eh .eh-controls { display: grid; grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));
           gap: 10px 24px; padding-top: 12px; border-top: 1px solid var(--eh-line); }
  .eh .eh-slider { display: grid; grid-template-columns: 1fr auto; gap: 7px 12px; align-items: baseline; }
  .eh .eh-slider label { color: var(--eh-muted); font-size: 10px; font-weight: 700;
           letter-spacing: .04em; text-transform: uppercase;
           white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .eh .eh-pill { justify-self: end; font-family: var(--eh-mono); font-variant-numeric: tabular-nums;
           font-size: calc(var(--eh-base) * .88); font-weight: 650; color: var(--eh-text); }
  .eh input[type=range] { grid-column: 1 / -1; width: 100%; accent-color: var(--eh-primary);
           height: 18px; margin: 0; }
  .eh input[type=text] { font: inherit; font-weight: 600; padding: 7px 12px; background: transparent;
           color: var(--eh-text); border: 1px solid var(--eh-line); border-radius: 6px;
           min-width: 150px; transition: border-color .15s, background .15s; }
  .eh input[type=text]:focus { outline: none; border-color: var(--eh-primary); background: var(--eh-soft); }
  .eh input[type=text].eh-ok { border-color: var(--eh-secondary); background: var(--eh-ok-soft); }
  .eh input[type=text].eh-bad { border-color: var(--eh-danger); background: var(--eh-bad-soft); }
  /* buttons: dashboard command buttons */
  .eh button { min-height: 34px; padding: 0 13px; font: inherit; font-size: calc(var(--eh-base) * .88);
           font-weight: 650; cursor: pointer; border-radius: 6px; border: 1px solid var(--eh-line);
           background: transparent; color: var(--eh-text);
           transition: background .15s, border-color .15s, color .15s; }
  .eh button:hover { border-color: var(--eh-primary); background: var(--eh-soft); }
  .eh button:focus-visible { outline: 2px solid var(--eh-primary); outline-offset: 2px; }
  .eh button.eh-primary { background: var(--eh-primary); border-color: var(--eh-primary);
           color: var(--eh-bg); font-weight: 700; }
  .eh button.eh-primary:hover { filter: brightness(1.08); }
  .eh button.eh-secondary { background: var(--eh-secondary); border-color: var(--eh-secondary);
           color: var(--eh-bg); font-weight: 700; }
  .eh button.eh-secondary:hover { filter: brightness(1.08); }
  .eh button.eh-ghost { color: var(--eh-muted); }
  .eh button.eh-ghost:hover { color: var(--eh-text); }
  .eh button:disabled { opacity: .45; cursor: default; filter: none; }
  .eh .eh-status { min-height: 1.5em; margin: 0; color: var(--eh-muted);
           font-size: calc(var(--eh-base) * .88); font-weight: 600; }
  .eh .eh-status.eh-ok { color: var(--eh-secondary); }
  .eh .eh-status.eh-bad { color: var(--eh-danger); }
  /* choices */
  .eh .eh-choices { display: grid; gap: 8px; max-width: 780px;
           grid-template-columns: repeat(auto-fit, minmax(min(100%, 300px), 1fr)); }
  .eh .eh-choice { display: flex; gap: 12px; align-items: center; text-align: left; padding: 12px 14px;
           border: 1px solid var(--eh-line); border-radius: 10px; background: transparent;
           color: var(--eh-text); font-size: calc(var(--eh-base) * .95); font-weight: 600;
           min-height: 0; transition: border-color .16s, background .16s, transform .16s; }
  .eh .eh-choice:hover:not(:disabled) { border-color: var(--eh-primary); background: var(--eh-soft);
           transform: translateY(-1px); }
  .eh .eh-choice .eh-letter { flex: 0 0 auto; width: 26px; height: 26px; border-radius: 6px;
           display: flex; align-items: center; justify-content: center;
           font: 700 11px/1 var(--eh-mono); color: var(--eh-muted); background: var(--eh-line); }
  .eh .eh-choice.eh-ok { border-color: var(--eh-secondary); background: var(--eh-ok-soft); }
  .eh .eh-choice.eh-ok .eh-letter { background: var(--eh-secondary); color: var(--eh-bg); }
  .eh .eh-choice.eh-bad { border-color: var(--eh-danger); background: var(--eh-bad-soft); opacity: .7; }
  .eh .eh-choice.eh-bad .eh-letter { background: var(--eh-danger); color: var(--eh-bg); }
  /* explanation reads like the dashboard verdict block */
  .eh .eh-explain { max-width: 66ch; margin: 0; padding: 11px 14px; background: var(--eh-ok-soft);
           border-left: 3px solid var(--eh-secondary); border-radius: 0 6px 6px 0;
           font-size: calc(var(--eh-base) * .9); font-weight: 600; line-height: 1.7; }
  /* sortable list */
  .eh .eh-list { display: flex; flex-direction: column; gap: 7px; max-width: 780px; }
  .eh .eh-chip { display: flex; gap: 12px; align-items: center; padding: 10px 13px; border-radius: 10px;
           border: 1px solid var(--eh-line); cursor: grab; background: transparent; user-select: none;
           font-weight: 600; transition: border-color .15s, background .15s; }
  .eh .eh-chip.eh-dragging { opacity: .35; }
  .eh .eh-chip.eh-over { border-color: var(--eh-primary); border-style: dashed; }
  .eh .eh-chip.eh-ok { border-color: var(--eh-secondary); background: var(--eh-ok-soft); }
  .eh .eh-chip.eh-bad { border-color: var(--eh-danger); background: var(--eh-bad-soft); }
  .eh .eh-chip .eh-index { flex: 0 0 auto; width: 26px; height: 26px; border-radius: 6px; display: flex;
           align-items: center; justify-content: center; font: 700 11px/1 var(--eh-mono);
           background: var(--eh-soft); color: var(--eh-text); }
  .eh .eh-chip .eh-grow { flex: 1 1 auto; }
  .eh .eh-chip button { min-height: 26px; padding: 0 9px; font-size: .8em; border-color: transparent;
           color: var(--eh-muted); }
  .eh .eh-chip button:hover { border-color: var(--eh-primary); color: var(--eh-text); }
  /* cloze */
  .eh .eh-sentence { max-width: 46ch; margin: 0; font-size: calc(var(--eh-base) * 1.4);
           font-weight: 600; line-height: 2.1; }
  .eh .eh-sentence input[type=text] { width: 180px; margin: 0 6px; text-align: center;
           font-size: calc(var(--eh-base) * 1.05); }
  .eh .eh-hintbox { margin: 0; color: var(--eh-muted); font-size: calc(var(--eh-base) * .85);
           font-weight: 600; }
  /* A short stage drops density before it drops the primary action off-screen. */
  @container stage (max-height: 540px) {
    .eh { gap: 10px; }
    .eh h2 { font-size: clamp(16px, calc(var(--eh-base) * .95), 18px); }
    .eh h2 .eh-badge { display: none; }
    .eh .eh-stage { min-height: 110px; }
    .eh .eh-controls { padding-top: 9px; gap: 7px 20px; }
    .eh .eh-sentence { font-size: calc(var(--eh-base) * 1.1); line-height: 1.9; }
    .eh .eh-sentence input[type=text] { width: 130px; min-width: 0; }
  }
  `;

  function ensureStyles() {
    if (document.getElementById(STYLE_ID)) return;
    const style = document.createElement("style");
    style.id = STYLE_ID;
    style.textContent = CSS;
    document.head.appendChild(style);
  }

  function cssVar(name, fallback) {
    const value = getComputedStyle(document.documentElement).getPropertyValue(name).trim();
    return value || fallback;
  }

  function header(title, badge, sub) {
    const h = el("h2", {}, [badge ? el("span", { className: "eh-badge", text: badge }) : null, title]);
    const out = [h];
    if (sub) out.push(el("p", { className: "eh-sub", text: sub }));
    return out;
  }

  function hintButton(hint, status, event) {
    if (!hint) return null;
    let shown = false;
    return el("button", {
      type: "button", className: "eh-ghost", text: "Hint",
      onClick: () => {
        shown = !shown;
        status.textContent = shown ? "Hint: " + hint : "";
        status.className = "eh-status";
        event("hint", { shown });
      },
    });
  }

  function continueButton(label, onClick) {
    return el("button", { type: "button", className: "eh-secondary", text: label || "Continue", onClick });
  }

  function regionRect(value, fallback, width, height) {
    const source = value && typeof value === "object" ? value : {};
    const x = clamp(finite(source.x, fallback.x), 0, width);
    const y = clamp(finite(source.y, fallback.y), 0, height);
    const right = clamp(finite(source.width, fallback.width), 0, width - x);
    const bottom = clamp(finite(source.height, fallback.height), 0, height - y);
    return { x, y, width: right, height: bottom };
  }

  function teachingGeometry(layout) {
    const width = clamp(finite(layout && layout.width, 1920), 320, 7680);
    const height = clamp(finite(layout && layout.height, 1080), 240, 4320);
    const padding = clamp(finite(layout && layout.padding, 40), 0, Math.min(width, height) / 3);
    const safeWidth = Math.max(1, width - (padding * 2));
    const titleHeight = height * 0.14;
    const contentTop = height * 0.18;
    const contentBottom = height * 0.84;
    const gap = safeWidth * 0.04;
    const textWidth = safeWidth * 0.30;
    const visualWidth = safeWidth * 0.66;
    const visualX = padding + textWidth + gap;
    const contentHeight = Math.max(1, contentBottom - contentTop);
    const defaults = {
      title: { x: padding, y: padding, width: safeWidth, height: Math.max(1, titleHeight - padding) },
      text: { x: padding, y: contentTop, width: textWidth, height: contentHeight },
      visual: { x: visualX, y: contentTop, width: visualWidth, height: contentHeight },
      footer: { x: padding, y: contentBottom + padding * 0.25, width: safeWidth,
                height: Math.max(1, height - contentBottom - padding * 1.25) },
    };
    const supplied = layout && layout.regions && typeof layout.regions === "object" ? layout.regions : {};
    const regions = {};
    Object.keys(defaults).forEach((name) => {
      const region = supplied[name] || (name === "text" ? supplied.lecture : null);
      regions[name] = regionRect(region, defaults[name], width, height);
    });
    return { width, height, padding, regions };
  }

  function setRegionGeometry(node, rect, geometry) {
    node.style.left = `${(rect.x / geometry.width) * 100}%`;
    node.style.top = `${(rect.y / geometry.height) * 100}%`;
    node.style.width = `${(rect.width / geometry.width) * 100}%`;
    node.style.height = `${(rect.height / geometry.height) * 100}%`;
  }

  function textLines(value) {
    if (Array.isArray(value)) return value.map((line) => String(line || "").trim()).filter(Boolean);
    const line = String(value || "").trim();
    return line ? [line] : [];
  }

  function mountTeachingBoard(root, config, template, parameters, renderer, success, event) {
    const layout = config.teaching_layout || {};
    const geometry = teachingGeometry(layout);
    const board = el("div", { className: "eh-board", "data-template": template });
    board.style.aspectRatio = `${geometry.width} / ${geometry.height}`;
    const font = layout.font || {};
    board.style.setProperty("--eh-board-title-size", `${clamp(finite(font.title, 48), 12, 200)}px`);
    board.style.setProperty("--eh-board-body-size", `${clamp(finite(font.body, 30), 12, 120)}px`);
    board.style.setProperty("--eh-board-small-size", `${clamp(finite(font.small, 19), 10, 80)}px`);

    const titleRegion = el("div", { className: "eh-board-region eh-board-title" });
    const title = String(layout.title || parameters.title || parameters.topic || config.instruction || "").trim();
    if (title) titleRegion.appendChild(el("h1", { text: title }));
    const notesRegion = el("div", { className: "eh-board-region eh-board-notes" });
    textLines(layout.lecture_lines).forEach((line) => notesRegion.appendChild(el("p", { text: line })));
    const visualRegion = el("div", { className: "eh-board-region eh-board-visual" });
    const card = el("div", { className: "eh", "data-template": template });
    visualRegion.appendChild(card);
    const footerRegion = el("div", { className: "eh-board-region eh-board-footer" });
    const takeaway = String(layout.takeaway || "").trim();
    if (takeaway) footerRegion.appendChild(el("p", { text: takeaway }));
    setRegionGeometry(titleRegion, geometry.regions.title, geometry);
    setRegionGeometry(notesRegion, geometry.regions.text, geometry);
    setRegionGeometry(visualRegion, geometry.regions.visual, geometry);
    setRegionGeometry(footerRegion, geometry.regions.footer, geometry);
    appendAll(board, [titleRegion, notesRegion, visualRegion, footerRegion]);
    root.classList.add("eh-has-board");
    root.appendChild(board);
    renderer(card, parameters, success, event);
  }

  // ------------------------------------------------------------------ physics_lever
  function mountPhysicsLever(root, p, success, event) {
    const colors = {
      primary: cssVar("--primary", "#3B82F6"), secondary: cssVar("--secondary", "#10B981"),
      text: cssVar("--text", "#F3F4F6"), muted: cssVar("--muted", "#9CA3AF"),
      danger: cssVar("--danger", "#EF4444"), bg: cssVar("--bg", "#121214"),
    };
    const maxD = clamp(finite(p.max_distance, 1), 0.1, 5);
    const allowDistance = p.allow_distance !== false;
    const targetBalance = p.target_balance !== false;
    const tolerance = Math.max(0.01, finite(p.tolerance, 0.5));
    const offset = clamp(finite(p.fulcrum_offset, 0), -0.5, 0.5);
    let wA = clamp(finite(p.default_weight_A, 8), 1, 50);
    let wB = clamp(finite(p.default_weight_B, 12), 1, 50);
    let dA = clamp(finite(p.default_distance_A, 0.6), 0.05, maxD);
    let dB = clamp(finite(p.default_distance_B, 0.6), 0.05, maxD);
    let interacted = false;
    let completed = false;
    let solved = false;
    let attempts = 0;

    // --- SVG scene ---------------------------------------------------------
    const W = 1200, H = 430, beamY = 250, beamLeft = 90, beamRight = 1110;
    const pivotX = (beamLeft + beamRight) / 2 + offset * (beamRight - beamLeft) * 0.6;
    const armLeftPx = pivotX - beamLeft - 40, armRightPx = beamRight - pivotX - 40;
    const view = svg("svg", { class: "eh-svg", viewBox: `0 0 ${W} ${H}`, role: "img", "aria-label": "Lever simulator" });
    // ground shadow + fulcrum
    view.appendChild(svg("path", { d: `M ${pivotX - 46} ${beamY + 130} L ${pivotX} ${beamY + 8} L ${pivotX + 46} ${beamY + 130} Z`, fill: colors.secondary }));
    view.appendChild(svg("rect", { x: pivotX - 140, y: beamY + 130, width: 280, height: 10, rx: 5, fill: colors.muted, opacity: 0.6 }));
    // torque bars (drawn behind the beam group)
    const barL = svg("rect", { x: pivotX - 58, y: beamY - 20, width: 24, height: 0, rx: 4, fill: colors.secondary });
    const barR = svg("rect", { x: pivotX + 34, y: beamY - 20, width: 24, height: 0, rx: 4, fill: colors.danger });
    const barLText = svg("text", { x: pivotX - 46, y: beamY - 30, "text-anchor": "middle", fill: colors.secondary, "font-size": 20, "font-weight": 700 });
    const barRText = svg("text", { x: pivotX + 46, y: beamY - 30, "text-anchor": "middle", fill: colors.danger, "font-size": 20, "font-weight": 700 });
    view.append(barL, barR, barLText, barRText);
    // bubble level
    const levelY = 40;
    view.appendChild(svg("rect", { x: pivotX - 110, y: levelY, width: 220, height: 30, rx: 15, fill: "none", stroke: colors.muted, "stroke-width": 3 }));
    view.appendChild(svg("line", { x1: pivotX, y1: levelY - 6, x2: pivotX, y2: levelY + 36, stroke: colors.muted, "stroke-width": 2 }));
    const bubble = svg("circle", { cx: pivotX, cy: levelY + 15, r: 10, fill: colors.primary });
    const levelText = svg("text", { x: pivotX + 130, y: levelY + 22, fill: colors.muted, "font-size": 20, text: "level" });
    view.append(bubble, levelText);
    // rotating beam group
    const beamGroup = svg("g", {});
    beamGroup.appendChild(svg("rect", { x: beamLeft, y: beamY - 7, width: beamRight - beamLeft, height: 14, rx: 7, fill: colors.text }));
    // distance ticks
    for (let i = 1; i <= 4; i++) {
      const dx = (armLeftPx * i) / 4;
      beamGroup.appendChild(svg("line", { x1: pivotX - dx, y1: beamY + 7, x2: pivotX - dx, y2: beamY + 16, stroke: colors.muted, "stroke-width": 2 }));
      const dxr = (armRightPx * i) / 4;
      beamGroup.appendChild(svg("line", { x1: pivotX + dxr, y1: beamY + 7, x2: pivotX + dxr, y2: beamY + 16, stroke: colors.muted, "stroke-width": 2 }));
    }
    const boxA = svg("rect", { fill: colors.primary, rx: 8 });
    const boxB = svg("rect", { fill: colors.primary, rx: 8 });
    const labelA = svg("text", { fill: colors.bg, "text-anchor": "middle", "font-size": 24, "font-weight": 700 });
    const labelB = svg("text", { fill: colors.bg, "text-anchor": "middle", "font-size": 24, "font-weight": 700 });
    const distA = svg("text", { fill: colors.muted, "text-anchor": "middle", "font-size": 20 });
    const distB = svg("text", { fill: colors.muted, "text-anchor": "middle", "font-size": 20 });
    const braceA = svg("path", { fill: "none", stroke: colors.muted, "stroke-width": 2 });
    const braceB = svg("path", { fill: "none", stroke: colors.muted, "stroke-width": 2 });
    beamGroup.append(braceA, braceB, boxA, boxB, labelA, labelB, distA, distB);
    view.appendChild(beamGroup);

    // --- controls ------------------------------------------------------------
    const status = el("p", { className: "eh-status", role: "status" });
    const readout = el("p", { className: "eh-readout" });
    const sliders = el("div", { className: "eh-controls" });
    function slider(label, min, max, step, value, unit, onInput) {
      const pill = el("span", { className: "eh-pill", text: `${fmt(value)} ${unit}` });
      const input = el("input", { type: "range", min, max, step, value, "aria-label": label });
      input.addEventListener("input", () => {
        interacted = true;
        const v = finite(input.value, value);
        pill.textContent = `${fmt(v)} ${unit}`;
        onInput(v);
        sync("input");
      });
      const wrap = el("div", { className: "eh-slider" }, [el("label", { text: label }), pill, input]);
      sliders.appendChild(wrap);
      return input;
    }
    slider("Weight A", 1, 50, 1, wA, "N", (v) => { wA = v; });
    if (allowDistance) slider("Arm A", 0.05, maxD, 0.05, dA, "m", (v) => { dA = v; });
    slider("Weight B", 1, 50, 1, wB, "N", (v) => { wB = v; });
    if (allowDistance) slider("Arm B", 0.05, maxD, 0.05, dB, "m", (v) => { dB = v; });

    const check = el("button", { type: "button", className: "eh-primary", text: targetBalance ? "Check balance" : "Continue" });
    const footer = el("div", { className: "eh-row" });
    const hint = hintButton(p.hint, status, event);
    check.addEventListener("click", () => {
      if (solved) return;
      interacted = true;
      attempts += 1;
      const { left, right } = torques();
      event("attempt", { manual: true, weight_A: wA, weight_B: wB, distance_A: dA, distance_B: dB, torque_left: left, torque_right: right });
      if (!targetBalance) { finish(); return; }
      if (Math.abs(left - right) <= tolerance) { markBalanced(); return; }
      status.className = "eh-status eh-bad";
      status.textContent = left > right
        ? `Not yet — the left side has more torque (${fmt(left)} vs ${fmt(right)} N·m).`
        : `Not yet — the right side has more torque (${fmt(right)} vs ${fmt(left)} N·m).`;
      if (attempts >= 3 && p.hint) status.textContent += " Hint: " + p.hint;
    });

    function torques() {
      return { left: wA * dA, right: wB * dB };
    }
    function finish() {
      if (completed) return;
      completed = true;
      const { left, right } = torques();
      success({ weight_A: wA, weight_B: wB, distance_A: dA, distance_B: dB,
                torque_left: left, torque_right: right, attempts });
    }
    // Reaching balance is feedback, not completion: a range input jumps on a
    // single track click, so auto-advancing here would skip the scene by accident
    // (and contradicts the on-screen "press Continue").
    function markBalanced() {
      if (solved) return;
      solved = true;
      const { left } = torques();
      status.className = "eh-status eh-ok";
      status.textContent = `Balanced — ${fmt(left)} N·m on both sides. Press Continue.`;
      check.disabled = true;
      footer.prepend(continueButton("Continue", finish));
    }
    function sync(source) {
      const { left, right } = torques();
      const maxT = Math.max(50 * maxD, left, right, 1);
      const net = clamp((right - left) / Math.max(maxT * 0.35, 1), -1, 1);
      const angle = net * 11;
      beamGroup.setAttribute("transform", `rotate(${angle.toFixed(2)} ${pivotX} ${beamY})`);
      // weights
      const sizeA = 34 + Math.sqrt(wA) * 9, sizeB = 34 + Math.sqrt(wB) * 9;
      const xA = pivotX - (dA / maxD) * armLeftPx, xB = pivotX + (dB / maxD) * armRightPx;
      boxA.setAttribute("x", xA - sizeA / 2); boxA.setAttribute("y", beamY - 7 - sizeA);
      boxA.setAttribute("width", sizeA); boxA.setAttribute("height", sizeA);
      boxB.setAttribute("x", xB - sizeB / 2); boxB.setAttribute("y", beamY - 7 - sizeB);
      boxB.setAttribute("width", sizeB); boxB.setAttribute("height", sizeB);
      labelA.setAttribute("x", xA); labelA.setAttribute("y", beamY - 7 - sizeA / 2 + 9); labelA.textContent = `${fmt(wA)} N`;
      labelB.setAttribute("x", xB); labelB.setAttribute("y", beamY - 7 - sizeB / 2 + 9); labelB.textContent = `${fmt(wB)} N`;
      braceA.setAttribute("d", `M ${xA} ${beamY + 26} v 10 H ${pivotX} v -10`);
      braceB.setAttribute("d", `M ${pivotX} ${beamY + 26} v 10 H ${xB} v -10`);
      distA.setAttribute("x", (xA + pivotX) / 2); distA.setAttribute("y", beamY + 60); distA.textContent = `${fmt(dA, 2)} m`;
      distB.setAttribute("x", (xB + pivotX) / 2); distB.setAttribute("y", beamY + 60); distB.textContent = `${fmt(dB, 2)} m`;
      // torque bars
      const scale = 130 / Math.max(left, right, 1e-6);
      const hL = Math.max(4, left * scale), hR = Math.max(4, right * scale);
      barL.setAttribute("height", hL); barL.setAttribute("y", beamY - 24 - hL);
      barR.setAttribute("height", hR); barR.setAttribute("y", beamY - 24 - hR);
      barLText.setAttribute("y", beamY - 32 - hL); barLText.textContent = `${fmt(left)} N·m`;
      barRText.setAttribute("y", beamY - 32 - hR); barRText.textContent = `${fmt(right)} N·m`;
      // bubble
      bubble.setAttribute("cx", pivotX - net * 95);
      const balanced = Math.abs(left - right) <= tolerance;
      bubble.setAttribute("fill", balanced ? colors.secondary : colors.primary);
      levelText.textContent = balanced ? "level" : (net > 0 ? "tilts right" : "tilts left");
      readout.textContent = `τ left = ${fmt(wA)} N × ${fmt(dA, 2)} m = ${fmt(left)} N·m   |   τ right = ${fmt(wB)} N × ${fmt(dB, 2)} m = ${fmt(right)} N·m`;
      if (source === "input" && !solved) {
        event("attempt", { weight_A: wA, weight_B: wB, distance_A: dA, distance_B: dB, torque_left: left, torque_right: right });
        if (targetBalance && interacted && balanced) markBalanced();
        else if (targetBalance && interacted) { status.className = "eh-status"; status.textContent = ""; }
      }
    }

    appendAll(footer, [check, hint, status]);
    root.append(
      ...header(p.instruction || "Balance the lever", "Simulate"),
      el("div", { className: "eh-stage" }, view),
      readout,
      sliders,
      footer
    );
    sync("init");
  }

  // ------------------------------------------------------------------ multiple_choice
  function mountMultipleChoice(root, p, success, event) {
    const choices = Array.isArray(p.choices) ? p.choices.map(String) : [];
    const correct = finite(p.correct_index, 0);
    const status = el("p", { className: "eh-status", role: "status" });
    const grid = el("div", { className: "eh-choices" });
    const footer = el("div", { className: "eh-row" });
    const buttons = [];
    let solved = false;
    choices.forEach((choice, index) => {
      const letter = String.fromCharCode(65 + index);
      const button = el("button", { type: "button", className: "eh-choice", "data-index": index }, [
        el("span", { className: "eh-letter", text: letter }),
        el("span", { text: choice }),
      ]);
      button.addEventListener("click", () => {
        if (solved) return;
        event("attempt", { choice_index: index, correct: index === correct });
        if (index === correct) {
          solved = true;
          button.classList.add("eh-ok");
          buttons.forEach((b) => { b.disabled = true; });
          status.className = "eh-status eh-ok";
          status.textContent = "Correct!";
          if (p.explanation) root.insertBefore(el("p", { className: "eh-explain", text: p.explanation }), footer);
          footer.prepend(continueButton("Continue", () => success({ choice_index: index })));
        } else {
          button.classList.add("eh-bad");
          button.disabled = true;
          status.className = "eh-status eh-bad";
          status.textContent = "Not quite — try another answer.";
        }
      });
      buttons.push(button);
      grid.appendChild(button);
    });
    const hint = hintButton(p.hint, status, event);
    appendAll(footer, [hint, status]);
    root.append(...header(p.question || "Choose the best answer", "Check"), grid, footer);
  }

  // ------------------------------------------------------------------ drag_sort
  function mountDragSort(root, p, success, event) {
    let items = Array.isArray(p.items) ? p.items.map(String) : [];
    const correct = Array.isArray(p.correct_order) ? p.correct_order.map(String) : [];
    const list = el("div", { className: "eh-list", role: "list" });
    const status = el("p", { className: "eh-status", role: "status" });
    let dragFrom = null;
    let solved = false;

    function move(from, to) {
      if (from === to || from < 0 || to < 0 || from >= items.length || to >= items.length) return;
      const [item] = items.splice(from, 1);
      items.splice(to, 0, item);
      paint();
      event("move", { order: [...items] });
    }
    function paint(marks) {
      list.replaceChildren();
      items.forEach((item, index) => {
        const chip = el("div", { className: "eh-chip", role: "listitem", draggable: solved ? "false" : "true", "data-index": index }, [
          el("span", { className: "eh-index", text: index + 1 }),
          el("span", { className: "eh-grow", text: item }),
          el("button", { type: "button", text: "↑", "aria-label": `Move ${item} up`, onClick: () => move(index, index - 1) }),
          el("button", { type: "button", text: "↓", "aria-label": `Move ${item} down`, onClick: () => move(index, index + 1) }),
        ]);
        if (marks) chip.classList.add(marks[index] ? "eh-ok" : "eh-bad");
        chip.addEventListener("dragstart", (e) => { dragFrom = index; chip.classList.add("eh-dragging"); if (e.dataTransfer) e.dataTransfer.effectAllowed = "move"; });
        chip.addEventListener("dragend", () => { chip.classList.remove("eh-dragging"); });
        chip.addEventListener("dragover", (e) => { e.preventDefault(); chip.classList.add("eh-over"); });
        chip.addEventListener("dragleave", () => chip.classList.remove("eh-over"));
        chip.addEventListener("drop", (e) => { e.preventDefault(); chip.classList.remove("eh-over"); if (dragFrom !== null) move(dragFrom, index); dragFrom = null; });
        list.appendChild(chip);
      });
    }
    const check = el("button", { type: "button", className: "eh-primary", text: "Check order" });
    check.addEventListener("click", () => {
      if (solved) return;
      const marks = items.map((value, index) => value === correct[index]);
      const ok = correct.length === items.length && marks.every(Boolean);
      event("attempt", { order: [...items], correct: ok });
      paint(marks);
      if (ok) {
        solved = true;
        status.className = "eh-status eh-ok";
        status.textContent = "Correct order!";
        check.disabled = true;
        footer.prepend(continueButton("Continue", () => success({ order: [...items] })));
      } else {
        status.className = "eh-status eh-bad";
        status.textContent = `${marks.filter(Boolean).length} of ${items.length} in the right place — keep going.`;
      }
    });
    const hint = hintButton(p.hint, status, event);
    const footer = el("div", { className: "eh-row" }, [check, hint, status]);
    paint();
    root.append(...header(p.prompt || "Put the steps in order", "Sort", "Drag the cards or use the arrows, then press Check."), list, footer);
  }

  // ------------------------------------------------------------------ fill_blank
  function mountFillBlank(root, p, success, event) {
    const blanks = Array.isArray(p.blanks) ? p.blanks : [];
    const prompt = String(p.prompt || "Fill in the blanks");
    const inputs = [];
    const status = el("p", { className: "eh-status", role: "status" });
    let attempts = 0;
    let solved = false;

    function accepts(blank, value) {
      const answers = String(blank.answer || "").split("|").map((a) => a.trim().toLowerCase()).filter(Boolean);
      const v = value.trim().toLowerCase();
      if (!v) return false;
      if (answers.includes(v)) return true;
      const num = Number(v.replace(",", "."));
      return Number.isFinite(num) && answers.some((a) => Number.isFinite(Number(a)) && Math.abs(Number(a) - num) < 1e-9);
    }
    function makeInput(blank) {
      const input = el("input", { type: "text", placeholder: blank.label || "answer", "aria-label": blank.label || "answer", autocomplete: "off" });
      inputs.push({ input, blank });
      return input;
    }
    const placeholders = prompt.split("___");
    let body;
    if (placeholders.length - 1 === blanks.length && blanks.length > 0) {
      body = el("p", { className: "eh-sentence" });
      placeholders.forEach((part, i) => {
        body.appendChild(document.createTextNode(part));
        if (i < blanks.length) body.appendChild(makeInput(blanks[i]));
      });
      root.append(...header("Complete the statement", "Fill in"), body);
    } else {
      body = el("div", { className: "eh-list" });
      blanks.forEach((blank) => {
        body.appendChild(el("div", { className: "eh-row" }, [el("span", { text: blank.label || "Answer" }), makeInput(blank)]));
      });
      root.append(...header(prompt, "Fill in"), body);
    }
    const check = el("button", { type: "button", className: "eh-primary", text: "Check" });
    const footer = el("div", { className: "eh-row" });
    check.addEventListener("click", () => {
      if (solved) return;
      attempts += 1;
      const answers = inputs.map(({ input }) => input.value.trim());
      const marks = inputs.map(({ input, blank }) => accepts(blank, input.value));
      inputs.forEach(({ input }, i) => { input.classList.toggle("eh-ok", marks[i]); input.classList.toggle("eh-bad", !marks[i]); });
      const ok = inputs.length > 0 && marks.every(Boolean);
      event("attempt", { answers, correct: ok });
      if (ok) {
        solved = true;
        status.className = "eh-status eh-ok";
        status.textContent = "Correct!";
        check.disabled = true;
        footer.prepend(continueButton("Continue", () => success({ answers, attempts })));
      } else {
        status.className = "eh-status eh-bad";
        status.textContent = attempts >= 3
          ? "Answer: " + inputs.map(({ blank }) => String(blank.answer || "").split("|")[0]).join(", ")
          : "Not yet — check the highlighted answers." + (p.hint && attempts >= 2 ? " Hint: " + p.hint : "");
        if (attempts >= 3) footer.prepend(continueButton("Continue", () => success({ answers, attempts, revealed: true })));
      }
    });
    inputs.forEach(({ input }) => input.addEventListener("keydown", (e) => { if (e.key === "Enter") check.click(); }));
    const hint = hintButton(p.hint, status, event);
    appendAll(footer, [check, hint, status]);
    root.append(footer);
  }

  // ------------------------------------------------------------------ number_line
  function mountNumberLine(root, p, success, event) {
    const colors = {
      primary: cssVar("--primary", "#3B82F6"), secondary: cssVar("--secondary", "#10B981"),
      text: cssVar("--text", "#F3F4F6"), muted: cssVar("--muted", "#9CA3AF"), danger: cssVar("--danger", "#EF4444"),
    };
    const min = finite(p.min, 0), max = finite(p.max, 10);
    const target = clamp(finite(p.target, (min + max) / 2), min, max);
    const tolerance = Math.max(1e-6, finite(p.tolerance, (max - min) / 20));
    const unit = p.unit ? " " + String(p.unit) : "";
    const span = max - min || 1;
    const rawStep = span / 10;
    const mag = Math.pow(10, Math.floor(Math.log10(rawStep)));
    const step = [1, 2, 2.5, 5, 10].map((m) => m * mag).find((s) => span / s <= 12) || rawStep;
    const digits = step < 1 ? Math.min(3, Math.ceil(-Math.log10(step))) : 0;
    let value = min + span / 2;
    let attempts = 0;
    let solved = false;

    const W = 1200, H = 200, x0 = 80, x1 = 1120, y = 100;
    const toX = (v) => x0 + ((v - min) / span) * (x1 - x0);
    const toV = (x) => min + ((clamp(x, x0, x1) - x0) / (x1 - x0)) * span;
    const view = svg("svg", { class: "eh-svg", viewBox: `0 0 ${W} ${H}`, role: "slider", "aria-valuemin": min, "aria-valuemax": max, "aria-valuenow": value, tabindex: 0 });
    view.style.maxHeight = "260px";
    view.style.touchAction = "none";
    view.appendChild(svg("line", { x1: x0 - 20, y1: y, x2: x1 + 20, y2: y, stroke: colors.text, "stroke-width": 5, "stroke-linecap": "round" }));
    for (let v = Math.ceil(min / step) * step; v <= max + 1e-9; v += step) {
      const x = toX(v);
      view.appendChild(svg("line", { x1: x, y1: y - 14, x2: x, y2: y + 14, stroke: colors.muted, "stroke-width": 3 }));
      view.appendChild(svg("text", { x, y: y + 44, "text-anchor": "middle", fill: colors.muted, "font-size": 22, text: v.toFixed(digits) }));
    }
    const targetMark = svg("g", { opacity: 0 }, [
      svg("line", { x1: 0, y1: y - 40, x2: 0, y2: y + 20, stroke: colors.secondary, "stroke-width": 4, "stroke-dasharray": "8 6" }),
      svg("text", { x: 0, y: y - 50, "text-anchor": "middle", fill: colors.secondary, "font-size": 22, text: `target ${fmt(target, 2)}${unit}` }),
    ]);
    view.appendChild(targetMark);
    const marker = svg("g", { style: "cursor:grab" }, [
      svg("line", { x1: 0, y1: y - 34, x2: 0, y2: y + 6, stroke: colors.primary, "stroke-width": 6, "stroke-linecap": "round" }),
      svg("circle", { cx: 0, cy: y - 44, r: 20, fill: colors.primary }),
      svg("text", { x: 0, y: y - 76, "text-anchor": "middle", fill: colors.text, "font-size": 26, "font-weight": 700 }),
    ]);
    view.appendChild(marker);
    const markerText = marker.lastChild;
    function setValue(v) {
      value = clamp(v, min, max);
      marker.setAttribute("transform", `translate(${toX(value)} 0)`);
      markerText.textContent = fmt(value, digits + 1) + unit;
      view.setAttribute("aria-valuenow", value);
      info.textContent = `Current value: ${fmt(value, digits + 1)}${unit}`;
    }
    let dragging = false;
    const pointToValue = (e) => {
      const rect = view.getBoundingClientRect();
      const x = ((e.clientX - rect.left) / rect.width) * W;
      return toV(x);
    };
    view.addEventListener("pointerdown", (e) => { if (solved) return; dragging = true; view.setPointerCapture(e.pointerId); setValue(pointToValue(e)); });
    view.addEventListener("pointermove", (e) => { if (dragging) setValue(pointToValue(e)); });
    view.addEventListener("pointerup", () => { dragging = false; });
    view.addEventListener("keydown", (e) => {
      if (solved) return;
      const fine = span / 100;
      if (e.key === "ArrowLeft") { setValue(value - fine); e.preventDefault(); }
      if (e.key === "ArrowRight") { setValue(value + fine); e.preventDefault(); }
    });
    const info = el("p", { className: "eh-readout" });
    const status = el("p", { className: "eh-status", role: "status" });
    const submit = el("button", { type: "button", className: "eh-primary", text: "Submit" });
    const footer = el("div", { className: "eh-row" });
    submit.addEventListener("click", () => {
      if (solved) return;
      attempts += 1;
      const ok = Math.abs(value - target) <= tolerance;
      event("attempt", { value, correct: ok, attempts });
      if (ok) {
        solved = true;
        targetMark.setAttribute("opacity", 1);
        status.className = "eh-status eh-ok";
        status.textContent = `Correct — ${fmt(value, digits + 1)}${unit} is within range.`;
        submit.disabled = true;
        footer.prepend(continueButton("Continue", () => success({ value, attempts })));
      } else {
        status.className = "eh-status eh-bad";
        status.textContent = value < target ? "Too far left — try a larger value." : "Too far right — try a smaller value.";
        if (attempts >= 3) {
          targetMark.setAttribute("opacity", 1);
          status.textContent += ` The target was ${fmt(target, 2)}${unit}.`;
          footer.prepend(continueButton("Continue", () => success({ value, attempts, revealed: true })));
          solved = true;
        }
      }
    });
    const hint = hintButton(p.hint, status, event);
    appendAll(footer, [submit, hint, status]);
    setValue(value);
    root.append(...header(p.prompt || "Place the value", "Estimate", "Drag the marker, then press Submit."), el("div", { className: "eh-stage" }, view), info, footer);
  }

  // ------------------------------------------------------------------ registry
  const RENDERERS = {
    physics_lever: mountPhysicsLever,
    multiple_choice: mountMultipleChoice,
    drag_sort: mountDragSort,
    fill_blank: mountFillBlank,
    number_line: mountNumberLine,
  };

  function mountInteractive(root, config, callbacks) {
    ensureStyles();
    const safeCallbacks = callbacks || {};
    let active = true;
    root.replaceChildren();
    root.classList.remove("eh-has-board");
    const template = config && config.template;
    const renderer = RENDERERS[template];
    if (!renderer) throw new Error(`Unknown interactive template: ${String(template)}`);
    const parameters = Object.assign({}, config.parameters || {});
    if (!parameters.instruction && config.instruction) parameters.instruction = config.instruction;
    const event = (type, detail) => {
      if (active && typeof safeCallbacks.onEvent === "function") safeCallbacks.onEvent(type, detail || {});
    };
    const success = (detail) => {
      if (!active) return;
      event("success", detail || {});
      if (typeof safeCallbacks.onSuccess === "function") safeCallbacks.onSuccess(detail || {});
    };
    event("start", { template });
    // Practice panels are intentionally independent of the teaching board.
    // Older configs may still carry teaching_layout metadata; ignoring it here
    // keeps previously bundled lessons consistent with new interactive scenes.
    const card = el("div", { className: "eh", "data-template": template });
    root.appendChild(card);
    renderer(card, parameters, success, event);
    return function cleanup() {
      active = false;
      root.classList.remove("eh-has-board");
      root.replaceChildren();
    };
  }

  global.EduHarnessInteractive = { mountInteractive, templates: Object.keys(RENDERERS) };
})(typeof window !== "undefined" ? window : globalThis);
