/* Stonic HUD extensions */
(function () {
  const theme = localStorage.getItem("sb_theme") || "cyan";
  document.documentElement.setAttribute("data-theme", theme);
  document.querySelectorAll(".theme-pills button").forEach((btn) => {
    btn.classList.toggle("active", btn.dataset.t === theme);
    btn.addEventListener("click", () => {
      document.documentElement.setAttribute("data-theme", btn.dataset.t);
      localStorage.setItem("sb_theme", btn.dataset.t);
      document.querySelectorAll(".theme-pills button").forEach((b) =>
        b.classList.toggle("active", b === btn)
      );
    });
  });

  async function loadCore() {
    try {
      const core = await api("/api/stonic/core");
      const line = document.getElementById("core-line");
      if (line) line.textContent = core.settings?.value || "ready";
      const circuits = document.getElementById("core-circuits");
      if (circuits) {
        circuits.innerHTML = ["memory", "skills", "soul", "settings"]
          .map((k) => {
            const c = core[k] || {};
            return `<div class="circuit"><div class="label">${c.label || k}</div><div class="val">${c.value || "—"}</div><div class="muted small">${c.detail || ""}</div></div>`;
          })
          .join("");
      }
      const dot = document.getElementById("chatgpt-dot");
      const badge = document.getElementById("chatgpt-badge");
      const on = !!core.settings?.chatgpt_authenticated;
      if (dot) dot.classList.toggle("on", on);
      if (badge) badge.textContent = on ? "linked" : "offline";
    } catch (e) {
      console.warn(e);
    }
  }

  async function loadTown() {
    try {
      const agents = await api("/api/stonic/agents");
      const grid = document.getElementById("agent-grid");
      if (!grid) return;
      grid.innerHTML = (agents || [])
        .map(
          (a) => `<div class="agent-card">
          <div class="name">${a.name}</div>
          <div class="role">${a.role} · ${a.specialty}</div>
          <div class="status"><span class="led"></span>${a.status} · desk ${a.desk}</div>
          <div class="task">${a.current_task || "—"}</div>
        </div>`
        )
        .join("");
    } catch (e) {
      console.warn(e);
    }
  }

  document.getElementById("chatgpt-status-btn")?.addEventListener("click", loadCore);
  document.getElementById("chatgpt-login-btn")?.addEventListener("click", () => {
    toast("Run in terminal: socialbot chatgpt login  (then refresh this page)");
  });

  const origNav = document.getElementById("nav");
  if (origNav) {
    origNav.addEventListener("click", (ev) => {
      const a = ev.target.closest("a[data-view]");
      if (!a) return;
      if (a.dataset.view === "command") loadCore();
      if (a.dataset.view === "town") loadTown();
    });
  }
  loadCore();
})();
