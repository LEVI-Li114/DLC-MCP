#!/usr/bin/env node

const fs = require("node:fs");
const os = require("node:os");
const path = require("node:path");

const defaultGatewayUrl = "http://64.186.234.87:8787/mcp";
const gatewayUrl = process.env.DLC_MCP_GATEWAY_URL || defaultGatewayUrl;
const gatewayToken = process.env.DLC_MCP_GATEWAY_TOKEN || "";

if (process.argv[2] === "install-codex") {
  installCodex();
  process.exit(0);
}

runGatewayClient(gatewayUrl);

function runGatewayClient(url) {
  let buffer = "";
  let chain = Promise.resolve();
  process.stdin.setEncoding("utf8");
  process.stdin.on("data", (chunk) => {
    buffer += chunk;
    const lines = buffer.split("\n");
    buffer = lines.pop();
    for (const line of lines) {
      if (line.trim()) chain = chain.then(() => postMcp(url, line));
    }
  });
}

async function postMcp(url, line) {
  try {
    const headers = { "content-type": "application/json" };
    if (gatewayToken) headers.authorization = `Bearer ${gatewayToken}`;
    const response = await fetch(url, {
      method: "POST",
      headers,
      body: line,
    });
    const text = await response.text();
    if (text.trim()) process.stdout.write(text.trim() + "\n");
  } catch (error) {
    process.stdout.write(JSON.stringify({ jsonrpc: "2.0", id: null, error: { code: -32000, message: String(error.message || error) } }) + "\n");
  }
}

function installCodex() {
  const codexDir = path.join(os.homedir(), ".codex");
  const configPath = path.join(codexDir, "config.toml");
  fs.mkdirSync(codexDir, { recursive: true });
  const current = fs.existsSync(configPath) ? fs.readFileSync(configPath, "utf8") : "";
  const next = replaceBlock(current, codexBlock()).trimEnd() + "\n";
  fs.writeFileSync(configPath, next);
  console.log(`Installed dlc-mcp MCP in ${configPath}`);
  console.log("Restart Codex, then ask with dlc-mcp directly. Do not ask Codex to run curl or shell commands for data queries.");
}

function codexBlock() {
  let block = `[mcp_servers.dlc-mcp]
command = "npx"
args = ["-y", "@levisli/dlc-mcp"]
type = "stdio"
`;
  block += `
[mcp_servers.dlc-mcp.env]
DLC_MCP_GATEWAY_URL = "${gatewayUrl}"
`;
  if (gatewayToken) {
    block += `DLC_MCP_GATEWAY_TOKEN = "${gatewayToken}"
`;
  }
  return block;
}

function replaceBlock(text, block) {
  const start = text.indexOf("[mcp_servers.dlc-mcp]");
  if (start === -1) return `${text.trimEnd()}\n\n${block}`;
  const rest = text.slice(start + "[mcp_servers.dlc-mcp]".length);
  const nextHeader = rest.search(/\n\[(?!mcp_servers\.dlc-mcp\.env\])[^\]]+\]/);
  const end = nextHeader === -1 ? text.length : start + "[mcp_servers.dlc-mcp]".length + nextHeader + 1;
  return `${text.slice(0, start).trimEnd()}\n\n${block}\n${text.slice(end).trimStart()}`.trimEnd() + "\n";
}
