#!/bin/zsh
set -e

cd "$(dirname "$0")"

HOST="${WORLDCUP_WEB_HOST:-127.0.0.1}"
PORT="${WORLDCUP_WEB_PORT:-8765}"
URL="http://${HOST}:${PORT}"

if command -v curl >/dev/null 2>&1 && curl -fsS "${URL}/api/health" >/dev/null 2>&1; then
  echo "世界杯预测已经在运行：${URL}"
  open "${URL}" >/dev/null 2>&1 || true
  exit 0
fi

if ! python3 - <<'PY'
import importlib.util
missing = [name for name in ("certifi", "openpyxl", "PIL") if importlib.util.find_spec(name) is None]
if missing:
    raise SystemExit("缺少组件：" + ", ".join(missing))
PY
then
  echo ""
  echo "请先双击 setup_worldcup_predictor.command 安装所需组件，然后再启动。"
  read -k 1 "?按任意键关闭窗口。"
  exit 1
fi

(sleep 1.5; open "${URL}" >/dev/null 2>&1 || true) &

echo "正在启动世界杯预测：${URL}"
echo "关闭本窗口即可停止本地服务。"
python3 -m worldcup_predictor.web_server --host "${HOST}" --port "${PORT}"
