#!/usr/bin/env node

const { spawn } = require("node:child_process");

const args = ["-m", "dlc_mcp.webhook", ...process.argv.slice(2)];
const child = spawn(process.env.PYTHON || "python3", args, { stdio: "inherit" });
child.on("exit", (code, signal) => {
  if (signal) process.kill(process.pid, signal);
  else process.exit(code ?? 1);
});
