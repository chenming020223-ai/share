from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass, field
from typing import Any

from .odds import is_reasonable_two_way_market, two_way_implied_sum

DEFAULT_BOOKMAKER = "Pinnacle"


@dataclass(frozen=True)
class MarketSnapshot:
    fixture_id: int | None = None
    bookmakers_count: int = 0
    required_bookmaker: str | None = None
    selected_bookmaker: str | None = None
    captured_at: str | None = None
    match_winner: dict[str, float] = field(default_factory=dict)
    totals: dict[float, dict[str, float]] = field(default_factory=dict)
    handicaps: dict[float, dict[str, float]] = field(default_factory=dict)
    raw_bookmakers: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

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
) -> MarketSnapshot:
    fixture_id: int | None = None
    selected_bookmakers: set[str] = set()
    selected_bookmaker: str | None = None
    capture_times: list[str] = []
    raw_bookmakers: list[dict[str, Any]] = []
    match_winner: dict[str, list[float]] = defaultdict(list)
    totals: dict[float, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    handicaps: dict[float, dict[str, list[float]]] = defaultdict(lambda: defaultdict(list))
    warnings: list[str] = []

    for fixture_row in rows:
        fixture = fixture_row.get("fixture") or {}
        if fixture_id is None and fixture.get("id") is not None:
            fixture_id = int(fixture["id"])

        bookmakers = fixture_row.get("bookmakers") or []
        for bookmaker in bookmakers:
            bookmaker_name = str(bookmaker.get("name") or bookmaker.get("id") or "未知公司")
            is_selected = required_bookmaker is None or _same_bookmaker(bookmaker_name, required_bookmaker)
            local_match_winner: dict[str, float] = {}
            local_totals: dict[float, dict[str, float]] = defaultdict(dict)
            local_handicaps: dict[float, dict[str, float]] = defaultdict(dict)
            raw_bookmakers.append(
                {
                    "id": bookmaker.get("id"),
                    "name": bookmaker.get("name"),
                    "bets": bookmaker.get("bets") or [],
                    "selected": is_selected,
                }
            )
            if not is_selected:
                continue
            selected_bookmakers.add(bookmaker_name.casefold())
            selected_bookmaker = bookmaker_name
            capture_time = str(fixture_row.get("update") or fixture_row.get("updated") or "").strip()
            if capture_time:
                capture_times.append(capture_time)
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

            _append_complete_match_winner(local_match_winner, match_winner, warnings, bookmaker_name)
            _append_valid_two_way_pairs(
                local_totals,
                totals,
                warnings,
                label="大小球",
                bookmaker_name=bookmaker_name,
                first_key="over",
                second_key="under",
            )
            _append_valid_two_way_pairs(
                local_handicaps,
                handicaps,
                warnings,
                label="让球",
                bookmaker_name=bookmaker_name,
                first_key="home",
                second_key="away",
            )

    if required_bookmaker and not selected_bookmaker:
        _add_warning(warnings, f"指定庄家 {required_bookmaker} 没有可用的全场盘口，模拟舱不产生信号。")

    return MarketSnapshot(
        fixture_id=fixture_id,
        bookmakers_count=len(selected_bookmakers),
        required_bookmaker=required_bookmaker,
        selected_bookmaker=selected_bookmaker,
        captured_at=max(capture_times) if capture_times else None,
        match_winner={key: _average(values) for key, values in match_winner.items()},
        totals={
            line: {side: _average(values) for side, values in odds.items()}
            for line, odds in totals.items()
        },
        handicaps={
            line: {side: _average(values) for side, values in odds.items()}
            for line, odds in handicaps.items()
        },
        raw_bookmakers=raw_bookmakers,
        warnings=warnings,
    )


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
