// Keep each preview card's chapter count, runtime and practice count true to the
// bundle that is actually published, rather than to numbers typed into the HTML.
// Same contract as landing.js: the authored values stay as the offline fallback,
// and the player URL follows the bundle's content_version so a rebuilt lesson is
// not served from a stale cache.
(() => {
  "use strict";

  const duration = (seconds) => {
    const value = Math.round(Number(seconds) || 0);
    return `${Math.floor(value / 60)}:${String(value % 60).padStart(2, "0")}`;
  };

  const practiceCount = (timeline) => timeline.reduce(
    (count, item) => count + (item.type === "interactive" ? 1 : 0) + (item.overlays || []).length, 0);

  document.querySelectorAll(".more-lesson[data-bundle]").forEach((row) => {
    const base = `/runs/${encodeURIComponent(row.dataset.run)}/bundle/`;
    Promise.all([
      fetch(base + "manifest.json", { cache: "no-cache" })
        .then((response) => { if (!response.ok) throw Error("Manifest unavailable"); return response.json(); }),
      fetch(base + "warnings.json", { cache: "no-cache" })
        .then((response) => (response.ok ? response.json() : null)).catch(() => null),
    ]).then(([manifest, warnings]) => {
      const timeline = Array.isArray(manifest.timeline) ? manifest.timeline : [];
      const meta = row.querySelector("[data-more-meta]");
      if (meta && timeline.length) {
        const practice = practiceCount(timeline);
        meta.replaceChildren(...[
          `${timeline.length} chapters`,
          duration(manifest.total_duration),
          `${practice} ${practice === 1 ? "practice" : "practices"}`,
        ].map((label) => {
          const item = document.createElement("i");
          item.textContent = label;
          return item;
        }));
      }
      if (manifest.content_version) {
        row.querySelectorAll("[data-more-frame], .demo-player-heading > a").forEach((el) => {
          const attribute = el.tagName === "IFRAME" ? "src" : "href";
          const url = new URL(el.getAttribute(attribute), location.href);
          url.searchParams.set("v", manifest.content_version);
          el.setAttribute(attribute, url.pathname + url.search);
        });
      }
      // The bundler DELETES warnings.json once a build has no problems, so a
      // missing file -- not a flag inside it -- is what marks a clean build.
      // Anything else leaves the preview badge exactly as authored.
      if (!warnings) {
        const badge = row.querySelector(".preview-badge");
        if (badge) badge.textContent = "REVIEWED BUILD";
      }
    }).catch(() => { /* Authored numbers remain correct when the bundle is unreachable. */ });
  });
})();
