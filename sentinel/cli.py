"""Sentinel CLI — the CI contract (PRD R6).

    sentinel validate FILE [--profile P] [--format json|text|html] [--strict] [-o OUT]
                          [--l3 [--toolchain ROOT]]        # Phase 2 rendered QC
    sentinel checks                 # list the check registry
    sentinel diff A B [--render [--toolchain ROOT]]        # R7 full
    sentinel batch DIR [--l3 ...]
    sentinel adm-compare ADM_WAV IAMF [--layout L]      # Pro: ADM master vs IAMF deliverable
    sentinel intent-compare SIDECAR ADM_WAV             # Pro: intent sidecar vs delivered ADM

Exit codes: 0 pass · 1 findings at/above threshold · 2 execution error.
"""

from __future__ import annotations
import argparse
import json
import os
import sys
from collections.abc import Iterator
from typing import Any

from .findings import Severity, REGISTRY
from .engine import validate
from .report import render
from .diff import diff_files, render_diff_text


def _resolve_toolchain(args: argparse.Namespace) -> tuple[Any, str | None]:
    """Return (Toolchain|None, error|None) for an --l3/--render request."""
    try:
        from sentinel_pro.oracle import Toolchain
    except ImportError:
        return None, ("L3 rendered QC requires the iamf-sentinel-pro plugin "
                      "(not installed) — all free checks still run without "
                      "--l3/--render")
    tc = Toolchain.discover(getattr(args, "toolchain", None))
    if not tc.available:
        return None, ("no decoder oracle found (looked for decoder_main/iamfdec "
                      "under --toolchain, $SENTINEL_TOOLCHAIN, and $PATH) — "
                      "L3 rendered QC needs the toolchain")
    # Measurement backend: the compiled sentinel-dsp kernel OR the numpy
    # reference path (ADR-6b backend switch — sentinel_pro doc 35). A broken
    # kernel is an error, never a silent downgrade to the Python path.
    from sentinel_pro import dsp as _dsp
    try:
        has_kernel = _dsp.kernel_path() is not None
    except _dsp.KernelError as e:
        return None, str(e)              # explicit $SENTINEL_DSP misconfiguration
    if not has_kernel:
        try:
            import numpy  # noqa: F401
        except ImportError:
            return None, ("L3 measurement needs a backend: install numpy "
                          "(pip install iamf-sentinel-pro[numpy]) or provide "
                          "the sentinel-dsp kernel binary (on $PATH or via "
                          "$SENTINEL_DSP)")
    return tc, None


def _cmd_validate(args: argparse.Namespace) -> int:
    fail_on = Severity.WARN if args.strict else Severity.FAIL
    toolchain = None
    if args.l3:
        toolchain, err = _resolve_toolchain(args)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
    report = validate(args.file, profile=args.profile, fail_on=fail_on,
                      toolchain=toolchain)
    out = render(report, args.format)
    if args.output:
        # UTF-8 + LF explicitly (doc 97b): the text and HTML reports carry
        # em dashes and middots, and the HTML declares UTF-8 in its own
        # header. An unqualified text write uses the LOCALE encoding, which
        # is cp1252 on Windows — the bytes on disk then contradict the
        # charset the file announces, and the report renders as mojibake.
        with open(args.output, "w", encoding="utf-8", newline="\n") as fh:
            fh.write(out)
        if args.format != "json":
            print(f"wrote {args.format} report to {args.output}")
    else:
        print(out)
    return report.exit_code(fail_on)


def _cmd_checks(args: argparse.Namespace) -> int:
    for cid in sorted(REGISTRY):
        c = REGISTRY[cid]
        frefs = f"  [{', '.join(c.f_refs)}]" if c.f_refs else ""
        print(f"{c.id}  {c.default_severity.label:<4} {c.layer:<9} {c.title}{frefs}")
        if args.verbose and c.description:
            print(f"         {c.description}")
    return 0


def _cmd_diff(args: argparse.Namespace) -> int:
    toolchain = None
    if args.render:
        toolchain, err = _resolve_toolchain(args)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
    res = diff_files(args.a, args.b, toolchain=toolchain,
                     render_layout=args.layout)
    if args.format == "json":
        print(json.dumps({
            "a": res.source_a, "b": res.source_b, "verdict": res.verdict(),
            "entries": [e.to_dict() for e in res.entries],
            "exit_code": res.exit_code(),
        }, indent=2))
    else:
        print(render_diff_text(res))
    return res.exit_code()


def _cmd_adm_compare(args: argparse.Namespace) -> int:
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("adm-compare requires numpy (pip install iamf-sentinel-pro[numpy]) "
              "— its envelope/alignment math is outside the sentinel-dsp "
              "kernel surface", file=sys.stderr)
        return 2
    try:
        from sentinel_pro.adm_compare import (compare, render_json as acr_json,
                                              render_text as acr_text)
        from sentinel_pro.oracle import Toolchain
    except ImportError:
        print("adm-compare requires the iamf-sentinel-pro plugin (not installed)",
              file=sys.stderr)
        return 2
    tc = Toolchain.discover(args.toolchain) if args.toolchain else Toolchain.discover()
    res = compare(args.source, args.output, layout=args.layout,
                  importance_threshold=args.importance_threshold,
                  toolchain=tc, ear_bin=args.ear)
    print(acr_json(res) if args.format == "json" else acr_text(res))
    return res.exit_code()


def _cmd_intent_compare(args: argparse.Namespace) -> int:
    try:
        import numpy  # noqa: F401
    except ImportError:
        print("intent-compare requires numpy (pip install "
              "iamf-sentinel-pro[numpy]) — its trajectory/level math is "
              "outside the sentinel-dsp kernel surface", file=sys.stderr)
        return 2
    try:
        from sentinel_pro.intent_compare import (compare, render_json as icr_json,
                                                 render_text as icr_text)
    except ImportError:
        print("intent-compare requires the iamf-sentinel-pro plugin "
              "(not installed)", file=sys.stderr)
        return 2
    res = compare(args.sidecar, args.delivered, ear_bin=args.ear,
                  workdir=args.workdir)
    print(icr_json(res) if args.format == "json" else icr_text(res))
    return res.exit_code()


def _iter_media(root: str) -> Iterator[str]:
    if os.path.isfile(root):
        yield root
        return
    for dirpath, _dirs, files in os.walk(root):
        for name in sorted(files):
            if name.lower().endswith((".iamf", ".mp4")):
                yield os.path.join(dirpath, name)


def _cmd_batch(args: argparse.Namespace) -> int:
    fail_on = Severity.WARN if args.strict else Severity.FAIL
    toolchain = None
    if args.l3:
        toolchain, err = _resolve_toolchain(args)
        if err:
            print(f"error: {err}", file=sys.stderr)
            return 2
    rows, worst = [], 0
    for path in _iter_media(args.root):
        r = validate(path, profile=args.profile, fail_on=fail_on,
                     toolchain=toolchain)
        code = r.exit_code()
        worst = max(worst, code)
        c = r.counts()
        rows.append({"file": path, "result": "PASS" if code == 0 else ("ERROR" if code == 2 else "FAIL"),
                     "exit": code, "counts": c})
    if args.format == "json":
        print(json.dumps({"root": args.root, "profile": args.profile,
                          "files": len(rows), "worst_exit": worst, "results": rows}, indent=2))
    else:
        print(f"Sentinel batch — {args.root}  (profile: {args.profile})")
        for row in rows:
            c = row["counts"]
            print(f"  {row['result']:5} [{c['FAIL']}F {c['WARN']}W {c['INFO']}I]  {row['file']}")
        npass = sum(1 for r in rows if r["result"] == "PASS")
        print(f"\n  {npass}/{len(rows)} passed   worst exit: {worst}")
    return worst


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="sentinel", description="IAMF conformance & QC validator")
    sub = p.add_subparsers(dest="cmd", required=True)

    v = sub.add_parser("validate", help="validate an .iamf or IAMF-in-MP4 file")
    v.add_argument("file")
    v.add_argument("--profile", default="generic", help="profile pack (generic, youtube)")
    v.add_argument("--format", choices=["json", "text", "html"], default="text")
    v.add_argument("--strict", action="store_true", help="treat WARN as failing")
    v.add_argument("-o", "--output", help="write report to a file instead of stdout")
    v.add_argument("--l3", action="store_true",
                   help="enable L3 rendered QC (decoder oracle + measured BS.1770-4)")
    v.add_argument("--toolchain", help="toolchain root containing the reference decoders")
    v.set_defaults(func=_cmd_validate)

    c = sub.add_parser("checks", help="list the check registry")
    c.add_argument("-v", "--verbose", action="store_true")
    c.set_defaults(func=_cmd_checks)

    d = sub.add_parser("diff", help="compare two files (descriptor structure + rendered PCM)")
    d.add_argument("a")
    d.add_argument("b")
    d.add_argument("--format", choices=["text", "json"], default="text")
    d.add_argument("--render", action="store_true",
                   help="also decode both files and compare rendered PCM (R7 full)")
    d.add_argument("--layout", help="force the rendered-comparison layout (e.g. 5.1)")
    d.add_argument("--toolchain", help="toolchain root containing the reference decoders")
    d.set_defaults(func=_cmd_diff)

    ac = sub.add_parser("adm-compare",
                        help="source-referenced fidelity QC: ADM source vs produced "
                             "IAMF (S-33x — F17/F18; needs ear-render + toolchain)")
    ac.add_argument("source", help="source ADM BW64 (.wav)")
    ac.add_argument("output", help="produced IAMF (.iamf)")
    ac.add_argument("--layout", default="5.1",
                    help="comparison layout (2.0, 5.1, 5.1.2, 5.1.4, 7.1, 7.1.4)")
    ac.add_argument("--importance-threshold", type=int, default=None,
                    help="threshold passed to the encoder; enables the S-331 check")
    ac.add_argument("--ear", help="path to ear-render (default: $SENTINEL_EAR or PATH)")
    ac.add_argument("--toolchain", help="toolchain root containing the reference decoders")
    ac.add_argument("--format", choices=["text", "json"], default="text")
    ac.set_defaults(func=_cmd_adm_compare)

    ic = sub.add_parser("intent-compare",
                        help="intent-conformance QC: the session's intent "
                             "sidecar vs the delivered ADM BW64 (S-34x; "
                             "needs ear-render only when the sidecar carries "
                             "decode predictions)")
    ic.add_argument("sidecar", help="intent sidecar (.intent.json, schema 0)")
    ic.add_argument("delivered", help="delivered ADM BW64 (.wav)")
    ic.add_argument("--ear", help="path to ear-render (default: $SENTINEL_EAR or PATH)")
    ic.add_argument("--workdir", help="keep isolation renders here instead of a temp dir")
    ic.add_argument("--format", choices=["text", "json"], default="text")
    ic.set_defaults(func=_cmd_intent_compare)

    b = sub.add_parser("batch", help="validate every .iamf/.mp4 under a directory (roll-up)")
    b.add_argument("root")
    b.add_argument("--profile", default="generic")
    b.add_argument("--format", choices=["text", "json"], default="text")
    b.add_argument("--strict", action="store_true")
    b.add_argument("--l3", action="store_true")
    b.add_argument("--toolchain")
    b.set_defaults(func=_cmd_batch)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
