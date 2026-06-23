from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from typing import Any, Callable

from .backtest import actual_result_key, brier_score, log_loss
from .storage import calibration_source_rows, market_dataset_coverage

OUTCOMES = ("home_win", "draw", "away_win")
MARKET_DATASET_VERSION = "priority_bookmaker_fulltime_snapshot_v3"
PBASE_MODEL_VERSION = "pbase_poisson_recent_form_v1"
PSHR_MODEL_VERSION = "pshr_outcome_bias_calibrated_pbase_v2"


@dataclass(frozen=True)
class CalibrationPolicy:
    min_eligible_samples: int = 100
    min_distinct_fixtures: int = 100
    min_calibration_samples: int = 20
    min_validation_samples: int = 20
    max_log_loss_gap_to_market: float = 0.02
    max_brier_gap_to_market: float = 0.01
    outcome_calibration_prior_samples: int = 20
    min_outcome_factor: float = 0.75
    max_outcome_factor: float = 1.35


@dataclass(frozen=True)
class CalibrationObservation:
    fixture_id: str
    snapshot_id: int
    prediction_created_at: str
    odds_captured_at: str
    kickoff_at: str
    pbase: dict[str, float]
    qmkt: dict[str, float]
    actual_key: str


@dataclass(frozen=True)
class PshrCandidate:
    formula: str
    market_weight: float
    raw_market_weight: float | None
    outcome_factors: dict[str, float]
    outcome_actual_rates: dict[str, float]
    outcome_predicted_rates: dict[str, float]
    outcome_target_rates: dict[str, float]
    prior_samples: int

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_model_validation_status(
    db_path: str | None = None,
    policy: CalibrationPolicy | None = None,
) -> dict[str, Any]:
    applied_policy = policy or CalibrationPolicy()
    observations, exclusions = _eligible_observations(calibration_source_rows(db_path=db_path))
    development, calibration, validation = _chronological_split(observations)
    pshr_fit = _fit_pshr_candidate(calibration, applied_policy) if calibration else None

    metrics = {
        "development": _metric_pack(development, pshr_fit),
        "calibration": _metric_pack(calibration, pshr_fit),
        "validation": _metric_pack(validation, pshr_fit),
    }
    checks = _acceptance_checks(observations, calibration, validation, metrics["validation"], applied_policy)
    qualified = bool(checks) and all(item["passed"] for item in checks)
    enough_samples = (
        len(observations) >= applied_policy.min_eligible_samples
        and len({item.fixture_id for item in observations}) >= applied_policy.min_distinct_fixtures
        and len(calibration) >= applied_policy.min_calibration_samples
        and len(validation) >= applied_policy.min_validation_samples
    )
    if not enough_samples:
        status = "INSUFFICIENT_DATA"
        label = "校准样本不足"
    elif qualified:
        status = "ELIGIBLE_FOR_REVIEW"
        label = "待人工审批"
    else:
        status = "REJECTED"
        label = "未通过校准验收"

    return {
        "status": status,
        "statusLabel": label,
        "formalEvEnabled": False,
        "formalEvLabel": "正式EV关闭",
        "datasetVersion": MARKET_DATASET_VERSION,
        "pbaseVersion": PBASE_MODEL_VERSION,
        "pshrVersion": PSHR_MODEL_VERSION,
        "pfinalStatus": "not_approved",
        "policy": asdict(applied_policy),
        "marketCoverage": market_dataset_coverage(db_path=db_path),
        "eligibleSamples": len(observations),
        "distinctFixtures": len({item.fixture_id for item in observations}),
        "split": {
            "development": len(development),
            "calibration": len(calibration),
            "validation": len(validation),
        },
        "fittedMarketWeight": pshr_fit.market_weight if pshr_fit else None,
        "rawCalibrationMarketWeight": pshr_fit.raw_market_weight if pshr_fit else None,
        "pshrParameters": pshr_fit.to_dict() if pshr_fit else None,
        "metrics": metrics,
        "checks": checks,
        "excluded": exclusions,
        "notes": [
            "仅纳入在开赛前生成、具备庄家优先级全场赔率时点且已有 90 分钟赛果的真实 API 快照。",
            "pshr 使用校准区间拟合主胜/平/客胜类别偏差校准因子；市场概率作为对照基准，验证区间只用于时间外评估。",
            "当前时间切分验收对象为胜平负三分类概率；大小球与让球仍需独立的比分分布校准验收。",
            "即使达到待审批条件，正式 EV 仍保持关闭，须另行确认 pfinal 公式与策略回测。",
        ],
    }


def _eligible_observations(rows: list[dict[str, Any]]) -> tuple[list[CalibrationObservation], dict[str, int]]:
    excluded = {
        "missing_snapshot_or_probability": 0,
        "missing_time_or_bookmaker": 0,
        "post_kickoff_or_future_odds": 0,
        "duplicate_fixture": 0,
    }
    selected: dict[str, CalibrationObservation] = {}
    for row in rows:
        payload = row.get("payload") or {}
        probabilities = payload.get("probabilities") or {}
        pbase = _normalized_probabilities(probabilities.get("pbase") or probabilities.get("model"))
        qmkt = _normalized_probabilities(probabilities.get("qmkt") or probabilities.get("market"))
        snapshot_id = row.get("snapshot_id")
        if not snapshot_id or not pbase or not qmkt:
            excluded["missing_snapshot_or_probability"] += 1
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

        fixture_id = str(row.get("fixture_id") or "")
        observation = CalibrationObservation(
            fixture_id=fixture_id,
            snapshot_id=int(snapshot_id),
            prediction_created_at=prediction_time.isoformat(),
            odds_captured_at=captured_time.isoformat(),
            kickoff_at=kickoff_time.isoformat(),
            pbase=pbase,
            qmkt=qmkt,
            actual_key=actual_result_key(int(row["home_goals_90"]), int(row["away_goals_90"])),
        )
        existing = selected.get(fixture_id)
        if existing is not None:
            excluded["duplicate_fixture"] += 1
            if _parse_time(existing.prediction_created_at) >= prediction_time:
                continue
        selected[fixture_id] = observation
    observations = sorted(selected.values(), key=lambda item: (_parse_time(item.kickoff_at), item.fixture_id))
    return observations, excluded


def _chronological_split(
    observations: list[CalibrationObservation],
) -> tuple[list[CalibrationObservation], list[CalibrationObservation], list[CalibrationObservation]]:
    count = len(observations)
    if count < 3:
        return observations, [], []
    development_end = max(1, int(count * 0.60))
    calibration_end = max(development_end + 1, int(count * 0.80))
    calibration_end = min(calibration_end, count - 1)
    return (
        observations[:development_end],
        observations[development_end:calibration_end],
        observations[calibration_end:],
    )


def _fit_market_shrinkage_alpha(observations: list[CalibrationObservation]) -> float | None:
    if not observations:
        return None
    candidates = [step / 20 for step in range(21)]
    return min(
        candidates,
        key=lambda alpha: (
            _mean_log_loss(observations, lambda item: _shrink_probability(item, alpha)),
            alpha,
        ),
    )


def _fit_pshr_candidate(observations: list[CalibrationObservation], policy: CalibrationPolicy) -> PshrCandidate | None:
    if not observations:
        return None
    raw_market_weight = _fit_market_shrinkage_alpha(observations)
    factors, actual_rates, predicted_rates, target_rates = _fit_outcome_factors(observations, policy)
    return PshrCandidate(
        formula="outcome_bias_calibrated_pbase",
        market_weight=0.0,
        raw_market_weight=raw_market_weight,
        outcome_factors=factors,
        outcome_actual_rates=actual_rates,
        outcome_predicted_rates=predicted_rates,
        outcome_target_rates=target_rates,
        prior_samples=policy.outcome_calibration_prior_samples,
    )


def _fit_outcome_factors(
    observations: list[CalibrationObservation],
    policy: CalibrationPolicy,
) -> tuple[dict[str, float], dict[str, float], dict[str, float], dict[str, float]]:
    count = len(observations)
    predicted_rates = {
        key: sum(item.pbase[key] for item in observations) / count
        for key in OUTCOMES
    }
    actual_rates = {
        key: sum(1.0 for item in observations if item.actual_key == key) / count
        for key in OUTCOMES
    }
    prior = max(0, policy.outcome_calibration_prior_samples)
    target_rates = {
        key: (actual_rates[key] * count + predicted_rates[key] * prior) / (count + prior)
        for key in OUTCOMES
    }
    factors = {
        key: _clamp(
            target_rates[key] / predicted_rates[key] if predicted_rates[key] > 0 else 1.0,
            policy.min_outcome_factor,
            policy.max_outcome_factor,
        )
        for key in OUTCOMES
    }
    return factors, actual_rates, predicted_rates, target_rates


def _metric_pack(observations: list[CalibrationObservation], pshr_fit: PshrCandidate | None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "samples": len(observations),
        "pbase": _probability_metrics(observations, lambda item: item.pbase),
        "qmkt": _probability_metrics(observations, lambda item: item.qmkt),
        "pshr": None,
    }
    if pshr_fit is not None:
        result["pshr"] = _probability_metrics(observations, lambda item: _pshr_probability(item, pshr_fit))
    return result


def _probability_metrics(
    observations: list[CalibrationObservation],
    probabilities_for: Callable[[CalibrationObservation], dict[str, float]],
) -> dict[str, float] | None:
    if not observations:
        return None
    return {
        "brierScore": sum(brier_score(probabilities_for(item), item.actual_key) for item in observations) / len(observations),
        "logLoss": _mean_log_loss(observations, probabilities_for),
        "calibrationError": _calibration_error(observations, probabilities_for),
    }


def _mean_log_loss(
    observations: list[CalibrationObservation],
    probabilities_for: Callable[[CalibrationObservation], dict[str, float]],
) -> float:
    return sum(log_loss(probabilities_for(item), item.actual_key) for item in observations) / len(observations)


def _calibration_error(
    observations: list[CalibrationObservation],
    probabilities_for: Callable[[CalibrationObservation], dict[str, float]],
) -> float:
    buckets: dict[int, list[tuple[float, float]]] = {}
    for item in observations:
        probabilities = probabilities_for(item)
        for key in OUTCOMES:
            probability = probabilities[key]
            bucket = min(9, int(probability * 10))
            buckets.setdefault(bucket, []).append((probability, 1.0 if item.actual_key == key else 0.0))
    total = sum(len(values) for values in buckets.values())
    error = 0.0
    for values in buckets.values():
        mean_prediction = sum(value[0] for value in values) / len(values)
        mean_actual = sum(value[1] for value in values) / len(values)
        error += len(values) / total * abs(mean_prediction - mean_actual)
    return error


def _acceptance_checks(
    observations: list[CalibrationObservation],
    calibration: list[CalibrationObservation],
    validation: list[CalibrationObservation],
    validation_metrics: dict[str, Any],
    policy: CalibrationPolicy,
) -> list[dict[str, Any]]:
    distinct = len({item.fixture_id for item in observations})
    checks: list[dict[str, Any]] = [
        _check("合格赛前样本", len(observations) >= policy.min_eligible_samples, len(observations), policy.min_eligible_samples),
        _check("独立比赛数量", distinct >= policy.min_distinct_fixtures, distinct, policy.min_distinct_fixtures),
        _check("校准区间样本", len(calibration) >= policy.min_calibration_samples, len(calibration), policy.min_calibration_samples),
        _check("验证区间样本", len(validation) >= policy.min_validation_samples, len(validation), policy.min_validation_samples),
    ]
    pbase = validation_metrics.get("pbase")
    qmkt = validation_metrics.get("qmkt")
    pshr = validation_metrics.get("pshr")
    if not pbase or not qmkt or not pshr:
        return checks
    checks.extend(
        [
            {
                "label": "pshr Brier 不劣于 pbase",
                "passed": pshr["brierScore"] <= pbase["brierScore"],
                "detail": f"{pshr['brierScore']:.4f} <= {pbase['brierScore']:.4f}",
            },
            {
                "label": "pshr Log Loss 不劣于 pbase",
                "passed": pshr["logLoss"] <= pbase["logLoss"],
                "detail": f"{pshr['logLoss']:.4f} <= {pbase['logLoss']:.4f}",
            },
            {
                "label": "pshr 未显著劣于市场基准",
                "passed": (
                    pshr["logLoss"] <= qmkt["logLoss"] + policy.max_log_loss_gap_to_market
                    and pshr["brierScore"] <= qmkt["brierScore"] + policy.max_brier_gap_to_market
                ),
                "detail": (
                    f"Log Loss 差 {pshr['logLoss'] - qmkt['logLoss']:+.4f}；"
                    f"Brier 差 {pshr['brierScore'] - qmkt['brierScore']:+.4f}"
                ),
            },
        ]
    )
    return checks


def _check(label: str, passed: bool, actual: int, required: int) -> dict[str, Any]:
    return {"label": label, "passed": passed, "detail": f"{actual} / {required}"}


def _shrink_probability(item: CalibrationObservation, alpha: float) -> dict[str, float]:
    return {
        key: (1.0 - alpha) * item.pbase[key] + alpha * item.qmkt[key]
        for key in OUTCOMES
    }


def _pshr_probability(item: CalibrationObservation, pshr_fit: PshrCandidate) -> dict[str, float]:
    calibrated = {
        key: item.pbase[key] * pshr_fit.outcome_factors[key]
        for key in OUTCOMES
    }
    total = sum(calibrated.values())
    if total <= 0:
        return item.pbase
    pbase_calibrated = {key: value / total for key, value in calibrated.items()}
    if pshr_fit.market_weight <= 0:
        return pbase_calibrated
    blended = {
        key: (1.0 - pshr_fit.market_weight) * pbase_calibrated[key] + pshr_fit.market_weight * item.qmkt[key]
        for key in OUTCOMES
    }
    total = sum(blended.values())
    return {key: value / total for key, value in blended.items()}


def _normalized_probabilities(raw: Any) -> dict[str, float] | None:
    if not isinstance(raw, dict):
        return None
    try:
        values = {key: max(0.0, float(raw[key])) for key in OUTCOMES}
    except (KeyError, TypeError, ValueError):
        return None
    total = sum(values.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in values.items()}


def _clamp(value: float, lower: float, upper: float) -> float:
    return min(upper, max(lower, value))


def _parse_time(value: Any) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
