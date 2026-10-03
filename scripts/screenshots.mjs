#!/usr/bin/env node
/**
 * Deterministic UI screenshots: headless Chrome driven over the DevTools protocol (no extra dependency; Node >= 22).
 * Real device emulation (phone widths are laid out at their true width), motion forced off so every frame is the settled state, and each
 * page addressed by URL (?theme=, ?open= drawers, ?tab=) so a capture can be reproduced exactly.
 *
 *   node scripts/screenshots.mjs OUT_DIR [BASE_URL]
 *   SIZES="1440x900 1024x768 390x844" THEMES="light dark" HERO=sig_90ee2542ae node scripts/screenshots.mjs docs/screenshots http://127.0.0.1:8000
 */
import { spawn } from "node:child_process";
import { mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const OUT = process.argv[2];
const BASE = process.argv[3] ?? "http://127.0.0.1:8000";
if (!OUT) {
  console.error("usage: node scripts/screenshots.mjs OUT_DIR [BASE_URL]");
  process.exit(2);
}
const CHROME = process.env.CHROME ?? "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome";
const HERO = process.env.HERO ?? "sig_90ee2542ae";
const SIZES = (process.env.SIZES ?? "1440x900 390x844").split(" ");
const THEMES = (process.env.THEMES ?? "light").split(" ");
const ONLY = process.env.ONLY ? new RegExp(process.env.ONLY) : null;
const PORT = 9300 + Math.floor(Math.random() * 400);

const PAGES = [
  { name: "feed", path: "/", full: false },
  { name: "event-top", path: `/events/${HERO}`, full: false },
  { name: "event-full", path: `/events/${HERO}`, full: true },
  { name: "event-inputs", path: `/events/${HERO}?open=inputs`, full: false },
  { name: "event-math", path: `/events/${HERO}?open=math`, full: false },
  { name: "event-timeline-end", path: `/events/${HERO}#evidence`, full: false, run: "timelineEnd" },
  { name: "stress-full", path: `/stress?signal=${HERO}&run=1`, full: true },
  { name: "stress-drill", path: `/stress?signal=${HERO}&run=1`, full: false, run: "drill" },
  { name: "evidence-top", path: "/evidence", full: false },
  { name: "evidence-pipeline", path: "/evidence?tab=pipeline", full: true },
];

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

const userDataDir = mkdtempSync(join(tmpdir(), "eventshock-shots-"));
const chrome = spawn(CHROME, [`--remote-debugging-port=${PORT}`, "--headless=new", "--disable-gpu", "--hide-scrollbars", `--user-data-dir=${userDataDir}`, "about:blank"], { stdio: "ignore" });
process.on("exit", () => chrome.kill());

async function cdp() {
  for (let i = 0; i < 60; i++) {
    try {
      const t = await (await fetch(`http://127.0.0.1:${PORT}/json/new?about:blank`, { method: "PUT" })).json();
      const ws = new WebSocket(t.webSocketDebuggerUrl);
      await new Promise((res, rej) => {
        ws.onopen = res;
        ws.onerror = rej;
      });
      let id = 0;
      const pending = new Map();
      ws.onmessage = (m) => {
        const d = JSON.parse(m.data);
        if (d.id && pending.has(d.id)) {
          pending.get(d.id)(d);
          pending.delete(d.id);
        }
      };
      const send = (method, params = {}) =>
        new Promise((res, rej) => {
          const n = ++id;
          pending.set(n, (d) => (d.error ? rej(new Error(`${method}: ${d.error.message}`)) : res(d.result)));
          ws.send(JSON.stringify({ id: n, method, params }));
        });
      return { send, close: () => ws.close() };
    } catch {
      await sleep(250);
    }
  }
  throw new Error("could not reach Chrome");
}

const evalJs = async (c, expression) => (await c.send("Runtime.evaluate", { expression, awaitPromise: true, returnByValue: true })).result.value;

const ACTIONS = {
  // drag the timeline to its last moment (what the market did afterwards) and bring it into view
  timelineEnd: `(async()=>{const el=document.getElementById('tl-range'); if(!el) return 'no slider';
    const set=Object.getOwnPropertyDescriptor(HTMLInputElement.prototype,'value').set; set.call(el, el.max); el.dispatchEvent(new Event('input',{bubbles:true}));
    await new Promise(r=>setTimeout(r,300)); el.closest('.tl').scrollIntoView({block:'start'}); window.scrollBy(0,-120); return 'ok';})()`,
  // drill the stress breakdown: portfolio -> equities -> first issuer
  drill: `(async()=>{const w=(ms)=>new Promise(r=>setTimeout(r,ms));
    const b=[...document.querySelectorAll('.drill button')].find(x=>/Equities/.test(x.getAttribute('aria-label')||'')); if(!b) return 'no bar'; b.click(); await w(300);
    const i=[...document.querySelectorAll('.drill ul button')][0]; if(i){i.click(); await w(300);} document.querySelector('.drill').scrollIntoView({block:'start'}); window.scrollBy(0,-90); return 'ok';})()`,
};

mkdirSync(OUT, { recursive: true });
const c = await cdp();
await c.send("Page.enable");
await c.send("Runtime.enable");
let count = 0;
for (const theme of THEMES) {
  for (const sz of SIZES) {
    const [w, h] = sz.split("x").map(Number);
    await c.send("Emulation.setDeviceMetricsOverride", { width: w, height: h, deviceScaleFactor: 1, mobile: w < 500 });
    await c.send("Emulation.setEmulatedMedia", { features: [{ name: "prefers-reduced-motion", value: "reduce" }] });
    for (const p of PAGES) {
      const name = `${p.name}-${theme}-${sz}`;
      if (ONLY && !ONLY.test(name)) continue;
      const [pathOnly, hash = ""] = p.path.split("#");
      const url = `${BASE}${pathOnly}${pathOnly.includes("?") ? "&" : "?"}theme=${theme}${hash ? `#${hash}` : ""}`;
      await c.send("Page.navigate", { url: "about:blank" });
      await c.send("Page.navigate", { url });
      // settled = fonts ready, no skeleton, no busy region, nothing animating
      await sleep(900);
      for (let i = 0; i < 40; i++) {
        const busy = await evalJs(c, `document.fonts.status!=='loaded' || !!document.querySelector('.skeleton,[aria-busy="true"],[role=status][aria-label^="Loading"]')`);
        if (!busy) break;
        await sleep(250);
      }
      await sleep(700);
      if (p.run) await evalJs(c, ACTIONS[p.run]);
      await sleep(500);
      let clip;
      if (p.full) {
        const height = Math.min(await evalJs(c, "Math.max(document.documentElement.scrollHeight, document.body.scrollHeight)"), 9000);
        clip = { x: 0, y: 0, width: w, height, scale: 1 };
      }
      const shot = await c.send("Page.captureScreenshot", { format: "png", captureBeyondViewport: !!p.full, ...(clip ? { clip } : {}) });
      writeFileSync(join(OUT, `${name}.png`), Buffer.from(shot.data, "base64"));
      count++;
      console.log("captured", name);
    }
  }
}
console.log(`${count} screenshots in ${OUT}`);
c.close();
chrome.kill();
process.exit(0);
