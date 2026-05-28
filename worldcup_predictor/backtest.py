from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any

from .api_football import ApiFootballClient
from .storage import pending_result_fixtures, prediction_payloads_with_results, record_match_result


@dataclass(frozen=True)
class SettledBet:
    market: str
    selection: str
    stake: float
    odds: float
    net_per_unit: float
    profit: float


def actual_result_key(home_goals_90: int, away_goals_90: int) -> str:
    if home_goals_90 > away_goals_90:
        return "home_win"
    if home_goals_90 < away_goals_90:
        return "away_win"
    return "draw"


def brier_score(probabilities: dict[str, float], actual_key: str) -> float:
    keys = ("home_win", "draw", "away_win")
    return sum((float(probabilities.get(key, 0.0)) - (1.0 if key == actual_key else 0.0)) ** 2 for key in keys)


def log_loss(probabilities: dict[str, float], actual_key: str, epsilon: float = 1e-12) -> float:
    probability = max(epsilon, min(1.0, float(probabilities.get(actual_key, 0.0))))
    return -math.log(probability)


def settle_prediction_payload(
    payload: dict[str, Any],
    home_goals_90: int,
    away_goals_90: int,
) -> dict[str, Any]:
    recommendations = payload.get("recommendations") or []
    settled = [
        item
        for item in (
            _settle_recommendation(payload, recommendation, home_goals_90, away_goals_90)
            for recommendation in recommendations
        )
        if item is not None
    ]
    probabilities = ((payload.get("probabilities") or {}).get("model") or {})
    actual_key = actual_result_key(home_goals_90, away_goals_90)
    total_stake = sum(item.stake for item in settled)
    total_profit = sum(item.profit for item in settled)
    return {
        "runId": payload.get("runId"),
        "fixtureId": (payload.get("match") or {}).get("id") or (payload.get("meta") or {}).get("fixtureId"),
        "homeGoals90": home_goals_90,
        "awayGoals90": away_goals_90,
        "actualResult": actual_key,
        "bets": [item.__dict__ for item in settled],
        "totalBets": len(settled),
        "winningBets": sum(1 for item in settled if item.profit > 0),
        "totalStake": total_stake,
        "totalProfit": total_profit,
        "roi": (total_profit / total_stake) if total_stake > 0 else 0.0,
        "brierScore": brier_score(probabilities, actual_key),
        "logLoss": log_loss(probabilities, actual_key),
    }


def performance_metrics(settled_runs: list[dict[str, Any]]) -> dict[str, float]:
    total_bets = sum(int(item.get("totalBets") or 0) for item in settled_runs)
    winning_bets = sum(int(item.get("winningBets") or 0) for item in settled_runs)
    total_stake = sum(float(item.get("totalStake") or 0.0) for item in settled_runs)
    total_profit = sum(float(item.get("totalProfit") or 0.0) for item in settled_runs)
    brier_values = [float(item["brierScore"]) for item in settled_runs if item.get("brierScore") is not None]
    logloss_values = [float(item["logLoss"]) for item in settled_runs if item.get("logLoss") is not None]
    profits = [float(item.get("totalProfit") or 0.0) for item in settled_runs]
    return {
        "totalRuns": float(len(settled_runs)),
        "totalBets": float(total_bets),
        "winningBets": float(winning_bets),
        "totalStake": total_stake,
        "totalProfit": total_profit,
        "roi": (total_profit / total_stake) if total_stake > 0 else 0.0,
        "maxDrawdown": max_drawdown(profits),
        "brierScore": sum(brier_values) / len(brier_values) if brier_values else 0.0,
        "logLoss": sum(logloss_values) / len(logloss_values) if logloss_values else 0.0,
    }


def max_drawdown(profits: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    drawdown = 0.0
    for profit in profits:
        equity += profit
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def record_result(
    fixture_id: str | int,
    home_goals_90: int,
    away_goals_90: int,
    notes: str = "",
    db_path: str | None = None,
) -> None:
    record_match_result(fixture_id, home_goals_90, away_goals_90, notes=notes, db_path=db_path)


def backtest_recorded_results(db_path: str | None = None) -> dict[str, Any]:
    rows = prediction_payloads_with_results(db_path=db_path)
    settled = [
        settle_prediction_payload(row["payload"], row["home_goals_90"], row["away_goals_90"])
        for row in rows
    ]
    return {
        "runs": settled,
        "metrics": performance_metrics(settled),
    }


def sync_completed_results(
    api_key: str | None = None,
    db_path: str | None = None,
    client: ApiFootballClient | None = None,
) -> dict[str, Any]:
    source = client or ApiFootballClient(api_key=api_key)
    pending = pending_result_fixtures(db_path=db_path)
    synced: list[str] = []
    awaiting: list[str] = []
    skipped: list[str] = []
    for fixture_id in pending:
        fixture_row = source.fixture_by_id(int(fixture_id))
        result = _extract_completed_90_minute_result(fixture_row)
        if result is None:
            status = str(((fixture_row.get("fixture") or {}).get("status") or {}).get("short") or "")
            if status in {"NS", "TBD", "PST", "1H", "HT", "2H", "ET", "BT", "P"}:
                awaiting.append(fixture_id)
            else:
                skipped.append(fixture_id)
            continue
        record_match_result(
            fixture_id,
            result[0],
            result[1],
            notes="API-Football 自动同步的 90 分钟赛果",
            db_path=db_path,
        )
        synced.append(fixture_id)
    return {
        "eligiblePending": len(pending),
        "synced": synced,
        "awaitingCompletion": awaiting,
        "skippedWithoutFulltimeScore": skipped,
    }


def _extract_completed_90_minute_result(fixture_row: dict[str, Any]) -> tuple[int, int] | None:
    fixture = fixture_row.get("fixture") or {}
    status = str((fixture.get("status") or {}).get("short") or "")
    if status not in {"FT", "AET", "PEN"}:
        return None
    fulltime = (fixture_row.get("score") or {}).get("fulltime") or {}
    home = fulltime.get("home")
    away = fulltime.get("away")
    if home is None or away is None:
        return None
    return int(home), int(away)


def _settle_recommendation(
    payload: dict[str, Any],
    recommendation: dict[str, Any],
    home_goals_90: int,
    away_goals_90: int,
) -> SettledBet | None:
    if recommendation.get("action") not in {"BUY", "PAPER_BUY"}:
        return None
    stake = float(recommendation.get("stake") or 0.0)
    odds = float(recommendation.get("odds") or 0.0)
    if stake <= 0 or odds <= 1.0:
        return None
    market = str(recommendation.get("market") or "")
    selection = str(recommendation.get("selection") or "")
    line = recommendation.get("line")
    if market == "胜平负":
        net = _settle_match_winner(payload, selection, home_goals_90, away_goals_90, odds)
    elif market == "大小球":
        net = _settle_total(selection, float(line), home_goals_90, away_goals_90, odds)
    elif market == "让球":
        net = _settle_handicap(payload, selection, float(line), home_goals_90, away_goals_90, odds)
    else:
        return None
    return SettledBet(
        market=market,
        selection=selection,
        stake=stake,
        odds=odds,
        net_per_unit=net,
        profit=stake * net,
    )


def _settle_match_winner(
    payload: dict[str, Any],
    selection: str,
    home_goals_90: int,
    away_goals_90: int,
    odds: float,
) -> float:
    match = payload.get("match") or {}
    home_names = {str(match.get("home") or ""), str(match.get("homeZh") or "")}
    away_names = {str(match.get("away") or ""), str(match.get("awayZh") or "")}
    actual = actual_result_key(home_goals_90, away_goals_90)
    if "平局" in selection:
        won = actual == "draw"
    elif any(selection == f"{name} 胜" for name in home_names if name):
        won = actual == "home_win"
    elif any(selection == f"{name} 胜" for name in away_names if name):
        won = actual == "away_win"
    else:
        won = False
    return odds - 1.0 if won else -1.0


def _settle_total(selection: str, line: float, home_goals_90: int, away_goals_90: int, odds: float) -> float:
    side = "over" if selection.startswith("大") else "under"
    goals = home_goals_90 + away_goals_90
    nets = []
    for split_line in _split_asian_line(line):
        diff = goals - split_line if side == "over" else split_line - goals
        nets.append(_settlement_net(diff, odds))
    return sum(nets) / len(nets)


def _settle_handicap(
    payload: dict[str, Any],
    selection: str,
    home_line: float,
    home_goals_90: int,
    away_goals_90: int,
    odds: float,
) -> float:
    match = payload.get("match") or {}
    home_names = {str(match.get("home") or ""), str(match.get("homeZh") or "")}
    side = "home" if any(selection.startswith(name) for name in home_names if name) else "away"
    nets = []
    for split_line in _split_asian_line(home_line):
        diff = home_goals_90 + split_line - away_goals_90
        if side == "away":
            diff = -diff
        nets.append(_settlement_net(diff, odds))
    return sum(nets) / len(nets)


def _split_asian_line(line: float) -> list[float]:
    rounded = round(line * 4) / 4
    lower = math.floor(rounded * 2) / 2
    upper = math.ceil(rounded * 2) / 2
    if abs(lower - upper) < 1e-9:
        return [rounded]
    return [lower, upper]


def _settlement_net(diff: float, odds: float) -> float:
    if diff > 1e-9:
        return odds - 1.0
    if diff < -1e-9:
        return -1.0
    return 0.0
