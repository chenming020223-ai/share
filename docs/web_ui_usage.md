# 网页界面使用说明

日期：2026-05-27

## 启动网页

首次使用先双击项目根目录的 `setup_worldcup_predictor.command`。

日常使用双击 `start_worldcup_predictor.command`。

在项目目录运行：

```bash
python3 -m worldcup_predictor.web_server
```

打开：

```text
http://127.0.0.1:8765
```

如果端口被占用：

```bash
python3 -m worldcup_predictor.web_server --port 8788
```

也可以通过 `.env` 配置：

```text
WORLDCUP_WEB_HOST=127.0.0.1
WORLDCUP_WEB_PORT=8765
WORLDCUP_DB_PATH=storage/worldcup_predictor.sqlite3
API_FOOTBALL_KEY=你的_api_key
API_FOOTBALL_RETRIES=3
```

## 数据入口

- 页面仅提供真实赛事分析入口，使用 API-Football 自动抓取比赛和赔率。
- 页面初次打开时不自动生成预测；只有选择真实赛程或输入比赛 ID 后提交，才保存新的预测运行。

## 页面输出

- 页面以“预测工作台 / 数据处理 / 模型审计 / 历史报告”四个区域组织信息。
- 展示融合概率（非 `pfinal`）。
- `pbase` 基础概率。
- `qmkt` 市场去水概率。
- 预期进球。
- 最可能比分。
- 胜平负、大小球、让球模拟舱方向。
- 启动资金、均注金额、占用资金、期望资金。
- 本地保存的预测 Run ID。
- 中文 Excel / PDF 报告导出按钮。

## 数据处理复核

- “数据处理”展示本场抓取流程、双方最近 10 场中可纳入的有效 90 分钟比赛，以及场均积分、场均进失球、攻防评分等特征。
- 近期比赛以时间顺序绘制积分与进失球线图，便于检查输入样本是否与模型输出方向一致。
- API 原始队名仅在这一审计区域随中文名附带显示，供翻译核定和问题追踪。
- 若本场只保存了一个赛前赔率快照，页面会明确说明不能据此绘制真实赔率走势；赔率时间序列应在持续采样后开放。

## 中文展示标准

- 比赛标题显示中文球队名，例如“墨西哥 vs 美国”。
- 比赛信息显示具体联赛名称，例如“国际友谊赛”或“国际足联世界杯”。
- API 时间统一转换为北京时间，例如“2026-06-12 08:00 北京时间”。
- 赛程搜索结果、概率表、市场表和中文报告都优先使用项目受控中文名录；未核定的名称显示 API 英文原名，避免无法识别，ID 继续保留供核验。

## API 辅助功能

页面提供三个赛事入口按钮：

- 搜索比赛：按球队搜索 API-Football 已排定赛程，选择后自动填入比赛 ID。
- 今日甲级联赛：抓取北京时间今天尚未开赛、被项目中文名录识别为足球甲级联赛的比赛列表；选择一场后点击“生成赛前分析”。
- 今日随机比赛：从当天 API-Football fixtures 中随机抽一场并直接预测。

如果两队没有未来直接交锋，页面会提示选择赛程或填写比赛 ID。
球队输入框可输入已映射的中文球队名；程序会在调用 API-Football 前反查为 API 可识别名称。
API-Football 不直接提供官方中文名字段；当前页面对已收录名称优先中文展示，未收录名称保留 API 英文原名，新增赛事的最终中文译名可由甲方验收后补充确认。

## 本地留档

每次网页预测都会保存到 SQLite：

```text
storage/worldcup_predictor.sqlite3
```

健康检查接口：

```text
http://127.0.0.1:8765/api/health
```

API 连接检查：

```text
http://127.0.0.1:8765/api/api-status
```

最近预测记录：

```text
http://127.0.0.1:8765/api/recent-predictions
```

## 重要说明

模拟舱只用于纸上回测和研究，不连接真实投注平台，也不保证收益。

## API 证书问题

如果页面提示 `CERTIFICATE_VERIFY_FAILED`，先停止本地服务再重启：

```bash
Control + C
python3 -m worldcup_predictor.web_server
```

项目会优先使用 `certifi` 证书包。如果仍失败，请参考 `docs/troubleshooting.md`。

## 中文报告导出

每次预测完成后，可点击“导出 Excel”或“导出 PDF”。报告包含：

- 90 分钟胜平负概率。
- 具体联赛名称和北京时间。
- 模型概率和市场概率。
- 预期进球和可能比分。
- 正期望模拟舱方向。
- 资金占用和期望资金。
- 数据处理特征摘要；Excel 额外列出近期比赛明细。
- 数据提示和风险边界。
