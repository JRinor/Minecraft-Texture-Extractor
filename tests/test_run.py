import pytest

from extractor.run import parse_combo_arg


def test_parse_combo_equals():
    assert parse_combo_arg("epee_arc=sword,bow") == ("epee_arc", ["sword", "bow"])


def test_parse_combo_colon():
    assert parse_combo_arg("pvp:sword,bow,potion") == ("pvp", ["sword", "bow", "potion"])


def test_parse_combo_strips_spaces():
    assert parse_combo_arg("x = a , b ") == ("x", ["a", "b"])


@pytest.mark.parametrize("bad", ["noseparator", "=a,b", "name=", "name="])
def test_parse_combo_invalid(bad):
    with pytest.raises(ValueError):
        parse_combo_arg(bad)
