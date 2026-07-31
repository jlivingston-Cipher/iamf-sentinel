# Design notes — reading the provenance references in this codebase

This project was developed against an internal, numbered design docset: every work
cycle produced a numbered document recording what was decided, what was measured, and
the evidence behind both. Code comments cite those records rather than restating them
(`doc 59`, `ADR-3`, `F31`, `E-B2`, …). The docset itself is not published — it contains
work-in-progress material beyond this repo's scope — but the notation is simple and the
index below preserves the context each citation carries, so a comment like
“trim retention (doc 59)” reads as “this exists because of a recorded, tested decision,”
not as a dangling pointer.

## Notation

| Form | Meaning |
|---|---|
| `doc NN` (§ optional) | A numbered internal design/evidence document; the index below gives each cited number's one-line content. |
| `ADR-1` … `ADR-6b` | Architecture Decision Records (recorded in doc 14, later amendments noted in the citing comments). |
| `WP1`, `WP3` | Work packages: WP1 = toolchain validation (real encoder/decoder behaviour), WP3 = ADM→IAMF fidelity study. `wp1-samples`/`wp3-samples` are their sample corpora (see the test-skip messages for staging paths). |
| `PRD`, `R1` … `R10` | The product requirements documents and their numbered requirements (validator PRD and packager PRD). |
| `F1` … `F34` | Entries in the failure-mode register: real defects and pitfalls found in the ecosystem's toolchains — **see [`F_TO_CHECK.md`](F_TO_CHECK.md)**, which ships in this repo and maps each F-number to the Sentinel check that catches it. |
| `G1` … `G11` | WP1 validation gates (doc 10): measured pass/fail criteria for the reference toolchain. |
| `S-NNN` | Sentinel check IDs — the stable check registry; list them with `sentinel checks` (add `-v` for descriptions). |
| `M-NNN` | iamf-loom compile diagnostics (the companion packager project). |
| `E-…` | A pre-registered expectation: written down *before* an experiment ran, then confirmed or refuted. Comments cite them to mark behaviour that was predicted, not retrofitted. |
| `D-…` | A pre-registered per-cycle design decision label (e.g. cache-admission contracts). |
| `D1`–`D4` | Program-level decisions: D1 = distribution/open-source shape, D3 = an upstream build-system contribution, D4 = the responsible-disclosure track for third-party findings (the F-register filings). |

## Index of cited documents

| Doc | What it established |
|---|---|
| 02 | Ecosystem landscape survey: formats, toolchains, deployment surfaces. |
| 04 | Fact base: Dolby Atmos delivery formats and constraints. |
| 05 | Fact base: MPEG-H, DTS:X, Audio Vivid. |
| 13 | The packager (iamf-loom) PRD — R1–R10. |
| 19 | Sentinel Phase 2: L3 rendered QC (decoder oracles + BS.1770-4 measurement). |
| 26 | The open-core seam split — the architecture now described in `PLUGIN_SEAM.md` (seam kept as architecture; everything Apache-2.0). |
| 30 | The WASM inspector (Phase 3a): the single-file browser build of the L1/L2 core. |
| 35 | The DSP backend switch: the `sentinel-dsp` C++ kernel becomes the measurement engine; numpy becomes an optional extra; a present-but-broken kernel is an error, never a silent fallback. |
| 48 | The decision to publish the whole stack as free software, Apache-2.0. |
| 56 | Refutation of an earlier FFmpeg remux finding (F5) — our invocation error; the correction was posted upstream. |
| 57 | Root-cause analysis of FFmpeg's IAMF start-trim carriage loss on stream copy (F31): spec §6.2.2 read, cause pinned in `iamf_writer.c`. |
| 59 | Sentinel's trim-carriage layer: `edts`/`elst` parsing, trim retention, checks S-407/S-408/S-409. |
| 60 | F32 adjudication: the MP4Box `stts` duration defect isolated with a one-variable patch matrix; FFmpeg's demux side exonerated. |
| 61 | Housekeeping: ADR-2's context statement replaced after both of its original grounds were refuted (the decision itself stands on the F31/F32 repairability asymmetry). |
| 63 | Browser-verification cycle: confirmed the F5 upstream ticket closed; F32 duplicate search clear (with positive controls). |
| 64 | Normative-revision audit: established which BS.1770 revision IAMF v1.1.0 binds to (BS.1770-4, cited by revision). |
| 65 | BS.1770-4 Tables 4/5 read: the conformant channel-weighting values used by the measurement engine. |
| 66 | Decision cycle: names finalized; F33 opened (an audit of our own 7.1.x weight tables). |
| 69 | F33 fix: 7.1.x rear-surround weights corrected to the BS.1770-4 tables in both the Python reference and the C++ kernel (differential re-pinned). |
| 70 | F34 fix: all loudness measurement routed through the `sentinel-dsp` kernel. |
| 71 | F32 filed upstream: gpac/gpac#3826 (issue + patch offer). |

The check registry (`sentinel/findings.py`), the failure register (`F_TO_CHECK.md`),
and the test suites are the living, shipped form of most of this history — the index
exists so the remaining pointers stay meaningful.
