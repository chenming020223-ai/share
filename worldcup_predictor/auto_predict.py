from __future__ import annotations

import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field, replace
from datetime import datetime, timedelta, timezone
from typing import Any

from .api_football import ApiFootballClient, ApiTeam
from .betting import (
    DEFAULT_MIN_EDGE,
    SIGNAL_STATUS_SUSPENDED,
    BetRecommendation,
    PaperPortfolio,
    build_recommendations,
    recalculate_portfolio,
)
from .localization import (
    to_api_name,
    to_beijing_time,
    translate_league_display,
    translate_team_display,
)
from .market import DEFAULT_BOOKMAKER_PRIORITY, MarketSnapshot, parse_api_football_odds
from .model_governance import ModelGovernance, api_model_governance, apply_formal_ev_gate
from .models import Fixture, ModelConfig, PredictionResult, TeamProfile, as_float, clamp
from .predictor import predict_match
from .poisson import score_matrix
from .risk import build_match_risk_context
from .score_calibration import build_score_distribution_calibration_status
from .settings import env_int, env_list, env_str
from .team_strength import blend_profile_with_prior, opponent_strength_elo, team_strength_prior

RECENT_MATCH_FETCH_COUNT = 10
MIN_VALID_RECENT_MATCHES = 5
COLLECTION_MODE_FAST = "fast"
COLLECTION_MODE_DEEP = "deep"
COLLECTION_MODE_BATCH = "batch"
SUPPORTED_COLLECTION_MODES = {COLLECTION_MODE_FAST, COLLECTION_MODE_DEEP, COLLECTION_MODE_BATCH}


@dataclass(frozen=True)
class AutoPrediction:
    fixture_id: int
    league_id: int | None
    league_name: str
    league_country: str
    season: int | None
    kickoff: str
    venue: str
    home_api_team: ApiTeam
    away_api_team: ApiTeam
    result: PredictionResult
    market: MarketSnapshot
    recommendations: list[BetRecommendation]
    portfolio: PaperPortfolio
    governance: ModelGovernance
    team_stats_available: bool = False
    recent_form_available: bool = False
    home_recent_matches: int = 0
    away_recent_matches: int = 0
    h2h_available: bool = False
    collection_mode: str = COLLECTION_MODE_DEEP
    deep_stats_available: bool = False
    deep_stats_matches: int = 0
    api_logical_requests: int = 0
    api_http_attempts: int = 0
    api_cache_hits: int = 0
    api_cache_misses: int = 0
    data_notes: list[str] = field(default_factory=list)
    raw_snapshot: dict[str, Any] = field(default_factory=dict)
    risk_context: dict[str, Any] = field(default_factory=dict)
    historical_mode: bool = False
    historical_as_of: str | None = None


def run_auto_prediction(
    home_name: str,
    away_name: str,
    api_key: str | None = None,
    fixture_id: int | None = None,
    market_weight: float = 0.45,
    bankroll: float = 1000.0,
    unit_stake: float | None = None,
    min_edge: float = DEFAULT_MIN_EDGE,
    force_picks: bool = False,
    collection_mode: str | None = None,
    client: ApiFootballClient | None = None,
    bookmaker_priority: list[str] | tuple[str, ...] | str | None = None,
    historical_as_of: str | datetime | None = None,
    score_distribution_calibration: dict[str, Any] | None = None,
    starting_bankroll: float = 1000.0,
    realized_pnl: float | None = None,
    reserved_stake: float = 0.0,
) -> AutoPrediction:
    active_mode = _normalize_collection_mode(collection_mode)
    source = client or ApiFootballClient(api_key=api_key)
    historical_mode = historical_as_of is not None
    search_home_name = to_api_name("team", home_name)
    search_away_name = to_api_name("team", away_name)
    if fixture_id:
        fixture_row = source.fixture_by_id(fixture_id)
        requested_home = ApiTeam(id=0, name=search_home_name or home_name)
        requested_away = ApiTeam(id=0, name=search_away_name or away_name)
    else:
        requested_home = source.resolve_team(search_home_name)
        requested_away = source.resolve_team(search_away_name)
        fixture_row = source.next_head_to_head(requested_home.id, requested_away.id)

    fixture_meta = fixture_row.get("fixture") or {}
    historical_cutoff: datetime | None = None
    if historical_mode:
        historical_cutoff = _historical_cutoff_from_fixture(fixture_meta, historical_as_of)
    else:
        _validate_pre_match_fixture(fixture_meta)
    league_meta = fixture_row.get("league") or {}
    teams_meta = fixture_row.get("teams") or {}
    home_meta = teams_meta.get("home") or {}
    away_meta = teams_meta.get("away") or {}

    actual_home = ApiTeam(
        id=int(home_meta.get("id") or requested_home.id),
        name=str(home_meta.get("name") or requested_home.name),
        country=requested_home.country,
        national=requested_home.national,
    )
    actual_away = ApiTeam(
        id=int(away_meta.get("id") or requested_away.id),
        name=str(away_meta.get("name") or requested_away.name),
        country=requested_away.country,
        national=requested_away.national,
    )

    fixture_api_id = int(fixture_meta.get("id") or fixture_id or 0)
    league_id = _optional_int(league_meta.get("id"))
    season = _optional_int(league_meta.get("season"))
    notes: list[str] = []

    if historical_mode and historical_cutoff:
        notes.append(
            "历史赛前模拟模式：本次只允许使用 "
            f"{historical_cutoff.astimezone(timezone.utc).isoformat()} 前已存在的数据；"
            "赛果只可用于后续结算，不进入正式赛前快照和 pfinal 验收。"
        )
    odds_rows = _safe_call(lambda: source.odds(fixture_api_id), notes, "赔率数据不可用")
    if historical_mode and historical_cutoff:
        original_odds_count = len(odds_rows or [])
        odds_rows = _odds_rows_before_cutoff(odds_rows or [], historical_cutoff)
        if original_odds_count and not odds_rows:
            notes.append("历史赛前模拟：API 返回的盘口没有可审计的赛前更新时间，已排除，盘口按缺失处理。")
        elif original_odds_count != len(odds_rows or []):
            notes.append(f"历史赛前模拟：已排除 {original_odds_count - len(odds_rows or [])} 条开赛后或无时点盘口。")
    priority = normalize_active_bookmaker_priority(bookmaker_priority)
    market = parse_api_football_odds(odds_rows or [], required_bookmaker=None, bookmaker_priority=priority)

    if historical_mode and historical_cutoff:
        home_recent_rows = _team_recent_rows_before_cutoff(source, actual_home.id, historical_cutoff, notes, "主队")
        away_recent_rows = _team_recent_rows_before_cutoff(source, actual_away.id, historical_cutoff, notes, "客队")
    else:
        home_recent_rows = _safe_call(
            lambda: source.team_last_fixtures(actual_home.id, RECENT_MATCH_FETCH_COUNT),
            notes,
            "主队近期比赛不可用",
        ) or []
        away_recent_rows = _safe_call(
            lambda: source.team_last_fixtures(actual_away.id, RECENT_MATCH_FETCH_COUNT),
            notes,
            "客队近期比赛不可用",
        ) or []
    home_recent = _valid_recent_matches(home_recent_rows, actual_home.id)
    away_recent = _valid_recent_matches(away_recent_rows, actual_away.id)
    deep_stats_limit = _deep_stats_limit(active_mode)
    deep_stats_matches = 0
    if active_mode in {COLLECTION_MODE_DEEP, COLLECTION_MODE_BATCH}:
        home_recent, home_deep_count = _enrich_recent_matches_with_deep_stats(
            source,
            home_recent,
            actual_home.id,
            notes,
            "主队",
            limit=deep_stats_limit,
        )
        away_recent, away_deep_count = _enrich_recent_matches_with_deep_stats(
            source,
            away_recent,
            actual_away.id,
            notes,
            "客队",
            limit=deep_stats_limit,
        )
        deep_stats_matches = home_deep_count + away_deep_count
        notes.append(
            f"数据抓取模式：{_collection_mode_label(active_mode)}；"
            f"已尝试补充双方近期比赛技术统计与事件，成功覆盖 {deep_stats_matches} 场。"
        )
    else:
        notes.append("数据抓取模式：快速模式；仅抓比赛、赔率、双方近期赛果、赛季统计和交锋。")
    recent_form_available = (
        len(home_recent) >= MIN_VALID_RECENT_MATCHES
        and len(away_recent) >= MIN_VALID_RECENT_MATCHES
    )
    notes.append(
        f"近期比赛有效覆盖：{translate_team_display(actual_home.name, '主队')} {len(home_recent)}/{RECENT_MATCH_FETCH_COUNT} 场，"
        f"{translate_team_display(actual_away.name, '客队')} {len(away_recent)}/{RECENT_MATCH_FETCH_COUNT} 场；"
        f"研究评估最低要求为双方各 {MIN_VALID_RECENT_MATCHES} 场。"
    )

    home_stats = None
    away_stats = None
    if historical_mode:
        notes.append("历史赛前模拟：跳过 API 赛季统计，避免使用赛后汇总数据穿越。")
    elif league_id and season:
        home_stats = _safe_call(
            lambda: source.team_statistics(league_id, season, actual_home.id),
            notes,
            "主队赛季统计不可用",
        )
        away_stats = _safe_call(
            lambda: source.team_statistics(league_id, season, actual_away.id),
            notes,
            "客队赛季统计不可用",
        )
    else:
        notes.append("赛事缺少 league/season，无法拉取球队赛季统计。")

    h2h_limit = 30 if historical_mode else 10
    h2h_rows = _safe_call(
        lambda: _last_h2h(source, actual_home.id, actual_away.id, h2h_limit),
        notes,
        "历史交锋不可用",
    ) or []
    if historical_mode and historical_cutoff:
        before_count = len(h2h_rows)
        h2h_rows = _rows_before_cutoff(h2h_rows, historical_cutoff, limit=10)
        if before_count != len(h2h_rows):
            notes.append(f"历史赛前模拟：历史交锋已按开赛前截断，排除 {before_count - len(h2h_rows)} 场未来交锋。")

    prior_recent_weight = _prior_recent_weight(active_mode, league_meta)
    home_profile = _profile_from_api(actual_home, home_stats, home_recent, prior_recent_weight=prior_recent_weight)
    away_profile = _profile_from_api(actual_away, away_stats, away_recent, prior_recent_weight=prior_recent_weight)
    prior_notes = _team_prior_notes(actual_home.name, actual_away.name, prior_recent_weight)
    if prior_notes:
        notes.extend(prior_notes)
    neutral_site = _neutral_site_for_fixture(league_meta)
    notes.append("世界杯正赛按中立场建模。" if neutral_site else "非世界杯正赛按实际主客场建模。")
    fixture = _fixture_from_api(
        fixture_api_id,
        actual_home,
        actual_away,
        market,
        neutral_site=neutral_site,
        h2h_edge_home=_h2h_edge(h2h_rows, actual_home.id),
        notes="; ".join(notes),
    )

    risk_context = build_match_risk_context(
        home_team=actual_home.name,
        away_team=actual_away.name,
        league_name=str(league_meta.get("name") or ""),
        league_country=str(league_meta.get("country") or ""),
        collection_mode=active_mode,
        deep_stats_matches=deep_stats_matches,
        home_recent_matches=len(home_recent),
        away_recent_matches=len(away_recent),
        required_recent_matches=MIN_VALID_RECENT_MATCHES,
    )
    score_distribution_calibration = score_distribution_calibration or build_score_distribution_calibration_status()
    risk_context = dict(risk_context)
    risk_context["scoreDistributionCalibration"] = score_distribution_calibration
    score_markets = score_distribution_calibration.get("markets") or {}
    total_market = score_markets.get("OU") or {}
    handicap_market = score_markets.get("AH") or {}
    notes.append(
        "比分分布独立校准："
        f"总样本 {score_distribution_calibration.get('sampleCount', 0)} 条；"
        f"大小球 {total_market.get('statusLabel') or '-'}，"
        f"让球 {handicap_market.get('statusLabel') or '-'}；"
        "按共享版口径输出 paper_EV 纸上模拟层，formal_EV 仍需 pfinal 审批。"
    )
    if risk_context.get("lambdaShrinkFactor", 1.0) < 1.0:
        notes.append(
            "λ 收缩已启用："
            f"factor={risk_context['lambdaShrinkFactor']:.2f}；"
            + "、".join(str(item) for item in risk_context.get("lambdaShrinkReasons", []))
        )
    config = ModelConfig(
        market_weight=clamp(market_weight, 0.0, 0.95),
        lambda_shrink_factor=as_float(risk_context.get("lambdaShrinkFactor"), 1.0),
        lambda_shrink_reasons=tuple(str(item) for item in risk_context.get("lambdaShrinkReasons", [])),
    )
    result = predict_match(home_profile, away_profile, fixture, config)
    matrix = score_matrix(result.expected_goals_home, result.expected_goals_away, config.max_goals)
    recommendations, portfolio = build_recommendations(
        result,
        matrix,
        market,
        bankroll=bankroll,
        unit_stake=unit_stake,
        min_edge=min_edge,
        force_picks=force_picks,
        risk_context=risk_context,
        starting_bankroll=starting_bankroll,
        realized_pnl=realized_pnl,
        reserved_stake=reserved_stake,
    )
    team_stats_available = recent_form_available
    if not recent_form_available:
        notes.append("双方近期有效比赛不足最低准入要求，模拟舱降级为观望。")
        recommendations, portfolio = _downgrade_buy_for_missing_strength(recommendations, portfolio)
    governance = api_model_governance()
    recommendations, portfolio = apply_formal_ev_gate(
        recommendations,
        portfolio,
        governance,
        enforce=True,
    )

    venue = fixture_meta.get("venue") or {}
    venue_text = ", ".join(part for part in [str(venue.get("name") or ""), str(venue.get("city") or "")] if part)
    snapshot_fixture_row = _fixture_without_result(fixture_row) if historical_mode else fixture_row
    return AutoPrediction(
        fixture_id=fixture_api_id,
        league_id=league_id,
        league_name=str(league_meta.get("name") or ""),
        league_country=str(league_meta.get("country") or ""),
        season=season,
        kickoff=str(fixture_meta.get("date") or ""),
        venue=venue_text,
        home_api_team=actual_home,
        away_api_team=actual_away,
        result=result,
        market=market,
        recommendations=recommendations,
        portfolio=portfolio,
        governance=governance,
        team_stats_available=team_stats_available,
        recent_form_available=recent_form_available,
        home_recent_matches=len(home_recent),
        away_recent_matches=len(away_recent),
        h2h_available=bool(h2h_rows),
        collection_mode=active_mode,
        deep_stats_available=deep_stats_matches > 0,
        deep_stats_matches=deep_stats_matches,
        api_logical_requests=int(getattr(source, "logical_requests", 0) or 0),
        api_http_attempts=int(getattr(source, "http_attempts", 0) or 0),
        api_cache_hits=int(getattr(source, "cache_hits", 0) or 0),
        api_cache_misses=int(getattr(source, "cache_misses", 0) or 0),
        data_notes=notes,
        raw_snapshot={
            "collection_mode": active_mode,
            "api_requests": {
                "logical": int(getattr(source, "logical_requests", 0) or 0),
                "http_attempts": int(getattr(source, "http_attempts", 0) or 0),
                "cache_hits": int(getattr(source, "cache_hits", 0) or 0),
                "cache_misses": int(getattr(source, "cache_misses", 0) or 0),
            },
            "fixture": snapshot_fixture_row,
            "odds": odds_rows or [],
            "team_stats": {
                "home": home_stats,
                "away": away_stats,
            },
            "recent_form": {
                "home": home_recent,
                "away": away_recent,
                "required_matches": MIN_VALID_RECENT_MATCHES,
                "requested_matches": RECENT_MATCH_FETCH_COUNT,
                "deep_stats_matches": deep_stats_matches,
            },
            "h2h": h2h_rows,
            "notes": list(notes),
            "risk_context": risk_context,
            "historical_mode": historical_mode,
            "historical_as_of": historical_cutoff.isoformat() if historical_cutoff else None,
            "leakage_policy": (
                "fixture, recent_form, h2h and odds are cutoff before kickoff/as_of; "
                "team season aggregate stats are disabled in historical mode."
                if historical_mode
                else "normal pre-match snapshot"
            ),
        },
        risk_context=risk_context,
        historical_mode=historical_mode,
        historical_as_of=historical_cutoff.isoformat() if historical_cutoff else None,
    )


def normalize_active_bookmaker_priority(value: list[str] | tuple[str, ...] | str | None = None) -> list[str]:
    if value:
        if isinstance(value, str):
            configured = [item.strip() for item in value.replace(";", ",").split(",") if item.strip()]
        else:
            configured = [str(item).strip() for item in value if str(item).strip()]
        return configured or list(DEFAULT_BOOKMAKER_PRIORITY)
    configured = env_list("WORLDCUP_BOOKMAKER_PRIORITY", DEFAULT_BOOKMAKER_PRIORITY)
    return configured or list(DEFAULT_BOOKMAKER_PRIORITY)


def _profile_from_api(
    team: ApiTeam,
    stats: dict[str, Any] | None,
    recent_matches: list[dict[str, Any]] | None = None,
    *,
    prior_recent_weight: float = 0.45,
) -> TeamProfile:
    if recent_matches and len(recent_matches) >= MIN_VALID_RECENT_MATCHES:
        played, gf_avg, ga_avg, points_per_game = _weighted_recent_summary(recent_matches)
        return _build_profile(
            team,
            played,
            gf_avg,
            ga_avg,
            points_per_game,
            prior_recent_weight=prior_recent_weight,
        )

    if not stats:
        return _profile_from_prior_or_default(team)

    fixtures = stats.get("fixtures") or {}
    played = as_float((fixtures.get("played") or {}).get("total"), 0.0)
    wins = as_float((fixtures.get("wins") or {}).get("total"), 0.0)
    draws = as_float((fixtures.get("draws") or {}).get("total"), 0.0)

    goals = stats.get("goals") or {}
    for_goals = goals.get("for") or {}
    against_goals = goals.get("against") or {}
    gf_avg = as_float((for_goals.get("average") or {}).get("total"), 1.25)
    ga_avg = as_float((against_goals.get("average") or {}).get("total"), 1.25)

    points_per_game = ((wins * 3.0) + draws) / played if played > 0 else 1.35
    return _build_profile(
        team,
        played,
        gf_avg,
        ga_avg,
        points_per_game,
        prior_recent_weight=min(prior_recent_weight, 0.35),
    )


def _build_profile(
    team: ApiTeam,
    played: float,
    gf_avg: float,
    ga_avg: float,
    points_per_game: float,
    *,
    prior_recent_weight: float = 0.45,
) -> TeamProfile:
    points_per_game = clamp(points_per_game, 0.0, 3.0)
    gf_avg = clamp(gf_avg, 0.0, 5.0)
    ga_avg = clamp(ga_avg, 0.0, 5.0)
    elo = 1450.0 + points_per_game * 110.0
    attack = clamp(0.55 + gf_avg / 1.8, 0.65, 1.6)
    defense = clamp(1.55 - ga_avg / 2.2, 0.65, 1.55)
    depth = clamp(0.9 + min(played, 20.0) / 100.0, 0.9, 1.1)

    recent_profile = TeamProfile(
        name=team.name,
        elo=elo,
        fifa_rank=80.0,
        attack_rating=attack,
        defense_rating=defense,
        squad_depth=depth,
        coach_rating=1.0,
    )
    return blend_profile_with_prior(recent_profile, team_strength_prior(team.name), recent_weight=prior_recent_weight)


def _profile_from_prior_or_default(team: ApiTeam) -> TeamProfile:
    profile = TeamProfile(name=team.name)
    return blend_profile_with_prior(profile, team_strength_prior(team.name), recent_weight=0.0)


def _weighted_recent_summary(recent_matches: list[dict[str, Any]]) -> tuple[float, float, float, float]:
    weighted_gf = 0.0
    weighted_ga = 0.0
    weighted_points = 0.0
    total_weight = 0.0
    for index, item in enumerate(recent_matches):
        recency_weight = 0.92**index
        opponent_name = str(item.get("opponent") or "")
        opp_elo = as_float(item.get("opponent_strength_elo"), opponent_strength_elo(opponent_name))
        attack_context = clamp(opp_elo / 1500.0, 0.65, 1.30)
        defense_context = clamp(1500.0 / max(opp_elo, 1.0), 0.70, 1.45)
        points_context = clamp(opp_elo / 1500.0, 0.70, 1.25)
        goals_for = as_float(item.get("goals_for"), 0.0)
        goals_against = as_float(item.get("goals_against"), 0.0)
        points = as_float(item.get("points"), 0.0)
        weighted_gf += goals_for * attack_context * recency_weight
        weighted_ga += goals_against * defense_context * recency_weight
        weighted_points += points * points_context * recency_weight
        total_weight += recency_weight
    if total_weight <= 0:
        return 0.0, 1.25, 1.25, 1.35
    played = float(len(recent_matches))
    gf_avg = weighted_gf / total_weight
    ga_avg = weighted_ga / total_weight
    points_per_game = weighted_points / total_weight
    return played, gf_avg, ga_avg, clamp(points_per_game, 0.0, 3.0)


def _prior_recent_weight(active_mode: str, league_meta: dict[str, Any]) -> float:
    league_name = str(league_meta.get("name") or "").casefold()
    if "friendly" in league_name or "friendlies" in league_name:
        return 0.15
    if "u21" in league_name or "u20" in league_name or "u23" in league_name:
        return 0.25
    if active_mode == COLLECTION_MODE_FAST:
        return 0.35
    return 0.45


def _team_prior_notes(home_name: str, away_name: str, recent_weight: float) -> list[str]:
    notes: list[str] = []
    for role, name in (("主队", home_name), ("客队", away_name)):
        prior = team_strength_prior(name)
        if not prior:
            continue
        notes.append(
            f"{role}应用球队强度先验：{prior.canonical_name}，Elo {prior.elo:.0f}，"
            f"近期样本权重 {recent_weight:.0%}。"
        )
    return notes


def _fixture_from_api(
    fixture_id: int,
    home: ApiTeam,
    away: ApiTeam,
    market: MarketSnapshot,
    neutral_site: bool,
    h2h_edge_home: float,
    notes: str,
) -> Fixture:
    return Fixture(
        match_id=str(fixture_id),
        home_team=home.name,
        away_team=away.name,
        neutral_site=neutral_site,
        h2h_edge_home=h2h_edge_home,
        rivalry_intensity=abs(h2h_edge_home) * 0.3,
        odds_home=market.match_winner.get("home_win", 0.0),
        odds_draw=market.match_winner.get("draw", 0.0),
        odds_away=market.match_winner.get("away_win", 0.0),
        notes=notes,
    )


def _valid_recent_matches(rows: list[dict[str, Any]], team_id: int) -> list[dict[str, Any]]:
    valid: list[dict[str, Any]] = []
    for row in rows[:RECENT_MATCH_FETCH_COUNT]:
        fixture = row.get("fixture") or {}
        status = str((fixture.get("status") or {}).get("short") or "")
        if status not in {"FT", "AET", "PEN"}:
            continue
        teams = row.get("teams") or {}
        home_id = _optional_int((teams.get("home") or {}).get("id"))
        away_id = _optional_int((teams.get("away") or {}).get("id"))
        if team_id not in {home_id, away_id}:
            continue
        fulltime = (row.get("score") or {}).get("fulltime") or {}
        home_goals = _optional_int(fulltime.get("home"))
        away_goals = _optional_int(fulltime.get("away"))
        if (home_goals is None or away_goals is None) and status == "FT":
            goals = row.get("goals") or {}
            home_goals = _optional_int(goals.get("home"))
            away_goals = _optional_int(goals.get("away"))
        if home_goals is None or away_goals is None:
            continue
        is_home = home_id == team_id
        goals_for = home_goals if is_home else away_goals
        goals_against = away_goals if is_home else home_goals
        points = 3 if goals_for > goals_against else 1 if goals_for == goals_against else 0
        opponent = teams.get("away") if is_home else teams.get("home")
        opponent_name = str((opponent or {}).get("name") or "")
        opponent_prior = team_strength_prior(opponent_name)
        league = row.get("league") or {}
        league_name = str(league.get("name") or "")
        league_country = str(league.get("country") or "")
        valid.append(
            {
                "fixture_id": fixture.get("id"),
                "date": fixture.get("date"),
                "date_beijing": to_beijing_time(fixture.get("date")),
                "status": status,
                "goals_for": goals_for,
                "goals_against": goals_against,
                "points": points,
                "venue": "home" if is_home else "away",
                "opponent": opponent_name,
                "opponent_zh": translate_team_display(opponent_name, "对手"),
                "opponent_strength_elo": opponent_prior.elo if opponent_prior else 1500.0,
                "opponent_strength_source": opponent_prior.source if opponent_prior else "unknown_default_1500",
                "league": league_name,
                "league_zh": translate_league_display(league_name, league_country),
            }
        )
    return valid


def _normalize_collection_mode(value: str | None) -> str:
    configured = str(value or env_str("WORLDCUP_COLLECTION_MODE", COLLECTION_MODE_DEEP)).strip().casefold()
    if configured in {"quick", "light"}:
        configured = COLLECTION_MODE_FAST
    if configured not in SUPPORTED_COLLECTION_MODES:
        return COLLECTION_MODE_DEEP
    return configured


def _collection_mode_label(value: str) -> str:
    return {
        COLLECTION_MODE_FAST: "快速模式",
        COLLECTION_MODE_DEEP: "深度模式",
        COLLECTION_MODE_BATCH: "批量建库模式",
    }.get(value, value)


def _deep_stats_limit(collection_mode: str) -> int:
    default_limit = RECENT_MATCH_FETCH_COUNT
    if collection_mode == COLLECTION_MODE_BATCH:
        default_limit = env_int("WORLDCUP_BATCH_DEEP_MATCH_LIMIT", RECENT_MATCH_FETCH_COUNT)
    return max(0, min(RECENT_MATCH_FETCH_COUNT, env_int("WORLDCUP_DEEP_MATCH_LIMIT", default_limit)))


def _enrich_recent_matches_with_deep_stats(
    client: ApiFootballClient,
    rows: list[dict[str, Any]],
    team_id: int,
    notes: list[str],
    role_label: str,
    *,
    limit: int,
) -> tuple[list[dict[str, Any]], int]:
    enriched: list[dict[str, Any] | None] = [None] * len(rows)
    successful = 0
    jobs: list[tuple[int, dict[str, Any], int]] = []
    for index, row in enumerate(rows):
        fixture_id = _optional_int(row.get("fixture_id"))
        if index >= limit or fixture_id is None:
            enriched[index] = row
        else:
            jobs.append((index, row, fixture_id))

    if not jobs:
        return [item for item in enriched if item is not None], 0

    workers = max(1, min(len(jobs), env_int("WORLDCUP_DEEP_FETCH_WORKERS", 4)))
    if workers == 1:
        for index, row, fixture_id in jobs:
            result, job_notes = _deep_stats_for_recent_match(client, row, team_id, fixture_id, role_label)
            notes.extend(job_notes)
            successful += 1 if result.get("technical_available") else 0
            enriched[index] = result
        return [item for item in enriched if item is not None], successful

    with ThreadPoolExecutor(max_workers=workers) as executor:
        future_map = {
            executor.submit(_deep_stats_for_recent_match, client, row, team_id, fixture_id, role_label): index
            for index, row, fixture_id in jobs
        }
        for future in as_completed(future_map):
            index = future_map[future]
            result, job_notes = future.result()
            notes.extend(job_notes)
            successful += 1 if result.get("technical_available") else 0
            enriched[index] = result

    return [item for item in enriched if item is not None], successful


def _deep_stats_for_recent_match(
    client: ApiFootballClient,
    row: dict[str, Any],
    team_id: int,
    fixture_id: int,
    role_label: str,
) -> tuple[dict[str, Any], list[str]]:
    job_notes: list[str] = []
    statistics = _safe_call(
        lambda fixture_id=fixture_id: client.fixture_statistics(fixture_id),
        job_notes,
        f"{role_label}历史比赛 {fixture_id} 技术统计不可用",
    ) or []
    events = _safe_call(
        lambda fixture_id=fixture_id: client.fixture_events(fixture_id),
        job_notes,
        f"{role_label}历史比赛 {fixture_id} 事件数据不可用",
    ) or []
    details = _technical_detail_for_team(statistics, events, team_id)
    return {**row, **details}, job_notes


def _technical_detail_for_team(
    statistics_rows: list[dict[str, Any]],
    events: list[dict[str, Any]],
    team_id: int,
) -> dict[str, Any]:
    team_stats = _stats_for_team(statistics_rows, team_id)
    opponent_stats = _stats_for_opponent(statistics_rows, team_id)
    red_cards_for = _event_count(events, team_id, event_type="card", detail_contains="red")
    penalties_for = _event_count(events, team_id, event_type="goal", detail_contains="penalty")
    return {
        "xg": _stat_number(team_stats, ("expected goals", "xg", "expected_goals")),
        "opponent_xga": _stat_number(opponent_stats, ("expected goals", "xg", "expected_goals")),
        "shots": _stat_number(team_stats, ("total shots", "shots total", "shots")),
        "shots_on_target": _stat_number(team_stats, ("shots on goal", "shots on target")),
        "possession_pct": _stat_number(team_stats, ("ball possession", "possession")),
        "red_cards": red_cards_for,
        "penalties": penalties_for,
        "technical_available": bool(team_stats),
    }


def _stats_for_team(rows: list[dict[str, Any]], team_id: int) -> dict[str, Any]:
    for row in rows:
        team = row.get("team") or {}
        if _optional_int(team.get("id")) == team_id:
            return _stats_dict(row.get("statistics") or [])
    return {}


def _stats_for_opponent(rows: list[dict[str, Any]], team_id: int) -> dict[str, Any]:
    for row in rows:
        team = row.get("team") or {}
        if _optional_int(team.get("id")) != team_id:
            stats = _stats_dict(row.get("statistics") or [])
            if stats:
                return stats
    return {}


def _stats_dict(items: list[dict[str, Any]]) -> dict[str, Any]:
    stats: dict[str, Any] = {}
    for item in items:
        key = str(item.get("type") or "").strip().casefold()
        if key:
            stats[key] = item.get("value")
    return stats


def _stat_number(stats: dict[str, Any], names: tuple[str, ...]) -> float | None:
    for name in names:
        if name.casefold() not in stats:
            continue
        value = stats[name.casefold()]
        if value in {None, ""}:
            return None
        text = str(value).replace("%", "").strip()
        try:
            return float(text)
        except ValueError:
            return None
    return None


def _event_count(
    events: list[dict[str, Any]],
    team_id: int,
    *,
    event_type: str,
    detail_contains: str,
) -> int:
    count = 0
    for event in events:
        team = event.get("team") or {}
        if _optional_int(team.get("id")) != team_id:
            continue
        kind = str(event.get("type") or "").casefold()
        detail = str(event.get("detail") or "").casefold()
        if event_type in kind and detail_contains in detail:
            count += 1
    return count


def _neutral_site_for_fixture(league_meta: dict[str, Any]) -> bool:
    league_name = str(league_meta.get("name") or "").casefold()
    if "world cup" not in league_name:
        return False
    return "qualification" not in league_name and "qualifier" not in league_name


def _validate_pre_match_fixture(fixture_meta: dict[str, Any], now: datetime | None = None) -> None:
    status = str((fixture_meta.get("status") or {}).get("short") or "").upper()
    if status and status not in {"NS", "TBD", "PST"}:
        raise ValueError("只能为尚未开赛的比赛生成预测快照；该比赛状态不是赛前状态。")
    kickoff_text = str(fixture_meta.get("date") or "").strip()
    if not kickoff_text:
        raise ValueError("比赛缺少开赛时间，无法形成可审计的赛前预测快照。")
    try:
        kickoff = datetime.fromisoformat(kickoff_text.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("比赛开赛时间无法解析，不能形成赛前预测快照。") from exc
    if kickoff.tzinfo is None:
        kickoff = kickoff.replace(tzinfo=timezone.utc)
    reference_time = now or datetime.now(timezone.utc)
    if kickoff <= reference_time:
        raise ValueError("该比赛已超过开赛时间，不能作为赛前预测或校准样本。")


def _historical_cutoff_from_fixture(
    fixture_meta: dict[str, Any],
    historical_as_of: str | datetime | None,
) -> datetime:
    kickoff = _parse_api_datetime(str(fixture_meta.get("date") or ""))
    if kickoff is None:
        raise ValueError("历史赛前模拟需要比赛开赛时间，当前 fixture 缺少可解析时间。")

    if isinstance(historical_as_of, datetime):
        cutoff = historical_as_of
    else:
        text = str(historical_as_of or "").strip()
        cutoff = _parse_api_datetime(text) if text else None

    if cutoff is None:
        cutoff = kickoff - timedelta(minutes=1)
    if cutoff.tzinfo is None:
        cutoff = cutoff.replace(tzinfo=timezone.utc)
    if cutoff >= kickoff:
        raise ValueError("历史赛前模拟的截止时间必须早于比赛开赛时间，避免赛后信息穿越。")
    return cutoff


def _team_recent_rows_before_cutoff(
    source: ApiFootballClient,
    team_id: int,
    cutoff: datetime,
    notes: list[str],
    role_label: str,
) -> list[dict[str, Any]]:
    fetch_limit = max(RECENT_MATCH_FETCH_COUNT * 4, 20)
    cutoff_date = (cutoff - timedelta(seconds=1)).date().isoformat()
    method = getattr(source, "team_finished_fixtures_until", None)
    rows: list[dict[str, Any]] = []
    if callable(method):
        rows = _safe_call(
            lambda: method(team_id, cutoff_date, fetch_limit),
            notes,
            f"{role_label}历史赛前近期比赛不可用",
        ) or []
    if not rows:
        rows = _safe_call(
            lambda: source.team_last_fixtures(team_id, fetch_limit),
            notes,
            f"{role_label}近期比赛回退抓取不可用",
        ) or []
        if rows:
            notes.append(f"{role_label}历史赛前样本使用回退过滤：API 未提供截止日前专用列表，已按开赛时间本地剔除未来比赛。")

    filtered = _rows_before_cutoff(rows, cutoff, limit=fetch_limit)
    completed = [
        item for item in filtered
        if str((((item.get("fixture") or {}).get("status") or {}).get("short") or "")).upper() in {"FT", "AET", "PEN"}
    ]
    return completed[:RECENT_MATCH_FETCH_COUNT]


def _rows_before_cutoff(rows: list[dict[str, Any]], cutoff: datetime, *, limit: int) -> list[dict[str, Any]]:
    filtered: list[dict[str, Any]] = []
    cutoff_utc = cutoff.astimezone(timezone.utc)
    for row in rows:
        fixture = row.get("fixture") or {}
        fixture_time = _parse_api_datetime(str(fixture.get("date") or ""))
        if fixture_time is None:
            continue
        if fixture_time.astimezone(timezone.utc) >= cutoff_utc:
            continue
        filtered.append(row)
    return sorted(
        filtered,
        key=lambda item: str(((item.get("fixture") or {}).get("date") or "")),
        reverse=True,
    )[:limit]


def _odds_rows_before_cutoff(rows: list[dict[str, Any]], cutoff: datetime) -> list[dict[str, Any]]:
    cutoff_utc = cutoff.astimezone(timezone.utc)
    filtered: list[dict[str, Any]] = []
    for row in rows:
        updated_at = _parse_api_datetime(str(row.get("update") or row.get("updated") or ""))
        if updated_at is None:
            continue
        if updated_at.astimezone(timezone.utc) <= cutoff_utc:
            filtered.append(row)
    return filtered


def _last_h2h(source: ApiFootballClient, team_a_id: int, team_b_id: int, limit: int) -> list[dict[str, Any]]:
    try:
        return source.last_head_to_head(team_a_id, team_b_id, limit)
    except TypeError:
        return source.last_head_to_head(team_a_id, team_b_id)


def _parse_api_datetime(value: str) -> datetime | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _fixture_without_result(row: dict[str, Any]) -> dict[str, Any]:
    sanitized = copy.deepcopy(row)
    sanitized.pop("goals", None)
    sanitized.pop("score", None)
    teams = sanitized.get("teams")
    if isinstance(teams, dict):
        for side in ("home", "away"):
            team = teams.get(side)
            if isinstance(team, dict):
                team.pop("winner", None)
    fixture = sanitized.get("fixture")
    if isinstance(fixture, dict):
        fixture["historical_asof_sanitized"] = True
    return sanitized


def _h2h_edge(rows: list[dict[str, Any]], home_team_id: int) -> float:
    if not rows:
        return 0.0
    weighted_diff = 0.0
    total_weight = 0.0
    for index, row in enumerate(rows[:10]):
        teams = row.get("teams") or {}
        goals = row.get("goals") or {}
        row_home_id = ((teams.get("home") or {}).get("id"))
        row_away_id = ((teams.get("away") or {}).get("id"))
        home_goals = as_float(goals.get("home"), 0.0)
        away_goals = as_float(goals.get("away"), 0.0)
        if row_home_id == home_team_id:
            diff = home_goals - away_goals
        elif row_away_id == home_team_id:
            diff = away_goals - home_goals
        else:
            continue
        weight = 0.85**index
        weighted_diff += clamp(diff / 3.0, -1.0, 1.0) * weight
        total_weight += weight
    return clamp(weighted_diff / total_weight if total_weight else 0.0, -1.0, 1.0)


def _safe_call(call, notes: list[str], failure_note: str):
    try:
        return call()
    except Exception as exc:  # noqa: BLE001 - external APIs can fail in many shapes.
        notes.append(f"{failure_note}: {exc}")
        return None


def _downgrade_buy_for_missing_strength(
    recommendations: list[BetRecommendation],
    portfolio: PaperPortfolio,
) -> tuple[list[BetRecommendation], PaperPortfolio]:
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
                signal_status=SIGNAL_STATUS_SUSPENDED,
                ev_pfinal_exec=None,
                risk_flags=[*item.risk_flags, "insufficient_recent_form"] if "insufficient_recent_form" not in item.risk_flags else item.risk_flags,
                reason=f"{item.reason} 双方近期有效比赛不足最低准入要求，模拟舱降级为观望。",
            )
        )
    return adjusted, recalculate_portfolio(portfolio, adjusted)


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
