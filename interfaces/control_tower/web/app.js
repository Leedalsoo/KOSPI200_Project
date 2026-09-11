/**
 * Project200 Control Tower — Frontend Controller
 * 5개 환경(High-Speed Test, 가상거래소, 가상증권사, 모의투자, 실투자) 실시간 연동 로직
 */

document.addEventListener("DOMContentLoaded", () => {
  let currentTab = "virtual_exchange";
  const pollIntervalMs = 2000;

  // DOM Elements
  const tabButtons = document.querySelectorAll(".tab-btn");
  const panels = document.querySelectorAll(".env-panel");
  const activeEnvBadge = document.getElementById("active-env-badge");
  const systemTimeEl = document.getElementById("system-time");
  const panicHaltBtn = document.getElementById("btn-panic-halt");
  const dockEnvName = document.getElementById("dock-env-name");
  const auditLogBox = document.getElementById("audit-log-box");

  // Tab mapping info
  const tabNames = {
    high_speed: "High-Speed Test",
    virtual_exchange: "가상거래소 (Virtual Market)",
    virtual_broker: "가상증권사 (Virtual Broker)",
    paper: "모의투자 (KIS Paper)",
    live: "실투자 (KIS Live)",
  };

  // 1. Tab Switching Event Handlers
  tabButtons.forEach((btn) => {
    btn.addEventListener("click", () => {
      const targetTab = btn.getAttribute("data-tab");
      switchTab(targetTab);
    });
  });

  function switchTab(tabId) {
    currentTab = tabId;

    // Update Tab Navigation Active State
    tabButtons.forEach((btn) => {
      if (btn.getAttribute("data-tab") === tabId) {
        btn.classList.add("active");
      } else {
        btn.classList.remove("active");
      }
    });

    // Update Panels Active State
    panels.forEach((p) => {
      if (p.id === `panel-${tabId}`) {
        p.classList.add("active");
      } else {
        p.classList.remove("active");
      }
    });

    // Update Header Badges
    if (activeEnvBadge) {
      activeEnvBadge.textContent = tabNames[tabId] || tabId;
    }
    if (dockEnvName) {
      dockEnvName.textContent = tabNames[tabId] || tabId;
    }

    // Post to Backend
    fetch("/api/active_tab", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ tab_id: tabId }),
    }).catch(() => {});

    // Fetch tab details immediately
    fetchTabDetail(tabId);
  }

  // 2. Panic Halt Button Handler
  if (panicHaltBtn) {
    panicHaltBtn.addEventListener("click", () => {
      const confirmed = confirm("비상정지(PANIC HALT)를 발동하시겠습니까?\n모든 미체결 주문이 즉시 취소되고 신규 주문이 차단됩니다.");
      if (confirmed) {
        fetch("/api/command", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ command: "PANIC_HALT" }),
        })
          .then((res) => res.json())
          .then((data) => {
            alert(`[비상정지 접수] ${data.message || "안전 정지 프로토콜 가동"}`);
            addAuditLog(`[PANIC_HALT] Operator triggered emergency stop. Fail-closed enforced.`);
          })
          .catch((err) => {
            alert("비상정지 요청 실패: " + err.message);
          });
      }
    });
  }

  // 3. Status Polling & Rendering
  async function fetchSummary() {
    try {
      const res = await fetch("/api/status");
      if (!res.ok) return;
      const data = await res.json();

      if (data.system_time && systemTimeEl) {
        systemTimeEl.textContent = data.system_time;
      }

      // Update Tab Status Pills
      if (data.tabs && Array.isArray(data.tabs)) {
        data.tabs.forEach((t) => {
          const tabBtn = document.getElementById(`tab-${t.tab_id}`);
          if (tabBtn) {
            const pill = tabBtn.querySelector(".tab-status-pill");
            if (pill) {
              pill.textContent = t.status;
            }
          }
        });
      }
    } catch (e) {
      // Backend polling error silently suppressed
    }
  }

  async function fetchTabDetail(tabId) {
    try {
      const res = await fetch(`/api/environment/${tabId}`);
      if (!res.ok) return;
      const data = await res.json();

      if (tabId === "virtual_exchange") {
        renderVirtualExchange(data);
      } else if (tabId === "virtual_broker") {
        renderVirtualBroker(data);
      } else if (tabId === "high_speed") {
        renderHighSpeed(data);
      }

      if (data.audit_logs && Array.isArray(data.audit_logs)) {
        data.audit_logs.forEach((log) => addAuditLog(`[${tabId.toUpperCase()}] ${log}`));
      }
    } catch (e) {
      // Detail fetch error silently suppressed
    }
  }

  function renderVirtualExchange(data) {
    const ticksTbody = document.getElementById("vm-ticks-tbody");
    if (ticksTbody && data.recent_ticks) {
      ticksTbody.innerHTML = data.recent_ticks
        .map((t) => {
          const chgClass = t.change >= 0 ? "text-up" : "text-down";
          const sign = t.change >= 0 ? "+" : "";
          const timeFormatted = t.time ? t.time.slice(11, 19) : "--:--:--";
          return `
            <tr>
              <td class="mono">${t.code}</td>
              <td>${t.name}</td>
              <td class="mono">${t.price.toFixed(2)}</td>
              <td class="mono ${chgClass}">${sign}${t.change.toFixed(2)}</td>
              <td class="mono">${t.volume.toLocaleString()}</td>
              <td class="mono text-muted">${timeFormatted}</td>
            </tr>
          `;
        })
        .join("");
    }
  }

  function renderVirtualBroker(data) {
    const ordersTbody = document.getElementById("vb-orders-tbody");
    if (ordersTbody && data.active_orders) {
      ordersTbody.innerHTML = data.active_orders
        .map(
          (o) => `
          <tr>
            <td class="mono">${o.order_id}</td>
            <td class="mono">${o.symbol}</td>
            <td class="${o.side === "BUY" ? "text-up" : "text-down"} font-bold">${o.side}</td>
            <td class="mono">${o.qty}</td>
            <td class="mono">${o.price}</td>
            <td><span class="status-badge badge-green">${o.status}</span></td>
          </tr>
        `
        )
        .join("");
    }

    const posTbody = document.getElementById("vb-positions-tbody");
    if (posTbody && data.positions) {
      posTbody.innerHTML = data.positions
        .map((p) => {
          const pnlClass = p.pnl >= 0 ? "text-up" : "text-down";
          const sign = p.pnl >= 0 ? "+" : "";
          return `
          <tr>
            <td class="mono">${p.symbol}</td>
            <td>${p.name}</td>
            <td class="mono">${p.qty}</td>
            <td class="mono">${p.avg_price.toFixed(2)}</td>
            <td class="mono">${p.current_price.toFixed(2)}</td>
            <td class="mono ${pnlClass}">${sign}₩ ${p.pnl.toLocaleString()}</td>
          </tr>
        `;
        })
        .join("");
    }
  }

  function renderHighSpeed(data) {
    const ticksEl = document.getElementById("hs-ticks");
    if (ticksEl) ticksEl.textContent = `${data.processed_ticks} / ${data.total_ticks}`;
    const decEl = document.getElementById("hs-decisions");
    if (decEl) decEl.textContent = data.strategy_decisions_count;
    const ordEl = document.getElementById("hs-orders");
    if (ordEl) ordEl.textContent = `${data.orders_submitted} / ${data.orders_filled}`;
  }

  function addAuditLog(msg) {
    if (!auditLogBox) return;
    const time = new Date().toLocaleTimeString();
    const line = document.createElement("div");
    line.className = "log-line";
    line.textContent = `[${time}] ${msg}`;
    auditLogBox.appendChild(line);
    // Keep max 5 lines
    while (auditLogBox.children.length > 5) {
      auditLogBox.removeChild(auditLogBox.firstChild);
    }
  }

  // Initial loads & setInterval
  fetchSummary();
  fetchTabDetail(currentTab);
  setInterval(() => {
    fetchSummary();
    fetchTabDetail(currentTab);
  }, pollIntervalMs);
});
