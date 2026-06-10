# 深度研究方案吸收计划

日期：2026-06-04  
来源：`/Users/hcm/Desktop/世界杯预测项目深度研究与可落地改造方案.pdf`  
目标：把深度研究报告转换为当前项目可执行的改造路径。

## 1. 总体判断

这份 PDF 与当前项目审查结论高度一致：项目可以继续交付为“足球预测研究 + 纸上模拟舱 + 赛后审计系统”，但不能交付为“已验证正期望正式执行系统”。

报告最有价值的地方不是提出更复杂模型，而是把下一阶段主线讲清楚：

```text
同庄家、同盘口、同时间点、可回测、可校准、可审计
```

这正好对应当前项目最大的短板：EV 已经能算，但概率对象和资金路径还没有达到正式审批级别。

## 2. 可立即吸收的内容

### 2.1 EV 字段重命名和分层

当前项目已有研究 EV，但字段和页面语义仍容易让用户误以为接近正式买入。应吸收 PDF 建议，把 EV 明确拆成四层：

| 字段 | 含义 | 当前状态 |
|---|---|---|
| `ev_pbase_research` | 基于基础模型 `pbase` 的研究 EV | 立即落地 |
| `ev_qmkt_anchor` | 市场锚定口径下的参考 EV | 下一步设计 |
| `ev_pshr_candidate` | 校准候选概率下的候选 EV | 样本累计后落地 |
| `ev_pfinal_exec` | 通过审批的正式执行 EV | 当前必须为空 |

落地要求：

- 页面、报告、复盘中不能只显示“EV”。
- 未审批前所有 EV 都必须带 `research/candidate` 身份。
- `ev_pfinal_exec` 只有 `pfinal_status=approved` 后才能生成。

### 2.2 模拟舱状态机

吸收 PDF 中的五状态建议：

| 状态 | 含义 | 是否占用资金 |
|---|---|---:|
| `MODEL_CANDIDATE` | 模型看到差异，仅候选 | 否 |
| `RESEARCH_WATCH` | 研究观察 | 否 |
| `PAPER_BUY` | 正式纸上买入 | 是 |
| `NO_MARKET` | 市场缺失 | 否 |
| `SUSPENDED` | 分歧、质量、样本、风控暂停 | 否 |

当前项目已有 `BUY/PAPER_BUY/WATCH/NO_MARKET/SUSPENDED_MODEL_DIVERGENCE`，但语义还不够干净。下一步应做兼容迁移：旧字段保留，新增标准状态字段。

### 2.3 资金账本 V2

当前 `bankroll.py` 已有五等分和盈利 50% 再投入的雏形，但 PDF 提出的“现金余额”和“可定注风险本金”分离更严谨，应吸收：

```text
initial_bankroll = 1000
realized_pnl_t      = 已结算累计盈亏
reserved_stake_t    = 未结算占用资金
cash_t              = initial_bankroll + realized_pnl_t - reserved_stake_t
staking_bankroll_t  = initial_bankroll + min(realized_pnl_t, 0) + 0.5 * max(realized_pnl_t, 0)
base_unit_t         = min(cash_t, staking_bankroll_t) / 5
```

必须增加的硬风控：

- 单场总暴露 <= 当前可用资金 40%
- 单日总暴露 <= 当前可用资金 60%
- 单市场类型暴露 <= 当前可用资金 25%
- 同联赛暴露 <= 当前可用资金 30%
- 长赔率冷门暴露 <= 当前可用资金 10%
- 连续亏损 3 笔后 5 笔注额乘数降到 0.6
- 连续亏损 5 笔后 5 笔注额乘数降到 0.4，并暂停长赔率冷门
- 峰值回撤 >= 20% 暂停新 `PAPER_BUY`
- 峰值回撤 >= 25% 进入人工复核状态

### 2.4 按时间线驱动批量模拟

当前批量分析已经能保存批次和复盘，但资金层仍偏“结果汇总”。应吸收 PDF 的事件流设计：

```text
events = kickoff / settlement / rebalance
按 event_ts 排序
开赛前预留 stake
赛果同步后结算 pnl
日初或触发条件下重算 base_unit
```

这会解决多场同时分析时，模拟舱资金曲线不真实的问题。

### 2.5 页面审计模块

应把以下模块升为一级页面或重点卡片：

- 概率审计：`pbase/qmkt/pshr/pfinal_candidate/pfinal_status`
- EV 分解：`ev_pbase_research/ev_pshr_candidate/ev_pfinal_exec`
- 模型分歧原因：`divergence_score/longshot_penalty/q_data/q_league`
- 模拟舱资金曲线：现金、预留资金、权益、回撤、连亏状态
- 赛后复盘归因：亏损来自概率、盘口、长赔率、质量、分歧还是数据缺失
- 高 EV 异常列表：默认作为风险审计，不作为买入推荐

## 3. 需要验证后再吸收的内容

### 3.1 市场锚定 DC-lite 比分分布

PDF 建议采用“市场锚定的 DC-lite”：

```text
P_base(g_h, g_a) = 基础模型比分分布
P_mkt(g_h, g_a)  = 同庄家市场锚定比分分布
P_shr ∝ P_mkt^α × P_base^β
```

这是正确方向，但不能一次性硬上生产。建议先做离线候选模块：

- 先保存 `score_distributions` 表。
- 先在报告中展示 `pbase_score_matrix` 和 `market_anchor_score_matrix`。
- 只做回测，不影响当前页面正式输出。

### 3.2 Power devig

PDF 建议 1X2 去水从简单 proportional normalization 升级到 Power method，以更好处理 favorite-longshot bias。可以作为 P1 实验：

- 先保留现有去水结果。
- 新增 `devig_method` 字段。
- 同时计算 `proportional` 和 `power` 两版。
- 用 OOT 验证决定默认方法，不直接替换。

### 3.3 Dirichlet calibration

Dirichlet calibration 适合多分类校准，但当前样本太少，不宜立即启用。应放在：

- 胜平负 >= 300 场独立已结算样本；
- OOT 验证窗口 >= 100 场；
- 校准样本中主胜/平/客胜分布都有基本支持。

## 4. 暂不建议现在做的内容

| 内容 | 暂不做原因 |
|---|---|
| xG 作为主模型 | API-Football 覆盖和口径不稳定，样本不足时容易引入偏差 |
| 负二项主模型 | 参数更多，当前样本量不足，方差风险高 |
| OO-EPC / FL-GLM | 方法较新，可做离线基准，不适合立刻生产默认 |
| 正式 CLV 审批 | 需要同庄家、同盘口线、同 side、可比较收盘赔率，当前字段还不完整 |
| 正式 BUY 开放 | `pfinal` 未审批，EV 候选复盘仍为负 |

## 5. 当前项目与 PDF 的差距

### 已具备

- API 快照。
- 结构化盘口报价。
- 赛果同步。
- 研究 EV。
- 亚洲盘拆分结算。
- 批量赛事池。
- 赛后复盘。
- 模拟舱账本基础。

### 缺失或不足

- `research_ev_pbase` 等 EV 身份字段未标准化。
- `pfinal_candidate` 尚未形成。
- `score_distributions` 表未独立。
- 收盘赔率字段缺失。
- CLV 可比性字段缺失。
- 批量模拟资金还不是完整时间线账本。
- 同联赛、同市场、长赔率冷门暴露上限未落地。
- 高 EV 异常没有独立一级审计页。

## 6. 建议下一阶段 P0 执行项

### P0-1：EV 身份治理

目标：阻断“研究 EV 被误读为正式 EV”。

落地：

- 增加标准字段 `ev_pbase_research`。
- 当前 `expected_value_per_unit` 保留兼容，但页面优先显示新字段。
- 新增 `ev_layer`、`probability_used`、`signal_status`。
- 报告中把“EV”改成“研究 EV / 候选 EV / 正式 EV”。

验收：

- `pfinal_status != approved` 时，`ev_pfinal_exec` 必须为空。
- 页面不得出现裸露的“买入 EV”。

### P0-2：模拟舱状态机

目标：把 `WATCH/BUY/PAPER_BUY` 的语义清理干净。

落地：

- 新增 `signal_status`。
- 映射旧 action：
  - `NO_MARKET -> NO_MARKET`
  - `SUSPENDED_MODEL_DIVERGENCE -> SUSPENDED`
  - 未审批候选 -> `RESEARCH_WATCH`
  - 审批后才允许 `PAPER_BUY`

验收：

- 当前正式 EV 关闭时，所有 API 模式信号最多只能到 `RESEARCH_WATCH`。
- 模拟资金占用保持 0。

### P0-3：资金账本 V2

目标：从“静态资金摘要”升级为“事件驱动账本”。

落地：

- 增加 `bankroll_events` 或扩展 `paper_bankroll_ledger`。
- 记录 `cash_before/after`、`reserved_before/after`、`staking_bankroll`、`drawdown_pct`、`risk_mode`。
- 批量结果按开赛时间生成模拟事件。

验收：

- 多场同日分析能生成资金曲线。
- 未结算比赛占用 reserved，不直接影响 realized pnl。
- 赛果同步后更新权益和回撤。

### P0-4：高 EV 异常审计

目标：把“高 EV 冷门亏损”变成可解释问题，而不是人工感觉。

落地：

- 新增高 EV 异常表或复盘分组。
- 字段包括 `odds_bucket`、`divergence_score`、`q_data`、`q_league`、`longshot_flag`、`actual_net`。
- 页面新增“高 EV 异常”列表。

验收：

- 能按赔率区间、市场、联赛、分歧程度查看亏损集中点。

## 7. 建议 P1 执行项

1. 新增 `score_distributions` 表。
2. 实现市场锚定比分分布候选。
3. 实现 Power devig 离线对照。
4. 实现大小球线别校准回测。
5. 实现让球净胜球 CDF 回测。
6. 增加收盘赔率字段和 CLV 可比性字段。

## 8. 建议 P2 执行项

1. Dixon-Coles 低比分修正。
2. Dirichlet 多分类校准。
3. xG 作为辅助特征而非主模型。
4. 更复杂赔率去水方法离线 benchmark。
5. 线上分享版或打包下载版。

## 9. 我的执行建议

下一步不建议直接改模型核心公式，而应先执行 P0：

```text
EV 身份治理
→ 模拟舱状态机
→ 资金账本 V2
→ 高 EV 异常审计
```

原因：

- 这些改造不会制造新的“假正期望”。
- 能直接提升甲方可读性和交付可信度。
- 能为后续 `pfinal`、CLV、大小球/让球专项校准打基础。
- 风险低，收益高。

