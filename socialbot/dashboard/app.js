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
    accounts: "Accounts", bot: "Growth bot", agents: "Agents", analytics: "Analytics",
    insights: "Insights", review: "Review", events: "Activity" }[view];
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
  if (S.view === "agents") renderAgents();
  if (S.view === "analytics") renderAnalytics();
  if (S.view === "insights") renderInsights();
  if (S.view === "review") renderReview();
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
  const guide = p.guide && p.guide.length
    ? `<details class="guide"><summary>📖 How to connect — step by step</summary>
       <ol>${p.guide.map((s) => `<li>${esc(s)}</li>`).join("")}</ol></details>`
    : "";
  const oauthBtn = p.oauth
    ? `<button class="btn oauth" onclick="oauthConnect('${name}')">🔑 Connect with ${esc(p.oauth.provider)}</button>
       <p class="muted small">Paste your OAuth ${esc(p.oauth.client_id_key || "client_id")}${p.oauth.client_secret_key ? " and " + esc(p.oauth.client_secret_key) : ""} below, then click — you'll authorize in a popup, no tokens to copy.</p>
       <p class="muted small" style="background:var(--bg3);border-radius:8px;padding:8px 10px;word-break:break-all"><strong>Register this exact redirect URI in your ${esc(p.oauth.provider)} app:</strong><br>${esc(location.origin)}/api/accounts/${name}/oauth/callback</p>`
    : "";
  $("modal").innerHTML = `
    <h2><span>${p.icon} ${esc(p.display_name)}</span><button class="close" onclick="closeModal()">✕</button></h2>
    ${guide}
    ${oauthBtn}
    <p class="muted small" style="margin:6px 0 4px">${p.auth_fields.length ? "Credentials (stored locally in your DB):" : "No credentials needed for this platform."}</p>
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
window.oauthConnect = async (name) => {
  const p = platform(name);
  const o = p.oauth;
  const cid = $(`af-${o.client_id_key || "client_id"}`)?.value.trim() || "";
  const sec = $(`af-${o.client_secret_key || "client_secret"}`)?.value.trim() || "";
  if (!cid) { $("af-msg").textContent = "❌ Paste your OAuth client id first (see the guide above)."; return; }
  let r;
  try {
    r = await api(`/api/accounts/${name}/oauth/start`, { method: "POST",
      body: JSON.stringify({ client_id: cid, client_secret: sec }) });
  } catch (e) { $("af-msg").textContent = "❌ " + e.message; return; }
  window.open(r.auth_url, "socialbot-oauth", "width=640,height=720");
  $("af-msg").textContent = "⏳ Authorize in the popup — this page refreshes automatically…";
};
window.addEventListener("message", (e) => {
  if (e.data && e.data.type === "socialbot-oauth-done") {
    toast(`${platform(e.data.platform)?.display_name || e.data.platform} connected`);
    render();
  }
});
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

/* ------------------------------------------------------------------- agents */
async function renderAgents() {
  const [monitors, inboxRules, feeds] = await Promise.all([
    api("/api/monitors"), api("/api/inbox"), api("/api/feeds")]);
  S.monitors = monitors; S.inboxRules = inboxRules; S.feeds = feeds;

  const mons = monitors.filter((m) => !m.competitors);
  const cmps = monitors.filter((m) => m.competitors);
  $("ag-mon-table").innerHTML = `<tr><th>Monitor</th><th>Platform</th><th>Action</th><th>Query</th><th>Last run</th><th></th></tr>` +
    (mons.length ? mons.map((m) => `
      <tr class="${m.enabled ? "" : "dim"}">
        <td><strong>${esc(m.name)}</strong> ${m.dry_run ? '<span class="chip">dry-run</span>' : '<span class="chip s-published">live</span>'}</td>
        <td>${platform(m.platform).icon} ${esc(platform(m.platform).display_name)}</td>
        <td class="mono">${esc(m.action)}</td>
        <td class="mono">${esc(m.query)}</td>
        <td class="small muted">${m.last_run ? fmtWhen(m.last_run) : "never"}<br>${m.last_result ? `${m.last_result.acted} acted / ${m.last_result.found} found` : ""}</td>
        <td style="white-space:nowrap">
          <button class="btn small" onclick="runMon('${m.id}')">run</button>
          <button class="btn danger small" onclick="delMon('${m.id}')">delete</button>
        </td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">No monitors — watch a hashtag and let the agent engage for you</td></tr>`);

  $("ag-cmp-table").innerHTML = `<tr><th>Watch</th><th>Platform</th><th>Competitors</th><th>Last run</th><th></th></tr>` +
    (cmps.length ? cmps.map((c) => `
      <tr class="${c.enabled ? "" : "dim"}">
        <td><strong>${esc(c.name)}</strong> ${c.create_drafts ? '<span class="chip">auto-draft</span>' : ""}</td>
        <td>${platform(c.platform).icon} ${esc(platform(c.platform).display_name)}</td>
        <td class="mono">${esc(c.competitors.join(", "))}</td>
        <td class="small muted">${c.last_run ? fmtWhen(c.last_run) : "never"}<br>${c.last_result ? `${c.last_result.recommendations} gaps / ${c.last_result.drafts_created} drafts` : ""}</td>
        <td style="white-space:nowrap">
          <button class="btn small" onclick="runCmp('${c.id}')">run</button>
          <button class="btn danger small" onclick="delMon('${c.id}')">delete</button>
        </td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No competitor watches yet</td></tr>`);

  $("ag-inb-table").innerHTML = `<tr><th>Responder</th><th>Platform</th><th>Intents</th><th>Last run</th><th></th></tr>` +
    (inboxRules.length ? inboxRules.map((r) => `
      <tr class="${r.enabled ? "" : "dim"}">
        <td><strong>${esc(r.name)}</strong> ${r.auto_reply ? "" : '<span class="chip">no auto-reply</span>'}</td>
        <td>${platform(r.platform).icon} ${esc(platform(r.platform).display_name)}</td>
        <td class="mono">${esc(r.intents.join(", "))}</td>
        <td class="small muted">${r.last_run ? fmtWhen(r.last_run) : "never"}<br>${r.last_result ? `${r.last_result.replied} replied / ${r.last_result.escalated} escalated` : ""}</td>
        <td style="white-space:nowrap">
          <button class="btn small" onclick="runInb('${r.id}')">run</button>
          <button class="btn danger small" onclick="delInb('${r.id}')">delete</button>
        </td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No responders — auto-answer pricing/demo/thanks DMs</td></tr>`);

  $("ag-feed-table").innerHTML = `<tr><th>Source</th><th>Kind</th><th>Target</th><th>Last run</th><th></th></tr>` +
    (feeds.length ? feeds.map((f) => `
      <tr class="${f.enabled ? "" : "dim"}">
        <td><strong>${esc(f.name)}</strong> ${f.auto_draft ? '<span class="chip">auto-draft</span>' : ""}</td>
        <td class="mono">${esc(f.kind)}</td>
        <td class="mono">${esc(f.url || `${f.items.length} items`)}${f.target_platforms.length ? " → " + esc(f.target_platforms.join(",")) : ""}</td>
        <td class="small muted">${f.last_run ? fmtWhen(f.last_run) : "never"}<br>${f.last_result ? `${f.last_result.new} new / ${f.last_result.drafts} drafts` : ""}</td>
        <td style="white-space:nowrap">
          <button class="btn small" onclick="pullFeed('${f.id}')">pull</button>
          <button class="btn danger small" onclick="delFeed('${f.id}')">delete</button>
        </td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No content sources — add an RSS feed to auto-generate drafts</td></tr>`);
  renderMonitoring();
}
$("ag-run-all").onclick = async () => { try { const r = await api("/api/agents/run", { method: "POST" }); toast(`Agents done: ${r.mentions.length} mentions, ${r.inbox.length} inbox, ${r.competitors.length} competitors, ${r.trends.length} trends`); } catch (e) { toast("Error: " + e.message); } renderAgents(); };
$("ag-mon-new").onclick = () => monModal(null);
$("ag-cmp-new").onclick = () => cmpModal(null);
$("ag-inb-new").onclick = () => inbModal(null);
$("ag-feed-new").onclick = () => feedModal(null);
$("ag-mon-refresh").onclick = () => renderMonitoring();

async function renderMonitoring() {
  let stats = {}, agents = [], tasks = [], health = { components: {} };
  try {
    const [s, a, t, m] = await Promise.all([
      api("/api/agents"), api("/api/tasks?limit=20"), api("/api/tasks?limit=20"),
      api("/api/monitoring")]);
    stats = s.stats || {}; agents = s.agents || [];
    tasks = t.tasks || []; health = m.health || {};
  } catch (e) { toast("Monitoring refresh failed: " + e.message); }
  $("ag-stats").innerHTML = [
    stat("Active workers", stats.active_agents ?? "—"),
    stat("Pending tasks", stats.pending_tasks ?? "—"),
    stat("Completed today", stats.completed_today ?? "—"),
    stat("Failed today", stats.failed_today ?? "—")].join("");

  $("ag-workers").innerHTML = `<tr><th>Agent</th><th>Status</th><th>Heartbeat</th><th>Tasks done</th><th>Current task</th></tr>` +
    (agents.length ? agents.map((a) => `
      <tr class="${a.status === "active" ? "" : "dim"}">
        <td class="mono">${esc(a.agent_id)}</td>
        <td><span class="chip ${a.status === "active" ? "s-published" : "s-draft"}">${esc(a.status)}</span></td>
        <td class="small muted">${a.last_heartbeat ? fmtWhen(a.last_heartbeat) : "—"}</td>
        <td>${a.tasks_completed} ✓ / ${a.tasks_failed} ✗</td>
        <td class="small mono">${a.current_task ? esc(a.current_task) : "—"}</td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No workers registered yet</td></tr>`);

  $("ag-task-table").innerHTML = `<tr><th>Task</th><th>Type</th><th>Status</th><th>Priority</th><th>Retries</th><th>Claimed by</th></tr>` +
    (tasks.length ? tasks.map((t) => `
      <tr>
        <td class="mono">${esc(t.task_id)}</td>
        <td class="mono">${esc(t.task_type)}</td>
        <td><span class="chip">${esc(t.status)}</span></td>
        <td>${t.priority}</td>
        <td>${t.retry_count}/${t.max_retries}</td>
        <td class="small mono">${t.claimed_by ? esc(t.claimed_by) : "—"}</td></tr>`).join("")
    : `<tr><td colspan="6" class="empty">Queue is empty — enqueue work with <span class="mono">socialbot tasks enqueue --type publish</span></td></tr>`);

  const comps = health.components || {};
  $("ag-health").innerHTML = `<tr><th>Component</th><th>Status</th><th>Latency</th><th>Message</th></tr>` +
    (Object.keys(comps).length ? Object.keys(comps).map((k) => {
      const c = comps[k];
      const cls = c.status === "healthy" ? "s-published" : (c.status === "degraded" ? "s-scheduled" : "s-failed");
      return `<tr><td>${esc(c.component)}</td><td><span class="chip ${cls}">${esc(c.status)}</span></td>
        <td class="small">${c.latency_ms != null ? c.latency_ms + " ms" : "—"}</td>
        <td class="small muted">${esc(c.message)}</td></tr>`;
    }).join("")
    : `<tr><td colspan="4" class="empty">No health checks run yet</td></tr>`);
}

function stat(label, value) {
  return `<div class="stat"><div class="stat-value">${esc(String(value))}</div><div class="stat-label">${esc(label)}</div></div>`;
}
$("ag-feed-pull").onclick = async () => { for (const f of (S.feeds || [])) { await api(`/api/feeds/${f.id}/run`, { method: "POST" }); } toast("Feeds pulled"); renderAgents(); };
window.runMon = async (id) => { try { const r = await api(`/api/monitors/mention/${id}/run`, { method: "POST" }); toast(r.ok ? `Found ${r.found}, acted ${r.acted}` : "Failed: " + r.error); } catch (e) { toast("Error: " + e.message); } renderAgents(); };
window.runCmp = async (id) => { try { const r = await api(`/api/monitors/competitor/${id}/run`, { method: "POST" }); toast(`Found ${r.recommendations} gaps, ${r.drafts_created} drafts`); } catch (e) { toast("Error: " + e.message); } renderAgents(); };
window.runInb = async (id) => { try { const r = await api(`/api/inbox/${id}/run`, { method: "POST" }); toast(`Replied ${r.replied}, escalated ${r.escalated}`); } catch (e) { toast("Error: " + e.message); } renderAgents(); };
window.pullFeed = async (id) => { try { const r = await api(`/api/feeds/${id}/run`, { method: "POST" }); toast(`${r.new} new item(s), ${r.drafts} draft(s)`); } catch (e) { toast("Error: " + e.message); } renderAgents(); };
window.delMon = async (id) => { if (confirm("Delete this monitor/watch?")) { await api(`/api/monitors/${id}`, { method: "DELETE" }); renderAgents(); } };
window.delInb = async (id) => { if (confirm("Delete this responder?")) { await api(`/api/inbox/${id}`, { method: "DELETE" }); renderAgents(); } };
window.delFeed = async (id) => { if (confirm("Delete this content source?")) { await api(`/api/feeds/${id}`, { method: "DELETE" }); renderAgents(); } };

function monModal(m) {
  m = m || {};
  $("modal").innerHTML = `
    <h2><span>${m.id ? "Edit" : "New"} mention monitor</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="form-grid">
      <div><label>Name</label><input id="mm-name" value="${esc(m.name || "")}" /></div>
      <div><label>Platform</label><select id="mm-platform">${S.platforms.filter((p) => p.capabilities.includes("search")).map((p) => `<option value="${p.name}" ${p.name === m.platform ? "selected" : ""}>${p.icon} ${esc(p.display_name)}</option>`).join("")}</select></div>
      <div><label>Query (hashtag / keyword / @mention)</label><input id="mm-query" value="${esc(m.query || "")}" /></div>
      <div><label>Action</label><select id="mm-action">${["like", "comment", "repost", "quote", "follow"].map((a) => `<option value="${a}" ${a === m.action ? "selected" : ""}>${a}</option>`).join("")}</select></div>
      <div style="grid-column:1/-1"><label>Comment template ({topic})</label><input id="mm-comment" placeholder="Thoughtful take on {topic}!" value="${esc(m.comment_template || "")}" /></div>
      <div><label>Max per run</label><input id="mm-run" type="number" value="${m.limit_per_run || 5}" /></div>
      <div><label>Mode</label><select id="mm-mode"><option value="dry" ${m.dry_run !== false ? "selected" : ""}>dry-run</option><option value="live" ${m.dry_run === false ? "selected" : ""}>live</option></select></div>
    </div>
    <div class="actions"><button class="btn" onclick="saveMon('${m.id || ""}')">Save monitor</button></div>`;
  $("modal-back").classList.add("show");
}
window.saveMon = async (id) => {
  const body = {
    name: $("mm-name").value || "monitor", platform: $("mm-platform").value,
    query: $("mm-query").value, action: $("mm-action").value,
    comment_template: $("mm-comment").value, limit_per_run: +$("mm-run").value || 5,
    dry_run: $("mm-mode").value !== "live",
  };
  try { await api(`/api/monitors/mention${id ? "/" + id : ""}`, { method: "POST", body: JSON.stringify(body) }); closeModal(); toast("Monitor saved"); renderAgents(); }
  catch (e) { toast("Error: " + e.message); }
};

function cmpModal(c) {
  c = c || {};
  $("modal").innerHTML = `
    <h2><span>${c.id ? "Edit" : "New"} competitor watch</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="form-grid">
      <div><label>Name</label><input id="cc-name" value="${esc(c.name || "")}" /></div>
      <div><label>Platform</label><select id="cc-platform">${S.platforms.filter((p) => p.capabilities.includes("search")).map((p) => `<option value="${p.name}" ${p.name === c.platform ? "selected" : ""}>${p.icon} ${esc(p.display_name)}</option>`).join("")}</select></div>
      <div style="grid-column:1/-1"><label>Competitor usernames (comma separated)</label><input id="cc-users" value="${esc((c.competitors || []).join(", "))}" /></div>
      <div style="grid-column:1/-1"><label>Your interests (comma separated, optional)</label><input id="cc-int" value="${esc(c.interests || "")}" /></div>
      <div><label>Auto-draft gap posts</label><select id="cc-draft"><option value="1" ${c.create_drafts !== false ? "selected" : ""}>yes</option><option value="0" ${c.create_drafts === false ? "selected" : ""}>no</option></select></div>
    </div>
    <div class="actions"><button class="btn" onclick="saveCmp('${c.id || ""}')">Save watch</button></div>`;
  $("modal-back").classList.add("show");
}
window.saveCmp = async (id) => {
  const body = {
    name: $("cc-name").value || "watch", platform: $("cc-platform").value,
    competitors: $("cc-users").value.split(",").map((s) => s.trim()).filter(Boolean),
    interests: $("cc-int").value, create_drafts: $("cc-draft").value === "1",
  };
  try { await api(`/api/monitors/competitor${id ? "/" + id : ""}`, { method: "POST", body: JSON.stringify(body) }); closeModal(); toast("Watch saved"); renderAgents(); }
  catch (e) { toast("Error: " + e.message); }
};

function inbModal(r) {
  r = r || {};
  $("modal").innerHTML = `
    <h2><span>${r.id ? "Edit" : "New"} inbox responder</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="form-grid">
      <div><label>Name</label><input id="ib-name" value="${esc(r.name || "")}" /></div>
      <div><label>Platform</label><select id="ib-platform">${S.platforms.filter((p) => p.capabilities.includes("inbox")).map((p) => `<option value="${p.name}" ${p.name === r.platform ? "selected" : ""}>${p.icon} ${esc(p.display_name)}</option>`).join("")}</select></div>
      <div style="grid-column:1/-1"><label>Intents to auto-reply (comma separated)</label><input id="ib-intents" value="${esc((r.intents || ["pricing", "demo", "thanks"]).join(", "))}" /></div>
      <div><label>Auto-reply</label><select id="ib-reply"><option value="1" ${r.auto_reply !== false ? "selected" : ""}>yes</option><option value="0" ${r.auto_reply === false ? "selected" : ""}>no</option></select></div>
      <div><label>Escalation webhook</label><input id="ib-hook" placeholder="https://… (complaints/unknowns)" value="${esc(r.escalate_webhook || "")}" /></div>
    </div>
    <div class="actions"><button class="btn" onclick="saveInb('${r.id || ""}')">Save responder</button></div>`;
  $("modal-back").classList.add("show");
}
window.saveInb = async (id) => {
  const body = {
    name: $("ib-name").value || "responder", platform: $("ib-platform").value,
    intents: $("ib-intents").value.split(",").map((s) => s.trim()).filter(Boolean),
    auto_reply: $("ib-reply").value === "1", escalate_webhook: $("ib-hook").value || null,
  };
  try { await api(`/api/inbox${id ? "/" + id : ""}`, { method: "POST", body: JSON.stringify(body) }); closeModal(); toast("Responder saved"); renderAgents(); }
  catch (e) { toast("Error: " + e.message); }
};

function feedModal(f) {
  f = f || {};
  $("modal").innerHTML = `
    <h2><span>${f.id ? "Edit" : "New"} content source</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="form-grid">
      <div><label>Name</label><input id="ff-name" value="${esc(f.name || "")}" /></div>
      <div><label>Kind</label><select id="ff-kind"><option value="rss" ${f.kind !== "curated" ? "selected" : ""}>RSS feed</option><option value="curated" ${f.kind === "curated" ? "selected" : ""}>Curated</option></select></div>
      <div style="grid-column:1/-1"><label>RSS URL</label><input id="ff-url" placeholder="https://blog.example.com/feed.xml" value="${esc(f.url || "")}" /></div>
      <div style="grid-column:1/-1"><label>Default platforms for drafts (comma separated)</label><input id="ff-targets" placeholder="telegram,linkedin" value="${esc((f.target_platforms || []).join(", "))}" /></div>
      <div><label>Drafts per pull</label><input id="ff-n" type="number" value="${f.n_drafts || 3}" /></div>
      <div><label>Auto-create drafts</label><select id="ff-auto"><option value="1" ${f.auto_draft !== false ? "selected" : ""}>yes</option><option value="0" ${f.auto_draft === false ? "selected" : ""}>no</option></select></div>
    </div>
    <div class="actions"><button class="btn" onclick="saveFeed('${f.id || ""}')">Save source</button></div>`;
  $("modal-back").classList.add("show");
}
window.saveFeed = async (id) => {
  const body = {
    name: $("ff-name").value || "feed", kind: $("ff-kind").value, url: $("ff-url").value.trim(),
    target_platforms: $("ff-targets").value.split(",").map((s) => s.trim()).filter(Boolean),
    n_drafts: +$("ff-n").value || 3, auto_draft: $("ff-auto").value === "1",
  };
  try { await api(`/api/feeds${id ? "/" + id : ""}`, { method: "POST", body: JSON.stringify(body) }); closeModal(); toast("Source saved"); renderAgents(); }
  catch (e) { toast("Error: " + e.message); }
};

/* ---------------------------------------------------------------- insights */
async function renderInsights() {
  const [adapt, safety, trends, profiles] = await Promise.all([
    api("/api/adapt/best-time"), api("/api/safety"), api("/api/trends?limit=20"),
    api("/api/profiles?limit=20")]);
  S.adapt = adapt; S.safety = safety; S.trends = trends; S.profiles = profiles;

  $("in-windows").innerHTML = adapt.windows && adapt.windows.length
    ? adapt.windows.map((w) => `<div class="card stat" style="margin:0">
        <div class="num">${adapt.windows_human[adapt.windows.indexOf(w)] || ""}</div>
        <div class="lbl">avg ${w.avg_engagement.toFixed(1)} · ${w.posts} posts</div></div>`).join("")
    : `<div class="empty" style="grid-column:1/-1">Not enough history yet — post a few times and refresh metrics (Analytics tab)</div>`;

  $("safety-platform").innerHTML = `<option value="">all platforms</option>` +
    S.platforms.map((p) => `<option>${p.name}</option>`).join("");
  $("in-safety").innerHTML = `<tr><th>Type</th><th>Platform</th><th>Username</th><th>Note</th><th></th></tr>` +
    (safety.length ? safety.map((r) => `<tr>
      <td><span class="chip ${r.list_type === "whitelist" ? "s-published" : "s-failed"}">${esc(r.list_type)}</span></td>
      <td class="mono">${esc(r.platform || "all")}</td>
      <td class="mono">@${esc(r.username)}</td>
      <td class="muted small">${esc(r.note)}</td>
      <td><button class="btn danger small" onclick="delSafety('${r.id}')">delete</button></td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">No rules — blacklist spammers, whitelist fans</td></tr>`);

  $("in-trends-table").innerHTML = `<tr><th>Topic</th><th>Platform</th><th>Captured</th></tr>` +
    (trends.length ? trends.map((t) => `<tr>
      <td><strong>${esc(t.topic)}</strong>${t.source ? ` <span class="chip">${esc(t.source)}</span>` : ""}</td>
      <td>${platform(t.platform).icon}</td>
      <td class="muted small">${fmtWhen(t.captured_at)}</td></tr>`).join("")
    : `<tr><td colspan="3" class="empty">No trends captured yet — hit “Capture trends”</td></tr>`);

  $("in-profiles").innerHTML = `<tr><th>User</th><th>Platform</th><th>Interests</th><th>Actions</th></tr>` +
    (profiles.length ? profiles.map((p) => `<tr>
      <td class="mono">@${esc(p.username)}</td>
      <td>${platform(p.platform).icon}</td>
      <td class="small">${esc((p.data.interests || []).slice(0, 4).join(", ")) || "—"}</td>
      <td class="small">${esc(JSON.stringify(p.data.actions || {}))}</td></tr>`).join("")
    : `<tr><td colspan="4" class="empty">No profiles yet — run the bot or agents to build them</td></tr>`);
}
$("in-analyze").onclick = async () => {
  const text = $("in-text").value.trim(); if (!text) return toast("Paste some text first");
  try {
    const r = await api("/api/analyze", { method: "POST", body: JSON.stringify({ text }) });
    $("in-result").innerHTML = `<div class="prow ok"><strong>${esc(r.label)}</strong>
      <span class="muted small">sentiment ${r.sentiment.toFixed(2)} · intent: ${esc(r.intent)} · topics: ${esc(r.topics.join(", ") || "—")}</span></div>
      <div class="detail-text">${esc(r.suggested_reply)}</div>`;
  } catch (e) { toast("Error: " + e.message); }
};
$("in-vibe").onclick = async () => {
  const text = $("in-text").value.trim(); if (!text) return toast("Paste some text first");
  try {
    const r = await api("/api/adapt/vibe", { method: "POST", body: JSON.stringify({ text }) });
    $("in-result").innerHTML = `<div class="prow ok"><strong>Style fit: ${r.fit}/100</strong>
      <span class="muted small">compared against ${r.posts_compared} post(s)</span></div>
      ${(r.suggestions || []).map((s) => `<div class="small">• ${esc(s)}</div>`).join("")}`;
  } catch (e) { toast("Error: " + e.message); }
};
$("in-hashtags").onclick = async () => {
  const text = $("in-text").value.trim(); if (!text) return toast("Write a topic first");
  try {
    const r = await api("/api/adapt/hashtags", { method: "POST", body: JSON.stringify({ text }) });
    $("in-result").innerHTML = `<div class="prow ok"><strong>Recommended hashtags</strong></div>
      <div class="small">${r.hashtags.map((h) => `<span class="chip">${esc(h)}</span>`).join(" ")}</div>`;
  } catch (e) { toast("Error: " + e.message); }
};
$("in-report").onclick = async () => {
  $("in-report").textContent = "… generating";
  try {
    const r = await api("/api/reports", { method: "POST" });
    $("in-result").innerHTML = `<div class="prow ok"><strong>📈 ${esc(r.month)}</strong></div>
      <div class="small">${r.posts_published} posts · ${r.engagement.likes} likes · ${r.engagement.comments} comments · ${r.follows_gained} follows · ${r.new_profiles_engaged} new users</div>`;
    toast("Report generated");
  } catch (e) { toast("Error: " + e.message); }
  $("in-report").textContent = "📈 Generate monthly report";
};
$("in-trends").onclick = async () => {
  try { const r = await api("/api/trends/capture", { method: "POST" }); toast("Trends captured"); renderInsights(); }
  catch (e) { toast("Error: " + e.message); }
};
$("safety-add").onclick = async () => {
  const username = $("safety-username").value.trim(); if (!username) return toast("Enter a username");
  try {
    await api("/api/safety", { method: "POST", body: JSON.stringify({
      list_type: $("safety-type").value, platform: $("safety-platform").value,
      username, note: $("safety-note").value }) });
    $("safety-username").value = ""; $("safety-note").value = "";
    toast("Safety rule added"); renderInsights();
  } catch (e) { toast("Error: " + e.message); }
};
window.delSafety = async (id) => { await api(`/api/safety/${id}`, { method: "DELETE" }); renderInsights(); };

/* ----------------------------------------------------------------- review */
$("rev-refresh").onclick = () => renderReview();

function askModal(html) {
  return new Promise((resolve) => {
    $("modal").innerHTML = `<h2><span>Review</span><button class="close" onclick="closeModal()">✕</button></h2>
      <div style="margin:10px 0">${html}</div>
      <div style="display:flex;gap:10px">
        <button class="btn" id="ask-ok">Confirm</button>
        <button class="btn ghost" onclick="closeModal()">Cancel</button>
      </div>`;
    $("modal-back").classList.add("show");
    const done = (v) => { $("modal-back").removeEventListener("click", onBack); resolve(v); };
    const onBack = (e) => { if (e.target === $("modal-back")) { closeModal(); done(false); } };
    $("modal-back").addEventListener("click", onBack);
    $("ask-ok").onclick = () => { closeModal(); done(true); };
    $("modal").querySelector(".close").onclick = () => { closeModal(); done(false); };
  });
}

async function renderReview() {
  const r = await api("/api/review");
  const rows = [
    ...r.pending.map((p) => [p, "⏳ pending"]),
    ...r.approved.map((p) => [p, "✅ approved"]),
  ];
  $("review-table").innerHTML =
    `<tr><th>Status</th><th>Source</th><th>Text</th><th>Platforms</th><th>Actions</th></tr>` +
    (rows.length ? rows.map(([p, badge]) => `<tr>
      <td><span class="chip">${badge}</span></td>
      <td class="mono small">${esc(p.origin || "agent")}</td>
      <td>${esc(p.text.slice(0, 140))}</td>
      <td>${platformDots(p.platforms || [])}</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="approvePost('${p.id}')">✓ Approve</button>
        <button class="btn ghost small" onclick="rejectPost('${p.id}')">✕ Reject</button>
      </td></tr>`).join("")
    : `<tr><td colspan="5" class="empty">Nothing to review — agents haven't drafted anything yet.</td></tr>`);
}

window.approvePost = async (postId) => {
  const platforms = S.accounts.filter((a) => a.enabled).map((a) => a.platform);
  const opts = { text: "Approve this agent draft?",
    body: `
      <p class="muted small">Connected platforms: ${platforms.length ? esc(platforms.join(", ")) : "none (mock still works)"}</p>
      <label>Platforms (comma-separated)</label>
      <input id="appr-platforms" value="${esc(platforms.join(","))}" />
      <label style="margin-top:8px">When</label>
      <select id="appr-when">
        <option value="draft">Stay as draft (schedule later)</option>
        <option value="best">Best engagement window</option>
        <option value="now">Publish now</option>
      </select>` };
  const ok = await askModal(opts.body);
  if (!ok) return;
  try {
    const plats = $("appr-platforms").value.split(",").map((s) => s.trim()).filter(Boolean);
    const when = $("appr-when").value;
    await api(`/api/review/${postId}/approve`, { method: "POST", body: JSON.stringify({
      platforms: plats,
      best_time: when === "best",
      scheduled_at: when === "now" ? "now" : undefined }) });
    toast("Approved"); renderReview();
  } catch (e) { toast("Error: " + e.message); }
};

window.rejectPost = async (postId) => {
  const ok = await askModal(`<label>Note (optional)</label><input id="rej-note" placeholder="why?" />`);
  if (!ok) return;
  try {
    await api(`/api/review/${postId}/reject`, { method: "POST",
      body: JSON.stringify({ note: $("rej-note").value }) });
    toast("Rejected"); renderReview();
  } catch (e) { toast("Error: " + e.message); }
};

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