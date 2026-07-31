"""Check context + severity resolution shared by all check modules."""

from __future__ import annotations
from dataclasses import dataclass, field

from ..findings import Finding, Severity, spec


@dataclass
class CheckContext:
    profile: str = "generic"
    severity_overrides: dict[str, str] = field(default_factory=dict)   # check_id -> "FAIL"/"WARN"/"INFO"
    mp4: object | None = None      # MP4Info when container == "mp4"
    # L3 (Phase 2): set only when a decoder-oracle run was requested
    toolchain: object | None = None          # oracle.Toolchain
    source_path: str | None = None           # on-disk path for subprocess oracles
    l3_options: dict = field(default_factory=dict)   # tolerances etc (profile [l3])
    l3_cache: dict = field(default_factory=dict)     # per-file decode/measure cache

    def severity(self, check_id: str) -> Severity:
        ov = self.severity_overrides.get(check_id)
        if ov:
            return Severity[ov]
        return spec(check_id).default_severity


def finding(ctx: CheckContext, check_id: str, message: str, *, where: str = "",
            expected: str | None = None, found: str | None = None,
            severity: Severity | None = None) -> Finding:
    sp = spec(check_id)
    sev = severity if severity is not None else ctx.severity(check_id)
    return Finding(
        check_id=check_id, severity=sev, message=message, where=where,
        expected=expected, found=found, f_refs=sp.f_refs,
    )
