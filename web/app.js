const DEFAULT_BATCH_LIMIT = 10;
const MAX_BATCH_LIMIT = 30;

const state = {
  currentRunId: null,
  activeView: "workbenchView",
  batchResult: null,
  recentBatches: [],
  batchHistorySearch: "",
  batchHistoryPage: 1,
  batchHistoryPageSize: 5,
  historyRuns: [],
  historyPage: 1,
  historyPageSize: 8,
  historyDetailsCache: new Map(),
  replayCache: new Map(),
  batchFilters: {
    action: "all",
    quality: "all",
    query: "",
    league: "all",
    bookmaker: "all",
    coverage: "all",
    timeWindow: "all",
    sort: "priority",
  },
  dailyReview: null,
  loaded: {
    modelValidation: false,
    liveReadiness: false,
    dailyReview: false,
    paperLedger: false,
  },
};

const appShell = document.querySelector(".app-shell");
const form = document.querySelector("#predictForm");
const formError = document.querySelector("#formError");
const statusPill = document.querySelector("#statusPill");
const homeTeam = document.querySelector("#homeTeam");
const awayTeam = document.querySelector("#awayTeam");
const exportExcel = document.querySelector("#exportExcel");
const exportPdf = document.querySelector("#exportPdf");
const openTrace = document.querySelector("#openTrace");
const fixtureResults = document.querySelector("#fixtureResults");
const batchPoolContent = document.querySelector("#batchPoolContent");
const batchPoolStatus = document.querySelector("#batchPoolStatus");
const searchFixtures = document.querySelector("#searchFixtures");
const todayFirstDivision = document.querySelector("#todayFirstDivision");
const randomToday = document.querySelector("#randomToday");
const batchToday = document.querySelector("#batchToday");
const batchCount = document.querySelector("#batchCount");
const batchFixtureIds = document.querySelector("#batchFixtureIds");
const historicalPredict = document.querySelector("#historicalPredict");
const syncResults = document.querySelector("#syncResults");
const reviewDate = document.querySelector("#reviewDate");
const loadReview = document.querySelector("#loadReview");
const exportReviewExcel = document.querySelector("#exportReviewExcel");
const traceDrawer = document.querySelector("#traceDrawer");
const traceDrawerContent = document.querySelector("#traceDrawerContent");
const historyTracePreview = document.querySelector("#historyTracePreview");
const historyPreviewCrumbs = document.querySelector("#historyPreviewCrumbs");
const historyRailContent = document.querySelector("#historyRailContent");
const preMatchCabin = document.querySelector("#preMatchCabin");
const preMatchCabinStatus = document.querySelector("#preMatchCabinStatus");
const liveCabin = document.querySelector("#liveCabin");
const liveCabinStatus = document.querySelector("#liveCabinStatus");
const historyLedger = document.querySelector("#historyLedger");
const historyLedgerStatus = document.querySelector("#historyLedgerStatus");

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

openTrace?.addEventListener("click", () => {
  if (!state.currentRunId) return;
  traceDrawer?.classList.remove("is-minimized");
  setActiveView("dataView");
  document.querySelector("#dataView")?.scrollIntoView({ behavior: "smooth", block: "start" });
});

traceDrawer?.querySelector(".trace-close")?.addEventListener("click", () => {
  traceDrawer.classList.toggle("is-minimized");
});

searchFixtures.addEventListener("click", async () => {
  formError.textContent = "";
  fixtureResults.innerHTML = `<div class="fixture-empty">搜索中...</div>`;
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
  fixtureResults.innerHTML = `<div class="fixture-empty">抓取中...</div>`;
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

historicalPredict?.addEventListener("click", async () => {
  formError.textContent = "";
  const originalText = historicalPredict.textContent;
  historicalPredict.disabled = true;
  historicalPredict.textContent = "模拟中";
  try {
    const response = await fetch("/api/predict", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        ...buildPayload(),
        mode: "historical_asof",
        historicalAsOf: historicalAsOfValue(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "历史赛前模拟失败");
    renderPrediction(data);
    setActiveView("cabinView");
  } catch (error) {
    clearPredictionForError(toChineseError(error.message));
  } finally {
    historicalPredict.disabled = false;
    historicalPredict.textContent = originalText;
  }
});

batchToday.addEventListener("click", async () => {
  formError.textContent = "";
  const fixtureIds = parseFixtureIds(batchFixtureIds.value);
  const batchLimit = syncBatchLimitValue();
  batchToday.disabled = true;
  batchToday.textContent = "批量中";
  fixtureResults.innerHTML = `<div class="fixture-empty">${
    fixtureIds.length
      ? `批量中：指定 ${fixtureIds.length} 场...`
      : `批量中：今日前 ${batchLimit} 场...`
  }</div>`;
  try {
    const response = await fetch("/api/batch-predict", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        ...buildPayload(),
        scope: "first_division",
        limit: fixtureIds.length || batchLimit,
        fixtureIds,
        collectionMode: "batch",
      }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "批量分析失败");
    renderBatchResult(data);
    setActiveView("batchView");
    loadHealth();
    loadHistory();
    loadRecentBatches();
  } catch (error) {
    formError.textContent = toChineseError(error.message);
  } finally {
    batchToday.disabled = false;
    updateBatchButtonLabel();
  }
});

batchCount.addEventListener("input", updateBatchButtonLabel);
batchCount.addEventListener("change", () => {
  syncBatchLimitValue();
  updateBatchButtonLabel();
});
batchFixtureIds.addEventListener("input", updateBatchButtonLabel);

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
    const ledgerSettled = data.paperLedger?.settledCount ?? 0;
    document.querySelector("#validationAction").textContent =
      `同步完成：新增 ${synced} · 待完赛 ${awaiting} · 结算 ${ledgerSettled}`;
    renderModelValidation(data.modelValidation || {});
    loadHealth();
    if (state.activeView === "reviewView") loadDailyReview();
  } catch (error) {
    document.querySelector("#validationAction").textContent = toChineseError(error.message);
  } finally {
    syncResults.disabled = false;
    syncResults.textContent = originalText;
  }
});

loadReview.addEventListener("click", () => loadDailyReview());

exportReviewExcel.addEventListener("click", () => {
  const date = reviewDate.value || defaultReviewDate();
  window.location.href = `/api/daily-review-report?date=${encodeURIComponent(date)}`;
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
  appShell?.setAttribute("data-active-view", state.activeView);
  if (reviewDate) reviewDate.value = defaultReviewDate();
  updateBatchButtonLabel();
  loadHealth();
  window.setTimeout(() => {
    loadHistory();
    loadRecentBatches();
  }, 0);
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
    document.querySelector("#healthStatus").textContent = `${runs} 条预测 · ${apiText}${retryText}`;
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
    state.loaded.modelValidation = true;
  } catch {
    document.querySelector("#validationStatus").textContent = "验收状态不可用";
    document.querySelector("#validationMetrics").innerHTML = "";
    document.querySelector("#validationNotes").innerHTML = "";
  }
}

async function loadLiveReadiness() {
  try {
    const response = await fetch("/api/live-readiness");
    const data = await response.json();
    renderLiveReadiness(data);
    state.loaded.liveReadiness = true;
  } catch {
    renderLiveReadiness({ statusLabel: "实盘准入不可用", checks: [] });
  }
}

function buildPayload() {
  return {
    mode: "auto",
    home: homeTeam.value.trim(),
    away: awayTeam.value.trim(),
    fixtureId: document.querySelector("#fixtureId").value.trim(),
    collectionMode: document.querySelector("#collectionMode").value || "deep",
    apiKey: document.querySelector("#apiKey").value.trim(),
    bankroll: numberValue("#bankroll", 1000),
    unit: numberValue("#unit", 0),
    marketWeight: numberValue("#marketWeight", 0.45),
    minEdge: numberValue("#minEdge", 0.08),
    minQuality: 0.6,
    forcePicks: false,
  };
}

function historicalAsOfValue() {
  const value = document.querySelector("#historicalAsOf")?.value.trim();
  if (!value) return "";
  const parsed = new Date(value);
  return Number.isNaN(parsed.getTime()) ? value : parsed.toISOString();
}

function renderPrediction(data) {
  const match = data.match;
  const meta = data.meta || {};
  const probabilities = data.probabilities || {};
  const display = probabilities.display || probabilities.final || {};
  const pbase = probabilities.pbase || probabilities.model || {};
  const qmkt = probabilities.qmkt || probabilities.market || {};
  const governance = data.modelGovernance || {};

  document.querySelector("#matchTitle").innerHTML = renderMatchTitle(match);
  document.querySelector("#matchMeta").textContent =
    [
      meta.leagueNameZh || meta.leagueName,
      meta.kickoffBeijing || meta.kickoff,
      meta.venue,
      meta.historicalMode && meta.historicalAsOfBeijing ? `历史模拟截止 ${meta.historicalAsOfBeijing}` : "",
    ]
      .filter(Boolean)
      .join(" · ") || "实时预测";
  document.querySelector("#dataSource").textContent = meta.dataSource || "-";
  document.querySelector("#runId").textContent = data.runId ? `运行 ${data.runId}` : "运行 -";
  state.currentRunId = data.runId || null;
  exportExcel.disabled = !state.currentRunId;
  exportPdf.disabled = !state.currentRunId;
  if (openTrace) openTrace.disabled = !state.currentRunId;

  renderProbabilities(match, display);
  document.querySelector("#homeXg").textContent = formatNumber(data.expectedGoals?.home, 2);
  document.querySelector("#awayXg").textContent = formatNumber(data.expectedGoals?.away, 2);
  renderScores(data.topScores || []);
  renderMarketTable(match, display, pbase, qmkt, governance);
  renderModelAudit(data.modelAudit || {});
  renderDataQuality(data.dataQuality || {});
  renderPortfolio(data.portfolio || {});
  renderRecommendations(data.recommendations || []);
  renderLiveReadiness(data.liveReadiness || {});
  renderDataProcessing(data.dataProcessing || {}, data);
  renderTraceDrawer(data);
  renderHistoryTracePreview(data, "当前单场");
  renderNotes(data.notes || []);
  if (data.modelValidation) {
    renderModelValidation(data.modelValidation);
    state.loaded.modelValidation = true;
  }
  if (data.liveReadiness) {
    state.loaded.liveReadiness = true;
  }
  window.setTimeout(() => {
    loadHealth();
    loadHistory();
    if (state.activeView === "cabinView") loadPaperLedgerBook();
  }, 0);
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
  const summary = message ? `<div class="fixture-empty">${escapeHtml(message)}</div>` : "";
  fixtureResults.innerHTML = summary + fixtures
    .map((item) => {
      const home = item.homeZh || item.home || "-";
      const away = item.awayZh || item.away || "-";
      const meta = [`ID ${item.fixtureId}`, item.dateBeijing || item.date, item.leagueZh || item.league, item.status]
        .filter(Boolean)
        .join(" · ");
      return `
        <div class="fixture-option fixture-card" data-fixture-id="${escapeHtml(item.fixtureId)}" data-home="${escapeHtml(home)}" data-away="${escapeHtml(away)}">
          <strong>${teamPairHtml(home, away, item.homeLogo || item.home_logo, item.awayLogo || item.away_logo)}</strong>
          <span>${escapeHtml(meta)}</span>
          <div class="fixture-actions">
            <button class="mini-action select-single" type="button">单场分析</button>
            <button class="mini-action add-batch" type="button">加入批量</button>
          </div>
        </div>
      `;
    })
    .join("");

  fixtureResults.querySelectorAll(".select-single").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest(".fixture-option");
      document.querySelector("#fixtureId").value = card.dataset.fixtureId || "";
      homeTeam.value = card.dataset.home || homeTeam.value;
      awayTeam.value = card.dataset.away || awayTeam.value;
      const title = `${card.dataset.home || "-"} vs ${card.dataset.away || "-"}`;
      fixtureResults.innerHTML = `
        <div class="fixture-empty">
          已选择 ${escapeHtml(title)} · ID ${escapeHtml(card.dataset.fixtureId || "-")}
        </div>
      `;
      formError.textContent = "";
    });
  });
  fixtureResults.querySelectorAll(".add-batch").forEach((button) => {
    button.addEventListener("click", () => {
      const card = button.closest(".fixture-option");
      addBatchFixtureId(card.dataset.fixtureId);
      button.textContent = "已加入";
      button.disabled = true;
      formError.textContent = `已加入批量：比赛 ID ${card.dataset.fixtureId || "-"}`;
    });
  });
}

function renderBatchResult(data) {
  if (data) state.batchResult = data;
  const current = state.batchResult || {};
  const request = current.apiRequests || {};
  const summary = current.batchSummary || {};
  const plan = summary.portfolioPlan || {};
  const collectedItems = current.collected || [];
  const failedItems = current.failed || [];
  const filteredCollected = sortBatchItems(collectedItems, "priority");
  const filteredFailed = failedItems;
  const visibleCount = filteredCollected.length + filteredFailed.length;
  const rawTotalCount = summary.total ?? (collectedItems.length + failedItems.length);
  const requestedCount = Number(current.requestedCount);
  const totalCount = Number.isFinite(requestedCount) && requestedCount > rawTotalCount ? requestedCount : rawTotalCount;
  const summaryCards = [
    ["批次", current.batchRunId ? `#${current.batchRunId}` : "-"],
    ["显示", `${visibleCount}/${totalCount}`],
    ["成功", summary.success ?? current.collectedCount ?? 0],
    ["信号", summary.signalCount ?? 0],
    ["失败", summary.failed ?? current.failedCount ?? 0],
    ["组合占用", formatMoney(plan.plannedStake)],
    ["组合期望", formatMoney(plan.expectedBankroll)],
  ]
    .map(([label, value]) => `
      <div class="batch-summary-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");
  const rows = filteredCollected
    .map((item) => `
      <div class="batch-pool-row ${plan.selectedRunIds?.includes(item.runId) ? "planned" : ""}" data-run-card="${escapeHtml(item.runId)}">
        <div class="batch-main">
          <strong>${teamPairHtml(item.home || "主队", item.away || "客队", item.homeLogo || item.home_logo, item.awayLogo || item.away_logo)}</strong>
          <span>运行 ${escapeHtml(item.runId)} · ID ${escapeHtml(item.fixtureId || "-")} · ${escapeHtml(item.league || "-")} · ${escapeHtml(item.kickoffBeijing || "-")}</span>
        </div>
        <span class="history-signal ${historyActionClass(item.signalStatus || item.recommendationAction)}">${escapeHtml(actionLabel(item.signalStatus || item.recommendationAction))}</span>
        <div class="run-result-grid">${renderRunResultBlocks(null, item)}</div>
        <p class="batch-reason">${escapeHtml(item.recommendationReason || item.gateLabel || "等待进一步复核。")}</p>
        <div class="batch-actions">
          <button class="mini-action open-run" type="button" data-run-id="${escapeHtml(item.runId)}">查看单场</button>
          <button class="mini-action open-trace" type="button" data-run-id="${escapeHtml(item.runId)}">回溯数据</button>
          <a class="history-link" href="/api/report?format=xlsx&amp;run_id=${encodeURIComponent(item.runId)}">Excel</a>
          <a class="history-link" href="/api/report?format=pdf&amp;run_id=${encodeURIComponent(item.runId)}">PDF</a>
        </div>
      </div>
    `)
    .join("");
  const failed = filteredFailed
    .map((item) => `
      <div class="batch-pool-row failed">
        <div class="batch-main">
          <strong>${teamPairHtml(item.home || "主队", item.away || "客队", item.homeLogo || item.home_logo, item.awayLogo || item.away_logo)}</strong>
          <span>ID ${escapeHtml(item.fixtureId || "-")} · ${escapeHtml(item.league || "-")} · ${escapeHtml(item.kickoffBeijing || "-")}</span>
        </div>
        <span class="history-signal no-market">${escapeHtml(item.failureLabel || "失败")}</span>
        <p class="batch-reason">${escapeHtml(item.error || "失败")}</p>
      </div>
    `)
    .join("");
  const contentHtml = `
    <div class="batch-summary-grid">${summaryCards}</div>
    ${renderBatchPortfolioPlan(plan)}
    ${rows || (filteredFailed.length ? "" : `<div class="fixture-empty">当前批次没有可展示的成功比赛。</div>`)}
    ${failed || ""}
  `;
  const target = batchPoolContent || fixtureResults;
  target.innerHTML = contentHtml;
  if (batchPoolStatus) {
    batchPoolStatus.textContent = `显示 ${visibleCount}/${totalCount} · 成功 ${summary.success ?? 0} · 信号 ${summary.signalCount ?? 0}`;
    batchPoolStatus.classList.toggle("insufficient", !Number(summary.success || 0));
  }
  if (batchPoolContent) {
    fixtureResults.innerHTML = `
      <div class="fixture-empty">
        批量完成：成功 ${escapeHtml(summary.success ?? 0)} · 信号 ${escapeHtml(summary.signalCount ?? 0)} · 失败 ${escapeHtml(summary.failed ?? 0)}
      </div>
    `;
  }
  bindBatchControls(target);
  const showHistory = target.querySelector(".show-batch-history");
  if (showHistory) {
    showHistory.addEventListener("click", () => {
      state.batchResult = null;
      renderRecentBatches();
      loadRecentBatches();
    });
  }
  target.querySelector(".mark-current-official")?.addEventListener("click", (event) => {
    markOfficialBatch(event.currentTarget);
  });
  target.querySelectorAll(".open-run").forEach((button) => {
    button.addEventListener("click", () => loadPredictionRun(button.dataset.runId));
  });
  target.querySelectorAll(".open-trace").forEach((button) => {
    button.addEventListener("click", () => loadPredictionRun(button.dataset.runId, "dataView"));
  });
  hydrateRunCards(filteredCollected);
}

function renderBatchControls(collectedItems = [], failedItems = []) {
  const filters = state.batchFilters;
  const filterOptions = buildBatchFilterOptions(collectedItems, failedItems);
  return `
    <div class="batch-filter-bar batch-filter-bar-advanced">
      <label class="batch-filter-search">
        <span>关键词</span>
        <input id="batchQueryFilter" type="search" value="${escapeHtml(filters.query)}" placeholder="球队、ID、联赛、方向、备注">
      </label>
      <label>
        <span>范围</span>
        <select id="batchActionFilter">
          ${batchOption("all", "全部", filters.action)}
          ${batchOption("signal", "只看信号", filters.action)}
          ${batchOption("planned", "组合预案", filters.action)}
          ${batchOption("watch", "只看观望", filters.action)}
          ${batchOption("no_market", "市场缺失", filters.action)}
          ${batchOption("failed", "失败记录", filters.action)}
        </select>
      </label>
      <label>
        <span>联赛</span>
        <select id="batchLeagueFilter">
          ${batchOption("all", "全部联赛", filters.league)}
          ${filterOptions.leagues.map((value) => batchOption(value, value, filters.league)).join("")}
        </select>
      </label>
      <label>
        <span>庄家</span>
        <select id="batchBookmakerFilter">
          ${batchOption("all", "全部庄家", filters.bookmaker)}
          ${filterOptions.bookmakers.map((value) => batchOption(value, value, filters.bookmaker)).join("")}
        </select>
      </label>
      <label>
        <span>盘口覆盖</span>
        <select id="batchCoverageFilter">
          ${batchOption("all", "全部盘口", filters.coverage)}
          ${batchOption("full", "三项完整", filters.coverage)}
          ${batchOption("partial", "部分可用", filters.coverage)}
          ${batchOption("missing", "盘口缺失", filters.coverage)}
        </select>
      </label>
      <label>
        <span>开赛时段</span>
        <select id="batchTimeFilter">
          ${batchOption("all", "全部时段", filters.timeWindow)}
          ${batchOption("before18", "18:00 前", filters.timeWindow)}
          ${batchOption("evening", "18:00-23:00", filters.timeWindow)}
          ${batchOption("late", "23:00 后/凌晨", filters.timeWindow)}
        </select>
      </label>
      <label>
        <span>质量</span>
        <select id="batchQualityFilter">
          ${batchOption("all", "全部质量", filters.quality)}
          ${batchOption("high", "高质量 ≥75%", filters.quality)}
          ${batchOption("medium", "可复核 ≥60%", filters.quality)}
        </select>
      </label>
      <label>
        <span>排序</span>
        <select id="batchSortBy">
          ${batchOption("priority", "推荐优先", filters.sort)}
          ${batchOption("quality", "质量优先", filters.sort)}
          ${batchOption("ev", "EV 优先", filters.sort)}
          ${batchOption("time", "时间优先", filters.sort)}
        </select>
      </label>
      <div class="batch-filter-actions">
        <button class="mini-action" id="applyBatchFilter" type="button">应用筛选</button>
        <button class="mini-action" id="resetBatchFilter" type="button">重置</button>
      </div>
    </div>
  `;
}

function batchOption(value, label, selected) {
  return `<option value="${escapeHtml(value)}"${value === selected ? " selected" : ""}>${escapeHtml(label)}</option>`;
}

function bindBatchControls(container = document) {
  const queryFilter = container.querySelector("#batchQueryFilter");
  const actionFilter = container.querySelector("#batchActionFilter");
  const leagueFilter = container.querySelector("#batchLeagueFilter");
  const bookmakerFilter = container.querySelector("#batchBookmakerFilter");
  const coverageFilter = container.querySelector("#batchCoverageFilter");
  const timeFilter = container.querySelector("#batchTimeFilter");
  const qualityFilter = container.querySelector("#batchQualityFilter");
  const sortBy = container.querySelector("#batchSortBy");
  if (!actionFilter || !qualityFilter || !sortBy) return;
  const applyFilters = () => {
    state.batchFilters.query = queryFilter?.value || "";
    state.batchFilters.action = actionFilter.value;
    state.batchFilters.league = leagueFilter?.value || "all";
    state.batchFilters.bookmaker = bookmakerFilter?.value || "all";
    state.batchFilters.coverage = coverageFilter?.value || "all";
    state.batchFilters.timeWindow = timeFilter?.value || "all";
    state.batchFilters.quality = qualityFilter.value;
    state.batchFilters.sort = sortBy.value;
    renderBatchResult();
  };
  queryFilter?.addEventListener("keydown", (event) => {
    if (event.key === "Enter") applyFilters();
  });
  actionFilter.addEventListener("change", () => {
    state.batchFilters.action = actionFilter.value;
    renderBatchResult();
  });
  leagueFilter?.addEventListener("change", () => {
    state.batchFilters.league = leagueFilter.value;
    renderBatchResult();
  });
  bookmakerFilter?.addEventListener("change", () => {
    state.batchFilters.bookmaker = bookmakerFilter.value;
    renderBatchResult();
  });
  coverageFilter?.addEventListener("change", () => {
    state.batchFilters.coverage = coverageFilter.value;
    renderBatchResult();
  });
  timeFilter?.addEventListener("change", () => {
    state.batchFilters.timeWindow = timeFilter.value;
    renderBatchResult();
  });
  qualityFilter.addEventListener("change", () => {
    state.batchFilters.quality = qualityFilter.value;
    renderBatchResult();
  });
  sortBy.addEventListener("change", () => {
    state.batchFilters.sort = sortBy.value;
    renderBatchResult();
  });
  container.querySelector("#applyBatchFilter")?.addEventListener("click", applyFilters);
  container.querySelector("#resetBatchFilter")?.addEventListener("click", () => {
    state.batchFilters = {
      action: "all",
      quality: "all",
      query: "",
      league: "all",
      bookmaker: "all",
      coverage: "all",
      timeWindow: "all",
      sort: "priority",
    };
    renderBatchResult();
  });
}

function renderBatchPortfolioPlan(plan) {
  const warnings = plan.warnings || [];
  return `
    <div class="batch-plan">
      <div class="batch-plan-head">
        <strong>${escapeHtml(plan.mode || "研究组合预案")}</strong>
        <span>${escapeHtml(plan.policy || "等待批量结果。")}</span>
      </div>
      <div class="batch-plan-grid">
        <span><b>候选</b>${escapeHtml(plan.selectedCount ?? 0)}/${escapeHtml(plan.candidateCount ?? 0)}</span>
        <span><b>上限</b>${formatMoney(plan.stakeCap)}</span>
        <span><b>计划占用</b>${formatMoney(plan.plannedStake)}</span>
        <span><b>期望资金</b>${formatMoney(plan.expectedBankroll)}</span>
      </div>
      <ul>
        ${warnings.map((warning) => `<li>${escapeHtml(warning)}</li>`).join("") || "<li>暂无集中度预警。</li>"}
      </ul>
    </div>
  `;
}

function filterBatchCollected(items, plan) {
  const filters = state.batchFilters;
  const plannedRunIds = new Set((plan.selectedRunIds || []).map((runId) => Number(runId)));
  let filtered = items.filter((item) => {
    const action = item.signalStatus || item.recommendationAction;
    if (filters.action === "signal" && action !== "PAPER_BUY") return false;
    if (filters.action === "planned" && !plannedRunIds.has(Number(item.runId))) return false;
    if (filters.action === "watch" && !["RESEARCH_WATCH", "MODEL_CANDIDATE", "WATCH", "SUSPENDED"].includes(action)) return false;
    if (filters.action === "no_market" && action !== "NO_MARKET") return false;
    if (filters.action === "failed") return false;
    const quality = Number(item.qualityScore || 0);
    if (filters.quality === "high" && quality < 0.75) return false;
    if (filters.quality === "medium" && quality < 0.6) return false;
    if (!passesBatchCommonFilters(item, false)) return false;
    return true;
  });
  return sortBatchItems(filtered, filters.sort);
}

function shouldShowBatchFailed() {
  return state.batchFilters.action === "all" || state.batchFilters.action === "failed";
}

function filterBatchFailed(items) {
  if (!shouldShowBatchFailed()) return [];
  return items.filter((item) => passesBatchCommonFilters(item, true));
}

function passesBatchCommonFilters(item, failed) {
  const filters = state.batchFilters;
  const query = String(filters.query || "").trim().toLowerCase();
  if (query && !batchSearchText(item).includes(query)) return false;
  if (filters.league !== "all" && String(item.league || "-") !== filters.league) return false;
  if (filters.bookmaker !== "all" && !batchBookmakers(item).includes(filters.bookmaker)) return false;
  if (filters.coverage !== "all" && batchCoverageStatus(item, failed) !== filters.coverage) return false;
  if (filters.timeWindow !== "all" && !matchesBatchTimeWindow(item.kickoffBeijing, filters.timeWindow)) return false;
  return true;
}

function buildBatchFilterOptions(collectedItems, failedItems) {
  const allItems = [...collectedItems, ...failedItems];
  return {
    leagues: uniqueSorted(allItems.map((item) => item.league).filter(Boolean)),
    bookmakers: uniqueSorted(collectedItems.flatMap((item) => batchBookmakers(item)).filter(Boolean)),
  };
}

function normalizeBatchFilters(collectedItems, failedItems) {
  const options = buildBatchFilterOptions(collectedItems, failedItems);
  if (state.batchFilters.league !== "all" && !options.leagues.includes(state.batchFilters.league)) {
    state.batchFilters.league = "all";
  }
  if (state.batchFilters.bookmaker !== "all" && !options.bookmakers.includes(state.batchFilters.bookmaker)) {
    state.batchFilters.bookmaker = "all";
  }
}

function batchSearchText(item) {
  const values = [
    item.fixtureId,
    item.runId,
    item.home,
    item.away,
    item.league,
    leagueSearchAliases(item.league),
    item.kickoffBeijing,
    item.recommendationSummary,
    item.recommendationMarket,
    item.recommendationSelection,
    item.recommendationReason,
    item.predictionLabel,
    item.qualityLabel,
    item.failureLabel,
    item.error,
    ...batchBookmakers(item),
  ];
  return values.map((value) => String(value ?? "").toLowerCase()).join(" ");
}

function leagueSearchAliases(league) {
  const text = String(league || "");
  const aliases = [
    ["英格兰足球超级联赛", "英超"],
    ["英格兰足球冠军联赛", "英冠"],
    ["西班牙足球甲级联赛", "西甲"],
    ["意大利足球甲级联赛", "意甲"],
    ["德国足球甲级联赛", "德甲"],
    ["法国足球甲级联赛", "法甲"],
    ["法国足球乙级联赛", "法乙"],
    ["荷兰足球甲级联赛", "荷甲"],
    ["葡萄牙足球超级联赛", "葡超"],
    ["美国职业足球大联盟", "美职联"],
    ["日本职业足球甲级联赛", "日职联"],
    ["韩国职业足球甲级联赛", "韩K联"],
    ["中国足球协会超级联赛", "中超"],
    ["阿根廷足球甲级联赛", "阿甲"],
    ["巴西足球甲级联赛", "巴甲"],
  ];
  return aliases
    .filter(([official]) => text.includes(official))
    .map(([, alias]) => alias)
    .join(" ");
}

function batchBookmakers(item) {
  const selected = item.selectedBookmakers || {};
  const values = Object.values(selected).filter(Boolean);
  if (item.bookmaker) values.push(item.bookmaker);
  return uniqueSorted(values.filter((value) => value && value !== "-"));
}

function batchCoverageStatus(item, failed = false) {
  if (failed) return "missing";
  const total = Number(item.totalMarkets || 0);
  const available = Number(item.availableMarkets || 0);
  if (total > 0 && available >= total) return "full";
  if (available > 0) return "partial";
  return "missing";
}

function matchesBatchTimeWindow(value, windowName) {
  const hour = beijingHour(value);
  if (hour == null) return false;
  if (windowName === "before18") return hour >= 6 && hour < 18;
  if (windowName === "evening") return hour >= 18 && hour < 23;
  if (windowName === "late") return hour >= 23 || hour < 6;
  return true;
}

function beijingHour(value) {
  const text = String(value || "");
  const match = text.match(/(?:^|\s)(\d{1,2}):\d{2}/);
  if (!match) return null;
  const hour = Number(match[1]);
  return Number.isFinite(hour) && hour >= 0 && hour <= 23 ? hour : null;
}

function formatBookmakerSummary(item) {
  const selected = item.selectedBookmakers || {};
  const labels = { "1X2": "胜平负", OU: "大小球", AH: "让球" };
  const parts = Object.entries(selected)
    .filter(([, value]) => value)
    .map(([key, value]) => `${labels[key] || key}=${value}`);
  if (parts.length) return parts.join(" · ");
  return item.bookmaker || "未取得";
}

function uniqueSorted(values) {
  return [...new Set(values.map((value) => String(value || "").trim()).filter(Boolean))]
    .sort((a, b) => a.localeCompare(b, "zh-Hans-CN"));
}

function sortBatchItems(items, sortBy) {
  const copy = [...items];
  if (sortBy === "quality") {
    return copy.sort((a, b) => Number(b.qualityScore || 0) - Number(a.qualityScore || 0));
  }
  if (sortBy === "ev") {
    return copy.sort((a, b) => batchEvValue(b) - batchEvValue(a));
  }
  if (sortBy === "time") {
    return copy.sort((a, b) => String(a.kickoffBeijing || "").localeCompare(String(b.kickoffBeijing || "")));
  }
  return copy.sort((a, b) => batchPriorityScore(b) - batchPriorityScore(a));
}

function batchPriorityScore(item) {
  const actionScore = {
    PAPER_BUY: 35,
    MODEL_CANDIDATE: 30,
    SUSPENDED: 24,
    RESEARCH_WATCH: 20,
    BUY: 30,
    WATCH: 20,
    NO_MARKET: 10,
  }[item.signalStatus || item.recommendationAction] || 0;
  return actionScore + Number(item.qualityScore || 0) * 10 + Math.max(-1, batchEvValue(item));
}

function batchEvValue(item) {
  if (item.conservativeExpectedValue != null) return Number(item.conservativeExpectedValue);
  if (item.expectedValue != null) return Number(item.expectedValue);
  return -99;
}

async function loadPredictionRun(runId, targetView = "workbenchView") {
  if (!runId) return;
  formError.textContent = "";
  try {
    const response = await fetch(`/api/prediction?run_id=${encodeURIComponent(runId)}`);
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取单场记录失败");
    state.historyDetailsCache.set(String(runId), data);
    renderPrediction(data);
    setActiveView(targetView);
    const scrollTarget = targetView === "workbenchView" ? ".match-context" : `#${targetView}`;
    document.querySelector(scrollTarget)?.scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (error) {
    formError.textContent = toChineseError(error.message);
  }
}

function clearPredictionForError(message) {
  formError.textContent = message;
  state.currentRunId = null;
  exportExcel.disabled = true;
  exportPdf.disabled = true;
  if (openTrace) openTrace.disabled = true;
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
  if (traceDrawerContent) {
    traceDrawerContent.innerHTML = `<div class="panel-placeholder">暂无回溯</div>`;
  }
  if (historyTracePreview) {
    historyTracePreview.innerHTML = `<div class="panel-placeholder">暂无回溯</div>`;
  }
  renderNotes([message]);
}

function renderProbabilities(match, final) {
  const rows = [
    [teamLabelHtml(match, "home"), final.home_win],
    ["平局", final.draw],
    [teamLabelHtml(match, "away"), final.away_win],
  ];
  document.querySelector("#probabilityGrid").innerHTML = rows
    .map(([label, value]) => {
      const pct = clamp((value || 0) * 100, 0, 100);
      return `
        <article class="prob-card">
          <strong>${label}</strong>
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
    [teamLabelHtml(match, "home"), display.home_win, pbase.home_win, qmkt?.home_win],
    ["平局", display.draw, pbase.draw, qmkt?.draw],
    [teamLabelHtml(match, "away"), display.away_win, pbase.away_win, qmkt?.away_win],
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
            <div>${label}</div>
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
  document.querySelector("#portfolioSummary").textContent = "";
}

function renderRecommendations(items) {
  document.querySelector("#recommendations").innerHTML = items
    .map((item) => {
      const signalStatus = item.signal_status || legacySignalStatus(item);
      const suspended =
        signalStatus === "SUSPENDED" ||
        ["SUSPENDED_MODEL_DIVERGENCE", "MODEL_MARKET_CONFLICT", "SUSPENDED"].includes(item.ev_status);
      const researchEv = suspended ? null : item.ev_pbase_research ?? item.audit_expected_value_per_unit ?? item.expected_value_per_unit;
      const paperEv = suspended
        ? null
        : item.paper_expected_value_per_unit ??
          item.ev_pshr_candidate ??
          item.conservative_ev_pbase_research ??
          item.audit_paper_expected_value_per_unit ??
          item.audit_conservative_expected_value_per_unit ??
          item.conservative_expected_value_per_unit;
      const scoreResearchOnly = item.ev_calculation?.evDecisionLayer === "research_audit_only";
      const displayEv = scoreResearchOnly ? researchEv : paperEv ?? researchEv;
      const probabilityLabel = item.model_probability_label || (item.market === "胜平负" ? "模型胜率" : "正收益概率");
      const marketProbabilityLabel = item.market === "胜平负" ? "市场胜率" : "市场概率";
      const probabilityGap = item.edge == null ? null : Number(item.edge);
      const gapClass = probabilityGap == null ? "" : Math.abs(probabilityGap) > 0.15 ? "negative" : Math.abs(probabilityGap) >= 0.12 ? "warning-text" : "";
      return `
        <div class="rec-item">
          <div class="rec-head">
            <strong>${escapeHtml(item.market)}</strong>
            <span>${escapeHtml(item.selection)}</span>
          </div>
          <div class="rec-metrics">
            <span>赔率 <strong>${item.odds == null ? "-" : formatNumber(item.odds, 2)}</strong></span>
            <span>${escapeHtml(probabilityLabel)} <strong>${formatPercent(item.model_probability)}</strong></span>
            <span>${escapeHtml(marketProbabilityLabel)} <strong>${item.market_probability == null ? "-" : formatPercent(item.market_probability)}</strong></span>
            <span>模型-市场差 <strong class="${gapClass}">${probabilityGap == null ? "-" : formatPercent(probabilityGap)}</strong></span>
            <span>EV <strong>${suspended ? "已暂停" : displayEv == null ? "-" : formatPercent(displayEv)}</strong></span>
          </div>
          ${renderEvCalculation(item.ev_calculation, suspended, signalStatus)}
          <p class="rec-reason">${escapeHtml(item.reason || "")}</p>
        </div>
      `;
    })
    .join("");
}

function formatEvLayer(layer, fallbackValue, fallbackLabel = "-") {
  if (layer) {
    if (layer.value != null) return formatPercent(layer.value);
    return escapeHtml(layer.statusLabel || fallbackLabel);
  }
  return fallbackValue == null ? escapeHtml(fallbackLabel) : formatPercent(fallbackValue);
}

function renderEvCalculation(calc, suspended, signalStatus) {
  const gates = (calc?.gates || [])
    .map((gate) => `
      <span class="gate-pill ${gate.passed ? "pass" : "fail"}">
        ${escapeHtml(gate.label)} ${gate.passed ? "通过" : "未过"}
      </span>
    `)
    .join("");
  if (suspended) {
    return `
      <div class="ev-path ev-suspended">
        <strong>EV 路径已暂停</strong>
        <span>${signalStatus === "SUSPENDED" ? "闸门未过" : "模型与市场冲突"}</span>
        ${gates ? `<div class="gate-list">${gates}</div>` : ""}
      </div>
    `;
  }
  if (!calc || !gates) return "";
  return `
    <div class="ev-path ev-gates-only">
      <div class="gate-list">${gates}</div>
    </div>
  `;
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
    ["优先庄家", factors.bookmaker_quality],
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
  appShell?.setAttribute("data-active-view", viewId);
  document.querySelectorAll(".view-tab").forEach((button) => {
    button.classList.toggle("active", button.dataset.view === viewId);
  });
  document.querySelectorAll(".content-view").forEach((view) => {
    view.classList.toggle("active", view.id === viewId);
  });
  if (viewId === "cabinView") {
    loadPaperLedgerBook();
  }
  if (viewId === "auditView") {
    if (!state.loaded.modelValidation) loadModelValidation();
    if (!state.loaded.liveReadiness) loadLiveReadiness();
  }
  if (viewId === "reviewView" && !state.loaded.dailyReview) {
    loadDailyReview();
  }
  if (viewId === "batchView" && !state.recentBatches.length) {
    loadRecentBatches();
  }
}

function renderDataProcessing(processing, data = {}) {
  const home = processing.home || {};
  const away = processing.away || {};
  const populated = Boolean(home.matches?.length || away.matches?.length);
  const coverage = document.querySelector("#dataCoverage");
  if (!populated) {
    coverage.textContent = "等待分析";
    coverage.classList.remove("insufficient");
    document.querySelector("#processingSteps").innerHTML = `<div class="panel-placeholder">等待数据</div>`;
    document.querySelector("#processingMetrics").innerHTML = `<div class="panel-placeholder">等待数据</div>`;
    const expAudit = document.querySelector("#expEdgeAudit");
    if (expAudit) expAudit.innerHTML = "";
    renderLineChart("#homeFormChart", [], []);
    renderLineChart("#awayFormChart", [], []);
    renderLineChart("#portfolioTrendChart", [], []);
    document.querySelector("#homeRecentTable").innerHTML = `<div class="panel-placeholder">等待数据</div>`;
    document.querySelector("#awayRecentTable").innerHTML = `<div class="panel-placeholder">等待数据</div>`;
    document.querySelector("#oddsTrendNotice").textContent = "生成后检查快照。";
    return;
  }

  coverage.textContent = processing.coverageReady
    ? `样本通过 · ${processing.collectionModeZh || "深度模式"} · 技术统计 ${processing.deepStatsMatches ?? 0} 场`
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
  const expAudit = document.querySelector("#expEdgeAudit");
  if (expAudit) expAudit.innerHTML = renderExpEdgeAudit(data);

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
  document.querySelector("#homeRecentTitle").textContent = `${home.displayName || "主队"} · 近 ${home.validCount || 0} 场`;
  document.querySelector("#awayRecentTitle").textContent = `${away.displayName || "客队"} · 近 ${away.validCount || 0} 场`;
  renderRecentTable("#homeRecentTable", home.matches || []);
  renderRecentTable("#awayRecentTable", away.matches || []);
  document.querySelector("#oddsTrendNotice").textContent =
    processing.oddsTrend?.message || "缺少连续赔率快照。";
}

function renderProcessingMetrics(home, away) {
  const rows = [
    ["有效样本", `${home.validCount ?? 0} 场`, `${away.validCount ?? 0} 场`],
    ["技术统计覆盖", `${home.technicalCount ?? 0} 场`, `${away.technicalCount ?? 0} 场`],
    ["场均积分", formatNumber(home.pointsPerGame, 2), formatNumber(away.pointsPerGame, 2)],
    ["场均进球", formatNumber(home.goalsForAverage, 2), formatNumber(away.goalsForAverage, 2)],
    ["场均失球", formatNumber(home.goalsAgainstAverage, 2), formatNumber(away.goalsAgainstAverage, 2)],
    ["场均 xG", formatNumber(home.xgAverage, 2), formatNumber(away.xgAverage, 2)],
    ["场均射门", formatNumber(home.shotsAverage, 1), formatNumber(away.shotsAverage, 1)],
    ["场均射正", formatNumber(home.shotsOnTargetAverage, 1), formatNumber(away.shotsOnTargetAverage, 1)],
    ["平均控球", formatNumber(home.possessionAverage, 1), formatNumber(away.possessionAverage, 1)],
    ["红牌 / 点球", `${home.redCards ?? 0} / ${home.penalties ?? 0}`, `${away.redCards ?? 0} / ${away.penalties ?? 0}`],
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

function renderExpEdgeAudit(data) {
  const expected = data.expectedGoals || {};
  const edges = data.featureEdges || {};
  if (expected.logEdge == null && !Object.keys(edges).length) return "";
  const match = data.match || {};
  const homeName = teamLabel(match, "home");
  const awayName = teamLabel(match, "away");
  const componentKeys = [
    "elo_edge",
    "fifa_rank_edge",
    "host_edge",
    "rest_edge",
    "travel_edge",
    "group_context_edge",
    "rotation_edge",
    "h2h_edge",
    "country_relation_edge",
    "commercial_incentive_edge",
  ];
  const labels = {
    elo_edge: "Elo 强度差",
    fifa_rank_edge: "FIFA 排名差",
    host_edge: "主场/中立场",
    rest_edge: "休息天数",
    travel_edge: "旅行距离",
    group_context_edge: "积分/战意",
    rotation_edge: "轮换风险",
    h2h_edge: "历史交锋",
    country_relation_edge: "国家关系",
    commercial_incentive_edge: "商业动机",
  };
  const rows = componentKeys.map((key) => {
    const value = Number(edges[key] || 0);
    return {
      key,
      label: labels[key] || key,
      value,
      side: value > 0 ? homeName : value < 0 ? awayName : "中性",
    };
  });
  const fallbackLogEdge = rows.reduce((sum, row) => sum + row.value, 0);
  const logEdge = Number.isFinite(Number(expected.logEdge)) ? Number(expected.logEdge) : fallbackLogEdge;
  const homeMultiplier = Number.isFinite(Number(expected.homeExpMultiplier)) ? Number(expected.homeExpMultiplier) : Math.exp(logEdge);
  const awayMultiplier = Number.isFinite(Number(expected.awayExpMultiplier)) ? Number(expected.awayExpMultiplier) : Math.exp(-logEdge);
  const drawBoost = Number(edges.rivalry_draw_boost || 0);
  return `
    <div class="exp-audit-card">
      <div class="exp-audit-head">
        <div>
          <p class="eyebrow">模型公式</p>
          <h3>综合优势 exp 计算</h3>
        </div>
        <span>${escapeHtml(logEdge >= 0 ? `${homeName} 优势` : `${awayName} 优势`)}</span>
      </div>
      <div class="exp-formula-flow">
        <span>基础 λ ${escapeHtml(homeName)} ${formatNumber(expected.baseHome, 2)} / ${escapeHtml(awayName)} ${formatNumber(expected.baseAway, 2)}</span>
        <b>×</b>
        <span>log_edge ${formatSignedNumber(logEdge, 3)}</span>
        <b>=</b>
        <span>exp 倍率 ${formatNumber(homeMultiplier, 3)} / ${formatNumber(awayMultiplier, 3)}</span>
        <b>→</b>
        <span>修正 λ ${formatNumber(expected.rawHome, 2)} / ${formatNumber(expected.rawAway, 2)}</span>
        <b>→</b>
        <span>最终 λ ${formatNumber(expected.home, 2)} / ${formatNumber(expected.away, 2)}</span>
      </div>
      <div class="exp-component-grid">
        ${rows
          .map((row) => `
            <div class="exp-component ${row.value > 0 ? "positive" : row.value < 0 ? "negative" : ""}">
              <span>${escapeHtml(row.label)}</span>
              <strong>${formatSignedNumber(row.value, 3)}</strong>
              <small>${escapeHtml(row.side)}</small>
            </div>
          `)
          .join("")}
      </div>
      <div class="exp-audit-note">
        <strong>计算口径</strong>
        <span>主队 λ = 基础 λ × exp(log_edge)，客队 λ = 基础 λ × exp(-log_edge)。宿敌/历史关系中的平局增强单独进入平局概率，本场 draw_boost ${formatSignedNumber(drawBoost, 3)}。风险收缩 factor ${formatNumber(expected.lambdaShrinkFactor, 2)}。</span>
      </div>
    </div>
  `;
}

function renderRecentTable(selector, matches) {
  const container = document.querySelector(selector);
  if (!matches.length) {
    container.innerHTML = `<div class="panel-placeholder">没有有效的近期 90 分钟赛果</div>`;
    return;
  }
  container.innerHTML = `
    <div class="recent-row header"><span>日期</span><span>对手 / 赛事</span><span>场地</span><span>比分</span><span>技术</span><span>赛果</span></div>
    ${matches
      .map((item) => {
        const resultClass = item.resultLabel === "胜" ? "win" : item.resultLabel === "平" ? "draw" : "loss";
        const raw = item.opponent && item.opponent !== item.opponentZh
          ? `<small class="raw-name">API 原名：${escapeHtml(item.opponent)}</small>`
          : "";
        const technical = item.technicalAvailable
          ? `xG ${formatNumber(item.xg, 2)} · 射 ${formatNumber(item.shots, 0)}/${formatNumber(item.shotsOnTarget, 0)}`
          : "-";
        return `
          <div class="recent-row">
            <span>${escapeHtml(shortDate(item.dateBeijing))}</span>
            <span>${escapeHtml(item.opponentZh || "-")}<small class="raw-name">${escapeHtml(item.leagueZh || "-")}</small>${raw}</span>
            <span>${escapeHtml(item.venueLabel || "-")}</span>
            <strong>${escapeHtml(`${item.goalsFor}-${item.goalsAgainst}`)}</strong>
            <span>${escapeHtml(technical)}</span>
            <span class="result-pill ${resultClass}">${escapeHtml(item.resultLabel || "-")}</span>
          </div>
        `;
      })
      .join("")}
  `;
}

function renderLineChart(selector, labels, series, options = {}) {
  const container = document.querySelector(selector);
  if (!container) return;
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
  if (!values.length) {
    container.innerHTML = `<div class="panel-placeholder">尚无真实趋势数据</div>`;
    return;
  }
  const rawMin = Math.min(...values);
  const rawMax = Math.max(...values);
  const range = Math.max(1, rawMax - rawMin);
  const minValue = options.baselineZero === false ? Math.floor(rawMin - range * 0.15) : 0;
  const maxValue = options.baselineZero === false ? Math.ceil(rawMax + range * 0.15) : Math.max(1, rawMax);
  const roundedMax = Math.max(minValue + 1, options.baselineZero === false ? maxValue : Math.max(3, Math.ceil(maxValue)));
  const x = (index) => left + ((width - left - right) * index) / Math.max(1, labels.length - 1);
  const y = (value) => top + (height - top - bottom) * (1 - (Number(value) - minValue) / (roundedMax - minValue));
  const grid = Array.from({ length: 4 }, (_, index) => {
    const value = minValue + ((roundedMax - minValue) * index) / 3;
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

async function loadDailyReview() {
  const date = reviewDate?.value || defaultReviewDate();
  if (reviewDate && !reviewDate.value) reviewDate.value = date;
  const status = document.querySelector("#reviewStatus");
  if (status) status.textContent = "读取中";
  try {
    const response = await fetch(`/api/daily-review?date=${encodeURIComponent(date)}`);
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取复盘失败");
    state.dailyReview = data;
    state.loaded.dailyReview = true;
    renderDailyReview(data);
  } catch (error) {
    if (status) status.textContent = toChineseError(error.message);
    document.querySelector("#reviewSummary").innerHTML = `<div class="panel-placeholder">复盘读取失败</div>`;
  }
}

function renderDailyReview(review) {
  const summary = review.summary || {};
  const batch = review.batch || {};
  const bankrollSummary = review.bankrollTimeline?.summary || {};
  document.querySelector("#reviewStatus").textContent =
    `${review.date || "-"} · ${batch?.isOfficial ? `官方批次 #${batch.batchRunId}` : "按日期最新预测"} · ${summary.formalSignalState || "正式EV关闭"}`;
  const cards = [
    ["比赛", `${summary.settledMatches ?? 0}/${summary.totalMatches ?? 0} 已结算`],
    ["方向命中", `${summary.hitCount ?? 0} · ${formatPercent(summary.hitRate)}`],
    ["Brier", formatNumber(summary.avgBrier, 3)],
    ["LogLoss", formatNumber(summary.avgLogLoss, 3)],
    ["EV候选", `${summary.settledEvCandidateCount ?? 0}/${summary.evCandidateCount ?? 0}`],
    ["高EV亏损", summary.highEvLossCount ?? 0],
    ["高EV异常", summary.highEvAnomalyCount ?? 0],
    ["正式占用", formatMoney(summary.formalStake)],
    ["EV等额盈亏", formatNumber(summary.settledEvNetPerUnit, 2)],
    ["模拟权益", formatMoney(bankrollSummary.equity ?? summary.paperEquity)],
    ["当前回撤", formatPercent(bankrollSummary.drawdownPct ?? summary.paperDrawdownPct)],
    ["盘口专项", `${review.marketLineBacktest?.summary?.settledCandidates ?? 0} 条`],
    ["比分分布", `${review.scoreDistributionBacktest?.summary?.settledMatches ?? 0} 场`],
  ];
  document.querySelector("#reviewSummary").innerHTML = cards
    .map(([label, value]) => `
      <div class="review-card">
        <span>${escapeHtml(label)}</span>
        <strong>${escapeHtml(value)}</strong>
      </div>
    `)
    .join("");
  renderReviewBankroll(review.bankrollTimeline || {});
  renderReviewAnomalies(review.highEvAnomalies || [], review.evAnomalyGroups || []);
  renderMarketLineBacktest(review.marketLineBacktest || {});
  renderScoreDistributionBacktest(review.scoreDistributionBacktest || {});
  renderReviewSettled(review.settled || []);
  renderReviewEv(review.evCandidates || []);
  renderReviewPending(review.pending || []);
}

function renderMarketLineBacktest(backtest) {
  const summary = backtest.summary || {};
  const lineGroups = backtest.lineGroups || [];
  const marketGroups = backtest.marketGroups || [];
  document.querySelector("#marketLineStatus").textContent =
    `${summary.settledCandidates ?? 0} 条已结算候选 · ${escapeHtml(summary.approvalLabel || "仅供研究")}`;
  const container = document.querySelector("#marketLineBacktest");
  if (!lineGroups.length && !marketGroups.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无盘口样本</div>`;
    return;
  }
  const marketChips = marketGroups.slice(0, 3)
    .map((group) => `
      <div class="anomaly-chip market-line-chip">
        <strong>${escapeHtml(group.market || "-")}</strong>
        <span>${escapeHtml(group.count ?? 0)} 条 · 净 ${formatNumber(group.netPerUnit, 2)} · ${escapeHtml(group.statusLabel || "-")}</span>
      </div>
    `)
    .join("");
  const rows = lineGroups.slice(0, 10)
    .map((group) => `
      <div class="review-row market-line">
        <span><strong>${escapeHtml(group.market || "-")} · ${escapeHtml(group.lineKey || "-")}</strong><small>${escapeHtml(group.statusLabel || "-")} · ${escapeHtml(group.diagnosis || "-")}</small></span>
        <span>${escapeHtml(group.count ?? 0)}<small>赢 ${escapeHtml(group.positiveCount ?? 0)} · 走 ${escapeHtml(group.pushCount ?? 0)} · 输 ${escapeHtml(group.lossCount ?? 0)}</small></span>
        <span class="${Number(group.netPerUnit || 0) >= 0 ? "positive" : "negative"}">${formatNumber(group.netPerUnit, 2)}<small>均值 ${formatNumber(group.roiPerUnit, 2)}</small></span>
        <span>${formatPercent(group.avgEv)}<small>分歧 ${formatPercent(group.avgDivergence)} · 高EV亏 ${escapeHtml(group.highEvLossCount ?? 0)}</small></span>
      </div>
    `)
    .join("");
  container.innerHTML = `
    <div class="anomaly-groups">${marketChips}</div>
    <div class="review-row market-line header"><span>盘口线</span><span>样本</span><span>等额结果</span><span>研究EV</span></div>
    ${rows}
  `;
}

function renderScoreDistributionBacktest(backtest) {
  const summary = backtest.summary || {};
  const scoreRows = backtest.scoreRows || [];
  const marketRows = backtest.marketRows || [];
  const status = document.querySelector("#scoreDistributionStatus");
  if (status) {
    status.textContent = `${summary.settledMatches ?? 0} 场 · ${escapeHtml(summary.approvalLabel || "仅供研究")}`;
  }
  const container = document.querySelector("#scoreDistributionBacktest");
  if (!container) return;
  if (!scoreRows.length && !marketRows.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无比分审计</div>`;
    return;
  }
  const summaryChips = [
    ["Top6 命中", formatPercent(summary.top6HitRate)],
    ["平均总进球偏差", formatSignedNumber(summary.avgTotalGoalError, 2)],
    ["平均绝对偏差", formatNumber(summary.avgAbsTotalGoalError, 2)],
    ["尾部概率", formatPercent(summary.avgTailMass)],
  ].map(([label, value]) => `
    <div class="anomaly-chip score-chip-audit">
      <strong>${escapeHtml(label)}</strong>
      <span>${escapeHtml(value)}</span>
    </div>
  `).join("");
  const scoreList = scoreRows.slice(0, 6).map((row) => `
    <div class="review-row score-dist">
      <span><strong>${escapeHtml(row.match || "-")}</strong><small>${escapeHtml(row.league || "-")} · ${escapeHtml(row.score90 || "-")} · ${escapeHtml(row.statusLabel || "-")}</small></span>
      <span>${formatNumber(row.expectedTotalGoals, 2)}<small>实际 ${escapeHtml(row.actualTotalGoals ?? "-")}</small></span>
      <span class="${Number(row.totalGoalError || 0) >= 0 ? "positive" : "negative"}">${formatSignedNumber(row.totalGoalError, 2)}<small>绝对 ${formatNumber(row.absTotalGoalError, 2)}</small></span>
      <span>${formatPercent(row.actualScoreProbability)}<small>排名 ${escapeHtml(row.actualScoreRank ?? "-")} · 尾部 ${formatPercent(row.tailMass)}</small></span>
    </div>
  `).join("");
  const marketList = marketRows.slice(0, 8).map((row) => `
    <div class="review-row score-market">
      <span><strong>${escapeHtml(row.market || "-")} · ${escapeHtml(row.selectionDisplay || row.selection || "-")}</strong><small>${escapeHtml(row.match || "-")} · ${escapeHtml(row.statusLabel || "-")}</small></span>
      <span>${formatPercent(row.winFraction)}<small>输权重 ${formatPercent(row.lossFraction)}</small></span>
      <span>${formatPercent(row.matrixPositiveProbability)}<small>盈亏平衡 ${row.breakEvenOdds == null ? "-" : formatNumber(row.breakEvenOdds, 2)}</small></span>
      <span class="${Number(row.actualNetPerUnit || 0) >= 0 ? "positive" : "negative"}">${formatNumber(row.actualNetPerUnit, 2)}<small>矩阵EV ${formatPercent(row.expectedValueFromMatrix)}</small></span>
    </div>
  `).join("");
  container.innerHTML = `
    <div class="anomaly-groups">${summaryChips}</div>
    <div class="review-row score-dist header"><span>比分偏差</span><span>预期总进球</span><span>偏差</span><span>实际比分概率</span></div>
    ${scoreList || `<div class="panel-placeholder">暂无比分样本</div>`}
    <div class="review-row score-market header"><span>盘口归因</span><span>赢亏权重</span><span>正收益概率</span><span>实际盈亏</span></div>
    ${marketList || `<div class="panel-placeholder">暂无盘口样本</div>`}
  `;
}

function renderReviewBankroll(timeline) {
  const summary = timeline.summary || {};
  const events = timeline.events || [];
  document.querySelector("#reviewBankrollStatus").textContent =
    `现金 ${formatMoney(summary.cash)} · 预留 ${formatMoney(summary.reservedStake)} · ${escapeHtml(summary.riskLabel || "正常")}`;
  const container = document.querySelector("#reviewBankroll");
  if (!events.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无资金事件</div>`;
    return;
  }
  const recent = [...events].slice(-10).reverse();
  container.innerHTML = `
    <div class="review-row bankroll header"><span>事件</span><span>资金状态</span><span>回撤</span><span>风险</span></div>
    ${recent
      .map((event) => `
        <div class="review-row bankroll">
          <span><strong>${escapeHtml(event.eventLabel || "-")} · ${escapeHtml(event.market || "-")}</strong><small>${escapeHtml(event.match || "-")} · ${escapeHtml(event.selection || "-")}</small></span>
          <span>${formatMoney(event.equity)}<small>现金 ${formatMoney(event.cash)} · 预留 ${formatMoney(event.reservedStake)}</small></span>
          <span>${formatPercent(event.drawdownPct)}<small>已实现 ${formatMoney(event.realizedPnl)}</small></span>
          <span>${escapeHtml(event.riskLabel || "-")}<small>连亏 ${escapeHtml(event.lossStreak ?? 0)} · ${escapeHtml(event.eventTs || "-")}</small></span>
        </div>
      `)
      .join("")}
  `;
}

function renderReviewAnomalies(rows, groups) {
  const container = document.querySelector("#reviewAnomalies");
  if (!rows.length && !groups.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无高 EV 异常</div>`;
    return;
  }
  const groupRows = (groups || []).slice(0, 5)
    .map((group) => `
      <div class="anomaly-chip">
        <strong>${escapeHtml(group.market || "-")} · ${escapeHtml(group.oddsBucket || "-")}</strong>
        <span>${escapeHtml(group.count ?? 0)} 条 · 亏损 ${escapeHtml(group.lossCount ?? 0)} · 净 ${formatNumber(group.netPerUnit, 2)}</span>
      </div>
    `)
    .join("");
  const anomalyRows = (rows || []).slice(0, 8)
    .map((row) => `
      <div class="review-row anomaly">
        <span><strong>${escapeHtml(row.anomalyType || "-")}</strong><small>${escapeHtml(row.market || "-")} · ${escapeHtml(row.selectionDisplay || row.selection || "-")}</small></span>
        <span>${formatPercent(row.expectedValue)}<small>赔率 ${row.odds == null ? "-" : formatNumber(row.odds, 2)} · ${escapeHtml(row.oddsBucket || "-")}</small></span>
        <span class="${Number(row.actualNetPerUnit || 0) >= 0 ? "positive" : "negative"}">${formatNumber(row.actualNetPerUnit, 2)}<small>分歧 ${formatPercent(row.divergenceScore)}</small></span>
        <span>${escapeHtml(row.match || "-")}<small>${escapeHtml(row.league || "-")}</small></span>
      </div>
    `)
    .join("");
  container.innerHTML = `
    <div class="anomaly-groups">${groupRows}</div>
    <div class="review-row anomaly header"><span>异常</span><span>研究EV</span><span>真实结果</span><span>比赛</span></div>
    ${anomalyRows}
  `;
}

function renderReviewSettled(rows) {
  const container = document.querySelector("#reviewSettled");
  if (!rows.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无已结算比赛</div>`;
    return;
  }
  container.innerHTML = `
    <div class="review-row header"><span>比赛</span><span>比分</span><span>预测</span><span>命中</span><span>质量</span><span>闸门</span></div>
    ${rows
      .map((row) => `
        <div class="review-row">
          <span><strong>${escapeHtml(row.match)}</strong><small>${escapeHtml(row.league || "-")} · ID ${escapeHtml(row.fixtureId)}</small></span>
          <span>${escapeHtml(row.score90 || "-")}<small>${escapeHtml(row.actualLabel || "-")}</small></span>
          <span>${escapeHtml(row.topPredictionLabel || "-")}<small>${formatPercent(row.topProbability)}</small></span>
          <span class="result-pill ${row.hit ? "win" : "loss"}">${escapeHtml(row.hitLabel || "-")}</span>
          <span>${formatPercent(row.dataQuality)}<small>${escapeHtml(row.qualityLabel || "-")}</small></span>
          <span>${escapeHtml(row.riskGate || "-")}<small>${escapeHtml(row.simAction || "-")}</small></span>
        </div>
      `)
      .join("")}
  `;
}

function renderReviewEv(rows) {
  const container = document.querySelector("#reviewEv");
  const settled = rows
    .filter((row) => row.actualNetPerUnit != null)
    .sort((a, b) => Number(b.expectedValue || 0) - Number(a.expectedValue || 0))
    .slice(0, 12);
  if (!settled.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无 EV 结算</div>`;
    return;
  }
  container.innerHTML = `
    <div class="review-row ev header"><span>方向</span><span>EV身份</span><span>真实盈亏</span><span>风险</span></div>
    ${settled
      .map((row) => `
        <div class="review-row ev">
          <span><strong>${escapeHtml(row.market || "-")} · ${escapeHtml(row.selectionDisplay || row.selection || "-")}</strong><small>${escapeHtml(row.match || "-")} · ${escapeHtml(row.score90 || "-")}</small></span>
          <span>研究 ${formatPercent(row.evPbaseResearch ?? row.expectedValue)}<small>正式 ${row.evPfinalExec == null ? "未开放" : formatPercent(row.evPfinalExec)} · 赔率 ${row.odds == null ? "-" : formatNumber(row.odds, 2)}</small></span>
          <span class="${Number(row.actualNetPerUnit || 0) >= 0 ? "positive" : "negative"}">${formatNumber(row.actualNetPerUnit, 2)}</span>
          <span>${escapeHtml(row.riskFlag || "常规复核")}<small>${escapeHtml(actionLabel(row.signalStatus || row.action || row.status || "-"))}</small></span>
        </div>
      `)
      .join("")}
  `;
}

function renderReviewPending(rows) {
  const container = document.querySelector("#reviewPending");
  if (!rows.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无待结算</div>`;
    return;
  }
  container.innerHTML = `
    <div class="review-row pending header"><span>比赛</span><span>开赛</span><span>预测</span><span>状态</span></div>
    ${rows
      .map((row) => `
        <div class="review-row pending">
          <span><strong>${escapeHtml(row.match)}</strong><small>${escapeHtml(row.league || "-")} · ID ${escapeHtml(row.fixtureId)}</small></span>
          <span>${escapeHtml(row.kickoffBeijing || "-")}</span>
          <span>${escapeHtml(row.topPredictionLabel || "-")}<small>${formatPercent(row.topProbability)}</small></span>
          <span>${escapeHtml(row.riskGate || "-")}<small>${escapeHtml(row.simAction || "-")}</small></span>
        </div>
      `)
      .join("")}
  `;
}

async function loadHistory() {
  try {
    const response = await fetch("/api/recent-predictions");
    const data = await response.json();
    renderHistory(data.runs || []);
    renderBankrollTrend(data.runs || []);
    if (state.activeView === "cabinView") loadPaperLedgerBook();
  } catch {
    document.querySelector("#historyList").innerHTML = `<div class="panel-placeholder">本地记录读取失败</div>`;
    renderBankrollTrend([]);
    if (state.activeView === "cabinView") renderPaperLedgerBook({});
  }
}

async function loadHistoryReplayLedger() {
  try {
    const response = await fetch("/api/history-replay-ledger");
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取历史回放账本失败");
    renderHistoryReplayLedger(data);
  } catch (error) {
    renderHistoryReplayLedger({ error: toChineseError(error.message) });
  }
}

function renderHistoryReplayLedger(ledger = {}) {
  const status = document.querySelector("#historyReplayStatus");
  if (ledger.error) {
    if (status) status.textContent = "回放读取失败";
    renderBankrollTrend([]);
    renderHistoryReplayRows([], ledger.error);
    return;
  }
  const original = ledger.modes?.original || {};
  const current = ledger.modes?.current || {};
  const originalSummary = original.summary || {};
  const currentSummary = current.summary || {};
  if (status) {
    status.textContent =
      `已结算 ${ledger.settledRuns ?? 0} 场 · 去重 ${ledger.duplicatesExcluded ?? 0} · 当前规则 ${formatSignedMoney(currentSummary.totalProfit || 0)}`;
  }
  const originalTimeline = original.timeline || [];
  const currentTimeline = current.timeline || [];
  const labels = longerTimelineLabels(originalTimeline, currentTimeline);
  const series = [
    { values: originalTimeline.map((item) => Number(item.bankroll || 0)), color: "#f26a21" },
    { values: currentTimeline.map((item) => Number(item.bankroll || 0)), color: "#7ca8ee" },
  ];
  renderLineChart("#historyBankrollChart", labels, series, { baselineZero: false });
  renderHistoryReplayRows(ledger.rows || [], ledger.notes?.[0]);
}

function longerTimelineLabels(first = [], second = []) {
  const timeline = first.length >= second.length ? first : second;
  return timeline.map((item, index) => index === 0 ? "起始" : String(item.label || `#${index}`));
}

function renderHistoryReplayRows(rows = [], note = "") {
  const container = document.querySelector("#historyReplayLedger");
  if (!container) return;
  const visibleRows = [...rows].slice(-6).reverse();
  if (!visibleRows.length) {
    container.innerHTML = `<div class="panel-placeholder">${escapeHtml(note || "暂无回放样本")}</div>`;
    return;
  }
  container.innerHTML = visibleRows
    .map((row) => {
      const original = row.original || {};
      const current = row.current || {};
      return `
        <button class="history-replay-row" type="button" data-run-id="${escapeHtml(row.runId || "")}">
          <span class="history-replay-match">
            <strong>${teamPairHtml(row.home || "主队", row.away || "客队", row.homeLogo, row.awayLogo)}</strong>
            <small>ID ${escapeHtml(row.fixtureId || "-")} · ${escapeHtml(row.league || "-")} · ${escapeHtml(row.scoreLabel || "待赛果")}</small>
          </span>
          <span><b>原始</b>${formatSignedMoney(original.totalProfit || 0)}<small>${compactSelections(original.selections)}</small></span>
          <span><b>当前</b>${formatSignedMoney(current.totalProfit || 0)}<small>${compactSelections(current.selections)}</small></span>
        </button>
      `;
    })
    .join("");
  container.querySelectorAll("[data-run-id]").forEach((button) => {
    button.addEventListener("click", () => previewPredictionRun(button.dataset.runId, { focusCabin: true }));
  });
}

function compactSelections(selections = []) {
  if (!selections.length) return "未入选";
  return selections
    .slice(0, 2)
    .map((item) => `${item.market || "-"} ${item.selection || "-"}`)
    .join(" / ");
}

async function loadPaperLedgerBook() {
  try {
    const response = await fetch("/api/paper-ledger");
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取模拟舱账本失败");
    state.loaded.paperLedger = true;
    renderPaperLedgerBook(data);
  } catch (error) {
    renderPaperLedgerBook({ error: toChineseError(error.message) });
  }
}

function renderPaperLedgerBook(book = {}) {
  const summary = book.summary || {};
  const ledgerRows = book.ledger || [];
  const liveRows = book.liveCabin || [];
  const liveReservedStake = liveRows.reduce((total, row) => total + Number(row.stake || 0), 0);
  const chartStatus = document.querySelector("#historyReplayStatus");
  if (chartStatus) {
    chartStatus.textContent = book.error
      ? "账本读取失败"
      : `起始 ${formatMoney(summary.startingBankroll ?? 1000)} · 当前 ${formatMoney(summary.equity ?? summary.startingBankroll ?? 1000)}`;
  }
  if (liveCabinStatus) {
    liveCabinStatus.textContent = book.error
      ? "读取失败"
      : `持仓 ${summary.liveCabinCount ?? liveRows.length} 笔 · 占用 ${formatMoney(liveReservedStake)}`;
  }
  if (historyLedgerStatus) {
    historyLedgerStatus.textContent = book.error
      ? "读取失败"
      : `下注 ${summary.ledgerCount ?? ledgerRows.length} 笔 · 已结算 ${summary.settledCount ?? 0} · 已折叠 ${summary.duplicatesExcluded ?? summary.duplicateCount ?? 0} 笔重复`;
  }
  renderPaperLedgerChart(book.timeline || [], book.error);
  renderPaperLedgerSummary(summary, ledgerRows, book.error || summary.note);
  renderLiveCabinRows(liveRows, book.error ? `读取失败：${book.error}` : "");
  renderHistoryLedgerRows(ledgerRows, book.error || summary.note);
}

function renderPaperLedgerChart(timeline = [], error = "") {
  if (error) {
    renderLineChart("#historyBankrollChart", [], [], { baselineZero: false });
    return;
  }
  const safeTimeline = timeline.length
    ? timeline
    : [{ date: "起始", label: "起始", bankroll: 1000 }];
  const labels = safeTimeline.map((item) => String(item.date || item.label || "起始"));
  const values = safeTimeline.map((item) => Number(item.bankroll || 0));
  renderLineChart(
    "#historyBankrollChart",
    labels,
    [{ values, color: "#2df0d0" }],
    { baselineZero: false },
  );
}

function renderPaperLedgerSummary(summary = {}, rows = [], note = "") {
  const container = document.querySelector("#historyReplayLedger");
  if (!container) return;
  if (!rows.length) {
    container.innerHTML = `<div class="panel-placeholder">${escapeHtml(note || "暂无下注记录")}</div>`;
    return;
  }
  const chips = [
    ["起始资金", formatMoney(summary.startingBankroll ?? 1000)],
    ["当前资金", formatMoney(summary.equity ?? summary.startingBankroll ?? 1000)],
    ["已实现盈亏", formatSignedMoney(summary.realizedPnl ?? 0)],
  ];
  container.innerHTML = `
    <div class="ledger-summary-strip">
      ${chips
        .map(([label, value]) => `
          <div>
            <span>${escapeHtml(label)}</span>
            <strong>${escapeHtml(value)}</strong>
          </div>
        `)
        .join("")}
    </div>
  `;
}

function renderPreMatchCabin(rows = [], note = "") {
  if (!preMatchCabin) return;
  if (!rows.length) {
    preMatchCabin.innerHTML = `
      <div class="panel-placeholder">
        ${escapeHtml(note || "暂无未开赛记录")}
      </div>
    `;
    return;
  }
  preMatchCabin.innerHTML = rows
    .map((row) => {
      const best = row.best || {};
      return `
        <article class="ledger-card pre-match-card">
          <div class="ledger-card-head">
            <strong>${teamPairHtml(row.home || "主队", row.away || "客队", row.homeLogo, row.awayLogo)}</strong>
            <span class="history-signal ${historyActionClass(best.signalStatus || best.action)}">${escapeHtml(actionLabel(best.signalStatus || best.action || "RESEARCH_WATCH"))}</span>
          </div>
          <div class="ledger-card-meta">
            <span>ID ${escapeHtml(row.fixtureId || "-")} · 运行 ${escapeHtml(row.runId || "-")}</span>
            <span>${escapeHtml(row.league || "-")} · ${escapeHtml(row.kickoffBeijing || "-")}</span>
            <span>盘口 ${escapeHtml(row.bookmaker || "未取得")} · ${escapeHtml(row.oddsCapturedAtBeijing || "未记录")}</span>
          </div>
          <div class="pre-market-strip">
            ${(row.markets || []).map(renderPreMatchMarketChip).join("")}
          </div>
          <p class="ledger-note">${escapeHtml(best.reason || "研究观察，未入账。")}</p>
        </article>
      `;
    })
    .join("");
}

function renderPreMatchMarketChip(item = {}) {
  const signal = item.signalStatus || item.action || "WATCH";
  return `
    <div class="pre-market-chip ${historyActionClass(signal)}">
      <span>${escapeHtml(item.market || "-")}</span>
      <strong>${escapeHtml(item.selection || "-")}</strong>
      <small>赔率 ${item.odds == null ? "-" : formatNumber(item.odds, 2)} · 研究EV ${formatPercent(item.evPbaseResearch ?? item.expectedValue)}</small>
    </div>
  `;
}

function renderLiveCabinRows(rows = [], note = "") {
  if (!liveCabin) return;
  if (!rows.length) {
    liveCabin.innerHTML = `
      <div class="panel-placeholder">
        ${escapeHtml(note || "暂无未开赛持仓")}
      </div>
    `;
    return;
  }
  liveCabin.innerHTML = `
    <div class="paper-ledger-table live-cabin-table">
      <div class="paper-ledger-row paper-ledger-head">
        <span>比赛 / 日期</span>
        <span>方向</span>
        <span>赔率 / 注额</span>
        <span>模型 / 市场</span>
        <span>状态 / 入账</span>
        <span>资金</span>
      </div>
      ${rows
        .map((row) => {
          const paperEv = row.expectedValue ?? row.paperExpectedValue ?? row.evPbaseResearch;
          const statusClass = historyActionClass(row.signalStatus || row.action || "PAPER_BUY");
          return `
            <button class="paper-ledger-row live-cabin-row" type="button" data-live-run="${escapeHtml(row.runId || "")}">
              <span class="paper-ledger-match">
                <strong>${teamPairHtml(row.home || "主队", row.away || "客队", row.homeLogo, row.awayLogo)}</strong>
                <small>ID ${escapeHtml(row.fixtureId || "-")} · 运行 ${escapeHtml(row.runId || "-")}</small>
                <small>${escapeHtml(row.league || "-")} · ${escapeHtml(row.kickoffBeijing || "开赛时间待核")}</small>
              </span>
              <span>
                <b>${escapeHtml(row.market || "-")}</b>
                <strong>${escapeHtml(row.selection || "-")}</strong>
                <small>${escapeHtml(row.bookmaker || "盘口未记录")}</small>
              </span>
              <span>
                <b>赔率</b>
                <strong>${row.odds == null ? "-" : formatNumber(row.odds, 2)}</strong>
                <small>注额 ${formatMoney(row.stake)}</small>
              </span>
              <span>
                <b>模型 / 市场</b>
                <strong>${formatPercent(row.modelProbability)} / ${formatPercent(row.marketProbability)}</strong>
                <small>EV ${formatPercent(paperEv)}</small>
              </span>
              <span>
                <span class="history-signal ${statusClass}">${escapeHtml(row.phaseLabel || row.statusLabel || "等待开赛")}</span>
                <strong>待结算 · 未结算</strong>
                <small>入账 ${escapeHtml(row.createdAtBeijing || "-")}</small>
              </span>
              <span>
                <b>当前资金</b>
                <strong>${formatMoney(row.currentEquity ?? row.bankrollBefore)}</strong>
                <small>可用 ${formatMoney(row.cashAfterStake ?? row.bankrollAfterStake)} · 预留 ${formatMoney(row.reservedStakeAfter ?? row.stake)}</small>
              </span>
            </button>
          `;
        })
        .join("")}
    </div>
  `;
  liveCabin.querySelectorAll("[data-live-run]").forEach((button) => {
    button.addEventListener("click", () => previewPredictionRun(button.dataset.liveRun, { focusCabin: true }));
  });
}

function renderHistoryLedgerRows(rows = [], note = "") {
  if (!historyLedger) return;
  if (!rows.length) {
    historyLedger.innerHTML = `
      <div class="panel-placeholder">
        ${escapeHtml(note || "暂无历史账本")}
      </div>
    `;
    return;
  }
  historyLedger.innerHTML = `
    <div class="paper-ledger-table">
      <div class="paper-ledger-row paper-ledger-head">
        <span>比赛 / 日期</span>
        <span>方向</span>
        <span>赔率 / 注额</span>
        <span>模型 / 市场</span>
        <span>赛果 / 盈亏</span>
        <span>资金</span>
      </div>
      ${rows
        .map((row) => {
      const statusClass = row.status === "SETTLED" ? (Number(row.profit || 0) >= 0 ? "buy" : "suspended") : "watch";
      return `
        <button class="paper-ledger-row ${row.duplicateFlag ? "has-folded-duplicates" : ""}" type="button" data-ledger-run="${escapeHtml(row.runId || "")}">
          <span class="paper-ledger-match">
            <strong>${teamPairHtml(row.home || "主队", row.away || "客队", row.homeLogo, row.awayLogo)}</strong>
            <small>ID ${escapeHtml(row.fixtureId || "-")} · 运行 ${escapeHtml(row.runId || "-")}</small>
            <small>${escapeHtml(row.league || "-")} · ${escapeHtml(row.kickoffBeijing || "-")}</small>
          </span>
          <span>
            <b>${escapeHtml(row.market || "-")}</b>
            <strong>${escapeHtml(row.selection || "-")}</strong>
            ${row.duplicateSuppressedCount ? `<small class="ledger-duplicate">已折叠重复 ${escapeHtml(row.duplicateSuppressedCount)} 笔</small>` : `<small>${escapeHtml(row.bookmaker || "未记录")}</small>`}
          </span>
          <span>
            <b>赔率</b>
            <strong>${row.odds == null ? "-" : formatNumber(row.odds, 2)}</strong>
            <small>注额 ${formatMoney(row.stake)}</small>
          </span>
          <span>
            <b>模型 / 市场</b>
            <strong>${formatPercent(row.modelProbability)} / ${formatPercent(row.marketProbability)}</strong>
            <small>研究EV ${formatPercent(row.evPbaseResearch ?? row.expectedValue)}</small>
          </span>
          <span>
            <span class="history-signal ${statusClass}">${escapeHtml(row.statusLabel || "-")}</span>
            <strong>${escapeHtml(row.score90 || "待结算")} · ${row.profit == null ? "未结算" : formatSignedMoney(row.profit)}</strong>
            <small>${escapeHtml(row.settledAtBeijing || row.createdAtBeijing || "-")}</small>
          </span>
          <span>
            <b>当前资金</b>
            <strong>${row.bankrollAfterSettlement == null ? "待结算" : formatMoney(row.bankrollAfterSettlement)}</strong>
            <small>${escapeHtml(row.status === "SETTLED" ? "已结算入曲线" : "未进入曲线")}</small>
          </span>
        </button>
      `;
    })
    .join("")}
    </div>
  `;
  historyLedger.querySelectorAll("[data-ledger-run]").forEach((button) => {
    button.addEventListener("click", () => previewPredictionRun(button.dataset.ledgerRun, { focusCabin: true }));
  });
}

async function loadRecentBatches() {
  try {
    const response = await fetch("/api/recent-batches");
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取批次失败");
    state.recentBatches = data.batches || [];
    const maxPage = Math.max(1, Math.ceil(state.recentBatches.length / state.batchHistoryPageSize));
    state.batchHistoryPage = clamp(Number(state.batchHistoryPage || 1), 1, maxPage);
    if (!state.batchResult) renderRecentBatches();
  } catch {
    if (!state.batchResult && batchPoolContent) {
      batchPoolContent.innerHTML = `<div class="panel-placeholder">本地批次读取失败</div>`;
    }
  }
}

function renderRecentBatches() {
  if (!batchPoolContent) return;
  if (!state.recentBatches.length) {
    batchPoolContent.innerHTML = `<div class="panel-placeholder">暂无批次</div>`;
    if (batchPoolStatus) batchPoolStatus.textContent = "等待批量分析";
    return;
  }
  const filtered = filteredRecentBatches();
  const pageSize = state.batchHistoryPageSize;
  const totalPages = Math.max(1, Math.ceil(filtered.length / pageSize));
  state.batchHistoryPage = clamp(Number(state.batchHistoryPage || 1), 1, totalPages);
  const start = (state.batchHistoryPage - 1) * pageSize;
  const pageItems = filtered.slice(start, start + pageSize);
  batchPoolContent.innerHTML = `
    <div class="batch-history-toolbar">
      <label class="batch-search-field">
        <span>搜索批次</span>
        <input id="batchHistorySearch" type="search" value="${escapeHtml(state.batchHistorySearch)}" placeholder="按名称、备注、日期、比赛 ID 搜索">
      </label>
      <div class="batch-search-actions">
        <button class="mini-action" id="applyBatchSearch" type="button">搜索</button>
        <button class="mini-action" id="clearBatchSearch" type="button">清空</button>
      </div>
      <div class="batch-history-count">
        <strong>${escapeHtml(filtered.length)}</strong>
        <span>匹配 / 共 ${escapeHtml(state.recentBatches.length)} 个批次</span>
      </div>
    </div>
    <div class="fixture-empty">本地批次，不消耗 API。</div>
    ${
      pageItems.length
        ? `<div class="history-list batch-history-list">${pageItems.map(renderBatchHistoryItem).join("")}</div>`
        : `<div class="panel-placeholder">无匹配批次</div>`
    }
    ${renderBatchHistoryPagination(filtered.length, totalPages)}
  `;
  if (batchPoolStatus) batchPoolStatus.textContent = `已保存 ${state.recentBatches.length} 个批次`;
  bindBatchHistoryControls(totalPages);
}

function renderBatchHistoryItem(batch) {
  const fixtureIds = batch.fixtureIds || [];
  const fixtureLabel = fixtureIds.slice(0, 6).join("、") || "按日期筛选";
  const hiddenCount = Math.max(0, fixtureIds.length - 6);
  return `
    <div class="history-item batch-history-item">
      <div class="history-main">
        <strong>${batch.isOfficial ? '<span class="official-badge">官方</span>' : ""}${escapeHtml(batch.label || `批次 ${batch.id}`)}</strong>
        <span class="muted">批次 ${escapeHtml(batch.id)} · ${escapeHtml(batch.date || "-")} · ${escapeHtml(batch.scopeZh || "-")} · ${escapeHtml(batch.created_at || "-")}</span>
      </div>
      <div class="history-insights">
        <span><b>成功/失败</b>${escapeHtml(batch.collected_count ?? 0)} / ${escapeHtml(batch.failed_count ?? 0)}</span>
        <span><b>信号</b>${escapeHtml(batch.signal_count ?? 0)} 个</span>
        <span><b>组合占用</b>${formatMoney(batch.planned_stake)}</span>
        <span><b>期望收益</b>${formatMoney(batch.expected_profit)}</span>
        <span><b>指定 ID</b>${escapeHtml(fixtureLabel)}${hiddenCount ? ` 等 ${hiddenCount} 场` : ""}</span>
        <span><b>备注</b>${escapeHtml(batch.notes || "未填写")}</span>
      </div>
      <div class="history-actions">
        <button class="mini-action restore-batch" type="button" data-batch-id="${escapeHtml(batch.id)}">恢复批次</button>
      </div>
    </div>
  `;
}

function renderBatchHistoryPagination(total, totalPages) {
  if (total <= state.batchHistoryPageSize) return "";
  return `
    <div class="batch-pagination">
      <button class="mini-action batch-history-page" type="button" data-page="${state.batchHistoryPage - 1}"${state.batchHistoryPage <= 1 ? " disabled" : ""}>上一页</button>
      <span>第 ${escapeHtml(state.batchHistoryPage)} / ${escapeHtml(totalPages)} 页</span>
      <button class="mini-action batch-history-page" type="button" data-page="${state.batchHistoryPage + 1}"${state.batchHistoryPage >= totalPages ? " disabled" : ""}>下一页</button>
    </div>
  `;
}

function bindBatchHistoryControls(totalPages) {
  const search = batchPoolContent.querySelector("#batchHistorySearch");
  if (search) {
    const applySearch = () => {
      state.batchHistorySearch = search.value;
      state.batchHistoryPage = 1;
      renderRecentBatches();
    };
    search.addEventListener("keydown", (event) => {
      if (event.key === "Enter") applySearch();
    });
    batchPoolContent.querySelector("#applyBatchSearch")?.addEventListener("click", applySearch);
    batchPoolContent.querySelector("#clearBatchSearch")?.addEventListener("click", () => {
      state.batchHistorySearch = "";
      state.batchHistoryPage = 1;
      renderRecentBatches();
    });
  }
  batchPoolContent.querySelectorAll(".batch-history-page").forEach((button) => {
    button.addEventListener("click", () => {
      state.batchHistoryPage = clamp(Number(button.dataset.page || 1), 1, totalPages);
      renderRecentBatches();
    });
  });
  batchPoolContent.querySelectorAll(".restore-batch").forEach((button) => {
    button.addEventListener("click", () => loadBatchRun(button.dataset.batchId));
  });
  batchPoolContent.querySelectorAll(".save-batch-meta").forEach((button) => {
    button.addEventListener("click", () => saveBatchMetadata(button));
  });
  batchPoolContent.querySelectorAll(".mark-official-batch").forEach((button) => {
    button.addEventListener("click", () => markOfficialBatch(button));
  });
}

function filteredRecentBatches() {
  const query = state.batchHistorySearch.trim().toLowerCase();
  if (!query) return [...state.recentBatches];
  return state.recentBatches.filter((batch) => {
    const values = [
      batch.id,
      batch.label,
      batch.fallbackLabel,
      batch.title,
      batch.notes,
      batch.date,
      batch.scopeZh,
      batch.created_at,
      ...(batch.fixtureIds || []),
    ];
    return values.some((value) => String(value ?? "").toLowerCase().includes(query));
  });
}

async function saveBatchMetadata(button) {
  const batchId = button.dataset.batchId;
  const item = button.closest(".batch-history-item");
  if (!batchId || !item) return;
  const title = item.querySelector(".batch-title-input")?.value || "";
  const notes = item.querySelector(".batch-notes-input")?.value || "";
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "保存中";
  try {
    const response = await fetch("/api/update-batch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({ batchId, title, notes }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "保存批次失败");
    const index = state.recentBatches.findIndex((batch) => String(batch.id) === String(batchId));
    if (index >= 0) {
      const cleanTitle = title.trim();
      const cleanNotes = notes.trim();
      const fallbackLabel = state.recentBatches[index].fallbackLabel || `批次 ${batchId}`;
      state.recentBatches[index] = {
        ...state.recentBatches[index],
        title: cleanTitle,
        notes: cleanNotes,
        label: cleanTitle || fallbackLabel,
      };
    }
    formError.textContent = "批次名称和备注已保存。";
    renderRecentBatches();
  } catch (error) {
    formError.textContent = toChineseError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function markOfficialBatch(button) {
  const batchId = button.dataset.batchId;
  if (!batchId) return;
  const originalText = button.textContent;
  button.disabled = true;
  button.textContent = "标记中";
  try {
    const response = await fetch("/api/mark-official-batch", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        batchId,
        officialDate: button.dataset.date || reviewDate?.value || defaultReviewDate(),
      }),
    });
    const data = await response.json();
    if (!response.ok) throw responseError(data, "标记官方批次失败");
    formError.textContent = `批次 ${batchId} 已设为官方复盘批次。`;
    await loadRecentBatches();
    await loadDailyReview();
  } catch (error) {
    formError.textContent = toChineseError(error.message);
  } finally {
    button.disabled = false;
    button.textContent = originalText;
  }
}

async function loadBatchRun(batchId) {
  if (!batchId) return;
  try {
    const response = await fetch(`/api/batch-run?batch_id=${encodeURIComponent(batchId)}`);
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取批次失败");
    renderBatchResult(data);
    setActiveView("batchView");
  } catch (error) {
    formError.textContent = toChineseError(error.message);
  }
}

function renderRunResultBlocks(payload, summary = {}) {
  const blocks = buildRunResultBlocks(payload, summary);
  return blocks.map((block) => `
    <article class="run-result-card ${escapeHtml(block.statusClass || "neutral")}">
      <span>${escapeHtml(block.label)}</span>
      <strong>${escapeHtml(block.value)}</strong>
      ${block.detail ? `<small>${escapeHtml(block.detail)}</small>` : ""}
    </article>
  `).join("");
}

function buildRunResultBlocks(payload, summary = {}) {
  const oneXtwo = marketBlock(payload, summary, "胜平负");
  const totals = marketBlock(payload, summary, "大小球");
  const handicap = marketBlock(payload, summary, "让球");
  const profit = singleRunProfit(payload, summary);
  return [
    oneXtwo,
    totals,
    handicap,
    {
      label: "资金",
      value: formatSignedMoney(profit),
      detail: "单场盈亏",
      statusClass: Number(profit || 0) > 0 ? "positive" : Number(profit || 0) < 0 ? "negative" : "neutral",
    },
  ];
}

function marketBlock(payload, summary, market) {
  const item = payload ? bestRecommendationForMarket(payload, market) : null;
  if (item) {
    const signal = item.signal_status || item.action || item.publicAction || "";
    const evValue =
      item.paper_expected_value_per_unit ??
      item.ev_pshr_candidate ??
      item.ev_pbase_research ??
      item.expected_value_per_unit ??
      item.conservative_expected_value_per_unit;
    const detailParts = [
      item.odds == null ? "" : `赔率 ${formatNumber(item.odds, 2)}`,
      item.model_probability == null ? "" : `模型 ${formatPercent(item.model_probability)}`,
      evValue == null ? "" : `EV ${formatPercent(evValue)}`,
    ].filter(Boolean);
    return {
      label: market,
      value: item.selection || "-",
      detail: detailParts.join(" · "),
      statusClass: historyActionClass(signal),
    };
  }

  if (market === "胜平负") {
    const label = summary.predictionLabel || summary.recommendationSelection || "-";
    const detailParts = [
      summary.odds == null ? "" : `赔率 ${formatNumber(summary.odds, 2)}`,
      summary.modelProbability == null
        ? summary.predictionProbability == null ? "" : `模型 ${formatPercent(summary.predictionProbability)}`
        : `模型 ${formatPercent(summary.modelProbability)}`,
      summary.evPbaseResearch == null && summary.expectedValue == null
        ? ""
        : `EV ${formatPercent(summary.evPbaseResearch ?? summary.expectedValue)}`,
    ].filter(Boolean);
    return {
      label: market,
      value: label,
      detail: detailParts.join(" · ") || "等待回溯",
      statusClass: historyActionClass(summary.signalStatus || summary.recommendationAction),
    };
  }

  if (summary.recommendationMarket === market) {
    const detailParts = [
      summary.odds == null ? "" : `赔率 ${formatNumber(summary.odds, 2)}`,
      summary.modelProbability == null ? "" : `模型 ${formatPercent(summary.modelProbability)}`,
      summary.evPbaseResearch == null && summary.expectedValue == null
        ? ""
        : `EV ${formatPercent(summary.evPbaseResearch ?? summary.expectedValue)}`,
    ].filter(Boolean);
    return {
      label: market,
      value: summary.recommendationSelection || summary.recommendationSummary || "-",
      detail: detailParts.join(" · "),
      statusClass: historyActionClass(summary.signalStatus || summary.recommendationAction),
    };
  }

  return {
    label: market,
    value: payload ? "暂无方向" : "回溯读取中",
    detail: payload ? "未形成该市场方向" : "本地记录补齐",
    statusClass: payload ? "neutral" : "loading",
  };
}

function bestRecommendationForMarket(payload, market) {
  const recommendations = (payload?.recommendations || []).filter((item) => item?.market === market);
  if (!recommendations.length) return null;
  const priority = {
    PAPER_BUY: 5,
    MODEL_CANDIDATE: 4,
    BUY: 4,
    SUSPENDED: 3,
    RESEARCH_WATCH: 2,
    WATCH: 2,
    NO_MARKET: 1,
  };
  return [...recommendations].sort((a, b) => {
    const aSignal = a.signal_status || a.action || "";
    const bSignal = b.signal_status || b.action || "";
    const aEv = Number(a.ev_pbase_research ?? a.expected_value_per_unit ?? -99);
    const bEv = Number(b.ev_pbase_research ?? b.expected_value_per_unit ?? -99);
    return (priority[bSignal] || 0) - (priority[aSignal] || 0) || bEv - aEv;
  })[0];
}

function singleRunProfit(payload, summary = {}) {
  if (payload?.portfolio?.expected_profit != null) return Number(payload.portfolio.expected_profit);
  if (summary.expectedProfit != null) return Number(summary.expectedProfit);
  if (summary.expectedBankroll != null && summary.bankroll != null) {
    return Number(summary.expectedBankroll) - Number(summary.bankroll);
  }
  return 0;
}

async function hydrateRunCards(items = []) {
  const runIds = [...new Set(items.map((item) => item.runId ?? item.id).filter(Boolean).map(String))];
  await Promise.allSettled(runIds.slice(0, 20).map(async (runId) => {
    const payload = await loadCachedPredictionPayload(runId);
    document.querySelectorAll("[data-run-card]").forEach((card) => {
      if (String(card.dataset.runCard) !== runId) return;
      const target = card.querySelector(".run-result-grid");
      if (target) target.innerHTML = renderRunResultBlocks(payload, items.find((item) => String(item.runId ?? item.id) === runId) || {});
    });
  }));
}

async function loadCachedPredictionPayload(runId) {
  const key = String(runId);
  if (state.historyDetailsCache.has(key)) return state.historyDetailsCache.get(key);
  const response = await fetch(`/api/prediction?run_id=${encodeURIComponent(key)}`);
  const data = await response.json();
  if (!response.ok) throw responseError(data, "读取单场记录失败");
  state.historyDetailsCache.set(key, data);
  return data;
}

async function loadPredictionReplay(runId) {
  const key = String(runId);
  if (state.replayCache.has(key)) return state.replayCache.get(key);
  const response = await fetch(`/api/prediction-replay?run_id=${encodeURIComponent(key)}`);
  const data = await response.json();
  if (!response.ok) throw responseError(data, "读取回溯模拟舱失败");
  state.replayCache.set(key, data);
  return data;
}

async function previewPredictionRun(runId, options = {}) {
  if (!runId) return;
  if (options.focusCabin) {
    setActiveView("cabinView");
    document.querySelector("#cabinView")?.scrollIntoView({ behavior: "smooth", block: "start" });
  }
  try {
    const replay = await loadPredictionReplay(runId);
    renderHistoryReplayPreview(replay);
    document.querySelectorAll("[data-run-card].selected").forEach((card) => card.classList.remove("selected"));
    document.querySelector(`[data-run-card="${CSS.escape(String(runId))}"]`)?.classList.add("selected");
  } catch (error) {
    try {
      const payload = await loadCachedPredictionPayload(runId);
      renderHistoryTracePreview(payload, "批次回溯");
    } catch {
      if (historyTracePreview) {
        historyTracePreview.innerHTML = `<div class="panel-placeholder">${escapeHtml(toChineseError(error.message))}</div>`;
      }
    }
  }
}

function renderTraceDrawer(data) {
  if (!traceDrawerContent) return;
  const match = data.match || {};
  const meta = data.meta || {};
  const processing = data.dataProcessing || {};
  const best = bestOverallRecommendation(data);
  const home = processing.home || {};
  const away = processing.away || {};
  const snapshotRows = buildTraceSnapshotRows(data, best);
  traceDrawerContent.innerHTML = `
    <div class="trace-meta-card">
      <span>比赛 ID</span>
      <strong>${escapeHtml(meta.fixtureId || data.match_id || "-")}</strong>
      <span>运行批次</span>
      <strong>${data.runId ? `#${escapeHtml(data.runId)}` : "未生成"}</strong>
      <span>分析时间</span>
      <strong>${escapeHtml(meta.oddsCapturedAtBeijing || "当前本地记录")}</strong>
    </div>
    <div class="trace-timeline">
      ${snapshotRows
        .map(
          (row) => `
            <div class="trace-line">
              <i></i>
              <div>
                <strong>${escapeHtml(row.label)}</strong>
                <span>${escapeHtml(row.value)}</span>
              </div>
            </div>
          `,
        )
        .join("")}
    </div>
    ${renderTraceChecklist(best)}
    <button class="secondary-action trace-review-link" type="button">查看完整赛后复盘 →</button>
  `;
  traceDrawerContent.querySelector(".trace-review-link")?.addEventListener("click", () => setActiveView("reviewView"));
}

function buildTraceSnapshotRows(data, best) {
  const meta = data.meta || {};
  const selected = meta.selectedBookmakers || {};
  const lines = [
    ["盘口快照", meta.oddsCapturedAtBeijing || "当前快照"],
    ["胜平负", bookmakerLine("1X2", selected, bestRecommendationForMarket(data, "胜平负"))],
    ["大小球", bookmakerLine("OU", selected, bestRecommendationForMarket(data, "大小球"))],
    ["让球", bookmakerLine("AH", selected, bestRecommendationForMarket(data, "让球"))],
  ];
  if (best) {
    lines.push(["模拟舱主方向", `${best.market || "-"} · ${best.selection || "-"} · ${actionLabel(best.signal_status || best.action || best.publicAction)}`]);
  }
  return lines.map(([label, value]) => ({ label, value }));
}

function bookmakerLine(key, selected, item) {
  const bookmaker = selected[key] || "-";
  const odds = item?.odds == null ? "" : ` @ ${formatNumber(item.odds, 2)}`;
  const selection = item?.selection ? ` · ${item.selection}` : "";
  return `${bookmaker}${selection}${odds}`;
}

function renderTraceChecklist(item) {
  const rows = [
    ["方向", item ? `${item.market || "-"}：${item.selection || "-"}` : "等待模拟舱方向", "ok"],
    ["研究EV(pbase)", item?.ev_pbase_research ?? item?.expected_value_per_unit, "ok"],
    ["纸上EV(p_adj)", item?.paper_expected_value_per_unit ?? item?.ev_pshr_candidate ?? item?.conservative_expected_value_per_unit, "warn"],
    ["正式EV(pfinal)", item?.ev_pfinal_exec, "info"],
    ["最终结果", "待赛后录入", "info"],
  ];
  return `
    <div class="trace-check-card">
      <h3>可回溯模拟舱结果</h3>
      ${rows
        .map(([label, value, tone]) => `
          <div class="trace-check ${tone}">
            <span>${escapeHtml(label)}</span>
            <strong>${typeof value === "number" ? formatPercent(value) : escapeHtml(value == null ? "未开放" : value)}</strong>
          </div>
        `)
        .join("")}
    </div>
  `;
}

function renderHistoryReplayPreview(replay) {
  if (!historyTracePreview) return;
  const match = replay.match || {};
  const meta = replay.meta || {};
  const result = replay.result || {};
  const original = replay.modes?.original || {};
  const current = replay.modes?.current || {};
  const originalRows = original.rows || [];
  const currentRows = current.rows || [];
  const replayRows = originalRows.length ? originalRows : currentRows;
  if (historyPreviewCrumbs) {
    historyPreviewCrumbs.textContent = `回溯 → 当时方向`;
  }
  historyTracePreview.innerHTML = `
    <div class="replay-lab compact-replay">
      <section class="replay-hero">
        <div>
          <span>历史回放</span>
          <strong>${teamPairHtml(match.homeZh || match.home || "主队", match.awayZh || match.away || "客队", match.homeLogo, match.awayLogo)}</strong>
          <small>${escapeHtml(meta.leagueNameZh || meta.leagueName || "-")} · ${escapeHtml(meta.kickoffBeijing || "-")} · 运行 #${escapeHtml(replay.runId || "-")}</small>
        </div>
        <div class="replay-result ${result.status === "SETTLED" ? "settled" : "pending"}">
          <span>${escapeHtml(result.statusLabel || "未结算")}</span>
          <strong>${escapeHtml(result.scoreLabel || "待赛果")}</strong>
          <small>${escapeHtml(result.actualResultLabel || "")}</small>
        </div>
      </section>

      <section class="replay-table-card">
        <div class="section-header compact">
          <div><p class="eyebrow">原始快照</p><h3>当时模拟舱方向</h3></div>
          <span class="muted">不重抓盘口</span>
        </div>
        ${renderReplayRows(replayRows)}
      </section>
    </div>
  `;
}

function renderReplayModeCard(mode) {
  const summary = mode.summary || {};
  return `
    <article class="replay-mode-card">
      <div class="replay-mode-head">
        <div>
          <span>${escapeHtml(mode.modeLabel || "-")}</span>
          <strong>${formatSignedMoney(summary.totalProfit || 0)}</strong>
        </div>
        <em>${escapeHtml(mode.modeNote || "")}</em>
      </div>
      <div class="replay-metrics">
        <div><span>入选</span><strong>${escapeHtml(summary.selectedCount ?? 0)}</strong></div>
        <div><span>已结算</span><strong>${escapeHtml(summary.settledCount ?? 0)}</strong></div>
        <div><span>占用</span><strong>${formatMoney(summary.totalStake || 0)}</strong></div>
        <div><span>ROI</span><strong>${formatPercent(summary.roi || 0)}</strong></div>
      </div>
      <div class="replay-market-strip">
        ${(mode.marketSummary || []).map((item) => `
          <span>
            ${escapeHtml(item.market || "-")}
            <b>${escapeHtml(item.selectedCount ?? 0)}</b>
            <small>${formatSignedMoney(item.totalProfit || 0)}</small>
          </span>
        `).join("")}
      </div>
    </article>
  `;
}

function renderReplayRows(rows = []) {
  if (!rows.length) return `<div class="panel-placeholder">暂无可回溯方向。</div>`;
  return `
    <div class="replay-rows">
      ${rows.map((row) => {
        const tone = row.selected
          ? row.profit > 0 ? "positive" : row.profit < 0 ? "negative" : "neutral"
          : "muted";
        return `
          <div class="replay-row ${tone}">
            <div>
              <span>${escapeHtml(row.market || "-")}</span>
              <strong>${escapeHtml(row.selection || "-")}</strong>
              <small>${escapeHtml(row.eligibilityLabel || "-")}</small>
            </div>
            <div><span>赔率</span><strong>${row.odds == null ? "-" : formatNumber(row.odds, 2)}</strong></div>
            <div><span>${escapeHtml(row.modelProbabilityLabel || "模型概率")}</span><strong>${formatPercent(row.modelProbability)}</strong></div>
            <div><span>研究EV</span><strong>${formatPercent(row.researchEv)}</strong></div>
            <div><span>纸上EV</span><strong>${row.paperEv == null ? "未开放" : formatPercent(row.paperEv)}</strong></div>
            <div><span>赛果</span><strong>${escapeHtml(row.settlementLabel || "-")}</strong></div>
            <div><span>盈亏</span><strong>${formatSignedMoney(row.profit || 0)}</strong></div>
          </div>
        `;
      }).join("")}
    </div>
  `;
}

function renderReplayChart(selector, timeline, color) {
  const labels = (timeline || []).map((item) => String(item.label || "-"));
  const values = (timeline || []).map((item) => Number(item.bankroll || 0));
  renderLineChart(selector, labels, [{ values, color }], { baselineZero: false });
}

function renderHistoryTracePreview(data, sourceLabel = "批次回溯") {
  if (!historyTracePreview) return;
  const match = data.match || {};
  const meta = data.meta || {};
  const processing = data.dataProcessing || {};
  const best = bestOverallRecommendation(data);
  const home = processing.home || {};
  const away = processing.away || {};
  const profit = singleRunProfit(data, {});
  if (historyPreviewCrumbs) {
    historyPreviewCrumbs.textContent = `${sourceLabel} → 查看单场 → 数据回溯 → 模拟舱结果`;
  }
  historyTracePreview.innerHTML = `
    <div class="trace-preview-grid">
      <article class="trace-preview-card match-card">
        <strong>${teamPairHtml(teamLabel(match, "home"), teamLabel(match, "away"), teamLogoFromMatch(match, "home"), teamLogoFromMatch(match, "away"))}</strong>
        <span>ID: ${escapeHtml(meta.fixtureId || "-")} · ${escapeHtml(meta.leagueNameZh || meta.leagueName || "-")}</span>
        <span>${escapeHtml(meta.kickoffBeijing || "-")} · ${escapeHtml(meta.venue || "-")}</span>
      </article>
      <article class="trace-preview-card">
        <span>盘口快照</span>
        <strong>${escapeHtml(meta.oddsCapturedAtBeijing || "当前快照")}</strong>
        <small>${escapeHtml((meta.bookmakerPriority || []).slice(0, 4).join(" / ") || meta.bookmaker || "未记录庄家")}</small>
      </article>
      <article class="trace-preview-card">
        <span>近 10 场样本</span>
        <strong>${escapeHtml(home.validCount ?? 0)}/10 · ${escapeHtml(away.validCount ?? 0)}/10</strong>
        <small>主队场均进球 ${formatNumber(home.goalsForAverage, 2)}，客队场均进球 ${formatNumber(away.goalsForAverage, 2)}</small>
      </article>
      <article class="trace-preview-card">
        <span>模拟舱原因</span>
        <strong>${escapeHtml(best ? actionLabel(best.signal_status || best.action || best.publicAction) : "等待方向")}</strong>
        <small>${escapeHtml(best?.reason || "等待模型生成可解释原因。")}</small>
      </article>
      <article class="trace-preview-card ev-card">
        <span>EV 闸门</span>
        <strong>${escapeHtml(best ? decisionLabel(best.decision_status || best.ev_status || best.signal_status) : "未开放")}</strong>
        <small>研究EV ${best?.ev_pbase_research == null ? "-" : formatPercent(best.ev_pbase_research)} · 纸上EV ${best?.paper_expected_value_per_unit == null ? "-" : formatPercent(best.paper_expected_value_per_unit)}</small>
      </article>
    </div>
    <div class="trace-preview-bottom">
      <div class="trace-time-axis">
        ${["盘口初盘", "早盘资金流", "临场波动", "比赛前10分钟", "开赛", "半场", "全场结束"]
          .map((label, index) => `<span class="${index === 3 ? "active" : ""}"><i></i>${escapeHtml(label)}</span>`)
          .join("")}
      </div>
      <div class="trace-profit-chart">
        <div>
          <span>模拟舱盈亏曲线</span>
          <strong>最终盈亏 ${formatSignedMoney(profit)}</strong>
        </div>
        ${miniProfitSvg(profit)}
      </div>
    </div>
  `;
}

function bestOverallRecommendation(payload) {
  const items = payload?.recommendations || [];
  if (!items.length) return null;
  const priority = {
    PAPER_BUY: 6,
    MODEL_CANDIDATE: 5,
    BUY: 5,
    RESEARCH_WATCH: 4,
    WATCH: 3,
    SUSPENDED: 2,
    NO_MARKET: 1,
  };
  return [...items].sort((a, b) => {
    const aSignal = a.signal_status || a.action || a.publicAction || "";
    const bSignal = b.signal_status || b.action || b.publicAction || "";
    const aEv = Number(a.ev_pbase_research ?? a.expected_value_per_unit ?? -99);
    const bEv = Number(b.ev_pbase_research ?? b.expected_value_per_unit ?? -99);
    return (priority[bSignal] || 0) - (priority[aSignal] || 0) || bEv - aEv;
  })[0];
}

function miniProfitSvg(profit) {
  const raw = Number(profit || 0);
  const end = Number.isFinite(raw) ? raw : 0;
  const values = [0, end * 0.16, end * 0.32, end * 0.58, end * 0.72, end * 0.86, end];
  const min = Math.min(...values, -20);
  const max = Math.max(...values, 20);
  const points = values
    .map((value, index) => {
      const x = 18 + index * 52;
      const y = 80 - ((value - min) / (max - min || 1)) * 54;
      return `${x},${y}`;
    })
    .join(" ");
  return `
    <svg viewBox="0 0 350 100" role="img" aria-label="模拟舱盈亏曲线">
      <defs>
        <linearGradient id="profitLine" x1="0" x2="1">
          <stop offset="0" stop-color="#2df0d0" />
          <stop offset="1" stop-color="#4fa7ff" />
        </linearGradient>
      </defs>
      <path d="M18 80H332" stroke="rgba(159,200,214,.2)" stroke-width="1" />
      <polyline points="${points}" fill="none" stroke="url(#profitLine)" stroke-width="3" stroke-linecap="round" stroke-linejoin="round" />
      <circle cx="330" cy="${points.split(" ").at(-1).split(",")[1]}" r="4" fill="${end >= 0 ? "#2df0d0" : "#ff6f71"}" />
    </svg>
  `;
}

function renderHistoryRailFacade(runs) {
  if (!historyRailContent) return;
  const latest = runs[0] || {};
  const signalCount = runs.filter((run) => ["PAPER_BUY", "MODEL_CANDIDATE", "BUY", "RESEARCH_WATCH"].includes(run.signalStatus || run.recommendationAction)).length;
  const watchCount = runs.filter((run) => ["RESEARCH_WATCH", "WATCH"].includes(run.signalStatus || run.recommendationAction)).length;
  const suspendedCount = runs.filter((run) => (run.signalStatus || run.recommendationAction) === "SUSPENDED").length;
  const bookmakers = uniqueSorted(runs.map((run) => run.bookmaker).filter(Boolean)).slice(0, 5);
  if (!runs.length) {
    historyRailContent.innerHTML = `<div class="panel-placeholder">暂无历史预测记录。</div>`;
    return;
  }
  historyRailContent.innerHTML = `
    <div class="history-rail-meta">
      <span>当前批次</span>
      <strong>运行 #${escapeHtml(latest.id || "-")}</strong>
      <span>最近时间</span>
      <strong>${escapeHtml(latest.kickoffBeijing || latest.created_at || "-")}</strong>
    </div>
    <div class="history-rail-stats">
      <span><b>${escapeHtml(runs.length)}</b> 总记录</span>
      <span><b>${escapeHtml(signalCount)}</b> 可观察</span>
      <span><b>${escapeHtml(watchCount)}</b> 观望</span>
      <span><b>${escapeHtml(suspendedCount)}</b> 暂停</span>
    </div>
    <div class="control-divider"><p class="eyebrow">博彩公司优先级</p></div>
    <div class="bookmaker-priority">
      ${(bookmakers.length ? bookmakers : ["Pinnacle", "Bet365", "Sbobt"])
        .map((bookmaker, index) => `<span class="${index === 0 ? "active" : ""}">${escapeHtml(bookmaker)}</span>`)
        .join("")}
    </div>
    <div class="control-divider"><p class="eyebrow">批次操作</p></div>
    <button class="secondary-action history-rail-action" type="button" data-history-action="batch">查看批量赛事池</button>
    <button class="secondary-action history-rail-action" type="button" data-history-action="review">查看赛后复盘</button>
  `;
  historyRailContent.querySelector('[data-history-action="batch"]')?.addEventListener("click", () => setActiveView("batchView"));
  historyRailContent.querySelector('[data-history-action="review"]')?.addEventListener("click", () => setActiveView("reviewView"));
}

function renderHistory(runs) {
  state.historyRuns = runs || [];
  if (!runs.length) {
    document.querySelector("#historyList").innerHTML = `<div class="panel-placeholder">暂无预测记录</div>`;
    renderHistoryRailFacade([]);
    return;
  }
  renderHistoryRailFacade(runs);
  const totalPages = Math.max(1, Math.ceil(runs.length / state.historyPageSize));
  state.historyPage = clamp(Number(state.historyPage || 1), 1, totalPages);
  const start = (state.historyPage - 1) * state.historyPageSize;
  const pageRuns = runs.slice(start, start + state.historyPageSize);
  document.querySelector("#historyList").innerHTML = `
    <div class="history-card-list">
      ${pageRuns
        .map((run) => `
          <article class="history-card-row" data-run-card="${escapeHtml(run.id)}">
            <div class="history-card-main">
              <strong>${teamPairHtml(run.homeZh || run.home_team || "主队", run.awayZh || run.away_team || "客队", run.homeLogo || run.home_logo, run.awayLogo || run.away_logo)}</strong>
              <span class="muted">ID: ${escapeHtml(run.match_id || run.fixtureId || "-")} · 运行 ${escapeHtml(run.id)}</span>
            </div>
            <div class="history-card-meta">
              <span>联赛 / 时间</span>
              <strong>${escapeHtml(run.leagueZh || "-")}</strong>
              <span>${escapeHtml(run.kickoffBeijing || run.created_at || "-")}</span>
              <small>${escapeHtml(run.bookmaker || "优先庄家")}</small>
            </div>
            <div class="run-result-grid history-card-markets">${renderRunResultBlocks(null, run)}</div>
            <div class="history-card-actions">
              <button class="mini-action open-run" type="button" data-run-id="${escapeHtml(run.id)}">查看单场</button>
              <button class="mini-action open-trace" type="button" data-run-id="${escapeHtml(run.id)}">回溯数据</button>
              <a class="history-link" href="/api/report?format=xlsx&amp;run_id=${encodeURIComponent(run.id)}">导出报告</a>
            </div>
          </article>
        `)
        .join("")}
    </div>
    ${renderHistoryPagination(runs.length, totalPages)}
  `;
  const historyList = document.querySelector("#historyList");
  historyList.querySelectorAll(".open-run").forEach((button) => {
    button.addEventListener("click", () => loadPredictionRun(button.dataset.runId));
  });
  historyList.querySelectorAll(".open-trace").forEach((button) => {
    button.addEventListener("click", () => previewPredictionRun(button.dataset.runId, { focusCabin: true }));
  });
  historyList.querySelectorAll(".history-page").forEach((button) => {
    button.addEventListener("click", () => {
      state.historyPage = clamp(Number(button.dataset.page || 1), 1, totalPages);
      renderHistory(state.historyRuns);
    });
  });
  hydrateRunCards(pageRuns);
  previewPredictionRun(pageRuns[0]?.id);
}

function renderHistoryPagination(total, totalPages) {
  if (total <= state.historyPageSize) return "";
  return `
    <div class="batch-pagination history-pagination">
      <button class="mini-action history-page" type="button" data-page="${state.historyPage - 1}"${state.historyPage <= 1 ? " disabled" : ""}>上一页</button>
      <span>第 ${escapeHtml(state.historyPage)} / ${escapeHtml(totalPages)} 页 · 共 ${escapeHtml(total)} 条</span>
      <button class="mini-action history-page" type="button" data-page="${state.historyPage + 1}"${state.historyPage >= totalPages ? " disabled" : ""}>下一页</button>
    </div>
  `;
}

function renderBankrollTrend(runs) {
  const ordered = [...runs]
    .reverse()
    .filter((run) => Number.isFinite(Number(run.bankroll)) || Number.isFinite(Number(run.expectedBankroll)));
  const labels = ordered.map((run) => `#${run.id}`);
  const bankroll = ordered.map((run) => Number(run.bankroll ?? run.expectedBankroll ?? 0));
  const expected = ordered.map((run) => Number(run.expectedBankroll ?? run.bankroll ?? 0));
  const series = [
    { values: bankroll, color: "#f26a21" },
    { values: expected, color: "#7ca8ee" },
  ];
  renderLineChart("#portfolioTrendChart", labels, series, { baselineZero: false });
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
  renderMarketValidation(validation.marketValidation || {});
  const checks = (validation.checks || [])
    .filter((item) => !item.passed)
    .slice(0, 4)
    .map((item) => `${item.label}不足：${item.detail}`);
  const notes = [
    `样本 ${validation.eligibleSamples ?? 0} · 独立 ${validation.distinctFixtures ?? 0}`,
    ...checks,
    ...(validation.notes || []).slice(0, 2),
  ];
  document.querySelector("#validationNotes").innerHTML =
    notes.map((note) => `<li>${escapeHtml(note)}</li>`).join("");
}

function renderMarketValidation(markets) {
  const container = document.querySelector("#marketValidationGrid");
  if (!container) return;
  const ordered = ["1X2", "OU", "AH"]
    .map((key) => markets[key])
    .filter(Boolean);
  if (!ordered.length) {
    container.innerHTML = "";
    return;
  }
  container.innerHTML = ordered
    .map((item) => {
      const failed = (item.failedChecks || []).filter((check) => check && !check.passed);
      const ready = item.status === "ELIGIBLE_FOR_REVIEW" || item.status === "PAPER_READY";
      const split = item.split || {};
      const detail = failed[0]
        ? `${failed[0].label || "未通过"}：${failed[0].detail || "-"}`
        : item.note || "门槛正常";
      return `
        <div class="market-validation-card ${ready ? "ready" : "blocked"}">
          <strong>${escapeHtml(item.marketLabel || item.market || "-")}</strong>
          <b>${escapeHtml(item.statusLabel || "-")}</b>
          <span>样本 ${escapeHtml(item.samples ?? 0)} · 独立比赛 ${escapeHtml(item.distinctFixtures ?? 0)}</span>
          <span>校准 ${escapeHtml(split.calibration ?? "-")} · 验证 ${escapeHtml(split.validation ?? "-")}</span>
          <small>${escapeHtml(detail)}</small>
        </div>
      `;
    })
    .join("");
}

function renderLiveReadiness(readiness) {
  const status = document.querySelector("#liveReadinessStatus");
  const checks = document.querySelector("#liveReadinessChecks");
  if (!status || !checks) return;
  const canUseRealMoney = Boolean(readiness.canUseRealMoney);
  status.textContent = `${readiness.statusLabel || "实盘禁用"} · ${readiness.realMoneyLabel || "禁止真实下注"}`;
  status.classList.toggle("ready", canUseRealMoney);
  status.classList.toggle("blocked", !canUseRealMoney);
  const failed = (readiness.checks || []).filter((item) => !item.passed);
  const visible = (failed.length ? failed : (readiness.checks || [])).slice(0, 6);
  checks.innerHTML = visible.length
    ? visible
        .map(
          (item) => `
            <div class="readiness-check ${item.passed ? "passed" : "blocked"}">
              <strong>${escapeHtml(item.label || "-")}</strong>
              <span>${escapeHtml(item.actual || "-")} / ${escapeHtml(item.required || "-")}</span>
              <p>${escapeHtml(item.nextStep || "")}</p>
            </div>
          `,
        )
        .join("")
    : `<div class="panel-placeholder">暂无准入数据</div>`;
}

function numberValue(selector, fallback) {
  const value = Number.parseFloat(document.querySelector(selector).value);
  return Number.isFinite(value) ? value : fallback;
}

function defaultReviewDate() {
  const date = new Date();
  date.setDate(date.getDate() - 1);
  return date.toISOString().slice(0, 10);
}

function parseFixtureIds(value) {
  return Array.from(
    new Set(
      String(value || "")
        .replaceAll("，", ",")
        .split(/[\s,]+/)
        .map((item) => item.trim())
        .filter((item) => /^\d+$/.test(item)),
    ),
  );
}

function addBatchFixtureId(fixtureId) {
  if (!fixtureId) return;
  const fixtureIds = parseFixtureIds(batchFixtureIds.value);
  if (!fixtureIds.includes(String(fixtureId))) fixtureIds.push(String(fixtureId));
  batchFixtureIds.value = fixtureIds.join(", ");
  updateBatchButtonLabel();
}

function selectedBatchLimit() {
  const value = Number.parseInt(batchCount?.value, 10);
  if (!Number.isFinite(value)) return DEFAULT_BATCH_LIMIT;
  return Math.max(1, Math.min(MAX_BATCH_LIMIT, value));
}

function syncBatchLimitValue() {
  const limit = selectedBatchLimit();
  if (batchCount) batchCount.value = String(limit);
  return limit;
}

function updateBatchButtonLabel() {
  const fixtureIds = parseFixtureIds(batchFixtureIds.value);
  const batchLimit = selectedBatchLimit();
  batchToday.textContent = fixtureIds.length ? `分析指定 ${fixtureIds.length} 场` : `批量分析 ${batchLimit} 场`;
}

function formatPercent(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return `${(Number(value) * 100).toFixed(1)}%`;
}

function formatNumber(value, digits) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return Number(value).toFixed(digits);
}

function formatSignedNumber(value, digits) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  const number = Number(value);
  return `${number > 0 ? "+" : ""}${number.toFixed(digits)}`;
}

function formatMoney(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return `¥${Number(value).toFixed(2)}`;
}

function formatSignedMoney(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  const number = Number(value);
  if (Math.abs(number) < 0.005) return "¥0.00";
  return `${number > 0 ? "+" : "-"}¥${Math.abs(number).toFixed(2)}`;
}

function formatLine(value) {
  if (value == null || !Number.isFinite(Number(value))) return "-";
  return Number(value).toFixed(2).replace(/\.00$/, "").replace(/0$/, "");
}

function formatBatchEv(item) {
  if (item.evStatus === "SUSPENDED_MODEL_DIVERGENCE") return "已暂停";
  if (item.conservativeExpectedValue != null) return `纸上 ${formatPercent(item.conservativeExpectedValue)}`;
  if (item.expectedValue != null) return `研究 ${formatPercent(item.expectedValue)}`;
  return "-";
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

function renderMatchTitle(match) {
  return `
    <span class="match-team">${teamLabelHtml(match, "home")}</span>
    <span class="vs-token">VS</span>
    <span class="match-team">${teamLabelHtml(match, "away")}</span>
  `;
}

function teamLabel(match, side) {
  const zhKey = `${side}Zh`;
  return match?.[zhKey] || match?.[side] || "-";
}

function teamLabelWithFlag(match, side) {
  return teamLabel(match, side);
}

function teamLabelHtml(match, side) {
  return teamNameHtml(teamLabel(match, side), teamLogoFromMatch(match, side));
}

function teamPairHtml(home, away, homeLogo = "", awayLogo = "") {
  return `
    <span class="team-pair">
      ${teamNameHtml(home, homeLogo)}
      <span class="pair-vs">vs</span>
      ${teamNameHtml(away, awayLogo)}
    </span>
  `;
}

function teamNameHtml(name, logoUrl = "") {
  const label = String(name || "-");
  return `
    <span class="team-name">
      ${teamVisualHtml(label, logoUrl)}
      <span>${escapeHtml(label)}</span>
    </span>
  `;
}

function teamVisualHtml(name, logoUrl = "") {
  const label = String(name || "").trim();
  const fallback = teamInitial(label);
  const countryCode = countryCodeForTeam(label);
  if (countryCode) {
    return `
      <span class="team-visual team-flag" data-fallback="${escapeHtml(fallback)}">
        <img src="${escapeHtml(flagImageUrl(countryCode))}" alt="${escapeHtml(label)} 国旗" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('.team-visual').classList.add('is-missing')" />
      </span>
    `;
  }
  const safeLogoUrl = sanitizeTeamImageUrl(logoUrl);
  if (safeLogoUrl) {
    return `
      <span class="team-visual team-logo" data-fallback="${escapeHtml(fallback)}">
        <img src="${escapeHtml(safeLogoUrl)}" alt="${escapeHtml(label)} 标识" loading="lazy" referrerpolicy="no-referrer" onerror="this.closest('.team-visual').classList.add('is-missing')" />
      </span>
    `;
  }
  return `<span class="team-visual team-placeholder" aria-hidden="true">${escapeHtml(fallback)}</span>`;
}

function teamLogoFromMatch(match, side) {
  const camelKey = `${side}Logo`;
  const snakeKey = `${side}_logo`;
  const urlKey = `${side}LogoUrl`;
  return match?.[camelKey] || match?.[snakeKey] || match?.[urlKey] || "";
}

function sanitizeTeamImageUrl(value) {
  const url = String(value || "").trim();
  if (!url) return "";
  if (/^https?:\/\//i.test(url) || url.startsWith("/assets/") || url.startsWith("assets/")) return url;
  return "";
}

function flagImageUrl(countryCode) {
  return `https://flagcdn.com/${String(countryCode).toLowerCase()}.svg`;
}

function teamInitial(name) {
  const text = String(name || "").trim();
  if (!text || text === "-") return "?";
  const chars = Array.from(text.replace(/\s+/g, ""));
  return (chars[0] || "?").toUpperCase();
}

function flagForTeam(name) {
  return countryCodeForTeam(name);
}

function countryCodeForTeam(name) {
  const original = String(name || "").trim();
  if (!original || original === "-") return "";
  const normalizedOriginal = original
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "");
  const normalized = original
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/\s+(U\d+|Women|女足)$/i, "")
    .replace(/（.*?）/g, "")
    .trim()
    .toLowerCase();
  const aliases = {
    "mexico": "mx", "墨西哥": "mx",
    "south africa": "za", "南非": "za",
    "south korea": "kr", "korea republic": "kr", "韩国": "kr",
    "czech republic": "cz", "czechia": "cz", "捷克": "cz",
    "bolivia": "bo", "玻利维亚": "bo",
    "algeria": "dz", "阿尔及利亚": "dz",
    "england": "gb-eng", "英格兰": "gb-eng",
    "scotland": "gb-sct", "苏格兰": "gb-sct",
    "wales": "gb-wls", "威尔士": "gb-wls",
    "northern ireland": "gb-nir", "北爱尔兰": "gb-nir",
    "costa rica": "cr", "哥斯达黎加": "cr",
    "portugal": "pt", "葡萄牙": "pt",
    "nigeria": "ng", "尼日利亚": "ng",
    "iraq": "iq", "伊拉克": "iq",
    "venezuela": "ve", "委内瑞拉": "ve",
    "saudi arabia": "sa", "沙特阿拉伯": "sa",
    "senegal": "sn", "塞内加尔": "sn",
    "togo": "tg", "多哥": "tg",
    "benin": "bj", "贝宁": "bj",
    "azerbaijan": "az", "阿塞拜疆": "az",
    "san marino": "sm", "圣马力诺": "sm",
    "angola": "ao", "安哥拉": "ao",
    "central african republic": "cf", "中非共和国": "cf",
    "russia": "ru", "俄罗斯": "ru",
    "trinidad and tobago": "tt", "特立尼达和多巴哥": "tt",
    "austria": "at", "奥地利": "at",
    "netherlands": "nl", "holland": "nl", "荷兰": "nl",
    "guatemala": "gt", "危地马拉": "gt",
    "usa": "us", "united states": "us", "美国": "us",
    "canada": "ca", "加拿大": "ca",
    "luxembourg": "lu", "卢森堡": "lu",
    "kosovo": "xk", "科索沃": "xk",
    "saudi arabia": "sa", "沙特": "sa",
    "qatar": "qa", "卡塔尔": "qa",
    "japan": "jp", "日本": "jp",
    "china": "cn", "中国": "cn",
    "france": "fr", "法国": "fr",
    "germany": "de", "德国": "de",
    "italy": "it", "意大利": "it",
    "spain": "es", "西班牙": "es",
    "turkey": "tr", "turkiye": "tr", "土耳其": "tr",
    "switzerland": "ch", "瑞士": "ch",
    "curacao": "cw", "库拉索": "cw",
    "brazil": "br", "巴西": "br",
    "argentina": "ar", "阿根廷": "ar",
    "uruguay": "uy", "乌拉圭": "uy",
    "chile": "cl", "智利": "cl",
    "colombia": "co", "哥伦比亚": "co",
    "paraguay": "py", "巴拉圭": "py",
    "ecuador": "ec", "厄瓜多尔": "ec",
    "peru": "pe", "秘鲁": "pe",
    "morocco": "ma", "摩洛哥": "ma",
    "egypt": "eg", "埃及": "eg",
    "ghana": "gh", "加纳": "gh",
    "cameroon": "cm", "喀麦隆": "cm",
    "cote d'ivoire": "ci", "ivory coast": "ci", "科特迪瓦": "ci",
    "australia": "au", "澳大利亚": "au",
    "new zealand": "nz", "新西兰": "nz",
  };
  return aliases[normalized] || aliases[normalizedOriginal] || aliases[original] || "";
}

function actionLabel(action) {
  return {
    BUY: "模型候选",
    MODEL_CANDIDATE: "模型候选",
    PAPER_BUY: "纸上模拟",
    WATCH: "研究观察",
    RESEARCH_WATCH: "研究观察",
    SUSPENDED: "模拟暂停",
    NO_MARKET: "市场缺失",
  }[action] || action || "-";
}

function decisionLabel(status) {
  return {
    NO_VALUE: "无价值",
    RESEARCH_OBSERVATION: "研究观察",
    PAPER_OBSERVATION: "纸上模拟",
    HIGH_RISK_OBSERVATION: "高风险观察",
    MODEL_MARKET_CONFLICT: "模型市场冲突",
    SUSPENDED: "暂停",
    FORMAL_EV_DISABLED: "正式EV关闭",
    DISABLED_PFINAL_NOT_APPROVED: "pfinal未批准",
    RESEARCH_ONLY: "仅研究",
  }[status] || status || "-";
}

function historyActionClass(action) {
  if (action === "PAPER_BUY") return "buy";
  if (action === "BUY" || action === "MODEL_CANDIDATE") return "candidate";
  if (action === "SUSPENDED") return "suspended";
  if (action === "NO_MARKET") return "no-market";
  return "watch";
}

function legacySignalStatus(item) {
  if (["SUSPENDED_MODEL_DIVERGENCE", "MODEL_MARKET_CONFLICT", "SUSPENDED"].includes(item.ev_status)) return "SUSPENDED";
  if (item.action === "BUY") return "MODEL_CANDIDATE";
  if (item.action === "PAPER_BUY") return "PAPER_BUY";
  if (item.action === "NO_MARKET") return "NO_MARKET";
  return "RESEARCH_WATCH";
}

function responseError(data, fallback) {
  const error = new Error(data?.error || fallback);
  error.kind = data?.errorKind || "";
  error.retryable = Boolean(data?.retryable);
  return error;
}

function toChineseError(message) {
  if (message.includes("No upcoming head-to-head fixture")) {
    return "未找到未来交锋。请搜索赛程或填写比赛 ID。";
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
