/**
 * Project200 Control Tower — Frontend Controller
 * Backend DTO를 단일 데이터 원천으로 사용하며, 가짜 상태/시장값을 생성하지 않는다.
 */
document.addEventListener("DOMContentLoaded", () => {
  let currentTab = "virtual_exchange";
  let pollInFlight = false;
  const pollIntervalMs = 2000;

  const tabButtons = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".env-panel");
  const activeEnvBadge = document.getElementById("active-env-badge");
  const systemTimeEl = document.getElementById("system-time");
  const safetyDot = document.querySelector(".indicator-dot");
  const safetyText = document.getElementById("safety-text");
  const panicHaltBtn = document.getElementById("btn-panic-halt");
  const dockEnvName = document.getElementById("dock-env-name");
  const auditLogBox = document.getElementById("audit-log-box");
  const strategySelect = document.getElementById("strategy-select");
  const scenarioSelect = document.getElementById("scenario-select");
  const runIdInput = document.getElementById("run-id");
  const runStatus = document.getElementById("run-status");
  const runCreateBtn = document.getElementById("run-create");
  const runStartBtn = document.getElementById("run-start");
  const runStopBtn = document.getElementById("run-stop");
  const runReplayBtn = document.getElementById("run-replay");

  const tabNames = {
    high_speed: "High-Speed Test",
    virtual_exchange: "가상거래소 (Virtual Market)",
    virtual_broker: "가상증권사 (Virtual Broker)",
    paper: "모의투자 (KIS Paper)",
    live: "실투자 (KIS Live)",
  };

  const escapeHtml = (value) => String(value ?? "—")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const numberText = (value, digits = 2) => {
    if (value === null || value === undefined || value === "") return "—";
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "—";
  };

  const moneyText = (value) => {
    if (value === null || value === undefined) return "—";
    const n = Number(value);
    if (!Number.isFinite(n)) return "—";
    return `${n >= 0 ? "+" : "−"}₩ ${Math.abs(n).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}`;
  };

  function setPanelLoading(panel, loading) {
    panel?.classList.toggle("is-loading", loading);
  }

  function setConnectionMessage(panelId, message) {
    const panel = document.getElementById(panelId);
    if (!panel) return;
    let box = panel.querySelector(".ui-error-message");
    if (!box) {
      box = document.createElement("div");
      box.className = "ui-error-message";
      panel.prepend(box);
    }
    if (!message) { box.remove(); return; }
    box.textContent = message;
  }

  async function apiFetch(url, options = {}) {
    const res = await fetch(url, { cache: "no-store", ...options });
    let data = null;
    try { data = await res.json(); } catch (_) { /* non-JSON response */ }
    if (!res.ok) {
      const message = data?.error || data?.message || `HTTP ${res.status}`;
      throw new Error(message);
    }
    return data;
  }

  async function refreshRunControls() {
    try {
      const [strategies, scenarios, run] = await Promise.all([
        apiFetch("/api/strategies"), apiFetch("/api/scenarios"), apiFetch("/api/run")
      ]);
      if (strategySelect && !strategySelect.options.length) {
        (strategies.strategies || []).forEach((x) => {
          const o=document.createElement("option"); o.value=`${x.strategy_id}:${x.version}`; o.textContent=`${x.strategy_id} v${x.version}`; strategySelect.appendChild(o);
        });
      }
      if (scenarioSelect && !scenarioSelect.options.length) {
        (scenarios.available_scenarios || []).forEach((x) => { const o=document.createElement("option"); o.value=x; o.textContent=x; scenarioSelect.appendChild(o); });
      }
      if (runStatus) runStatus.textContent = `RUN: ${run.run_id || "—"} / ${run.runtime_state || "STOPPED"}`;
      const readModel = document.getElementById("run-read-model");
      if (readModel) readModel.textContent = JSON.stringify({run_id: run.run_id, runtime_state: run.runtime_state, historical_source: run.historical_source, last_replay_tick: run.last_replay_tick, account: run.account, position: run.position, margin: run.margin, pnl: run.pnl, execution_reports: run.execution_reports}, null, 2);
    } catch (error) { addAuditLog(`[RUN] control read failed: ${error.message}`, "error"); }
  }

  async function runAction(action) {
    try { const data=await apiFetch("/api/run/action", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}); addAuditLog(`[RUN] ${action} completed`); refreshRunControls(); return data; }
    catch(error) { addAuditLog(`[RUN] ${action} failed: ${error.message}`, "error"); alert(error.message); }
  }
  runCreateBtn?.addEventListener("click", async () => {
    const key=(strategySelect?.value || "").split(":");
    if (!runIdInput?.value.trim() || key.length !== 2) return alert("Run ID와 Strategy를 선택하세요.");
    try { await apiFetch("/api/run", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({run_id:runIdInput.value.trim(),environment:"virtual",scenario:scenarioSelect?.value || null,strategy_keys:[[key[0],key[1]]]})}); refreshRunControls(); }
    catch(error) { alert(`RUN 생성 실패: ${error.message}`); }
  });
  runStartBtn?.addEventListener("click", () => runAction("START"));
  runStopBtn?.addEventListener("click", () => runAction("STOP"));
  runReplayBtn?.addEventListener("click", () => runAction("REPLAY"));

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
  });

  function switchTab(tabId) {
    if (!tabNames[tabId]) return;
    currentTab = tabId;
    tabButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tabId));
    panels.forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${tabId}`));
    if (activeEnvBadge) activeEnvBadge.textContent = tabNames[tabId];
    if (dockEnvName) dockEnvName.textContent = tabNames[tabId];

    apiFetch("/api/active_tab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tab_id: tabId }),
    }).catch((error) => addAuditLog(`[UI] 탭 상태 저장 실패: ${error.message}`, "error"));

    fetchTabDetail(tabId);
  }

  panicHaltBtn?.addEventListener("click", async () => {
    if (panicHaltBtn.disabled) return;
    if (!confirm("비상정지(PANIC HALT)를 발동하시겠습니까?\n실제 RiskEngine/Runtime에 정지 명령이 전달됩니다.")) return;
    panicHaltBtn.disabled = true;
    try {
      const data = await apiFetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "PANIC_HALT" }),
      });
      addAuditLog(`[PANIC_HALT] ${data.message || "비상정지 완료"}`, "warning");
      updateSafetyState(data.kill_switch_active === true, data.runtime_state);
    } catch (error) {
      addAuditLog(`[PANIC_HALT] 실행 실패: ${error.message}`, "error");
      alert(`비상정지 요청 실패: ${error.message}`);
    } finally {
      panicHaltBtn.disabled = false;
      fetchSummary();
    }
  });

  function updateSafetyState(killSwitchActive, runtimeState) {
    const active = killSwitchActive === true;
    safetyDot?.classList.toggle("dot-safe", active);
    safetyDot?.classList.toggle("dot-danger", !active);
    if (safetyText) {
      safetyText.textContent = active ? "FAIL-SAFE ENGAGED" : `ARMED / ${runtimeState || "UNKNOWN"}`;
    }
  }

  async function fetchSummary() {
    try {
      const data = await apiFetch("/api/status");
      if (data.system_time && systemTimeEl) systemTimeEl.textContent = data.system_time;
      updateSafetyState(data.kill_switch_global, data.runtime_state);
      data.tabs?.forEach((tab) => {
        const btn = document.getElementById(`tab-${tab.tab_id}`);
        const pill = btn?.querySelector(".tab-status-pill");
        if (pill) {
          pill.textContent = tab.status || "UNKNOWN";
          pill.className = `tab-status-pill ${statusClass(tab.status)}`;
          pill.title = tab.connection || "";
        }
      });
    } catch (error) {
      addAuditLog(`[STATUS] 상태 조회 실패: ${error.message}`, "error");
      setConnectionMessage(`panel-${currentTab}`, `상태 조회 실패: ${error.message}`);
    }
  }

  function statusClass(status) {
    const value = String(status || "").toUpperCase();
    if (["OPEN", "RUNNING", "OPERATIONAL", "CONNECTED"].includes(value)) return "status-running";
    if (["READY", "STOPPED", "DISCONNECTED", "NOT_INITIALIZED"].includes(value)) return "status-stopped";
    return "status-blocked";
  }

  async function fetchTabDetail(tabId) {
    const panel = document.getElementById(`panel-${tabId}`);
    setPanelLoading(panel, true);
    try {
      const data = await apiFetch(`/api/environment/${encodeURIComponent(tabId)}`);
      setConnectionMessage(`panel-${tabId}`, "");
      if (tabId === "virtual_exchange") renderVirtualExchange(data);
      else if (tabId === "virtual_broker") renderVirtualBroker(data);
      else if (tabId === "high_speed") renderHighSpeed(data);
      else if (tabId === "paper") renderPaper(data);
      else if (tabId === "live") renderLive(data);
      (data.audit_logs || []).slice(-3).forEach((log) => addAuditLog(`[${tabId.toUpperCase()}] ${log}`));
    } catch (error) {
      setConnectionMessage(`panel-${tabId}`, `환경 데이터 조회 실패: ${error.message}`);
      addAuditLog(`[${tabId.toUpperCase()}] 조회 실패: ${error.message}`, "error");
    } finally {
      setPanelLoading(panel, false);
    }
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  function renderHighSpeed(data) {
    const connected = data.connection_state === "CONNECTED";
    setText("hs-ticks", connected ? `${data.processed_ticks ?? 0} / ${data.total_ticks ?? 0}` : "—");
    setText("hs-decisions", connected ? (data.strategy_decisions_count ?? 0) : "—");
    setText("hs-orders", connected ? `${data.orders_submitted ?? 0} / ${data.orders_filled ?? 0}` : "—");
    setText("hs-pnl", moneyText(data.total_pnl));
    setText("hs-speed", `${numberText(data.speed_multiplier, 2)}x`);
    setText("hs-scenario", data.scenario_name || "—");
    const progress = Number(data.progress_ratio);
    const bar = document.getElementById("hs-progress");
    if (bar) bar.style.width = `${Number.isFinite(progress) ? Math.max(0, Math.min(100, progress * 100)) : 0}%`;
    renderRows("hs-positions-tbody", data.positions, 5, (p) => `
      <tr><td class="mono">${escapeHtml(p.symbol)}</td><td>${escapeHtml(p.qty)}</td>
      <td class="mono">${numberText(p.avg_price)}</td><td class="mono">${numberText(p.current_price)}</td>
      <td class="mono">${escapeHtml(moneyText(p.pnl))}</td></tr>`);
  }

  function renderVirtualExchange(data) {
    setText("vm-underlying", numberText(data.underlying_index_price));
    setText("vm-vkospi", data.volatility_index == null ? "—" : `${numberText(data.volatility_index)} %`);
    setText("vm-instruments", data.instruments_count ?? 0);
    setText("vm-feed-status", data.connection_state || "UNKNOWN");
    setText("vm-feed-badge", data.market_state || "UNKNOWN");
    setText("vm-latency", data.feed_latency_ms == null ? "LATENCY: —" : `LATENCY: ${numberText(data.feed_latency_ms)} ms`);
    renderRows("vm-ticks-tbody", data.recent_ticks, 6, (t) => `
      <tr><td class="mono">${escapeHtml(t.code)}</td><td>${escapeHtml(t.name)}</td>
      <td class="mono">${numberText(t.price)}</td><td class="mono">${numberText(t.change)}</td>
      <td class="mono">${numberText(t.volume, 0)}</td><td class="mono text-muted">${escapeHtml(formatTime(t.time))}</td></tr>`);
    renderDepth(data.market_depth);
  }

  function renderDepth(depth) {
    const root = document.getElementById("vm-depth");
    if (!root) return;
    const asks = Array.isArray(depth?.asks) ? depth.asks : [];
    const bids = Array.isArray(depth?.bids) ? depth.bids : [];
    const rows = (items, cls) => items.map((x) => `<div class="depth-row"><span class="price ${cls}">${numberText(x.price)}</span><span class="qty">${escapeHtml(x.qty)}</span></div>`).join("");
    root.innerHTML = asks.length || bids.length ? `${rows(asks, "text-down")}<div class="depth-spread">${escapeHtml(depth.spread ?? "—")}</div>${rows(bids, "text-up")}` : `<div class="empty-state">실제 호가 데이터 없음</div>`;
  }

  function renderVirtualBroker(data) {
    setText("vb-cash", moneyText(data.cash_balance));
    setText("vb-margin", moneyText(data.margin_used));
    setText("vb-margin-available", moneyText(data.margin_available));
    setText("vb-realized", moneyText(data.realized_pnl));
    setText("vb-unrealized", moneyText(data.unrealized_pnl));
    setText("vb-account", data.account_number || "—");
    renderRows("vb-orders-tbody", data.active_orders, 6, (o) => `<tr><td class="mono">${escapeHtml(o.order_id)}</td><td class="mono">${escapeHtml(o.symbol)}</td><td>${escapeHtml(o.side)}</td><td>${escapeHtml(o.qty)}</td><td>${numberText(o.price)}</td><td>${escapeHtml(o.status)}</td></tr>`);
    renderRows("vb-positions-tbody", data.positions, 6, (p) => `<tr><td class="mono">${escapeHtml(p.symbol)}</td><td>${escapeHtml(p.name || p.symbol)}</td><td>${escapeHtml(p.qty)}</td><td class="mono">${numberText(p.avg_price)}</td><td class="mono">${numberText(p.current_price)}</td><td class="mono">${escapeHtml(moneyText(p.pnl))}</td></tr>`);
  }

  function renderPaper(data) {
    setText("paper-connection", data.connection_state || "UNKNOWN");
    setText("paper-auth", data.auth_state || "UNKNOWN");
    setText("paper-risk", data.risk_state || "UNKNOWN");
    setText("paper-account", data.account_number || "—");
    setText("paper-reason", data.blocked_reason || "—");
  }

  function renderLive(data) {
    setText("live-connection", data.connection_state || "UNKNOWN");
    setText("live-auth", data.auth_state || "UNKNOWN");
    setText("live-approval", data.live_approval ? "APPROVED" : "NOT APPROVED");
    setText("live-kill-switch", data.kill_switch_engaged ? "ENGAGED" : "NOT ENGAGED");
    setText("live-execution", data.execution_allowed ? "ALLOWED" : "BLOCKED");
    setText("live-reason", data.blocked_reason || "—");
  }

  function renderRows(id, rows, colspan, renderer) {
    const tbody = document.getElementById(id);
    if (!tbody) return;
    if (!Array.isArray(rows) || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">실제 데이터 없음</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map(renderer).join("");
  }

  function formatTime(value) {
    if (!value) return "—";
    const text = String(value);
    return text.length >= 19 ? text.slice(11, 19) : text;
  }

  function addAuditLog(message, level = "info") {
    if (!auditLogBox || !message) return;
    const signature = `${level}:${message}`;
    if (auditLogBox.dataset.last === signature) return;
    auditLogBox.dataset.last = signature;
    const line = document.createElement("div");
    line.className = `log-line log-${level}`;
    line.textContent = `[${new Date().toLocaleTimeString("ko-KR")}] ${message}`;
    auditLogBox.appendChild(line);
    while (auditLogBox.children.length > 8) auditLogBox.removeChild(auditLogBox.firstChild);
  }

  async function poll() {
    if (pollInFlight) return;
    pollInFlight = true;
    try {
      await fetchSummary();
      await fetchTabDetail(currentTab);
    } finally {
      pollInFlight = false;
    }
  }

  fetchSummary();
  fetchTabDetail(currentTab);
  refreshRunControls();
  setInterval(poll, pollIntervalMs);
});
