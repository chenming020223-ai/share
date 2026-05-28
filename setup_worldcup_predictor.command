#!/bin/zsh
set -e

cd "$(dirname "$0")"

echo "正在检查 Python..."
python3 --version

echo "正在安装/更新世界杯预测所需组件..."
python3 -m pip install -r requirements.txt

echo ""
echo "安装完成。现在可以双击 start_worldcup_predictor.command 启动世界杯预测。"
read -k 1 "?按任意键关闭窗口。"
