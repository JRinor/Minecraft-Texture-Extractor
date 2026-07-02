from extractor.matcher import find_matches
from extractor.models import Candidate, ItemProfile, ProfileType
from extractor.pack_discovery import discover_packs_for_entry


def _make_pack(tmp_path):
    base = tmp_path / "mypack" / "assets" / "minecraft" / "textures" / "items"
    base.mkdir(parents=True)
    (base / "diamond_sword.png").write_bytes(b"sword")
    (base / "bow_standby.png").write_bytes(b"b0")
    (base / "bow_pulling_0.png").write_bytes(b"b1")
    (base / "potion_overlay.png").write_bytes(b"p")
    (base / "potion_overlay.png.mcmeta").write_bytes(b"{anim}")
    (tmp_path / "mypack" / "pack.mcmeta").write_text(
        '{"pack":{"pack_format":15,"description":"d"}}', encoding="utf-8")
    packs = list(discover_packs_for_entry(tmp_path / "mypack"))
    assert len(packs) == 1
    return packs[0]


def _basenames(unit):
    return sorted(f.rel_path.rsplit("/", 1)[-1] for f in unit.files)


def test_match_simple(tmp_path):
    pack = _make_pack(tmp_path)
    profile = ItemProfile(id="sword", type=ProfileType.SIMPLE, display_name="s",
                          candidates=(Candidate("diamond_sword.png"),), path_hints=("item",))
    units = find_matches(profile, pack)
    assert len(units) == 1
    assert _basenames(units[0]) == ["diamond_sword.png"]


def test_match_set_pulls_companions(tmp_path):
    pack = _make_pack(tmp_path)
    profile = ItemProfile(id="bow", type=ProfileType.SET, display_name="b",
                          candidates=(Candidate("bow_standby.png"),),
                          companions=(Candidate("bow_pulling_0.png"),), path_hints=("item",))
    units = find_matches(profile, pack)
    assert len(units) == 1
    assert _basenames(units[0]) == ["bow_pulling_0.png", "bow_standby.png"]


def test_sidecar_mcmeta_included(tmp_path):
    pack = _make_pack(tmp_path)
    profile = ItemProfile(id="potion", type=ProfileType.SIMPLE, display_name="p",
                          candidates=(Candidate("potion_overlay.png"),), path_hints=("item",))
    units = find_matches(profile, pack)
    assert "potion_overlay.png.mcmeta" in _basenames(units[0])


def test_source_meta_read(tmp_path):
    pack = _make_pack(tmp_path)
    meta = pack.source_meta()
    assert meta.pack_format == 15
    assert meta.description == "d"
