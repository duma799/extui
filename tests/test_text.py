from __future__ import annotations

from extui.api.text import motd_to_rich, plain_text, sanitize, strip_ansi, to_rich


def test_strips_terminal_control_sequences() -> None:
    assert sanitize("\x1b[31mdanger\x1b[0m\x07") == "danger"
    assert sanitize("clear\x1b[2Jscreen") == "clearscreen"
    assert sanitize("title\x1b]0;evil\x07end") == "titleend"
    assert "\x1b" not in sanitize("\x1b[38;5;196mred\x1b[m")


def test_keeps_sgr_when_asked_but_drops_everything_else() -> None:
    value = sanitize("\x1b[31mred\x1b[2Jcleared\x1b[0m", keep_sgr=True)
    assert value == "\x1b[31mredcleared\x1b[0m"
    assert "\x1b[2J" not in value


def test_keep_sgr_does_not_corrupt_surrounding_text() -> None:
    assert sanitize("plain text", keep_sgr=True) == "plain text"
    assert sanitize("a\x1b[31mb\x1b[0mc", keep_sgr=True) == "a\x1b[31mb\x1b[0mc"
    assert sanitize("0\x1b[31m1\x1b[0m2", keep_sgr=True) == "0\x1b[31m1\x1b[0m2"
    assert sanitize("tab\there\x1b[0m", keep_sgr=True) == "tab    here\x1b[0m"


def test_plain_text_removes_minecraft_section_codes() -> None:
    assert plain_text("§7Welcome to the server of §9duma799§7!") == "Welcome to the server of duma799!"
    assert plain_text("§kobfuscated") == "obfuscated"
    assert plain_text("incomplete §") == "incomplete §"
    assert plain_text("unknown §z code") == "unknown §z code"


def test_preserves_unicode() -> None:
    assert plain_text("Привет 世界 👋") == "Привет 世界 👋"


def test_tabs_become_spaces_and_control_chars_go() -> None:
    assert sanitize("a\tb") == "a    b"
    assert sanitize("bell\x07null\x00") == "bellnull"


def test_to_rich_renders_colors_without_leaking_escapes() -> None:
    text = to_rich("§aGreen §cRed")
    assert text.plain == "Green Red"
    assert text.spans, "expected styled spans from § codes"


def test_to_rich_neutralizes_forged_escape_sequences() -> None:
    text = to_rich("safe\x1b[2Jforged")
    assert text.plain == "safeforged"


def test_motd_expands_escaped_newlines() -> None:
    assert "\n" in motd_to_rich("line one\\nline two").plain


def test_strip_ansi_is_total() -> None:
    assert strip_ansi("\x1b[1;32mx\x1b[0m\x1b]8;;http://x\x07link") == "xlink"
