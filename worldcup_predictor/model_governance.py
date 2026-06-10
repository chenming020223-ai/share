from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from .betting import (
    EV_LAYER_PBASE_RESEARCH,
    SIGNAL_STATUS_RESEARCH_WATCH,
    BetRecommendation,
    PaperPortfolio,
    recalculate_portfolio,
)


@dataclass(frozen=True)
class ModelGovernance:
    pbase_status: str
    qmkt_status: str
    pshr_status: str
    pfinal_status: str
    display_probability_version: str
    ev_probability_source: str
    formal_ev_enabled: bool
    gate_label: str
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            **asdict(self),
            "formalEvEnabled": self.formal_ev_enabled,
            "gateLabel": self.gate_label,
            "displayProbabilityVersion": self.display_probability_version,
            "evProbabilitySource": self.ev_probability_source,
        }


def api_model_governance() -> ModelGovernance:
    return ModelGovernance(
        pbase_status="available_unvalidated",
        qmkt_status="available_when_pinnacle_odds_complete",
        pshr_status="pipeline_available_pending_eligible_samples",
        pfinal_status="not_validated",
        display_probability_version="mvp_display_blend_not_pfinal",
        ev_probability_source="pbase_candidate_only",
        formal_ev_enabled=False,
        gate_label="正式EV待校准",
        notes=[
            "基础模型概率仅作为 pbase 候选概率，尚未通过时间切分校准验证。",
            "指定庄家去水概率作为 qmkt 市场基准，不直接产生模拟信号。",
            "pshr 时间切分审计流程已建立；pfinal 尚未验收，API 模式保留研究试算 EV 供复核但不占用资金。",
        ],
    )


def sample_model_governance() -> ModelGovernance:
    return ModelGovernance(
        pbase_status="demo_only",
        qmkt_status="demo_only",
        pshr_status="not_applicable_to_demo",
        pfinal_status="not_available",
        display_probability_version="mvp_display_blend_not_pfinal",
        ev_probability_source="demo_candidate_only",
        formal_ev_enabled=False,
        gate_label="本地演示",
        notes=[
            "示例模式只用于界面、报告和流程验收，不代表正式模型准入状态。",
        ],
    )


def apply_formal_ev_gate(
    recommendations: list[BetRecommendation],
    portfolio: PaperPortfolio,
    governance: ModelGovernance,
    *,
    enforce: bool,
) -> tuple[list[BetRecommendation], PaperPortfolio]:
    if not enforce or governance.formal_ev_enabled:
        return recommendations, portfolio

    adjusted: list[BetRecommendation] = []
    for item in recommendations:
        if item.action not in {"BUY", "PAPER_BUY"}:
            adjusted.append(item)
            continue
        adjusted.append(
            replace(
                item,
                action="WATCH",
                stake=0.0,
                signal_status=SIGNAL_STATUS_RESEARCH_WATCH,
                ev_layer=EV_LAYER_PBASE_RESEARCH,
                ev_pfinal_exec=None,
                reason=(
                    f"{item.reason} 当前仅形成研究试算 EV，pshr/pfinal 尚未通过时间切分校准与回测验证；"
                    "正式模拟信号未启用，降级为待校准复核。"
                ),
            )
        )

    return adjusted, recalculate_portfolio(portfolio, adjusted)
