# SPDX-License-Identifier: Apache-2.0
"""`mousepods menu`: interactive on/off overview in the terminal (curses, no extra dependency).

Thin adapter: rows and what a key press does come from features.menu_rows / features.activate.
"""
import curses

import features

HELP = "↑↓/Tab move   Space/Enter toggle   r recenter   q quit"


def run(load_cfg, apply_update, send, is_running):
    """load_cfg() -> config dict; apply_update(dict); send(cmd) -> bool; is_running() -> bool."""
    curses.wrapper(_loop, load_cfg, apply_update, send, is_running)


def _loop(screen, load_cfg, apply_update, send, is_running):
    curses.curs_set(0)
    curses.use_default_colors()
    curses.init_pair(1, curses.COLOR_GREEN, -1)
    curses.init_pair(2, curses.COLOR_YELLOW, -1)
    screen.timeout(500)                    # redraw twice a second: picks up shortcuts and web app changes
    selected = 0
    message = ""
    while True:
        cfg = load_cfg()
        running = is_running()
        rows = features.menu_rows(cfg)
        selected %= len(rows)
        _draw(screen, rows, selected, running, cfg, message)
        key = screen.getch()
        if key in (ord("q"), 27):
            return
        if key in (curses.KEY_DOWN, ord("j"), 9):
            selected += 1
        elif key in (curses.KEY_UP, ord("k"), curses.KEY_BTAB):
            selected -= 1
        elif key in (ord(" "), 10, 13, curses.KEY_ENTER, ord("r")):
            row = rows[selected] if key != ord("r") else next(r for r in rows if r.key == "recenter")
            action = features.activate(row.key, cfg, running)
            if isinstance(action, features.ConfigUpdate):
                apply_update(action.updates)
                message = f"{row.key} changed" + ("" if running else " (applies when MousePods starts)")
            elif isinstance(action, features.Send):
                message = f"{row.key}: sent" if send(action.command) else "MousePods is not running"
            else:
                message = "start MousePods first" if row.key == "recenter" else ""


def _draw(screen, rows, selected, running, cfg, message):
    screen.erase()
    height, width = screen.getmaxyx()

    def put(y, x, text, attr=0):
        if 0 <= y < height:
            screen.addnstr(y, x, text, max(0, width - x - 1), attr)

    status = "running" if running else "not running"
    put(0, 1, "MousePods", curses.A_BOLD)
    put(0, 12, f"● {status}", curses.color_pair(1 if running else 2))
    put(0, 30, f"mouse {'PAUSED' if cfg.get('mouse_paused') else 'ACTIVE'}   mode {cfg.get('mode')}")
    for i, row in enumerate(rows):
        y = 2 + i
        pointer = "▸" if i == selected else " "
        if row.state in ("on", "off"):
            box = "[x]" if row.state == "on" else "[ ]"
        elif row.state is None:
            box = " ⟲ "
        else:
            box = f"({row.state})"
        attr = curses.A_REVERSE if i == selected else 0
        put(y, 2, f"{pointer} {box:12s} {row.key:9s}", attr | (curses.color_pair(1) if row.state == "on" else 0))
        put(y, 30, row.description, curses.A_DIM)
    put(3 + len(rows), 2, HELP, curses.A_DIM)
    if message:
        put(5 + len(rows), 2, message, curses.color_pair(2))
    screen.refresh()
