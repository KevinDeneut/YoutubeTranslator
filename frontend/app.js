const API = "http://localhost:8000";

// Language names (populated after loadLanguages)
let SUPPORTED_LANGUAGES = {};

// ─── Tabs ────────────────────────────────────────────────────────────────────

document.querySelectorAll(".tab").forEach(tab => {
  tab.addEventListener("click", () => switchTab(tab.dataset.tab));
});

function switchTab(name, arg) {
  document.querySelectorAll(".tab").forEach(t =>
    t.classList.toggle("active", t.dataset.tab === name));
  document.querySelectorAll(".tab-content").forEach(s =>
    s.classList.toggle("active", s.id === `tab-${name}`));
  if (name === "profiles") loadProfiles();
  if (name === "jobs") loadJobs(arg);
}

document.querySelectorAll("[data-goto]").forEach(link => {
  link.addEventListener("click", e => {
    e.preventDefault();
    switchTab(link.dataset.goto);
  });
});

// ─── Languages ───────────────────────────────────────────────────────────────

async function loadLanguages() {
  const langs = await apiFetch("/api/languages");
  SUPPORTED_LANGUAGES = langs || {};
  const srcSel = document.getElementById("source-lang");
  const tgtSel = document.getElementById("target-lang");
  for (const [code, name] of Object.entries(langs)) {
    srcSel.insertAdjacentHTML("beforeend", `<option value="${code}">${name}</option>`);
    tgtSel.insertAdjacentHTML("beforeend", `<option value="${code}">${name}</option>`);
  }
  tgtSel.value = "nl";
}

// ─── Translate tab ────────────────────────────────────────────────────────────

document.getElementById("btn-fetch-info").addEventListener("click", async () => {
  const url = document.getElementById("translate-url").value.trim();
  if (!url) return;
  const info = await apiFetch("/api/video-info", "POST", { url });
  if (!info) return;

  document.getElementById("video-thumb").src = info.thumbnail || "";
  document.getElementById("video-title").textContent = info.title || "";
  document.getElementById("video-channel").textContent = info.channel || "";
  document.getElementById("video-duration").textContent = info.duration ? formatDuration(info.duration) : "";
  document.getElementById("video-preview").classList.remove("hidden");
  checkTranslateReady();
});

document.getElementById("translate-url").addEventListener("input", checkTranslateReady);
document.getElementById("target-lang").addEventListener("change", checkTranslateReady);
document.getElementById("voice-profile").addEventListener("change", checkTranslateReady);

function checkTranslateReady() {
  const url = document.getElementById("translate-url").value.trim();
  const lang = document.getElementById("target-lang").value;
  const profile = document.getElementById("voice-profile").value;
  document.getElementById("btn-translate").disabled = !(url && lang && profile);
}

document.getElementById("btn-translate").addEventListener("click", async () => {
  const body = {
    youtube_url: document.getElementById("translate-url").value.trim(),
    source_language: document.getElementById("source-lang").value || null,
    target_language: document.getElementById("target-lang").value,
    voice_profile_id: document.getElementById("voice-profile").value,
  };

  const res = await apiFetch("/api/translate", "POST", body);
  if (!res) return;

  switchTab("jobs", res.job_id);
});

// ─── Voice profiles ───────────────────────────────────────────────────────────

let _profileVideoDuration = null;

document.getElementById("btn-profile-fetch").addEventListener("click", async () => {
  const url = document.getElementById("profile-url").value.trim();
  if (!url) return;
  const info = await apiFetch("/api/video-info", "POST", { url });
  if (!info) return;

  _profileVideoDuration = info.duration;
  document.getElementById("profile-thumb").src = info.thumbnail || "";
  document.getElementById("profile-title").textContent = info.title || "";
  document.getElementById("profile-channel").textContent = info.channel || "";
  document.getElementById("profile-video-duration").textContent = info.duration ? formatDuration(info.duration) : "";
  document.getElementById("profile-video-preview").classList.remove("hidden");

  if (!document.getElementById("profile-name").value && info.channel) {
    document.getElementById("profile-name").value = info.channel;
  }
  updateIntervalHint();
});

function updateIntervalHint() {
  const start = parseFloat(document.getElementById("profile-start").value) || 0;
  const dur   = parseFloat(document.getElementById("profile-duration").value) || 0;
  const display = document.getElementById("interval-display");
  const hint    = document.getElementById("profile-interval-hint");
  if (dur > 0) {
    display.textContent = `${formatDuration(start)} – ${formatDuration(start + dur)} (${dur}s)`;
    hint.classList.remove("hidden");
  }
}

document.getElementById("profile-start").addEventListener("input", updateIntervalHint);
document.getElementById("profile-duration").addEventListener("input", updateIntervalHint);

document.getElementById("btn-create-profile").addEventListener("click", async () => {
  const body = {
    name: document.getElementById("profile-name").value.trim(),
    youtube_url: document.getElementById("profile-url").value.trim(),
    start_time: parseFloat(document.getElementById("profile-start").value),
    duration: parseFloat(document.getElementById("profile-duration").value),
  };
  if (!body.name || !body.youtube_url) { alert("Fill in a name and URL."); return; }

  const res = await apiFetch("/api/voice-profiles", "POST", body);
  if (!res) return;

  document.getElementById("profile-progress").classList.remove("hidden");
  trackJob(res.job_id, "profile-progress-text", "profile-progress-fill", () => {
    document.getElementById("profile-name").value = "";
    document.getElementById("profile-url").value = "";
    document.getElementById("profile-video-preview").classList.add("hidden");
    document.getElementById("profile-interval-hint").classList.add("hidden");
    document.getElementById("profile-progress").classList.add("hidden");
    _profileVideoDuration = null;
    loadProfiles();
    loadVoiceProfilesSelect();
  });
});

async function loadProfiles() {
  const profiles = await apiFetch("/api/voice-profiles");
  const list = document.getElementById("profiles-list");
  if (!profiles || profiles.length === 0) {
    list.innerHTML = '<p class="empty">No profiles yet.</p>';
    return;
  }
  list.innerHTML = profiles.map(p => `
    <div class="profile-card">
      <div class="profile-info">
        <strong>${esc(p.name)}</strong>
        <span>${esc(p.channel || "")} &middot; ${p.duration}s sample</span>
      </div>
      <div class="profile-actions">
        <audio controls src="${API}/data/voice_profiles/${p.id}/reference.wav"></audio>
        <button class="btn-danger" onclick="deleteProfile('${p.id}')">Delete</button>
      </div>
    </div>
  `).join("");
}

async function deleteProfile(id) {
  if (!confirm("Delete this voice profile?")) return;
  await apiFetch(`/api/voice-profiles/${id}`, "DELETE");
  loadProfiles();
  loadVoiceProfilesSelect();
}

async function loadVoiceProfilesSelect() {
  const profiles = await apiFetch("/api/voice-profiles");
  const sel = document.getElementById("voice-profile");
  const current = sel.value;
  sel.innerHTML = '<option value="">Select a voice profile</option>';
  (profiles || []).forEach(p => {
    sel.insertAdjacentHTML("beforeend", `<option value="${p.id}">${esc(p.name)}</option>`);
  });
  sel.value = current;
  checkTranslateReady();
}

// ─── Jobs tab ────────────────────────────────────────────────────────────────

let _activeJobId = null;
let _jobPollInterval = null;

function langLabel(srcCode, tgtCode) {
  return `<span class="lang-label"><span class="lang-chip">${esc(srcCode.toUpperCase())}</span><span class="lang-arrow">›</span><span class="lang-chip">${esc(tgtCode.toUpperCase())}</span></span>`;
}

document.getElementById("btn-refresh-jobs").addEventListener("click", () => loadJobs());

async function loadJobs(openJobId) {
  const jobs = await apiFetch("/api/jobs");
  const list = document.getElementById("jobs-list");

  if (!jobs || jobs.length === 0) {
    list.innerHTML = '<p class="empty">No jobs yet.</p>';
    return;
  }

  const sorted = [...jobs].sort((a, b) => (b.created_at || 0) - (a.created_at || 0));
  list.innerHTML = sorted.map(j => {
    const meta = j.metadata || {};
    const src = meta.source_language;
    const tgt = meta.target_language;
    const title = meta.video?.title;
    const version = meta.version ? `<span class="version-badge">${esc(meta.version)}</span>` : "";
    const isTranslation = src && tgt && title;
    const mainLine = isTranslation
      ? `${langLabel(src, tgt)} <span class="job-title">${esc(title)}</span> ${version}`
      : `${esc(j.description)} ${version}`;
    return `
      <div class="job-row" data-job-id="${j.id}" onclick="openJob('${j.id}')">
        <span class="status-badge status-${j.status}">${j.status}</span>
        <div class="job-desc">
          <div class="job-desc-main">${mainLine}</div>
          <div class="job-desc-sub">${esc(j.progress)}</div>
        </div>
        <span class="job-chevron">›</span>
      </div>
    `;
  }).join("");

  const toOpen = openJobId
    || sorted.find(j => j.status === "running")?.id
    || sorted[0]?.id;

  if (toOpen) openJob(toOpen);
}

function openJob(jobId) {
  if (_activeJobId !== jobId) _detailsOpen = false;
  _activeJobId = jobId;

  document.querySelectorAll(".job-row").forEach(r =>
    r.classList.toggle("job-row-active", r.dataset.jobId === jobId));

  renderJobDetail(null);
  refreshJobDetail();
}

function renderJobDetail(job) {
  const detail = document.getElementById("job-detail");
  if (!job) {
    detail.innerHTML = '<p class="empty">Loading...</p>';
    detail.classList.remove("hidden");
    return;
  }

  const meta = job.metadata || {};
  const timing = meta.timing || {};
  const video = meta.video || {};
  const version = meta.version || "";
  const pctMatch = (job.progress || "").match(/\((\d+)%\)/);
  const pct = pctMatch ? parseInt(pctMatch[1]) : (job.status === "done" ? 100 : 0);
  const hasDetails = video.title || timing.total_s != null;

  // First render, or job changed, or hasDetails just became true (details button must appear)
  const hadDetails = detail.dataset.hasDetails === "1";
  if (!detail.dataset.jobId || detail.dataset.jobId !== job.id || (hasDetails && !hadDetails)) {
    detail.dataset.jobId = job.id;
    detail.dataset.hasDetails = hasDetails ? "1" : "0";
    detail.classList.remove("hidden");
    const srcLangCode = meta.source_language;
    const tgtLangCode = meta.target_language;
    const videoTitle = video.title;
    const isTranslationJob = srcLangCode && tgtLangCode && videoTitle;
    const headerTitle = isTranslationJob
      ? `${langLabel(srcLangCode, tgtLangCode)} <span class="detail-title">${esc(videoTitle)}</span> ${version ? `<span class="version-badge">${esc(version)}</span>` : ""}`
      : `<span class="detail-title">${esc(job.description)}</span> ${version ? `<span class="version-badge">${esc(version)}</span>` : ""}`;

    detail.innerHTML = `
      <div class="detail-header">
        <span class="dyn-status status-badge status-${job.status}">${job.status}</span>
        ${headerTitle}
      </div>

      <div class="progress-label">
        <span class="dyn-progress-text">${esc(job.progress || "")}</span>
        <span class="dyn-progress-pct">${pct > 0 ? pct + "%" : ""}</span>
      </div>
      <div class="progress-bar">
        <div class="dyn-progress-fill" style="width:${pct}%; ${job.status === 'error' ? 'background:#c00' : ''}"></div>
      </div>

      <div class="dyn-error">${job.error ? `<pre class="job-error">${esc(job.error)}</pre>` : ""}</div>
      <div class="dyn-result">${job.result?.video_url ? renderResultBlock(job) : ""}</div>

      <div class="detail-footer">
        ${hasDetails
          ? `<button class="btn-ghost" onclick="toggleJobDetails('${job.id}')">Details <span id="details-arrow-${job.id}">${_detailsOpen ? "▴" : "▾"}</span></button>`
          : `<span></span>`}
        <button class="btn-danger" onclick="deleteJob('${job.id}')">Delete</button>
      </div>

      ${hasDetails ? `
        <div id="job-details-${job.id}" class="job-details-panel ${_detailsOpen ? "" : "hidden"}">
          <div class="details-grid-inner">${renderDetailsPanel(meta, job)}</div>
        </div>` : ""}
    `;
    return;
  }

  // Subsequent renders: patch only the dynamic parts
  const q = sel => detail.querySelector(sel);
  const status = q(".dyn-status");
  if (status) { status.textContent = job.status; status.className = `dyn-status status-badge status-${job.status}`; }
  const pt = q(".dyn-progress-text"); if (pt) pt.textContent = job.progress || "";
  const pp = q(".dyn-progress-pct"); if (pp) pp.textContent = pct > 0 ? pct + "%" : "";
  const pf = q(".dyn-progress-fill");
  if (pf) { pf.style.width = pct + "%"; pf.style.background = job.status === "error" ? "#c00" : ""; }
  const er = q(".dyn-error");
  if (er) er.innerHTML = job.error ? `<pre class="job-error">${esc(job.error)}</pre>` : "";
  const re = q(".dyn-result");
  if (re && job.result?.video_url && !re.innerHTML.trim()) {
    re.innerHTML = renderResultBlock(job);
  }

  // Update details panel content (live, without touching open/closed state)
  const panel = document.getElementById(`job-details-${job.id}`);
  if (panel) panel.querySelector(".details-grid-inner").innerHTML = renderDetailsPanel(meta, job);
}

let _detailsOpen = false;

function renderResultBlock(job) {
  const url = job.result.video_url;
  return `<div class="result-block">
    <div class="result-header">
      <button class="btn-ghost" onclick="toggleVideo('${job.id}')">Video <span id="video-arrow-${job.id}">▾</span></button>
      <a href="${API}${url}" download>Download</a>
    </div>
    <div id="video-panel-${job.id}" class="hidden">
      <video controls src="${API}${url}"></video>
    </div>
  </div>`;
}

function toggleVideo(jobId) {
  const panel = document.getElementById(`video-panel-${jobId}`);
  const arrow = document.getElementById(`video-arrow-${jobId}`);
  const hidden = panel.classList.toggle("hidden");
  arrow.textContent = hidden ? "▾" : "▴";
}
let _liveTimerInterval = null;

function startLiveTimers() {
  if (_liveTimerInterval) return;
  _liveTimerInterval = setInterval(() => {
    const now = Date.now() / 1000;
    document.querySelectorAll(".live-timer").forEach(el => {
      el.textContent = fmtElapsed(now - parseFloat(el.dataset.start));
    });
  }, 250);
}

function stopLiveTimers() {
  clearInterval(_liveTimerInterval);
  _liveTimerInterval = null;
}

function toggleJobDetails(jobId) {
  const panel = document.getElementById(`job-details-${jobId}`);
  const arrow = document.getElementById(`details-arrow-${jobId}`);
  _detailsOpen = panel.classList.toggle("hidden") === false;
  arrow.textContent = _detailsOpen ? "▴" : "▾";
}

function renderDetailsPanel(meta, job) {
  const timing = meta.timing || {};
  const video = meta.video || {};
  const profile = meta.voice_profile || {};
  const createdAt = job.created_at
    ? new Date(job.created_at * 1000).toLocaleString("nl-BE")
    : "";

  const srcLang = SUPPORTED_LANGUAGES[meta.source_language] || meta.source_language || "";
  const tgtLang = SUPPORTED_LANGUAGES[meta.target_language] || meta.target_language || "";

  function fmtS(s) {
    if (s == null) return "—";
    if (s >= 60) {
      const m = Math.floor(s / 60);
      const sec = Math.round(s % 60);
      return `${m}m ${sec}s`;
    }
    return `${s}s`;
  }

  // Render a phase row: done = static, started = live timer, not started = hidden
  function phaseRow(label, startKey, doneKey, extra = "") {
    if (timing[doneKey] != null) {
      return `<div class="details-row"><span>${label}</span><span>${fmtS(timing[doneKey])}${extra}</span></div>`;
    }
    if (timing[startKey] != null) {
      const elapsed = Date.now() / 1000 - timing[startKey];
      return `<div class="details-row details-row-active"><span>${label}</span><span><span class="live-timer" data-start="${timing[startKey]}">${fmtElapsed(elapsed)}</span></span></div>`;
    }
    return "";
  }

  const synthDetail = timing.synthesis_avg_s != null
    ? ` &nbsp;<span class="details-sub">avg ${timing.synthesis_avg_s}s &middot; min ${timing.synthesis_min_s}s &middot; max ${timing.synthesis_max_s}s</span>`
    : "";

  const videoSection = video.title ? `
    <div class="details-section">
      <div class="details-section-title">Video</div>
      <div class="details-row"><span>Title</span><span>${esc(video.title)}</span></div>
      ${video.channel ? `<div class="details-row"><span>Channel</span><span>${esc(video.channel)}</span></div>` : ""}
      ${video.duration ? `<div class="details-row"><span>Duration</span><span>${formatDuration(video.duration)}</span></div>` : ""}
      ${video.url ? `<div class="details-row"><span>URL</span><span class="details-url"><a href="${esc(video.url)}" target="_blank">${esc(video.url)}</a></span></div>` : ""}
    </div>
  ` : "";

  const translationSection = (srcLang || tgtLang || profile.name) ? `
    <div class="details-section">
      <div class="details-section-title">Translation</div>
      ${srcLang ? `<div class="details-row"><span>Source</span><span>${esc(srcLang)}</span></div>` : ""}
      ${tgtLang ? `<div class="details-row"><span>Target</span><span>${esc(tgtLang)}</span></div>` : ""}
      ${profile.name ? `<div class="details-row"><span>Voice profile</span><span>${esc(profile.name)}</span></div>` : ""}
      ${meta.segments_count ? `<div class="details-row"><span>Segments</span><span>${meta.segments_count}</span></div>` : ""}
    </div>
  ` : "";

  const hasAnyTiming = timing.download_start != null;
  const sumPhases = [
    timing.download_s, timing.transcribe_s, timing.translate_s,
    timing.synthesis_s, timing.render_audio_s, timing.render_s,
  ].reduce((acc, v) => acc + (v ?? 0), 0);

  const savedS = timing.total_s != null && sumPhases > 0
    ? Math.round((sumPhases - timing.total_s) * 10) / 10
    : null;

  const totalRow = timing.total_s != null
    ? `<div class="details-row details-total"><span>Total</span><span>${fmtS(timing.total_s)}</span></div>`
      + (savedS != null
        ? `<div class="details-row"><span class="details-sub">vs serie</span><span class="details-sub">${savedS >= 0 ? "+" : ""}${fmtS(Math.abs(savedS))} ${savedS >= 0 ? "saved" : "overhead"}</span></div>`
        : "")
    : timing.download_start != null
      ? `<div class="details-row details-total"><span>Total</span><span><span class="live-timer" data-start="${timing.download_start}">${fmtElapsed(Date.now() / 1000 - timing.download_start)}</span></span></div>`
      : "";

  const timingSection = hasAnyTiming ? `
    <div class="details-section">
      <div class="details-section-title">Performance ${meta.version ? `<span class="version-badge">${esc(meta.version)}</span>` : ""}</div>
      ${createdAt ? `<div class="details-row"><span>Started</span><span>${esc(createdAt)}</span></div>` : ""}
      ${phaseRow("Download", "download_start", "download_s")}
      ${phaseRow("Transcribe", "transcribe_start", "transcribe_s")}
      ${phaseRow("Translate", "translate_start", "translate_s")}
      ${phaseRow("Synthesis", "synthesis_start", "synthesis_s", synthDetail)}
      ${phaseRow("Build audio", "render_audio_start", "render_audio_s")}
      ${phaseRow("Render video", "render_start", "render_s")}
      ${totalRow}
    </div>
  ` : "";

  return `<div class="details-grid">${videoSection}${translationSection}${timingSection}</div>`;
}

async function deleteJob(jobId) {
  if (!confirm("Delete this job and all its files?")) return;
  const ok = await apiFetch(`/api/jobs/${jobId}`, "DELETE");
  if (!ok) return;
  clearTimeout(_jobPollInterval);
  _activeJobId = null;
  document.getElementById("job-detail").classList.add("hidden");
  loadJobs();
}

async function refreshJobDetail() {
  if (!_activeJobId) return;
  const job = await apiFetch(`/api/jobs/${_activeJobId}`);
  if (!job) return;

  renderJobDetail(job);

  const row = document.querySelector(`.job-row[data-job-id="${_activeJobId}"] .job-desc-sub`);
  if (row) row.textContent = job.progress;
  const badge = document.querySelector(`.job-row[data-job-id="${_activeJobId}"] .status-badge`);
  if (badge) { badge.textContent = job.status; badge.className = `status-badge status-${job.status}`; }

  clearTimeout(_jobPollInterval);
  if (job.status === "running" || job.status === "pending") {
    _jobPollInterval = setTimeout(refreshJobDetail, 1000);
    startLiveTimers();
  } else {
    stopLiveTimers();
  }
}

// ─── Job progress via WebSocket (used for voice profile creation) ─────────────

function trackJob(jobId, textElId, fillElId, onDone) {
  const ws = new WebSocket(`ws://localhost:8000/ws/jobs/${jobId}`);
  const textEl = document.getElementById(textElId);
  const fillEl = document.getElementById(fillElId);

  ws.onmessage = ({ data }) => {
    const job = JSON.parse(data);
    if (job.ping) return;
    if (textEl) textEl.textContent = job.progress || job.status;

    const pctMatch = (job.progress || "").match(/\((\d+)%\)/);
    if (fillEl) fillEl.style.width = pctMatch ? `${pctMatch[1]}%` : "50%";

    if (job.status === "done") {
      if (fillEl) { fillEl.style.width = "100%"; fillEl.style.animation = "none"; }
      ws.close();
      if (onDone) onDone(job.result);
    } else if (job.status === "error") {
      if (textEl) textEl.textContent = `Error: ${job.error}`;
      if (fillEl) { fillEl.style.background = "#c00"; fillEl.style.animation = "none"; fillEl.style.width = "100%"; }
      ws.close();
    }
  };

  ws.onerror = () => {
    if (textEl) textEl.textContent = "Connection error.";
  };
}

// ─── Utilities ────────────────────────────────────────────────────────────────

async function apiFetch(path, method = "GET", body = null) {
  try {
    const opts = {
      method,
      headers: body ? { "Content-Type": "application/json" } : {},
      body: body ? JSON.stringify(body) : undefined,
    };
    const res = await fetch(`${API}${path}`, opts);
    if (!res.ok) {
      const err = await res.json().catch(() => ({ detail: res.statusText }));
      alert(`API error: ${err.detail || res.statusText}`);
      return null;
    }
    return res.json();
  } catch (e) {
    alert(`Network error: ${e.message}\nIs the backend running on port 8000?`);
    return null;
  }
}

function fmtElapsed(secs) {
  if (secs >= 3600) {
    const h = Math.floor(secs / 3600);
    const m = Math.floor((secs % 3600) / 60);
    const s = Math.floor(secs % 60);
    return `${h}h ${m}m ${s}s`;
  }
  if (secs >= 60) {
    const m = Math.floor(secs / 60);
    const s = Math.floor(secs % 60);
    return `${m}m ${s}s`;
  }
  return `${Math.floor(secs)}s`;
}

function formatDuration(secs) {
  const h = Math.floor(secs / 3600);
  const m = Math.floor((secs % 3600) / 60);
  const s = Math.floor(secs % 60);
  return h
    ? `${h}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`
    : `${m}:${String(s).padStart(2, "0")}`;
}

function esc(str) {
  return String(str ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;");
}

// ─── Init ─────────────────────────────────────────────────────────────────────

(async () => {
  await loadLanguages();
  await loadVoiceProfilesSelect();
})();
