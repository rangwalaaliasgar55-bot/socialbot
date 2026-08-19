/* SocialBot dashboard — vanilla JS single-page app */
"use strict";

const S = { platforms: [], posts: [], accounts: [], rules: [], calMonth: null,
            view: "calendar", platformsSig: "" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

/* ---------------------------------------------------------------- API + auth */
function apiToken() { return sessionStorage.getItem("sb_token") || ""; }

async function api(path, opts = {}) {
  const headers = { "Content-Type": "application/json", ...(opts.headers || {}) };
  const tok = apiToken();
  if (tok) headers["Authorization"] = "Bearer " + tok;
  const res = await fetch(path, { ...opts, headers });
  if (res.status === 401 && !tok) {
    const token = prompt("This SocialBot is protected by SOCIALBOT_API_TOKEN.\nEnter the API token:");
    if (token) { sessionStorage.setItem("sb_token", token); return api(path, opts); }
  }
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

function toast(msg, ms = 3200) {
  const t = $("toast"); t.textContent = msg; t.classList.add("show");
  clearTimeout(t._h); t._h = setTimeout(() => t.classList.remove("show"), ms);
}

function fmtWhen(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
function platform(name) { return S.platforms.find((p) => p.name === name) || { display_name: name, color: "#555", icon: "●" }; }
function platformDots(names) {
  return (names || []).map((n) => { const p = platform(n);
    return `<span class="ptag" style="background:${p.color}" title="${esc(p.display_name)}"></span>`; }).join(" ");
}
function statusChip(st) { return `<span class="chip s-${esc(st)}">${esc(st)}</span>`; }

/* ---------------------------------------------------------------- nav */
$("nav").addEventListener("click", (e) => {
  const a = e.target.closest("a[data-view]"); if (!a) return;
  e.preventDefault(); setView(a.dataset.view);
});
function setView(view) {
  S.view = view;
  document.querySelectorAll("nav a[data-view]").forEach((a) =>
    a.classList.toggle("active", a.dataset.view === view));
  document.querySelectorAll("main > section").forEach((s) => s.classList.add("hidden"));
  $(`view-${view}`).classList.remove("hidden");
  $("view-title").textContent = { calendar: "Calendar", queue: "Queue", composer: "Composer",
    accounts: "Accounts", bot: "Growth bot", analytics: "Analytics", events: "Activity" }[view];
  render();
}

/* ---------------------------------------------------------------- data */
async function loadAll() {
  try {
    const [platforms, posts, accounts, rules, health] = await Promise.all([
      api("/api/platforms"), api("/api/posts"), api("/api/accounts"),
      api("/api/bot/rules"), api("/api/health")]);
    S.platforms = platforms; S.posts = posts; S.accounts = accounts; S.rules = rules;
    const sch = health.scheduler || {};
    const on = sch.running;
    $("sched-pill").innerHTML =
      `<span class="dot ${on ? "on" : ""}"></span> ${on ? "scheduler live" : "scheduler off"}` +
      (on && sch.pending ? ` · ${sch.pending} queued` : "");
  } catch (err) { toast("API error: " + err.message); }
}

async function render() {
  await loadAll();
  if (S.view === "calendar") { renderCalendar(); renderUpcoming(); }
  if (S.view === "queue") renderQueue();
  if (S.view === "composer") renderComposer();
  if (S.view === "accounts") renderAccounts();
  if (S.view === "bot") renderBot();
  if (S.view === "analytics") renderAnalytics();
  if (S.view === "events") renderEvents();
}

/* ------------------------------------------------------------ calendar */
function renderCalendar() {
  const now = new Date();
  const base = S.calMonth ? new Date(S.calMonth) : now;
  S.calMonth = base;
  $("cal-title").textContent = base.toLocaleString([], { month: "long", year: "numeric" });

  const first = new Date(base.getFullYear(), base.getMonth(), 1);
  const days = new Date(base.getFullYear(), base.getMonth() + 1, 0).getDate();
  const startDow = (first.getDay() + 6) % 7; // Monday-first
  const grid = $("cal-grid");
  let html = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
    .map((d) => `<div class="dow">${d}</div>`).join("");
  for (let i = 0; i < startDow; i++) html += `<div class="day empty"></div>`;

  for (let d = 1; d <= days; d++) {
    const dayStart = new Date(base.getFullYear(), base.getMonth(), d);
    const dayKey = dayStart.toDateString();
    const evts = S.posts.filter((p) => {
      const t = p.scheduled_at || p.published_at;
      return t && new Date(t).toDateString() === dayKey &&
        ["scheduled", "published", "partial", "publishing"].includes(p.status);
    });
    const today = dayStart.toDateString() === now.toDateString();
    html += `<div class="day ${today ? "today" : ""}" data-day="${d}" title="Click to schedule for this day">
      <div class="dnum">${d}</div>
      ${evts.slice(0, 3).map((p) =>
        `<div class="evt">${platformDots(p.platforms)} ${esc((p.tag ? "#" + p.tag + " " : "") + p.text.slice(0, 22))}</div>`).join("")}
      ${evts.length > 3 ? `<div class="evt muted">+${evts.length - 3} more</div>` : ""}
    </div>`;
  }
  grid.innerHTML = html;
  grid.querySelectorAll(".day[data-day]").forEach((el) =>
    el.addEventListener("click", () => {
      setView("composer");
      const dt = new Date(base.getFullYear(), base.getMonth(), +el.dataset.day, 9, 0);
      const pad = (n) => String(n).padStart(2, "0");
      $("c-when").value = `${dt.getFullYear()}-${pad(dt.getMonth() + 1)}-${pad(dt.getDate())}T${pad(dt.getHours())}:${pad(dt.getMinutes())}`;
      saveComposerDraft();
    }));
}
$("cal-prev").onclick = () => { const d = new Date(S.calMonth); d.setMonth(d.getMonth() - 1); S.calMonth = d; renderCalendar(); };
$("cal-next").onclick = () => { const d = new Date(S.calMonth); d.setMonth(d.getMonth() + 1); S.calMonth = d; renderCalendar(); };
$("cal-today").onclick = () => { S.calMonth = null; renderCalendar(); };

function renderUpcoming() {
  const up = S.posts.filter((p) => p.status === "scheduled")
    .sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || "")).slice(0, 6);
  $("upcoming").innerHTML = up.length ? `<table><tr><th>When</th><th>Platforms</th><th>Post</th><th></th></tr>
    ${up.map((p) => `<tr class="clickable" onclick="postModal('${p.id}')"><td class="muted small">${fmtWhen(p.scheduled_at)}</td>
      <td>${platformDots(p.platforms)}</td>
      <td>${esc(p.text.slice(0, 60))}${p.tag ? ` <span class="chip">#${esc(p.tag)}</span>` : ""}</td>
      <td><button class="btn danger small" onclick="event.stopPropagation();cancelPost('${p.id}')">cancel</button></td></tr>`).join("")}</table>`
    : `<div class="empty">Nothing scheduled — hit “New post” 🚀</div>`;
}
window.cancelPost = async (id) => { await api(`/api/posts/${id}`, { method: "DELETE" }); render(); };

/* ---------------------------------------------------------------- queue */
function renderQueue() {
  const filter = $("queue-filter").value;
  const rows = (filter ? S.posts.filter((p) => p.status === filter) : S.posts);
  $("queue-table").innerHTML = `<tr><th>Status</th><th>When</th><th>Platforms</th><th>Text</th><th>Results</th><th></th></tr>` +
    (rows.length ? rows.map((p) => `<tr class="clickable" onclick="postModal('${p.id}')">
      <td>${statusChip(p.status)}</td>
      <td class="muted small">${fmtWhen(p.scheduled_at || p.published_at)}</td>
      <td>${platformDots(p.platforms)}</td>
      <td style="max-width:280px">${esc(p.text.slice(0, 90))}${p.tag ? `<br><span class="chip">#${esc(p.tag)}</span>` : ""}</td>
      <td class="small">${Object.entries(p.results || {}).map(([pl, r]) =>
        `${platform(pl).icon} ${r.ok ? "✅" : "❌ " + esc((r.error || "").slice(0, 40))}`).join("<br>") || "—"}</td>
      <td style="white-space:nowrap">
        ${p.status === "scheduled" ? `<button class="btn small" onclick="event.stopPropagation();pubNow('${p.id}')">publish</button> ` : ""}
        ${["failed", "partial"].includes(p.status) ? `<button class="btn ghost small" onclick="event.stopPropagation();retry('${p.id}')">retry</button> ` : ""}
        <button class="btn danger small" onclick="event.stopPropagation();delPost('${p.id}')">delete</button>
      </td></tr>`).join("") : `<tr><td colspan="6" class="empty">No posts yet</td></tr>`);
}
$("queue-filter").onchange = renderQueue;
$("tick-now").onclick = async () => { const r = await api("/api/scheduler/tick", { method: "POST" }); toast(`Processed ${r.processed} due post(s)`); render(); };
window.pubNow = async (id) => { await api(`/api/posts/${id}/publish`, { method: "POST" }); render(); };
window.retry = async (id) => { await api(`/api/posts/${id}/retry`, { method: "POST" }); render(); };
window.delPost = async (id) => { await api(`/api/posts/${id}`, { method: "DELETE" }); closeModal(); render(); };

/* ------------------------------------------------------- post detail modal */
window.postModal = (id) => {
  const p = S.posts.find((x) => x.id === id); if (!p) return;
  const results = Object.entries(p.results || {}).map(([pl, r]) => `
    <div class="prow ${r.ok ? "ok" : "err"}">
      <strong>${platform(pl).icon} ${esc(platform(pl).display_name)}</strong>
      <span class="muted small">${r.ok ? "✅ published" : "❌ failed"}</span>
      ${r.url ? `<a href="${esc(r.url)}" target="_blank" class="small">${esc(r.url.slice(0, 60))} ↗</a>` : ""}
      ${r.remote_id ? `<span class="muted small mono">${esc(r.remote_id.slice(0, 60))}</span>` : ""}
      ${r.error ? `<div class="small" style="color:var(--danger)">${esc(r.error)}</div>` : ""}
    </div>`).join("");
  const editable = ["scheduled", "draft"].includes(p.status);
  const canRemote = Object.values(p.results || {}).some((r) => r.ok && r.remote_id);
  $("modal").innerHTML = `
    <h2><span>Post detail ${statusChip(p.status)}</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="detail-text">${esc(p.text)}</div>
    <div class="detail-meta">
      <span>${platformDots(p.platforms)}</span>
      ${p.tag ? `<span class="chip">#${esc(p.tag)}</span>` : ""}
      ${p.scheduled_at ? `<span class="muted small">scheduled ${fmtWhen(p.scheduled_at)}</span>` : ""}
      ${p.published_at ? `<span class="muted small">published ${fmtWhen(p.published_at)}</span>` : ""}
      ${p.recurrence ? `<span class="muted small mono">repeat: ${esc(JSON.stringify(p.recurrence))}</span>` : ""}
    </div>
    ${p.media && p.media.length ? `<div class="detail-meta"><span class="muted small">media:</span> ${p.media.map((m) => `<a class="small" href="${esc(m)}" target="_blank">${esc(m.slice(0, 40))}</a>`).join(" · ")}</div>` : ""}
    <h3 style="margin-top:14px">Per-platform results</h3>
    ${results || `<div class="muted small">not published yet</div>`}
    <div class="actions" style="flex-wrap:wrap">
      ${editable ? `<button class="btn" onclick="editPost('${p.id}')">✏️ Edit</button>` : ""}
      ${p.status === "scheduled" ? `<button class="btn ghost" onclick="pubNow('${p.id}')">Publish now</button>` : ""}
      ${["failed", "partial"].includes(p.status) ? `<button class="btn ghost" onclick="retry('${p.id}')">Retry</button>` : ""}
      ${canRemote ? `<button class="btn ghost" onclick="delRemote('${p.id}')">🗑 Delete on platforms</button>` : ""}
      <button class="btn danger" onclick="delPost('${p.id}')">Delete post</button>
    </div>`;
  $("modal-back").classList.add("show");
};
window.delRemote = async (id) => {
  if (!confirm("Delete this post from the remote platforms too?")) return;
  try {
    const r = await api(`/api/posts/${id}/remote`, { method: "POST" });
    toast("Remote delete: " + Object.entries(r.outcomes).map(([k, v]) => `${k}=${v}`).join(", "));
    render();
  } catch (e) { toast("Remote delete failed: " + e.message); }
};

window.editPost = (id) => {
  const p = S.posts.find((x) => x.id === id); if (!p) return;
  $("modal").innerHTML = `
    <h2><span>✏️ Edit post</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="field"><label>Text</label><textarea id="ep-text" style="min-height:120px">${esc(p.text)}</textarea></div>
    <div class="field"><label>Schedule (local time, leave empty to clear)</label>
      <input id="ep-when" type="datetime-local" value="${p.scheduled_at ? localInput(p.scheduled_at) : ""}" /></div>
    <div class="field"><label>Tag</label><input id="ep-tag" value="${esc(p.tag || "")}" /></div>
    <div class="actions">
      <button class="btn ghost" onclick="closeModal()">Cancel</button>
      <button class="btn" onclick="saveEdit('${p.id}')">Save changes</button>
    </div>`;
};
window.saveEdit = async (id) => {
  try {
    const body = { text: $("ep-text").value, tag: $("ep-tag").value || null };
    const when = $("ep-when").value;
    body.scheduled_at = when ? new Date(when).toISOString() : null;
    await api(`/api/posts/${id}`, { method: "PATCH", body: JSON.stringify(body) });
    closeModal(); toast("Post updated"); render();
  } catch (e) { toast("Save failed: " + e.message); }
};
function localInput(iso) {
  const d = new Date(iso); const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}T${pad(d.getHours())}:${pad(d.getMinutes())}`;
}

/* ------------------------------------------------------------- composer */
const DRAFT_KEY = "sb_composer";
function readDraft() { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || "{}"); } catch { return {}; } }
function saveComposerDraft() {
  const d = {
    text: $("c-text").value, media: $("c-media").value, tag: $("c-tag").value,
    signature: $("c-signature").value, when: $("c-when").value,
    repeat: $("c-repeat").value, webhook: $("c-webhook").value,
    picked: pickedPlatforms(),
  };
  localStorage.setItem(DRAFT_KEY, JSON.stringify(d));
}
function clearComposerDraft() {
  localStorage.removeItem(DRAFT_KEY);
  ["c-text", "c-media", "c-tag", "c-signature", "c-when", "c-webhook"].forEach((id) => $(id).value = "");
  $("c-repeat").value = "";
  document.querySelectorAll(".ppick.on").forEach((el) => el.classList.remove("on"));
  updateCounter();
}

function renderComposer() {
  const wrap = $("c-platforms");
  const sig = S.platforms.map((p) => p.name + ":" + p.configured).join("|");
  if (sig !== S.platformsSig || !wrap.dataset.built) {
    wrap.dataset.built = "1"; S.platformsSig = sig;
    wrap.innerHTML = S.platforms.map((p) =>
      `<div class="ppick" data-p="${p.name}" style="${p.configured ? "" : "opacity:.55"}">
        <span>${p.icon}</span><span>${esc(p.display_name)}</span></div>`).join("");
    wrap.querySelectorAll(".ppick").forEach((el) =>
      el.addEventListener("click", () => { el.classList.toggle("on"); saveComposerDraft(); updateCounter(); }));
    const draft = readDraft();
    if (draft.picked) {
      const names = new Set(draft.picked);
      wrap.querySelectorAll(".ppick").forEach((el) => el.classList.toggle("on", names.has(el.dataset.p)));
    }
  }
}
function pickedPlatforms() {
  return [...document.querySelectorAll(".ppick.on")].map((el) => el.dataset.p);
}
function updateCounter() {
  const picked = pickedPlatforms().map(platform);
  const limit = picked.length ? Math.min(...picked.map((p) => p.max_length || Infinity)) : null;
  const len = $("c-text").value.length;
  $("c-counter").textContent = limit ? `${len} / ${limit} chars` : `${len} chars`;
  $("c-counter").classList.toggle("over", limit != null && len > limit);
}
$("c-text").addEventListener("input", () => { updateCounter(); saveComposerDraft(); });
["c-media", "c-tag", "c-signature", "c-when", "c-repeat", "c-webhook"].forEach((id) =>
  $(id).addEventListener("input", saveComposerDraft));
$("c-text").addEventListener("keydown", (e) => {
  if ((e.ctrlKey || e.metaKey) && e.key === "Enter") { e.preventDefault(); $("c-send-now").click(); }
});
$("new-post-btn").onclick = () => setView("composer");

function composerBody(scheduledIso) {
  return {
    text: $("c-text").value,
    platforms: pickedPlatforms(),
    media: $("c-media").value.split("\n").map((s) => s.trim()).filter(Boolean),
    tag: $("c-tag").value || null,
    signature: $("c-signature").value || null,
    webhook_url: $("c-webhook").value || null,
    scheduled_at: scheduledIso,
    recurrence: repeatValue(),
  };
}
function repeatValue() {
  const v = $("c-repeat").value; if (!v) return null;
  if (v.startsWith("interval:")) return { type: "interval", value: +v.split(":")[1] };
  return { type: "cron", value: v === "daily" ? "0 9 * * *" : "0 9 * * 1" };
}
function localToIso(el) {
  const v = el.value; if (!v) return null;
  const d = new Date(v); return isNaN(d) ? null : d.toISOString();
}
$("c-send-now").onclick = async () => {
  try {
    const body = composerBody(null);
    if (!body.platforms.length) return toast("Pick at least one platform");
    const post = await api("/api/posts", { method: "POST", body: JSON.stringify({ ...body, publish_now: true }) });
    toast(post.status === "published" ? "🎉 Published!" : `Finished with status: ${post.status}`);
    clearComposerDraft();
    setView("queue");
  } catch (e) { toast("Error: " + e.message); }
};
$("c-schedule").onclick = async () => {
  try {
    const iso = localToIso($("c-when"));
    if (!iso) return toast("Pick a date & time first");
    const body = composerBody(iso);
    if (!body.platforms.length) return toast("Pick at least one platform");
    await api("/api/posts", { method: "POST", body: JSON.stringify(body) });
    toast("Scheduled ✅"); clearComposerDraft();
    setView("calendar");
  } catch (e) { toast("Error: " + e.message); }
};
$("c-ai").onclick = async () => {
  const topic = $("c-text").value.trim();
  if (!topic) return toast("Write a topic in the box first");
  $("c-ai").textContent = "… thinking";
  try {
    const r = await api("/api/generate", { method: "POST", body: JSON.stringify({ topic, n: 3 }) });
    $("c-drafts").innerHTML = r.drafts.map((d, i) =>
      `<div class="draft" data-i="${i}">${esc(d.text)}</div>`).join("");
    $("c-drafts").querySelectorAll(".draft").forEach((el) =>
      el.addEventListener("click", () => {
        $("c-text").value = r.drafts[+el.dataset.i].text; updateCounter(); saveComposerDraft();
        $("c-drafts").innerHTML = ""; toast("Draft loaded");
      }));
  } catch (e) { toast("AI error: " + e.message); }
  $("c-ai").textContent = "✨ AI drafts";
};

/* -------------------------------------------------------------- accounts */
function renderAccounts() {
  const byName = Object.fromEntries(S.accounts.map((a) => [a.platform, a]));
  $("acct-grid").innerHTML = S.platforms.map((p) => {
    const acc = byName[p.name];
    const configured = p.configured;
    return `<div class="card acct-card" style="margin:0" onclick="acctModal('${p.name}')">
      <div class="head">
        <div class="iconwrap" style="color:${p.color}">${p.icon}</div>
        <div><strong>${esc(p.display_name)}</strong><br>
          <span class="muted small">${configured ? (esc(acc?.label) || "connected") : "not connected"}</span></div>
      </div>
      <div>${configured ? statusChip("published").replace("published", "connected") : statusChip("draft").replace("draft", "connect")}</div>
    </div>`;
  }).join("");
}
window.acctModal = (name) => {
  const p = platform(name);
  const acc = S.accounts.find((a) => a.platform === name) || { config: {}, label: "" };
  const connected = !!acc.platform;
  $("modal").innerHTML = `
    <h2><span>${p.icon} ${esc(p.display_name)}</span><button class="close" onclick="closeModal()">✕</button></h2>
    <p class="muted small" style="margin:6px 0 4px">${p.auth_fields.length ? "Enter credentials (stored locally in your DB):" : "No credentials needed for this platform."}</p>
    ${p.auth_fields.map((f) => `
      <div class="field"><label>${esc(f.label)}${f.required ? " *" : ""}${f.help ? ` — ${esc(f.help)}` : ""}</label>
      <input id="af-${esc(f.key)}" type="${f.secret ? "password" : "text"}" value="${esc(String(acc.config[f.key] ?? ""))}" /></div>`).join("")}
    <div class="field"><label>Label (nickname)</label><input id="af-__label" value="${esc(acc.label || "")}" /></div>
    <div class="field"><label>Default signature (appended to posts)</label><input id="af-__signature" value="${esc(acc.config.signature ?? "")}" /></div>
    <div class="actions" style="flex-wrap:wrap">
      <a class="btn ghost small" target="_blank" href="${p.docs_url}">docs ↗</a>
      <button class="btn ghost" onclick="verifyAcct('${name}')">Verify</button>
      <button class="btn" onclick="saveAcct('${name}')">Save</button>
      ${connected ? `<button class="btn danger" onclick="delAcct('${name}')">Disconnect</button>` : ""}
    </div>
    <div class="small muted" id="af-msg" style="margin-top:8px"></div>`;
  $("modal-back").classList.add("show");
};
window.closeModal = () => $("modal-back").classList.remove("show");
$("modal-back").addEventListener("click", (e) => { if (e.target === $("modal-back")) closeModal(); });

window.saveAcct = async (name) => {
  const p = platform(name);
  const config = {};
  p.auth_fields.forEach((f) => { const v = $(`af-${f.key}`).value.trim(); if (v) config[f.key] = v; });
  const sig = $("af-__signature").value.trim(); if (sig) config.signature = sig;
  try {
    const r = await api("/api/accounts", { method: "POST",
      body: JSON.stringify({ platform: name, label: $("af-__label").value, config }) });
    $("af-msg").textContent = r.verified ? "✅ " + r.verify_message : "⚠️ saved, but verify failed: " + r.verify_message;
    toast("Account saved");
    render();
  } catch (e) { toast("Error: " + e.message); }
};
window.verifyAcct = async (name) => {
  await saveAcct(name);
  try {
    const r = await api(`/api/accounts/${name}/verify`, { method: "POST" });
    $("af-msg").textContent = (r.ok ? "✅ " : "❌ ") + r.message;
  } catch (e) { $("af-msg").textContent = "❌ " + e.message; }
};
window.delAcct = async (name) => {
  if (!confirm(`Disconnect ${platform(name).display_name}? Credentials will be removed.`)) return;
  await api(`/api/accounts/${name}`, { method: "DELETE" });
  closeModal(); toast("Account disconnected"); render();
};

/* ------------------------------------------------------------------- bot */
function renderBot() {
  $("bot-table").innerHTML = `<tr><th>Rule</th><th>Platform</th><th>Action</th><th>Trigger</th>
    <th>Last run</th><th>Stats</th><th></th></tr>` +
    (S.rules.length ? S.rules.map((r) => {
      const p = platform(r.platform);
      return `<tr class="${r.enabled ? "" : "dim"}">
      <td><strong>${esc(r.name)}</strong> ${r.dry_run ? '<span class="chip">dry-run</span>' : '<span class="chip s-published">live</span>'}
        ${r.enabled ? "" : '<span class="chip s-cancelled">paused</span>'}</td>
      <td>${p.icon} ${esc(p.display_name)}</td>
      <td class="mono">${esc(r.action)}</td>
      <td class="mono">${esc(r.trigger_type)}: ${esc(r.trigger_value)}</td>
      <td class="small muted">${r.last_run ? fmtWhen(r.last_run) : "never"}<br>
        ${r.last_result ? esc(JSON.stringify({ found: r.last_result.found, acted: r.last_result.acted, error: r.last_result.error })) : ""}</td>
      <td class="small">${r.total_actions} actions</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="runRule('${r.id}')">run</button>
        <button class="btn ghost small" onclick="editRule('${r.id}')">edit</button>
        <button class="btn ghost small" onclick="toggleRule('${r.id}')">${r.enabled ? "pause" : "resume"}</button>
        <button class="btn danger small" onclick="delRule('${r.id}')">delete</button>
      </td></tr>`;
    }).join("") : `<tr><td colspan="7" class="empty">No rules yet — try “comment on #python posts on Bluesky”</td></tr>`);
}
window.toggleRule = async (id) => {
  const r = S.rules.find((x) => x.id === id); if (!r) return;
  await api(`/api/bot/rules/${id}`, { method: "PATCH", body: JSON.stringify({ ...r, enabled: !r.enabled }) });
  toast(r.enabled ? "Rule paused" : "Rule resumed"); render();
};
$("bot-new").onclick = () => ruleModal(null);
window.editRule = (id) => ruleModal(S.rules.find((x) => x.id === id) || null);
function ruleModal(rule) {
  const searchable = S.platforms.filter((p) => p.capabilities.includes("search"));
  const r = rule || {};
  $("modal").innerHTML = `
    <h2><span>${rule ? "✏️ Edit rule" : "New automation rule"}</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="form-grid">
      <div><label>Name</label><input id="br-name" value="${esc(r.name || "My rule")}" /></div>
      <div><label>Platform</label><select id="br-platform">${searchable.map((p) => `<option value="${p.name}" ${p.name === r.platform ? "selected" : ""}>${p.icon} ${esc(p.display_name)}</option>`).join("")}</select></div>
      <div><label>Action</label><select id="br-action">
        ${["like", "comment", "follow", "repost"].map((a) => `<option value="${a}" ${a === r.action ? "selected" : ""}>${a}</option>`).join("")}</select></div>
      <div><label>Trigger</label><select id="br-ttype"><option value="keyword" ${r.trigger_type !== "hashtag" ? "selected" : ""}>keyword</option><option value="hashtag" ${r.trigger_type === "hashtag" ? "selected" : ""}>hashtag</option></select></div>
      <div style="grid-column:1/-1"><label>Trigger value</label><input id="br-tvalue" placeholder="e.g. python or opensource" value="${esc(r.trigger_value || "")}" /></div>
      <div style="grid-column:1/-1"><label>Comment template (use {topic})</label><input id="br-comment" placeholder="Nice take on {topic}!" value="${esc(r.comment_template || "")}" /></div>
      <div><label>Max per run</label><input id="br-perrun" type="number" min="1" max="50" value="${r.limit_per_run ?? 5}" /></div>
      <div><label>Max per hour</label><input id="br-perhour" type="number" min="1" max="500" value="${r.limit_per_hour ?? 20}" /></div>
      <div><label>Mode</label><select id="br-mode"><option value="dry" ${r.dry_run !== false ? "selected" : ""}>dry-run (safe)</option><option value="live" ${r.dry_run === false ? "selected" : ""}>live</option></select></div>
      <div><label>Status</label><select id="br-status"><option value="on" ${r.enabled !== false ? "selected" : ""}>enabled</option><option value="off" ${r.enabled === false ? "selected" : ""}>paused</option></select></div>
    </div>
    <div class="actions"><button class="btn" onclick="saveRule('${rule ? rule.id : ""}')">${rule ? "Save rule" : "Create rule"}</button></div>`;
  $("modal-back").classList.add("show");
}
window.saveRule = async (id) => {
  try {
    const body = {
      name: $("br-name").value, platform: $("br-platform").value, action: $("br-action").value,
      trigger_type: $("br-ttype").value, trigger_value: $("br-tvalue").value,
      comment_template: $("br-comment").value,
      limit_per_run: +$("br-perrun").value || 5, limit_per_hour: +$("br-perhour").value || 20,
      dry_run: $("br-mode").value !== "live", enabled: $("br-status").value === "on",
    };
    await api(`/api/bot/rules${id ? "/" + id : ""}`, { method: id ? "PATCH" : "POST", body: JSON.stringify(body) });
    closeModal(); toast(id ? "Rule updated" : "Rule created (dry-run)"); render();
  } catch (e) { toast("Error: " + e.message); }
};
window.runRule = async (id) => {
  toast("Running rule…");
  try {
    const r = await api(`/api/bot/rules/${id}/run`, { method: "POST" });
    toast(r.ok ? `Rule ran: found ${r.found}, acted ${r.acted}${r.dry_run ? " (dry-run)" : ""}` : "Failed: " + (r.error || "see details"));
  } catch (e) { toast("Failed: " + e.message); }
  render();
};
$("bot-run-all").onclick = async () => {
  try { await api("/api/bot/run", { method: "POST" }); toast("All enabled rules executed"); render(); }
  catch (e) { toast("Error: " + e.message); }
};
window.delRule = async (id) => {
  if (!confirm("Delete this rule?")) return;
  await api(`/api/bot/rules/${id}`, { method: "DELETE" }); render();
};

/* -------------------------------------------------------------- analytics */
async function renderAnalytics() {
  const a = await api("/api/analytics/summary");
  const engagement = Object.values(a.engagement || {}).reduce((acc, m) => {
    for (const [k, v] of Object.entries(m)) acc[k] = (acc[k] || 0) + v; return acc; }, {});
  const cards = [
    ["Total posts", a.total_posts],
    ["Published", (a.by_status.published || 0) + (a.by_status.partial || 0)],
    ["Scheduled", a.by_status.scheduled || 0],
    ["Failed", a.by_status.failed || 0],
    ["Likes tracked", engagement.likes || 0],
    ["Shares tracked", engagement.shares || 0],
    ["Comments tracked", engagement.comments || 0],
    ["Impressions", engagement.impressions || 0],
  ];
  $("an-stats").innerHTML = cards.map(([l, n]) => `<div class="card stat" style="margin:0">
    <div class="num">${n}</div><div class="lbl">${l}</div></div>`).join("");

  const perPlatform = Object.entries(a.engagement || {}).map(([name, m]) =>
    [name, (m.likes || 0) + (m.shares || 0) + (m.comments || 0) + (m.impressions || 0)]);
  const max = Math.max(1, ...perPlatform.map(([, v]) => v));
  $("an-bars").innerHTML = perPlatform.length ? perPlatform.map(([name, v]) => {
    const p = platform(name);
    return `<div class="bar-row"><span>${p.icon} ${esc(p.display_name)}</span>
      <div class="bar"><div style="width:${(100 * v) / max}%;background:${p.color}"></div></div>
      <span class="muted">${v}</span></div>`; }).join("")
    : `<div class="empty">No metrics yet — publish something and hit “Refresh metrics”</div>`;

  $("an-table").innerHTML = `<tr><th>Post</th><th>Platform</th><th>Likes</th><th>Shares</th><th>Comments</th><th>Views</th><th>Captured</th></tr>` +
    (a.latest_metrics.length ? a.latest_metrics.slice(0, 25).map((m) => {
      const post = S.posts.find((p) => p.id === m.post_id);
      return `<tr><td style="max-width:260px">${esc((post?.text || m.post_id).slice(0, 50))}</td>
      <td>${platform(m.platform).icon}</td><td>${m.metrics.likes ?? "—"}</td><td>${m.metrics.shares ?? "—"}</td>
      <td>${m.metrics.comments ?? "—"}</td><td>${m.metrics.impressions ?? "—"}</td>
      <td class="muted small">${fmtWhen(m.captured_at)}</td></tr>`; }).join("")
    : `<tr><td colspan="7" class="empty">Nothing tracked yet</td></tr>`);
}
$("an-refresh").onclick = async () => { const r = await api("/api/analytics/refresh", { method: "POST" }); toast(`Updated ${r.updated} post metrics`); renderAnalytics(); };

/* ----------------------------------------------------------------- events */
async function renderEvents() {
  const events = await api("/api/events?limit=100");
  $("events-table").innerHTML = `<tr><th>Time</th><th>Type</th><th>Message</th></tr>` +
    (events.length ? events.map((e) => `<tr><td class="muted small">${fmtWhen(e.ts)}</td>
      <td class="mono">${esc(e.type)}</td><td>${esc(e.message)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty">No activity yet</td></tr>`);
}

/* ------------------------------------------------------------------ boot */
render();
setInterval(() => { if (!document.hidden) loadAll().then(() => {
  if (S.view === "calendar") { renderCalendar(); renderUpcoming(); }
  if (S.view === "queue") renderQueue();
}); }, 20000);