"""Generate the hybrid timeline player and copy its trusted JS runtime.

The warm, quiet player frame leaves the lesson's own style_config palette intact.
The embedded board layout pairs a prominent stage with readable chapter navigation;
standalone lessons use a compact horizontal chapter rail.
"""

from __future__ import annotations

from html import escape
import hashlib
import json
from pathlib import Path
from urllib.parse import quote

from ..schema import Manifest


RUNTIME_PATH = Path(__file__).with_name("interactive_runtime.js")

FONT_LINK = """<link rel="preconnect" href="https://fonts.googleapis.com"/>
  <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin/>
  <link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600;700&display=swap"/>"""

PLAYER_JS = r"""
(function () {
  "use strict";
  const State = Object.freeze({
    IDLE: "IDLE",
    PLAYING_MEDIA: "PLAYING_MEDIA",
    INTERACTIVE_PAUSE: "INTERACTIVE_PAUSE",
    FINISHED: "FINISHED",
    ERROR: "ERROR",
  });

  // A standalone build injects window.EDUHARNESS_INLINE with every asset already
  // embedded; the served bundle leaves it undefined and fetches instead.
  async function loadJSON(path) {
    const inline = window.EDUHARNESS_INLINE;
    if (inline && Object.prototype.hasOwnProperty.call(inline, path)) {
      return JSON.parse(JSON.stringify(inline[path]));
    }
    const response = await fetch(path, { cache: "no-cache" });
    if (!response.ok) throw new Error(`Cannot load ${path}: HTTP ${response.status}`);
    return response.json();
  }

  function applyStyle(style) {
    const root = document.documentElement;
    const palette = style.palette || {};
    const typography = style.typography || {};
    const layout = style.layout || {};
    const tokens = {
      "--bg": palette.background, "--primary": palette.primary,
      "--secondary": palette.secondary, "--text": palette.text,
      "--muted": palette.muted, "--danger": palette.danger,
      "--pad": layout.safe_padding, "--font": typography.font_family,
      "--base-size": typography.base_size,
      "--heading-scale": String(typography.heading_scale || 1.25),
      "--layout-title-ratio": String(layout.title_ratio || 0.14),
      "--layout-content-top": String(layout.content_top_ratio || 0.18),
      "--layout-content-bottom": String(layout.content_bottom_ratio || 0.84),
      "--layout-text-ratio": String(layout.text_ratio || 0.56),
      "--layout-visual-ratio": String(layout.visual_ratio || 0.34),
      "--layout-gap-ratio": String(layout.content_gap_ratio || 0.04),
    };
    Object.entries(tokens).forEach(([key, value]) => {
      if (value !== undefined && value !== null) root.style.setProperty(key, String(value));
    });
    if (layout.width && layout.height) {
      root.style.setProperty("--stage-ratio", `${Number(layout.width)} / ${Number(layout.height)}`);
    }
  }

  function clock(seconds) {
    const s = Math.max(0, Math.round(Number(seconds) || 0));
    return `${String(Math.floor(s / 60)).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
  }

  async function startPlayer(manifestUrl) {
    const manifest = await loadJSON(manifestUrl);
    applyStyle(manifest.style || {});
    document.getElementById("topic").textContent = manifest.topic || "Lesson";

    const stage = document.getElementById("stage");
    const video = document.getElementById("video");
    const image = document.getElementById("image");
    const narration = document.getElementById("narration");
    const interactive = document.getElementById("interactive");
    const status = document.getElementById("status");
    const caption = document.getElementById("caption");
    const captionToggle = document.getElementById("captions");
    const progress = document.getElementById("progress");
    const total = manifest.timeline.length;
    let state = State.IDLE;
    let index = 0;
    let generation = 0;
    let timerId = null;
    let intervalId = null;
    let cleanupInteractive = null;
    let activeOverlay = null;
    let pendingOverlays = [];
    let captionsOn = true;
    const fills = [];
    const events = [];
    const sessionKey = `eduharness:${manifest.bundle_id || "bundle"}:events`;
    const contentVersion = manifest.content_version || manifest.timeline.map((item) =>
      `${item.id}:${item.type}:${item.duration || 0}:${item.src || item.config_src || ""}`).join("|");
    function assetURL(src) {
      if (!src || !manifest.content_version || /^(data|blob):/i.test(src)) return src;
      const url = new URL(src, location.href);
      url.searchParams.set("v", manifest.content_version);
      return url.href;
    }
    const resumeKey = `eduharness:${manifest.bundle_id || "bundle"}:resume:v1:${encodeURIComponent(contentVersion).slice(0, 180)}`;
    const startFresh = new URLSearchParams(window.location.search).get("fresh") === "1";
    let resumePoint = null;
    let imageStartedAt = 0;
    let lastSavedAt = 0;

    if (!startFresh) {
      try {
        const saved = JSON.parse(localStorage.getItem(resumeKey) || "null");
        if (saved && saved.version === contentVersion && Number.isInteger(saved.index)
            && saved.index >= 0 && saved.index < total
            && saved.scene_id === manifest.timeline[saved.index].id
            && Number.isFinite(Number(saved.position)) && Number(saved.position) >= 0) {
          resumePoint = saved;
          captionsOn = saved.captions_on !== false;
        }
      } catch (_) {}
    }
    captionToggle.classList.toggle("active", captionsOn);
    captionToggle.setAttribute("aria-pressed", String(captionsOn));

    // Rail widths are proportional to how long each scene actually lasts.
    const weights = manifest.timeline.map((item) =>
      Math.max(5, Number(item.duration) || (item.type === "interactive" ? 14 : 8)));

    function record(type, detail) {
      const event = {
        type, detail: detail || {}, state, item_index: index,
        at: new Date().toISOString(),
      };
      events.push(event);
      try { localStorage.setItem(sessionKey, JSON.stringify(events)); } catch (_) {}
    }

    function saveResume(extra) {
      const now = Date.now();
      if (!extra && now - lastSavedAt < 750) return;
      lastSavedAt = now;
      const item = manifest.timeline[index];
      if (!item || state === State.FINISHED) {
        try { localStorage.removeItem(resumeKey); } catch (_) {}
        return;
      }
      const position = item.type === "video"
        ? Number(video.currentTime || 0)
        : item.type === "image" && imageStartedAt
          ? Math.max(0, (now - imageStartedAt) / 1000)
          : 0;
      try {
        localStorage.setItem(resumeKey, JSON.stringify({
          version: contentVersion, index, position, scene_id: item.id, captions_on: captionsOn,
          saved_at: new Date(now).toISOString(), ...(extra || {}),
        }));
      } catch (_) {}
      const savedLabel = document.getElementById("resume-saved");
      if (savedLabel) savedLabel.textContent = "Saved";
    }

    function setState(next, persist = true) {
      state = next;
      stage.dataset.state = next;
      document.body.dataset.mode = next === State.INTERACTIVE_PAUSE ? "practice" : "watch";
      record("state", { value: next });
      if (persist) saveResume({ state: next });
    }

    function setCaption(text) {
      caption.textContent = captionsOn ? (text || "") : "";
      caption.classList.toggle("is-empty", !captionsOn || !text);
    }

    function setStatus(parts) {
      status.replaceChildren();
      parts.forEach(([text, cls]) => {
        if (!text) return;
        const span = document.createElement("span");
        span.className = cls;
        span.textContent = text;
        status.appendChild(span);
      });
    }

    // Badge colours follow the dashboard's ink/soft pairs.
    const BADGE = { video: "lbl", image: "lbl", interactive: "dl-warn",
                    "your turn": "caution", complete: "dl-ok", error: "caution" };

    function sceneStatus(item, timecode) {
      const kind = activeOverlay ? "your turn" : item.type;
      setStatus([
        [`${String(Math.min(index + 1, total)).padStart(2, "0")} / ${String(total).padStart(2, "0")}`, "num"],
        [item.title || item.id, "name"],
        [kind, `badge ${BADGE[kind] || "lbl"}`],
        [timecode, "time"],
      ]);
    }

    function setFill(i, ratio) {
      if (fills[i]) fills[i].style.transform = `scaleX(${Math.max(0, Math.min(1, ratio))})`;
    }

    function paintProgress() {
      progress.replaceChildren();
      fills.length = 0;
      manifest.timeline.forEach((item, i) => {
        const step = document.createElement("button");
        step.type = "button";
        step.className = "step" + (i < index ? " done" : i === index ? " current" : "");
        step.dataset.type = item.type;
        step.style.flexGrow = String(weights[i]);
        const name = item.title || item.id;
        step.title = `${i + 1}. ${name}${item.duration ? " · " + clock(item.duration) : ""}`;
        step.setAttribute("aria-label", step.title);

        const track = document.createElement("span");
        track.className = "step-track";
        const fill = document.createElement("span");
        fill.className = "step-fill";
        track.appendChild(fill);
        fills[i] = fill;
        (item.overlays || []).forEach((overlay) => {
          const tick = document.createElement("span");
          tick.className = "step-tick";
          const span = Math.max(0.1, Number(item.duration) || weights[i]);
          tick.style.left = `${Math.min(96, Math.max(3, (Number(overlay.trigger_at || 0) / span) * 100))}%`;
          tick.title = `${overlay.title || overlay.id} · ${clock(overlay.trigger_at)}`;
          track.appendChild(tick);
        });

        const meta = document.createElement("span");
        meta.className = "step-meta";
        const num = document.createElement("span");
        num.className = "step-num";
        num.textContent = String(i + 1).padStart(2, "0");
        const label = document.createElement("span");
        label.className = "step-label";
        label.textContent = name;
        meta.append(num, label);

        step.append(track, meta);
        step.addEventListener("click", () => { if (i !== index) show(i); });
        progress.appendChild(step);
        setFill(i, i < index ? 1 : 0);
      });
    }

    function stopNarration() {
      narration.onended = null;
      narration.pause();
      narration.removeAttribute("src");
    }

    function playNarration(src, onEnded) {
      stopNarration();
      if (!src) { if (onEnded) onEnded(); return; }
      narration.src = assetURL(src);
      narration.onended = () => { if (onEnded) onEnded(); };
      narration.onerror = () => { if (onEnded) onEnded(); };
      narration.play().catch(() => { if (onEnded) onEnded(); });
    }

    function clearActive() {
      generation += 1;
      if (timerId !== null) { clearTimeout(timerId); timerId = null; }
      if (intervalId !== null) { clearInterval(intervalId); intervalId = null; }
      if (cleanupInteractive) { cleanupInteractive(); cleanupInteractive = null; }
      activeOverlay = null;
      video.onended = null;
      video.ontimeupdate = null;
      video.onerror = null;
      image.onerror = null;
      video.pause();
      stopNarration();
      video.classList.add("hidden");
      image.classList.add("hidden");
      interactive.classList.add("hidden");
      interactive.replaceChildren();
    }

    function fail(error) {
      clearActive();
      setState(State.ERROR);
      const message = `Playback error: ${error.message || error}`;
      setStatus([["error", "badge caution"], [String(error.message || error), "name"]]);
      setCaption("");
      const panel = document.createElement("div");
      panel.className = "error";
      panel.textContent = message;
      interactive.append(panel);
      interactive.classList.remove("hidden");
      record("error", { message: String(error.message || error) });
    }

    async function mountConfig(configSrc, template, onSuccess, meta) {
      const token = generation;
      try {
        const config = await loadJSON(configSrc);
        if (token !== generation) return;
        if (meta && meta.overlay_id && (!activeOverlay || activeOverlay.id !== meta.overlay_id)) return;
        if (template) config.template = template;
        interactive.classList.remove("hidden");
        cleanupInteractive = window.EduHarnessInteractive.mountInteractive(
          interactive,
          config,
          {
            onEvent: (type, detail) => record(`interactive_${type}`, { ...meta, ...detail }),
            onSuccess: (detail) => {
              if (token !== generation) return;
              onSuccess(detail || {});
            },
          }
        );
      } catch (error) { fail(error); }
    }

    function resumeAfterOverlay() {
      if (cleanupInteractive) cleanupInteractive();
      cleanupInteractive = null;
      stopNarration();
      interactive.classList.add("hidden");
      activeOverlay = null;
      setState(State.PLAYING_MEDIA);
      const item = manifest.timeline[index];
      sceneStatus(item, `${clock(video.currentTime)} / ${clock(item.duration)}`);
      setCaption(item.narration);
      video.play().catch(() => {});
    }

    async function pauseForOverlay(overlay) {
      if (state !== State.PLAYING_MEDIA) return;
      video.pause();
      activeOverlay = overlay;
      setState(State.INTERACTIVE_PAUSE);
      setStatus([
        [`${String(index + 1).padStart(2, "0")} / ${String(total).padStart(2, "0")}`, "num"],
        [overlay.title || overlay.id, "name"],
        ["your turn", "badge caution"],
      ]);
      setCaption(overlay.narration);
      playNarration(overlay.audio_src);
      record("overlay_pause", { id: overlay.id, at_seconds: video.currentTime });
      saveResume({ overlay_id: overlay.id });
      await mountConfig(overlay.config_src, overlay.template, () => {
        if (!activeOverlay) return;
        record("overlay_resume", { id: overlay.id, at_seconds: video.currentTime });
        resumeAfterOverlay();
      }, { overlay_id: overlay.id });
    }

    async function show(position, options) {
      clearActive();
      index = position;
      paintProgress();
      const token = generation;
      if (index >= total) {
        setState(State.FINISHED);
        setStatus([["complete", "badge dl-ok"]]);
        setCaption("");
        interactive.classList.remove("hidden");
        const done = document.createElement("div");
        done.className = "lesson-done";
        const head = document.createElement("strong");
        head.textContent = "Lesson complete";
        const sub = document.createElement("span");
        sub.textContent = `${total} scenes · ${clock(manifest.total_duration)} of media`;
        done.append(head, sub);
        interactive.append(done);
        fills.forEach((_, i) => setFill(i, 1));
        record("lesson_finished", {});
        return;
      }

      const item = manifest.timeline[index];
      const restoreSeconds = options && Number(options.position || 0) > 0
        ? Number(options.position) : 0;
      const hold = Boolean(options && options.hold);
      sceneStatus(item, item.type === "interactive" ? "" : `00:00 / ${clock(item.duration)}`);
      setCaption(item.narration);
      record("scene_start", { id: item.id, type: item.type });

      if (item.type === "video") {
        setState(State.PLAYING_MEDIA, !hold);
        pendingOverlays = [...(item.overlays || [])].sort((a, b) => a.trigger_at - b.trigger_at);
        video.poster = assetURL((window.EDUHARNESS_POSTERS || {})[item.id] || "");
        video.src = assetURL(item.src);
        video.classList.remove("hidden");
        video.ontimeupdate = () => {
          if (token !== generation) return;
          const span = video.duration || item.duration || 1;
          setFill(index, video.currentTime / span);
          if (!activeOverlay) sceneStatus(item, `${clock(video.currentTime)} / ${clock(span)}`);
          if (!hold) saveResume();
          if (activeOverlay || !pendingOverlays.length) return;
          if (video.currentTime >= Number(pendingOverlays[0].trigger_at || 0)) {
            pauseForOverlay(pendingOverlays.shift());
          }
        };
        video.onended = () => {
          if (token === generation && !activeOverlay) show(index + 1);
        };
        video.onerror = () => fail(new Error(`Video failed: ${item.src}`));
        if (restoreSeconds) {
          video.addEventListener("loadedmetadata", () => {
            video.currentTime = Math.min(restoreSeconds, Math.max(0, (video.duration || restoreSeconds) - 0.1));
          }, { once: true });
        }
        if (!hold) {
          try { await video.play(); } catch (_) { /* the controls are visible */ }
        }
      } else if (item.type === "image") {
        setState(State.PLAYING_MEDIA, !hold);
        image.src = assetURL(item.src);
        image.classList.remove("hidden");
        image.onerror = () => fail(new Error(`Image failed: ${item.src}`));
        const totalMilliseconds = Math.max(2000, Number(item.duration || 8) * 1000);
        const consumed = Math.min(totalMilliseconds - 250, restoreSeconds * 1000);
        const milliseconds = Math.max(250, totalMilliseconds - consumed);
        const started = Date.now() - consumed;
        imageStartedAt = started;
        if (hold) {
          setFill(index, consumed / totalMilliseconds);
          sceneStatus(item, `${clock(consumed / 1000)} / ${clock(item.duration)}`);
          return;
        }
        intervalId = setInterval(() => {
          if (token !== generation) return;
          const elapsed = Date.now() - started;
          setFill(index, elapsed / milliseconds);
          sceneStatus(item, `${clock(elapsed / 1000)} / ${clock(item.duration)}`);
          saveResume();
          if (elapsed >= milliseconds && intervalId !== null) {
            clearInterval(intervalId);
            intervalId = null;
          }
        }, 250);
        let narrationDone = !item.audio_src;
        let timerDone = false;
        const advance = () => { if (token === generation && narrationDone && timerDone) show(index + 1); };
        timerId = setTimeout(() => { timerDone = true; advance(); }, milliseconds);
        playNarration(item.audio_src, () => { narrationDone = true; advance(); });
      } else if (item.type === "interactive") {
        setState(State.INTERACTIVE_PAUSE);
        setFill(index, 1);
        playNarration(item.audio_src);
        await mountConfig(item.config_src, item.template, () => show(index + 1), { scene_id: item.id });
      } else fail(new Error(`Unknown timeline type: ${String(item.type)}`));
      if (!hold) saveResume({ state });
    }

    document.getElementById("next").addEventListener("click", () => {
      record("skip", { overlay_id: activeOverlay && activeOverlay.id });
      if (activeOverlay) resumeAfterOverlay();
      else show(Math.min(index + 1, total));
    });
    document.getElementById("prev").addEventListener("click", () => {
      record("back", {});
      show(Math.max(0, index - 1));
    });
    captionToggle.addEventListener("click", () => {
      captionsOn = !captionsOn;
      captionToggle.classList.toggle("active", captionsOn);
      captionToggle.setAttribute("aria-pressed", String(captionsOn));
      const item = manifest.timeline[index];
      setCaption(activeOverlay ? activeOverlay.narration : (item && item.narration));
      saveResume({ captions_on: captionsOn });
    });
    const eventsButton = document.getElementById("download-log");
    // A standalone build is often opened inside a sandboxed viewer where a
    // download link is inert and fails silently, so hand the log over through
    // the clipboard there instead of offering a button that does nothing.
    const canDownload = !window.EDUHARNESS_INLINE
      && "download" in document.createElement("a");
    eventsButton.textContent = canDownload ? "Events" : "Copy events";
    eventsButton.title = canDownload
      ? "Download the interaction log"
      : "Copy the interaction log to the clipboard";
    eventsButton.addEventListener("click", async () => {
      const json = JSON.stringify(events, null, 2);
      if (canDownload) {
        const blob = new Blob([json], { type: "application/json" });
        const anchor = document.createElement("a");
        anchor.href = URL.createObjectURL(blob);
        anchor.download = `${manifest.bundle_id || "eduharness"}-events.json`;
        anchor.click();
        URL.revokeObjectURL(anchor.href);
        return;
      }
      const label = eventsButton.textContent;
      let ok = false;
      try {
        await navigator.clipboard.writeText(json);
        ok = true;
      } catch (err) {
        ok = false;
      }
      eventsButton.textContent = ok
        ? `Copied ${events.length} events`
        : "Clipboard blocked";
      setTimeout(() => { eventsButton.textContent = label; }, 1800);
    });
    window.addEventListener("pagehide", () => saveResume({ state }));
    document.addEventListener("visibilitychange", () => {
      if (document.visibilityState === "hidden") saveResume({ state });
    });
    const resumeButton = document.getElementById("resume-last");
    const restartButton = document.getElementById("restart-lesson");
    if (resumePoint) {
      resumeButton.classList.remove("hidden");
      resumeButton.textContent = `Resume ${String(resumePoint.index + 1).padStart(2, "0")} · ${clock(resumePoint.position)}`;
      resumeButton.addEventListener("click", () => {
        const point = resumePoint;
        resumePoint = null;
        resumeButton.classList.add("hidden");
        show(point.index, { position: point.position });
      });
    }
    restartButton.addEventListener("click", () => {
      try { localStorage.removeItem(resumeKey); } catch (_) {}
      resumePoint = null;
      resumeButton.classList.add("hidden");
      show(0);
    });
    await show(resumePoint ? resumePoint.index : 0, resumePoint
      ? { position: resumePoint.position, hold: true } : undefined);
  }

  function startAmbient() {
    const canvas = document.getElementById("ambient");
    if (!canvas || !canvas.getContext) return;
    const context = canvas.getContext("2d");
    const still = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    const styles = getComputedStyle(document.documentElement);
    const cool = styles.getPropertyValue("--ui-blue").trim() || "#356B8F";
    const warm = styles.getPropertyValue("--ui-green").trim() || "#16734A";
    let seed = 20260904;
    const rnd = () => {
      seed = (Math.imul(seed, 1664525) + 1013904223) >>> 0;
      return seed / 4294967296;
    };
    const dots = Array.from({ length: 44 }, () => ({
      x: rnd(), y: rnd(), r: 1 + rnd() * 1.8,
      speed: 0.0015 + rnd() * 0.006, phase: rnd() * Math.PI * 2,
      drift: 8 + rnd() * 26, alpha: 0.05 + rnd() * 0.06, warm: rnd() > 0.72,
    }));
    let width = 0, height = 0;
    function resize() {
      const ratio = Math.min(window.devicePixelRatio || 1, 2);
      width = canvas.clientWidth;
      height = canvas.clientHeight;
      canvas.width = Math.round(width * ratio);
      canvas.height = Math.round(height * ratio);
      context.setTransform(ratio, 0, 0, ratio, 0, 0);
    }
    function draw(seconds) {
      context.clearRect(0, 0, width, height);
      dots.forEach((d) => {
        const y = (((d.y - seconds * d.speed) % 1) + 1) % 1;
        const x = d.x * width + Math.sin(seconds * 0.4 + d.phase) * d.drift;
        context.globalAlpha = d.alpha;
        context.fillStyle = d.warm ? warm : cool;
        context.beginPath();
        context.arc(x, y * height, d.r, 0, Math.PI * 2);
        context.fill();
      });
      context.globalAlpha = 1;
    }
    resize();
    window.addEventListener("resize", () => { resize(); if (still) draw(0); });
    if (still) { draw(0); return; }
    const start = performance.now();
    (function frame(now) {
      draw((now - start) / 1000);
      requestAnimationFrame(frame);
    })(start);
  }

  window.EduHarnessPlayer = { startPlayer, startAmbient, State };
})();
"""


PLAYER_CSS = """
:root {
  color-scheme: light;
  /* Lesson colours remain independent from the player frame. */
  --bg: #121214; --primary: #3B82F6; --secondary: #10B981;
  --text: #F3F4F6; --muted: #9CA3AF; --danger: #EF4444;
  --pad: 40px; --font: Arial; --base-size: 16px; --heading-scale: 1.25;
  --stage-ratio: 16 / 9;
  --ui-ground: #f7f5f0; --ui-surface: #fffefa; --ui-soft: #f0f1e9;
  --ui-ink: #252a24; --ui-dim: #737871;
  --ui-line: #e4e5dd; --ui-line-strong: #cdd2c7;
  --ui-green: #54705b; --ui-green-soft: #eaf0e8;
  --ui-red: #aa5145; --ui-red-soft: #faece6;
  --ui-blue: #54705b; --ui-blue-soft: #eaf0e8;
  --ui-amber: #c45e3c; --ui-amber-soft: #f9ece3;
  --ui-shadow: 0 8px 28px rgba(36, 43, 40, .05);
  --ui-sans: Inter, ui-sans-serif, system-ui, -apple-system, "Segoe UI", sans-serif;
  --ui-mono: ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
}
* { box-sizing: border-box; }
html { background: var(--ui-ground); }
body {
  margin: 0; min-width: 280px; min-height: 100vh;
  background: var(--ui-ground); color: var(--ui-ink);
  font-family: var(--ui-sans); font-size: 14px; line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}
#ambient { display: none; }
button { font: inherit; color: inherit; }
button:focus-visible { outline: 2px solid var(--ui-green); outline-offset: 3px; }
.topbar {
  min-height: 74px; padding: 16px 28px;
  display: flex; align-items: center; justify-content: space-between; gap: 20px;
  background: var(--ui-surface); border-bottom: 1px solid var(--ui-line);
}
.brand { display: flex; align-items: center; gap: 12px; min-width: 0; }
.brand-mark {
  flex: 0 0 auto; width: 32px; height: 32px; display: grid;
  grid-template-columns: repeat(2, 1fr); gap: 3px; padding: 7px;
  background: var(--ui-green); border-radius: 10px;
}
.brand-mark i { background: #fff; border-radius: 1px; }
.brand-mark i:nth-child(2), .brand-mark i:nth-child(3) { opacity: .5; }
.brand-text { min-width: 0; }
#topic {
  margin: 0; font-size: 14px; font-weight: 600; line-height: 1.4;
  white-space: nowrap; overflow: hidden; text-overflow: ellipsis;
}
.eyebrow { margin: 3px 0 0; color: var(--ui-dim); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
.header-actions { display: flex; align-items: center; gap: 7px; flex-shrink: 0; }
header button {
  min-height: 34px; padding: 0 11px; border: 1px solid var(--ui-line);
  background: var(--ui-surface); border-radius: 8px; cursor: pointer;
  font-size: 11px; font-weight: 500; color: var(--ui-ink);
  transition: border-color .18s, background .18s, color .18s;
}
header button:hover { border-color: var(--ui-line-strong); background: var(--ui-soft); }
header button.ghost { color: var(--ui-dim); border-color: transparent; background: transparent; }
header button.ghost:hover { background: var(--ui-soft); }
header button.ghost.active { color: var(--ui-green); background: var(--ui-green-soft); }
header button#next { background: var(--ui-green); border-color: var(--ui-green); color: #fff; }
header button#next:hover { background: #45604f; border-color: #45604f; }
main { max-width: 1320px; margin-inline: auto; }
.stage-band { padding: 22px 28px 0; min-width: 0; }
.stage-wrap { margin: 0 auto; max-width: min(1120px, max(560px, calc((100vh - 310px) * 16 / 9))); }
.now-playing { display: flex; align-items: baseline; gap: 14px; margin: 0 0 14px; min-height: 24px; }
.status-label { flex: 0 0 auto; margin: 0; color: var(--ui-dim); font-size: 10px; letter-spacing: .08em; text-transform: uppercase; }
#status { display: flex; align-items: center; gap: 9px; flex-wrap: wrap; min-width: 0; }
#status .num, #status .time { font: 500 10px/1 var(--ui-mono); color: var(--ui-dim); font-variant-numeric: tabular-nums; }
#status .name { font-size: 12px; font-weight: 500; }
.badge {
  display: inline-flex; align-items: center; padding: 3px 7px; border-radius: 5px;
  font-size: 9px; font-weight: 500; white-space: nowrap; text-transform: uppercase; letter-spacing: .04em;
}
.badge.dl-ok { color: var(--ui-green); background: var(--ui-green-soft); }
.badge.dl-warn { color: var(--ui-amber); background: var(--ui-amber-soft); }
.badge.lbl { color: var(--ui-blue); background: var(--ui-blue-soft); }
.badge.caution { color: var(--ui-red); background: var(--ui-red-soft); }
#stage {
  position: relative; width: 100%; aspect-ratio: var(--stage-ratio); background: var(--bg);
  border: 1px solid var(--ui-line); border-radius: 14px; overflow: hidden; box-shadow: var(--ui-shadow);
}
#stage[data-state="INTERACTIVE_PAUSE"] { border-color: #d7b199; }
#stage[data-state="ERROR"] { border-color: #d9a9a5; }
#video, #image { display: block; width: 100%; height: 100%; object-fit: contain; background: var(--bg); }
#interactive { position: absolute; inset: 0; padding: clamp(14px, 3.4%, 40px); background: var(--bg);
  overflow: auto; container-type: size; container-name: stage; }
.hidden { display: none !important; }
.error { max-width: 62ch; margin: 9% auto 0; text-align: center; color: var(--danger); font: 600 13.5px/1.7 var(--ui-mono); }
.lesson-done { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; gap: 10px; }
.lesson-done strong { font-size: 28px; font-weight: 700; color: var(--text); }
.lesson-done span { font: 500 12px/1.4 var(--ui-mono); color: var(--muted); }
.narration-block { display: grid; grid-template-columns: 82px minmax(0, 1fr); gap: 14px; padding: 17px 2px 6px; }
.narration-label { margin: 3px 0 0; color: var(--ui-dim); font-size: 9px; text-transform: uppercase; letter-spacing: .09em; }
#caption { margin: 0; color: #646c62; font-size: 12px; line-height: 1.8; min-height: 2.2em; }
#caption.is-empty { color: transparent; }
.rail-band { padding: 18px 28px 22px; min-width: 0; }
.rail-heading { display: flex; align-items: center; justify-content: space-between; gap: 12px; margin: 0 0 12px; }
.rail-heading h2 { margin: 0; font-size: 10px; letter-spacing: .08em; text-transform: uppercase; color: var(--ui-dim); font-weight: 500; }
.rail-heading span { font-size: 9px; color: var(--ui-dim); }
#progress { display: flex; align-items: stretch; gap: 8px; overflow-x: auto; padding: 3px 0 5px; }
.step {
  position: relative; flex: 1 1 0; min-width: 84px; display: flex; flex-direction: column; gap: 8px;
  padding: 10px; border: 1px solid transparent; border-radius: 9px; background: transparent;
  text-align: left; cursor: pointer; color: var(--ui-dim); transition: background .18s, border-color .18s;
}
.step:hover { color: var(--ui-ink); background: #f1f2ec; }
.step:focus-visible { outline-offset: -2px; }
.step-track { position: relative; height: 8px; display: flex; align-items: center; }
.step-track::before { content: ""; position: absolute; left: 0; right: 0; height: 3px; border-radius: 3px; background: var(--ui-line); }
.step[data-type="interactive"] .step-track::before { background: #ecd5c3; }
.step-fill { position: absolute; left: 0; right: 0; height: 3px; border-radius: 3px; background: var(--ui-green);
  transform: scaleX(0); transform-origin: left center; transition: transform .25s linear; }
.step[data-type="interactive"] .step-fill { background: var(--ui-amber); }
.step-tick { position: absolute; top: 0; height: 8px; width: 3px; border-radius: 2px; background: var(--ui-amber); transform: translateX(-50%); }
.step-meta { display: flex; align-items: baseline; gap: 8px; min-width: 0; }
.step-num { flex: 0 0 auto; font: 500 10px/1 var(--ui-mono); }
.step-label { flex: 1 1 auto; min-width: 0; font-size: 11px; font-weight: 400; line-height: 1.5; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.step.done .step-num, .step.current .step-num { color: var(--ui-green); }
.step[data-type="interactive"].done .step-num, .step[data-type="interactive"].current .step-num { color: var(--ui-amber); }
.step.current { color: var(--ui-ink); background: var(--ui-green-soft); border-color: #d9e2d5; }
.step.current .step-label { font-weight: 500; }
.step[data-type="interactive"].current { background: var(--ui-amber-soft); border-color: #eddacb; }
footer { max-width: 1320px; margin-inline: auto; display: flex; justify-content: space-between; gap: 16px; padding: 0 28px 20px; color: var(--ui-dim); font-size: 10px; }
#preview-note { padding: 9px 24px; background: var(--ui-blue-soft); border-bottom: 1px solid var(--ui-line); color: var(--ui-blue); font-size: 11.5px; text-align: center; }
/* The home-page embed uses a chapter sidebar and keeps the lesson itself large. */
html[data-layout="board"] body { min-height: 0; }
html[data-layout="board"] .topbar { min-height: 62px; padding: 12px 22px; }
html[data-layout="board"] .brand-mark, html[data-layout="board"] .eyebrow, html[data-layout="board"] #download-log { display: none; }
html[data-layout="board"] main { display: grid; grid-template-columns: minmax(0, 1fr) 226px; padding: 20px 22px 16px; gap: 22px; max-width: 1480px; }
html[data-layout="board"] .stage-band { padding: 0; }
html[data-layout="board"] .stage-wrap { max-width: none; }
html[data-layout="board"] .now-playing { margin-bottom: 12px; }
html[data-layout="board"] .status-label { display: none; }
html[data-layout="board"] #status .name { font-size: 11px; }
html[data-layout="board"] .rail-band { padding: 0 0 0 20px; border-left: 1px solid var(--ui-line); }
html[data-layout="board"] .rail-heading { margin: 5px 0 18px; }
html[data-layout="board"] .rail-heading span { display: none; }
html[data-layout="board"] #progress { flex-direction: column; overflow: visible; gap: 7px; }
html[data-layout="board"] .step { width: 100%; min-width: 0; flex: 0 0 auto; padding: 12px 10px; flex-direction: column-reverse; gap: 10px; }
html[data-layout="board"] .step-track { margin-left: 24px; height: 4px; }
html[data-layout="board"] .step-tick { top: -2px; }
html[data-layout="board"] .step-meta { align-items: flex-start; gap: 10px; }
html[data-layout="board"] .step-num { padding-top: 3px; }
html[data-layout="board"] .step-label { white-space: normal; overflow: visible; font-size: 11px; }
html[data-layout="board"] footer { padding: 0 24px 16px; max-width: 1480px; }
@media (max-width: 980px) {
  .topbar { padding: 14px 20px; gap: 12px; }
  #topic { font-size: 12px; }
  .header-actions { gap: 4px; }
  header button { padding: 0 8px; font-size: 10px; }
  html[data-layout="board"] main { grid-template-columns: minmax(0, 1fr) 190px; gap: 16px; padding-inline: 18px; }
  html[data-layout="board"] .rail-band { padding-left: 14px; }
}
@media (max-width: 720px) {
  .topbar, html[data-layout="board"] .topbar { align-items: flex-start; flex-wrap: wrap; gap: 12px; padding: 16px; }
  .header-actions { width: 100%; flex-wrap: wrap; gap: 6px; }
  .header-actions button { min-height: 34px; padding: 0 10px; font-size: 11px; }
  .brand { width: 100%; }
  #topic { font-size: 13px; white-space: normal; }
  .stage-band, .rail-band { padding-inline: 16px; }
  .stage-wrap { max-width: none; }
  .now-playing { gap: 8px; flex-wrap: wrap; }
  #status { gap: 7px; }
  #status .name { font-size: 11px; }
  .status-label { display: none; }
  #stage { border-radius: 10px; }
  #stage[data-state="INTERACTIVE_PAUSE"] { min-height: 460px; aspect-ratio: auto; }
  #stage[data-state="INTERACTIVE_PAUSE"] #interactive { position: relative; min-height: 460px; container-type: inline-size; }
  #stage[data-state="INTERACTIVE_PAUSE"] #interactive .eh { height: auto; min-height: 430px; gap: 12px; }
  #stage[data-state="INTERACTIVE_PAUSE"] #interactive .eh h2 { font-size: 16px; }
  #stage[data-state="INTERACTIVE_PAUSE"] #interactive .eh h2 .eh-badge { display: none; }
  #stage[data-state="INTERACTIVE_PAUSE"] #interactive .eh-stage { flex: 0 0 140px; min-height: 140px; }
  #stage[data-state="INTERACTIVE_PAUSE"] #interactive svg.eh-svg { width: 100%; height: 140px; }
  .narration-block { grid-template-columns: 1fr; gap: 6px; padding-top: 14px; }
  #caption { font-size: 11px; line-height: 1.75; }
  #progress { gap: 6px; }
  .step { min-width: 124px; padding: 10px; }
  .step-label { white-space: normal; }
  footer { padding: 0 16px 18px; font-size: 9px; }
  html[data-layout="board"] main { display: block; padding: 16px; }
  html[data-layout="board"] .rail-band { padding: 20px 0 0; border-left: 0; }
  html[data-layout="board"] .rail-heading { margin-bottom: 10px; }
  html[data-layout="board"] #progress { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 6px; }
  html[data-layout="board"] .step { height: 100%; padding: 10px; justify-content: space-between; }
  html[data-layout="board"] .step-track { margin-left: 24px; }
  html[data-layout="board"] footer { padding: 0 16px 16px; }
}
@media (prefers-reduced-motion: reduce) { * { transition: none !important; animation: none !important; } }
"""


def shell_html(
    topic: str,
    *,
    extra_css: str = "",
    body_prefix: str = "",
    scripts: str,
    footer_right: str = "EduCast",
) -> str:
    """The player shell, shared by the served bundle and the standalone preview."""
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>{escape(topic)}</title>
  <script>if (new URLSearchParams(location.search).get("layout") === "board") document.documentElement.dataset.layout = "board";</script>
  {FONT_LINK}
  <style>{PLAYER_CSS}{extra_css}</style>
</head>
<body>
  <canvas id="ambient" aria-hidden="true"></canvas>
{body_prefix}  <header class="topbar">
    <div class="brand">
      <div class="brand-mark" aria-hidden="true"><i></i><i></i><i></i><i></i></div>
      <div class="brand-text">
        <h1 id="topic"></h1>
        <p class="eyebrow">Interactive lesson</p>
      </div>
    </div>
    <div class="header-actions">
      <button id="captions" class="ghost active" type="button" aria-pressed="true" title="Toggle captions">Captions</button>
      <button id="download-log" class="ghost" type="button" title="Download interaction log">Events</button>
      <button id="resume-last" class="ghost hidden" type="button" title="Resume saved position">Resume</button>
      <button id="restart-lesson" class="ghost" type="button" title="Start lesson over">Restart</button>
      <button id="prev" type="button">Back</button>
      <button id="next" type="button">Next</button>
    </div>
  </header>
  <main>
    <div class="stage-band">
      <div class="now-playing">
        <p class="status-label">Now playing</p>
        <div id="status" role="status">Loading…</div>
      </div>
      <div class="stage-wrap">
        <div id="stage" data-state="IDLE">
          <video id="video" class="hidden" playsinline controls></video>
          <img id="image" class="hidden" alt="Lesson scene"/>
          <div id="interactive" class="hidden"></div>
          <audio id="narration" preload="auto"></audio>
        </div>
        <div class="narration-block">
          <p class="narration-label">Narration</p>
          <div id="caption" class="is-empty"></div>
        </div>
      </div>
    </div>
    <div class="rail-band">
      <div class="rail-heading"><h2>Lesson chapters</h2><span>Select a chapter to explore</span></div>
      <nav id="progress" aria-label="Lesson progress"></nav>
    </div>
  </main>
  <footer><span>Animation · illustration · practice</span><span>{escape(footer_right)}</span></footer>
  <script>
    if (window.parent !== window && document.documentElement.dataset.layout === "board") {{
      const reportHeight = () => window.parent.postMessage({{
        type: "educast-player:resize", height: Math.ceil(document.body.getBoundingClientRect().height)
      }}, location.origin);
      new ResizeObserver(reportHeight).observe(document.body);
      window.addEventListener("load", reportHeight);
    }}
  </script>
{scripts}</body>
</html>
"""


def write_player(bundle_dir: Path, manifest: Manifest) -> Path:
    bundle_dir.mkdir(parents=True, exist_ok=True)
    (bundle_dir / "interactive-runtime.js").write_text(
        RUNTIME_PATH.read_text(encoding="utf-8"), encoding="utf-8"
    )
    (bundle_dir / "player.js").write_text(PLAYER_JS, encoding="utf-8")
    posters = {}
    for item in manifest.timeline:
        if item.type != "video" or not item.src:
            continue
        poster = (bundle_dir / item.src).with_suffix(".poster.jpg").resolve()
        try:
            relative = poster.relative_to(bundle_dir.resolve())
        except ValueError:
            continue
        if poster.is_file():
            posters[item.id] = relative.as_posix()
    poster_script = json.dumps(posters, ensure_ascii=True).replace("<", "\\u003c")
    manifest_url = "./manifest.json"
    if manifest.content_version:
        manifest_url += f"?v={quote(manifest.content_version, safe='')}"
    runtime_version = hashlib.sha256((bundle_dir / "interactive-runtime.js").read_bytes()).hexdigest()[:12]
    player_version = hashlib.sha256(PLAYER_JS.encode("utf-8")).hexdigest()[:12]
    scripts = (
        f'  <script>window.EDUHARNESS_POSTERS = {poster_script};</script>\n'
        f'  <script src="./interactive-runtime.js?v={runtime_version}"></script>\n'
        f'  <script src="./player.js?v={player_version}"></script>\n'
        '  <script>window.EduHarnessPlayer.startAmbient();'
        f' window.EduHarnessPlayer.startPlayer({json.dumps(manifest_url)});</script>\n'
    )
    out = bundle_dir / "index.html"
    out.write_text(shell_html(manifest.topic, scripts=scripts), encoding="utf-8")
    (bundle_dir / "README.txt").write_text(
        "Serve this folder over HTTP with byte-range support, then open index.html.\n"
        "Example: python -m eduharness.serve <this folder> --port 8790\n"
        "(python -m http.server works too, but the browser cannot seek inside videos.)\n"
        "Single file, no server: python -m eduharness.preview <run dir>\n",
        encoding="utf-8",
    )
    return out
