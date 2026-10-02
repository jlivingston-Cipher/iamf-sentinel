"""L1 structural checks (S-1xx): OBU syntax, ordering, referential integrity."""

from __future__ import annotations
from collections.abc import Iterator

from .base import CheckContext, finding
from ..findings import Finding, Severity
from .. import model as m

KNOWN_CODECS = {"Opus", "ipcm", "fLaC", "mp4a"}
KNOWN_PROFILES = set(m.PROFILE_NAME)      # 0..5; 6..255 are reserved (v2:695)


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    # S-108 clean parse: every genuine ParseError, whatever its wording.
    # Forward-compat skips and "not modelled" notes live in parse_notes only.
    for err in mod.parse_errors:
        yield finding(ctx, "S-108", f"structural parse problem: {err}")

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
        # S-102 profile recognised. 6..255 are "Reserved for future profiles"
        # (v2:695) in both fields, but the two do not weigh the same.
        defined = "defined profiles are 0-5: " + ", ".join(m.PROFILE_NAME.values())
        if sh.primary_profile not in KNOWN_PROFILES:
            # At the registry severity (FAIL; a pack may override it): parsers
            # SHOULD discard an IA Sequence whose primary_profile they do not
            # support (v2:683), so nothing built to this specification is
            # expected to play the stream.
            yield finding(ctx, "S-102", f"primary_profile {sh.primary_profile} is "
                          f"reserved ({defined}). A parser is told to discard an IA "
                          "Sequence whose primary_profile it does not support, so "
                          "no parser of a defined profile is expected to play this "
                          "stream", found=str(sh.primary_profile))
        if sh.additional_profile not in KNOWN_PROFILES:
            # Always INFO: the text does not forbid a reserved value here, and
            # describes the field as the place where a profile from a later
            # version is signalled beside a primary one that older parsers
            # know (v2:698-700).
            yield finding(ctx, "S-102", f"additional_profile {sh.additional_profile} "
                          f"is reserved ({defined}). The specification does not "
                          "forbid this: the field can name a profile that a later "
                          "version defines, beside a primary_profile that today's "
                          "parsers support, so it is noted and not counted against "
                          "the stream", found=str(sh.additional_profile),
                          severity=Severity.INFO)

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
