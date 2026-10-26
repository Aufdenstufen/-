"""``winsound`` shim that forwards WAV bytes to the browser's Web Audio.

``game.py`` synthesises short WAV clips and plays them with
``winsound.PlaySound(data, SND_MEMORY | SND_ASYNC | SND_NODEFAULT)``.  The
same calls work here: the bytes are base64 encoded and handed to JavaScript,
which decodes and plays them asynchronously.
"""

from __future__ import annotations

import base64

try:  # pragma: no cover - inside Pyodide
    import js as _js  # type: ignore
except ImportError:  # headless testing
    _js = None

# Windows flag values (only used by callers as opaque bits).
SND_SYNC = 0x0000
SND_ASYNC = 0x0001
SND_NODEFAULT = 0x0002
SND_MEMORY = 0x0004
SND_LOOP = 0x0008
SND_PURGE = 0x0040
SND_FILENAME = 0x00020000

_available = _js is not None


def PlaySound(sound, flags: int = SND_FILENAME) -> None:  # noqa: N802
    if sound is None:
        return
    if isinstance(sound, (bytes, bytearray)):
        data = base64.b64encode(bytes(sound)).decode("ascii")
        if not _available:
            return
        try:
            _js.TK.playWav(data)
        except Exception:
            pass


def Beep(frequency: int = 440, duration: int = 200) -> None:  # noqa: N802
    return None


def MessageBeep(*args, **kwargs) -> None:  # noqa: N802
    return None
