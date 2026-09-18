# extui

A terminal dashboard and CLI for Minecraft servers hosted on [exaroton](https://exaroton.com).

[![License: GPL v3](https://img.shields.io/badge/License-GPLv3-blue.svg)](LICENSE)

Start and stop the server, watch the live console, manage player lists, run Chunky
pregeneration, track advancements, locate biomes and structures, browse files and read
logs.

## Install

With [uv](https://docs.astral.sh/uv/):

```sh
uv tool install extui
```

Or with pipx or pip:

```sh
pipx install extui
pip install extui
```

Python 3.11 or newer is required. To install straight from source:

```sh
uv tool install git+https://github.com/duma799/extui
```

## Setup

```sh
extui login                # paste your API token
extui servers              # list the servers on the account
extui select <server-id>   # pick the default one
extui                      # open the dashboard
```

Get a token from your [exaroton account page](https://exaroton.com/account/). It is stored
in the system keyring.

On a headless server or in a container there is usually no keyring. Set the token in the
environment instead, which also takes priority over a stored one:

```sh
export EXAROTON_TOKEN=your-token
```

To try it without an account:

```sh
extui --demo
```

## Using the dashboard

Ten pages, reachable with `1`-`9` and `0`, or from the sidebar:

Overview, Console, Players, Chunky, Advancements, Exploration, Structures, Waypoints,
Files, Logs.

| Key | Action |
|---|---|
| `1`-`9`, `0` | Jump to a page |
| `Esc` | Back to the sidebar |
| `Enter` | Move into the page |
| `s` | Start or stop the server |
| `r` | Restart |
| `c` | Console |
| `F5` | Refresh the page |
| `?` | All key bindings |
| `Ctrl+P` | Command palette, including themes |
| `q` | Quit |

Letter shortcuts belong to the focused page, so while a text box has focus they get typed
instead. Press `Esc` first. Actions that still matter while typing, such as saving a
locate result, are also on `Ctrl+S`.

The sidebar shows live badges: online players, Chunky progress, unread console warnings,
saved waypoints. It collapses to icons below 100 columns.

## CLI

```sh
extui status
extui balance
extui start | stop | restart
extui console "time set day"
extui console                      # interactive, Ctrl-D to leave
extui chunky start --dimension world --center-x 0 --center-z 0 --radius 5000
extui chunky status | pause | resume | cancel
extui advancements [--player NAME_OR_UUID]
extui biomes       [--player NAME_OR_UUID]
extui locate biome minecraft:ice_spikes
extui locate structure minecraft:ancient_city
extui waypoint list | add | rename | delete
extui player associate <name> <uuid>
extui logout
```

List output is tab separated and never wrapped, so it pipes cleanly.

## Appearance

The default theme is Tokyo Night. `Ctrl+P` then "theme" switches it, and the choice is
saved.

Icons are Nerd Font glyphs. If your terminal font is not a Nerd Font you will see empty
boxes, so there is an ASCII set:

```sh
EXTUI_ICONS=ascii extui
```

Set `"icons": "ascii"` in `config.json` to make it permanent.

## Files

| What | Where |
|---|---|
| API token | System keychain, or `EXAROTON_TOKEN` |
| Settings | `<app data>/extui/config.json` |
| Waypoints | `<app data>/extui/waypoints.json` |

On macOS `<app data>` is `~/Library/Application Support`. `EXTUI_HOME` moves both files.

## Notes

The file browser is read-only. Missing advancement criteria are only computed from a
definition that was actually read, so on an unrecognised Minecraft version the Exploration
page says the biome list is unknown rather than guessing. Console text is stripped of
terminal escape sequences before it is drawn.

## Licence

GPL-3.0-or-later. See [LICENSE](LICENSE).

## Development

```sh
uv sync
uv run pytest
uv run extui --demo
```

```
extui/api/         REST client, WebSocket stream, models, text sanitizing
extui/minecraft/   Chunky, locate, advancements, waypoints
extui/tui/         Textual app, pages, dialogs, widgets, icons, stylesheet
extui/cli.py       command line front end
extui/fake.py      in-memory server for --demo and the tests
```
