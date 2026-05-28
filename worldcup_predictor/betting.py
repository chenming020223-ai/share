from __future__ import annotations

import math
from dataclasses import dataclass, replace

from .models import PredictionResult, clamp
from .odds import devig_three_way, devig_two_way, is_reasonable_two_way_market, two_way_implied_sum

DEFAULT_MIN_EDGE = 0.08
DEFAULT_MIN_EV = 0.05
DEFAULT_PROBABILITY_DISCOUNT = 0.05
DEFAULT_MIN_CONSERVATIVE_EV = 0.03
DEFAULT_MAX_PROBABILITY_GAP = 0.15
DEFAULT_MIN_1X2_MODEL_PROBABILITY = 0.40
EV_STATUS_RESEARCH_ONLY = "RESEARCH_ONLY"
EV_STATUS_SUSPENDED_MODEL_DIVERGENCE = "SUSPENDED_MODEL_DIVERGENCE"


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
    implied_probability: float | None = None
    ev_status: str = EV_STATUS_RESEARCH_ONLY
    audit_expected_value_per_unit: float | None = None
    audit_conservative_expected_value_per_unit: float | None = None


@dataclass(frozen=True)
class PaperPortfolio:
    bankroll: float
    unit_stake: float
    active_bets: int
    total_stake: float
    bankroll_after_stakes: float
    expected_profit: float
    expected_bankroll: float


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
) -> tuple[list[BetRecommendation], PaperPortfolio]:
    stake = unit_stake if unit_stake is not None else bankroll * 0.01
    stake = max(0.0, min(stake, bankroll))

    recommendations = [
        _recommend_match_winner(
            result,
            market_snapshot.match_winner,
            stake,
            min_edge,
            min_ev,
            probability_discount,
            force_picks,
        ),
        _recommend_total_goals(score_probs, market_snapshot, stake, min_edge, min_ev, probability_discount, force_picks),
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
        ),
    ]
    recommendations = [
        item if item.action in {"BUY", "PAPER_BUY"} else replace(item, stake=0.0)
        for item in recommendations
    ]
    distribution_audit = build_distribution_audit(result, market_snapshot)
    if distribution_audit["evSuspended"]:
        recommendations = [
            _suspend_ev_for_model_divergence(item, str(distribution_audit["reason"]))
            for item in recommendations
        ]

    active = [item for item in recommendations if item.action in {"BUY", "PAPER_BUY"}]
    total_stake = stake * len(active)
    expected_profit = sum(
        stake * (item.expected_value_per_unit or 0.0)
        for item in active
        if item.expected_value_per_unit is not None
    )
    portfolio = PaperPortfolio(
        bankroll=bankroll,
        unit_stake=stake,
        active_bets=len(active),
        total_stake=total_stake,
        bankroll_after_stakes=bankroll - total_stake,
        expected_profit=expected_profit,
        expected_bankroll=bankroll + expected_profit,
    )
    return recommendations, portfolio


def build_distribution_audit(result: PredictionResult, market_snapshot) -> dict[str, object]:
    if str(market_snapshot.required_bookmaker or "").casefold() != "pinnacle":
        return {
            "status": "NOT_APPLICABLE",
            "statusLabel": "不适用",
            "evSuspended": False,
        }
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
    suspended = max_gap > DEFAULT_MAX_PROBABILITY_GAP
    reason = (
        f"模型分歧异常：{labels[trigger_key]} 的 pbase 与 Pinnacle 去水概率相差 "
        f"{max_gap * 100:.1f} 个百分点，超过 {DEFAULT_MAX_PROBABILITY_GAP * 100:.1f} 个百分点；"
        "本场所有市场 EV 暂停计算，仅供模型复核。"
        if suspended
        else (
            f"最大 pbase / Pinnacle 去水概率差异为 {max_gap * 100:.1f} 个百分点，"
            "未触发整场模型分歧暂停。"
        )
    )
    return {
        "status": "ANOMALY" if suspended else "PASS",
        "statusLabel": "模型分歧异常" if suspended else "分歧检查通过",
        "evSuspended": suspended,
        "triggerSelection": labels[trigger_key],
        "maxProbabilityGap": max_gap,
        "threshold": DEFAULT_MAX_PROBABILITY_GAP,
        "reason": reason,
        "gaps": gaps,
    }


def _suspend_ev_for_model_divergence(item: BetRecommendation, reason: str) -> BetRecommendation:
    if item.expected_value_per_unit is None:
        return item
    return replace(
        item,
        action="WATCH",
        stake=0.0,
        reason=reason,
        ev_status=EV_STATUS_SUSPENDED_MODEL_DIVERGENCE,
        audit_expected_value_per_unit=item.expected_value_per_unit,
        audit_conservative_expected_value_per_unit=item.conservative_expected_value_per_unit,
        expected_value_per_unit=None,
        conservative_expected_value_per_unit=None,
    )


def _recommend_match_winner(
    result: PredictionResult,
    odds: dict[str, float],
    stake: float,
    min_edge: float,
    min_ev: float,
    probability_discount: float,
    force_picks: bool,
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
        conservative_ev = _conservative_ev(ev, odd, probability_discount)
        implied_probability = 1.0 / odd
        candidates.append((ev, model_prob - market_prob, key, odd, model_prob, market_prob, conservative_ev, implied_probability))

    ev, edge, key, odd, model_prob, market_prob, conservative_ev, implied_probability = max(candidates, key=lambda item: item[0])
    action, reason = _signal_action(
        ev,
        edge,
        conservative_ev,
        model_prob,
        min_edge,
        min_ev,
        force_picks,
        min_model_probability=DEFAULT_MIN_1X2_MODEL_PROBABILITY,
    )
    return BetRecommendation(
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
        conservative_ev,
        implied_probability,
    )


def _recommend_total_goals(
    score_probs: dict[tuple[int, int], float],
    market_snapshot,
    stake: float,
    min_edge: float,
    min_ev: float,
    probability_discount: float,
    force_picks: bool,
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
        model_prob = asian_total_positive_return_probability(score_probs, line, side)
        ev = asian_total_expected_value(score_probs, line, side, odds[side])
        edge = model_prob - market_probs[side]
        conservative_ev = _conservative_ev(ev, odds[side], probability_discount)
        implied_probability = 1.0 / odds[side]
        candidates.append((ev, edge, side, odds[side], model_prob, market_probs[side], conservative_ev, implied_probability))

    ev, edge, side, odd, model_prob, market_prob, conservative_ev, implied_probability = max(candidates, key=lambda item: item[0])
    label = f"{'大' if side == 'over' else '小'} {line:g}"
    action, reason = _signal_action(ev, edge, conservative_ev, model_prob, min_edge, min_ev, force_picks)
    return BetRecommendation(
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
        conservative_ev,
        implied_probability,
    )


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
        model_prob = asian_handicap_positive_return_probability(score_probs, home_line, side)
        ev = asian_handicap_expected_value(score_probs, home_line, side, odds[side])
        edge = model_prob - market_probs[side]
        conservative_ev = _conservative_ev(ev, odds[side], probability_discount)
        implied_probability = 1.0 / odds[side]
        candidates.append((ev, edge, side, odds[side], model_prob, market_probs[side], conservative_ev, implied_probability))

    ev, edge, side, odd, model_prob, market_prob, conservative_ev, implied_probability = max(candidates, key=lambda item: item[0])
    label = _handicap_label(side, home_line, home_team, away_team)
    action, reason = _signal_action(ev, edge, conservative_ev, model_prob, min_edge, min_ev, force_picks)
    return BetRecommendation(
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
        conservative_ev,
        implied_probability,
    )


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
    for (home_goals, away_goals), probability in score_probs.items():
        goals = home_goals + away_goals
        net = 0.0
        for split_line in lines:
            diff = goals - split_line if side == "over" else split_line - goals
            net += _settlement_net(diff, odd)
        net /= len(lines)
        if net > 0:
            positive += probability
        ev += probability * net
    return {"positive": positive, "ev": ev}


def _asian_handicap_settlement(
    score_probs: dict[tuple[int, int], float],
    home_line: float,
    side: str,
    odd: float = 2.0,
) -> dict[str, float]:
    home_lines = _split_asian_line(home_line)
    positive = 0.0
    ev = 0.0
    for (home_goals, away_goals), probability in score_probs.items():
        net = 0.0
        for split_line in home_lines:
            diff = home_goals + split_line - away_goals
            if side == "away":
                diff = -diff
            net += _settlement_net(diff, odd)
        net /= len(home_lines)
        if net > 0:
            positive += probability
        ev += probability * net
    return {"positive": positive, "ev": ev}


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


def _passes_signal_gate(ev: float, edge: float, conservative_ev: float, min_edge: float, min_ev: float) -> bool:
    return ev >= min_ev and edge >= min_edge and conservative_ev >= DEFAULT_MIN_CONSERVATIVE_EV


def _buy_reason(min_edge: float, min_ev: float) -> str:
    return (
        "通过研究试算 EV 门槛：EV 为正，模型优势达到 "
        f"{min_edge * 100:.1f}%，基础 EV 达到 {min_ev * 100:.1f}%，"
        f"保守 EV 达到 {DEFAULT_MIN_CONSERVATIVE_EV * 100:.1f}%。"
    )


def _watch_reason(min_edge: float, min_ev: float, conservative_ev: float | None) -> str:
    conservative_text = "-" if conservative_ev is None else f"{conservative_ev * 100:.1f}%"
    return (
        "未通过研究试算 EV 门槛，观望。需要同时满足："
        f"基础 EV≥{min_ev * 100:.1f}%、模型优势≥{min_edge * 100:.1f}%、"
        f"保守 EV≥{DEFAULT_MIN_CONSERVATIVE_EV * 100:.1f}%；当前保守 EV {conservative_text}。"
    )


def _signal_action(
    ev: float,
    edge: float,
    conservative_ev: float,
    model_probability: float,
    min_edge: float,
    min_ev: float,
    force_picks: bool,
    min_model_probability: float = 0.0,
) -> tuple[str, str]:
    if model_probability < min_model_probability:
        return (
            "WATCH",
            f"pbase 基础概率 {model_probability * 100:.1f}% 低于胜平负研究方向下限 "
            f"{min_model_probability * 100:.1f}%，不将高赔率直接视为机会。",
        )
    if abs(edge) > DEFAULT_MAX_PROBABILITY_GAP:
        return (
            "WATCH",
            f"pbase 与指定庄家去水概率 qmkt 的差值 {abs(edge) * 100:.1f}% 超过 "
            f"{DEFAULT_MAX_PROBABILITY_GAP * 100:.1f}% 复核上限，不形成研究方向。",
        )
    if _passes_signal_gate(ev, edge, conservative_ev, min_edge, min_ev):
        return "BUY", _buy_reason(min_edge, min_ev)
    if force_picks:
        return "PAPER_BUY", "强制均注演示：当前未达到保守信号门槛。"
    return "WATCH", _watch_reason(min_edge, min_ev, conservative_ev)


def _handicap_label(side: str, home_line: float, home_team: str, away_team: str) -> str:
    if side == "home":
        return f"{home_team} {home_line:+g}"
    return f"{away_team} {-home_line:+g}"


def _missing_market(market: str, stake: float, reason: str) -> BetRecommendation:
    return BetRecommendation(market, "无可用方向", None, None, 0.0, None, None, None, stake, "NO_MARKET", reason)


def _invalid_market(market: str, line: float, stake: float, reason: str) -> BetRecommendation:
    return BetRecommendation(market, f"盘口 {line:g} 无效", line, None, 0.0, None, None, None, stake, "NO_MARKET", reason)


def _pct(value: float | None) -> str:
    if value is None:
        return "-"
    return f"{value * 100:.1f}%"
