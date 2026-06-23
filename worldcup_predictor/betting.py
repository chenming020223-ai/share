from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from .bankroll import dynamic_unit_stake
from .models import PredictionResult, clamp
from .odds import devig_three_way, devig_two_way, is_reasonable_two_way_market, two_way_implied_sum
from .score_calibration import (
    apply_score_market_settlement_calibration,
    market_paper_ev_enabled,
    market_status_label,
)

DEFAULT_MIN_EDGE = 0.08
DEFAULT_MIN_EV = 0.05
DEFAULT_PROBABILITY_DISCOUNT = 0.05
DEFAULT_MIN_CONSERVATIVE_EV = 0.03
DEFAULT_MAX_PROBABILITY_GAP = 0.15
DEFAULT_CONFLICT_PROBABILITY_GAP = 0.20
DEFAULT_MIN_1X2_MODEL_PROBABILITY = 0.40
DEFAULT_MAX_1X2_RESEARCH_ODDS = 4.50
EV_STATUS_RESEARCH_ONLY = "RESEARCH_ONLY"
EV_STATUS_PAPER_OBSERVATION = "PAPER_OBSERVATION"
EV_STATUS_SUSPENDED = "SUSPENDED"
EV_STATUS_MODEL_MARKET_CONFLICT = "MODEL_MARKET_CONFLICT"
EV_STATUS_DISABLED_PFINAL_NOT_APPROVED = "DISABLED_PFINAL_NOT_APPROVED"
EV_STATUS_SUSPENDED_MODEL_DIVERGENCE = EV_STATUS_MODEL_MARKET_CONFLICT
EV_LAYER_PBASE_RESEARCH = "pbase_research"
EV_LAYER_PFINAL_EXEC = "pfinal_exec"
DECISION_NO_VALUE = "NO_VALUE"
DECISION_RESEARCH_OBSERVATION = "RESEARCH_OBSERVATION"
DECISION_PAPER_OBSERVATION = "PAPER_OBSERVATION"
DECISION_HIGH_RISK_OBSERVATION = "HIGH_RISK_OBSERVATION"
DECISION_MODEL_MARKET_CONFLICT = "MODEL_MARKET_CONFLICT"
DECISION_SUSPENDED = "SUSPENDED"
DECISION_FORMAL_EV_DISABLED = "FORMAL_EV_DISABLED"
SIGNAL_STATUS_MODEL_CANDIDATE = "MODEL_CANDIDATE"
SIGNAL_STATUS_RESEARCH_WATCH = "RESEARCH_WATCH"
SIGNAL_STATUS_PAPER_BUY = "PAPER_BUY"
SIGNAL_STATUS_NO_MARKET = "NO_MARKET"
SIGNAL_STATUS_SUSPENDED = "SUSPENDED"


@dataclass(frozen=True)
class BetRecommendation:
    market: str
    selection: str
    line: float | None
    odds: float | None
    model_probability: float
    market_probability: float | None
    edge: float | None
    expected_value_per_unit: float | None
    stake: float
    action: str
    reason: str
    conservative_expected_value_per_unit: float | None = None
    paper_expected_value_per_unit: float | None = None
    adjusted_probability: float | None = None
    shrink_k: float | None = None
    implied_probability: float | None = None
    ev_status: str = EV_STATUS_RESEARCH_ONLY
    decision_status: str = DECISION_RESEARCH_OBSERVATION
    audit_expected_value_per_unit: float | None = None
    audit_conservative_expected_value_per_unit: float | None = None
    audit_paper_expected_value_per_unit: float | None = None
    ev_calculation: dict[str, Any] = field(default_factory=dict)
    ev_layer: str = EV_LAYER_PBASE_RESEARCH
    probability_used: str = "pbase"
    signal_status: str = SIGNAL_STATUS_RESEARCH_WATCH
    ev_pbase_research: float | None = None
    conservative_ev_pbase_research: float | None = None
    ev_qmkt_anchor: float | None = None
    ev_pshr_candidate: float | None = None
    ev_pfinal_exec: float | None = None
    risk_flags: list[str] = field(default_factory=list)
    model_probability_label: str = "模型概率"
    ev_probability_basis: str = "pbase_result_probability"


@dataclass(frozen=True)
class PaperPortfolio:
    bankroll: float
    unit_stake: float
    active_bets: int
    total_stake: float
    bankroll_after_stakes: float
    expected_profit: float
    expected_bankroll: float
    starting_bankroll: float = 1000.0
    parts: int = 5
    profit_reinvest_rate: float = 0.50
    available_for_unit: float = 1000.0
    suggested_unit_stake: float = 200.0
    max_match_exposure: float = 400.0
    stake_source: str = "dynamic"
    policy_label: str = "滚动权益计算；盈利只按 50% 纳入下一轮注额；动态注额按 paper_EV 分档，并扣除未结算预留资金。"
    realized_pnl: float = 0.0
    reserved_stake: float = 0.0
    cash: float = 1000.0
    staking_bankroll: float = 1000.0
    max_daily_exposure: float = 600.0
    max_market_exposure: float = 250.0
    max_league_exposure: float = 300.0
    max_longshot_exposure: float = 100.0
    risk_mode: str = "paper_simulation"


def build_recommendations(
    result: PredictionResult,
    score_probs: dict[tuple[int, int], float],
    market_snapshot,
    bankroll: float = 1000.0,
    unit_stake: float | None = None,
    min_edge: float = DEFAULT_MIN_EDGE,
    min_ev: float = DEFAULT_MIN_EV,
    probability_discount: float = DEFAULT_PROBABILITY_DISCOUNT,
    force_picks: bool = False,
    risk_context: dict[str, Any] | None = None,
    starting_bankroll: float = 1000.0,
    realized_pnl: float | None = None,
    reserved_stake: float = 0.0,
) -> tuple[list[BetRecommendation], PaperPortfolio]:
    bankroll_plan = dynamic_unit_stake(
        bankroll,
        starting_bankroll=starting_bankroll,
        realized_pnl=realized_pnl,
        reserved_stake=reserved_stake,
    )
    stake_source = "manual" if unit_stake is not None and unit_stake > 0 else "dynamic"
    stake = unit_stake if stake_source == "manual" else bankroll_plan.unit_stake
    stake = max(0.0, min(stake, bankroll_plan.cash))

    recommendations = [
        _recommend_match_winner(
            result,
            market_snapshot.match_winner,
            stake,
            min_edge,
            min_ev,
            probability_discount,
            force_picks,
            risk_context,
        ),
        _recommend_total_goals(
            score_probs,
            market_snapshot,
            stake,
            min_edge,
            min_ev,
            probability_discount,
            force_picks,
            result,
            risk_context,
        ),
        _recommend_handicap(
            score_probs,
            market_snapshot,
            result.home_team,
            result.away_team,
            stake,
            min_edge,
            min_ev,
            probability_discount,
            force_picks,
            result,
            risk_context,
        ),
    ]
    recommendations = [
        item if item.action in {"BUY", "PAPER_BUY"} else replace(item, stake=0.0)
        for item in recommendations
    ]
    if stake_source == "dynamic":
        recommendations = _apply_paper_stake_sizing(recommendations, bankroll_plan)
    distribution_audit = build_distribution_audit(result, market_snapshot)
    if distribution_audit["evSuspended"]:
        recommendations = [
            _suspend_ev_for_model_divergence(item, str(distribution_audit["reason"]))
            if item.market == "胜平负"
            else _tag_match_winner_divergence(item, distribution_audit)
            for item in recommendations
        ]

    recommendations = _apply_match_exposure_cap(recommendations, bankroll_plan.max_match_exposure)
    portfolio = recalculate_portfolio(
        PaperPortfolio(
            bankroll=bankroll,
            unit_stake=stake,
            active_bets=0,
            total_stake=0.0,
            bankroll_after_stakes=bankroll,
            expected_profit=0.0,
            expected_bankroll=bankroll,
            starting_bankroll=bankroll_plan.starting_bankroll,
            parts=bankroll_plan.parts,
            profit_reinvest_rate=bankroll_plan.profit_reinvest_rate,
            available_for_unit=bankroll_plan.available_for_unit,
            suggested_unit_stake=bankroll_plan.unit_stake,
            max_match_exposure=bankroll_plan.max_match_exposure,
            stake_source=stake_source,
            realized_pnl=bankroll_plan.realized_pnl,
            reserved_stake=bankroll_plan.reserved_stake,
            cash=bankroll_plan.cash,
            staking_bankroll=bankroll_plan.staking_bankroll,
            max_daily_exposure=bankroll_plan.max_daily_exposure,
            max_market_exposure=bankroll_plan.max_market_exposure,
            max_league_exposure=bankroll_plan.max_league_exposure,
            max_longshot_exposure=bankroll_plan.max_longshot_exposure,
            risk_mode=bankroll_plan.risk_mode,
        ),
        recommendations,
    )
    return recommendations, portfolio


def recalculate_portfolio(
    portfolio: PaperPortfolio,
    recommendations: list[BetRecommendation],
) -> PaperPortfolio:
    active = [item for item in recommendations if item.action in {"BUY", "PAPER_BUY"} and item.stake > 0]
    total_stake = sum(item.stake for item in active)
    expected_profit = sum(
        item.stake * _execution_ev_per_unit(item)
        for item in active
        if _execution_ev_per_unit(item) is not None
    )
    return replace(
        portfolio,
        active_bets=len(active),
        total_stake=total_stake,
        bankroll_after_stakes=max(0.0, portfolio.cash - total_stake),
        expected_profit=expected_profit,
        expected_bankroll=portfolio.bankroll + expected_profit,
    )


def _execution_ev_per_unit(item: BetRecommendation) -> float | None:
    if item.action == "PAPER_BUY":
        return item.paper_expected_value_per_unit
    if item.action == "BUY":
        return item.ev_pfinal_exec if item.ev_pfinal_exec is not None else item.expected_value_per_unit
    return None


def build_distribution_audit(result: PredictionResult, market_snapshot) -> dict[str, object]:
    benchmark_bookmaker = (
        getattr(market_snapshot, "bookmaker_for_market", lambda key: None)("1X2")
        or getattr(market_snapshot, "selected_bookmaker", None)
        or getattr(market_snapshot, "required_bookmaker", None)
        or "盘口"
    )
    market_probs = devig_three_way(
        market_snapshot.match_winner.get("home_win", 0.0),
        market_snapshot.match_winner.get("draw", 0.0),
        market_snapshot.match_winner.get("away_win", 0.0),
    )
    if not market_probs:
        return {
            "status": "NOT_ASSESSED",
            "statusLabel": "无法检查模型分歧",
            "evSuspended": False,
        }

    labels = {
        "home_win": "主胜",
        "draw": "平局",
        "away_win": "客胜",
    }
    gaps = {
        key: result.model_probabilities[key] - market_probs[key]
        for key in ("home_win", "draw", "away_win")
    }
    trigger_key, signed_gap = max(gaps.items(), key=lambda item: abs(item[1]))
    max_gap = abs(signed_gap)
    suspended = max_gap >= DEFAULT_CONFLICT_PROBABILITY_GAP
    high_risk = DEFAULT_MAX_PROBABILITY_GAP <= max_gap < DEFAULT_CONFLICT_PROBABILITY_GAP
    reason = (
        f"模型分歧异常：{labels[trigger_key]} 的 pbase 与 {benchmark_bookmaker} 去水概率相差 "
        f"{max_gap * 100:.1f} 个百分点，达到 {DEFAULT_CONFLICT_PROBABILITY_GAP * 100:.1f} 个百分点冲突线；"
        "胜平负 EV 暂停计算。大小球/让球仅标记跨市场风险，仍按本市场盘口分歧、数据质量和比分分布校准独立判断。"
        if suspended
        else (
            f"最大 pbase / {benchmark_bookmaker} 去水概率差异为 {max_gap * 100:.1f} 个百分点，"
            + (
                "处于 15%-20% 高分歧观察区，不得视为强方向。"
                if high_risk
                else "未触发整场模型分歧暂停。"
            )
        )
    )
    return {
        "status": "ANOMALY" if suspended else "HIGH_RISK" if high_risk else "PASS",
        "statusLabel": "模型市场冲突" if suspended else "高分歧观察" if high_risk else "分歧检查通过",
        "evSuspended": suspended,
        "highRiskObservation": high_risk,
        "triggerSelection": labels[trigger_key],
        "maxProbabilityGap": max_gap,
        "threshold": DEFAULT_MAX_PROBABILITY_GAP,
        "conflictThreshold": DEFAULT_CONFLICT_PROBABILITY_GAP,
        "reason": reason,
        "gaps": gaps,
    }


def _suspend_ev_for_model_divergence(item: BetRecommendation, reason: str) -> BetRecommendation:
    if item.expected_value_per_unit is None:
        if item.action == "NO_MARKET":
            return replace(
                item,
                action="WATCH",
                stake=0.0,
                signal_status=SIGNAL_STATUS_SUSPENDED,
                risk_flags=_append_risk_flag(item.risk_flags, "model_market_divergence"),
                reason=item.reason,
            )
        return replace(
            item,
            action="WATCH",
            stake=0.0,
            reason=reason,
            ev_status=EV_STATUS_MODEL_MARKET_CONFLICT,
            decision_status=DECISION_MODEL_MARKET_CONFLICT,
            signal_status=SIGNAL_STATUS_SUSPENDED,
            ev_pfinal_exec=None,
            risk_flags=_append_risk_flag(item.risk_flags, "model_market_divergence"),
        )
    return replace(
        item,
        action="WATCH",
        stake=0.0,
        reason=reason,
        ev_status=EV_STATUS_MODEL_MARKET_CONFLICT,
        decision_status=DECISION_MODEL_MARKET_CONFLICT,
        audit_expected_value_per_unit=item.expected_value_per_unit,
        audit_conservative_expected_value_per_unit=item.conservative_expected_value_per_unit,
        audit_paper_expected_value_per_unit=item.paper_expected_value_per_unit,
        expected_value_per_unit=None,
        conservative_expected_value_per_unit=None,
        paper_expected_value_per_unit=None,
        signal_status=SIGNAL_STATUS_SUSPENDED,
        ev_pbase_research=item.expected_value_per_unit,
        conservative_ev_pbase_research=item.conservative_expected_value_per_unit,
        ev_pshr_candidate=item.paper_expected_value_per_unit,
        ev_pfinal_exec=None,
        risk_flags=_append_risk_flag(item.risk_flags, "model_market_divergence"),
    )


def _tag_match_winner_divergence(
    item: BetRecommendation,
    distribution_audit: dict[str, object],
) -> BetRecommendation:
    calculation = dict(item.ev_calculation or {})
    if calculation:
        calculation["matchWinnerDistributionAudit"] = {
            "status": distribution_audit.get("status"),
            "statusLabel": distribution_audit.get("statusLabel"),
            "triggerSelection": distribution_audit.get("triggerSelection"),
            "maxProbabilityGap": distribution_audit.get("maxProbabilityGap"),
            "note": "胜平负分歧仅作为跨市场风险标签，不直接暂停大小球/让球。",
        }
    return replace(
        item,
        ev_calculation=calculation,
        risk_flags=_append_risk_flag(item.risk_flags, "MATCH_WINNER_MODEL_MARKET_DIVERGENCE"),
    )


def _suspend_ev_for_selection_divergence(item: BetRecommendation) -> BetRecommendation:
    if item.expected_value_per_unit is None or item.edge is None:
        return item
    if abs(item.edge) < DEFAULT_MAX_PROBABILITY_GAP:
        return item
    if abs(item.edge) < DEFAULT_CONFLICT_PROBABILITY_GAP and item.market == "胜平负":
        return replace(
            item,
            action="WATCH",
            stake=0.0,
            decision_status=DECISION_HIGH_RISK_OBSERVATION,
            signal_status=SIGNAL_STATUS_RESEARCH_WATCH,
            risk_flags=_append_risk_flag(item.risk_flags, "high_model_market_gap"),
            reason=(
                f"pbase 与 qmkt 差值 {abs(item.edge) * 100:.1f}% 处于 15%-20% 高分歧观察区；"
                "保留 research_EV / paper_EV 作复盘，不形成方向。"
            ),
        )
    reason = (
        f"pbase 与当前市场基准去水概率 qmkt 的差值 {abs(item.edge) * 100:.1f}% 超过 "
        f"{DEFAULT_MAX_PROBABILITY_GAP * 100:.1f}% 复核上限；本市场研究 EV 暂停主展示，"
        "仅保留为审计值，不形成研究方向。"
    )
    return replace(
        item,
        action="WATCH",
        stake=0.0,
        reason=reason,
        ev_status=EV_STATUS_MODEL_MARKET_CONFLICT,
        decision_status=DECISION_MODEL_MARKET_CONFLICT,
        audit_expected_value_per_unit=item.expected_value_per_unit,
        audit_conservative_expected_value_per_unit=item.conservative_expected_value_per_unit,
        audit_paper_expected_value_per_unit=item.paper_expected_value_per_unit,
        expected_value_per_unit=None,
        conservative_expected_value_per_unit=None,
        paper_expected_value_per_unit=None,
        signal_status=SIGNAL_STATUS_SUSPENDED,
        ev_pbase_research=item.expected_value_per_unit,
        conservative_ev_pbase_research=item.conservative_expected_value_per_unit,
        ev_pshr_candidate=item.paper_expected_value_per_unit,
        ev_pfinal_exec=None,
        risk_flags=_append_risk_flag(item.risk_flags, "selection_market_divergence"),
    )


def _append_risk_flag(flags: list[str] | None, flag: str) -> list[str]:
    output = list(flags or [])
    if flag not in output:
        output.append(flag)
    return output


def _context_risk_flags(risk_context: dict[str, Any] | None) -> list[str]:
    flags: list[str] = []
    for flag in (risk_context or {}).get("riskFlags") or []:
        flags = _append_risk_flag(flags, str(flag))
    return flags


def _signal_status_for_action(action: str) -> str:
    if action == "NO_MARKET":
        return SIGNAL_STATUS_NO_MARKET
    if action == "PAPER_BUY":
        return SIGNAL_STATUS_PAPER_BUY
    if action == "BUY":
        return SIGNAL_STATUS_MODEL_CANDIDATE
    return SIGNAL_STATUS_RESEARCH_WATCH


def _research_identity_fields(
    *,
    action: str,
    ev: float | None,
    paper_ev: float | None,
    adjusted_probability: float | None,
    shrink_k: float | None,
    qmkt_anchor_ev: float | None,
    probability_used: str,
    ev_calculation: dict[str, Any] | None = None,
    decision_status: str | None = None,
) -> dict[str, Any]:
    calculation = dict(ev_calculation or {})
    if calculation:
        calculation.setdefault("evLayer", EV_LAYER_PBASE_RESEARCH)
        calculation.setdefault("formalExecutionEnabled", False)
        calculation.setdefault("paperSimulationEnabled", action == "PAPER_BUY")
        calculation.setdefault("formalProbabilitySource", "paper_ev_p_adj" if action == "PAPER_BUY" else "pfinal_not_approved")
    return {
        "ev_calculation": calculation,
        "ev_layer": EV_LAYER_PBASE_RESEARCH,
        "probability_used": probability_used,
        "ev_status": EV_STATUS_PAPER_OBSERVATION
        if action == "PAPER_BUY" and paper_ev is not None and paper_ev >= DEFAULT_MIN_CONSERVATIVE_EV
        else EV_STATUS_RESEARCH_ONLY,
        "signal_status": _signal_status_for_action(action),
        "ev_pbase_research": ev,
        "conservative_ev_pbase_research": paper_ev,
        "ev_qmkt_anchor": qmkt_anchor_ev,
        "ev_pshr_candidate": paper_ev,
        "ev_pfinal_exec": None,
        "decision_status": decision_status or _decision_status_for_action(action, paper_ev),
    }


def _recommend_match_winner(
    result: PredictionResult,
    odds: dict[str, float],
    stake: float,
    min_edge: float,
    min_ev: float,
    probability_discount: float,
    force_picks: bool,
    risk_context: dict[str, Any] | None,
) -> BetRecommendation:
    labels = {
        "home_win": f"{result.home_team} 胜",
        "draw": "平局",
        "away_win": f"{result.away_team} 胜",
    }
    market_probs = devig_three_way(
        odds.get("home_win", 0.0),
        odds.get("draw", 0.0),
        odds.get("away_win", 0.0),
    )
    if not market_probs:
        return _missing_market("胜平负", stake, "没有可用的 1X2 欧赔。")

    candidates = []
    for key in ("home_win", "draw", "away_win"):
        model_prob = result.model_probabilities[key]
        market_prob = market_probs[key]
        odd = odds[key]
        ev = model_prob * odd - 1.0
        paper = _paper_ev_layer(
            model_prob=model_prob,
            market_prob=market_prob,
            odd=odd,
            research_ev=ev,
            market_type="1X2",
            risk_context=risk_context,
        )
        implied_probability = 1.0 / odd
        candidates.append((ev, model_prob - market_prob, key, odd, model_prob, market_prob, paper, implied_probability))

    reviewable_candidates = [
        item for item in candidates
        if item[4] >= DEFAULT_MIN_1X2_MODEL_PROBABILITY and item[3] <= DEFAULT_MAX_1X2_RESEARCH_ODDS
    ]
    ev, edge, key, odd, model_prob, market_prob, paper, implied_probability = max(
        reviewable_candidates or candidates,
        key=lambda item: item[0],
    )
    action, reason = _signal_action(
        ev,
        edge,
        paper["paper_ev"],
        model_prob,
        min_edge,
        min_ev,
        force_picks,
        min_model_probability=DEFAULT_MIN_1X2_MODEL_PROBABILITY,
        odds=odd,
        max_odds=DEFAULT_MAX_1X2_RESEARCH_ODDS,
    )
    ev_calculation = _one_x2_ev_calculation(
        model_prob=model_prob,
        market_prob=market_prob,
        odd=odd,
        ev=ev,
        paper_ev=paper["paper_ev"],
        adjusted_probability=paper["adjusted_probability"],
        shrink_k=paper["shrink_k"],
        qmkt_anchor_ev=paper["qmkt_anchor_ev"],
        implied_probability=implied_probability,
        edge=edge,
        probability_discount=probability_discount,
        min_edge=min_edge,
        min_ev=min_ev,
        min_model_probability=DEFAULT_MIN_1X2_MODEL_PROBABILITY,
        max_odds=DEFAULT_MAX_1X2_RESEARCH_ODDS,
        action=action,
    )
    return _suspend_ev_for_selection_divergence(
        BetRecommendation(
            "胜平负",
            labels[key],
            None,
            odd,
            model_prob,
            market_prob,
            edge,
            ev,
            stake,
            action,
            reason,
            paper["paper_ev"],
            paper["paper_ev"],
            paper["adjusted_probability"],
            paper["shrink_k"],
            implied_probability,
            risk_flags=_context_risk_flags(risk_context),
            model_probability_label="模型胜率",
            ev_probability_basis="pbase_result_probability",
            **_research_identity_fields(
                action=action,
                ev=ev,
                paper_ev=paper["paper_ev"],
                adjusted_probability=paper["adjusted_probability"],
                shrink_k=paper["shrink_k"],
                qmkt_anchor_ev=paper["qmkt_anchor_ev"],
                probability_used="pbase",
                ev_calculation=ev_calculation,
            ),
        )
    )


def _recommend_total_goals(
    score_probs: dict[tuple[int, int], float],
    market_snapshot,
    stake: float,
    min_edge: float,
    min_ev: float,
    probability_discount: float,
    force_picks: bool,
    result: PredictionResult,
    risk_context: dict[str, Any] | None,
) -> BetRecommendation:
    line_odds = market_snapshot.best_total_line()
    if not line_odds:
        return _missing_market("大小球", stake, "没有可用的大小球赔率。")

    line, odds = line_odds
    if not _reasonable_two_way_odds(odds.get("over", 0.0), odds.get("under", 0.0)):
        return _invalid_market("大小球", line, stake, "大小球盘口水位异常，已排除。")
    market_probs = devig_two_way(odds.get("over", 0.0), odds.get("under", 0.0), "over", "under")
    if not market_probs:
        return _missing_market("大小球", stake, "大小球赔率不完整。")

    candidates = []
    for side in ("over", "under"):
        settlement = apply_score_market_settlement_calibration(
            _asian_total_settlement(score_probs, line, side, odds[side]),
            odds[side],
            "OU",
            side,
            (risk_context or {}).get("scoreDistributionCalibration"),
        )
        model_prob = settlement["positive"]
        ev = settlement["ev"]
        edge = model_prob - market_probs[side]
        paper = _paper_ev_layer(
            model_prob=model_prob,
            market_prob=market_probs[side],
            odd=odds[side],
            research_ev=ev,
            market_type="OU",
            risk_context=risk_context,
        )
        implied_probability = 1.0 / odds[side]
        candidates.append((ev, edge, side, odds[side], model_prob, market_probs[side], paper, implied_probability, settlement))

    ev, edge, side, odd, model_prob, market_prob, paper, implied_probability, settlement = max(candidates, key=lambda item: item[0])
    label = f"{'大' if side == 'over' else '小'} {line:g}"
    action, reason = _signal_action(ev, edge, paper["paper_ev"], model_prob, min_edge, min_ev, force_picks)
    ev_calculation = _asian_ev_calculation(
        market_type="OU",
        formula_label="EV = 盈利注权重 × (赔率 - 1) - 亏损注权重",
        model_prob=model_prob,
        market_prob=market_prob,
        odd=odd,
        ev=ev,
        paper_ev=paper["paper_ev"],
        adjusted_probability=paper["adjusted_probability"],
        shrink_k=paper["shrink_k"],
        qmkt_anchor_ev=paper["qmkt_anchor_ev"],
        implied_probability=implied_probability,
        edge=edge,
        line=line,
        settlement=settlement,
        probability_discount=probability_discount,
        min_edge=min_edge,
        min_ev=min_ev,
        action=action,
    )
    item = _suspend_ev_for_selection_divergence(
        BetRecommendation(
            "大小球",
            label,
            line,
            odd,
            model_prob,
            market_prob,
            edge,
            ev,
            stake,
            action,
            reason,
            paper["paper_ev"],
            paper["paper_ev"],
            paper["adjusted_probability"],
            paper["shrink_k"],
            implied_probability,
            risk_flags=_context_risk_flags(risk_context),
            model_probability_label="正收益概率",
            ev_probability_basis="asian_settlement_weight",
            **_research_identity_fields(
                action=action,
                ev=ev,
                paper_ev=paper["paper_ev"],
                adjusted_probability=paper["adjusted_probability"],
                shrink_k=paper["shrink_k"],
                qmkt_anchor_ev=paper["qmkt_anchor_ev"],
                probability_used="score_matrix_pbase",
                ev_calculation=ev_calculation,
            ),
        )
    )
    return _apply_score_market_shutdown(item, result, risk_context)


def _recommend_handicap(
    score_probs: dict[tuple[int, int], float],
    market_snapshot,
    home_team: str,
    away_team: str,
    stake: float,
    min_edge: float,
    min_ev: float,
    probability_discount: float,
    force_picks: bool,
    result: PredictionResult,
    risk_context: dict[str, Any] | None,
) -> BetRecommendation:
    line_odds = market_snapshot.best_handicap_line()
    if not line_odds:
        return _missing_market("让球", stake, "没有可用的让球赔率。")

    home_line, odds = line_odds
    if not _reasonable_two_way_odds(odds.get("home", 0.0), odds.get("away", 0.0)):
        return _invalid_market("让球", home_line, stake, "让球盘口水位异常，已排除。")
    market_probs = devig_two_way(odds.get("home", 0.0), odds.get("away", 0.0), "home", "away")
    if not market_probs:
        return _missing_market("让球", stake, "让球赔率不完整。")

    candidates = []
    for side in ("home", "away"):
        settlement = apply_score_market_settlement_calibration(
            _asian_handicap_settlement(score_probs, home_line, side, odds[side]),
            odds[side],
            "AH",
            side,
            (risk_context or {}).get("scoreDistributionCalibration"),
        )
        model_prob = settlement["positive"]
        ev = settlement["ev"]
        edge = model_prob - market_probs[side]
        paper = _paper_ev_layer(
            model_prob=model_prob,
            market_prob=market_probs[side],
            odd=odds[side],
            research_ev=ev,
            market_type="AH",
            risk_context=risk_context,
        )
        implied_probability = 1.0 / odds[side]
        candidates.append((ev, edge, side, odds[side], model_prob, market_probs[side], paper, implied_probability, settlement))

    ev, edge, side, odd, model_prob, market_prob, paper, implied_probability, settlement = max(candidates, key=lambda item: item[0])
    label = _handicap_label(side, home_line, home_team, away_team)
    action, reason = _signal_action(ev, edge, paper["paper_ev"], model_prob, min_edge, min_ev, force_picks)
    ev_calculation = _asian_ev_calculation(
        market_type="AH",
        formula_label="EV = 赢盘注权重 × (赔率 - 1) - 输盘注权重",
        model_prob=model_prob,
        market_prob=market_prob,
        odd=odd,
        ev=ev,
        paper_ev=paper["paper_ev"],
        adjusted_probability=paper["adjusted_probability"],
        shrink_k=paper["shrink_k"],
        qmkt_anchor_ev=paper["qmkt_anchor_ev"],
        implied_probability=implied_probability,
        edge=edge,
        line=home_line,
        settlement=settlement,
        probability_discount=probability_discount,
        min_edge=min_edge,
        min_ev=min_ev,
        action=action,
    )
    item = _suspend_ev_for_selection_divergence(
        BetRecommendation(
            "让球",
            label,
            home_line,
            odd,
            model_prob,
            market_prob,
            edge,
            ev,
            stake,
            action,
            reason,
            paper["paper_ev"],
            paper["paper_ev"],
            paper["adjusted_probability"],
            paper["shrink_k"],
            implied_probability,
            risk_flags=_context_risk_flags(risk_context),
            model_probability_label="正收益概率",
            ev_probability_basis="asian_settlement_weight",
            **_research_identity_fields(
                action=action,
                ev=ev,
                paper_ev=paper["paper_ev"],
                adjusted_probability=paper["adjusted_probability"],
                shrink_k=paper["shrink_k"],
                qmkt_anchor_ev=paper["qmkt_anchor_ev"],
                probability_used="score_matrix_pbase",
                ev_calculation=ev_calculation,
            ),
        )
    )
    return _apply_score_market_shutdown(item, result, risk_context)


def asian_total_positive_return_probability(
    score_probs: dict[tuple[int, int], float],
    line: float,
    side: str,
) -> float:
    return _asian_total_settlement(score_probs, line, side)["positive"]


def asian_total_expected_value(
    score_probs: dict[tuple[int, int], float],
    line: float,
    side: str,
    odd: float,
) -> float:
    return _asian_total_settlement(score_probs, line, side, odd)["ev"]


def asian_handicap_positive_return_probability(
    score_probs: dict[tuple[int, int], float],
    home_line: float,
    side: str,
) -> float:
    return _asian_handicap_settlement(score_probs, home_line, side)["positive"]


def asian_handicap_expected_value(
    score_probs: dict[tuple[int, int], float],
    home_line: float,
    side: str,
    odd: float,
) -> float:
    return _asian_handicap_settlement(score_probs, home_line, side, odd)["ev"]


def _asian_total_settlement(
    score_probs: dict[tuple[int, int], float],
    line: float,
    side: str,
    odd: float = 2.0,
) -> dict[str, float]:
    lines = _split_asian_line(line)
    positive = 0.0
    ev = 0.0
    win_fraction_total = 0.0
    loss_fraction_total = 0.0
    full_win = 0.0
    half_win = 0.0
    push = 0.0
    half_loss = 0.0
    full_loss = 0.0
    for (home_goals, away_goals), probability in score_probs.items():
        goals = home_goals + away_goals
        net, win_fraction, loss_fraction = _split_settlement_net(
            ((goals - split_line if side == "over" else split_line - goals) for split_line in lines),
            odd,
        )
        if net > 0:
            positive += probability
        bucket = _settlement_bucket(net, odd)
        if bucket == "full_win":
            full_win += probability
        elif bucket == "half_win":
            half_win += probability
        elif bucket == "push":
            push += probability
        elif bucket == "half_loss":
            half_loss += probability
        elif bucket == "full_loss":
            full_loss += probability
        win_fraction_total += probability * win_fraction
        loss_fraction_total += probability * loss_fraction
        ev += probability * net
    return {
        "positive": positive,
        "ev": ev,
        "win_fraction": win_fraction_total,
        "loss_fraction": loss_fraction_total,
        "full_win": full_win,
        "half_win": half_win,
        "push": push,
        "half_loss": half_loss,
        "full_loss": full_loss,
        "break_even_odds": _break_even_odds(win_fraction_total, loss_fraction_total),
    }


def _asian_handicap_settlement(
    score_probs: dict[tuple[int, int], float],
    home_line: float,
    side: str,
    odd: float = 2.0,
) -> dict[str, float]:
    home_lines = _split_asian_line(home_line)
    positive = 0.0
    ev = 0.0
    win_fraction_total = 0.0
    loss_fraction_total = 0.0
    full_win = 0.0
    half_win = 0.0
    push = 0.0
    half_loss = 0.0
    full_loss = 0.0
    for (home_goals, away_goals), probability in score_probs.items():
        diffs = []
        for split_line in home_lines:
            diff = home_goals + split_line - away_goals
            if side == "away":
                diff = -diff
            diffs.append(diff)
        net, win_fraction, loss_fraction = _split_settlement_net(diffs, odd)
        if net > 0:
            positive += probability
        bucket = _settlement_bucket(net, odd)
        if bucket == "full_win":
            full_win += probability
        elif bucket == "half_win":
            half_win += probability
        elif bucket == "push":
            push += probability
        elif bucket == "half_loss":
            half_loss += probability
        elif bucket == "full_loss":
            full_loss += probability
        win_fraction_total += probability * win_fraction
        loss_fraction_total += probability * loss_fraction
        ev += probability * net
    return {
        "positive": positive,
        "ev": ev,
        "win_fraction": win_fraction_total,
        "loss_fraction": loss_fraction_total,
        "full_win": full_win,
        "half_win": half_win,
        "push": push,
        "half_loss": half_loss,
        "full_loss": full_loss,
        "break_even_odds": _break_even_odds(win_fraction_total, loss_fraction_total),
    }


def _split_settlement_net(diffs, odd: float) -> tuple[float, float, float]:
    diff_list = list(diffs)
    if not diff_list:
        return 0.0, 0.0, 0.0
    win_fraction = 0.0
    loss_fraction = 0.0
    net = 0.0
    for diff in diff_list:
        if diff > 1e-9:
            win_fraction += 1.0
            net += odd - 1.0
        elif diff < -1e-9:
            loss_fraction += 1.0
            net -= 1.0
    count = len(diff_list)
    return net / count, win_fraction / count, loss_fraction / count


def _settlement_bucket(net: float, odd: float) -> str:
    full_win_net = odd - 1.0
    half_win_net = full_win_net / 2.0
    if _near(net, full_win_net):
        return "full_win"
    if _near(net, half_win_net):
        return "half_win"
    if _near(net, 0.0):
        return "push"
    if _near(net, -0.5):
        return "half_loss"
    return "full_loss"


def _near(left: float, right: float, tolerance: float = 1e-9) -> bool:
    return abs(left - right) <= tolerance


def _break_even_odds(win_fraction: float, loss_fraction: float) -> float | None:
    if win_fraction <= 1e-12:
        return None
    return 1.0 + loss_fraction / win_fraction


def _split_asian_line(line: float) -> list[float]:
    rounded = round(line * 4) / 4
    lower = math.floor(rounded * 2) / 2
    upper = math.ceil(rounded * 2) / 2
    if abs(lower - upper) < 1e-9:
        return [rounded]
    return [lower, upper]


def _settlement_net(diff: float, odd: float) -> float:
    if diff > 1e-9:
        return odd - 1.0
    if diff < -1e-9:
        return -1.0
    return 0.0


def _reasonable_two_way_odds(first_odds: float, second_odds: float) -> bool:
    return is_reasonable_two_way_market(first_odds, second_odds)


def _conservative_ev(ev: float, odd: float, probability_discount: float) -> float:
    discount = clamp(probability_discount, 0.0, 0.5)
    return ev - discount * odd


def _paper_ev_layer(
    *,
    model_prob: float,
    market_prob: float,
    odd: float,
    research_ev: float,
    market_type: str,
    risk_context: dict[str, Any] | None,
) -> dict[str, float]:
    shrink_k = _dynamic_shrink_k(model_prob, market_prob, odd, market_type, risk_context)
    adjusted_probability = clamp(market_prob + shrink_k * (model_prob - market_prob), 0.0, 1.0)
    qmkt_anchor_ev = market_prob * odd - 1.0
    if market_type == "1X2":
        paper_ev = adjusted_probability * odd - 1.0
    else:
        paper_ev = qmkt_anchor_ev + shrink_k * (research_ev - qmkt_anchor_ev)
    return {
        "shrink_k": shrink_k,
        "adjusted_probability": adjusted_probability,
        "paper_ev": paper_ev,
        "qmkt_anchor_ev": qmkt_anchor_ev,
    }


def _dynamic_shrink_k(
    model_prob: float,
    market_prob: float,
    odd: float,
    market_type: str,
    risk_context: dict[str, Any] | None,
) -> float:
    context = risk_context or {}
    gap = abs(model_prob - market_prob)
    k = 0.45
    if context:
        k = 0.35
    if context.get("missingTechnicalStats") or context.get("missingXg"):
        k = min(k, 0.25)
    if context.get("youthFlag") or context.get("friendlyFlag"):
        k = min(k, 0.15)
    if context.get("youthFlag") and context.get("friendlyFlag") and (
        context.get("missingTechnicalStats") or context.get("missingXg")
    ):
        k = 0.0
    if gap >= DEFAULT_CONFLICT_PROBABILITY_GAP:
        k = 0.0
    elif gap >= DEFAULT_MAX_PROBABILITY_GAP:
        k = min(k, 0.20)
    elif gap >= 0.10:
        k = min(k, 0.30)
    if odd < 1.35:
        k = min(k, 0.25)
    elif odd > 3.50:
        k = min(k, 0.10)
    elif odd > 2.20:
        k = min(k, 0.25)
    if market_type in {"OU", "AH"} and (
        context.get("youthFlag")
        or context.get("friendlyFlag")
        or context.get("missingTechnicalStats")
        or context.get("missingXg")
    ):
        k = 0.0
    return clamp(k, 0.0, 0.60)


def _passes_signal_gate(ev: float, edge: float, paper_ev: float, min_edge: float, min_ev: float) -> bool:
    return ev >= min_ev and edge >= min_edge and paper_ev >= DEFAULT_MIN_CONSERVATIVE_EV


def _buy_reason(min_edge: float, min_ev: float) -> str:
    return (
        "通过纸上模拟闸门：research_EV 为正，模型优势达到 "
        f"{min_edge * 100:.1f}%，基础 EV 达到 {min_ev * 100:.1f}%，"
        f"paper_EV 达到 {DEFAULT_MIN_CONSERVATIVE_EV * 100:.1f}%；资金占用按 paper_EV 计算。"
    )


def _watch_reason(min_edge: float, min_ev: float, paper_ev: float | None) -> str:
    paper_text = "-" if paper_ev is None else f"{paper_ev * 100:.1f}%"
    return (
        "未通过研究试算 EV 门槛，观望。需要同时满足："
        f"基础 EV≥{min_ev * 100:.1f}%、模型优势≥{min_edge * 100:.1f}%、"
        f"paper_EV≥{DEFAULT_MIN_CONSERVATIVE_EV * 100:.1f}%；当前 paper_EV {paper_text}。"
    )


def _signal_action(
    ev: float,
    edge: float,
    paper_ev: float,
    model_probability: float,
    min_edge: float,
    min_ev: float,
    force_picks: bool,
    min_model_probability: float = 0.0,
    odds: float | None = None,
    max_odds: float | None = None,
) -> tuple[str, str]:
    if model_probability < min_model_probability:
        return (
            "WATCH",
            f"pbase 基础概率 {model_probability * 100:.1f}% 低于胜平负研究方向下限 "
            f"{min_model_probability * 100:.1f}%，不将高赔率直接视为机会。",
        )
    if max_odds is not None and odds is not None and odds > max_odds:
        return (
            "WATCH",
            f"1X2 赔率 {odds:.2f} 高于高赔率复核上限 {max_odds:.2f}；"
            "当前只记录研究 EV，不进入纸上资金或正式模拟方向。",
        )
    if abs(edge) >= DEFAULT_CONFLICT_PROBABILITY_GAP:
        return (
            "WATCH",
            f"pbase 与当前市场基准去水概率 qmkt 的差值 {abs(edge) * 100:.1f}% 超过 "
            f"{DEFAULT_CONFLICT_PROBABILITY_GAP * 100:.1f}% 冲突线，不形成研究方向。",
        )
    if abs(edge) >= DEFAULT_MAX_PROBABILITY_GAP:
        return (
            "WATCH",
            f"pbase 与 qmkt 差值 {abs(edge) * 100:.1f}% 处于高分歧观察区，不得视为强方向。",
        )
    if _passes_signal_gate(ev, edge, paper_ev, min_edge, min_ev):
        return "PAPER_BUY", _buy_reason(min_edge, min_ev)
    if force_picks:
        return "PAPER_BUY", "强制均注演示：当前未达到保守信号门槛。"
    return "WATCH", _watch_reason(min_edge, min_ev, paper_ev)


def _decision_status_for_action(action: str, paper_ev: float | None) -> str:
    if action == "NO_MARKET":
        return DECISION_NO_VALUE
    if action == "PAPER_BUY":
        return DECISION_PAPER_OBSERVATION
    if action == "BUY":
        return DECISION_PAPER_OBSERVATION if paper_ev is not None and paper_ev >= DEFAULT_MIN_CONSERVATIVE_EV else DECISION_RESEARCH_OBSERVATION
    return DECISION_RESEARCH_OBSERVATION


def _apply_score_market_shutdown(
    item: BetRecommendation,
    result: PredictionResult,
    risk_context: dict[str, Any] | None,
) -> BetRecommendation:
    if item.market not in {"大小球", "让球"} or item.action == "NO_MARKET":
        return item
    context = risk_context or {}
    risk_flags = list(item.risk_flags)
    for flag in list(context.get("riskFlags") or []):
        risk_flags = _append_risk_flag(risk_flags, str(flag))
    lambda_total = (result.expected_goals_home or 0.0) + (result.expected_goals_away or 0.0)
    raw_lambda_total = (result.raw_expected_goals_home or result.expected_goals_home or 0.0) + (
        result.raw_expected_goals_away or result.expected_goals_away or 0.0
    )
    if raw_lambda_total >= 3.80:
        risk_flags = _append_risk_flag(risk_flags, "EXTREME_TOTAL_GOALS_LAMBDA")
    elif raw_lambda_total >= 3.30 or lambda_total >= 3.30:
        risk_flags = _append_risk_flag(risk_flags, "HIGH_TOTAL_GOALS_LAMBDA")
    if item.market == "大小球" and item.edge is not None and abs(item.edge) >= DEFAULT_MAX_PROBABILITY_GAP:
        return _suspend_score_market(
            item,
            "TOTAL_GOALS_MODEL_MARKET_CONFLICT",
            "大小球比分分布与盘口去水概率分歧达到 15% 以上，当前只能进入异常观察池。",
            risk_flags,
            decision_status=DECISION_MODEL_MARKET_CONFLICT,
        )
    if item.market == "让球":
        risk_flags = _append_risk_flag(risk_flags, "HANDICAP_MARGIN_DISTRIBUTION_NOT_CALIBRATED")
    if item.signal_status == SIGNAL_STATUS_SUSPENDED or item.decision_status in {
        DECISION_MODEL_MARKET_CONFLICT,
        DECISION_SUSPENDED,
    }:
        return replace(item, risk_flags=risk_flags)
    if context.get("youthFlag") or context.get("friendlyFlag") or context.get("missingXg") or context.get("missingTechnicalStats"):
        reason = (
            f"{item.market}依赖比分分布专项校准；当前赛事存在 U21/友谊赛/缺 xG 或技术统计风险，"
            "formal_EV 关闭，本方向暂停，仅进入异常观察池。"
        )
        return _suspend_score_market(item, "DATA_QUALITY_RISK", reason, risk_flags)
    if raw_lambda_total >= 3.80 and item.market == "大小球":
        return _suspend_score_market(
            item,
            "EXTREME_TOTAL_GOALS_LAMBDA",
            "原始 λ_total 达到极端总进球风险区，大小球方向暂停，仅保留审计。",
            risk_flags,
        )
    calibration = (item.ev_calculation or {}).get("scoreDistributionCalibration") or {}
    calibration_note = ""
    if calibration.get("applied"):
        factor = calibration.get("positiveFactor")
        factor_text = f"（{calibration.get('sideLabel') or item.market}因子 {factor:.2f}）" if isinstance(factor, (int, float)) else ""
        calibration_note = f"已应用比分分布独立校准{factor_text}；"
    score_validation = context.get("scoreDistributionCalibration")
    if market_paper_ev_enabled(score_validation, item.market):
        calculation = dict(item.ev_calculation or {})
        calculation["paperSimulationEnabled"] = item.action == "PAPER_BUY"
        calculation["formalExecutionEnabled"] = False
        calculation["formalProbabilitySource"] = "paper_score_distribution_validated_pfinal_not_approved"
        calculation["scoreDistributionValidation"] = (
            ((score_validation or {}).get("markets") or {}).get("OU" if item.market == "大小球" else "AH")
        )
        return replace(
            item,
            reason=(
                f"{item.reason} {calibration_note}{item.market}已通过比分分布独立校准，"
                "允许输出 paper_EV 候选；但 formal_EV 仍需 pfinal 人工审批，资金占用会被正式闸门控制。"
            ),
            risk_flags=_append_risk_flag(risk_flags, "SCORE_DISTRIBUTION_PAPER_VALIDATED"),
            ev_calculation=calculation,
        )
    return _score_market_paper_research_open(
        item,
        risk_flags,
        reason=(
            f"{calibration_note}{item.market}依赖比分分布专项校准；当前状态："
            f"{market_status_label(score_validation, item.market)}。"
            "已按共享版纸上模拟口径开放 paper_EV、p_adj 与 shrink_k；"
            "formal_EV 未审批，当前只占用纸上模拟资金。"
        ),
    )


def _score_market_research_only(
    item: BetRecommendation,
    risk_flags: list[str],
    *,
    reason: str,
) -> BetRecommendation:
    calculation = _score_market_research_only_calculation(item.ev_calculation)
    return replace(
        item,
        action="WATCH",
        stake=0.0,
        reason=reason,
        conservative_expected_value_per_unit=None,
        paper_expected_value_per_unit=None,
        adjusted_probability=None,
        shrink_k=None,
        ev_status=EV_STATUS_RESEARCH_ONLY,
        decision_status=DECISION_RESEARCH_OBSERVATION,
        signal_status=SIGNAL_STATUS_RESEARCH_WATCH,
        ev_pbase_research=item.ev_pbase_research if item.ev_pbase_research is not None else item.expected_value_per_unit,
        conservative_ev_pbase_research=None,
        ev_pshr_candidate=None,
        ev_pfinal_exec=None,
        risk_flags=_append_risk_flag(risk_flags, "SCORE_DISTRIBUTION_NOT_VALIDATED"),
        ev_calculation=calculation,
    )


def _score_market_paper_research_open(
    item: BetRecommendation,
    risk_flags: list[str],
    *,
    reason: str,
) -> BetRecommendation:
    calculation = _score_market_paper_research_open_calculation(item.ev_calculation)
    risk_flags = _append_risk_flag(risk_flags, "SCORE_DISTRIBUTION_NOT_VALIDATED")
    risk_flags = _append_risk_flag(risk_flags, "PAPER_EV_RESEARCH_OPEN")
    action = item.action if item.action in {"PAPER_BUY", "BUY"} else "WATCH"
    stake = item.stake if action == "PAPER_BUY" else 0.0
    signal_status = SIGNAL_STATUS_PAPER_BUY if action == "PAPER_BUY" else SIGNAL_STATUS_RESEARCH_WATCH
    decision_status = DECISION_PAPER_OBSERVATION if action == "PAPER_BUY" else DECISION_RESEARCH_OBSERVATION
    calculation["paperSimulationEnabled"] = action == "PAPER_BUY" and stake > 0
    calculation["candidateAction"] = action
    calculation["paperReviewOnly"] = action != "PAPER_BUY"
    return replace(
        item,
        action=action,
        stake=stake,
        reason=reason,
        ev_status=EV_STATUS_PAPER_OBSERVATION,
        decision_status=decision_status,
        signal_status=signal_status,
        ev_pbase_research=item.ev_pbase_research if item.ev_pbase_research is not None else item.expected_value_per_unit,
        conservative_ev_pbase_research=None,
        ev_pfinal_exec=None,
        risk_flags=risk_flags,
        ev_calculation=calculation,
    )


def _score_market_paper_research_open_calculation(calculation: dict[str, Any]) -> dict[str, Any]:
    if not calculation:
        return {}
    updated = dict(calculation)
    updated["evDecisionLayer"] = "paper_research_open"
    updated["paperSimulationEnabled"] = False
    updated["formalExecutionEnabled"] = False
    updated["formalProbabilitySource"] = "paper_ev_research_open_pfinal_not_approved"
    updated["candidateAction"] = "WATCH"
    updated["paperReviewOnly"] = True
    updated["paperOpenReason"] = "专项验收未通过时按共享版保留纸上模拟层；不触发 formal_EV 或真实资金。"
    if not updated.get("paperFormula"):
        updated["paperFormula"] = "paper_EV = qmkt_anchor_EV + k × (research_EV - qmkt_anchor_EV)"
    gates = []
    for gate in updated.get("gates") or []:
        gate_copy = dict(gate)
        if gate_copy.get("key") == "paper_ev":
            gate_copy.update(
                {
                    "label": "纸上EV",
                    "enabled": True,
                    "reason": "纸上模拟开放：可占用纸上资金，formal_EV 继续等待 pfinal 审批。",
                }
            )
        gates.append(gate_copy)
    updated["gates"] = gates
    return updated


def _score_market_research_only_calculation(calculation: dict[str, Any]) -> dict[str, Any]:
    if not calculation:
        return {}
    updated = dict(calculation)
    updated["paperExpectedValue"] = None
    updated["conservativeExpectedValue"] = None
    updated["adjustedProbability"] = None
    updated["shrinkK"] = None
    calibration = updated.get("scoreDistributionCalibration") or updated.get("totalGoalsCalibration") or {}
    if isinstance(calibration, dict) and calibration.get("applied"):
        updated["paperFormula"] = "已应用比分分布独立校准修正 research_EV；该市场尚未通过 paper_EV 独立验收。"
    else:
        updated["paperFormula"] = "比分分布层未完成独立校准，paper_EV 暂不开放。"
    updated["evDecisionLayer"] = "research_audit_only"
    updated["paperSimulationEnabled"] = False
    updated["formalExecutionEnabled"] = False
    updated["formalProbabilitySource"] = "pfinal_not_approved"
    updated["candidateAction"] = "WATCH"
    gates = []
    for gate in updated.get("gates") or []:
        gate_copy = dict(gate)
        if gate_copy.get("key") == "paper_ev":
            gate_copy.update(
                {
                    "label": "纸上EV",
                    "value": None,
                    "passed": False,
                    "enabled": False,
                    "reason": "大小球/让球需完成比分分布专项校准后才开放 paper_EV。",
                }
            )
        gates.append(gate_copy)
    updated["gates"] = gates
    return updated


def _suspend_score_market(
    item: BetRecommendation,
    flag: str,
    reason: str,
    risk_flags: list[str],
    *,
    decision_status: str = DECISION_SUSPENDED,
) -> BetRecommendation:
    risk_flags = _append_risk_flag(risk_flags, flag)
    risk_flags = _append_risk_flag(risk_flags, "FORMAL_EV_DISABLED")
    return replace(
        item,
        action="WATCH",
        stake=0.0,
        reason=reason,
        ev_status=EV_STATUS_SUSPENDED if decision_status == DECISION_SUSPENDED else EV_STATUS_MODEL_MARKET_CONFLICT,
        decision_status=decision_status,
        audit_expected_value_per_unit=(
            item.audit_expected_value_per_unit
            if item.audit_expected_value_per_unit is not None
            else item.expected_value_per_unit
        ),
        audit_conservative_expected_value_per_unit=(
            item.audit_conservative_expected_value_per_unit
            if item.audit_conservative_expected_value_per_unit is not None
            else item.conservative_expected_value_per_unit
        ),
        audit_paper_expected_value_per_unit=(
            item.audit_paper_expected_value_per_unit
            if item.audit_paper_expected_value_per_unit is not None
            else item.paper_expected_value_per_unit
        ),
        expected_value_per_unit=None,
        conservative_expected_value_per_unit=None,
        paper_expected_value_per_unit=None,
        signal_status=SIGNAL_STATUS_SUSPENDED,
        ev_pbase_research=(
            item.ev_pbase_research if item.ev_pbase_research is not None else item.expected_value_per_unit
        ),
        conservative_ev_pbase_research=(
            item.conservative_ev_pbase_research
            if item.conservative_ev_pbase_research is not None
            else item.conservative_expected_value_per_unit
        ),
        ev_pshr_candidate=item.ev_pshr_candidate if item.ev_pshr_candidate is not None else item.paper_expected_value_per_unit,
        ev_pfinal_exec=None,
        risk_flags=risk_flags,
    )


def _one_x2_ev_calculation(
    *,
    model_prob: float,
    market_prob: float,
    odd: float,
    ev: float,
    paper_ev: float,
    adjusted_probability: float,
    shrink_k: float,
    qmkt_anchor_ev: float,
    implied_probability: float,
    edge: float,
    probability_discount: float,
    min_edge: float,
    min_ev: float,
    min_model_probability: float,
    max_odds: float | None,
    action: str,
) -> dict[str, Any]:
    win_fraction = model_prob
    loss_fraction = max(0.0, 1.0 - model_prob)
    return {
        "type": "1X2",
        "probabilitySource": "pbase",
        "formula": "EV = pbase × odds - 1",
        "expandedFormula": "EV = pbase × (odds - 1) - (1 - pbase)",
        "modelProbability": model_prob,
        "modelProbabilityLabel": "模型胜率",
        "evProbabilityBasis": "pbase_result_probability",
        "marketProbability": market_prob,
        "impliedProbability": implied_probability,
        "edge": edge,
        "odds": odd,
        "line": None,
        "winStakeFraction": win_fraction,
        "lossStakeFraction": loss_fraction,
        "breakEvenOdds": (1.0 / model_prob) if model_prob > 0 else None,
        "expectedValue": ev,
        "researchExpectedValue": ev,
        "paperExpectedValue": paper_ev,
        "conservativeExpectedValue": paper_ev,
        "qmktAnchorExpectedValue": qmkt_anchor_ev,
        "shrinkK": shrink_k,
        "adjustedProbability": adjusted_probability,
        "probabilityDiscount": clamp(probability_discount, 0.0, 0.5),
        "paperFormula": "p_adj = qmkt + k × (pbase - qmkt); paper_EV = p_adj × odds - 1",
        "conservativeFormula": "已废弃旧公式：EV - probability_discount × odds",
        "gates": _gate_audit(
            ev,
            edge,
            paper_ev,
            model_prob,
            min_edge,
            min_ev,
            min_model_probability,
            odds=odd,
            max_odds=max_odds,
        ),
        "candidateAction": action,
    }


def _asian_ev_calculation(
    *,
    market_type: str,
    formula_label: str,
    model_prob: float,
    market_prob: float,
    odd: float,
    ev: float,
    paper_ev: float,
    adjusted_probability: float,
    shrink_k: float,
    qmkt_anchor_ev: float,
    implied_probability: float,
    edge: float,
    line: float,
    settlement: dict[str, float],
    probability_discount: float,
    min_edge: float,
    min_ev: float,
    action: str,
) -> dict[str, Any]:
    calibration = settlement.get("calibration") if isinstance(settlement.get("calibration"), dict) else None
    return {
        "type": market_type,
        "probabilitySource": "score_matrix_pbase",
        "modelProbabilityLabel": "正收益概率",
        "evProbabilityBasis": "asian_settlement_weight",
        "formula": formula_label,
        "modelProbability": model_prob,
        "marketProbability": market_prob,
        "impliedProbability": implied_probability,
        "edge": edge,
        "odds": odd,
        "line": line,
        "positiveReturnProbability": settlement["positive"],
        "rawPositiveReturnProbability": settlement.get("raw_positive"),
        "winStakeFraction": settlement["win_fraction"],
        "rawWinStakeFraction": settlement.get("raw_win_fraction"),
        "lossStakeFraction": settlement["loss_fraction"],
        "rawLossStakeFraction": settlement.get("raw_loss_fraction"),
        "breakEvenOdds": settlement.get("break_even_odds"),
        "expectedValue": ev,
        "rawExpectedValue": settlement.get("raw_ev"),
        "researchExpectedValue": ev,
        "paperExpectedValue": paper_ev,
        "conservativeExpectedValue": paper_ev,
        "qmktAnchorExpectedValue": qmkt_anchor_ev,
        "shrinkK": shrink_k,
        "adjustedProbability": adjusted_probability,
        "probabilityDiscount": clamp(probability_discount, 0.0, 0.5),
        "paperFormula": "paper_EV = qmkt_anchor_EV + k × (research_EV - qmkt_anchor_EV)",
        "conservativeFormula": "已废弃旧公式：EV - probability_discount × odds",
        "settlement": {
            "positiveReturnProbability": settlement["positive"],
            "rawPositiveReturnProbability": settlement.get("raw_positive"),
            "fullWinProbability": settlement["full_win"],
            "rawFullWinProbability": settlement.get("raw_full_win"),
            "halfWinProbability": settlement["half_win"],
            "rawHalfWinProbability": settlement.get("raw_half_win"),
            "pushProbability": settlement["push"],
            "rawPushProbability": settlement.get("raw_push"),
            "halfLossProbability": settlement["half_loss"],
            "rawHalfLossProbability": settlement.get("raw_half_loss"),
            "fullLossProbability": settlement["full_loss"],
            "rawFullLossProbability": settlement.get("raw_full_loss"),
        },
        "scoreDistributionCalibration": calibration,
        "totalGoalsCalibration": calibration if market_type == "OU" else None,
        "gates": _gate_audit(
            ev,
            edge,
            paper_ev,
            model_prob,
            min_edge,
            min_ev,
            0.0,
        ),
        "candidateAction": action,
    }


def _gate_audit(
    ev: float,
    edge: float,
    paper_ev: float,
    model_probability: float,
    min_edge: float,
    min_ev: float,
    min_model_probability: float,
    *,
    odds: float | None = None,
    max_odds: float | None = None,
) -> list[dict[str, Any]]:
    gates = [
        {
            "key": "model_probability",
            "label": "模型概率下限",
            "value": model_probability,
            "threshold": min_model_probability,
            "passed": model_probability >= min_model_probability,
            "comparison": ">=",
            "enabled": min_model_probability > 0,
        },
        {
            "key": "max_odds",
            "label": "高赔率复核上限",
            "value": odds,
            "threshold": max_odds,
            "passed": odds is not None and max_odds is not None and odds <= max_odds,
            "comparison": "<=",
            "enabled": max_odds is not None,
        },
        {
            "key": "model_market_gap",
            "label": "模型与市场分歧上限",
            "value": abs(edge),
            "threshold": DEFAULT_MAX_PROBABILITY_GAP,
            "passed": abs(edge) <= DEFAULT_MAX_PROBABILITY_GAP,
            "comparison": "<=",
            "enabled": True,
        },
        {
            "key": "edge",
            "label": "模型优势",
            "value": edge,
            "threshold": min_edge,
            "passed": edge >= min_edge,
            "comparison": ">=",
            "enabled": True,
        },
        {
            "key": "ev",
            "label": "基础研究EV",
            "value": ev,
            "threshold": min_ev,
            "passed": ev >= min_ev,
            "comparison": ">=",
            "enabled": True,
        },
        {
            "key": "paper_ev",
            "label": "纸上EV",
            "value": paper_ev,
            "threshold": DEFAULT_MIN_CONSERVATIVE_EV,
            "passed": paper_ev >= DEFAULT_MIN_CONSERVATIVE_EV,
            "comparison": ">=",
            "enabled": True,
        },
    ]
    return [gate for gate in gates if gate["enabled"]]


def _apply_match_exposure_cap(
    recommendations: list[BetRecommendation],
    max_match_exposure: float,
) -> list[BetRecommendation]:
    active = [item for item in recommendations if item.action in {"BUY", "PAPER_BUY"} and item.stake > 0]
    total_stake = sum(item.stake for item in active)
    if not active or max_match_exposure <= 0 or total_stake <= max_match_exposure:
        return recommendations

    capped_stake = max_match_exposure / len(active)
    adjusted: list[BetRecommendation] = []
    for item in recommendations:
        if item.action not in {"BUY", "PAPER_BUY"} or item.stake <= 0:
            adjusted.append(item)
            continue
        adjusted.append(
            replace(
                item,
                stake=capped_stake,
                reason=(
                    f"{item.reason} 单场多市场总占用超过资金上限，已将本方向注额调整为 "
                    f"{capped_stake:.2f}。"
                ),
            )
        )
    return adjusted


def _apply_paper_stake_sizing(
    recommendations: list[BetRecommendation],
    bankroll_plan,
) -> list[BetRecommendation]:
    adjusted: list[BetRecommendation] = []
    for item in recommendations:
        if item.action not in {"BUY", "PAPER_BUY"} or item.stake <= 0:
            adjusted.append(item)
            continue
        ev = _execution_ev_per_unit(item)
        multiplier = _paper_stake_multiplier(ev)
        if multiplier <= 0:
            adjusted.append(replace(item, stake=0.0))
            continue
        cap = bankroll_plan.max_market_exposure
        if item.odds is not None and item.odds >= 3.0:
            cap = min(cap, bankroll_plan.max_longshot_exposure)
        sized_stake = max(0.0, min(item.stake * multiplier, cap, bankroll_plan.cash))
        sized_stake = round(sized_stake, 2)
        if abs(sized_stake - item.stake) < 0.005:
            adjusted.append(item)
            continue
        adjusted.append(
            replace(
                item,
                stake=sized_stake,
                reason=(
                    f"{item.reason} 动态纸上资金策略：按 paper_EV 分档与未结算预留资金调整，"
                    f"本方向注额 {sized_stake:.2f}。"
                ),
            )
        )
    return adjusted


def _paper_stake_multiplier(ev: float | None) -> float:
    if ev is None or ev < DEFAULT_MIN_CONSERVATIVE_EV:
        return 0.0
    if ev < 0.05:
        return 0.50
    if ev < 0.08:
        return 0.75
    if ev < 0.12:
        return 1.00
    return 1.15


def _handicap_label(side: str, home_line: float, home_team: str, away_team: str) -> str:
    if side == "home":
        return f"{home_team} {home_line:+g}"
    return f"{away_team} {-home_line:+g}"


def _missing_market(market: str, stake: float, reason: str) -> BetRecommendation:
    return BetRecommendation(
        market,
        "无可用方向",
        None,
        None,
        0.0,
        None,
        None,
        None,
        stake,
        "NO_MARKET",
        reason,
        signal_status=SIGNAL_STATUS_NO_MARKET,
        probability_used="none",
    )


def _invalid_market(market: str, line: float, stake: float, reason: str) -> BetRecommendation:
    return BetRecommendation(
        market,
        f"盘口 {line:g} 无效",
        line,
        None,
        0.0,
        None,
        None,
        None,
        stake,
        "NO_MARKET",
        reason,
        signal_status=SIGNAL_STATUS_NO_MARKET,
        probability_used="none",
        risk_flags=["invalid_market"],
    )


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"
