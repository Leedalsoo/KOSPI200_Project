/**
 * Project200 Control Tower ??Frontend Controller
 * Backend DTO projection only; the frontend renders server-provided state.
 */
document.addEventListener("DOMContentLoaded", () => {
  const storedTab = localStorage.getItem("p200:lastTab");
  let currentTab = storedTab && document.querySelector(`.tab-btn[data-tab="${storedTab}"]`) ? storedTab : "virtual_exchange";
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
  const runControlPanel = document.getElementById("run-control-panel");
  const runControlScope = document.getElementById("run-control-scope");

  const tabNames = {
    high_speed: "High-Speed Test",
    virtual_exchange: "가상거래소 (Virtual Market)",
    virtual_broker: "가상증권사 (Virtual Broker)",
    option_program: "옵션프로그램 (Option Program)",
    paper: "모의투자 (KIS Paper)",
    live: "\uc2e4\ud22c\uc790 (KIS Live)",
  };

  const escapeHtml = (value) => String(value ?? "?")
    .replaceAll("&", "&amp;").replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;").replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const numberText = (value, digits = 2) => {
    if (value === null || value === undefined || value === "") return "?";
    const n = Number(value);
    return Number.isFinite(n) ? n.toLocaleString("ko-KR", { minimumFractionDigits: digits, maximumFractionDigits: digits }) : "?";
  };

  const moneyText = (value) => {
    if (value === null || value === undefined) return "?";
    const n = Number(value);
    if (!Number.isFinite(n)) return "?";
    return `${n >= 0 ? "+" : "-"}₩${Math.abs(n).toLocaleString("ko-KR", { maximumFractionDigits: 0 })}`;
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
      if (runStatus) runStatus.textContent = `RUN: ${run.run_id || "?"} / ${run.runtime_state || "STOPPED"}`;
      const readModel = document.getElementById("run-read-model");
      if (readModel) readModel.textContent = JSON.stringify({run_id: run.run_id, runtime_state: run.runtime_state, historical_source: run.historical_source, last_replay_tick: run.last_replay_tick, account: run.account, position: run.position, margin: run.margin, pnl: run.pnl, execution_reports: run.execution_reports}, null, 2);
    } catch (error) { addAuditLog(`[RUN] control read failed: ${error.message}`, "error"); }
  }

  async function runAction(action) {
    try { const data=await apiFetch("/api/run/action", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({action})}); addAuditLog(`[RUN] ${action} completed`); refreshRunControls(); return data; }
    catch(error) { addAuditLog(`[RUN] ${action} failed: ${error.message}`, "error"); alert(error.message); }
  }

  async function setStrategyControl(strategyId, version, field, value) {
    try {
      await apiFetch("/api/strategy/control", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({strategy_id: strategyId, version, [field]: value}),
      });
      addAuditLog(`[STRATEGY] ${strategyId} ${field}=${value ? "ON" : "OFF"}`);
      await fetchTabDetail("option_program");
    } catch (error) {
      addAuditLog(`[STRATEGY] ${strategyId} control failed: ${error.message}`, "error");
      alert(error.message);
    }
  }

  document.getElementById("op-strategy-controls")?.addEventListener("change", (event) => {
    const input = event.target.closest("input[data-strategy-id]");
    if (!input) return;
    setStrategyControl(input.dataset.strategyId, input.dataset.version, input.dataset.control, input.checked);
  });
  runCreateBtn?.addEventListener("click", async () => {
    const key=(strategySelect?.value || "").split(":");
    if (!runIdInput?.value.trim() || key.length !== 2) return alert("Run ID\uc640 Strategy\ub97c \uc120\ud0dd\ud574 \uc8fc\uc138\uc694.");
    try { await apiFetch("/api/run", {method:"POST",headers:{"Content-Type":"application/json"},body:JSON.stringify({run_id:runIdInput.value.trim(),environment:"virtual",scenario:scenarioSelect?.value || null,strategy_keys:[[key[0],key[1]]]})}); refreshRunControls(); }
    catch(error) { alert(`RUN \uc0dd\uc131 \uc2e4\ud328: ${error.message}`); }
  });
  runStartBtn?.addEventListener("click", () => runAction("START"));
  runStopBtn?.addEventListener("click", () => runAction("STOP"));
  runReplayBtn?.addEventListener("click", () => runAction("REPLAY"));

  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => switchTab(btn.dataset.tab));
    btn.addEventListener("dragstart", (event) => { event.dataTransfer.setData("text/plain", btn.dataset.tab); });
    btn.addEventListener("dragover", (event) => event.preventDefault());
    btn.addEventListener("drop", (event) => {
      event.preventDefault();
      const sourceId = event.dataTransfer.getData("text/plain");
      const source = document.querySelector(`.tab-btn[data-tab="${sourceId}"]`);
      if (source && source !== btn) {
        btn.parentNode.insertBefore(source, btn);
        localStorage.setItem("p200:tabOrder", JSON.stringify([...document.querySelectorAll(".tab-btn")].map((x) => x.dataset.tab)));
      }
    });
  });

  function switchTab(tabId) {
    if (!tabNames[tabId]) return;
    currentTab = tabId;
    localStorage.setItem("p200:lastTab", tabId);
    tabButtons.forEach((btn) => btn.setAttribute("aria-selected", String(btn.dataset.tab === tabId)));
    const virtualOnly = tabId === "virtual_exchange" || tabId === "virtual_broker" || tabId === "option_program";
    runControlPanel?.classList.toggle("is-hidden", !virtualOnly);
    if (runControlScope) runControlScope.textContent = virtualOnly ? "VIRTUAL ONLY" : "CONTROL DISABLED";
    tabButtons.forEach((btn) => btn.classList.toggle("active", btn.dataset.tab === tabId));
    panels.forEach((panel) => panel.classList.toggle("active", panel.id === `panel-${tabId}`));
    if (activeEnvBadge) activeEnvBadge.textContent = tabNames[tabId];
    if (dockEnvName) dockEnvName.textContent = tabNames[tabId];

    apiFetch("/api/active_tab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tab_id: tabId }),
    }).catch((error) => addAuditLog(`[UI] \ud0ed \uc804\ud658 \uc2e4\ud328: ${error.message}`, "error"));

    fetchTabDetail(tabId);
  }

  panicHaltBtn?.addEventListener("click", async () => {
    if (panicHaltBtn.disabled) return;
    if (!confirm("\uae34\uae09 \uc815\uc9c0(PANIC HALT)? \uc694\uccad\ud569\ub2c8\uae4c?\n\uc2e4\ud589 \uc5ec\ubd80\ub294 \uc2dc\uc2a4\ud15c \uc0c1\ud0dc\uc640 \uc5f0\uacb0 \uc5ec\ubd80\uc5d0 \ub530\ub77c \ub2ec\ub77c\uc9c8 \uc218 \uc788\uc2b5\ub2c8\ub2e4.")) return;
    panicHaltBtn.disabled = true;
    try {
      const data = await apiFetch("/api/command", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ command: "PANIC_HALT" }),
      });
      addAuditLog(`[PANIC_HALT] ${data.message || "\uae34\uae09 \uc815\uc9c0 \uc694\uccad\uc774 \ucc28\ub2e8\ub418\uc5c8\uc2b5\ub2c8\ub2e4"}`, "warning");
      updateSafetyState(data.kill_switch_active === true, data.runtime_state);
    } catch (error) {
      addAuditLog(`[PANIC_HALT] \uc694\uccad \uc2e4\ud328: ${error.message}`, "error");
      alert(`\uae34\uae09 \uc815\uc9c0 \uc694\uccad \uc2e4\ud328: ${error.message}`);
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
      addAuditLog(`[STATUS] \uc0c1\ud0dc \uc870\ud68c \uc2e4\ud328: ${error.message}`, "error");
      setConnectionMessage(`panel-${currentTab}`, `\uc0c1\ud0dc \uc870\ud68c \uc2e4\ud328: ${error.message}`);
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
      else if (tabId === "option_program") {
        const controlModel = await apiFetch("/api/strategies");
        renderOptionProgram(data, controlModel);
        await renderCurrentVerification();
      }
      else if (tabId === "high_speed") renderHighSpeed(data);
      else if (tabId === "paper") renderPaper(data);
      else if (tabId === "live") renderLive(data);
      (data.audit_logs || []).slice(-3).forEach((log) => addAuditLog(`[${tabId.toUpperCase()}] ${log}`));
    } catch (error) {
      setConnectionMessage(`panel-${tabId}`, `\uc5f0\uacb0 \uc0c1\ud0dc \uc870\ud68c \uc2e4\ud328: ${error.message}`);
      addAuditLog(`[${tabId.toUpperCase()}] \uc5f0\uacb0 \uc0c1\ud0dc \uc870\ud68c \uc2e4\ud328: ${error.message}`, "error");
    } finally {
      setPanelLoading(panel, false);
    }
  }

  function setText(id, value) {
    const el = document.getElementById(id);
    if (el) el.textContent = value;
  }

  async function renderCurrentVerification() {
    const summary = document.getElementById("current-verification-summary");
    const grid = document.getElementById("current-verification-grid");
    if (!summary || !grid) return;
    try {
      const data = await apiFetch("/api/verification/current");
      const reports = Array.isArray(data.reports) ? data.reports : [];
      const byTrack = new Map(reports.map((item) => [item.strategy_id, item]));
      const target = Number(data.target_ticks || 5000);
      const passCount = reports.filter((item) => item.processed_ticks === target && !item.errors?.length).length;
      const blockedCount = reports.filter((item) => item.processed_ticks !== target || item.errors?.length).length;
      summary.innerHTML = [
        ["Basis", "CURRENT_BASELINE"], ["Target", target.toLocaleString("ko-KR") + " ticks / strategy"],
        ["Completed reports", reports.length + " / 9"], ["5,000-tick complete", passCount + " / 9"],
        ["Blocked / incomplete", blockedCount + " / 9"],
      ].map(([label, value]) => `<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
      const strategyRows = [
        ["TRACK 01", "TRACK1_TAIL_DEFENSE"], ["TRACK 02", "track2_asymmetric_trap"],
        ["TRACK 03", "Strategy_3_StatArb"], ["TRACK 04", "track4_gamma_scalping"],
        ["TRACK 05", "track5_gap_divergence"], ["TRACK 06", "track6_daily_tail_insurance"],
        ["TRACK 07", "track7_volatility_skew_weekly_insurance"],
        ["TRACK 08", "track8_macro_regime_monthly_strangle"],
        ["TRACK 09", "track9_event_overnight_insurance"],
      ];
      grid.innerHTML = strategyRows.map(([track, strategyId]) => {
        const item = byTrack.get(strategyId);
        if (!item) return `<div class="verification-item"><span>${track}</span><strong>${escapeHtml(strategyId)}</strong><span>Current baseline</span><b>NOT RUN</b></div>`;
        const result = item.result || {};
        const status = item.strategy_status?.[strategyId] || {};
        const complete = item.processed_ticks === target && !(item.errors || []).length;
        const state = complete ? "OBSERVED" : "BLOCKED / INCOMPLETE";
        return `<div class="verification-item"><span>${track}</span><strong>${escapeHtml(strategyId)}</strong><span>Ticks / source</span><b>${escapeHtml(String(item.processed_ticks) + " / " + target)} · ${escapeHtml(item.source || "?")}</b><span>Signal / Approved / Routed / Filled</span><b>${escapeHtml(String(status.reaction_signals ?? result.signals ?? 0) + " / " + String(status.approved ?? result.approved ?? 0) + " / " + String(status.routed ?? result.routed ?? 0) + " / " + String(status.filled_quantity ?? result.filled ?? 0))}</b><span>Verdict</span><b>${escapeHtml(state)}</b></div>`;
      }).join("");
    } catch (error) {
      summary.textContent = "CURRENT BASELINE VERIFICATION UNAVAILABLE: " + error.message;
      grid.innerHTML = "";
    }
  }

  function renderStrategyCompositionGraph(graph) {
    const legs = Array.isArray(graph?.legs) ? graph.legs.filter((leg) => leg && leg.trade_price != null) : [];
    if (!legs.length) {
      return '<div class="strategy-graph-unavailable">BUY / SELL DATA UNAVAILABLE</div>';
    }
    const plotted = legs.map((leg, index) => ({
      ...leg,
      xValue: Number.isFinite(Number(leg.strike)) ? Number(leg.strike) : index + 1,
      yValue: Number(leg.trade_price),
    })).filter((leg) => Number.isFinite(leg.yValue));
    if (!plotted.length) {
      return '<div class="strategy-graph-unavailable">TRADE VALUE UNAVAILABLE</div>';
    }
    const xs = plotted.map((leg) => leg.xValue);
    const ys = plotted.map((leg) => leg.yValue);
    const xmin = Math.min(...xs), xmax = Math.max(...xs);
    const ymin = Math.min(...ys), ymax = Math.max(...ys);
    const xspan = xmax === xmin ? 1 : xmax - xmin;
    const yspan = ymax === ymin ? Math.max(1, Math.abs(ymax) * 0.08) : ymax - ymin;
    const left = 28, right = 286, top = 12, bottom = 104;
    const x = (value) => left + ((value - xmin) / xspan) * (right - left);
    const y = (value) => bottom - ((value - ymin) / yspan) * (bottom - top);
    const bySide = (side) => plotted.filter((leg) => leg.side === side).sort((a,b) => a.xValue - b.xValue);
    const line = (items, cls) => items.length > 1
      ? `<polyline class="${cls}" points="${items.map((leg) => `${x(leg.xValue)},${y(leg.yValue)}`).join(" ")}"/>`
      : "";
    const points = plotted.map((leg) => {
      const cls = leg.side === "BUY" ? "strategy-graph-buy" : leg.side === "SELL" ? "strategy-graph-sell" : "strategy-graph-unknown";
      const label = `${leg.side} ${leg.option_type || leg.asset_type || ""} ${leg.strike ?? ""} @ ${leg.trade_price}`;
      return `<circle class="${cls}" cx="${x(leg.xValue)}" cy="${y(leg.yValue)}" r="4"><title>${escapeHtml(label)}</title></circle>`;
    }).join("");
    const buyCount = plotted.filter((leg) => leg.side === "BUY").length;
    const sellCount = plotted.filter((leg) => leg.side === "SELL").length;
    return `<div class="strategy-graph-wrap">
      <div class="strategy-graph-legend"><span class="legend-buy">BUY ${buyCount}</span><span class="legend-sell">SELL ${sellCount}</span><span>TRADE VALUE ONLY</span></div>
      <svg class="strategy-composition-svg" viewBox="0 0 300 120" role="img" aria-label="Strategy BUY SELL composition graph">
        <line class="strategy-graph-axis" x1="${left}" y1="${bottom}" x2="${right}" y2="${bottom}"/>
        <line class="strategy-graph-axis" x1="${left}" y1="${top}" x2="${left}" y2="${bottom}"/>
        ${line(bySide("BUY"), "strategy-graph-line-buy")}
        ${line(bySide("SELL"), "strategy-graph-line-sell")}
        ${points}
      </svg>
      <div class="strategy-graph-scale"><span>${escapeHtml(String(xmin))}</span><span>STRIKE / LEG</span><span>${escapeHtml(String(xmax))}</span></div>
    </div>`;
  }

  function renderStrategyControls(strategies) {
    const root = document.getElementById("op-strategy-controls");
    if (!root) return;
    root.innerHTML = strategies.map((item, index) => {
      const sid = escapeHtml(item.strategy_id);
      const version = escapeHtml(item.version);
      const key = `s${index + 1}`;
      return `<div class="strategy-control-card">
        <div class="strategy-control-title"><span>STRATEGY ${String(index + 1).padStart(2, "0")}</span><strong>${sid}</strong></div>
        <span class="strategy-control-version">v${version}</span>
        <label><input type="checkbox" data-strategy-id="${sid}" data-version="${version}" data-control="enabled" ${item.enabled ? "checked" : ""}> USE <b>${item.enabled ? "ON" : "OFF"}</b></label>
        <label><input type="checkbox" data-strategy-id="${sid}" data-version="${version}" data-control="entry_enabled" ${item.entry_enabled ? "checked" : ""} ${item.enabled ? "" : "disabled"}> ENTRY <b>${item.entry_enabled ? "ON" : "OFF"}</b></label>
        <label><input type="checkbox" data-strategy-id="${sid}" data-version="${version}" data-control="exit_enabled" ${item.exit_enabled ? "checked" : ""} ${item.enabled ? "" : "disabled"}> EXIT <b>${item.exit_enabled ? "ON" : "OFF"}</b></label>
      </div>`;
    }).join("");
  }

  function renderOptionProgram(data, controlModel = null) {
    setText("op-runtime-state", data.runtime_state || "STOPPED");
    setText("op-run-id", "RUN: " + (data.run_id || "?"));
    const market = data.market_input;
    setText("op-market-input", market ? (market.symbol || "?") + " @ " + numberText(market.last, 4) : "UNAVAILABLE");
    const result = data.last_result || {};
    setText("op-signals", result.signals ?? "?");
    setText("op-decisions", (result.approved ?? "?") + " / " + (result.rejected ?? "?"));
    setText("op-execution", (result.routed ?? "?") + " / " + (result.filled ?? "?"));
    const flow = data.flow || {};
    const flowItems = [["Market Input", flow.market_input],["Strategy", flow.strategy],["Signal", flow.signal],["Decision Approved", flow.decision_approved],["Risk / Router Rejected", flow.risk_or_router_rejected],["Order Routed", flow.order_routed],["Execution Filled", flow.execution_filled],["Position / PnL", flow.position_pnl]];
    const flowGrid = document.getElementById("op-flow-grid");
    if (flowGrid) flowGrid.innerHTML = flowItems.map(([label,value]) => `<div class="flow-node"><span>${escapeHtml(label)}</span><strong>${escapeHtml(value ?? "?")}</strong></div>`).join("");
    const strategies = Array.isArray(data.strategies) ? data.strategies : [];
    const controls = Array.isArray(controlModel?.strategies) ? controlModel.strategies : [];
    const controlById = new Map(controls.map((item) => [`${item.strategy_id}:${item.version}`, item]));
    const strategiesWithControls = strategies.map((item) => controlById.get(`${item.strategy_id}:${item.version}`) ? { ...item, ...controlById.get(`${item.strategy_id}:${item.version}`) } : item);
    renderStrategyControls(strategiesWithControls);
    const strategyGraphs = new Map((Array.isArray(data.strategy_graphs) ? data.strategy_graphs : []).map((item) => [item.strategy_id, item]));
    const grid = document.getElementById("op-strategy-grid");
    setText("op-strategy-count", strategies.length + " / 9");
    if (grid) grid.innerHTML = strategies.map(function(item,index) {
      const status=item.status||{}; const state=item.enabled?"ENABLED":"DISABLED"; const observation=item.observation_state||"NO_SIGNAL_OBSERVED";
      const cls=observation.includes("BLOCKED")||observation==="INPUT_UNAVAILABLE"?"blocked":(observation.includes("OBSERVED")?"observed":"neutral");
      const graph = strategyGraphs.get(item.strategy_id) || { data_status: "UNAVAILABLE", legs: [] };
      const pnl = graph.net_pnl;
      const pnlClass = pnl == null ? "pnl-neutral" : Number(pnl) >= 0 ? "pnl-positive" : "pnl-negative";
      const pnlLabel = pnl == null ? "STRATEGY INTEGRATED P/L UNAVAILABLE" : `STRATEGY INTEGRATED P/L ${moneyText(pnl)}`;
      const trades = Array.isArray(graph.trades) ? graph.trades : [];
      const tradeLedger = trades.length ? `<div class="strategy-trade-ledger"><div class="strategy-trade-ledger-title">MONTHLY TRADE P/L · ENTRY → CLOSE / EXPIRY</div>${trades.map((trade, tradeIndex) => {
        const value = trade.total_pnl;
        const valueClass = value == null ? "pnl-neutral" : Number(value) >= 0 ? "pnl-positive" : "pnl-negative";
        const stateLabel = trade.complete ? "CLOSED" : "OPEN";
        return `<div class="strategy-trade-row"><span>#${tradeIndex + 1}</span><span>${escapeHtml(trade.expiry || "EXPIRY UNAVAILABLE")}</span><span>${escapeHtml(stateLabel)}</span><b class="${valueClass}">${escapeHtml(value == null ? "P/L UNAVAILABLE" : moneyText(value))}</b></div>`;
      }).join("")}</div>` : `<div class="strategy-trade-ledger-unavailable">TRADE-LEVEL P/L UNAVAILABLE</div>`;
      return `<article class="strategy-card"><div class="strategy-card-top"><span>TRACK ${String(index+1).padStart(2,"0")}</span><b>${escapeHtml(state)}</b></div><h4>${escapeHtml(item.strategy_id)}</h4><div class="strategy-version">${escapeHtml(item.version)}</div><div class="strategy-graph-heading"><span>OPTION / FUTURES COMPOSITION</span><b>BUY · SELL</b></div>${renderStrategyCompositionGraph(graph)}${tradeLedger}<div class="strategy-stats"><span>signals <b>${escapeHtml(status.reaction_signals??0)}</b></span><span>approved <b>${escapeHtml(status.approved??0)}</b></span><span>routed <b>${escapeHtml(status.routed??0)}</b></span><span>filled <b>${escapeHtml(status.filled_quantity??0)}</b></span></div><div class="strategy-evidence"><span>Source <b>${escapeHtml(item.source_status||"SOURCE_UNSPECIFIED")}</b></span><span>Runtime Input <b>${escapeHtml(item.runtime_input_status||"UNAVAILABLE")}</b></span><span>Signal <b>${escapeHtml(item.signal_status||observation)}</b></span></div><span class="verification-state ${cls}">${escapeHtml(observation)}</span><div class="strategy-pnl-footer ${pnlClass}">${escapeHtml(pnlLabel)}</div></article>`;
    }).join("");
    const marketDetail=document.getElementById("op-market-detail"); if(marketDetail) marketDetail.textContent=JSON.stringify(market||{status:"UNAVAILABLE"},null,2);
    const accountDetail=document.getElementById("op-account-detail"); if(accountDetail) accountDetail.textContent=JSON.stringify({account:data.account,margin:data.margin,pnl:data.pnl,position:data.position,execution_reports:data.execution_reports},null,2);
    const verification=data.verification||{}; setText("op-e2e-status","FULL E2E: "+(verification.full_e2e_status||"NOT_CLAIMED"));
    const summary=document.getElementById("op-verification-summary"); if(summary) summary.innerHTML=[["Scope",verification.scope||"RUN_OBSERVATION_ONLY"],["Source",verification.source||"UNSPECIFIED"],["Environment",data.environment||"UNSPECIFIED"],["Scenario",data.scenario||"UNSPECIFIED"]].map(([label,value])=>`<div><span>${escapeHtml(label)}</span><strong>${escapeHtml(value)}</strong></div>`).join("");
    const vg=document.getElementById("op-verification-grid"); if(vg) vg.innerHTML=strategies.map(function(item,index){const st=item.status||{};return `<div class="verification-item"><span>TRACK ${String(index+1).padStart(2,"0")}</span><strong>${escapeHtml(item.strategy_id)}</strong><span>Current run observation</span><b>${escapeHtml(item.observation_state||"NO_SIGNAL_OBSERVED")}</b><span>Signals / Approved / Routed / Filled</span><b>${escapeHtml(st.reaction_signals??0)} / ${escapeHtml(st.approved??0)} / ${escapeHtml(st.routed??0)} / ${escapeHtml(st.filled_quantity??0)}</b></div>`;}).join("");
    const unavailable=data.unavailable_sections||[]; setText("op-unavailable",unavailable.length?unavailable.join(", "):"현재 Read Model에서 공급되지 않는 세부 항목 없음");
  }

  function renderHighSpeed(data) {
    const connected = data.connection_state === "CONNECTED";
    setText("hs-ticks", connected ? `${data.processed_ticks ?? 0} / ${data.total_ticks ?? 0}` : "?");
    setText("hs-decisions", connected ? (data.strategy_decisions_count ?? 0) : "?");
    setText("hs-orders", connected ? `${data.orders_submitted ?? 0} / ${data.orders_filled ?? 0}` : "?");
    setText("hs-pnl", moneyText(data.total_pnl));
    setText("hs-speed", `${numberText(data.speed_multiplier, 2)}x`);
    setText("hs-scenario", data.scenario_name || "?");
    const progress = Number(data.progress_ratio);
    const bar = document.getElementById("hs-progress");
    if (bar) { const percent = Number.isFinite(progress) ? Math.max(0, Math.min(100, progress * 100)) : 0; bar.value = percent; bar.textContent = `${percent}%`; }
    renderRows("hs-positions-tbody", data.positions, 5, (p) => `
      <tr><td class="mono">${escapeHtml(p.symbol)}</td><td>${escapeHtml(p.qty)}</td>
      <td class="mono">${numberText(p.avg_price)}</td><td class="mono">${numberText(p.current_price)}</td>
      <td class="mono">${escapeHtml(moneyText(p.pnl))}</td></tr>`);
  }

  function renderVirtualExchange(data) {
    setText("vm-underlying", numberText(data.underlying_index_price));
    setText("vm-vkospi", data.volatility_index == null ? "?" : `${numberText(data.volatility_index)} %`);
    setText("vm-instruments", data.instruments_count ?? 0);
    setText("vm-feed-status", data.connection_state || "UNKNOWN");
    setText("vm-feed-badge", data.market_state || "UNKNOWN");
    setText("vm-latency", data.feed_latency_ms == null ? "LATENCY: ?" : `LATENCY: ${numberText(data.feed_latency_ms)} ms`);
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
    root.innerHTML = asks.length || bids.length ? `${rows(asks, "text-down")}<div class="depth-spread">${escapeHtml(depth.spread ?? "?")}</div>${rows(bids, "text-up")}` : `<div class="empty-state">No live market data</div>`;
  }

  function renderVirtualBroker(data) {
    setText("vb-cash", moneyText(data.cash_balance));
    setText("vb-margin", moneyText(data.margin_used));
    setText("vb-margin-available", moneyText(data.margin_available));
    setText("vb-realized", moneyText(data.realized_pnl));
    setText("vb-unrealized", moneyText(data.unrealized_pnl));
    setText("vb-account", data.account_number || "?");
    renderRows("vb-orders-tbody", data.active_orders, 6, (o) => `<tr><td class="mono">${escapeHtml(o.order_id)}</td><td class="mono">${escapeHtml(o.symbol)}</td><td>${escapeHtml(o.side)}</td><td>${escapeHtml(o.qty)}</td><td>${numberText(o.price)}</td><td>${escapeHtml(o.status)}</td></tr>`);
    renderRows("vb-positions-tbody", data.positions, 6, (p) => `<tr><td class="mono">${escapeHtml(p.symbol)}</td><td>${escapeHtml(p.name || p.symbol)}</td><td>${escapeHtml(p.qty)}</td><td class="mono">${numberText(p.avg_price)}</td><td class="mono">${numberText(p.current_price)}</td><td class="mono">${escapeHtml(moneyText(p.pnl))}</td></tr>`);
  }

  function renderPaper(data) {
    setText("paper-connection", data.connection_state || "UNKNOWN");
    setText("paper-auth", data.auth_state || "UNKNOWN");
    setText("paper-risk", data.risk_state || "UNKNOWN");
    setText("paper-account", data.account_number || "?");
    setText("paper-reason", data.blocked_reason || "?");
  }

  function renderLive(data) {
    setText("live-connection", data.connection_state || "UNKNOWN");
    setText("live-auth", data.auth_state || "UNKNOWN");
    setText("live-approval", data.live_approval ? "APPROVED" : "NOT APPROVED");
    setText("live-kill-switch", data.kill_switch_engaged ? "ENGAGED" : "NOT ENGAGED");
    setText("live-execution", data.execution_allowed ? "ALLOWED" : "BLOCKED");
    setText("live-reason", data.blocked_reason || "?");
  }

  function renderRows(id, rows, colspan, renderer) {
    const tbody = document.getElementById(id);
    if (!tbody) return;
    if (!Array.isArray(rows) || rows.length === 0) {
      tbody.innerHTML = `<tr><td colspan="${colspan}" class="empty-state">\ud45c\uc2dc\ud560 \ub370\uc774\ud130\uac00 \uc5c6\uc2b5\ub2c8\ub2e4</td></tr>`;
      return;
    }
    tbody.innerHTML = rows.map(renderer).join("");
  }

  function formatTime(value) {
    if (!value) return "?";
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
  }

  async function poll() {
    if (pollInFlight || document.visibilityState !== "visible") return;
    pollInFlight = true;
    try {
      await fetchSummary();
      await fetchTabDetail(currentTab);
    } finally {
      pollInFlight = false;
    }
  }

  let savedOrder = null;
  try { savedOrder = JSON.parse(localStorage.getItem("p200:tabOrder") || "null"); } catch (_) { savedOrder = null; }
  if (Array.isArray(savedOrder)) {
    const nav = document.querySelector(".tabs-nav");
    const buttons = new Map([...tabButtons].map((btn) => [btn.dataset.tab, btn]));
    savedOrder.forEach((tabId) => { const btn = buttons.get(tabId); if (btn) nav?.appendChild(btn); });
  }
  switchTab(currentTab);
  fetchSummary();
  fetchTabDetail(currentTab);
  refreshRunControls();
  setInterval(poll, pollIntervalMs);
});
