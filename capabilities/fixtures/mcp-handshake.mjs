#!/usr/bin/env node
/**
 * mcp-handshake.mjs — minimal MCP stdio client used as REAL-CONNECTION evidence.
 *
 * Speaks exactly what Claude Code speaks to a stdio MCP server: newline-delimited
 * JSON-RPC 2.0 on stdin/stdout, starting with `initialize`, then the
 * `notifications/initialized` notification, then `tools/list`. Records the real
 * server responses and kills the whole process tree afterwards.
 *
 * The point of this script is honesty: it spawns the SAME argv that
 * tools/wiring_mcp.py writes into .mcp.json, so a pass here means that command
 * line really is an MCP server (not that some other spelling is).
 *
 * Usage:
 *   node mcp-handshake.mjs --argv-json '["cmd","/c","npx","-y","@playwright/mcp@0.0.83","--headless"]'
 *   node mcp-handshake.mjs --cli C:/path/to/@playwright/mcp/cli.js [--extra "--headless"]
 *   node mcp-handshake.mjs ... --cwd <dir> --timeout-ms 90000 --json
 *
 * Exit codes: 0 handshake OK; 1 handshake failed; 2 usage/transport error.
 */
import { spawn } from "node:child_process";
import process from "node:process";

const argv = process.argv.slice(2);
function flag(name, dflt = null) {
  const i = argv.indexOf(name);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : dflt;
}
const asJson = argv.includes("--json");
const timeoutMs = Number(flag("--timeout-ms", "90000"));
const cwd = flag("--cwd", process.cwd());

let childArgv;
const argvJson = flag("--argv-json");
if (argvJson) {
  childArgv = JSON.parse(argvJson);
} else {
  const cli = flag("--cli");
  if (!cli) {
    console.error("usage: node mcp-handshake.mjs --argv-json '<json array>' | --cli <cli.js>");
    process.exit(2);
  }
  childArgv = [process.execPath, cli, "--headless", "--isolated", "--browser", "chromium"];
}

const started = Date.now();
const child = spawn(childArgv[0], childArgv.slice(1), {
  cwd, stdio: ["pipe", "pipe", "pipe"], windowsHide: true,
});

const stderrTail = [];
child.stderr.setEncoding("utf8");
child.stderr.on("data", (chunk) => {
  for (const line of chunk.split(/\r?\n/)) if (line.trim()) stderrTail.push(line.trim());
  while (stderrTail.length > 8) stderrTail.shift();
});

let stdoutBuf = "";
const inbox = [];
const waiters = [];
child.stdout.setEncoding("utf8");
child.stdout.on("data", (chunk) => {
  stdoutBuf += chunk;
  let nl;
  while ((nl = stdoutBuf.indexOf("\n")) >= 0) {
    const line = stdoutBuf.slice(0, nl).trim();
    stdoutBuf = stdoutBuf.slice(nl + 1);
    if (!line) continue;
    let obj;
    try { obj = JSON.parse(line); } catch { inbox.push({ _raw: line }); continue; }
    inbox.push(obj);
  }
});
let exited = false;
child.on("exit", (code, signal) => { exited = true; inbox.push({ _exit: { code, signal } }); });

function waitFor(pred, ms, what) {
  return new Promise((resolve, reject) => {
    const deadline = Date.now() + ms;
    const scan = () => {
      const hit = inbox.find((o) => pred(o));
      if (hit) return resolve(hit);
      if (exited && !inbox.some((o) => pred(o))) {
        return reject(new Error(`${what}: child exited before responding`));
      }
      if (Date.now() > deadline) return reject(new Error(`${what}: timeout after ${ms}ms`));
      const t = setTimeout(scan, 25);
      waiters.push(t);
    };
    scan();
  });
}

function send(obj) {
  child.stdin.write(JSON.stringify(obj) + "\n");
}

function killTree() {
  if (child.exitCode !== null) return;
  if (process.platform === "win32") {
    spawn("taskkill", ["/PID", String(child.pid), "/T", "/F"], { windowsHide: true });
  } else {
    try { process.kill(-child.pid, "SIGTERM"); } catch { child.kill("SIGTERM"); }
  }
}

const report = { argv: childArgv, cwd, pid: child.pid, ok: false, steps: {} };

try {
  send({
    jsonrpc: "2.0", id: 1, method: "initialize",
    params: {
      protocolVersion: "2025-06-18", capabilities: {},
      clientInfo: { name: "aiwb-mcp-handshake", version: "1.0.0" },
    },
  });
  const init = await waitFor((o) => o.id === 1, timeoutMs, "initialize");
  report.steps.initialize = {
    ok: !init.error,
    protocolVersion: init.result?.protocolVersion,
    serverInfo: init.result?.serverInfo,
    capabilities: Object.keys(init.result?.capabilities ?? {}),
    error: init.error ?? null,
  };

  send({ jsonrpc: "2.0", method: "notifications/initialized" });
  send({ jsonrpc: "2.0", id: 2, method: "tools/list", params: {} });
  const list = await waitFor((o) => o.id === 2, timeoutMs, "tools/list");
  const tools = list.result?.tools ?? [];
  report.steps.tools_list = {
    ok: !list.error && tools.length > 0,
    count: tools.length,
    names: tools.slice(0, 12).map((t) => t.name),
    error: list.error ?? null,
  };
  report.ok = report.steps.initialize.ok && report.steps.tools_list.ok;

  // Optional: real tool calls (proves the server drives a browser, not just that
  // it answers a handshake). --call '[{"name":"browser_navigate","arguments":{...}}]'
  const callsJson = flag("--call");
  if (callsJson) {
    const calls = JSON.parse(callsJson);
    report.steps.tool_calls = [];
    let id = 100;
    for (const c of calls) {
      id += 1;
      send({ jsonrpc: "2.0", id, method: "tools/call",
             params: { name: c.name, arguments: c.arguments ?? {} } });
      let resp;
      try {
        resp = await waitFor((o) => o.id === id, Math.max(timeoutMs, 120000), `tools/call ${c.name}`);
      } catch (err) {
        report.steps.tool_calls.push({ name: c.name, ok: false, error: String(err.message) });
        report.ok = false;
        continue;
      }
      const text = (resp.result?.content ?? []).map((b) => b.text ?? `[${b.type}]`).join("\n");
      report.steps.tool_calls.push({
        name: c.name, ok: !resp.error && !resp.result?.isError,
        error: resp.error ?? null,
        text_head: text.slice(0, 300),
        text_len: text.length,
      });
      if (resp.error || resp.result?.isError) report.ok = false;
    }
  }
} catch (err) {
  report.error = String(err.message ?? err);
} finally {
  report.stderr_tail = stderrTail.slice(-4);
  report.elapsed_ms = Date.now() - started;
  killTree();
  await new Promise((r) => setTimeout(r, 500));
  report.child_alive_after_kill = child.exitCode === null;
  for (const t of waiters) clearTimeout(t);
}

if (asJson) {
  console.log(JSON.stringify(report, null, 2));
} else {
  console.log(`argv        : ${report.argv.join(" ")}`);
  console.log(`server      : ${report.steps.initialize?.serverInfo?.name ?? "?"} ` +
              `${report.steps.initialize?.serverInfo?.version ?? "?"} ` +
              `(protocol ${report.steps.initialize?.protocolVersion ?? "?"})`);
  console.log(`tools/list  : ${report.steps.tools_list?.count ?? 0} tools` +
              `  e.g. ${(report.steps.tools_list?.names ?? []).slice(0, 5).join(", ")}`);
  for (const c of report.steps.tool_calls ?? []) {
    console.log(`tools/call  : ${c.name} -> ${c.ok ? "OK" : "FAIL"}` +
                (c.text_head ? ` — ${c.text_head.split("\n")[0]}` : ""));
  }
  console.log(`elapsed_ms  : ${report.elapsed_ms}`);
  console.log(`verdict     : ${report.ok ? "HANDSHAKE OK" : "HANDSHAKE FAILED"}` +
              (report.error ? ` — ${report.error}` : ""));
  if (report.stderr_tail?.length) console.log(`stderr_tail : ${report.stderr_tail.join(" | ")}`);
}
process.exit(report.ok ? 0 : 1);
