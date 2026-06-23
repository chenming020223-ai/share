from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from .localization import localize_selection, to_beijing_time, translate_league_display, translate_team_display
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

    rows = _dedupe_raw_ledger_rows(rows)
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


def build_paper_ledger_book(
    *,
    starting_bankroll: float = 1000.0,
    prediction_limit: int = 120,
    ledger_limit: int = 120,
    db_path: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the paper bankroll ledger view from actual simulated bets only."""
    current_time = now or datetime.now(timezone.utc)
    if current_time.tzinfo is None:
        current_time = current_time.replace(tzinfo=timezone.utc)

    with connect(db_path) as conn:
        ledger_rows = conn.execute(
            """
            SELECT
                l.*,
                p.payload_json,
                p.created_at AS prediction_created_at,
                r.home_goals_90,
                r.away_goals_90
            FROM paper_bankroll_ledger AS l
            JOIN prediction_runs AS p
                ON p.id = l.run_id
            LEFT JOIN match_results AS r
                ON r.fixture_id = l.fixture_id
            ORDER BY l.created_at DESC, l.id DESC
            LIMIT ?
            """,
            (ledger_limit,),
        ).fetchall()

    _ = prediction_limit
    ledger = _ledger_book_rows(ledger_rows)
    start = max(1.0, float(starting_bankroll or 1000.0))
    _apply_rolling_book_balances(ledger, start)
    live_cabin = _live_cabin_rows(ledger, current_time)
    timeline = _ledger_book_timeline(ledger, start)
    open_count = sum(1 for row in ledger if row["status"] == "OPEN")
    settled_count = sum(1 for row in ledger if row["status"] == "SETTLED")
    realized_pnl = sum(float(row.get("profit") or 0.0) for row in ledger if row["status"] == "SETTLED")
    raw_count = len(ledger_rows)
    duplicate_count = max(0, raw_count - len(ledger))
    reserved_stake = sum(float(row.get("stake") or 0.0) for row in ledger if row["status"] == "OPEN")
    return {
        "summary": {
            "startingBankroll": start,
            "preMatchCount": 0,
            "liveCabinCount": len(live_cabin),
            "ledgerCount": len(ledger),
            "rawLedgerCount": raw_count,
            "openCount": open_count,
            "settledCount": settled_count,
            "realizedPnl": realized_pnl,
            "reservedStake": reserved_stake,
            "cash": start + realized_pnl - reserved_stake,
            "equity": start + realized_pnl,
            "duplicateCount": duplicate_count,
            "duplicatesExcluded": duplicate_count,
            "formalEvEnabled": False,
            "modeLabel": "模拟舱下注账本",
            "note": "这里只展示已经进入模拟舱账本的下注记录；同一场比赛、同一市场、同一方向与盘口只保留第一次入账。",
        },
        "preMatch": [],
        "liveCabin": live_cabin,
        "ledger": ledger,
        "timeline": timeline,
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


def _dedupe_raw_ledger_rows(rows: list[Any]) -> list[Any]:
    canonical: dict[tuple[str, str, str, str], Any] = {}
    for row in sorted(rows, key=lambda item: (_event_sort_ts(item["created_at"]), int(item["id"] or 0))):
        key = _ledger_unique_key(row["fixture_id"], row["market"], row["selection"], row["line"])
        canonical.setdefault(key, row)
    return sorted(canonical.values(), key=lambda item: (_event_sort_ts(item["created_at"]), int(item["id"] or 0)))


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


def _pre_match_cabin_rows(rows: list[Any], now: datetime) -> list[dict[str, Any]]:
    seen: set[str] = set()
    output: list[dict[str, Any]] = []
    for row in rows:
        if row["result_fixture_id"]:
            continue
        payload = _safe_json(row["payload_json"])
        meta = payload.get("meta") or {}
        kickoff = _parse_datetime(meta.get("kickoff"))
        if not kickoff or kickoff < now:
            continue
        fixture_id = str(row["match_id"] or meta.get("fixtureId") or "")
        if fixture_id in seen:
            continue
        seen.add(fixture_id)
        market_rows = [_recommendation_row(payload, item) for item in payload.get("recommendations") or [] if isinstance(item, dict)]
        best = _best_recommendation(market_rows)
        output.append(
            {
                "runId": int(row["id"]),
                "fixtureId": fixture_id,
                "createdAt": str(row["created_at"] or ""),
                "createdAtBeijing": to_beijing_time(str(row["created_at"] or "")),
                "kickoff": kickoff.isoformat(),
                "kickoffBeijing": meta.get("kickoffBeijing") or to_beijing_time(kickoff.isoformat()),
                "match": _match_label(payload),
                "home": _team_label(payload, "home"),
                "away": _team_label(payload, "away"),
                "homeLogo": (payload.get("match") or {}).get("homeLogo") or "",
                "awayLogo": (payload.get("match") or {}).get("awayLogo") or "",
                "league": meta.get("leagueNameZh") or translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
                "venue": meta.get("venue") or "",
                "bookmaker": meta.get("bookmaker") or "",
                "oddsCapturedAtBeijing": meta.get("oddsCapturedAtBeijing") or to_beijing_time(meta.get("oddsCapturedAt")),
                "best": best,
                "markets": market_rows,
                "ledgerStatus": "NOT_ENTERED",
                "ledgerLabel": "未入账",
            }
        )
    return sorted(output, key=lambda item: (item["kickoff"], item["runId"]))[:30]


def _ledger_book_rows(rows: list[Any]) -> list[dict[str, Any]]:
    raw: list[dict[str, Any]] = []
    duplicate_groups: dict[tuple[Any, ...], int] = {}
    for row in rows:
        payload = _safe_json(row["payload_json"])
        key = _ledger_unique_key(row["fixture_id"], row["market"], row["selection"], row["line"])
        duplicate_groups[key] = duplicate_groups.get(key, 0) + 1
        raw.append(_ledger_row(payload, row, key))
    canonical: dict[tuple[Any, ...], dict[str, Any]] = {}
    sequence: dict[tuple[Any, ...], int] = {}
    for item in sorted(raw, key=lambda row: (_event_sort_ts(row.get("createdAt")), int(row.get("ledgerId") or 0))):
        key = item.pop("_duplicateKey")
        sequence[key] = sequence.get(key, 0) + 1
        item["duplicateSequence"] = sequence[key]
        item["duplicateGroupCount"] = duplicate_groups.get(key, 1)
        item["duplicateSuppressedCount"] = max(0, duplicate_groups.get(key, 1) - 1)
        item["duplicateFlag"] = duplicate_groups.get(key, 1) > 1
        canonical.setdefault(key, item)
    return sorted(canonical.values(), key=lambda row: (_event_sort_ts(row.get("createdAt")), int(row.get("ledgerId") or 0)), reverse=True)


def _apply_rolling_book_balances(rows: list[dict[str, Any]], starting_bankroll: float) -> None:
    events: list[tuple[datetime, int, str, dict[str, Any]]] = []
    for row in rows:
        events.append((_event_sort_ts(row.get("createdAt")), 0, "RESERVE", row))
        if row.get("status") == "SETTLED" and row.get("settledAt"):
            events.append((_event_sort_ts(row.get("settledAt")), 1, "SETTLE", row))

    realized_pnl = 0.0
    reserved_stake = 0.0
    for _, _, event_type, row in sorted(events, key=lambda item: (item[0], item[1], int(item[3].get("ledgerId") or 0))):
        equity = starting_bankroll + realized_pnl
        stake = float(row.get("stake") or 0.0)
        if event_type == "RESERVE":
            row["bankrollBefore"] = equity
            reserved_stake = max(0.0, reserved_stake + stake)
            row["bankrollAfterStake"] = max(0.0, equity - reserved_stake)
            row["cashAfterStake"] = row["bankrollAfterStake"]
            row["currentEquity"] = equity
            row["reservedStakeAfter"] = reserved_stake
            continue

        reserved_stake = max(0.0, reserved_stake - stake)
        realized_pnl += float(row.get("profit") or 0.0)
        equity = starting_bankroll + realized_pnl
        row["bankrollAfterSettlement"] = equity
        row["cashAfterSettlement"] = max(0.0, equity - reserved_stake)
        row["currentEquity"] = equity
        row["reservedStakeAfter"] = reserved_stake


def _ledger_row(payload: dict[str, Any], row: Any, duplicate_key: tuple[Any, ...]) -> dict[str, Any]:
    meta = payload.get("meta") or {}
    status = str(row["status"] or "")
    home_goals = row["home_goals_90"]
    away_goals = row["away_goals_90"]
    score = str(row["result_score"] or "")
    if not score and home_goals is not None and away_goals is not None:
        score = f"{home_goals}-{away_goals}"
    return {
        "_duplicateKey": duplicate_key,
        "ledgerId": int(row["id"]),
        "runId": int(row["run_id"]),
        "fixtureId": str(row["fixture_id"] or ""),
        "match": _match_label(payload),
        "home": _team_label(payload, "home"),
        "away": _team_label(payload, "away"),
        "homeLogo": (payload.get("match") or {}).get("homeLogo") or "",
        "awayLogo": (payload.get("match") or {}).get("awayLogo") or "",
        "league": meta.get("leagueNameZh") or translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
        "kickoff": str(meta.get("kickoff") or ""),
        "kickoffBeijing": meta.get("kickoffBeijing") or to_beijing_time(meta.get("kickoff")),
        "createdAt": str(row["created_at"] or ""),
        "createdAtBeijing": to_beijing_time(str(row["created_at"] or "")),
        "settledAt": str(row["settled_at"] or ""),
        "settledAtBeijing": to_beijing_time(str(row["settled_at"] or "")),
        "market": str(row["market"] or ""),
        "selection": localize_selection(str(row["selection"] or ""), _team_label(payload, "home"), _team_label(payload, "away")),
        "line": row["line"],
        "bookmaker": str(row["bookmaker"] or ""),
        "odds": row["decimal_odds"],
        "modelProbability": row["model_probability"],
        "marketProbability": row["market_probability"],
        "expectedValue": row["expected_value_per_unit"],
        "evPbaseResearch": row["ev_pbase_research"],
        "evPfinalExec": row["ev_pfinal_exec"],
        "signalStatus": str(row["signal_status"] or row["action"] or ""),
        "evLayer": str(row["ev_layer"] or ""),
        "stake": float(row["stake"] or 0.0),
        "action": str(row["action"] or ""),
        "status": status,
        "statusLabel": "已结算" if status == "SETTLED" else "待结算",
        "score90": score,
        "netPerUnit": row["net_per_unit"],
        "profit": row["profit"],
        "bankrollBefore": row["bankroll_before"],
        "bankrollAfterStake": row["bankroll_after_stake"],
        "cashAfterStake": row["bankroll_after_stake"],
        "currentEquity": row["bankroll_before"],
        "reservedStakeAfter": None,
        "bankrollAfterSettlement": None,
        "cashAfterSettlement": None,
        "notes": str(row["notes"] or ""),
    }


def _live_cabin_rows(rows: list[dict[str, Any]], now: datetime) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        if row.get("status") != "OPEN":
            continue
        kickoff = _parse_datetime(row.get("kickoff"))
        if kickoff and kickoff < now:
            continue
        phase_label = "等待开赛" if kickoff else "开赛时间待核"
        output.append(
            {
                **row,
                "phaseLabel": phase_label,
                "statusLabel": phase_label,
            }
        )
    return sorted(output, key=lambda item: (_event_sort_ts(item.get("kickoff") or item.get("createdAt")), int(item.get("ledgerId") or 0)))[:50]


def _ledger_unique_key(fixture_id: Any, market: Any, selection: Any, line: Any) -> tuple[str, str, str, str]:
    line_key = "" if line is None else f"{float(line):.3f}"
    return (
        str(fixture_id or ""),
        str(market or "").casefold(),
        str(selection or "").casefold(),
        line_key,
    )


def _ledger_book_timeline(rows: list[dict[str, Any]], starting_bankroll: float) -> list[dict[str, Any]]:
    bankroll = starting_bankroll
    timeline: list[dict[str, Any]] = [
        {
            "date": "起始",
            "label": "起始",
            "bankroll": starting_bankroll,
            "profit": 0.0,
            "fixtureId": "",
            "ledgerId": "",
            "match": "起始资金",
        }
    ]
    settled_rows = sorted(
        [row for row in rows if row.get("status") == "SETTLED"],
        key=lambda row: (_event_sort_ts(row.get("settledAt") or row.get("createdAt")), int(row.get("ledgerId") or 0)),
    )
    for row in settled_rows:
        profit = float(row.get("profit") or 0.0)
        bankroll += profit
        row["bankrollAfterSettlement"] = bankroll
        event_ts = row.get("settledAt") or row.get("createdAt")
        timeline.append(
            {
                "date": _timeline_date(event_ts),
                "label": _timeline_date(event_ts),
                "bankroll": bankroll,
                "profit": profit,
                "fixtureId": row.get("fixtureId") or "",
                "ledgerId": row.get("ledgerId") or "",
                "match": row.get("match") or "",
                "market": row.get("market") or "",
                "selection": row.get("selection") or "",
            }
        )
    return timeline


def _timeline_date(value: Any) -> str:
    dt = _event_sort_ts(value)
    if dt.date() == datetime.max.date():
        return str(value or "-")[:10] or "-"
    return dt.astimezone(timezone(timedelta(hours=8))).strftime("%Y-%m-%d")


def _recommendation_row(payload: dict[str, Any], item: dict[str, Any]) -> dict[str, Any]:
    match = payload.get("match") or {}
    return {
        "market": str(item.get("market") or ""),
        "selection": localize_selection(str(item.get("selection") or ""), str(match.get("home") or ""), str(match.get("away") or "")),
        "line": item.get("line"),
        "odds": item.get("odds"),
        "modelProbability": item.get("model_probability"),
        "marketProbability": item.get("market_probability"),
        "expectedValue": item.get("expected_value_per_unit"),
        "evPbaseResearch": item.get("ev_pbase_research"),
        "evPfinalExec": item.get("ev_pfinal_exec"),
        "stake": float(item.get("stake") or 0.0),
        "action": str(item.get("action") or ""),
        "signalStatus": str(item.get("signal_status") or item.get("action") or ""),
        "evStatus": str(item.get("ev_status") or ""),
        "decisionStatus": str(item.get("decision_status") or ""),
        "reason": str(item.get("reason") or ""),
    }


def _best_recommendation(rows: list[dict[str, Any]]) -> dict[str, Any] | None:
    if not rows:
        return None
    priority = {
        "PAPER_BUY": 6,
        "MODEL_CANDIDATE": 5,
        "BUY": 5,
        "RESEARCH_WATCH": 4,
        "WATCH": 3,
        "SUSPENDED": 2,
        "NO_MARKET": 1,
    }
    return sorted(
        rows,
        key=lambda item: (
            priority.get(str(item.get("signalStatus") or item.get("action") or ""), 0),
            float(item.get("evPbaseResearch") or item.get("expectedValue") or -99.0),
        ),
        reverse=True,
    )[0]


def _match_label(payload: dict[str, Any]) -> str:
    return f"{_team_label(payload, 'home')} vs {_team_label(payload, 'away')}"


def _team_label(payload: dict[str, Any], side: str) -> str:
    match = payload.get("match") or {}
    return str(match.get(f"{side}Zh") or translate_team_display(match.get(side), "主队" if side == "home" else "客队"))


def _safe_json(value: Any) -> dict[str, Any]:
    try:
        parsed = json.loads(value)
    except (TypeError, json.JSONDecodeError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_datetime(value: Any) -> datetime | None:
    text = str(value or "").strip().replace("Z", "+00:00")
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed
