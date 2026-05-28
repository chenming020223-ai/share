# 模型优化与增强理论研究

日期：2026-05-21  
阶段：模型增强前置研究  
适用项目：世界杯预测  
预测口径：90 分钟赛果

## 1. 研究结论先行

当前项目已经有可运行 MVP，但模型仍处于“规则型 + 演示型”阶段。下一阶段优化的核心，不是简单增加变量，而是建立一套可校准、可回测、可解释的分层模型。

建议采用五层结构：

1. **球队评分层**：Elo/FIFA/近期表现/攻防强度，作为基础强弱判断。
2. **进球分布层**：用 Poisson 或 Dixon-Coles 类模型生成比分矩阵，再派生胜平负、大小球、让球。
3. **市场校准层**：把赔率去水后的市场概率作为强信号，但按数据质量动态决定权重。
4. **世界杯情景层**：处理小组积分、出线压力、轮换、赛程和比赛地影响。
5. **风险与回测层**：用历史数据验证概率质量和模拟舱长期表现。

最重要的判断：**模型优化必须先优化概率质量，再谈下注方向。** 如果概率没有校准，正期望只是看起来精确的错觉。

## 2. 当前 MVP 的主要不足

### 2.1 球队强度底座偏弱

当前 API 模式主要依赖 API-Football 的赛季统计和默认 TeamProfile 兜底。国家队比赛经常统计不完整，导致强弱判断容易退化为平均值。

需要补强：

- World Football Elo 或类似 Elo 评分。
- FIFA 官方排名及排名分。
- 近期国家队正式比赛表现。
- 球员层面的阵容质量代理变量。

### 2.2 赔率融合过于静态

当前 `market_weight` 是用户输入的固定权重。真实情况下，市场信号质量取决于：

- 是否有 1X2、大小球、让球完整赔率。
- bookmaker 数量。
- 是否接近开赛。
- 是否为主流赛事。
- 赔率是否已经过临场伤停和首发信息修正。

因此市场权重应从固定参数升级为动态参数。

### 2.3 小组赛博弈尚未建模

世界杯小组赛不是普通友谊赛。积分、净胜球、小组第三排名、潜在淘汰赛对手都会改变球队收益函数。

例如：

- 打平即可出线的一方，风险偏好降低。
- 必须赢的一方，进攻倾向上升，但防守暴露也上升。
- 已提前出线的强队，轮换风险上升。
- 第三名也可能晋级时，“平局是否足够”不能简单判断。

### 2.4 缺少概率校准与回测

当前模型能输出概率，但尚未证明这些概率是否可靠。

需要回答：

- 预测 60% 的事件，历史上是否真的约 60% 发生？
- 模型是否长期优于只看市场赔率？
- 正期望方向是否能跑出正收益？
- 最大回撤和连续亏损风险有多大？

没有这些验证，模型只能作为研究工具，不能作为决策工具。

## 3. 优化目标定义

模型增强不应只追求“猜对胜负”，而应追求以下目标。

### 3.1 概率质量

核心指标：

- Log Loss：惩罚高置信度错误。
- Brier Score：衡量概率与真实结果的均方误差。
- Calibration Curve：检查概率是否校准。
- 1X2 分项表现：主胜、平局、客胜分别评估。

### 3.2 市场对比

核心指标：

- 是否优于去水后的市场概率。
- 是否能在部分赛事、部分盘口中发现稳定偏差。
- 是否有 Closing Line Value，即预测方向是否优于临场收盘线。

### 3.3 模拟舱表现

核心指标：

- ROI。
- 最大回撤。
- 连续亏损场次。
- 正期望下注次数。
- 每个市场的独立表现：胜平负、大小球、让球分开统计。

### 3.4 可解释性

每场比赛报告至少回答：

- 基础强度谁占优。
- 市场更看好谁。
- 模型与市场分歧在哪里。
- 数据完整性是否足够。
- 模拟舱为什么买或为什么不买。

## 4. 建议的模型架构

### 4.1 数据输入层

建议把数据分成六类。

| 数据类型 | 作用 | 优先级 |
|---|---|---:|
| fixture 信息 | 确定具体比赛、联赛、时间、主客队 | P0 |
| odds 信息 | 市场概率和 EV 计算 | P0 |
| 球队评分 | 强弱底座 | P0 |
| 近期比赛 | 状态、攻防趋势、交锋 | P1 |
| 世界杯积分 | 出线形势和动机 | P1 |
| 阵容信息 | 伤停、首发、轮换 | P2 |

API-Football 继续作为第一数据源，用于 fixture、odds、teams/statistics、head-to-head 等；外部评分和世界杯专项数据作为补充层。

### 4.2 球队评分层

推荐建立综合评分：

```text
team_strength =
  w_elo * normalized_elo
  + w_fifa * normalized_fifa_points
  + w_recent * recent_form
  + w_attack * attack_rating
  + w_defense * defense_rating
  + w_squad * squad_quality
```

第一版权重不需要训练得很复杂，可以先用保守规则：

- Elo 权重最高。
- FIFA 排名作为辅助，不单独主导。
- 近期状态做短期修正。
- 阵容质量作为国家队稀疏数据的兜底。

原因：

- FIFA 男足排名已经采用类似 Elo 的赛后加减分逻辑，会考虑比赛重要性、结果、预期结果和对手强度。
- 但 FIFA 排名有赛程与洲际赛事偏差，不应直接等同于真实胜率。

### 4.3 进球分布层

建议从当前 Poisson 模型升级为“攻防强度 + 低比分修正”的比分模型。

基础公式：

```text
log(lambda_home) =
  base_goal
  + attack_home
  - defense_away
  + home_or_host_advantage
  + context_edge

log(lambda_away) =
  base_goal
  + attack_away
  - defense_home
  - home_or_host_advantage
  - context_edge
```

然后用比分矩阵得到：

```text
P(home_win) = sum P(x, y), x > y
P(draw)     = sum P(x, y), x = y
P(away_win) = sum P(x, y), x < y
```

优化方向：

- 第一阶段继续使用独立 Poisson，先做校准。
- 第二阶段加入 Dixon-Coles 低比分相关修正，改善 0-0、1-0、0-1、1-1 等低比分概率。
- 第三阶段再考虑更复杂的双变量 Poisson 或层级贝叶斯模型。

不要一开始就上过复杂模型。世界杯样本少，复杂模型如果没有足够历史数据支撑，很容易过拟合。

### 4.4 市场校准层

赔率不是结果真相，但它是极强的集体信息源。

建议流程：

1. 欧赔转隐含概率。
2. 去除庄家水位。
3. 计算市场数据质量。
4. 动态决定市场融合权重。

动态市场权重示例：

```text
market_quality =
  q_bookmaker_count
  * q_market_completeness
  * q_time_to_kickoff
  * q_league_coverage

effective_market_weight =
  base_market_weight * market_quality
```

市场完整时，可以提高市场权重；盘口缺失或 bookmaker 数量少时，降低市场权重。

### 4.5 世界杯情景层

世界杯专项模型不应只给“必须赢”一个字段，而应建立结果收益函数。

对每支球队计算：

```text
utility(team, result) =
  qualification_value
  + group_rank_value
  + goal_difference_value
  - injury_fatigue_cost
  - rotation_cost
```

然后将收益差转成比赛倾向：

- 进攻倾向。
- 节奏倾向。
- 平局接受度。
- 轮换风险。

关键字段：

- 当前积分。
- 当前净胜球。
- 当前进球数。
- 小组排名。
- 小组第三排名压力。
- 平局是否足够。
- 输球是否仍可出线。
- 对潜在淘汰赛对手的规避或争取。

### 4.6 阵容与球员层

国家队比赛中，球队赛季统计经常不够稳定。球员层信息可以作为更好的兜底。

建议使用代理变量：

- 预计首发球员总身价。
- 五大联赛主力人数。
- 关键球员可用性。
- 门将质量。
- 中锋与核心创造者可用性。
- 后防主力缺席数量。

实现上先不用复杂爬虫，可以先留出字段，后续人工或半自动导入。

### 4.7 情绪、国家关系和商业叙事层

这类变量只放在敏感性分析层，不进入主模型核心。

合理用法：

- 影响 rivalry_intensity。
- 影响比赛对抗强度。
- 影响公众投注热度。
- 用于解释市场是否可能高估热门叙事。

不合理用法：

- 直接给某队加大胜率。
- 假设商业收益一定改变比赛结果。
- 把不可验证叙事写成确定因果。

## 5. 推荐的 V2 模型形态

建议命名为 `Model V2: Rating + Goals + Market Calibration`。

### 5.1 输入

```text
fixture
team_rating_home
team_rating_away
recent_form_home
recent_form_away
market_snapshot
world_cup_context
data_quality
```

### 5.2 输出

```text
model_probabilities:
  home_win
  draw
  away_win

score_matrix
total_goals_probabilities
handicap_cover_probabilities
market_probabilities
final_probabilities
data_quality_score
confidence_level
```

### 5.3 决策规则

模拟舱仍保持甲方已确认规则：

```text
只有当：
  EV > 0
  且 model_probability - market_probability >= min_edge
  且 data_quality_score >= min_quality
才允许 BUY
```

如果数据质量不足，即使 EV 为正，也应降级为 `WATCH` 或 `LOW_CONFIDENCE_WATCH`。

## 6. 回测设计

### 6.1 数据集划分

不能随机切分历史比赛。足球数据有时间顺序，必须使用时间切分。

建议：

- 训练集：较早比赛。
- 验证集：中间比赛，用于调参。
- 测试集：最近比赛，用于最终评估。
- 世界杯专项：用历届世界杯、洲际杯、预选赛做补充测试。

### 6.2 Walk-forward 回测

每次只使用比赛前已知数据：

```text
for match in chronological_matches:
  build_features(data_before_match)
  predict(match)
  record_prediction()
  after_result_known:
    settle_bets()
    update_ratings()
```

这样可以避免未来数据泄漏。

### 6.3 概率评估

每场记录：

- 模型概率。
- 市场概率。
- 最终融合概率。
- 实际结果。
- Log Loss。
- Brier Score。
- 是否校准。

### 6.4 模拟舱评估

每个市场独立记录：

- 选择方向。
- 盘口线。
- 下注赔率。
- 收盘赔率。
- 结果。
- 盈亏。
- EV 预测。
- 是否 beat closing line。

最终输出：

- 总 ROI。
- 各市场 ROI。
- 最大回撤。
- 盈亏曲线。
- 分赔率区间表现。
- 分赛事类型表现。

## 7. 数据质量评分

建议新增 `data_quality_score`，范围 0 到 1。

评分维度：

| 维度 | 权重建议 | 说明 |
|---|---:|---|
| fixture 确定性 | 0.20 | 是否明确 fixture_id |
| 赔率完整性 | 0.25 | 1X2、大小球、让球是否齐全 |
| bookmaker 数量 | 0.15 | 来源越多越稳定 |
| 球队评分可用性 | 0.20 | Elo/FIFA/近期状态是否可用 |
| 情景数据可用性 | 0.10 | 小组积分、赛程、场地 |
| 阵容信息可用性 | 0.10 | 伤停、首发、轮换 |

质量等级：

```text
0.80 - 1.00  高：可以正常输出 BUY/WATCH
0.60 - 0.79  中：允许 WATCH，BUY 需更高 EV 门槛
0.40 - 0.59  低：只输出研究方向，不建议模拟舱买入
0.00 - 0.39  很低：只展示数据，不生成方向
```

## 8. 实施路线

### 阶段一：先提升可信度

目标：不改变模型主体，先让输出更可靠。

任务：

- 增加市场完整性判断。
- 增加数据质量评分。
- 报告展示数据缺失原因。
- 正期望判断增加 `min_quality` 门槛。

验收：

- 没有赔率或赔率不完整时，不会误出 BUY。
- 用户能看懂本场预测数据质量。

### 阶段二：加入评分底座

目标：国家队比赛不再依赖 API-Football 赛季统计兜底。

任务：

- 增加 Elo/FIFA 导入文件。
- 建立球队中文名、API 名、评分名的映射。
- 在 `TeamProfile` 中加入评分来源。
- 预测报告显示基础强度差。

验收：

- 国家队比赛即使没有 team statistics，也有合理强度差。

### 阶段三：升级进球模型

目标：提升比分矩阵和大小球/让球派生概率。

任务：

- 重构进球模型为独立模块。
- 保存完整 score matrix。
- 增加低比分修正参数。
- 回测低比分概率是否改善。

验收：

- 1X2 概率不劣化。
- 大小球和让球概率更稳定。

### 阶段四：世界杯专项情景

目标：让小组赛预测能解释积分和出线形势。

任务：

- 新增 group standings 数据结构。
- 计算出线压力。
- 计算平局接受度。
- 计算轮换风险。
- 报告增加“小组形势”段落。

验收：

- 小组最后一轮能输出合理的动机解释。

### 阶段五：历史回测闭环

目标：证明模型是否真的有价值。

任务：

- 保存 API 原始快照。
- 保存预测快照。
- 录入或抓取赛果。
- 结算模拟舱。
- 输出资金曲线和评分指标。

验收：

- 可以回答“模型是否优于市场”和“正期望是否兑现”。

## 9. 不建议马上做的事

暂时不建议：

- 直接接入真实投注平台。
- 直接做自动投注。
- 过早使用复杂深度学习。
- 把国家关系和商业叙事做成高权重变量。
- 在没有回测前宣传收益率。

原因：

- 当前最大短板是数据完整性和概率校准，不是模型复杂度。
- 世界杯样本小，复杂模型很容易过拟合。
- 模拟舱必须先作为研究和纸上回测。

## 10. 下一步建议

理论研究完成后，代码实现建议从两个低风险模块开始：

1. **数据质量评分模块**  
   已新增 `worldcup_predictor/data_quality.py`，对 fixture、odds、team stats、market coverage 打分。

2. **市场完整性展示模块**  
   已实现后端输出每个市场的 `available / missing / incomplete`，前端和报告同步展示。

这两步不会大幅改变模型概率，但会显著提升产品可信度，是模型 V2 的地基。下一步应继续做 API 原始响应快照和 Elo/FIFA 评分底座。

## 11. 参考资料

- FIFA 男足世界排名计算说明：<https://inside.fifa.com/fifa-world-ranking/procedure-men>
- FIFA 男足世界排名页面：<https://inside.fifa.com/fifa-world-ranking/men>
- API-Football 官方文档：<https://www.api-football.com/documentation-v3>
- API-SPORTS Football v3 文档：<https://api-sports.io/documentation/football/v3>
- Maher, M. J. (1982). Modelling association football scores. DOI: <https://doi.org/10.1111/j.1467-9574.1982.tb00782.x>
- Dixon, M. J. and Coles, S. G. (1997). Modelling association football scores and inefficiencies in the football betting market. DOI: <https://doi.org/10.1111/1467-9876.00065>
