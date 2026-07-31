# iamf-sentinel — the free IAMF conformance check the ecosystem doesn't have

Code comments throughout cite an internal numbered design docset (`doc NN`), ADRs, and pre-registered expectation labels — **[DESIGN-NOTES.md](DESIGN-NOTES.md)** explains the notation and indexes every cited document.

**One line for CI:** `iamf-sentinel` tells your pipeline whether an IAMF file is *correct* —
structurally, semantically, and against a platform profile — and returns a stable exit code and a
citable list of check IDs. Pure standard-library Python; drops into any CI job with no procurement,
no native build, no toolchain.

> **Scope.** Checks are written against the **AOM IAMF v1.1.0** specification
> and ISO/IEC 14496-12, and cross-checked against the AOM reference tools. The
> tool is **spec- and reference-validated, not platform-certified**: a
> `--profile` name (e.g. `youtube`) applies the publicly-known shape
> constraints for that target, not a guarantee of acceptance by that platform's
> private ingest pipeline. A clean report means "conformant to the spec and the
> references" — necessary, but not by itself sufficient for any given platform.

## Why this exists

A syntactically valid, fully decodable IAMF file can ship with two height channels silently missing
and C/LFE duplicated into the surrounds — produced by *plausible* CLI usage, and passed clean by the
encoder, the muxer, **and both AOM reference decoders**. Nothing in the ecosystem flags it. This tool
does (check `S-201`). The encode side self-certifies and the content-QC burden falls entirely on
publishers who have had no tooling — this is that tooling, and it is free to run and free to cite.

## Install

```bash
pip install iamf-sentinel          # pure stdlib, Python ≥ 3.11 — no third-party runtime deps
```

**Verified platforms.** Every push runs the core test suite on **Linux, macOS, and Windows**
against **Python 3.11 and 3.12** — [`ci.yml`](.github/workflows/ci.yml) is the claim; the matrix
is the evidence. `requires-python` is `>=3.11`, but only the two versions above are measured, and
the sample-gated and plugin-gated tests skip in that environment by design. Nothing here is
claimed for a platform that does not have a green leg.

## Run

```bash
sentinel validate path/to/file.iamf                       # raw .iamf or IAMF-in-MP4
sentinel validate movie.mp4 --profile generic --format html -o report.html
sentinel validate file.iamf --format json                 # CI: machine-readable findings
sentinel batch ./deliverables                             # directory roll-up, worst-exit for CI
sentinel diff a.iamf b.mp4                                 # descriptor-structure diff (remux proof)
sentinel checks -v                                        # list the stable check registry
```

Exit codes (the CI contract): **0** pass · **1** findings at/above threshold · **2** execution error.
`--strict` promotes WARN to failing. `batch` returns the worst exit across the tree.

### Validate in a browser — zero install

**→ [Open the hosted inspector](https://jlivingston-cipher.github.io/iamf-sentinel/)** — no install,
no account, nothing to upload.

The same core also runs client-side as a **WASM inspector**: a single self-contained HTML page
that validates and inspects an IAMF file in a browser tab. The file is parsed in-tab and never
leaves your machine — the page is static and has no server side. The hosted copy is
[`docs/index.html`](docs/index.html) in this repository, built from this tree by
`python3 wasm/make_inspector.py .` — the build is byte-deterministic, so you can regenerate it and
confirm the page you are running is the code you are reading. A native-vs-browser differential gate
keeps the embedded core finding-identical to this package.

## What the free core checks

- **L1 — structural (clean-room OBU parser, written from the AOM IAMF v1.1.0 spec).** Every read is
  bounds-checked; truncated or fuzzed input yields a structured finding, never a crash (a 63k-call
  bounded-fuzz acceptance pass: no hangs, no uncaught exceptions).
- **L2 — channel semantics (the corruption killer).** Substream topology vs declared layout
  (coupled-pairs-first invariant), coupled/mono sanity, ambisonics (N+1)²/ACN completeness,
  dropped/duplicated/spurious substreams, annotation-presence.
- **Descriptor-level loudness & container checks that need no decoder.** Unmeasured `0.0` loudness,
  stereo-only loudness on multichannel programs, declared clipping, RFC 6381 codec-string casing,
  IAMF brand / fast-start / sample-entry, ISO-BMFF `iacb` extraction so L1/L2 run on IAMF-in-MP4
  exactly as on raw `.iamf`.
- **The CI contract.** Stable check-ID taxonomy (`S-1xx` structural / `S-2xx` semantic / `S-3xx`
  loudness / `S-4xx` container), FAIL/WARN/INFO severities, `json | text | html` reports, and a
  declarative `generic` profile. **This is the surface you cite:** "passes iamf-sentinel `S-1xx…S-4xx`
  at v0.3.1." (This example is version-coupled: it moves with every release.)

## What's in the Pro plugin (`iamf-sentinel-pro`) — also free, Apache-2.0

The core reads the file. The **L3 rendered QC** plugin *decodes* it and measures the truth
(it is a separate package for architecture, not licensing: the core stays stdlib-pure and
CI-frictionless; the decoder oracles, DSP, and their dependencies live behind the seam):

- Decode each mix presentation × declared layout through the reference decoders (as subprocess oracles)
  and measure **BS.1770-4** integrated loudness and true peak with an independent, calibrated
  implementation — catching declared-vs-measured loudness lies that descriptor checks can't see.
- **Channel-identity** on decoded PCM — catches the pure essence-misroute corruption (descriptor-clean,
  PCM-scrambled) that even L2 cannot see from the bitstream alone.
- Platform **profile packs** (e.g. YouTube ingest) and the loudness-measurement calibration that keeps
  *correct* files from being flagged at tight tolerances.

`sentinel validate --l3`, `diff --render`, and `batch --l3` activate automatically when the plugin is
installed; without it they print a one-line "requires iamf-sentinel-pro" notice and the free checks
still run. See the pro repo's
[`PLUGIN_SEAM.md`](https://github.com/jlivingston-Cipher/iamf-sentinel-pro/blob/main/PLUGIN_SEAM.md)
for the exact boundary.

## Fixtures

`fixtures/` ships the clean-room IAMF serializer, the mutation suite (topology / drop / dup /
ambisonics / truncation), and the corpus generator — so you can reproduce every check and build your
own regression corpus. These are part of the free core on purpose: they make the checks auditable and
the check IDs trustworthy.

## Traceability

`F_TO_CHECK.md` maps the executed WP1/WP3 failure catalogue to the checks that catch each one —
the requirements trail and the acceptance test in one table.

## Related projects

- [`iamf-sentinel-pro`](https://github.com/jlivingston-Cipher/iamf-sentinel-pro) — L3 rendered-QC
  plugin: decoder oracles, BS.1770-4 measurement, ADM fidelity, platform profile packs
- [`iamf-loom`](https://github.com/jlivingston-Cipher/iamf-loom) — manifest-driven IAMF packager;
  every output is gated by this validator
- [`iamf-adm-corpus`](https://github.com/jlivingston-Cipher/iamf-adm-corpus) — synthetic ADM
  corpus + harness (the input-side instrument; this validator is the output-side one)
- [`iamf-sentinel-mcp`](https://github.com/jlivingston-Cipher/iamf-sentinel-mcp) — MCP server
  exposing the validator and packager to agent runtimes

## License & support

Apache-2.0 (see `LICENSE` / `NOTICE`) — and not just this core: **the whole stack is free
software under Apache-2.0** — this package, the `iamf-sentinel-pro` plugin (L3 rendered QC,
ADM fidelity, profile packs), the `sentinel-dsp` measurement kernel, and the Loom
manifest-driven packager. The parser and all checks are original clean-room works written
from the AOM IAMF v1.1.0 spec and ISO/IEC 14496-12; no reference-decoder or encoder source
is used or derived. Reference decoders are invoked only as subprocess oracles, and only by
the separate `-pro` plugin.

This is an independent project, not an AOM deliverable; "IAMF" appears throughout as
descriptive nominative use of the format name, not as a product name.

Maintained best-effort; **commercial support and consulting are available** — see
`SUPPORT.md`.
