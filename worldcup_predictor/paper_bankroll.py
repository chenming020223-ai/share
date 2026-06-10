from __future__ import annotations

import json
from datetime import datetime, timezone
from typing import Any

from .storage import connect


def build_paper_bankroll_timeline(
    *,
    starting_bankroll: float = 1000.0,
    limit: int = 80,
    db_path: str | None = None,
) -> dict[str, Any]:
    start = max(1.0, float(starting_bankroll or 1000.0))
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                l.*,
                p.payload_json
            FROM paper_bankroll_ledger AS l
            JOIN prediction_runs AS p
                ON p.id = l.run_id
            ORDER BY l.created_at ASC, l.id ASC
            """
        ).fetchall()

    events: list[dict[str, Any]] = []
    for row in rows:
        base = _ledger_base_event(row)
        events.append(
            {
                **base,
                "eventType": "RESERVE",
                "eventLabel": "预留注额",
                "eventTs": str(row["created_at"] or ""),
                "stakeDelta": float(row["stake"] or 0.0),
                "profit": 0.0,
            }
        )
        if str(row["status"] or "") == "SETTLED" and row["settled_at"]:
            events.append(
                {
                    **base,
                    "eventType": "SETTLE",
                    "eventLabel": "赛果结算",
                    "eventTs": str(row["settled_at"] or ""),
                    "stakeDelta": -float(row["stake"] or 0.0),
                    "profit": float(row["profit"] or 0.0),
                    "netPerUnit": row["net_per_unit"],
                    "resultScore": str(row["result_score"] or ""),
                }
            )

    events.sort(key=lambda item: (_event_sort_ts(item.get("eventTs")), 0 if item["eventType"] == "RESERVE" else 1))
    timeline: list[dict[str, Any]] = []
    realized_pnl = 0.0
    reserved_stake = 0.0
    peak_equity = start
    loss_streak = 0
    settled_count = 0
    open_count = 0

    for event in events:
        if event["eventType"] == "RESERVE":
            reserved_stake = max(0.0, reserved_stake + float(event.get("stakeDelta") or 0.0))
            open_count += 1
        else:
            reserved_stake = max(0.0, reserved_stake + float(event.get("stakeDelta") or 0.0))
            profit = float(event.get("profit") or 0.0)
            realized_pnl += profit
            settled_count += 1
            open_count = max(0, open_count - 1)
            if profit < 0:
                loss_streak += 1
            elif profit > 0:
                loss_streak = 0

        equity = start + realized_pnl
        peak_equity = max(peak_equity, equity)
        drawdown_pct = (peak_equity - equity) / peak_equity if peak_equity > 0 else 0.0
        cash = max(0.0, start + realized_pnl - reserved_stake)
        risk_mode = _risk_mode(drawdown_pct, loss_streak)
        timeline.append(
            {
                **event,
                "cash": cash,
                "reservedStake": reserved_stake,
                "realizedPnl": realized_pnl,
                "equity": equity,
                "peakEquity": peak_equity,
                "drawdownPct": drawdown_pct,
                "lossStreak": loss_streak,
                "riskMode": risk_mode,
                "riskLabel": _risk_label(risk_mode),
                "openCount": open_count,
                "settledCount": settled_count,
            }
        )

    latest = timeline[-1] if timeline else {
        "cash": start,
        "reservedStake": 0.0,
        "realizedPnl": 0.0,
        "equity": start,
        "peakEquity": start,
        "drawdownPct": 0.0,
        "lossStreak": 0,
        "riskMode": "normal",
        "riskLabel": "正常",
        "openCount": 0,
        "settledCount": 0,
    }
    open_rows = [row for row in rows if str(row["status"] or "") == "OPEN"]
    return {
        "summary": {
            "startingBankroll": start,
            "cash": latest["cash"],
            "reservedStake": latest["reservedStake"],
            "realizedPnl": latest["realizedPnl"],
            "equity": latest["equity"],
            "peakEquity": latest["peakEquity"],
            "drawdownPct": latest["drawdownPct"],
            "lossStreak": latest["lossStreak"],
            "riskMode": latest["riskMode"],
            "riskLabel": latest["riskLabel"],
            "ledgerCount": len(rows),
            "eventCount": len(timeline),
            "openCount": len(open_rows),
            "settledCount": sum(1 for row in rows if str(row["status"] or "") == "SETTLED"),
            "marketExposure": _exposure(open_rows, "market"),
            "leagueExposure": _league_exposure(open_rows),
        },
        "events": timeline[-limit:],
    }


def _ledger_base_event(row: Any) -> dict[str, Any]:
    payload = json.loads(row["payload_json"])
    match = payload.get("match") or {}
    meta = payload.get("meta") or {}
    return {
        "ledgerId": int(row["id"]),
        "runId": int(row["run_id"]),
        "fixtureId": str(row["fixture_id"] or ""),
        "match": f"{match.get('homeZh') or match.get('home') or '-'} vs {match.get('awayZh') or match.get('away') or '-'}",
        "league": meta.get("leagueNameZh") or meta.get("leagueName") or "-",
        "kickoffBeijing": meta.get("kickoffBeijing") or "",
        "market": str(row["market"] or ""),
        "selection": str(row["selection"] or ""),
        "line": row["line"],
        "bookmaker": str(row["bookmaker"] or ""),
        "odds": row["decimal_odds"],
        "stake": float(row["stake"] or 0.0),
        "status": str(row["status"] or ""),
    }


def _exposure(rows: list[Any], key: str) -> dict[str, float]:
    output: dict[str, float] = {}
    for row in rows:
        label = str(row[key] or "-")
        output[label] = output.get(label, 0.0) + float(row["stake"] or 0.0)
    return output


def _league_exposure(rows: list[Any]) -> dict[str, float]:
    output: dict[str, float] = {}
    for row in rows:
        try:
            payload = json.loads(row["payload_json"])
        except (TypeError, json.JSONDecodeError):
            payload = {}
        meta = payload.get("meta") or {}
        label = str(meta.get("leagueNameZh") or meta.get("leagueName") or "-")
        output[label] = output.get(label, 0.0) + float(row["stake"] or 0.0)
    return output


def _event_sort_ts(value: Any) -> datetime:
    text = str(value or "").replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return datetime.max.replace(tzinfo=timezone.utc)
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed


def _risk_mode(drawdown_pct: float, loss_streak: int) -> str:
    if drawdown_pct >= 0.25:
        return "manual_review"
    if drawdown_pct >= 0.20:
        return "pause_new_paper_buy"
    if loss_streak >= 5:
        return "loss_streak_5"
    if loss_streak >= 3:
        return "loss_streak_3"
    return "normal"


def _risk_label(mode: str) -> str:
    return {
        "normal": "正常",
        "loss_streak_3": "连亏降档",
        "loss_streak_5": "连亏强降档",
        "pause_new_paper_buy": "回撤暂停",
        "manual_review": "人工复核",
    }.get(mode, mode)
