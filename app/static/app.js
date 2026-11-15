"use strict";

/* ════════════════════════════════════════════════════════════
   Utilidades
   ════════════════════════════════════════════════════════════ */
const TOKEN = document.querySelector('meta[name="api-token"]').content;
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
const media = (runId, path) => `/media/${encodeURIComponent(runId)}/${path.split("/").map(encodeURIComponent).join("/")}?t=${encodeURIComponent(TOKEN)}`;

async function api(path, opts = {}) {
  const res = await fetch(path, {
    ...opts,
    headers: { "X-Token": TOKEN, "Content-Type": "application/json", ...(opts.headers || {}) },
    body: opts.body !== undefined ? JSON.stringify(opts.body) : undefined,
  });
  let data = null;
  try { data = await res.json(); } catch { /* sin cuerpo */ }
  if (!res.ok) throw new Error((data && data.detail) || `Error ${res.status}`);
  setConn(true);
  return data;
}

function toast(msg, kind = "") {
  const t = document.createElement("div");
  t.className = `toast ${kind}`;
  t.textContent = msg;
  $("#toasts").appendChild(t);
  setTimeout(() => t.remove(), kind === "err" ? 7000 : 4000);
}

function fmtDur(sec) {
  if (sec == null || isNaN(sec)) return "";
  sec = Math.max(0, Math.round(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return h ? `${h}h ${String(m).padStart(2, "0")}m` : m ? `${m}m ${String(s).padStart(2, "0")}s` : `${s}s`;
}
const fmtTime = (ts) => new Date(ts * 1000).toLocaleTimeString("es", { hour: "2-digit", minute: "2-digit", second: "2-digit" });
const fmtDate = (ts) => new Date(ts * 1000).toLocaleString("es", { day: "2-digit", month: "short", hour: "2-digit", minute: "2-digit" });
const fmtNum = (n) => (n == null ? "—" : Intl.NumberFormat("es", { notation: n >= 10000 ? "compact" : "standard" }).format(n));
const itemLabel = (k) => (k === "long" ? "Video largo" : k.startsWith("short_") ? `Short ${k.split("_")[1]}` : k);
const STATUS_TEXT = { running: "En curso", done: "Completado", failed: "Falló", cancelled: "Cancelado", interrupted: "Interrumpido", idle: "En espera" };

const ICONS = {
  pending: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="3"/></svg>',
  running: '<svg viewBox="0 0 24 24"><path d="M21 12a9 9 0 1 1-6.2-8.6"/></svg>',
  done: '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>',
  failed: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  skipped: '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>',
  cancelled: '<svg viewBox="0 0 24 24"><path d="M5 12h14"/></svg>',
};

function setConn(ok) {
  const c = $("#connState");
  c.classList.toggle("off", !ok);
  c.lastElementChild.textContent = ok ? "Conectado" : "Sin conexión";
}

/* tema */
(function initTheme() {
  let t = "dark";
  try { t = localStorage.getItem("theme") || "dark"; } catch { /* almacenamiento no disponible */ }
  document.documentElement.dataset.theme = t;
  $("#themeBtn").onclick = () => {
    const n = document.documentElement.dataset.theme === "dark" ? "light" : "dark";
    document.documentElement.dataset.theme = n;
    try { localStorage.setItem("theme", n); } catch { /* ignorar */ }
  };
})();

/* ════════════════════════════════════════════════════════════
   Navegación
   ════════════════════════════════════════════════════════════ */
let currentView = "live";
function showView(name) {
  currentView = name;
  $$(".nav-item").forEach((b) => b.classList.toggle("active", b.dataset.view === name));
  $$(".view").forEach((v) => v.classList.toggle("active", v.id === `view-${name}`));
  if (name === "history") loadHistory();
  if (name === "learning") loadLearning();
  if (name === "settings") loadSettings();
  window.scrollTo({ top: 0 });
  history.replaceState(null, "", name === "live" ? location.pathname : `#${name}`);
}
$$(".nav-item").forEach((b) => (b.onclick = () => showView(b.dataset.view)));

/* ════════════════════════════════════════════════════════════
   Estado global (polling ligero)
   ════════════════════════════════════════════════════════════ */
let app = { steps: [], active: null, readiness: [], firstLoad: true };

async function refreshState() {
  try {
    const s = await api("/api/state");
    app.steps = s.steps;
    app.readiness = s.readiness;
    const prevActive = app.active && app.active.run_id;
    app.active = s.active;
    $("#brandNiche").textContent = s.niche;
    $("#navLiveDot").classList.toggle("on", !!s.active);
    $("#legacyBanner").classList.toggle("hidden", !s.legacy_files);
    $("#navCfgBadge").classList.toggle("hidden", !(s.legacy_files || s.readiness.some((r) => r.critical && !r.ok)));
    if (app.firstLoad) {
      $("#optPublish").checked = s.auto_publish;
      app.firstLoad = false;
      if (s.active) attach(s.active.run_id);
      else {
        const runs = await api("/api/runs?limit=1");
        if (runs.length) attach(runs[0].id);
        else renderLive();
      }
    } else if (s.active && s.active.run_id !== prevActive && (!live.pinned || !live.runId)) {
      attach(s.active.run_id);
    }
    renderReadiness();
    renderActions();
  } catch (e) {
    setConn(false);
  }
}

function renderReadiness() {
  const missing = app.readiness.filter((r) => !r.ok);
  const b = $("#readinessBanner");
  if (!missing.length || (live.status === "running")) { b.classList.add("hidden"); return; }
  const crit = missing.some((r) => r.critical);
  b.className = `banner ${crit ? "danger" : "warn"}`;
  b.innerHTML = `<div><b>${crit ? "Falta configuración necesaria para iniciar" : "Configuración recomendada pendiente"}</b>
    <ul>${missing.map((r) => `<li>${esc(r.label)} — <span class="muted">${esc(r.hint)}</span></li>`).join("")}</ul></div>
    <button class="btn ${crit ? "primary" : "ghost"}" onclick="showView('settings')">Ir a configuración</button>`;
}

/* ════════════════════════════════════════════════════════════
   Panel en vivo
   ════════════════════════════════════════════════════════════ */
const live = {
  runId: null, pinned: false, es: null, offset: 0, ended: false,
  status: "idle", title: null, started: null, finished: null, error: null,
  steps: {}, logs: [], filter: "all", items: {}, itemOrder: [], currentItem: null,
  script: null, hook: null, research: null, uploads: [], options: {},
};

function resetLive(runId) {
  if (live.es) live.es.close();
  Object.assign(live, {
    runId, es: null, offset: 0, ended: false, status: "idle", title: null, started: null, finished: null, error: null,
    steps: {}, logs: [], items: {}, itemOrder: [], currentItem: null, script: null, hook: null, research: null, uploads: [], options: {},
  });
  for (const s of app.steps) live.steps[s.id] = { label: s.label, status: "pending", progress: 0, message: "" };
  $("#console").innerHTML = "";
}

async function attach(runId, pinned = false) {
  resetLive(runId);
  live.pinned = pinned;
  try {
    const { run, script, research_top } = await api(`/api/runs/${encodeURIComponent(runId)}`);
    live.status = run.status || "running";
    live.title = run.title;
    live.started = run.started;
    live.finished = run.finished;
    live.error = run.error;
    live.options = run.options || {};
    if (script) setScript(script, run.hook_style);
    if (research_top && research_top.length) live.research = research_top;
  } catch (e) { /* aún no existe run.json: lo traerá el stream */ }
  renderLive();
  openStream();
}

function openStream() {
  if (!live.runId || live.ended) return;
  const runId = live.runId;
  const es = new EventSource(`/api/runs/${encodeURIComponent(runId)}/stream?offset=${live.offset}&t=${encodeURIComponent(TOKEN)}`);
  live.es = es;
  es.onmessage = (e) => {
    if (live.runId !== runId) return;
    if (e.lastEventId) live.offset = +e.lastEventId;
    try { handleEvent(JSON.parse(e.data)); } catch (err) { console.error(err); }
  };
  es.addEventListener("end", async (e) => {
    es.close();
    if (live.runId !== runId) return;
    live.ended = true;
    try {
      const { run } = await api(`/api/runs/${encodeURIComponent(runId)}`);
      live.status = run.status; live.finished = run.finished; live.error = run.error;
      for (const [k, v] of Object.entries(run.steps || {})) live.steps[k] = { ...live.steps[k], ...v };
    } catch { /* ignorar */ }
    scheduleRender();
    refreshState();
  });
  es.onerror = () => {
    es.close();
    setConn(false);
    if (live.runId === runId && !live.ended) setTimeout(() => live.runId === runId && openStream(), 2000);
  };
}

function handleEvent(ev) {
  setConn(true);
  switch (ev.type) {
    case "log":
      live.logs.push(ev);
      appendLog(ev);
      break;
    case "step":
      live.steps[ev.step] = { ...live.steps[ev.step], ...ev };
      if (ev.status === "running" && live.status !== "running" && !live.ended) live.status = "running";
      if (!live.started) live.started = ev.started || ev.ts;
      break;
    case "artifact":
      onArtifact(ev);
      break;
    case "upload":
      live.uploads.push(ev);
      break;
    case "status":
      live.status = ev.status;
      live.error = ev.error;
      live.finished = ev.ts;
      break;
  }
  scheduleRender();
}

function ensureItem(key) {
  if (!live.items[key]) {
    live.items[key] = { shots: [], video: null, thumb: null, duration: null, size: null, title: null, portrait: key !== "long" };
    live.itemOrder.push(key);
    live.itemOrder.sort((a, b) => (a === "long" ? -1 : b === "long" ? 1 : a.localeCompare(b, "es", { numeric: true })));
    if (!live.currentItem) live.currentItem = key;
  }
  return live.items[key];
}

function setScript(script, hook) {
  live.script = script;
  live.hook = hook || live.hook;
  if (script.long_video && script.long_video.scenes && script.long_video.scenes.length > 1) ensureItem("long").title = script.long_video.title;
  (script.shorts || []).forEach((s, i) => (ensureItem(`short_${i + 1}`).title = s.title));
}

function onArtifact(ev) {
  switch (ev.kind) {
    case "research": live.research = ev.top; break;
    case "script":
      setScript(ev.data, ev.hook_style);
      if (!live.title) live.title = ev.data.long_video?.title || ev.data.shorts?.[0]?.title;
      break;
    case "audio": ensureItem(ev.item).duration = ev.duration; break;
    case "shot": ensureItem(ev.item).shots.push({ path: ev.path, src: ev.kind_src }); break;
    case "thumb": ensureItem(ev.item).thumb = ev.path; break;
    case "thumbnail": ensureItem(ev.item).thumbnail = ev.path; break;
    case "review": ensureItem(ev.item).review = ev.data; break;
    case "video": {
      const it = ensureItem(ev.item);
      Object.assign(it, { video: ev.path, duration: ev.duration, size: ev.size_mb, title: ev.title || it.title });
      break;
    }
  }
}

/* render con rAF para no saturar durante la reproducción del historial */
let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderLive(); });
}

function renderLive() {
  renderHeader();
  renderSteps();
  renderProduction();
  renderScript();
  renderResearch();
  renderUploads();
  renderActions();
  renderReadiness();
  $("#logCount").textContent = live.logs.length ? `${live.logs.length} eventos` : "";
  const c = $("#console");
  if (!c.children.length) c.innerHTML = '<div class="console-empty">La actividad aparecerá aquí en tiempo real.</div>';
}

function renderHeader() {
  const st = live.runId ? live.status : "idle";
  $("#liveTitle").textContent = live.title || (live.runId ? (st === "running" ? "Generando contenido…" : "Run sin título") : "Listo para crear");
  const pill = $("#liveStatus");
  pill.className = `pill ${st}`;
  pill.textContent = STATUS_TEXT[st] || st;
  $("#liveRunId").textContent = live.runId ? `Run ${live.runId}` : "";
  const isActive = app.active && app.active.run_id === live.runId;
  $("#liveEyebrow").textContent = isActive ? "Panel en vivo · en curso" : live.runId ? "Panel en vivo · revisando run" : "Panel en vivo";
  updateElapsed();
  if (live.error && st !== "running") {
    $("#liveRunId").textContent += ` · ${live.error.slice(0, 140)}`;
  }
}

function updateElapsed() {
  if (!live.started) { $("#liveElapsed").textContent = ""; return; }
  const end = live.status === "running" ? Date.now() / 1000 : (live.finished || Date.now() / 1000);
  $("#liveElapsed").textContent = `⏱ ${fmtDur(end - live.started)}`;
}
setInterval(() => { if (live.status === "running") { updateElapsed(); renderStepTimes(); } }, 1000);

function renderSteps() {
  const ol = $("#steps");
  if (ol.children.length !== app.steps.length) {
    ol.innerHTML = app.steps.map((s) => `<li class="step pending" data-step="${s.id}">
      <div class="step-icon"></div>
      <div><div class="step-top"><span class="step-name">${esc(s.label)}</span><span class="step-time"></span></div>
      <div class="step-msg"></div><div class="step-bar"><div></div></div></div></li>`).join("");
  }
  let total = 0, sum = 0;
  for (const s of app.steps) {
    const d = live.steps[s.id] || { status: "pending", progress: 0 };
    const li = ol.querySelector(`[data-step="${s.id}"]`);
    if (li.dataset.status !== d.status) {
      li.className = `step ${d.status}`;
      li.dataset.status = d.status;
      li.querySelector(".step-icon").innerHTML = ICONS[d.status] || ICONS.pending;
    }
    li.querySelector(".step-msg").textContent = d.message || (d.status === "skipped" ? "Omitido" : "");
    li.querySelector(".step-bar > div").style.width = `${Math.round((d.progress || 0) * 100)}%`;
    total += 1;
    sum += ["done", "skipped"].includes(d.status) ? 1 : d.status === "running" ? (d.progress || 0) : 0;
  }
  renderStepTimes();
  const pct = live.runId ? Math.round((sum / Math.max(total, 1)) * 100) : 0;
  $("#overallBar").style.width = `${pct}%`;
  $("#overallPct").textContent = live.runId ? `${pct}%` : "";
}

function renderStepTimes() {
  for (const s of app.steps) {
    const d = live.steps[s.id];
    const el = $(`#steps [data-step="${s.id}"] .step-time`);
    if (!el || !d) continue;
    if (d.started && (d.finished || d.status === "running")) {
      el.textContent = fmtDur((d.finished || Date.now() / 1000) - d.started);
    } else el.textContent = "";
  }
}

/* consola */
function logMatches(ev) {
  return live.filter === "all" || (live.filter === "warn" ? ["warn", "error"].includes(ev.level) : ev.level === "error");
}
function appendLog(ev) {
  if (!logMatches(ev)) return;
  const c = $("#console");
  const empty = c.querySelector(".console-empty");
  if (empty) empty.remove();
  const stepLabel = ev.step ? (app.steps.find((s) => s.id === ev.step)?.label || ev.step).split(" ")[0] : "";
  const row = document.createElement("div");
  row.className = `log ${ev.level}`;
  row.innerHTML = `<span class="t">${fmtTime(ev.ts)}</span><span class="s" title="${esc(stepLabel)}">${esc(stepLabel)}</span><span class="m"></span>`;
  row.lastElementChild.textContent = ev.msg;
  c.appendChild(row);
  while (c.children.length > 1500) c.firstChild.remove();
  if ($("#autoScroll").checked) c.scrollTop = c.scrollHeight;
}
function rerenderLogs() {
  $("#console").innerHTML = "";
  live.logs.forEach(appendLog);
  if (!$("#console").children.length) $("#console").innerHTML = '<div class="console-empty">Sin eventos para este filtro.</div>';
}
$$("#logFilter button").forEach((b) => (b.onclick = () => {
  $$("#logFilter button").forEach((x) => x.classList.toggle("active", x === b));
  live.filter = b.dataset.level;
  rerenderLogs();
}));

/* producción */
function renderProduction() {
  const tabs = $("#itemTabs");
  const box = $("#production");
  if (!live.itemOrder.length) {
    tabs.innerHTML = "";
    if (!box.querySelector(".empty")) {
      box.innerHTML = `<div class="empty"><svg viewBox="0 0 24 24"><rect x="2" y="5" width="15" height="14" rx="2"/><path d="M17 10l5-3v10l-5-3"/></svg>
        <p>Cuando inicies un run verás aquí el guion, cada toma a medida que se prepara y los videos terminados.</p></div>`;
    }
    return;
  }
  tabs.innerHTML = live.itemOrder.map((k) => `<button class="tab ${k === live.currentItem ? "active" : ""}" data-item="${k}">
    ${live.items[k].video ? '<span class="ok"></span>' : ""}${esc(itemLabel(k))}</button>`).join("");
  $$(".tab", tabs).forEach((t) => (t.onclick = () => { live.currentItem = t.dataset.item; renderProduction(); }));

  const key = live.currentItem;
  const it = live.items[key];
  let view = box.querySelector(".item-view");
  if (!view || view.dataset.item !== key) {
    box.innerHTML = `<div class="item-view" data-item="${key}"><div class="player-slot"></div><div class="item-info"></div></div>`;
    view = box.querySelector(".item-view");
  }
  // reproductor: solo se reemplaza si cambia la fuente (no interrumpe la reproducción)
  const slot = view.querySelector(".player-slot");
  const lastShot = it.shots[it.shots.length - 1];
  const want = it.video ? `v:${it.video}` : lastShot ? `i:${lastShot.path}` : "none";
  if (slot.dataset.src !== want) {
    slot.dataset.src = want;
    const cls = `player ${it.portrait ? "portrait" : "landscape"}`;
    if (it.video) {
      slot.innerHTML = `<div class="${cls}"><video controls preload="metadata" playsinline ${it.thumb ? `poster="${media(live.runId, it.thumb)}"` : ""} src="${media(live.runId, it.video)}"></video></div>`;
    } else if (lastShot) {
      slot.innerHTML = `<div class="${cls}"><img src="${media(live.runId, lastShot.path)}" alt=""><div class="placeholder" style="background:rgba(0,0,0,.45);color:#fff">Preparando tomas…</div></div>`;
    } else {
      slot.innerHTML = `<div class="${cls}"><div class="placeholder">${live.status === "running" ? "Esperando narración y material visual…" : "Sin video"}</div></div>`;
    }
  }
  const info = view.querySelector(".item-info");
  const shotsHtml = it.shots.map((s) => `<img class="${s.src === "color" ? "src-color" : ""}" title="${s.src === "color" ? "Fondo de respaldo (sin material)" : s.src === "image" ? "Foto con movimiento" : "Clip de video"}" src="${media(live.runId, s.path)}" loading="lazy" alt="">`).join("");
  const rv = it.review;
  const reviewHtml = rv ? `<div class="review ${rv.ok ? "ok" : "bad"}">
      <div class="review-head"><b>Revisión con IA: ${rv.score}/10 ${rv.ok ? "· aprobado" : "· no aprobado"}</b>
        <span class="muted small">${rv.audio ? "imagen y audio" : "solo imagen"}</span></div>
      <div class="small">${esc(rv.summary || "")}</div>
      ${rv.issues?.length ? `<ul class="small">${rv.issues.map((i) => `<li><span class="sev ${esc(i.severity)}">${esc(i.severity)}</span> <b>${esc(i.at)}</b> ${esc(i.problem)}</li>`).join("")}</ul>` : ""}
      ${rv.ok ? "" : `<div class="small muted">La publicación automática se salta este video. Si te parece bien, publícalo con el botón «Publicar».</div>`}
    </div>` : "";
  const thumbHtml = it.thumbnail ? `<div class="muted small" style="margin:4px 0 6px">Miniatura para YouTube:</div>
      <a href="${media(live.runId, it.thumbnail)}" target="_blank" rel="noopener"><img class="yt-thumb" src="${media(live.runId, it.thumbnail)}" alt="Miniatura"></a>` : "";
  const sig = `${it.title}|${it.duration}|${it.size}|${it.shots.length}|${it.video}|${rv ? rv.score : ""}|${it.thumbnail || ""}`;
  if (info.dataset.sig !== sig) {
    info.dataset.sig = sig;
    info.innerHTML = `<h3>${esc(it.title || itemLabel(key))}</h3>
      <div class="facts">
        <span>Formato <b>${it.portrait ? "Vertical 9:16" : "Horizontal 16:9"}</b></span>
        ${it.duration ? `<span>Duración <b>${fmtDur(it.duration)}</b></span>` : ""}
        <span>Tomas <b>${it.shots.length}</b></span>
        ${it.size ? `<span>Tamaño <b>${it.size} MB</b></span>` : ""}
      </div>
      ${it.video ? `<div style="display:flex;gap:8px;margin-bottom:14px;flex-wrap:wrap">
        <button class="btn sm" data-act="full">Ver en grande</button>
        <a class="btn sm" href="${media(live.runId, it.video)}" download="${esc(key)}.mp4">Descargar MP4</a></div>` : ""}
      ${reviewHtml}${thumbHtml}
      <div class="muted small" style="margin-bottom:8px">${it.shots.length ? "Tomas preparadas (en orden):" : "Las tomas aparecerán aquí a medida que se preparan."}</div>
      <div class="filmstrip ${it.portrait ? "portrait" : ""}">${shotsHtml}</div>`;
    const full = info.querySelector('[data-act="full"]');
    if (full) full.onclick = () => {
      const v = $("#dialogVideo");
      v.src = media(live.runId, it.video);
      $("#videoDialog").showModal();
      v.play().catch(() => {});
    };
  }
}
$("#videoDialog").addEventListener("close", () => $("#dialogVideo").pause());

function renderScript() {
  const box = $("#scriptBox");
  $("#hookChip").textContent = live.hook ? `Gancho: ${live.hook.replace("_", " ")}` : "";
  const s = live.script;
  if (!s) { box.className = "script-box muted"; box.textContent = live.runId ? "El guion aparecerá cuando la IA termine de escribirlo." : "Sin guion todavía."; return; }
  const sig = JSON.stringify(s).length;
  if (box.dataset.sig == sig) return;
  box.dataset.sig = sig;
  box.className = "script-box";
  const plan = (p, label, open) => `<details class="script-section" ${open ? "open" : ""}><summary>${esc(label)} — ${esc(p.title)}</summary>
    <div class="muted small" style="margin:2px 0 6px">${esc(p.description)}</div>
    <div class="small" style="margin-bottom:6px;color:var(--accent-2)">${esc((p.hashtags || []).join(" "))}</div>
    ${p.scenes.map((sc, i) => `<div class="scene"><span class="scene-n">${i + 1}</span><div><p>${esc(sc.narration)}</p><div class="q">🎬 ${esc(sc.visual_query)}</div>${sc.animation ? `<div class="q anim-q">✨ ${esc(sc.animation.type)}: ${esc(sc.animation.type === "dato" ? `${sc.animation.value} ${sc.animation.label}` : sc.animation.type === "lista" ? [sc.animation.headline, ...(sc.animation.items || [])].filter(Boolean).join(" · ") : sc.animation.headline)}</div>` : ""}</div></div>`).join("")}
    </details>`;
  const hasLong = s.long_video && s.long_video.scenes.length > 1;
  box.innerHTML = `<div class="script-title">${esc(s.topic)}</div><div class="muted small" style="margin-bottom:12px">${esc(s.angle)}</div>
    ${hasLong ? plan(s.long_video, "Video largo", true) : ""}
    ${(s.shorts || []).map((p, i) => plan(p, `Short ${i + 1}`, !hasLong && i === 0)).join("")}`;
}

function renderResearch() {
  const box = $("#researchBox");
  const r = live.research;
  if (!r || !r.length) { box.className = "muted"; box.textContent = live.steps.research?.status === "skipped" ? "Investigación omitida (falta la YouTube API key o falló la consulta)." : "Sin datos todavía."; return; }
  box.className = "";
  box.innerHTML = r.map((v) => `<div class="trend"><a class="tt" href="https://youtu.be/${encodeURIComponent(v.video_id)}" target="_blank" rel="noopener" title="${esc(v.title)}">${esc(v.title)}</a>
    <span class="tv">${fmtNum(Math.round(v.views_per_day))}/día · ${(v.engagement * 100).toFixed(1)}%</span></div>`).join("");
}

function renderUploads() {
  const box = $("#uploadsBox");
  if (!live.uploads.length) {
    box.className = "muted";
    box.textContent = live.steps.publish?.status === "skipped" ? (live.steps.publish.message || "Publicación omitida.") : "Nada publicado en este run.";
    return;
  }
  box.className = "";
  box.innerHTML = live.uploads.map((u) => `<div class="upload"><span class="platform ${u.platform}">${esc(u.platform)}</span>
    <div class="u-main"><div>${esc(itemLabel(u.item))}${u.privacy ? ` <span class="muted small">· ${esc(u.privacy)}</span>` : ""}</div>
    ${u.error ? `<div class="u-err">${esc(u.error)}</div>` : ""}${u.note ? `<div class="u-note">${esc(u.note)}</div>` : ""}</div>
    ${u.url ? `<a href="${esc(u.url)}" target="_blank" rel="noopener" class="btn sm">Abrir</a>` : ""}</div>`).join("");
}

function renderActions() {
  const activeId = app.active && app.active.run_id;
  const viewingActive = activeId && activeId === live.runId;
  const busy = !!activeId;
  const critMissing = app.readiness.some((r) => r.critical && !r.ok);
  const btnStart = $("#btnStart");
  btnStart.classList.toggle("hidden", busy);
  btnStart.disabled = critMissing;
  btnStart.title = critMissing ? "Completa la configuración necesaria primero" : "";
  $("#btnCancel").classList.toggle("hidden", !viewingActive);
  $("#btnBackToActive").classList.toggle("hidden", !(busy && !viewingActive));
  const hasVideos = Object.values(live.items).some((i) => i.video);
  const canPublish = !busy && live.runId && hasVideos && ["done", "failed", "interrupted", "cancelled"].includes(live.status);
  const published = live.uploads.some((u) => u.platform_id);
  const canResume = !busy && live.runId && ["failed", "cancelled", "interrupted"].includes(live.status)
    && live.options?.mode !== "metrics";
  $("#btnResume").classList.toggle("hidden", !canResume);
  const btnPub = $("#btnPublish");
  btnPub.classList.toggle("hidden", !canPublish);
  btnPub.lastChild.textContent = published ? "Publicar pendientes" : "Publicar";
}

$("#btnStart").onclick = async () => {
  const btn = $("#btnStart");
  btn.disabled = true;
  try {
    const { id } = await api("/api/runs", { method: "POST", body: { publish: $("#optPublish").checked } });
    toast("Run iniciado", "ok");
    app.active = { run_id: id };
    await attach(id, true);
    refreshState();
  } catch (e) { toast(e.message, "err"); }
  finally { btn.disabled = false; }
};
$("#btnCancel").onclick = async () => {
  if (!confirm("¿Cancelar el run en curso? Se detendrá inmediatamente.")) return;
  try { await api(`/api/runs/${encodeURIComponent(live.runId)}/cancel`, { method: "POST" }); toast("Run cancelado", "warn"); refreshState(); }
  catch (e) { toast(e.message, "err"); }
};
$("#btnPublish").onclick = () => publishRun(live.runId);
$("#btnResume").onclick = async () => {
  const id = live.runId;
  try {
    await api(`/api/runs/${encodeURIComponent(id)}/resume`, { method: "POST" });
    toast("Reintentando desde el paso que falló", "ok");
    app.active = { run_id: id };
    await attach(id, true);
    refreshState();
  } catch (e) { toast(e.message, "err"); }
};
$("#btnBackToActive").onclick = () => app.active && attach(app.active.run_id);

async function publishRun(runId) {
  if (!confirm("¿Publicar los videos de este run en las plataformas activas?")) return;
  try {
    await api(`/api/runs/${encodeURIComponent(runId)}/publish`, { method: "POST" });
    toast("Publicación iniciada", "ok");
    showView("live");
    app.active = { run_id: runId };
    if (live.runId === runId) {
      live.ended = false;
      live.status = "running";
      live.steps.publish = { ...live.steps.publish, status: "running", progress: 0, message: "Iniciando…" };
      renderLive();
      openStream();
    } else await attach(runId, true);
    refreshState();
  } catch (e) { toast(e.message, "err"); }
}

/* ════════════════════════════════════════════════════════════
   Historial
   ════════════════════════════════════════════════════════════ */
async function loadHistory() {
  const grid = $("#historyGrid");
  try {
    const runs = await api("/api/runs");
    if (!runs.length) { grid.innerHTML = '<div class="card muted">Todavía no hay runs. Inicia el primero desde el panel en vivo.</div>'; return; }
    grid.innerHTML = runs.map((r) => {
      const plats = [...new Set(r.uploads.map((u) => u.platform))];
      const items = Object.keys(r.items);
      const dur = r.finished && r.started ? fmtDur(r.finished - r.started) : "";
      return `<div class="card run-card" data-id="${esc(r.id)}">
        <div class="run-thumb">${r.thumb ? `<img src="${media(r.id, r.thumb)}" alt="" loading="lazy">` : '<svg viewBox="0 0 24 24" style="width:30px;height:30px"><rect x="2" y="5" width="15" height="14" rx="2"/><path d="M17 10l5-3v10l-5-3"/></svg>'}</div>
        <div class="run-body">
          <div class="run-meta"><span class="pill ${r.status}">${STATUS_TEXT[r.status] || r.status}</span><span>${r.started ? fmtDate(r.started) : esc(r.id)}</span></div>
          <div class="run-title">${esc(r.title || r.topic || (r.options.mode === "metrics" ? "Actualización de métricas" : "Sin título"))}</div>
          <div class="run-meta"><span>${items.length ? `${items.length} video${items.length > 1 ? "s" : ""}` : ""}${dur ? ` · ${dur}` : ""}</span>
            <span class="badges">${plats.map((p) => `<span class="platform ${p}">${p}</span>`).join("")}${r.upload_errors ? `<span class="platform" style="background:var(--err-soft);color:var(--err)">${r.upload_errors} error</span>` : ""}</span></div>
          <div class="run-actions">
            <button class="btn sm" data-act="open">Abrir</button>
            ${Object.values(r.items).some((i) => i.video) && !app.active ? `<button class="btn sm secondary" data-act="publish">Publicar</button>` : ""}
            <button class="btn sm ghost" data-act="delete" style="margin-left:auto">Borrar</button>
          </div>
        </div></div>`;
    }).join("");
    $$(".run-card", grid).forEach((card) => {
      const id = card.dataset.id;
      card.onclick = (e) => {
        const act = e.target.closest("[data-act]")?.dataset.act;
        if (act === "delete") { e.stopPropagation(); deleteRun(id); return; }
        if (act === "publish") { e.stopPropagation(); publishRun(id); return; }
        showView("live");
        attach(id, true);
      };
    });
  } catch (e) { grid.innerHTML = `<div class="card">${esc(e.message)}</div>`; }
}
$("#btnRefreshHistory").onclick = loadHistory;

async function deleteRun(id) {
  if (!confirm(`¿Borrar el run ${id} y todos sus archivos (videos incluidos)? No se puede deshacer. Lo ya publicado no se ve afectado.`)) return;
  try {
    await api(`/api/runs/${encodeURIComponent(id)}`, { method: "DELETE" });
    toast("Run borrado", "ok");
    if (live.runId === id) { resetLive(null); renderLive(); }
    loadHistory();
  } catch (e) { toast(e.message, "err"); }
}

/* ════════════════════════════════════════════════════════════
   Aprendizaje
   ════════════════════════════════════════════════════════════ */
async function loadLearning() {
  try {
    const d = await api("/api/learning");
    const st = d.learning.styles || {};
    $("#learnSamples").textContent = `${d.learning.samples || 0} publicaciones con métricas maduras`;
    const means = Object.values(st).map((s) => Math.abs(s.mean));
    const scale = Math.max(0.5, ...means);
    $("#styleBars").innerHTML = Object.entries(d.styles).map(([k, desc]) => {
      const s = st[k];
      let bar = "";
      if (s) {
        const w = (Math.abs(s.mean) / scale) * 50;
        const left = s.mean >= 0 ? 50 : 50 - w;
        bar = `<div style="left:${left}%;width:${Math.max(w, 1)}%;background:${s.mean >= 0 ? "var(--ok)" : "var(--err)"}"></div>`;
      }
      return `<div title="${esc(desc)}"><div class="sbar-top"><span>${esc(k.replace("_", " "))}</span>
        <span>${s ? `${s.mean >= 0 ? "+" : ""}${s.mean.toFixed(2)} · n=${s.n}` : "sin datos"}</span></div>
        <div class="sbar"><span class="mid"></span>${bar}</div></div>`;
    }).join("");
    const pubs = d.publications;
    $("#pubTable").innerHTML = pubs.length ? `<thead><tr><th>Fecha</th><th>Plataforma</th><th>Título</th><th>Gancho</th><th>Vistas</th><th>Likes</th><th>Coment.</th><th>Edad</th><th></th></tr></thead>
      <tbody>${pubs.map((p) => `<tr><td>${fmtDate(p.published_at)}</td><td><span class="platform ${p.platform}">${p.platform}</span></td>
        <td class="wrap">${esc(p.title)}</td><td>${esc((p.hook_style || "").replace("_", " "))}</td>
        <td class="num">${fmtNum(p.views)}</td><td class="num">${fmtNum(p.likes)}</td><td class="num">${fmtNum(p.comments)}</td>
        <td class="num">${p.age_hours != null ? `${Math.round(p.age_hours)} h` : "—"}</td>
        <td>${p.url ? `<a href="${esc(p.url)}" target="_blank" rel="noopener">Abrir</a>` : ""}</td></tr>`).join("")}</tbody>`
      : '<tbody><tr><td class="muted">Aún no hay publicaciones registradas.</td></tr></tbody>';
  } catch (e) { toast(e.message, "err"); }
}
$("#btnMetrics").onclick = async () => {
  try {
    const { id } = await api("/api/metrics", { method: "POST" });
    toast("Actualizando métricas…", "ok");
    showView("live");
    await attach(id, true);
    refreshState();
  } catch (e) { toast(e.message, "err"); }
};

/* ════════════════════════════════════════════════════════════
   Configuración
   ════════════════════════════════════════════════════════════ */
let cfg = { loaded: null, draft: null, secrets: {}, meta: {}, voices: [], redirect: "", musicFiles: [], musicDir: "" };
const TESTABLE = { gemini_api_key: "gemini", anthropic_api_key: "anthropic", pixabay_api_key: "pixabay", pexels_api_key: "pexels", youtube_api_key: "youtube_api", facebook_page_token: "facebook" };

const get = (o, p) => p.split(".").reduce((a, k) => (a == null ? a : a[k]), o);
function set(o, p, v) { const ks = p.split("."); let a = o; ks.slice(0, -1).forEach((k) => (a = a[k])); a[ks.at(-1)] = v; }

async function loadSettings() {
  try {
    const d = await api("/api/settings");
    cfg.loaded = d.settings;
    cfg.draft = structuredClone(d.settings);
    cfg.secrets = d.secrets;
    cfg.meta = d.secret_meta;
    cfg.redirect = d.redirect_uri;
    cfg.musicFiles = d.music_files;
    cfg.musicDir = d.music_dir;
    cfg.geminiVoices = d.gemini_voices || ["Puck"];
    cfg.motion = d.motion || { ok: false, msg: "" };
    renderSettings();
    if (!cfg.voices.length) api("/api/voices").then((v) => { cfg.voices = v; renderVoiceSelect(); }).catch(() => {});
    loadConnections();
    loadSchedule();
  } catch (e) { toast(e.message, "err"); }
}

function field(path, label, type = "text", opts = {}) {
  const v = get(cfg.draft, path);
  const id = `f-${path.replace(/\./g, "-")}`;
  let input;
  if (type === "select") {
    input = `<select id="${id}" data-path="${path}">${opts.options.map(([val, txt]) => `<option value="${esc(val)}" ${String(v) === String(val) ? "selected" : ""}>${esc(txt)}</option>`).join("")}</select>`;
  } else if (type === "textarea") {
    input = `<textarea id="${id}" data-path="${path}" rows="3" style="font-family:inherit;font-size:14px">${esc(v)}</textarea>`;
  } else if (type === "color") {
    input = `<input type="color" id="${id}" data-path="${path}" value="${esc(v)}" style="height:40px;padding:4px;width:90px">`;
  } else if (type === "number") {
    input = `<input type="number" id="${id}" data-path="${path}" data-num="1" value="${esc(v)}" ${opts.min != null ? `min="${opts.min}"` : ""} ${opts.max != null ? `max="${opts.max}"` : ""} step="${opts.step || 1}">`;
  } else {
    input = `<input type="text" id="${id}" data-path="${path}" value="${esc(v)}" placeholder="${esc(opts.placeholder || "")}">`;
  }
  return `<div class="field ${opts.full ? "full" : ""}"><label for="${id}">${esc(label)}</label>${input}${opts.help ? `<span class="help">${opts.help}</span>` : ""}</div>`;
}
function toggle(path, title, desc) {
  return `<div class="toggle-row"><div class="tr-text"><b>${esc(title)}</b>${desc ? `<span>${desc}</span>` : ""}</div>
    <label class="switch"><input type="checkbox" data-path="${path}" ${get(cfg.draft, path) ? "checked" : ""}><span class="track"></span></label></div>`;
}
function radioCards(path, options) {
  const v = get(cfg.draft, path);
  return `<div class="radio-cards">${options.map(([val, title, desc]) => `<label class="radio-card ${v === val ? "on" : ""}">
    <input type="radio" name="${path}" data-path="${path}" value="${esc(val)}" ${v === val ? "checked" : ""}><div><b>${esc(title)}</b><span>${desc}</span></div></label>`).join("")}</div>`;
}

// listas que muestran u ocultan otras opciones al cambiar
const RERENDER = ["publish.youtube_method", "publish.tiktok_method", "video.ai_select"];

function renderSettings() {
  const d = cfg.draft;
  const body = $("#settingsBody");
  body.innerHTML = `
  <div class="card" id="s-content">
    <div class="card-head"><h2>Contenido</h2></div>
    <p class="card-desc">Sobre qué crea el agente y para quién.</p>
    <div class="form-grid">
      ${field("content.niche", "Nicho / temática")}
      ${field("content.audience", "Audiencia")}
      ${field("content.language", "Idioma", "select", { options: [["es", "Español"], ["en", "Inglés"], ["pt", "Portugués"]] })}
      ${field("content.region_code", "Región de tendencias", "text", { placeholder: "MX, CO, ES… (vacío = global)" })}
      ${field("content.research_days", "Analizar videos de los últimos (días)", "number", { min: 3, max: 180 })}
      ${field("content.extra_instructions", "Instrucciones adicionales para el guion", "textarea", { full: true, help: "Ej.: «Tono cercano, recetas de menos de 20 minutos, sin ingredientes caros»." })}
    </div>
  </div>

  <div class="card" id="s-ai">
    <div class="card-head"><h2>Inteligencia artificial (guion)</h2></div>
    <p class="card-desc">La IA escribe los guiones (no genera video). La API de Claude se factura aparte de la suscripción Pro de claude.ai; Gemini tiene un plan gratuito sin tarjeta.</p>
    ${radioCards("llm.provider", [
      ["claude", "Claude API (recomendado)", "Mejor redacción y gancho. Unos centavos de dólar por guion."],
      ["gemini", "Gemini API (gratis)", "En la nube, sin instalar nada. Plan gratuito con pocas solicitudes diarias; Google puede usar los datos para mejorar sus productos."],
      ["ollama", "Ollama local (gratis)", "Corre en tu equipo. Más lento y de menor calidad en CPU. Requiere instalar Ollama."],
    ])}
    <div class="form-grid" style="margin-top:16px">
      ${d.llm.provider === "gemini" ? `
        ${field("llm.gemini_model", "Modelo de Gemini", "select", { options: [["gemini-4-hydrogen", "Gemini 4 Hydrogen (el mejor gratis)"], ["gemini-3.8-flash", "Gemini 3.8 Flash"], ["gemini-3.6-flash", "Gemini 3.6 Flash"], ["gemini-3.5-flash-lite", "Gemini 3.5 Flash-Lite (más cuota)"]], help: "Si se agota la cuota diaria de un modelo, se prueba automáticamente el siguiente." })}
        <div class="field full"><details class="howto"><summary>¿Cómo obtengo la clave gratis?</summary><ol>
          <li>Entra a <a href="https://aistudio.google.com/apikey" target="_blank" rel="noopener">aistudio.google.com/apikey</a> con tu cuenta de Google.</li>
          <li>Pulsa <b>Create API key</b> (no pide tarjeta).</li>
          <li>Pégala en Credenciales → «Gemini API key» y pulsa <b>Probar</b>.</li></ol>
          <p>La misma clave sirve para la selección inteligente de clips. En el plan gratuito Google puede usar el contenido enviado para mejorar sus productos: no envíes información privada.</p></details></div>`
      : d.llm.provider === "claude" ? `
        ${field("llm.claude_model", "Modelo de Claude", "select", { options: [["claude-opus-5-5", "Claude Opus 5.5 (máxima calidad)"], ["claude-sonnet-5-5", "Claude Sonnet 5.5 (equilibrado)"], ["claude-haiku-5-5", "Claude Haiku 5.5 (económico)"]] })}
        ${field("llm.claude_effort", "Esfuerzo de razonamiento", "select", { options: [["low", "Bajo (más rápido)"], ["medium", "Medio"], ["high", "Alto (mejor calidad)"]] })}`
      : `
        ${field("llm.ollama_url", "URL de Ollama")}
        ${field("llm.ollama_model", "Modelo de Ollama", "text", { help: "Recomendado en tu equipo: <code>qwen2.5:7b</code> o <code>qwen2.5:3b</code> (más rápido)." })}
        <div class="field"><label>&nbsp;</label><button class="btn sm" id="btnTestOllama" type="button">Probar Ollama</button><span class="help" id="ollamaMsg"></span></div>
        <div class="field full"><details class="howto"><summary>¿Cómo instalo Ollama?</summary><ol>
          <li>Descárgalo de <a href="https://ollama.com/download" target="_blank" rel="noopener">ollama.com/download</a> e instálalo (queda en ejecución junto al reloj).</li>
          <li>Abre una terminal (PowerShell) y ejecuta <code>ollama pull ${esc(d.llm.ollama_model)}</code> (descarga unos GB, una sola vez).</li>
          <li>Pulsa <b>Probar Ollama</b>.</li></ol>
          <p>En un equipo sin tarjeta gráfica dedicada, cada guion puede tardar varios minutos.</p></details></div>`}
    </div>
  </div>

  <div class="card" id="s-video">
    <div class="card-head"><h2>Video y voz</h2></div>
    <p class="card-desc">El video largo es horizontal; los Shorts se generan nativos en vertical, cada uno con su propio guion.</p>
    <div class="form-grid">
      ${field("video.long_minutes", "Duración del video largo (min)", "number", { min: 1, max: 15 })}
      ${field("video.shorts_count", "Shorts por run", "number", { min: 0, max: 5 })}
      ${field("video.quality", "Calidad", "select", { options: [["1080p", "1080p (mejor)"], ["720p", "720p (más rápido)"]] })}
      ${field("voice.engine", "Motor de voz", "select", { options: [["edge", "Microsoft Edge (gratis, sincronía exacta)"], ["gemini", "Gemini TTS (gratis con tu clave, más expresiva)"]], help: d.voice.engine === "gemini" ? "Si Gemini falla o se agota la cuota, ese video se narra con la voz de Edge." : "" })}
      ${d.voice.engine === "gemini" ? `
      ${field("voice.gemini_voice", "Voz de Gemini", "select", { options: cfg.geminiVoices.map((v) => [v, v]) })}
      ${field("voice.gemini_style", "Estilo de lectura", "text", { help: "Cómo debe sonar, en tus palabras. Ej.: «cercano y con energía, acento latino neutro, ritmo ágil»." })}` : ""}
      <div class="field"><label for="f-voice-name">Voz de Edge${d.voice.engine === "gemini" ? " (respaldo)" : ""}</label><select id="f-voice-name" data-path="voice.name"><option>${esc(d.voice.name)}</option></select></div>
      ${field("voice.rate", "Velocidad (Edge)", "select", { options: [["-10%", "Lenta"], ["+0%", "Normal"], ["+6%", "Ágil"], ["+12%", "Rápida"], ["+20%", "Muy rápida"]] })}
    </div>
    <div style="margin-top:12px">
      ${toggle("video.long_enabled", "Crear video largo", "Si lo desactivas, cada run produce solo Shorts.")}
      ${toggle("video.subtitles", "Subtítulos animados", "Palabra por palabra, quemados en el video.")}
      ${toggle("video.music", "Música de fondo", "Se crea para cada video según su estado de ánimo (lo elige la IA del guion) y baja de volumen cuando habla la voz.")}
    </div>
    ${d.video.music ? `<div class="form-grid" style="margin-top:6px">
      ${field("video.music_source", "Origen de la música", "select", { options: [["generada", "Generada automáticamente (gratis, sin derechos de autor)"], ["lyria", "Lyria, IA de Google (de pago, ~US$0.04–0.08 por video)"], ["carpeta", "Mis archivos de assets/music"]], help: d.video.music_source === "carpeta" ? `Carpeta: <code>${esc(cfg.musicDir)}</code> — ${cfg.musicFiles.length ? `${cfg.musicFiles.length} archivo(s)` : "vacía: se usará la música generada"}.` : d.video.music_source === "lyria" ? "Usa tu Gemini API key; requiere activar la facturación en Google AI Studio. Si falla, se usa la generada." : "Compone acordes, bajo, arpegios y batería con la duración exacta del video." })}
      ${field("video.music_volume", "Volumen de la música (0–1)", "number", { min: 0, max: 1, step: 0.01 })}
    </div>` : ""}
    ${toggle("video.animations", "Animaciones (Remotion)", `Gráficos animados sobre algunas escenas: gancho en texto grande, listas, cifras, frases clave y cierre. La IA decide dónde van. ${cfg.motion.ok ? '<span style="color:var(--ok)">✓ Remotion listo.</span>' : `<span class="err-text">${esc(cfg.motion.msg)}</span>`}`)}
    ${d.video.animations ? `<div class="form-grid" style="margin-top:6px">${field("video.anim_color", "Color de resaltado", "color", { help: "Por defecto, el mismo amarillo de los subtítulos." })}</div>` : ""}
    ${toggle("video.sfx", "Efectos de sonido", "Un «whoosh» cuando entra cada animación, un golpe en el gancho y, en Shorts, un barrido suave en cada cambio de escena.")}
    ${toggle("video.transitions", "Acercamiento al cambiar de escena", "La toma entra un poco acercada y se asienta en 0,3 s: da ritmo sin alargar el video.")}
    ${toggle("video.thumbnail", "Miniatura automática (YouTube)", "Para el video largo: la IA elige el mejor cuadro y Remotion le pone un texto llamativo. YouTube exige verificar el canal con tu teléfono para usar miniaturas personalizadas.")}
    <div class="form-grid" style="margin-top:6px">
      ${field("video.review", "Revisión de calidad con IA", "select", { options: [["auto", "Automática (Gemini gratis: imagen y audio; si no, Claude: imagen)"], ["gemini", "Solo Gemini (gratis)"], ["claude", "Solo Claude (de pago)"], ["off", "Desactivada"]], help: "Al terminar cada video, la IA mira cuadros y escucha el audio: clips sin relación, textos cortados, voz tapada por la música…" })}
      ${field("video.review_min_score", "Nota mínima para aprobar (1–10)", "number", { min: 1, max: 10 })}
    </div>
    ${toggle("video.review_block", "No publicar automáticamente videos reprobados", "Los puedes revisar y publicar a mano igual.")}
    <h2 style="margin:22px 0 12px">Material visual</h2>
    ${radioCards("video.visual_provider", [
      ["pexels", "Clips reales de stock (Pixabay / Pexels)", "Gratis. Videos de stock elegidos escena por escena según el guion. Usa las claves que tengas guardadas."],
      ["fal", "Video generado con IA (fal.ai)", "De pago. Se combina con stock igual que la opción local, para pagar solo las escenas que lo necesitan."],
      ["comfyui", "Video IA local en tu GPU (ComfyUI)", "Gratis, en tu tarjeta NVIDIA. Lento, por eso se combina con stock: IA en las escenas que lo necesitan y clips de Pixabay/Pexels en las genéricas."],
    ])}
    ${d.video.visual_provider === "comfyui" ? `<div class="form-grid" style="margin-top:16px">
      ${field("video.ai_select", "Qué escenas van con IA", "select", { options: [["smart", "Mixto inteligente: IA solo donde hace falta, stock en lo genérico"], ["hook", "Las primeras tomas (el gancho)"], ["all", "Todas (muy lento o costoso)"]], help: "En modo mixto, el guion marca las escenas con el personaje o momentos concretos de la historia; paisajes, ciudades y objetos salen gratis de Pixabay/Pexels. Si el stock no tiene nada que encaje con una escena, esa escena también se genera con IA." })}
      ${field("video.comfy_max_shots", "Máximo de tomas con IA por video", "number", { min: 0, max: 30, help: "Tope de tiempo o de costo. 0 = sin tope." })}
      ${field("video.fal_scope", "Usar IA en", "select", { options: [["shorts", "Solo Shorts (stock para el largo)"], ["all", "Shorts y video largo"]] })}
      ${field("video.comfy_resolution", "Resolución IA", "select", { options: [["480p", "480p (recomendada con 6–8 GB de VRAM)"], ["544p", "544p"], ["704p", "704p (nativa, pide 12 GB o más)"]], help: "Se escala al tamaño final del video." })}
      ${field("video.comfy_segment_seconds", "Segundos por segmento IA", "number", { min: 2, max: 8 })}
      ${field("video.comfy_chain", "Continuidad", "select", { options: [["scene", "Encadenar dentro de cada escena (corte al cambiar)"], ["all", "Una sola cadena para todo el video"]], help: "Cada toma sigue desde el último cuadro de la anterior. Con una sola cadena el video es más continuo, pero tiende a alejarse de la narración." })}
      ${field("video.comfy_director_min", "Nota mínima del director IA (1–10)", "number", { min: 1, max: 10, help: "Las imágenes clave con nota menor se repiten (hasta 3 intentos) y las tomas se regeneran una vez; se queda la mejor." })}
      ${field("video.ai_style", "Estilo visual (opcional)", "text", { help: "Se agrega a cada escena, en inglés. Ej.: <code>cinematic, film grain, shallow depth of field</code> o <code>anime style, studio quality</code>." })}
      ${field("video.comfy_steps", "Pasos de muestreo", "number", { min: 4, max: 50, help: "Más pasos = más detalle y más tiempo. 20 es el valor del modelo." })}
      ${field("video.comfy_path", "Carpeta de ComfyUI portable", "text", { help: "Si ComfyUI está cerrado, el run lo abre y lo cierra al terminar (libera la memoria)." })}
      ${field("video.comfy_url", "Dirección de ComfyUI", "text", { help: "Otro PC de la red también sirve, p. ej. <code>http://192.168.1.50:8188</code>." })}
      ${field("video.comfy_workflow", "Workflow", "text", { help: "En <code>agente/workflows/</code> o ruta completa. Formato API con marcadores {{prompt}}, {{width}}…" })}
    </div>
    ${toggle("video.comfy_keyframes", "Imagen clave primero", "Cada escena empieza con una imagen (~1 min) que el director revisa y repite si no muestra la escena; luego se anima. Evita gastar 5-8 min en tomas de video que salen mal.")}
    ${toggle("video.comfy_director", "Director IA", "Tras cada toma, una IA con visión (Gemini gratis) compara dos cuadros con la narración y regenera la toma si se desvió. Cuesta más tiempo de GPU solo cuando regenera.")}
    <div class="form-grid">
      <div class="field full"><span class="help">⏱ En una RTX 4050 de 6 GB cada toma de 5 s a 480p tarda ~8 min (la primera ~11 min, porque carga los modelos): un Short con 2 tomas IA suma ~20 min. Si una toma falla, se usa un clip de stock.</span></div>
    </div>` : ""}
    ${d.video.visual_provider !== "fal" || d.video.ai_select !== "all" ? `<div class="form-grid" style="margin-top:16px">
      ${field("video.smart_clips", "Selección inteligente de clips", "select", { options: [["auto", "Automática (Gemini gratis si hay clave, si no Claude)"], ["gemini", "Solo Gemini (gratis)"], ["claude", "Solo Claude (de pago, Haiku)"], ["off", "Desactivada (primer resultado del banco)"]], help: "Una IA con visión mira las miniaturas de varios clips por escena y elige el que mejor muestra lo que dice la narración." })}
    </div>` : ""}
    ${d.video.visual_provider === "fal" ? `<div class="form-grid" style="margin-top:16px">
      ${field("video.ai_select", "Qué escenas van con IA", "select", { options: [["smart", "Mixto inteligente: IA solo donde hace falta, stock en lo genérico"], ["hook", "Las primeras tomas (el gancho)"], ["all", "Todas (muy lento o costoso)"]], help: "En modo mixto, el guion marca las escenas con el personaje o momentos concretos de la historia; paisajes, ciudades y objetos salen gratis de Pixabay/Pexels. Si el stock no tiene nada que encaje con una escena, esa escena también se genera con IA." })}
      ${field("video.comfy_max_shots", "Máximo de tomas con IA por video", "number", { min: 0, max: 30, help: "Tope de tiempo o de costo. 0 = sin tope." })}
      ${field("video.fal_scope", "Usar IA en", "select", { options: [["shorts", "Solo Shorts (stock para el largo)"], ["all", "Todo (costoso)"]] })}
      ${field("video.fal_segment_seconds", "Segundos por segmento IA", "number", { min: 2, max: 10 })}
      ${field("video.fal_t2v_model", "Modelo texto→video", "text", { help: "ID del modelo en fal.ai/models" })}
      ${field("video.fal_i2v_model", "Modelo imagen→video", "text", { help: "Recibe el último fotograma de la toma anterior" })}
      <div class="field full"><span class="help">⚠ Costo aproximado: cada segmento de ~5 s cuesta entre US$0.10 y US$0.50 según el modelo. Un Short de 45 s ≈ 9 segmentos. Si una toma falla, se usan clips de stock como respaldo.</span></div>
    </div>` : ""}
  </div>

  <div class="card" id="s-publish">
    <div class="card-head"><h2>Publicación</h2></div>
    ${toggle("publish.auto_publish", "Publicar automáticamente", "Si está desactivado, revisas los videos y publicas con un clic desde el panel. La ejecución diaria programada usa este ajuste.")}
    <div class="platform-block" style="margin-top:12px">
      ${toggle("publish.youtube", "YouTube", "Video largo + Shorts.")}
      ${d.publish.youtube ? `<div class="form-grid">
        ${field("publish.youtube_method", "Cómo se conecta", "select", { options: [["browser", "Navegador: tu sesión de YouTube Studio (recomendado)"], ["api", "API de Google (sin auditoría sube en privado)"]], help: "Con el navegador no hace falta crear un proyecto en Google Cloud y los videos pueden salir públicos." })}
        ${field("publish.youtube_privacy", "Privacidad", "select", { options: [["private", "Privado"], ["unlisted", "No listado"], ["public", "Público"]], help: d.publish.youtube_method === "api" ? "Los proyectos de API sin auditoría de Google solo pueden subir en privado." : "" })}
        ${d.publish.youtube_method === "api" ? field("publish.youtube_category", "Categoría", "select", { options: [["26", "Consejos y estilo"], ["22", "Personas y blogs"], ["27", "Educación"], ["24", "Entretenimiento"], ["28", "Ciencia y tecnología"], ["19", "Viajes y eventos"]] }) : ""}
      </div>` : ""}
    </div>
    <div class="platform-block">
      ${toggle("publish.tiktok", "TikTok", "Solo los Shorts verticales.")}
      ${d.publish.tiktok ? `<div class="form-grid">
        ${field("publish.tiktok_method", "Cómo se conecta", "select", { options: [["browser", "Navegador: tu sesión de TikTok Studio (recomendado)"], ["api", "API de TikTok (sin auditoría: privado o borrador)"]], help: "Con el navegador no hace falta una app de desarrollador y se puede publicar en público." })}
        ${d.publish.tiktok_method === "api" ? field("publish.tiktok_mode", "Modo", "select", { options: [["inbox", "Enviar a borradores (terminas en la app)"], ["direct", "Publicación directa"]] }) : ""}
        ${field("publish.tiktok_privacy", "Privacidad (directa)", "select", { options: [["SELF_ONLY", "Solo yo"], ["MUTUAL_FOLLOW_FRIENDS", "Amigos"], ["FOLLOWER_OF_CREATOR", "Seguidores"], ["PUBLIC_TO_EVERYONE", "Público"]], help: "Las apps de TikTok sin auditoría solo pueden publicar como «Solo yo»." })}
      </div>` : ""}
    </div>
    ${(d.publish.youtube && d.publish.youtube_method !== "api") || (d.publish.tiktok && d.publish.tiktok_method !== "api") ? `<div class="platform-block">
      ${toggle("publish.browser_visible", "Ver la ventana del navegador al publicar", "Útil para revisar las primeras publicaciones. Desactivado, Chrome trabaja fuera de la pantalla.")}
      <div class="form-grid"><div class="field full"><span class="help">⚠ Publicar con el navegador imita lo que harías a mano, pero YouTube y TikTok no lo permiten oficialmente: puede aparecer un captcha o una advertencia en la cuenta. Publica pocas veces al día. Si cambian su página, puede dejar de funcionar hasta actualizar la app; en ese caso queda una captura del error.</span></div></div>
    </div>` : ""}
    <div class="platform-block">
      ${toggle("publish.facebook", "Facebook", "Video largo como video de página y Shorts como Reels.")}
      ${d.publish.facebook ? `<div class="form-grid">${field("publish.facebook_graph_version", "Versión de Graph API", "text", { help: "Ej. v24.0. Actualízala si Meta la deja obsoleta." })}</div>` : ""}
    </div>
    <div class="platform-block">
      ${toggle("publish.instagram", "Instagram Reels", "Solo los Shorts. Usa el mismo token de página de Facebook; tu Instagram debe ser profesional y estar vinculado a la página.")}
    </div>
    <div class="form-grid" style="margin-top:16px">
      ${field("metrics.min_age_hours", "Horas mínimas antes de medir un video", "number", { min: 6, max: 720 })}
      ${field("metrics.exploration", "Exploración del aprendizaje (0–1)", "number", { min: 0, max: 1, step: 0.05, help: "Probabilidad de probar un gancho distinto al mejor." })}
    </div>
  </div>

  <div class="card" id="s-connections">
    <div class="card-head"><h2>Conexiones</h2></div>
    <p class="card-desc">Autoriza tus cuentas una sola vez. Los tokens se guardan cifrados en el Administrador de credenciales de Windows.</p>
    <div id="connBox" class="muted">Cargando…</div>
  </div>

  <div class="card" id="s-secrets">
    <div class="card-head"><h2>Credenciales</h2></div>
    <p class="card-desc">Se guardan en el Administrador de credenciales de Windows, nunca en archivos del proyecto. Por seguridad no se vuelven a mostrar: para cambiar una, escribe el nuevo valor.</p>
    <div id="secretRows"></div>
  </div>

  <div class="card" id="s-schedule">
    <div class="card-head"><h2>Ejecución diaria</h2></div>
    <p class="card-desc">Crea una tarea en el Programador de tareas de Windows que ejecuta el run cada día (el equipo debe estar encendido). Publica solo si «Publicar automáticamente» está activo.</p>
    <div id="scheduleBox" class="muted">Cargando…</div>
  </div>

  <div class="card" id="s-storage">
    <div class="card-head"><h2>Espacio y avisos</h2></div>
    <p class="card-desc">Cada run guarda tomas y audios intermedios que ocupan mucho. Se borran solos pasados unos días; los videos finales, miniaturas y guiones se conservan.</p>
    <div id="storageBox" class="muted small">Calculando…</div>
    <div class="form-grid" style="margin-top:12px">
      ${field("storage.keep_work_days", "Borrar archivos de trabajo tras (días)", "number", { min: 1, max: 365 })}
      ${field("storage.cache_max_gb", "Tope de la caché de clips (GB)", "number", { min: 1, max: 100 })}
      ${field("storage.delete_videos_days", "Borrar videos finales tras (días)", "number", { min: 0, max: 3650, help: "0 = nunca." })}
    </div>
    ${toggle("general.notify", "Aviso de Windows al terminar", "Una notificación cuando un run termina o falla (útil con la ejecución diaria).")}
  </div>`;

  renderSecrets();
  renderVoiceSelect();
  bindSettingsInputs();
  const t = $("#btnTestOllama");
  if (t) t.onclick = async () => {
    await saveSettings(true);
    const m = $("#ollamaMsg");
    m.textContent = "Probando…"; m.style.color = "";
    try {
      const r = await api("/api/test/ollama", { method: "POST" });
      m.textContent = r.msg;
      m.style.color = r.ok ? "var(--ok)" : "var(--err)";
    } catch (e) { m.textContent = e.message; m.style.color = "var(--err)"; }
    refreshState();
  };
}

function renderVoiceSelect() {
  const sel = $("#f-voice-name");
  if (!sel || !cfg.voices.length) return;
  const cur = cfg.draft.voice.name;
  sel.innerHTML = cfg.voices.map((v) => `<option value="${esc(v.name)}" ${v.name === cur ? "selected" : ""}>${esc(v.name.replace(/Neural$/, ""))} · ${v.gender === "Female" ? "Mujer" : "Hombre"}</option>`).join("");
}

function bindSettingsInputs() {
  $$("#settingsBody [data-path]").forEach((el) => {
    const evt = el.tagName === "SELECT" || el.type === "checkbox" || el.type === "radio" ? "change" : "input";
    el.addEventListener(evt, () => {
      let v;
      if (el.type === "checkbox") v = el.checked;
      else if (el.type === "radio") { if (!el.checked) return; v = el.value; }
      else if (el.dataset.num) v = el.value === "" ? 0 : Number(el.value);
      else v = el.value;
      set(cfg.draft, el.dataset.path, v);
      updateSaveBar();
      // re-render cuando cambian opciones que muestran/ocultan secciones
      if (el.type === "checkbox" || el.type === "radio" || RERENDER.includes(el.dataset.path)) {
        const y = window.scrollY;
        renderSettings();
        loadConnections(); loadSchedule();
        window.scrollTo({ top: y });
      }
    });
  });
}

function updateSaveBar() {
  const dirty = JSON.stringify(cfg.draft) !== JSON.stringify(cfg.loaded);
  $("#saveBar").classList.toggle("hidden", !dirty);
}
async function saveSettings(silent = false) {
  try {
    const { settings } = await api("/api/settings", { method: "PUT", body: cfg.draft });
    cfg.loaded = settings;
    cfg.draft = structuredClone(settings);
    updateSaveBar();
    if (!silent) toast("Configuración guardada", "ok");
    refreshState();
  } catch (e) { toast(e.message, "err"); }
}
$("#btnSave").onclick = () => saveSettings();
$("#btnDiscard").onclick = () => { cfg.draft = structuredClone(cfg.loaded); renderSettings(); loadConnections(); loadSchedule(); updateSaveBar(); };

function renderSecrets() {
  const rows = Object.entries(cfg.meta).map(([name, m]) => {
    const ok = cfg.secrets[name];
    const multiline = name === "youtube_client_secret";
    const input = multiline
      ? `<textarea data-secret="${name}" rows="2" placeholder="${ok ? "Guardado — pega un nuevo JSON para reemplazarlo" : '{"installed": {...}}'}"></textarea>`
      : `<input type="password" data-secret="${name}" autocomplete="off" placeholder="${ok ? "•••••••••• guardado — escribe para reemplazar" : "Pega la clave aquí"}">`;
    return `<div class="secret-row" data-row="${name}">
      <div class="sr-label"><b>${esc(m.label)}</b><span>${esc(m.help)}</span></div>
      <div class="secret-input"><span class="status-tag ${ok ? "ok" : "missing"}">${ok ? "Guardado" : "Falta"}</span>${input}</div>
      <div class="sr-actions">
        <button class="btn sm primary" data-save="${name}">Guardar</button>
        ${TESTABLE[name] ? `<button class="btn sm" data-test="${name}" ${ok ? "" : "disabled"}>Probar</button>` : ""}
        ${ok ? `<button class="btn sm ghost" data-del="${name}" title="Borrar">✕</button>` : ""}
      </div>
      <div class="test-msg" data-msg="${name}"></div>
    </div>`;
  }).join("");
  $("#secretRows").innerHTML = rows;
  $$("#secretRows [data-save]").forEach((b) => (b.onclick = async () => {
    const name = b.dataset.save;
    const el = $(`[data-secret="${name}"]`);
    if (!el.value.trim()) { toast("Escribe un valor primero", "warn"); return; }
    try {
      const res = await api(`/api/secrets/${name}`, { method: "PUT", body: { value: el.value } });
      cfg.secrets[name] = true;
      toast(res?.note || `${cfg.meta[name].label} guardada`, res?.note?.includes("Atención") ? "err" : "ok");
      renderSecrets();
      refreshState();
      if (TESTABLE[name]) $(`[data-test="${name}"]`)?.click();
    } catch (e) { toast(e.message, "err"); }
  }));
  $$("#secretRows [data-test]").forEach((b) => (b.onclick = async () => {
    const name = b.dataset.test;
    const msg = $(`[data-msg="${name}"]`);
    msg.className = "test-msg muted"; msg.textContent = "Probando…";
    try {
      const r = await api(`/api/test/${TESTABLE[name]}`, { method: "POST" });
      msg.className = `test-msg ${r.ok ? "ok" : "err"}`;
      msg.textContent = (r.ok ? "✓ " : "✕ ") + r.msg;
    } catch (e) { msg.className = "test-msg err"; msg.textContent = e.message; }
  }));
  $$("#secretRows [data-del]").forEach((b) => (b.onclick = async () => {
    const name = b.dataset.del;
    if (!confirm(`¿Borrar ${cfg.meta[name].label}?`)) return;
    await api(`/api/secrets/${name}`, { method: "DELETE" });
    cfg.secrets[name] = false;
    renderSecrets();
    refreshState();
  }));
}

const GUIDES = {
  youtube: `<ol>
    <li>Entra a <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">Google Cloud Console</a> y crea un proyecto.</li>
    <li>En <i>APIs y servicios → Biblioteca</i>, habilita <b>YouTube Data API v3</b>.</li>
    <li>En <i>Google Auth Platform</i> (antes «Pantalla de consentimiento de OAuth») configura la app como <b>Externa</b>.</li>
    <li>En <i>Google Auth Platform → Clientes → Crear cliente</i>, tipo <b>App de escritorio</b>. Descarga el JSON, ábrelo con el Bloc de notas y pega todo su contenido en «YouTube OAuth client (JSON)».</li>
    <li><b>Para evitar «Acceso bloqueado»</b>, en <i>Google Auth Platform → Público</i> elige una opción:
      <ul>
        <li><b>Recomendado: «Publicar app»</b> (estado <i>En producción</i>). No necesitas la verificación de Google para usarla con tu propia cuenta. Al conectar verás «Google no verificó esta app»: pulsa <i>Configuración avanzada → Ir a … (no seguro)</i>. Es seguro porque la app es tuya. La autorización no vence.</li>
        <li>O deja la app en <i>Prueba</i> y agrega tu correo en <b>Usuarios de prueba</b>. Funciona, pero Google <b>vence la autorización cada 7 días</b> y tendrás que reconectar.</li>
      </ul></li>
    <li>Vuelve aquí y pulsa <b>Conectar YouTube</b>.</li></ol>
    <p>En ese mismo proyecto, <i>Credenciales → Crear credenciales → Clave de API</i> te da la «YouTube Data API key» para investigar tendencias. Aparte, mientras Google no audite tu proyecto, los videos se suben como <b>privados</b>; la auditoría se solicita en el formulario de YouTube API Services.</p>`,
  tiktok: () => `<ol>
    <li>Entra a <a href="https://developers.tiktok.com/" target="_blank" rel="noopener">developers.tiktok.com</a> → <i>Manage apps</i> → crea una app.</li>
    <li>Agrega los productos <b>Login Kit</b> y <b>Content Posting API</b>.</li>
    <li>En Login Kit registra la Redirect URI: <code>${esc(cfg.redirect)}</code></li>
    <li>Copia el <b>Client key</b> y el <b>Client secret</b> en Credenciales.</li>
    <li>Vuelve aquí y pulsa <b>Conectar TikTok</b>.</li></ol>
    <p>Mientras TikTok no audite tu app, los videos solo se publican como «Solo yo».</p>`,
  facebook: `<ol>
    <li>Entra a <a href="https://developers.facebook.com/apps" target="_blank" rel="noopener">Meta for Developers</a> y crea una app de tipo <b>Empresa</b>.</li>
    <li>Abre el <a href="https://developers.facebook.com/tools/explorer/" target="_blank" rel="noopener">Explorador de la Graph API</a>, elige tu app y agrega los permisos <code>pages_show_list</code>, <code>pages_manage_posts</code>, <code>pages_read_engagement</code>, <code>publish_video</code> y, para Instagram, <code>instagram_basic</code> e <code>instagram_content_publish</code>.</li>
    <li>Pulsa <i>Generate Access Token</i> y autoriza tu página (deja «Usuario» seleccionado: es un token de <b>usuario</b>).</li>
    <li><b>Importante para que no venza:</b> copia ese token, ábrelo en el <a href="https://developers.facebook.com/tools/debug/accesstoken/" target="_blank" rel="noopener">Depurador de tokens</a> y pulsa <i>Extend Access Token</i>. Copia el token largo que aparece abajo.</li>
    <li>Pega ese token largo en «Facebook Page access token». La app obtiene sola el token de tu página, que <b>no vence</b>.</li></ol>
    <p>Si pegas un token de página corto, funciona solo unas horas: por eso al día siguiente aparece «Session has expired».</p>
    <p><b>Instagram:</b> tu cuenta debe ser profesional (empresa o creador) y estar vinculada a la página (Instagram → Configuración → Cuenta → Página vinculada).</p>`,
};

function goSecret(name) {
  const row = $(`[data-row="${name}"]`);
  if (!row) return;
  row.scrollIntoView({ behavior: "smooth", block: "center" });
  row.classList.remove("flash"); void row.offsetWidth; row.classList.add("flash");
  setTimeout(() => row.querySelector("[data-secret]")?.focus({ preventScroll: true }), 400);
}

const howTo = (key) => `<details class="howto"><summary>¿Cómo lo obtengo?</summary>${typeof GUIDES[key] === "function" ? GUIDES[key]() : GUIDES[key]}</details>`;

let ytPoll = null;
async function loadConnections() {
  const box = $("#connBox");
  if (!box) return;
  try {
    const c = await api("/api/connections");
    const yt = c.youtube, tt = c.tiktok, fb = c.facebook, ig = c.instagram || {};
    const ytPending = yt.pending && yt.pending.state === "waiting";
    const ytReady = cfg.secrets.youtube_client_secret;
    const ttMissing = !cfg.secrets.tiktok_client_key ? "tiktok_client_key" : !cfg.secrets.tiktok_client_secret ? "tiktok_client_secret" : null;
    const status = (p) => p.connected ? `Conectado${p.name ? `: ${esc(p.name)}` : ""}` : "No conectado";

    const ytHint = ytPending ? "Esperando autorización en la pestaña del navegador…"
      : yt.pending?.state === "error" ? `<span class="err-text">${esc(yt.pending.msg)}</span>`
      : !ytReady ? "Paso 1: guarda el «YouTube OAuth client (JSON)» en Credenciales. Paso 2: pulsa Conectar."
      : yt.connected && yt.error ? `<span class="err-text">${esc(yt.error)}</span>`
      : yt.connected ? "Se usa para subir videos y leer sus métricas." : "Listo para conectar: se abrirá una pestaña para autorizar tu canal. Si Google muestra «Acceso bloqueado», abre «¿Cómo lo obtengo?».";
    const ttHint = ttMissing ? "Paso 1: guarda el client key y el client secret de tu app de TikTok en Credenciales. Paso 2: pulsa Conectar."
      : tt.connected ? "Se usa para publicar los Shorts." : "Listo para conectar: se abrirá TikTok para autorizar tu cuenta.";
    const fbHint = !fb.connected ? "Facebook se conecta con un token de página: guárdalo en Credenciales y queda listo."
      : fb.error ? `<span class="err-text">${esc(fb.error)}</span>` : "Se usa para publicar el video largo y los Reels en tu página.";

    const br = c.browser || {};
    const methods = { youtube: cfg.draft.publish.youtube_method || "browser", tiktok: cfg.draft.publish.tiktok_method || "browser" };
    const browserRow = (p, label, cls) => {
      const s = br[p] || {};
      const hint = s.pending ? "Se abrió una ventana de Chrome: inicia sesión ahí. Se cierra sola al terminar."
        : s.error ? `<span class="err-text">${esc(s.error)}</span>`
        : s.connected ? "Sesión guardada en este PC. Se usa para publicar con el navegador."
        : `Pulsa el botón: se abre Chrome para que inicies sesión en ${label} una sola vez.`;
      return `<div class="conn-row">
        <span class="platform ${cls}">${label}</span>
        <div class="cr-text"><b>${s.connected ? "Conectado (navegador)" : s.pending ? "Esperando inicio de sesión…" : "No conectado"}</b><span>${hint}</span></div>
        ${s.connected ? `<button class="btn sm ghost" data-bdisc="${p}">Cerrar sesión</button>` : ""}
        <button class="btn sm ${s.connected ? "" : "primary"}" data-blogin="${p}" ${s.pending ? "disabled" : ""}>${s.connected ? "Volver a iniciar sesión" : `Iniciar sesión en ${label}`}</button>
      </div>`;
    };
    box.className = "";
    box.innerHTML = `
      ${methods.youtube === "browser" ? browserRow("youtube", "YouTube", "youtube") : `<div class="conn-row">
        <span class="platform youtube">YouTube</span>
        <div class="cr-text"><b>${yt.connected && yt.error ? "Hay que reconectar" : status(yt)}</b><span>${ytHint}</span>${howTo("youtube")}</div>
        ${yt.connected ? `<button class="btn sm ghost" data-disc="youtube">Desconectar</button>` : ""}
        ${ytReady
          ? `<button class="btn sm ${yt.connected ? "" : "primary"}" id="btnConnYT" ${ytPending ? "disabled" : ""}>${yt.connected ? "Reconectar" : "Conectar YouTube"}</button>`
          : `<button class="btn sm secondary" data-goto="youtube_client_secret">Agregar credencial</button>`}
      </div>`}
      ${methods.tiktok === "browser" ? browserRow("tiktok", "TikTok", "tiktok") : `<div class="conn-row">
        <span class="platform tiktok">TikTok</span>
        <div class="cr-text"><b>${status(tt)}</b><span>${ttHint}</span>${howTo("tiktok")}</div>
        ${tt.connected ? `<button class="btn sm ghost" data-disc="tiktok">Desconectar</button>` : ""}
        ${ttMissing
          ? `<button class="btn sm secondary" data-goto="${ttMissing}">Agregar credenciales</button>`
          : `<button class="btn sm ${tt.connected ? "" : "primary"}" id="btnConnTT">${tt.connected ? "Reconectar" : "Conectar TikTok"}</button>`}
      </div>`}
      <div class="conn-row">
        <span class="platform facebook">Facebook</span>
        <div class="cr-text"><b>${fb.connected ? (fb.error ? "Token con problemas" : status(fb)) : "No conectado"}</b><span>${fbHint}</span>${howTo("facebook")}</div>
        <button class="btn sm ${fb.connected && !fb.error ? "" : "secondary"}" data-goto="facebook_page_token">${fb.connected ? "Cambiar token" : "Agregar token"}</button>
      </div>
      ${cfg.draft.publish.instagram ? `<div class="conn-row">
        <span class="platform instagram">Instagram</span>
        <div class="cr-text"><b>${ig.connected ? `Vinculado: ${esc(ig.name)}` : "No vinculado"}</b><span>${ig.error ? `<span class="err-text">${esc(ig.error)}</span>` : ig.connected ? "Se usa para publicar los Shorts como Reels." : "Usa el token de Facebook: guárdalo con los permisos de Instagram."}</span>${howTo("facebook")}</div>
        <button class="btn sm secondary" data-goto="facebook_page_token">Token de Facebook</button>
      </div>` : ""}`;
    $$("#connBox [data-goto]").forEach((b) => (b.onclick = () => goSecret(b.dataset.goto)));
    $$("#connBox [data-blogin]").forEach((b) => (b.onclick = async () => {
      const p = b.dataset.blogin;
      try {
        await api(`/api/browser-login/${p}`, { method: "POST" });
        toast("Se abrió Chrome: inicia sesión en la ventana nueva", "ok");
        loadConnections();
        let tries = 0;
        const iv = setInterval(async () => {
          tries++;
          const s = await api("/api/connections");
          const st = (s.browser || {})[p] || {};
          if (!st.pending || tries > 330) {
            clearInterval(iv);
            toast(st.connected ? "Sesión guardada" : (st.error || "No se completó el inicio de sesión"), st.connected ? "ok" : "err");
            loadConnections(); refreshState();
          }
        }, 2000);
      } catch (e) { toast(e.message, "err"); }
    }));
    $$("#connBox [data-bdisc]").forEach((b) => (b.onclick = async () => {
      if (!confirm("¿Cerrar la sesión guardada en este PC?")) return;
      await api(`/api/browser-disconnect/${b.dataset.bdisc}`, { method: "POST" });
      loadConnections(); refreshState();
    }));
    const bYT = $("#btnConnYT");
    if (bYT) bYT.onclick = async () => {
      try {
        await api("/api/connect/youtube", { method: "POST" });
        toast("Autoriza el acceso en la pestaña que se abrió", "ok");
        clearInterval(ytPoll);
        ytPoll = setInterval(async () => {
          const s = await api("/api/connections");
          if (s.youtube.pending.state !== "waiting") {
            clearInterval(ytPoll);
            toast(s.youtube.pending.msg || "Listo", s.youtube.pending.state === "ok" ? "ok" : "err");
            cfg.secrets.youtube_token = s.youtube.connected;
            loadConnections(); refreshState();
          }
        }, 2000);
        loadConnections();
      } catch (e) { toast(e.message, "err"); }
    };
    const bTT = $("#btnConnTT");
    if (bTT) bTT.onclick = async () => {
      try {
        const { url } = await api("/api/connect/tiktok");
        window.open(url, "_blank", "noopener");
        toast("Autoriza en TikTok y vuelve aquí", "ok");
        let tries = 0;
        const iv = setInterval(async () => {
          tries++;
          const s = await api("/api/connections");
          if (s.tiktok.connected || tries > 90) { clearInterval(iv); loadConnections(); refreshState(); if (s.tiktok.connected) toast("TikTok conectado", "ok"); }
        }, 2000);
      } catch (e) { toast(e.message, "err"); }
    };
    $$("#connBox [data-disc]").forEach((b) => (b.onclick = async () => {
      if (!confirm("¿Desconectar esta cuenta?")) return;
      await api(`/api/disconnect/${b.dataset.disc}`, { method: "POST" });
      loadConnections(); refreshState();
    }));
  } catch (e) { box.textContent = e.message; }
}

async function loadStorage() {
  const box = $("#storageBox");
  if (!box) return;
  try {
    const u = await api("/api/storage");
    box.innerHTML = `<div class="facts" style="margin:0">
        <span>Runs <b>${u.runs}</b></span><span>Archivos de trabajo <b>${u.work_gb} GB</b></span>
        <span>Videos finales <b>${u.videos_gb} GB</b></span><span>Caché de clips <b>${u.cache_gb} GB</b></span></div>
      <button class="btn sm" id="btnCleanNow" style="margin-top:8px">Liberar espacio ahora</button>
      <span class="help">Borra los archivos de trabajo de todos los runs terminados y la caché. No toca los videos finales.</span>`;
    $("#btnCleanNow").onclick = async () => {
      if (!confirm("¿Borrar los archivos de trabajo de todos los runs terminados y la caché de clips? Los videos finales se conservan, pero «Reintentar» tendrá que regenerar voces y tomas.")) return;
      try {
        const r = await api("/api/storage/cleanup", { method: "POST" });
        toast(`Se liberaron ${r.freed_gb} GB`, "ok");
        loadStorage();
      } catch (e) { toast(e.message, "err"); }
    };
  } catch (e) { box.textContent = e.message; }
}

async function loadSchedule() {
  loadStorage();
  const box = $("#scheduleBox");
  if (!box) return;
  try {
    const s = await api("/api/schedule");
    box.className = "";
    box.innerHTML = `<div class="conn-row">
      <div class="cr-text"><b>${s.enabled ? "Programada" : "Desactivada"}</b><span>${s.enabled && s.next_run ? `Próxima ejecución: ${esc(s.next_run)}` : "El agente solo se ejecuta cuando lo inicias manualmente."}</span></div>
      <input type="time" id="schedTime" value="09:00" style="width:120px">
      ${s.enabled ? '<button class="btn sm ghost" id="btnSchedOff">Desactivar</button>' : ""}
      <button class="btn sm primary" id="btnSchedOn">${s.enabled ? "Cambiar hora" : "Activar"}</button></div>`;
    $("#btnSchedOn").onclick = async () => {
      try { await api("/api/schedule", { method: "PUT", body: { enabled: true, time: $("#schedTime").value } }); toast("Ejecución diaria programada", "ok"); loadSchedule(); }
      catch (e) { toast(e.message, "err"); }
    };
    const off = $("#btnSchedOff");
    if (off) off.onclick = async () => { await api("/api/schedule", { method: "PUT", body: { enabled: false } }); toast("Ejecución diaria desactivada", "warn"); loadSchedule(); };
  } catch (e) { box.textContent = e.message; }
}

$("#btnImportLegacy").onclick = async () => {
  if (!confirm("Se importarán las claves de config.yaml y client_secret.json al almacén seguro de Windows y se ELIMINARÁN esos dos archivos. ¿Continuar?")) return;
  try {
    const r = await api("/api/import-legacy", { method: "POST", body: { delete: true } });
    toast(`Importadas: ${r.imported.join(", ") || "ninguna"}. Eliminados: ${r.deleted.join(", ") || "ninguno"}.`, "ok");
    toast("Recuerda regenerar esas credenciales en cada plataforma: estuvieron expuestas.", "warn");
    loadSettings();
    refreshState();
  } catch (e) { toast(e.message, "err"); }
};

/* nav de configuración: scroll suave */
$$("#settingsNav a").forEach((a) => (a.onclick = (e) => { e.preventDefault(); $(a.getAttribute("href"))?.scrollIntoView({ behavior: "smooth" }); }));

window.addEventListener("beforeunload", (e) => {
  if (!$("#saveBar").classList.contains("hidden")) { e.preventDefault(); e.returnValue = ""; }
});

/* ════════════════════════════════════════════════════════════
   Arranque
   ════════════════════════════════════════════════════════════ */
refreshState().then(() => {
  const h = location.hash.slice(1);
  if (["history", "learning", "settings"].includes(h)) showView(h);
});
setInterval(refreshState, 3000);
