#!/bin/zsh
set -e

cd "$(dirname "$0")"

HOST="${WORLDCUP_WEB_HOST:-127.0.0.1}"
PORT="${WORLDCUP_WEB_PORT:-8766}"
URL="http://${HOST}:${PORT}"
LOG_DIR="storage"
PID_FILE="${LOG_DIR}/web_server.pid"
LOG_FILE="${LOG_DIR}/web_server.log"
ERR_FILE="${LOG_DIR}/web_server.err.log"
SERVICE_LABEL="com.worldcup.predictor.web.v2"
SCREEN_NAME="worldcup_predictor_web_v2"
PLIST_FILE="${HOME}/Library/LaunchAgents/${SERVICE_LABEL}.plist"
PROJECT_DIR="$(pwd)"
PYTHON_BIN="$(command -v python3)"

mkdir -p "${LOG_DIR}"
mkdir -p "${HOME}/Library/LaunchAgents"

health_ok() {
  command -v curl >/dev/null 2>&1 && curl -fsS --max-time 2 "${URL}/healthz" >/dev/null 2>&1
}

remember_port_pid() {
  PORT_PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
  if [[ -n "${PORT_PID}" ]]; then
    echo "${PORT_PID}" > "${PID_FILE}"
  fi
}

write_launch_agent() {
  cat > "${PLIST_FILE}" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key>
  <string>${SERVICE_LABEL}</string>
  <key>WorkingDirectory</key>
  <string>${PROJECT_DIR}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/zsh</string>
    <string>-lc</string>
    <string>cd "${PROJECT_DIR}" &amp;&amp; exec "${PYTHON_BIN}" -u -m worldcup_predictor.web_server --host "${HOST}" --port "${PORT}"</string>
  </array>
  <key>RunAtLoad</key>
  <true/>
  <key>KeepAlive</key>
  <true/>
  <key>StandardOutPath</key>
  <string>${PROJECT_DIR}/${LOG_FILE}</string>
  <key>StandardErrorPath</key>
  <string>${PROJECT_DIR}/${ERR_FILE}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONUNBUFFERED</key>
    <string>1</string>
  </dict>
</dict>
</plist>
EOF
}

start_with_launch_agent() {
  write_launch_agent
  launchctl bootout "gui/$(id -u)" "${PLIST_FILE}" >/dev/null 2>&1 || true
  launchctl bootstrap "gui/$(id -u)" "${PLIST_FILE}"
  launchctl kickstart -k "gui/$(id -u)/${SERVICE_LABEL}" >/dev/null 2>&1 || true
}

start_with_screen() {
  launchctl bootout "gui/$(id -u)" "${PLIST_FILE}" >/dev/null 2>&1 || true
  screen -S "${SCREEN_NAME}" -X quit >/dev/null 2>&1 || true
  screen -dmS "${SCREEN_NAME}" /bin/zsh -lc "cd \"${PROJECT_DIR}\" && exec \"${PYTHON_BIN}\" -u -m worldcup_predictor.web_server --host \"${HOST}\" --port \"${PORT}\" >> \"${PROJECT_DIR}/${LOG_FILE}\" 2>> \"${PROJECT_DIR}/${ERR_FILE}\""
}

if health_ok; then
  remember_port_pid
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

if [[ -f "${PID_FILE}" ]]; then
  OLD_PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${OLD_PID}" ]] && kill -0 "${OLD_PID}" >/dev/null 2>&1; then
    OLD_CMD="$(ps -p "${OLD_PID}" -o command= 2>/dev/null || true)"
    if [[ "${OLD_CMD}" == *"worldcup_predictor.web_server"* ]]; then
      echo "检测到旧的世界杯预测服务未响应，正在清理：PID ${OLD_PID}"
      kill "${OLD_PID}" >/dev/null 2>&1 || true
      sleep 1
      kill -9 "${OLD_PID}" >/dev/null 2>&1 || true
    fi
  fi
fi

PORT_PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
if [[ -n "${PORT_PID}" ]]; then
  PORT_CMD="$(ps -p "${PORT_PID}" -o command= 2>/dev/null || true)"
  if [[ "${PORT_CMD}" == *"worldcup_predictor.web_server"* ]]; then
    echo "检测到端口 ${PORT} 上有旧服务，正在重启：PID ${PORT_PID}"
    kill "${PORT_PID}" >/dev/null 2>&1 || true
    sleep 1
    kill -9 "${PORT_PID}" >/dev/null 2>&1 || true
  else
    echo "端口 ${PORT} 已被其他程序占用，无法启动世界杯预测。"
    echo "占用进程：${PORT_CMD}"
    read -k 1 "?按任意键关闭窗口。"
    exit 1
  fi
fi

echo "正在启动世界杯预测后台服务：${URL}"
echo "服务名称：${SCREEN_NAME}"
echo "日志文件：${LOG_FILE}"
START_MODE="${WORLDCUP_START_MODE:-screen}"
if [[ "${START_MODE}" == "launch_agent" ]] && command -v launchctl >/dev/null 2>&1; then
  start_with_launch_agent
elif command -v screen >/dev/null 2>&1; then
  start_with_screen
elif command -v launchctl >/dev/null 2>&1; then
  start_with_launch_agent
else
  nohup "${PYTHON_BIN}" -u -m worldcup_predictor.web_server --host "${HOST}" --port "${PORT}" >> "${LOG_FILE}" 2>> "${ERR_FILE}" &
  SERVER_PID=$!
  echo "${SERVER_PID}" > "${PID_FILE}"
  disown "${SERVER_PID}" >/dev/null 2>&1 || true
fi

for _ in {1..40}; do
  if health_ok; then
    remember_port_pid
    echo "启动成功：${URL}"
    open "${URL}" >/dev/null 2>&1 || true
    exit 0
  fi
  if [[ -n "${SERVER_PID:-}" ]]; then
    if ! kill -0 "${SERVER_PID}" >/dev/null 2>&1; then
      echo "启动失败。最近日志："
      tail -n 40 "${LOG_FILE}" 2>/dev/null || true
      tail -n 40 "${ERR_FILE}" 2>/dev/null || true
      if [[ -t 0 ]]; then read -k 1 "?按任意键关闭窗口。"; fi
      exit 1
    fi
  fi
  sleep 0.25
done

echo "启动超时。最近日志："
tail -n 40 "${LOG_FILE}" 2>/dev/null || true
tail -n 40 "${ERR_FILE}" 2>/dev/null || true
if [[ -t 0 ]]; then read -k 1 "?按任意键关闭窗口。"; fi
exit 1
