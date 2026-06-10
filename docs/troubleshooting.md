# 故障排查

日期：2026-06-03

## API-Football SSL 证书错误

页面报错类似：

```text
API-Football request failed: [SSL: CERTIFICATE_VERIFY_FAILED]
```

原因通常是 macOS 上 Python 的本地证书链不完整。

项目已在 API 客户端中优先使用 `certifi` 证书包。更新代码后需要重启本地网页服务。日常使用建议先双击：

```text
stop_worldcup_predictor.command
```

再双击：

```text
start_worldcup_predictor.command
```

如果重启后仍然报证书错误，运行：

```bash
python3 -m pip install -U certifi
```

如果你使用的是 python.org 安装的 Python，也可以运行对应版本的证书安装脚本，例如：

```bash
open "/Applications/Python 3.14/Install Certificates.command"
```

## API-Football 连接中断或 EOF

页面报错类似：

```text
API-Football 连接被中断，已自动重试 3 次仍失败。
```

或底层英文包含：

```text
UNEXPECTED_EOF_WHILE_READING
EOF occurred in violation of protocol
```

这通常不是模型计算问题，而是本机到 API-Football 的 HTTPS 连接被中途断开，常见原因包括网络波动、VPN、代理、防火墙、运营商链路或 API-Football 临时不可用。

当前版本会自动重试，默认 3 次。可以在 `.env` 调整：

```text
API_FOOTBALL_RETRIES=3
```

如果仍失败，建议：

- 稍后重试。
- 关闭或切换 VPN / 代理。
- 换一个网络环境。
- 打开 `http://127.0.0.1:8765/api/api-status` 检查 API 连接状态。
- 如果网页能打开但 API 失败，可先查看“历史报告”确认本地数据库和报告导出是否正常。

## API 模式找不到比赛

如果输入两支球队后提示找不到未来交锋，建议填写 API-Football 的 `fixture_id`。球队名搜索可能会匹配到俱乐部或历史赛事，fixture id 更准确。

## 本地网页打不开

优先双击项目根目录中的启动脚本：

```text
start_worldcup_predictor.command
```

新版启动脚本会把网页服务放到后台运行。启动成功后，即使关闭弹出的终端窗口，`http://127.0.0.1:8765` 也应继续可用。

如果提示缺少组件，先双击：

```text
setup_worldcup_predictor.command
```

如果想确认服务是否正常，打开健康检查：

```text
http://127.0.0.1:8765/healthz
```

返回 `ok: true` 表示本地服务还活着。

停止本地服务：

```text
stop_worldcup_predictor.command
```

如果仍然打不开，可以在项目目录运行下面的检查命令：

```bash
screen -ls
curl http://127.0.0.1:8765/healthz
lsof -nP -iTCP:8765 -sTCP:LISTEN
tail -80 storage/web_server.err.log
```

常见原因：

- 没有双击启动脚本，后台服务根本没有运行。
- 旧版前台服务随着终端窗口关闭而停止。
- 端口 `8765` 被其他程序占用。
- Python 组件缺失，需要先运行安装脚本。
- API-Football 网络或密钥异常，这种情况网页通常能打开，但预测会失败。

开发调试时才建议手动启动前台服务：

```bash
python3 -m worldcup_predictor.web_server
```

然后打开：

```text
http://127.0.0.1:8765
```

如果端口被占用：

```bash
python3 -m worldcup_predictor.web_server --port 8788
```

然后打开：

```text
http://127.0.0.1:8788
```
