/* Pyodide + canvas driver for the Tkinter table tennis game. */
(function () {
  "use strict";

  if (window.self !== window.top) {
    document.documentElement.classList.add("embedded");
  }

  var W = 1000;
  var H = 620;
  var PYODIDE_VERSION = "v0.26.4";
  var CDN_BASES = window.PONG_PYODIDE_BASES || [
    "https://cdn.jsdelivr.net/pyodide/" + PYODIDE_VERSION + "/full/",
    "https://fastly.jsdelivr.net/pyodide/" + PYODIDE_VERSION + "/full/"
  ];
  var FILES = [
    ["game.py", "game.py"],
    ["boot.py", "boot.py"],
    ["winsound.py", "winsound.py"],
    ["tkinter/__init__.py", "tkinter/__init__.py"],
    ["tkinter/messagebox.py", "tkinter/messagebox.py"]
  ];

  var stage = document.getElementById("stage");
  var canvas = document.getElementById("screen");
  var ctx = canvas.getContext("2d");
  var overlay = document.getElementById("overlay");
  var statusEl = document.getElementById("status");
  var startBtn = document.getElementById("start");
  var errorBox = document.getElementById("error");

  var dpr = 1;
  var items = [];
  var lastPayload = null;
  var clickHandler = null;
  var inputHandler = null;
  var focusOutHandler = null;
  var loopStarted = false;
  var started = false;
  var ready = false;

  /* ---------------------------------------------------------------- canvas */

  function setupCanvas() {
    dpr = Math.max(1, Math.min(2.5, window.devicePixelRatio || 1));
    canvas.width = Math.round(W * dpr);
    canvas.height = Math.round(H * dpr);
    ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.textBaseline = "middle";
    ctx.lineJoin = "miter";
    ctx.lineCap = "butt";
  }

  setupCanvas();

  var SANS_FALLBACK =
    '"Microsoft YaHei UI", "Microsoft YaHei", "PingFang SC", ' +
    '"Hiragino Sans GB", "Noto Sans SC", "Source Han Sans SC", ' +
    '"Segoe UI", "Helvetica Neue", Arial, sans-serif';
  var MONO_FALLBACK =
    '"Cascadia Mono", Consolas, "SFMono-Regular", "DejaVu Sans Mono", ' +
    'Menlo, "Courier New", monospace';

  function familyStack(family) {
    var quoted = '"' + String(family || "sans-serif").replace(/"/g, "") + '"';
    if (/mono|consolas|courier/i.test(family || "")) {
      return quoted + ", " + MONO_FALLBACK;
    }
    return quoted + ", " + SANS_FALLBACK;
  }

  function fontSizeOf(spec) {
    var size = 12;
    if (spec && spec.length > 1) size = Number(spec[1]) || 12;
    // Tk sizes are points; browsers want CSS pixels (96 dpi / 72 pt).
    return Math.max(7, Math.round(size * (4 / 3) * 4) / 4);
  }

  function fontOf(spec) {
    var family = spec && spec[0] ? spec[0] : "sans-serif";
    var weight = spec && spec.length > 2 && /bold/i.test(spec[2]) ? "700" : "400";
    return weight + " " + fontSizeOf(spec) + "px " + familyStack(family);
  }

  function render(payloadText) {
    var data = JSON.parse(payloadText);
    lastPayload = payloadText;
    items = data.items || [];
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.fillStyle = data.bg || "#101820";
    ctx.fillRect(0, 0, data.w || W, data.h || H);
    for (var i = 0; i < items.length; i += 1) {
      try {
        drawItem(items[i]);
      } catch (err) {
        /* one broken item must not stop the frame */
      }
    }
  }

  function drawItem(it) {
    if (!it) return;
    if (it.k === "t") {
      ctx.font = fontOf(it.font);
      ctx.fillStyle = it.f || "#ffffff";
      ctx.textAlign = it.a === "w" ? "left" : it.a === "e" ? "right" : "center";
      ctx.fillText(it.s == null ? "" : String(it.s), it.x, it.y);
      return;
    }
    ctx.setLineDash([]);
    if (it.k === "l") {
      var lc = it.c || [];
      if (lc.length < 4) return;
      ctx.beginPath();
      ctx.moveTo(lc[0], lc[1]);
      for (var li = 2; li + 1 < lc.length; li += 2) ctx.lineTo(lc[li], lc[li + 1]);
      ctx.strokeStyle = it.s || "#ffffff";
      ctx.lineWidth = it.w || 1;
      if (it.d && it.d.length) ctx.setLineDash(it.d);
      ctx.stroke();
      return;
    }
    var c = it.c || [];
    if (c.length < 4) return;
    if (it.k === "r") {
      var x1 = Math.min(c[0], c[2]);
      var y1 = Math.min(c[1], c[3]);
      var w = Math.abs(c[2] - c[0]);
      var h = Math.abs(c[3] - c[1]);
      if (it.f) {
        ctx.fillStyle = it.f;
        ctx.fillRect(x1, y1, w, h);
      }
      if (it.o && (it.w || 1) > 0) {
        ctx.strokeStyle = it.o;
        ctx.lineWidth = it.w || 1;
        if (it.d && it.d.length) ctx.setLineDash(it.d);
        ctx.strokeRect(x1, y1, w, h);
      }
      return;
    }
    if (it.k === "o") {
      var cx = (c[0] + c[2]) / 2;
      var cy = (c[1] + c[3]) / 2;
      var rx = Math.abs(c[2] - c[0]) / 2;
      var ry = Math.abs(c[3] - c[1]) / 2;
      if (rx <= 0 || ry <= 0) return;
      ctx.beginPath();
      ctx.ellipse(cx, cy, rx, ry, 0, 0, Math.PI * 2);
      if (it.f) {
        ctx.fillStyle = it.f;
        ctx.fill();
      }
      if (it.o) {
        ctx.strokeStyle = it.o;
        ctx.lineWidth = it.w || 1;
        if (it.d && it.d.length) ctx.setLineDash(it.d);
        ctx.stroke();
      }
    }
  }

  /* ------------------------------------------------------------- hit test */

  function hitItem(it, x, y) {
    var c = it.c || [];
    if (it.k === "r" || it.k === "o") {
      if (c.length < 4) return false;
      var left = Math.min(c[0], c[2]);
      var right = Math.max(c[0], c[2]);
      var top = Math.min(c[1], c[3]);
      var bottom = Math.max(c[1], c[3]);
      if (it.k === "r") {
        return x >= left - 2 && x <= right + 2 && y >= top - 2 && y <= bottom + 2;
      }
      var rx = (right - left) / 2 || 0.001;
      var ry = (bottom - top) / 2 || 0.001;
      var nx = (x - (left + right) / 2) / rx;
      var ny = (y - (top + bottom) / 2) / ry;
      return nx * nx + ny * ny <= 1.1;
    }
    if (it.k === "t") {
      ctx.font = fontOf(it.font);
      var width = ctx.measureText(it.s == null ? "" : String(it.s)).width;
      var height = fontSizeOf(it.font) * 1.25;
      var startX = it.a === "w" ? it.x : it.a === "e" ? it.x - width : it.x - width / 2;
      return (
        x >= startX && x <= startX + width && y >= it.y - height / 2 && y <= it.y + height / 2
      );
    }
    if (it.k === "l" && c.length >= 4) {
      for (var i = 0; i + 3 < c.length; i += 2) {
        var dx = c[i + 2] - c[i];
        var dy = c[i + 3] - c[i + 1];
        var len = dx * dx + dy * dy;
        var t = len ? ((x - c[i]) * dx + (y - c[i + 1]) * dy) / len : 0;
        t = Math.max(0, Math.min(1, t));
        var px = c[i] + t * dx;
        var py = c[i + 1] + t * dy;
        var dist = Math.hypot(x - px, y - py);
        if (dist <= (it.w || 1) + 3) return true;
      }
    }
    return false;
  }

  function hitTest(x, y) {
    for (var i = items.length - 1; i >= 0; i -= 1) {
      var it = items[i];
      if (!it || !it.b) continue;
      if (hitItem(it, x, y)) return it.i;
    }
    return null;
  }

  function pointToCanvas(ev) {
    var rect = canvas.getBoundingClientRect();
    return {
      x: ((ev.clientX - rect.left) / rect.width) * W,
      y: ((ev.clientY - rect.top) / rect.height) * H
    };
  }

  /* ---------------------------------------------------------------- audio */

  var audioCtx = null;
  var wavCache = new Map();

  function ensureAudio() {
    if (!audioCtx) {
      var Ctor = window.AudioContext || window.webkitAudioContext;
      if (Ctor) audioCtx = new Ctor();
    }
    if (audioCtx && audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }

  function decodeWav(ac, b64) {
    try {
      var binary = atob(b64);
      var bytes = new Uint8Array(binary.length);
      for (var i = 0; i < binary.length; i += 1) bytes[i] = binary.charCodeAt(i);
      return ac.decodeAudioData(bytes.buffer).catch(function () {
        return null;
      });
    } catch (err) {
      return Promise.resolve(null);
    }
  }

  function playWav(b64) {
    var ac = ensureAudio();
    if (!ac || !b64) return;
    var entry = wavCache.get(b64);
    if (!entry) {
      if (wavCache.size > 64) wavCache.clear();
      entry = decodeWav(ac, b64);
      wavCache.set(b64, entry);
    }
    entry.then(function (buffer) {
      if (!buffer || !audioCtx) return;
      try {
        var src = audioCtx.createBufferSource();
        src.buffer = buffer;
        src.connect(audioCtx.destination);
        src.start();
      } catch (err) {
        /* ignore */
      }
    });
  }

  /* ---------------------------------------------------------------- input */

  var PREVENT_KEYS = {
    space: 1, Up: 1, Down: 1, Left: 1, Right: 1, BackSpace: 1, Tab: 1, slash: 1
  };

  function keysymOf(ev) {
    var k = ev.key;
    if (!k) return "";
    if (k === " ") return "space";
    if (k === "Escape") return "Escape";
    if (k === "Enter") return "Return";
    if (k === "Tab") return "Tab";
    if (k === "Backspace") return "BackSpace";
    if (k === "ArrowUp") return "Up";
    if (k === "ArrowDown") return "Down";
    if (k === "ArrowLeft") return "Left";
    if (k === "ArrowRight") return "Right";
    if (k === "[") return "bracketleft";
    if (k === "]") return "bracketright";
    if (k === ",") return "comma";
    if (k === ".") return "period";
    if (k === "/") return "slash";
    if (k === ";") return "semicolon";
    if (k === "'") return "apostrophe";
    if (k === "\\") return "backslash";
    if (k === "-") return "minus";
    if (k === "=") return "equal";
    if (k === "`") return "grave";
    if (k === "Shift") return ev.location === 2 ? "Shift_R" : "Shift_L";
    if (k === "Control") return ev.location === 2 ? "Control_R" : "Control_L";
    if (k === "Alt") return ev.location === 2 ? "Alt_R" : "Alt_L";
    if (k === "Meta") return ev.location === 2 ? "Meta_R" : "Meta_L";
    if (k.length === 1) return k;
    return k;
  }

  window.addEventListener("keydown", function (ev) {
    if (!started || !inputHandler) return;
    if (ev.ctrlKey || ev.metaKey || ev.altKey) return;
    var sym = keysymOf(ev);
    if (!sym) return;
    if (sym === "f" || sym === "F") {
      ev.preventDefault();
      if (!ev.repeat) toggleFullscreen();
      return;
    }
    if (PREVENT_KEYS[sym]) ev.preventDefault();
    if (ev.repeat) return;
    try {
      inputHandler(sym, true);
    } catch (err) {
      showError(err);
    }
  });

  window.addEventListener("keyup", function (ev) {
    if (!started || !inputHandler) return;
    var sym = keysymOf(ev);
    if (!sym) return;
    if (PREVENT_KEYS[sym]) ev.preventDefault();
    try {
      inputHandler(sym, false);
    } catch (err) {
      showError(err);
    }
  });

  window.addEventListener("blur", function () {
    if (focusOutHandler) {
      try {
        focusOutHandler();
      } catch (err) {
        /* ignore */
      }
    }
  });

  document.addEventListener("visibilitychange", function () {
    if (document.hidden && focusOutHandler) {
      try {
        focusOutHandler();
      } catch (err) {
        /* ignore */
      }
    }
  });

  canvas.addEventListener("pointerdown", function (ev) {
    ev.preventDefault();
    if (!started) return;
    stage.focus();
    ensureAudio();
    if (!clickHandler) return;
    var p = pointToCanvas(ev);
    var id = hitTest(p.x, p.y);
    if (id === null) return;
    try {
      clickHandler(id, p.x, p.y);
    } catch (err) {
      showError(err);
    }
  });

  var hoverPending = null;
  canvas.addEventListener("pointermove", function (ev) {
    if (hoverPending) return;
    hoverPending = requestAnimationFrame(function () {
      hoverPending = null;
      if (!started) return;
      var p = pointToCanvas(ev);
      canvas.style.cursor = hitTest(p.x, p.y) === null ? "default" : "pointer";
    });
  });

  /* ----------------------------------------------------------------- loop */

  function startLoop(tick) {
    if (loopStarted) return;
    loopStarted = true;
    var last = 0;
    function frame(now) {
      if (!loopStarted) return;
      last = now;
      try {
        tick(now);
      } catch (err) {
        loopStarted = false;
        showError(err);
        return;
      }
      window.requestAnimationFrame(frame);
    }
    window.requestAnimationFrame(frame);
    // Safety net: some embeds (hidden iframes, odd headless builds) starve
    // requestAnimationFrame. Keep the game stepping at a sane rate.
    window.setInterval(function () {
      if (!loopStarted || document.hidden) return;
      var rect = stage.getBoundingClientRect();
      if (rect.width < 40 || rect.height < 40) return;
      var now = window.performance.now();
      if (now - last < 45) return;
      last = now;
      try {
        tick(now);
      } catch (err) {
        loopStarted = false;
        showError(err);
      }
    }, 25);
  }

  /* -------------------------------------------------------------------- UI */

  var statusTimer = null;
  var statusStarted = 0;

  function setStatus(text) {
    statusEl.textContent = text;
    if (!statusStarted) {
      statusStarted = Date.now();
      statusTimer = window.setInterval(function () {
        var secs = Math.round((Date.now() - statusStarted) / 1000);
        statusEl.textContent = text + "（" + secs + "s）";
      }, 1000);
    }
  }

  function clearStatusTimer() {
    if (statusTimer) window.clearInterval(statusTimer);
    statusTimer = null;
  }

  function markReady() {
    ready = true;
    clearStatusTimer();
    startBtn.disabled = false;
    startBtn.textContent = "点击开始";
    statusEl.textContent = "已就绪 · 首次进入需要点击一次以启用键盘与声音";
  }

  function showError(err) {
    var message = err && err.message ? err.message : String(err);
    console.error(err);
    clearStatusTimer();
    errorBox.hidden = false;
    errorBox.querySelector(".detail").textContent = message;
  }

  function beginGame() {
    if (!ready || started) return;
    started = true;
    ensureAudio();
    stage.focus();
    overlay.classList.add("hidden");
    window.setTimeout(function () {
      overlay.style.display = "none";
    }, 420);
  }

  startBtn.addEventListener("click", beginGame);

  function toggleFullscreen() {
    if (document.fullscreenElement) {
      document.exitFullscreen();
    } else if (stage.requestFullscreen) {
      stage.requestFullscreen().catch(function () {});
    }
  }

  canvas.addEventListener("dblclick", function (ev) {
    ev.preventDefault();
    if (started) toggleFullscreen();
  });

  window.addEventListener("resize", function () {
    var next = Math.max(1, Math.min(2.5, window.devicePixelRatio || 1));
    if (next !== dpr) {
      setupCanvas();
      if (lastPayload) render(lastPayload);
    }
  });

  /* ---------------------------------------------------------------- bridge */

  window.TK = {
    render: function (payload) {
      try {
        render(payload);
      } catch (err) {
        showError(err);
      }
    },
    playWav: function (b64) {
      playWav(b64);
    },
    start: function (tick) {
      startLoop(tick);
    },
    setClick: function (fn) {
      clickHandler = fn;
    },
    setInput: function (fn) {
      inputHandler = fn;
    },
    setFocusOut: function (fn) {
      focusOutHandler = fn;
    },
    ready: function () {
      markReady();
    },
    showError: function (message) {
      showError({ message: String(message) });
    },
    focus: function () {
      try {
        stage.focus();
      } catch (err) {
        /* ignore */
      }
    }
  };

  /* ------------------------------------------------------------- bootstrap */

  function fetchText(url) {
    return fetch(url, { cache: "no-store" }).then(function (response) {
      if (!response.ok) throw new Error("无法读取 " + url + "（HTTP " + response.status + "）");
      return response.text();
    });
  }

  function loadScript(src) {
    return new Promise(function (resolve, reject) {
      var el = document.createElement("script");
      el.src = src;
      el.async = true;
      el.onload = resolve;
      el.onerror = function () {
        reject(new Error("无法下载 " + src));
      };
      document.head.appendChild(el);
    });
  }

  function bootWith(py, base) {
    return (async function () {
      py.FS.mkdirTree("/home/pyodide/tkinter");
      setStatus("载入游戏代码…");
      for (var i = 0; i < FILES.length; i += 1) {
        var dest = FILES[i][0];
        var src = FILES[i][1];
        var text = await fetchText(src);
        py.FS.writeFile("/home/pyodide/" + dest, text, { encoding: "utf8" });
      }
      setStatus("启动游戏…");
      var bootSource = await fetchText("boot.py");
      await py.runPythonAsync(bootSource);
    })();
  }

  async function pickRuntimeBase() {
    for (var i = 0; i < CDN_BASES.length; i += 1) {
      var base = CDN_BASES[i];
      try {
        if (!window.loadPyodide) await loadScript(base + "pyodide.js");
        if (window.loadPyodide) return base;
      } catch (err) {
        console.warn("Pyodide script failed:", base, err);
      }
    }
    throw new Error(
      "无法下载 Python 运行时（cdn.jsdelivr.net 与 fastly 均不可达）。" +
      "请检查网络，或把 Pyodide 放到站点本地后修改 app.js 中的 CDN_BASES。"
    );
  }

  async function startRuntime() {
    if (location.protocol === "file:") {
      throw new Error(
        "这个页面需要通过 HTTP 打开（例如 GitHub Pages 或本地静态服务器），直接双击 file:// 无法读取游戏文件。"
      );
    }
    setStatus("下载 Python 运行时…");
    var base = await pickRuntimeBase();
    setStatus("解压 Python 标准库…");
    var py = await window.loadPyodide({ indexURL: base });
    await bootWith(py, base);
    return py;
  }

  startRuntime().catch(function (err) {
    showError(err);
    startBtn.disabled = true;
    startBtn.textContent = "加载失败";
    statusEl.textContent = "加载失败 · 请检查网络后刷新页面";
  });

  overlay.addEventListener("click", function () {
    if (ready) beginGame();
  });
})();
