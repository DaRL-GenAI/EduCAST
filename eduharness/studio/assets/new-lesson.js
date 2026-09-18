(() => {
  'use strict';

  const $ = (id) => document.getElementById(id);
  const form = $('lesson-form');
  const fields = $('lesson-fields');
  const submit = $('lesson-submit');
  const stages = [...document.querySelectorAll('.lesson-stages li')];
  const stageDescriptions = stages.map((item) => item.querySelector('[data-stage-detail]').textContent);
  const storageKey = 'educast.newLesson';
  let lessonId = null;
  let currentLesson = null;
  let submitting = false;
  let pollTimer;
  let polling = false;
  let configured = true;
  let configLoaded = false;
  let draftRestored = false;
  let formTouched = false;
  let pendingKey = null;

  const storage = {
    get(key) { try { return localStorage.getItem(`${storageKey}.${key}`); } catch { return null; } },
    set(key, value) { try { localStorage.setItem(`${storageKey}.${key}`, value); } catch { /* Reload recovery still works through the URL. */ } },
    remove(key) { try { localStorage.removeItem(`${storageKey}.${key}`); } catch { /* Storage may be unavailable. */ } },
  };

  function payload() {
    const values = {};
    for (const control of fields.querySelectorAll('[name]')) {
      values[control.name] = control.type === 'checkbox' ? control.checked : control.value.trim();
    }
    return values;
  }

  function fill(values) {
    if (!values || typeof values !== 'object') return;
    for (const control of fields.querySelectorAll('[name]')) {
      if (control.name === 'openai_api_key') continue;
      if (!Object.prototype.hasOwnProperty.call(values, control.name)) continue;
      if (control.type === 'checkbox') control.checked = Boolean(values[control.name]);
      else if (typeof values[control.name] === 'string') control.value = values[control.name];
    }
  }

  function saveDraft() {
    const draft = payload();
    // Never put a customer secret in localStorage or the draft payload.
    delete draft.openai_api_key;
    storage.set('draft', JSON.stringify(draft));
  }

  function submissionKey() {
    const saved = pendingKey || storage.get('pending-key');
    if (saved) return saved;
    const key = typeof globalThis.crypto?.randomUUID === 'function' ? crypto.randomUUID() : `lesson-${Date.now()}-${Math.random().toString(16).slice(2)}`;
    pendingKey = key;
    storage.set('pending-key', key);
    return key;
  }

  function showError(message = '') {
    $('lesson-error').textContent = message;
    $('lesson-error').hidden = !message;
  }

  function syncControls() {
    const busy = submitting || Boolean(lessonId);
    fields.disabled = submitting || (Boolean(lessonId) && currentLesson?.status === 'running');
    submit.disabled = busy || !configured || !configLoaded;
    submit.textContent = submitting ? 'Starting your lesson…' : currentLesson?.status === 'running' ? 'Lesson in progress…' : lessonId ? 'Lesson saved' : 'Generate lesson ↗';
    $('lesson-retry').disabled = submitting || !configured;
    form.setAttribute('aria-busy', String(submitting));
  }

  async function request(url, options = {}) {
    let response;
    try { response = await fetch(url, { cache: 'no-store', ...options }); }
    catch { throw new Error('We couldn’t connect to the lesson service. Your brief is still here; please try again.'); }
    let data;
    try { data = await response.json(); } catch { throw new Error('The service returned an unexpected response. Please try again.'); }
    if (!response.ok) {
      const error = new Error(data.error || `The request could not be completed (${response.status}).`);
      error.status = response.status;
      throw error;
    }
    return data;
  }

  function rememberLesson(id) {
    lessonId = id;
    storage.set('active', id);
    const url = new URL(location.href);
    url.searchParams.set('lesson', id);
    history.replaceState(null, '', url);
  }

  function safeBundle(url) {
    if (typeof url !== 'string' || !url) return null;
    try {
      const target = new URL(url, location.origin);
      return target.origin === location.origin && target.pathname.startsWith('/runs/') && target.pathname.includes('/bundle/') ? target.href : null;
    } catch { return null; }
  }

  function render(lesson) {
    if (!lesson || typeof lesson.id !== 'string') throw new Error('The lesson status could not be read. Please try again.');
    currentLesson = lesson;
    rememberLesson(lesson.id);
    const running = lesson.status === 'running';
    const ready = lesson.status === 'ready';
    const retryable = ['failed', 'interrupted', 'needs_attention'].includes(lesson.status);
    const titles = { running: 'Your idea is taking shape.', ready: 'Your lesson is ready.', needs_attention: 'A little more care is needed.', failed: 'This build needs another try.', interrupted: 'Your lesson is saved.' };
    const summaries = { running: 'Follow the saved progress below. You can return to this page while the lesson continues.', ready: 'Your lesson has been built and is ready to explore.', needs_attention: 'The build has finished with items that need attention. You can open any available preview or retry generation.', failed: 'Generation stopped before the lesson was finished. Your brief is saved for another attempt.', interrupted: 'Generation is not running. Your saved lesson can be retried below.' };
    $('lesson-progress-kicker').textContent = '02 / YOUR LESSON, IN THE MAKING';
    $('progress-heading').textContent = titles[lesson.status] || 'Your lesson';
    $('lesson-progress-copy').textContent = lesson.message || summaries[lesson.status] || 'Checking the saved lesson status.';
    $('lesson-live').hidden = false;
    $('lesson-live').dataset.status = lesson.status;
    const stageLabel = typeof lesson.stage === 'string' ? lesson.stage : '';
    $('lesson-status-text').textContent = ready ? 'Ready to explore' : running ? `${stageLabel && stageLabel.toLowerCase() !== 'all' ? `${stageLabel} · ` : ''}In progress` : { needs_attention: 'Needs attention', failed: 'Generation stopped', interrupted: 'Ready to retry' }[lesson.status] || 'Saved';
    const counts = lesson.counts || {};
    const count = (key) => Math.max(0, Number(counts[key]) || 0);
    const total = count('total');
    const values = [count('planned'), count('prepared'), count('rendered'), count('passed')];
    const stageKeys = ['plan', 'prepare', 'render', 'review', 'bundle'];
    let currentStage = stageKeys.findIndex((key) => stageLabel.toLowerCase().startsWith(key));
    if (currentStage < 0) currentStage = !total ? 0 : values.findIndex((value) => value < total);
    if (currentStage < 0) currentStage = 4;
    stages.forEach((item, index) => {
      const done = ready || (index < 4 && total > 0 && values[index] >= total);
      item.classList.toggle('is-done', done);
      item.classList.toggle('is-current', running && index === currentStage);
      if (running && index === currentStage) item.setAttribute('aria-current', 'step');
      else item.removeAttribute('aria-current');
      item.querySelector('.lesson-stage-check').textContent = done ? '✓' : '';
      item.querySelector('[data-stage-detail]').textContent = total && index < 4 ? `${values[index]} of ${total} scenes ${['planned', 'prepared', 'rendered', 'passed review'][index]}` : index === 4 && ready ? 'Your lesson player is ready.' : stageDescriptions[index];
    });
    const bundle = safeBundle(lesson.bundle_url);
    const open = $('lesson-open');
    open.hidden = !bundle;
    if (bundle) open.href = bundle;
    else open.removeAttribute('href');
    open.textContent = ready ? 'Open your lesson ↗' : 'Open lesson preview ↗';
    $('lesson-retry').hidden = !retryable;
    $('lesson-start-over').hidden = running;
    $('lesson-result').hidden = !bundle && !retryable && running;
    $('lesson-timing').textContent = lesson.topic || 'Your progress is saved. Keep this page link to return to your lesson.';
    $('lesson-connection-note').hidden = true;
    syncControls();
  }

  function schedulePoll(delay = 3000) {
    clearTimeout(pollTimer);
    if (lessonId) pollTimer = setTimeout(poll, delay);
  }

  async function poll() {
    if (!lessonId || polling || submitting) return;
    polling = true;
    const requestedId = lessonId;
    try {
      const data = await request(`/api/lessons/${encodeURIComponent(requestedId)}`);
      if (requestedId !== lessonId) return;
      render(data.lesson);
      if (data.lesson.status === 'running') schedulePoll();
    } catch (error) {
      if (requestedId !== lessonId) return;
      $('lesson-connection-note').hidden = false;
      if (error.status === 404) {
        $('lesson-connection-note').textContent = 'This saved lesson could not be found. You can start a new lesson with your saved brief.';
        $('lesson-result').hidden = false;
        $('lesson-start-over').hidden = false;
      } else {
        $('lesson-connection-note').textContent = 'The connection is taking a moment. We’ll check again automatically; your generation has not been restarted.';
        schedulePoll(5000);
      }
    } finally { polling = false; }
  }

  async function start(retry = false) {
    if (submitting || (!retry && lessonId) || !configured || !configLoaded) return;
    const apiKey = $('openai-api-key').value.trim();
    if (!apiKey) {
      showError('Enter your OpenAI API key to start this build.');
      $('openai-api-key').focus();
      return;
    }
    submitting = true;
    showError();
    clearTimeout(pollTimer);
    saveDraft();
    syncControls();
    try {
      const data = await request(retry ? `/api/lessons/${encodeURIComponent(lessonId)}/retry` : '/api/lessons', {
        method: 'POST', headers: { 'Content-Type': 'application/json', ...(retry ? {} : { 'Idempotency-Key': submissionKey() }) }, body: JSON.stringify(retry ? { openai_api_key: apiKey } : { ...payload(), openai_api_key: apiKey }),
      });
      $('openai-api-key').value = '';
      if (!retry) { storage.remove('pending-key'); pendingKey = null; }
      render(data.lesson);
      if (data.lesson.status === 'running') schedulePoll();
      if (matchMedia('(max-width: 730px)').matches) $('lesson-process').scrollIntoView({ behavior: matchMedia('(prefers-reduced-motion: reduce)').matches ? 'instant' : 'smooth', block: 'start' });
    } catch (error) {
      showError(error.message || 'We couldn’t connect to the lesson service. Your brief is still here; please try again.');
      if (!retry && [400, 409].includes(error.status)) { storage.remove('pending-key'); pendingKey = null; }
      if (retry && lessonId) schedulePoll();
    } finally {
      submitting = false;
      syncControls();
    }
  }

  function startOver() {
    $('openai-api-key').value = '';
    clearTimeout(pollTimer);
    lessonId = null;
    currentLesson = null;
    storage.remove('active');
    const url = new URL(location.href);
    url.searchParams.delete('lesson');
    history.replaceState(null, '', url);
    $('lesson-progress-kicker').textContent = '02 / FROM BRIEF TO POSSIBILITY';
    $('progress-heading').textContent = 'Ideas take shape, one step at a time.';
    $('lesson-progress-copy').textContent = 'A thoughtful path from what you want to teach to something students can explore.';
    ['lesson-live', 'lesson-result', 'lesson-connection-note'].forEach((id) => { $(id).hidden = true; });
    $('lesson-timing').textContent = 'Build time depends on your lesson and selected media.';
    stages.forEach((item, index) => {
      item.classList.remove('is-current', 'is-done');
      item.removeAttribute('aria-current');
      item.querySelector('.lesson-stage-check').textContent = '';
      item.querySelector('[data-stage-detail]').textContent = stageDescriptions[index];
    });
    showError();
    syncControls();
    $('lesson-topic').focus();
  }

  async function loadConfig() {
    try {
      const config = await request('/api/lessons/config');
      configured = (config.configured ?? config.available) !== false;
      if (!draftRestored && !formTouched && !lessonId) fill(config.defaults);
      const capabilities = Array.isArray(config.capabilities) ? config.capabilities : [];
      const capabilityMap = new Map();
      capabilities.forEach((capability) => {
        if (!capability || typeof capability.id !== 'string') return;
        const key = capability.id.replace(/^enable_/, '');
        capabilityMap.set(key, capability);
      });
      fields.querySelectorAll('.lesson-media-grid input[type="checkbox"]').forEach((control) => {
        const capability = capabilityMap.get(control.name.replace(/^enable_/, ''));
        if (!capability) return;
        const available = capability.available !== false;
        control.disabled = !available;
        control.closest('label')?.classList.toggle('is-unavailable', !available);
        if (!available) control.checked = false;
        if (capability.label) control.closest('label')?.setAttribute('title', available ? capability.label : `${capability.label} is currently unavailable`);
      });
      if (!configured) {
        $('lesson-config-note').textContent = 'Lesson generation is temporarily unavailable. Your brief can stay here until the service is ready.';
        $('lesson-config-note').hidden = false;
      } else $('lesson-config-note').hidden = true;
    } catch {
      $('lesson-config-note').textContent = 'We couldn’t check service availability. You can still try submitting your lesson.';
      $('lesson-config-note').hidden = false;
    } finally {
      configLoaded = true;
      syncControls();
    }
  }

  form.addEventListener('submit', (event) => {
    event.preventDefault();
    $('lesson-topic').value = $('lesson-topic').value.trim();
    if (form.reportValidity()) start();
  });
  form.addEventListener('input', () => { formTouched = true; saveDraft(); });
  form.addEventListener('change', () => { formTouched = true; saveDraft(); });
  $('lesson-retry').addEventListener('click', () => start(true));
  $('lesson-start-over').addEventListener('click', startOver);
  window.addEventListener('online', () => { if (lessonId && (!currentLesson || currentLesson.status === 'running')) schedulePoll(0); });
  try {
    const draft = JSON.parse(storage.get('draft') || 'null');
    if (draft && typeof draft === 'object') { fill(draft); draftRestored = true; }
  } catch { /* A damaged draft should not block lesson creation. */ }
  const savedId = new URL(location.href).searchParams.get('lesson') || storage.get('active');
  if (savedId && /^[A-Za-z0-9][A-Za-z0-9_-]{0,95}$/.test(savedId)) {
    lessonId = savedId;
    $('progress-heading').textContent = 'Welcome back to your lesson.';
    $('lesson-progress-copy').textContent = 'Checking your saved progress…';
    poll();
  }
  syncControls();
  loadConfig();
})();
