"""A small, Pyodide-friendly subset of Tkinter that paints into an HTML canvas.

Only the API surface used by ``game.py`` is implemented: ``Tk``, ``Canvas``,
``Event`` and ``TclError`` plus a handful of canvas item operations.  The
canvas keeps a display list in Python and hands the whole list to JavaScript
once per animation frame, so a frame costs a single call across the
Python/JavaScript boundary.

The module also imports cleanly in a normal CPython interpreter (``js`` is
missing): in that case the rendering bridge is a no-op and ``_pump()`` lets a
test harness drive the game loop without a browser.
"""

from __future__ import annotations

import heapq
import json
import time
import traceback
from typing import Any, Callable, Optional

try:  # pragma: no cover - only true inside Pyodide
    import js as _js  # type: ignore
except ImportError:  # local CPython: headless mode
    _js = None


class TclError(Exception):
    """Mimics ``tkinter.TclError`` for code that guards against it."""


class Event:
    """Minimal stand-in for ``tkinter.Event``."""

    def __init__(self, **kwargs: Any) -> None:
        self.keysym = ""
        self.char = ""
        self.x = 0.0
        self.y = 0.0
        self.widget: Any = None
        self.__dict__.update(kwargs)


# ---------------------------------------------------------------------------
# JavaScript bridge
# ---------------------------------------------------------------------------


class _NullBridge:
    """Records the last payload so tests can inspect what would be painted."""

    last_payload: Optional[str] = None
    wavs: list = []

    def render(self, payload: str) -> None:
        _NullBridge.last_payload = payload

    def playWav(self, data: str) -> None:  # noqa: N802 - JS naming
        _NullBridge.wavs.append(len(data))

    def start(self, tick: Any) -> None:
        self.tick = tick

    def setClick(self, click: Any) -> None:  # noqa: N802
        self.click = click

    def setInput(self, handler: Any) -> None:  # noqa: N802
        self.input = handler

    def setFocusOut(self, handler: Any) -> None:  # noqa: N802
        self.focus_out = handler

    def showError(self, message: str) -> None:  # noqa: N802
        print("[tk bridge error]", message)

    def ready(self, *args: Any) -> None:
        pass

    def focus(self) -> None:
        pass


_NULL = _NullBridge()
_bridge_cache: Any = None


def _bridge() -> Any:
    global _bridge_cache
    if _bridge_cache is None:
        _bridge_cache = _NULL if _js is None else _js.TK
    return _bridge_cache


# ---------------------------------------------------------------------------
# Global state
# ---------------------------------------------------------------------------

_tk_root: Optional["Tk"] = None
_current_canvas: Optional["Canvas"] = None
_dirty = False
_after_queue: list = []  # heap of (due, seq, callback)
_after_seq = 0
_click_proxy: Any = None


def _mark_dirty() -> None:
    global _dirty
    _dirty = True


def _flush() -> None:
    global _dirty
    canvas = _current_canvas
    if not _dirty or canvas is None:
        return
    _dirty = False
    payload = json.dumps(
        canvas._serialize(), ensure_ascii=False, separators=(",", ":")
    )
    try:
        _bridge().render(payload)
    except Exception:  # pragma: no cover - rendering must never kill the game
        _report_exception()


def _report_exception() -> None:
    trace = traceback.format_exc()
    print(trace)
    try:
        _bridge().showError(trace)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Canvas items
# ---------------------------------------------------------------------------

_GEOMETRY_KINDS = {"rectangle", "oval", "line", "text"}


class Canvas:
    def __init__(
        self,
        master: Any = None,
        width: int = 640,
        height: int = 480,
        bg: str = "#ffffff",
        **kwargs: Any,
    ) -> None:
        global _current_canvas
        self.master = master
        self.width = int(width)
        self.height = int(height)
        self.bg = bg
        self._items: dict = {}
        self._order: list = []
        self._bindings: dict = {}
        self._next_id = 1
        _current_canvas = self
        _mark_dirty()

    # -- geometry -----------------------------------------------------------
    def _create(self, kind: str, coords: list, options: dict) -> int:
        iid = self._next_id
        self._next_id += 1
        options = dict(options)
        tags = options.pop("tags", ())
        if isinstance(tags, str):
            tags = (tags,)
        state = options.pop("state", "normal")
        if "font" in options:
            options["font"] = _normalize_font(options["font"])
        if "dash" in options:
            options["dash"] = [float(v) for v in options["dash"]]
        if "text" in options:
            options["text"] = str(options["text"])
        self._items[iid] = {
            "kind": kind,
            "coords": [float(v) for v in coords],
            "opts": options,
            "tags": list(tags),
            "state": state,
        }
        self._order.append(iid)
        _mark_dirty()
        return iid

    def create_rectangle(self, *args: float, **kwargs: Any) -> int:
        return self._create("rectangle", args, kwargs)

    def create_oval(self, *args: float, **kwargs: Any) -> int:
        return self._create("oval", args, kwargs)

    def create_line(self, *args: float, **kwargs: Any) -> int:
        return self._create("line", args, kwargs)

    def create_text(self, *args: float, **kwargs: Any) -> int:
        return self._create("text", args, kwargs)

    def coords(self, item: Any, *args: float) -> Any:
        entry = self._items.get(item)
        if entry is None:
            return ()
        if args:
            entry["coords"] = [float(v) for v in args]
            _mark_dirty()
        return tuple(entry["coords"])

    def itemconfig(self, item: Any, **kwargs: Any) -> None:
        entry = self._items.get(item)
        if entry is None:
            return
        for key, value in kwargs.items():
            if key == "tags":
                if isinstance(value, str):
                    value = (value,)
                entry["tags"] = list(value)
            elif key == "state":
                entry["state"] = value
            elif key == "font":
                entry["opts"]["font"] = _normalize_font(value)
            elif key == "dash":
                entry["opts"]["dash"] = [float(v) for v in value]
            elif key == "text":
                entry["opts"]["text"] = str(value)
            else:
                entry["opts"][key] = value
        _mark_dirty()

    itemconfigure = itemconfig

    def _matches(self, spec: Any) -> list:
        if spec == "all":
            return list(self._order)
        if isinstance(spec, int):
            return [spec] if spec in self._items else []
        if isinstance(spec, str) and spec.isdigit():
            iid = int(spec)
            return [iid] if iid in self._items else []
        if isinstance(spec, (tuple, list)):
            found: list = []
            for tag in spec:
                for iid in self._matches(tag):
                    if iid not in found:
                        found.append(iid)
            return found
        matches = []
        for iid in self._order:
            entry = self._items.get(iid)
            if entry and spec in entry["tags"]:
                matches.append(iid)
        return matches

    def delete(self, *specs: Any) -> None:
        for spec in specs:
            for iid in self._matches(spec):
                self._items.pop(iid, None)
                try:
                    self._order.remove(iid)
                except ValueError:
                    pass
                for key in [k for k in self._bindings if k[0] == iid]:
                    del self._bindings[key]
        _mark_dirty()

    def move(self, spec: Any, dx: float, dy: float) -> None:
        for iid in self._matches(spec):
            entry = self._items[iid]
            coords = entry["coords"]
            for index in range(0, len(coords) - 1, 2):
                coords[index] += dx
                coords[index + 1] += dy
        _mark_dirty()

    def tag_raise(self, spec: Any) -> None:
        moving = [iid for iid in self._matches(spec)]
        if not moving:
            return
        rest = [iid for iid in self._order if iid not in moving]
        self._order = rest + moving
        _mark_dirty()

    tag_lower = tag_raise

    def tag_bind(self, item: Any, sequence: str, func: Callable) -> None:
        for iid in self._matches(item):
            self._bindings[(iid, sequence)] = func

    def bbox(self, item: Any) -> tuple:
        entry = self._items.get(item)
        if entry is None:
            return ()
        coords = entry["coords"]
        if entry["kind"] == "text":
            x, y = coords[0], coords[1]
            return (x - 8, y - 8, x + 8, y + 8)
        xs = coords[0::2]
        ys = coords[1::2]
        return (min(xs), min(ys), max(xs), max(ys))

    # -- no-ops used by the game -------------------------------------------
    def pack(self, *args: Any, **kwargs: Any) -> None:
        pass

    def place(self, *args: Any, **kwargs: Any) -> None:
        pass

    def grid(self, *args: Any, **kwargs: Any) -> None:
        pass

    def config(self, **kwargs: Any) -> None:
        if "bg" in kwargs:
            self.bg = kwargs["bg"]
            _mark_dirty()

    configure = config

    def bind(self, sequence: str, func: Callable) -> None:
        pass

    def focus_set(self) -> None:
        _bridge().focus()

    focus = focus_set

    def destroy(self) -> None:
        self._items.clear()
        self._order.clear()
        self._bindings.clear()
        _mark_dirty()

    # -- serialisation ------------------------------------------------------
    def _serialize(self) -> dict:
        items = []
        for iid in self._order:
            entry = self._items.get(iid)
            if entry is None or entry["state"] == "hidden":
                continue
            kind = entry["kind"]
            coords = entry["coords"]
            opts = entry["opts"]
            if kind == "text":
                data = {
                    "i": iid,
                    "k": "t",
                    "x": coords[0] if coords else 0.0,
                    "y": coords[1] if len(coords) > 1 else 0.0,
                    "s": opts.get("text", ""),
                    "f": opts.get("fill", "#ffffff"),
                }
                font = opts.get("font")
                if font:
                    data["font"] = font
                anchor = opts.get("anchor")
                if anchor and anchor != "center":
                    data["a"] = anchor
            elif kind == "line":
                data = {
                    "i": iid,
                    "k": "l",
                    "c": coords,
                    "s": opts.get("fill", "#ffffff"),
                    "w": _num(opts.get("width", 1)),
                }
                if opts.get("dash"):
                    data["d"] = opts["dash"]
            else:
                data = {
                    "i": iid,
                    "k": "r" if kind == "rectangle" else "o",
                    "c": coords,
                }
                if opts.get("fill"):
                    data["f"] = opts["fill"]
                if opts.get("outline"):
                    data["o"] = opts["outline"]
                    data["w"] = _num(opts.get("width", 1))
                if opts.get("dash"):
                    data["d"] = opts["dash"]
            if (iid, "<Button-1>") in self._bindings:
                data["b"] = 1
            items.append(data)
        return {"w": self.width, "h": self.height, "bg": self.bg, "items": items}


def _num(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 1.0


def _normalize_font(font: Any) -> list:
    if isinstance(font, str):
        return [font, 12, ""]
    values = list(font)
    family = str(values[0]) if values else "sans-serif"
    size = 12
    if len(values) > 1:
        try:
            size = float(values[1])
        except (TypeError, ValueError):
            size = 12
    weight = ""
    if len(values) > 2 and values[2]:
        weight = str(values[2]).lower()
    return [family, size, weight]


# ---------------------------------------------------------------------------
# Tk root / event loop
# ---------------------------------------------------------------------------


class Tk:
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        global _tk_root
        self._bindings: dict = {}
        self._protocols: dict = {}
        self.title_text = ""
        self._destroyed = False
        _tk_root = self

    # -- window chrome ------------------------------------------------------
    def title(self, text: str) -> None:
        self.title_text = text

    def resizable(self, *args: Any) -> None:
        pass

    def geometry(self, *args: Any) -> None:
        pass

    def iconbitmap(self, *args: Any, **kwargs: Any) -> None:
        # No window icon in the browser.
        return None

    def protocol(self, name: str, func: Callable) -> None:
        self._protocols[name] = func

    def wm_protocol(self, name: str, func: Callable) -> None:
        self.protocol(name, func)

    def attributes(self, *args: Any, **kwargs: Any) -> None:
        pass

    def destroy(self) -> None:
        self._destroyed = True
        global _running
        _running = False

    def focus_force(self) -> None:
        _bridge().focus()

    # -- bindings -----------------------------------------------------------
    def bind(self, sequence: str, func: Optional[Callable] = None, add: Any = None) -> None:
        if func is None:
            return
        if add:
            previous = self._bindings.get(sequence)
            if previous is not None:
                def chained(event: Event, previous=previous, func=func) -> None:
                    previous(event)
                    func(event)
                self._bindings[sequence] = chained
                return
        self._bindings[sequence] = func

    def unbind(self, sequence: str, func: Any = None) -> None:
        self._bindings.pop(sequence, None)

    # -- timers -------------------------------------------------------------
    def after(self, ms: float, func: Optional[Callable] = None, *args: Any) -> int:
        global _after_seq
        _after_seq += 1
        if func is None:
            return _after_seq
        due = time.perf_counter() + max(0.0, float(ms)) / 1000.0
        heapq.heappush(_after_queue, (due, _after_seq, func, args))
        return _after_seq

    def after_cancel(self, handle: int) -> None:
        pass

    def update(self) -> None:
        _flush()

    update_idletasks = update

    def mainloop(self, n: int = 0) -> None:
        global _running, _tick_proxy
        _running = True
        _install_bridge_callbacks()
        _flush()
        try:
            try:
                from pyodide.ffi import create_proxy  # type: ignore
            except ImportError:  # plain CPython / fake js module
                def create_proxy(func: Any) -> Any:
                    return func

            _tick_proxy = create_proxy(_tick)
            _proxies.append(_tick_proxy)
            _bridge().start(_tick_proxy)
        except Exception:
            _report_exception()

    def quit(self) -> None:
        global _running
        _running = False


_running = False


_proxies: list = []
_tick_proxy: Any = None


def _install_bridge_callbacks() -> None:
    """Hand Python callables to JavaScript, keeping the proxies alive."""
    global _click_proxy
    if _js is None or _proxies:
        return
    try:
        try:
            from pyodide.ffi import create_proxy  # type: ignore
        except ImportError:  # plain CPython / fake js module
            def create_proxy(func: Any) -> Any:
                return func

        bridge = _bridge()
        _click_proxy = create_proxy(_handle_click)
        _proxies.append(_click_proxy)
        bridge.setClick(_click_proxy)

        key_proxy = create_proxy(_web_input)
        _proxies.append(key_proxy)
        bridge.setInput(key_proxy)

        focus_proxy = create_proxy(_web_focus_out)
        _proxies.append(focus_proxy)
        bridge.setFocusOut(focus_proxy)
    except Exception:
        _click_proxy = None


def _handle_click(iid: Any, x: Any = 0.0, y: Any = 0.0) -> None:
    try:
        item = int(iid)
    except (TypeError, ValueError):
        return
    canvas = _current_canvas
    if canvas is None:
        return
    callback = canvas._bindings.get((item, "<Button-1>"))
    if callback is None:
        return
    try:
        callback(Event(x=float(x), y=float(y), widget=canvas))
    except Exception:
        _report_exception()
    _flush()


def _web_input(keysym: Any, pressed: Any) -> None:
    _dispatch_key(str(keysym), bool(pressed))


def _web_focus_out(*_args: Any) -> None:
    _focus_out()


def _dispatch_key(keysym: str, pressed: bool) -> None:
    root = _tk_root
    if root is None:
        return
    candidates: list = []
    if pressed:
        candidates.append("<KeyPress-%s>" % keysym)
        if keysym in ("space", "Escape", "Return", "Tab", "BackSpace"):
            candidates.append("<%s>" % keysym)
        candidates.append("<KeyPress>")
    else:
        candidates.append("<KeyRelease-%s>" % keysym)
        candidates.append("<KeyRelease>")
    for sequence in candidates:
        callback = root._bindings.get(sequence)
        if callback is not None:
            try:
                callback(Event(keysym=keysym, widget=root))
            except Exception:
                _report_exception()
            break
    _flush()


def _focus_out() -> None:
    root = _tk_root
    if root is None:
        return
    callback = root._bindings.get("<FocusOut>")
    if callback is not None:
        try:
            callback(Event(widget=root))
        except Exception:
            _report_exception()
    _flush()


def _tick(*_args: Any) -> None:
    """Runs the timers that are due, then paints. Called once per rAF."""
    if not _running:
        return
    now = time.perf_counter()
    processed = 0
    while _after_queue and _after_queue[0][0] <= now and processed < 4:
        _, _, callback, args = heapq.heappop(_after_queue)
        processed += 1
        try:
            callback(*args)
        except Exception:
            _report_exception()
    _flush()


def _pump(rounds: int = 1) -> None:
    """Headless helper: fire the next timer(s) regardless of wall clock."""
    for _ in range(rounds):
        if not _after_queue:
            return
        _, _, callback, args = heapq.heappop(_after_queue)
        callback(*args)
    _flush()


# Names exported for the bridge/boot script.
__all__ = ["Tk", "Canvas", "Event", "TclError"]

# ``messagebox`` is imported lazily by the package __init__ of the real
# tkinter; our shim lives next to this file.
from . import messagebox  # noqa: E402,F401  (keeps ``from tkinter import messagebox`` working)
