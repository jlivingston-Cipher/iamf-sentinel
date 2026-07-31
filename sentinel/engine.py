"""Validation orchestrator: read -> parse -> run checks -> Report.

Ties the clean-room parser, the MP4 walker, the profile packs, and the check
modules together behind ``validate()``. Execution never raises to the caller;
an unexpected failure becomes an S-000 execution-error finding and exit code 2
(PRD R6 CI contract).
"""

from __future__ import annotations
from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Any
import os
import tomllib

from . import model as m
from .parser import parse_bytes
from .container.mp4 import parse_mp4, MP4Info, extract_iamf_stream
from .findings import Finding, Severity
from .checks.base import CheckContext, finding
from .checks import l1_structural, l2_semantics, l3_loudness, container as container_checks

PROFILE_DIR = os.path.join(os.path.dirname(__file__), "profiles")


@dataclass
class Report:
    source: str
    profile: str
    container: str
    findings: list[Finding] = field(default_factory=list)
    model: m.IAMFModel | None = None
    mp4: MP4Info | None = None
    execution_error: str | None = None
    fail_on: Severity = Severity.FAIL          # threshold at/above which we exit 1

    def counts(self) -> dict[str, int]:
        c = {"FAIL": 0, "WARN": 0, "INFO": 0}
        for f in self.findings:
            c[f.severity.label] += 1
        return c

    def exit_code(self, fail_on: Severity | None = None) -> int:
        if self.execution_error is not None:
            return 2
        thr = self.fail_on if fail_on is None else fail_on
        return 1 if any(f.severity >= thr for f in self.findings) else 0

    def passed(self, fail_on: Severity | None = None) -> bool:
        return self.exit_code(fail_on) == 0

    def sorted_findings(self) -> list[Finding]:
        return sorted(self.findings, key=lambda f: (-int(f.severity), f.check_id))


def profile_dirs() -> list[str]:
    """Profile search path: the open core's packs, then the pro plugin's (if installed)."""
    dirs = [PROFILE_DIR]
    try:
        import sentinel_pro  # the Pro plugin registers by being importable
    except ImportError:
        pass
    else:
        pro_dir = os.path.join(os.path.dirname(sentinel_pro.__file__), "profiles")
        if os.path.isdir(pro_dir):
            dirs.append(pro_dir)
    return dirs


def load_profile(name: str) -> dict:
    dirs = profile_dirs()
    for d in dirs:
        path = os.path.join(d, f"{name}.toml")
        if os.path.exists(path):
            with open(path, "rb") as fh:
                return tomllib.load(fh)
    raise FileNotFoundError(
        f"unknown profile {name!r} (looked in {', '.join(dirs)}"
        + ("" if len(dirs) > 1 else "; platform profile packs ship with iamf-sentinel-pro")
        + ")")


def detect_container(data: bytes) -> str:
    if len(data) >= 8 and data[4:8] == b"ftyp":
        return "mp4"
    if data[:1] == b"\xf8":       # IA Sequence Header OBU (type 31)
        return "raw"
    if b"ftyp" in data[:64]:
        return "mp4"
    return "raw"


def validate(path: str, *, profile: str = "generic",
             fail_on: Severity = Severity.FAIL,
             toolchain: Any = None) -> Report:
    """`toolchain`: an oracle.Toolchain to enable L3 rendered QC (Phase 2)."""
    try:
        with open(path, "rb") as fh:
            data = fh.read()
    except OSError as e:
        r = Report(source=path, profile=profile, container="?")
        r.execution_error = f"cannot read file: {e}"
        return r
    return validate_bytes(data, source=path, profile=profile, fail_on=fail_on,
                          toolchain=toolchain, source_path=path)


def validate_bytes(data: bytes, *, source: str = "<bytes>", profile: str = "generic",
                   fail_on: Severity = Severity.FAIL,
                   toolchain: Any = None,
                   source_path: str | None = None) -> Report:
    try:
        prof = load_profile(profile)
    except (FileNotFoundError, tomllib.TOMLDecodeError) as e:
        r = Report(source=source, profile=profile, container="?")
        r.execution_error = str(e)
        return r

    ctx = CheckContext(
        profile=prof.get("name", profile),
        severity_overrides={k: v for k, v in prof.get("severity", {}).items()},
        toolchain=toolchain if (toolchain and source_path) else None,
        source_path=source_path,
        l3_options=dict(prof.get("l3", {})),
    )
    report = Report(source=source, profile=ctx.profile, container="?", fail_on=fail_on)

    try:
        container = detect_container(data)
        report.container = container
        mp4info = None
        if container == "mp4":
            mp4info = parse_mp4(data)
            report.mp4 = mp4info
            ctx.mp4 = mp4info
            if not mp4info.descriptor_obus:
                report.findings.append(finding(
                    ctx, "S-404", "MP4 has no readable IAMF descriptor (iacb) — "
                    "cannot validate payload"))
                mod = m.IAMFModel(source=source, container="mp4")
            else:
                mod = parse_bytes(mp4info.descriptor_obus, source=source, container="mp4")
                # Re-walk the MP4-carried audio frames so the trim checks
                # (S-407..S-409) can see the OBU trimming fields — the F31
                # class is invisible to a descriptor-only parse.
                raw = extract_iamf_stream(data, mp4info)
                if raw is not None:
                    mp4info.frame_refs = parse_bytes(
                        raw, source=source, container="mp4").audio_frames
        else:
            mod = parse_bytes(data, source=source, container="raw")
        report.model = mod

        modules = [l1_structural, l2_semantics, l3_loudness, container_checks]
        l3_rendered = None
        if ctx.toolchain is not None:
            # The L3 rendered-QC checks live in the Pro plugin (plugin seam,
            # PLUGIN_SEAM.md). A toolchain without the plugin is an execution
            # error (exit 2), not a silent downgrade: the caller asked for
            # rendered QC and must not read the report as having delivered it.
            try:
                from sentinel_pro import l3_rendered
            except ImportError:
                report.execution_error = ("L3 rendered QC requested but the "
                                          "iamf-sentinel-pro plugin is not installed")
                report.findings.append(Finding("S-000", Severity.FAIL,
                                               report.execution_error))
        if ctx.toolchain is not None and l3_rendered is not None:
            if container == "mp4" and mp4info is not None:
                # Oracles are raw-input; reconstruct the delivered IAMF stream
                # from the MP4 sample tables (clean-room extractor).
                raw = extract_iamf_stream(data, mp4info)
                if raw is not None:
                    ctx.source_path = ctx.toolchain.materialize_raw(raw)
            modules.append(l3_rendered)
        for module in modules:
            report.findings.extend(module.run(mod, ctx))

        report.findings.extend(_profile_requirements(mod, ctx, prof.get("require", {})))
    except Exception as e:   # last-resort guard: never crash the CI job
        report.execution_error = f"{type(e).__name__}: {e}"
    finally:
        if ctx.toolchain is not None:
            ctx.toolchain.cleanup()
    return report


def _profile_requirements(mod: m.IAMFModel, ctx: CheckContext,
                          require: dict) -> Iterator[Finding]:
    """Assert platform-profile hard requirements (R5)."""
    if not require:
        return
    sh = mod.sequence_header
    if "primary_profile" in require and sh is not None:
        if sh.primary_profile != require["primary_profile"]:
            want = m.PROFILE_NAME.get(require["primary_profile"], require["primary_profile"])
            got = m.PROFILE_NAME.get(sh.primary_profile, sh.primary_profile)
            yield finding(ctx, "S-109", f"profile '{ctx.profile}' requires {want} profile",
                          expected=str(want), found=str(got), severity=Severity.FAIL)
    if "codec_id" in require:
        codecs = {cc.codec_id for cc in mod.codec_configs.values()}
        if require["codec_id"] not in codecs:
            yield finding(ctx, "S-103", f"profile '{ctx.profile}' requires codec "
                          f"{require['codec_id']}", expected=require["codec_id"],
                          found=str(sorted(codecs)), severity=Severity.FAIL)
    if require.get("container") == "mp4" and mod.container != "mp4":
        yield finding(ctx, "S-404", f"profile '{ctx.profile}' requires an MP4 container",
                      expected="mp4", found=mod.container, severity=Severity.FAIL)
    if "brand" in require and ctx.mp4 is not None:
        if require["brand"] not in ctx.mp4.compatible_brands:
            yield finding(ctx, "S-401", f"profile '{ctx.profile}' requires brand "
                          f"'{require['brand']}'", expected=require["brand"],
                          found=str(ctx.mp4.compatible_brands), severity=Severity.FAIL)
