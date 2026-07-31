#!/usr/bin/env python3
"""Generate the single-file WASM L1/L2 inspector HTML with the embedded core zip.

Usage:  make_inspector.py OSS_ROOT [PRO_ROOT] [-o OUT.html]

Builds the embedded core zip directly from the D1 split trees (PLUGIN_SEAM.md):
the OSS `sentinel` package (stdlib L1/L2 + container + descriptor checks +
`generic` profile) plus — if PRO_ROOT is given — `profiles/youtube.toml` from
the pro tree, embedded at `sentinel/profiles/youtube.toml` (doc 30's embedded
surface; the "youtube free vs paid" D1 sub-question, doc 26, governs whether a
public build may include it). The in-page profile selector is generated from
whatever was embedded, so a public build offers only the profiles it ships.
Pro-boundary code (dsp/oracle/l3_rendered/adm_compare) is never embedded.
The embedded zip is byte-deterministic: same source files, same artifact.
"""
import argparse
import base64
import io
import os
import zipfile

OSS_CORE_FILES = [
    "sentinel/__init__.py", "sentinel/__main__.py", "sentinel/reader.py",
    "sentinel/parser.py", "sentinel/model.py", "sentinel/layouts.py",
    "sentinel/findings.py", "sentinel/report.py", "sentinel/engine.py",
    "sentinel/cli.py", "sentinel/diff.py",
    "sentinel/checks/__init__.py", "sentinel/checks/base.py",
    "sentinel/checks/l1_structural.py", "sentinel/checks/l2_semantics.py",
    "sentinel/checks/l3_loudness.py", "sentinel/checks/container.py",
    "sentinel/container/__init__.py", "sentinel/container/mp4.py",
    "sentinel/profiles/generic.toml",
]

ap = argparse.ArgumentParser()
ap.add_argument("oss_root", help="sentinel-oss tree root")
ap.add_argument("pro_root", nargs="?", help="sentinel-pro tree root (for youtube.toml)")
ap.add_argument("-o", "--output", default="iamf-inspector.html")
args = ap.parse_args()

# Deterministic archive. `ZipFile.write` stamps each member with the source
# file's mtime, which made the embedded blob a function of *when* the tree was
# checked out rather than of what it contains: two builds of identical sources
# differed in bytes, so a rebuild always looked like a change and the hosted
# artifact could not be reproduced by a third party. A fixed timestamp and mode
# make the blob a pure function of the source bytes.
ZIP_EPOCH = (1980, 1, 1, 0, 0, 0)


def add(zf, arcname, src):
    zi = zipfile.ZipInfo(arcname, date_time=ZIP_EPOCH)
    zi.compress_type = zipfile.ZIP_DEFLATED
    zi.external_attr = 0o644 << 16
    with open(src, "rb") as fh:
        zf.writestr(zi, fh.read())


profiles = ["generic"]
buf = io.BytesIO()
with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
    for rel in OSS_CORE_FILES:
        add(zf, rel, os.path.join(args.oss_root, rel))
    if args.pro_root:
        add(zf, "sentinel/profiles/youtube.toml",
            os.path.join(args.pro_root, "sentinel_pro/profiles/youtube.toml"))
        profiles.append("youtube")
B64 = base64.b64encode(buf.getvalue()).decode()

# The profile selector is a function of what was actually embedded. It used to
# be hardcoded with a `youtube` entry, so a build without PRO_ROOT offered a
# profile it did not ship: choosing it returned "unknown profile 'youtube' ...
# platform profile packs ship with iamf-sentinel-pro", advice that cannot be
# acted on inside a browser page.
PROFILE_OPTIONS = "".join(
    '<option value="{0}"{1}>{0}</option>'.format(p, " selected" if i == 0 else "")
    for i, p in enumerate(profiles))
PYODIDE_VERSION = "0.28.3"

HTML = r"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>IAMF Inspector — in-browser L1/L2 conformance</title>
<link rel="icon" href="data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 16 16'><rect width='16' height='16' rx='3' fill='%23223'/><path d='M3 11 6 5l2 4 2-6 3 8' stroke='%2378c' stroke-width='1.6' fill='none'/></svg>">
<style>
  :root { --bg:#14161a; --panel:#1d2026; --line:#2c3038; --ink:#e8eaed; --dim:#9aa0a8;
          --fail:#e05252; --warn:#d9a13b; --info:#5b9bd5; --pass:#4caf7d; --acc:#7aa2d8; }
  * { box-sizing:border-box; }
  body { margin:0; background:var(--bg); color:var(--ink);
         font:14px/1.5 "SF Mono", ui-monospace, Menlo, Consolas, monospace; }
  header { padding:18px 24px 10px; border-bottom:1px solid var(--line); }
  header h1 { margin:0; font-size:17px; font-weight:600; letter-spacing:.02em; }
  header p { margin:4px 0 0; color:var(--dim); font-size:12px; }
  main { max-width:980px; margin:0 auto; padding:20px 24px 60px; }
  #status { font-size:12px; color:var(--dim); padding:8px 0; }
  #status.ready { color:var(--pass); }
  #status.err { color:var(--fail); }
  #drop { border:1.5px dashed var(--line); border-radius:10px; padding:34px 20px;
          text-align:center; color:var(--dim); cursor:pointer; transition:border-color .15s; }
  #drop.armed:hover, #drop.over { border-color:var(--acc); color:var(--ink); }
  #drop input { display:none; }
  .row { display:flex; gap:14px; align-items:center; margin:14px 0; flex-wrap:wrap; }
  select, button { background:var(--panel); color:var(--ink); border:1px solid var(--line);
          border-radius:6px; padding:6px 10px; font:inherit; cursor:pointer; }
  button:disabled { opacity:.4; cursor:default; }
  .badge { display:inline-block; padding:2px 10px; border-radius:20px; font-size:12px; font-weight:600; }
  .b-pass { background:#153824; color:var(--pass); } .b-fail { background:#3a1a1a; color:var(--fail); }
  .b-err  { background:#3a2a12; color:var(--warn); }
  #summary { background:var(--panel); border:1px solid var(--line); border-radius:10px;
             padding:14px 18px; margin-top:18px; display:none; }
  #summary h2 { margin:0 0 8px; font-size:14px; }
  #summary .kv { color:var(--dim); font-size:12px; }
  #summary .kv b { color:var(--ink); font-weight:600; }
  table { width:100%; border-collapse:collapse; margin-top:12px; font-size:12.5px; }
  th { text-align:left; color:var(--dim); font-weight:600; border-bottom:1px solid var(--line);
       padding:6px 8px; }
  td { padding:6px 8px; border-bottom:1px solid #23262c; vertical-align:top; }
  td.sev-FAIL { color:var(--fail); font-weight:700; } td.sev-WARN { color:var(--warn); font-weight:700; }
  td.sev-INFO { color:var(--info); } td.mono { color:var(--dim); }
  details { margin-top:14px; } summary { cursor:pointer; color:var(--dim); font-size:12px; }
  pre { background:#111318; border:1px solid var(--line); border-radius:8px; padding:12px;
        overflow:auto; font-size:12px; max-height:420px; }
  footer { color:var(--dim); font-size:11px; margin-top:34px; border-top:1px solid var(--line);
           padding-top:10px; }
  #timing { font-size:11px; color:var(--dim); margin-top:6px; }
</style>
</head>
<body>
<header>
  <h1>IAMF Inspector <span style="color:var(--dim);font-weight:400">— L1 structural · L2 channel-semantics · container checks, entirely in your browser</span></h1>
  <p>Clean-room IAMF v1.1.0 validation (no upload — the file never leaves this page). Rendered/loudness QC (L3) requires the native tool and its decoder oracles; it is not offered here by design.</p>
</header>
<main>
  <div id="status">Loading Python runtime (WASM)…</div>
  <label id="drop"><input type="file" id="file" accept=".iamf,.mp4,.m4a,application/octet-stream">
    Drop an <b>.iamf</b> or IAMF-in-<b>MP4</b> file here, or click to choose
  </label>
  <div class="row">
    <span style="color:var(--dim);font-size:12px">profile</span>
    <select id="profile">__PROFILE_OPTIONS__</select>
    <button id="revalidate" disabled>re-validate</button>
    <button id="dljson" disabled>download JSON report</button>
  </div>
  <div id="summary"></div>
  <div id="timing"></div>
  <details id="rawjson-w"><summary>raw JSON report</summary><pre id="rawjson"></pre></details>
  <details id="rawtext-w"><summary>text report</summary><pre id="rawtext"></pre></details>
  <footer>
    Single-file build: the validator core ships inside this page (base64 zip); only the Pyodide
    runtime loads from its pinned CDN (override with <code>?pyodide=&lt;baseURL&gt;</code> for
    offline/self-hosted use). Checks: S-1xx structural · S-2xx semantic · S-3xx descriptor-derived
    loudness · S-4xx container/profile. Exit semantics match the CLI: 0 pass · 1 findings · 2 error.
  </footer>
</main>
<script>
const CORE_ZIP_B64 = "__CORE_ZIP_B64__";
const PYODIDE_VERSION = "__PYODIDE_VERSION__";
const params = new URLSearchParams(location.search);
const baseParam = params.get("pyodide");
const PYODIDE_SOURCES = baseParam
  ? [new URL(baseParam.endsWith("/") ? baseParam : baseParam + "/", location.href).href]
  : [`https://cdn.jsdelivr.net/pyodide/v${PYODIDE_VERSION}/full/`,
     `https://cdnjs.cloudflare.com/ajax/libs/pyodide/${PYODIDE_VERSION}/`];
let PYODIDE_BASE = null;
let pyodide = null, lastResult = null, lastFile = null;
const el = id => document.getElementById(id);
window.__pageErrors = [];
window.addEventListener("error", e => window.__pageErrors.push(String(e.message)));
window.addEventListener("unhandledrejection", e => window.__pageErrors.push(String(e.reason)));

function loadScript(src) {
  return new Promise((res, rej) => {
    const s = document.createElement("script");
    s.src = src; s.onload = res; s.onerror = () => rej(new Error("cannot load " + src));
    document.head.appendChild(s);
  });
}
async function boot() {
  try {
    let lastErr = null;
    for (const base of PYODIDE_SOURCES) {
      try {
        el("status").textContent = "Loading Python runtime (WASM) from " + new URL(base).host + "…";
        await loadScript(base + "pyodide.js");
        PYODIDE_BASE = base; break;
      } catch (e) { lastErr = e; }
    }
    if (!PYODIDE_BASE) throw lastErr || new Error("no pyodide source reachable");
    pyodide = await loadPyodide({ indexURL: PYODIDE_BASE });
    pyodide.globals.set("CORE_ZIP_B64", CORE_ZIP_B64);
    await pyodide.runPythonAsync(`
import base64, io, json, os, sys, time, zipfile
zf = zipfile.ZipFile(io.BytesIO(base64.b64decode(CORE_ZIP_B64)))
zf.extractall('/pkg'); os.makedirs('/work', exist_ok=True)
sys.path.insert(0, '/pkg')
from sentinel.engine import validate
from sentinel.report import render_json, render_text

def run_validate(path, profile):
    t0 = time.time()
    r = validate(path, profile=profile)
    ms = int((time.time() - t0) * 1000)
    return json.dumps({
        'json': render_json(r), 'text': render_text(r),
        'exit_code': r.exit_code(), 'ms': ms,
        'numpy_loaded': 'numpy' in sys.modules,
    })
`);
    el("status").textContent = "Runtime ready — Python " + pyodide.runPython("import sys; '.'.join(map(str, sys.version_info[:3]))") + " / Pyodide " + PYODIDE_VERSION;
    el("status").className = "ready";
    el("drop").classList.add("armed");
  } catch (e) {
    el("status").textContent = "Runtime failed to load: " + e.message;
    el("status").className = "err";
    window.__pageErrors.push(String(e.message));
  }
}
boot();

// Core entry point — used by the UI and by automated differential testing.
window.validateFile = async function (name, b64data, profile) {
  if (!pyodide) throw new Error("runtime not ready");
  const bytes = Uint8Array.from(atob(b64data), c => c.charCodeAt(0));
  const safe = name.replace(/[^A-Za-z0-9._-]/g, "_");
  pyodide.FS.writeFile("/work/" + safe, bytes);
  const out = pyodide.globals.get("run_validate")("/work/" + safe, profile);
  return out; // JSON string {json,text,exit_code,ms,numpy_loaded}
};
window.runtimeReady = () => !!pyodide;

function fmtSummary(res, name) {
  const doc = JSON.parse(res.json), s = doc.summary, c = s.counts;
  const badge = s.result === "PASS" ? "b-pass" : (s.result === "ERROR" ? "b-err" : "b-fail");
  let h = `<h2>${name} <span class="badge ${badge}">${s.result}</span>
    <span class="kv" style="margin-left:8px">exit ${doc.exit_code} · ${s.container} · profile ${s.profile}</span></h2>`;
  h += `<div class="kv">FAIL <b>${c.FAIL}</b> · WARN <b>${c.WARN}</b> · INFO <b>${c.INFO}</b>`;
  if (s.stream) h += ` &nbsp;|&nbsp; ${s.stream.primary_profile} profile · codecs ${s.stream.codecs.join(",")}
    · ${s.stream.audio_elements} element(s) · ${s.stream.mix_presentations} mix presentation(s)
    · ${s.stream.audio_frames} frames`;
  if (s.execution_error) h += ` &nbsp;|&nbsp; <span style="color:var(--fail)">${s.execution_error}</span>`;
  h += `</div>`;
  if (doc.findings.length) {
    h += `<table><tr><th>severity</th><th>check</th><th>message</th></tr>`;
    for (const f of doc.findings)
      h += `<tr><td class="sev-${f.severity}">${f.severity}</td><td class="mono">${f.check_id}</td><td>${f.message.replace(/&/g,"&amp;").replace(/</g,"&lt;")}</td></tr>`;
    h += `</table>`;
  } else h += `<div class="kv" style="margin-top:8px">No findings.</div>`;
  return h;
}

async function handle(file) {
  if (!pyodide || !file) return;
  el("status").textContent = "Validating " + file.name + "…";
  const buf = new Uint8Array(await file.arrayBuffer());
  let b64 = ""; const CH = 0x8000;
  for (let i = 0; i < buf.length; i += CH) b64 += String.fromCharCode.apply(null, buf.subarray(i, i + CH));
  b64 = btoa(b64);
  lastFile = { name: file.name, b64 };
  const res = JSON.parse(await window.validateFile(file.name, b64, el("profile").value));
  lastResult = res;
  el("summary").style.display = "block";
  el("summary").innerHTML = fmtSummary(res, file.name);
  el("rawjson").textContent = JSON.stringify(JSON.parse(res.json), null, 2);
  el("rawtext").textContent = res.text;
  el("timing").textContent = `validated in ${res.ms} ms (in-page) · numpy loaded: ${res.numpy_loaded}`;
  el("status").textContent = "Runtime ready"; el("status").className = "ready";
  el("revalidate").disabled = false; el("dljson").disabled = false;
}
el("file").addEventListener("change", e => handle(e.target.files[0]));
const drop = el("drop");
drop.addEventListener("dragover", e => { e.preventDefault(); drop.classList.add("over"); });
drop.addEventListener("dragleave", () => drop.classList.remove("over"));
drop.addEventListener("drop", e => { e.preventDefault(); drop.classList.remove("over"); handle(e.dataTransfer.files[0]); });
el("revalidate").addEventListener("click", async () => {
  if (!lastFile) return;
  const res = JSON.parse(await window.validateFile(lastFile.name, lastFile.b64, el("profile").value));
  lastResult = res;
  el("summary").innerHTML = fmtSummary(res, lastFile.name);
  el("rawjson").textContent = JSON.stringify(JSON.parse(res.json), null, 2);
  el("rawtext").textContent = res.text;
  el("timing").textContent = `validated in ${res.ms} ms (in-page) · numpy loaded: ${res.numpy_loaded}`;
});
el("dljson").addEventListener("click", () => {
  if (!lastResult || !lastFile) return;
  const a = document.createElement("a");
  a.href = URL.createObjectURL(new Blob([lastResult.json], { type: "application/json" }));
  a.download = lastFile.name.replace(/\.[^.]*$/, "") + ".report.json";
  a.click(); URL.revokeObjectURL(a.href);
});
</script>
</body>
</html>
"""

out = (HTML.replace("__CORE_ZIP_B64__", B64)
           .replace("__PYODIDE_VERSION__", PYODIDE_VERSION)
           .replace("__PROFILE_OPTIONS__", PROFILE_OPTIONS))
open(args.output, 'w').write(out)
print(args.output, len(out), 'bytes')
