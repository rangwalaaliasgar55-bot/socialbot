/* SocialBot dashboard — vanilla JS single-page app */
"use strict";

const S = { platforms: [], posts: [], accounts: [], rules: [], calMonth: null, view: "calendar" };

const $ = (id) => document.getElementById(id);
const esc = (s) => String(s ?? "").replace(/[&<>"']/g, (c) =>
  ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

async function api(path, opts = {}) {
  const res = await fetch(path, { headers: { "Content-Type": "application/json" }, ...opts });
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
    const on = health.scheduler && health.scheduler.running;
    $("sched-pill").innerHTML = `<span class="dot ${on ? "on" : ""}"></span> ${on ? "scheduler live" : "scheduler off"}`;
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
    html += `<div class="day ${today ? "today" : ""}" data-day="${day}" title="Click to schedule for this day">
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
    }));
}
$("cal-prev").onclick = () => { const d = new Date(S.calMonth); d.setMonth(d.getMonth() - 1); S.calMonth = d; renderCalendar(); };
$("cal-next").onclick = () => { const d = new Date(S.calMonth); d.setMonth(d.getMonth() + 1); S.calMonth = d; renderCalendar(); };

function renderUpcoming() {
  const up = S.posts.filter((p) => p.status === "scheduled")
    .sort((a, b) => (a.scheduled_at || "").localeCompare(b.scheduled_at || "")).slice(0, 6);
  $("upcoming").innerHTML = up.length ? `<table><tr><th>When</th><th>Platforms</th><th>Post</th><th></th></tr>
    ${up.map((p) => `<tr><td class="muted small">${fmtWhen(p.scheduled_at)}</td>
      <td>${platformDots(p.platforms)}</td>
      <td>${esc(p.text.slice(0, 60))}${p.tag ? ` <span class="chip">#${esc(p.tag)}</span>` : ""}</td>
      <td><button class="btn danger small" onclick="cancelPost('${p.id}')">cancel</button></td></tr>`).join("")}</table>`
    : `<div class="empty">Nothing scheduled — hit “New post” 🚀</div>`;
}
window.cancelPost = async (id) => { await api(`/api/posts/${id}`, { method: "DELETE" }); render(); };

/* ---------------------------------------------------------------- queue */
function renderQueue() {
  const filter = $("queue-filter").value;
  const rows = (filter ? S.posts.filter((p) => p.status === filter) : S.posts);
  $("queue-table").innerHTML = `<tr><th>Status</th><th>When</th><th>Platforms</th><th>Text</th><th>Results</th><th></th></tr>` +
    (rows.length ? rows.map((p) => `<tr>
      <td>${statusChip(p.status)}</td>
      <td class="muted small">${fmtWhen(p.scheduled_at || p.published_at)}</td>
      <td>${platformDots(p.platforms)}</td>
      <td style="max-width:280px">${esc(p.text.slice(0, 90))}${p.tag ? `<br><span class="chip">#${esc(p.tag)}</span>` : ""}</td>
      <td class="small">${Object.entries(p.results || {}).map(([pl, r]) =>
        `${platform(pl).icon} ${r.ok ? "✅" : "❌ " + esc((r.error || "").slice(0, 40))}`).join("<br>") || "—"}</td>
      <td style="white-space:nowrap">
        ${p.status === "scheduled" ? `<button class="btn small" onclick="pubNow('${p.id}')">publish</button> ` : ""}
        ${["failed", "partial"].includes(p.status) ? `<button class="btn ghost small" onclick="retry('${p.id}')">retry</button> ` : ""}
        <button class="btn danger small" onclick="delPost('${p.id}')">delete</button>
      </td></tr>`).join("") : `<tr><td colspan="6" class="empty">No posts yet</td></tr>`);
}
$("queue-filter").onchange = renderQueue;
$("tick-now").onclick = async () => { const r = await api("/api/scheduler/tick", { method: "POST" }); toast(`Processed ${r.processed} due post(s)`); render(); };
window.pubNow = async (id) => { await api(`/api/posts/${id}/publish`, { method: "POST" }); render(); };
window.retry = async (id) => { await api(`/api/posts/${id}/retry`, { method: "POST" }); render(); };
window.delPost = async (id) => { await api(`/api/posts/${id}`, { method: "DELETE" }); render(); };

/* ------------------------------------------------------------- composer */
function renderComposer() {
  const wrap = $("c-platforms");
  if (!wrap.dataset.built) {
    wrap.innerHTML = S.platforms.map((p) =>
      `<div class="ppick" data-p="${p.name}" style="${p.configured ? "" : "opacity:.55"}">
        <span>${p.icon}</span><span>${esc(p.display_name)}</span></div>`).join("");
    wrap.querySelectorAll(".ppick").forEach((el) =>
      el.addEventListener("click", () => { el.classList.toggle("on"); updateCounter(); }));
    wrap.dataset.built = "1";
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
$("c-text").addEventListener("input", updateCounter);
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
    toast("Scheduled ✅"); setView("calendar");
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
        $("c-text").value = r.drafts[+el.dataset.i].text; updateCounter();
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
  $("modal").innerHTML = `
    <h2><span>${p.icon} ${esc(p.display_name)}</span><button class="close" onclick="closeModal()">✕</button></h2>
    <p class="muted small" style="margin:6px 0 4px">${p.auth_fields.length ? "Enter credentials (stored locally in your DB):" : "No credentials needed for this platform."}</p>
    ${p.auth_fields.map((f) => `
      <div class="field"><label>${esc(f.label)}${f.required ? " *" : ""}${f.help ? ` — ${esc(f.help)}` : ""}</label>
      <input id="af-${esc(f.key)}" type="${f.secret ? "password" : "text"}" value="${esc(String(acc.config[f.key] ?? ""))}" /></div>`).join("")}
    <div class="field"><label>Label (nickname)</label><input id="af-__label" value="${esc(acc.label || "")}" /></div>
    <div class="field"><label>Default signature (appended to posts)</label><input id="af-__signature" value="${esc(acc.config.signature ?? "")}" /></div>
    <div class="actions">
      <a class="btn ghost small" target="_blank" href="${p.docs_url}">docs ↗</a>
      <button class="btn ghost" onclick="verifyAcct('${name}')">Verify</button>
      <button class="btn" onclick="saveAcct('${name}')">Save</button>
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
  } catch (e) { toast("Error: " + e.message); }
};
window.verifyAcct = async (name) => {
  await saveAcct(name);
  try {
    const r = await api(`/api/accounts/${name}/verify`, { method: "POST" });
    $("af-msg").textContent = (r.ok ? "✅ " : "❌ ") + r.message;
  } catch (e) { $("af-msg").textContent = "❌ " + e.message; }
};

/* ------------------------------------------------------------------- bot */
function renderBot() {
  $("bot-table").innerHTML = `<tr><th>Rule</th><th>Platform</th><th>Action</th><th>Trigger</th>
    <th>Last run</th><th>Stats</th><th></th></tr>` +
    (S.rules.length ? S.rules.map((r) => {
      const p = platform(r.platform);
      return `<tr>
      <td><strong>${esc(r.name)}</strong> ${r.dry_run ? '<span class="chip">dry-run</span>' : '<span class="chip s-published">live</span>'}</td>
      <td>${p.icon} ${esc(p.display_name)}</td>
      <td class="mono">${esc(r.action)}</td>
      <td class="mono">${esc(r.trigger_type)}: ${esc(r.trigger_value)}</td>
      <td class="small muted">${r.last_run ? fmtWhen(r.last_run) : "never"}<br>
        ${r.last_result ? esc(JSON.stringify({ found: r.last_result.found, acted: r.last_result.acted, error: r.last_result.error })) : ""}</td>
      <td class="small">${r.total_actions} actions</td>
      <td style="white-space:nowrap">
        <button class="btn small" onclick="runRule('${r.id}')">run</button>
        <button class="btn danger small" onclick="delRule('${r.id}')">delete</button>
      </td></tr>`;
    }).join("") : `<tr><td colspan="7" class="empty">No rules yet — try “comment on #python posts on Bluesky”</td></tr>`);
}
$("bot-new").onclick = () => {
  const searchable = S.platforms.filter((p) => p.capabilities.includes("search"));
  $("modal").innerHTML = `
    <h2><span>New automation rule</span><button class="close" onclick="closeModal()">✕</button></h2>
    <div class="form-grid">
      <div><label>Name</label><input id="br-name" value="My rule" /></div>
      <div><label>Platform</label><select id="br-platform">${searchable.map((p) => `<option value="${p.name}">${p.icon} ${esc(p.display_name)}</option>`).join("")}</select></div>
      <div><label>Action</label><select id="br-action">
        <option value="like">like</option><option value="comment">comment</option>
        <option value="follow">follow</option><option value="repost">repost</option></select></div>
      <div><label>Trigger</label><select id="br-ttype"><option value="keyword">keyword</option><option value="hashtag">hashtag</option></select></div>
      <div style="grid-column:1/-1"><label>Trigger value</label><input id="br-tvalue" placeholder="e.g. python or opensource" /></div>
      <div style="grid-column:1/-1"><label>Comment template (use {topic})</label><input id="br-comment" placeholder="Nice take on {topic}!" /></div>
    </div>
    <div class="actions"><button class="btn" onclick="saveRule()">Create rule</button></div>`;
  $("modal-back").classList.add("show");
};
window.saveRule = async () => {
  try {
    await api("/api/bot/rules", { method: "POST", body: JSON.stringify({
      name: $("br-name").value, platform: $("br-platform").value, action: $("br-action").value,
      trigger_type: $("br-ttype").value, trigger_value: $("br-tvalue").value,
      comment_template: $("br-comment").value }) });
    closeModal(); toast("Rule created (dry-run)"); render();
  } catch (e) { toast("Error: " + e.message); }
};
window.runRule = async (id) => {
  toast("Running rule…");
  const r = await api(`/api/bot/rules/${id}/run`, { method: "POST" });
  toast(r.ok ? `Rule ran: found ${r.found}, acted ${r.acted}${r.dry_run ? " (dry-run)" : ""}` : "Failed: " + (r.error || "see details"));
  render();
};
$("bot-run-all").onclick = async () => { await api("/api/bot/run", { method: "POST" }); toast("All rules executed"); render(); };
window.delRule = async (id) => { await api(`/api/bot/rules/${id}`, { method: "DELETE" }); render(); };

/* -------------------------------------------------------------- analytics */
async function renderAnalytics() {
  const a = await api("/api/analytics/summary");
  const engagement = Object.values(a.engagement || {}).reduce((acc, m) => {
    for (const [k, v] of Object.entries(m)) acc[k] = (acc[k] || 0) + v; return acc; }, {});
  const cards = [
    ["Total posts", a.total_posts],
    ["Published", (a.by_status.published || 0) + (a.by_status.partial || 0)],
    ["Scheduled", a.by_status.scheduled || 0],
    ["Likes tracked", engagement.likes || 0],
    ["Shares tracked", engagement.shares || 0],
    ["Comments tracked", engagement.comments || 0],
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
setInterval(() => { if (!document.hidden) loadAll().then(() => { if (S.view === "calendar") { renderCalendar(); renderUpcoming(); } }); }, 30000);
