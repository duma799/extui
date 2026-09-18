from __future__ import annotations

import re

from rich.text import Text

_CSI = re.compile(r"\x1b\[[0-?]*[ -/]*[@-~]")
_OSC = re.compile(r"\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)?")
_OTHER_ESC = re.compile(r"\x1b[@-Z\\-_]?")
_SGR = re.compile(r"\x1b\[[0-9;]*m")
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f]")
_SECTION = re.compile(r"§([0-9a-fk-orA-FK-OR])")

_MC_SGR = {
    "0": "0;30", "1": "0;34", "2": "0;32", "3": "0;36", "4": "0;31", "5": "0;35", "6": "0;33", "7": "0;37",
    "8": "0;90", "9": "0;94", "a": "0;92", "b": "0;96", "c": "0;91", "d": "0;95", "e": "0;93", "f": "0;97",
    "l": "1", "m": "9", "n": "4", "o": "3", "r": "0", "k": "",
}


def strip_ansi(value: str) -> str:
    value = _OSC.sub("", value)
    value = _CSI.sub("", value)
    return _OTHER_ESC.sub("", value)


def _scrub(value: str) -> str:
    return _CONTROL.sub("", strip_ansi(value).replace("\t", "    "))


def sanitize(value: str, keep_sgr: bool = False) -> str:
    if not keep_sgr:
        return _scrub(value)
    parts: list[str] = []
    position = 0
    for match in _SGR.finditer(value):
        parts.append(_scrub(value[position : match.start()]))
        parts.append(match.group(0))
        position = match.end()
    parts.append(_scrub(value[position:]))
    return "".join(parts)


def plain_text(value: str) -> str:
    return _SECTION.sub("", sanitize(value))


def to_rich(value: str) -> Text:
    safe = sanitize(value, keep_sgr=True)
    emitted = False

    def replace(match: re.Match[str]) -> str:
        nonlocal emitted
        code = _MC_SGR.get(match.group(1).lower())
        if code is None:
            return match.group(0)
        if code == "":
            return ""
        emitted = True
        return f"\x1b[{code}m"

    converted = _SECTION.sub(replace, safe)
    if emitted:
        converted += "\x1b[0m"
    return Text.from_ansi(converted)


def motd_to_rich(value: str) -> Text:
    return to_rich(value.replace("\\n", "\n"))
