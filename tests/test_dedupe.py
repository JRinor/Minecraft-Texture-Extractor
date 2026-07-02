from extractor.dedupe import DedupeStore, compute_unit_hash
from extractor.models import FoundFile, ItemProfile, MatchUnit, ProfileType


def _unit(files):
    profile = ItemProfile(id="x", type=ProfileType.SIMPLE, display_name="x")
    found = [FoundFile(rel_path=p, data=d) for p, d in files]
    return MatchUnit(profile=profile, source_pack_label="lbl", files=found, icon_file=found[0])


def test_hash_independent_of_file_order():
    u1 = _unit([("a.png", b"1"), ("b.png", b"2")])
    u2 = _unit([("b.png", b"2"), ("a.png", b"1")])
    assert compute_unit_hash(u1) == compute_unit_hash(u2)


def test_hash_differs_on_content():
    assert compute_unit_hash(_unit([("a.png", b"1")])) != compute_unit_hash(_unit([("a.png", b"2")]))


def test_dedupe_store_is_per_profile():
    store = DedupeStore()
    assert store.is_duplicate("sword", "h") is False
    assert store.is_duplicate("sword", "h") is True
    # Même hash, autre profil : indépendant
    assert store.is_duplicate("bow", "h") is False
