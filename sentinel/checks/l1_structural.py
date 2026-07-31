"""L1 structural checks (S-1xx): OBU syntax, ordering, referential integrity."""

from __future__ import annotations
from collections.abc import Iterator

from .base import CheckContext, finding
from ..findings import Finding
from .. import model as m

KNOWN_CODECS = {"Opus", "ipcm", "fLaC", "mp4a"}
KNOWN_PROFILES = {0, 1, 2}


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    # S-108 clean parse
    for note in mod.parse_notes:
        if "truncated" in note or "exceeds" in note or "smaller than" in note:
            yield finding(ctx, "S-108", f"structural parse problem: {note}")

    # S-101 sequence header present + first + ia_code
    sh = mod.sequence_header
    if sh is None:
        yield finding(ctx, "S-101", "no IA Sequence Header OBU found")
    else:
        if mod.obu_order and mod.obu_order[0] != "SequenceHeader":
            yield finding(ctx, "S-101", "IA Sequence Header is not the first OBU",
                          expected="SequenceHeader first", found=mod.obu_order[0])
        if sh.ia_code != "iamf":
            yield finding(ctx, "S-101", f"ia_code is {sh.ia_code!r}, expected 'iamf'",
                          expected="iamf", found=sh.ia_code)
        # S-102 profile recognised
        for role, val in (("primary", sh.primary_profile), ("additional", sh.additional_profile)):
            if val not in KNOWN_PROFILES:
                yield finding(ctx, "S-102", f"{role}_profile {val} not recognised "
                              f"(Simple/Base/Base-Enhanced = 0/1/2)", found=str(val))

    # S-103 codec config valid
    if not mod.codec_configs:
        yield finding(ctx, "S-103", "no codec config OBU present")
    for cid, cc in mod.codec_configs.items():
        if cc.codec_id not in KNOWN_CODECS:
            yield finding(ctx, "S-103", f"unknown codec_id {cc.codec_id!r}",
                          where=f"codec_config {cid}", found=cc.codec_id)
        if cc.num_samples_per_frame <= 0:
            yield finding(ctx, "S-103", "num_samples_per_frame must be > 0",
                          where=f"codec_config {cid}", found=str(cc.num_samples_per_frame))
        if cc.audio_roll_distance > 0:
            yield finding(ctx, "S-103", "audio_roll_distance must be <= 0",
                          where=f"codec_config {cid}", found=str(cc.audio_roll_distance))

    # S-104 / S-105 descriptor presence
    if not mod.audio_elements:
        yield finding(ctx, "S-104", "no audio element OBU present")
    if not mod.mix_presentations:
        yield finding(ctx, "S-105", "no mix presentation OBU present "
                      "(IAMF requires at least one)")

    # S-106 referential integrity
    for aid, ae in mod.audio_elements.items():
        if ae.codec_config_id not in mod.codec_configs:
            yield finding(ctx, "S-106", f"audio_element references missing codec_config "
                          f"{ae.codec_config_id}", where=f"audio_element {aid}",
                          found=str(ae.codec_config_id))
    for mp in mod.mix_presentations:
        for sm in mp.sub_mixes:
            for ref in sm.audio_element_ids:
                if ref not in mod.audio_elements:
                    yield finding(ctx, "S-106", f"mix_presentation references missing "
                                  f"audio_element {ref}",
                                  where=f"mix_presentation {mp.mix_presentation_id}",
                                  found=str(ref))

    # S-107 OBU ordering: no descriptor OBU after the first audio frame
    seen_frame = False
    for name in mod.obu_order:
        is_frame = name.startswith("AudioFrame")
        is_desc = name in ("SequenceHeader", "CodecConfig", "AudioElement", "MixPresentation")
        if is_frame:
            seen_frame = True
        elif is_desc and seen_frame:
            yield finding(ctx, "S-107", f"descriptor OBU {name} appears after audio frames "
                          "(descriptors must precede the first temporal unit)", found=name)
            break
