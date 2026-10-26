"""Pong Table Tennis — single-file Tkinter arcade game (v2).

Controls
--------
W/S, Up/Down        move the paddle vertically
A/D, Left/Right     move the paddle forward/back along the table
Shift (hold)        sprint (drains stamina)
J                   smash
C                   chop (backspin)
K                   counterattack
E                   signature skill (needs full energy)
1 / 2 / 3           choose serve spin
W/S + A/D           aim the serve while waiting
Space               start a match / serve
P                   pause or resume
M                   mute / unmute
[ / ]               volume down / up
Esc                 return to the menu

Local 2P: arrows move P2, , . / for smash/chop/counter, L for burst.
"""

from __future__ import annotations

import array
import io
import json
import math
import os
import random
import time
import tkinter as tk
import wave
from dataclasses import dataclass
from datetime import date
from tkinter import messagebox
from typing import Callable, Optional

try:
    import winsound
except ImportError:  # pragma: no cover - Windows-only game
    winsound = None

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

WIDTH, HEIGHT = 1000, 620
FPS_MS = 16
MAX_FRAME_DT = 0.035
WIN_SCORE = 11
APP_NAME = "PongTableTennis"
SAVE_VERSION = 2

COURT_LEFT, COURT_TOP = 26, 64
COURT_RIGHT, COURT_BOTTOM = WIDTH - 26, HEIGHT - 26
PLAY_TOP, PLAY_BOTTOM = 76, HEIGHT - 38

BALL_RADIUS = 9
PADDLE_W, PADDLE_H = 18, 94

PLAYER_X_RANGE = (72.0, 300.0)
CPU_X_RANGE = (WIDTH - 300.0, WIDTH - 72.0)
PADDLE_Y_RANGE = (120.0, HEIGHT - 85.0)

BASE_MOVE_SPEED = 5.0
SPRINT_FACTOR = 1.75
SPRINT_DRAIN = 30.0
STAMINA_REGEN = 18.0
SKILL_MOVE_FACTOR = 1.22

SMASH_COST, SMASH_CD = 22.0, 2.4
CHOP_COST, CHOP_CD = 12.0, 1.2
COUNTER_COST, COUNTER_CD = 18.0, 1.8
SKILL_COST = 16.0
SKILL_ENERGY = 100.0
SMASH_POWER = 1.65

AI_BASE_SPEED = 3.1
AI_SPEED_FACTOR = 1.05
AI_TRACK_X_SPEED = 2.2

STAMINA_BAR = (40, HEIGHT - 52, 230, 14)
ENERGY_BAR = (292, HEIGHT - 52, 170, 14)
SERVE_TARGET_RANGE = (560.0, 900.0, 145.0, 490.0)

BG = "#101820"
PANEL = "#172a34"
TABLE = "#1c3943"
LINE = "#66828a"
WHITE = "#f2f5f3"
MUTED = "#a2b4ba"
GOLD = "#f4c95d"
CYAN = "#59d8c3"
RED = "#ff7474"
GREEN = "#91df9a"
PURPLE = "#b79cff"

UI_FONT = "Microsoft YaHei UI"
MONO_FONT = "Consolas"


def ui(size: int, bold: bool = False) -> tuple:
    return (UI_FONT, size, "bold") if bold else (UI_FONT, size)


def mono(size: int, bold: bool = False) -> tuple:
    return (MONO_FONT, size, "bold") if bold else (MONO_FONT, size)


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


def pct(value: float, maximum: float) -> float:
    return clamp(value / maximum, 0.0, 1.0) if maximum else 0.0


# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Player:
    name: str
    title: str
    hand: str
    speed: float
    power: float
    control: float
    stamina: int
    color: str
    trait: str
    skill: str
    skill_desc: str
    mechanic: str
    ai_aggression: float = 0.4
    ai_error: float = 0.3
    energy_gain: float = 1.0

    ai_speed: float = 1.0
    ai_spin: float = 0.0
    ai_return_speed: float = 1.0
    ai_return_vy: float = 1.0
    player_spin: float = 0.0
    smash_bonus: float = 1.0
    counter_bonus: float = 1.28
    skill_move_buff: bool = False


def _player(
    name: str,
    title: str,
    hand: str,
    speed: float,
    power: float,
    control: float,
    stamina: int,
    color: str,
    trait: str,
    skill: str,
    skill_desc: str,
    mechanic: str,
    aggression: float = 0.4,
    error: float = 0.3,
    energy: float = 1.0,
    **mods,
) -> Player:
    return Player(
        name, title, hand, speed, power, control, stamina, color,
        trait, skill, skill_desc, mechanic,
        ai_aggression=aggression, ai_error=error, energy_gain=energy,
        **mods,
    )


PLAYERS = {
    p.name: p
    for p in (
        _player(
            "新秀", "基础型球员", "右手横板", 1.00, 1.00, 1.00, 100,
            "#b8c7cc", "基础均衡，适合熟悉操作。", "稳扎稳打",
            "技能 E：稳定一击，提升本次回球控制。",
            "均衡：没有短板，适合熟悉全部操作。",
        ),
        _player(
            "马龙", "六边形战士", "右手横板", 1.02, 1.03, 1.16, 115,
            "#f4c95d", "全面稳定，控制与体力优秀。", "全台掌控",
            "技能 E：短时间提升移动与控球。",
            "相持：连续对拉会逐拍提升控制与回球质量。",
            aggression=0.45, error=0.20,
            ai_speed=1.08, ai_return_vy=0.97, counter_bonus=1.48,
            skill_move_buff=True,
        ),
        _player(
            "张继科", "爆发进攻型", "右手横板", 1.04, 1.18, 0.98, 95,
            "#ff7474", "强力进攻，爆发高但体力较少。", "霸王拧",
            "技能 E：打出高速爆冲球。",
            "搏杀：体力越低，扣杀与进攻球越重。",
            aggression=0.85, error=0.40, energy=1.10,
            ai_speed=0.94, ai_return_speed=1.08, smash_bonus=1.12,
        ),
        _player(
            "许昕", "左手直板弧圈型", "左手直板", 0.98, 1.05, 1.08, 110,
            "#59d8c3", "旋转与落点变化突出。", "魔幻弧线",
            "技能 E：大幅增强旋转与弧线。",
            "弧圈：回球附带更强侧旋，弧线更飘。",
            aggression=0.55, error=0.30,
            ai_speed=0.98, ai_spin=0.14, player_spin=0.11,
        ),
        _player(
            "樊振东", "近台力量型", "右手横板", 1.08, 1.15, 1.00, 105,
            "#b79cff", "移动快，近台力量突出。", "暴力快撕",
            "技能 E：高力量快速反击。",
            "近台：站位越靠前，回球力量越高。",
            aggression=0.75, error=0.28, energy=1.05,
            ai_speed=1.12, ai_return_speed=1.06,
        ),
        _player(
            "王楚钦", "左手快攻型", "左手横板", 1.10, 1.08, 1.02, 102,
            "#ff9d5c", "速度与衔接能力出色。", "左手突袭",
            "技能 E：提高速度并改变回球角度。",
            "突袭：大角度回球会获得额外速度。",
            aggression=0.70, error=0.32,
            ai_spin=0.10, skill_move_buff=True,
        ),
        _player(
            "林诗栋", "新生代两面弧圈", "右手横板", 1.07, 1.10, 1.00, 100,
            "#a6df73", "连续进攻，擅长快速衔接。", "连续压制",
            "技能 E：连续球加速，短时间强化移动。",
            "连压：连续击球会逐拍加速。",
            aggression=0.65, error=0.30, energy=1.05,
            skill_move_buff=True,
        ),
        _player(
            "梁靖崑", "强力对抗型", "右手横板", 0.96, 1.20, 0.96, 108,
            "#e78cc5", "单板力量大，移动稍慢。", "重炮轰击",
            "技能 E：消耗体力打出极重一击。",
            "重炮：扣杀命中后会短暂压制对手移动。",
            aggression=0.80, error=0.38,
        ),
        _player(
            "陈梦", "稳健相持型", "右手横板", 1.00, 1.02, 1.14, 112,
            "#82b7ff", "相持稳定，落点控制优秀。", "防线固守",
            "技能 E：短时间提升防守与控球。",
            "稳固：体力较低时控球和防守反而提升。",
            aggression=0.30, error=0.20,
            ai_return_vy=0.88, counter_bonus=1.48, skill_move_buff=True,
        ),
        _player(
            "孙颖莎", "快速衔接型", "右手横板", 1.12, 1.04, 1.08, 100,
            "#ff8e9e", "反应快，台内衔接灵活。", "闪电衔接",
            "技能 E：瞬间提升移动速度并快速回球。",
            "衔接：每次击球额外积攒技能能量。",
            aggression=0.60, error=0.25, energy=1.25,
            skill_move_buff=True,
        ),
        _player(
            "王曼昱", "全面防反型", "右手横板", 1.03, 1.06, 1.12, 115,
            "#8bd8d1", "防守覆盖面大，反击稳定。", "韧性反击",
            "技能 E：防守反击的威力更强。",
            "防反：防反命中后回复少量体力。",
            aggression=0.35, error=0.22,
            ai_return_vy=0.88, counter_bonus=1.48, skill_move_buff=True,
        ),
        _player(
            "伊藤美诚", "节奏变化型", "右手横板", 1.05, 1.03, 1.06, 98,
            "#d6a4ff", "节奏变化多，善于扰乱对手。", "节奏扰动",
            "技能 E：回球附加强烈的节奏变化。",
            "节奏：每三次击球会改变旋转和节奏。",
            aggression=0.65, error=0.35, energy=1.05,
            ai_spin=0.10,
        ),
    )
}


QUOTES = {
    "新秀": ("稳住，这一板我能接住。", "基础扎实，就是最好的天赋。"),
    "马龙": ("全台，都在我的掌控之中。", "六边形，没有短板。"),
    "张继科": ("这一板，我要直接打穿。", "藏獒出笼，绝不回头。"),
    "许昕": ("看这球的弧线。", "人民艺术家，从不按常理出牌。"),
    "樊振东": ("近台，就是我的领域。", "力量，是最直接的语言。"),
    "王楚钦": ("左手，也可以撕开角度。", "速度会替我说话。"),
    "林诗栋": ("一板接一板，别想停。", "新生代，不怕多拍。"),
    "梁靖崑": ("这一炮，你接得住吗？", "重炮之下，没有侥幸。"),
    "陈梦": ("稳住，机会会来的。", "防线，也是一种进攻。"),
    "孙颖莎": ("衔接再快一点。", "小魔王，随时上线。"),
    "王曼昱": ("防回去，再反击。", "韧性，就是我的底牌。"),
    "伊藤美诚": ("节奏，变了。", "别猜我下一板。"),
}


@dataclass(frozen=True)
class Difficulty:
    name: str
    ai_scale: float
    aim_noise: float
    prediction: float


DIFFICULTIES = {
    d.name: d
    for d in (
        Difficulty("简单", 0.70, 34.0, 0.0),
        Difficulty("普通", 1.00, 15.0, 0.0),
        Difficulty("困难", 1.22, 0.0, 0.25),
        Difficulty("专家", 1.42, 0.0, 0.70),
    )
}
DIFF_ORDER = ["简单", "普通", "困难", "专家"]


@dataclass(frozen=True)
class ServeStyle:
    name: str
    speed: float
    angle: float
    spin: float


SERVES = {
    s.name: s
    for s in (
        ServeStyle("普通发球", 6.0, 0.34, 0.0),
        ServeStyle("旋转发球", 5.2, 0.34, 0.19),
        ServeStyle("急长球", 8.2, 0.16, 0.0),
    )
}
SERVE_KEYS = {"1": "普通发球", "2": "旋转发球", "3": "急长球"}


@dataclass(frozen=True)
class Challenge:
    cid: str
    name: str
    desc: str
    opponent: str
    difficulty: str
    win_score: int
    time_limit: float
    stamina_scale: float
    coins: int
    tickets: int
    shards: int
    tip: str


CHALLENGES = {
    c.cid: c
    for c in (
        Challenge(
            "blitz", "闪电战", "90 秒内先到 7 分", "王楚钦", "困难",
            7, 90.0, 1.0, 80, 1, 0, "节奏很快：多用急长球和扣杀抢分。",
        ),
        Challenge(
            "iron", "体力极限", "体力上限 60%，先到 7 分", "马龙", "困难",
            7, 0.0, 0.60, 60, 0, 30, "体力很紧：减少冲刺，靠落点得分。",
        ),
        Challenge(
            "expert", "专家试炼", "先到 5 分，对手为专家 AI", "樊振东", "专家",
            5, 0.0, 1.0, 100, 1, 20, "容错很低：抓住每一个发球轮。",
        ),
    )
}
CHALLENGE_ORDER = ["blitz", "iron", "expert"]


@dataclass(frozen=True)
class MatchConfig:
    mode: str = "quick"
    opponent: str = "新秀"
    difficulty: str = "普通"
    best_of: int = 3
    win_score: int = WIN_SCORE
    time_limit: float = 0.0
    stamina_scale: float = 1.0
    local_two_player: bool = False
    training_type: str = ""
    challenge_id: str = ""
    tournament_round: int = -1


TRAINING_INFO = {
    "serve": (
        "发球练习", "自由选择旋转与落点，连续发球找手感。",
        "1/2/3 选旋转 · W/S/A/D 调落点 · 空格发球",
    ),
    "receive": (
        "接发球练习", "对手连续发球，练习判断旋转与回球。",
        "等对手发球，用 J/C/K 处理不同来球",
    ),
    "skill": (
        "技能练习", "能量保持满值，反复练习专属技能。",
        "E 释放技能 · 观察球路与落点",
    ),
}

DAILY_TASKS = (
    {"id": "wins", "label": "赢下 2 场比赛", "target": 2,
     "coins": 60, "tickets": 0, "shards": 0},
    {"id": "smashes", "label": "完成 10 次扣杀", "target": 10,
     "coins": 0, "tickets": 1, "shards": 0},
    {"id": "rally", "label": "单回合达到 10 拍", "target": 10,
     "coins": 0, "tickets": 0, "shards": 25},
)
WEEKLY_TASK = {
    "id": "wins", "label": "本周赢下 8 场比赛", "target": 8,
    "coins": 150, "tickets": 2, "shards": 0,
}
MASTERY_THRESHOLDS = (0, 40, 100, 180, 300, 450)
MASTERY_TITLES = ("初出茅庐", "渐入佳境", "球场好手", "王牌选手", "传奇球星")

GACHA_COIN_COST = 80
SHARD_PLAYER_COST = 150
DUPLICATE_SHARDS = 20


def mastery_level(xp: int) -> int:
    level = 1
    for index, need in enumerate(MASTERY_THRESHOLDS[1:], start=2):
        if xp >= need:
            level = index
    return min(level, 5)


def mastery_progress(xp: int) -> tuple:
    level = mastery_level(xp)
    current = MASTERY_THRESHOLDS[level - 1]
    if level >= 5:
        return level, 1.0, 0
    target = MASTERY_THRESHOLDS[level]
    span = max(1, target - current)
    return level, clamp((xp - current) / span, 0.0, 1.0), target - xp


# ---------------------------------------------------------------------------
# Save data
# ---------------------------------------------------------------------------


def default_save() -> dict:
    return {
        "version": SAVE_VERSION,
        "unlocked": ["新秀"],
        "tickets": 1,
        "coins": 120,
        "shards": 0,
        "trophies": 0,
        "selected": "新秀",
        "opponent": "新秀",
        "difficulty": "普通",
        "volume": 0.7,
        "muted": False,
        "stats": {
            "matches": 0, "wins": 0, "losses": 0,
            "best_rally": 0, "perfects": 0, "smashes": 0, "skills": 0,
        },
        "mastery": {},
        "daily": {
            "date": "", "progress": {"wins": 0, "smashes": 0, "rally": 0},
            "claimed": [],
        },
        "weekly": {"week": "", "wins": 0, "claimed": False},
        "daily_challenge": {"date": "", "claimed": False},
        "challenge_wins": {},
        "tournament": None,
    }


def default_save_path() -> str:
    override = os.environ.get("PONG_TABLE_TENNIS_SAVE")
    if override:
        return os.path.abspath(override)
    base = os.environ.get("APPDATA")
    if not base:
        base = os.path.expanduser("~")
    return os.path.join(base, APP_NAME, "save.json")


class SaveManager:
    def __init__(self, path: Optional[str] = None) -> None:
        self.path = path or default_save_path()
        self.fallback_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "save.json"
        )
        self.data = self._load()
        self._normalize()

    def _load(self) -> dict:
        data = default_save()
        try:
            with open(self.path, "r", encoding="utf-8") as handle:
                loaded = json.load(handle)
            if isinstance(loaded, dict):
                for key, value in data.items():
                    if key not in loaded:
                        loaded[key] = value
                data = loaded
        except (OSError, ValueError, TypeError):
            pass
        return data

    def _normalize(self) -> None:
        data = self.data
        defaults = default_save()
        valid = set(PLAYERS)
        unlocked = [
            name for name in data.get("unlocked", []) if name in valid
        ] if isinstance(data.get("unlocked"), list) else []
        if "新秀" not in unlocked:
            unlocked.insert(0, "新秀")
        data["unlocked"] = list(dict.fromkeys(unlocked))
        if data.get("selected") not in data["unlocked"]:
            data["selected"] = "新秀"
        if data.get("opponent") not in valid:
            data["opponent"] = "新秀"
        if data.get("difficulty") not in DIFFICULTIES:
            data["difficulty"] = "普通"
        for key, value in defaults.items():
            data.setdefault(key, value)
        for key, value in defaults["stats"].items():
            if not isinstance(data.get("stats"), dict):
                data["stats"] = dict(defaults["stats"])
                break
            data["stats"].setdefault(key, value)
        for key in ("mastery", "challenge_wins"):
            if not isinstance(data.get(key), dict):
                data[key] = {}
        daily = data.get("daily")
        if not isinstance(daily, dict):
            daily = dict(defaults["daily"])
            data["daily"] = daily
        daily.setdefault("date", "")
        daily.setdefault("claimed", [])
        if not isinstance(daily.get("claimed"), list):
            daily["claimed"] = []
        progress = daily.get("progress")
        if not isinstance(progress, dict):
            progress = {"wins": 0, "smashes": 0, "rally": 0}
            daily["progress"] = progress
        for key in ("wins", "smashes", "rally"):
            progress.setdefault(key, 0)
        weekly = data.get("weekly")
        if not isinstance(weekly, dict):
            weekly = dict(defaults["weekly"])
            data["weekly"] = weekly
        weekly.setdefault("week", "")
        weekly.setdefault("wins", 0)
        weekly.setdefault("claimed", False)
        challenge_day = data.get("daily_challenge")
        if not isinstance(challenge_day, dict):
            data["daily_challenge"] = dict(defaults["daily_challenge"])
        else:
            challenge_day.setdefault("date", "")
            challenge_day.setdefault("claimed", False)
        tournament = data.get("tournament")
        if tournament is not None:
            valid_tournament = (
                isinstance(tournament, dict)
                and isinstance(tournament.get("players"), list)
                and len(tournament["players"]) in (2, 4, 8)
                and all(name in valid for name in tournament["players"])
                and isinstance(tournament.get("player_slot"), int)
                and 0 <= tournament["player_slot"] < len(tournament["players"])
                and isinstance(tournament.get("round"), int)
                and 0 <= tournament["round"] <= 2
            )
            if not valid_tournament:
                data["tournament"] = None
        data["version"] = SAVE_VERSION
        try:
            data["volume"] = clamp(float(data.get("volume", 0.7)), 0.0, 1.0)
        except (TypeError, ValueError):
            data["volume"] = 0.7
        data["muted"] = bool(data.get("muted", False))
        data["tickets"] = max(0, int(data.get("tickets", 0)))
        data["coins"] = max(0, int(data.get("coins", 0)))
        data["shards"] = max(0, int(data.get("shards", 0)))
        data["trophies"] = max(0, int(data.get("trophies", 0)))

    def save(self) -> None:
        payload = json.dumps(self.data, ensure_ascii=False, indent=2)
        for path in (self.path, self.fallback_path):
            try:
                directory = os.path.dirname(path)
                if directory:
                    os.makedirs(directory, exist_ok=True)
                temporary = path + ".tmp"
                with open(temporary, "w", encoding="utf-8") as handle:
                    handle.write(payload)
                os.replace(temporary, path)
                if path != self.path:
                    self.path = path
                return
            except OSError:
                continue

    # convenience ---------------------------------------------------------
    def unlock(self, name: str) -> bool:
        if name in self.data["unlocked"]:
            return False
        self.data["unlocked"].append(name)
        return True

    def is_unlocked(self, name: str) -> bool:
        return name in self.data["unlocked"]

    def grant(self, coins: int = 0, tickets: int = 0, shards: int = 0) -> None:
        self.data["coins"] = max(0, int(self.data["coins"]) + coins)
        self.data["tickets"] = max(0, int(self.data["tickets"]) + tickets)
        self.data["shards"] = max(0, int(self.data["shards"]) + shards)

    def add_mastery(self, name: str, xp: int) -> None:
        if name not in PLAYERS or xp <= 0:
            return
        entry = self.data["mastery"].setdefault(
            name, {"xp": 0, "matches": 0, "wins": 0}
        )
        entry["xp"] = int(entry.get("xp", 0)) + int(xp)

    def mastery_entry(self, name: str) -> dict:
        return self.data["mastery"].get(
            name, {"xp": 0, "matches": 0, "wins": 0}
        )


# ---------------------------------------------------------------------------
# Sound
# ---------------------------------------------------------------------------


class SoundBank:
    SAMPLE_RATE = 22050

    def __init__(self, volume: float = 0.7) -> None:
        self.volume = clamp(volume, 0.0, 1.0)
        self.enabled = winsound is not None and os.environ.get(
            "PONG_TABLE_TENNIS_MUTE"
        ) != "1"
        self._sounds: dict = {}
        self._build()

    def _samples(
        self,
        freq: float,
        duration: float,
        amp: float,
        end_freq: Optional[float] = None,
        noise: float = 0.0,
    ) -> array.array:
        count = max(1, int(self.SAMPLE_RATE * duration))
        result = array.array("h")
        phase = 0.0
        for index in range(count):
            ratio = index / count
            current = freq if end_freq is None else freq + (end_freq - freq) * ratio
            phase += 2.0 * math.pi * current / self.SAMPLE_RATE
            envelope = (1.0 - ratio) ** 1.8
            value = math.sin(phase) * amp
            if noise:
                value += random.uniform(-1.0, 1.0) * noise
            value *= envelope * self.volume
            result.append(int(clamp(value, -1.0, 1.0) * 32767))
        return result

    def _wav(self, samples: array.array) -> bytes:
        buffer = io.BytesIO()
        with wave.open(buffer, "wb") as handle:
            handle.setnchannels(1)
            handle.setsampwidth(2)
            handle.setframerate(self.SAMPLE_RATE)
            handle.writeframes(samples.tobytes())
        return buffer.getvalue()

    def _sequence(self, parts: tuple) -> bytes:
        samples = array.array("h")
        gap = array.array("h", [0] * int(self.SAMPLE_RATE * 0.008))
        for freq, duration, amp, end_freq, noise in parts:
            samples.extend(self._samples(freq, duration, amp, end_freq, noise))
            samples.extend(gap)
        return self._wav(samples)

    def _build(self) -> None:
        if not self.enabled:
            return
        make = self._sequence
        self._sounds = {
            "hit": make(((720, 0.055, 0.35, 520, 0.05),)),
            "perfect": make(
                ((1100, 0.045, 0.30, 1100, 0.0), (1500, 0.07, 0.28, 1500, 0.0))
            ),
            "smash": make(((190, 0.16, 0.55, 55, 0.28),)),
            "chop": make(((430, 0.085, 0.28, 300, 0.04),)),
            "counter": make(((600, 0.09, 0.38, 900, 0.03),)),
            "skill": make(
                ((440, 0.07, 0.25, 440, 0.0), (660, 0.07, 0.30, 660, 0.0),
                 (880, 0.13, 0.30, 880, 0.0))
            ),
            "score": make(
                ((660, 0.07, 0.30, 660, 0.0), (880, 0.10, 0.30, 880, 0.0))
            ),
            "win": make(
                ((523, 0.09, 0.28, 523, 0.0), (659, 0.09, 0.28, 659, 0.0),
                 (784, 0.09, 0.28, 784, 0.0), (1047, 0.22, 0.32, 1047, 0.0))
            ),
            "lose": make(
                ((392, 0.11, 0.28, 392, 0.0), (330, 0.11, 0.28, 330, 0.0),
                 (262, 0.22, 0.28, 262, 0.0))
            ),
            "ui": make(((900, 0.025, 0.18, 900, 0.0),)),
            "serve": make(((520, 0.035, 0.20, 520, 0.0),)),
            "break": make(
                ((700, 0.05, 0.22, 700, 0.0), (500, 0.06, 0.22, 500, 0.0))
            ),
        }

    def set_volume(self, volume: float) -> None:
        volume = clamp(volume, 0.0, 1.0)
        if abs(volume - self.volume) < 0.001:
            return
        self.volume = volume
        self._build()

    def play(self, name: str) -> None:
        if not self.enabled or self.volume <= 0:
            return
        data = self._sounds.get(name)
        if not data:
            return
        try:
            winsound.PlaySound(
                data,
                winsound.SND_MEMORY | winsound.SND_ASYNC | winsound.SND_NODEFAULT,
            )
        except RuntimeError:
            pass


# ---------------------------------------------------------------------------
# Particles
# ---------------------------------------------------------------------------


@dataclass
class Particle:
    item: int
    x: float
    y: float
    vx: float
    vy: float
    life: float
    max_life: float
    size: float
    gravity: float


class ParticleSystem:
    def __init__(self, canvas: tk.Canvas) -> None:
        self.canvas = canvas
        self.items: list = []
        self.limit = 160

    def _new(
        self, x: float, y: float, color: str, size: float, life: float,
        vx: float, vy: float, gravity: float,
    ) -> None:
        item = self.canvas.create_oval(
            x - size, y - size, x + size, y + size,
            fill=color, outline="", tags=("fx",),
        )
        self.items.append(Particle(item, x, y, vx, vy, life, life, size, gravity))
        if len(self.items) > self.limit:
            old = self.items.pop(0)
            self.canvas.delete(old.item)

    def trail(self, x: float, y: float, color: str) -> None:
        self._new(x, y, color, 3.5, 0.18, 0.0, 0.0, 0.0)

    def burst(
        self, x: float, y: float, color: str, count: int = 8,
        speed: float = 3.5, size: float = 3.5, life: float = 0.45,
        gravity: float = 0.06,
    ) -> None:
        for _ in range(count):
            angle = random.uniform(0, math.tau)
            magnitude = random.uniform(0.35, 1.0) * speed
            self._new(
                x, y, color, size * random.uniform(0.6, 1.3),
                life * random.uniform(0.7, 1.2),
                math.cos(angle) * magnitude, math.sin(angle) * magnitude,
                gravity,
            )

    def confetti(self, x: float, y: float) -> None:
        colors = (GOLD, CYAN, GREEN, RED, PURPLE, WHITE)
        for _ in range(30):
            angle = random.uniform(-math.pi, 0.0)
            magnitude = random.uniform(2.0, 6.0)
            self._new(
                x, y, random.choice(colors),
                random.uniform(2.0, 4.5), random.uniform(0.7, 1.3),
                math.cos(angle) * magnitude, math.sin(angle) * magnitude,
                0.14,
            )

    def update(self, dt: float) -> None:
        frame = dt * 60.0
        for particle in list(self.items):
            particle.life -= dt
            if particle.life <= 0:
                self.canvas.delete(particle.item)
                self.items.remove(particle)
                continue
            particle.vy += particle.gravity * frame
            particle.x += particle.vx * frame
            particle.y += particle.vy * frame
            ratio = particle.life / particle.max_life
            size = max(0.8, particle.size * ratio)
            self.canvas.coords(
                particle.item, particle.x - size, particle.y - size,
                particle.x + size, particle.y + size,
            )

    def clear(self, delete_items: bool = True) -> None:
        if delete_items and self.canvas:
            self.canvas.delete("fx")
        self.items.clear()


# ---------------------------------------------------------------------------
# Game
# ---------------------------------------------------------------------------


class TableTennisGame:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title("PONG TABLE TENNIS | 球员收集计划")
        root.resizable(False, False)
        icon_path = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "app.ico"
        )
        if os.path.exists(icon_path):
            try:
                root.iconbitmap(default=icon_path)
            except tk.TclError:
                pass
        self.canvas = tk.Canvas(
            root, width=WIDTH, height=HEIGHT, bg=BG, highlightthickness=0
        )
        self.canvas.pack()

        self.save = SaveManager()
        self.data = self.save.data
        self._ensure_periods()
        self.selected = self.data["selected"]
        self.opponent = self.data["opponent"]
        self.difficulty = self.data["difficulty"]
        self.muted = bool(self.data["muted"])
        self.sound = SoundBank(0.0 if self.muted else float(self.data["volume"]))
        self.particles = ParticleSystem(self.canvas)

        self.screen = "menu"
        self.keys: set = set()
        self._scene: Optional[dict] = None
        self.message = ""
        self._message_timer = 0.0
        self.last_draw: Optional[str] = None
        self.last_draw_duplicate = False
        self.last_draw_shards = 0

        self.serve_style = "普通发球"
        self.match_config = MatchConfig()
        self.last_result: Optional[dict] = None

        # Match state, initialised fully by start_match().
        self.player_score = 0
        self.cpu_score = 0
        self.player_games = 0
        self.cpu_games = 0
        self.games_to_win = 2
        self.win_score = WIN_SCORE
        self.player_x = self.player_y = 0.0
        self.cpu_x = self.cpu_y = 0.0
        self.ball_x = self.ball_y = 0.0
        self.ball_vx = self.ball_vy = self.ball_spin = 0.0
        self.stamina = 100.0
        self.max_stamina = 100.0
        self.skill_energy = 0.0
        self.p2_stamina = 100.0
        self.p2_max_stamina = 100.0
        self.p2_energy = 0.0
        self.smash_cooldown = 0.0
        self.chop_cooldown = 0.0
        self.counter_cooldown = 0.0
        self.p2_smash_cooldown = 0.0
        self.p2_chop_cooldown = 0.0
        self.p2_counter_cooldown = 0.0
        self.skill_flash = 0.0
        self.skill_buff = 0.0
        self.smash_flash = 0.0
        self.p2_flash = 0.0
        self.timing_text = ""
        self.timing_timer = 0.0
        self.timing_color = GOLD
        self.paused = False
        self.serve_pending = True
        self.serve_owner = "player"
        self.serve_wait = 0.0
        self.serve_target_x = 740.0
        self.serve_target_y = HEIGHT / 2
        self.game_break = 0.0
        self.break_text = ""
        self.time_left = 0.0
        self.match_time = 0.0
        self.rally = 0
        self.max_rally = 0
        self.volley_best = 0
        self.smash_count = 0
        self.perfect_count = 0
        self.cpu_stun = 0.0
        self.shake = 0.0
        self._shake_offset = (0.0, 0.0)
        self.match_over = False
        self.training_type = ""
        self.local_two_player = False
        self._trail_tick = 0
        self.last_hit_side = ""
        self.receiving_serve = False
        self.slowmo = 0.0

        self._bind_events()
        self.show("menu")
        self.last_tick = time.perf_counter()
        root.after(FPS_MS, self.loop)

    # -- helpers ------------------------------------------------------------

    def _bind_events(self) -> None:
        self.root.bind("<KeyPress>", self.key_down)
        self.root.bind("<KeyRelease>", self.key_up)
        self.root.bind("<FocusOut>", self.clear_keys)
        self.root.bind("<space>", self.on_space)
        self.root.bind("<Escape>", self.on_escape)
        self.root.bind("<KeyPress-p>", self.on_pause)
        self.root.bind("<KeyPress-P>", self.on_pause)
        self.root.bind("<KeyPress-m>", self.on_mute)
        self.root.bind("<KeyPress-M>", self.on_mute)
        self.root.bind("<KeyPress-bracketleft>", self.on_volume_down)
        self.root.bind("<KeyPress-bracketright>", self.on_volume_up)
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def _ensure_periods(self) -> None:
        today = date.today()
        daily = self.data["daily"]
        if daily.get("date") != today.isoformat():
            daily["date"] = today.isoformat()
            daily["progress"] = {"wins": 0, "smashes": 0, "rally": 0}
            daily["claimed"] = []
        weekly = self.data["weekly"]
        iso = today.isocalendar()
        week_key = f"{iso[0]}-W{iso[1]:02d}"
        if weekly.get("week") != week_key:
            weekly["week"] = week_key
            weekly["wins"] = 0
            weekly["claimed"] = False
        if self.data["daily_challenge"].get("date") != today.isoformat():
            self.data["daily_challenge"] = {
                "date": today.isoformat(), "claimed": False,
            }

    def _toast(self, text: str, seconds: float = 1.6) -> None:
        self.message = text
        self._message_timer = seconds

    def _bump_stat(self, key: str, amount: int = 1) -> None:
        self.data["stats"][key] = int(self.data["stats"].get(key, 0)) + amount

    def _bump_daily(self, key: str, amount: int = 1) -> None:
        progress = self.data["daily"]["progress"]
        if key == "rally":
            progress[key] = max(int(progress.get(key, 0)), amount)
        else:
            progress[key] = int(progress.get(key, 0)) + amount

    def _mastery_entry(self, name: str) -> dict:
        return self.data["mastery"].setdefault(
            name, {"xp": 0, "matches": 0, "wins": 0}
        )

    def _record_mastery(self, name: str, won: bool) -> None:
        entry = self._mastery_entry(name)
        entry["matches"] = int(entry.get("matches", 0)) + 1
        if won:
            entry["wins"] = int(entry.get("wins", 0)) + 1
        entry["xp"] = int(entry.get("xp", 0)) + (26 if won else 10)
        if self.perfect_count:
            entry["xp"] += min(12, self.perfect_count)
        if self.smash_count:
            entry["xp"] += min(8, self.smash_count // 2)

    def set_selected(self, name: str) -> None:
        if not self.save.is_unlocked(name):
            return
        t = self.data.get("tournament")
        if t and t.get("active") and name != t.get("player", name):
            self._toast("锦标赛进行中，不能更换参赛球员")
            self.draw()
            return
        self.selected = name
        self.data["selected"] = name
        self.save.save()
        self.draw()

    def set_opponent(self, name: str) -> None:
        if name not in PLAYERS:
            return
        self.opponent = name
        self.data["opponent"] = name
        self.save.save()
        self.draw()

    def cycle_opponent(self, step: int) -> None:
        names = list(PLAYERS)
        index = (names.index(self.opponent) + step) % len(names)
        self.set_opponent(names[index])

    def set_difficulty(self, level: str) -> None:
        if level not in DIFFICULTIES:
            return
        self.difficulty = level
        self.data["difficulty"] = level
        self.save.save()
        self.draw()

    def toggle_mute(self) -> None:
        self.muted = not self.muted
        self.data["muted"] = self.muted
        self.sound.set_volume(0.0 if self.muted else float(self.data["volume"]))
        self.save.save()

    def on_mute(self, _event: Optional[tk.Event] = None) -> str:
        self.toggle_mute()
        self._toast("音效已关闭" if self.muted else "音效已开启")
        self.draw()
        return "break"

    def adjust_volume(self, delta: float) -> None:
        volume = clamp(float(self.data["volume"]) + delta, 0.0, 1.0)
        self.data["volume"] = volume
        if volume > 0:
            self.muted = False
            self.data["muted"] = False
        self.sound.set_volume(0.0 if self.muted else volume)
        self.save.save()
        self._toast(f"音效音量：{int(volume * 100)}%")
        self.draw()

    def on_volume_down(self, _event: Optional[tk.Event] = None) -> str:
        self.adjust_volume(-0.1)
        return "break"

    def on_volume_up(self, _event: Optional[tk.Event] = None) -> str:
        self.adjust_volume(0.1)
        return "break"

    # -- navigation ---------------------------------------------------------

    def show(self, screen: str) -> None:
        self.screen = screen
        self.keys.clear()
        self._scene = None
        self.particles.clear()
        self._reset_shake(force=True)
        if screen in ("menu", "modes", "gacha", "roster", "tasks",
                      "shop", "help", "tournament", "challenge",
                      "training", "result"):
            self.message = ""
            self._message_timer = 0.0
        if screen == "gacha":
            self.last_draw = None
            self.last_draw_duplicate = False
            self.last_draw_shards = 0
        self.draw()

    def to_menu(self) -> None:
        self.paused = False
        self.show("menu")

    def on_close(self) -> None:
        self.save.save()
        self.root.destroy()

    def on_space(self, _event: Optional[tk.Event] = None) -> str:
        if self.screen == "game":
            if not self.paused and self.serve_pending and self.serve_owner == "player":
                if self.game_break <= 0:
                    self.launch_ball("player")
        elif self.screen == "menu":
            self.start_quick_match()
        elif self.screen == "result":
            self.result_primary()
        return "break"

    def on_escape(self, _event: Optional[tk.Event] = None) -> str:
        if self.screen == "game":
            if self.paused:
                self.to_menu()
            else:
                self.paused = True
                self.draw()
        elif self.screen != "menu":
            self.to_menu()
        return "break"

    def on_pause(self, _event: Optional[tk.Event] = None) -> str:
        if self.screen == "game" and self.game_break <= 0:
            self.paused = not self.paused
            if self.paused:
                self.sound.play("ui")
            self.draw()
        return "break"

    # -- input --------------------------------------------------------------

    def key_down(self, event: tk.Event) -> None:
        key = event.keysym.lower()
        if key not in self.keys:
            if key == "j":
                self.try_smash()
            elif key == "c":
                self.try_chop()
            elif key == "k":
                self.try_counterattack()
            elif key == "e":
                self.try_player_skill()
            elif key == "comma":
                self.try_p2_smash()
            elif key == "period":
                self.try_p2_chop()
            elif key == "slash":
                self.try_p2_counter()
            elif key == "l":
                self.try_p2_skill()
            elif (
                key in SERVE_KEYS
                and self.screen == "game"
                and self.serve_pending
                and self.serve_owner == "player"
                and not self.paused
            ):
                self.serve_style = SERVE_KEYS[key]
                self._toast(f"发球旋转：{self.serve_style}", 0.9)
            elif key == "h" and self.screen in ("menu", "modes"):
                self.show("help")
        self.keys.add(key)

    def key_up(self, event: tk.Event) -> None:
        self.keys.discard(event.keysym.lower())

    def clear_keys(self, _event: Optional[tk.Event] = None) -> None:
        self.keys.clear()

    # -- drawing helpers ----------------------------------------------------

    def button(
        self,
        x: float,
        y: float,
        w: float,
        h: float,
        label: str,
        command: Optional[Callable[[], None]],
        fill: str = "#28434e",
        outline: str = "#55747e",
        text_color: str = WHITE,
        font_size: int = 14,
    ) -> None:
        c = self.canvas
        active = command is not None
        rect = c.create_rectangle(
            x, y, x + w, y + h, fill=fill if active else "#202b31",
            outline=outline if active else "#3c4b51",
        )
        text = c.create_text(
            x + w / 2, y + h / 2, text=label,
            fill=text_color if active else "#69767a",
            font=ui(font_size, True),
        )
        if command is not None:
            for item in (rect, text):
                c.tag_bind(
                    item, "<Button-1>",
                    lambda _event, cmd=command: self._click(cmd),
                )

    def _click(self, command: Callable[[], None]) -> None:
        self.sound.play("ui")
        command()

    def base_background(self, title: Optional[str] = None) -> None:
        self._scene = None
        self.particles.clear(delete_items=False)
        self._shake_offset = (0.0, 0.0)
        c = self.canvas
        c.delete("all")
        c.create_rectangle(0, 0, WIDTH, HEIGHT, fill=BG, outline="")
        c.create_rectangle(
            24, 24, WIDTH - 24, HEIGHT - 24, fill=PANEL,
            outline="#304b55", width=2,
        )
        c.create_text(
            48, 42, anchor="w", text="TABLE TENNIS / ARCADE",
            fill=MUTED, font=mono(11, True),
        )
        c.create_text(
            WIDTH - 48, 42, anchor="e", text="SEASON 1",
            fill=MUTED, font=mono(10),
        )
        if title:
            c.create_text(
                WIDTH / 2, 95, text=title, fill=GOLD, font=ui(28, True)
            )

    def resource_bar(self, y: float) -> None:
        data = self.data
        entries = (
            ("金币", data["coins"], GOLD),
            ("招募券", data["tickets"], CYAN),
            ("碎片", data["shards"], PURPLE),
            ("奖杯", data["trophies"], GREEN),
        )
        start = WIDTH / 2 - 240
        for index, (label, value, color) in enumerate(entries):
            x = start + index * 160
            self.canvas.create_text(
                x, y, text=f"{label} {value}", fill=color, font=ui(11, True)
            )

    def draw(self) -> None:
        if self.screen == "game":
            self._reset_shake()
            if self._scene is None:
                self._build_game_scene()
            else:
                self._sync_game()
            self._apply_shake()
            return
        self._scene = None
        if self.screen == "menu":
            self._draw_menu()
        elif self.screen == "modes":
            self._draw_modes()
        elif self.screen == "gacha":
            self._draw_gacha()
        elif self.screen == "shop":
            self._draw_shop()
        elif self.screen == "roster":
            self._draw_roster()
        elif self.screen == "tasks":
            self._draw_tasks()
        elif self.screen == "help":
            self._draw_help()
        elif self.screen == "tournament":
            self._draw_tournament()
        elif self.screen == "challenge":
            self._draw_challenge()
        elif self.screen == "training":
            self._draw_training()
        elif self.screen == "result":
            self._draw_result()

    # -- menu ---------------------------------------------------------------

    def _draw_menu(self) -> None:
        self.base_background()
        c = self.canvas
        c.create_text(
            WIDTH / 2, 82, text="乒乓球员收集计划",
            fill=WHITE, font=ui(28, True),
        )
        c.create_text(
            WIDTH / 2, 112, text="赢下比赛，招募球员，向锦标赛冠军进发。",
            fill=MUTED, font=ui(12),
        )
        self.resource_bar(140)

        p = PLAYERS[self.selected]
        c.create_rectangle(
            270, 160, 730, 270, fill=TABLE, outline=p.color, width=2
        )
        c.create_text(
            WIDTH / 2, 181,
            text=f"当前球员：{self.selected}  /  {p.title}",
            fill=p.color, font=ui(16, True),
        )
        level, progress, remain = mastery_progress(
            int(self.save.mastery_entry(self.selected).get("xp", 0))
        )
        c.create_text(
            WIDTH / 2, 203,
            text=f"熟练度 Lv.{level} {MASTERY_TITLES[level - 1]}",
            fill=GOLD, font=ui(10, True),
        )
        c.create_rectangle(
            410, 214, 590, 220, fill="#26383e", outline="",
        )
        if progress > 0:
            c.create_rectangle(
                410, 214, 410 + 180 * progress, 220,
                fill=GOLD, outline="",
            )
        c.create_text(
            WIDTH / 2, 236, text=p.mechanic,
            fill=MUTED, font=ui(9),
        )
        c.create_text(
            WIDTH / 2, 254,
            text=f"已解锁 {len(self.data['unlocked'])}/{len(PLAYERS)} 名球员",
            fill=MUTED, font=ui(9),
        )

        c.create_text(
            WIDTH / 2, 290,
            text=f"选择对手：{self.opponent}    |    AI 难度：{self.difficulty}",
            fill=RED, font=ui(12, True),
        )
        opponent = PLAYERS[self.opponent]
        self.button(
            170, 303, 70, 28, "◀", lambda: self.cycle_opponent(-1),
            font_size=10,
        )
        self.button(
            250, 303, 500, 28,
            f"{self.opponent} · {opponent.title} · {self._ai_style(opponent)}",
            lambda: self.cycle_opponent(1),
            fill="#4a3035", outline=opponent.color,
            text_color=opponent.color, font_size=9,
        )
        self.button(
            760, 303, 70, 28, "▶", lambda: self.cycle_opponent(1),
            font_size=10,
        )
        for i, level_name in enumerate(DIFF_ORDER):
            active = self.difficulty == level_name
            self.button(
                305 + i * 100, 340, 90, 26, level_name,
                lambda selected=level_name: self.set_difficulty(selected),
                fill="#345966" if active else "#243941",
                outline=CYAN if active else "#4a626a",
                font_size=9,
            )

        self.button(
            350, 376, 300, 38, "开始比赛", self.start_quick_match,
            fill="#345966", outline=CYAN, font_size=15,
        )
        tournament_active = bool(
            self.data.get("tournament")
            and self.data["tournament"].get("active")
        )
        modes_label = "游戏模式   ● 锦标赛进行中" if tournament_active else "游戏模式"
        self.button(
            350, 421, 300, 32, modes_label,
            lambda: self.show("modes"),
            fill="#3a354f", outline="#8f80c8", font_size=11,
        )
        self.button(
            230, 460, 170, 32, "球员抽卡",
            lambda: self.show("gacha"),
            fill="#3a354f", outline="#8f80c8", font_size=10,
        )
        self.button(
            415, 460, 170, 32, "球员图鉴",
            lambda: self.show("roster"),
            fill="#293f46", outline="#6a8b95", font_size=10,
        )
        self.button(
            600, 460, 170, 32, "每日任务",
            lambda: self.show("tasks"),
            fill="#294336", outline="#6fa983", font_size=10,
        )
        c.create_text(
            WIDTH / 2, 512,
            text="W/S 上下 · A/D 前后 · Shift 冲刺 · J 扣杀 · C 削球 · "
                 "K 防反 · E 技能",
            fill=MUTED, font=ui(9),
        )
        c.create_text(
            WIDTH / 2, 532,
            text="发球时 1/2/3 选旋转，W/S/A/D 调落点，空格发球",
            fill=MUTED, font=ui(9),
        )
        c.create_text(
            WIDTH / 2, 552,
            text=f"H 帮助 · M {'取消静音' if self.muted else '静音'} · "
                 f"音量 {int(float(self.data['volume']) * 100)}% · Esc 返回",
            fill=MUTED, font=ui(9),
        )
        if self.data.get("tournament") and self.data["tournament"].get("active"):
            c.create_text(
                WIDTH / 2, 576, text="锦标赛正在进行：游戏模式 → 锦标赛",
                fill=CYAN, font=ui(9, True),
            )
        elif self.message:
            c.create_text(
                WIDTH / 2, 576, text=self.message,
                fill=GOLD, font=ui(10, True),
            )

    def _draw_modes(self) -> None:
        self._ensure_periods()
        self.base_background("游戏模式")
        self.resource_bar(130)
        cards = (
            (80, 155, "锦标赛", "8 人单败淘汰，三局两胜，决赛五局三胜。",
             "冠军可获得奖杯与大量奖励。", self._mode_tournament_status(),
             self.open_tournament),
            (510, 155, "每日挑战", "3 个固定挑战，完成条件与奖励各不相同。",
             "每日首次完成指定挑战获得双倍金币。",
             self._mode_challenge_status(), lambda: self.show("challenge")),
            (80, 325, "训练模式", "发球、接发球、技能三种练习。",
             "无限体力，不记分，适合熟悉手感。",
             "随时可以进入", lambda: self.show("training")),
            (510, 325, "本地双人", "P1 使用 WASD，P2 使用方向键移动。",
             "P2：逗号扣杀 · 句号削球 · 斜杠防反 · L 爆发。",
             f"P2：{self.opponent}", self.start_local_match),
        )
        for x, y, title, line1, line2, status, command in cards:
            c = self.canvas
            c.create_rectangle(
                x, y, x + 410, y + 145, fill=TABLE,
                outline="#42616c", width=2,
            )
            c.create_text(
                x + 22, y + 24, anchor="w", text=title,
                fill=GOLD, font=ui(18, True),
            )
            c.create_text(
                x + 22, y + 55, anchor="w", text=line1,
                fill=WHITE, font=ui(10),
            )
            c.create_text(
                x + 22, y + 76, anchor="w", text=line2,
                fill=MUTED, font=ui(9),
            )
            c.create_text(
                x + 22, y + 101, anchor="w", text=status,
                fill=CYAN, font=ui(9, True),
            )
            self.button(
                x + 250, y + 100, 140, 30, "进入",
                command, fill="#345966", outline=CYAN, font_size=10,
            )
        self.button(390, 510, 220, 36, "返回主菜单", self.to_menu, font_size=11)

    def _mode_tournament_status(self) -> str:
        t = self.data.get("tournament")
        if not t:
            return "尚未开始 · 可从 8 强打起"
        if t.get("active"):
            return f"进行中：{('八强赛', '半决赛', '决赛')[t['round']]}"
        if t.get("champion") == t.get("player", self.selected):
            return "已夺冠 · 可开启新赛事"
        return f"上届冠军：{t.get('champion', '未知')}"

    def _mode_challenge_status(self) -> str:
        today = self.data["daily_challenge"]
        cid = self._daily_challenge_id()
        if today.get("claimed"):
            return f"今日已完成：{CHALLENGES[cid].name}"
        return f"今日双倍：{CHALLENGES[cid].name}"

    def _ai_style(self, player: Player) -> str:
        if player.ai_aggression >= 0.70:
            return "凶悍抢攻"
        if player.ai_aggression >= 0.50:
            return "主动进攻"
        return "稳健控制"

    def _daily_challenge_id(self) -> str:
        return CHALLENGE_ORDER[date.today().toordinal() % len(CHALLENGE_ORDER)]


    # -- tasks --------------------------------------------------------------

    def _task_progress(self, task_id: str, weekly: bool = False) -> int:
        if weekly:
            return int(self.data["weekly"].get("wins", 0))
        return int(self.data["daily"]["progress"].get(task_id, 0))

    def _claim_daily(self, task: dict) -> None:
        claimed = self.data["daily"]["claimed"]
        progress = self._task_progress(task["id"])
        if task["id"] in claimed or progress < task["target"]:
            return
        self.save.grant(task["coins"], task["tickets"], task["shards"])
        claimed.append(task["id"])
        self.save.save()
        self.sound.play("win")
        self._toast(f"任务完成：{task['label']}", 2.0)
        self.draw()

    def _claim_weekly(self) -> None:
        weekly = self.data["weekly"]
        if weekly.get("claimed") or self._task_progress("wins", True) < WEEKLY_TASK["target"]:
            return
        self.save.grant(
            WEEKLY_TASK["coins"], WEEKLY_TASK["tickets"], WEEKLY_TASK["shards"]
        )
        weekly["claimed"] = True
        self.save.save()
        self.sound.play("win")
        self._toast("每周任务完成！", 2.0)
        self.draw()

    def _draw_tasks(self) -> None:
        self._ensure_periods()
        self.base_background("每日任务")
        self.resource_bar(130)
        c = self.canvas
        c.create_text(
            90, 160, anchor="w",
            text="刷新时间：每天 0 点 · 周任务每周一重置",
            fill=WHITE, font=ui(13, True),
        )

        rows = [(task, False) for task in DAILY_TASKS] + [(WEEKLY_TASK, True)]
        for index, (task, weekly) in enumerate(rows):
            y = 182 + index * 70
            progress = self._task_progress(task["id"], weekly)
            claimed = (
                self.data["weekly"].get("claimed")
                if weekly else task["id"] in self.data["daily"]["claimed"]
            )
            complete = progress >= task["target"]
            c.create_rectangle(
                90, y, 910, y + 58, fill=TABLE,
                outline="#42616c", width=1,
            )
            label = ("每周 · " if weekly else "") + task["label"]
            c.create_text(
                108, y + 17, anchor="w", text=label,
                fill=WHITE, font=ui(11, True),
            )
            c.create_text(
                108, y + 40, anchor="w",
                text=f"进度 {min(progress, task['target'])}/{task['target']}",
                fill=MUTED, font=mono(9),
            )
            c.create_rectangle(
                230, y + 36, 520, y + 44,
                fill="#26383e", outline="",
            )
            ratio = pct(progress, task["target"])
            if ratio > 0:
                c.create_rectangle(
                    230, y + 36, 230 + 290 * ratio, y + 44,
                    fill=GREEN if complete else CYAN, outline="",
                )
            reward_bits = []
            if task["coins"]:
                reward_bits.append(f"{task['coins']} 金币")
            if task["tickets"]:
                reward_bits.append(f"{task['tickets']} 招募券")
            if task["shards"]:
                reward_bits.append(f"{task['shards']} 碎片")
            c.create_text(
                550, y + 29, anchor="w", text="奖励：" + " + ".join(reward_bits),
                fill=GOLD, font=ui(9),
            )
            if claimed:
                self.button(
                    760, y + 14, 130, 30, "已领取", None, font_size=10,
                )
            elif complete:
                command = self._claim_weekly if weekly else (
                    lambda t=task: self._claim_daily(t)
                )
                self.button(
                    760, y + 14, 130, 30, "领取", command,
                    fill="#2f5a3c", outline=GREEN, font_size=10,
                )
            else:
                self.button(
                    760, y + 14, 130, 30, "进行中", None, font_size=10,
                )

        stats = self.data["stats"]
        c.create_text(
            WIDTH / 2, 490,
            text=f"总场次 {stats['matches']} · 胜场 {stats['wins']} · "
                 f"最佳回合 {stats['best_rally']} · "
                 f"PERFECT {stats['perfects']}",
            fill=MUTED, font=ui(10),
        )
        self.button(390, 515, 220, 36, "返回主菜单", self.to_menu, font_size=11)
        if self.message:
            c.create_text(
                WIDTH / 2, 575, text=self.message, fill=GOLD, font=ui(10, True)
            )

    # -- gacha / shop -------------------------------------------------------

    def _draw_gacha(self) -> None:
        self.base_background("球员招募")
        self.resource_bar(130)
        c = self.canvas
        data = self.data
        can_ticket = data["tickets"] > 0
        can_coin = data["coins"] >= GACHA_COIN_COST
        c.create_text(
            WIDTH / 2, 155,
            text=f"单抽消耗 1 张招募券，或 {GACHA_COIN_COST} 金币；"
                 f"重复球员转化为 {DUPLICATE_SHARDS} 碎片",
            fill=MUTED, font=ui(9),
        )

        if self.last_draw:
            name = self.last_draw
            p = PLAYERS[name]
            c.create_rectangle(
                300, 175, 700, 370, fill=TABLE, outline=p.color, width=3
            )
            c.create_text(
                WIDTH / 2, 205, text="招募成功", fill=GOLD, font=ui(14, True)
            )
            c.create_text(
                WIDTH / 2, 248, text=name, fill=p.color, font=ui(28, True)
            )
            c.create_text(
                WIDTH / 2, 282, text=p.title, fill=WHITE, font=ui(14)
            )
            c.create_text(
                WIDTH / 2, 312, text=p.trait, fill=MUTED, font=ui(10)
            )
            c.create_text(
                WIDTH / 2, 332, text=p.mechanic, fill=MUTED, font=ui(9)
            )
            c.create_text(
                WIDTH / 2, 353,
                text=(
                    f"重复招募：转化为 {self.last_draw_shards} 碎片"
                    if self.last_draw_duplicate
                    else "首次招募！已加入球员图鉴"
                ),
                fill=MUTED if self.last_draw_duplicate else GREEN,
                font=ui(9, True),
            )
        else:
            c.create_rectangle(
                300, 175, 700, 370, fill="#202c3a",
                outline="#8f80c8", width=2,
            )
            c.create_text(
                WIDTH / 2, 225, text="PLAYER", fill="#8f80c8",
                font=mono(18, True),
            )
            c.create_text(
                WIDTH / 2, 275, text="?", fill=GOLD, font=mono(54, True)
            )
            c.create_text(
                WIDTH / 2, 332, text="点击招募，抽取一名球员",
                fill=MUTED, font=ui(12),
            )
            if len(data["unlocked"]) >= len(PLAYERS):
                c.create_text(
                    WIDTH / 2, 353, text="已收集全部球员，之后只会获得碎片",
                    fill=CYAN, font=ui(9),
                )

        self.button(
            300, 390, 190, 40, "招募（1 券）",
            (lambda: self.perform_draw(False)) if can_ticket else None,
            fill="#3a354f", outline="#a495e0", font_size=11,
        )
        self.button(
            510, 390, 190, 40, f"金币招募（{GACHA_COIN_COST}）",
            (lambda: self.perform_draw(True)) if can_coin else None,
            fill="#4a3a2a", outline=GOLD, font_size=10,
        )
        self.button(
            300, 444, 190, 38, "碎片商店",
            lambda: self.show("shop"),
            fill="#293f46", outline=PURPLE, font_size=10,
        )
        self.button(
            510, 444, 190, 38, "返回主菜单", self.to_menu, font_size=10,
        )
        if self.message:
            c.create_text(
                WIDTH / 2, 520, text=self.message, fill=GOLD, font=ui(10, True)
            )

    def perform_draw(self, use_coins: bool = False) -> None:
        data = self.data
        if use_coins:
            if data["coins"] < GACHA_COIN_COST:
                self._toast("金币不足")
                self.draw()
                return
            data["coins"] -= GACHA_COIN_COST
        else:
            if data["tickets"] <= 0:
                self._toast("招募券不足，赢下比赛可以获得")
                self.draw()
                return
            data["tickets"] -= 1

        pool = [name for name in PLAYERS if not self.save.is_unlocked(name)]
        if pool:
            name = random.choice(pool)
            self.save.unlock(name)
            self.last_draw_duplicate = False
            self.last_draw_shards = 0
            self.sound.play("win")
        else:
            name = random.choice(list(PLAYERS))
            self.last_draw_duplicate = True
            self.last_draw_shards = DUPLICATE_SHARDS
            data["shards"] += DUPLICATE_SHARDS
            self.sound.play("score")
        self.last_draw = name
        self.save.save()
        self.draw()

    def _draw_shop(self) -> None:
        self.base_background("碎片商店")
        self.resource_bar(130)
        c = self.canvas
        locked = [name for name in PLAYERS if not self.save.is_unlocked(name)]
        c.create_text(
            WIDTH / 2, 155,
            text=f"使用碎片直接兑换指定球员 · 每名 {SHARD_PLAYER_COST} 碎片",
            fill=MUTED, font=ui(9),
        )
        if not locked:
            c.create_text(
                WIDTH / 2, 260, text="所有球员都已解锁！",
                fill=GOLD, font=ui(20, True),
            )
            c.create_text(
                WIDTH / 2, 300, text="继续比赛或抽卡，把碎片留给下一季吧。",
                fill=MUTED, font=ui(11),
            )
        else:
            for index, name in enumerate(locked):
                x = 48 + (index % 4) * 226
                y = 180 + (index // 4) * 108
                p = PLAYERS[name]
                affordable = self.data["shards"] >= SHARD_PLAYER_COST
                tag = f"shop-card-{index}"
                c.create_rectangle(
                    x, y, x + 218, y + 96,
                    fill=TABLE if affordable else "#20282d",
                    outline=p.color if affordable else "#3c4b51", width=2,
                    tags=(tag,),
                )
                c.create_text(
                    x + 14, y + 16, anchor="w", text=name, fill=p.color,
                    font=ui(15, True), tags=(tag,),
                )
                c.create_text(
                    x + 14, y + 37, anchor="w", text=p.title,
                    fill=WHITE, font=ui(9), tags=(tag,),
                )
                c.create_text(
                    x + 14, y + 58, anchor="w",
                    text=f"技能：{p.skill}",
                    fill=MUTED, font=ui(8), tags=(tag,),
                )
                c.create_text(
                    x + 14, y + 80, anchor="w",
                    text=f"{SHARD_PLAYER_COST} 碎片"
                    + ("" if affordable else "（不足）"),
                    fill=GOLD if affordable else MUTED,
                    font=ui(9, True), tags=(tag,),
                )
                if affordable:
                    c.tag_bind(
                        tag, "<Button-1>",
                        lambda _event, n=name: self.buy_player(n),
                    )
        self.button(390, 512, 220, 38, "返回招募", lambda: self.show("gacha"),
                    font_size=11)
        if self.message:
            c.create_text(
                WIDTH / 2, 570, text=self.message, fill=GOLD, font=ui(10, True)
            )

    def buy_player(self, name: str) -> None:
        if self.save.is_unlocked(name):
            return
        if self.data["shards"] < SHARD_PLAYER_COST:
            self._toast("碎片不足")
            self.draw()
            return
        self.data["shards"] -= SHARD_PLAYER_COST
        self.save.unlock(name)
        self.save.save()
        self.sound.play("win")
        self._toast(f"已兑换：{name}")
        self.draw()

    # -- roster / help ------------------------------------------------------

    def _draw_roster(self) -> None:
        self.base_background("球员图鉴")
        c = self.canvas
        c.create_text(
            48, 122, anchor="w",
            text=f"解锁 {len(self.data['unlocked'])}/{len(PLAYERS)} · "
                 f"点击卡片选择或前往兑换",
            fill=MUTED, font=ui(9),
        )
        for index, name in enumerate(PLAYERS):
            x = 48 + (index % 4) * 226
            y = 136 + (index // 4) * 112
            p = PLAYERS[name]
            unlocked = self.save.is_unlocked(name)
            selected = name == self.selected
            tag = f"roster-card-{index}"

            c.create_rectangle(
                x, y, x + 218, y + 104,
                fill=TABLE if unlocked else "#20282d",
                outline=(GOLD if selected else p.color) if unlocked else "#3c4b51",
                width=3 if selected else 2, tags=(tag,),
            )
            c.create_text(
                x + 14, y + 17, anchor="w",
                text=name if unlocked else "未解锁球员",
                fill=p.color if unlocked else MUTED,
                font=ui(15, True), tags=(tag,),
            )
            c.create_text(
                x + 14, y + 38, anchor="w",
                text=p.title if unlocked else "可在碎片商店兑换",
                fill=WHITE if unlocked else MUTED,
                font=ui(9), tags=(tag,),
            )
            if unlocked:
                c.create_text(
                    x + 14, y + 56, anchor="w",
                    text=f"速度 {p.speed:.2f}  力量 {p.power:.2f}  "
                         f"控制 {p.control:.2f}",
                    fill=MUTED, font=mono(7), tags=(tag,),
                )
                xp = int(self.save.mastery_entry(name).get("xp", 0))
                level, _, _ = mastery_progress(xp)
                c.create_text(
                    x + 14, y + 73, anchor="w",
                    text=f"Lv.{level} {MASTERY_TITLES[level - 1]} · XP {xp}",
                    fill=GOLD, font=ui(8), tags=(tag,),
                )
                c.create_text(
                    x + 14, y + 91, anchor="w",
                    text=f"技能：{p.skill}", fill=p.color,
                    font=ui(8), tags=(tag,),
                )
                if selected:
                    c.create_text(
                        x + 204, y + 17, anchor="e", text="使用中",
                        fill=GOLD, font=ui(8, True), tags=(tag,),
                    )
                c.tag_bind(
                    tag, "<Button-1>",
                    lambda _event, n=name: self.set_selected(n),
                )
            else:
                c.create_text(
                    x + 14, y + 62, anchor="w",
                    text=f"兑换需要 {SHARD_PLAYER_COST} 碎片",
                    fill=GOLD, font=ui(9, True), tags=(tag,),
                )
                c.create_text(
                    x + 14, y + 84, anchor="w",
                    text="点击查看碎片商店", fill=MUTED, font=ui(8),
                    tags=(tag,),
                )
                c.tag_bind(
                    tag, "<Button-1>",
                    lambda _event: self.show("shop"),
                )
        self.button(390, 500, 220, 36, "返回主菜单", self.to_menu, font_size=11)

    def _draw_help(self) -> None:
        self.base_background("操作与机制")
        c = self.canvas
        left = (
            ("移动与冲刺", "W/S 上下 · A/D 前后 · Shift 冲刺消耗体力"),
            ("四种回球", "J 扣杀 · C 削球 · K 防守反击 · E 专属技能"),
            ("发球", "1/2/3 选旋转 · W/S/A/D 调落点 · 空格发球"),
            ("比赛", "三局两胜 · 每 2 分轮换发球 · 10:10 后每分轮换"),
            ("暂停与音效", "P 暂停 · M 静音 · [ / ] 调音量 · Esc 返回"),
        )
        right = (
            ("能量", "击球、PERFECT 和得分会积攒能量，满 100 可放技能"),
            ("PERFECT", "球拍中心附近击球会提升球速、控制与能量"),
            ("体力", "冲刺、扣杀、削球、防反都会消耗体力"),
            ("经济", "金币抽卡、碎片兑换指定球员、奖杯来自锦标赛"),
            ("本地双人", "P2：方向键移动 · , 扣杀 · . 削球 · / 防反 · L 爆发"),
        )
        for column, entries in enumerate((left, right)):
            x = 80 + column * 460
            c.create_text(
                x, 145, anchor="w",
                text="基础操作" if column == 0 else "进阶机制",
                fill=GOLD, font=ui(16, True),
            )
            for row, (heading, body) in enumerate(entries):
                y = 180 + row * 62
                c.create_text(
                    x, y, anchor="w", text=heading,
                    fill=CYAN, font=ui(11, True),
                )
                c.create_text(
                    x, y + 20, anchor="w", text=body,
                    fill=WHITE, font=ui(9),
                )
        c.create_text(
            WIDTH / 2, 520,
            text="提示：赢下比赛获得招募券与金币；重复球员会转化为碎片。",
            fill=MUTED, font=ui(9),
        )
        self.button(390, 545, 220, 34, "返回", lambda: self.show("menu"),
                    font_size=10)

    # -- tournament ---------------------------------------------------------

    def _create_tournament(self) -> None:
        others = [name for name in PLAYERS if name != self.selected]
        random.shuffle(others)
        field = others[:7] + [self.selected]
        random.shuffle(field)
        self.data["tournament"] = {
            "active": True,
            "round": 0,
            "player": self.selected,
            "players": field,
            "player_slot": field.index(self.selected),
            "champion": None,
            "done": False,
            "history": [],
            "base_difficulty": self.difficulty,
        }
        self.save.save()
        self.sound.play("break")

    def open_tournament(self) -> None:
        if not self.data.get("tournament"):
            self._create_tournament()
        self.show("tournament")

    def _tournament_round_name(self, round_index: int) -> str:
        return ("八强赛", "半决赛", "决赛")[max(0, min(2, round_index))]

    def _draw_tournament(self) -> None:
        self.base_background("锦标赛")
        c = self.canvas
        t = self.data.get("tournament")
        if not t:
            c.create_text(
                WIDTH / 2, 200, text="八人单败淘汰赛",
                fill=WHITE, font=ui(20, True),
            )
            c.create_text(
                WIDTH / 2, 240,
                text="依次挑战八强、半决赛、决赛。三局两胜，决赛五局三胜。",
                fill=MUTED, font=ui(11),
            )
            c.create_text(
                WIDTH / 2, 270,
                text="冠军奖励：奖杯 + 300 金币 + 2 招募券 + 80 碎片",
                fill=GOLD, font=ui(10, True),
            )
            self.button(
                350, 330, 300, 44, "创建锦标赛", self._create_tournament,
                fill="#345966", outline=CYAN, font_size=15,
            )
            self.button(390, 500, 220, 36, "返回", lambda: self.show("modes"),
                        font_size=11)
            return

        if t.get("done"):
            champion = t.get("champion", "未知")
            won = champion == t.get("player", self.selected)
            c.create_text(
                WIDTH / 2, 175,
                text="冠军：你！" if won else f"冠军：{champion}",
                fill=GOLD if won else WHITE, font=ui(24, True),
            )
            history = t.get("history", [])
            last = history[-1] if history else None
            if last:
                c.create_text(
                    WIDTH / 2, 215,
                    text=f"你的最后一轮：{self._tournament_round_name(last['round'])} "
                         f"{last['score']} · {'胜' if last['won'] else '负'} "
                         f"vs {last['opponent']}",
                    fill=GREEN if last["won"] else RED, font=ui(11),
                )
            c.create_text(
                WIDTH / 2, 250,
                text="你已经完成本届锦标赛，可以开启新的一届。",
                fill=MUTED, font=ui(10),
            )
            self.button(
                350, 300, 300, 42, "开启新锦标赛", self._create_tournament,
                fill="#345966", outline=CYAN, font_size=13,
            )
            self.button(
                390, 500, 220, 36, "返回模式", lambda: self.show("modes"),
                font_size=11,
            )
            return

        round_index = int(t["round"])
        players = t["players"]
        slot = int(t["player_slot"])
        player_name = t.get("player", self.selected)
        opponent = players[slot ^ 1]
        c.create_text(
            WIDTH / 2, 132,
            text=f"{self._tournament_round_name(round_index)} · "
                 f"你的对手：{opponent}",
            fill=GOLD, font=ui(18, True),
        )
        c.create_text(
            WIDTH / 2, 158,
            text=f"赛制：{'五局三胜' if round_index == 2 else '三局两胜'} · "
                 f"难度：{self._tournament_difficulty(round_index)}",
            fill=MUTED, font=ui(9),
        )

        pairs = [(players[i], players[i + 1]) for i in range(0, len(players), 2)]
        columns = 2 if len(pairs) > 2 else 1
        box_w = 380 if columns == 2 else 560
        for index, (a, b) in enumerate(pairs):
            col = index % columns
            row = index // columns
            x = 80 + col * 440 if columns == 2 else 220
            y = 190 + row * 86
            is_player = a == player_name or b == player_name
            c.create_rectangle(
                x, y, x + box_w, y + 68,
                fill="#243941" if not is_player else "#2c4b4a",
                outline=GOLD if is_player else "#42616c", width=2,
            )
            c.create_text(
                x + 18, y + 22, anchor="w",
                text=("你" if a == player_name else a), fill=WHITE,
                font=ui(11, True),
            )
            c.create_text(
                x + 18, y + 45, anchor="w",
                text=("你" if b == player_name else b), fill=WHITE,
                font=ui(11),
            )
            c.create_text(
                x + box_w / 2, y + 34, text="VS",
                fill=MUTED, font=mono(10, True),
            )
            if is_player:
                c.create_text(
                    x + box_w - 16, y + 14, anchor="e",
                    text="本轮", fill=GOLD, font=ui(8, True),
                )

        self.button(
            350, 405, 300, 40, "开始本轮比赛",
            self.start_tournament_match,
            fill="#345966", outline=CYAN, font_size=13,
        )
        if t.get("history"):
            last = t["history"][-1]
            c.create_text(
                WIDTH / 2, 458,
                text=f"上一轮：{last['opponent']} {last['score']} "
                     f"{'胜' if last['won'] else '负'}",
                fill=GREEN if last["won"] else RED, font=ui(9),
            )
        c.create_text(
            WIDTH / 2, 480,
            text="冠军奖励：奖杯 + 300 金币 + 2 招募券 + 80 碎片",
            fill=MUTED, font=ui(9),
        )
        self.button(
            390, 508, 220, 34, "返回模式", lambda: self.show("modes"),
            font_size=10,
        )
        self.button(
            80, 508, 140, 34, "放弃本届",
            self.abandon_tournament,
            fill="#3a2528", outline=RED, text_color=RED, font_size=10,
        )

    def abandon_tournament(self) -> None:
        t = self.data.get("tournament")
        if not t or not t.get("active"):
            return
        if not messagebox.askyesno(
            "放弃锦标赛", "确定放弃本届锦标赛吗？当前进度不会保留。",
            parent=self.root,
        ):
            return
        self.data["tournament"] = None
        self.save.save()
        self.show("modes")

    def _tournament_difficulty(self, round_index: int) -> str:
        t = self.data.get("tournament") or {}
        base = t.get("base_difficulty", self.difficulty)
        index = DIFF_ORDER.index(base) if base in DIFF_ORDER else 1
        return DIFF_ORDER[min(3, index + round_index)]

    # -- challenge ----------------------------------------------------------

    def _draw_challenge(self) -> None:
        self._ensure_periods()
        self.base_background("挑战模式")
        self.resource_bar(130)
        c = self.canvas
        daily_id = self._daily_challenge_id()
        claimed = bool(self.data["daily_challenge"].get("claimed"))
        for index, cid in enumerate(CHALLENGE_ORDER):
            challenge = CHALLENGES[cid]
            y = 168 + index * 105
            is_daily = cid == daily_id
            c.create_rectangle(
                90, y, 910, y + 92, fill=TABLE,
                outline=GOLD if is_daily else "#42616c", width=2,
            )
            c.create_text(
                110, y + 18, anchor="w", text=challenge.name,
                fill=GOLD if is_daily else WHITE, font=ui(14, True),
            )
            c.create_text(
                110, y + 42, anchor="w", text=challenge.desc,
                fill=WHITE, font=ui(10),
            )
            c.create_text(
                110, y + 64, anchor="w",
                text=f"对手：{challenge.opponent} · {challenge.difficulty} · "
                     f"奖励 {challenge.coins} 金币"
                     + (f" + {challenge.tickets} 券" if challenge.tickets else "")
                     + (f" + {challenge.shards} 碎片" if challenge.shards else ""),
                fill=MUTED, font=ui(8),
            )
            wins = int(self.data["challenge_wins"].get(cid, 0))
            c.create_text(
                110, y + 80, anchor="w", text=f"已通关 {wins} 次",
                fill=CYAN, font=ui(8),
            )
            if is_daily:
                c.create_text(
                    680, y + 18, anchor="e",
                    text="今日双倍" + (" · 已领取" if claimed else ""),
                    fill=GREEN if not claimed else MUTED,
                    font=ui(9, True),
                )
            self.button(
                770, y + 45, 120, 34, "开始",
                lambda cid=cid: self.start_challenge(cid),
                fill="#345966", outline=CYAN, font_size=10,
            )
        self.button(390, 505, 220, 36, "返回模式", lambda: self.show("modes"),
                    font_size=11)

    # -- training -----------------------------------------------------------

    def _draw_training(self) -> None:
        self.base_background("训练模式")
        c = self.canvas
        for index, key in enumerate(("serve", "receive", "skill")):
            title, desc, tip = TRAINING_INFO[key]
            y = 150 + index * 112
            c.create_rectangle(
                90, y, 910, y + 96, fill=TABLE, outline="#42616c", width=2
            )
            c.create_text(
                112, y + 22, anchor="w", text=title,
                fill=GOLD, font=ui(16, True),
            )
            c.create_text(
                112, y + 47, anchor="w", text=desc,
                fill=WHITE, font=ui(10),
            )
            c.create_text(
                112, y + 70, anchor="w", text=tip,
                fill=MUTED, font=ui(9),
            )
            self.button(
                770, y + 30, 120, 36, "开始",
                lambda k=key: self.start_training(k),
                fill="#345966", outline=CYAN, font_size=10,
            )
        c.create_text(
            WIDTH / 2, 500,
            text="训练模式不计分、不消耗体力，也不会获得奖励。",
            fill=MUTED, font=ui(9),
        )
        self.button(390, 525, 220, 34, "返回模式", lambda: self.show("modes"),
                    font_size=10)

    # -- result -------------------------------------------------------------

    def _draw_result(self) -> None:
        result = self.last_result
        if not result:
            self.to_menu()
            return
        self.base_background()
        c = self.canvas
        won = bool(result["won"])
        c.create_text(
            WIDTH / 2, 145, text=result["title"],
            fill=GOLD if won else RED, font=ui(28, True),
        )
        c.create_text(
            WIDTH / 2, 192, text=result.get("score", ""),
            fill=WHITE, font=mono(30, True),
        )
        subtitle = result.get("subtitle", "")
        if subtitle:
            c.create_text(
                WIDTH / 2, 232, text=subtitle,
                fill=GREEN if won else MUTED, font=ui(11),
            )
        rewards = result.get("rewards", (0, 0, 0))
        reward_text = []
        if rewards[0]:
            reward_text.append(f"+{rewards[0]} 金币")
        if rewards[1]:
            reward_text.append(f"+{rewards[1]} 招募券")
        if rewards[2]:
            reward_text.append(f"+{rewards[2]} 碎片")
        if reward_text:
            c.create_text(
                WIDTH / 2, 260, text="奖励：" + "  ".join(reward_text),
                fill=GOLD, font=ui(11, True),
            )
        c.create_text(
            WIDTH / 2, 286,
            text=f"最大回合 {self.max_rally} · PERFECT {self.perfect_count} · "
                 f"扣杀 {self.smash_count}",
            fill=MUTED, font=ui(9),
        )

        mode = result.get("mode", "quick")
        if mode == "quick":
            if won:
                self.button(
                    300, 325, 190, 40, "前往抽卡", lambda: self.show("gacha"),
                    fill="#3a354f", outline="#a495e0", font_size=11,
                )
            self.button(
                510 if won else 350, 325, 190 if won else 300, 40,
                "再打一场", self.start_quick_match,
                fill="#345966", outline=CYAN, font_size=11,
            )
            self.button(390, 385, 220, 36, "返回主菜单", self.to_menu,
                        font_size=11)
        elif mode == "tournament":
            self.button(
                300, 325, 190, 40, "查看锦标赛", self.open_tournament,
                fill="#345966", outline=CYAN, font_size=11,
            )
            self.button(510, 325, 190, 40, "返回主菜单", self.to_menu,
                        font_size=11)
        elif mode == "challenge":
            self.button(
                300, 325, 190, 40, "重试挑战",
                lambda: self.start_challenge(result.get("challenge_id", "blitz")),
                fill="#345966", outline=CYAN, font_size=11,
            )
            self.button(
                510, 325, 190, 40, "返回挑战", lambda: self.show("challenge"),
                font_size=11,
            )
        elif mode == "local":
            self.button(
                300, 325, 190, 40, "再来一局", self.start_local_match,
                fill="#345966", outline=CYAN, font_size=11,
            )
            self.button(
                510, 325, 190, 40, "返回模式", lambda: self.show("modes"),
                font_size=11,
            )
        if self.message:
            c.create_text(
                WIDTH / 2, 470, text=self.message, fill=GOLD, font=ui(10, True)
            )

    def result_primary(self) -> None:
        result = self.last_result or {}
        mode = result.get("mode", "quick")
        if mode == "tournament":
            self.open_tournament()
        elif mode == "challenge":
            self.start_challenge(result.get("challenge_id", "blitz"))
        elif mode == "local":
            self.start_local_match()
        elif result.get("won"):
            self.show("gacha")
        else:
            self.start_quick_match()


    # -- match setup --------------------------------------------------------

    def start_quick_match(self) -> None:
        config = MatchConfig(
            mode="quick", opponent=self.opponent,
            difficulty=self.difficulty, best_of=3,
        )
        self.start_match(config)

    def start_tournament_match(self) -> None:
        t = self.data.get("tournament")
        if not t or not t.get("active"):
            return
        player_name = t.get("player", self.selected)
        if player_name in PLAYERS:
            self.selected = player_name
            self.data["selected"] = player_name
            self.save.save()
        round_index = int(t["round"])
        opponent = t["players"][t["player_slot"] ^ 1]
        self.start_match(MatchConfig(
            mode="tournament",
            opponent=opponent,
            difficulty=self._tournament_difficulty(round_index),
            best_of=5 if round_index == 2 else 3,
            tournament_round=round_index,
        ))

    def start_challenge(self, cid: str) -> None:
        challenge = CHALLENGES.get(cid)
        if not challenge:
            return
        self.start_match(MatchConfig(
            mode="challenge",
            opponent=challenge.opponent,
            difficulty=challenge.difficulty,
            best_of=1,
            win_score=challenge.win_score,
            time_limit=challenge.time_limit,
            stamina_scale=challenge.stamina_scale,
            challenge_id=cid,
        ))

    def start_training(self, kind: str) -> None:
        if kind not in TRAINING_INFO:
            return
        self.start_match(MatchConfig(
            mode="training",
            opponent="新秀",
            difficulty="普通",
            best_of=1,
            training_type=kind,
        ))

    def start_local_match(self) -> None:
        self.start_match(MatchConfig(
            mode="local",
            opponent=self.opponent,
            difficulty=self.difficulty,
            best_of=3,
            local_two_player=True,
        ))

    def start_match(self, config: MatchConfig) -> None:
        self.match_config = config
        self.local_two_player = config.local_two_player
        self.training_type = config.training_type
        self.win_score = config.win_score
        self.games_to_win = max(1, config.best_of // 2 + 1)
        self.player_games = 0
        self.cpu_games = 0
        self.player_score = 0
        self.cpu_score = 0
        self.player_x = 115.0
        self.player_y = HEIGHT / 2
        self.cpu_x = WIDTH - 145.0
        self.cpu_y = HEIGHT / 2
        self.ball_x = WIDTH / 2
        self.ball_y = HEIGHT / 2
        self.ball_vx = 0.0
        self.ball_vy = 0.0
        self.ball_spin = 0.0
        self.max_stamina = (
            float(PLAYERS[self.selected].stamina) * config.stamina_scale
        )
        self.stamina = self.max_stamina
        p2 = PLAYERS[config.opponent]
        self.p2_max_stamina = float(p2.stamina) * config.stamina_scale
        self.p2_stamina = self.p2_max_stamina
        self.skill_energy = 100.0 if config.training_type == "skill" else 0.0
        self.p2_energy = 0.0
        self.smash_cooldown = 0.0
        self.chop_cooldown = 0.0
        self.counter_cooldown = 0.0
        self.p2_smash_cooldown = 0.0
        self.p2_chop_cooldown = 0.0
        self.p2_counter_cooldown = 0.0
        self.skill_flash = 0.0
        self.skill_buff = 0.0
        self.smash_flash = 0.0
        self.p2_flash = 0.0
        self.timing_text = ""
        self.timing_timer = 0.0
        self.paused = False
        self.match_over = False
        self.serve_pending = True
        self.serve_style = "普通发球"
        self.serve_target_x = 740.0
        self.serve_target_y = HEIGHT / 2
        self.serve_owner = (
            "cpu" if config.training_type in ("receive", "skill") else "player"
        )
        self._game_first_server = self.serve_owner
        self._serve_points = 0
        self.serve_wait = 0.75 if self.serve_owner != "player" else 0.0
        self.game_break = 0.0
        self.break_text = ""
        self.time_left = config.time_limit
        self.match_time = 0.0
        self.rally = 0
        self.max_rally = 0
        self.smash_count = 0
        self.perfect_count = 0
        self.player_streak = 0
        self.cpu_streak = 0
        self.cpu_stun = 0.0
        self.shake = 0.0
        self._shake_offset = (0.0, 0.0)
        self.last_hit_side = ""
        self._trail_tick = 0
        self.message = ""
        self._message_timer = 0.0
        self.receiving_serve = False
        self.slowmo = 0.0
        self.last_result = None

        self.screen = "game"
        self.keys.clear()
        self._scene = None
        self.particles.clear()
        self._reset_shake(force=True)
        self.last_tick = time.perf_counter()
        self.draw()

    # -- game scene ---------------------------------------------------------

    def _serve_target_label(self) -> str:
        depth = (
            "近网" if self.serve_target_x < 690
            else "中台" if self.serve_target_x < 800
            else "底线"
        )
        side = (
            "左" if self.serve_target_y < 230
            else "右" if self.serve_target_y > 390
            else "中"
        )
        return f"{depth} · {side}路"

    def _build_game_scene(self) -> None:
        self.particles.clear(delete_items=False)
        self._shake_offset = (0.0, 0.0)
        c = self.canvas
        c.delete("all")
        scene: dict = {}
        p = PLAYERS[self.selected]
        opponent = PLAYERS[self.match_config.opponent]

        c.create_rectangle(
            COURT_LEFT, COURT_TOP, COURT_RIGHT, COURT_BOTTOM,
            fill=TABLE, outline="#42616c", width=2,
        )
        c.create_line(
            WIDTH / 2, COURT_TOP + 2, WIDTH / 2, COURT_BOTTOM - 2,
            fill=LINE, dash=(8, 8), width=2,
        )

        c.create_text(
            45, 32, anchor="w", text=f"{self.selected}  |  {p.title}",
            fill=p.color, font=ui(11, True),
        )
        right_title = (
            f"P2：{self.match_config.opponent}" if self.local_two_player
            else f"对手：{self.match_config.opponent}"
        )
        c.create_text(
            WIDTH - 45, 32, anchor="e",
            text=right_title + f"  |  {opponent.title}",
            fill=opponent.color, font=ui(10, True),
        )
        scene["game_score"] = c.create_text(
            WIDTH / 2, 32, text="", fill=WHITE, font=ui(10, True)
        )
        scene["score_player"] = c.create_text(
            WIDTH * 0.38, 96, text="0", fill=WHITE, font=mono(30, True)
        )
        scene["score_cpu"] = c.create_text(
            WIDTH * 0.62, 96, text="0", fill=WHITE, font=mono(30, True)
        )
        scene["mode_info"] = c.create_text(
            WIDTH / 2, 50, text="", fill=MUTED, font=ui(9)
        )
        scene["left_info"] = c.create_text(
            45, 50, anchor="w", text="", fill=MUTED, font=mono(8)
        )
        scene["serve_info"] = c.create_text(
            WIDTH - 45, 50, anchor="e", text="", fill=CYAN,
            font=ui(9, True),
        )
        scene["rally"] = c.create_text(
            WIDTH / 2, 125, text="", fill=MUTED, font=ui(9)
        )

        scene["player"] = c.create_rectangle(
            0, 0, 0, 0, fill=p.color, outline=WHITE, width=1
        )
        scene["cpu"] = c.create_rectangle(
            0, 0, 0, 0,
            fill=(opponent.color if self.local_two_player else RED),
            outline=WHITE, width=1,
        )
        scene["ball"] = c.create_oval(0, 0, 0, 0, fill=GOLD, outline="")
        scene["landing"] = c.create_oval(
            0, 0, 0, 0, outline=MUTED, width=1, dash=(3, 3),
            state="hidden",
        )

        bx, by, bw, bh = STAMINA_BAR
        c.create_text(
            bx, by - 12, anchor="w", text="体力", fill=MUTED,
            font=mono(8, True),
        )
        c.create_rectangle(
            bx, by, bx + bw, by + bh, fill="#26383e", outline="#58717a"
        )
        scene["stamina_fill"] = c.create_rectangle(
            bx + 2, by + 2, bx + bw - 2, by + bh - 2,
            fill=GREEN, outline="",
        )
        ex, ey, ew, eh = ENERGY_BAR
        c.create_text(
            ex, ey - 12, anchor="w", text="技能能量", fill=MUTED,
            font=mono(8, True),
        )
        c.create_rectangle(
            ex, ey, ex + ew, ey + eh, fill="#26383e", outline="#58717a"
        )
        scene["energy_fill"] = c.create_rectangle(
            ex + 2, ey + 2, ex + ew - 2, ey + eh - 2,
            fill=CYAN, outline="",
        )

        # P2 gauges (top right, shown only in local 2P)
        scene["p2_stamina_label"] = c.create_text(
            700, 70, anchor="w", text="P2 体力", fill=MUTED,
            font=mono(7, True), state="hidden",
        )
        scene["p2_stamina_bg"] = c.create_rectangle(
            780, 67, 940, 75, fill="#26383e", outline="", state="hidden",
        )
        scene["p2_stamina_fill"] = c.create_rectangle(
            782, 69, 938, 73, fill=GREEN, outline="", state="hidden",
        )
        scene["p2_energy_label"] = c.create_text(
            700, 88, anchor="w", text="P2 能量", fill=MUTED,
            font=mono(7, True), state="hidden",
        )
        scene["p2_energy_bg"] = c.create_rectangle(
            780, 85, 940, 93, fill="#26383e", outline="", state="hidden",
        )
        scene["p2_energy_fill"] = c.create_rectangle(
            782, 87, 938, 91, fill=CYAN, outline="", state="hidden",
        )

        scene["smash_hint"] = c.create_text(
            WIDTH - 40, HEIGHT - 67, anchor="e", text="",
            fill=GOLD, font=ui(9, True),
        )
        controls_text = (
            "P1 WASD / J C K E | P2 方向键 / , . / L | P 暂停"
            if self.local_two_player
            else "J 扣杀 | C 削球 | K 防反 | E 技能 | 1/2/3 发球 | "
                 "P 暂停 | M 静音"
        )
        c.create_text(
            WIDTH - 40, HEIGHT - 45, anchor="e",
            text=controls_text, fill=MUTED, font=ui(9),
        )

        scene["timing"] = c.create_text(
            0, 0, text="", fill=GOLD, font=ui(14, True), state="hidden"
        )
        scene["banner"] = c.create_text(
            WIDTH / 2, 168, text="", fill=GOLD,
            font=ui(18, True), state="hidden",
        )
        scene["message"] = c.create_text(
            WIDTH / 2, HEIGHT - 91, text="", fill=GOLD,
            font=ui(10, True), state="hidden",
        )
        scene["smash_flash"] = c.create_text(
            WIDTH / 2, 145, text="SMASH! 扣杀！", fill=GOLD,
            font=ui(20, True), state="hidden",
        )
        scene["skill_flash"] = c.create_text(
            WIDTH / 2, 180, text="", fill=p.color,
            font=ui(17, True), state="hidden",
        )
        scene["p2_flash"] = c.create_text(
            WIDTH / 2, 210, text="", fill=opponent.color,
            font=ui(14, True), state="hidden",
        )

        scene["serve_circle"] = c.create_oval(
            0, 0, 0, 0, outline=GOLD, width=2, dash=(4, 3), state="hidden"
        )
        scene["serve_cross_x"] = c.create_line(
            0, 0, 0, 0, fill=GOLD, width=1, state="hidden"
        )
        scene["serve_cross_y"] = c.create_line(
            0, 0, 0, 0, fill=GOLD, width=1, state="hidden"
        )

        scene["serve_box"] = c.create_rectangle(
            315, 230, 685, 350, fill="#10232b", outline="#69838b",
            width=2, state="hidden",
        )
        scene["serve_title"] = c.create_text(
            WIDTH / 2, 262, text="", fill=GOLD,
            font=ui(20, True), state="hidden",
        )
        scene["serve_sub"] = c.create_text(
            WIDTH / 2, 296, text="", fill=WHITE,
            font=ui(12), state="hidden",
        )
        scene["serve_hint"] = c.create_text(
            WIDTH / 2, 327, text="", fill=MUTED,
            font=ui(9), state="hidden",
        )

        scene["pause_box"] = c.create_rectangle(
            340, 230, 660, 360, fill="#10232b", outline="#69838b",
            width=2, state="hidden",
        )
        scene["pause_title"] = c.create_text(
            WIDTH / 2, 260, text="已暂停", fill=GOLD,
            font=ui(22, True), state="hidden",
        )
        scene["pause_hint"] = c.create_text(
            WIDTH / 2, 298, text="P 继续 · Esc 返回 · M 静音", fill=WHITE,
            font=ui(11), state="hidden",
        )
        scene["pause_sub"] = c.create_text(
            WIDTH / 2, 326,
            text=f"音量 {int(float(self.data['volume']) * 100)}% · "
                 f"[ / ] 调节",
            fill=MUTED, font=ui(9), state="hidden",
        )

        scene["break_box"] = c.create_rectangle(
            310, 225, 690, 355, fill="#10232b", outline="#69838b",
            width=2, state="hidden",
        )
        scene["break_title"] = c.create_text(
            WIDTH / 2, 258, text="", fill=GOLD,
            font=ui(21, True), state="hidden",
        )
        scene["break_sub"] = c.create_text(
            WIDTH / 2, 296, text="", fill=WHITE,
            font=ui(11), state="hidden",
        )
        scene["break_hint"] = c.create_text(
            WIDTH / 2, 326, text="即将开始下一局……", fill=MUTED,
            font=ui(9), state="hidden",
        )

        for key in (
            "timing", "banner", "message", "smash_flash", "skill_flash",
            "p2_flash", "serve_circle", "serve_cross_x", "serve_cross_y",
            "serve_box", "serve_title", "serve_sub", "serve_hint",
            "pause_box", "pause_title", "pause_hint", "pause_sub",
            "break_box", "break_title", "break_sub", "break_hint",
        ):
            c.itemconfig(scene[key], tags=("overlay",))

        self._scene = scene
        self._sync_game()

    def _sync_game(self) -> None:
        scene = self._scene
        if scene is None:
            return
        c = self.canvas
        p = PLAYERS[self.selected]
        opponent = PLAYERS[self.match_config.opponent]
        half_w, half_h = PADDLE_W / 2, PADDLE_H / 2

        c.coords(
            scene["player"],
            self.player_x - half_w, self.player_y - half_h,
            self.player_x + half_w, self.player_y + half_h,
        )
        c.coords(
            scene["cpu"],
            self.cpu_x - half_w, self.cpu_y - half_h,
            self.cpu_x + half_w, self.cpu_y + half_h,
        )
        c.coords(
            scene["ball"],
            self.ball_x - BALL_RADIUS, self.ball_y - BALL_RADIUS,
            self.ball_x + BALL_RADIUS, self.ball_y + BALL_RADIUS,
        )

        show_landing = (
            self.ball_vx < -0.5
            and self.ball_x > self.player_x + 10
            and self.match_config.difficulty != "专家"
            and not self.local_two_player
            and not self.match_over
        )
        if show_landing:
            time_to_paddle = (self.player_x - self.ball_x) / self.ball_vx
            predicted_y = self.ball_y + self.ball_vy * time_to_paddle
            predicted_y = clamp(predicted_y, PLAY_TOP, PLAY_BOTTOM)
            marker_x = self.player_x - 34
            c.coords(
                scene["landing"],
                marker_x - 11, predicted_y - 11,
                marker_x + 11, predicted_y + 11,
            )
            c.itemconfig(scene["landing"], state="normal")
        else:
            c.itemconfig(scene["landing"], state="hidden")

        game_no = min(
            self.match_config.best_of,
            self.player_games + self.cpu_games + 1,
        )
        if self.game_break > 0:
            c.itemconfig(
                scene["game_score"],
                text=f"第 {self.player_games + self.cpu_games} 局结束 · "
                     f"局分 {self.player_games} : {self.cpu_games}",
            )
        elif self.match_config.best_of > 1:
            c.itemconfig(
                scene["game_score"],
                text=f"第 {game_no} 局 · 局分 {self.player_games} : {self.cpu_games}",
            )
        elif self.match_config.mode == "challenge":
            c.itemconfig(scene["game_score"], text="挑战模式 · 一局定胜负")
        elif self.match_config.mode == "training":
            c.itemconfig(
                scene["game_score"],
                text="训练模式 · " + TRAINING_INFO[self.training_type][0],
            )
        else:
            c.itemconfig(
                scene["game_score"],
                text=f"{self.match_config.mode.upper()} · 一局定胜负",
            )
        c.itemconfig(scene["score_player"], text=str(self.player_score))
        c.itemconfig(scene["score_cpu"], text=str(self.cpu_score))

        mode_info = ""
        if self.match_config.mode == "challenge":
            challenge = CHALLENGES.get(self.match_config.challenge_id)
            name = challenge.name if challenge else "挑战"
            if self.time_left > 0:
                seconds = max(0, int(math.ceil(self.time_left)))
                mode_info = f"{name} · 剩余 {seconds}s"
                c.itemconfig(
                    scene["mode_info"],
                    fill=RED if seconds <= 10 else MUTED,
                )
            else:
                mode_info = f"{name} · 先到 {self.win_score} 分"
                c.itemconfig(scene["mode_info"], fill=MUTED)
        elif self.match_config.mode == "tournament":
            mode_info = (
                f"锦标赛 · {self._tournament_round_name(self.match_config.tournament_round)}"
                f" · {self.match_config.difficulty}"
            )
            c.itemconfig(scene["mode_info"], fill=MUTED)
        elif self.match_config.mode == "training":
            mode_info = "训练模式 · " + TRAINING_INFO[self.training_type][0]
            c.itemconfig(scene["mode_info"], fill=CYAN)
        elif self.local_two_player:
            mode_info = f"本地双人 · P1 {self.selected} vs P2 {opponent.name}"
            c.itemconfig(scene["mode_info"], fill=CYAN)
        else:
            mode_info = f"AI 难度：{self.match_config.difficulty}"
            c.itemconfig(scene["mode_info"], fill=MUTED)
        c.itemconfig(scene["mode_info"], text=mode_info)

        c.itemconfig(
            scene["left_info"],
            text=f"PERFECT {self.perfect_count} · 扣杀 {self.smash_count}",
        )
        if self.serve_pending:
            if self.serve_owner == "player":
                serve_info = "你的发球"
            elif self.local_two_player:
                serve_info = "P2 发球"
            else:
                serve_info = "对手发球"
        else:
            serve_info = f"回合 {self.rally}"
        c.itemconfig(scene["serve_info"], text=serve_info)

        spin_label = "平击"
        if self.ball_spin > 0.04:
            spin_label = "上旋"
        elif self.ball_spin < -0.04:
            spin_label = "下旋"
        speed = int(math.hypot(self.ball_vx, self.ball_vy) * 8)
        if self.training_type:
            rally_text = f"练习回合 {self.rally} · 球速 {speed}"
        else:
            left_label = "P1" if self.local_two_player else "你"
            right_label = "P2" if self.local_two_player else "对手"
            rally_text = (
                f"回合 {self.rally} · {spin_label} · 球速 {speed}"
                + (
                    f" · {left_label} 连得 {self.player_streak}"
                    if self.player_streak >= 2 else ""
                )
                + (
                    f" · {right_label} 连得 {self.cpu_streak}"
                    if self.cpu_streak >= 2 else ""
                )
            )
        c.itemconfig(scene["rally"], text=rally_text)

        bx, by, bw, bh = STAMINA_BAR
        stamina_ratio = pct(self.stamina, self.max_stamina)
        c.coords(
            scene["stamina_fill"],
            bx + 2, by + 2, bx + 2 + (bw - 4) * stamina_ratio, by + bh - 2,
        )
        c.itemconfig(
            scene["stamina_fill"],
            fill=GREEN if stamina_ratio > 0.35 else RED,
        )
        ex, ey, ew, eh = ENERGY_BAR
        energy_ratio = pct(self.skill_energy, SKILL_ENERGY)
        c.coords(
            scene["energy_fill"],
            ex + 2, ey + 2, ex + 2 + (ew - 4) * energy_ratio, ey + eh - 2,
        )
        c.itemconfig(
            scene["energy_fill"],
            fill=GOLD if energy_ratio >= 1.0 else CYAN,
        )

        if self.local_two_player:
            p2_stamina_ratio = pct(self.p2_stamina, self.p2_max_stamina)
            c.coords(
                scene["p2_stamina_fill"],
                782, 69, 782 + 156 * p2_stamina_ratio, 73,
            )
            p2_energy_ratio = pct(self.p2_energy, SKILL_ENERGY)
            c.coords(
                scene["p2_energy_fill"],
                782, 87, 782 + 156 * p2_energy_ratio, 91,
            )
            for key in (
                "p2_stamina_label", "p2_stamina_bg", "p2_stamina_fill",
                "p2_energy_label", "p2_energy_bg", "p2_energy_fill",
            ):
                c.itemconfig(scene[key], state="normal")
        else:
            for key in (
                "p2_stamina_label", "p2_stamina_bg", "p2_stamina_fill",
                "p2_energy_label", "p2_energy_bg", "p2_energy_fill",
            ):
                c.itemconfig(scene[key], state="hidden")

        if self.smash_cooldown <= 0 and self.stamina >= SMASH_COST:
            smash_text = "J 扣杀就绪"
            smash_color = GOLD
        elif self.smash_cooldown > 0:
            smash_text = f"J 扣杀冷却 {self.smash_cooldown:.1f}s"
            smash_color = MUTED
        else:
            smash_text = "J 扣杀：体力不足"
            smash_color = MUTED
        if self.skill_energy >= SKILL_ENERGY:
            skill_text = " · E 技能就绪"
            skill_color = GOLD
        else:
            skill_text = f" · E 能量 {int(self.skill_energy)}%"
            skill_color = smash_color
        if self.local_two_player:
            smash_text = "P1 " + smash_text
        c.itemconfig(
            scene["smash_hint"], text=smash_text + skill_text, fill=skill_color,
        )

        if self.timing_timer > 0:
            c.coords(scene["timing"], self.timing_x, self.timing_y)
            c.itemconfig(
                scene["timing"], text=self.timing_text,
                fill=self.timing_color, state="normal",
            )
        else:
            c.itemconfig(scene["timing"], state="hidden")

        c.itemconfig(
            scene["message"], text=self.message,
            state="normal"
            if self.message and not self.serve_pending and self.game_break <= 0
            else "hidden",
        )
        c.itemconfig(
            scene["smash_flash"],
            state="normal" if self.smash_flash > 0 else "hidden",
        )
        c.itemconfig(
            scene["skill_flash"], text=f"技能发动：{p.skill}！",
            state="normal" if self.skill_flash > 0 else "hidden",
        )
        c.itemconfig(
            scene["p2_flash"], text=f"P2 爆发：{opponent.skill}！",
            state="normal" if self.p2_flash > 0 else "hidden",
        )

        banner_text = ""
        banner_color = GOLD
        if not self.training_type and not self.match_over:
            player_game_point = (
                self.player_score >= self.win_score - 1
                and self.player_score > self.cpu_score
            )
            cpu_game_point = (
                self.cpu_score >= self.win_score - 1
                and self.cpu_score > self.player_score
            )
            player_match_point = (
                player_game_point
                and self.player_games == self.games_to_win - 1
            )
            cpu_match_point = (
                cpu_game_point
                and self.cpu_games == self.games_to_win - 1
            )
            if player_match_point:
                banner_text = "赛点"
            elif cpu_match_point:
                banner_text = "对手赛点"
                banner_color = RED
            elif player_game_point:
                banner_text = "局点"
            elif cpu_game_point:
                banner_text = "对手局点"
                banner_color = RED
        if banner_text and not self.serve_pending:
            c.itemconfig(
                scene["banner"], text=banner_text, fill=banner_color,
                state="normal",
            )
        else:
            c.itemconfig(scene["banner"], state="hidden")

        show_serve = self.serve_pending and self.game_break <= 0 and not self.paused
        serve_state = "normal" if show_serve else "hidden"
        for key in ("serve_box", "serve_title", "serve_sub", "serve_hint"):
            c.itemconfig(scene[key], state=serve_state)
        if show_serve:
            if self.serve_owner == "player":
                title = "准备发球"
                sub = f"{self.serve_style} · 落点：{self._serve_target_label()}"
                hint = "空格发球 · 1/2/3 换旋转 · WASD 调落点"
            elif self.local_two_player:
                title = "P2 发球"
                sub = "P2 正在发球……"
                hint = "观察来球，准备接发球"
            else:
                title = "对手发球"
                sub = "对手正在发球……"
                hint = "观察旋转，准备接发球"
            c.itemconfig(scene["serve_title"], text=title)
            c.itemconfig(scene["serve_sub"], text=sub)
            c.itemconfig(scene["serve_hint"], text=hint)

        reticle_state = "normal" if show_serve and self.serve_owner == "player" else "hidden"
        for key in ("serve_circle", "serve_cross_x", "serve_cross_y"):
            c.itemconfig(scene[key], state=reticle_state)
        if reticle_state == "normal":
            tx, ty = self.serve_target_x, self.serve_target_y
            radius = 14
            c.coords(
                scene["serve_circle"],
                tx - radius, ty - radius, tx + radius, ty + radius,
            )
            c.coords(scene["serve_cross_x"], tx - 22, ty, tx + 22, ty)
            c.coords(scene["serve_cross_y"], tx, ty - 22, tx, ty + 22)

        pause_state = "normal" if self.paused else "hidden"
        for key in ("pause_box", "pause_title", "pause_hint", "pause_sub"):
            c.itemconfig(scene[key], state=pause_state)
        if self.paused:
            c.itemconfig(
                scene["pause_sub"],
                text=f"音量 {int(float(self.data['volume']) * 100)}% · "
                     f"[ / ] 调节",
            )

        break_state = "normal" if self.game_break > 0 else "hidden"
        for key in ("break_box", "break_title", "break_sub", "break_hint"):
            c.itemconfig(scene[key], state=break_state)
        if self.game_break > 0:
            c.itemconfig(scene["break_title"], text="本局结束")
            c.itemconfig(scene["break_sub"], text=self.break_text)

        c.tag_raise("overlay")

    # -- screen shake -------------------------------------------------------

    def _reset_shake(self, force: bool = False) -> None:
        dx, dy = self._shake_offset
        if force or dx or dy:
            try:
                self.canvas.move("all", -dx, -dy)
            except tk.TclError:
                pass
            self._shake_offset = (0.0, 0.0)

    def _apply_shake(self) -> None:
        if self.screen != "game" or self.paused or self.shake <= 0:
            return
        magnitude = 4.5 * clamp(self.shake, 0.0, 1.0)
        dx = random.uniform(-magnitude, magnitude)
        dy = random.uniform(-magnitude, magnitude)
        self.canvas.move("all", dx, dy)
        self._shake_offset = (dx, dy)


    # -- serve --------------------------------------------------------------

    def _other_serve(self, owner: str) -> str:
        return "cpu" if owner == "player" else "player"

    def _aim_serve(self, dt: float) -> None:
        keys = self.keys
        speed = 260.0 * dt
        if "w" in keys or "up" in keys:
            self.serve_target_y -= speed
        if "s" in keys or "down" in keys:
            self.serve_target_y += speed
        if "a" in keys or "left" in keys:
            self.serve_target_x -= speed
        if "d" in keys or "right" in keys:
            self.serve_target_x += speed
        low_x, high_x, low_y, high_y = SERVE_TARGET_RANGE
        self.serve_target_x = clamp(self.serve_target_x, low_x, high_x)
        self.serve_target_y = clamp(self.serve_target_y, low_y, high_y)

    def _rotate_serve(self) -> None:
        if self.training_type:
            return
        self._serve_points += 1
        deuce = (
            self.player_score >= self.win_score - 1
            and self.cpu_score >= self.win_score - 1
        )
        if self._serve_points >= (1 if deuce else 2):
            self.serve_owner = self._other_serve(self.serve_owner)
            self._serve_points = 0

    def _reset_ball_for_serve(self, owner: str, delay: float = 0.0) -> None:
        self.ball_x = WIDTH / 2
        self.ball_y = HEIGHT / 2
        self.ball_vx = 0.0
        self.ball_vy = 0.0
        self.ball_spin = 0.0
        self.serve_pending = True
        self.serve_owner = owner
        self.serve_wait = delay if owner != "player" else 0.0
        self.rally = 0
        self.last_hit_side = ""

    def launch_ball(self, owner: str) -> None:
        if not self.serve_pending:
            return
        if owner == "player":
            style = SERVES[self.serve_style]
            target_x = self.serve_target_x
            target_y = self.serve_target_y
        else:
            style = SERVES[random.choice(list(SERVES))]
            target_x = random.uniform(110.0, 330.0)
            target_y = random.uniform(180.0, 480.0)

        dx = target_x - self.ball_x
        dy = target_y - self.ball_y
        angle = math.atan2(dy, dx)
        speed = style.speed
        if self.training_type:
            speed = 5.4 if self.training_type == "skill" else style.speed
        self.ball_vx = speed * math.cos(angle)
        self.ball_vy = speed * math.sin(angle)
        self.ball_spin = (
            random.choice((-1.0, 1.0)) * style.spin if style.spin else 0.0
        )
        self.serve_pending = False
        self.serve_wait = 0.0
        self.rally = 0
        self.last_hit_side = ""
        self.receiving_serve = owner != "player"
        self.message = f"{style.name}！"
        self._message_timer = 1.0
        self.sound.play("serve")
        self.particles.burst(self.ball_x, self.ball_y, GOLD, 5, 2.0, 2.5, 0.3)

    # -- player actions -----------------------------------------------------

    def _action_allowed(self) -> bool:
        return (
            self.screen == "game"
            and not self.paused
            and not self.serve_pending
            and not self.match_over
            and self.game_break <= 0
        )

    def _incoming_in_range(
        self, near: float, far: float, half_height: float
    ) -> bool:
        return (
            self.ball_vx < 0
            and self.player_x + near < self.ball_x < self.player_x + far
            and abs(self.ball_y - self.player_y) < half_height
        )

    def _p2_incoming_in_range(
        self, near: float, far: float, half_height: float
    ) -> bool:
        return (
            self.ball_vx > 0
            and self.cpu_x - far < self.ball_x < self.cpu_x - near
            and abs(self.ball_y - self.cpu_y) < half_height
        )

    def _in_skill_range(self, limit: float = 170.0) -> bool:
        return self.ball_vx < 0 and self.ball_x < self.player_x + limit

    def _show_timing(
        self, text: str, color: str, x: float, y: float, duration: float = 0.7
    ) -> None:
        self.timing_text = text
        self.timing_color = color
        self.timing_timer = duration
        self.timing_x = x
        self.timing_y = y

    def _register_hit(self, side: str, perfect: bool = False) -> None:
        self.rally += 1
        self.max_rally = max(self.max_rally, self.rally)
        if self._tracked_progress():
            self._bump_daily("rally", min(10, self.rally))
        if side == "player":
            p = PLAYERS[self.selected]
            gain = (7.0 + (4.0 if perfect else 0.0)) * p.energy_gain
            if p.name == "孙颖莎":
                gain += 3.0
            elif p.name == "新秀":
                gain += 2.0
            self.skill_energy = min(SKILL_ENERGY, self.skill_energy + gain)
            if perfect:
                self.perfect_count += 1
                if self._tracked_progress():
                    self._bump_stat("perfects")
        elif side == "p2":
            self.p2_energy = min(SKILL_ENERGY, self.p2_energy + 8.0)

    def _tracked_progress(self) -> bool:
        return self.match_config.mode not in ("training", "local")

    def try_smash(self) -> None:
        if not self._action_allowed():
            return
        if self.smash_cooldown > 0:
            self.message = f"扣杀冷却中：{self.smash_cooldown:.1f} 秒"
            self._message_timer = 1.0
            return
        if self.stamina < SMASH_COST and not self.training_type:
            self.message = "体力不足，无法扣杀！"
            self._message_timer = 1.0
            return
        if not self._incoming_in_range(12, 145, 78):
            self.message = "扣杀条件不满足：等球靠近并朝你飞来"
            self._message_timer = 1.0
            return

        p = PLAYERS[self.selected]
        if not self.training_type:
            self.stamina -= SMASH_COST
        self.smash_cooldown = SMASH_CD
        self.smash_flash = 0.45
        self.smash_count += 1
        if self._tracked_progress():
            self._bump_stat("smashes")
            self._bump_daily("smashes")
        self.shake = max(self.shake, 0.65)
        self.slowmo = 0.18
        self.sound.play("smash")
        relative = clamp((self.ball_y - self.player_y) / 70.0, -1.0, 1.0)
        power = SMASH_POWER * p.power * p.smash_bonus
        serve_attack = self.receiving_serve
        self.receiving_serve = False
        if serve_attack:
            power *= 1.08
        if p.name == "张继科" and pct(self.stamina, self.max_stamina) < 0.45:
            power *= 1.12
        speed = min(
            16.0,
            max(10.0, math.hypot(self.ball_vx, self.ball_vy) * power),
        )
        self.ball_x = self.player_x + 22
        self.ball_vx = speed
        self.ball_vy = relative * 3.2
        if self.selected == "许昕":
            self.ball_spin += relative * 0.10
        if self.selected == "梁靖崑":
            self.cpu_stun = 0.8
        perfect = abs(relative) < 0.25
        self._register_hit("player", perfect=perfect)
        self._show_timing(
            "PERFECT SMASH!" if perfect else "SMASH!",
            GOLD, self.player_x + 95, self.player_y - 75,
        )
        self.particles.burst(
            self.ball_x, self.ball_y, GOLD, 18, 5.5, 4.5, 0.55, 0.10
        )
        self.message = (
            f"接发球抢攻！{self.selected} 直接扣杀！" if serve_attack
            else f"{self.selected} 发动扣杀！"
        )
        self._message_timer = 1.2

    def try_chop(self) -> None:
        if not self._action_allowed():
            return
        if self.chop_cooldown > 0 or (
            self.stamina < CHOP_COST and not self.training_type
        ):
            self.message = "削球冷却中或体力不足"
            self._message_timer = 1.0
            return
        if not self._incoming_in_range(10, 155, 88):
            self.message = "削球需要等球靠近"
            self._message_timer = 1.0
            return

        p = PLAYERS[self.selected]
        if not self.training_type:
            self.stamina -= CHOP_COST
        self.chop_cooldown = CHOP_CD
        rel = clamp((self.ball_y - self.player_y) / 80.0, -1.0, 1.0)
        self.ball_x = self.player_x + 24
        self.ball_vx = 4.2 * p.power
        self.ball_vy = rel * 2.2
        self.ball_spin = -0.34 if self.selected == "许昕" else -0.24
        self.receiving_serve = False
        self._register_hit("player")
        self.sound.play("chop")
        self.shake = max(self.shake, 0.2)
        self.particles.burst(
            self.ball_x, self.ball_y, CYAN, 10, 3.0, 3.0, 0.4
        )
        self.message = f"{self.selected} 削球！下旋来袭"
        self._message_timer = 1.0

    def try_counterattack(self) -> None:
        if not self._action_allowed():
            return
        if self.counter_cooldown > 0 or (
            self.stamina < COUNTER_COST and not self.training_type
        ):
            self.message = "防守反击冷却中或体力不足"
            self._message_timer = 1.0
            return
        if not self._incoming_in_range(8, 125, 76):
            self.message = "时机不对：等来球进入防守范围"
            self._message_timer = 1.0
            return

        p = PLAYERS[self.selected]
        if not self.training_type:
            self.stamina -= COUNTER_COST
        self.counter_cooldown = COUNTER_CD
        self.ball_x = self.player_x + 24
        self.ball_vx = min(
            15.0,
            max(
                8.0,
                math.hypot(self.ball_vx, self.ball_vy)
                * p.counter_bonus * p.power,
            ),
        )
        self.ball_vy = clamp((self.ball_y - self.player_y) / 18.0, -4.5, 4.5)
        self.ball_spin = 0.08 if self.selected == "王曼昱" else 0.02
        if self.selected == "王曼昱":
            self.stamina = min(self.max_stamina, self.stamina + 5.0)
        self.receiving_serve = False
        self._register_hit("player")
        self.sound.play("counter")
        self.shake = max(self.shake, 0.3)
        self.particles.burst(
            self.ball_x, self.ball_y, GREEN, 12, 3.8, 3.2, 0.45
        )
        self.message = f"漂亮的防守反击！{self.selected} 抓住机会"
        self._message_timer = 1.0

    def try_player_skill(self) -> None:
        if not self._action_allowed():
            return
        if self.skill_energy < SKILL_ENERGY:
            self.message = f"技能能量不足：{int(self.skill_energy)}%"
            self._message_timer = 1.0
            return
        if self.stamina < SKILL_COST and not self.training_type:
            self.message = "体力不足，专属技能无法发动"
            self._message_timer = 1.0
            return

        if not self.training_type:
            self.stamina -= SKILL_COST
        self.skill_energy = 100.0 if self.training_type else 0.0
        self.skill_flash = 0.9
        self.skill_buff = 2.2
        self.shake = max(self.shake, 0.45)
        self.slowmo = 0.22
        self.receiving_serve = False
        if self._tracked_progress():
            self._bump_stat("skills")

        name = self.selected
        p = PLAYERS[name]

        if name == "张继科":
            self.ball_vx = max(self.ball_vx, 0.0) + 9.0 * p.power
            self.ball_vy = clamp(
                (self.ball_y - self.player_y) / 14.0, -5.0, 5.0
            )
        elif name == "许昕":
            self.ball_spin += random.choice((-1.0, 1.0)) * 0.42
            if self._in_skill_range(160):
                self.ball_vx = abs(self.ball_vx) * 1.12
        elif name == "樊振东":
            if self._in_skill_range():
                self.ball_x = self.player_x + 24
                self.ball_vx = min(
                    16.0, max(9.0, abs(self.ball_vx) * 1.6)
                )
        elif name == "梁靖崑":
            if self._in_skill_range():
                self.ball_x = self.player_x + 24
                self.ball_vx = min(
                    16.0, max(10.0, abs(self.ball_vx) * 1.8)
                )
                self.stamina = max(0.0, self.stamina - 5.0)
        elif name == "王楚钦":
            self.ball_spin += 0.18
            self.ball_vy += random.choice((-2.0, 2.0))
        elif name == "林诗栋":
            self.ball_vx *= 1.18
        elif name == "孙颖莎":
            self.player_x = min(300.0, self.player_x + 22.0)
            self.player_y = clamp(
                self.player_y + (self.ball_y - self.player_y) * 0.25,
                *PADDLE_Y_RANGE,
            )
            if self._in_skill_range():
                self.ball_x = self.player_x + 24
                self.ball_vx = abs(self.ball_vx) * 1.25
        elif name in ("马龙", "陈梦", "王曼昱"):
            self.skill_buff = 3.5
            if (
                name == "王曼昱"
                and self.ball_vx < 0
                and self.ball_x < self.player_x + 165
            ):
                self.ball_x = self.player_x + 24
                self.ball_vx = abs(self.ball_vx) * 1.4
        elif name == "伊藤美诚":
            self.ball_spin += random.choice((-1.0, 1.0)) * 0.55
            self.ball_vy += random.choice((-3.0, 3.0))

        self.sound.play("skill")
        self.particles.burst(
            self.player_x + 20, self.player_y, p.color, 26, 6.0, 5.0, 0.7
        )
        self.message = f"{p.skill}！{QUOTES.get(name, ('', ''))[0]}"
        self._message_timer = 1.4

    # -- local P2 actions ---------------------------------------------------

    def try_p2_smash(self) -> None:
        if not self._local_action_allowed():
            return
        if self.p2_smash_cooldown > 0:
            self.message = f"P2 扣杀冷却：{self.p2_smash_cooldown:.1f}s"
            self._message_timer = 1.0
            return
        if self.p2_stamina < SMASH_COST:
            self.message = "P2 体力不足"
            self._message_timer = 1.0
            return
        if not self._p2_incoming_in_range(12, 145, 78):
            self.message = "P2 扣杀时机不对"
            self._message_timer = 1.0
            return

        p = PLAYERS[self.match_config.opponent]
        self.p2_stamina -= SMASH_COST
        self.p2_smash_cooldown = SMASH_CD
        self.p2_flash = 0.55
        self.shake = max(self.shake, 0.55)
        self.sound.play("smash")
        relative = clamp((self.ball_y - self.cpu_y) / 70.0, -1.0, 1.0)
        speed = min(
            16.0,
            max(9.0, math.hypot(self.ball_vx, self.ball_vy)
                * SMASH_POWER * p.power),
        )
        self.ball_x = self.cpu_x - 22
        self.ball_vx = -speed
        self.ball_vy = relative * 3.2
        self._register_hit("p2", perfect=abs(relative) < 0.25)
        self.particles.burst(
            self.ball_x, self.ball_y, p.color, 16, 5.0, 4.0, 0.5
        )
        self.message = f"P2 {p.name} 扣杀！"
        self._message_timer = 1.0

    def try_p2_chop(self) -> None:
        if not self._local_action_allowed():
            return
        if self.p2_chop_cooldown > 0 or self.p2_stamina < CHOP_COST:
            self.message = "P2 削球冷却中或体力不足"
            self._message_timer = 1.0
            return
        if not self._p2_incoming_in_range(10, 155, 88):
            self.message = "P2 削球需要等球靠近"
            self._message_timer = 1.0
            return

        p = PLAYERS[self.match_config.opponent]
        self.p2_stamina -= CHOP_COST
        self.p2_chop_cooldown = CHOP_CD
        relative = clamp((self.ball_y - self.cpu_y) / 80.0, -1.0, 1.0)
        self.ball_x = self.cpu_x - 24
        self.ball_vx = -4.2 * p.power
        self.ball_vy = relative * 2.2
        self.ball_spin = 0.24
        self._register_hit("p2")
        self.sound.play("chop")
        self.particles.burst(
            self.ball_x, self.ball_y, p.color, 10, 3.0, 3.0, 0.4
        )
        self.message = f"P2 {p.name} 削球！"
        self._message_timer = 1.0

    def try_p2_counter(self) -> None:
        if not self._local_action_allowed():
            return
        if self.p2_counter_cooldown > 0 or self.p2_stamina < COUNTER_COST:
            self.message = "P2 防反冷却中或体力不足"
            self._message_timer = 1.0
            return
        if not self._p2_incoming_in_range(8, 125, 76):
            self.message = "P2 防反时机不对"
            self._message_timer = 1.0
            return

        p = PLAYERS[self.match_config.opponent]
        self.p2_stamina -= COUNTER_COST
        self.p2_counter_cooldown = COUNTER_CD
        self.ball_x = self.cpu_x - 24
        self.ball_vx = -min(
            15.0,
            max(8.0, math.hypot(self.ball_vx, self.ball_vy)
                * p.counter_bonus * p.power),
        )
        self.ball_vy = clamp((self.ball_y - self.cpu_y) / 18.0, -4.5, 4.5)
        self.ball_spin = -0.02
        self._register_hit("p2")
        self.sound.play("counter")
        self.particles.burst(
            self.ball_x, self.ball_y, p.color, 12, 3.8, 3.2, 0.45
        )
        self.message = f"P2 {p.name} 防守反击！"
        self._message_timer = 1.0

    def try_p2_skill(self) -> None:
        if not self._local_action_allowed():
            return
        if self.ball_x < WIDTH * 0.5:
            self.message = "P2 爆发需要球在己方半场"
            self._message_timer = 1.0
            return
        if self.p2_energy < SKILL_ENERGY:
            self.message = f"P2 能量不足：{int(self.p2_energy)}%"
            self._message_timer = 1.0
            return
        p = PLAYERS[self.match_config.opponent]
        self.p2_energy = 0.0
        self.p2_flash = 0.9
        self.shake = max(self.shake, 0.4)
        self.ball_vx = -min(17.0, max(9.0, abs(self.ball_vx) * 1.55))
        self.ball_vy += random.choice((-2.5, 2.5))
        self.ball_spin += random.choice((-1.0, 1.0)) * 0.25
        self.sound.play("skill")
        self.particles.burst(
            self.cpu_x - 20, self.cpu_y, p.color, 24, 6.0, 5.0, 0.7
        )
        self.message = f"P2 爆发：{p.name} 全力一击！"
        self._message_timer = 1.2

    def _local_action_allowed(self) -> bool:
        return (
            self.local_two_player
            and self._action_allowed()
        )


    # -- timers / movement --------------------------------------------------

    def _tick_timers(self, dt: float) -> None:
        self.smash_cooldown = max(0.0, self.smash_cooldown - dt)
        self.chop_cooldown = max(0.0, self.chop_cooldown - dt)
        self.counter_cooldown = max(0.0, self.counter_cooldown - dt)
        self.p2_smash_cooldown = max(0.0, self.p2_smash_cooldown - dt)
        self.p2_chop_cooldown = max(0.0, self.p2_chop_cooldown - dt)
        self.p2_counter_cooldown = max(0.0, self.p2_counter_cooldown - dt)
        self.skill_flash = max(0.0, self.skill_flash - dt)
        self.skill_buff = max(0.0, self.skill_buff - dt)
        self.smash_flash = max(0.0, self.smash_flash - dt)
        self.p2_flash = max(0.0, self.p2_flash - dt)
        self.timing_timer = max(0.0, self.timing_timer - dt)
        self.shake = max(0.0, self.shake - dt * 4.0)
        self.cpu_stun = max(0.0, self.cpu_stun - dt)
        if self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self.message = ""

    def _move_player(self, dt: float) -> None:
        p = PLAYERS[self.selected]
        keys = self.keys
        arrow = not self.local_two_player
        up = "w" in keys or (arrow and "up" in keys)
        down = "s" in keys or (arrow and "down" in keys)
        forward = "d" in keys or (arrow and "right" in keys)
        back = "a" in keys or (arrow and "left" in keys)
        sprinting = "shift_l" in keys or "shift_r" in keys

        moving = up or down or forward or back
        sprint = (
            sprinting and moving and self.stamina > 0.5
            and not self.training_type
        )
        speed_factor = SPRINT_FACTOR if sprint else 1.0
        if self.skill_buff > 0 and p.skill_move_buff:
            speed_factor *= SKILL_MOVE_FACTOR
        speed = BASE_MOVE_SPEED * p.speed * speed_factor * dt * 60.0

        if self.training_type:
            self.stamina = self.max_stamina
        elif sprint:
            self.stamina = max(0.0, self.stamina - SPRINT_DRAIN * dt)
        else:
            self.stamina = min(
                self.max_stamina, self.stamina + STAMINA_REGEN * dt
            )

        if up:
            self.player_y -= speed
        if down:
            self.player_y += speed
        if back:
            self.player_x -= speed
        if forward:
            self.player_x += speed
        self.player_x = clamp(self.player_x, *PLAYER_X_RANGE)
        self.player_y = clamp(self.player_y, *PADDLE_Y_RANGE)

    def _move_p2(self, dt: float) -> None:
        p = PLAYERS[self.match_config.opponent]
        keys = self.keys
        up = "up" in keys
        down = "down" in keys
        left = "left" in keys
        right = "right" in keys
        stun = 0.45 if self.cpu_stun > 0 else 1.0
        speed = BASE_MOVE_SPEED * p.speed * stun * dt * 60.0
        if up:
            self.cpu_y -= speed
        if down:
            self.cpu_y += speed
        if left:
            self.cpu_x -= speed
        if right:
            self.cpu_x += speed
        self.cpu_x = clamp(self.cpu_x, *CPU_X_RANGE)
        self.cpu_y = clamp(self.cpu_y, *PADDLE_Y_RANGE)
        if self.training_type:
            self.p2_stamina = self.p2_max_stamina
        else:
            self.p2_stamina = min(
                self.p2_max_stamina, self.p2_stamina + STAMINA_REGEN * dt
            )

    def _move_cpu(self, dt: float) -> None:
        cpu = PLAYERS[self.match_config.opponent]
        diff = DIFFICULTIES[self.match_config.difficulty]
        stun = 0.45 if self.cpu_stun > 0 else 1.0
        ai_speed = (
            (AI_BASE_SPEED + AI_SPEED_FACTOR * cpu.speed)
            * diff.ai_scale * cpu.ai_speed * dt * 60.0 * stun
        )
        target_y = self.ball_y + self.ball_vy * diff.prediction
        if diff.aim_noise:
            target_y += random.uniform(-diff.aim_noise, diff.aim_noise)
        target_y += random.uniform(-1.0, 1.0) * cpu.ai_error * 9.0

        if self.cpu_y < target_y - 10:
            self.cpu_y += min(ai_speed, target_y - self.cpu_y)
        elif self.cpu_y > target_y + 10:
            self.cpu_y -= min(ai_speed, self.cpu_y - target_y)

        target_x = WIDTH - 145.0
        if self.ball_x > WIDTH * 0.56:
            target_x = clamp(self.ball_x + 80.0, *CPU_X_RANGE)
        track = AI_TRACK_X_SPEED * dt * 60.0 * stun
        if self.cpu_x < target_x - 8:
            self.cpu_x += min(track, target_x - self.cpu_x)
        elif self.cpu_x > target_x + 8:
            self.cpu_x -= min(track, self.cpu_x - target_x)
        self.cpu_x = clamp(self.cpu_x, *CPU_X_RANGE)
        self.cpu_y = clamp(self.cpu_y, *PADDLE_Y_RANGE)

    # -- ball physics -------------------------------------------------------

    def update(self, dt: float) -> None:
        if self.screen != "game" or self.paused:
            return
        real_dt = min(dt, MAX_FRAME_DT)
        if self.slowmo > 0:
            self.slowmo = max(0.0, self.slowmo - real_dt)
            dt = real_dt * 0.45
        else:
            dt = real_dt
        self.match_time += dt
        self.particles.update(dt)
        self._tick_timers(dt)

        if self.game_break > 0:
            self.game_break -= dt
            if self.game_break <= 0:
                self._start_next_game()
            return
        if self.match_over:
            return
        if self.time_left > 0:
            self.time_left -= dt
            if self.time_left <= 0:
                self.end_match(False, "时间到")
                return
        if self.serve_pending:
            if self.serve_owner == "player":
                self._aim_serve(dt)
            else:
                self.serve_wait -= dt
                if self.serve_wait <= 0:
                    self.launch_ball(self.serve_owner)
            return

        self._move_player(dt)
        if self.local_two_player:
            self._move_p2(dt)
        else:
            self._move_cpu(dt)
        self._advance_ball(dt)

    def _start_next_game(self) -> None:
        self.player_score = 0
        self.cpu_score = 0
        self.serve_owner = self._other_serve(self._game_first_server)
        self._game_first_server = self.serve_owner
        self._serve_points = 0
        self._reset_ball_for_serve(
            self.serve_owner, 0.8 if self.serve_owner != "player" else 0.0
        )
        self.game_break = 0.0
        self.break_text = ""
        self.shake = 0.0
        self.sound.play("break")
        self.message = (
            f"第 {self.player_games + self.cpu_games + 1} 局开始"
        )
        self._message_timer = 1.2

    def _advance_ball(self, dt: float) -> None:
        frame = dt * 60.0
        self.ball_vy += self.ball_spin * frame
        self.ball_spin *= 0.992 ** frame

        self._trail_tick += 1
        if self._trail_tick % 2 == 0:
            self.particles.trail(self.ball_x, self.ball_y, GOLD)

        old_x = self.ball_x
        self.ball_x += self.ball_vx * frame
        self.ball_y += self.ball_vy * frame

        if self.ball_y <= PLAY_TOP:
            self.ball_y = PLAY_TOP
            self.ball_vy = abs(self.ball_vy)
        elif self.ball_y >= PLAY_BOTTOM:
            self.ball_y = PLAY_BOTTOM
            self.ball_vy = -abs(self.ball_vy)

        if (
            self.ball_vx < 0
            and old_x >= self.player_x - PADDLE_W / 2
            and self._overlaps_paddle(self.player_x, self.player_y)
        ):
            self.ball_x = self.player_x + PADDLE_W / 2 + BALL_RADIUS
            self._bounce_from_paddle("player", 1)

        right_side = "p2" if self.local_two_player else "cpu"
        if (
            self.ball_vx > 0
            and old_x <= self.cpu_x + PADDLE_W / 2
            and self._overlaps_paddle(self.cpu_x, self.cpu_y)
        ):
            self.ball_x = self.cpu_x - PADDLE_W / 2 - BALL_RADIUS
            self._bounce_from_paddle(right_side, -1)

        if self.training_type:
            if self.ball_x < 20 or self.ball_x > WIDTH - 20:
                self._training_reset()
        elif self.ball_x < 20:
            self.score_point(False)
        elif self.ball_x > WIDTH - 20:
            self.score_point(True)

    def _training_reset(self) -> None:
        owner = "player" if self.training_type == "serve" else "cpu"
        self._reset_ball_for_serve(
            owner, 0.9 if owner != "player" else 0.0
        )
        self.stamina = self.max_stamina
        self.p2_stamina = self.p2_max_stamina
        if self.training_type == "skill":
            self.skill_energy = SKILL_ENERGY
        self.message = "继续练习：调整站位，准备下一球。"
        self._message_timer = 1.4

    def _overlaps_paddle(self, paddle_x: float, paddle_y: float) -> bool:
        closest_x = clamp(
            self.ball_x, paddle_x - PADDLE_W / 2, paddle_x + PADDLE_W / 2
        )
        closest_y = clamp(
            self.ball_y, paddle_y - PADDLE_H / 2, paddle_y + PADDLE_H / 2
        )
        dx = self.ball_x - closest_x
        dy = self.ball_y - closest_y
        return dx * dx + dy * dy <= BALL_RADIUS * BALL_RADIUS

    def _bounce_from_paddle(self, side: str, direction: int) -> None:
        if side == "player":
            player = PLAYERS[self.selected]
        else:
            player = PLAYERS[self.match_config.opponent]

        relative = clamp(
            (self.ball_y - (
                self.player_y if side == "player" else self.cpu_y
            )) / 55.0, -1.0, 1.0,
        )
        offset = abs(relative)
        perfect = side in ("player", "p2") and offset <= 0.20
        good = side in ("player", "p2") and offset <= 0.55
        control = player.control
        if side == "player" and self.selected == "陈梦":
            if pct(self.stamina, self.max_stamina) < 0.5:
                control *= 1.08

        if side == "player":
            self.receiving_serve = False

        self._register_hit(side, perfect=perfect)
        speed_factor = 1.12 if perfect else 1.04 if good else 1.0

        name = player.name
        if side == "player":
            if name == "马龙" and self.rally >= 3:
                speed_factor *= 1.04
                self.stamina = min(self.max_stamina, self.stamina + 1.2)
            elif name == "张继科" and pct(self.stamina, self.max_stamina) < 0.45:
                speed_factor *= 1.08
            elif name == "樊振东" and self.player_x > 220:
                speed_factor *= 1.06
            elif name == "王楚钦" and abs(self.ball_y - HEIGHT / 2) > 110:
                speed_factor *= 1.05
            elif name == "林诗栋" and self.rally >= 3:
                speed_factor *= 1.03

        angle = relative * (0.88 / max(0.85, control))
        if perfect:
            angle *= 0.92
        speed = min(
            13.0,
            min(11.5, math.hypot(self.ball_vx, self.ball_vy) + 0.25)
            * player.power,
        )
        speed = min(15.0, speed * speed_factor)
        self.ball_vx = direction * speed * math.cos(angle)
        self.ball_vy = speed * math.sin(angle)

        spin_factor = player.player_spin if side == "player" else player.ai_spin
        if spin_factor:
            self.ball_spin = relative * spin_factor
        if side == "player" and name == "许昕" and self.rally >= 2:
            self.ball_spin += 0.035
        if side == "player" and name == "伊藤美诚" and self.rally % 3 == 0:
            self.ball_spin += random.choice((-0.08, 0.08))
            speed *= 1.03

        if side == "cpu":
            aggression = player.ai_aggression
            if random.random() < aggression * 0.30:
                self.ball_vx *= 1.08
                self.ball_vy += (self.player_y - self.ball_y) * 0.003
                self.message = f"{player.name} 抢攻！"
                self._message_timer = 0.8
            if random.random() < player.ai_error * (
                1.35 - DIFFICULTIES[self.match_config.difficulty].ai_scale * 0.25
            ):
                self.ball_vx *= 0.93
                self.ball_vy += random.uniform(-1.8, 1.8)
            self.ball_vx *= player.ai_return_speed
            self.ball_vy *= player.ai_return_vy

        if side == "cpu":
            self.sound.play("hit")
        elif perfect:
            self.sound.play("perfect")
            self.shake = max(self.shake, 0.16)
            self.particles.burst(
                self.ball_x, self.ball_y, GOLD, 12, 4.0, 3.5, 0.5
            )
        else:
            self.sound.play("hit")
            self.particles.burst(
                self.ball_x, self.ball_y, player.color, 5, 2.5, 2.5, 0.3
            )

        if side == "player":
            self._show_timing(
                "PERFECT!" if perfect else "GOOD" if good else "",
                GOLD if perfect else CYAN,
                self.player_x + 88, self.player_y - 70,
                0.65 if (perfect or good) else 0.0,
            )
        elif side == "p2":
            self._show_timing(
                "P2 PERFECT!" if perfect else "P2 GOOD" if good else "",
                GOLD if perfect else CYAN,
                self.cpu_x - 88, self.cpu_y - 70,
                0.65 if (perfect or good) else 0.0,
            )
        self.last_hit_side = side

    # -- scoring / match end ------------------------------------------------

    def score_point(self, player_scored: bool) -> None:
        if self.training_type:
            self._training_reset()
            return
        if self.match_over or self.game_break > 0:
            return

        if player_scored:
            self.player_score += 1
            self.player_streak += 1
            self.cpu_streak = 0
            self.skill_energy = min(SKILL_ENERGY, self.skill_energy + 12.0)
        else:
            self.cpu_score += 1
            self.cpu_streak += 1
            self.player_streak = 0
            self.skill_energy = min(SKILL_ENERGY, self.skill_energy + 5.0)

        self.sound.play("score")
        self.shake = max(self.shake, 0.35)
        self.particles.confetti(self.ball_x, self.ball_y)
        self.message = "P1 得分！" if player_scored else "P2 得分！"
        if not self.local_two_player:
            self.message = "得分！" if player_scored else "对手得分"
        self._message_timer = 1.0

        game_finished = (
            max(self.player_score, self.cpu_score) >= self.win_score
            and abs(self.player_score - self.cpu_score) >= 2
        )
        if game_finished:
            if player_scored:
                self.player_games += 1
            else:
                self.cpu_games += 1
            self.ball_vx = 0.0
            self.ball_vy = 0.0
            self.serve_pending = True
            self.serve_wait = 0.0
            if (
                self.player_games >= self.games_to_win
                or self.cpu_games >= self.games_to_win
            ):
                self.end_match(self.player_games > self.cpu_games)
                return
            self.game_break = 1.5
            self.break_text = (
                f"局分 {self.player_games} : {self.cpu_games} · "
                f"第 {self.player_games + self.cpu_games + 1} 局即将开始"
            )
            self.sound.play("break")
            return

        self._rotate_serve()
        owner = self.serve_owner
        self._reset_ball_for_serve(
            owner, 0.85 if owner != "player" else 0.0
        )

    def _sim_winner(self, name_a: str, name_b: str) -> str:
        a = PLAYERS[name_a]
        b = PLAYERS[name_b]
        score_a = (
            a.power * 1.15 + a.speed + a.control * 1.1
            + a.ai_aggression * 0.5 + random.uniform(0.0, 1.8)
        )
        score_b = (
            b.power * 1.15 + b.speed + b.control * 1.1
            + b.ai_aggression * 0.5 + random.uniform(0.0, 1.8)
        )
        return name_a if score_a >= score_b else name_b

    def _simulate_champion(self, winners: list) -> str:
        current = list(winners)
        while len(current) > 1:
            next_round = []
            for index in range(0, len(current), 2):
                next_round.append(
                    self._sim_winner(current[index], current[index + 1])
                )
            current = next_round
        return current[0] if current else "未知"

    def _finish_tournament_match(self, won: bool) -> tuple:
        t = self.data.get("tournament")
        if not t:
            return (0, 0, 0), ""
        players = list(t["players"])
        slot = int(t["player_slot"])
        round_index = int(t["round"])
        player_name = t.get("player", self.selected)
        opponent = players[slot ^ 1]
        player_pair = slot // 2
        winners = []
        for index in range(0, len(players), 2):
            pair = index // 2
            a, b = players[index], players[index + 1]
            if pair == player_pair:
                winner = player_name if won else (
                    b if a == player_name else a
                )
            else:
                winner = self._sim_winner(a, b)
            winners.append(winner)

        t.setdefault("history", []).append({
            "round": round_index,
            "opponent": opponent,
            "won": won,
            "score": f"{self.player_games}:{self.cpu_games}",
        })

        if won:
            if round_index >= 2:
                t["champion"] = player_name
                t["active"] = False
                t["done"] = True
                self.data["trophies"] += 1
                rewards = (300, 2, 80)
                note = "锦标赛冠军！奖杯 + 300 金币 + 2 招募券 + 80 碎片"
            else:
                t["players"] = winners
                t["player_slot"] = player_pair
                t["round"] = round_index + 1
                coins = 60 + round_index * 30
                shards = 10 + round_index * 5
                rewards = (coins, 0, shards)
                note = (
                    f"晋级{self._tournament_round_name(round_index + 1)}！"
                    f" 奖励 {coins} 金币 + {shards} 碎片"
                )
        else:
            t["champion"] = self._simulate_champion(winners)
            t["active"] = False
            t["done"] = True
            rewards = (20, 0, 0)
            note = (
                f"止步{self._tournament_round_name(round_index)}，"
                f"冠军由 {t['champion']} 获得。"
            )
        self.save.save()
        return rewards, note

    def end_match(self, won: bool, subtitle: str = "") -> None:
        if self.match_over:
            return
        self._ensure_periods()
        self.match_over = True
        self.paused = False
        self.keys.clear()

        mode = self.match_config.mode
        coins = tickets = shards = 0
        note = subtitle
        rewards = (0, 0, 0)
        self.message = ""
        self._message_timer = 0.0

        if mode == "quick":
            if won:
                coins = 40 + DIFF_ORDER.index(self.match_config.difficulty) * 10
                tickets = 1
                note = subtitle
            else:
                coins = 10
                note = subtitle
            rewards = (coins, tickets, shards)
        elif mode == "challenge":
            challenge = CHALLENGES.get(self.match_config.challenge_id)
            if challenge and won:
                coins = challenge.coins
                tickets = challenge.tickets
                shards = challenge.shards
                daily = self._daily_challenge_id()
                if (
                    challenge.cid == daily
                    and not self.data["daily_challenge"].get("claimed")
                ):
                    coins *= 2
                    self.data["daily_challenge"]["claimed"] = True
                    note = "今日双倍奖励已领取！"
                else:
                    note = note or "挑战完成！"
                self.data["challenge_wins"][challenge.cid] = (
                    int(self.data["challenge_wins"].get(challenge.cid, 0)) + 1
                )
            elif challenge:
                note = note or "再试一次，调整站位和体力分配。"
            rewards = (coins, tickets, shards)
        elif mode == "tournament":
            rewards, tournament_note = self._finish_tournament_match(won)
            coins, tickets, shards = rewards
            note = subtitle or tournament_note
        elif mode == "local":
            rewards = (0, 0, 0)
            note = "本地双人模式不记录奖励，再来一局吧。"

        if mode not in ("local", "training"):
            self._bump_stat("matches")
            if won:
                self._bump_stat("wins")
                self._bump_daily("wins")
                self.data["weekly"]["wins"] = (
                    int(self.data["weekly"].get("wins", 0)) + 1
                )
            else:
                self._bump_stat("losses")
            self.data["stats"]["best_rally"] = max(
                int(self.data["stats"].get("best_rally", 0)), self.max_rally
            )
            old_level = mastery_level(
                int(self.save.mastery_entry(self.selected).get("xp", 0))
            )
            self._record_mastery(self.selected, won)
            new_level = mastery_level(
                int(self.save.mastery_entry(self.selected).get("xp", 0))
            )
            if new_level > old_level:
                note = (
                    f"{note} · " if note else ""
                ) + f"熟练度提升至 Lv.{new_level}"
            self.save.grant(coins, tickets, shards)
            self.save.save()

        if mode == "local":
            title = "P1 获胜！" if won else "P2 获胜！"
        elif mode == "tournament":
            t = self.data.get("tournament") or {}
            if won and t.get("champion") == t.get("player"):
                title = "锦标赛冠军！"
            elif won:
                title = "晋级成功！"
            else:
                title = "锦标赛结束"
        elif mode == "challenge":
            title = "挑战成功！" if won else "挑战失败"
        elif mode == "training":
            title = "训练结束"
        else:
            title = "比赛胜利！" if won else "比赛失利"

        if self.match_config.best_of > 1:
            score = f"局分 {self.player_games} : {self.cpu_games}"
        else:
            score = f"{self.player_score} : {self.cpu_score}"

        self.last_result = {
            "won": won,
            "mode": mode,
            "title": title,
            "score": score,
            "subtitle": note,
            "rewards": rewards,
            "challenge_id": self.match_config.challenge_id,
        }
        if won and mode not in ("local", "training"):
            self._toast(QUOTES.get(self.selected, ("", ""))[1], 3.0)
        self.screen = "result"
        self._scene = None
        self.particles.clear()
        self.sound.play("win" if won else "lose")
        self.draw()


    # -- main loop ----------------------------------------------------------

    def loop(self) -> None:
        now = time.perf_counter()
        dt = now - self.last_tick
        self.last_tick = now

        if self.screen == "game":
            if not self.paused:
                self.update(dt)
            self.draw()
        elif self._message_timer > 0:
            self._message_timer -= dt
            if self._message_timer <= 0:
                self.message = ""
                self.draw()

        self.root.after(FPS_MS, self.loop)


def main() -> None:
    root = tk.Tk()
    TableTennisGame(root)
    root.mainloop()


if __name__ == "__main__":
    main()
