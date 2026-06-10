# 模型胜率与 EV 口径审计

日期：2026-06-05

## 结论

本轮重点确认“模型胜率”和“EV”是否存在口径混乱。

检查结论：

- 胜平负 EV 公式可审计，当前使用 `pbase` 研究概率，不使用展示融合概率。
- 大小球 / 让球 EV 公式按亚洲盘半赢、走水、半输进行结算，计算结构正确。
- 当前最大风险不在 EV 公式本身，而在 `pbase` 比分矩阵尚未校准，尤其总进球偏高会放大大小球研究 EV。
- 正式 EV 仍关闭，`pfinal` 未批准，模拟舱不得产生正式资金占用。

## 概率身份

### 胜平负

胜平负是三分类市场，程序展示的概率口径为“模型胜率”：

```text
model_probability = pbase(selection)
research_EV = pbase(selection) * decimal_odds - 1
```

展开式：

```text
research_EV = pbase * (odds - 1) - (1 - pbase)
```

例如：

```text
乌迪内斯胜，赔率 7.56，模型概率 23.0%
EV = 0.23 * 7.56 - 1 = 0.7388 = 73.88%
```

但当前 1X2 研究方向还必须通过：

- 模型概率下限；
- pbase 与 qmkt 分歧上限；
- 模型优势；
- 基础研究 EV；
- 保守研究 EV；
- 正式 EV 闸门。

### 大小球 / 让球

亚洲盘不能只看普通胜率，因为存在：

- 全赢；
- 半赢；
- 走水；
- 半输；
- 全输。

因此程序中大小球 / 让球的 `model_probability` 明确标记为“正收益概率”，不是普通胜率。

EV 使用的是注权重：

```text
research_EV =
  盈利注权重 * (odds - 1)
  - 亏损注权重
```

同时输出：

```text
positive_return_probability = P(net_return > 0)
win_stake_fraction = 平均盈利注权重
loss_stake_fraction = 平均亏损注权重
break_even_odds = 1 + loss_stake_fraction / win_stake_fraction
```

## 本轮修正

本轮未改动核心预测公式和 EV 数值公式，只修正概率身份与展示口径：

- `BetRecommendation` 新增 `model_probability_label`。
- `BetRecommendation` 新增 `ev_probability_basis`。
- 胜平负标记为：
  - `model_probability_label = 模型胜率`
  - `ev_probability_basis = pbase_result_probability`
- 大小球 / 让球标记为：
  - `model_probability_label = 正收益概率`
  - `ev_probability_basis = asian_settlement_weight`
- EV 计算路径新增：
  - `positiveReturnProbability`
  - `winStakeFraction`
  - `lossStakeFraction`
  - `breakEvenOdds`
- 网页模拟舱、批量摘要、复盘 Excel、中文报告同步展示概率口径。

## 当前校准状态

截至本轮检查：

- 正式状态：`INSUFFICIENT_DATA`
- 合格赛前样本：`15 / 100`
- 独立比赛：`15 / 100`
- 校准区间：`3 / 20`
- 验证区间：`3 / 20`
- `pfinal`：未批准
- 正式 EV：关闭

## 后续必须解决

1. 继续积累合格赛前样本，达到校准门槛。
2. 针对胜平负校准 `pbase / qmkt / pshr`。
3. 针对大小球和让球单独校准比分矩阵，尤其总进球层。
4. 正式 EV 只能在 `pfinal` 通过验收后启用。
