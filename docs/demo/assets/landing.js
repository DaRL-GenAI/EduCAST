(function () {
  "use strict";
  const $ = (id) => document.getElementById(id);
  const qsa = (selector) => [...document.querySelectorAll(selector)];
  const reducedMotion = matchMedia("(prefers-reduced-motion: reduce)").matches;

  // The small experiment is an illustrative introduction to torque: F × r.
  const distance = $("lever-distance");
  function updateLever() {
    const r = Number(distance.value);
    const rightTorque = 10 * r;
    const balanced = Math.abs(rightTorque - 30) < 0.05;
    $("distance-output").textContent = `${r.toFixed(1)} m`;
    distance.setAttribute("aria-valuetext", `${r.toFixed(1)} metres; ${rightTorque.toFixed(0)} newton metres on the right`);
    $("lever-weight").setAttribute("transform", `translate(${270 + r * 60} 141)`);
    $("lever-distance-line").setAttribute("d", `M270 167v6h${r * 60}v-6`);
    $("lever-distance-label").setAttribute("x", String(270 + r * 30));
    $("lever-distance-label").textContent = `${r.toFixed(1)} m`;
    $("lever-beam").setAttribute("transform", `rotate(${Math.max(-16, Math.min(16, (rightTorque - 30) * 0.65))} 270 146)`);
    $("balance-feedback").classList.toggle("balanced", balanced);
    $("balance-message").textContent = balanced
      ? "Balanced! 20 N × 1.5 m = 10 N × 3 m."
      : `${rightTorque < 30 ? "Move farther out" : "Move a little closer"} — left: 30 N·m · right: ${rightTorque.toFixed(0)} N·m`;
    $("balance-feedback").querySelector(".balance-symbol").textContent = balanced ? "✓" : "↔";
  }
  distance.addEventListener("input", updateLever);
  $("reset-experiment").addEventListener("click", () => { distance.value = "1.5"; updateLever(); });
  updateLever();

  const originalBlueprint = $("pipeline-artifact").innerHTML;
  const artifact = (label, content) => `<div class="artifact-top"><span class="artifact-dot"></span>${label}<span>Illustrative example</span></div>${content}`;
  const stages = {
    plan: {
      kicker: "01 / A PURPOSE FOR EVERY SCENE", title: "Good teaching starts with a clear intention.",
      description: "The planner turns your topic, audience, and learning goal into a scene-by-scene blueprint. Every scene gets a medium, narration, and a short list of ideas that must be visible.",
      tags: ["Learning goals", "Scene planning", "Shared visual style"], visual: originalBlueprint,
    },
    prepare: {
      kicker: "02 / THE RIGHT MEDIUM FOR THE IDEA", title: "Different ideas deserve different tools.",
      description: "Scene executors prepare animation instructions, generate teaching illustrations, and configure trusted practice templates. Narration is synthesized and cached, ready to accompany each explanation.",
      tags: ["Four media tools", "Five practice templates", "Narration"],
      visual: artifact("CREATIVE INGREDIENTS", '<div class="artifact-grid"><div class="artifact-tile"><i>▥</i>Remotion<span>Stories, steps, and comparisons</span></div><div class="artifact-tile"><i>ƒ</i>Manim<span>Equations and geometry</span></div><div class="artifact-tile"><i>✳</i>Illustration<span>Diagrams and visual intuition</span></div><div class="artifact-tile"><i>↔</i>Interactive<span>Explore, answer, and practice</span></div></div>'),
    },
    render: {
      kicker: "03 / PIECES BECOME AN EXPERIENCE", title: "A common visual language. A natural rhythm.",
      description: "Local renderers turn prepared scenes into motion, diagrams, and practice panels. Shared style settings keep the lesson coherent; narration is combined with video while scene checkpoints preserve progress.",
      tags: ["Local rendering", "Shared teaching board", "Audio and visual timing"],
      visual: artifact("THE RENDER WORKSPACE", '<div class="bundle-art"><div class="bundle-screen">τ = F × r</div><div class="bundle-timeline"><i></i><i></i><i></i><i></i><i></i></div></div><div class="blueprint-row" style="margin:0 20px 16px"><span>♫</span><strong>Narration + visual explanation</strong><i>One scene</i></div>'),
    },
    review: {
      kicker: "04 / CHECK, LEARN, IMPROVE", title: "A second look at every explanation.",
      description: "Deterministic guards check for clipped text, overlaps, blank frames, and overflowing interactions. An independent visual reviewer checks the lesson’s key elements. Blocking issues trigger targeted repairs and another review.",
      tags: ["Layout guards", "Visual review", "Targeted repair loop"],
      visual: artifact("WHAT GETS CHECKED", '<div class="review-list"><div class="review-line"><span>Text stays inside the frame</span><i>LAYOUT GUARD</i></div><div class="review-line"><span>Key ideas are visible</span><i>VISUAL REVIEW</i></div><div class="review-line"><span>Practice fits its panel</span><i>OVERFLOW CHECK</i></div><div class="review-line warning"><span>Blocking issue found?</span><i>REPAIR → RECHECK</i></div></div><div class="artifact-caption">Review criteria shown here; actual results are available in Studio.</div>'),
    },
    bundle: {
      kicker: "05 / MORE THAN A VIDEO", title: "Watch a little. Try a little. Make it click.",
      description: "EduBundle brings the lesson together in a chapter-based player. A video can pause for a question and continue after practice. Learners can revisit chapters, read captions, and resume where they left off.",
      tags: ["Chapter navigation", "Practice in the timeline", "Standalone HTML export"],
      visual: artifact("ONE CONNECTED LESSON", '<div class="bundle-art"><div class="bundle-screen">Watch. Wonder. Try.</div><div class="bundle-timeline"><i></i><i></i><i></i><i></i><i></i></div></div><div class="review-list"><div class="review-line"><span>Watch the explanation</span><i>▶ PLAY</i></div><div class="review-line warning"><span>Pause for a practice checkpoint</span><i>↔ TRY</i></div><div class="review-line"><span>Continue the story</span><i>↗ EXPLORE</i></div></div>'),
    },
  };
  function selectStage(button) {
    const stage = stages[button.dataset.stage];
    qsa(".pipeline-card").forEach((candidate) => {
      const selected = candidate === button;
      candidate.classList.toggle("active", selected);
      candidate.setAttribute("aria-selected", String(selected));
      candidate.tabIndex = selected ? 0 : -1;
    });
    $("pipeline-detail").setAttribute("aria-labelledby", button.id);
    $("pipeline-detail-kicker").textContent = stage.kicker;
    $("pipeline-detail-title").textContent = stage.title;
    $("pipeline-detail-description").textContent = stage.description;
    $("pipeline-detail-tags").replaceChildren(...stage.tags.map((tag) => {
      const node = document.createElement("span"); node.textContent = tag; return node;
    }));
    $("pipeline-artifact").innerHTML = stage.visual;
  }
  qsa(".pipeline-card").forEach((button) => button.addEventListener("click", () => selectStage(button)));

  // Arrow, Home, and End keys follow the same tab order as pointer selection.
  qsa('[role="tablist"]').forEach((tablist) => tablist.addEventListener("keydown", (event) => {
    const tabs = [...tablist.querySelectorAll('[role="tab"]')];
    const index = tabs.indexOf(document.activeElement);
    if (index < 0 || !["ArrowRight", "ArrowLeft", "Home", "End"].includes(event.key)) return;
    event.preventDefault();
    const next = event.key === "Home" ? 0 : event.key === "End" ? tabs.length - 1 : (index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length;
    tabs[next].click(); tabs[next].focus({ preventScroll: true });
    if (tablist.classList.contains("pipeline-visual") && matchMedia("(max-width: 800px)").matches) {
      const target = tabs[next];
      tablist.scrollTo({ left: Math.max(0, target.offsetLeft - tablist.offsetLeft - 10), behavior: reducedMotion ? "instant" : "smooth" });
    }
  }));

  // The starter chips fill the composer so a visitor can begin from an example.
  const topic = $("lesson-topic");
  qsa(".starter-chip").forEach((chip) => chip.addEventListener("click", () => {
    const audience = $("lesson-audience");
    topic.value = chip.dataset.topic;
    if (audience && !audience.value.trim()) audience.value = chip.dataset.audience || "";
    [topic, audience].forEach((field) => field && field.dispatchEvent(new Event("input", { bubbles: true })));
    topic.focus();
    topic.setSelectionRange(topic.value.length, topic.value.length);
  }));


  if ("IntersectionObserver" in window) {
    const anchors = qsa(".top-nav a");
    const observer = new IntersectionObserver((entries) => {
      entries.forEach((entry) => {
        if (entry.isIntersecting) anchors.forEach((link) => {
          const active = link.hash === `#${entry.target.id}`;
          link.classList.toggle("active", active);
          if (active) link.setAttribute("aria-current", "location"); else link.removeAttribute("aria-current");
        });
      });
    }, { rootMargin: "-15% 0px -65%" });
    qsa("#top, #try, #pipeline, #studio").forEach((section) => observer.observe(section));
  }
})();
