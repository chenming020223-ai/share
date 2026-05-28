# 模型完整计算公式

日期：2026-05-21  
项目：世界杯预测  
预测口径：90 分钟赛果  
用途：作为模型开发、验收、报告解释和后续回测的统一公式口径。

## 1. 符号约定

| 符号 | 含义 |
|---|---|
| H | 主队或球队 A |
| A | 客队或球队 B |
| i | 主队进球数 |
| j | 客队进球数 |
| G | 最大枚举进球数，当前默认 G = 8 |
| lambda_H | 主队预期进球 |
| lambda_A | 客队预期进球 |
| O_k | 某结果的十进制赔率 |
| P_model(k) | 模型概率 |
| P_market(k) | 市场去水概率 |
| P_display(k) | 当前用于页面比较的融合展示概率，不是正式 `pfinal` |
| P_independent(k) | 独立基础模型概率，当前等同于 `pbase`，仅用于研究试算 EV 诊断 |
| w_x | 某项权重 |
| EV | 每 1 元本金的期望收益 |

基础函数：

```text
clamp(x, low, high) = min(max(x, low), high)
safe_ratio(x, y) = clamp(x, 0.2, 2.5) / clamp(y, 0.2, 2.5)
```

当前默认权重：

```text
base_goals = 1.28
market_weight = 0.45
strength_weight = 0.36
rank_weight = 0.16
host_weight = 0.11
rest_weight = 0.055
travel_weight = 0.045
group_weight = 0.10
rotation_weight = 0.09
h2h_weight = 0.055
country_relation_weight = 0.025
commercial_weight = 0.035
draw_rivalry_weight = 0.08
```

## 2. 当前 MVP 已实现公式

执行边界：本章产生的基础概率属于 `pbase`；赔率去水概率属于 `qmkt`；当前市场权重融合结果属于 `P_display`。在 `pshr` 与 `pfinal` 经时间切分校准和回测验证前，以下 EV 只能作为候选研究指标，不得触发 API 正式模拟信号。

### 2.1 球队基础预期进球

当前先用双方攻防评分生成基础预期进球：

```text
lambda_H_base = base_goals * safe_ratio(attack_H, defense_A)
lambda_A_base = base_goals * safe_ratio(attack_A, defense_H)
```

其中：

- `attack_H`：主队进攻评分。
- `defense_A`：客队防守评分。
- `base_goals`：单队基础进球均值，当前为 1.28。

### 2.2 特征优势项

所有优势项以“主队相对客队”为方向。正数偏向主队，负数偏向客队。

#### 2.2.1 Elo 优势

```text
E_elo = clamp((elo_H - elo_A) / 400, -1.5, 1.5) * strength_weight
```

#### 2.2.2 FIFA 排名优势

FIFA 排名数字越小越强，所以使用 `rank_A - rank_H`。

```text
E_rank = clamp((rank_A - rank_H) / 100, -1.0, 1.0) * rank_weight
```

#### 2.2.3 主场或准主场优势

```text
E_host = I(neutral_site = false) * host_weight
       + clamp(host_factor_H - host_factor_A, -1.0, 1.0) * host_weight
```

其中 `I(condition)` 为指示函数，条件成立取 1，否则取 0。

#### 2.2.4 休息天数优势

```text
E_rest = clamp((rest_days_H - rest_days_A) / 5, -1.0, 1.0) * rest_weight
```

#### 2.2.5 旅行距离优势

客队旅行更远，对主队有利。

```text
E_travel = clamp((travel_km_A - travel_km_H) / 6000, -1.0, 1.0) * travel_weight
```

#### 2.2.6 小组形势优势

先计算必须赢球压力：

```text
E_group_need_raw = clamp(must_win_H - must_win_A, -1.0, 1.0)
```

再计算积分和净胜球位置压力：

```text
E_group_position_raw =
  clamp(
    ((group_points_A - group_points_H) / 6)
    + ((group_goal_diff_A - group_goal_diff_H) / 12),
    -1.0,
    1.0
  )
```

合成小组形势优势：

```text
E_group =
  (0.7 * E_group_need_raw + 0.3 * E_group_position_raw)
  * group_weight
```

解释：

- 一方更需要赢球，会提高其进攻倾向。
- 积分或净胜球落后，也会增加主动性。
- 这不是“必胜加成”，而是策略倾向修正。

#### 2.2.7 轮换风险优势

客队轮换风险更高，对主队有利。

```text
E_rotation =
  clamp(rotation_risk_A - rotation_risk_H, -1.0, 1.0)
  * rotation_weight
```

#### 2.2.8 历史交锋优势

```text
E_h2h = h2h_edge_H * h2h_weight
```

`h2h_edge_H` 范围为 [-1, 1]。

#### 2.2.9 国家关系情景优势

```text
E_country = country_relation_edge_H * country_relation_weight
```

该项只作为低权重情景变量。

#### 2.2.10 商业叙事情景优势

```text
E_commercial = commercial_incentive_edge_H * commercial_weight
```

该项只作为低权重敏感性变量，不作为操盘证据。

#### 2.2.11 宿敌强度平局加成

```text
draw_boost = rivalry_intensity * draw_rivalry_weight
```

该项不进入预期进球差，而是在结果概率汇总时提高平局权重。

### 2.3 总优势项

当前程序把除平局加成、原始情景字段外的优势项相加：

```text
E_total =
  E_elo
  + E_rank
  + E_host
  + E_rest
  + E_travel
  + E_group
  + E_rotation
  + E_h2h
  + E_country
  + E_commercial
```

### 2.4 修正后的预期进球

优势项以指数形式作用于双方预期进球：

```text
lambda_H = lambda_H_base * exp(E_total)
lambda_A = lambda_A_base * exp(-E_total)
```

再做边界限制：

```text
lambda_H = clamp(lambda_H, 0.15, 4.5)
lambda_A = clamp(lambda_A, 0.15, 4.5)
```

### 2.5 比分矩阵

单队进球概率使用 Poisson 分布：

```text
P_H(i) = exp(-lambda_H) * lambda_H^i / i!
P_A(j) = exp(-lambda_A) * lambda_A^j / j!
```

比分概率：

```text
P_score(i, j) = P_H(i) * P_A(j)
```

当前枚举 `i, j = 0 ... G`，然后对截断矩阵归一化：

```text
P_score_norm(i, j) =
  P_score(i, j) / sum_{x=0..G} sum_{y=0..G} P_score(x, y)
```

### 2.6 胜平负模型概率

```text
P_model(H_win) = sum P_score_norm(i, j), where i > j
P_model(draw)  = sum P_score_norm(i, j) * (1 + draw_boost), where i = j
P_model(A_win) = sum P_score_norm(i, j), where i < j
```

由于平局加成会改变总和，所以再次归一化：

```text
P_model_norm(k) = P_model(k) / sum P_model(k)
```

其中 `k in {H_win, draw, A_win}`。

### 2.7 赔率去水概率

#### 2.7.1 胜平负三项去水

十进制赔率：

```text
O_H = 主胜赔率
O_D = 平局赔率
O_A = 客胜赔率
```

隐含概率：

```text
q_H = 1 / O_H
q_D = 1 / O_D
q_A = 1 / O_A
```

庄家水位：

```text
overround = q_H + q_D + q_A
```

去水后市场概率：

```text
P_market(H_win) = q_H / overround
P_market(draw)  = q_D / overround
P_market(A_win) = q_A / overround
```

#### 2.7.2 两项市场去水

大小球、让球等两项市场：

```text
q_1 = 1 / O_1
q_2 = 1 / O_2
overround = q_1 + q_2

P_market(1) = q_1 / overround
P_market(2) = q_2 / overround
```

### 2.8 展示融合概率（非正式 `pfinal`）

如果没有可用市场概率：

```text
P_display(k) = P_model(k)
```

如果有市场概率：

```text
P_display(k) =
  (1 - market_weight) * P_model(k)
  + market_weight * P_market(k)
```

当前 `market_weight` 被限制在 [0, 0.95]。

融合后再次归一化：

```text
P_display_norm(k) = P_display(k) / sum P_display(k)
```

`P_display` 只用于在页面中并列观察基础模型和市场的关系。它未经时间切分校准与回测审批，不得称为正式执行概率 `pfinal`。

## 3. 模拟舱公式

模拟舱不连接真实投注账户，只做纸上回测。

### 3.1 均注金额

如果用户输入 `unit_stake`：

```text
stake = unit_stake
```

如果未输入：

```text
stake = bankroll * 0.01
```

边界：

```text
stake = clamp(stake, 0, bankroll)
```

### 3.2 胜平负 EV

当前程序计算的是研究试算 EV，使用 `pbase` 基础概率，不使用展示融合概率 `P_display`。原因是 `P_display` 已经混入市场概率，如果再拿它和市场赔率比较，容易把市场信息重复使用。研究试算 EV 只用于发现需要复核的定价分歧，并非正式下注依据。

对每个结果 `k`：

```text
pbase(k) = P_model(k)
research_EV_k = pbase(k) * O_k - 1
candidate_edge_k = pbase(k) - qmkt(k)
break_even_probability_k = 1 / O_k
```

当前增加保守概率折扣，默认 `probability_discount = 0.05`：

```text
conservative_research_EV_k = research_EV_k - probability_discount * O_k
```

选择 EV 最大的方向：

```text
k* = argmax(research_EV_k)
```

研究方向筛选条件：

```text
research_EV_k* >= min_ev
and candidate_edge_k* >= min_edge
and conservative_research_EV_k* >= min_conservative_ev
and abs(candidate_edge_k*) <= max_probability_gap
and (market != 1X2 or pbase(k*) >= min_1x2_probability)
```

当前默认：

```text
min_ev = 0.05
min_edge = 0.08
probability_discount = 0.05
min_conservative_ev = 0.03
max_probability_gap = 0.15
min_1x2_probability = 0.40
```

否则：

```text
WATCH
```

解释：胜平负是三项市场，模型胜率低于 50% 理论上可能存在赔率价值；但在未完成大样本回测前，当前交付版本对胜平负增加 40% 下限。若完整 Pinnacle 胜平负盘口的任一方向出现 `abs(pbase - qmkt) > 0.15`，系统将整场比分分布标记为“模型分歧异常”，胜平负、大小球和让球的 EV 展示全部暂停，避免把同一偏差扩散为多条机会。

### 3.2.1 两项盘口有效性校验

胜平负、大小球、让球必须先通过盘口有效性校验，才允许参与 EV 计算。

正式 API 模式固定使用 `Pinnacle`。胜平负必须来自该庄家同一个全场市场的完整三项赔率：

```text
valid_1x2(bookmaker) =
  home_win_odds exists
  and draw_odds exists
  and away_win_odds exists
```

大小球和让球必须来自 `Pinnacle` 同一个全场市场、同一盘口线的成对赔率：

```text
valid_pair(line) =
  over_odds(line, bookmaker) exists
  and under_odds(line, bookmaker) exists
```

让球同理：

```text
valid_pair(line) =
  home_handicap_odds(line, bookmaker) exists
  and away_handicap_odds(line, bookmaker) exists
```

两项盘口隐含概率和：

```text
two_way_implied_sum = 1 / O_1 + 1 / O_2
```

当前有效区间：

```text
0.98 <= two_way_implied_sum <= 1.25
```

如果低于 0.98，通常说明把不同盘口或不同玩法拼在了一起；如果高于 1.25，水位过厚或数据异常。异常盘口直接排除，不生成研究方向。

当同一全场市场返回多个盘口线时，选择两侧赔率最接近平衡的一组作为主盘口；半场、卡牌与角球市场全部排除。

### 3.3 大小球亚洲盘结算

总进球：

```text
T = i + j
```

盘口拆分：

```text
split_line(line):
  rounded = round(line * 4) / 4
  lower = floor(rounded * 2) / 2
  upper = ceil(rounded * 2) / 2
  if lower == upper: return [rounded]
  else: return [lower, upper]
```

单个盘口的净收益函数：

```text
settlement_net(diff, odds):
  if diff > 0: return odds - 1
  if diff < 0: return -1
  if diff = 0: return 0
```

大球：

```text
diff = T - line_part
```

小球：

```text
diff = line_part - T
```

若有拆分盘口，对每个比分的净收益取平均：

```text
net_total(i, j, side) =
  average(settlement_net(diff_part, odds_side))
```

大小球模型正收益概率：

```text
P_positive_total(side) =
  sum P_score(i, j), where net_total(i, j, side) > 0
```

大小球研究试算 EV：

```text
research_EV_total(side) =
  sum P_score(i, j) * net_total(i, j, side)
```

研究方向筛选条件：

```text
valid_two_way_market(line)
and research_EV_total(side*) >= min_ev
and [P_positive_total(side*) - P_market(side*)] >= min_edge
and conservative_research_EV_total(side*) > 0
```

### 3.4 让球亚洲盘结算

设主队盘口为 `handicap_H`。

主队方向：

```text
diff = i + handicap_H - j
```

客队方向：

```text
diff = -(i + handicap_H - j)
```

净收益：

```text
net_handicap(i, j, side) =
  average(settlement_net(diff_part, odds_side))
```

让球模型正收益概率：

```text
P_positive_handicap(side) =
  sum P_score(i, j), where net_handicap(i, j, side) > 0
```

让球研究试算 EV：

```text
research_EV_handicap(side) =
  sum P_score(i, j) * net_handicap(i, j, side)
```

研究方向筛选条件：

```text
valid_two_way_market(line)
and research_EV_handicap(side*) >= min_ev
and [P_positive_handicap(side*) - P_market(side*)] >= min_edge
and conservative_research_EV_handicap(side*) > 0
```

### 3.5 模拟舱资金

正式可占用模拟资金的方向：

```text
active_bets = count(action = FORMAL_SIGNAL)
```

当前真实 API 模式中 `formal_ev_enabled = false`，所以 `active_bets = 0`。代码内部的 `BUY` 只表示候选筛选曾通过，输出前由模型治理闸门降级为 `WATCH`；内部测试样本只用于自动化回归，不在交付网页入口展示。

总占用：

```text
total_stake = stake * active_bets
```

期望收益：

```text
expected_profit =
  sum stake * EV_bet for all active bets
```

期望资金：

```text
expected_bankroll = bankroll + expected_profit
```

下注后剩余资金：

```text
bankroll_after_stakes = bankroll - total_stake
```

### 3.6 当前安全闸门

API 模式下，如果无法取得可靠球队强度数据，程序不允许研究方向进入正式执行链路。当前第一版用硬闸门处理：

```text
if team_stats_available = false:
  action = WATCH
  data_quality_score = min(data_quality_score, min_quality - 0.01, 0.59)
```

即使盘口 EV 看起来大于 0，也只做观望：

```text
if team_stats_available = false:
  candidate_pass -> WATCH
```

今日随机比赛只允许赛前比赛：

```text
fixture_status in {NS, TBD, PST}
and kickoff_beijing > now_beijing
```

大小球和让球盘口只允许使用同公司、同盘口线、成对且水位合理的数据：

```text
if two_way_implied_sum < 0.98 or two_way_implied_sum > 1.25:
  market_status = invalid
  action = NO_MARKET
```

## 4. V2 完整增强公式

以下为下一阶段建议实现的完整公式，不一定已经全部写进当前代码。

### 4.1 综合球队评分

先把每个指标转为 0 到 1 的标准分。

Elo 标准分：

```text
elo_score = clamp((elo - 1200) / 800, 0, 1)
```

FIFA 排名标准分，排名越小越强：

```text
fifa_rank_score = clamp((220 - fifa_rank) / 219, 0, 1)
```

近期状态：

```text
recent_form =
  (3 * wins_recent + draws_recent)
  / (3 * matches_recent)
```

进攻标准分：

```text
attack_score = clamp(goals_for_avg / league_or_team_baseline_goals, 0.5, 1.8)
```

防守标准分，失球越少越好：

```text
defense_score = clamp(league_or_team_baseline_conceded / goals_against_avg, 0.5, 1.8)
```

阵容质量：

```text
squad_score =
  0.50 * starter_value_score
  + 0.25 * top_league_player_score
  + 0.25 * key_player_availability
```

综合强度：

```text
strength_score =
  0.40 * elo_score
  + 0.15 * fifa_rank_score
  + 0.15 * recent_form
  + 0.12 * attack_score
  + 0.12 * defense_score
  + 0.06 * squad_score
```

强度差：

```text
strength_edge = strength_score_H - strength_score_A
```

### 4.2 V2 攻防评分

建议将当前 `attack_rating` 和 `defense_rating` 拆成更明确的来源。

```text
attack_rating =
  0.45 * goals_for_index
  + 0.30 * xg_for_index
  + 0.15 * chance_creation_index
  + 0.10 * set_piece_attack_index
```

```text
defense_rating =
  0.45 * goals_against_index
  + 0.30 * xg_against_index
  + 0.15 * shot_suppression_index
  + 0.10 * goalkeeper_index
```

如果没有 xG 数据，则回退：

```text
attack_rating =
  0.70 * goals_for_index
  + 0.20 * recent_form
  + 0.10 * squad_score
```

```text
defense_rating =
  0.70 * goals_against_index
  + 0.20 * recent_clean_sheet_rate
  + 0.10 * squad_score
```

### 4.3 V2 预期进球公式

建议改成 log-linear 结构：

```text
log(lambda_H) =
  alpha
  + beta_attack * attack_H
  - beta_defense * defense_A
  + beta_strength * strength_edge
  + beta_context * context_edge
  + beta_host * host_edge
```

```text
log(lambda_A) =
  alpha
  + beta_attack * attack_A
  - beta_defense * defense_H
  - beta_strength * strength_edge
  - beta_context * context_edge
  - beta_host * host_edge
```

转回预期进球：

```text
lambda_H = exp(log(lambda_H))
lambda_A = exp(log(lambda_A))
```

边界：

```text
lambda_H = clamp(lambda_H, 0.15, 4.5)
lambda_A = clamp(lambda_A, 0.15, 4.5)
```

### 4.4 世界杯情景收益函数

对每队、每种结果计算收益。

结果集合：

```text
R in {win, draw, loss}
```

收益函数：

```text
utility_team(R) =
  u_qualification * qualification_delta(R)
  + u_group_rank * group_rank_delta(R)
  + u_goal_diff * goal_diff_delta(R)
  + u_knockout_path * path_value_delta(R)
  - u_fatigue * fatigue_cost
  - u_rotation * rotation_need
```

两队收益差：

```text
utility_edge =
  utility_H(target_result_H)
  - utility_A(target_result_A)
```

转换为策略倾向：

```text
attack_intent_edge = tanh(utility_edge / scale_utility)
draw_acceptance =
  sigmoid(draw_utility_H + draw_utility_A - win_utility_pressure)
rotation_risk =
  sigmoid(rotation_need - must_win_pressure)
```

其中：

```text
sigmoid(x) = 1 / (1 + exp(-x))
tanh(x) = (exp(x) - exp(-x)) / (exp(x) + exp(-x))
```

### 4.5 V2 情景总优势

```text
context_edge =
  beta_rest * rest_edge
  + beta_travel * travel_edge
  + beta_group * attack_intent_edge
  + beta_draw * (-draw_acceptance)
  + beta_rotation * rotation_edge
  + beta_h2h * h2h_edge
```

注意：

- `draw_acceptance` 不一定给某队加胜率，更适合提高平局概率、降低总进球。
- `country_relation` 和 `commercial` 不进入核心公式，只做敏感性分析。

### 4.6 Dixon-Coles 低比分修正

独立 Poisson：

```text
P_ind(i, j) = Pois(i, lambda_H) * Pois(j, lambda_A)
```

Dixon-Coles 对低比分做相关修正：

```text
P_dc(i, j) = tau(i, j, lambda_H, lambda_A, rho) * P_ind(i, j)
```

常见修正项：

```text
tau(0,0) = 1 - lambda_H * lambda_A * rho
tau(0,1) = 1 + lambda_H * rho
tau(1,0) = 1 + lambda_A * rho
tau(1,1) = 1 - rho
tau(i,j) = 1 for other scores
```

然后归一化：

```text
P_dc_norm(i, j) =
  P_dc(i, j) / sum P_dc(i, j)
```

`rho` 需要用历史数据回测或训练，不能拍脑袋固定过大。

### 4.7 动态市场权重（研究候选，不是已批准 `pfinal`）

市场质量：

```text
market_quality =
  q_required_bookmaker
  * q_market_completeness
  * q_time_to_kickoff
  * q_league_coverage
```

指定庄家评分：

```text
q_required_bookmaker = 1 if Pinnacle full-time odds available else 0
```

市场完整度：

```text
q_market_completeness =
  available_markets / required_markets
```

临近开赛评分：

```text
q_time_to_kickoff =
  1 - clamp(hours_to_kickoff / 168, 0, 1) * 0.4
```

动态市场权重：

```text
effective_market_weight =
  base_market_weight * market_quality
```

研究展示融合：

```text
P_display_v2(k) =
  (1 - effective_market_weight) * P_model(k)
  + effective_market_weight * P_market(k)
```

### 4.8 数据质量评分

```text
data_quality_score =
  0.20 * fixture_certainty
  + 0.25 * odds_completeness
  + 0.15 * bookmaker_quality
  + 0.20 * team_rating_availability
  + 0.10 * context_availability
  + 0.10 * lineup_availability
```

建议等级：

```text
score >= 0.80: HIGH
0.60 <= score < 0.80: MEDIUM
0.40 <= score < 0.60: LOW
score < 0.40: VERY_LOW
```

未来正式信号准入条件（须在 `pfinal` 验证通过后启用）：

```text
formal_EV(pfinal, odds) > 0
and edge >= min_edge
and data_quality_score >= min_quality
and market_status = available
```

当前第一版已经加入球队强度缺失上限：

```text
if team_rating_availability < required_rating_quality:
  data_quality_score = min(data_quality_score, min_quality - 0.01, 0.59)
  action = WATCH
```

如果数据质量不足：

```text
LOW_CONFIDENCE_WATCH
```

## 5. 回测评估公式

### 5.1 Log Loss

对单场实际结果 `y`：

```text
LogLoss = -log(P_eval(y))
```

多场平均：

```text
AverageLogLoss =
  (1 / N) * sum [-log(P_eval_n(y_n))]
```

### 5.2 Brier Score

三分类 1X2：

```text
Brier =
  sum_{k in {H,D,A}} (P_eval(k) - I(y = k))^2
```

当前最小回测模块默认使用 `pbase` 作为 `P_eval`，因为它用于检验基础模型本身的预测能力。后续批量回测必须分别输出 `pbase`、`P_display` 和经校准候选 `pfinal` 的指标，只有后者通过验收才允许进入正式 EV。

多场平均：

```text
AverageBrier = (1 / N) * sum Brier_n
```

### 5.3 校准曲线

将预测概率按区间分桶：

```text
bucket = [0.50, 0.60)
```

桶内校准：

```text
calibration_error_bucket =
  average_predicted_probability
  - actual_hit_rate
```

### 5.4 ROI

```text
ROI = total_profit / total_stake
```

### 5.5 最大回撤

资金曲线：

```text
B_t = 第 t 场后的资金
```

历史峰值：

```text
Peak_t = max(B_0, B_1, ..., B_t)
```

回撤：

```text
Drawdown_t = (Peak_t - B_t) / Peak_t
```

最大回撤：

```text
MaxDrawdown = max(Drawdown_t)
```

### 5.6 Closing Line Value

若下注赔率为 `O_bet`，收盘赔率为 `O_close`：

```text
CLV_decimal = O_bet / O_close - 1
```

如果长期 `CLV_decimal > 0`，说明模型经常拿到优于收盘线的价格。

### 5.7 `pshr` 时间切分校准审计（已实现第一版）

当前第一版只审计胜平负三分类概率。可进入样本集的预测必须满足：

```text
mode = API
and snapshot_id exists
and bookmaker = Pinnacle
and pbase and qmkt are complete 1X2 probabilities
and odds_captured_at < prediction_created_at < kickoff_at
and 90_minute_result exists
```

同一比赛存在多个合格赛前快照时，只保留开赛前最后生成的一条预测，避免同一赛果重复扩大样本权重。

样本按 `kickoff_at` 排序后切分：

```text
development = earliest 60%
calibration = next 20%
validation  = latest 20%
```

在校准区间拟合市场收缩权重 `alpha`：

```text
alpha in {0.00, 0.05, ..., 1.00}

pshr_alpha(k) = (1 - alpha) * pbase(k) + alpha * qmkt(k)

alpha* = argmin_alpha AverageLogLoss_calibration(pshr_alpha)
```

在验证区间仅评估、不得再次调参：

```text
evaluate pbase, qmkt, pshr_alpha*
using Brier Score, Log Loss, Calibration Error
```

进入 `pfinal` 人工审批前的最低工程门槛：

```text
eligible_pre_match_settled_fixtures >= 100
calibration_samples >= 20
validation_samples >= 20
pshr Brier <= pbase Brier on validation
pshr LogLoss <= pbase LogLoss on validation
pshr LogLoss <= qmkt LogLoss + 0.02 on validation
pshr Brier <= qmkt Brier + 0.01 on validation
```

即使上述条件全部满足，程序也仅输出 `ELIGIBLE_FOR_REVIEW`，不会自动将 `formal_ev_enabled` 设为真。大小球和让球仍需针对比分分布及亚洲盘结算另行完成校准验收。

## 6. 当前输出与正式执行口径

单场比赛最终输出：

```text
P_display(H_win)       # 页面展示融合概率，非 pfinal
P_display(draw)
P_display(A_win)
pbase(H_win)           # 基础模型概率
pbase(draw)
pbase(A_win)
qmkt(H_win)            # 指定庄家去水概率
qmkt(draw)
qmkt(A_win)
lambda_H
lambda_A
Top scorelines
P_over(line)
P_under(line)
P_handicap_home(line)
P_handicap_away(line)
research_EV_1X2
research_EV_total
research_EV_handicap
conservative_research_EV
data_quality_score
market_status
action
```

研究方向筛选：

```text
if market_valid
and required_bookmaker = Pinnacle
and recent_valid_matches_home >= 5
and recent_valid_matches_away >= 5
and research_EV >= min_ev
and candidate_edge >= min_edge
and conservative_research_EV >= min_conservative_ev
and abs(candidate_edge) <= max_probability_gap
and (market != 1X2 or pbase(selection) >= min_1x2_probability)
and data_quality_score >= min_quality:
  candidate_action = PASS
else:
  candidate_action = WATCH
```

当前项目已实现第一版 `dataQuality` 输出、API 模式质量门槛、两项盘口有效性校验、保守研究试算 EV、整场模型分歧暂停和正式 EV 闸门。真实 API 模式下，即使研究方向满足：

```text
market_valid
and required_bookmaker = Pinnacle
and recent_valid_matches_home >= 5
and recent_valid_matches_away >= 5
and research_EV >= 0.05
and candidate_edge >= 0.08
and conservative_research_EV >= 0.03
and max_abs_gap_1X2(pbase, qmkt) <= 0.15
and (market != 1X2 or pbase(selection) >= 0.40)
and data_quality_score >= min_quality
```

仍必须执行正式准入：

```text
if pfinal_validated = false or formal_ev_enabled = false:
  action = WATCH
  total_stake = 0
else if formal_EV(pfinal, odds) passes approved thresholds:
  action = FORMAL_SIGNAL
```

内部测试样本标记为 `DEMO`，用于自动化回归和流程验证，不在交付网页入口展示，也不代表真实比赛数据质量或可执行信号。
