from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .odds import is_reasonable_two_way_market, two_way_implied_sum

DEFAULT_BOOKMAKER_PRIORITY = ("Pinnacle", "Bet365", "Betfair", "SBO", "10Bet", "1xBet")
DEFAULT_BOOKMAKER = DEFAULT_BOOKMAKER_PRIORITY[0]


@dataclass(frozen=True)
class BookmakerMarket:
    order: int
    id: Any
    name: str
    captured_at: str
    match_winner: dict[str, float] = field(default_factory=dict)
    totals: dict[float, dict[str, float]] = field(default_factory=dict)
    handicaps: dict[float, dict[str, float]] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketSnapshot:
    fixture_id: int | None = None
    bookmakers_count: int = 0
    available_bookmakers_count: int = 0
    required_bookmaker: str | None = None
    bookmaker_priority: list[str] = field(default_factory=list)
    selected_bookmaker: str | None = None
    selected_bookmakers: dict[str, str] = field(default_factory=dict)
    captured_at: str | None = None
    match_winner: dict[str, float] = field(default_factory=dict)
    totals: dict[float, dict[str, float]] = field(default_factory=dict)
    handicaps: dict[float, dict[str, float]] = field(default_factory=dict)
    raw_bookmakers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def bookmaker_for_market(self, market_type: str) -> str | None:
        normalized = _normalize_market_type(market_type)
        return self.selected_bookmakers.get(normalized) or self.selected_bookmaker

    def best_total_line(self, preferred: float = 2.5) -> tuple[float, dict[str, float]] | None:
        candidates = [
            (line, odds)
            for line, odds in self.totals.items()
            if odds.get("over", 0) > 1.0 and odds.get("under", 0) > 1.0
            and is_reasonable_two_way_market(odds["over"], odds["under"])
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                abs(item[1]["over"] - item[1]["under"]),
                abs(item[0] - preferred),
                item[0],
            ),
        )

    def best_handicap_line(self) -> tuple[float, dict[str, float]] | None:
        candidates = [
            (line, odds)
            for line, odds in self.handicaps.items()
            if odds.get("home", 0) > 1.0 and odds.get("away", 0) > 1.0
            and is_reasonable_two_way_market(odds["home"], odds["away"])
        ]
        if not candidates:
            return None
        return min(
            candidates,
            key=lambda item: (
                abs(item[1]["home"] - item[1]["away"]),
                abs(item[0]),
            ),
        )


def parse_api_football_odds(
    rows: list[dict[str, Any]],
    required_bookmaker: str | None = DEFAULT_BOOKMAKER,
    bookmaker_priority: list[str] | tuple[str, ...] | str | None = None,
) -> MarketSnapshot:
    fixture_id: int | None = None
    priority = normalize_bookmaker_priority(
        bookmaker_priority if bookmaker_priority is not None else required_bookmaker
    )
    if not priority:
        priority = normalize_bookmaker_priority(DEFAULT_BOOKMAKER_PRIORITY)
    raw_bookmakers: list[dict[str, Any]] = []
    warnings: list[str] = []
    candidates: list[BookmakerMarket] = []
    available_names: list[str] = []

    for fixture_row in rows:
        fixture = fixture_row.get("fixture") or {}
        if fixture_id is None and fixture.get("id") is not None:
            fixture_id = int(fixture["id"])

        capture_time = str(fixture_row.get("update") or fixture_row.get("updated") or "").strip()
        bookmakers = fixture_row.get("bookmakers") or []
        for bookmaker in bookmakers:
            bookmaker_name = str(bookmaker.get("name") or bookmaker.get("id") or "未知公司")
            available_names.append(bookmaker_name)
            local_match_winner: dict[str, float] = {}
            local_totals: dict[float, dict[str, float]] = defaultdict(dict)
            local_handicaps: dict[float, dict[str, float]] = defaultdict(dict)
            raw_bookmakers.append(
                {
                    "id": bookmaker.get("id"),
                    "name": bookmaker.get("name"),
                    "bets": bookmaker.get("bets") or [],
                    "selected": False,
                    "selectedMarkets": [],
                }
            )
            for bet in bookmaker.get("bets") or []:
                bet_name = _normalize_market_name(str(bet.get("name") or ""))
                values = bet.get("values") or []

                if _is_match_winner_market(bet_name):
                    for item in values:
                        key = _match_winner_key(str(item.get("value") or ""))
                        odd = _parse_odd(item.get("odd"))
                        if key and odd:
                            local_match_winner[key] = odd

                elif _is_total_market(bet_name):
                    for item in values:
                        parsed = _parse_total_value(str(item.get("value") or ""))
                        odd = _parse_odd(item.get("odd"))
                        if parsed and odd:
                            side, line = parsed
                            local_totals[line][side] = odd

                elif _is_handicap_market(bet_name):
                    for item in values:
                        parsed = _parse_handicap_value(str(item.get("value") or ""))
                        odd = _parse_odd(item.get("odd"))
                        if parsed and odd:
                            side, home_line = parsed
                            local_handicaps[home_line][side] = odd

            candidates.append(
                BookmakerMarket(
                    order=len(candidates),
                    id=bookmaker.get("id"),
                    name=bookmaker_name,
                    captured_at=capture_time,
                    match_winner=_complete_match_winner(local_match_winner, warnings, bookmaker_name),
                    totals=_valid_two_way_pairs(
                        local_totals,
                        warnings,
                        label="大小球",
                        bookmaker_name=bookmaker_name,
                        first_key="over",
                        second_key="under",
                    ),
                    handicaps=_valid_two_way_pairs(
                        local_handicaps,
                        warnings,
                        label="让球",
                        bookmaker_name=bookmaker_name,
                        first_key="home",
                        second_key="away",
                    ),
                )
            )

    ordered = _rank_bookmaker_candidates(candidates, priority)
    winner_source = next((item for item in ordered if _has_complete_match_winner(item.match_winner)), None)
    total_source = next((item for item in ordered if item.totals), None)
    handicap_source = next((item for item in ordered if item.handicaps), None)

    selected_bookmakers: dict[str, str] = {}
    capture_times: list[str] = []
    if winner_source:
        selected_bookmakers["1X2"] = winner_source.name
        if winner_source.captured_at:
            capture_times.append(winner_source.captured_at)
    if total_source:
        selected_bookmakers["OU"] = total_source.name
        if total_source.captured_at:
            capture_times.append(total_source.captured_at)
    if handicap_source:
        selected_bookmakers["AH"] = handicap_source.name
        if handicap_source.captured_at:
            capture_times.append(handicap_source.captured_at)

    selected_set = {name.casefold() for name in selected_bookmakers.values()}
    selected_markets_by_name: dict[str, list[str]] = defaultdict(list)
    for market_type, name in selected_bookmakers.items():
        selected_markets_by_name[name.casefold()].append(market_type)
    for raw in raw_bookmakers:
        name = str(raw.get("name") or raw.get("id") or "")
        raw["selected"] = name.casefold() in selected_set
        raw["selectedMarkets"] = selected_markets_by_name.get(name.casefold(), [])

    primary_bookmaker = (
        selected_bookmakers.get("1X2")
        or selected_bookmakers.get("OU")
        or selected_bookmakers.get("AH")
    )
    for market_key, source in (("胜平负", winner_source), ("大小球", total_source), ("让球", handicap_source)):
        if source is None:
            _add_warning(warnings, f"{market_key}未取得庄家优先级内可用全场盘口。")
            continue
        if priority and not _same_bookmaker(source.name, priority[0]):
            _add_warning(warnings, f"{market_key}未取得首选庄家 {priority[0]}，已回退使用 {source.name}。")

    available_unique = _unique_names(available_names)

    return MarketSnapshot(
        fixture_id=fixture_id,
        bookmakers_count=len(selected_set),
        available_bookmakers_count=len(available_unique),
        required_bookmaker=priority[0] if priority else required_bookmaker,
        bookmaker_priority=priority,
        selected_bookmaker=primary_bookmaker,
        selected_bookmakers=selected_bookmakers,
        captured_at=max(capture_times) if capture_times else None,
        match_winner=dict(winner_source.match_winner) if winner_source else {},
        totals=dict(total_source.totals) if total_source else {},
        handicaps=dict(handicap_source.handicaps) if handicap_source else {},
        raw_bookmakers=raw_bookmakers,
        warnings=warnings,
    )


def normalize_bookmaker_priority(value: list[str] | tuple[str, ...] | str | None) -> list[str]:
    if value is None:
        return list(DEFAULT_BOOKMAKER_PRIORITY)
    if isinstance(value, str):
        parts = value.replace(";", ",").split(",")
    else:
        parts = [str(item) for item in value]
    priority: list[str] = []
    seen: set[str] = set()
    for part in parts:
        item = part.strip()
        if not item:
            continue
        key = item.casefold()
        if key in seen:
            continue
        seen.add(key)
        priority.append(item)
    return priority


def _is_match_winner_market(name: str) -> bool:
    return name in {"match winner", "1x2", "fulltime result", "full time result"}


def _is_total_market(name: str) -> bool:
    return name in {"goals over/under", "total goals", "fulltime total goals", "full time total goals"}


def _is_handicap_market(name: str) -> bool:
    return name in {"asian handicap", "fulltime asian handicap", "full time asian handicap"}


def _normalize_market_name(name: str) -> str:
    return re.sub(r"\s+", " ", name.casefold().strip())


def _same_bookmaker(actual: str, required: str) -> bool:
    return actual.casefold().strip() == required.casefold().strip()


def _match_winner_key(value: str) -> str | None:
    normalized = value.casefold().strip()
    if normalized in {"home", "1"}:
        return "home_win"
    if normalized in {"draw", "x"}:
        return "draw"
    if normalized in {"away", "2"}:
        return "away_win"
    return None


def _parse_total_value(value: str) -> tuple[str, float] | None:
    match = re.search(r"\b(over|under)\b\s*([0-9]+(?:\.[0-9]+)?)", value, re.IGNORECASE)
    if not match:
        return None
    return match.group(1).casefold(), float(match.group(2))


def _parse_handicap_value(value: str) -> tuple[str, float] | None:
    normalized = value.strip()
    match = re.search(r"\b(home|away)\b\s*([+-]?[0-9]+(?:\.[0-9]+)?)", normalized, re.IGNORECASE)
    if not match:
        return None

    side = match.group(1).casefold()
    line = float(match.group(2))
    # API-Football represents both selections against the same listed AH line,
    # for example Home -1.25 and Away -1.25 are the paired full-time market.
    return side, line


def _parse_odd(value: Any) -> float | None:
    try:
        odd = float(value)
    except (TypeError, ValueError):
        return None
    return odd if odd > 1.0 else None


def _average(values: list[float]) -> float:
    return sum(values) / len(values) if values else 0.0


def _normalize_market_type(value: str) -> str:
    normalized = str(value or "").strip().upper()
    aliases = {
        "MATCH_WINNER": "1X2",
        "WINNER": "1X2",
        "胜平负": "1X2",
        "TOTAL": "OU",
        "TOTAL_GOALS": "OU",
        "大小球": "OU",
        "HANDICAP": "AH",
        "让球": "AH",
    }
    return aliases.get(normalized, normalized)


def _unique_names(names: list[str]) -> list[str]:
    unique: list[str] = []
    seen: set[str] = set()
    for name in names:
        key = str(name or "").casefold().strip()
        if not key or key in seen:
            continue
        seen.add(key)
        unique.append(name)
    return unique


def _priority_index(name: str, priority: list[str]) -> int:
    for index, candidate in enumerate(priority):
        if _same_bookmaker(name, candidate):
            return index
    return len(priority) + 1


def _rank_bookmaker_candidates(candidates: list[BookmakerMarket], priority: list[str]) -> list[BookmakerMarket]:
    return sorted(candidates, key=lambda item: (_priority_index(item.name, priority), item.order))


def _has_complete_match_winner(odds: dict[str, float]) -> bool:
    return all(odds.get(key, 0.0) > 1.0 for key in ("home_win", "draw", "away_win"))


def _complete_match_winner(
    local_odds: dict[str, float],
    warnings: list[str],
    bookmaker_name: str,
) -> dict[str, float]:
    required = ("home_win", "draw", "away_win")
    present = [key for key in required if local_odds.get(key, 0.0) > 1.0]
    if not present:
        return {}
    if len(present) < len(required):
        _add_warning(warnings, f"胜平负在 {bookmaker_name} 缺少完整 1X2 赔率，已排除。")
        return {}
    return {key: local_odds[key] for key in required}


def _valid_two_way_pairs(
    local_pairs: dict[float, dict[str, float]],
    warnings: list[str],
    *,
    label: str,
    bookmaker_name: str,
    first_key: str,
    second_key: str,
) -> dict[float, dict[str, float]]:
    valid: dict[float, dict[str, float]] = {}
    for line, odds in local_pairs.items():
        first = odds.get(first_key, 0.0)
        second = odds.get(second_key, 0.0)
        if first > 1.0 and second > 1.0:
            implied_sum = two_way_implied_sum(first, second)
            if is_reasonable_two_way_market(first, second):
                valid[line] = {first_key: first, second_key: second}
            else:
                _add_warning(
                    warnings,
                    f"{label} {line:g} 在 {bookmaker_name} 的盘口水位异常"
                    f"（隐含概率和 {implied_sum * 100:.1f}%），已排除。",
                )
        elif first > 1.0 or second > 1.0:
            _add_warning(warnings, f"{label} {line:g} 在 {bookmaker_name} 缺少同公司成对赔率，已排除。")
    return valid


def _append_complete_match_winner(
    local_odds: dict[str, float],
    target: dict[str, list[float]],
    warnings: list[str],
    bookmaker_name: str,
) -> None:
    required = ("home_win", "draw", "away_win")
    present = [key for key in required if local_odds.get(key, 0.0) > 1.0]
    if not present:
        return
    if len(present) < len(required):
        _add_warning(warnings, f"胜平负在 {bookmaker_name} 缺少完整 1X2 赔率，已排除。")
        return
    for key in required:
        target[key].append(local_odds[key])


def _append_valid_two_way_pairs(
    local_pairs: dict[float, dict[str, float]],
    target: dict[float, dict[str, list[float]]],
    warnings: list[str],
    *,
    label: str,
    bookmaker_name: str,
    first_key: str,
    second_key: str,
) -> None:
    for line, odds in local_pairs.items():
        first = odds.get(first_key, 0.0)
        second = odds.get(second_key, 0.0)
        if first > 1.0 and second > 1.0:
            implied_sum = two_way_implied_sum(first, second)
            if is_reasonable_two_way_market(first, second):
                target[line][first_key].append(first)
                target[line][second_key].append(second)
            else:
                _add_warning(
                    warnings,
                    f"{label} {line:g} 在 {bookmaker_name} 的盘口水位异常"
                    f"（隐含概率和 {implied_sum * 100:.1f}%），已排除。",
                )
        elif first > 1.0 or second > 1.0:
            _add_warning(warnings, f"{label} {line:g} 在 {bookmaker_name} 缺少同公司成对赔率，已排除。")


def _add_warning(warnings: list[str], message: str, limit: int = 20) -> None:
    if len(warnings) >= limit or message in warnings:
        return
    warnings.append(message)
