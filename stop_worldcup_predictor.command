#!/bin/zsh
set -e

cd "$(dirname "$0")"

PORT="${WORLDCUP_WEB_PORT:-8765}"
PID_FILE="storage/web_server.pid"
SERVICE_LABEL="com.worldcup.predictor.web.v2"
SCREEN_NAME="worldcup_predictor_web_v2"
PLIST_FILE="${HOME}/Library/LaunchAgents/${SERVICE_LABEL}.plist"

STOPPED=0

if command -v screen >/dev/null 2>&1; then
  if screen -ls 2>/dev/null | grep -q "[.]${SCREEN_NAME}[[:space:]]"; then
    echo "正在停止世界杯预测后台会话：${SCREEN_NAME}"
    screen -S "${SCREEN_NAME}" -X quit >/dev/null 2>&1 || true
    STOPPED=1
    sleep 1
  fi
fi

if command -v launchctl >/dev/null 2>&1; then
  if launchctl print "gui/$(id -u)/${SERVICE_LABEL}" >/dev/null 2>&1; then
    echo "正在卸载世界杯预测后台服务：${SERVICE_LABEL}"
    launchctl bootout "gui/$(id -u)" "${PLIST_FILE}" >/dev/null 2>&1 || true
    STOPPED=1
    sleep 1
  fi
fi

if [[ -f "${PID_FILE}" ]]; then
  PID="$(cat "${PID_FILE}" 2>/dev/null || true)"
  if [[ -n "${PID}" ]] && kill -0 "${PID}" >/dev/null 2>&1; then
    CMD="$(ps -p "${PID}" -o command= 2>/dev/null || true)"
    if [[ "${CMD}" == *"worldcup_predictor.web_server"* ]]; then
      echo "正在停止世界杯预测服务：PID ${PID}"
      kill "${PID}" >/dev/null 2>&1 || true
      sleep 1
      kill -9 "${PID}" >/dev/null 2>&1 || true
      STOPPED=1
    fi
  fi
  rm -f "${PID_FILE}"
fi

PORT_PID="$(lsof -tiTCP:"${PORT}" -sTCP:LISTEN 2>/dev/null | head -n 1 || true)"
if [[ -n "${PORT_PID}" ]]; then
  PORT_CMD="$(ps -p "${PORT_PID}" -o command= 2>/dev/null || true)"
  if [[ "${PORT_CMD}" == *"worldcup_predictor.web_server"* ]]; then
    echo "正在停止端口 ${PORT} 上的世界杯预测服务：PID ${PORT_PID}"
    kill "${PORT_PID}" >/dev/null 2>&1 || true
    sleep 1
    kill -9 "${PORT_PID}" >/dev/null 2>&1 || true
    STOPPED=1
  fi
fi

if [[ "${STOPPED}" == "1" ]]; then
  echo "世界杯预测服务已停止。"
else
  echo "当前没有检测到正在运行的世界杯预测服务。"
fi

if [[ -t 0 ]]; then
  read -k 1 "?按任意键关闭窗口。"
fi
