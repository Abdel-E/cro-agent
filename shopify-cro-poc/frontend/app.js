const API = (window.API_BASE || "http://localhost:8000").replace(/\/+$/, "");

// ── Panel definitions: three hardcoded visitor personas ──────────────
const PANELS = [
  {
    context: { device_type: "mobile", traffic_source: "meta", is_returning: false },
    label: "Mobile · Meta Ad · New",
  },
  {
    context: { device_type: "desktop", traffic_source: "direct", is_returning: false },
    label: "Desktop · Direct · New",
  },
  {
    context: { device_type: "desktop", traffic_source: "direct", is_returning: true },
    label: "Returning Visitor",
  },
];

const decisions = [null, null, null]; // active decision per panel
const feedbackSent = [false, false, false];
let agentAutoTimer = null;
let agentTickInFlight = false;
let latestReasoning = null;

// ── Helpers ──────────────────────────────────────────────────────────

async function postJson(url, body) {
  const r = await fetch(url, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

async function getJson(url) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${r.status}`);
  return r.json();
}

function pct(v) { return `${(v * 100).toFixed(1)}%`; }

// ── Panel rendering ─────────────────────────────────────────────────

function renderPanel(idx, data) {
  const c = data.content || {};
  const hero = document.getElementById(`hero-${idx}`);
  const headline = document.getElementById(`headline-${idx}`);
  const subtitle = document.getElementById(`subtitle-${idx}`);
  const cta = document.getElementById(`cta-${idx}`);
  const trust = document.getElementById(`trust-${idx}`);
  const meta = document.getElementById(`meta-${idx}`);

  hero.className = "hero " + (c.style_class || "variant-a");
  headline.textContent = c.headline || "—";
  subtitle.textContent = c.subtitle || "";
  cta.textContent = c.cta_text || "Shop Now";

  trust.innerHTML = (c.trust_signals || [])
    .map((s) => `<span class="trust-pill">${s}</span>`)
    .join("");

  meta.textContent =
    `Variant ${data.variant_id} · Segment: ${data.segment} · Score: ${data.probability.toFixed(3)}`;
}

async function loadPanel(idx) {
  try {
    const d = await postJson(`${API}/decide`, {
      surface_id: "hero_banner",
      context: PANELS[idx].context,
    });
    decisions[idx] = d;
    feedbackSent[idx] = false;
    renderPanel(idx, d);
  } catch (e) {
    document.getElementById(`headline-${idx}`).textContent = `Error: ${e.message}`;
  }
}

async function sendPanelFeedback(idx, reward) {
  if (!decisions[idx] || feedbackSent[idx]) return;
  feedbackSent[idx] = true;
  try {
    await postJson(`${API}/feedback`, {
      decision_id: decisions[idx].decision_id,
      variant_id: decisions[idx].variant_id,
      reward,
    });
  } catch { /* best-effort */ }
  fetchMetrics();
}

// ── Dashboard ───────────────────────────────────────────────────────

function renderKpis(data, agentStatus = null) {
  const t = data.totals || {};
  const segCount = Object.keys(data.segments || {}).length;
  const loopTicks = agentStatus?.tick_count || 0;
  const activeExperiments = (agentStatus?.active_experiments || []).length;

  document.getElementById("kpis").innerHTML = [
    { label: "Total Impressions", value: t.impressions || 0 },
    { label: "Total Clicks", value: t.successes || 0 },
    { label: "Overall CTR", value: pct(t.ctr || 0) },
    { label: "Active Segments", value: segCount },
    { label: "Sandbox Ticks", value: loopTicks },
    { label: "Active Sandbox Experiments", value: activeExperiments },
  ]
    .map(
      (k) => `
    <div class="kpi">
      <span class="kpi-label">${k.label}</span>
      <strong>${k.value}</strong>
    </div>`
    )
    .join("");
}

function renderSegments(data) {
  const segs = data.segments || {};
  const grid = document.getElementById("segment-grid");
  if (!Object.keys(segs).length) {
    grid.innerHTML = '<p style="font-size:12px;color:var(--muted)">No segment data yet — run a simulation or click CTAs.</p>';
    return;
  }

  grid.innerHTML = Object.entries(segs)
    .map(([segId, s]) => {
      const vars = s.variants || {};
      const total = s.totals?.impressions || 1;
      const bars = ["A", "B", "C"]
        .map((v) => {
          const imp = vars[v]?.impressions || 0;
          const share = imp / total;
          const ctr = vars[v]?.ctr || 0;
          return `
          <div class="seg-bar-row">
            <span class="seg-bar-label">${v}</span>
            <div class="seg-bar-track">
              <div class="seg-bar-fill seg-bar-fill--${v.toLowerCase()}" style="width:${Math.round(share * 100)}%"></div>
            </div>
            <span class="seg-bar-pct">${pct(share)}</span>
            <span class="seg-bar-pct">${pct(ctr)}</span>
          </div>`;
        })
        .join("");

      return `
        <div class="seg-card">
          <div class="seg-card-title">${segId.replace(/_/g, " ")}</div>
          <div style="display:flex;justify-content:space-between;font-size:10px;color:var(--muted);margin-bottom:2px">
            <span></span><span style="width:36px;text-align:right">Share</span><span style="width:36px;text-align:right">CTR</span>
          </div>
          ${bars}
          <div style="font-size:10px;color:var(--muted);margin-top:4px">${s.totals?.impressions || 0} impressions</div>
        </div>`;
    })
    .join("");
}

function renderHistory(data) {
  const list = document.getElementById("history-list");
  const history = (data.history || []).slice(-10).reverse();
  if (!history.length) {
    list.innerHTML = '<li class="history-item"><span>No events yet</span><span>—</span></li>';
    return;
  }
  list.innerHTML = history
    .map(
      (h) => `
    <li class="history-item">
      <span>#${h.step} · Variant ${h.variant_id} · <em>${h.segment}</em></span>
      <span class="reward-${h.reward}">${h.reward === 1 ? "click" : "no click"}</span>
    </li>`
    )
    .join("");
}

async function fetchMetrics() {
  try {
    const [metricsResp, statusResp] = await Promise.all([
      fetch(`${API}/metrics`),
      fetch(`${API}/agent/status`),
    ]);
    if (!metricsResp.ok) return;

    const data = await metricsResp.json();
    const agentStatus = statusResp.ok ? await statusResp.json() : null;

    renderKpis(data, agentStatus);
    renderSegments(data);
    renderHistory(data);
  } catch { /* silent */ }
}

// ── Experimental agent sandbox ───────────────────────────────────────

function renderAgentKpis(status) {
  const kpis = document.getElementById("agent-kpis");
  const active = (status.active_experiments || []).length;
  const completed = (status.completed_experiments || []).length;
  const sessions = status.journey_sessions?.total || 0;
  kpis.innerHTML = [
    { label: "Sandbox Ticks", value: status.tick_count || 0 },
    { label: "Latest Signals", value: status.latest_observations || 0 },
    { label: "Active Experiments", value: active },
    { label: "Completed Experiments", value: completed },
    { label: "Sandbox Sessions", value: sessions },
  ]
    .map((k) => `
      <div class="kpi">
        <span class="kpi-label">${k.label}</span>
        <strong>${k.value}</strong>
      </div>`)
    .join("");
}

function renderJourneyStageSnapshot(metrics) {
  const grid = document.getElementById("journey-stage-grid");
  const stages = metrics?.stages || {};
  const order = ["landing", "product_page", "cart"];

  grid.innerHTML = order
    .map((stage) => {
      const s = stages[stage] || {};
      const conv = s.conversion_rate || 0;
      const imp = s.impressions || 0;
      const drops = s.drop_offs || 0;
      return `
        <div class="stage-row">
          <div class="stage-head">
            <span>${stage.replace(/_/g, " ")}</span>
            <span>${pct(conv)} conv</span>
          </div>
          <div class="stage-track"><div class="stage-fill" style="width:${Math.round(conv * 100)}%"></div></div>
          <div class="stage-head" style="margin-top:4px">
            <span>${imp} impressions</span>
            <span>${drops} drop-offs</span>
          </div>
        </div>`;
    })
    .join("");
}

function renderAgentExperiments(status) {
  const host = document.getElementById("agent-experiments");
  const active = status.active_experiments || [];
  const completed = (status.completed_experiments || []).slice(-3).reverse();

  if (!active.length && !completed.length) {
    host.innerHTML = '<div class="agent-item">No experiments yet. Run a tick with simulated sessions.</div>';
    return;
  }

  host.innerHTML = [
    ...active.map((exp) => `
      <div class="agent-item">
        <strong>${exp.experiment_id} · ${exp.stage}</strong>
        <span>Status: active · Started at ${exp.start_impressions} sandbox stage impressions</span>
      </div>`),
    ...completed.map((exp) => `
      <div class="agent-item">
        <strong>${exp.experiment_id} · ${exp.stage}</strong>
        <span>Graduated: winner ${exp.winner_variant || "—"} at ${pct(exp.winner_rate || 0)}</span>
      </div>`),
  ].join("");
}

function renderAgentHypotheses(reasoning) {
  const host = document.getElementById("agent-hypotheses");
  const hypotheses = reasoning?.hypotheses || [];
  if (!hypotheses.length) {
    host.innerHTML = '<div class="agent-item">No hypotheses for current thresholds.</div>';
    return;
  }

  host.innerHTML = hypotheses
    .slice(0, 4)
    .map((h) => `
      <div class="agent-item">
        <strong>${h.hypothesis_id} · ${h.stage}</strong>
        <span>${h.rationale}</span>
      </div>`)
    .join("");
}

function renderAgentEvents(events) {
  const list = document.getElementById("agent-events");
  if (!events || !events.length) {
    list.innerHTML = '<li class="agent-event">No loop events yet.</li>';
    return;
  }

  list.innerHTML = events
    .map((evt) => `
      <li class="agent-event" data-type="${evt.event_type}">
        <strong>#${evt.tick} · ${evt.event_type}</strong><br />
        <span>${evt.message}</span>
      </li>`)
    .join("");
}

function updateAgentLoopStatus(message) {
  const el = document.getElementById("agent-loop-status");
  if (!el) return;
  el.textContent = message;
}

function getAgentSessionsPerTick() {
  const input = document.getElementById("agent-sessions");
  const raw = Number(input.value);
  if (!Number.isFinite(raw)) return 40;
  return Math.max(0, Math.min(400, Math.round(raw)));
}

async function fetchReasoningForPanel() {
  latestReasoning = await getJson(
    `${API}/journey/reasoning?min_stage_impressions=15&stage_drop_off_threshold=0.5&max_hypotheses=4&max_experiments=4`
  );
  document.getElementById("agent-insight").textContent =
    latestReasoning.insight || "No reasoning yet.";
  renderAgentHypotheses(latestReasoning);
}

async function refreshAgentView() {
  try {
    const [status, history] = await Promise.all([
      getJson(`${API}/agent/status`),
      getJson(`${API}/agent/history?limit=40`),
    ]);
    renderAgentKpis(status);
    renderJourneyStageSnapshot(status.journey_metrics || {});
    renderAgentExperiments(status);
    renderAgentEvents(history.events || []);
    updateAgentLoopStatus(
      `Sandbox status: tick #${status.tick_count || 0} · active ${
        (status.active_experiments || []).length
      } · completed ${(status.completed_experiments || []).length}`
    );
    await fetchReasoningForPanel();
  } catch (e) {
    updateAgentLoopStatus(`Agent view error: ${e.message}`);
    document.getElementById("agent-insight").textContent = `Agent view error: ${e.message}`;
  }
}

async function runAgentTick() {
  if (agentTickInFlight) return;
  agentTickInFlight = true;

  try {
    const payload = {
      simulate_sessions: getAgentSessionsPerTick(),
      min_stage_impressions: 15,
      stage_drop_off_threshold: 0.5,
      min_segment_impressions: 8,
      segment_gap_threshold: 0.08,
      trend_window: 20,
      trend_decline_threshold: 0.15,
      max_hypotheses: 3,
      max_experiments: 3,
    };
    const tick = await postJson(`${API}/agent/tick`, payload);

    renderAgentKpis(tick.status || {});
    renderJourneyStageSnapshot(tick.status?.journey_metrics || {});
    renderAgentExperiments(tick.status || {});
    renderAgentEvents(tick.events || []);
    updateAgentLoopStatus(
      `Sandbox tick #${tick.tick} complete · simulated ${tick.simulation?.sessions || 0} sessions · launched ${
        (tick.launched || []).length
      } · graduated ${(tick.graduated || []).length}`
    );
    document.getElementById("agent-insight").textContent = tick.insight || "No insight returned.";
    fetchMetrics();
    await fetchReasoningForPanel();
  } catch (e) {
    updateAgentLoopStatus(`Agent tick error: ${e.message}`);
    document.getElementById("agent-insight").textContent = `Agent tick error: ${e.message}`;
  } finally {
    agentTickInFlight = false;
  }
}

function stopAutoLoop() {
  if (agentAutoTimer) {
    clearInterval(agentAutoTimer);
    agentAutoTimer = null;
  }
  updateAgentLoopStatus("Auto sandbox stopped. You can run a manual tick anytime.");
  document.getElementById("btn-agent-auto").textContent = "Start Auto Sandbox";
}

function toggleAutoLoop() {
  if (agentAutoTimer) {
    stopAutoLoop();
    return;
  }

  document.getElementById("btn-agent-auto").textContent = "Stop Auto Sandbox";
  updateAgentLoopStatus("Auto sandbox running... a tick is executed every 3 seconds.");
  runAgentTick();
  agentAutoTimer = setInterval(runAgentTick, 3000);
}

// ── Init ────────────────────────────────────────────────────────────

async function init() {
  // Wire CTA clicks for each panel
  for (let i = 0; i < 3; i++) {
    const idx = i;
    document.getElementById(`cta-${idx}`).addEventListener("click", () => {
      sendPanelFeedback(idx, 1);
    });
  }

  // Refresh button
  document.getElementById("btn-refresh").addEventListener("click", () => {
    for (let i = 0; i < 3; i++) {
      // Send no-click feedback for old decisions
      if (decisions[i] && !feedbackSent[i]) sendPanelFeedback(i, 0);
      loadPanel(i);
    }
  });

  // Reset button
  document.getElementById("btn-reset").addEventListener("click", async () => {
    stopAutoLoop();
    await postJson(`${API}/reset`, {});
    for (let i = 0; i < 3; i++) loadPanel(i);
    fetchMetrics();
    refreshAgentView();
  });

  document.getElementById("btn-agent-step").addEventListener("click", runAgentTick);
  document.getElementById("btn-agent-auto").addEventListener("click", toggleAutoLoop);
  document.getElementById("btn-agent-refresh").addEventListener("click", refreshAgentView);

  // Load initial panels
  for (let i = 0; i < 3; i++) loadPanel(i);
  fetchMetrics();
  refreshAgentView();

  // Poll metrics
  setInterval(fetchMetrics, 3000);
  setInterval(refreshAgentView, 6000);
}

init();
