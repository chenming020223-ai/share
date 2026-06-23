from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .models import clamp
from .poisson import score_matrix
from .storage import calibration_source_rows

SCORE_DISTRIBUTION_CALIBRATION_VERSION = "score_distribution_market_factor_v1"
SCORE_MATRIX_MAX_GOALS = 10
MARKET_SIDES = {
    "OU": ("over", "under"),
    "AH": ("home", "away"),
}
MARKET_LABELS = {
    "OU": "大小球",
    "AH": "让球",
}
SIDE_LABELS = {
    "over": "大球",
    "under": "小球",
    "home": "主队让球侧",
    "away": "客队受让侧",
}


@dataclass(frozen=True)
class ScoreDistributionCalibrationPolicy:
    min_market_samples: int = 40
    min_calibration_samples: int = 20
    min_validation_samples: int = 10
    min_side_samples: int = 8
    min_factor: float = 0.70
    max_factor: float = 1.30
    max_brier_worsening: float = 0.01
    max_ev_mae_worsening: float = 0.02


@dataclass(frozen=True)
class ScoreMarketObservation:
    fixture_id: str
    snapshot_id: int
    prediction_created_at: str
    kickoff_at: str
    market: str
    side: str
    line: float
    odds: float
    model_positive_probability: float
    model_win_fraction: float
    model_loss_fraction: float
    model_expected_value: float
    market_probability: float | None
    actual_positive: float
    actual_win_fraction: float
    actual_loss_fraction: float
    actual_net: float


def build_score_distribution_calibration_status(
    db_path: str | None = None,
    policy: ScoreDistributionCalibrationPolicy | None = None,
) -> dict[str, Any]:
    applied_policy = policy or ScoreDistributionCalibrationPolicy()
    observations, excluded = _eligible_score_market_observations(
        calibration_source_rows(db_path=db_path),
        applied_policy,
    )
    markets = {
        market: _market_calibration_status(market, observations, applied_policy)
        for market in ("OU", "AH")
    }
    ready_markets = [key for key, item in markets.items() if item["paperEvEnabled"]]
    if len(ready_markets) == len(markets):
        status = "PAPER_READY"
        label = "比分分布纸上EV校准通过"
    elif ready_markets:
        status = "PARTIAL_READY"
        label = "比分分布部分市场通过"
    else:
        status = "NOT_READY"
        label = "比分分布纸上EV未通过"

    return {
        "version": SCORE_DISTRIBUTION_CALIBRATION_VERSION,
        "status": status,
        "statusLabel": label,
        "enabled": True,
        "paperEvEnabled": bool(ready_markets),
        "formalApproved": False,
        "formalEvEnabled": False,
        "policy": asdict(applied_policy),
        "sampleCount": len(observations),
        "distinctFixtures": len({item.fixture_id for item in observations}),
        "markets": markets,
        "excluded": excluded,
        "notes": [
            "该校准只决定大小球/让球 paper_EV 是否可作为纸上复核候选，不开放 formal_EV。",
            "样本按开赛时间切分；校准集拟合因子，验证集只评估，不反向调参。",
            "同一场、同一市场、同一盘口、同一方向只保留最早赛前快照，避免重复扩大样本。",
        ],
    }


def apply_score_market_settlement_calibration(
    settlement: dict[str, float],
    odd: float,
    market: str,
    side: str,
    calibration_status: dict[str, Any] | None,
) -> dict[str, float | dict[str, Any]]:
    market_key = _market_key(market)
    side_key = _normalized_side(side)
    market_status = (((calibration_status or {}).get("markets") or {}).get(market_key) or {})
    side_calibration = ((market_status.get("sides") or {}).get(side_key) or {})
    if not side_calibration or not market_status.get("paperEvEnabled"):
        return dict(settlement)

    positive_factor = _safe_number(side_calibration.get("positiveFactor"), 1.0)
    win_factor = _safe_number(side_calibration.get("winFactor"), 1.0)
    loss_factor = _safe_number(side_calibration.get("lossFactor"), 1.0)
    raw_positive = _safe_number(settlement.get("positive"), 0.0)
    raw_ev = _safe_number(settlement.get("ev"), 0.0)
    raw_win = _safe_number(settlement.get("win_fraction"), 0.0)
    raw_loss = _safe_number(settlement.get("loss_fraction"), 0.0)

    calibrated_positive = clamp(raw_positive * positive_factor, 0.0, 1.0)
    calibrated_win = clamp(raw_win * win_factor, 0.0, 1.0)
    calibrated_loss = clamp(raw_loss * loss_factor, 0.0, 1.0)
    active = calibrated_win + calibrated_loss
    if active > 1.0:
        calibrated_win /= active
        calibrated_loss /= active
    calibrated_ev = calibrated_win * (odd - 1.0) - calibrated_loss

    raw_full_win = _safe_number(settlement.get("full_win"), 0.0)
    raw_half_win = _safe_number(settlement.get("half_win"), 0.0)
    raw_push = _safe_number(settlement.get("push"), 0.0)
    raw_half_loss = _safe_number(settlement.get("half_loss"), 0.0)
    raw_full_loss = _safe_number(settlement.get("full_loss"), 0.0)
    bucket_win_fraction = raw_full_win + 0.5 * raw_half_win
    bucket_loss_fraction = raw_full_loss + 0.5 * raw_half_loss
    win_bucket_scale = calibrated_win / bucket_win_fraction if bucket_win_fraction > 1e-12 else 1.0
    loss_bucket_scale = calibrated_loss / bucket_loss_fraction if bucket_loss_fraction > 1e-12 else 1.0
    calibrated_full_win = clamp(raw_full_win * win_bucket_scale, 0.0, 1.0)
    calibrated_half_win = clamp(raw_half_win * win_bucket_scale, 0.0, 1.0)
    calibrated_half_loss = clamp(raw_half_loss * loss_bucket_scale, 0.0, 1.0)
    calibrated_full_loss = clamp(raw_full_loss * loss_bucket_scale, 0.0, 1.0)
    calibrated_push = clamp(
        1.0 - calibrated_full_win - calibrated_half_win - calibrated_half_loss - calibrated_full_loss,
        0.0,
        1.0,
    )

    updated: dict[str, float | dict[str, Any]] = dict(settlement)
    updated.update(
        {
            "raw_positive": raw_positive,
            "raw_ev": raw_ev,
            "raw_win_fraction": raw_win,
            "raw_loss_fraction": raw_loss,
            "raw_full_win": raw_full_win,
            "raw_half_win": raw_half_win,
            "raw_push": raw_push,
            "raw_half_loss": raw_half_loss,
            "raw_full_loss": raw_full_loss,
            "positive": calibrated_positive,
            "ev": calibrated_ev,
            "win_fraction": calibrated_win,
            "loss_fraction": calibrated_loss,
            "full_win": calibrated_full_win,
            "half_win": calibrated_half_win,
            "push": calibrated_push,
            "half_loss": calibrated_half_loss,
            "full_loss": calibrated_full_loss,
            "break_even_odds": _break_even_odds(calibrated_win, calibrated_loss),
            "calibration": {
                "applied": True,
                "version": (calibration_status or {}).get("version") or SCORE_DISTRIBUTION_CALIBRATION_VERSION,
                "status": market_status.get("status"),
                "statusLabel": market_status.get("statusLabel"),
                "paperApproved": bool(market_status.get("paperEvEnabled")),
                "formalApproved": False,
                "market": market_key,
                "marketLabel": MARKET_LABELS.get(market_key, market_key),
                "side": side_key,
                "sideLabel": side_calibration.get("sideLabel") or SIDE_LABELS.get(side_key, side_key),
                "positiveFactor": positive_factor,
                "winFactor": win_factor,
                "lossFactor": loss_factor,
                "credibility": side_calibration.get("credibility"),
                "sampleCount": side_calibration.get("sampleCount"),
                "actualPositiveRate": side_calibration.get("actualPositiveRate"),
                "meanModelPositiveProbability": side_calibration.get("meanModelPositiveProbability"),
                "modelBias": side_calibration.get("modelBias"),
                "rawExpectedValue": raw_ev,
                "calibratedExpectedValue": calibrated_ev,
                "rawPositiveReturnProbability": raw_positive,
                "calibratedPositiveReturnProbability": calibrated_positive,
                "note": (
                    "比分分布独立校准已通过，可输出 paper_EV 候选；formal_EV 仍需 pfinal 审批。"
                    if market_status.get("paperEvEnabled")
                    else "比分分布独立校准未通过或样本不足，仅用于 research_EV 审计。"
                ),
            },
        }
    )
    return updated


def market_paper_ev_enabled(calibration_status: dict[str, Any] | None, market: str) -> bool:
    market_key = _market_key(market)
    market_status = (((calibration_status or {}).get("markets") or {}).get(market_key) or {})
    return bool(market_status.get("paperEvEnabled"))


def market_status_label(calibration_status: dict[str, Any] | None, market: str) -> str:
    market_key = _market_key(market)
    market_status = (((calibration_status or {}).get("markets") or {}).get(market_key) or {})
    return str(market_status.get("statusLabel") or "比分分布校准未完成")


def _eligible_score_market_observations(
    rows: list[dict[str, Any]],
    policy: ScoreDistributionCalibrationPolicy,
) -> tuple[list[ScoreMarketObservation], dict[str, int]]:
    excluded = {
        "missing_snapshot_or_recommendation": 0,
        "missing_time_or_bookmaker": 0,
        "post_kickoff_or_future_odds": 0,
        "missing_score_market_fields": 0,
        "duplicate_fixture_market_line_side": 0,
    }
    selected: dict[tuple[str, str, float, str], ScoreMarketObservation] = {}
    for row in rows:
        snapshot_id = row.get("snapshot_id")
        payload = row.get("payload") or {}
        recommendations = [
            item for item in payload.get("recommendations") or []
            if isinstance(item, dict) and str(item.get("market") or "") in {"大小球", "让球"}
        ]
        if not snapshot_id or not recommendations:
            excluded["missing_snapshot_or_recommendation"] += 1
            continue

        prediction_time = _parse_time(row.get("prediction_created_at"))
        captured_time = _parse_time(row.get("odds_captured_at"))
        kickoff_time = _parse_time(row.get("kickoff_at"))
        bookmaker = str(row.get("selected_bookmaker") or "").strip()
        if not prediction_time or not captured_time or not kickoff_time or not bookmaker:
            excluded["missing_time_or_bookmaker"] += len(recommendations)
            continue
        if prediction_time >= kickoff_time or captured_time >= kickoff_time or captured_time > prediction_time:
            excluded["post_kickoff_or_future_odds"] += len(recommendations)
            continue

        for recommendation in recommendations:
            observation = _observation_from_recommendation(row, recommendation, int(snapshot_id))
            if observation is None:
                excluded["missing_score_market_fields"] += 1
                continue

            key = (
                observation.fixture_id,
                observation.market,
                round(observation.line, 2),
                observation.side,
            )
            existing = selected.get(key)
            if existing is not None:
                excluded["duplicate_fixture_market_line_side"] += 1
                if _parse_time(existing.prediction_created_at) <= prediction_time:
                    continue
            selected[key] = observation

    observations = sorted(
        selected.values(),
        key=lambda item: (_parse_time(item.kickoff_at) or datetime.max.replace(tzinfo=timezone.utc), item.fixture_id),
    )
    return observations, excluded


def _observation_from_recommendation(
    row: dict[str, Any],
    recommendation: dict[str, Any],
    snapshot_id: int,
) -> ScoreMarketObservation | None:
    fixture_id = str(row.get("fixture_id") or "")
    market = _market_key(str(recommendation.get("market") or ""))
    side = _selection_side(row.get("payload") or {}, market, str(recommendation.get("selection") or ""))
    line = _safe_number(recommendation.get("line"), math.nan)
    odds = _safe_number(recommendation.get("odds"), math.nan)
    if (
        not fixture_id
        or market not in MARKET_SIDES
        or side not in MARKET_SIDES[market]
        or not math.isfinite(line)
        or not math.isfinite(odds)
        or odds <= 1
    ):
        return None

    settlement = _model_settlement(row.get("payload") or {}, recommendation, market, side, line, odds)
    if settlement is None:
        return None
    actual = _actual_settlement(
        int(row["home_goals_90"]),
        int(row["away_goals_90"]),
        market,
        side,
        line,
        odds,
    )
    return ScoreMarketObservation(
        fixture_id=fixture_id,
        snapshot_id=snapshot_id,
        prediction_created_at=str(row.get("prediction_created_at") or ""),
        kickoff_at=str(row.get("kickoff_at") or ""),
        market=market,
        side=side,
        line=line,
        odds=odds,
        model_positive_probability=clamp(settlement["positive"], 0.0, 1.0),
        model_win_fraction=clamp(settlement["win_fraction"], 0.0, 1.0),
        model_loss_fraction=clamp(settlement["loss_fraction"], 0.0, 1.0),
        model_expected_value=settlement["ev"],
        market_probability=_first_number(recommendation.get("market_probability")),
        actual_positive=1.0 if actual["net"] > 0 else 0.0,
        actual_win_fraction=actual["win_fraction"],
        actual_loss_fraction=actual["loss_fraction"],
        actual_net=actual["net"],
    )


def _model_settlement(
    payload: dict[str, Any],
    recommendation: dict[str, Any],
    market: str,
    side: str,
    line: float,
    odds: float,
) -> dict[str, float] | None:
    calc = recommendation.get("ev_calculation") or {}
    model_positive = _first_number(
        calc.get("rawPositiveReturnProbability"),
        calc.get("positiveReturnProbability"),
        recommendation.get("model_probability"),
    )
    model_win = _first_number(calc.get("rawWinStakeFraction"), calc.get("winStakeFraction"))
    model_loss = _first_number(calc.get("rawLossStakeFraction"), calc.get("lossStakeFraction"))
    model_ev = _first_number(
        calc.get("rawExpectedValue"),
        calc.get("expectedValue"),
        recommendation.get("ev_pbase_research"),
        recommendation.get("expected_value_per_unit"),
        recommendation.get("audit_expected_value_per_unit"),
    )
    if model_positive is not None and model_win is not None and model_loss is not None and model_ev is not None:
        return {
            "positive": model_positive,
            "win_fraction": model_win,
            "loss_fraction": model_loss,
            "ev": model_ev,
        }

    expected = payload.get("expectedGoals") or {}
    home_mu = _first_number(expected.get("home"))
    away_mu = _first_number(expected.get("away"))
    if home_mu is None or away_mu is None:
        return None
    matrix = score_matrix(home_mu, away_mu, SCORE_MATRIX_MAX_GOALS)
    if market == "OU":
        return _asian_total_settlement(matrix, line, side, odds)
    return _asian_handicap_settlement(matrix, line, side, odds)


def _market_calibration_status(
    market: str,
    observations: list[ScoreMarketObservation],
    policy: ScoreDistributionCalibrationPolicy,
) -> dict[str, Any]:
    market_rows = [item for item in observations if item.market == market]
    calibration, validation = _chronological_split(market_rows)
    sides = {
        side: _side_calibration_status(side, calibration, policy)
        for side in MARKET_SIDES[market]
    }
    validation_metrics = _validation_metrics(validation, sides)
    enough_samples = (
        len(market_rows) >= policy.min_market_samples
        and len(calibration) >= policy.min_calibration_samples
        and len(validation) >= policy.min_validation_samples
        and all(sides[side]["sampleCount"] >= policy.min_side_samples for side in MARKET_SIDES[market])
    )
    validation_passed = (
        validation_metrics["sampleCount"] >= policy.min_validation_samples
        and validation_metrics["calibratedPositiveBrier"]
        <= validation_metrics["rawPositiveBrier"] + policy.max_brier_worsening
        and validation_metrics["calibratedEvMae"]
        <= validation_metrics["rawEvMae"] + policy.max_ev_mae_worsening
    )
    if not enough_samples:
        status = "INSUFFICIENT_DATA"
        label = f"{MARKET_LABELS[market]}样本不足"
    elif validation_passed:
        status = "PAPER_READY"
        label = f"{MARKET_LABELS[market]}独立校准通过"
    else:
        status = "REJECTED"
        label = f"{MARKET_LABELS[market]}独立校准未通过"

    return {
        "market": market,
        "marketLabel": MARKET_LABELS[market],
        "status": status,
        "statusLabel": label,
        "paperEvEnabled": status == "PAPER_READY",
        "formalEvEnabled": False,
        "sampleCount": len(market_rows),
        "distinctFixtures": len({item.fixture_id for item in market_rows}),
        "split": {
            "calibration": len(calibration),
            "validation": len(validation),
        },
        "sides": sides,
        "validation": validation_metrics,
        "checks": [
            _check("市场样本", len(market_rows), policy.min_market_samples),
            _check("校准样本", len(calibration), policy.min_calibration_samples),
            _check("验证样本", len(validation), policy.min_validation_samples),
            {
                "label": "校准后正收益Brier不劣化",
                "passed": (
                    validation_metrics["calibratedPositiveBrier"]
                    <= validation_metrics["rawPositiveBrier"] + policy.max_brier_worsening
                ),
                "detail": (
                    f"{validation_metrics['calibratedPositiveBrier']:.4f} <= "
                    f"{validation_metrics['rawPositiveBrier'] + policy.max_brier_worsening:.4f}"
                ),
            },
            {
                "label": "校准后EV误差不劣化",
                "passed": (
                    validation_metrics["calibratedEvMae"]
                    <= validation_metrics["rawEvMae"] + policy.max_ev_mae_worsening
                ),
                "detail": (
                    f"{validation_metrics['calibratedEvMae']:.4f} <= "
                    f"{validation_metrics['rawEvMae'] + policy.max_ev_mae_worsening:.4f}"
                ),
            },
        ],
    }


def _side_calibration_status(
    side: str,
    observations: list[ScoreMarketObservation],
    policy: ScoreDistributionCalibrationPolicy,
) -> dict[str, Any]:
    side_rows = [item for item in observations if item.side == side]
    count = len(side_rows)
    credibility = clamp(count / max(1, policy.min_side_samples), 0.0, 1.0)
    if not side_rows:
        return {
            "side": side,
            "sideLabel": SIDE_LABELS.get(side, side),
            "status": "LOW_SAMPLE",
            "sampleCount": 0,
            "credibility": 0.0,
            "positiveFactor": 1.0,
            "winFactor": 1.0,
            "lossFactor": 1.0,
        }
    mean_model_positive = _mean(item.model_positive_probability for item in side_rows)
    mean_model_win = _mean(item.model_win_fraction for item in side_rows)
    mean_model_loss = _mean(item.model_loss_fraction for item in side_rows)
    actual_positive_rate = _mean(item.actual_positive for item in side_rows)
    actual_win_rate = _mean(item.actual_win_fraction for item in side_rows)
    actual_loss_rate = _mean(item.actual_loss_fraction for item in side_rows)
    return {
        "side": side,
        "sideLabel": SIDE_LABELS.get(side, side),
        "status": "OK" if count >= policy.min_side_samples else "LOW_SAMPLE",
        "sampleCount": count,
        "credibility": credibility,
        "positiveFactor": _blended_factor(actual_positive_rate, mean_model_positive, credibility, policy),
        "winFactor": _blended_factor(actual_win_rate, mean_model_win, credibility, policy),
        "lossFactor": _blended_factor(actual_loss_rate, mean_model_loss, credibility, policy),
        "meanModelPositiveProbability": mean_model_positive,
        "actualPositiveRate": actual_positive_rate,
        "meanModelWinFraction": mean_model_win,
        "actualWinFractionRate": actual_win_rate,
        "meanModelLossFraction": mean_model_loss,
        "actualLossFractionRate": actual_loss_rate,
        "meanMarketProbability": _nullable_mean(item.market_probability for item in side_rows),
        "meanModelExpectedValue": _mean(item.model_expected_value for item in side_rows),
        "meanActualNet": _mean(item.actual_net for item in side_rows),
        "modelBias": mean_model_positive - actual_positive_rate,
        "winFractionBias": mean_model_win - actual_win_rate,
        "lossFractionBias": mean_model_loss - actual_loss_rate,
    }


def _validation_metrics(
    observations: list[ScoreMarketObservation],
    sides: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    rows = []
    for item in observations:
        calibrated = _calibrated_components(
            item.model_positive_probability,
            item.model_win_fraction,
            item.model_loss_fraction,
            item.odds,
            sides.get(item.side) or {},
        )
        rows.append((item, calibrated))
    if not rows:
        return {
            "sampleCount": 0,
            "rawPositiveBrier": 0.0,
            "calibratedPositiveBrier": 0.0,
            "rawEvMae": 0.0,
            "calibratedEvMae": 0.0,
            "meanRawExpectedValue": 0.0,
            "meanCalibratedExpectedValue": 0.0,
            "meanActualNet": 0.0,
        }
    return {
        "sampleCount": len(rows),
        "rawPositiveBrier": _mean((item.model_positive_probability - item.actual_positive) ** 2 for item, _ in rows),
        "calibratedPositiveBrier": _mean((calibrated["positive"] - item.actual_positive) ** 2 for item, calibrated in rows),
        "rawEvMae": _mean(abs(item.model_expected_value - item.actual_net) for item, _ in rows),
        "calibratedEvMae": _mean(abs(calibrated["ev"] - item.actual_net) for item, calibrated in rows),
        "meanRawExpectedValue": _mean(item.model_expected_value for item, _ in rows),
        "meanCalibratedExpectedValue": _mean(calibrated["ev"] for _, calibrated in rows),
        "meanActualNet": _mean(item.actual_net for item, _ in rows),
    }


def _calibrated_components(
    positive: float,
    win_fraction: float,
    loss_fraction: float,
    odd: float,
    side_status: dict[str, Any],
) -> dict[str, float]:
    calibrated_positive = clamp(positive * _safe_number(side_status.get("positiveFactor"), 1.0), 0.0, 1.0)
    calibrated_win = clamp(win_fraction * _safe_number(side_status.get("winFactor"), 1.0), 0.0, 1.0)
    calibrated_loss = clamp(loss_fraction * _safe_number(side_status.get("lossFactor"), 1.0), 0.0, 1.0)
    active = calibrated_win + calibrated_loss
    if active > 1.0:
        calibrated_win /= active
        calibrated_loss /= active
    return {
        "positive": calibrated_positive,
        "win_fraction": calibrated_win,
        "loss_fraction": calibrated_loss,
        "ev": calibrated_win * (odd - 1.0) - calibrated_loss,
    }


def _chronological_split(
    observations: list[ScoreMarketObservation],
) -> tuple[list[ScoreMarketObservation], list[ScoreMarketObservation]]:
    if len(observations) < 3:
        return observations, []
    calibration_end = max(1, int(len(observations) * 0.70))
    calibration_end = min(calibration_end, len(observations) - 1)
    return observations[:calibration_end], observations[calibration_end:]


def _actual_settlement(
    home_goals: int,
    away_goals: int,
    market: str,
    side: str,
    line: float,
    odds: float,
) -> dict[str, float]:
    if market == "OU":
        return _actual_total_settlement(home_goals + away_goals, line, side, odds)
    return _actual_handicap_settlement(home_goals, away_goals, line, side, odds)


def _actual_total_settlement(total_goals: int, line: float, side: str, odds: float) -> dict[str, float]:
    diffs = [
        (total_goals - split_line if side == "over" else split_line - total_goals)
        for split_line in _split_asian_line(line)
    ]
    net, win_fraction, loss_fraction = _split_settlement_net(diffs, odds)
    return {"net": net, "win_fraction": win_fraction, "loss_fraction": loss_fraction}


def _actual_handicap_settlement(
    home_goals: int,
    away_goals: int,
    home_line: float,
    side: str,
    odds: float,
) -> dict[str, float]:
    diffs = []
    for split_line in _split_asian_line(home_line):
        diff = home_goals + split_line - away_goals
        if side == "away":
            diff = -diff
        diffs.append(diff)
    net, win_fraction, loss_fraction = _split_settlement_net(diffs, odds)
    return {"net": net, "win_fraction": win_fraction, "loss_fraction": loss_fraction}


def _asian_total_settlement(
    score_probs: dict[tuple[int, int], float],
    line: float,
    side: str,
    odd: float,
) -> dict[str, float]:
    return _score_matrix_settlement(
        score_probs,
        [
            (lambda home, away, split_line=split_line: home + away - split_line)
            if side == "over"
            else (lambda home, away, split_line=split_line: split_line - home - away)
            for split_line in _split_asian_line(line)
        ],
        odd,
    )


def _asian_handicap_settlement(
    score_probs: dict[tuple[int, int], float],
    home_line: float,
    side: str,
    odd: float,
) -> dict[str, float]:
    line_fns = []
    for split_line in _split_asian_line(home_line):
        if side == "away":
            line_fns.append(lambda home, away, split_line=split_line: -(home + split_line - away))
        else:
            line_fns.append(lambda home, away, split_line=split_line: home + split_line - away)
    return _score_matrix_settlement(score_probs, line_fns, odd)


def _score_matrix_settlement(score_probs, line_fns, odd: float) -> dict[str, float]:
    positive = 0.0
    ev = 0.0
    win_fraction_total = 0.0
    loss_fraction_total = 0.0
    for (home_goals, away_goals), probability in score_probs.items():
        diffs = [line_fn(home_goals, away_goals) for line_fn in line_fns]
        net, win_fraction, loss_fraction = _split_settlement_net(diffs, odd)
        if net > 0:
            positive += probability
        win_fraction_total += probability * win_fraction
        loss_fraction_total += probability * loss_fraction
        ev += probability * net
    return {
        "positive": positive,
        "win_fraction": win_fraction_total,
        "loss_fraction": loss_fraction_total,
        "ev": ev,
    }


def _selection_side(payload: dict[str, Any], market: str, selection: str) -> str | None:
    text = selection.strip().casefold()
    if market == "OU":
        if selection.startswith("大") or text.startswith("over"):
            return "over"
        if selection.startswith("小") or text.startswith("under"):
            return "under"
        return None
    match = payload.get("match") or {}
    home_names = {
        str(match.get("home") or "").casefold(),
        str(match.get("homeZh") or "").casefold(),
    }
    away_names = {
        str(match.get("away") or "").casefold(),
        str(match.get("awayZh") or "").casefold(),
    }
    if any(name and text.startswith(name) for name in home_names):
        return "home"
    if any(name and text.startswith(name) for name in away_names):
        return "away"
    return None


def _market_key(value: str) -> str:
    if value in {"OU", "大小球"}:
        return "OU"
    if value in {"AH", "让球"}:
        return "AH"
    return value


def _normalized_side(value: str) -> str:
    text = str(value or "").strip().casefold()
    if text in {"over", "under", "home", "away"}:
        return text
    return str(value or "")


def _blended_factor(
    actual_rate: float,
    model_rate: float,
    credibility: float,
    policy: ScoreDistributionCalibrationPolicy,
) -> float:
    raw = actual_rate / model_rate if model_rate > 1e-9 else 1.0
    return clamp(1.0 + credibility * (raw - 1.0), policy.min_factor, policy.max_factor)


def _split_asian_line(line: float) -> list[float]:
    rounded = round(line * 4) / 4
    lower = math.floor(rounded * 2) / 2
    upper = math.ceil(rounded * 2) / 2
    if abs(lower - upper) < 1e-9:
        return [rounded]
    return [lower, upper]


def _split_settlement_net(diffs, odd: float) -> tuple[float, float, float]:
    diff_list = list(diffs)
    if not diff_list:
        return 0.0, 0.0, 0.0
    net = 0.0
    win_fraction = 0.0
    loss_fraction = 0.0
    for diff in diff_list:
        if diff > 1e-9:
            net += odd - 1.0
            win_fraction += 1.0
        elif diff < -1e-9:
            net -= 1.0
            loss_fraction += 1.0
    count = len(diff_list)
    return net / count, win_fraction / count, loss_fraction / count


def _break_even_odds(win_fraction: float, loss_fraction: float) -> float | None:
    if win_fraction <= 1e-12:
        return None
    return 1.0 + loss_fraction / win_fraction


def _check(label: str, actual: int, required: int) -> dict[str, Any]:
    return {
        "label": label,
        "passed": actual >= required,
        "detail": f"{actual} / {required}",
    }


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


def _safe_number(value: Any, default: float) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return default
    return result if math.isfinite(result) else default


def _first_number(*values: Any) -> float | None:
    for value in values:
        try:
            result = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(result):
            return result
    return None


def _mean(values) -> float:
    numbers = [float(item) for item in values]
    return sum(numbers) / len(numbers) if numbers else 0.0


def _nullable_mean(values) -> float | None:
    numbers = [float(item) for item in values if item is not None]
    return sum(numbers) / len(numbers) if numbers else None
