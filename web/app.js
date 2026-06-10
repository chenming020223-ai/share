const state = {
  currentRunId: null,
  activeView: "workbenchView",
  batchResult: null,
  recentBatches: [],
  batchHistorySearch: "",
  batchHistoryPage: 1,
  batchHistoryPageSize: 5,
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
};

const form = document.querySelector("#predictForm");
const formError = document.querySelector("#formError");
const statusPill = document.querySelector("#statusPill");
const homeTeam = document.querySelector("#homeTeam");
const awayTeam = document.querySelector("#awayTeam");
const exportExcel = document.querySelector("#exportExcel");
const exportPdf = document.querySelector("#exportPdf");
const fixtureResults = document.querySelector("#fixtureResults");
const batchPoolContent = document.querySelector("#batchPoolContent");
const batchPoolStatus = document.querySelector("#batchPoolStatus");
const searchFixtures = document.querySelector("#searchFixtures");
const todayFirstDivision = document.querySelector("#todayFirstDivision");
const randomToday = document.querySelector("#randomToday");
const batchToday = document.querySelector("#batchToday");
const batchFixtureIds = document.querySelector("#batchFixtureIds");
const syncResults = document.querySelector("#syncResults");
const reviewDate = document.querySelector("#reviewDate");
const loadReview = document.querySelector("#loadReview");
const exportReviewExcel = document.querySelector("#exportReviewExcel");

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

batchToday.addEventListener("click", async () => {
  formError.textContent = "";
  const originalText = batchToday.textContent;
  const fixtureIds = parseFixtureIds(batchFixtureIds.value);
  batchToday.disabled = true;
  batchToday.textContent = "批量中";
  fixtureResults.innerHTML = `<div class="fixture-empty">${
    fixtureIds.length
      ? `正在批量分析指定的 ${fixtureIds.length} 场比赛...`
      : "正在批量分析北京时间今日甲级联赛前 5 场..."
  }</div>`;
  try {
    const response = await fetch("/api/batch-predict", {
      method: "POST",
      headers: { "content-type": "application/json" },
      body: JSON.stringify({
        ...buildPayload(),
        scope: "first_division",
        limit: fixtureIds.length || 5,
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
    batchToday.textContent = originalText;
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
    const ledgerSettled = data.paperLedger?.settledCount ?? 0;
    document.querySelector("#validationAction").textContent =
      `同步完成：新增 ${synced} 场赛果，等待完赛 ${awaiting} 场，模拟舱结算 ${ledgerSettled} 条。`;
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
  if (reviewDate) reviewDate.value = defaultReviewDate();
  loadHealth();
  loadModelValidation();
  loadLiveReadiness();
  loadHistory();
  loadRecentBatches();
  loadDailyReview();
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

async function loadLiveReadiness() {
  try {
    const response = await fetch("/api/live-readiness");
    const data = await response.json();
    renderLiveReadiness(data);
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
  renderLiveReadiness(data.liveReadiness || {});
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
        <div class="fixture-option fixture-card" data-fixture-id="${escapeHtml(item.fixtureId)}" data-home="${escapeHtml(home)}" data-away="${escapeHtml(away)}">
          <strong>${escapeHtml(title)}</strong>
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
          已选择 ${escapeHtml(title)}（比赛 ID ${escapeHtml(card.dataset.fixtureId || "-")}）。点击“生成赛前分析”继续。
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
  normalizeBatchFilters(collectedItems, failedItems);
  const filteredCollected = filterBatchCollected(collectedItems, plan);
  const filteredFailed = filterBatchFailed(failedItems);
  const visibleCount = filteredCollected.length + filteredFailed.length;
  const totalCount = summary.total ?? (collectedItems.length + failedItems.length);
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
      <div class="batch-pool-row ${plan.selectedRunIds?.includes(item.runId) ? "planned" : ""}">
        <div class="batch-main">
          <strong>${escapeHtml(`${item.home || "主队"} vs ${item.away || "客队"}`)}</strong>
          <span>运行 ${escapeHtml(item.runId)} · ID ${escapeHtml(item.fixtureId || "-")} · ${escapeHtml(item.league || "-")} · ${escapeHtml(item.kickoffBeijing || "-")}</span>
        </div>
        <span class="history-signal ${historyActionClass(item.signalStatus || item.recommendationAction)}">${escapeHtml(actionLabel(item.signalStatus || item.recommendationAction))}</span>
        <div class="batch-insights">
          <span><b>预测</b>${escapeHtml(item.predictionLabel || "-")} ${formatPercent(item.predictionProbability)}</span>
          <span><b>模拟舱</b>${escapeHtml(item.recommendationSummary || "-")}</span>
          <span><b>质量</b>${escapeHtml(item.qualityLabel || "-")} · 盘口 ${escapeHtml(item.availableMarkets ?? 0)}/${escapeHtml(item.totalMarkets ?? 0)}</span>
          <span><b>EV</b>${formatBatchEv(item)}</span>
          <span><b>资金</b>占用 ${formatMoney(item.totalStake)} · 期望 ${formatMoney(item.expectedBankroll)}</span>
          <span><b>庄家</b>${escapeHtml(formatBookmakerSummary(item))}</span>
        </div>
        <p class="batch-reason">${escapeHtml(item.recommendationReason || item.gateLabel || "等待进一步复核。")}</p>
        <div class="batch-actions">
          <button class="mini-action open-run" type="button" data-run-id="${escapeHtml(item.runId)}">查看单场</button>
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
          <strong>${escapeHtml(`${item.home || "主队"} vs ${item.away || "客队"}`)}</strong>
          <span>ID ${escapeHtml(item.fixtureId || "-")} · ${escapeHtml(item.league || "-")} · ${escapeHtml(item.kickoffBeijing || "-")}</span>
        </div>
        <span class="history-signal no-market">${escapeHtml(item.failureLabel || "失败")}</span>
        <p class="batch-reason">${escapeHtml(item.error || "失败")}</p>
      </div>
    `)
    .join("");
  const contentHtml = `
    <div class="fixture-empty batch-result-intro">
      <span>
        ${escapeHtml(current.message || "批量分析完成")} ${current.fixtureIds?.length ? `指定 ID ${escapeHtml(current.fixtureIds.join("、"))}。` : ""}逻辑请求 ${escapeHtml(request.logical ?? 0)}，HTTP ${escapeHtml(request.httpAttempts ?? 0)}，缓存命中 ${escapeHtml(request.cacheHits ?? 0)}。
        <br>${escapeHtml(summary.bankrollMode || "批量总览仅用于研究排序。")}
      </span>
      <button class="mini-action show-batch-history" type="button">查看历史批次</button>
      ${current.batchRunId ? `<button class="mini-action mark-current-official" type="button" data-batch-id="${escapeHtml(current.batchRunId)}" data-date="${escapeHtml(current.date || "")}">设为官方批次</button>` : ""}
    </div>
    <div class="batch-summary-grid">${summaryCards}</div>
    ${renderBatchControls(collectedItems, failedItems)}
    ${renderBatchPortfolioPlan(plan)}
    ${rows || (filteredFailed.length ? "" : `<div class="fixture-empty">当前筛选条件下没有匹配的成功比赛。</div>`)}
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
        批量赛事池已生成：成功 ${escapeHtml(summary.success ?? 0)} 场，信号 ${escapeHtml(summary.signalCount ?? 0)} 个，失败 ${escapeHtml(summary.failed ?? 0)} 场。请打开“批量赛事池”查看筛选、排序和组合预案。
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

async function loadPredictionRun(runId) {
  if (!runId) return;
  formError.textContent = "";
  try {
    const response = await fetch(`/api/prediction?run_id=${encodeURIComponent(runId)}`);
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取单场记录失败");
    renderPrediction(data);
    setActiveView("workbenchView");
  } catch (error) {
    formError.textContent = toChineseError(error.message);
  }
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
  const unit = portfolio.suggested_unit_stake ?? portfolio.unit_stake;
  const cash = portfolio.cash ?? portfolio.bankroll;
  document.querySelector("#portfolioSummary").textContent =
    `资金 ${formatMoney(portfolio.bankroll)} · 现金 ${formatMoney(cash)} · 单注 ${formatMoney(unit)} · 占用 ${formatMoney(portfolio.total_stake)} · 期望 ${formatMoney(portfolio.expected_bankroll)}`;
}

function renderRecommendations(items) {
  document.querySelector("#recommendations").innerHTML = items
    .map((item) => {
      const signalStatus = item.signal_status || legacySignalStatus(item);
      const suspended =
        signalStatus === "SUSPENDED" ||
        ["SUSPENDED_MODEL_DIVERGENCE", "MODEL_MARKET_CONFLICT", "SUSPENDED"].includes(item.ev_status);
      const actionClass = historyActionClass(signalStatus);
      const displayAction = item.publicActionLabel || actionLabel(item.publicAction || signalStatus);
      const researchEv = suspended ? null : item.ev_pbase_research ?? item.audit_expected_value_per_unit ?? item.expected_value_per_unit;
      const paperEv = suspended
        ? null
        : item.paper_expected_value_per_unit ??
          item.ev_pshr_candidate ??
          item.conservative_ev_pbase_research ??
          item.audit_paper_expected_value_per_unit ??
          item.audit_conservative_expected_value_per_unit ??
          item.conservative_expected_value_per_unit;
      const formalEv = item.ev_pfinal_exec;
      const scoreResearchOnly = item.ev_calculation?.evDecisionLayer === "research_audit_only";
      const pAdj = item.adjusted_probability;
      const shrinkK = item.shrink_k;
      const decisionStatus = item.decision_status || item.ev_status || signalStatus;
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
          <span class="action ${actionClass}">${escapeHtml(displayAction)}</span>
          <div class="rec-metrics">
            <span>赔率 <strong>${item.odds == null ? "-" : formatNumber(item.odds, 2)}</strong></span>
            <span>${escapeHtml(probabilityLabel)} <strong>${formatPercent(item.model_probability)}</strong></span>
            <span>${escapeHtml(marketProbabilityLabel)} <strong>${item.market_probability == null ? "-" : formatPercent(item.market_probability)}</strong></span>
            <span>模型-市场差 <strong class="${gapClass}">${probabilityGap == null ? "-" : formatPercent(probabilityGap)}</strong></span>
            <span>p_adj <strong>${scoreResearchOnly ? "未开放" : pAdj == null ? "-" : formatPercent(pAdj)}</strong></span>
            <span>shrink_k <strong>${scoreResearchOnly ? "未开放" : shrinkK == null ? "-" : formatNumber(shrinkK, 2)}</strong></span>
            <span>研究EV(pbase) <strong>${suspended ? "已暂停" : researchEv == null ? "-" : formatPercent(researchEv)}</strong></span>
            <span>纸上EV(p_adj) <strong>${suspended ? "已暂停" : scoreResearchOnly ? "未开放" : paperEv == null ? "-" : formatPercent(paperEv)}</strong></span>
            <span>正式EV(pfinal) <strong>${formalEv == null ? "未开放" : formatPercent(formalEv)}</strong></span>
            <span>决策状态 <strong>${escapeHtml(decisionLabel(decisionStatus))}</strong></span>
          </div>
          ${renderEvCalculation(item.ev_calculation, suspended, signalStatus)}
          <p class="rec-reason">${escapeHtml(item.reason || "")}</p>
        </div>
      `;
    })
    .join("");
}

function renderEvCalculation(calc, suspended, signalStatus) {
  if (suspended) {
    return `
      <div class="ev-path ev-suspended">
        <strong>EV 路径已暂停</strong>
        <span>${signalStatus === "SUSPENDED" ? "数据质量、近期样本或模型分歧未通过闸门，本场不允许进入模拟资金。" : "基础模型与市场基准分歧超限，本场不允许进入模拟资金。"}</span>
      </div>
    `;
  }
  if (!calc || !calc.formula) return "";

  const formula = calc.type === "1X2"
    ? `${formatPercent(calc.modelProbability)} × ${formatNumber(calc.odds, 2)} - 1 = ${formatPercent(calc.expectedValue)}`
    : `${formatNumber(calc.winStakeFraction, 3)} × (${formatNumber(calc.odds, 2)} - 1) - ${formatNumber(calc.lossStakeFraction, 3)} = ${formatPercent(calc.expectedValue)}`;
  const paperLine = calc.evDecisionLayer === "research_audit_only"
    ? `<div class="ev-line"><strong>纸上EV</strong><span>${escapeHtml(calc.paperFormula || "比分分布层未完成独立校准，paper_EV 暂不开放。")}</span></div>`
    : calc.paperExpectedValue == null
    ? ""
    : `<div class="ev-line"><strong>纸上EV</strong><span>p_adj ${formatPercent(calc.adjustedProbability)}，shrink_k ${formatNumber(calc.shrinkK, 2)}；${escapeHtml(calc.paperFormula || "paper_EV = p_adj × odds - 1")}；结果 ${formatPercent(calc.paperExpectedValue)}</span></div>`;
  const expanded = calc.type === "1X2"
    ? `展开：(${formatNumber(calc.odds, 2)} - 1) × ${formatPercent(calc.modelProbability)} - ${formatPercent(calc.lossStakeFraction)}`
    : `盈亏权重：正收益概率 ${formatPercent(calc.positiveReturnProbability)}，盈利注权重 ${formatNumber(calc.winStakeFraction, 3)}，亏损注权重 ${formatNumber(calc.lossStakeFraction, 3)}，盈亏平衡赔率 ${calc.breakEvenOdds == null ? "-" : formatNumber(calc.breakEvenOdds, 2)}`;
  const settlement = calc.settlement
    ? `
      <div class="settlement-grid">
        <span>全赢 ${formatPercent(calc.settlement.fullWinProbability)}</span>
        <span>半赢 ${formatPercent(calc.settlement.halfWinProbability)}</span>
        <span>走水 ${formatPercent(calc.settlement.pushProbability)}</span>
        <span>半输 ${formatPercent(calc.settlement.halfLossProbability)}</span>
        <span>全输 ${formatPercent(calc.settlement.fullLossProbability)}</span>
      </div>
    `
    : "";
  const gates = (calc.gates || [])
    .map((gate) => `
      <span class="gate-pill ${gate.passed ? "pass" : "fail"}">
        ${escapeHtml(gate.label)} ${gate.passed ? "通过" : "未过"}
      </span>
    `)
    .join("");

  return `
    <div class="ev-path">
      <div class="ev-line"><strong>研究EV</strong><span>${escapeHtml(calc.formula)}；${escapeHtml(formula)}</span></div>
      ${paperLine}
      <div class="ev-line"><strong>复核</strong><span>${escapeHtml(expanded)}；P_display 不参与 EV，formal_EV 当前未开放。</span></div>
      ${settlement}
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
    renderLineChart("#portfolioTrendChart", [], []);
    document.querySelector("#homeRecentTable").innerHTML = `<div class="panel-placeholder">等待真实数据</div>`;
    document.querySelector("#awayRecentTable").innerHTML = `<div class="panel-placeholder">等待真实数据</div>`;
    document.querySelector("#oddsTrendNotice").textContent = "生成分析后检查是否具备多个赛前赔率快照。";
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
    processing.oddsTrend?.message || "当前缺少可验证的连续赔率快照。";
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
  if (status) status.textContent = "正在读取复盘";
  try {
    const response = await fetch(`/api/daily-review?date=${encodeURIComponent(date)}`);
    const data = await response.json();
    if (!response.ok) throw responseError(data, "读取复盘失败");
    state.dailyReview = data;
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
    container.innerHTML = `<div class="panel-placeholder">暂无已结算大小球/让球候选。同步赛果后会按盘口线统计。</div>`;
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
    container.innerHTML = `<div class="panel-placeholder">暂无比分分布审计。同步赛果后会重建 pbase 比分矩阵。</div>`;
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
    ${scoreList || `<div class="panel-placeholder">暂无比分偏差样本。</div>`}
    <div class="review-row score-market header"><span>盘口归因</span><span>赢亏权重</span><span>正收益概率</span><span>实际盈亏</span></div>
    ${marketList || `<div class="panel-placeholder">暂无盘口归因样本。</div>`}
  `;
}

function renderReviewBankroll(timeline) {
  const summary = timeline.summary || {};
  const events = timeline.events || [];
  document.querySelector("#reviewBankrollStatus").textContent =
    `现金 ${formatMoney(summary.cash)} · 预留 ${formatMoney(summary.reservedStake)} · ${escapeHtml(summary.riskLabel || "正常")}`;
  const container = document.querySelector("#reviewBankroll");
  if (!events.length) {
    container.innerHTML = `<div class="panel-placeholder">暂无纸上观察资金事件。正式 EV 未开放时这里保持空账本，是正常状态。</div>`;
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
    container.innerHTML = `<div class="panel-placeholder">暂无高 EV 异常。后续同步赛果后，会按市场、赔率区间和模型分歧自动归因。</div>`;
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
    container.innerHTML = `<div class="panel-placeholder">暂无已结算比赛。先同步赛果后再复盘。</div>`;
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
    container.innerHTML = `<div class="panel-placeholder">暂无已结算 EV 候选。同步赛果后会显示高 EV 是否失真。</div>`;
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
    container.innerHTML = `<div class="panel-placeholder">当前复盘日期没有待结算比赛。</div>`;
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
  } catch {
    document.querySelector("#historyList").innerHTML = `<div class="panel-placeholder">本地记录读取失败</div>`;
    renderBankrollTrend([]);
  }
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
    batchPoolContent.innerHTML = `<div class="panel-placeholder">暂无批量批次。完成一次批量分析后，这里会保存批次并支持恢复。</div>`;
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
    <div class="fixture-empty">批次历史从本地数据库读取，恢复和编辑名称备注都不消耗 API 请求。</div>
    ${
      pageItems.length
        ? `<div class="history-list batch-history-list">${pageItems.map(renderBatchHistoryItem).join("")}</div>`
        : `<div class="panel-placeholder">没有匹配的批次。可以换一个关键词，或清空搜索。</div>`
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
      <div class="batch-edit-grid">
        <label>
          <span>批次名称</span>
          <input class="batch-title-input" value="${escapeHtml(batch.title || "")}" placeholder="例如：0603 今日甲级五场">
        </label>
        <label>
          <span>备注</span>
          <textarea class="batch-notes-input" rows="2" placeholder="记录筛选条件、异常盘口或复盘结论">${escapeHtml(batch.notes || "")}</textarea>
        </label>
      </div>
      <div class="history-actions">
        <button class="mini-action save-batch-meta" type="button" data-batch-id="${escapeHtml(batch.id)}">保存名称备注</button>
        <button class="mini-action mark-official-batch" type="button" data-batch-id="${escapeHtml(batch.id)}" data-date="${escapeHtml(batch.date || batch.officialDate || "")}">${batch.isOfficial ? "已是官方" : "设为官方批次"}</button>
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

function renderHistory(runs) {
  if (!runs.length) {
    document.querySelector("#historyList").innerHTML = `<div class="panel-placeholder">暂无预测记录</div>`;
    return;
  }
  document.querySelector("#historyList").innerHTML = runs
    .map((run) => `
      <div class="history-item">
        <div class="history-main">
          <strong>${escapeHtml(`${run.homeZh || "主队"} vs ${run.awayZh || "客队"}`)}</strong>
          <span class="muted">运行 ${escapeHtml(run.id)} · ${escapeHtml(run.leagueZh || "-")} · ${escapeHtml(run.kickoffBeijing || run.created_at || "-")}</span>
        </div>
        <div class="history-insights">
          <span><b>预测</b>${escapeHtml(run.predictionLabel || "-")} ${formatPercent(run.predictionProbability)}</span>
          <span><b>模拟舱</b>${escapeHtml(run.recommendationSummary || "-")}</span>
          <span><b>资金</b>${formatMoney(run.bankroll)} → ${formatMoney(run.expectedBankroll)}</span>
          <span><b>质量</b>${escapeHtml(run.qualityLabel || "-")} · 庄家 ${escapeHtml(run.bookmaker || "未取得")}</span>
        </div>
        <div class="history-actions">
          <span class="history-signal ${historyActionClass(run.signalStatus || run.recommendationAction)}">${escapeHtml(actionLabel(run.signalStatus || run.recommendationAction))}</span>
          <a class="history-link" href="/api/report?format=xlsx&amp;run_id=${encodeURIComponent(run.id)}">Excel</a>
          <a class="history-link" href="/api/report?format=pdf&amp;run_id=${encodeURIComponent(run.id)}">PDF</a>
        </div>
      </div>
    `)
    .join("");
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
  renderLineChart("#historyBankrollChart", labels, series, { baselineZero: false });
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
    : `<div class="panel-placeholder">暂无实盘准入数据。</div>`;
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

function teamLabel(match, side) {
  const zhKey = `${side}Zh`;
  return match?.[zhKey] || match?.[side] || "-";
}

function actionLabel(action) {
  return {
    BUY: "模型候选",
    MODEL_CANDIDATE: "模型候选",
    PAPER_BUY: "纸上观察",
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
    PAPER_OBSERVATION: "纸上观察",
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
