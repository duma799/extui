from __future__ import annotations

import dataclasses

import pytest

from extui.tui.icons import ASCII, NERD, SETS, IconSet, icons, resolve_name, use


@pytest.fixture(autouse=True)
def restore_default():
    yield
    use("nerd")


def test_every_set_defines_every_glyph() -> None:
    names = {f.name for f in dataclasses.fields(IconSet)}
    for name, icon_set in SETS.items():
        for field in names:
            assert getattr(icon_set, field), f"{name} is missing {field}"


def test_nerd_glyphs_are_single_width_characters() -> None:
    for field in dataclasses.fields(IconSet):
        glyph = getattr(NERD, field.name)
        assert len(glyph) == 1, f"{field.name} must be one character, got {glyph!r}"


def test_nerd_page_glyphs_live_in_the_private_use_area() -> None:
    for page in ("overview", "console", "players", "chunky", "advancements",
                 "exploration", "structures", "waypoints", "files", "logs"):
        assert 0xE000 <= ord(getattr(NERD, page)) <= 0xF8FF, f"{page} is not a Nerd Font glyph"


def test_ascii_set_is_pure_ascii() -> None:
    for field in dataclasses.fields(IconSet):
        getattr(ASCII, field.name).encode("ascii")


def test_no_emoji_anywhere_in_either_set() -> None:
    for icon_set in SETS.values():
        for field in dataclasses.fields(IconSet):
            for char in getattr(icon_set, field.name):
                assert not (0x1F000 <= ord(char) <= 0x1FAFF), f"{field.name} still uses an emoji"


def test_resolution_order_is_environment_then_config_then_default(monkeypatch) -> None:
    monkeypatch.delenv("EXTUI_ICONS", raising=False)
    assert resolve_name(None) == "nerd"
    assert resolve_name("ascii") == "ascii"
    assert resolve_name("nonsense") == "nerd", "an unknown name falls back rather than crashing"
    monkeypatch.setenv("EXTUI_ICONS", "ascii")
    assert resolve_name(None) == "ascii"
    assert resolve_name("nerd") == "ascii", "the environment overrides config"


def test_use_switches_the_active_set(monkeypatch) -> None:
    monkeypatch.delenv("EXTUI_ICONS", raising=False)
    use("ascii")
    assert icons() is ASCII
    use("nerd")
    assert icons() is NERD
