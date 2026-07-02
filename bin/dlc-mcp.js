#!/usr/bin/env node

const { spawn } = require("node:child_process");
const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

if (process.argv[2] === "install-codex") {
  installCodex();
  process.exit(0);
}

const host = process.env.DLC_MCP_SSH_HOST || "data-agent-host";
const remoteDir = process.env.DLC_MCP_REMOTE_DIR || "/opt/dlc-mcp/DLC-MCP";
const db = process.env.DLC_MCP_DB || "/data/dlc-mcp/assets.db";
const python = process.env.DLC_MCP_PYTHON || "python3";

const child = host
  ? spawn("ssh", [host, `cd ${remoteDir} && DLC_MCP_DB=${db} ${python} -m dlc_mcp.server`], { stdio: "inherit" })
  : spawn(python, ["-m", "dlc_mcp.server"], {
      cwd: path.resolve(__dirname, ".."),
      env: process.env,
      stdio: "inherit",
    });

child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  process.exit(code || 0);
});

function installCodex() {
  const codexDir = path.join(os.homedir(), ".codex");
  const configPath = path.join(codexDir, "config.toml");
  fs.mkdirSync(codexDir, { recursive: true });
  const current = fs.existsSync(configPath) ? fs.readFileSync(configPath, "utf8") : "";
  const next = replaceBlock(current, codexBlock()).trimEnd() + "\n";
  fs.writeFileSync(configPath, next);
  console.log(`Installed dlc-mcp MCP in ${configPath}`);
}

function codexBlock() {
  return `[mcp_servers.dlc-mcp]
command = "npx"
args = ["-y", "@baiying/dlc-mcp"]
type = "stdio"
`;
}

function replaceBlock(text, block) {
  const start = text.indexOf("[mcp_servers.dlc-mcp]");
  if (start === -1) return `${text.trimEnd()}\n\n${block}`;
  const rest = text.slice(start + "[mcp_servers.dlc-mcp]".length);
  const nextHeader = rest.search(/\n\[[^\]]+\]/);
  const end = nextHeader === -1 ? text.length : start + "[mcp_servers.dlc-mcp]".length + nextHeader + 1;
  return `${text.slice(0, start).trimEnd()}\n\n${block}\n${text.slice(end).trimStart()}`.trimEnd() + "\n";
}
