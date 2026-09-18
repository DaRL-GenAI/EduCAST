(function () {
  "use strict";

  const PIPELINE = [
    ["01", "Planner"],
    ["02", "Prepare"],
    ["03", "Render"],
    ["04", "Review"],
    ["05", "Bundle"],
  ];
  const HEALTH = {
    ready: "Bundle ready",
    running: "Running",
    interrupted: "Interrupted",
    attention: "Needs attention",
    needs_review: "Needs review",
    unreviewed_bundle: "Unreviewed bundle",
    in_progress: "In progress",
  };
  const SCENE_STATE = {
    passed: "Passed",
    needs_review: "Needs review",
    prepared: "Prepared",
    planned: "Planned",
  };
  const TOOL_LABEL = {
    remotion: "Remotion",
    manim: "Manim",
    image: "Illustration",
    interactive: "Interactive",
    unknown: "Unknown",
  };
  const $ = (id) => document.getElementById(id);
  const qsa = (selector) => [...document.querySelectorAll(selector)];
  const state = {
    payload: null,
    runs: [],
    activeId: localStorage.getItem("eduharness:studio:active") || "",
    activeSceneId: "",
    sceneFilter: "all",
    poller: null,
    toastTimer: null,
    newMode: false,
    dirty: false,
  };

  function escapeHTML(value) {
    const node = document.createElement("div");
    node.textContent = String(value == null ? "" : value);
    return node.innerHTML;
  }

  function clock(seconds) {
    if (seconds == null || Number.isNaN(Number(seconds))) return "-";
    const value = Math.max(0, Math.round(Number(seconds)));
    return `${String(Math.floor(value / 60)).padStart(2, "0")}:${String(value % 60).padStart(2, "0")}`;
  }

  function relativeTime(value) {
    if (!value) return "";
    const delta = Date.now() - new Date(value).getTime();
    if (!Number.isFinite(delta)) return "";
    const minutes = Math.round(Math.abs(delta) / 60000);
    if (minutes < 1) return "Saved just now";
    if (minutes < 60) return `Saved ${minutes} min ago`;
    const hours = Math.round(minutes / 60);
    if (hours < 24) return `Saved ${hours} hr ago`;
    return new Intl.DateTimeFormat("en", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(new Date(value));
  }

  function notify(message, error) {
    const toast = $("toast");
    toast.textContent = message;
    toast.classList.toggle("error", Boolean(error));
    toast.classList.add("show");
    clearTimeout(state.toastTimer);
    state.toastTimer = setTimeout(() => toast.classList.remove("show"), 2400);
  }

  async function request(url, options) {
    const response = await fetch(url, options);
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) throw new Error(data.error || `HTTP ${response.status}`);
    return data;
  }

  function activeRun() {
    return state.runs.find((run) => run.id === state.activeId) || state.runs[0] || null;
  }

  function setConnection(online, text) {
    const node = $("connection");
    node.classList.toggle("online", online);
    node.classList.toggle("offline", !online);
    node.querySelector("span").textContent = text;
  }

  async function refresh(silent) {
    try {
      const payload = await request("/api/state");
      state.payload = payload;
      state.runs = payload.runs || [];
      if (!state.runs.some((run) => run.id === state.activeId)) state.activeId = state.runs[0] ? state.runs[0].id : "";
      setConnection(true, payload.api_configured ? "API ready" : "Local mode");
      render();
      const run = activeRun();
      schedulePoll(run && run.job && run.job.status === "running" ? 1600 : 5000);
      if (!silent) notify("Status refreshed");
    } catch (error) {
      setConnection(false, "Connection lost");
      if (!silent) notify(error.message, true);
      schedulePoll(4500);
    }
  }

  function schedulePoll(delay) {
    clearTimeout(state.poller);
    state.poller = setTimeout(() => refresh(true), delay);
  }

  function render() {
    renderRuns();
    renderCapabilities();
    if (state.newMode) return;
    const run = activeRun();
    if (!run) {
      $("project-title").textContent = "No builds yet";
      $("project-goal").textContent = "Start a new lesson to create the first resumable build.";
      return;
    }
    localStorage.setItem("eduharness:studio:active", run.id);
    renderProject(run);
    renderScenes(run);
    renderRequestForm(run.request);
    renderDiagnostics(run);
  }

  function renderRuns() {
    const query = $("run-search").value.trim().toLowerCase();
    const runs = state.runs.filter((run) => `${run.topic} ${run.id}`.toLowerCase().includes(query));
    $("run-count").textContent = String(runs.length);
    $("run-list").innerHTML = runs.length ? runs.map((run) => `
      <button class="run-item ${run.id === state.activeId && !state.newMode ? "active" : ""}" type="button" data-run="${escapeHTML(run.id)}">
        <i class="run-health ${escapeHTML(run.health)}"></i><span class="run-copy"><strong>${escapeHTML(run.topic)}</strong><small>${escapeHTML(run.id)} · ${escapeHTML(run.next_stage_label)}</small></span><span class="run-ratio">${run.counts.passed}/${run.counts.total}</span>
      </button>`).join("") : '<div class="empty-list">No matching builds</div>';
    qsa("#run-list [data-run]").forEach((button) => button.addEventListener("click", () => {
      state.newMode = false;
      state.dirty = false;
      state.activeId = button.dataset.run;
      state.activeSceneId = "";
      render();
      scrollToStudio();
    }));
  }

  function renderCapabilities() {
    const capabilities = (state.payload && state.payload.capabilities) || [];
    $("capability-mini").innerHTML = capabilities.map((item) => `<span class="mini-cap ${item.available ? "on" : ""}">${escapeHTML(item.label)}</span>`).join("");
  }

  function renderProject(run) {
    $("project-id").textContent = run.id;
    $("project-health").className = `status-pill ${run.health}`;
    $("project-health").textContent = HEALTH[run.health] || run.health;
    $("project-saved").textContent = relativeTime(run.updated_at);
    $("project-title").textContent = run.topic;
    $("project-goal").textContent = run.learning_goal || run.audience || "";
    setLink($("open-player"), run.bundle_url);
    setLink($("open-standalone"), run.standalone_url);
    $("copy-command").disabled = !run.recovery_command;
    const jobRunning = run.job && run.job.status === "running";
    const resume = $("resume-action");
    resume.disabled = !run.next_stage || jobRunning;
    resume.textContent = jobRunning ? `${run.job.stage} running...` : run.next_stage ? `Continue ${run.next_stage_label}` : "Build complete";
    $("metric-scenes").textContent = String(run.counts.total || 0);
    $("metric-scenes-detail").textContent = `${run.counts.rendered} rendered · ${run.timeline_count} timeline nodes`;
    $("metric-review").textContent = `${run.counts.passed} / ${run.counts.total}`;
    $("metric-review-detail").textContent = run.counts.needs_review ? `${run.counts.needs_review} scenes need attention` : "All current checkpoints passed";
    $("metric-runtime").textContent = clock(run.runtime);
    $("metric-runtime-detail").textContent = run.bundle_ready ? "Bundle ready to play" : "Bundle not built";
    $("metric-cost").textContent = run.cost_usd == null ? "-" : `$${Number(run.cost_usd).toFixed(2)}`;
    $("metric-cost-detail").textContent = run.usage_calls == null ? "Usage not recorded" : `${run.usage_calls} API calls`;
    $("diagnostic-count").textContent = String(run.counts.review_errors + run.counts.guard_findings + run.counts.hitl + (run.warnings || []).length);
    renderPipeline(run);
  }

  function setLink(anchor, href) {
    anchor.href = href || "#";
    anchor.setAttribute("aria-disabled", String(!href));
  }

  function renderPipeline(run) {
    const currentIndex = Math.min(4, run.stage_index);
    $("pipeline-steps").innerHTML = PIPELINE.map(([number, label], index) => {
      let cls = index < currentIndex ? "done" : index === currentIndex ? "current" : "";
      if (index === 4 && ["attention", "needs_review", "unreviewed_bundle", "interrupted"].includes(run.health)) cls = "problem";
      let detail = "Waiting";
      if (index === 0) detail = run.request_persisted ? "Saved" : "From blueprint";
      if (index === 1) detail = `${run.counts.planned} scenes`;
      if (index === 2) detail = `${run.counts.prepared} checkpoints`;
      if (index === 3) detail = `${run.counts.rendered} artifacts`;
      if (index === 4) detail = run.bundle_ready ? "Bundle ready" : `${run.counts.passed}/${run.counts.total} passed`;
      return `<li class="pipeline-step ${cls}"><span>${number} · ${escapeHTML(detail)}</span><strong>${label}</strong></li>`;
    }).join("");
  }

  function renderScenes(run) {
    const scenes = run.scenes || [];
    if (!scenes.some((scene) => scene.id === state.activeSceneId)) state.activeSceneId = (scenes.find((scene) => scene.state === "needs_review") || scenes[0] || {}).id || "";
    $("tool-coverage").innerHTML = ["remotion", "manim", "image", "interactive"].map((tool) => `<div class="tool-stat ${tool}"><i></i><strong>${run.tools[tool] || 0}</strong><span>${TOOL_LABEL[tool]}</span></div>`).join("");
    const filtered = scenes.filter((scene) => state.sceneFilter === "all" || scene.state === "needs_review" || scene.review_error || scene.guard_findings.length);
    $("scene-list").innerHTML = filtered.length ? filtered.map((scene, index) => `<button class="scene-row ${scene.id === state.activeSceneId ? "active" : ""}" type="button" data-scene="${escapeHTML(scene.id)}"><span class="scene-number">${String(index + 1).padStart(2, "0")}</span><span class="scene-copy"><strong>${escapeHTML(scene.title)}</strong><small><i class="${escapeHTML(scene.state)}"></i>${escapeHTML(TOOL_LABEL[scene.type] || scene.type)} · ${escapeHTML(SCENE_STATE[scene.state] || scene.state)}</small></span><span class="scene-score">${scene.score == null ? clock(scene.duration) : Number(scene.score).toFixed(1)}</span></button>`).join("") : '<div class="empty-list">No scenes match this filter</div>';
    qsa("[data-scene]").forEach((button) => button.addEventListener("click", () => { state.activeSceneId = button.dataset.scene; renderScenes(run); }));
    renderPreview(run, scenes.find((scene) => scene.id === state.activeSceneId));
  }

  function renderPreview(run, scene) {
    const stage = $("preview-stage");
    const gallery = $("preview-gallery");
    if (!scene) {
      stage.innerHTML = '<div class="preview-empty"><span aria-hidden="true">&#9638;</span><p>Select a scene</p></div>';
      gallery.classList.add("hidden");
      gallery.innerHTML = "";
      return;
    }
    $("preview-title").textContent = scene.title;
    $("preview-tool").className = `tool-pill ${scene.type}`;
    $("preview-tool").textContent = TOOL_LABEL[scene.type] || scene.type;
    $("preview-renderer").textContent = scene.render_mode || scene.type;
    $("preview-duration").textContent = clock(scene.duration);
    $("preview-review").textContent = scene.review_passed ? `Passed${scene.score == null ? "" : ` · ${Number(scene.score).toFixed(1)}`}` : SCENE_STATE[scene.state] || "Needs attention";
    $("preview-attempt").textContent = `#${Number(scene.attempt || 0) + 1}`;
    setLink($("open-asset"), scene.asset_url || scene.preview_url);
    if (scene.type === "interactive" && scene.interactive_preview_url) stage.innerHTML = `<iframe src="${escapeHTML(scene.interactive_preview_url)}" title="${escapeHTML(scene.title)}"></iframe>`;
    else if (scene.asset_url && /\.mp4(?:$|\?)/i.test(scene.asset_url)) stage.innerHTML = `<video src="${escapeHTML(scene.asset_url)}" controls playsinline preload="metadata"></video>`;
    else if (scene.asset_url && /\.(?:png|jpe?g|webp|gif)(?:$|\?)/i.test(scene.asset_url)) stage.innerHTML = `<img src="${escapeHTML(scene.asset_url)}" alt="${escapeHTML(scene.title)}">`;
    else stage.innerHTML = `<div class="preview-empty"><span aria-hidden="true">&#9638;</span><p>${escapeHTML(SCENE_STATE[scene.state] || "Artifact not generated")}</p></div>`;
    const frames = Array.isArray(scene.frame_urls) ? scene.frame_urls : [];
    const galleryItems = frames.map((url, index) => `<a class="preview-frame" href="${escapeHTML(url)}" target="_blank" rel="noopener"><img src="${escapeHTML(url)}" alt="${escapeHTML(scene.title)} frame ${index + 1}" loading="lazy"><span>Frame ${String(index + 1).padStart(2, "0")}</span></a>`);
    if (scene.audio_url) galleryItems.push(`<a class="preview-audio" href="${escapeHTML(scene.audio_url)}" target="_blank" rel="noopener"><span aria-hidden="true">&#9835;</span><span>Open narration audio</span></a>`);
    gallery.classList.toggle("hidden", galleryItems.length === 0);
    gallery.innerHTML = galleryItems.join("");
    const issues = [...(scene.issues || []), ...(scene.guard_findings || []).map((finding) => finding.message || finding.kind)];
    const callout = $("preview-issues");
    callout.classList.toggle("hidden", issues.length === 0);
    callout.innerHTML = issues.length ? `<strong>Attention needed</strong><ul>${issues.slice(0, 4).map((issue) => `<li>${escapeHTML(issue)}</li>`).join("")}</ul>` : "";
  }

  function renderRequestForm(requestData) {
    const form = $("request-form");
    if (state.dirty) return;
    let draft = null;
    try { draft = JSON.parse(localStorage.getItem("eduharness:studio:draft") || "null"); } catch (_) {}
    const value = state.newMode && draft ? draft : { ...((state.payload && state.payload.defaults) || {}), ...(requestData || {}) };
    [...form.elements].forEach((field) => {
      if (!field.name || !(field.name in value)) return;
      if (field.type === "checkbox") field.checked = Boolean(value[field.name]);
      else if (field.type === "radio") field.checked = field.value === String(value[field.name]);
      else field.value = value[field.name] == null ? "" : String(value[field.name]);
    });
    form.elements.request_id.disabled = !state.newMode;
    $("draft-state").textContent = state.newMode && draft ? "Draft restored" : state.newMode ? "New request" : "No changes";
  }

  function formValue() {
    const form = $("request-form");
    return { request_id: form.elements.request_id.value.trim(), topic: form.elements.topic.value.trim(), audience: form.elements.audience.value.trim(), learning_goal: form.elements.learning_goal.value.trim(), source_text: form.elements.source_text.value.trim(), preferred_theme: form.elements.preferred_theme.value || "studio_light", language: form.elements.language.value || "en", max_review_rounds: Number(form.elements.max_review_rounds.value || 3), enable_remotion: form.elements.enable_remotion.checked, enable_manim: form.elements.enable_manim.checked, enable_image: form.elements.enable_image.checked, enable_narration: form.elements.enable_narration.checked, voice: form.elements.voice.value || "alloy", allow_unreviewed_bundle: false, parallel: Number(form.elements.parallel.value || 4) };
  }

  async function saveRequest(startPlan) {
    try {
      const form = $("request-form");
      if (!form.checkValidity()) { form.reportValidity(); return; }
      const result = await request("/api/runs", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(formValue()) });
      state.activeId = result.run.id;
      state.newMode = false;
      state.dirty = false;
      localStorage.removeItem("eduharness:studio:draft");
      notify("Request saved. It is safe to disconnect.");
      await refresh(true);
      if (startPlan) await startJob("1");
    } catch (error) { notify(error.message, true); }
  }

  async function startJob(stage) {
    const run = activeRun();
    if (!run || !stage) return;
    try {
      await request(`/api/runs/${encodeURIComponent(run.id)}/jobs`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ stage }) });
      notify(`${stage} started in the background. It will keep running if you disconnect.`);
      activateTab("diagnostics");
      await refresh(true);
    } catch (error) { notify(error.message, true); }
  }

  function renderDiagnostics(run) {
    const capabilities = (state.payload && state.payload.capabilities) || [];
    $("capability-list").innerHTML = capabilities.map((item) => `<div class="capability-row"><span>${escapeHTML(item.label)}</span><small class="state-dot ${item.available ? "on" : ""}"><i></i>${item.available ? "Available" : "Not configured"}</small></div>`).join("");
    const qualities = [["Visual review", `${run.counts.passed}/${run.counts.total} passed`], ["Guard findings", `${run.counts.guard_findings}`], ["Reviewer errors", `${run.counts.review_errors}`], ["HITL flags", `${run.counts.hitl}`], ["Bundle warnings", `${(run.warnings || []).length}`]];
    $("quality-list").innerHTML = qualities.map(([label, value]) => `<div class="quality-row"><span>${escapeHTML(label)}</span><small>${escapeHTML(value)}</small></div>`).join("");
    loadLog(run.id);
  }

  async function loadLog(runId) {
    try { const data = await request(`/api/runs/${encodeURIComponent(runId)}/log`); $("job-log").textContent = data.log || "No Studio job yet. Recovery commands and checkpoints are shown here."; $("job-log").scrollTop = $("job-log").scrollHeight; } catch (_) {}
  }

  function activateTab(name) {
    qsa(".tab").forEach((tab) => tab.classList.toggle("active", tab.dataset.tab === name));
    qsa(".tab-panel").forEach((panel) => panel.classList.toggle("active", panel.id === `${name}-tab`));
    if (name === "diagnostics" && activeRun()) loadLog(activeRun().id);
  }

  // The operation desk is a tool, not part of the story the page tells. It stays
  // out of the document until someone asks to add a lesson.
  function revealStudio() {
    const desk = $("studio");
    if (!desk.hidden) return desk;
    desk.hidden = false;
    desk.classList.add("is-visible");
    return desk;
  }

  function scrollToStudio() { revealStudio().scrollIntoView({ behavior: "smooth", block: "start" }); }

  function beginNew() {
    state.newMode = true;
    state.dirty = false;
    renderRuns();
    $("project-id").textContent = "new-build";
    $("project-health").className = "status-pill in_progress";
    $("project-health").textContent = "New request";
    $("project-saved").textContent = "Draft saved in this browser";
    $("project-title").textContent = "Create teaching media";
    $("project-goal").textContent = "Define the learning goal and combine the right render tools.";
    setLink($("open-player"), null);
    setLink($("open-standalone"), null);
    $("copy-command").disabled = true;
    $("resume-action").disabled = true;
    $("resume-action").textContent = "Save to begin";
    ["metric-scenes", "metric-review", "metric-runtime", "metric-cost"].forEach((id) => $(id).textContent = "-");
    ["metric-scenes-detail", "metric-review-detail", "metric-runtime-detail", "metric-cost-detail"].forEach((id) => $(id).textContent = "Waiting for a plan");
    $("pipeline-steps").innerHTML = PIPELINE.map(([number, label], index) => `<li class="pipeline-step ${index === 0 ? "current" : ""}"><span>${number} · ${index === 0 ? "Editing" : "Waiting"}</span><strong>${label}</strong></li>`).join("");
    renderRequestForm({ ...((state.payload && state.payload.defaults) || {}), request_id: `lesson_${new Date().toISOString().slice(0, 10).replaceAll("-", "")}`, enable_remotion: true, enable_manim: true, enable_image: true, enable_narration: true });
    activateTab("generate");
    scrollToStudio();
  }

  function bind() {
    $("refresh").addEventListener("click", () => refresh(false));
    $("new-build").addEventListener("click", beginNew);
    // The showcase composer replaced the hero and demo build buttons.
    ["hero-new-build", "pipeline-new-build"].forEach((id) => {
      const button = $(id);
      if (button) button.addEventListener("click", beginNew);
    });
    qsa('.top-nav a[href="#studio"]').forEach((link) => link.addEventListener("click", () => revealStudio()));
    $("run-search").addEventListener("input", renderRuns);
    qsa(".tab").forEach((tab) => tab.addEventListener("click", () => activateTab(tab.dataset.tab)));
    qsa("#scene-filter button").forEach((button) => button.addEventListener("click", () => { state.sceneFilter = button.dataset.filter; qsa("#scene-filter button").forEach((candidate) => candidate.classList.toggle("active", candidate === button)); if (activeRun()) renderScenes(activeRun()); }));
    $("copy-command").addEventListener("click", async () => { const run = activeRun(); if (!run || !run.recovery_command) return; try { await navigator.clipboard.writeText(run.recovery_command); notify("Recovery command copied"); } catch (_) { notify(run.recovery_command); } });
    $("resume-action").addEventListener("click", () => { const run = activeRun(); if (run) startJob(run.next_stage); });
    $("request-form").addEventListener("input", () => { state.dirty = true; $("draft-state").textContent = "Unsaved changes"; localStorage.setItem("eduharness:studio:draft", JSON.stringify(formValue())); });
    $("request-form").addEventListener("submit", (event) => { event.preventDefault(); saveRequest(false); });
    $("save-and-plan").addEventListener("click", () => saveRequest(true));
    $("copy-log").addEventListener("click", async () => { try { await navigator.clipboard.writeText($("job-log").textContent); notify("Log copied"); } catch (_) { notify("Clipboard access was blocked", true); } });
  }

  bind();
  if (location.hash === "#studio") revealStudio();
  window.addEventListener("hashchange", () => { if (location.hash === "#studio") revealStudio(); });
  refresh(true);
})();
