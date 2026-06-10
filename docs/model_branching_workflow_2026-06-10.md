# 世界杯预测模型固定与分叉说明

日期：2026-06-10

## 目标

将当前可运行模型固定为稳定基准版，并在独立工作副本中继续做模型、EV、模拟舱和数据层调整。

## 固定策略

- 稳定基准提交：记录当前程序代码、网页、模型、测试、启动脚本和交付文档。
- 稳定基准分支：`stable/current-model-2026-06-10`
- 稳定基准标签：`baseline-current-model-2026-06-10`
- 调整实验分支：`experiment/model-v2-2026-06-10`
- 调整工作副本：`/Users/hcm/Documents/世界杯预测_调整版`

## 不纳入基准提交的内容

- `.env`：包含本地 API 密钥。
- `storage/`：本地数据库、日志、运行 PID、API 缓存。
- `artifacts/`：本地生成素材。
- `outputs/`：临时报表、预览图、中间文件。

这些内容是运行数据或生成物，不属于模型代码本体。

## 使用方式

稳定版继续保留在：

```bash
/Users/hcm/Documents/世界杯预测
```

后续模型改造在独立副本中进行：

```bash
/Users/hcm/Documents/世界杯预测_调整版
```

打开实验版：

```bash
cd /Users/hcm/Documents/世界杯预测_调整版
./start_worldcup_predictor.command
```

实验版默认访问地址：

```bash
http://127.0.0.1:8766
```

稳定版默认访问地址仍为：

```bash
http://127.0.0.1:8765
```

回到稳定版：

```bash
cd /Users/hcm/Documents/世界杯预测
git switch stable/current-model-2026-06-10
./start_worldcup_predictor.command
```

从任意分支恢复到基准标签：

```bash
git switch -c restore-from-baseline baseline-current-model-2026-06-10
```

## 后续开发原则

- 稳定版只做紧急修复，不直接做大模型实验。
- 实验版可以调整数据抓取、模型胜率、EV、模拟舱、UI 和批量分析。
- 每完成一个可验证阶段，在实验分支形成提交，并记录测试结果。
- 只有实验版经过回测和页面验证后，才考虑合并回稳定版。
