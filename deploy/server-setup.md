# Server Setup

For the full end-to-end MCP + real WeData flow, see `docs/server-mcp-wedata-flow.md`.

Target layout:

```text
/opt/dlc-mcp
/data/dlc-mcp/assets.db
/etc/dlc-mcp/env
```

## 1. Install code

```bash
sudo mkdir -p /opt/dlc-mcp /data/dlc-mcp /etc/dlc-mcp
sudo chown -R "$USER":"$USER" /opt/dlc-mcp /data/dlc-mcp
cd /opt/dlc-mcp
git clone <your-repo-url> .
python3 -m unittest discover -s tests -v
```

## 2. Store Tencent Cloud keys for sync only

Create a dedicated Tencent Cloud CAM sub-account for this service. Give it read-only WeData permissions only.

Put the keys on the server only:

```bash
sudo cp /opt/dlc-mcp/deploy/env.example /etc/dlc-mcp/env
sudo chmod 600 /etc/dlc-mcp/env
sudo vi /etc/dlc-mcp/env
```

Fill these values:

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
WEDATA_VERSION=2025-08-06
WEDATA_PROJECT_ID=your-wedata-project-id
DLC_MCP_DB=/data/dlc-mcp/assets.db
```

Do not put Tencent Cloud keys in git, npm, user Codex config, or user laptops.

## 3. Create asset DB

Demo data:

```bash
python3 -m dlc_mcp.seed
cp data/assets.db /data/dlc-mcp/assets.db
```

Live WeData smoke test:

```bash
set -a
. /etc/dlc-mcp/env
set +a
python3 -m dlc_mcp.call_wedata_api ListTasks "{\"ProjectId\":\"$WEDATA_PROJECT_ID\"}"
```

One-shot sync for the implemented task dump. This fetches all `ListTasks` pages, writes the raw dump to `/data/dlc-mcp/sync/wedata_tasks.json`, imports it into SQLite, and runs a small MCP smoke test:

```bash
cd /opt/dlc-mcp
bash deploy/sync-wedata-once.sh
```

To sync task instance start/end/duration after `ListTaskInstances` works in your tenant, set:

```bash
sudo vi /etc/dlc-mcp/env
```

```bash
WEDATA_SYNC_INSTANCES=1
WEDATA_INSTANCE_START=2026-07-01 00:00:00
WEDATA_INSTANCE_END=2026-07-01 23:59:59
```

If your repo lives under `/opt/dlc-mcp/DLC-MCP`, run:

```bash
cd /opt/dlc-mcp/DLC-MCP
bash deploy/sync-wedata-once.sh
```

Import saved Tencent Cloud API responses:

```bash
python3 -m dlc_mcp.import_wedata_api_dump \
  --tables /data/dlc-mcp/wedata_tables.json \
  --tasks /data/dlc-mcp/wedata_tasks.json \
  --quality-rules /data/dlc-mcp/wedata_quality_rules.json \
  --db /data/dlc-mcp/assets.db
```

## 4. Smoke test local MCP on server

```bash
cd /opt/dlc-mcp
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```

## 5. Smoke test HTTP Gateway

Run from a user laptop:

```bash
curl -s http://64.186.234.87:8787/health

curl -s http://64.186.234.87:8787/mcp \
  -H 'content-type: application/json' \
  -H 'authorization: Bearer your-token' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/list"}'
```

## 6. User install

After the npm package is published:

```bash
npx -y @levisli/dlc-mcp install-codex
```

Restart Codex, then ask:

```text
用 dlc-mcp 查一下 ads_customer_revenue_daily 是不是核心表，有哪些字段，有没有质量监控
```

After task sync, test task search:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"search_tasks","arguments":{"query":"test"}}}' \
  | DLC_MCP_DB=/data/dlc-mcp/assets.db python3 -m dlc_mcp.server
```
