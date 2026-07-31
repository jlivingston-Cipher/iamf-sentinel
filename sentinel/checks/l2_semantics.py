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
"""

from __future__ import annotations
from collections.abc import Iterator

from .base import CheckContext, finding
from ..findings import Finding
from .. import model as m
from ..layouts import (LOUDSPEAKER_LAYOUT, RESERVED_LOUDSPEAKER_LAYOUTS,
                       EXPANDED_LOUDSPEAKER_LAYOUT)

_TEMPLATE_ANNOTATIONS = ("test_mix_pres", "test_sub_mix_", "test_audio_element",
                         "testmix", "default mix presentation", "mainelement")


def run(mod: m.IAMFModel, ctx: CheckContext) -> Iterator[Finding]:
    yield from _channel_topology(mod, ctx)
    yield from _ambisonics(mod, ctx)
    yield from _param_rate(mod, ctx)
    yield from _substream_ids(mod, ctx)
    yield from _frame_coverage(mod, ctx)
    yield from _annotations(mod, ctx)


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
            cum_sub += layer.substream_count
            cum_coupled += layer.coupled_substream_count
            top_layout = cl

        # S-201 top-layout consistency: cumulative substreams/coupled must equal
        # the final layout's canonical topology (coupled-pairs-first invariant).
        if top_layout and top_layout.expected_substreams >= 0:
            if (cum_sub != top_layout.expected_substreams or
                    cum_coupled != top_layout.expected_coupled):
                yield finding(
                    ctx, "S-201",
                    f"substream topology does not match declared {top_layout.name} layout — "
                    f"an F4-class silent-corruption signature",
                    where=where,
                    expected=f"{top_layout.expected_substreams} substreams "
                             f"({top_layout.expected_coupled} coupled) for {top_layout.name}",
                    found=f"{cum_sub} substreams ({cum_coupled} coupled)")
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
