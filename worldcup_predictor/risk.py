from __future__ import annotations

import re
from typing import Any

from .models import clamp


YOUTH_PATTERN = re.compile(r"\b(?:u|under)[\s-]?(?:19|20|21|23)\b", re.IGNORECASE)


def build_match_risk_context(
    *,
    home_team: str = "",
    away_team: str = "",
    league_name: str = "",
    league_country: str = "",
    collection_mode: str = "",
    deep_stats_matches: int = 0,
    home_recent_matches: int = 0,
    away_recent_matches: int = 0,
    required_recent_matches: int = 5,
) -> dict[str, Any]:
    text = " ".join([home_team, away_team, league_name, league_country])
    text_lower = text.casefold()
    youth_flag = bool(YOUTH_PATTERN.search(text))
    friendly_flag = any(token in text_lower for token in ("friendly", "friendlies", "友谊"))
    missing_technical_stats = int(deep_stats_matches or 0) <= 0
    missing_xg = missing_technical_stats
    weak_recent_sample = min(int(home_recent_matches or 0), int(away_recent_matches or 0)) < int(required_recent_matches or 0)

    flags: list[str] = []
    reasons: list[str] = []
    if youth_flag:
        flags.append("U21_RISK_DISCOUNT")
        reasons.append("青年队赛事历史样本稳定性较弱")
    if friendly_flag:
        flags.append("FRIENDLY_RISK_DISCOUNT")
        reasons.append("友谊赛阵容与战意不稳定")
    if missing_xg:
        flags.append("MISSING_XG")
        reasons.append("缺少 xG 数据")
    if missing_technical_stats:
        flags.append("MISSING_TECHNICAL_STATS")
        reasons.append("缺少可用技术统计")
    if weak_recent_sample:
        flags.append("WEAK_RECENT_SAMPLE")
        reasons.append("双方近期有效样本不足")

    lambda_shrink_factor = 0.90
    if missing_technical_stats:
        lambda_shrink_factor = min(lambda_shrink_factor, 0.80)
    if youth_flag:
        lambda_shrink_factor = min(lambda_shrink_factor, 0.70)
    if friendly_flag:
        lambda_shrink_factor = min(lambda_shrink_factor, 0.70)
    if weak_recent_sample:
        lambda_shrink_factor = min(lambda_shrink_factor, 0.75)
    if youth_flag and friendly_flag and missing_technical_stats:
        lambda_shrink_factor = min(lambda_shrink_factor, 0.55)
    elif (youth_flag or friendly_flag) and missing_technical_stats:
        lambda_shrink_factor = min(lambda_shrink_factor, 0.60)

    if not flags:
        lambda_shrink_factor = 0.95
        reasons.append("成熟赛事且关键样本覆盖相对完整")

    flags.append("FORMAL_EV_DISABLED")
    return {
        "leagueName": league_name,
        "leagueCountry": league_country,
        "collectionMode": collection_mode,
        "deepStatsMatches": int(deep_stats_matches or 0),
        "homeRecentMatches": int(home_recent_matches or 0),
        "awayRecentMatches": int(away_recent_matches or 0),
        "requiredRecentMatches": int(required_recent_matches or 0),
        "youthFlag": youth_flag,
        "friendlyFlag": friendly_flag,
        "missingXg": missing_xg,
        "missingTechnicalStats": missing_technical_stats,
        "weakRecentSample": weak_recent_sample,
        "lambdaShrinkFactor": clamp(lambda_shrink_factor, 0.35, 1.0),
        "lambdaShrinkReasons": reasons,
        "riskFlags": _unique(flags),
    }


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    for value in values:
        if value not in output:
            output.append(value)
    return output
