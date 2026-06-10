#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo "正在执行世界杯预测每日批量建库..."
echo "默认范围：北京时间今日甲级联赛；默认模式：批量建库。"
python3 -m worldcup_predictor.batch_collect --scope "${WORLDCUP_BATCH_SCOPE:-first_division}" --mode batch

echo ""
echo "批量建库完成。日志保存在 storage/batch_logs。"
if [[ -t 0 ]]; then
  read -k 1 "?按任意键关闭窗口。"
fi
