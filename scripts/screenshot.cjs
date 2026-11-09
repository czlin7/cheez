// Render a Cheez page at phone and laptop widths, light and dark, and report overflow.
// Usage: node scripts/screenshot.cjs <page.html> <outdir>
const { chromium } = require("playwright");
const path = require("node:path");
const fs = require("node:fs");

const [, , page, outdir = "screenshots"] = process.argv;
if (!page) { console.error("usage: node scripts/screenshot.cjs <page.html> [outdir]"); process.exit(2); }
fs.mkdirSync(outdir, { recursive: true });
const url = "file://" + path.resolve(page);
(async () => {
const browser = await chromium.launch();
const results = [];
for (const [name, width, height] of [["phone", 390, 844], ["laptop", 1280, 900]]) {
  for (const scheme of ["light", "dark"]) {
    const ctx = await browser.newContext({ viewport: { width, height }, colorScheme: scheme, deviceScaleFactor: 2 });
    const p = await ctx.newPage();
    const errors = [];
    p.on("pageerror", (e) => errors.push(String(e)));
    p.on("console", (m) => { if (m.type() === "error") errors.push(m.text()); });
    await p.goto(url, { waitUntil: "networkidle" });
    const metrics = await p.evaluate(() => {
      const de = document.documentElement;
      const wide = [];
      for (const el of document.querySelectorAll("body *")) {
        const r = el.getBoundingClientRect();
        if (r.right > de.clientWidth + 1 && !el.closest(".tablewrap, .edbar nav, .pulse")) wide.push(el.tagName + "." + el.className);
      }
      return { scrollWidth: de.scrollWidth, clientWidth: de.clientWidth, height: de.scrollHeight, wide: wide.slice(0, 8) };
    });
    const file = path.join(outdir, `${name}-${scheme}.png`);
    await p.screenshot({ path: file, fullPage: true });
    results.push({ name, scheme, ...metrics, errors, file });
    await ctx.close();
  }
}
await browser.close();
console.log(JSON.stringify(results, null, 1));
})();
