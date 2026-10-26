"""Browser-backed replacements for ``tkinter.messagebox``."""

from __future__ import annotations

try:  # pragma: no cover - inside Pyodide
    import js as _js  # type: ignore
except ImportError:  # headless testing
    _js = None


def _ask(message: str, title: str = "") -> bool:
    text = message if not title else f"{title}\n\n{message}"
    if _js is None:
        print("[messagebox]", text)
        return False
    try:
        return bool(_js.confirm(text))
    except Exception:
        return False


def askyesno(title: str = "", message: str = "", **kwargs) -> bool:
    return _ask(message or kwargs.get("message", ""), title)


def askokcancel(title: str = "", message: str = "", **kwargs) -> bool:
    return _ask(message, title)


def showinfo(title: str = "", message: str = "", **kwargs) -> None:
    if _js is not None:
        try:
            _js.alert(message or title)
            return
        except Exception:
            pass
    print("[info]", title, message)


def showwarning(title: str = "", message: str = "", **kwargs) -> None:
    showinfo(title, message)


def showerror(title: str = "", message: str = "", **kwargs) -> None:
    showinfo(title, message)
