# DLC-MCP 普通用户接入方案

本文档说明如何让普通用户只通过 HTTP Gateway 使用 DLC-MCP 查询数据资产，不开放服务器 SSH、不暴露腾讯云 AK/SK、不提供代码修改权限。

## 接入链路

```text
Codex -> npx @levisli/dlc-mcp -> HTTP Gateway -> DLC-MCP 服务端 -> assets.db / WeData
```

普通用户只需要：

```text
Node.js / npx
Gateway URL
Gateway token
Codex
```

普通用户不需要：

```text
服务器 SSH
腾讯云 AK/SK
GitHub 写权限
Python 环境
服务器目录
assets.db 文件
```

## token 如何生成

当前内部测试 token 是用 Python 标准库随机生成的：

```bash
python3 - <<'PY'
import secrets
print(secrets.token_urlsafe(32))
PY
```

它是一个随机共享密钥，不是从腾讯云 AK/SK 派生，也不和数据库密码有关。

## 服务器启动 Gateway

在服务器上执行：

```bash
cd /opt/dlc-mcp/DLC-MCP
DLC_MCP_GATEWAY_HOST=0.0.0.0 \
DLC_MCP_GATEWAY_PORT=8787 \
DLC_MCP_DB=/data/dlc-mcp/assets.db \
python3 -m dlc_mcp.gateway
```

如果已经把 token 写入 `/etc/dlc-mcp/env`：

```bash
DLC_MCP_GATEWAY_TOKEN=replace-with-random-token
```

Gateway 会自动读取并要求 `/mcp` 请求带 token。

## 验证 Gateway

健康检查不需要 token：

```bash
curl -s http://64.186.234.87:8787/health
```

预期：

```json
{"ok": true}
```

MCP 请求需要 token：

```bash
curl -s http://64.186.234.87:8787/mcp \
  -H 'content-type: application/json' \
  -H 'authorization: Bearer replace-with-random-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

不带 token 会返回 `401`。

## 普通用户安装

发布 npm 后，普通用户执行：

```bash
DLC_MCP_GATEWAY_TOKEN=replace-with-random-token \
  npx -y @levisli/dlc-mcp install-codex
```

可以直接发给普通用户：

```bash
DLC_MCP_GATEWAY_TOKEN=你发给他的token \
  npx -y @levisli/dlc-mcp install-codex
```

执行后，安装器会把 token 写入用户的 Codex config：

```toml
[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "http://64.186.234.87:8787/mcp"
DLC_MCP_GATEWAY_TOKEN = "..."
```

如果 Gateway URL 不是默认值，同时传：

```bash
DLC_MCP_GATEWAY_URL=http://64.186.234.87:8787/mcp \
DLC_MCP_GATEWAY_TOKEN=replace-with-random-token \
  npx -y @levisli/dlc-mcp install-codex
```

安装器会写入 `~/.codex/config.toml`：

```toml
[mcp_servers.dlc-mcp]
command = "npx"
args = ["-y", "@levisli/dlc-mcp"]
type = "stdio"

[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "http://64.186.234.87:8787/mcp"
DLC_MCP_GATEWAY_TOKEN = "replace-with-random-token"
```

然后重启 Codex。

## 避免 Codex 命令确认

推荐流程：

```text
普通终端执行一次 install-codex -> 重启 Codex -> 在 Codex 里直接问 dlc-mcp
```

不要让 Codex 在对话里代跑 `curl`、`ssh` 或 `TOKEN=$(...)` 去查资产。那些是 shell 命令，Codex 会按安全策略询问是否允许。安装完成后，查询表结构、资产画像、任务运行状态都应该直接走 `dlc-mcp` MCP 工具。

## 用户验证

在 Codex 中提问：

```text
用 dlc-mcp 查一下 dws_360_fin_sms_job_1d_di 统计了哪些指标
```

能返回指标口径说明，就表示接入成功。

## 权限边界

普通用户可以：

```text
查表资产
查字段
查指标口径
查任务
查运行实例
查质量规则
查核心表判断
```

普通用户不能：

```text
修改代码
提交 GitHub
部署服务器
查看腾讯云 AK/SK
登录服务器
下载 assets.db
执行任意 shell 命令
```

## 后续增强

内部测试先用共享 token。

正式推广前建议升级为：

```text
HTTPS
公司 VPN / IP 白名单
统一 token 轮换
或 SSO
```
