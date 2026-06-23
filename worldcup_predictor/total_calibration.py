from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any

from .models import clamp
from .storage import calibration_source_rows

TOTAL_GOALS_CALIBRATION_VERSION = "total_goals_side_factor_v1"


@dataclass(frozen=True)
class TotalGoalsCalibrationPolicy:
    min_total_samples: int = 40
    min_side_samples: int = 20
    min_factor: float = 0.70
    max_factor: float = 1.30


@dataclass(frozen=True)
class TotalGoalsObservation:
    fixture_id: str
    snapshot_id: int
    prediction_created_at: str
    kickoff_at: str
    side: str
    line: float
    odds: float
    model_positive_probability: float
    model_win_fraction: float
    model_loss_fraction: float
    market_probability: float | None
    expected_value: float | None
    actual_positive: float
    actual_win_fraction: float
    actual_loss_fraction: float
    actual_net: float


def build_total_goals_calibration_status(
    db_path: str | None = None,
    policy: TotalGoalsCalibrationPolicy | None = None,
) -> dict[str, Any]:
    applied_policy = policy or TotalGoalsCalibrationPolicy()
    observations, excluded = _eligible_total_observations(
        calibration_source_rows(db_path=db_path),
        applied_policy,
    )
    side_status = {
        side: _side_calibration_status(side, observations, applied_policy)
        for side in ("over", "under")
    }
    enough_total = len(observations) >= applied_policy.min_total_samples
    enough_sides = all(side_status[side]["sampleCount"] >= applied_policy.min_side_samples for side in ("over", "under"))
    status = "RESEARCH_READY" if enough_total and enough_sides else "INSUFFICIENT_OU_DATA"
    return {
        "version": TOTAL_GOALS_CALIBRATION_VERSION,
        "status": status,
        "statusLabel": "大小球研究校准可用" if status == "RESEARCH_READY" else "大小球样本不足",
        "enabled": True,
        "formalApproved": False,
        "formalEvEnabled": False,
        "policy": asdict(applied_policy),
        "sampleCount": len(observations),
        "distinctFixtures": len({item.fixture_id for item in observations}),
        "sides": side_status,
        "excluded": excluded,
        "notes": [
            "大小球校准因子只修正 research_EV，不开放 paper_EV、pfinal 或正式资金。",
            "同一场、同一盘口、同一方向只保留最早赛前快照，避免重复分析放大样本。",
            "样本不足时因子按可信度自动收缩到 1.00，避免小样本过度修正。",
        ],
    }


def apply_total_goals_settlement_calibration(
    settlement: dict[str, float],
    odd: float,
    side: str,
    calibration_status: dict[str, Any] | None,
) -> dict[str, float | dict[str, Any]]:
    side_key = "over" if side == "over" else "under"
    side_calibration = ((calibration_status or {}).get("sides") or {}).get(side_key) or {}
    if not side_calibration:
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
                "version": (calibration_status or {}).get("version") or TOTAL_GOALS_CALIBRATION_VERSION,
                "status": (calibration_status or {}).get("status"),
                "formalApproved": False,
                "side": side_key,
                "sideLabel": "大球" if side_key == "over" else "小球",
                "factor": positive_factor,
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
                "note": "大小球研究校准因子已应用；仅影响 research_EV 审计，不开放正式资金。",
            },
        }
    )
    return updated


def _eligible_total_observations(
    rows: list[dict[str, Any]],
    policy: TotalGoalsCalibrationPolicy,
) -> tuple[list[TotalGoalsObservation], dict[str, int]]:
    excluded = {
        "missing_snapshot_or_recommendation": 0,
        "missing_time_or_bookmaker": 0,
        "post_kickoff_or_future_odds": 0,
        "missing_total_fields": 0,
        "duplicate_fixture_line_side": 0,
    }
    selected: dict[tuple[str, float, str], TotalGoalsObservation] = {}
    for row in rows:
        snapshot_id = row.get("snapshot_id")
        payload = row.get("payload") or {}
        recommendation = _total_recommendation(payload)
        if not snapshot_id or not recommendation:
            excluded["missing_snapshot_or_recommendation"] += 1
            continue

        prediction_time = _parse_time(row.get("prediction_created_at"))
        captured_time = _parse_time(row.get("odds_captured_at"))
        kickoff_time = _parse_time(row.get("kickoff_at"))
        bookmaker = str(row.get("selected_bookmaker") or "").strip()
        if not prediction_time or not captured_time or not kickoff_time or not bookmaker:
            excluded["missing_time_or_bookmaker"] += 1
            continue
        if prediction_time >= kickoff_time or captured_time >= kickoff_time or captured_time > prediction_time:
            excluded["post_kickoff_or_future_odds"] += 1
            continue

        observation = _observation_from_recommendation(row, recommendation, int(snapshot_id))
        if observation is None:
            excluded["missing_total_fields"] += 1
            continue

        key = (observation.fixture_id, round(observation.line, 2), observation.side)
        existing = selected.get(key)
        if existing is not None:
            excluded["duplicate_fixture_line_side"] += 1
            if _parse_time(existing.prediction_created_at) <= prediction_time:
                continue
        selected[key] = observation

    observations = sorted(
        selected.values(),
        key=lambda item: (_parse_time(item.kickoff_at) or datetime.max.replace(tzinfo=timezone.utc), item.fixture_id),
    )
    return observations, excluded


def _total_recommendation(payload: dict[str, Any]) -> dict[str, Any] | None:
    for item in payload.get("recommendations") or []:
        if not isinstance(item, dict):
            continue
        if str(item.get("market") or "") == "大小球":
            return item
    return None


def _observation_from_recommendation(
    row: dict[str, Any],
    recommendation: dict[str, Any],
    snapshot_id: int,
) -> TotalGoalsObservation | None:
    fixture_id = str(row.get("fixture_id") or "")
    side = _selection_side(str(recommendation.get("selection") or ""))
    line = _safe_number(recommendation.get("line"), math.nan)
    odds = _safe_number(recommendation.get("odds"), math.nan)
    if not fixture_id or side not in {"over", "under"} or not math.isfinite(line) or not math.isfinite(odds) or odds <= 1:
        return None

    calc = recommendation.get("ev_calculation") or {}
    model_positive = _first_number(
        calc.get("rawPositiveReturnProbability"),
        calc.get("positiveReturnProbability"),
        recommendation.get("model_probability"),
    )
    model_win = _first_number(calc.get("rawWinStakeFraction"), calc.get("winStakeFraction"))
    model_loss = _first_number(calc.get("rawLossStakeFraction"), calc.get("lossStakeFraction"))
    if model_positive is None or model_win is None or model_loss is None:
        return None

    home_goals = int(row["home_goals_90"])
    away_goals = int(row["away_goals_90"])
    actual = _actual_total_settlement(home_goals + away_goals, line, side, odds)
    return TotalGoalsObservation(
        fixture_id=fixture_id,
        snapshot_id=snapshot_id,
        prediction_created_at=str(row.get("prediction_created_at") or ""),
        kickoff_at=str(row.get("kickoff_at") or ""),
        side=side,
        line=line,
        odds=odds,
        model_positive_probability=clamp(model_positive, 0.0, 1.0),
        model_win_fraction=clamp(model_win, 0.0, 1.0),
        model_loss_fraction=clamp(model_loss, 0.0, 1.0),
        market_probability=_first_number(recommendation.get("market_probability")),
        expected_value=_first_number(
            calc.get("rawExpectedValue"),
            recommendation.get("ev_pbase_research"),
            recommendation.get("expected_value_per_unit"),
            recommendation.get("audit_expected_value_per_unit"),
        ),
        actual_positive=1.0 if actual["net"] > 0 else 0.0,
        actual_win_fraction=actual["win_fraction"],
        actual_loss_fraction=actual["loss_fraction"],
        actual_net=actual["net"],
    )


def _side_calibration_status(
    side: str,
    observations: list[TotalGoalsObservation],
    policy: TotalGoalsCalibrationPolicy,
) -> dict[str, Any]:
    side_rows = [item for item in observations if item.side == side]
    count = len(side_rows)
    credibility = clamp(count / max(1, policy.min_side_samples), 0.0, 1.0)
    if not side_rows:
        return {
            "side": side,
            "sideLabel": "大球" if side == "over" else "小球",
            "sampleCount": 0,
            "status": "LOW_SAMPLE",
            "credibility": 0.0,
            "positiveFactor": 1.0,
            "winFactor": 1.0,
            "lossFactor": 1.0,
            "factor": 1.0,
        }
    mean_model_positive = _mean(item.model_positive_probability for item in side_rows)
    mean_model_win = _mean(item.model_win_fraction for item in side_rows)
    mean_model_loss = _mean(item.model_loss_fraction for item in side_rows)
    actual_positive_rate = _mean(item.actual_positive for item in side_rows)
    actual_win_rate = _mean(item.actual_win_fraction for item in side_rows)
    actual_loss_rate = _mean(item.actual_loss_fraction for item in side_rows)
    positive_factor = _blended_factor(actual_positive_rate, mean_model_positive, credibility, policy)
    win_factor = _blended_factor(actual_win_rate, mean_model_win, credibility, policy)
    loss_factor = _blended_factor(actual_loss_rate, mean_model_loss, credibility, policy)
    return {
        "side": side,
        "sideLabel": "大球" if side == "over" else "小球",
        "status": "OK" if count >= policy.min_side_samples else "LOW_SAMPLE",
        "sampleCount": count,
        "credibility": credibility,
        "positiveFactor": positive_factor,
        "winFactor": win_factor,
        "lossFactor": loss_factor,
        "factor": positive_factor,
        "meanModelPositiveProbability": mean_model_positive,
        "actualPositiveRate": actual_positive_rate,
        "meanModelWinFraction": mean_model_win,
        "actualWinFractionRate": actual_win_rate,
        "meanModelLossFraction": mean_model_loss,
        "actualLossFractionRate": actual_loss_rate,
        "meanMarketProbability": _nullable_mean(item.market_probability for item in side_rows),
        "meanExpectedValue": _nullable_mean(item.expected_value for item in side_rows),
        "meanActualNet": _mean(item.actual_net for item in side_rows),
        "modelBias": mean_model_positive - actual_positive_rate,
        "winFractionBias": mean_model_win - actual_win_rate,
        "lossFractionBias": mean_model_loss - actual_loss_rate,
    }


def _blended_factor(
    actual_rate: float,
    model_rate: float,
    credibility: float,
    policy: TotalGoalsCalibrationPolicy,
) -> float:
    if model_rate <= 1e-9:
        raw = 1.0
    else:
        raw = actual_rate / model_rate
    return clamp(1.0 + credibility * (raw - 1.0), policy.min_factor, policy.max_factor)


def _actual_total_settlement(total_goals: int, line: float, side: str, odd: float) -> dict[str, float]:
    diffs = [
        (total_goals - split_line if side == "over" else split_line - total_goals)
        for split_line in _split_asian_line(line)
    ]
    net, win_fraction, loss_fraction = _split_settlement_net(diffs, odd)
    return {"net": net, "win_fraction": win_fraction, "loss_fraction": loss_fraction}


def _split_asian_line(line: float) -> list[float]:
    rounded = round(line * 4) / 4
    lower = math.floor(rounded * 2) / 2
    upper = math.ceil(rounded * 2) / 2
    if abs(lower - upper) < 1e-9:
        return [rounded]
    return [lower, upper]


def _split_settlement_net(diffs: list[float], odd: float) -> tuple[float, float, float]:
    if not diffs:
        return 0.0, 0.0, 0.0
    net = 0.0
    win_fraction = 0.0
    loss_fraction = 0.0
    for diff in diffs:
        if diff > 1e-9:
            net += odd - 1.0
            win_fraction += 1.0
        elif diff < -1e-9:
            net -= 1.0
            loss_fraction += 1.0
    count = len(diffs)
    return net / count, win_fraction / count, loss_fraction / count


def _selection_side(selection: str) -> str | None:
    text = selection.strip().casefold()
    if text.startswith("大") or text.startswith("over"):
        return "over"
    if text.startswith("小") or text.startswith("under"):
        return "under"
    return None


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


def _break_even_odds(win_fraction: float, loss_fraction: float) -> float | None:
    if win_fraction <= 1e-12:
        return None
    return 1.0 + loss_fraction / win_fraction
