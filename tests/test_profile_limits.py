"""Profile limits (S-109), profile recognition (S-102), and the pack keys that
select a platform's accepted profiles.

Every limit is exercised as a pair synthesised by fixtures/: a file that sits
on the limit and says nothing, and a file one step past it that fires. Test
names say which is which — ``_silent`` expects no S-109, ``_fires`` expects
one — because a test that has only ever passed proves nothing: run against a
tree without the rule, every ``_fires`` test has to fail.

The expected limits are written out here, not read from the module under test,
so a changed cap in the code cannot move the expectation with it. Citations
(``v2:`` IAMF v2.0.0, ``v1.1:`` v1.1.0, ``err:`` v1.0.0-errata, by source line)
are beside each cap in sentinel/checks/l1_profile.py.

All bytes are synthesised by fixtures/ — no reference vectors are involved.
"""

from __future__ import annotations

import json

import pytest

from fixtures import build as B
from sentinel.engine import validate_bytes
from sentinel.findings import Severity
from sentinel.parser import parse_bytes

NAME = {0: "Simple", 1: "Base", 2: "Base-Enhanced", 3: "Base-Advanced",
        4: "Advanced-1", 5: "Advanced-2"}
ELEMENT_CAP = {0: 1, 1: 2, 2: 28, 3: 18, 4: 18, 5: 28}
CHANNEL_CAP = {0: 16, 1: 18, 2: 28, 3: 18, 4: 18, 5: 28}
SUB_MIX_CAP = {0: 1, 1: 1, 2: 1, 3: 2, 4: 2, 5: 2}
LAYOUTS = [B.LayoutSpec(0, -18.0, -6.0, -5.0)]


class Seq:
    """Assembles one IA Sequence element by element, handing out element and
    substream ids; each adder returns the audio_element_id."""

    def __init__(self, primary: int, additional: int | None = None) -> None:
        self.spec = B.IAMFSpec(
            primary_profile=primary,
            additional_profile=primary if additional is None else additional)
        self._next_substream = 0

    def _add(self, kind: str, n_substreams: int, **kw) -> int:
        eid = 300 + len(self.spec.elements)
        ids = list(range(self._next_substream, self._next_substream + n_substreams))
        self._next_substream += n_substreams
        self.spec.elements.append(B.ElementSpec(eid, 0, kind, ids, **kw))
        return eid

    # -- channel-based ------------------------------------------------------
    def channel(self, layout: int, substreams: int, coupled: int,
                expanded: int | None = None) -> int:
        return self._add("channel", substreams, layers=[
            B.ChannelLayerSpec(layout, substreams, coupled, expanded)])

    def mono(self) -> int: return self.channel(0, 1, 0)                  # 1 ch
    def stereo(self) -> int: return self.channel(1, 1, 1)                # 2 ch
    def surround_7_1_4(self) -> int: return self.channel(7, 7, 5)        # 12 ch
    def top_4(self) -> int: return self.channel(15, 2, 2, 6)             # 4 ch
    def top_6(self) -> int: return self.channel(15, 3, 3, 12)            # 6 ch
    def layout_10_2_9_3(self) -> int: return self.channel(15, 16, 8, 13)   # 24 ch
    def layout_7_1_5_4(self) -> int: return self.channel(15, 10, 7, 16)    # 17 ch
    def reserved_layout(self) -> int: return self.channel(12, 1, 0)      # unknown

    def scalable(self) -> int:
        """Two layers, Stereo then 5.1: 6 channels by its highest layer."""
        return self._add("channel", 4, layers=[B.ChannelLayerSpec(1, 1, 1),
                                               B.ChannelLayerSpec(2, 3, 1)])

    # -- scene-based --------------------------------------------------------
    def ambisonics(self, order: int, coded: int | None = None) -> int:
        """Full order by default. ``coded`` substreams make the coded channel
        count differ from output_channel_count ((order + 1)^2)."""
        occ = (order + 1) ** 2
        if coded is None:
            return self._add("scene", occ, ambi_order=order)
        mapping = [i if i < coded else 255 for i in range(occ)]
        return self._add("scene", coded, ambi_order=order,
                         ambi_substream_count=coded, ambi_mapping=mapping)

    def toa(self) -> int: return self.ambisonics(3)                      # 16 ch

    def scene_17(self) -> int:
        """17 output channels, 17 substreams: not an ambisonics order (S-203
        says so), but a channel count one past Simple's 16 in one element."""
        return self._add("scene", 17, ambi_order=3, ambi_occ_override=17,
                         ambi_substream_count=17, ambi_mapping=list(range(17)))

    # -- object-based -------------------------------------------------------
    def obj(self, num_objects: int = 1, **kw) -> int:
        return self._add("object", 1, num_objects=num_objects, **kw)

    def unparsed_objects(self) -> int:
        """Type 2 with a zero-size config, as a pre-v2.0.0 stream may carry."""
        return self._add("object", 1, raw_config=b"\x00")

    def reserved_type(self) -> int:
        return self._add("object", 1, audio_element_type=3, raw_config=b"\x00")

    def unknown(self, kind: str) -> int:
        """An element whose channel count cannot be read."""
        if kind == "dangling":
            return 999                       # referenced, never declared
        return getattr(self, kind)()

    # -- mixes --------------------------------------------------------------
    def mix(self, *sub_mixes: list[int]) -> "Seq":
        self.spec.mixes.append(B.MixSpec(
            42 + len(self.spec.mixes), list(sub_mixes[0]), "Programme", LAYOUTS,
            extra_sub_mixes=[list(s) for s in sub_mixes[1:]]))
        return self

    def report(self, profile: str = "generic"):
        report = validate_bytes(B.build(self.spec), profile=profile)
        assert report.execution_error is None, report.execution_error
        return report


UNKNOWN_KINDS = ["reserved_layout", "unparsed_objects", "reserved_type", "dangling"]


def s109(report, severity: Severity | None = None) -> list[str]:
    return [f.message for f in report.findings if f.check_id == "S-109"
            and (severity is None or f.severity == severity)]


def assert_silent(report) -> None:
    assert s109(report) == []


def s108(report) -> list[str]:
    """One marker per S-108 finding: which kind of parse problem it reports."""
    kinds = ("not an ObjectsConfig", "reserved header bit 6")
    return [next((k for k in kinds if k in f.message), f.message)
            for f in report.findings if f.check_id == "S-108"]


def fired(report, severity: Severity, *needles: str) -> list[str]:
    """S-109 messages of that severity containing every needle."""
    return [msg for msg in s109(report, severity) if all(n in msg for n in needles)]


def assert_only(report, severity: Severity, *needles: str) -> str:
    """Exactly one S-109 in the whole report: that severity, those words."""
    assert len(s109(report)) == 1, s109(report)
    assert len(fired(report, severity, *needles)) == 1, s109(report)
    return s109(report)[0]


# ============================================================ S-102 / naming
@pytest.mark.parametrize("profile", range(6))
def test_defined_profiles_carry_no_s102_silent(profile):
    q = Seq(profile)
    report = q.mix([q.stereo()]).report()
    assert [f for f in report.findings if f.check_id == "S-102"] == []
    assert_silent(report)


DEFINED_RANGE = ("defined profiles are 0-5: Simple, Base, Base-Enhanced, "
                 "Base-Advanced, Advanced-1, Advanced-2")


def s102(report) -> list:
    return [f for f in report.findings if f.check_id == "S-102"]


def _stereo_sequence(primary: int, additional: int, pack: str = "generic"):
    q = Seq(primary, additional)
    q.mix([q.stereo()])
    report = validate_bytes(B.build(q.spec), profile=pack)
    assert report.execution_error is None
    return report


@pytest.mark.parametrize("value", range(6))
def test_defined_primary_profile_silent(value):
    assert s102(_stereo_sequence(value, 1)) == []


@pytest.mark.parametrize("value", [6, 255])
def test_reserved_primary_profile_is_a_fail_fires(value):
    report = _stereo_sequence(value, 1)
    (f,) = s102(report)
    assert f.severity == Severity.FAIL
    assert f.message.startswith(f"primary_profile {value} is reserved ({DEFINED_RANGE}). ")
    assert "told to discard" in f.message and "0/1/2" not in f.message
    assert report.exit_code() == 1


@pytest.mark.parametrize("value", range(6))
def test_defined_additional_profile_silent(value):
    assert s102(_stereo_sequence(1, value)) == []


@pytest.mark.parametrize("value", [6, 255])
def test_reserved_additional_profile_alone_is_an_info_fires(value):
    report = _stereo_sequence(1, value)
    (f,) = s102(report)
    assert f.severity == Severity.INFO
    assert f.message.startswith(f"additional_profile {value} is reserved ({DEFINED_RANGE}). ")
    assert "does not forbid" in f.message
    assert [x.check_id for x in report.findings] == ["S-102"]
    assert report.exit_code() == 0 and report.exit_code(Severity.WARN) == 0


def test_both_profiles_reserved_is_one_fail_and_one_info_fires():
    report = _stereo_sequence(7, 200)
    assert [(f.severity, f.message.split(" is ")[0]) for f in s102(report)] == [
        (Severity.FAIL, "primary_profile 7"), (Severity.INFO, "additional_profile 200")]
    assert report.exit_code() == 1


def test_s102_registry_severity_is_the_primary_case():
    from sentinel.findings import REGISTRY
    assert REGISTRY["S-102"].default_severity == Severity.FAIL


@pytest.mark.parametrize("override,primary_exit", [("WARN", 0), ("INFO", 0), ("FAIL", 1)])
def test_pack_moves_the_reserved_primary_case_only(tmp_path, monkeypatch,
                                                   override, primary_exit):
    _packs(tmp_path, monkeypatch, tuned=f'[severity]\nS-102 = "{override}"')
    for value in (6, 255):
        report = _stereo_sequence(value, 1, pack="tuned")
        assert [f.severity.label for f in s102(report)] == [override]
        assert report.exit_code() == primary_exit
        report = _stereo_sequence(1, value, pack="tuned")
        assert [f.severity for f in s102(report)] == [Severity.INFO]
        assert report.exit_code() == 0
    assert s102(_stereo_sequence(5, 5, pack="tuned")) == []


def test_reserved_primary_profile_keeps_s109_silent():
    # Over every limit of every profile: S-102 has already spoken.
    q = Seq(7)
    ids = [q.mono() for _ in range(30)]
    spec_report = q.mix(ids, ids, ids).report()
    assert_silent(spec_report)
    assert any(f.check_id == "S-102" for f in spec_report.findings)


def test_shipped_fixtures_stay_clear_of_s102_and_s109_silent():
    for name, spec in B.all_valid_specs().items():
        report = validate_bytes(B.build(spec))
        assert [f.check_id for f in report.findings
                if f.check_id in ("S-102", "S-109")] == [], name


# ================================================= per-mix: audio elements
@pytest.mark.parametrize("profile", range(6))
def test_element_count_at_limit_silent(profile):
    q = Seq(profile)
    assert_silent(q.mix([q.mono() for _ in range(ELEMENT_CAP[profile])]).report())


@pytest.mark.parametrize("profile", range(6))
def test_element_count_over_limit_fires(profile):
    cap = ELEMENT_CAP[profile]
    q = Seq(profile)
    report = q.mix([q.mono() for _ in range(cap + 1)]).report()
    assert len(fired(report, Severity.FAIL,
                     f"no Mix Presentation fits primary_profile {NAME[profile]} ({profile})",
                     "mix_presentation 42",
                     f"{cap + 1} audio elements (limit {cap})")) == 1, s109(report)


# ====================================================== per-mix: channels
def _channels(q: Seq, profile: int, over: bool) -> list[int]:
    """Elements summing to the profile's channel limit, or to one more."""
    if profile == 0:                     # one element only
        return [q.scene_17()] if over else [q.toa()]                      # 17 / 16
    if profile == 1:                     # two elements only
        return ([q.scene_17(), q.stereo()] if over                        # 19
                else [q.toa(), q.stereo()])                               # 18
    ids = [q.toa(), q.surround_7_1_4() if CHANNEL_CAP[profile] == 28 else q.stereo()]
    return ids + [q.mono()] if over else ids


@pytest.mark.parametrize("profile", range(6))
def test_channel_count_at_limit_silent(profile):
    q = Seq(profile)
    assert_silent(q.mix(_channels(q, profile, over=False)).report())


@pytest.mark.parametrize("profile", range(6))
def test_channel_count_over_limit_fires(profile):
    cap = CHANNEL_CAP[profile]
    q = Seq(profile)
    report = q.mix(_channels(q, profile, over=True)).report()
    assert len(fired(report, Severity.FAIL, "no Mix Presentation fits",
                     f"{cap + 1} channels before mixing (limit {cap})")) == 1, s109(report)


def test_expanded_layouts_10_2_9_3_and_top_4_count_28_silent():
    q = Seq(5)
    assert_silent(q.mix([q.layout_10_2_9_3(), q.top_4()]).report())      # 24 + 4


def test_expanded_layouts_one_channel_past_28_fires():
    q = Seq(5)
    report = q.mix([q.layout_10_2_9_3(), q.top_4(), q.mono()]).report()
    assert fired(report, Severity.FAIL, "29 channels before mixing (limit 28)")


def test_dual_objects_count_two_channels_each_at_limit_silent():
    q = Seq(3)
    assert_silent(q.mix([q.obj(2) for _ in range(9)]).report())          # 18


def test_dual_objects_count_two_channels_each_over_limit_fires():
    q = Seq(3)
    report = q.mix([q.obj(2) for _ in range(10)]).report()               # 20
    assert fired(report, Severity.FAIL, "no Mix Presentation fits",
                 "20 channels before mixing (limit 18)")


def test_scalable_element_at_limit_silent():
    q = Seq(1)
    assert_silent(q.mix([q.scalable(), q.surround_7_1_4()]).report())    # 6 + 12


def test_scalable_element_counts_its_highest_layer_fires():
    q = Seq(1)                           # 16 + 6; by the first layer it would be 18
    report = q.mix([q.toa(), q.scalable()]).report()
    assert_only(report, Severity.FAIL, "22 channels before mixing (limit 18)")


# ===================================================== per-mix: sub-mixes
@pytest.mark.parametrize("profile", range(6))
def test_sub_mix_count_at_limit_silent(profile):
    q = Seq(profile)
    a = q.stereo()
    subs = [[a]] if SUB_MIX_CAP[profile] == 1 else [[a], [q.mono()]]
    assert_silent(q.mix(*subs).report())


@pytest.mark.parametrize("profile", range(6))
def test_sub_mix_count_over_limit_fires(profile):
    cap = SUB_MIX_CAP[profile]
    q = Seq(profile)
    report = q.mix(*[[q.mono()] for _ in range(cap + 1)]).report()
    assert len(fired(report, Severity.FAIL, "no Mix Presentation fits",
                     f"{cap + 1} sub-mixes (limit {cap})")) == 1, s109(report)


# ================================================= per-mix: element types
@pytest.mark.parametrize("profile", [3, 4, 5])
def test_object_element_under_object_profiles_silent(profile):
    q = Seq(profile)
    assert_silent(q.mix([q.obj()]).report())


@pytest.mark.parametrize("profile", [0, 1, 2])
def test_object_element_in_the_only_mix_fires(profile):
    q = Seq(profile)
    report = q.mix([q.obj()]).report()
    assert_only(report, Severity.FAIL, "no Mix Presentation fits",
                "object-based audio_element(s) [300]",
                f"the {NAME[profile]} profile defines channel-based and scene-based")


def test_base_one_scene_element_silent():
    q = Seq(1)
    assert_silent(q.mix([q.ambisonics(1), q.stereo()]).report())


def test_base_two_scene_elements_fires():
    q = Seq(1)
    report = q.mix([q.ambisonics(1), q.ambisonics(1)]).report()
    assert_only(report, Severity.FAIL, "2 scene-based elements (limit 1)")


def test_base_one_scalable_element_silent():
    q = Seq(1)
    assert_silent(q.mix([q.scalable(), q.stereo()]).report())
    q = Seq(1)
    assert_silent(q.mix([q.scalable(), q.ambisonics(1)]).report())


def test_base_two_scalable_elements_fires():
    q = Seq(1)
    report = q.mix([q.scalable(), q.scalable()]).report()
    assert_only(report, Severity.FAIL, "2 scalable channel-based elements (limit 1)")


def test_base_combination_rules_do_not_bind_base_enhanced_silent():
    q = Seq(2)
    assert_silent(q.mix([q.ambisonics(1), q.ambisonics(1), q.scalable(),
                         q.scalable()]).report())


# ============================== scene-based: declared against coded channels
def test_mixed_order_within_limit_under_both_counts_silent():
    q = Seq(1)
    assert_silent(q.mix([q.ambisonics(3, coded=4), q.stereo()]).report())   # 18 / 6


def test_mixed_order_over_by_declared_only_is_one_info_fires():
    q = Seq(1)
    report = q.mix([q.ambisonics(4, coded=4), q.stereo()]).report()          # 27 / 6
    msg = assert_only(report, Severity.INFO, "mix_presentation 42",
                      "Base profile (1) limit of 18 channels",
                      "over when scene-based elements are counted by "
                      "output_channel_count (27)",
                      "coded channels, substreams + coupled (6)",
                      "does not say which count")
    assert "not treated as over" in msg


def test_scene_over_by_coded_only_is_one_info_fires():
    # More substreams than output channels: over by the coded count alone.
    q = Seq(1)
    eid = q._add("scene", 25, ambi_order=1, ambi_substream_count=25,
                 ambi_mapping=[0, 1, 2, 3])
    report = q.mix([eid, q.stereo()]).report()                               # 6 / 27
    assert_only(report, Severity.INFO,
                "over when scene-based elements are counted by coded channels, "
                "substreams + coupled (27)", "output_channel_count (6)")


def test_scene_over_under_both_counts_fires():
    q = Seq(1)
    report = q.mix([q.ambisonics(4), q.stereo()]).report()                   # 27 / 27
    assert_only(report, Severity.FAIL, "27 channels before mixing (limit 18)")


def test_open_count_against_additional_profile_fires():
    # The second mix is outside Simple; whether it is inside Base is the open point.
    q = Seq(0, 1)
    a = q.stereo()
    report = q.mix([a]).mix([q.ambisonics(4, coded=4), a]).report()
    assert_only(report, Severity.INFO, "mix_presentation 43", "Base profile (1)")


def test_open_count_beside_an_unknown_element_silent():
    # Unknown stays unknown: no INFO claims the rest of the mix is readable.
    q = Seq(1)
    assert_silent(q.mix([q.ambisonics(4, coded=4), q.reserved_layout()]).report())


def test_open_sequence_total_is_an_info_fires():
    q = Seq(5)
    report = q.mix([q.ambisonics(5, coded=4)]).report()                      # 36 / 4
    assert len(s109(report)) == 2 and len(s109(report, Severity.INFO)) == 2
    assert len(fired(report, Severity.INFO, "in total across the Audio Elements",
                     "output_channel_count (36)", "(4)")) == 1


def test_open_sequence_total_beside_an_unknown_element_keeps_only_the_mix_note():
    # Same sequence plus an element that cannot be counted: the per-mix note
    # stands, and nothing is said about a total that is no longer readable.
    q = Seq(5)
    q.mix([q.ambisonics(5, coded=4)])
    q.reserved_layout()
    report = q.report()
    assert_only(report, Severity.INFO, "mix_presentation 42")
    assert fired(report, Severity.INFO, "in total") == []


# =========================================== unknown counts and lower bounds
@pytest.mark.parametrize("kind", UNKNOWN_KINDS)
def test_unknown_element_beside_known_within_limit_silent(kind):
    q = Seq(4)
    ids = [q.toa(), q.stereo(), q.unknown(kind)]                 # 18 known
    report = q.mix(ids).report()
    assert_silent(report)
    # Under a profile that defines objects the unreadable config is itself a
    # parse error; S-109 still does not guess a count for it.
    assert s108(report) == (["not an ObjectsConfig"] if kind == "unparsed_objects" else [])


@pytest.mark.parametrize("kind", UNKNOWN_KINDS)
def test_unknown_element_beside_known_over_limit_fires(kind):
    q = Seq(4)
    ids = [q.toa(), q.stereo(), q.mono(), q.unknown(kind)]       # 19 known
    report = q.mix(ids).report()
    assert len(fired(report, Severity.FAIL, "no Mix Presentation fits",
                     "at least 19 channels before mixing (limit 18)")) == 1, s109(report)


def test_object_count_zero_is_unknown_silent():
    # num_objects 0 is not a count. Were it read as "no channels", the mix
    # would be fully known and its open scene count would earn an INFO.
    q = Seq(4, 1)                        # additional 1: no sequence-wide total
    assert_silent(q.mix([q.ambisonics(4, coded=4), q.obj(0)]).report())


# ====================================================== sequence-wide total
SEQUENCE_TOTALS = [(3, 3, 18), (4, 4, 18), (3, 4, 18), (5, 3, 18), (5, 5, 28),
                   (2, 2, 28), (0, 2, 28)]


def _single_element_mixes(q: Seq, cap: int, extra: int) -> Seq:
    """Each element in a Mix Presentation of its own, so every mix fits every
    profile and only the total across the sequence can be over."""
    ids = [q.toa(), q.surround_7_1_4() if cap == 28 else q.stereo()]
    ids += [q.mono() for _ in range(extra)]
    for eid in ids:
        q.mix([eid])
    return q


@pytest.mark.parametrize("primary,additional,cap", SEQUENCE_TOTALS)
def test_sequence_total_at_limit_silent(primary, additional, cap):
    assert_silent(_single_element_mixes(Seq(primary, additional), cap, 0).report())


@pytest.mark.parametrize("primary,additional,cap", SEQUENCE_TOTALS)
def test_sequence_total_over_limit_fires(primary, additional, cap):
    report = _single_element_mixes(Seq(primary, additional), cap, 1).report()
    assert_only(report, Severity.FAIL, f"{cap + 1} channels in total",
                f"additional_profile {NAME[additional]} ({additional})",
                f"limited to {cap}")


@pytest.mark.parametrize("primary,additional", [(5, 2), (3, 2), (1, 1), (0, 0), (2, 1)])
def test_sequence_total_where_no_sentence_sets_one_silent(primary, additional):
    # additional_profile 2 binds only primary_profile <= 2; 0 and 1 have no total.
    assert_silent(_single_element_mixes(Seq(primary, additional), 28, 3).report())


def test_sequence_total_leaves_objects_out_under_base_enhanced_silent():
    q = _single_element_mixes(Seq(2), 28, 0)
    q.obj()                              # declared, in no mix: not recognisable
    assert_silent(q.report())


def test_sequence_total_counts_objects_under_advanced_2_fires():
    q = _single_element_mixes(Seq(5), 28, 0)
    q.mix([q.obj()])
    assert_only(q.report(), Severity.FAIL, "29 channels in total")


def test_sequence_total_leaves_reserved_types_out_silent():
    q = _single_element_mixes(Seq(3), 18, 0)
    q.reserved_type()
    assert_silent(q.report())


def test_sequence_total_beside_a_reserved_type_is_exact_fires():
    # Not recognisable, so left out of the total: the 19 is the whole count,
    # not a lower bound.
    q = _single_element_mixes(Seq(3), 18, 1)
    q.reserved_type()
    msg = assert_only(q.report(), Severity.FAIL, "19 channels in total")
    assert "at least" not in msg


def test_sequence_total_v2_layout_under_base_enhanced_is_not_counted():
    # Expanded layout 13 (10.2.9.3ch) is the first value v1.1.0 reserves:
    # whether a Base-Enhanced parser recognises it is unsettled, so it is not
    # counted against 28.
    q = _single_element_mixes(Seq(2), 28, 0)
    q.mix([q.layout_10_2_9_3()])
    report = q.report()
    assert s109(report, Severity.FAIL) == [] and s109(report, Severity.WARN) == []
    assert_only(report, Severity.INFO, "mix_presentation 44", "reserved in IAMF v1.1.0")


def test_sequence_total_v2_layout_under_advanced_2_fires():
    q = _single_element_mixes(Seq(5), 28, 0)
    q.mix([q.layout_10_2_9_3()])
    assert_only(q.report(), Severity.FAIL, "52 channels in total")


def test_sequence_total_v1_1_layout_under_base_enhanced_fires():
    q = _single_element_mixes(Seq(2), 28, 0)
    q.mix([q.top_6()])                   # expanded layout 12: defined in v1.1.0
    assert_only(q.report(), Severity.FAIL, "34 channels in total")


@pytest.mark.parametrize("kind", ["reserved_layout", "unparsed_objects"])
def test_sequence_total_known_part_within_limit_silent(kind):
    q = _single_element_mixes(Seq(3), 18, 0)
    q.unknown(kind)
    assert_silent(q.report())


@pytest.mark.parametrize("kind", ["reserved_layout", "unparsed_objects"])
def test_sequence_total_known_part_over_limit_fires(kind):
    q = _single_element_mixes(Seq(3), 18, 1)
    q.unknown(kind)
    assert_only(q.report(), Severity.FAIL, "at least 19 channels in total",
                "limited to 18")


def test_sequence_total_known_part_over_limit_base_enhanced_fires():
    q = _single_element_mixes(Seq(2), 28, 1)
    q.mix([q.layout_10_2_9_3()])         # unsettled, left out; the rest is 29
    report = q.report()
    assert s109(report, Severity.FAIL) == fired(report, Severity.FAIL,
                                               "at least 29 channels in total")
    assert len(s109(report, Severity.FAIL)) == 1


# ========================================== Mix Presentations and profiles
def test_mix_inside_additional_profile_only_silent():
    q = Seq(0, 1)
    a = q.stereo()
    assert_silent(q.mix([a]).mix([a, q.mono()]).report())


def test_mix_outside_both_profiles_fires():
    q = Seq(0, 1)
    a = q.stereo()
    report = q.mix([a]).mix([a, q.mono(), q.mono()]).report()
    msg = assert_only(report, Severity.WARN, "mix_presentation 43",
                      "outside both declared profiles",
                      "primary_profile Simple (0): 3 audio elements (limit 1)",
                      "additional_profile Base (1): 3 audio elements (limit 2)")
    assert "mix_presentation 42" not in msg
    assert report.exit_code() == 0 and report.exit_code(Severity.WARN) == 1


def test_mix_outside_the_only_declared_profile_fires():
    q = Seq(0)
    a = q.stereo()
    report = q.mix([a]).mix([a, q.mono()]).report()
    assert_only(report, Severity.WARN, "mix_presentation 43",
                "outside the Simple profile (0), the only profile",
                "2 audio elements (limit 1)")


def test_mix_outside_primary_with_reserved_additional_fires():
    q = Seq(2, 255)
    a = q.stereo()
    report = q.mix([a]).mix([q.mono() for _ in range(29)]).report()
    assert_only(report, Severity.WARN, "mix_presentation 43",
                "outside primary_profile Base-Enhanced (2)",
                "29 audio elements (limit 28)",
                "additional_profile 255 is reserved")


def test_no_mix_fits_is_one_fail_naming_the_nearest_fires():
    q = Seq(0, 1)
    a, b, c = q.stereo(), q.mono(), q.mono()
    report = q.mix([a, b], [c]).mix([a, b]).report()
    assert_only(report, Severity.FAIL, "no Mix Presentation fits primary_profile "
                "Simple (0)", "nearest is mix_presentation 43",
                "2 audio elements (limit 1)")


def test_pack_severity_moves_the_warn_class_only(tmp_path, monkeypatch):
    _packs(tmp_path, monkeypatch, strict='[severity]\nS-109 = "FAIL"')
    q = Seq(0)
    a = q.stereo()
    report = q.mix([a]).mix([a, q.mono()]).report(profile="strict")
    assert len(s109(report, Severity.FAIL)) == 1 and len(s109(report)) == 1
    q = Seq(1)
    report = q.mix([q.ambisonics(4, coded=4), q.stereo()]).report(profile="strict")
    assert len(s109(report, Severity.INFO)) == 1 and len(s109(report)) == 1


# ============================================ a sub-mix with no elements
def test_sub_mix_with_an_element_silent():
    q = Seq(3)
    assert_silent(q.mix([q.stereo()], [q.mono()]).report())


def test_only_mix_has_a_sub_mix_with_no_elements_fires():
    q = Seq(3)
    report = q.mix([q.stereo()], []).report()
    assert_only(report, Severity.FAIL, "no Mix Presentation fits",
                "sub-mix 2 has num_audio_elements = 0, which no profile admits")


@pytest.mark.parametrize("profile", range(6))
def test_mix_of_one_empty_sub_mix_beside_a_fitting_mix_fires(profile):
    # Zero elements, zero channels: it must not pass as the mix that fits.
    q = Seq(profile)
    report = q.mix([q.stereo()]).mix([]).report()
    assert_only(report, Severity.WARN, "mix_presentation 43",
                "sub-mix 1 has num_audio_elements = 0")


def test_mix_of_one_empty_sub_mix_is_not_the_mix_that_fits_fires():
    q = Seq(0)
    a = q.stereo()
    report = q.mix([]).mix([a, q.mono()]).report()
    assert_only(report, Severity.FAIL, "no Mix Presentation fits primary_profile "
                "Simple (0)")


# =============================================== a mix with no sub-mixes
def _with_empty_mix(q: Seq, mix_id: int, first: bool = False) -> bytes:
    """The sequence plus a Mix Presentation whose num_sub_mixes is 0 (hand-framed:
    the builder always writes at least one sub-mix)."""
    empty = B.obu(2, B.Writer().leb128(mix_id).leb128(1).cstring("en-us")
                  .cstring("Programme").leb128(0).bytes())
    spec = q.spec.copy()
    frames = B._audio_frames(spec)
    spec.temporal_units = 0
    spec.mixes = []
    head = B.build(spec)
    mixes = b"".join(B._mix_presentation(mx) for mx in q.spec.mixes)
    return head + (empty + mixes if first else mixes + empty) + frames


@pytest.mark.parametrize("profile", range(6))
def test_mix_with_one_sub_mix_beside_another_silent(profile):
    q = Seq(profile)
    a = q.stereo()
    assert_silent(q.mix([a]).mix([a]).report())


@pytest.mark.parametrize("profile", range(6))
def test_mix_with_no_sub_mixes_beside_a_fitting_mix_fires(profile):
    q = Seq(profile)
    q.mix([q.stereo()])
    report = validate_bytes(_with_empty_mix(q, 43))
    assert report.execution_error is None and report.model.parse_errors == []
    assert [len(mp.sub_mixes) for mp in report.model.mix_presentations] == [1, 0]
    assert_only(report, Severity.WARN, "mix_presentation 43",
                "num_sub_mixes = 0, which no profile admits")


def test_only_mix_has_no_sub_mixes_fires():
    q = Seq(3)
    q.stereo()
    report = validate_bytes(_with_empty_mix(q, 42))
    assert_only(report, Severity.FAIL, "no Mix Presentation fits primary_profile "
                "Base-Advanced (3)", "mix_presentation 42: num_sub_mixes = 0")


def test_mix_with_no_sub_mixes_is_not_the_mix_that_fits_fires():
    q = Seq(0)
    a = q.stereo()
    q.mix([a, q.mono()])
    report = validate_bytes(_with_empty_mix(q, 41, first=True))
    assert_only(report, Severity.FAIL, "no Mix Presentation fits primary_profile "
                "Simple (0)")


# ============================= expanded layouts 13..19 under profiles 0..2
@pytest.mark.parametrize("profile,version", [(0, "IAMF v1.0.0-errata"),
                                             (1, "IAMF v1.0.0-errata"),
                                             (2, "IAMF v1.1.0")])
def test_v2_layout_under_an_older_profile_is_one_info_fires(profile, version):
    q = Seq(profile)
    eid = q.layout_10_2_9_3()
    report = q.mix([eid]).report()
    assert_only(report, Severity.INFO, "mix_presentation 42",
                f"audio_element(s) [{eid}]", f"reserved in {version}",
                f"the {NAME[profile]} profile ({profile})", "does not say whether")
    assert not any(f.check_id == "S-109" and f.severity > Severity.INFO
                   for f in report.findings)


def test_v2_layout_under_advanced_2_silent():
    q = Seq(5)
    assert_silent(q.mix([q.layout_10_2_9_3()]).report())                 # 24 of 28


@pytest.mark.parametrize("profile", [3, 4])
def test_v2_layout_counts_normally_under_v2_profiles_fires(profile):
    q = Seq(profile)
    report = q.mix([q.layout_10_2_9_3()]).report()
    assert fired(report, Severity.FAIL, "no Mix Presentation fits",
                 "24 channels before mixing (limit 18)")
    assert s109(report, Severity.INFO) == []


def test_v1_1_layout_counts_normally_under_base_enhanced_fires():
    q = Seq(2)                           # Top-6ch is expanded layout 12
    report = q.mix([q.toa(), q.surround_7_1_4(), q.top_6()]).report()
    assert fired(report, Severity.FAIL, "no Mix Presentation fits",
                 "34 channels before mixing (limit 28)")
    assert s109(report, Severity.INFO) == []


def test_v2_layout_beside_known_elements_within_limit_is_only_the_info():
    q = Seq(2)
    report = q.mix([q.toa(), q.surround_7_1_4(), q.layout_10_2_9_3()]).report()
    assert_only(report, Severity.INFO, "reserved in IAMF v1.1.0")        # 28 known


def test_v2_layout_beside_known_elements_over_limit_fires():
    q = Seq(2)
    ids = [q.toa(), q.surround_7_1_4(), q.mono(), q.layout_10_2_9_3()]
    report = q.mix(ids).report()                                         # 29 known
    assert len(fired(report, Severity.FAIL, "no Mix Presentation fits",
                     "at least 29 channels before mixing (limit 28)")) == 1
    assert s109(report, Severity.INFO) == []


def test_v2_layout_does_not_hide_a_definite_violation_fires():
    q = Seq(2)
    report = q.mix([q.layout_10_2_9_3(), q.obj()]).report()
    assert_only(report, Severity.FAIL, "no Mix Presentation fits",
                "object-based audio_element(s)")


def test_v2_layout_inside_primary_says_nothing_about_additional_silent():
    q = Seq(5, 2)
    assert_silent(q.mix([q.layout_10_2_9_3()]).report())


def test_v2_layout_judged_against_an_older_additional_profile_fires():
    q = Seq(0, 2)
    a = q.stereo()
    report = q.mix([a]).mix([q.layout_10_2_9_3(), a]).report()
    assert_only(report, Severity.INFO, "mix_presentation 43",
                "the Base-Enhanced profile (2)")


# ============================================== redundant descriptor copies
def _with_redundant_descriptors(spec: B.IAMFSpec) -> bytes:
    """descriptors, frames, the same descriptors marked redundant, frames."""
    spec = spec.copy()
    frames = B._audio_frames(spec)
    spec.temporal_units = 0
    descriptors = B.build(spec)
    copy = bytearray(descriptors)
    p = 0
    while p < len(copy):                 # one-byte header, then leb128 obu_size
        copy[p] |= 0x04                  # obu_redundant_copy
        size, shift, q = 0, 0, p + 1
        while True:
            size |= (copy[q] & 0x7F) << shift
            shift += 7
            q += 1
            if not copy[q - 1] & 0x80:
                break
        p = q + size
    return descriptors + frames + bytes(copy) + frames


def test_mix_outside_the_profile_once_without_redundant_copies_fires():
    q = Seq(1)
    a = q.stereo()
    q.mix([a]).mix([a, q.mono(), q.mono()])
    assert_only(q.report(), Severity.WARN, "mix_presentation 43")


def test_mix_outside_the_profile_once_with_redundant_copies_fires():
    q = Seq(1)
    a = q.stereo()
    q.mix([a]).mix([a, q.mono(), q.mono()])
    report = validate_bytes(_with_redundant_descriptors(q.spec))
    assert report.execution_error is None
    assert len(report.model.mix_presentations) == 4      # the model keeps every OBU
    assert_only(report, Severity.WARN, "mix_presentation 43")


def test_open_count_info_once_with_redundant_copies_fires():
    q = Seq(1)
    q.mix([q.ambisonics(4, coded=4), q.stereo()])
    report = validate_bytes(_with_redundant_descriptors(q.spec))
    assert_only(report, Severity.INFO, "mix_presentation 42")


def test_first_mix_rule_reads_the_first_obu_with_redundant_copies_fires():
    q = Seq(3)
    o1, ch = q.obj(), q.stereo()
    q.mix([ch, o1]).mix([o1])
    report = validate_bytes(_with_redundant_descriptors(q.spec))
    assert_only(report, Severity.FAIL, "the first Mix Presentation (mix_presentation 42)")


# ======================================= Base-Advanced: the first-mix rule
def test_first_mix_objects_only_silent():
    q = Seq(3)
    o1, o2, ch = q.obj(), q.obj(2), q.stereo()
    assert_silent(q.mix([o1, o2]).mix([o1, ch]).report())


def test_first_mix_channel_and_object_fires():
    q = Seq(3)
    o1, ch = q.obj(), q.stereo()
    assert_only(q.mix([ch, o1]).mix([o1]).report(), Severity.FAIL,
                "primary_profile Base-Advanced (3)",
                "the first Mix Presentation (mix_presentation 42) has to reference "
                "object-based elements only",
                f"channel-based audio_element(s) [{ch}]")


def test_first_mix_scene_only_before_an_object_mix_fires():
    q = Seq(3)
    o1, sc = q.obj(), q.ambisonics(1)
    assert_only(q.mix([sc]).mix([o1]).report(), Severity.FAIL,
                "mix_presentation 43 references object-based audio elements",
                f"scene-based audio_element(s) [{sc}]")


def test_first_mix_rule_without_objects_anywhere_silent():
    q = Seq(3)
    assert_silent(q.mix([q.stereo()]).mix([q.ambisonics(1)]).report())


def test_first_mix_rule_is_base_advanced_only_silent():
    q = Seq(4)
    o1, ch = q.obj(), q.stereo()
    assert_silent(q.mix([ch, o1]).mix([o1]).report())


def test_first_mix_rule_ignores_an_object_mix_past_18_elements():
    # v2:3197 scopes the trigger to Mix Presentations for at most 18 elements.
    q = Seq(3, 1)                        # additional 1: no sequence-wide total
    ch = q.stereo()
    report = q.mix([ch]).mix([q.obj() for _ in range(19)]).report()
    assert s109(report, Severity.FAIL) == []
    assert len(fired(report, Severity.WARN, "mix_presentation 43")) == 1


def test_first_mix_rule_at_18_object_elements_fires():
    q = Seq(3, 1)
    ch = q.stereo()
    report = q.mix([ch]).mix([q.obj() for _ in range(18)]).report()
    assert_only(report, Severity.FAIL, "has to reference object-based elements only")


# ======================================================= Codec Config count
def _two_sub_mix_sequence(profile: int, extra: list[tuple[int, str]]) -> Seq:
    q = Seq(profile)
    q.spec.extra_codec_configs = extra
    return q.mix([q.stereo()], [q.mono()])


@pytest.mark.parametrize("profile", [0, 1, 2])
def test_one_codec_config_with_redundant_copies_silent(profile):
    q = Seq(profile)
    q.spec.redundant_codec_configs = 2
    report = q.mix([q.stereo()]).report()
    assert_silent(report)
    assert report.model.obu_order.count("CodecConfig") == 3
    assert len(report.model.codec_configs) == 1


@pytest.mark.parametrize("profile", [0, 1, 2])
def test_redundant_codec_config_copy_with_trailing_pad_bytes_silent(profile):
    # obu_size may exceed the syntax (v2:643): the padded copy is the same
    # Codec Config, not a second one.
    q = Seq(profile)
    q.spec.redundant_codec_configs = 1
    q.spec.redundant_codec_config_padding = b"\x00\x00\x00"
    report = q.mix([q.stereo()]).report()
    assert_silent(report)
    assert report.model.parse_errors == []
    assert report.model.obu_order.count("CodecConfig") == 2


@pytest.mark.parametrize("profile", [0, 1, 2])
def test_two_codec_configs_under_one_codec_profiles_fires(profile):
    q = Seq(profile)
    q.spec.extra_codec_configs = [(1, "ipcm")]
    report = q.mix([q.stereo()]).report()
    assert_only(report, Severity.FAIL, "2 unique Codec Config OBUs",
                f"primary_profile {NAME[profile]} ({profile}) allows only one")


@pytest.mark.parametrize("profile", [3, 4, 5])
def test_two_codec_configs_with_a_two_sub_mix_presentation_silent(profile):
    assert_silent(_two_sub_mix_sequence(profile, [(1, "Opus")]).report())


@pytest.mark.parametrize("profile", [3, 4, 5])
def test_three_codec_configs_fires(profile):
    report = _two_sub_mix_sequence(profile, [(1, "Opus"), (2, "ipcm")]).report()
    assert_only(report, Severity.FAIL, "3 unique Codec Config OBUs",
                f"primary_profile {NAME[profile]} ({profile}) allows at most 2")


@pytest.mark.parametrize("profile", [3, 4, 5])
def test_two_codec_configs_with_single_sub_mix_presentations_fires(profile):
    q = Seq(profile)
    q.spec.extra_codec_configs = [(1, "Opus")]
    report = q.mix([q.stereo()]).mix([q.mono()]).report()
    assert_only(report, Severity.FAIL, "2 unique Codec Config OBUs",
                "every Mix Presentation has one sub-mix")


# ========================================================= model and parser
def test_objects_config_is_read_and_extension_bytes_skipped():
    q = Seq(4)
    eid = q.obj(2, objects_extension=b"\xaa\xbb\xcc")
    report = q.mix([eid]).report()
    cfg = report.model.audio_elements[eid].objects
    assert (cfg.objects_config_size, cfg.num_objects, cfg.extension_bytes) == (4, 2, 3)
    assert report.model.parse_errors == [] and report.model.parse_notes == []


NOT_AN_OBJECTS_CONFIG = pytest.mark.parametrize(
    "raw", [b"", b"\x00", b"\x05\x01"],
    ids=["no-bytes", "size-0", "size-past-the-obu"])


def _type_2_with(raw: bytes, primary: int, additional: int):
    q = Seq(primary, additional)
    eid = q._add("object", 1, raw_config=raw)
    report = q.mix([q.stereo()]).mix([eid]).report()
    ae = report.model.audio_elements[eid]
    assert ae.audio_element_type == 2 and ae.objects is None    # kept, count unknown
    assert any("not an ObjectsConfig" in n for n in report.model.parse_notes)
    return report


@NOT_AN_OBJECTS_CONFIG
@pytest.mark.parametrize("primary,additional", [(0, 0), (1, 1), (2, 2), (0, 2), (1, 255)])
def test_bad_objects_config_where_no_profile_defines_objects_is_a_note(
        raw, primary, additional):
    # Type 2 was reserved before v2.0.0: any bytes may follow it there.
    report = _type_2_with(raw, primary, additional)
    assert report.model.parse_errors == [] and s108(report) == []


@NOT_AN_OBJECTS_CONFIG
@pytest.mark.parametrize("primary,additional", [(3, 3), (4, 4), (5, 5), (1, 4), (4, 1)])
def test_bad_objects_config_under_an_object_profile_is_a_parse_error_fires(
        raw, primary, additional):
    report = _type_2_with(raw, primary, additional)
    assert s108(report) == ["not an ObjectsConfig"]
    assert len(report.model.parse_errors) == 1
    assert report.exit_code() == 1


def test_bad_objects_config_before_any_sequence_header_is_a_note():
    spec = B.IAMFSpec(elements=[B.ElementSpec(300, 0, "object", [0], raw_config=b"\x00")])
    mod = parse_bytes(B._audio_element(spec.elements[0]))
    assert mod.sequence_header is None and mod.parse_errors == []
    assert mod.audio_elements[300].objects is None


def test_object_count_zero_under_an_object_profile_is_left_alone_silent():
    # Forbidden by the text, and owned by a later check: here it is a config
    # that parses, with a count that is not usable.
    q = Seq(3)
    report = q.mix([q.obj(0)]).report()
    assert_silent(report)
    assert s108(report) == [] and report.model.parse_errors == []


def test_expanded_layout_is_read_after_the_output_gain_fields():
    # ChannelAudioLayerConfig(): output_gain_flags and output_gain come first,
    # expanded_loudspeaker_layout last.
    def element(with_gain: bool) -> B.ElementSpec:
        w = B.Writer().u8(1 << 5)                           # num_layers = 1
        w.u8((15 << 4) | (0x08 if with_gain else 0)).u8(16).u8(8)
        if with_gain:
            w.u8(0x05 << 2).s16(-384)                       # flags, output_gain
        w.u8(13)                                            # 10.2.9.3ch
        return B.ElementSpec(300, 0, "channel", list(range(16)), raw_config=w.bytes())

    for with_gain in (False, True):
        spec = B.IAMFSpec(primary_profile=5, additional_profile=5,
                          elements=[element(with_gain)],
                          mixes=[B.MixSpec(42, [300], "Programme", LAYOUTS)])
        report = validate_bytes(B.build(spec))
        layer = report.model.audio_elements[300].channel_layers[0]
        assert layer.expanded_loudspeaker_layout == 13, with_gain
        assert (layer.output_gain_flags, layer.output_gain) == (
            (5, -384) if with_gain else (None, None))
        assert report.model.parse_errors == []
        assert_silent(report)                               # 24 channels, Advanced-2


def test_scene_element_keeps_declared_and_coded_counts():
    q = Seq(1)
    mixed = q.ambisonics(3, coded=4)
    w = B.Writer().leb128(1).u8(4).u8(1).u8(1).raw(b"\x00" * 16)    # projection
    proj = q._add("scene", 1, raw_config=w.bytes())
    mod = parse_bytes(B.build(q.spec))
    a = mod.audio_elements[mixed].ambisonics
    assert (a.output_channel_count, a.coded_channel_count) == (16, 4)
    p = mod.audio_elements[proj].ambisonics
    assert (p.mode, p.output_channel_count, p.coded_channel_count) == (1, 4, 2)


def test_expanded_layout_table_covers_0_to_19():
    from sentinel.layouts import EXPANDED_LAYOUT_CHANNELS, EXPANDED_LOUDSPEAKER_LAYOUT
    assert EXPANDED_LAYOUT_CHANNELS == {
        0: 1, 1: 2, 2: 2, 3: 2, 4: 2, 5: 2, 6: 4, 7: 3, 8: 16, 9: 2, 10: 2, 11: 2,
        12: 6, 13: 24, 14: 2, 15: 3, 16: 17, 17: 4, 18: 1, 19: 5}
    assert sorted(EXPANDED_LOUDSPEAKER_LAYOUT) == list(range(20))
    assert EXPANDED_LOUDSPEAKER_LAYOUT[13] == "10.2.9.3"
    assert EXPANDED_LOUDSPEAKER_LAYOUT[16] == "7.1.5.4"


# ================================================== display and JSON contract
def test_json_names_a_defined_profile_and_keeps_a_reserved_value_bare():
    from sentinel.report import render_html, render_json, render_text
    q = Seq(4)
    report = q.mix([q.stereo()]).report()
    value = json.loads(render_json(report))["summary"]["stream"]["primary_profile"]
    assert value == "Advanced-1" and isinstance(value, str)
    assert "Advanced-1 profile" in render_text(report)

    q = Seq(7)
    report = q.mix([q.stereo()]).report()
    value = json.loads(render_json(report))["summary"]["stream"]["primary_profile"]
    assert value == 7 and isinstance(value, int)
    assert "reserved (7) profile" in render_text(report)
    assert "reserved (7) profile" in render_html(report)


def test_diff_keeps_a_reserved_profile_bare_in_json_and_labels_it_in_text(tmp_path):
    from sentinel.diff import diff_files, render_diff_text
    paths = []
    for primary in (4, 7):
        q = Seq(primary)
        q.mix([q.stereo()])
        paths.append(tmp_path / f"p{primary}.iamf")
        paths[-1].write_bytes(B.build(q.spec))
    res = diff_files(str(paths[0]), str(paths[1]))
    entry = next(e for e in res.entries if e.where == "primary_profile").to_dict()
    assert entry["a"] == "Advanced-1"
    assert entry["b"] == 7 and isinstance(entry["b"], int)
    text = render_diff_text(res)
    assert "a=Advanced-1" in text and "b=reserved (7)" in text


# ================================================================ pack keys
def _packs(tmp_path, monkeypatch, **bodies: str) -> None:
    """Write one profile pack per keyword and point the engine at them."""
    from sentinel import engine
    for name, body in bodies.items():
        (tmp_path / f"{name}.toml").write_text(
            f'name = "{name}"\n{body}\n', encoding="utf-8")
    monkeypatch.setattr(engine, "PROFILE_DIR", str(tmp_path))


def _stereo(primary: int, pack: str):
    q = Seq(primary)
    q.mix([q.stereo()])
    return validate_bytes(B.build(q.spec), profile=pack)


def test_pack_exact_primary_profile_is_unchanged(tmp_path, monkeypatch):
    _packs(tmp_path, monkeypatch, exact="[require]\nprimary_profile = 1")
    assert s109(_stereo(1, "exact")) == []
    f = next(f for f in _stereo(2, "exact").findings if f.check_id == "S-109")
    assert (f.severity, f.message) == (Severity.FAIL, "profile 'exact' requires Base profile")
    assert (f.expected, f.found) == ("Base", "Base-Enhanced")
    f = next(f for f in _stereo(7, "exact").findings if f.check_id == "S-109")
    assert (f.expected, f.found) == ("Base", "7")


@pytest.mark.parametrize("primary,accepted", [(1, True), (3, True), (0, False),
                                              (2, False), (7, False)])
def test_pack_primary_profile_in(tmp_path, monkeypatch, primary, accepted):
    _packs(tmp_path, monkeypatch, inset="[require]\nprimary_profile_in = [1, 3]")
    report = _stereo(primary, "inset")
    assert report.execution_error is None
    if accepted:
        assert s109(report) == []
    else:
        assert s109(report, Severity.FAIL) == [
            "profile 'inset' requires one of the profiles Base, Base-Advanced"]


AT_MOST = {0: {0}, 1: {0, 1}, 2: {0, 1, 2}, 3: {0, 1, 3}, 4: {0, 1, 3, 4},
           5: {0, 1, 2, 3, 4, 5}}


@pytest.mark.parametrize("top", range(6))
def test_pack_primary_profile_at_most_follows_the_partial_order(tmp_path, monkeypatch, top):
    _packs(tmp_path, monkeypatch, atmost=f"[require]\nprimary_profile_at_most = {top}")
    for primary in list(range(6)) + [6, 255]:
        report = _stereo(primary, "atmost")
        assert report.execution_error is None
        failed = bool(s109(report, Severity.FAIL))
        assert failed == (primary not in AT_MOST[top]), (top, primary)


def test_pack_base_enhanced_is_not_at_most_base_advanced_fires(tmp_path, monkeypatch):
    _packs(tmp_path, monkeypatch, atmost="[require]\nprimary_profile_at_most = 3")
    assert s109(_stereo(2, "atmost"), Severity.FAIL) == [
        "profile 'atmost' requires Base-Advanced profile or simpler "
        "(Simple, Base, Base-Advanced)"]
    assert s109(_stereo(1, "atmost")) == []


@pytest.mark.parametrize("body,words", [
    ("primary_profile = 1\nprimary_profile_at_most = 3",
     ("require.primary_profile and require.primary_profile_at_most", "alternatives")),
    ("primary_profile = 1\nprimary_profile_in = [1]",
     ("require.primary_profile and require.primary_profile_in", "alternatives")),
    ("primary_profile_in = [1, 3]\nprimary_profile_at_most = 3",
     ("require.primary_profile_in and require.primary_profile_at_most", "alternatives")),
    ("primary_profile_in = []", ("primary_profile_in must be a non-empty list",)),
    ('primary_profile_in = [1, "3"]', ("primary_profile_in must be a non-empty list",)),
    ("primary_profile_in = 1", ("primary_profile_in must be a non-empty list",)),
    ("primary_profile_at_most = 9", ("primary_profile_at_most must be a defined profile",)),
    ("primary_profile_at_most = true", ("primary_profile_at_most must be a defined profile",)),
], ids=["exact+at_most", "exact+in", "in+at_most", "in-empty", "in-not-int",
        "in-not-list", "at_most-reserved", "at_most-bool"])
def test_pack_that_cannot_be_applied_is_an_execution_error(tmp_path, monkeypatch,
                                                           body, words):
    _packs(tmp_path, monkeypatch, bad=f"[require]\n{body}")
    report = _stereo(1, "bad")
    assert report.exit_code() == 2 and report.findings == []
    for w in words + ("'bad'",):
        assert w in report.execution_error
