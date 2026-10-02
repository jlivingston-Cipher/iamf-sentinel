"""L2 channel-semantics checks (S-2xx): the F4 killer.

At the descriptor level Sentinel catches the *structurally expressible* F4
family: a topology declaration that is internally inconsistent with its
loudspeaker_layout, a substream set that does not match the declaration
(dropped/duplicated substream), ambisonics that violate (N+1)^2/ACN
completeness, zero parameter_rate (F1), and duplicate substream ids. The one
F4 sub-class that is byte-identical in the descriptor (essence physically
misrouted while counts stay correct) is caught by L3 channel-identity on
decoded PCM (Phase 2, decoder oracle) — flagged as such, never silently
claimed here.

S-210..S-217 are the object and rendering checks: what IAMF v2.0.0 says of an
object-based element's ObjectsConfig() and of the RenderingConfig() a Mix
Presentation gives each element. They read descriptors, and S-217 the sizes
of LPCM audio frames. Positions over time — the Parameter Block OBUs a
position definition points at — are not read, so a clean result says nothing
about them. Citations are source line numbers of IAMF v2.0.0 (``v2:``,
index.bs at 4d2c6da).

Three things are left unjudged on purpose, each because the specification does
not settle it or the parser has already said what is wrong:

* an element of a reserved audio_element_type (3..7), and a rendering config
  that points at one. Parsers are told to ignore such an Audio Element OBU
  (v2:831) and the Mix Presentations that use it (v2:1384); a later version
  may define the type with rules of its own.
* a type-2 element whose config bytes are not an ObjectsConfig(), and a
  rendering config whose extension bytes are not the v2.0.0 syntax. The parser
  reports both (a note, or S-108 under a profile that v2.0.0 defines).
* a rendering config that carries a parameter definition type this version
  does not define. It may be the position definition of a later version, so
  the element is not said to lack one; S-216 reports the unknown type.
"""

from __future__ import annotations
from collections.abc import Iterator

from .base import CheckContext, finding
from ..findings import Finding, Severity
from .. import model as m
from ..layouts import (LOUDSPEAKER_LAYOUT, RESERVED_LOUDSPEAKER_LAYOUTS,
                       EXPANDED_LOUDSPEAKER_LAYOUT, channel_group_counts)

_TEMPLATE_ANNOTATIONS = ("test_mix_pres", "test_sub_mix_", "test_audio_element",
                         "testmix", "default mix presentation", "mainelement")


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    yield from _channel_topology(mod, ctx)
    yield from _ambisonics(mod, ctx)
    yield from _param_rate(mod, ctx)
    yield from _substream_ids(mod, ctx)
    yield from _frame_coverage(mod, ctx)
    yield from _annotations(mod, ctx)
    yield from _objects(mod, ctx)
    yield from _rendering(mod, ctx)
    yield from _object_frames(mod, ctx)


def _channel_topology(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    for aid, ae in mod.audio_elements.items():
        if ae.audio_element_type != m.AUDIO_ELEMENT_CHANNEL:
            continue
        where = f"audio_element {aid}"
        if not ae.channel_layers:
            yield finding(ctx, "S-202", "channel-based element has no channel layers",
                          where=where)
            continue

        cum_sub = cum_coupled = 0
        top_layout = None
        below = None      # loudspeaker_layout of the layer under this one
        for i, layer in enumerate(ae.channel_layers):
            lsl = layer.loudspeaker_layout
            # reserved / expanded handling
            if lsl in RESERVED_LOUDSPEAKER_LAYOUTS:
                yield finding(ctx, "S-201", f"layer {i} uses reserved loudspeaker_layout {lsl}",
                              where=where, found=str(lsl))
                continue
            if lsl == 15:
                exp = layer.expanded_loudspeaker_layout
                name = EXPANDED_LOUDSPEAKER_LAYOUT.get(exp, f"expanded-{exp}")
                # Base-Enhanced expanded layout: light sanity only
                if layer.coupled_substream_count > layer.substream_count:
                    yield finding(ctx, "S-201", f"expanded layout {name}: coupled "
                                  f"({layer.coupled_substream_count}) exceeds substreams "
                                  f"({layer.substream_count})", where=where)
                cum_sub += layer.substream_count
                cum_coupled += layer.coupled_substream_count
                top_layout = None
                below = lsl
                continue

            cl = LOUDSPEAKER_LAYOUT.get(lsl)
            # per-layer sanity
            if layer.coupled_substream_count > layer.substream_count:
                yield finding(ctx, "S-201",
                              f"layer {i} ({cl.name if cl else lsl}): coupled_substream_count "
                              f"({layer.coupled_substream_count}) exceeds substream_count "
                              f"({layer.substream_count})", where=where,
                              expected="coupled <= substream",
                              found=f"{layer.coupled_substream_count} > {layer.substream_count}")
            if cl and cl.name == "Mono" and layer.coupled_substream_count != 0:
                yield finding(ctx, "S-201", "Mono layout cannot have a coupled substream",
                              where=where, expected="0 coupled", found=str(layer.coupled_substream_count))

            # S-201 layer topology: a layer declares the substreams of its own
            # Channel Group (coupled-pairs-first invariant). The first layer's
            # group is its whole layout; a layer above it holds only what its
            # layout adds to the layer below (v2:1180-1193), so the counts
            # follow from the pair of layouts, not from the top layout alone:
            # over a Mono first layer L2 is a substream of its own and never
            # half of a coupled L/R (v2:1185, v2:1039). A layout that the
            # Channel Layout Generation Rule does not let follow the layer
            # below (v2:1167-1171), a Binaural layer of a scalable element
            # (v2:964) and a layer above an expanded layout (v2:1138) have no
            # Channel Group to be counted against.
            want = channel_group_counts(below, lsl)
            over = (cl.name if below is None
                    else f"{cl.name} over {LOUDSPEAKER_LAYOUT[below].name}")
            if want is None:
                yield finding(
                    ctx, "S-201",
                    f"layer {i}: {over} is not a step a scalable element can take — "
                    f"no Channel Group is defined for it",
                    where=where,
                    expected="surround, LFE and height channel counts that never decrease "
                             "and are not all equal; Binaural and expanded layouts only "
                             "as a single layer",
                    found=over)
            elif want != (layer.substream_count, layer.coupled_substream_count):
                what = (f"declared {cl.name} layout" if below is None
                        else f"what layer {i} adds ({over})")
                yield finding(
                    ctx, "S-201",
                    f"substream topology does not match {what} — "
                    f"an F4-class silent-corruption signature",
                    where=where,
                    expected=f"{want[0]} substreams ({want[1]} coupled) for {over}",
                    found=f"{layer.substream_count} substreams "
                          f"({layer.coupled_substream_count} coupled)")
            cum_sub += layer.substream_count
            cum_coupled += layer.coupled_substream_count
            top_layout = cl
            below = lsl

        if top_layout and top_layout.expected_substreams >= 0:
            # channel-count implied by topology
            implied_ch = 2 * cum_coupled + (cum_sub - cum_coupled)
            if implied_ch != top_layout.channels:
                yield finding(
                    ctx, "S-201",
                    f"channel count implied by substreams ({implied_ch}) != {top_layout.name} "
                    f"channel count ({top_layout.channels})", where=where,
                    expected=f"{top_layout.channels} channels", found=f"{implied_ch}")

        # S-202 element num_substreams vs layer sum
        if cum_sub and ae.num_substreams != cum_sub:
            yield finding(ctx, "S-202",
                          f"num_substreams ({ae.num_substreams}) != sum of layer "
                          f"substream_count ({cum_sub})", where=where,
                          expected=str(cum_sub), found=str(ae.num_substreams))
        if len(ae.audio_substream_ids) != ae.num_substreams:
            yield finding(ctx, "S-202",
                          f"audio_substream_ids length ({len(ae.audio_substream_ids)}) != "
                          f"num_substreams ({ae.num_substreams})", where=where)


def _ambisonics(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    for aid, ae in mod.audio_elements.items():
        a = ae.ambisonics
        if a is None:
            continue
        where = f"audio_element {aid} (scene)"
        if a.order is None:
            yield finding(ctx, "S-203",
                          f"output_channel_count {a.output_channel_count} is not (N+1)^2 — "
                          "not a valid ambisonics channel count", where=where,
                          found=str(a.output_channel_count))
            continue
        if a.mode == 0:  # MONO
            if len(a.channel_mapping) != a.output_channel_count:
                yield finding(ctx, "S-203",
                              f"channel_mapping length ({len(a.channel_mapping)}) != "
                              f"output_channel_count ({a.output_channel_count})", where=where)
            used = [x for x in a.channel_mapping if x != 255]
            if len(set(used)) != len(used):
                dup = sorted({x for x in used if used.count(x) > 1})
                yield finding(ctx, "S-203",
                              f"ACN channel_mapping has duplicate substream references {dup} "
                              "(ambisonics completeness violation)", where=where, found=str(dup))
            expected = set(range(a.substream_count))
            if set(used) != expected and a.substream_count == a.output_channel_count:
                missing = sorted(expected - set(used))
                if missing:
                    yield finding(ctx, "S-203",
                                  f"ACN channel_mapping does not cover substreams {missing} "
                                  "(gap in ambisonics scene)", where=where, found=str(sorted(used)))
            if ae.num_substreams != a.substream_count:
                yield finding(ctx, "S-203",
                              f"element num_substreams ({ae.num_substreams}) != ambisonics "
                              f"substream_count ({a.substream_count})", where=where)


def _param_rate(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    for aid, ae in mod.audio_elements.items():
        for pd in ae.parameters:
            if not pd.rate_present or pd.parameter_rate == 0:
                yield finding(ctx, "S-204",
                              f"parameter_id {pd.parameter_id} has parameter_rate 0 "
                              "(F1: rate required per parameter_id)",
                              where=f"audio_element {aid}", found="0")


def _substream_ids(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    all_ids: list[int] = []
    for ae in mod.audio_elements.values():
        all_ids.extend(ae.audio_substream_ids)
    seen = set()
    dups = sorted({x for x in all_ids if x in seen or seen.add(x)})
    if dups:
        yield finding(ctx, "S-205",
                      f"audio_substream_id(s) {dups} declared by more than one element/slot "
                      "(routing ambiguity)", found=str(dups))


def _frame_coverage(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    if not mod.audio_frames:
        return  # descriptor-only input (e.g. MP4 config box); coverage needs the mdat
    declared = set()
    for ae in mod.audio_elements.values():
        declared.update(ae.audio_substream_ids)
    framed = {f.substream_id for f in mod.audio_frames}
    missing = sorted(declared - framed)
    extra = sorted(framed - declared)
    if missing:
        yield finding(ctx, "S-207",
                      f"declared substream(s) {missing} carry no audio frames "
                      "(dropped substream — F4-class)", expected=f"frames for {sorted(declared)}",
                      found=f"frames for {sorted(framed)}")
    if extra:
        yield finding(ctx, "S-207",
                      f"audio frame(s) reference undeclared substream(s) {extra} "
                      "(spurious/duplicated substream — F4-class)",
                      expected=f"substreams {sorted(declared)}", found=str(sorted(framed)))

    # S-206 first-temporal-unit coverage: the first TU is the maximal frame prefix
    # with no repeated substream id (frames are grouped per temporal unit).
    first_tu: set[int] = set()
    for f in mod.audio_frames:
        if f.substream_id in first_tu:
            break
        first_tu.add(f.substream_id)
    if first_tu and first_tu != declared and not missing and not extra:
        yield finding(ctx, "S-206",
                      "first temporal unit does not contain a frame for every substream",
                      expected=f"{sorted(declared)}", found=f"{sorted(first_tu)}")


def _annotations(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    for mp in mod.mix_presentations:
        for ann in mp.annotations:
            low = ann.strip().lower()
            if any(t in low for t in _TEMPLATE_ANNOTATIONS) or low == "":
                yield finding(ctx, "S-208",
                              f"mix_presentation annotation {ann!r} is a template/placeholder — "
                              "source programme names were dropped (F24)",
                              where=f"mix_presentation {mp.mix_presentation_id}", found=ann)
                break


# ------------------------------------------------- objects and rendering
def _objects(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    """S-210: what the specification says of an object-based Audio Element."""
    for aid, ae in mod.audio_elements.items():
        if ae.audio_element_type != m.AUDIO_ELEMENT_OBJECT or ae.objects is None:
            continue
        where = f"audio_element {aid} (object)"
        n = ae.objects.num_objects
        if n == 0:                                   # v2:1316 "SHALL NOT be set to 0"
            yield finding(ctx, "S-210", "num_objects is 0; an object-based element "
                          "provides the audio of at least one object", where=where,
                          expected="1 or 2", found="0")
        elif n > 2:
            # Not forbidden in so many words: only 0 is. But 1 and 2 are the
            # only counts given a meaning (v2:1318-1320) and the only ones a
            # position definition is allowed for (v2:1554-1562).
            yield finding(ctx, "S-210", f"num_objects is {n}; IAMF v2.0.0 gives a "
                          "meaning to 1 and 2 only and allows no position "
                          "definition for any other count, so no parser of this "
                          "version can place these objects", where=where,
                          expected="1 or 2", found=str(n), severity=Severity.WARN)
        if ae.num_parameters != 0:                   # v2:849 "SHALL be set to 0"
            yield finding(ctx, "S-210", f"num_parameters is {ae.num_parameters} in "
                          "the Audio Element OBU of an object-based element; it has "
                          "to be 0 (an object's position definition belongs to the "
                          "rendering_config of a Mix Presentation)", where=where,
                          expected="0", found=str(ae.num_parameters))
        if ae.num_substreams != 1:
            # No sentence says "one substream". ObjectsConfig() speaks of "the
            # referenced Audio Substream", whose channels are the objects
            # (v2:1316-1320), and says nothing of a second one.
            yield finding(ctx, "S-210", f"object-based element declares "
                          f"{ae.num_substreams} audio substreams; ObjectsConfig "
                          "describes one Audio Substream that carries every object "
                          "of the element, and the specification gives no meaning "
                          "to further substreams", where=where, expected="1",
                          found=str(ae.num_substreams), severity=Severity.WARN)


def _q78(raw: int) -> str:
    return f"{raw / 256.0:+.2f} dB"


def _position_range_problems(pd: m.PositionParamDefinition) -> list[str]:
    """Default position values outside the range the specification states."""
    ptype = pd.param_definition_type
    out: list[str] = []
    for i, (a, b, c) in enumerate(pd.defaults):
        obj = f"object {i + 1} " if len(pd.defaults) > 1 else ""
        if ptype in m.POLAR_PARAM_TYPES:
            # Defined by clipping (v2:1687-1695); the 7-bit distance cannot
            # leave 0..127, that is 0.0..1.0 (v2:1697-1700).
            if not -180 <= a <= 180:
                out.append(f"{obj}default azimuth {a} is outside -180..180 degrees "
                           f"(a parser clips it to {max(-180, min(180, a))})")
            if not -90 <= b <= 90:
                out.append(f"{obj}default elevation {b} is outside -90..90 degrees "
                           f"(a parser clips it to {max(-90, min(90, b))})")
            continue
        # Cartesian: value / 127 or value / 32767 (v2:1780-1793, v2:1812-1825),
        # where -1.0 and 1.0 are the surface of the cube (v2:1738). Only the
        # most negative code falls outside it.
        scale = 127 if ptype in (m.PARAM_CART8, m.PARAM_DUAL_CART8) else 32767
        for axis, v in zip("xyz", (a, b, c)):
            if v < -scale:
                out.append(f"{obj}default {axis} {v} normalises to {v / scale:.5f}, "
                           "outside the -1.0..1.0 cube (the specification does not "
                           "say how a parser treats it)")
    return out


def _rendering(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    """S-211..S-216: the RenderingConfig() of every element of every sub-mix.

    A Mix Presentation is judged once, however many redundant copies of the
    descriptors the stream repeats."""
    seen: set[int] = set()
    for mp in mod.mix_presentations:
        if mp.mix_presentation_id in seen:
            continue
        seen.add(mp.mix_presentation_id)
        ignored: list[str] = []          # why a parser ignores this Mix Presentation
        for sm in mp.sub_mixes:
            for aid, rc in zip(sm.audio_element_ids, sm.rendering_configs):
                where = f"mix_presentation {mp.mix_presentation_id} / audio_element {aid}"
                yield from _rendering_config(mod, ctx, aid, rc, where, ignored)
        if ignored:
            yield finding(
                ctx, "S-216",
                f"mix_presentation {mp.mix_presentation_id} is one that parsers of "
                f"IAMF v2.0.0 are told to ignore: {'; '.join(ignored)}",
                where=f"mix_presentation {mp.mix_presentation_id}")


def _rendering_config(mod: m.IAMFModel, ctx: CheckContext, aid: int,
                      rc: m.RenderingConfig, where: str,
                      ignored: list[str]) -> Iterator[Finding]:
    # S-215: binaural_filter_profile 3 is "Reserved for future use" (v2:1537).
    if rc.binaural_filter_profile not in m.BINAURAL_FILTER_PROFILE_NAME:
        yield finding(ctx, "S-215", f"binaural_filter_profile "
                      f"{rc.binaural_filter_profile} is reserved; IAMF v2.0.0 "
                      "defines 0 (AMBIENT), 1 (DIRECT) and 2 (REVERBERANT), so a "
                      "binaural renderer has no filter profile to use for this "
                      "element", where=where, expected="0, 1 or 2",
                      found=str(rc.binaural_filter_profile))

    # S-216, collected per Mix Presentation by the caller.
    if rc.headphones_rendering_mode not in m.DEFINED_HEADPHONES_RENDERING_MODES:
        ignored.append(f"audio_element {aid} has the reserved "       # v2:1515, v2:1519
                       f"headphones_rendering_mode {rc.headphones_rendering_mode}")
    unknown = [t for t in rc.other_param_definition_types if t not in m.PARAM_TYPE_NAME]
    if unknown:                                                       # v2:1565
        ignored.append(f"the rendering_config of audio_element {aid} carries "
                       f"param_definition_type {', '.join(map(str, unknown))}, which "
                       "this version does not define")

    if not rc.extension_read:
        return                           # the parser has reported it

    # S-211: which parameter definitions a RenderingConfig may hold.
    misplaced = [t for t in rc.other_param_definition_types if t in m.PARAM_TYPE_NAME]
    if misplaced:                        # v2:1550 "SHALL NOT contain any other type"
        names = ", ".join(f"{m.PARAM_TYPE_NAME[t]} ({t})" for t in misplaced)
        yield finding(ctx, "S-211", f"rendering_config carries param_definition_type "
                      f"{names}; the only types a rendering_config may hold are the "
                      "six position-based ones (3..8)", where=where,
                      expected="position-based definitions only", found=names)
    n_pos = len(rc.position_definitions)
    kinds = ", ".join(f"{m.PARAM_TYPE_NAME[pd.param_definition_type]} "
                      f"({pd.param_definition_type})" for pd in rc.position_definitions)
    ae = mod.audio_elements.get(aid)
    if ae is not None and ae.audio_element_type in (m.AUDIO_ELEMENT_CHANNEL,
                                                    m.AUDIO_ELEMENT_SCENE):
        if n_pos:                        # v2:1549 "only when ... OBJECT_BASED"
            kind = ("channel-based" if ae.audio_element_type == m.AUDIO_ELEMENT_CHANNEL
                    else "scene-based")
            yield finding(ctx, "S-211", f"rendering_config of a {kind} element "
                          f"carries a position definition ({kinds}); position "
                          "definitions belong to object-based elements only",
                          where=where, expected="no position definition",
                          found=kinds)
    elif (ae is not None and ae.audio_element_type == m.AUDIO_ELEMENT_OBJECT
          and ae.objects is not None):
        if n_pos == 0 and not unknown:   # v2:1549 "SHALL contain one of"
            yield finding(ctx, "S-211", "rendering_config of an object-based "
                          "element carries no position definition; it has to "
                          "contain one of POLAR, CART8, CART16, DUAL_POLAR, "
                          "DUAL_CART8, DUAL_CART16 (param_definition_type 3..8)",
                          where=where, expected="one position definition",
                          found="none")
        elif n_pos > 1:
            # "SHALL contain one of the position-based parameter definitions"
            # (v2:1549): read here as one, but the sentence does not say
            # "exactly one", so more than one is a warning.
            yield finding(ctx, "S-211", f"rendering_config of an object-based "
                          f"element carries {n_pos} position definitions "
                          f"({kinds}); the specification asks for one and does not "
                          "say which a parser uses when there are several",
                          where=where, expected="one position definition",
                          found=str(n_pos), severity=Severity.WARN)
        # S-212: single against dual (v2:1551, v2:1554-1562). A count other
        # than 1 or 2 has no row in that table; S-210 reports the count.
        n_obj = ae.objects.num_objects
        if n_obj in (1, 2):
            allowed = " / ".join(f"{m.PARAM_TYPE_NAME[t]} ({t})"
                                 for t, k in m.POSITION_PARAM_OBJECTS.items()
                                 if k == n_obj)
            for pd in rc.position_definitions:
                if m.POSITION_PARAM_OBJECTS[pd.param_definition_type] != n_obj:
                    name = m.PARAM_TYPE_NAME[pd.param_definition_type]
                    yield finding(
                        ctx, "S-212",
                        f"position definition {name} ({pd.param_definition_type}) "
                        f"places {m.POSITION_PARAM_OBJECTS[pd.param_definition_type]} "
                        f"object(s) but audio_element {aid} has num_objects = "
                        f"{n_obj}; the definitions allowed for {n_obj} object(s) "
                        f"are {allowed}", where=where, expected=allowed,
                        found=f"{name} ({pd.param_definition_type})")

    # S-213: default positions, whatever the element.
    for pd in rc.position_definitions:
        problems = _position_range_problems(pd)
        if problems:
            name = m.PARAM_TYPE_NAME[pd.param_definition_type]
            yield finding(ctx, "S-213", f"position definition {name} (parameter_id "
                          f"{pd.param.parameter_id}): {'; '.join(problems)}",
                          where=where)

    # S-214: the element gain offset.
    g = rc.element_gain_offset
    if g is None:
        return
    if g.element_gain_offset_type not in m.GAIN_OFFSET_TYPE_NAME:     # v2:1626
        yield finding(ctx, "S-214", f"element_gain_offset_type "
                      f"{g.element_gain_offset_type} is reserved; IAMF v2.0.0 "
                      "defines 0 (VALUE) and 1 (RANGE), so a parser skips the "
                      f"{g.extension_bytes} byte(s) that follow and applies no "
                      "element gain offset", where=where, expected="0 or 1",
                      found=str(g.element_gain_offset_type))
    elif g.element_gain_offset_type == m.GAIN_OFFSET_RANGE:
        if g.min_element_gain_offset > 0:                             # v2:1634
            yield finding(ctx, "S-214", "min_element_gain_offset is "
                          f"{_q78(g.min_element_gain_offset)}; a lower bound is "
                          "zero or negative, and a parser regards a positive one "
                          "as 0 dB", where=where, expected="at most 0 dB",
                          found=_q78(g.min_element_gain_offset))
        if g.max_element_gain_offset < 0:                             # v2:1636
            yield finding(ctx, "S-214", "max_element_gain_offset is "
                          f"{_q78(g.max_element_gain_offset)}; an upper bound is "
                          "zero or positive, and a parser regards a negative one "
                          "as 0 dB", where=where, expected="at least 0 dB",
                          found=_q78(g.max_element_gain_offset))


LPCM_SAMPLE_SIZES = (16, 24, 32)                     # v2:3111 "SHALL take a value"


def _object_frames(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    """S-217: one object is coded mono, two objects stereo (v2:1318-1320).

    The coding mode is a property of the coded frames, and frames are not
    decoded. For LPCM the size of a frame is enough: an audio_frame is one
    mono or stereo PCM frame (v2:3115) of num_samples_per_frame samples
    (v2:745) at sample_size bits, so its length gives the channel count. A
    frame whose length is neither is not judged here, and neither are the
    frames of any other codec.

    Frames come from the raw stream or, in MP4, from the sample walk; a file
    whose samples were not walked (fragmented MP4) is not judged.
    """
    frames = ctx.mp4.frame_refs if ctx.mp4 is not None else mod.audio_frames
    if not frames:
        return
    # substream id -> {frame length: how many frames}, in one pass
    lengths: dict[int, dict[int, int]] = {}
    for f in frames:
        by_length = lengths.setdefault(f.substream_id, {})
        by_length[f.frame_bytes] = by_length.get(f.frame_bytes, 0) + 1
    for aid, ae in mod.audio_elements.items():
        if (ae.audio_element_type != m.AUDIO_ELEMENT_OBJECT or ae.objects is None
                or ae.objects.num_objects not in (1, 2) or ae.num_substreams != 1):
            continue                                 # S-210 speaks for the rest
        cc = mod.codec_configs.get(ae.codec_config_id)
        if (cc is None or cc.codec_id != "ipcm" or cc.num_samples_per_frame <= 0
                or cc.bit_depth not in LPCM_SAMPLE_SIZES):
            continue
        n_obj = ae.objects.num_objects
        one_channel = cc.num_samples_per_frame * cc.bit_depth // 8
        other = 3 - n_obj                            # the other of mono / stereo
        sid = ae.audio_substream_ids[0]
        own = lengths.get(sid, {})
        wrong = own.get(other * one_channel, 0)
        if wrong:
            mode = {1: "one channel (mono)", 2: "two channels (stereo)"}
            yield finding(
                ctx, "S-217",
                f"num_objects is {n_obj}, so the element's audio substream has to "
                f"be coded as {mode[n_obj]}, but {wrong} of its {sum(own.values())} "
                f"LPCM frame(s) are {other * one_channel} bytes: {mode[other]} of "
                f"{cc.num_samples_per_frame} samples at {cc.bit_depth} bits",
                where=f"audio_element {aid} (object) / substream {sid}",
                expected=f"{n_obj * one_channel} bytes per frame",
                found=f"{other * one_channel} bytes")
