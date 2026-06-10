#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo "正在执行世界杯预测最终交付验收..."
echo "检查内容：模型治理、真实资金闸门、报告导出、前端脚本、Python 编译和自动化测试。"
python3 -m worldcup_predictor.delivery --full

echo ""
echo "验收完成。审计文件保存在 outputs/delivery_audit。"
if [[ -t 0 ]]; then
  read -k 1 "?按任意键关闭窗口。"
fi
