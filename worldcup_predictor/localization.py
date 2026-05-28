from __future__ import annotations

import csv
from datetime import datetime, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

PROJECT_ROOT = Path(__file__).resolve().parents[1]
TRANSLATION_PATH = PROJECT_ROOT / "data/name_translations.csv"
BEIJING_TZ = ZoneInfo("Asia/Shanghai")
GENERIC_FIRST_DIVISION_NAMES = {
    "1. division",
    "first division",
    "first league",
    "primera división",
    "primera division",
    "première division",
    "premiere division",
    "championnat d1",
}


@lru_cache(maxsize=1)
def _translation_rows() -> list[dict[str, str]]:
    if not TRANSLATION_PATH.exists():
        return []
    with TRANSLATION_PATH.open("r", encoding="utf-8", newline="") as handle:
        return [
            {key: (value or "").strip() for key, value in row.items()}
            for row in csv.DictReader(handle)
            if (row.get("kind") or "").strip() and (row.get("name") or "").strip()
        ]


@lru_cache(maxsize=1)
def _translation_map() -> dict[tuple[str, str], str]:
    table: dict[tuple[str, str], str] = {}
    for row in _translation_rows():
        key = (row["kind"].casefold(), row["name"].casefold())
        table[key] = row.get("zh") or row["name"]
    return table


@lru_cache(maxsize=1)
def _reverse_translation_map() -> dict[tuple[str, str], str]:
    table: dict[tuple[str, str], str] = {}
    for row in _translation_rows():
        zh = row.get("zh") or ""
        if zh:
            table.setdefault((row["kind"].casefold(), zh.casefold()), row["name"])
    return table


def translate_name(kind: str, name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    exact = _translation_map().get((kind.casefold(), text.casefold()))
    if exact:
        return exact
    if kind.casefold() == "league":
        return _translate_league_by_pattern(text)
    return text


def has_controlled_translation(kind: str, name: Any) -> bool:
    text = str(name or "").strip()
    if not text:
        return False
    return (kind.casefold(), text.casefold()) in _translation_map()


def translate_team_display(name: Any, fallback_label: str = "球队") -> str:
    text = str(name or "").strip()
    if not text:
        return fallback_label
    translated = translate_name("team", text)
    if translated != text or has_controlled_translation("team", text):
        return translated
    return text


def translate_league_name(name: Any, country: Any = "") -> str:
    league = str(name or "").strip()
    country_text = str(country or "").strip()
    if country_text:
        combined = f"{country_text} {league}".strip()
        exact = _translation_map().get(("league", combined.casefold()))
        if exact:
            return exact
        if league.casefold() in GENERIC_FIRST_DIVISION_NAMES:
            return f"{translate_name('country', country_text)}足球甲级联赛"
    translated = translate_name("league", league)
    if translated != league:
        return translated
    return translated


def translate_league_display(name: Any, country: Any = "") -> str:
    league = str(name or "").strip()
    if not league:
        return "赛事未提供"
    translated = translate_league_name(league, country)
    if translated != league or has_controlled_translation("league", league):
        return translated
    return league


def is_first_division_league(name: Any, country: Any = "") -> bool:
    league = str(name or "").strip()
    if league.casefold() in GENERIC_FIRST_DIVISION_NAMES:
        return True
    return "足球甲级联赛" in translate_league_name(league, country)


def to_api_name(kind: str, name: Any) -> str:
    text = str(name or "").strip()
    if not text:
        return ""
    return _reverse_translation_map().get((kind.casefold(), text.casefold()), text)


def to_beijing_time(value: Any) -> str:
    text = str(value or "").strip()
    if not text:
        return ""
    normalized = text[:-1] + "+00:00" if text.endswith("Z") else text
    try:
        dt = datetime.fromisoformat(normalized)
    except ValueError:
        return text
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING_TZ).strftime("%Y-%m-%d %H:%M 北京时间")


def localize_selection(selection: Any, home_name: str, away_name: str) -> str:
    text = str(selection or "")
    replacements = [
        (home_name, translate_team_display(home_name, "主队")),
        (away_name, translate_team_display(away_name, "客队")),
    ]
    for source, target in replacements:
        if source and target:
            text = text.replace(source, target)
    return text


def _translate_league_by_pattern(name: str) -> str:
    normalized = name.casefold()
    if normalized.startswith("world cup - qualification"):
        return "世界杯预选赛"
    if "friendlies" in normalized or "friendly" in normalized:
        return "国际友谊赛"
    return name
