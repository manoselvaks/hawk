// Screenshot the built site: main pages at desktop and phone width, light and dark.
//
//   NODE_PATH="$(npm root -g)" node scripts/screenshots.cjs site/_build docs/screenshots
//
// Needs the `playwright` package and a Chromium it can launch. Serves the build
// directory itself on a free local port, so no other server is needed.
"use strict";
const http = require("http");
const fs = require("fs");
const path = require("path");
const { chromium } = require("playwright");

const [root = "site/_build", outDir = "docs/screenshots", member = "huw-pill"] = process.argv.slice(2);
const TYPES = { ".html": "text/html", ".css": "text/css", ".js": "text/javascript", ".json": "application/json", ".svg": "image/svg+xml", ".png": "image/png" };

const PAGES = [
  ["home", ""],
  ["speeches", "speeches/"],
  ["speech-detail", "speeches/#doc=__FIRST_MPC__"],
  ["members", "members/"],
  ["member", `members/${member}/`],
  ["findings", "findings/"],
  ["methodology", "methodology/"],
];
const VIEWPORTS = [
  ["desktop", { width: 1440, height: 1000 }, 1],
  ["phone", { width: 390, height: 844 }, 2],
];

function serve(dir) {
  const server = http.createServer((req, res) => {
    let p = decodeURIComponent(new URL(req.url, "http://x").pathname);
    let file = path.join(dir, p);
    if (fs.existsSync(file) && fs.statSync(file).isDirectory()) file = path.join(file, "index.html");
    if (!file.startsWith(path.resolve(dir)) || !fs.existsSync(file)) { res.writeHead(404); res.end(); return; }
    res.writeHead(200, { "Content-Type": TYPES[path.extname(file)] || "application/octet-stream" });
    fs.createReadStream(file).pipe(res);
  });
  return new Promise((ok) => server.listen(0, "127.0.0.1", () => ok(server)));
}

(async () => {
  const dir = path.resolve(root);
  fs.mkdirSync(outDir, { recursive: true });
  const server = await serve(dir);
  const base = `http://127.0.0.1:${server.address().port}/`;
  const docs = JSON.parse(fs.readFileSync(path.join(dir, "data/docs.json"), "utf8"));
  const c = Object.fromEntries(docs.columns.map((k, i) => [k, i]));
  const first = docs.rows.slice().reverse().find((r) => r[c.mpc] === 1 && r[c.stance] != null && r[c.reason]);
  const browser = await chromium.launch(process.env.CHROMIUM_PATH ? { executablePath: process.env.CHROMIUM_PATH } : {});
  for (const [vp, size, scale] of VIEWPORTS) {
    for (const scheme of ["light", "dark"]) {
      const ctx = await browser.newContext({ viewport: size, deviceScaleFactor: scale, colorScheme: scheme, locale: "en-GB", reducedMotion: "reduce" });
      const page = await ctx.newPage();
      for (const [name, rel] of PAGES) {
        await page.goto(base + rel.replace("__FIRST_MPC__", first[c.id]), { waitUntil: "networkidle" });
        await page.waitForTimeout(300);
        const file = path.join(outDir, `${name}-${vp}-${scheme}.png`);
        await page.screenshot({ path: file, fullPage: name === "home" && vp === "desktop" && scheme === "light" });
        console.log("wrote", file);
      }
      await ctx.close();
    }
  }
  await browser.close();
  server.close();
})().catch((e) => { console.error(e); process.exit(1); });
