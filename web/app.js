const state = {
  currentRunId: null,
  activeView: "workbenchView",
};

const form = document.querySelector("#predictForm");
const formError = document.querySelector("#formError");
const statusPill = document.querySelector("#statusPill");
const homeTeam = document.querySelector("#homeTeam");
const awayTeam = document.querySelector("#awayTeam");
const exportExcel = document.querySelector("#exportExcel");
const exportPdf = document.querySelector("#exportPdf");
const fixtureResults = document.querySelector("#fixtureResults");
const searchFixtures = document.querySelector("#searchFixtures");
const todayFirstDivision = document.querySelector("#todayFirstDivision");
const randomToday = document.querySelector("#randomToday");
const syncResults = document.querySelector("#syncResults");

document.querySelectorAll(".view-tab").forEach((button) => {
  button.addEventListener("click", () => setActiveView(button.dataset.view));
});

exportExcel.addEventListener("click", () => {
  if (!state.currentRunId) return;
  window.location.href = `/api/report?format=xlsx&run_id=${encodeURIComponent(state.currentRunId)}`;
});

exportPdf.addEventListener("click", () => {
  if (!state.currentRunId) return;
  window.location.href = `/api/report?format=pdf&run_id=${encodeURIComponent(state.currentRunId)}`;
});

searchFixtures.addEventListener("click", async () => {
  formError.textContent = "";
  fixtureResults.innerHTML = `<div class="fixture-empty">正在搜索 API-Football 赛程...</div>`;
  try {
    const response = await fetch("/api/search-fixtures", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        home: homeTeam.value.trim(),
        away: awayTeam.value.trim(),
        apiKey: document.querySelector("#apiKey").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "搜索比赛失败");
    renderFixtureResults(data.fixtures || []);
  } catch (error) {
    fixtureResults.innerHTML = "";
    formError.textContent = toChineseError(error.message);
  }
});

todayFirstDivision.addEventListener("click", async () => {
  formError.textContent = "";
  const originalText = todayFirstDivision.textContent;
  todayFirstDivision.disabled = true;
  todayFirstDivision.textContent = "抓取中";
  fixtureResults.innerHTML = `<div class="fixture-empty">正在抓取北京时间今日甲级联赛...</div>`;
  try {
    const response = await fetch("/api/today-fixtures", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        scope: "first_division",
        apiKey: document.querySelector("#apiKey").value.trim(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "抓取今日甲级联赛失败");
    renderFixtureResults(data.fixtures || [], data.message);
  } catch (error) {
    fixtureResults.innerHTML = "";
    formError.textContent = toChineseError(error.message);
  } finally {
    todayFirstDivision.disabled = false;
    todayFirstDivision.textContent = originalText;
  }
});

randomToday.addEventListener("click", async () => {
  formError.textContent = "";
  const originalText = randomToday.textContent;
  randomToday.disabled = true;
  randomToday.textContent = "抽取中";
  try {
    const response = await fetch("/api/random-today-predict", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(buildPayload()),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "今日随机比赛预测失败");
    renderPrediction(data);
  } catch (error) {
    clearPredictionForError(toChineseError(error.message));
  } finally {
    randomToday.disabled = false;
    randomToday.textContent = originalText;
  }
});

syncResults.addEventListener("click", async () => {
  const originalText = syncResults.textContent;
  syncResults.disabled = true;
  syncResults.textContent = "同步中";
  document.querySelector("#validationAction").textContent = "";
  try {
    const response = await fetch("/api/sync-results", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ apiKey: document.querySelector("#apiKey").value.trim() }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "同步赛果失败");
    const synced = data.synced?.length ?? 0;
    const awaiting = data.awaitingCompletion?.length ?? 0;
    document.querySelector("#validationAction").textContent =
      `同步完成：新增 ${synced} 场赛果，等待完赛 ${awaiting} 场。`;
    renderModelValidation(data.modelValidation || {});
    loadHealth();
  } catch (error) {
    document.querySelector("#validationAction").textContent = toChineseError(error.message);
  } finally {
    syncResults.disabled = false;
    syncResults.textContent = originalText;
  }
});

form.addEventListener("submit", async (event) => {
  event.preventDefault();
  formError.textContent = "";
  const submit = form.querySelector(".primary-action");
  submit.disabled = true;
  submit.textContent = "预测中";

  try {
    const payload = buildPayload();
    const response = await fetch("/api/predict", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "预测失败");
    renderPrediction(data);
  } catch (error) {
    clearPredictionForError(toChineseError(error.message));
  } finally {
    submit.disabled = false;
    submit.textContent = "生成赛前分析";
  }
});

async function init() {
  loadHealth();
  loadModelValidation();
  loadHistory();
}

async function loadHealth() {
  try {
    const response = await fetch("/api/health");
    const data = await response.json();
    const runs = data.storage?.prediction_runs ?? 0;
    const publicMode = Boolean(data.deployment?.publicMode);
    document.querySelector("#apiKeyField").hidden = publicMode;
    if (publicMode) document.querySelector("#apiKey").value = "";
    const apiText = data.api?.configured
      ? (publicMode ? "数据源已接入" : "API 已配置")
      : "API 未配置";
    const retryText = data.api?.retries == null ? "" : ` · 自动重试 ${data.api.retries} 次`;
    document.querySelector("#healthStatus").textContent = `已保存 ${runs} 条预测 · ${apiText}${retryText}`;
    statusPill.textContent = data.api?.configured ? (publicMode ? "在线服务" : "API 已就绪") : "API 待配置";
    statusPill.classList.toggle("offline", !data.api?.configured);
  } catch {
    document.querySelector("#healthStatus").textContent = "健康检查不可用";
    statusPill.textContent = "API 状态未知";
    statusPill.classList.add("offline");
  }
}

async function loadModelValidation() {
  try {
    const response = await fetch("/api/model-validation");
    const data = await response.json();
    renderModelValidation(data);
  } catch {
    document.querySelector("#validationStatus").textContent = "验收状态不可用";
    document.querySelector("#validationMetrics").innerHTML = "";
    document.querySelector("#validationNotes").innerHTML = "";
  }
}

function buildPayload() {
  return {
    mode: "auto",
    home: homeTeam.value.trim(),
    away: awayTeam.value.trim(),
    fixtureId: document.querySelector("#fixtureId").value.trim(),
    apiKey: document.querySelector("#apiKey").value.trim(),
    bankroll: numberValue("#bankroll", 1000),
    unit: numberValue("#unit", 10),
    marketWeight: numberValue("#marketWeight", 0.45),
    minEdge: numberValue("#minEdge", 0.08),
    minQuality: 0.6,
    forcePicks: false,
  };
}

function renderPrediction(data) {
  const match = data.match;
  const meta = data.meta || {};
  const probabilities = data.probabilities || {};
  const display = probabilities.display || probabilities.final || {};
  const pbase = probabilities.pbase || probabilities.model || {};
  const qmkt = probabilities.qmkt || probabilities.market || {};
  const governance = data.modelGovernance || {};

  const homeLabel = teamLabel(match, "home");
  const awayLabel = teamLabel(match, "away");
  document.querySelector("#matchTitle").textContent = `${homeLabel} vs ${awayLabel}`;
  document.querySelector("#matchMeta").textContent =
    [meta.leagueNameZh || meta.leagueName, meta.kickoffBeijing || meta.kickoff, meta.venue]
      .filter(Boolean)
      .join(" · ") || "实时预测";
  document.querySelector("#dataSource").textContent = meta.dataSource || "-";
  document.querySelector("#runId").textContent = data.runId ? `运行 ${data.runId}` : "运行 -";
  state.currentRunId = data.runId || null;
  exportExcel.disabled = !state.currentRunId;
  exportPdf.disabled = !state.currentRunId;

  renderProbabilities(match, display);
  document.querySelector("#homeXg").textContent = formatNumber(data.expectedGoals?.home, 2);
  document.querySelector("#awayXg").textContent = formatNumber(data.expectedGoals?.away, 2);
  renderScores(data.topScores || []);
  renderMarketTable(match, display, pbase, qmkt, governance);
  renderModelAudit(data.modelAudit || {});
  renderDataQuality(data.dataQuality || {});
  renderPortfolio(data.portfolio || {});
  renderRecommendations(data.recommendations || []);
  renderDataProcessing(data.dataProcessing || {});
  renderNotes(data.notes || []);
  loadHealth();
  loadModelValidation();
  loadHistory();
}

function renderFixtureResults(fixtures, message = "") {
  if (!fixtures.length) {
    fixtureResults.innerHTML = `
      <div class="fixture-empty">
        ${escapeHtml(message || "API-Football 未找到两队已排定的未来直接交锋。可以只填球队 A 搜索近期赛程，或填写已知比赛 ID。")}
      </div>
    `;
    return;
  }
  const summary = message ? `<div class="fixture-empty">${escapeHtml(message)}请选择一场后点击“生成赛前分析”。</div>` : "";
  fixtureResults.innerHTML = summary + fixtures
    .map((item) => {
      const home = item.homeZh || item.home || "-";
      const away = item.awayZh || item.away || "-";
      const title = `${home} vs ${away}`;
      const meta = [`ID ${item.fixtureId}`, item.dateBeijing || item.date, item.leagueZh || item.league, item.status]
        .filter(Boolean)
        .join(" · ");
      return `
        <button class="fixture-option" type="button" data-fixture-id="${escapeHtml(item.fixtureId)}" data-home="${escapeHtml(home)}" data-away="${escapeHtml(away)}">
          <strong>${escapeHtml(title)}</strong>
          <span>${escapeHtml(meta)}</span>
        </button>
      `;
    })
    .join("");

  fixtureResults.querySelectorAll(".fixture-option").forEach((button) => {
    button.addEventListener("click", () => {
      document.querySelector("#fixtureId").value = button.dataset.fixtureId || "";
      homeTeam.value = button.dataset.home || homeTeam.value;
      awayTeam.value = button.dataset.away || awayTeam.value;
      const title = `${button.dataset.home || "-"} vs ${button.dataset.away || "-"}`;
      fixtureResults.innerHTML = `
        <div class="fixture-empty">
          已选择 ${escapeHtml(title)}（比赛 ID ${escapeHtml(button.dataset.fixtureId || "-")}）。点击“生成赛前分析”继续。
        </div>
      `;
      formError.textContent = "";
    });
  });
}

function clearPredictionForError(message) {
  formError.textContent = message;
  state.currentRunId = null;
  exportExcel.disabled = true;
  exportPdf.disabled = true;
  document.querySelector("#matchTitle").textContent = "预测失败";
  document.querySelector("#matchMeta").textContent = "请搜索比赛、选择比赛 ID，或换一场今日比赛。";
  document.querySelector("#dataSource").textContent = "API 未完成";
  document.querySelector("#runId").textContent = "运行 -";
  document.querySelector("#probabilityGrid").innerHTML = "";
  document.querySelector("#homeXg").textContent = "-";
  document.querySelector("#awayXg").textContent = "-";
  document.querySelector("#scoreList").innerHTML = "";
  document.querySelector("#marketTable").classList.add("table-idle");
  document.querySelector("#marketTable").innerHTML = `<div class="panel-placeholder">未生成有效分析</div>`;
  renderModelAudit({});
  document.querySelector("#qualitySummary").textContent = "";
  document.querySelector("#qualityFactors").innerHTML = "";
  document.querySelector("#marketStatusCards").innerHTML = "";
  document.querySelector("#portfolioSummary").textContent = "";
  document.querySelector("#recommendations").innerHTML = "";
  renderDataProcessing({});
  renderNotes([message]);
}

function renderProbabilities(match, final) {
  const rows = [
    [teamLabel(match, "home"), final.home_win],
    ["平局", final.draw],
    [teamLabel(match, "away"), final.away_win],
  ];
  document.querySelector("#probabilityGrid").innerHTML = rows
    .map(([label, value]) => {
      const pct = clamp((value || 0) * 100, 0, 100);
      return `
        <article class="prob-card">
          <strong>${escapeHtml(label)}</strong>
          <div class="prob-value">${formatPercent(value)}</div>
          <div class="prob-track"><div class="prob-fill" style="width:${pct}%"></div></div>
        </article>
      `;
    })
    .join("");
}

function renderScores(scores) {
  document.querySelector("#scoreList").innerHTML = scores
    .slice(0, 6)
    .map((item) => `<span class="score-chip">${escapeHtml(item.score)} · ${formatPercent(item.probability)}</span>`)
    .join("");
}

function renderMarketTable(match, display, pbase, qmkt, governance) {
  const rows = [
    [teamLabel(match, "home"), display.home_win, pbase.home_win, qmkt?.home_win],
    ["平局", display.draw, pbase.draw, qmkt?.draw],
    [teamLabel(match, "away"), display.away_win, pbase.away_win, qmkt?.away_win],
  ];
  document.querySelector("#bookmakerCount").textContent = governance.gateLabel || "";
  document.querySelector("#marketTable").classList.remove("table-idle");
  document.querySelector("#marketTable").innerHTML = `
    <div class="table-row header">
      <div>结果</div><div>展示概率</div><div>独立模型</div><div>盘口概率</div>
    </div>
    ${rows
      .map(
        ([label, displayValue, pbaseValue, qmktValue]) => `
          <div class="table-row">
            <div>${escapeHtml(label)}</div>
            <div>${formatPercent(displayValue)}</div>
            <div>${formatPercent(pbaseValue)}</div>
            <div>${qmktValue == null ? "-" : formatPercent(qmktValue)}</div>
          </div>
        `,
      )
      .join("")}
  `;
}

function renderModelAudit(audit) {
  const alert = document.querySelector("#modelAuditAlert");
  if (!audit.evSuspended) {
    alert.classList.add("hidden");
    alert.innerHTML = "";
    return;
  }
  alert.classList.remove("hidden");
  alert.innerHTML = `
    <strong>${escapeHtml(audit.statusLabel || "模型分歧异常")}</strong>
    <span>${escapeHtml(audit.reason || "本场所有市场 EV 已暂停，仅供模型复核。")}</span>
  `;
}

function renderPortfolio(portfolio) {
  document.querySelector("#portfolioSummary").textContent =
    `资金 ${formatMoney(portfolio.bankroll)} · 占用 ${formatMoney(portfolio.total_stake)} · 期望 ${formatMoney(portfolio.expected_bankroll)}`;
}

function renderRecommendations(items) {
  document.querySelector("#recommendations").innerHTML = items
    .map((item) => {
      const suspended = item.ev_status === "SUSPENDED_MODEL_DIVERGENCE";
      const actionClass =
        item.action === "BUY" || item.action === "PAPER_BUY"
          ? "buy"
          : item.action === "NO_MARKET"
            ? "no-market"
            : "watch";
      return `
        <div class="rec-item">
          <div class="rec-head">
            <strong>${escapeHtml(item.market)}</strong>
            <span>${escapeHtml(item.selection)}</span>
          </div>
          <span class="action ${actionClass}">${escapeHtml(actionLabel(item.action))}</span>
          <div class="rec-metrics">
            <span>赔率 <strong>${item.odds == null ? "-" : formatNumber(item.odds, 2)}</strong></span>
            <span>模型概率 <strong>${formatPercent(item.model_probability)}</strong></span>
            <span>${suspended ? "EV" : "研究 EV"} <strong>${suspended ? "已暂停" : item.expected_value_per_unit == null ? "-" : formatPercent(item.expected_value_per_unit)}</strong></span>
            <span>${suspended ? "执行状态" : "保守研究 EV"} <strong>${suspended ? "不可执行" : item.conservative_expected_value_per_unit == null ? "-" : formatPercent(item.conservative_expected_value_per_unit)}</strong></span>
          </div>
          <p class="rec-reason">${escapeHtml(item.reason || "")}</p>
        </div>
      `;
    })
    .join("");
}

function renderDataQuality(quality) {
  const score = quality.score;
  const grade = quality.gradeLabel || "-";
  document.querySelector("#qualitySummary").textContent =
    score == null ? "质量评分 -" : `质量 ${formatPercent(score)} · ${grade}`;

  const factors = quality.factors || {};
  const factorRows = [
    ["比赛确定", factors.fixture_certainty],
    ["赔率完整", factors.odds_completeness],
    ["指定庄家", factors.bookmaker_quality],
    ["球队评分", factors.team_rating_availability],
    ["情景数据", factors.context_availability],
    ["阵容信息", factors.lineup_availability],
  ];
  document.querySelector("#qualityFactors").innerHTML = factorRows
    .map(([label, value]) => {
      const pct = clamp((Number(value) || 0) * 100, 0, 100);
      return `
        <div class="quality-factor">
          <span>${escapeHtml(label)}</span>
          <strong>${formatPercent(value)}</strong>
          <div class="mini-track"><div style="width:${pct}%"></div></div>
        </div>
      `;
    })
    .join("");

  const markets = quality.markets || [];
  document.querySelector("#marketStatusCards").innerHTML = markets
    .map((item) => {
      const status = item.status || "missing";
      const line = item.line == null ? "" : ` · 盘口 ${formatLine(item.line)}`;
      return `
        <div class="market-status ${escapeHtml(status)}">
          <strong>${escapeHtml(item.label || "-")}</strong>
          <span>${escapeHtml(item.status_label || item.statusLabel || "-")}${escapeHtml(line)}</span>
          <p>${escapeHtml(item.details || "")}</p>
        </div>
      `;
    })
    .join("");
}

function renderNotes(notes) {
  document.querySelector("#notesList").innerHTML = notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("");
}

function setActiveView(viewId) {
  state.activeView = viewId;
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
  });
  document.querySelectorAll(".content-view").forEach((view) => {
    view.classList.toggle("active", view.id === viewId);
  });
}

function renderDataProcessing(processing) {
  const home = processing.home || {};
  const away = processing.away || {};
  const populated = Boolean(home.matches?.length || away.matches?.length);
  const coverage = document.querySelector("#dataCoverage");
  if (!populated) {
    coverage.textContent = "等待生成分析";
    coverage.classList.remove("insufficient");
    document.querySelector("#processingSteps").innerHTML = `<div class="panel-placeholder">等待真实数据</div>`;
    document.querySelector("#processingMetrics").innerHTML = `<div class="panel-placeholder">等待真实数据</div>`;
    renderLineChart("#homeFormChart", [], []);
    renderLineChart("#awayFormChart", [], []);
    renderLineChart("#pointsTrendChart", [], []);
    document.querySelector("#homeRecentTable").innerHTML = `<div class="panel-placeholder">等待真实数据</div>`;
    document.querySelector("#awayRecentTable").innerHTML = `<div class="panel-placeholder">等待真实数据</div>`;
    document.querySelector("#oddsTrendNotice").textContent = "生成分析后检查是否具备多个赛前赔率快照。";
    return;
  }

  coverage.textContent = processing.coverageReady
    ? `样本通过 · 双方至少 ${processing.requiredMatches} 场`
    : `样本不足 · 要求每队至少 ${processing.requiredMatches} 场`;
  coverage.classList.toggle("insufficient", !processing.coverageReady);
  document.querySelector("#processingSteps").innerHTML = (processing.steps || [])
    .map((step, index) => `
      <div class="process-step ${step.status === "不足" || step.status === "缺失" || step.status === "限制" ? "warn" : ""}">
        <span class="step-node">${index + 1}</span>
        <strong>${escapeHtml(step.label)}<br><span class="muted">${escapeHtml(step.status)}</span></strong>
        <p>${escapeHtml(step.detail)}</p>
      </div>
    `)
    .join("");
  document.querySelector("#processingMetrics").innerHTML = renderProcessingMetrics(home, away);

  document.querySelector("#homeChartTitle").textContent = `${home.displayName || "主队"} · 进球与失球`;
  document.querySelector("#awayChartTitle").textContent = `${away.displayName || "客队"} · 进球与失球`;
  renderLineChart(
    "#homeFormChart",
    (home.matches || []).map((item) => shortDate(item.dateBeijing)),
    [
      { values: (home.matches || []).map((item) => item.goalsFor), color: "#f26a21" },
      { values: (home.matches || []).map((item) => item.goalsAgainst), color: "#10899a" },
    ],
  );
  renderLineChart(
    "#awayFormChart",
    (away.matches || []).map((item) => shortDate(item.dateBeijing)),
    [
      { values: (away.matches || []).map((item) => item.goalsFor), color: "#f26a21" },
      { values: (away.matches || []).map((item) => item.goalsAgainst), color: "#10899a" },
    ],
  );
  const maximumMatches = Math.max(home.matches?.length || 0, away.matches?.length || 0);
  const sequenceLabels = Array.from({ length: maximumMatches }, (_, index) => `第${index + 1}场`);
  renderLineChart("#pointsTrendChart", sequenceLabels, [
    { values: (home.matches || []).map((item) => item.cumulativePoints), color: "#f26a21" },
    { values: (away.matches || []).map((item) => item.cumulativePoints), color: "#3068ae" },
  ]);
  document.querySelector("#homeRecentTitle").textContent = `${home.displayName || "主队"} · 近 ${home.validCount || 0} 场`;
  document.querySelector("#awayRecentTitle").textContent = `${away.displayName || "客队"} · 近 ${away.validCount || 0} 场`;
  renderRecentTable("#homeRecentTable", home.matches || []);
  renderRecentTable("#awayRecentTable", away.matches || []);
  document.querySelector("#oddsTrendNotice").textContent =
    processing.oddsTrend?.message || "当前缺少可验证的连续赔率快照。";
}

function renderProcessingMetrics(home, away) {
  const rows = [
    ["有效样本", `${home.validCount ?? 0} 场`, `${away.validCount ?? 0} 场`],
    ["场均积分", formatNumber(home.pointsPerGame, 2), formatNumber(away.pointsPerGame, 2)],
    ["场均进球", formatNumber(home.goalsForAverage, 2), formatNumber(away.goalsForAverage, 2)],
    ["场均失球", formatNumber(home.goalsAgainstAverage, 2), formatNumber(away.goalsAgainstAverage, 2)],
    ["进攻评分", formatNumber(home.attackRating, 2), formatNumber(away.attackRating, 2)],
    ["防守评分", formatNumber(home.defenseRating, 2), formatNumber(away.defenseRating, 2)],
    ["估算 Elo", formatNumber(home.estimatedElo, 0), formatNumber(away.estimatedElo, 0)],
  ];
  return `
    <div class="metric-cell heading">指标</div>
    <div class="metric-cell heading">${escapeHtml(home.displayName || "主队")}</div>
    <div class="metric-cell heading">${escapeHtml(away.displayName || "客队")}</div>
    ${rows
      .map(([label, homeValue, awayValue]) => `
        <div class="metric-cell heading">${escapeHtml(label)}</div>
        <div class="metric-cell value">${escapeHtml(homeValue)}</div>
        <div class="metric-cell value">${escapeHtml(awayValue)}</div>
      `)
      .join("")}
  `;
}

function renderRecentTable(selector, matches) {
  const container = document.querySelector(selector);
  if (!matches.length) {
    container.innerHTML = `<div class="panel-placeholder">没有有效的近期 90 分钟赛果</div>`;
    return;
  }
  container.innerHTML = `
    <div class="recent-row header"><span>日期</span><span>对手 / 赛事</span><span>场地</span><span>比分</span><span>赛果</span></div>
    ${matches
      .map((item) => {
        const resultClass = item.resultLabel === "胜" ? "win" : item.resultLabel === "平" ? "draw" : "loss";
        const raw = item.opponent && item.opponent !== item.opponentZh
          ? `<small class="raw-name">API 原名：${escapeHtml(item.opponent)}</small>`
          : "";
        return `
          <div class="recent-row">
            <span>${escapeHtml(shortDate(item.dateBeijing))}</span>
            <span>${escapeHtml(item.opponentZh || "-")}<small class="raw-name">${escapeHtml(item.leagueZh || "-")}</small>${raw}</span>
            <span>${escapeHtml(item.venueLabel || "-")}</span>
            <strong>${escapeHtml(`${item.goalsFor}-${item.goalsAgainst}`)}</strong>
            <span class="result-pill ${resultClass}">${escapeHtml(item.resultLabel || "-")}</span>
          </div>
        `;
      })
      .join("")}
  `;
}

function renderLineChart(selector, labels, series) {
  const container = document.querySelector(selector);
  const available = series.some((item) => item.values.length);
  if (!available || !labels.length) {
    container.innerHTML = `<div class="panel-placeholder">尚无真实趋势数据</div>`;
    return;
  }
  const width = 620;
  const height = 210;
  const left = 36;
  const right = 14;
  const top = 18;
  const bottom = 32;
  const values = series.flatMap((item) => item.values).filter((value) => Number.isFinite(Number(value)));
  const maxValue = Math.max(1, ...values);
  const roundedMax = Math.max(3, Math.ceil(maxValue));
  const x = (index) => left + ((width - left - right) * index) / Math.max(1, labels.length - 1);
  const y = (value) => top + (height - top - bottom) * (1 - Number(value) / roundedMax);
  const grid = Array.from({ length: 4 }, (_, index) => {
    const value = (roundedMax * index) / 3;
    const position = y(value);
    return `<line x1="${left}" y1="${position}" x2="${width - right}" y2="${position}" class="chart-grid-line"></line><text x="${left - 8}" y="${position + 4}" class="chart-axis" text-anchor="end">${value.toFixed(value % 1 ? 1 : 0)}</text>`;
  }).join("");
  const tickStep = labels.length > 6 ? 2 : 1;
  const ticks = labels.map((label, index) => index % tickStep === 0 || index === labels.length - 1
    ? `<text x="${x(index)}" y="${height - 10}" class="chart-axis" text-anchor="middle">${escapeHtml(label)}</text>`
    : "").join("");
  const lines = series.map((item) => {
    if (!item.values.length) return "";
    const points = item.values.map((value, index) => `${x(index)},${y(value)}`).join(" ");
    const dots = item.values.map((value, index) => `<circle cx="${x(index)}" cy="${y(value)}" r="3" fill="${item.color}"></circle>`).join("");
    return `<polyline points="${points}" fill="none" stroke="${item.color}" stroke-width="2.3" stroke-linejoin="round" stroke-linecap="round"></polyline>${dots}`;
  }).join("");
  container.innerHTML = `
    <svg viewBox="0 0 ${width} ${height}" aria-hidden="true">
      ${grid}
      ${ticks}
      ${lines}
    </svg>
  `;
}

async function loadHistory() {
  try {
    const response = await fetch("/api/recent-predictions");
    const data = await response.json();
    renderHistory(data.runs || []);
  } catch {
    document.querySelector("#historyList").innerHTML = `<div class="panel-placeholder">本地记录读取失败</div>`;
  }
}

function renderHistory(runs) {
  if (!runs.length) {
    document.querySelector("#historyList").innerHTML = `<div class="panel-placeholder">暂无预测记录</div>`;
    return;
  }
  document.querySelector("#historyList").innerHTML = runs
    .map((run) => `
      <div class="history-item">
        <div>
          <strong>${escapeHtml(`${run.homeZh || "主队"} vs ${run.awayZh || "客队"}`)}</strong>
          <span class="muted">运行 ${escapeHtml(run.id)} · ${escapeHtml(run.leagueZh || "-")}</span>
        </div>
        <span class="muted">${escapeHtml(run.kickoffBeijing || run.created_at || "-")}</span>
        <div class="history-actions">
          <a class="history-link" href="/api/report?format=xlsx&amp;run_id=${encodeURIComponent(run.id)}">Excel</a>
          <a class="history-link" href="/api/report?format=pdf&amp;run_id=${encodeURIComponent(run.id)}">PDF</a>
        </div>
      </div>
    `)
    .join("");
}

function renderModelValidation(validation) {
  const coverage = validation.marketCoverage || {};
  const split = validation.split || {};
  document.querySelector("#validationStatus").textContent =
    `${validation.statusLabel || "-"} · ${validation.formalEvLabel || "正式EV关闭"}`;
  const rows = [
    ["结构化报价", coverage.structured_quotes ?? 0],
    ["合格赛前快照", coverage.eligible_pre_match_snapshots ?? 0],
    ["已隔离赛后快照", coverage.post_kickoff_snapshots ?? 0],
    ["验证样本", split.validation ?? 0],
  ];
  document.querySelector("#validationMetrics").innerHTML = rows
    .map(
      ([label, value]) => `
        <div class="validation-metric">
          <span>${escapeHtml(label)}</span>
          <strong>${escapeHtml(value)}</strong>
        </div>
      `,
    )
    .join("");
  const checks = (validation.checks || [])
    .filter((item) => !item.passed)
    .slice(0, 4)
    .map((item) => `${item.label}不足：${item.detail}`);
  const notes = [
    `合格已结算样本 ${validation.eligibleSamples ?? 0}，独立比赛 ${validation.distinctFixtures ?? 0}。`,
    ...checks,
    ...(validation.notes || []).slice(0, 3),
  ];
  document.querySelector("#validationNotes").innerHTML =
    notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("");
}

function numberValue(selector, fallback) {
  const value = Number.parseFloat(document.querySelector(selector).value);
  return Number.isFinite(value) ? value : fallback;
}

function formatPercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatNumber(value, digits) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function formatMoney(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return `¥${Number(value).toFixed(2)}`;
}

function formatLine(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return Number(value).toFixed(2).replace(/\.00$/, "").replace(/0$/, "");
}

function shortDate(value) {
  const text = String(value || "");
  const date = text.slice(5, 10);
  return date || "-";
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function escapeHtml(value) {
  return String(value ?? "")
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");
}

function teamLabel(match, side) {
  const zhKey = `${side}Zh`;
  return match?.[zhKey] || match?.[side] || "-";
}

function actionLabel(action) {
  return {
    BUY: "研究通过",
    PAPER_BUY: "演示候选",
    WATCH: "观望",
    NO_MARKET: "市场缺失",
  }[action] || action || "-";
}

function responseError(data, fallback) {
  const error = new Error(data?.error || fallback);
  error.kind = data?.errorKind || "";
  error.retryable = Boolean(data?.retryable);
  return error;
}

function toChineseError(message) {
  if (message.includes("No upcoming head-to-head fixture")) {
    return "API-Football 未找到两队已排定的未来直接交锋。请点击“搜索比赛”选择赛程，或填写已知比赛 ID。";
  }
  if (message.includes("No API-Football team found")) {
    return "API-Football 未找到该球队，请检查球队英文名。";
  }
  if (message.includes("UNEXPECTED_EOF") || message.includes("EOF occurred") || message.includes("protocol")) {
    return "API-Football 连接被中断。系统会自动重试；如果仍失败，请稍后再试，或检查网络、VPN、代理、防火墙。";
  }
  if (message.includes("CERTIFICATE_VERIFY_FAILED")) {
    return "API-Football HTTPS 证书验证失败。请重启本地服务；如果仍失败，请更新 certifi 或运行 Python 证书安装脚本。";
  }
  return message;
}

init();
