"""`sentinel adm-check`: an ADM BWF master judged against Dolby's delivery rules.

Every rule is driven both ways: a master that meets it, and a master built
to break it alone, so each row is shown able to say something other than
PASS. Masters come from the clean-room builder (fixtures/dbmd_build.py); no
Dolby-written master is available, which is why rows S-511..S-515 carry the
field-map basis and why the measured rows can only be UNDETERMINED here.
"""

from __future__ import annotations

import json
import os
import sys

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fixtures import dbmd_build as B  # noqa: E402
from sentinel import adm_check as A  # noqa: E402
from sentinel.cli import main  # noqa: E402
from sentinel.findings import REGISTRY, Severity  # noqa: E402

BED_712 = ["0001"] * 10
SEEN: set[str] = set()


@pytest.fixture(autouse=True)
def _no_plugin(monkeypatch):
    """The core's own behaviour: no measurement plugin, whatever is installed.
    Tests of the plugin seam install a fake one (below)."""
    monkeypatch.setattr(A, "_measure_plugin", lambda: None)


def _dbmd(binaural=None, n=14, **kw9):
    binaural = [1] * n if binaural is None else binaural
    seg10_kw = {k: kw9.pop(k) for k in ("trims",) if k in kw9}
    return B.dbmd([B.segment(9, B.segment9(**kw9)),
                   B.segment(10, B.segment10(list(binaural), **seg10_kw))])


def master(tmp_path, name="m.wav", *, channels=14, types=None, dbmd=..., **kw):
    if types is None:
        types = (BED_712 + ["0003"] * channels)[:channels]
    payload = _dbmd(n=channels) if dbmd is ... else dbmd
    p = tmp_path / name
    p.write_bytes(B.adm_wav(channels=channels, types=types, dbmd_payload=payload,
                            frames=48, **kw))
    return str(p)


def rows(path):
    res = A.check_master(path)
    for r in res["rows"]:
        SEEN.add(r["id"])
    return {r["id"]: r for r in res["rows"]}, res


def v(path, rid):
    return rows(path)[0][rid]["verdict"]


# --------------------------------------------------------------- a clean master

def test_clean_master_has_nothing_failed_and_says_what_was_not_judged(tmp_path):
    p = master(tmp_path)
    rs, res = rows(p)
    assert {r["verdict"] for r in rs.values()} == {"PASS", "UNDETERMINED"}
    assert sorted(k for k, r in rs.items() if r["verdict"] == "UNDETERMINED") == [
        "S-516", "S-520", "S-521", "S-522", "S-523", "S-524", "S-525"]
    assert res["verdict"] == "PASS" and res["complete"] is False
    assert res["facts"]["bedChannels"] == 10 and res["facts"]["objects"] == 4
    line = A._verdict_line(res)
    assert line.startswith("NOTHING FAILED; 7 RULE(S) NOT DETERMINED")
    assert "PASSES" not in line                      # undetermined is never a pass
    for rid in ("S-511", "S-512", "S-513", "S-514", "S-515"):
        assert "not yet confirmed" in rs[rid]["basis"]
    assert "remedy" not in rs["S-501"] and "remedy" in rs["S-520"]
    assert "iamf-sentinel-pro" in rs["S-522"]["notes"][0]       # says what it needs
    assert "stereo master" in rs["S-523"]["notes"][0]


# ------------------------------------------------------------ container rules

def test_s501_not_a_wave_fails_and_errors(tmp_path):
    p = tmp_path / "x.wav"
    p.write_bytes(b"OggS" + bytes(60))
    rs, res = rows(str(p))
    assert rs["S-501"]["verdict"] == "FAIL" and not res["readable"]
    assert A.run([str(p)])["exit_code"] == 2


@pytest.mark.parametrize("drop", [b"axml", b"chna"])
def test_s501_missing_adm_chunk_fails(tmp_path, drop):
    rs, _ = rows(master(tmp_path, drop=(drop,)))
    assert rs["S-501"]["verdict"] == "FAIL"
    assert any(drop.decode() in n for n in rs["S-501"]["notes"])


def test_s501_truncated_data_fails(tmp_path):
    rs, _ = rows(master(tmp_path, truncate=10))
    assert rs["S-501"]["verdict"] == "FAIL"
    assert any("runs past the end" in n for n in rs["S-501"]["notes"])


def test_s502_format_tag(tmp_path):
    assert v(master(tmp_path, "a.wav"), "S-502") == "PASS"
    rs, _ = rows(master(tmp_path, "b.wav", fmt_tag=0xFFFE))
    assert rs["S-502"]["verdict"] == "FAIL" and "EXTENSIBLE" in rs["S-502"]["measured"]


def test_s503_channel_limit(tmp_path):
    assert v(master(tmp_path, "a.wav", channels=128,
                    dbmd=_dbmd(n=128)), "S-503") == "PASS"
    assert v(master(tmp_path, "b.wav", channels=129,
                    dbmd=_dbmd(n=129)), "S-503") == "FAIL"


def test_s504_object_limit_and_track_types(tmp_path):
    ok = master(tmp_path, "a.wav", channels=128, types=BED_712 + ["0003"] * 118,
                dbmd=_dbmd(n=128))
    assert v(ok, "S-504") == "PASS"
    over = master(tmp_path, "b.wav", channels=128, types=["0001"] * 9 + ["0003"] * 119,
                  dbmd=_dbmd(n=128))
    rs, _ = rows(over)
    assert rs["S-504"]["verdict"] == "FAIL" and "119 objects" in rs["S-504"]["notes"]
    hoa = master(tmp_path, "c.wav", types=BED_712 + ["0004"] * 4)
    rs, _ = rows(hoa)
    assert rs["S-504"]["verdict"] == "FAIL" and "HOA" in rs["S-504"]["notes"][0]


@pytest.mark.parametrize("bits,verdict", [(24, "PASS"), (16, "FAIL"), (32, "FAIL")])
def test_s505_bit_depth(tmp_path, bits, verdict):
    assert v(master(tmp_path, bits=bits), "S-505") == verdict


@pytest.mark.parametrize("rate,verdict", [(48000, "PASS"), (96000, "FAIL"), (44100, "FAIL")])
def test_s506_sample_rate(tmp_path, rate, verdict):
    rs, _ = rows(master(tmp_path, rate=rate))
    assert rs["S-506"]["verdict"] == verdict
    if rate == 96000:
        assert "DAMF" in rs["S-506"]["notes"][0]


@pytest.mark.parametrize("container,verdict", [(b"RF64", "PASS"), (b"BW64", "FAIL")])
def test_s507_four_gigabytes_must_be_rf64(tmp_path, container, verdict):
    # A ds64 that declares 4 GiB of RIFF data, without writing them.
    rs, res = rows(master(tmp_path, container=container, ds64_riff=1 << 32))
    assert rs["S-507"]["verdict"] == verdict and res["facts"]["fourGigabytesOrMore"]


@pytest.mark.parametrize("container", [b"RIFF", b"RF64", b"BW64"])
def test_s507_under_four_gigabytes_any_container(tmp_path, container):
    rs, res = rows(master(tmp_path, container=container))
    assert rs["S-507"]["verdict"] == "PASS" and not res["facts"]["fourGigabytesOrMore"]


def test_s508_chna_integrity(tmp_path):
    assert v(master(tmp_path, "a.wav"), "S-508") == "PASS"
    rs, _ = rows(master(tmp_path, "b.wav", chna_uids=13))
    assert rs["S-508"]["verdict"] == "FAIL"
    assert any("numUID 13 != numTrack 14" in n for n in rs["S-508"]["notes"])
    rs, _ = rows(master(tmp_path, "c.wav", chna_tracks=12))
    assert rs["S-508"]["verdict"] == "FAIL"
    assert any("2 track(s) with no UID" in n for n in rs["S-508"]["notes"])


@pytest.mark.parametrize("junk,verdict", [(28, "PASS"), (64, "PASS"), (66, "FAIL")])
def test_s509_junk_limit_under_four_gigabytes(tmp_path, junk, verdict):
    assert v(master(tmp_path, junk=junk), "S-509") == verdict


# ------------------------------------------------------------- Dolby's block

def test_s510_absent_block_warns_and_leaves_settings_undetermined(tmp_path):
    rs, res = rows(master(tmp_path, dbmd=None))
    assert rs["S-510"]["verdict"] == "WARN"
    for rid in ("S-511", "S-512", "S-513", "S-514", "S-515"):
        assert rs[rid]["verdict"] == "UNDETERMINED"
        assert rs[rid]["measured"].startswith("no dbmd block")
    assert not any("S-511..S-515 read" in n for n in res["notes"])


def test_s510_placeholder_block_warns_as_empty(tmp_path):
    # Inseglet's placeholder: a version word, then zeroes.
    rs, _ = rows(master(tmp_path, dbmd=bytes.fromhex("00000001") + bytes(28)))
    assert rs["S-510"]["verdict"] == "WARN" and "empty" in rs["S-510"]["measured"]
    assert rs["S-511"]["verdict"] == "UNDETERMINED"


@pytest.mark.parametrize("fps,verdict", [(2, "PASS"), (3, "FAIL"), (1, "FAIL"),
                                         (0, "UNDETERMINED")])
def test_s511_frame_rate(tmp_path, fps, verdict):
    assert v(master(tmp_path, dbmd=_dbmd(fps=fps)), "S-511") == verdict


def test_s512_first_frame_of_action(tmp_path):
    assert v(master(tmp_path, "a.wav"), "S-512") == "PASS"
    rs, _ = rows(master(tmp_path, "b.wav", dbmd=_dbmd(ffoa=(0, 0, 400000))))
    assert rs["S-512"]["verdict"] == "FAIL" and rs["S-512"]["measured"] == "set at 4.00000 s"


@pytest.mark.parametrize("warp,verdict", [(0, "PASS"), (1, "WARN"), (3, "WARN"), (4, "WARN")])
def test_s513_51x_downmix(tmp_path, warp, verdict):
    assert v(master(tmp_path, dbmd=_dbmd(warp=warp)), "S-513") == verdict


@pytest.mark.parametrize("dm,verdict", [(1, "PASS"), (0, "WARN"), (2, "WARN"), (4, "WARN")])
def test_s514_51_to_20_downmix(tmp_path, dm, verdict):
    rs, _ = rows(master(tmp_path, dbmd=_dbmd(downmix5to2=dm)))
    assert rs["S-514"]["verdict"] == verdict
    if dm == 0:
        assert "not indicated" in rs["S-514"]["notes"][0]


def test_s515_headphone_modes(tmp_path):
    rs, _ = rows(master(tmp_path, "a.wav", dbmd=_dbmd(binaural=[0, 1, 2, 3] * 3 + [1, 1])))
    assert rs["S-515"]["verdict"] == "PASS"
    assert rs["S-515"]["measured"] == "Off x3, Near x5, Mid x3, Far x3"   # 2 Far, 3 Mid
    rs, _ = rows(master(tmp_path, "b.wav", dbmd=_dbmd(binaural=[1] * 13 + [4])))
    assert rs["S-515"]["verdict"] == "WARN"
    assert "1 track(s) not indicated (first: track 14)" in rs["S-515"]["notes"]
    rs, _ = rows(master(tmp_path, "c.wav", dbmd=_dbmd(binaural=[1] * 10)))
    assert rs["S-515"]["verdict"] == "WARN"
    assert "segment 10 gives modes for 10 of 14 tracks" in rs["S-515"]["notes"]
    rs, _ = rows(master(tmp_path, "d.wav", dbmd=_dbmd(binaural=[0] * 14)))
    assert rs["S-515"]["verdict"] == "PASS" and "every track is Off" in rs["S-515"]["notes"]


# ------------------------------------------------------------------ the album

def _album(tmp_path, specs):
    d = tmp_path / "album"
    d.mkdir(parents=True)
    for i, kw in enumerate(specs):
        master(d, f"{i + 1:02d}.wav", dbmd=_dbmd(**kw))
    return str(d)


def _album_rows(res):
    assert len(res["albums"]) == 1
    for r in res["albums"][0]["rows"]:
        SEEN.add(r["id"])
    return {r["id"]: r for r in res["albums"][0]["rows"]}


def test_s530_bed_modes_match_and_differ(tmp_path):
    same = _album(tmp_path / "x", [{}, {"binaural": [1] * 10 + [2, 3, 0, 0]}])
    rs = _album_rows(A.run([same], album=True))
    assert rs["S-530"]["verdict"] == "PASS"          # objects differ; beds match
    diff = _album(tmp_path / "y", [{}, {"binaural": [2] + [1] * 13}])
    rs = _album_rows(A.run([diff], album=True))
    assert rs["S-530"]["verdict"] == "WARN" and rs["S-530"]["measured"] == "differs on 02.wav"
    assert "S-531" not in rs                          # gapless rules need --gapless


def test_s530_reads_beds_by_track_index_not_chna_order(tmp_path):
    # chna may list its entries in any order; the dbmd's n-th mode is the n-th
    # audio track. Beds are tracks 1-10 here, listed last; objects differ.
    d = tmp_path / "album"
    d.mkdir()
    for i, objs in enumerate(([1, 1, 1, 1], [2, 3, 0, 2])):
        master(d, f"{i + 1:02d}.wav", chna_reversed=True,
               dbmd=_dbmd(binaural=[1] * 10 + objs))
    res = A.run([str(d)], album=True)
    assert res["masters"][0]["facts"]["bedChannels"] == 10
    assert _album_rows(res)["S-530"]["verdict"] == "PASS"


def test_gapless_rules(tmp_path):
    ok = _album(tmp_path / "x", [{}, {}])
    rs = _album_rows(A.run([ok], gapless=True))
    assert [rs[k]["verdict"] for k in ("S-531", "S-532", "S-533", "S-534")] == [
        "PASS", "PASS", "UNDETERMINED", "UNDETERMINED"]
    assert "iamf-sentinel-pro" in rs["S-533"]["notes"][0]
    bad = _album(tmp_path / "y", [{}, {"downmix5to2": 2}])
    res = A.run([bad], gapless=True)
    rs = _album_rows(res)
    assert rs["S-531"]["verdict"] == "FAIL" and res["exit_code"] == 1
    trims = _album(tmp_path / "z", [{}, {"trims": [(-3.0, -1.0, 0.0, 0, 0)] + ["auto"] * 8}])
    rs = _album_rows(A.run([trims], gapless=True))
    assert rs["S-531"]["verdict"] == "PASS" and rs["S-532"]["verdict"] == "WARN"


def test_gapless_with_an_unreadable_setting_is_undetermined(tmp_path):
    d = tmp_path / "album"
    d.mkdir()
    master(d, "01.wav")
    master(d, "02.wav", dbmd=None)
    rs = _album_rows(A.run([str(d)], gapless=True))
    assert rs["S-531"]["verdict"] == "UNDETERMINED"
    assert rs["S-530"]["verdict"] == "UNDETERMINED"   # one track with modes is not a comparison


# ------------------------------------------------------- folders and the CLI

def test_folder_walk_skips_non_adm_wave_and_lists_it(tmp_path):
    d = tmp_path / "cat"
    (d / "a").mkdir(parents=True)
    master(d / "a", "song.wav")
    stereo = d / "a" / "other.wav"          # not named after a master: skipped, not paired
    stereo.write_bytes(B.adm_wav(channels=2, drop=(b"axml", b"chna")))
    (d / "a" / "notes.txt").write_text("x", encoding="utf-8")
    res = A.run([str(d)])
    assert [os.path.basename(m["path"]) for m in res["masters"]] == ["song.wav"]
    assert res["skipped"] == [str(stereo)] and res["exit_code"] == 0
    assert res["stereoPairs"] == {}


def test_named_non_adm_file_is_judged_not_skipped(tmp_path):
    p = tmp_path / "stereo.wav"
    p.write_bytes(B.adm_wav(channels=2, drop=(b"axml", b"chna")))
    res = A.run([str(p)])
    assert res["masters"][0]["verdict"] == "FAIL" and res["exit_code"] == 1


def test_a_folder_with_no_adm_master_is_an_error_that_says_so(tmp_path):
    (tmp_path / "stereo.wav").write_bytes(B.adm_wav(channels=2, drop=(b"axml", b"chna")))
    res = A.run([str(tmp_path)])
    assert res["exit_code"] == 2 and "no ADM master" in res["errors"][0]
    assert res["skipped"] == [str(tmp_path / "stereo.wav")]


def test_missing_path_is_an_error(tmp_path):
    res = A.run([str(tmp_path / "nope.wav")])
    assert res["exit_code"] == 2 and "no such file" in res["errors"][0]


def test_cli_json_text_html_and_strict(tmp_path, capsys):
    p = master(tmp_path, dbmd=_dbmd(warp=1))
    assert main(["adm-check", p, "--format", "json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["masters"][0]["verdict"] == "WARN" and out["exit_code"] == 0
    assert out["specifications"] == [A.DELIVERY, A.PROFILE]
    assert main(["adm-check", p, "--strict"]) == 1
    txt = capsys.readouterr().out
    assert "WARN         S-513" in txt and "to fix: Set the 5.1 and 5.1.x downmix" in txt
    assert "not affiliated with or endorsed by Dolby" in txt
    h = tmp_path / "r.html"
    assert main(["adm-check", p, "--format", "html", "-o", str(h)]) == 0
    page = h.read_text(encoding="utf-8")
    assert page.startswith("<!doctype html>") and 'class="v WARN"' in page
    assert "not affiliated" in page and "S-520" in page


# ------------------------------------------------- the measurement plugin seam

class FakePlugin:
    """Stands in for sentinel_pro.adm_delivery: records its calls and returns
    what a test asks for."""
    API = 1

    def __init__(self, rows=None, boom=None, gapless=None):
        self.calls, self.rows, self.boom, self.gapless = [], rows or {}, boom, gapless

    def measure_master(self, path, info, stereo=None):
        self.calls.append((os.path.basename(path), stereo and os.path.basename(stereo)))
        if self.boom:
            raise self.boom
        out = [dict(id=k, reference="ref", notes=["n"], **v) for k, v in self.rows.items()
               if k != "S-523" or stereo is not None]
        data = {"lfeTracks": [4]}
        if stereo is not None:
            data["sync"] = {"offsetSamples": 0, "extraTailSamples": 0, "frameSamples": 2000}
        return {"rows": out, "data": data}

    def gapless_boundaries(self, syncs, names):
        return self.gapless or {"verdict": "PASS", "measured": f"{len(syncs)} tracks",
                                "reference": "half a frame", "notes": []}


SVG = '<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 1 1"><polyline points="0,0"/></svg>'
ROWS = {"S-522": {"verdict": "WARN", "measured": "worst +7.0 dB", "plot": SVG},
        "S-524": {"verdict": "PASS", "measured": "all carry signal"},
        "S-525": {"verdict": "PASS", "measured": "48 kHz: not applicable"},
        "S-523": {"verdict": "FAIL", "measured": "offset +480 samples"}}


def _plug(monkeypatch, **kw):
    fake = FakePlugin(**kw)
    monkeypatch.setattr(A, "_measure_plugin", lambda: fake)
    return fake


def _stereo(path):
    path.write_bytes(B.adm_wav(channels=2, drop=(b"axml", b"chna")))
    return str(path)


def test_plugin_rows_fill_the_measured_rules(tmp_path, monkeypatch):
    fake = _plug(monkeypatch, rows=ROWS)
    p = master(tmp_path)
    rs, res = rows(p)
    assert {k: rs[k]["verdict"] for k in ("S-522", "S-524", "S-525", "S-523")} == {
        "S-522": "WARN", "S-524": "PASS", "S-525": "PASS", "S-523": "UNDETERMINED"}
    assert "stereo master" in rs["S-523"]["notes"][0]   # no stereo: not asked of the plugin
    assert rs["S-522"]["plot"] == SVG and fake.calls == [("m.wav", None)]
    assert res["facts"]["measured"]["lfeTracks"] == [4]


def test_a_stereo_beside_the_master_is_paired_and_not_skipped(tmp_path, monkeypatch):
    fake = _plug(monkeypatch, rows=ROWS)
    master(tmp_path, "song.wav")
    st = _stereo(tmp_path / "Song_Stereo.wav")
    res = A.run([str(tmp_path)])
    assert res["stereoPairs"] == {str(tmp_path / "song.wav"): st} and res["skipped"] == []
    assert fake.calls == [("song.wav", "Song_Stereo.wav")]
    r = {x["id"]: x for x in res["masters"][0]["rows"]}
    assert r["S-523"]["verdict"] == "FAIL" and res["exit_code"] == 1


def test_stereo_option_file_and_folder(tmp_path, monkeypatch):
    fake = _plug(monkeypatch, rows=ROWS)
    one = master(tmp_path, "a.wav")
    st = _stereo(tmp_path / "anything.wav")
    A.run([one], stereo=st)                      # a file, one master: used as is
    sd = tmp_path / "st"
    sd.mkdir()
    _stereo(sd / "a-stereo.wav")
    _stereo(sd / "unrelated.wav")
    A.run([one], stereo=str(sd))                 # a folder: paired by name
    assert fake.calls == [("a.wav", "anything.wav"), ("a.wav", "a-stereo.wav")]
    assert "no such stereo" in A.run([one], stereo=str(tmp_path / "nope"))["errors"][0]


def test_without_the_plugin_a_paired_stereo_says_the_plugin_is_needed(tmp_path):
    master(tmp_path, "song.wav")
    _stereo(tmp_path / "song_stereo.wav")
    r = {x["id"]: x for x in A.run([str(tmp_path)])["masters"][0]["rows"]}
    assert r["S-523"]["verdict"] == "UNDETERMINED"
    assert "iamf-sentinel-pro" in r["S-523"]["notes"][0]


def test_a_failing_measurement_is_undetermined_never_fatal(tmp_path, monkeypatch):
    _plug(monkeypatch, boom=ValueError("bad pcm"))
    rs, res = rows(master(tmp_path))
    for rid in ("S-522", "S-523", "S-524", "S-525"):
        assert rs[rid]["verdict"] == "UNDETERMINED"
        assert "ValueError: bad pcm" in rs[rid]["notes"][0]
    assert res["readable"]


def test_gapless_boundaries_come_from_each_tracks_sync(tmp_path, monkeypatch):
    _plug(monkeypatch, rows=ROWS, gapless={"verdict": "FAIL", "measured": "1500 samples",
                                           "notes": []})
    d = tmp_path / "album"
    d.mkdir()
    for n in ("01", "02"):
        master(d, f"{n}.wav")
        _stereo(d / f"{n}_stereo.wav")
    rs = _album_rows(A.run([str(d)], gapless=True))
    assert rs["S-533"]["verdict"] == "FAIL" and rs["S-533"]["measured"] == "1500 samples"
    os.remove(d / "02_stereo.wav")
    rs = _album_rows(A.run([str(d)], gapless=True))
    assert rs["S-533"]["verdict"] == "UNDETERMINED" and "1 of 2" in rs["S-533"]["measured"]


def test_html_embeds_a_plot_only_when_it_is_a_bare_svg(tmp_path, monkeypatch):
    _plug(monkeypatch, rows=ROWS)
    page = A.render_html(A.run([master(tmp_path)]))
    assert SVG in page
    for bad in ('<svg onload="x()"></svg>', '<svg ><a href="https://e"/></svg>',
                '<svg ><script>x</script></svg>', "<b>not svg</b>"):
        assert not A._safe_svg(bad), bad
    assert A._safe_svg(SVG)


# --------------------------------------------------------------- the registry

def test_rules_are_registered_with_their_documents_level():
    for rid, rule in A.RULES.items():
        spec = REGISTRY[rid]
        assert spec.layer == "ADM" and spec.title == rule.title
        want = Severity.WARN if rule.level in ("SHOULD", "profile", "advisory") else Severity.FAIL
        assert spec.default_severity == want, rid
        assert rule.source in spec.description


def test_every_rule_was_reported_by_some_test():
    # Runs last in this file: each rule above appeared in at least one report.
    assert SEEN == set(A.RULES), sorted(set(A.RULES) - SEEN)
