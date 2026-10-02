"""L1 profile-limit checks (S-109): what the declared IA profiles admit.

A profile is a decoder capability set. The bitstream obligation that follows
from it is narrow: at least one Mix Presentation has to comply with the
conformance points of primary_profile (v2:3164, v1.1:1929). A Mix Presentation
outside the profile next to one inside it is not a violation; a decoder simply
does not play it. So this module separates three outcomes:

    FAIL  no Mix Presentation fits primary_profile; a sequence-wide SHALL is
          broken (channel total, Codec Config count, Base-Advanced first mix)
    WARN  one Mix Presentation fits neither declared profile, another fits
    INFO  the answer turns on a point the specification leaves open

A Mix Presentation is judged once, however many redundant copies of the
descriptors the stream repeats.

Nothing here guesses. An element whose channel count cannot be read (reserved
layout, reserved audio_element_type, config bytes that are not an
ObjectsConfig, a dangling reference) contributes nothing to a total. The
elements that can be read give a lower bound: when they alone exceed a limit
the limit is exceeded, and otherwise the test is "unknown", which never fails
or warns.

Citations are source line numbers in the three specification files the limits
were read from: ``v2:`` IAMF v2.0.0 (index.bs at 4d2c6da), ``v1.1:`` IAMF
v1.1.0, ``err:`` IAMF v1.0.0-errata. v2.0.0 defers Simple and Base to
v1.0.0-errata (v2:3174, v2:3181) and Base-Enhanced to v1.1.0 (v2:3188).

Not checked here, deliberately: the literal "only one / at most two unique
Audio Element OBUs" of Simple and Base (err:1853, err:1866) as a sequence-wide
count; values that are reserved only in the specification version a profile
0..2 was defined in, other than the object element type and the expanded
layouts 13..19 (which are flagged as unsettled, not judged); whether a Mix
Presentation that references a reserved audio_element_type (3..7) is outside
every profile; the value of num_objects (S-210 judges it; here 0 is only an
unknown channel count, silently, and 3..255 are counted as given); whether a
Mix Presentation that parsers are told to ignore for a reserved rendering
value (S-216) still counts as one that fits a profile; whether any Mix
Presentation complies with additional_profile; and the remaining two-codec
rules of v2:3145-3147.
"""

from __future__ import annotations
from collections.abc import Iterator
from dataclasses import dataclass, field

from .base import CheckContext, finding
from ..findings import Finding, Severity
from .. import model as m
from ..layouts import LOUDSPEAKER_LAYOUT, EXPANDED_LAYOUT_CHANNELS

# Audio Elements one Mix Presentation may reference, summed over its sub-mixes.
MAX_AUDIO_ELEMENTS = {
    0: 1,     # err:1853 (one Audio Element), err:1858 (reconstruct one)
    1: 2,     # err:1866 (at most two), err:1881-1882 (reconstruct / mix two)
    2: 28,    # v1.1:1951
    3: 18,    # v2:3196
    4: 18,    # v2:3222
    5: 28,    # v2:3244
}

# Channels summed across the Audio Elements of one Mix Presentation before
# mixing (the scope is v2:3162 / v1.1:1927; err:1879 for Base).
MAX_CHANNELS = {
    0: 16,    # err:1857
    1: 18,    # err:1878
    2: 28,    # v1.1:1958
    3: 18,    # v2:3211
    4: 18,    # v2:3233
    5: 28,    # v2:3249
}

# num_sub_mixes a parser of the profile does not ignore.
MAX_SUB_MIXES = {
    0: 1, 1: 1, 2: 1,     # v1.1:1920 ("> 1 SHOULD be ignored"; same err:1839)
    3: 2, 4: 2, 5: 2,     # v2:3155 ("> 2 SHOULD be ignored")
}

# Unique Codec Config OBUs in the IA Sequence.
MAX_CODEC_CONFIGS = {
    0: 1, 1: 1, 2: 1,     # v1.1:1912 ("only one"; same err:1831)
    3: 2, 4: 2, 5: 2,     # v2:3143 (two only when not every mix has one sub-mix)
}

# Base only: of the (at most two) elements, how many may be scalable
# channel-based (num_layers > 1) and how many scene-based.
BASE_MAX_SCALABLE_ELEMENTS = 1    # err:1867 (combinations err:1870-1873)
BASE_MAX_SCENE_ELEMENTS = 1       # err:1868 (combinations err:1870-1873)

# Channels in total across all Audio Elements of the IA Sequence, keyed by
# additional_profile. The profile 2 entry binds only when primary_profile is
# at most 2 (v1.1:1953); the v2.0.0 sentences carry no such condition.
SEQUENCE_MAX_CHANNELS = {
    2: 28,    # v1.1:1953
    3: 18,    # v2:3166
    4: 18,    # v2:3166
    5: 28,    # v2:3167
}

# Profiles defined by a specification version earlier than v2.0.0, and that
# version (v2:3174, v2:3181, v2:3188). Two things follow from the older text.
# Object-based elements do not exist there: audio_element_type 2 is reserved
# in v1.0.0-errata (err:699) and in v1.1.0 (v1.1:732), and v2.0.0 introduces
# objects as a new capability of Base-Advanced (v2:3204) — a mix that
# references one is outside these profiles.
PRE_V2_PROFILES = {0: "IAMF v1.0.0-errata", 1: "IAMF v1.0.0-errata", 2: "IAMF v1.1.0"}

# Highest expanded_loudspeaker_layout defined before v2.0.0: v1.1.0 reserves
# 13..255 (v1.1:1073) and v1.0.0-errata has no expanded layouts at all
# (err:985); 13..19 arrive with v2.0.0 (v2:1105-1123). No sentence says
# whether a profile defined by the older text admits them, so against a
# PRE_V2 profile such an element is unsettled: not counted, not judged.
PRE_V2_MAX_EXPANDED_LAYOUT = 12


def later_layout(ae: m.AudioElement) -> bool:
    """A channel-based element whose expanded layout was added by v2.0.0."""
    if ae.audio_element_type != m.AUDIO_ELEMENT_CHANNEL or not ae.channel_layers:
        return False
    top = ae.channel_layers[-1]
    return (top.loudspeaker_layout == 15
            and (top.expanded_loudspeaker_layout or 0) > PRE_V2_MAX_EXPANDED_LAYOUT)


def element_channels(ae: m.AudioElement) -> tuple[int, int] | None:
    """(declared, coded) channel count of one Audio Element; None = unknown.

    Channel-based: the layout of the highest layer (the expanded layout when
    loudspeaker_layout is 15). Object-based: num_objects, one channel per
    object (v2:1318-1320, "11 objects (11 channels)" v2:3235). Scene-based:
    output_channel_count declared, substreams + coupled coded — the two differ
    for mixed-order and projection content and the limits do not say which
    one is meant, so callers get both.
    """
    if ae.audio_element_type == m.AUDIO_ELEMENT_CHANNEL:
        if not ae.channel_layers:
            return None
        top = ae.channel_layers[-1]
        if top.loudspeaker_layout == 15:
            n = EXPANDED_LAYOUT_CHANNELS.get(top.expanded_loudspeaker_layout)
        else:
            cl = LOUDSPEAKER_LAYOUT.get(top.loudspeaker_layout)
            n = cl.channels if cl else None          # 10..14 are reserved
        return None if n is None else (n, n)
    if ae.audio_element_type == m.AUDIO_ELEMENT_SCENE:
        a = ae.ambisonics
        if a is None:                                # ambisonics_mode not modelled
            return None
        return (a.output_channel_count, a.coded_channel_count)
    if ae.audio_element_type == m.AUDIO_ELEMENT_OBJECT:
        # num_objects 0 is forbidden (v2:1316) and is not a channel count.
        if ae.objects is None or ae.objects.num_objects == 0:
            return None
        return (ae.objects.num_objects, ae.objects.num_objects)
    return None                                      # reserved audio_element_type


def _count_text(declared: int, coded: int, complete: bool = True) -> str:
    """The channel total as read; "at least" when some element is unknown."""
    floor = "" if complete else "at least "
    if declared == coded:
        return f"{floor}{declared} channels"
    return (f"{floor}{declared} channels by output_channel_count / {coded} by "
            "coded channels")


@dataclass
class _Mix:
    """What one Mix Presentation references, summed over its sub-mixes."""
    mp: m.MixPresentation
    n_elements: int = 0
    # Channel totals over the elements whose count is known: scene-based by
    # output_channel_count (declared) and by coded channels (coded).
    declared: int = 0
    coded: int = 0
    channels_known: bool = True       # False: the totals are lower bounds
    # Elements counted above whose expanded layout arrived with v2.0.0, and
    # their channels: taken back out when judging against a PRE_V2 profile.
    later_layout_ids: list[int] = field(default_factory=list)
    later_layout_channels: int = 0
    # 1-based indexes of sub-mixes with num_audio_elements = 0 (v2:1382
    # "SHALL NOT be set to 0"); such a Mix Presentation is inside no profile,
    # and neither is one with no sub-mixes at all (v2:1380).
    empty_sub_mixes: list[int] = field(default_factory=list)
    object_ids: list[int] = field(default_factory=list)
    scene_ids: list[int] = field(default_factory=list)
    scalable_ids: list[int] = field(default_factory=list)
    channel_ids: list[int] = field(default_factory=list)

    @property
    def name(self) -> str:
        return f"mix_presentation {self.mp.mix_presentation_id}"


def _survey(mod: m.IAMFModel, mp: m.MixPresentation) -> _Mix:
    mix = _Mix(mp)
    for i, sm in enumerate(mp.sub_mixes, start=1):
        if not sm.audio_element_ids:
            mix.empty_sub_mixes.append(i)
        for aid in sm.audio_element_ids:
            mix.n_elements += 1
            ae = mod.audio_elements.get(aid)
            if ae is None:                           # dangling: S-106 reports it
                mix.channels_known = False
                continue
            if ae.audio_element_type == m.AUDIO_ELEMENT_OBJECT:
                mix.object_ids.append(aid)
            elif ae.audio_element_type == m.AUDIO_ELEMENT_SCENE:
                mix.scene_ids.append(aid)
            elif ae.audio_element_type == m.AUDIO_ELEMENT_CHANNEL:
                mix.channel_ids.append(aid)
                if len(ae.channel_layers) > 1:
                    mix.scalable_ids.append(aid)
            counts = element_channels(ae)
            if counts is None:
                mix.channels_known = False
            else:
                mix.declared += counts[0]
                mix.coded += counts[1]
                if later_layout(ae):
                    mix.later_layout_ids.append(aid)
                    mix.later_layout_channels += counts[0]
    return mix


def _mixes(mod: m.IAMFModel) -> list[_Mix]:
    """Each Mix Presentation once, in file order. A stream may repeat its
    descriptors as redundant copies; the first OBU with a given
    mix_presentation_id stands for all of them."""
    seen: set[int] = set()
    out: list[_Mix] = []
    for mp in mod.mix_presentations:
        if mp.mix_presentation_id not in seen:
            seen.add(mp.mix_presentation_id)
            out.append(_survey(mod, mp))
    return out


@dataclass
class _Fit:
    """One Mix Presentation against one profile."""
    violations: list[str]             # definite; empty when none
    channels: str                     # "ok" | "over" | "open" | "unknown"
    # Elements left unjudged because their layout is reserved in the version
    # that defines this profile (they make the channel test "unknown").
    unsettled_ids: list[int] = field(default_factory=list)

    @property
    def state(self) -> str:
        """"no" (definitely outside), "unknown", or "yes" (an open channel
        count is read in the file's favour and reported as INFO)."""
        if self.violations:
            return "no"
        return "unknown" if self.channels == "unknown" else "yes"


def _fit(mix: _Mix, p: int) -> _Fit:
    name = m.PROFILE_NAME[p]
    out: list[str] = []
    if not mix.mp.sub_mixes:             # v2:1380 "SHALL NOT be set to 0"
        out.append("num_sub_mixes = 0, which no profile admits")
    for i in mix.empty_sub_mixes:
        out.append(f"sub-mix {i} has num_audio_elements = 0, which no profile admits")
    if mix.n_elements > MAX_AUDIO_ELEMENTS[p]:
        out.append(f"{mix.n_elements} audio elements (limit {MAX_AUDIO_ELEMENTS[p]})")
    n_sub = len(mix.mp.sub_mixes)
    if n_sub > MAX_SUB_MIXES[p]:
        out.append(f"{n_sub} sub-mixes (limit {MAX_SUB_MIXES[p]})")
    if p in PRE_V2_PROFILES and mix.object_ids:
        out.append(f"object-based audio_element(s) {mix.object_ids} (the {name} "
                   "profile defines channel-based and scene-based elements only)")
    if p == 1:
        if len(mix.scalable_ids) > BASE_MAX_SCALABLE_ELEMENTS:
            out.append(f"{len(mix.scalable_ids)} scalable channel-based elements "
                       f"(limit {BASE_MAX_SCALABLE_ELEMENTS})")
        if len(mix.scene_ids) > BASE_MAX_SCENE_ELEMENTS:
            out.append(f"{len(mix.scene_ids)} scene-based elements "
                       f"(limit {BASE_MAX_SCENE_ELEMENTS})")
    cap = MAX_CHANNELS[p]
    unsettled = mix.later_layout_ids if p in PRE_V2_PROFILES else []
    declared, coded = mix.declared, mix.coded
    if unsettled:
        declared -= mix.later_layout_channels
        coded -= mix.later_layout_channels
    known = mix.channels_known and not unsettled
    if min(declared, coded) > cap:
        # Over under both counts. The known elements alone exceed the limit,
        # so an unknown element beside them cannot bring the mix back under.
        channels = "over"
        out.append(f"{_count_text(declared, coded, known)} "
                   f"before mixing (limit {cap})")
    elif not known:
        channels = "unknown"
    elif max(declared, coded) > cap:                 # over under exactly one
        channels = "open"
    else:
        channels = "ok"
    return _Fit(out, channels, list(unsettled))


def _open_count_text(declared: int, coded: int, cap: int) -> str:
    """Which of the two scene-based counts is over ``cap``."""
    if declared > coded:
        over, within = (f"output_channel_count ({declared})",
                        f"coded channels, substreams + coupled ({coded})")
    else:
        over, within = (f"coded channels, substreams + coupled ({coded})",
                        f"output_channel_count ({declared})")
    return (f"over when scene-based elements are counted by {over}, within "
            f"it when counted by {within}")


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    sh = mod.sequence_header
    if sh is None or sh.primary_profile not in m.PROFILE_NAME:
        return          # no header is S-101's; a reserved primary_profile is S-102's
    pp, ap = sh.primary_profile, sh.additional_profile
    yield from _mix_presentations(mod, ctx, pp, ap)
    yield from _sequence_channel_total(mod, ctx, pp, ap)
    if pp == 3:
        yield from _base_advanced_first_mix(mod, ctx)
    yield from _codec_config_count(mod, ctx, pp)


def _mix_presentations(mod: m.IAMFModel, ctx: CheckContext, pp: int,
                       ap: int) -> Iterator[Finding]:
    if not mod.mix_presentations:
        return                                       # S-105 reports it
    pname = m.PROFILE_NAME[pp]
    mixes = _mixes(mod)
    primary = [_fit(mix, pp) for mix in mixes]

    # No Mix Presentation complies with primary_profile (v2:3164, v1.1:1929).
    if all(f.state == "no" for f in primary):
        best = min(range(len(mixes)), key=lambda i: len(primary[i].violations))
        yield finding(
            ctx, "S-109",
            f"no Mix Presentation fits primary_profile {pname} ({pp}); the "
            f"nearest is {mixes[best].name}: {'; '.join(primary[best].violations)}",
            where=mixes[best].name,
            expected=f"at least one Mix Presentation within the {pname} profile",
            found=f"{len(mixes)} Mix Presentation(s), none within it",
            severity=Severity.FAIL)
        return

    ap_defined = ap in m.PROFILE_NAME
    for mix, fit in zip(mixes, primary):
        other = _fit(mix, ap) if (ap_defined and ap != pp) else None
        judged = pp                      # the profile whose fit decides this mix
        if fit.state == "no":
            if other is None:
                if ap == pp:
                    msg = (f"{mix.name} is outside the {pname} profile ({pp}), "
                           f"the only profile this sequence declares: "
                           f"{'; '.join(fit.violations)}. A {pname} decoder is "
                           "not required to play it")
                else:
                    msg = (f"{mix.name} is outside primary_profile {pname} "
                           f"({pp}): {'; '.join(fit.violations)}. "
                           f"additional_profile {ap} is reserved, so no "
                           "declared profile is known to cover it")
                yield finding(ctx, "S-109", msg, where=mix.name)
                continue
            if other.state == "no":
                aname = m.PROFILE_NAME[ap]
                yield finding(
                    ctx, "S-109",
                    f"{mix.name} is outside both declared profiles — "
                    f"primary_profile {pname} ({pp}): {'; '.join(fit.violations)}; "
                    f"additional_profile {aname} ({ap}): "
                    f"{'; '.join(other.violations)}. A decoder of either profile "
                    "is not required to play it", where=mix.name)
                continue
            # Outside primary, inside (or possibly inside) additional: the
            # design working as intended. Only an open point is worth a note.
            fit, judged = other, ap
        jname, cap = m.PROFILE_NAME[judged], MAX_CHANNELS[judged]
        if fit.state == "unknown" and fit.unsettled_ids:
            yield finding(
                ctx, "S-109",
                f"{mix.name}: audio_element(s) {fit.unsettled_ids} use an "
                "expanded_loudspeaker_layout that IAMF v2.0.0 adds and that is "
                f"reserved in {PRE_V2_PROFILES[judged]}, the version that defines "
                f"the {jname} profile ({judged}). The specification does not say "
                "whether that profile admits such a layout, so the mix is not "
                f"judged against the {jname} profile", where=mix.name,
                severity=Severity.INFO)
        elif fit.state == "yes" and fit.channels == "open":
            yield finding(
                ctx, "S-109",
                f"{mix.name}: against the {jname} profile ({judged}) limit of "
                f"{cap} channels the mix is "
                f"{_open_count_text(mix.declared, mix.coded, cap)}. The "
                "specification does not say which count the limit uses, so the "
                "mix is not treated as over it", where=mix.name,
                severity=Severity.INFO)


def _recognised(ae: m.AudioElement, ap: int) -> bool | None:
    """Whether a parser of profile ``ap`` recognises the element: True, False,
    or None when the text does not settle it."""
    if ae.audio_element_type not in (m.AUDIO_ELEMENT_CHANNEL, m.AUDIO_ELEMENT_SCENE,
                                     m.AUDIO_ELEMENT_OBJECT):
        return False                                 # reserved type (v2:831)
    if ap in PRE_V2_PROFILES:
        if ae.audio_element_type == m.AUDIO_ELEMENT_OBJECT:
            return False
        if later_layout(ae):
            # Reserved in v1.1.0, defined in v2.0.0: whether a
            # Base-Enhanced parser "can recognize" it is not settled.
            return None
    return True


def _sequence_channel_total(mod: m.IAMFModel, ctx: CheckContext, pp: int,
                            ap: int) -> Iterator[Finding]:
    cap = SEQUENCE_MAX_CHANNELS.get(ap)
    if cap is None or (ap == 2 and pp > 2):          # v1.1:1953 binds pp <= 2 only
        return
    declared = coded = 0
    complete = True
    for ae in mod.audio_elements.values():
        known = _recognised(ae, ap)
        if known is False:
            continue             # the total counts recognisable elements only
        counts = element_channels(ae)
        if known is None or counts is None:
            complete = False     # unknown: left out, the total is a lower bound
            continue
        declared += counts[0]
        coded += counts[1]
    aname = m.PROFILE_NAME[ap]
    if min(declared, coded) > cap:
        # Over under both counts, on the known recognisable elements alone.
        yield finding(
            ctx, "S-109",
            f"{_count_text(declared, coded, complete)} in total across the Audio "
            f"Elements of the IA Sequence; with additional_profile {aname} ({ap}) "
            f"the total is limited to {cap}",
            expected=f"at most {cap} channels in total",
            found=_count_text(declared, coded, complete), severity=Severity.FAIL)
    elif not complete:
        return                   # within the limit so far, the rest unknown
    elif max(declared, coded) > cap:
        yield finding(
            ctx, "S-109",
            f"against the limit of {cap} channels in total across the Audio "
            f"Elements of the IA Sequence (additional_profile {aname}, {ap}) the "
            f"sequence is {_open_count_text(declared, coded, cap)}. The "
            "specification does not say which count the limit uses, so the "
            "sequence is not treated as over it", severity=Severity.INFO)


def _base_advanced_first_mix(mod: m.IAMFModel,
                             ctx: CheckContext) -> Iterator[Finding]:
    """primary_profile 3 only (v2:3195-3199): when a Mix Presentation for at
    most 18 Audio Elements references object-based elements, the first Mix
    Presentation references object-based elements only."""
    mixes = _mixes(mod)              # mixes[0] is the first Mix Presentation OBU
    cap = MAX_AUDIO_ELEMENTS[3]                      # 18, v2:3197
    with_objects = [mix for mix in mixes
                    if mix.object_ids and mix.n_elements <= cap]
    if not with_objects:
        return
    first = mixes[0]
    others = sorted(first.channel_ids + first.scene_ids)
    if not others:
        return
    kinds = " and ".join(k for k, ids in (("channel-based", first.channel_ids),
                                         ("scene-based", first.scene_ids)) if ids)
    yield finding(
        ctx, "S-109",
        f"primary_profile Base-Advanced (3): {with_objects[0].name} references "
        f"object-based audio elements, so the first Mix Presentation "
        f"({first.name}) has to reference object-based elements only, but it "
        f"references {kinds} audio_element(s) {others}",
        where=first.name, expected="object-based elements only in the first "
        "Mix Presentation", found=f"{kinds} audio_element(s) {others}",
        severity=Severity.FAIL)


def _codec_config_count(mod: m.IAMFModel, ctx: CheckContext,
                        pp: int) -> Iterator[Finding]:
    # Unique Codec Config OBUs = distinct codec_config_id values. Comparing
    # bytes would be wrong: a redundant copy is the same OBU (v2:3135) even
    # when it carries trailing bytes the original does not, since obu_size MAY
    # exceed the syntax and parsers ignore the excess (v2:643).
    n = len(mod.codec_configs)
    pname = m.PROFILE_NAME[pp]
    limit = MAX_CODEC_CONFIGS[pp]
    if n > limit:
        allowed = "only one" if limit == 1 else f"at most {limit}"
        yield finding(
            ctx, "S-109",
            f"{n} unique Codec Config OBUs; primary_profile {pname} ({pp}) "
            f"allows {allowed}", expected=f"{allowed} unique Codec Config OBU(s)",
            found=str(n), severity=Severity.FAIL)
    elif (n > 1 and mod.mix_presentations
          and all(len(mp.sub_mixes) == 1 for mp in mod.mix_presentations)):
        # v2:3143: one unique Codec Config OBU if num_sub_mixes = 1 in all
        # Mix Presentation OBUs, "otherwise there MAY be two".
        yield finding(
            ctx, "S-109",
            f"{n} unique Codec Config OBUs while every Mix Presentation has one "
            f"sub-mix; primary_profile {pname} ({pp}) allows a second Codec "
            "Config only when some Mix Presentation has more than one sub-mix",
            expected="only one unique Codec Config OBU", found=str(n),
            severity=Severity.FAIL)
