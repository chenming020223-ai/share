from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime, timezone
from typing import Any

from .api_football import ApiFootballClient, ApiTeam
from .betting import DEFAULT_MIN_EDGE, BetRecommendation, PaperPortfolio, build_recommendations
from .localization import (
    to_api_name,
    to_beijing_time,
    translate_league_display,
    translate_team_display,
)
from .market import DEFAULT_BOOKMAKER, MarketSnapshot, parse_api_football_odds
from .model_governance import ModelGovernance, api_model_governance, apply_formal_ev_gate
from .models import Fixture, ModelConfig, PredictionResult, TeamProfile, as_float, clamp
from .predictor import predict_match
from .poisson import score_matrix

RECENT_MATCH_FETCH_COUNT = 10
MIN_VALID_RECENT_MATCHES = 5


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
    data_notes: list[str] = field(default_factory=list)
    raw_snapshot: dict[str, Any] = field(default_factory=dict)


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
) -> AutoPrediction:
    client = ApiFootballClient(api_key=api_key)
    search_home_name = to_api_name("team", home_name)
    search_away_name = to_api_name("team", away_name)
    if fixture_id:
        fixture_row = client.fixture_by_id(fixture_id)
        requested_home = ApiTeam(id=0, name=search_home_name or home_name)
        requested_away = ApiTeam(id=0, name=search_away_name or away_name)
    else:
        requested_home = client.resolve_team(search_home_name)
        requested_away = client.resolve_team(search_away_name)
        fixture_row = client.next_head_to_head(requested_home.id, requested_away.id)

    fixture_meta = fixture_row.get("fixture") or {}
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

    odds_rows = _safe_call(lambda: client.odds(fixture_api_id), notes, "赔率数据不可用")
    market = parse_api_football_odds(odds_rows or [], required_bookmaker=DEFAULT_BOOKMAKER)

    home_recent_rows = _safe_call(
        lambda: client.team_last_fixtures(actual_home.id, RECENT_MATCH_FETCH_COUNT),
        notes,
        "主队近期比赛不可用",
    ) or []
    away_recent_rows = _safe_call(
        lambda: client.team_last_fixtures(actual_away.id, RECENT_MATCH_FETCH_COUNT),
        notes,
        "客队近期比赛不可用",
    ) or []
    home_recent = _valid_recent_matches(home_recent_rows, actual_home.id)
    away_recent = _valid_recent_matches(away_recent_rows, actual_away.id)
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
    if league_id and season:
        home_stats = _safe_call(
            lambda: client.team_statistics(league_id, season, actual_home.id),
            notes,
            "主队赛季统计不可用",
        )
        away_stats = _safe_call(
            lambda: client.team_statistics(league_id, season, actual_away.id),
            notes,
            "客队赛季统计不可用",
        )
    else:
        notes.append("赛事缺少 league/season，无法拉取球队赛季统计。")

    h2h_rows = _safe_call(
        lambda: client.last_head_to_head(actual_home.id, actual_away.id),
        notes,
        "历史交锋不可用",
    ) or []

    home_profile = _profile_from_api(actual_home, home_stats, home_recent)
    away_profile = _profile_from_api(actual_away, away_stats, away_recent)
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

    config = ModelConfig(market_weight=clamp(market_weight, 0.0, 0.95))
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
        data_notes=notes,
        raw_snapshot={
            "fixture": fixture_row,
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
            },
            "h2h": h2h_rows,
            "notes": list(notes),
        },
    )


def _profile_from_api(
    team: ApiTeam,
    stats: dict[str, Any] | None,
    recent_matches: list[dict[str, Any]] | None = None,
) -> TeamProfile:
    if recent_matches and len(recent_matches) >= MIN_VALID_RECENT_MATCHES:
        played = float(len(recent_matches))
        gf_avg = sum(as_float(item.get("goals_for"), 0.0) for item in recent_matches) / played
        ga_avg = sum(as_float(item.get("goals_against"), 0.0) for item in recent_matches) / played
        points_per_game = sum(as_float(item.get("points"), 0.0) for item in recent_matches) / played
        return _build_profile(team, played, gf_avg, ga_avg, points_per_game)

    if not stats:
        return TeamProfile(name=team.name)

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
    return _build_profile(team, played, gf_avg, ga_avg, points_per_game)


def _build_profile(
    team: ApiTeam,
    played: float,
    gf_avg: float,
    ga_avg: float,
    points_per_game: float,
) -> TeamProfile:
    elo = 1450.0 + points_per_game * 110.0
    attack = clamp(0.55 + gf_avg / 1.8, 0.65, 1.6)
    defense = clamp(1.55 - ga_avg / 2.2, 0.65, 1.55)
    depth = clamp(0.9 + min(played, 20.0) / 100.0, 0.9, 1.1)

    return TeamProfile(
        name=team.name,
        elo=elo,
        fifa_rank=80.0,
        attack_rating=attack,
        defense_rating=defense,
        squad_depth=depth,
        coach_rating=1.0,
    )


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
                "league": league_name,
                "league_zh": translate_league_display(league_name, league_country),
            }
        )
    return valid


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
                reason=f"{item.reason} 双方近期有效比赛不足最低准入要求，模拟舱降级为观望。",
            )
        )
    active = [item for item in adjusted if item.action in {"BUY", "PAPER_BUY"}]
    total_stake = portfolio.unit_stake * len(active)
    expected_profit = sum(
        portfolio.unit_stake * (item.expected_value_per_unit or 0.0)
        for item in active
        if item.expected_value_per_unit is not None
    )
    return adjusted, PaperPortfolio(
        bankroll=portfolio.bankroll,
        unit_stake=portfolio.unit_stake,
        active_bets=len(active),
        total_stake=total_stake,
        bankroll_after_stakes=portfolio.bankroll - total_stake,
        expected_profit=expected_profit,
        expected_bankroll=portfolio.bankroll + expected_profit,
    )


def _optional_int(value: Any) -> int | None:
    try:
        return int(value)
    except (TypeError, ValueError):
        return None
