"""Web entry point for the Tkinter game, running under Pyodide.

The page loads this file as Python source and executes it after the game,
the tkinter shim and the winsound shim have been written into the virtual
file system.  Its jobs are:

* restore the save file from ``localStorage`` (GitHub Pages is static, so the
  browser is the only storage we have);
* mirror every save back into ``localStorage``;
* start the Tk main loop, which hands control to the animation frame driver.
"""

import json
import os
import sys

HOME = "/home/pyodide"
if HOME not in sys.path:
    sys.path.insert(0, HOME)

SAVE_KEY = "pong_table_tennis_save_v2"
SAVE_PATH = HOME + "/save.json"
# game.py honours this variable so the save lands in the Pyodide FS.
os.environ["PONG_TABLE_TENNIS_SAVE"] = SAVE_PATH

try:  # pragma: no cover - inside a browser
    import js as _js
    from js import localStorage as _storage
except ImportError:  # headless testing
    _js = None
    _storage = None


def _restore_save() -> None:
    if _storage is None:
        return
    try:
        raw = _storage.getItem(SAVE_KEY)
    except Exception:
        return
    if not raw:
        return
    try:
        os.makedirs(os.path.dirname(SAVE_PATH), exist_ok=True)
        with open(SAVE_PATH, "w", encoding="utf-8") as handle:
            handle.write(raw)
    except OSError:
        pass


_restore_save()

import tkinter  # noqa: E402
from game import SaveManager, TableTennisGame  # noqa: E402

_original_save = SaveManager.save


def _persist_save(self) -> None:
    _original_save(self)
    if _storage is None:
        return
    try:
        _storage.setItem(SAVE_KEY, json.dumps(self.data, ensure_ascii=False))
    except Exception:
        pass


SaveManager.save = _persist_save

root = tkinter.Tk()
app = TableTennisGame(root)
root.mainloop()

if _js is not None:
    try:
        _js.TK.ready()
    except Exception:
        pass
