# 美加墨世界杯比赛预测模型

这是一个第一版、可解释的足球比赛预测程序。它不是“玄学结论机”，而是把多个维度拆成可维护的数据字段，再输出胜、平、负概率和可能比分。

项目文档：

- 项目记忆：`docs/project_memory.md`
- 后续计划：`docs/next_steps_plan.md`
- 理论研究：`docs/theory_research.md`
- 项目流程与准备清单：`docs/project_workflow.md`
- 模型优化与增强理论研究：`docs/model_optimization_research.md`
- 模型完整计算公式：`docs/model_formulas.md`
- 模型吸收规范与正式 EV 准入：`docs/model_adoption_spec_v1.md`
- 模型审查报告：`docs/model_review_2026-05-22.md`
- 项目深度报告：`docs/project_deep_review_report_2026-05-22.md`
- 最终程序成果模拟：`docs/final_product_demo.md`
- 自动预测程序使用说明：`docs/auto_program_usage.md`
- 网页界面使用说明：`docs/web_ui_usage.md`
- 可交付项目验收清单：`docs/delivery_checklist.md`
- 甲方确认需求：`docs/client_requirements.md`
- 故障排查：`docs/troubleshooting.md`
- 交付说明：`交付说明.md`
- 交付更新记录：`docs/release_notes_2026-05-22.md`
- 公网分享部署说明：`docs/online_sharing_deployment.md`

## 自动模式

设置 API-Football key：

```bash
export API_FOOTBALL_KEY="你的_api_key"
```

输入两支球队自动预测：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France
```

带 1000 元模拟舱、每注 10 元：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --bankroll 1000 --unit 10
```

输出 JSON：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --json
```

## 网页界面

项目名：世界杯预测  
预测口径：90 分钟赛果  
模拟舱规则：API 模式只使用 Pinnacle 全场盘口；当前仅保留研究试算 EV 供复核，重大模型分歧时暂停展示，待 `pfinal` 经校准和回测验证后再启用正式模拟信号

网页采用真实赛事单入口：搜索或抽取赛前比赛后生成分析，初次打开页面不会自动创建演示预测记录。新版界面为石墨灰玻璃工作台布局，按“预测工作台 / 数据处理 / 模型审计 / 历史报告”组织操作和复核信息。

首次使用先双击 `setup_worldcup_predictor.command` 安装依赖。

最简单启动方式：双击项目根目录里的 `start_worldcup_predictor.command`，程序会自动打开本地网页。

启动本地网页：

```bash
python3 -m worldcup_predictor.web_server
```

然后打开：

```text
http://127.0.0.1:8765
```

健康检查：

```text
http://127.0.0.1:8765/api/health
```

API 连接检查：

```text
http://127.0.0.1:8765/api/api-status
```

模型校准验收状态：

```text
http://127.0.0.1:8765/api/model-validation
```

今日甲级联赛赛前列表：

```text
http://127.0.0.1:8765/api/today-fixtures?scope=first_division
```

每次预测完成后，页面可以导出中文 Excel 报告或 PDF 报告。

## 公网分享版

项目已支持受控公网分享部署。线上模式使用服务器侧 `API_FOOTBALL_KEY`，页面不向访客显示 API 密钥输入框，并可通过共享访问口令保护入口。Render 部署配置位于 `render.yaml`，完整发布步骤见 `docs/online_sharing_deployment.md`。

公网发布前必须换用新的 API-Football 密钥；对受邀用户共享历史记录的版本，应使用持久磁盘保存 SQLite 数据。

展示标准：

- 比赛标题优先显示项目受控中文名录中的球队名；尚无可靠中文映射时显示 API 英文原名，确保可识别，后续可继续补入名录。
- 比赛信息包含具体联赛名称。
- 开赛时间统一转换为北京时间。
- API 原始英文名称仍保留在内部字段，便于继续查询和排错。
- 页面和报告会展示数据质量评分、三类市场完整性以及模型治理状态。
- API-Football 请求遇到临时网络中断、EOF、限流或服务端错误时会自动重试，最终失败会给出中文原因。
- API 模式会保存原始数据快照和双方最近 10 场中的有效 90 分钟结果，便于后续复盘和回测。
- 页面“数据处理”板块展示双方近 5–10 场有效样本、场均指标、累计积分曲线与处理步骤；仅有一个赔率快照时明确提示无法形成真实赔率走势。
- API 模式会将 Pinnacle 全场赔率按 `snapshot_id + market_type + line + selection` 保存为结构化报价，并保存赔率时点、开赛时点与模型版本。
- 页面“模型验收”区域可以点击“同步赛果”，仅为已经存在合格赛前快照的比赛回填 API-Football 90 分钟结果。
- 人工填写比赛 ID 同样禁止对已开赛比赛生成新的预测快照，避免把赛后信息混入校准数据。
- 今日随机比赛只抽取赛前比赛；双方任一方少于 5 场有效近期比赛时，模拟舱会降级为观望。
- 页面“今日甲级联赛”会抓取北京时间当天尚未开赛、中文赛事名属于足球甲级联赛的赛程供选择；选中后再预测，不批量制造无盘口快照。
- 正式 API 模式的赔率固定使用 `Pinnacle`；胜平负只接受完整全场 1X2，大小球和让球只接受同盘口线的全场成对赔率；半场、卡牌、角球盘口会排除。
- 报告区分“指定庄家”和“已取得盘口庄家”；未取得 Pinnacle 盘口时三类市场显示缺失且资金占用为零。
- 当前研究复核门槛：优势不低于 8%，基础 EV 不低于 5%，保守 EV 不低于 3%；胜平负方向基础模型概率低于 40% 时不形成研究方向。
- 当 API 模式完整 Pinnacle 胜平负盘口中任一方向的 `pbase` 与 `qmkt` 差异超过 15 个百分点时，程序标记整场“模型分歧异常”，胜平负、大小球和让球全部暂停 EV 数值展示；原始试算只写入中文报告审计附录，资金占用为零。
- 当前概率身份：基础模型为 `pbase`，Pinnacle 去水概率为 `qmkt`；页面的展示融合概率不是 `pfinal`。在 `pshr/pfinal` 完成时间切分校准和回测验证前，API 模式研究方向统一为观望且模拟资金占用为零。
- 完整字段与准入规则见 `docs/prediction_data_standard_v1.md`。

## 已支持的维度

- 球队实力：Elo、FIFA 排名、进攻评分、防守评分、阵容厚度、教练评分。
- 庄家水位：正式 API 模式固定读取 Pinnacle 全场盘口，程序会先做去水，再和模型概率融合。
- 小组积分形势：积分、净胜球、必须赢球程度、轮换风险。
- 历史关系：交锋心理优势、德比/宿敌强度。
- 国家关系：作为低权重情景变量输入，只表达假设，不代表事实判断。
- 商业收益：作为低权重情景变量输入，只表达假设，不代表操盘证据。

## 快速运行

```bash
python3 -m worldcup_predictor --match-id MEX-USA
```

输出 JSON：

```bash
python3 -m worldcup_predictor --match-id MEX-USA --json
```

调整对赔率的信任程度：

```bash
python3 -m worldcup_predictor --match-id MEX-USA --market-weight 0.60
```

## 数据文件

球队数据在 `data/sample_teams.csv`。

关键字段：

- `elo`：球队综合实力，越高越强。
- `fifa_rank`：FIFA 排名，数字越小越强。
- `attack_rating`：进攻评分，1.00 为平均水平。
- `defense_rating`：防守评分，1.00 为平均水平，越高防守越好。
- `host_factor`：东道主/准主场加成，范围建议 0 到 1。

比赛数据在 `data/sample_fixtures.csv`。

关键字段：

- `must_win_home`、`must_win_away`：必须赢球程度，0 到 1。
- `rotation_risk_home`、`rotation_risk_away`：轮换或留力风险，0 到 1。
- `h2h_edge_home`：历史交锋对主队的边际影响，-1 到 1。
- `rivalry_intensity`：宿敌/德比强度，0 到 1；主要影响平局概率。
- `country_relation_home_edge`：国家关系对主队的假设边际，-1 到 1。
- `commercial_incentive_home_edge`：商业收益叙事对主队的假设边际，-1 到 1。
- `odds_home`、`odds_draw`、`odds_away`：欧赔主胜、平、客胜。

名称映射在 `data/name_translations.csv`，用于把 API-Football 的球队和联赛名称转换为中文展示名。

## 模型逻辑

1. 用进攻评分和对手防守评分生成双方预期进球。
2. 用 Elo、排名、赛程体能、旅行距离、小组形势、轮换风险、历史交锋等因素修正预期进球。
3. 用泊松分布生成比分矩阵。
4. 汇总比分矩阵得到胜、平、负概率。
5. 如果有赔率，先去掉庄家利润得到 `qmkt`，再生成仅用于展示比较的融合概率；该值当前不是正式 `pfinal`。

## 重要边界

国家关系、商业收益、资本叙事这类变量很容易过拟合，也容易让模型变成“解释故事”。所以第一版默认给它们很低权重。真正上线前，建议用历史世界杯、洲际杯、预选赛和赔率收盘数据做回测，再决定是否保留这些字段。

后续可以加的模块：

- 自动抓取赔率和盘口变化。
- 接入赛前伤停、首发名单和天气。
- 用历史比赛训练权重，而不是手工权重。
- 加入 Asian Handicap、大小球、凯利指数、成交量变化。
- 做回测，输出命中率、Brier Score、Log Loss。

## 回测基础

项目已新增赛果同步、回测与时间切分校准模块 `worldcup_predictor/backtest.py`、`worldcup_predictor/calibration.py`，支持：

- 录入 90 分钟赛果。
- 基于预测当时保存的 payload 结算模拟舱。
- 输出 ROI、最大回撤、Brier Score、Log Loss。
- 将合格赛前样本按时间划分为开发、校准与验证区间，拟合候选 `pshr` 并对照 `pbase`、`qmkt`。
- 明确排除赛后生成、缺少赔率时点、非 Pinnacle 或重复比赛的样本。

当前真实留档已回填 `236` 条结构化 Pinnacle 报价，并同步 `2` 场合格赛前预测的赛果；样本量不足验收门槛。2026-05-26 对“哈萨克斯坦足球甲级联赛：阿斯塔纳二队 vs 汗腾格里”完成页面真实预测验证（运行 `56`），因未取得 Pinnacle 盘口而正确输出市场缺失、占用 `0` 元，不增加合格校准样本。当前校准审计仅覆盖胜平负概率，大小球与让球仍需单独验证；在 `pfinal` 审批前不能宣称模型已经验证正期望，也不启用 API 正式模拟信号。
