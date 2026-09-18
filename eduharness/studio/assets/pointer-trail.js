(() => {
  "use strict";

  // Preserve the original landing page's pastel number trail.
  function initNumberTrail() {
    const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)");
    const finePointer = window.matchMedia("(pointer: fine)");
    if (reduceMotion.matches || !finePointer.matches || document.querySelector(".number-trail-layer")) return;
    const layer = document.createElement("div");
    layer.className = "number-trail-layer";
    layer.setAttribute("aria-hidden", "true");
    document.body.appendChild(layer);
    const colors = ["#f7a6ac", "#f7b2c7", "#f3bbb1", "#eec78a", "#eee9a2", "#cbe4b1", "#b3ddcb", "#b8e5fa"];
    const numbers = ["01", "02", "03", "04", "05", "06", "07", "08", "09"];
    const trailScales = [0.62, 0.82, 1.08, 1.34, 1.72, 0.9, 1.2, 1.92];
    let lastX = 0;
    let lastY = 0;
    let lastSpawn = 0;
    let sequence = 0;
    const maxParticles = 120;
    const spawn = (event, now) => {
      const dx = event.clientX - lastX;
      const dy = event.clientY - lastY;
      const distance = Math.hypot(dx, dy);
      if (now - lastSpawn < 24 || distance < 8) return;
      lastX = event.clientX;
      lastY = event.clientY;
      lastSpawn = now;
      const particleCount = Math.min(4, Math.max(2, Math.ceil(distance / 18)));
      const directionX = distance ? dx / distance : 0;
      const directionY = distance ? dy / distance : 0;
      const normalX = -directionY;
      const normalY = directionX;
      for (let index = 0; index < particleCount; index += 1) {
        while (layer.childElementCount >= maxParticles) layer.firstElementChild.remove();
        const particle = document.createElement("span");
        const particleSequence = sequence;
        const progress = particleCount === 1 ? 0 : index / (particleCount - 1);
        const behind = Math.min(distance * 0.58, 38) * progress;
        const spread = (((particleSequence * 5 + index * 3) % 7) - 3) * 4;
        particle.className = "number-trail";
        particle.textContent = numbers[particleSequence % numbers.length];
        particle.style.setProperty("--trail-color", colors[particleSequence % colors.length]);
        particle.style.left = `${event.clientX - directionX * behind + normalX * spread}px`;
        particle.style.top = `${event.clientY - directionY * behind + normalY * spread}px`;
        particle.style.setProperty("--trail-drift", `${Math.round(((particleSequence * 7 + index * 5) % 9 - 4) * 8)}px`);
        particle.style.setProperty("--trail-lift", `${64 + ((particleSequence + index * 2) % 4) * 11}px`);
        particle.style.setProperty("--trail-rotate", `${((particleSequence * 3 + index * 7) % 9 - 4) * 3}deg`);
        particle.style.setProperty("--trail-scale", `${trailScales[particleSequence % trailScales.length]}`);
        sequence += 1;
        layer.appendChild(particle);
        particle.addEventListener("animationend", () => particle.remove(), { once: true });
        particle.addEventListener("animationcancel", () => particle.remove(), { once: true });
      }
    };
    window.addEventListener("pointermove", (event) => {
      if (reduceMotion.matches || !finePointer.matches || event.pointerType === "touch" || (event.target instanceof Element && event.target.closest("iframe"))) return;
      spawn(event, performance.now());
    }, { passive: true });
    document.addEventListener("visibilitychange", () => {
      if (document.hidden) layer.replaceChildren();
    });
    const clearDisabledTrail = () => {
      if (reduceMotion.matches || !finePointer.matches) layer.replaceChildren();
    };
    reduceMotion.addEventListener("change", clearDisabledTrail);
    finePointer.addEventListener("change", clearDisabledTrail);
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initNumberTrail, { once: true });
  } else {
    initNumberTrail();
  }
})();
