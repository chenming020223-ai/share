from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from .backtest import (
    _settle_handicap,
    _settle_match_winner,
    _settle_total,
    actual_result_key,
)
from .localization import localize_selection, translate_league_display, translate_team_display
from .payload_governance import apply_current_score_validation_to_payload
from .score_calibration import build_score_distribution_calibration_status
from .storage import connect


DEFAULT_REPLAY_UNIT_STAKE = 200.0


@dataclass(frozen=True)
class StoredPrediction:
    run_id: int
    created_at: str
    payload: dict[str, Any]
    home_goals_90: int | None
    away_goals_90: int | None


def build_prediction_replay(
    run_id: int,
    *,
    starting_bankroll: float = 1000.0,
    db_path: str | None = None,
) -> dict[str, Any]:
    stored = _load_stored_prediction(run_id, db_path=db_path)
    if stored is None:
        raise ValueError("Prediction not found")

    payload = stored.payload
    match = payload.get("match") or {}
    meta = payload.get("meta") or {}
    result = _result_payload(stored)
    score_validation = build_score_distribution_calibration_status(db_path=db_path)
    current_payload = apply_current_score_validation_to_payload(payload, score_validation) or payload
    unit = _unit_stake(payload)
    original = _simulate_mode(
        payload,
        stored,
        mode="original",
        starting_bankroll=starting_bankroll,
        unit_stake=unit,
        score_validation=score_validation,
    )
    current = _simulate_mode(
        current_payload,
        stored,
        mode="current",
        starting_bankroll=starting_bankroll,
        unit_stake=unit,
        score_validation=score_validation,
    )
    return {
        "runId": stored.run_id,
        "createdAt": stored.created_at,
        "match": {
            "id": match.get("id") or meta.get("fixtureId"),
            "home": match.get("home") or "",
            "away": match.get("away") or "",
            "homeZh": match.get("homeZh") or translate_team_display(match.get("home"), "主队"),
            "awayZh": match.get("awayZh") or translate_team_display(match.get("away"), "客队"),
            "homeLogo": match.get("homeLogo") or match.get("home_logo") or "",
            "awayLogo": match.get("awayLogo") or match.get("away_logo") or "",
        },
        "meta": {
            **meta,
            "leagueNameZh": meta.get("leagueNameZh")
            or translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
        },
        "result": result,
        "scoreDistributionValidation": score_validation,
        "modes": {
            "original": original,
            "current": current,
        },
        "notes": [
            "原始快照回放只使用当时保存的预测、盘口和模拟舱判断。",
            "当前规则重放只用当前闸门解释历史快照，不重新抓取赛后数据。",
            "formal_EV 未批准前，回溯资金为纸上模拟，不代表正式下注。",
        ],
    }


def build_history_replay_ledger(
    *,
    limit: int = 120,
    starting_bankroll: float = 1000.0,
    db_path: str | None = None,
) -> dict[str, Any]:
    stored, duplicate_count, pending_count = _load_settled_prediction_history(limit=limit, db_path=db_path)
    score_validation = build_score_distribution_calibration_status(db_path=db_path)
    original = _simulate_history_mode(
        stored,
        mode="original",
        starting_bankroll=starting_bankroll,
        score_validation=score_validation,
    )
    current = _simulate_history_mode(
        stored,
        mode="current",
        starting_bankroll=starting_bankroll,
        score_validation=score_validation,
    )
    rows = [
        _history_match_row(item, original["runMap"].get(item.run_id, {}), current["runMap"].get(item.run_id, {}))
        for item in stored
    ]
    for mode in (original, current):
        mode.pop("runMap", None)
    return {
        "mode": "history_replay",
        "modeLabel": "历史比赛模拟舱回溯",
        "dedupeMode": "同一比赛保留最近一次预测",
        "settledRuns": len(stored),
        "pendingRuns": pending_count,
        "duplicatesExcluded": duplicate_count,
        "startingBankroll": starting_bankroll,
        "scoreDistributionValidation": score_validation,
        "modes": {
            "original": original,
            "current": current,
        },
        "rows": rows,
        "notes": [
            "历史回放只使用本地已留档预测与已同步 90 分钟赛果。",
            "同一比赛多次分析时，批量回放默认保留最新一次预测，避免重复计算同一场。",
            "原始快照模式用于审计当时模拟舱，当前规则模式用于查看现行闸门如何解释历史样本。",
        ],
    }


def _load_stored_prediction(run_id: int, *, db_path: str | None = None) -> StoredPrediction | None:
    with connect(db_path) as conn:
        row = conn.execute(
            """
            SELECT
                p.id,
                p.created_at,
                p.payload_json,
                r.home_goals_90,
                r.away_goals_90
            FROM prediction_runs AS p
            LEFT JOIN match_results AS r
                ON r.fixture_id = p.match_id
            WHERE p.id = ?
            """,
            (int(run_id),),
        ).fetchone()
    if not row:
        return None
    payload = json.loads(row["payload_json"])
    payload["runId"] = int(row["id"])
    return StoredPrediction(
        run_id=int(row["id"]),
        created_at=str(row["created_at"] or ""),
        payload=payload,
        home_goals_90=None if row["home_goals_90"] is None else int(row["home_goals_90"]),
        away_goals_90=None if row["away_goals_90"] is None else int(row["away_goals_90"]),
    )


def _load_settled_prediction_history(
    *,
    limit: int,
    db_path: str | None = None,
) -> tuple[list[StoredPrediction], int, int]:
    with connect(db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                p.id,
                p.created_at,
                p.payload_json,
                p.match_id,
                r.home_goals_90,
                r.away_goals_90
            FROM prediction_runs AS p
            JOIN match_results AS r
                ON r.fixture_id = p.match_id
            WHERE p.match_id <> ''
            ORDER BY p.id ASC
            """
        ).fetchall()
        pending_count = conn.execute(
            """
            SELECT COUNT(*) AS count
            FROM prediction_runs AS p
            LEFT JOIN match_results AS r
                ON r.fixture_id = p.match_id
            WHERE p.match_id <> '' AND r.fixture_id IS NULL
            """
        ).fetchone()["count"]
    latest_by_fixture: dict[str, Any] = {}
    duplicate_count = 0
    for row in rows:
        fixture_id = str(row["match_id"] or "")
        if fixture_id in latest_by_fixture:
            duplicate_count += 1
        latest_by_fixture[fixture_id] = row
    selected = sorted(latest_by_fixture.values(), key=lambda row: int(row["id"]))[-max(1, int(limit or 120)) :]
    stored: list[StoredPrediction] = []
    for row in selected:
        payload = json.loads(row["payload_json"])
        payload["runId"] = int(row["id"])
        stored.append(
            StoredPrediction(
                run_id=int(row["id"]),
                created_at=str(row["created_at"] or ""),
                payload=payload,
                home_goals_90=int(row["home_goals_90"]),
                away_goals_90=int(row["away_goals_90"]),
            )
        )
    return stored, duplicate_count, int(pending_count or 0)


def _result_payload(stored: StoredPrediction) -> dict[str, Any]:
    if stored.home_goals_90 is None or stored.away_goals_90 is None:
        return {
            "status": "PENDING",
            "statusLabel": "未结算",
            "homeGoals90": None,
            "awayGoals90": None,
            "scoreLabel": "待赛果",
            "actualResult": None,
            "actualResultLabel": "待赛果",
        }
    actual = actual_result_key(stored.home_goals_90, stored.away_goals_90)
    return {
        "status": "SETTLED",
        "statusLabel": "已结算",
        "homeGoals90": stored.home_goals_90,
        "awayGoals90": stored.away_goals_90,
        "scoreLabel": f"{stored.home_goals_90}-{stored.away_goals_90}",
        "actualResult": actual,
        "actualResultLabel": {"home_win": "主胜", "draw": "平局", "away_win": "客胜"}[actual],
    }


def _simulate_history_mode(
    stored_items: list[StoredPrediction],
    *,
    mode: str,
    starting_bankroll: float,
    score_validation: dict[str, Any],
) -> dict[str, Any]:
    bankroll = float(starting_bankroll or 1000.0)
    timeline = [
        {
            "label": "起始",
            "bankroll": bankroll,
            "profit": 0.0,
            "runId": None,
            "market": "-",
            "selection": "-",
        }
    ]
    events: list[dict[str, Any]] = []
    run_map: dict[int, dict[str, Any]] = {}
    all_rows: list[dict[str, Any]] = []
    for stored in stored_items:
        payload = stored.payload
        if mode == "current":
            payload = apply_current_score_validation_to_payload(payload, score_validation) or payload
        unit = _unit_stake(payload)
        simulated = _simulate_mode(
            payload,
            stored,
            mode=mode,
            starting_bankroll=bankroll,
            unit_stake=unit,
            score_validation=score_validation,
        )
        selected = [row for row in simulated["rows"] if row["selected"]]
        match_profit = 0.0
        match_stake = 0.0
        for row in selected:
            profit = float(row.get("profit") or 0.0)
            stake = float(row.get("stake") or 0.0)
            before = bankroll
            bankroll += profit
            match_profit += profit
            match_stake += stake
            event = _history_event(stored, row, before, bankroll, profit)
            events.append(event)
            timeline.append(
                {
                    "label": f"#{stored.run_id}",
                    "bankroll": bankroll,
                    "profit": profit,
                    "runId": stored.run_id,
                    "market": row.get("market") or "-",
                    "selection": row.get("selection") or "-",
                }
            )
        run_summary = {
            "runId": stored.run_id,
            "selectedCount": len(selected),
            "settledCount": sum(1 for row in selected if row["settlementStatus"] == "SETTLED"),
            "totalStake": match_stake,
            "totalProfit": match_profit,
            "roi": (match_profit / match_stake) if match_stake > 0 else 0.0,
            "rows": simulated["rows"],
            "selectedRows": selected,
        }
        run_map[stored.run_id] = run_summary
        all_rows.extend(simulated["rows"])
    total_stake = sum(float(event.get("stake") or 0.0) for event in events)
    total_profit = sum(float(event.get("profit") or 0.0) for event in events)
    hit_count = sum(1 for event in events if float(event.get("profit") or 0.0) > 0)
    loss_count = sum(1 for event in events if float(event.get("profit") or 0.0) < 0)
    return {
        "mode": mode,
        "modeLabel": "原始快照回放" if mode == "original" else "当前规则重放",
        "modeNote": (
            "串联历史预测当时保存的动作和注额。"
            if mode == "original"
            else "用当前闸门重新解释历史预测，只做纸上回放。"
        ),
        "summary": {
            "startingBankroll": float(starting_bankroll or 1000.0),
            "endingBankroll": bankroll,
            "totalRuns": len(stored_items),
            "selectedCount": len(events),
            "hitCount": hit_count,
            "lossCount": loss_count,
            "pushCount": max(0, len(events) - hit_count - loss_count),
            "totalStake": total_stake,
            "totalProfit": total_profit,
            "roi": (total_profit / total_stake) if total_stake > 0 else 0.0,
            "formalEvEnabled": False,
        },
        "marketSummary": _market_summary(all_rows),
        "events": events,
        "timeline": timeline,
        "runMap": run_map,
    }


def _history_event(
    stored: StoredPrediction,
    row: dict[str, Any],
    bankroll_before: float,
    bankroll_after: float,
    profit: float,
) -> dict[str, Any]:
    match = stored.payload.get("match") or {}
    meta = stored.payload.get("meta") or {}
    return {
        "runId": stored.run_id,
        "fixtureId": match.get("id") or meta.get("fixtureId"),
        "match": f"{match.get('homeZh') or match.get('home') or '主队'} vs {match.get('awayZh') or match.get('away') or '客队'}",
        "league": meta.get("leagueNameZh") or translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
        "kickoffBeijing": meta.get("kickoffBeijing") or "",
        "scoreLabel": f"{stored.home_goals_90}-{stored.away_goals_90}",
        "market": row.get("market") or "",
        "selection": row.get("selection") or "",
        "odds": row.get("odds"),
        "stake": row.get("stake") or 0.0,
        "netPerUnit": row.get("netPerUnit"),
        "profit": profit,
        "bankrollBefore": bankroll_before,
        "bankrollAfter": bankroll_after,
        "settlementLabel": row.get("settlementLabel") or "",
    }


def _history_match_row(
    stored: StoredPrediction,
    original: dict[str, Any],
    current: dict[str, Any],
) -> dict[str, Any]:
    match = stored.payload.get("match") or {}
    meta = stored.payload.get("meta") or {}
    return {
        "runId": stored.run_id,
        "fixtureId": match.get("id") or meta.get("fixtureId"),
        "home": match.get("homeZh") or translate_team_display(match.get("home"), "主队"),
        "away": match.get("awayZh") or translate_team_display(match.get("away"), "客队"),
        "homeLogo": match.get("homeLogo") or match.get("home_logo") or "",
        "awayLogo": match.get("awayLogo") or match.get("away_logo") or "",
        "league": meta.get("leagueNameZh") or translate_league_display(meta.get("leagueName"), meta.get("leagueCountry")),
        "kickoffBeijing": meta.get("kickoffBeijing") or "",
        "scoreLabel": f"{stored.home_goals_90}-{stored.away_goals_90}",
        "original": _compact_run_summary(original),
        "current": _compact_run_summary(current),
    }


def _compact_run_summary(summary: dict[str, Any]) -> dict[str, Any]:
    selected = summary.get("selectedRows") or []
    return {
        "selectedCount": summary.get("selectedCount") or 0,
        "totalStake": summary.get("totalStake") or 0.0,
        "totalProfit": summary.get("totalProfit") or 0.0,
        "roi": summary.get("roi") or 0.0,
        "selections": [
            {
                "market": row.get("market"),
                "selection": row.get("selection"),
                "odds": row.get("odds"),
                "profit": row.get("profit"),
                "settlementLabel": row.get("settlementLabel"),
            }
            for row in selected
        ],
    }


def _simulate_mode(
    payload: dict[str, Any],
    stored: StoredPrediction,
    *,
    mode: str,
    starting_bankroll: float,
    unit_stake: float,
    score_validation: dict[str, Any],
) -> dict[str, Any]:
    rows = [
        _replay_row(payload, stored, item, mode=mode, unit_stake=unit_stake, score_validation=score_validation)
        for item in payload.get("recommendations") or []
        if isinstance(item, dict)
    ]
    rows = [row for row in rows if row is not None]
    selected = [row for row in rows if row["selected"]]
    timeline = _timeline(selected, starting_bankroll)
    total_stake = sum(float(row["stake"] or 0.0) for row in selected)
    total_profit = sum(float(row["profit"] or 0.0) for row in selected if row["profit"] is not None)
    settled_count = sum(1 for row in selected if row["settlementStatus"] == "SETTLED")
    return {
        "mode": mode,
        "modeLabel": "原始快照回放" if mode == "original" else "当前规则重放",
        "modeNote": (
            "使用当时保存的动作和注额，最接近真实赛前判断。"
            if mode == "original"
            else "用当前闸门重新解释历史方向；不重新抓盘口，不开放正式资金。"
        ),
        "summary": {
            "startingBankroll": starting_bankroll,
            "unitStake": unit_stake,
            "totalRecommendations": len(rows),
            "selectedCount": len(selected),
            "settledCount": settled_count,
            "totalStake": total_stake,
            "totalProfit": total_profit,
            "roi": (total_profit / total_stake) if total_stake > 0 else 0.0,
            "endingBankroll": starting_bankroll + total_profit,
            "formalEvEnabled": False,
        },
        "marketSummary": _market_summary(rows),
        "rows": rows,
        "timeline": timeline,
    }


def _replay_row(
    payload: dict[str, Any],
    stored: StoredPrediction,
    recommendation: dict[str, Any],
    *,
    mode: str,
    unit_stake: float,
    score_validation: dict[str, Any],
) -> dict[str, Any] | None:
    market = str(recommendation.get("market") or "")
    if not market:
        return None
    selection = localize_selection(
        str(recommendation.get("selection") or ""),
        str((payload.get("match") or {}).get("home") or ""),
        str((payload.get("match") or {}).get("away") or ""),
    )
    odds = _float_or_none(recommendation.get("odds"))
    action = str(recommendation.get("action") or "")
    signal = str(recommendation.get("signal_status") or action)
    selected, stake, eligibility, eligibility_label = _selection_for_mode(
        recommendation,
        market,
        mode=mode,
        unit_stake=unit_stake,
        score_validation=score_validation,
    )
    net = None
    profit = None
    settlement_status = "PENDING"
    settlement_label = "待赛果"
    if stored.home_goals_90 is not None and stored.away_goals_90 is not None and odds and odds > 1:
        try:
            net = _settle_net(
                payload,
                market,
                selection,
                recommendation.get("line"),
                stored.home_goals_90,
                stored.away_goals_90,
                odds,
            )
            settlement_status = "SETTLED"
            settlement_label = _settlement_label(net)
            profit = stake * net if selected else 0.0
        except (TypeError, ValueError):
            settlement_status = "UNSETTLED"
            settlement_label = "无法结算"
    return {
        "market": market,
        "selection": selection,
        "line": recommendation.get("line"),
        "odds": odds,
        "action": action,
        "signalStatus": signal,
        "decisionStatus": recommendation.get("decision_status") or recommendation.get("ev_status") or "",
        "modelProbability": _float_or_none(recommendation.get("model_probability")),
        "modelProbabilityLabel": recommendation.get("model_probability_label") or "模型概率",
        "marketProbability": _float_or_none(recommendation.get("market_probability")),
        "edge": _float_or_none(recommendation.get("edge")),
        "researchEv": _first_float(
            recommendation.get("ev_pbase_research"),
            recommendation.get("expected_value_per_unit"),
        ),
        "paperEv": _first_float(
            recommendation.get("paper_expected_value_per_unit"),
            recommendation.get("conservative_expected_value_per_unit"),
            (recommendation.get("ev_calculation") or {}).get("paperExpectedValue"),
        ),
        "formalEv": _float_or_none(recommendation.get("ev_pfinal_exec")),
        "selected": selected,
        "stake": stake,
        "eligibility": eligibility,
        "eligibilityLabel": eligibility_label,
        "settlementStatus": settlement_status,
        "settlementLabel": settlement_label,
        "netPerUnit": net,
        "profit": profit,
        "reason": recommendation.get("reason") or "",
    }


def _selection_for_mode(
    recommendation: dict[str, Any],
    market: str,
    *,
    mode: str,
    unit_stake: float,
    score_validation: dict[str, Any],
) -> tuple[bool, float, str, str]:
    action = str(recommendation.get("action") or "")
    signal = str(recommendation.get("signal_status") or action)
    if mode == "original":
        stake = float(recommendation.get("stake") or 0.0)
        selected = action in {"BUY", "PAPER_BUY"} and signal == "PAPER_BUY" and stake > 0
        return (
            selected,
            stake if selected else 0.0,
            "ORIGINAL_SELECTED" if selected else "ORIGINAL_NOT_SELECTED",
            "当时已进入纸上模拟" if selected else "当时未买入",
        )

    if signal in {"SUSPENDED", "NO_MARKET"} or action == "NO_MARKET":
        return False, 0.0, "CURRENT_BLOCKED", "当前规则：暂停或市场缺失"
    paper_ev = _first_float(
        recommendation.get("paper_expected_value_per_unit"),
        recommendation.get("conservative_expected_value_per_unit"),
        (recommendation.get("ev_calculation") or {}).get("paperExpectedValue"),
    )
    research_ev = _first_float(recommendation.get("ev_pbase_research"), recommendation.get("expected_value_per_unit"))
    edge = _float_or_none(recommendation.get("edge"))
    passes_value = (
        (paper_ev is not None and paper_ev >= 0.03)
        or (
            paper_ev is None
            and research_ev is not None
            and research_ev >= 0.05
            and (edge is None or edge >= 0.08)
        )
    )
    if not passes_value:
        return False, 0.0, "CURRENT_NO_VALUE", "当前规则：EV 或优势未过线"
    if market == "胜平负":
        model_probability = _float_or_none(recommendation.get("model_probability"))
        if model_probability is not None and model_probability < 0.40:
            return False, 0.0, "CURRENT_PROBABILITY_LOW", "当前规则：胜平负模型概率低于下限"
    return True, unit_stake, "CURRENT_PAPER_SELECTED", "当前规则：纸上重放入选"


def _settle_net(
    payload: dict[str, Any],
    market: str,
    selection: str,
    line: Any,
    home_goals: int,
    away_goals: int,
    odds: float,
) -> float:
    if market == "胜平负":
        return _settle_match_winner(payload, selection, home_goals, away_goals, odds)
    if market == "大小球":
        return _settle_total(selection, float(line), home_goals, away_goals, odds)
    if market == "让球":
        return _settle_handicap(payload, selection, float(line), home_goals, away_goals, odds)
    raise ValueError(f"Unsupported market: {market}")


def _timeline(rows: list[dict[str, Any]], starting_bankroll: float) -> list[dict[str, Any]]:
    bankroll = float(starting_bankroll or 1000.0)
    timeline = [
        {
            "label": "起始",
            "bankroll": bankroll,
            "profit": 0.0,
            "market": "-",
            "selection": "-",
        }
    ]
    for index, row in enumerate(rows, start=1):
        profit = float(row.get("profit") or 0.0)
        bankroll += profit
        timeline.append(
            {
                "label": f"{index}.{row.get('market') or '-'}",
                "bankroll": bankroll,
                "profit": profit,
                "market": row.get("market") or "-",
                "selection": row.get("selection") or "-",
            }
        )
    return timeline


def _market_summary(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for market in ("胜平负", "大小球", "让球"):
        market_rows = [row for row in rows if row["market"] == market]
        selected = [row for row in market_rows if row["selected"]]
        total_stake = sum(float(row["stake"] or 0.0) for row in selected)
        total_profit = sum(float(row["profit"] or 0.0) for row in selected if row["profit"] is not None)
        output.append(
            {
                "market": market,
                "recommendationCount": len(market_rows),
                "selectedCount": len(selected),
                "totalStake": total_stake,
                "totalProfit": total_profit,
                "roi": (total_profit / total_stake) if total_stake > 0 else 0.0,
            }
        )
    return output


def _unit_stake(payload: dict[str, Any]) -> float:
    portfolio = payload.get("portfolio") or {}
    unit = _float_or_none(portfolio.get("unit_stake"))
    if unit and unit > 0:
        return unit
    bankroll = _float_or_none(portfolio.get("bankroll")) or 1000.0
    return max(1.0, min(DEFAULT_REPLAY_UNIT_STAKE, bankroll / 5.0))


def _settlement_label(net: float | None) -> str:
    if net is None:
        return "待赛果"
    if net > 0:
        return "命中"
    if net < 0:
        return "未中"
    return "走水"


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def _first_float(*values: Any) -> float | None:
    for value in values:
        result = _float_or_none(value)
        if result is not None:
            return result
    return None
