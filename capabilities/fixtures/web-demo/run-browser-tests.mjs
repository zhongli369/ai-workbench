#!/usr/bin/env node
/**
 * run-browser-tests.mjs — real-browser regression for the web-demo fixture.
 *
 * Three tests, all against a real Chromium launched by Playwright:
 *   T1 button event     : click changes DOM state (text + data-state + counter)
 *   T2 layout defect    : narrow viewport reproduces the overflow bug, the same
 *                         HTML with styles.fixed.css verified fixed
 *   T3 slider drag      : real pointer drag changes value, fires input+change,
 *                         and the page stays interactive afterwards
 *
 * Honesty note printed by every run: the "mobile" pass is a DESKTOP Chromium
 * with a mobile viewport/UA/touch emulation. That is NOT a real Android/iOS
 * device; no physical device was involved. It catches layout and event bugs,
 * not device-specific rendering, scrolling physics, or real touch latency.
 *
 * Usage (needs a Playwright install — the @playwright/mcp package bundles one):
 *   node run-browser-tests.mjs --playwright-root <dir containing node_modules/playwright-core>
 *   node run-browser-tests.mjs --pw-root <dir> --headed --keep-evidence
 * Exit: 0 all tests pass; 1 a test failed; 2 setup error.
 */
import { createRequire } from "node:module";
import { createServer } from "node:http";
import { cp, mkdir, readFile, writeFile } from "node:fs/promises";
import { existsSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { tmpdir } from "node:os";
import process from "node:process";

const HERE = dirname(fileURLToPath(import.meta.url));
const argv = process.argv.slice(2);
const arg = (n, d = null) => {
  const i = argv.indexOf(n);
  return i >= 0 && i + 1 < argv.length ? argv[i + 1] : d;
};
const headed = argv.includes("--headed");
const pwRoot = resolve(arg("--playwright-root", arg("--pw-root", process.env.AIWB_PLAYWRIGHT_ROOT || "")));
if (!pwRoot || !existsSync(join(pwRoot, "node_modules"))) {
  console.error("需要 --playwright-root <含 node_modules 的目录> (安装 @playwright/mcp 的项目目录)");
  process.exit(2);
}
const require = createRequire(join(pwRoot, "aiwb-resolve-anchor.js"));
const { chromium } = require("playwright-core");
// Default: the Playwright-downloaded chromium. --channel chrome|msedge uses a
// system browser instead (launch() still spins up a throwaway profile — a real
// browser profile is never opened or read).
const channel = arg("--channel", null);

const MOBILE = { width: 375, height: 812 };
const DESKTOP = { width: 1280, height: 800 };
const EVID = join(HERE, "evidence");

// ---------------------------------------------------------------- static server
const MIME = { ".html": "text/html; charset=utf-8", ".css": "text/css; charset=utf-8",
               ".js": "text/javascript; charset=utf-8", ".png": "image/png" };

async function buildFixedCopy() {
  const dir = join(tmpdir(), `aiwb-web-demo-fixed-${Date.now()}`);
  await mkdir(dir, { recursive: true });
  await cp(join(HERE, "index.html"), join(dir, "index.html"));
  await cp(join(HERE, "styles.fixed.css"), join(dir, "styles.css"));
  return dir;
}

function serve(roots) {
  const server = createServer(async (req, res) => {
    try {
      const url = new URL(req.url, "http://127.0.0.1");
      let path = url.pathname;
      let root = roots.main;
      for (const [prefix, dir] of Object.entries(roots.alias ?? {})) {
        if (path === prefix || path.startsWith(prefix + "/")) {
          root = dir;
          path = path.slice(prefix.length) || "/";
          break;
        }
      }
      if (path === "/" || path === "") path = "/index.html";
      const full = join(root, path.replace(/^\/+/, ""));
      if (!full.startsWith(root)) { res.writeHead(403).end("forbidden"); return; }
      const body = await readFile(full);
      res.writeHead(200, { "content-type": MIME[full.slice(full.lastIndexOf("."))] ?? "application/octet-stream",
                           "cache-control": "no-store" });
      res.end(body);
    } catch {
      res.writeHead(404).end("not found");
    }
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

// ---------------------------------------------------------------- assertions
const results = [];
function check(test, name, pass, detail) {
  results.push({ test, name, pass: Boolean(pass), detail });
  console.log(`  ${pass ? "PASS" : "FAIL"}  [${test}] ${name}${detail ? " — " + detail : ""}`);
}

async function layout(page) {
  return page.evaluate(() => {
    const rect = (sel) => {
      const el = document.querySelector(sel);
      if (!el) return null;
      const r = el.getBoundingClientRect();
      return { left: Math.round(r.left), right: Math.round(r.right), top: Math.round(r.top),
               width: Math.round(r.width) };
    };
    return {
      innerWidth: window.innerWidth,
      scrollWidth: document.documentElement.scrollWidth,
      innerHeight: window.innerHeight,
      scrollHeight: document.documentElement.scrollHeight,
      export: rect("#export"), toolbar: rect("#toolbar"), cards: rect("#cards"),
      cardCount: document.querySelectorAll(".card").length,
      firstCardTop: document.querySelector(".card")?.getBoundingClientRect().top ?? -1,
      lastCardTop: document.querySelector(".card:last-child")?.getBoundingClientRect().top ?? -1,
      bodyBg: getComputedStyle(document.body).backgroundColor,
    };
  });
}

const overflowed = (m) => m.scrollWidth > m.innerWidth + 1;
// Measured against the DEVICE width, not innerWidth: under mobile emulation an
// overflowing page widens the layout viewport (375 -> 1012 here) instead of
// scrolling, so `scrollWidth > innerWidth` is blind to the very bug we hunt.
const exceedsDevice = (m, devWidth) =>
  [m.export, m.toolbar, m.cards].filter((r) => r && r.right > devWidth + 1);

// ---------------------------------------------------------------- the suite
async function main() {
  await mkdir(EVID, { recursive: true });
  const fixedDir = await buildFixedCopy();
  const server = await serve({ main: HERE, alias: { "/fixed": fixedDir } });
  const base = `http://127.0.0.1:${server.address().port}`;
  const browser = await chromium.launch({ headless: !headed, ...(channel ? { channel } : {}) });
  const engine = channel ? `${channel} (system, throwaway profile)` : "bundled chromium";
  const report = { base, engine, browserVersion: browser.version(), tests: {},
                   evidence: {}, resultCounts: {} };
  console.log(`引擎: ${engine} — ${browser.version()}\n`);

  try {
    // ---------------- T1: button event ----------------
    console.log("T1 按钮事件");
    const ctx1 = await browser.newContext({ viewport: DESKTOP });
    const p1 = await ctx1.newPage();
    const errors = [];
    const consoleErrors = [];
    p1.on("pageerror", (e) => errors.push(String(e)));
    p1.on("console", (m) => { if (m.type() === "error") consoleErrors.push(m.text()); });
    await p1.goto(`${base}/index.html`, { waitUntil: "load" });
    const before = await p1.evaluate(() => ({
      text: document.querySelector("#cta").textContent.trim(),
      state: document.querySelector("#cta").dataset.state,
      counter: document.querySelector("#counter").textContent.trim(),
    }));
    await p1.click("#cta");
    const after = await p1.evaluate(() => ({
      text: document.querySelector("#cta").textContent.trim(),
      state: document.querySelector("#cta").dataset.state,
      counter: document.querySelector("#counter").textContent.trim(),
    }));
    check("T1", "点击前按钮为 idle", before.state === "idle" && before.counter === "已保存 0 次",
          JSON.stringify(before));
    check("T1", "点击后 text/data-state/counter 全部变化",
          after.state === "saved" && after.text !== before.text &&
          after.counter === "已保存 1 次", JSON.stringify(after));
    check("T1", "无未捕获页面错误", errors.length === 0, errors.join("; "));
    check("T1", "无 console error (favicon 404 之类的也只记录不隐藏)",
          consoleErrors.length === 0, consoleErrors.join("; "));
    report.tests.T1 = { before, after, errors, consoleErrors };
    await p1.screenshot({ path: join(EVID, "t1-desktop-click.png") });
    report.evidence.T1 = "evidence/t1-desktop-click.png";

    // ---------------- T2: responsive layout defect ----------------
    console.log("T2 布局缺陷 (桌面正常 / 窄屏错位 / 修 CSS 后正常)");
    const dctx = await browser.newContext({ viewport: DESKTOP });
    const dp = await dctx.newPage();
    await dp.goto(`${base}/index.html`, { waitUntil: "load" });
    const deskBefore = await layout(dp);
    await dp.screenshot({ path: join(EVID, "t2-desktop.png") });
    check("T2", "桌面 1280px 无横向溢出", !overflowed(deskBefore),
          `scrollWidth=${deskBefore.scrollWidth} innerWidth=${deskBefore.innerWidth}`);
    check("T2", "桌面三张卡片同一行 (>=3 列)",
          deskBefore.firstCardTop === deskBefore.lastCardTop && deskBefore.cardCount === 3,
          `top=${deskBefore.firstCardTop}/${deskBefore.lastCardTop}`);

    // Two narrow modes, because they fail differently:
    //   (a) plain 375px viewport  -> document scrolls horizontally
    //   (b) mobile emulation      -> layout viewport widens past the device width
    const narrow = async (ctxOpts, tag, shot) => {
      const ctx = await browser.newContext(ctxOpts);
      const p = await ctx.newPage();
      await p.goto(`${base}/index.html`, { waitUntil: "load" });
      const broken = await layout(p);
      if (shot) await p.screenshot({ path: join(EVID, shot.before) });
      await p.goto(`${base}/fixed/index.html`, { waitUntil: "load" });
      const fixed = await layout(p);
      if (shot) await p.screenshot({ path: join(EVID, shot.after) });
      await ctx.close();
      check("T2", `${tag}: 复现缺陷 — 内容按 1000px 排布, 越出 375px 设备宽度`,
            exceedsDevice(broken, MOBILE.width).length >= 2 &&
            Math.max(broken.scrollWidth, broken.innerWidth) >= 1000,
            `innerWidth=${broken.innerWidth} scrollWidth=${broken.scrollWidth} 越界元素=` +
            exceedsDevice(broken, MOBILE.width).map((r) => r.right).join("/"));
      check("T2", `${tag}: 同一 HTML + styles.fixed.css — 回到设备宽度且无越界`,
            exceedsDevice(fixed, MOBILE.width).length === 0 &&
            fixed.innerWidth <= MOBILE.width + 1 && !overflowed(fixed),
            `innerWidth=${fixed.innerWidth} scrollWidth=${fixed.scrollWidth}`);
      check("T2", `${tag}: 修复只改布局, 未换皮 (body 背景一致)`,
            broken.bodyBg === fixed.bodyBg, broken.bodyBg);
      return { broken, fixed };
    };

    const plainNarrow = await narrow({ viewport: MOBILE }, "窄屏(桌面引擎)", null);
    const mobileEmu = await narrow({
      viewport: MOBILE, deviceScaleFactor: 2, isMobile: true, hasTouch: true,
      userAgent: "Mozilla/5.0 (Linux; Android 14; Pixel 7) AppleWebKit/537.36 (KHTML, like Gecko) " +
                 "Chrome/140.0.0.0 Mobile Safari/537.36",
    }, "窄屏(移动模拟)", { before: "t2-before-mobile-broken.png", after: "t2-after-mobile-fixed.png" });
    check("T2", "窄屏(桌面引擎) 文档横向溢出 (scrollWidth > innerWidth)",
          overflowed(plainNarrow.broken) && !overflowed(plainNarrow.fixed),
          `broken ${plainNarrow.broken.scrollWidth}/${plainNarrow.broken.innerWidth} -> ` +
          `fixed ${plainNarrow.fixed.scrollWidth}/${plainNarrow.fixed.innerWidth}`);
    report.evidence.T2_before = "evidence/t2-before-mobile-broken.png";
    report.evidence.T2_after = "evidence/t2-after-mobile-fixed.png";
    report.tests.T2 = { desktop: deskBefore, plain_narrow: plainNarrow, mobile_emu: mobileEmu };
    await dctx.close();

    // ---------------- T3: slider drag ----------------
    console.log("T3 滑动条拖动");
    const ctx3 = await browser.newContext({ viewport: DESKTOP });
    const p3 = await ctx3.newPage();
    await p3.goto(`${base}/index.html`, { waitUntil: "load" });
    const start = await p3.inputValue("#zoom");
    const box = await p3.locator("#zoom").boundingBox();
    const y = box.y + box.height / 2;
    await p3.mouse.move(box.x + box.width * 0.3, y);
    await p3.mouse.down();
    for (const f of [0.45, 0.6, 0.72, 0.8]) {
      await p3.mouse.move(box.x + box.width * f, y, { steps: 6 });
    }
    await p3.mouse.up();
    const drag = await p3.evaluate(() => ({
      value: document.querySelector("#zoom").value,
      out: document.querySelector("#zoom-out").textContent.trim(),
      input: Number(document.querySelector("#eventlog").dataset.input),
      change: Number(document.querySelector("#eventlog").dataset.change),
    }));
    check("T3", "拖动后值改变", Number(drag.value) > Number(start) + 20,
          `value ${start} -> ${drag.value}`);
    check("T3", "input 事件触发", drag.input >= 1, `input=${drag.input}`);
    check("T3", "change 事件触发 (鼠标释放)", drag.change >= 1, `change=${drag.change}`);
    check("T3", "显示值跟随", drag.out === `${drag.value}%`, drag.out);
    await p3.click("#cta");
    const afterDrag = await p3.evaluate(() => document.querySelector("#counter").textContent.trim());
    check("T3", "拖动后其他按钮仍可交互", afterDrag === "已保存 1 次", afterDrag);
    await p3.screenshot({ path: join(EVID, "t3-slider.png") });
    report.evidence.T3 = "evidence/t3-slider.png";
    report.tests.T3 = { start, drag, counterAfterDrag: afterDrag };
    await ctx3.close();
  } finally {
    await browser.close();
    server.close();
  }

  const failed = results.filter((r) => !r.pass);
  report.resultCounts = { pass: results.length - failed.length, fail: failed.length };
  report.failures = failed;
  await writeFile(join(EVID, "last-run.json"), JSON.stringify(report, null, 2), "utf8");
  console.log(`\n结果: ${report.resultCounts.pass} pass / ${report.resultCounts.fail} fail`);
  console.log("诚实标注: 窄屏测试是桌面 Chromium 的移动视口模拟(含 UA/touch), " +
              "不是真实 Android/iOS 真机; 未验证真机渲染、滚动物理与真实触摸延迟。");
  process.exit(failed.length === 0 ? 0 : 1);
}

main().catch((e) => { console.error("SETUP ERROR:", e); process.exit(2); });
