// Browser side of the WASM differential: drive the inspector page in headless Chromium.
//
// Environment (all optional):
//   SENTINEL_OSS   sentinel-oss tree root (default: ../ of this file)
//   WASM_CORPUS    corpus root with valid/ + corrupt/ (default: $SENTINEL_OSS/corpus)
//   WP1_SAMPLES / WP3_SAMPLES  real-sample dirs
//   INSPECTOR_URL  page URL (default http://127.0.0.1:8765/iamf-inspector.html?pyodide=/node_modules/pyodide/)
//   CHROMIUM_BIN   chromium executable (default: /opt/pw-browsers/chromium-1194/chrome-linux/chrome)
//   WASM_OUT       output dir (default: cwd)
import { chromium } from 'playwright';
import { readFileSync, readdirSync, writeFileSync, existsSync } from 'fs';
import { join, basename, dirname } from 'path';
import { fileURLToPath } from 'url';

const HERE = dirname(fileURLToPath(import.meta.url));
const OSS = process.env.SENTINEL_OSS || dirname(HERE);
const CORPUS = process.env.WASM_CORPUS || join(OSS, 'corpus');
const WP1 = process.env.WP1_SAMPLES || '/tmp/sentinel_build/wp1/wp1-samples';
const WP3 = process.env.WP3_SAMPLES || '/tmp/sentinel_build/wp3/wp3-samples';
const OUT = process.env.WASM_OUT || process.cwd();
const URL = process.env.INSPECTOR_URL ||
  'http://127.0.0.1:8765/iamf-inspector.html?pyodide=/node_modules/pyodide/';

const cases = [];
for (const d of ['valid', 'corrupt']) {
  const dd = join(CORPUS, d);
  if (existsSync(dd))
    for (const f of readdirSync(dd).sort()) cases.push([join(dd, f), 'generic']);
}
for (const f of ['stereo_ffmpeg.iamf', 'stereo_iamftools.iamf', 'youtube_candidate_5dot1.mp4']) {
  const p = join(WP1, f);
  if (existsSync(p)) cases.push([p, 'generic']);
}
for (const f of ['cd_bed_stereo.iamf', 'dlb_obj_static1.iamf']) {
  const p = join(WP3, f);
  if (existsSync(p)) cases.push([p, 'generic']);
}
{
  const yt = join(WP1, 'youtube_candidate_5dot1.mp4');
  if (existsSync(yt)) cases.push([yt, 'youtube']);
}

const browser = await chromium.launch({
  executablePath: process.env.CHROMIUM_BIN || '/opt/pw-browsers/chromium-1194/chrome-linux/chrome',
  args: ['--no-sandbox'],
});
const page = await browser.newPage();
const pageErrors = [];
page.on('pageerror', e => pageErrors.push(String(e)));
page.on('console', m => { if (m.type() === 'error') pageErrors.push('console: ' + m.text()); });

const t0 = Date.now();
await page.goto(URL);
await page.waitForFunction(() => window.runtimeReady && window.runtimeReady(), null, { timeout: 180000 });
const bootMs = Date.now() - t0;

const out = {}, timings = {};
for (const [path, profile] of cases) {
  const name = basename(path);
  const b64 = readFileSync(path).toString('base64');
  const res = JSON.parse(await page.evaluate(
    ([n, b, p]) => window.validateFile(n, b, p), [name, b64, profile]));
  out[`${name}::${profile}`] = JSON.parse(res.json);
  timings[`${name}::${profile}`] = { ms: res.ms, numpy_loaded: res.numpy_loaded, exit_code: res.exit_code };
}
writeFileSync(join(OUT, 'browser_reports.json'), JSON.stringify(out, null, 1));
writeFileSync(join(OUT, 'browser_meta.json'), JSON.stringify(
  { bootMs, timings, pageErrors, pageErrorsFromWindow: await page.evaluate(() => window.__pageErrors) }, null, 1));
console.log(`${Object.keys(out).length} browser reports; boot ${bootMs} ms; pageErrors=${pageErrors.length}`);
await browser.close();
