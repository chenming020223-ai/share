from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from .betting import (
    DECISION_FORMAL_EV_DISABLED,
    DECISION_PAPER_OBSERVATION,
    EV_STATUS_DISABLED_PFINAL_NOT_APPROVED,
    EV_STATUS_PAPER_OBSERVATION,
    EV_LAYER_PBASE_RESEARCH,
    SIGNAL_STATUS_PAPER_BUY,
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
        ev_probability_source="paper_ev_p_adj_for_simulation_pfinal_closed",
        formal_ev_enabled=False,
        gate_label="纸上模拟开放，正式EV关闭",
        notes=[
            "基础模型概率仅作为 pbase 候选概率，尚未通过时间切分校准验证。",
            "指定庄家去水概率作为 qmkt 市场基准，不直接产生模拟信号。",
            "pshr 时间切分审计流程已建立；pfinal 尚未验收，正式 EV 不开放。",
            "模拟舱按 paper_EV / p_adj 纸上层占用资金；真实下注与 formal_EV 仍必须等待 pfinal 审批。",
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
        if item.action == "PAPER_BUY":
            calculation = dict(item.ev_calculation or {})
            if calculation:
                calculation["paperSimulationEnabled"] = item.stake > 0
                calculation["formalExecutionEnabled"] = False
                calculation["formalProbabilitySource"] = "paper_ev_p_adj_formal_disabled"
                calculation["candidateAction"] = "PAPER_BUY"
                calculation["governanceNote"] = (
                    "pfinal 尚未通过时间切分校准与回测验收；正式资金关闭，纸上模拟保留。"
                )
            adjusted.append(
                replace(
                    item,
                    signal_status=SIGNAL_STATUS_PAPER_BUY,
                    ev_status=EV_STATUS_PAPER_OBSERVATION,
                    decision_status=DECISION_PAPER_OBSERVATION,
                    ev_pfinal_exec=None,
                    ev_calculation=calculation,
                    reason=_append_sentence(
                        item.reason,
                        "pfinal/formal_EV 未审批，当前仅占用纸上模拟资金，不代表真实下注或正式执行。",
                    ),
                )
            )
            continue
        if item.action != "BUY":
            adjusted.append(item)
            continue
        calculation = dict(item.ev_calculation or {})
        if calculation:
            calculation["paperSimulationEnabled"] = False
            calculation["formalExecutionEnabled"] = False
            calculation["formalProbabilitySource"] = "pfinal_not_approved"
            calculation["candidateAction"] = "WATCH"
            calculation["governanceNote"] = "pfinal 尚未通过时间切分校准与回测验收，资金占用关闭。"
        adjusted.append(
            replace(
                item,
                action="WATCH",
                stake=0.0,
                signal_status=SIGNAL_STATUS_RESEARCH_WATCH,
                ev_layer=EV_LAYER_PBASE_RESEARCH,
                ev_status=EV_STATUS_DISABLED_PFINAL_NOT_APPROVED,
                decision_status=DECISION_FORMAL_EV_DISABLED,
                ev_pfinal_exec=None,
                ev_calculation=calculation,
                reason=(
                    f"{item.reason} 当前仅形成研究试算 EV，pshr/pfinal 尚未通过时间切分校准与回测验证；"
                    "正式模拟资金未启用，降级为待校准复核。"
                ),
            )
        )

    return adjusted, recalculate_portfolio(portfolio, adjusted)


def _append_sentence(text: str, sentence: str) -> str:
    if sentence in text:
        return text
    separator = "" if text.endswith(("。", "！", "？", ".", "!", "?")) else "。"
    return f"{text}{separator}{sentence}"
