# SPDX-License-Identifier: Apache-2.0
"""Short commands: `mousepods on|off <feature>...`, `mousepods status`, `mousepods pause|resume|recenter|quit`.

Switches are written to config.json; a running controller reloads it within a second, so no restart is needed.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Feature:
    path: tuple            # (config section, key) holding the on/off flag
    description: str


FEATURES = {
    "hands": Feature(("hands", "enabled"), "camera pinch: click, drag, right click, scroll (macOS)"),
    "stem": Feature(("stem", "enabled"), "stem press: click, right click, scroll"),
    "dwell": Feature(("dwell_click", "enabled"), "click by holding still"),
    "tilt": Feature(("roll_click", "enabled"), "click by a quick head tilt"),
}


@dataclass(frozen=True)
class Toggle:
    on: bool
    names: tuple


@dataclass(frozen=True)
class Status:
    pass


@dataclass(frozen=True)
class Send:
    """A command for the running controller, same as `--send`."""
    command: str


SEND_WORDS = ("pause", "resume", "toggle", "recenter", "quit")


@dataclass(frozen=True)
class Menu:
    """The interactive overview (menu_tui.py)."""


@dataclass(frozen=True)
class Invalid:
    message: str


def _usage():
    return "usage: mousepods on|off " + "|".join(FEATURES) + " [...]   or   mousepods status"


def parse(argv):
    """Toggle | Status | Send | Invalid, or None when argv is for the normal options."""
    if len(argv) == 1 and argv[0] in SEND_WORDS:
        return Send(argv[0])
    if argv == ["menu"]:
        return Menu()
    if not argv or argv[0] not in ("on", "off", "status"):
        return None
    if argv[0] == "status":
        return Status() if len(argv) == 1 else Invalid(_usage())
    names = tuple(argv[1:])
    unknown = [n for n in names if n not in FEATURES]
    if not names or unknown:
        what = f"unknown feature: {', '.join(unknown)}. " if unknown else ""
        return Invalid(f"{what}{_usage()}")
    return Toggle(argv[0] == "on", names)


def config_updates(toggle):
    """The config.json updates for a Toggle (merged one level deep, other keys stay)."""
    updates = {}
    for name in toggle.names:
        section, key = FEATURES[name].path
        updates.setdefault(section, {})[key] = toggle.on
    return updates


def status_lines(cfg):
    lines = []
    for name, feature in FEATURES.items():
        section, key = feature.path
        state = "on" if cfg.get(section, {}).get(key) else "off"
        lines.append(f"{name:6s}  {state:7s} {feature.description}")
    lines.append(f"{'mouse':6s}  {'paused' if cfg.get('mouse_paused') else 'active':7s} "
                 "mouse control (Control+Option+P or mousepods --send toggle)")
    lines.append(f"{'mode':6s}  {cfg.get('mode', '?'):7s} souris = mouse, pointeur = pointer (Control+Option+M)")
    return lines


# --------------------------------------------------------------------------- interactive menu (menu_tui.py)
@dataclass(frozen=True)
class Row:
    key: str
    state: object          # "on" | "off" | a mode name | None for an action
    description: str


@dataclass(frozen=True)
class ConfigUpdate:
    updates: dict


MODES = ("souris", "pointeur")       # glide ("glisse") is experimental: reachable with Control+Option+M


def menu_rows(cfg):
    rows = [Row("mouse", "off" if cfg.get("mouse_paused") else "on", "mouse control (Control+Option+P)")]
    for name, feature in FEATURES.items():
        section, key = feature.path
        rows.append(Row(name, "on" if cfg.get(section, {}).get(key) else "off", feature.description))
    rows.append(Row("mode", cfg.get("mode", "souris"), "souris = mouse, pointeur = pointer (aim at the screen)"))
    rows.append(Row("recenter", None, "cursor back to the middle (Control+Option+C)"))
    return rows


def activate(key, cfg, running):
    """What Enter/Space on a row does: ConfigUpdate | Send | None."""
    if key == "mouse":
        return Send("toggle") if running else ConfigUpdate({"mouse_paused": not cfg.get("mouse_paused")})
    if key in FEATURES:
        section, flag = FEATURES[key].path
        return ConfigUpdate({section: {flag: not cfg.get(section, {}).get(flag)}})
    if key == "mode":
        current = cfg.get("mode")
        return ConfigUpdate({"mode": MODES[(MODES.index(current) + 1) % len(MODES)] if current in MODES else MODES[0]})
    if key == "recenter":
        return Send("recenter") if running else None
    return None
