// UI-path + CDN-default test: no ?pyodide override, real file input, screenshot.
// Env (defaults match browser_runner.mjs): CHROMIUM_BIN, UI_TEST_SAMPLE (a corpus
// .iamf to feed the file input), UI_TEST_SHOT (screenshot output path).
import { chromium } from 'playwright';

const CHROMIUM = process.env.CHROMIUM_BIN || 'chromium';
const SAMPLE = process.env.UI_TEST_SAMPLE || 'corpus/corrupt/f4_coupled_wrong_7_1_4.iamf';
const SHOT = process.env.UI_TEST_SHOT || 'inspector_screenshot.png';

const browser = await chromium.launch({
  executablePath: CHROMIUM,
  args: ['--no-sandbox'],
});
const page = await browser.newPage({ viewport: { width: 1180, height: 900 } });
const errs = [];
page.on('pageerror', e => errs.push(String(e)));
// 1) CDN-default graceful-failure check (both CDNs are outside this sandbox's allowlist)
await page.goto('http://127.0.0.1:8765/iamf-inspector.html');
await page.waitForFunction(() => document.getElementById('status').className !== '', null, { timeout: 240000 });
console.log('CDN-default status:', (await page.textContent('#status')).trim(),
            '| class:', await page.getAttribute('#status', 'class'));

// 2) UI path on the local runtime
const t0 = Date.now();
await page.goto('http://127.0.0.1:8765/iamf-inspector.html?pyodide=/node_modules/pyodide/');
let cdnOk = true;
try {
  await page.waitForFunction(() => window.runtimeReady && window.runtimeReady(), null, { timeout: 240000 });
} catch { cdnOk = false; }
console.log('local boot:', cdnOk ? `OK in ${Date.now() - t0} ms` : 'FAILED');
if (cdnOk) {
  await page.setInputFiles('#file', SAMPLE);
  await page.waitForSelector('#summary table', { timeout: 60000 });
  console.log('UI summary:', (await page.textContent('#summary h2')).trim().replace(/\s+/g, ' '));
  const rows = await page.$$eval('#summary table tr td.mono', tds => tds.map(t => t.textContent));
  console.log('UI check ids:', rows.join(','));
  await page.screenshot({ path: SHOT });
}
console.log('pageErrors:', errs.length);
await browser.close();
