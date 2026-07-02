import json

import pytest

from extractor.profile_loader import ProfileError, load_profiles


def _write(path, data):
    path.write_text(json.dumps(data), encoding="utf-8")


def test_load_simple(tmp_path):
    _write(tmp_path / "sword.json", {"id": "sword", "type": "simple", "candidates": ["diamond_sword.png"]})
    profiles = load_profiles(tmp_path)
    assert "sword" in profiles
    assert profiles["sword"].is_simple()


def test_skip_underscore_files(tmp_path):
    _write(tmp_path / "sword.json", {"id": "sword", "type": "simple", "candidates": ["x.png"]})
    _write(tmp_path / "_schema.json", {"not": "a profile"})
    profiles = load_profiles(tmp_path)
    assert set(profiles) == {"sword"}


def test_simple_requires_candidates(tmp_path):
    _write(tmp_path / "bad.json", {"id": "bad", "type": "simple"})
    with pytest.raises(ProfileError):
        load_profiles(tmp_path)


def test_group_requires_anchor_and_keys(tmp_path):
    _write(tmp_path / "g.json", {"id": "g", "type": "group"})
    with pytest.raises(ProfileError):
        load_profiles(tmp_path)


def test_wanted_ids_missing(tmp_path):
    _write(tmp_path / "sword.json", {"id": "sword", "type": "simple", "candidates": ["x.png"]})
    with pytest.raises(ProfileError):
        load_profiles(tmp_path, wanted_ids=["sword", "inexistant"])
