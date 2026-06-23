# 模型吸收规范 V1

日期：2026-05-26  
状态：执行基线  
适用范围：API 预测、模拟舱、中文 Excel/PDF 报告、后续历史回测  
预测口径：仅计算 90 分钟赛果

## 1. 本次吸收结论

本规范依据当前项目代码、桌面 `程序1.0` 原型、`预测/数据` 工作簿、`Football` 架构代码及导师 V3.2 资料形成。

本项目吸收以下原则：

1. 赛前快照、统一庄家、同盘口线结算和完整审计链必须保留。
2. 基础模型概率不能直接作为正式模拟信号的概率输入。
3. 赔率去水概率是市场基准，不等于模型优势，也不直接产生信号。
4. 让球与大小球必须先按比分矩阵完成走水、半赢、半输和拆半注结算，再计算研究试算 EV。
5. `No Bet` / `观望` 是正式允许结果；未完成概率校准前，不占用模拟资金。

本项目不直接复制以下内容：

1. `程序1.0` 中以原始泊松概率直接触发正 EV 的逻辑。
2. 表格中无法复算的人工校准概率或权重。
3. 导师 V3.2 尚未冻结的校准、最终概率和资金管理公式。

## 2. 概率对象口径

正式采用四层概率概念，并与当前 MVP 字段建立对应关系：

| 正式概念 | 定义 | 当前程序对应 | 是否允许进入正式 EV |
|---|---|---|---:|
| `pbase` | 基于球队数据和比分矩阵的基础概率 | 当前 `model_probabilities` | 否 |
| `qmkt` | 优先庄家赔率去水后的市场概率 | 当前 `market_probabilities` | 否 |
| `pshr` | 用独立校准集验证的候选校准概率 | 时间切分审计管道已实现，当前采用胜平负类别偏差校准候选公式 | 否 |
| `pfinal` | 通过最终准入和回测门槛的执行概率 | 尚未实现 | 是 |

当前程序中的 `final_probabilities` 是以手工市场权重形成的展示融合概率，只用于展示和比较，不得解释为已验证的 `pfinal`。

## 3. 当前可执行公式

### 3.0 pbase 输入层校正

`pbase` 仍然是独立基础模型概率，不使用市场赔率作为输入。为修复短期样本导致的强弱误判，API 模式先执行两步输入校正：

1. 双方近 10 场有效 90 分钟比赛按时间衰减和对手强度校正：对强队进球/拿分升权，对弱队刷进球/拿分降权，被弱队进球惩罚更大。
2. 国家队、青年队和友谊赛等高噪声场景与内部球队强度先验融合。当前友谊赛近期样本权重为 `15%`，U21/U20/U23 为 `25%`，深度/批量常规模式为 `45%`。

该校正只修复 `pbase` 的球队画像输入，不代表已经完成 `pshr/pfinal` 校准，也不能绕过正式 EV 闸门。

### 3.1 市场去水概率 `qmkt`

对于同一优先庄家、同一市场、同一盘口线的十进制赔率 `O_i`：

```text
r_i = 1 / O_i
qmkt_i = r_i / sum(r_j)
```

胜平负必须同时具备主胜、平局、客胜三项赔率。大小球和让球必须具备同盘口线两侧完整赔率。

### 3.2 研究试算 EV

胜平负的研究试算 EV 可按以下公式计算：

```text
research_EV = pbase_i * O_i - 1
```

大小球和让球的研究试算 EV 必须使用比分矩阵的结算期望：

```text
research_EV = sum(P_score(s) * net_return(s, line, odds))
```

其中 `net_return` 必须正确处理全赢、走水、全输及 `0.25/0.75` 分段线的半赢/半输。

大小球和让球在研究层增加比分分布独立校准因子，按已结算赛前快照分别统计市场方向：

```text
positive_factor_side = shrink_to_1(actual_positive_rate_side / model_positive_rate_side, credibility)
win_factor_side      = shrink_to_1(actual_win_fraction_side / model_win_fraction_side, credibility)
loss_factor_side     = shrink_to_1(actual_loss_fraction_side / model_loss_fraction_side, credibility)

calibrated_win_fraction  = raw_win_fraction * win_factor_side
calibrated_loss_fraction = raw_loss_fraction * loss_factor_side
research_EV_score_calibrated = calibrated_win_fraction * (odds - 1) - calibrated_loss_fraction
```

其中 `credibility = min(1, side_sample_count / min_side_samples)`，样本不足时因子自动收缩到 `1.00`；同一场、同一市场、同一盘口、同一方向只保留最早赛前快照，避免重复分析放大样本。每个市场再按开赛时间切分校准集与验证集，校准集拟合方向因子，验证集只评估正收益 Brier 与 EV 误差，不反向调参。

当前比分分布专项校准为分市场状态，实际可用性以 `/api/model-validation` 的实时验收结果为准。只有状态为 `PAPER_READY` 的市场才允许应用校准因子并显示 `paper_EV` 纸上复核候选；状态为 `REJECTED` 或 `INSUFFICIENT_DATA` 的市场不应用失败校准因子，只输出原始 `research_EV` 和逐比分结算审计。`formal_EV` 仍必须等待 `pfinal` 人工审批和正式资金策略验收，比分分布市场不进入正式资金。

研究试算 EV 仅用于诊断基础模型与市场的分歧，在 `pfinal` 可用前不得触发正式模拟信号。若当前胜平负市场基准中任一方向的 `pbase` 与 `qmkt` 绝对差异达到冲突线，胜平负研究 EV 暂停主展示；大小球和让球只记录跨市场风险标签，仍按各自盘口去水概率、比分分布专项校准、数据质量和本市场分歧独立判断，避免胜平负异常一刀切误伤比分分布市场。

### 3.3 正式 EV

正式 EV 的概率输入固定为 `pfinal`：

```text
formal_EV = expected_net_return(pfinal, settlement_object, executable_odds)
```

当前 `pshr` 时间切分审计流程已经实现。新版候选公式不再直接把 20 场校准样本拟合出的市场收缩权重作为执行概率，而是使用校准区间估计主胜、平局、客胜的类别偏差因子：

```text
actual_rate_k = count(actual = k) / N_cal
pred_rate_k   = mean(pbase_k)
target_rate_k = (actual_rate_k * N_cal + pred_rate_k * prior_samples) / (N_cal + prior_samples)
factor_k      = clamp(target_rate_k / pred_rate_k, min_factor, max_factor)

pshr_k = normalize(pbase_k * factor_k)
```

其中当前 `prior_samples = 20`，`factor_k` 会被限制在 `[0.75, 1.35]`，避免短样本把概率拉爆。校准区间拟合出的原始市场收缩权重仍作为审计字段保存，但不直接作为新版 `pshr` 执行权重。`pfinal` 尚未完成最终人工审批，因此正式 EV 状态仍为“未启用”。

## 4. 市场键和审计字段

每一条进入分析或报告的市场对象必须可由以下字段追溯：

| 字段 | 要求 |
|---|---|
| `fixture_id` | API-Football 比赛 ID |
| `snapshot_id` | 本次抓取和预测快照 ID |
| `market_type` | `1X2` / `OU` / `AH` |
| `line` | 盘口线；`1X2` 为空值 |
| `selection_scope` | 主胜/平/客胜、大/小、主让/客受让等具体方向 |
| `bookmaker` | 正式 API 模式记录实际使用庄家，默认优先级为 `Pinnacle > Bet365 > Betfair > SBO > 10Bet > 1xBet` |
| `captured_at` | 真实赔率抓取或更新时间 |
| `model_version` | 计算所使用的模型版本 |

后续完整键规范采用：

```text
market_family_key = fixture_id + snapshot_id + market_type
market_line_key   = fixture_id + snapshot_id + market_type + line
selection_key     = fixture_id + snapshot_id + market_type + line + selection_scope
```

## 5. 模拟舱当前准入规则

现有盘口、数据质量和纸上 EV 校验继续保留，但增加概率治理硬门槛：

| 校验 | 当前状态 |
|---|---|
| 优先庄家全场盘口完整 | 已实现 |
| 双方各至少 5 场有效近期比赛 | 已实现 |
| 同公司、同盘口线成对赔率 | 已实现 |
| 让球/大小球拆半结算 | 已实现 |
| 基础研究 EV、优势、纸上 EV 和分歧阈值 | 已实现研究候选层 |
| 比分分布独立校准 | 分市场动态验收；只有 `PAPER_READY` 市场开放 paper_EV，未通过市场不应用校准因子 |
| `pfinal` 经时间切分校准验证 | 未完成 |
| 正式模拟信号 | 暂不启用 |

执行规则：

```text
若胜平负出现重大模型分歧 -> 胜平负研究 EV 暂停展示；大小球/让球仅记录跨市场风险，并继续执行各自专项闸门
若 research_EV 和既有门槛未通过 -> 观望/市场缺失
若 research_EV 通过但 pfinal 未验证 -> 待校准复核，资金占用为 0
若未来 pfinal 验证通过且正式 EV 通过 -> 方可输出模拟信号
```

## 6. 回测解锁条件

恢复正式模拟信号前，至少完成：

1. 固定训练集、校准集、验证集的时间切分，不允许赛后信息进入预测快照。
2. 对 `pbase`、`qmkt`、候选 `pshr/pfinal` 分别输出 Brier Score、Log Loss 和校准曲线。
3. 对胜平负、大小球、让球分别统计候选信号数量、ROI、最大回撤和赔率区间表现。
4. 保留每笔信号的 `snapshot_id`、实际使用庄家赔率、真实抓取时间和结算规则。
5. 经书面确认采用的 `pshr -> pfinal` 公式与门槛。

CLV 只有在赔率时间点和收盘赔率均可靠保存后才纳入正式评估。

## 7. 执行批次

### 批次 A：治理闸门与对外口径

- 页面、API payload 和中文报告区分 `pbase`、`qmkt` 与展示融合概率。
- 标明当前没有经验证的 `pfinal`。
- API 模式下将任何候选模拟信号降级为待校准复核，不占用资金。

### 批次 B：快照和市场键完善

- 在预测快照中保存模型版本、市场键和每个方向的指定庄家赔率。已完成。
- 对真实抓取时间与比赛时间进行独立校验。已完成，赛后生成快照强制隔离。

### 批次 C：校准与回测

- 建立时间切分样本集。胜平负第一版已完成。
- 实现并比较候选校准方案。旧版 `pbase -> qmkt` 市场收缩审计已保留为 raw market weight；新版 `pshr` 采用胜平负类别偏差校准后的 `pbase`。
- 用概率质量和模拟舱指标决定是否启用 `pfinal`。即使候选达到待审批状态，正式 EV 仍需人工确认公式、专项市场验收与资金策略后才可打开。

### 批次 D：正式信号审批

- 输出校准与回测报告。
- 经确认后配置正式 EV 和模拟信号开关。

## 8. 当前交付声明

当前版本可以交付为：

- 本地数据抓取、预测展示和报告生成系统；
- 研究试算 EV 诊断与纸上复核系统；
- 数据快照和回测建设基础。

当前数据状态（2026-05-26）：

- 已形成 `market_quotes` 结构化市场数据表，回填 `236` 条 Pinnacle 全场报价。
- 已同步 `2` 场合格赛前预测的 90 分钟赛果；最低验收门槛为 `100` 场独立比赛。
- 已检测并隔离赛后生成的预测记录；它们不会进入时间切分校准。
- 当前校准管道中，胜平负 `pshr` 状态以实时验收接口为准；比分分布层按大小球、让球分别验收，未通过市场不应用失败校准因子；正式准入仍需 `pfinal` 人工审批和资金策略验收。

当前版本不得宣称为：

- 已验证正期望的模拟下注系统；
- 已具备可执行 `pfinal` 的正式决策模型；
- 可用于真实投注的收益工具。
