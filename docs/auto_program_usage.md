# 自动预测程序使用说明

日期：2026-05-21  
状态：已加入第一版自动模式。

## 1. 程序目标

程序目标是：

```text
输入两支队伍
  ↓
自动从 API-Football 抓取比赛、赔率、球队统计、历史交锋
  ↓
生成模型概率和市场概率
  ↓
给出胜平负、大小球、让球三个市场的模拟舱方向
  ↓
用 1000 元启动资金做纸上均注模拟
```

这里的“模拟舱”只用于纸上研究和回测，不连接真实投注账户，也不保证收益。

## 2. API Key 准备

需要准备 API-Football key，并设置环境变量：

```bash
export API_FOOTBALL_KEY="你的_api_key"
```

也可以运行时传入：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --api-key "你的_api_key"
```

## 3. 自动模式运行

输入两支球队：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France
```

如果你已经知道 API-Football 的 fixture id，建议直接传入，这样最准确：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --fixture-id 123456
```

输出 JSON：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --json
```

## 4. 模拟舱参数

默认启动资金为 1000 元：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --bankroll 1000
```

默认均注金额为资金的 1%，即 1000 元资金下每个方向 10 元。

手动设置每注金额：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --bankroll 1000 --unit 20
```

设置模型优势门槛：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --min-edge 0.08
```

含义：模型概率至少比市场概率高 8 个百分点。正式 API 模式仅使用 Pinnacle 全场盘口；双方须各有至少 5 场有效近期比赛；研究试算 EV 不低于 5%、保守研究试算 EV 不低于 3%。若胜平负中任一方向的基础模型概率与 Pinnacle 去水概率差异超过 15 个百分点，整场三类市场 EV 暂停展示。胜平负方向还要求基础模型概率至少为 40%。

调试时也可以强制每个可用市场都给方向：

```bash
python3 -m worldcup_predictor --auto --home Brazil --away France --force-picks
```

注意：`--force-picks` 只保留给命令行调试。正式网页交付版会保留通过 Pinnacle 全场盘口、近期数据、概率分歧、优势门槛和保守研究试算 EV 校验的研究方向；`pfinal` 校准验收前，API 模式不会输出正式模拟信号或占用资金。

## 5. 输出字段解释

### 展示融合概率（非 `pfinal`）

融合基础模型概率和市场概率后的页面比较结果，尚不是正式执行概率。

### `pbase` 基础概率

程序基于球队统计、预期进球和泊松比分矩阵计算的概率。

### `qmkt` 市场去水概率

市场赔率转成隐含概率后，再去掉庄家利润。

### 研究方向

每场最多覆盖三个市场：

- 胜平负。
- 大小球。
- 让球。

动作含义：

| 动作 | 含义 |
|---|---|
| BUY | 内部研究筛选通过；API 模式会在正式 EV 闸门处降级为“观望” |
| WATCH | 未通过门槛，模拟舱观望 |
| PAPER_BUY | 强制均注演示研究方向，不代表有优势 |
| NO_MARKET | API 没有提供该市场赔率，或盘口被判定为异常 |

### 研究试算 EV/注

以 `pbase` 对比市场价格计算的每 1 元期望收益试算，仅用于研究复核。若触发整场模型分歧异常，网页显示为“EV 已暂停”，原始试算仅保留在导出报告的模型异常审计附录。

例如：

```text
EV/注: 4.5%
```

表示模型估计每 1 元纸上投注的期望收益为 0.045 元。它只是模型估计，不是确定收益。

## 6. 当前自动模式会抓取的数据

已接入：

- 球队搜索。
- 未来交锋比赛。
- 指定 fixture id 的比赛。
- 欧赔 1X2。
- 大小球赔率。
- 让球赔率。
- 球队赛季统计。
- 历史交锋。

第一版暂未完全使用：

- 伤停。
- 官方首发。
- 小组积分。
- 天气。
- FIFA 排名。
- Elo。
- 球员身价。

这些会在后续模块中逐步加入。

## 7. 重要限制

### API-Football 赔率需要定时保存

赔率是时间序列数据。API 返回的是当前或有限历史范围内的数据，所以要研究初盘、即时盘、临场盘和收盘盘，必须定时抓取并保存到本地数据库。

### 自动球队统计不等于完整实力评分

API-Football 的球队统计可以做第一版模型，但最终最好补充：

- World Football Elo。
- FIFA 官方排名。
- 球员身价。
- 伤停首发。
- xG 数据。

### 模拟舱不是投注建议

模拟舱用于回答：

- 模型方向是否长期优于市场。
- 哪类市场更容易产生优势。
- 均注资金曲线是否可接受。

它不保证真实收益，也不应该替代风险控制。

## 8. 后续开发优先级

1. 增加本地数据库，保存每次 API 快照。
2. 每小时自动保存赔率。
3. 接入小组积分和出线形势。
4. 接入伤停和首发。
5. 加入 Elo 与 FIFA 排名。
6. 做模拟舱历史回测，输出资金曲线。
