"""Scalable channel audio: S-201 reads a layer chain layer by layer.

A channel-based element of more than one layer carries one Channel Group per
layer. The first group is the first layer's whole layout. Each group above it
holds only the channels its layout adds to the layer below (Channel Group
Format, v2:1180-1193), a pair of coupled stereo channels as one coupled
substream and any other channel as a substream of its own (v2:1037-1039).
Which layout may follow which is the Channel Layout Generation Rule
(v2:1167-1171); Binaural and the expanded layouts stand alone (v2:964,
v2:1138). IAMF v1.1.0 and v1.0.0-errata say the same in their own lines.

S-201 used to hold an element's summed counts against those of its top layout
coded as a single layer. That is what the layers sum to from every first
layer but Mono: above Mono the L2 channel is a substream of its own, so the
element has one substream more and one coupled substream fewer. Every
Mono-based chain failed, valid or not — 87 of the 166 multi-layer chains the
rule permits — and AOM's Mono > Stereo > 5.1 conformance vector with them.

Every rule is exercised as a pair synthesised by fixtures/: a chain that
declares what its layers hold and says nothing, and one a step away that
fires. Test names say which is which — ``_silent`` expects no S-201,
``_fires`` expects one — because a test that has only ever passed proves
nothing.

The expected counts are written out here, not read from the module under
test: ALONE is a layout coded as a single layer, ADDS what a layer adds to the
layer below, one row per step the rule permits, with the channels named. The
two tables are checked against each other when this module is imported.
Citations (``v2:`` IAMF v2.0.0, by source line of index.bs at 4d2c6da) are
beside the rule in sentinel/layouts.py and sentinel/checks/l2_semantics.py.

Not covered: the expanded layouts, whose counts S-201 does not judge, and an
expanded layer placed above another layer, which S-201 does not flag.

All bytes are synthesised by fixtures/ — no reference vectors are involved.
"""

from __future__ import annotations

import pytest

from fixtures import build as B
from fixtures.mp4wrap import wrap_mp4
from sentinel.engine import validate_bytes
from sentinel.findings import Severity

NAME = {0: "Mono", 1: "Stereo", 2: "5.1", 3: "5.1.2", 4: "5.1.4", 5: "7.1",
        6: "7.1.2", 7: "7.1.4", 8: "3.1.2", 9: "Binaural"}
MONO, BINAURAL, EXPANDED = 0, 9, 15

# loudspeaker_layout -> (substream_count, coupled_substream_count) when the
# layout is the only layer or the first one.
ALONE = {
    0: (1, 0),      # Mono     C
    1: (1, 1),      # Stereo   (L/R)
    2: (4, 2),      # 5.1      (L/R) (Ls/Rs) C LFE
    3: (5, 3),      # 5.1.2    (L/R) (Ls/Rs) (Ltf/Rtf) C LFE
    4: (6, 4),      # 5.1.4    (L/R) (Ls/Rs) (Ltf/Rtf) (Ltr/Rtr) C LFE
    5: (5, 3),      # 7.1      (L/R) (Lss/Rss) (Lrs/Rrs) C LFE
    6: (6, 4),      # 7.1.2    (L/R) (Lss/Rss) (Lrs/Rrs) (Ltf/Rtf) C LFE
    7: (7, 5),      # 7.1.4    (L/R) (Lss/Rss) (Lrs/Rrs) (Ltf/Rtf) (Ltb/Rtb) C LFE
    8: (4, 2),      # 3.1.2    (L/R) (Ltf/Rtf) C LFE
    9: (1, 1),      # Binaural (L/R)
}

# (layout below, layout) -> (substream_count, coupled_substream_count) the
# layer adds. The 31 steps the Channel Layout Generation Rule permits; any
# other pair of layouts is not a step. (pairs) are coupled substreams.
ADDS = {
    (0, 1): (1, 0),     # Stereo over Mono     L2
    (0, 2): (4, 1),     # 5.1 over Mono        (L5/R5) C LFE L2
    (0, 8): (4, 1),     # 3.1.2 over Mono      (Ltf/Rtf) C LFE L2
    (0, 3): (5, 2),     # 5.1.2 over Mono      (L5/R5) (Ltf/Rtf) C LFE L2
    (0, 5): (5, 2),     # 7.1 over Mono        (L5/R5) (Lss7/Rss7) C LFE L2
    (0, 4): (6, 3),     # 5.1.4 over Mono      (L5/R5) (Ltf/Rtf) (Ltr/Rtr) C LFE L2
    (0, 6): (6, 3),     # 7.1.2 over Mono      (L5/R5) (Lss7/Rss7) (Ltf/Rtf) C LFE L2
    (0, 7): (7, 4),     # 7.1.4 over Mono      (L5/R5) (Lss7/Rss7) (Ltf/Rtf) (Ltb/Rtb) C LFE L2
    (1, 2): (3, 1),     # 5.1 over Stereo      (L5/R5) C LFE
    (1, 8): (3, 1),     # 3.1.2 over Stereo    (Ltf/Rtf) C LFE
    (1, 3): (4, 2),     # 5.1.2 over Stereo    (L5/R5) (Ltf/Rtf) C LFE
    (1, 5): (4, 2),     # 7.1 over Stereo      (L5/R5) (Lss7/Rss7) C LFE
    (1, 4): (5, 3),     # 5.1.4 over Stereo    (L5/R5) (Ltf/Rtf) (Ltr/Rtr) C LFE
    (1, 6): (5, 3),     # 7.1.2 over Stereo    (L5/R5) (Lss7/Rss7) (Ltf/Rtf) C LFE
    (1, 7): (6, 4),     # 7.1.4 over Stereo    (L5/R5) (Lss7/Rss7) (Ltf/Rtf) (Ltb/Rtb) C LFE
    (2, 3): (1, 1),     # 5.1.2 over 5.1       (Ltf/Rtf)
    (2, 5): (1, 1),     # 7.1 over 5.1         (Lss7/Rss7)
    (2, 4): (2, 2),     # 5.1.4 over 5.1       (Ltf/Rtf) (Ltr/Rtr)
    (2, 6): (2, 2),     # 7.1.2 over 5.1       (Lss7/Rss7) (Ltf/Rtf)
    (2, 7): (3, 3),     # 7.1.4 over 5.1       (Lss7/Rss7) (Ltf/Rtf) (Ltb/Rtb)
    (8, 3): (1, 1),     # 5.1.2 over 3.1.2     (L5/R5)
    (8, 4): (2, 2),     # 5.1.4 over 3.1.2     (L5/R5) (Ltf/Rtf)
    (8, 6): (2, 2),     # 7.1.2 over 3.1.2     (L5/R5) (Lss7/Rss7)
    (8, 7): (3, 3),     # 7.1.4 over 3.1.2     (L5/R5) (Lss7/Rss7) (Ltf/Rtf)
    (3, 4): (1, 1),     # 5.1.4 over 5.1.2     (Ltf/Rtf)
    (3, 6): (1, 1),     # 7.1.2 over 5.1.2     (Lss7/Rss7)
    (3, 7): (2, 2),     # 7.1.4 over 5.1.2     (Lss7/Rss7) (Ltf/Rtf)
    (5, 6): (1, 1),     # 7.1.2 over 7.1       (Ltf/Rtf)
    (5, 7): (2, 2),     # 7.1.4 over 7.1       (Ltf/Rtf) (Ltb/Rtb)
    (4, 7): (1, 1),     # 7.1.4 over 5.1.4     (Lss7/Rss7)
    (6, 7): (1, 1),     # 7.1.4 over 7.1.2     (Ltf/Rtf)
}
STEPS = list(ADDS)
NOT_A_STEP = [(a, b) for a in NAME for b in NAME if (a, b) not in ADDS]
TOPOLOGY = "substream topology does not match"
NO_STEP = "is not a step a scalable element can take"


def _chains() -> list[tuple[int, ...]]:
    """Every layer chain the rule permits, a single layer included."""
    out: list[tuple[int, ...]] = []

    def grow(chain: list[int]) -> None:
        out.append(tuple(chain))
        for below, layout in STEPS:
            if below == chain[-1]:
                grow(chain + [layout])
    for first in range(9):
        grow([first])
    return out


def counts_of(chain) -> list[tuple[int, int]]:
    """What each layer of a permitted chain declares."""
    return [ALONE[chain[0]]] + [ADDS[step] for step in zip(chain, chain[1:])]


def chain_id(chain) -> str:
    return ">".join(NAME[x] for x in chain)


CHAINS = _chains() + [(BINAURAL,)]
MONO_BASED = [c for c in CHAINS if c[0] == MONO and len(c) > 1]

# The tables above against each other and against the rule's own arithmetic.
# From any first layer but Mono the layers sum to the top layout coded alone;
# from Mono, to one substream more and one coupled substream fewer. Every
# chain codes exactly the channels of its top layout.
CHANNELS = {0: 1, 1: 2, 2: 6, 3: 8, 4: 10, 5: 8, 6: 10, 7: 12, 8: 6, 9: 2}
assert len(STEPS) == 31 and len(NOT_A_STEP) == 69
assert len(CHAINS) == 176 and max(map(len, CHAINS)) == 6
assert len([c for c in CHAINS if len(c) > 1]) == 166 and len(MONO_BASED) == 87
for _chain in CHAINS:
    _sub = sum(s for s, _c in counts_of(_chain))
    _coupled = sum(c for _s, c in counts_of(_chain))
    _alone = ALONE[_chain[-1]]
    assert (_sub, _coupled) == ((_alone[0] + 1, _alone[1] - 1) if _chain in MONO_BASED
                               else _alone), _chain
    assert _sub + _coupled == CHANNELS[_chain[-1]], _chain


def element(*layers) -> B.IAMFSpec:
    """One channel-based element whose layers are written exactly as given:
    (loudspeaker_layout, substream_count, coupled_substream_count), with the
    expanded_loudspeaker_layout as an optional fourth value."""
    n = sum(layer[1] for layer in layers)
    return B.IAMFSpec(
        elements=[B.ElementSpec(300, 0, "channel", list(range(n)),
                                layers=[B.ChannelLayerSpec(*layer) for layer in layers])],
        mixes=[B.MixSpec(42, [300], "Fixture Program",
                         [B.LayoutSpec(0, -18.0, -6.0), B.LayoutSpec(1, -20.0, -8.0)])])


def report(*layers, mp4: bool = False):
    data = B.build(element(*layers))
    r = validate_bytes(wrap_mp4(data) if mp4 else data)
    assert r.execution_error is None, r.execution_error
    assert [(x.loudspeaker_layout, x.substream_count, x.coupled_substream_count)
            for x in r.model.audio_elements[300].channel_layers] == [
                tuple(layer[:3]) for layer in layers]
    return r


def s201(r) -> list:
    return [f for f in r.findings if f.check_id == "S-201"]


def assert_silent(r) -> None:
    assert [f.to_dict() for f in r.findings if f.check_id in ("S-201", "S-202")] == []


def assert_fires(r, needle: str) -> list:
    """At least one S-201 at FAIL whose message has the needle; returns them."""
    hits = [f for f in s201(r) if needle in f.message]
    assert hits, [f.to_dict() for f in s201(r)]
    assert all(f.severity == Severity.FAIL for f in s201(r))
    assert r.exit_code() == 1
    return hits


def layers_of(chain) -> list[tuple[int, int, int]]:
    """A permitted chain as the layers it declares when every count is right."""
    return [(layout, *c) for layout, c in zip(chain, counts_of(chain))]


# ====================================================== the chains permitted
@pytest.mark.parametrize("chain", CHAINS, ids=chain_id)
def test_permitted_chain_declaring_what_its_layers_hold_silent(chain):
    assert_silent(report(*layers_of(chain)))


@pytest.mark.parametrize("mp4", [False, True], ids=["raw", "mp4"])
def test_mono_stereo_5_1_passes_clean(mp4):
    # the shape of the AOM vector: 1/0, 1/0, 3/1 — five substreams, one coupled
    r = report((0, 1, 0), (1, 1, 0), (2, 3, 1), mp4=mp4)
    assert [f.to_dict() for f in r.findings if f.severity == Severity.FAIL] == []
    assert r.passed() and r.exit_code() == 0
    assert_silent(r)


# ======================================================= one count off, fires
def _one_off(counts) -> list[tuple[int, int]]:
    """Each count one up and one down, where the result can be written."""
    sub, coupled = counts
    return [(s, c) for s, c in ((sub + 1, coupled), (sub - 1, coupled),
                                (sub, coupled + 1), (sub, coupled - 1))
            if min(s, c) >= 0]


@pytest.mark.parametrize("layout", list(ALONE), ids=lambda x: NAME[x])
def test_single_layer_one_count_off_fires(layout):
    for sub, coupled in _one_off(ALONE[layout]):
        assert_fires(report((layout, sub, coupled)),
                     f"{TOPOLOGY} declared {NAME[layout]} layout")


@pytest.mark.parametrize("step", STEPS, ids=chain_id)
def test_upper_layer_one_count_off_fires(step):
    below, layout = step
    over = f"{NAME[layout]} over {NAME[below]}"
    for sub, coupled in _one_off(ADDS[step]):
        (f,) = assert_fires(report((below, *ALONE[below]), (layout, sub, coupled)),
                            f"{TOPOLOGY} what layer 1 adds")
        assert f.message == (f"{TOPOLOGY} what layer 1 adds ({over}) — "
                             "an F4-class silent-corruption signature")
        assert f.expected == (f"{ADDS[step][0]} substreams ({ADDS[step][1]} coupled) "
                              f"for {over}")
        assert f.found == f"{sub} substreams ({coupled} coupled)"


@pytest.mark.parametrize("step", STEPS, ids=chain_id)
def test_counts_moved_between_two_layers_fires(step):
    # the element's totals are right; one substream sits in the wrong layer
    below, layout = step
    (sub, coupled), (low_sub, low_coupled) = ADDS[step], ALONE[below]
    pair = 1 if coupled else 0           # move a coupled substream when there is one
    r = report((below, low_sub + 1, low_coupled + pair),
               (layout, sub - 1, coupled - pair))
    assert_fires(r, f"{TOPOLOGY} declared {NAME[below]} layout")
    assert_fires(r, f"{TOPOLOGY} what layer 1 adds")


@pytest.mark.parametrize("top", [2, 3, 4, 5, 6, 7, 8], ids=lambda x: NAME[x])
def test_mono_based_chain_declaring_its_top_layout_coded_alone_fires(top):
    # the counts S-201 used to ask of a Mono-based chain: summed, those of the
    # top layout as a single layer. Stereo is left out: its remainder over
    # Mono would be 0 substreams, 1 coupled, which the coupled <= substream
    # rule already rejects.
    sub, coupled = ALONE[top][0] - 1, ALONE[top][1]
    (f,) = assert_fires(report((0, 1, 0), (top, sub, coupled)),
                        f"{TOPOLOGY} what layer 1 adds")
    want = ADDS[(0, top)]
    assert f.expected == f"{want[0]} substreams ({want[1]} coupled) for {NAME[top]} over Mono"


def test_mono_stereo_5_1_with_a_wrong_coupled_count_fires():
    r = report((0, 1, 0), (1, 1, 0), (2, 3, 2))
    (f,) = assert_fires(r, TOPOLOGY)
    assert f.message == (f"{TOPOLOGY} what layer 2 adds (5.1 over Stereo) — "
                         "an F4-class silent-corruption signature")
    assert (f.expected, f.found) == ("3 substreams (1 coupled) for 5.1 over Stereo",
                                     "3 substreams (2 coupled)")


def test_stereo_based_5_1_with_five_substreams_fires():
    r = report((1, 1, 1), (2, 4, 1))
    (f,) = assert_fires(r, TOPOLOGY)
    assert (f.expected, f.found) == ("3 substreams (1 coupled) for 5.1 over Stereo",
                                     "4 substreams (1 coupled)")


def test_a_layer_is_counted_against_the_layer_directly_below_fires():
    # 5.1 over Mono adds 4 substreams, but here Stereo lies between them
    r = report((0, 1, 0), (1, 1, 0), (2, 4, 1))
    (f,) = assert_fires(r, TOPOLOGY)
    assert (f.expected, f.found) == ("3 substreams (1 coupled) for 5.1 over Stereo",
                                     "4 substreams (1 coupled)")


# ============================================== layouts that cannot be layered
@pytest.mark.parametrize("pair", NOT_A_STEP, ids=chain_id)
def test_layout_that_cannot_follow_the_layer_below_fires(pair):
    below, layout = pair
    # where it can be written, the upper layer declares the remainder up to
    # its layout coded alone: counts whose sum S-201 used to accept
    sub = ALONE[layout][0] - ALONE[below][0]
    coupled = ALONE[layout][1] - ALONE[below][1]
    if not 0 <= coupled <= sub:
        sub, coupled = ALONE[layout]
    (f,) = assert_fires(report((below, *ALONE[below]), (layout, sub, coupled)), NO_STEP)
    assert f.message == (f"layer 1: {NAME[layout]} over {NAME[below]} {NO_STEP} — "
                         "no Channel Group is defined for it")
    assert f.found == f"{NAME[layout]} over {NAME[below]}"


def test_layer_above_an_expanded_layout_fires():
    # Stereo-S (expanded layout 1) then 5.1: an expanded layout is one layer
    (f,) = assert_fires(report((EXPANDED, 1, 1, 1), (2, 3, 1)), NO_STEP)
    assert f.found == "5.1 over Expanded"


def test_lfe_count_alone_may_not_decrease(monkeypatch):
    # Among the nine layouts the LFE count never drops unless the surround
    # count drops with it, so no stream can show the rule's Y comparison at
    # work. A made-up 5.0.0 layout does: 5.1 cannot be followed by it, and it
    # can be followed by 5.1, which then adds the LFE alone.
    from sentinel import layouts
    monkeypatch.setitem(layouts.LAYOUT_XYZ, 99, (5, 0, 0))
    assert layouts.channel_group_counts(2, 99) is None
    assert layouts.channel_group_counts(99, 2) == (1, 0)


# ===================================================== what did not change
def test_single_layer_finding_reads_as_before():
    r = report((7, 7, 4))
    assert [(f.message, f.expected, f.found) for f in s201(r)] == [
        ("substream topology does not match declared 7.1.4 layout — "
         "an F4-class silent-corruption signature",
         "7 substreams (5 coupled) for 7.1.4", "7 substreams (4 coupled)"),
        ("channel count implied by substreams (11) != 7.1.4 channel count (12)",
         "12 channels", "11"),
    ]
