# 世界杯预测项目流程与准备清单

日期：2026-05-21  
阶段：理论研究完成后，进入项目执行规划。

## 1. 项目总目标

建立一个针对 2026 美加墨世界杯的足球比赛预测系统，能够在赛前输出：

- 胜、平、负概率。
- 可能比分。
- 预期进球。
- 赔率与模型分歧。
- 关键影响因素解释。
- 小组出线形势和战意分析。
- 风险提示和置信度。

最终目标不是“每场都猜中”，而是长期概率判断更稳定、更可解释，并能通过历史回测证明有效。

## 2. 总体流程

项目可以分成 8 个阶段：

| 阶段 | 名称 | 核心任务 | 主要产出 |
|---|---|---|---|
| 0 | 目标定义 | 明确预测对象和使用场景 | 项目边界、预测目标 |
| 1 | 数据准备 | 收集球队、赛程、赔率、积分等数据 | 原始数据表 |
| 2 | 数据建库 | 清洗、统一格式、建立字段标准 | 标准化数据集 |
| 3 | 特征工程 | 把原始信息转成模型变量 | 特征表 |
| 4 | 基线模型 | 建立 Elo、泊松、赔率融合模型 | 第一版预测模型 |
| 5 | 回测校准 | 用历史赛事验证和调权重 | 回测报告 |
| 6 | 实战预测 | 赛前多时间点更新预测 | 单场预测报告 |
| 7 | 赛后复盘 | 对比结果、更新模型 | 误差分析和迭代计划 |

## 3. 阶段 0：目标定义

### 需要先决定的问题

- 预测的是 90 分钟赛果，还是包括加时点球后的晋级结果。
- 主要预测 1X2，还是还要预测比分、大小球、让球。
- 输出给谁看：个人研究、投注辅助、内容分析、数据产品。
- 是否需要自动化每日更新。
- 是否需要图形界面或只用命令行/表格。

### 建议第一版目标

第一版聚焦：

- 小组赛和淘汰赛 90 分钟胜平负。
- 胜平负概率。
- 预期进球。
- 最可能比分。
- 赔率去水概率。
- 模型与市场分歧。
- 关键因素解释。

暂时不把“是否投注”作为系统核心目标。先把概率做准，再讨论交易策略。

## 4. 阶段 1：数据准备

### A. 球队基础数据

需要准备：

- 球队名称标准表。
- FIFA 排名。
- Elo 评分。
- 近 5 场、近 10 场战绩。
- 近 1 年正式比赛战绩。
- 进球、失球、净胜球。
- 主教练信息。
- 阵容总身价。
- 核心球员名单。
- 阵容深度评分。

建议字段：

```text
team_id
team_name
confederation
fifa_rank
elo
market_value
coach_name
coach_rating
attack_rating
defense_rating
squad_depth
recent_form_score
```

### B. 球员和阵容数据

需要准备：

- 最终大名单。
- 预计首发。
- 关键球员伤停。
- 停赛情况。
- 球员俱乐部出场时间。
- 球员位置和角色。
- 门将能力。
- 中卫组合稳定性。
- 前锋终结能力。

建议字段：

```text
player_id
player_name
team_id
position
club
market_value
minutes_recent
injury_status
suspension_status
starter_probability
importance_score
```

### C. 比赛赛程数据

需要准备：

- 比赛编号。
- 比赛日期和时间。
- 主队、客队。
- 小组。
- 球场。
- 城市和国家。
- 是否中立场。
- 旅行距离。
- 休息天数。
- 当地温度、湿度、海拔。

建议字段：

```text
match_id
stage
group
home_team
away_team
kickoff_time_local
kickoff_time_utc
stadium
city
country
neutral_site
rest_days_home
rest_days_away
travel_km_home
travel_km_away
weather_temp
weather_humidity
altitude
```

### D. 赔率和盘口数据

这是最重要的数据之一。

需要准备：

- 欧赔主胜、平、客胜。
- 亚盘盘口和水位。
- 大小球盘口和水位。
- 初盘。
- 即时盘。
- 收盘盘。
- 多家公司的赔率。
- 赔率更新时间。
- 盘口变化轨迹。

建议字段：

```text
match_id
bookmaker
timestamp
odds_home
odds_draw
odds_away
asian_handicap
asian_home_water
asian_away_water
over_under_line
over_water
under_water
```

注意：

- 欧赔必须去水后才能当概率使用。
- 单家公司赔率不够，最好采集多家公司。
- 临场赔率通常比早盘信息更多。

### E. 小组积分和出线形势

需要准备：

- 当前积分。
- 净胜球。
- 进球数。
- 相互战绩。
- 当前排名。
- 出线概率。
- 小组第一概率。
- 打平是否足够。
- 输球是否仍可出线。
- 是否已提前出线。
- 是否已淘汰。

建议字段：

```text
match_id
team_id
points_before_match
goal_diff_before_match
goals_for_before_match
rank_before_match
qualification_probability
group_winner_probability
must_win_score
draw_enough
already_qualified
already_eliminated
rotation_risk
```

### F. 历史交锋和关系数据

需要准备：

- 两队历史交锋。
- 正式比赛交锋。
- 近 10 年交锋。
- 交锋进球数。
- 是否宿敌。
- 是否同洲或同区。
- 风格克制关系。

建议字段：

```text
team_a
team_b
match_date
competition
score_a
score_b
is_official
years_since_match
weighted_h2h_edge
rivalry_intensity
```

### G. 国家关系和商业收益情景数据

这类数据只能作为低权重情景输入，不作为主模型核心。

可准备的代理指标：

- 两国关系紧张度评分。
- 媒体关注度。
- 搜索热度。
- 社交媒体热度。
- 明星球员商业影响力。
- 球队晋级后的潜在市场收益。
- 东道主球队票房和收视影响。

建议字段：

```text
match_id
country_relation_edge
media_heat_home
media_heat_away
star_power_home
star_power_away
commercial_incentive_edge
public_betting_heat_home
public_betting_heat_away
```

约束：

- 这些字段必须有来源说明。
- 权重必须低。
- 只能用于敏感性分析。
- 不能把不可验证叙事当事实。

## 5. 阶段 2：数据建库

### 文件结构建议

```text
data/
  raw/
    teams/
    fixtures/
    odds/
    standings/
    players/
    injuries/
    weather/
  processed/
    teams.csv
    fixtures.csv
    odds_snapshots.csv
    standings_snapshots.csv
    player_availability.csv
    match_features.csv
  external/
    source_notes.md
```

### 数据标准化重点

- 统一球队名称，例如 USA、United States、美国必须映射到同一个 ID。
- 统一时间格式，全部保存 UTC，同时保留当地时间。
- 赔率保留时间戳，不能只存最后一个值。
- 小组积分要保存“赛前快照”，不能赛后覆盖。
- 伤停信息要有确认时间。
- 每条数据尽量保留来源。

### 需要准备的映射表

```text
team_aliases.csv
bookmaker_aliases.csv
stadium_locations.csv
competition_codes.csv
country_codes.csv
```

## 6. 阶段 3：特征工程

把原始数据转成模型能用的变量。

### 核心特征

- `elo_diff`：双方 Elo 差。
- `rank_diff`：双方 FIFA 排名差。
- `attack_vs_defense_home`：主队进攻相对客队防守。
- `attack_vs_defense_away`：客队进攻相对主队防守。
- `rest_diff`：休息天数差。
- `travel_diff`：旅行距离差。
- `market_home_prob`：赔率去水主胜概率。
- `market_draw_prob`：赔率去水平局概率。
- `market_away_prob`：赔率去水客胜概率。
- `odds_movement_home`：主胜赔率变化。
- `must_win_diff`：必须赢球程度差。
- `rotation_risk_diff`：轮换风险差。
- `h2h_edge`：历史交锋边际。
- `rivalry_intensity`：宿敌强度。
- `commercial_edge`：商业情景边际。

### 小组赛专用特征

- 打平收益。
- 输球代价。
- 小组第一收益。
- 提前出线状态。
- 已淘汰状态。
- 第三名晋级压力。
- 同组另一场比赛影响。

### 淘汰赛专用特征

- 是否可能踢加时。
- 点球能力。
- 门将扑点能力。
- 球队保守倾向。
- 上轮是否加时。
- 主力累计疲劳。

## 7. 阶段 4：基线模型

建议先做三层模型，不要一开始就做复杂黑箱。

### 模型 1：Elo 基础模型

目的：

- 给出强弱基础概率。
- 作为最低基准线。

输出：

- 主队强度优势。
- 客队强度优势。

### 模型 2：泊松比分模型

目的：

- 预测预期进球。
- 生成比分概率矩阵。
- 汇总胜平负概率。

输出：

- 预期进球。
- 最可能比分。
- 大小球概率。
- 胜平负概率。

### 模型 3：赔率融合模型

目的：

- 利用市场信息修正模型盲区。
- 发现模型与赔率的分歧。

输出：

- 去水后市场概率。
- 模型概率。
- 融合后概率。
- 分歧指数。

### 先不要做的事情

- 不要一开始就上复杂深度学习。
- 不要让国家关系、商业叙事主导模型。
- 不要在没有回测前人工大幅调权重。
- 不要用赛后信息污染赛前特征。

## 8. 阶段 5：回测校准

### 需要准备的历史样本

- 近几届世界杯。
- 欧洲杯、美洲杯、亚洲杯、非洲杯。
- 世界杯预选赛。
- 国家队正式比赛。

### 回测要保存的赛前数据

- 赛前球队评分。
- 赛前赔率。
- 赛前伤停。
- 赛前积分。
- 赛前天气。
- 赛前媒体热度。

### 核心评估指标

- 命中率：直观但不够稳定。
- Brier Score：衡量概率误差。
- Log Loss：惩罚过度自信。
- Calibration：检查概率是否校准。
- Closing Line Value：是否优于收盘赔率。
- ROI：只有进入投注策略阶段才重点看。

### 回测输出

```text
backtest_report.md
calibration_chart.png
model_vs_market.csv
error_cases.csv
recommended_weights.json
```

### 重要原则

- 按时间切分训练和验证。
- 不能随机打散比赛。
- 每一场只能使用赛前已经知道的信息。
- 一定要记录模型错误的原因。

## 9. 阶段 6：实战预测流程

每场比赛建议做 5 次更新。

### T-7 天：初始预测

准备：

- 球队实力。
- 大致赛程。
- 初盘赔率。
- 小组形势初判。

输出：

- 初始胜平负概率。
- 大致比分倾向。
- 风险点。

### T-72 小时：信息增强

准备：

- 伤停更新。
- 训练消息。
- 赔率变化。
- 天气预报。
- 小组积分形势。

输出：

- 第二版概率。
- 与初始预测的变化原因。

### T-24 小时：临场前预测

准备：

- 主要媒体首发预测。
- 赔率最新变化。
- 球队发布会信息。
- 出线形势精算。

输出：

- 主预测版本。
- 赔率分歧分析。
- 风险等级。

### T-1 小时：首发确认

准备：

- 官方首发。
- 官方替补。
- 最终伤停。
- 临场赔率。

输出：

- 最终赛前概率。
- 首发变化影响。
- 模型置信度。

### 赛后：复盘

准备：

- 最终比分。
- xG。
- 红黄牌。
- 点球。
- VAR。
- 赔率收盘。

输出：

- 预测误差。
- 是否输在模型、数据还是随机事件。
- 是否需要调整权重。

## 10. 单场预测报告模板

```text
比赛：A vs B
阶段：小组赛 / 淘汰赛
时间：
地点：

一、最终概率
- A 胜：
- 平局：
- B 胜：

二、预期进球
- A：
- B：

三、最可能比分
- 1：
- 2：
- 3：

四、赔率分析
- 欧赔去水概率：
- 模型概率：
- 分歧：
- 盘口变化：

五、关键影响因素
- 球队实力：
- 伤停：
- 小组形势：
- 赛程体能：
- 历史关系：
- 情景变量：

六、风险提示
- 最大不确定性：
- 临场需关注：
- 是否建议等待首发：

七、结论
- 主判断：
- 保守判断：
- 激进情景：
```

## 11. 需要准备的工具

### 数据工具

- CSV 或 SQLite：第一版足够。
- 后续可升级 PostgreSQL。
- 数据采集脚本。
- 数据校验脚本。
- 定时更新任务。

### 分析工具

- Python。
- pandas。
- numpy。
- scikit-learn。
- scipy。
- matplotlib 或 plotly。

### 模型工具

- Elo 更新模块。
- 泊松比分模块。
- 赔率去水模块。
- 市场融合模块。
- 回测模块。
- 报告生成模块。

### 展示工具

- 命令行输出。
- Excel / PDF 报告。
- CSV 结果表。
- 后续可做 Web 页面或仪表盘。

## 12. 人工准备清单

### 每支球队要准备

- 球队实力评分。
- 核心阵容。
- 伤停名单。
- 战术风格。
- 主教练特点。
- 小组目标。
- 轮换可能性。

### 每场比赛要准备

- 赛程和地点。
- 积分形势。
- 赔率快照。
- 天气情况。
- 预计首发。
- 历史交锋。
- 情绪和媒体热度。
- 是否存在特殊商业叙事。

### 每天需要更新

- 赔率。
- 伤停。
- 小组积分。
- 新闻发布会。
- 天气。
- 首发预测。

## 13. 项目目录建议

```text
世界杯预测/
  README.md
  docs/
    theory_research.md
    project_workflow.md
    data_dictionary.md
    backtest_plan.md
  data/
    raw/
    processed/
    external/
  reports/
    matches/
    backtests/
  worldcup_predictor/
    data.py
    models.py
    odds.py
    poisson.py
    predictor.py
    cli.py
  tests/
```

## 14. 优先级路线图

### 第一步：完成数据字典

明确所有字段含义、范围、默认值、来源和更新时间。

### 第二步：做历史数据样本

先选 50 到 200 场国际比赛做小样本回测。

### 第三步：完善赔率模块

加入多家公司赔率、赔率变化、收盘赔率对比。

### 第四步：加入小组形势模拟

根据积分、净胜球、同组另一场比赛，计算每个结果的出线收益。

### 第五步：建立回测报告

输出模型是否真的比简单 Elo 或赔率基线更好。

### 第六步：实战预测模板

世界杯开始后，每场按 T-7、T-72、T-24、T-1 小时更新。

## 15. 当前项目下一步

建议下一步不是继续写复杂模型，而是先补三份基础文档和数据：

1. `docs/data_dictionary.md`：完整字段字典。
2. `docs/backtest_plan.md`：历史回测方案。
3. `data/processed/teams.csv`：球队标准表。

这三项完成后，模型和程序扩展会更稳，不会边写边改字段。
