# Server Setup

Target layout:

```text
/opt/dlc-agent
/data/dlc-agent/assets.db
/etc/dlc-agent/env
```

## 1. Install code

```bash
sudo mkdir -p /opt/dlc-agent /data/dlc-agent /etc/dlc-agent
sudo chown -R "$USER":"$USER" /opt/dlc-agent /data/dlc-agent
cd /opt/dlc-agent
git clone <your-repo-url> .
python -m unittest discover -s tests -v
```

## 2. Store Tencent Cloud keys for sync only

Create a dedicated Tencent Cloud CAM sub-account for this service. Give it read-only WeData permissions only.

Put the keys on the server only:

```bash
sudo cp /opt/dlc-agent/deploy/env.example /etc/dlc-agent/env
sudo chmod 600 /etc/dlc-agent/env
sudo vi /etc/dlc-agent/env
```

Fill these values:

```bash
TENCENTCLOUD_SECRET_ID=your-secret-id
TENCENTCLOUD_SECRET_KEY=your-secret-key
TENCENTCLOUD_REGION=ap-guangzhou
WEDATA_VERSION=2025-08-06
WEDATA_PROJECT_ID=your-wedata-project-id
DLC_AGENT_DB=/data/dlc-agent/assets.db
```

Do not put Tencent Cloud keys in git, npm, user Codex config, or user laptops.

## 3. Create asset DB

Demo data:

```bash
python -m dlc_agent.seed
cp data/assets.db /data/dlc-agent/assets.db
```

Live WeData smoke test:

```bash
set -a
. /etc/dlc-agent/env
set +a
python -m dlc_agent.call_wedata_api ListTasks "{\"ProjectId\":\"$WEDATA_PROJECT_ID\"}"
```

One-shot sync for the implemented task dump. This fetches all `ListTasks` pages, writes the raw dump to `/data/dlc-agent/sync/wedata_tasks.json`, imports it into SQLite, and runs a small MCP smoke test:

```bash
cd /opt/dlc-agent
bash deploy/sync-wedata-once.sh
```

If your repo lives under `/opt/dlc-agent/DLC-Agent`, run:

```bash
cd /opt/dlc-agent/DLC-Agent
bash deploy/sync-wedata-once.sh
```

Import saved Tencent Cloud API responses:

```bash
python -m dlc_agent.import_wedata_api_dump \
  --tables /data/dlc-agent/wedata_tables.json \
  --tasks /data/dlc-agent/wedata_tasks.json \
  --quality-rules /data/dlc-agent/wedata_quality_rules.json \
  --db /data/dlc-agent/assets.db
```

## 4. Smoke test local MCP on server

```bash
cd /opt/dlc-agent
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | DLC_AGENT_DB=/data/dlc-agent/assets.db python -m dlc_agent.server
```

## 5. Smoke test MCP over SSH

Run from a user laptop that has SSH access:

```bash
printf '%s\n' '{"jsonrpc":"2.0","id":1,"method":"tools/list"}' \
  | ssh data-agent-host 'cd /opt/dlc-agent && DLC_AGENT_DB=/data/dlc-agent/assets.db python -m dlc_agent.server'
```

## 6. User install

After the npm package is published:

```bash
npx -y @baiying/dlc-agent-mcp install-codex
```

Restart Codex, then ask:

```text
用 dlc-agent 查一下 ads_customer_revenue_daily 是不是核心表，有哪些字段，有没有质量监控
```
