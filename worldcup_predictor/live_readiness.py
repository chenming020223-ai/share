from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from .calibration import build_model_validation_status
from .paper_bankroll import build_paper_bankroll_timeline
from .storage import storage_health


@dataclass(frozen=True)
class LiveReadinessPolicy:
    min_model_eligible_samples: int = 100
    min_distinct_fixtures: int = 100
    min_settled_paper_bets: int = 50
    min_paper_roi: float = 0.02
    max_paper_drawdown: float = 0.20
    min_market_quotes: int = 1000


def build_live_readiness_status(
    db_path: str | None = None,
    policy: LiveReadinessPolicy | None = None,
    *,
    model_validation: dict[str, Any] | None = None,
    storage: dict[str, Any] | None = None,
    bankroll_timeline: dict[str, Any] | None = None,
) -> dict[str, Any]:
    applied_policy = policy or LiveReadinessPolicy()
    validation = model_validation or build_model_validation_status(db_path=db_path)
    health = storage or storage_health(db_path=db_path)
    timeline = bankroll_timeline or build_paper_bankroll_timeline(db_path=db_path)
    paper = _paper_metrics(timeline)

    checks = [
        _check(
            "模型时间切分验收",
            validation.get("status") == "ELIGIBLE_FOR_REVIEW",
            str(validation.get("statusLabel") or validation.get("status") or "-"),
            "达到待人工审批",
            "先完成赛前样本、校准区间、验证区间和 pshr 指标验收。",
        ),
        _check(
            "合格赛前样本",
            int(validation.get("eligibleSamples") or 0) >= applied_policy.min_model_eligible_samples,
            f"{int(validation.get('eligibleSamples') or 0)} / {applied_policy.min_model_eligible_samples}",
            f">= {applied_policy.min_model_eligible_samples}",
            "继续批量建库并同步 90 分钟赛果。",
        ),
        _check(
            "独立比赛数量",
            int(validation.get("distinctFixtures") or 0) >= applied_policy.min_distinct_fixtures,
            f"{int(validation.get('distinctFixtures') or 0)} / {applied_policy.min_distinct_fixtures}",
            f">= {applied_policy.min_distinct_fixtures}",
            "避免同一 fixture 重复预测污染验证集。",
        ),
        _check(
            "正式 pfinal 概率",
            str(validation.get("pfinalStatus") or "") == "approved" and bool(validation.get("formalEvEnabled")),
            str(validation.get("pfinalStatus") or "not_approved"),
            "approved + formalEvEnabled=true",
            "冻结 pshr -> pfinal 公式，经人工审批后才允许进入正式 EV。",
        ),
        _check(
            "大小球/让球专项校准",
            False,
            "未完成",
            "OU/AH settlement calibration passed",
            "胜平负验收不能替代大小球和让球；需要比分分布层专项回测。",
        ),
        _check(
            "结构化盘口数据",
            int(health.get("market_quotes") or 0) >= applied_policy.min_market_quotes,
            f"{int(health.get('market_quotes') or 0)} / {applied_policy.min_market_quotes}",
            f">= {applied_policy.min_market_quotes}",
            "继续保存同庄家、同盘口线、同时间点的全场盘口报价。",
        ),
        _check(
            "纸上下注已结算",
            paper["settledBets"] >= applied_policy.min_settled_paper_bets,
            f"{paper['settledBets']} / {applied_policy.min_settled_paper_bets}",
            f">= {applied_policy.min_settled_paper_bets}",
            "正式实盘前必须先跑纸上账本，验证资金曲线和结算逻辑。",
        ),
        _check(
            "纸上 ROI",
            paper["roi"] >= applied_policy.min_paper_roi,
            f"{paper['roi'] * 100:.1f}%",
            f">= {applied_policy.min_paper_roi * 100:.1f}%",
            "只允许用已结算纸上观察结果评估，不使用未结算期望收益。",
        ),
        _check(
            "纸上最大回撤",
            paper["maxDrawdownPct"] <= applied_policy.max_paper_drawdown and paper["settledBets"] > 0,
            f"{paper['maxDrawdownPct'] * 100:.1f}%",
            f"<= {applied_policy.max_paper_drawdown * 100:.1f}%",
            "回撤超过阈值时进入人工复核，不得升级实盘。",
        ),
    ]

    passed = all(item["passed"] for item in checks)
    if passed:
        status = "READY_FOR_MANUAL_APPROVAL"
        label = "达到人工实盘审批门槛"
    else:
        status = "BLOCKED"
        label = "实盘禁用"

    return {
        "status": status,
        "statusLabel": label,
        "canUseRealMoney": False,
        "realMoneyLabel": "禁止真实下注",
        "policy": asdict(applied_policy),
        "modelValidation": validation,
        "storage": health,
        "paperTrading": paper,
        "checks": checks,
        "blockingReasons": [item["label"] for item in checks if not item["passed"]],
        "notes": [
            "本判定器只负责实盘准入审计，不会自动开放真实下注。",
            "当前系统即使出现研究 EV，也不能视为实盘信号；正式 EV 只能来自已批准 pfinal。",
            "大小球和让球必须完成独立的比分分布层校准，不能借用胜平负校准结论。",
        ],
    }


def _paper_metrics(timeline: dict[str, Any]) -> dict[str, Any]:
    events = timeline.get("events") or []
    settles = [
        item for item in events
        if isinstance(item, dict) and item.get("eventType") == "SETTLE"
    ]
    total_profit = sum(float(item.get("profit") or 0.0) for item in settles)
    total_stake = sum(float(item.get("stake") or 0.0) for item in settles)
    max_drawdown = max((float(item.get("drawdownPct") or 0.0) for item in events if isinstance(item, dict)), default=0.0)
    summary = timeline.get("summary") or {}
    return {
        "settledBets": len(settles),
        "openBets": int(summary.get("openCount") or 0),
        "totalStake": total_stake,
        "totalProfit": total_profit,
        "roi": (total_profit / total_stake) if total_stake > 0 else 0.0,
        "maxDrawdownPct": max_drawdown,
        "riskMode": str(summary.get("riskMode") or "normal"),
        "riskLabel": str(summary.get("riskLabel") or "正常"),
    }


def _check(label: str, passed: bool, actual: str, required: str, next_step: str) -> dict[str, Any]:
    return {
        "label": label,
        "passed": bool(passed),
        "actual": actual,
        "required": required,
        "nextStep": next_step,
    }
