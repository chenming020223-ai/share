from __future__ import annotations

from dataclasses import asdict, dataclass, replace

from .betting import BetRecommendation, PaperPortfolio
from .market import MarketSnapshot
from .models import clamp


@dataclass(frozen=True)
class MarketAvailability:
    key: str
    label: str
    status: str
    status_label: str
    score: float
    details: str
    line: float | None = None


@dataclass(frozen=True)
class DataQualityReport:
    score: float
    grade: str
    grade_label: str
    min_quality: float
    factors: dict[str, float]
    markets: list[MarketAvailability]
    notes: list[str]

    def to_dict(self) -> dict:
        return {
            "score": self.score,
            "grade": self.grade,
            "gradeLabel": self.grade_label,
            "minQuality": self.min_quality,
            "factors": dict(self.factors),
            "markets": [asdict(item) for item in self.markets],
            "notes": list(self.notes),
        }


def build_data_quality_report(
    market: MarketSnapshot,
    fixture_id: str | int | None,
    team_rating_score: float,
    context_score: float,
    lineup_score: float = 0.0,
    min_quality: float = 0.60,
    sample: bool = False,
    max_score: float | None = None,
    extra_notes: list[str] | None = None,
) -> DataQualityReport:
    markets = market_availability(market)
    available_markets = sum(1 for item in markets if item.status == "available")
    odds_completeness = available_markets / len(markets) if markets else 0.0
    fixture_certainty = 1.0 if str(fixture_id or "").strip() else 0.0
    if market.required_bookmaker:
        bookmaker_quality = 1.0 if market.selected_bookmaker else 0.0
    else:
        bookmaker_quality = clamp(market.bookmakers_count / 8.0, 0.0, 1.0)
    if sample and market.bookmakers_count > 0:
        bookmaker_quality = 0.55

    factors = {
        "fixture_certainty": fixture_certainty,
        "odds_completeness": odds_completeness,
        "bookmaker_quality": bookmaker_quality,
        "team_rating_availability": clamp(team_rating_score, 0.0, 1.0),
        "context_availability": clamp(context_score, 0.0, 1.0),
        "lineup_availability": clamp(lineup_score, 0.0, 1.0),
    }
    score = (
        0.20 * factors["fixture_certainty"]
        + 0.25 * factors["odds_completeness"]
        + 0.15 * factors["bookmaker_quality"]
        + 0.20 * factors["team_rating_availability"]
        + 0.10 * factors["context_availability"]
        + 0.10 * factors["lineup_availability"]
    )
    score = clamp(score, 0.0, 1.0)
    notes: list[str] = []
    if market.required_bookmaker and not sample:
        if market.selected_bookmaker:
            notes.append(f"赔率来源已限定为指定庄家 {market.selected_bookmaker} 的全场盘口。")
        else:
            notes.append(f"未取得指定庄家 {market.required_bookmaker} 的全场盘口，模拟舱不得产生信号。")
    if max_score is not None and score > max_score:
        score = clamp(max_score, 0.0, 1.0)
        notes.append("未满足可靠球队强度或近期有效比赛准入条件，模拟舱降级为观望。")
    grade, grade_label = _grade(score)
    notes.extend(_quality_notes(markets, score, min_quality))
    notes.extend(market.warnings)
    if extra_notes:
        notes.extend(extra_notes)
    if sample:
        grade = "DEMO"
        grade_label = "演示"
        notes.insert(0, "本地示例只用于界面和流程验证，数据质量评分不代表真实比赛可用性。")
    return DataQualityReport(
        score=score,
        grade=grade,
        grade_label=grade_label,
        min_quality=min_quality,
        factors=factors,
        markets=markets,
        notes=notes,
    )


def market_availability(market: MarketSnapshot) -> list[MarketAvailability]:
    return [
        _match_winner_status(market),
        _total_status(market),
        _handicap_status(market),
    ]


def apply_quality_gate(
    recommendations: list[BetRecommendation],
    portfolio: PaperPortfolio,
    quality: DataQualityReport,
    enforce: bool,
) -> tuple[list[BetRecommendation], PaperPortfolio]:
    if not enforce or quality.score >= quality.min_quality:
        return recommendations, portfolio

    adjusted: list[BetRecommendation] = []
    for item in recommendations:
        if item.action != "BUY":
            adjusted.append(item)
            continue
        adjusted.append(
            replace(
                item,
                action="WATCH",
                stake=0.0,
                reason=(
                    f"{item.reason} 数据质量评分 {quality.score * 100:.1f}% "
                    f"低于门槛 {quality.min_quality * 100:.1f}%，模拟舱降级观望。"
                ),
            )
        )

    active = [item for item in adjusted if item.action in {"BUY", "PAPER_BUY"}]
    total_stake = portfolio.unit_stake * len(active)
    expected_profit = sum(
        portfolio.unit_stake * (item.expected_value_per_unit or 0.0)
        for item in active
        if item.expected_value_per_unit is not None
    )
    gated_portfolio = PaperPortfolio(
        bankroll=portfolio.bankroll,
        unit_stake=portfolio.unit_stake,
        active_bets=len(active),
        total_stake=total_stake,
        bankroll_after_stakes=portfolio.bankroll - total_stake,
        expected_profit=expected_profit,
        expected_bankroll=portfolio.bankroll + expected_profit,
    )
    return adjusted, gated_portfolio


def _match_winner_status(market: MarketSnapshot) -> MarketAvailability:
    required = {"home_win", "draw", "away_win"}
    present = {key for key in required if market.match_winner.get(key, 0.0) > 1.0}
    if present == required:
        return MarketAvailability("match_winner", "胜平负", "available", "可用", 1.0, f"{_source_text(market)}全场 1X2 欧赔完整。")
    if present:
        missing = "、".join(_match_winner_label(key) for key in sorted(required - present))
        return MarketAvailability("match_winner", "胜平负", "incomplete", "不完整", 0.45, f"缺少 {missing} 赔率。")
    if any(note.startswith("胜平负") for note in market.warnings):
        return MarketAvailability("match_winner", "胜平负", "incomplete", "不完整", 0.35, "1X2 赔率缺少同公司完整组合，已排除。")
    return MarketAvailability("match_winner", "胜平负", "missing", "缺失", 0.0, "没有可用的 1X2 欧赔。")


def _total_status(market: MarketSnapshot) -> MarketAvailability:
    line = market.best_total_line()
    if line:
        return MarketAvailability("total_goals", "大小球", "available", "可用", 1.0, f"{_source_text(market)}全场大小球盘口完整。", line[0])
    if market.totals:
        return MarketAvailability("total_goals", "大小球", "incomplete", "不完整", 0.35, "有大小球盘口，但缺少同公司成对赔率或水位异常。")
    if any(note.startswith("大小球") for note in market.warnings):
        return MarketAvailability("total_goals", "大小球", "incomplete", "不完整", 0.35, "大小球盘口已因水位异常或缺少成对赔率被排除。")
    return MarketAvailability("total_goals", "大小球", "missing", "缺失", 0.0, "没有可用的大小球赔率。")


def _handicap_status(market: MarketSnapshot) -> MarketAvailability:
    line = market.best_handicap_line()
    if line:
        return MarketAvailability("handicap", "让球", "available", "可用", 1.0, f"{_source_text(market)}全场让球盘口完整。", line[0])
    if market.handicaps:
        return MarketAvailability("handicap", "让球", "incomplete", "不完整", 0.35, "有让球盘口，但缺少同公司成对赔率或水位异常。")
    if any(note.startswith("让球") for note in market.warnings):
        return MarketAvailability("handicap", "让球", "incomplete", "不完整", 0.35, "让球盘口已因水位异常或缺少成对赔率被排除。")
    return MarketAvailability("handicap", "让球", "missing", "缺失", 0.0, "没有可用的让球赔率。")


def _quality_notes(markets: list[MarketAvailability], score: float, min_quality: float) -> list[str]:
    notes = [f"{item.label}市场：{item.status_label}，{item.details}" for item in markets]
    if score < min_quality:
        notes.append("数据质量低于研究试算 EV 门槛，真实 API 模式只允许观望。")
    return notes


def _grade(score: float) -> tuple[str, str]:
    if score >= 0.80:
        return "HIGH", "高"
    if score >= 0.60:
        return "MEDIUM", "中"
    if score >= 0.40:
        return "LOW", "低"
    return "VERY_LOW", "很低"


def _match_winner_label(key: str) -> str:
    return {"away_win": "客胜", "draw": "平局", "home_win": "主胜"}.get(key, key)


def _source_text(market: MarketSnapshot) -> str:
    return f"{market.selected_bookmaker} " if market.selected_bookmaker else ""
