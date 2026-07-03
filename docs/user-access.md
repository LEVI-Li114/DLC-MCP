# DLC-MCP 普通用户接入方案

本文档说明如何让普通用户只使用 DLC-MCP 查询数据资产，不给代码修改权限、不暴露腾讯云 AK/SK、不要求每个用户配置服务器 SSH。

## 当前 SSH 模式

你当前本机 Codex 能使用 DLC-MCP，是因为 `~/.codex/config.toml` 配置了 SSH stdio MCP：

```toml
[mcp_servers.dlc-mcp]
command = "ssh"
args = ["root@64.186.234.87", "cd /opt/dlc-mcp/DLC-MCP && DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server"]
type = "stdio"
```

这个模式的链路是：

```text
Codex -> ssh root@64.186.234.87 -> 启动 python3 -m dlc_mcp.server -> 读取 assets.db / WeData
```

所以它能用的前提是你的电脑已经能免密 SSH 登录服务器，或 SSH agent/钥匙串里已有可用私钥。

验证方式：

```bash
ssh root@64.186.234.87 'echo ok'
```

如果返回 `ok`，Codex 也通常可以通过同一套 SSH 配置连接。

当前 SSH 模式不适合普通用户大规模接入，因为每个用户都要具备服务器 SSH 权限。

## 推荐目标：HTTP Gateway 模式

目标链路：

```text
Codex -> npx @baiying/dlc-mcp -> HTTPS Gateway -> DLC-MCP 服务端 -> assets.db / WeData
```

普通用户只需要执行：

```bash
npx -y @baiying/dlc-mcp install-codex
```

然后重启 Codex，不需要 SSH、不需要 AK/SK、不需要知道服务器目录。

## 管理员操作步骤

### 1. 保留现有只读 MCP 能力

继续保留现有 stdio MCP 服务：

```bash
cd /opt/dlc-mcp/DLC-MCP
DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

注意不要新增高危工具，例如：

```text
run_shell
write_file
deploy
git_pull
update_config
```

### 2. 启动 HTTP Gateway

在服务器上启动常驻 HTTP 服务，只接收 MCP JSON-RPC 请求，并转发给现有 `dlc_mcp.mcp.handle_request`。

第一版已经提供这些端点：

```text
GET  /health
POST /mcp
```

临时启动测试：

```bash
cd /opt/dlc-mcp/DLC-MCP
DLC_MCP_GATEWAY_HOST=0.0.0.0 \
DLC_MCP_GATEWAY_PORT=8787 \
DLC_MCP_DB=/data/dlc-mcp/assets.db \
python3 -m dlc_mcp.gateway
```

`POST /mcp` 请求体就是 MCP JSON-RPC，例如：

```json
{"jsonrpc":"2.0","id":1,"method":"tools/list"}
```

本机验证健康检查：

```bash
curl -s http://64.186.234.87:8787/health
```

预期返回：

```json
{"ok": true}
```

本机验证 MCP tools：

```bash
curl -s http://64.186.234.87:8787/mcp \
  -H 'content-type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

### 3. Gateway 只读连接本地资产库

Gateway 在服务器内部读取：

```bash
DLC_MCP_DB=/data/dlc-mcp/assets.db
DLC_MCP_ENV_FILE=/etc/dlc-mcp/env
```

腾讯云 AK/SK 继续只放在：

```bash
/etc/dlc-mcp/env
```

不要把 AK/SK 放到 npm、GitHub、Codex config 或用户电脑。

### 4. 增加访问控制

内部测试最小方案：共享 token。

服务器启动 Gateway 时设置：

```bash
DLC_MCP_GATEWAY_TOKEN=replace-with-random-token
```

客户端请求 `/mcp` 时需要带：

```text
Authorization: Bearer replace-with-random-token
```

或：

```text
X-DLC-MCP-Token: replace-with-random-token
```

本机验证 MCP tools：

```bash
curl -s http://64.186.234.87:8787/mcp \
  -H 'content-type: application/json' \
  -H 'authorization: Bearer replace-with-random-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

进一步方案：

```text
只允许公司 VPN / 办公网 IP 访问 Gateway
```

更安全方案：

```text
Gateway 增加统一 token 或接入公司 SSO
```

如果先走 IP 白名单，普通用户不需要额外配置 token。

### 5. 配置 HTTPS

Gateway 对外建议只暴露 HTTPS：

```text
https://dlc-mcp.your-company.com/mcp
```

可以用 Nginx 做反向代理和 HTTPS 证书。

### 6. 修改 npm launcher

`@baiying/dlc-mcp` 已支持双模式：

```text
没有 DLC_MCP_GATEWAY_URL：继续走 SSH 模式
有 DLC_MCP_GATEWAY_URL：走 HTTP Gateway 模式
```

Gateway 模式配置：

```text
DLC_MCP_GATEWAY_URL=http://64.186.234.87:8787/mcp
```

本地 launcher 做一件事：

```text
从 Codex stdin 读取 MCP JSON-RPC -> POST 到 Gateway -> 把 Gateway 响应写回 stdout
```

### 7. 更新 install-codex 默认配置

管理员本机建议先保留原来的 SSH 配置，再新增一个 Gateway 测试配置，不要删除旧配置：

```toml
[mcp_servers.dlc-mcp]
command = "ssh"
args = ["root@64.186.234.87", "cd /opt/dlc-mcp/DLC-MCP && DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server"]
type = "stdio"

[mcp_servers.dlc-mcp-gateway]
command = "npx"
args = ["-y", "@baiying/dlc-mcp"]
type = "stdio"

[mcp_servers.dlc-mcp-gateway.env]
DLC_MCP_GATEWAY_URL = "http://64.186.234.87:8787/mcp"
DLC_MCP_GATEWAY_TOKEN = "replace-with-random-token"
```

这样：

```text
dlc-mcp          继续走 SSH，作为管理员兜底
dlc-mcp-gateway 走 HTTP Gateway，用来测试普通用户接入
```

普通用户安装后，`~/.codex/config.toml` 应该类似：

```toml
[mcp_servers.dlc-mcp]
command = "npx"
args = ["-y", "@baiying/dlc-mcp"]
type = "stdio"

[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "http://64.186.234.87:8787/mcp"
DLC_MCP_GATEWAY_TOKEN = "replace-with-random-token"
```

不再需要：

```toml
DLC_MCP_SSH_HOST
DLC_MCP_REMOTE_DIR
DLC_MCP_DB
```

### 8. 普通用户验证

普通用户执行：

```bash
DLC_MCP_GATEWAY_URL=http://64.186.234.87:8787/mcp \
DLC_MCP_GATEWAY_TOKEN=replace-with-random-token \
  npx -y @baiying/dlc-mcp install-codex
```

然后重启 Codex，提问：

```text
用 dlc-mcp 查一下 dws_360_fin_sms_job_1d_di 统计了哪些指标
```

能返回指标口径说明，就表示接入成功。

## 普通用户权限边界

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

## 迁移建议

当前先保留 SSH 模式给管理员使用。

团队推广时改用 HTTP Gateway 模式：

```text
管理员：SSH 模式，方便排查问题
普通用户：HTTP Gateway 模式，只读查询
```
