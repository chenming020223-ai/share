from __future__ import annotations

import math

from .models import Fixture, ModelConfig, PredictionResult, TeamProfile, clamp
from .odds import blend_probabilities, devig_three_way
from .poisson import result_probabilities, score_matrix, top_scorelines


def predict_match(
    home: TeamProfile,
    away: TeamProfile,
    fixture: Fixture,
    config: ModelConfig | None = None,
) -> PredictionResult:
    config = config or ModelConfig()
    feature_edges = calculate_feature_edges(home, away, fixture, config)

    home_rate = config.base_goals * _safe_ratio(home.attack_rating, away.defense_rating)
    away_rate = config.base_goals * _safe_ratio(away.attack_rating, home.defense_rating)

    log_edge = sum(
        value
        for key, value in feature_edges.items()
        if key not in {"rivalry_draw_boost", "commercial_raw_edge", "country_relation_raw_edge"}
    )
    home_rate *= math.exp(log_edge)
    away_rate *= math.exp(-log_edge)

    home_rate = clamp(home_rate, 0.15, 4.5)
    away_rate = clamp(away_rate, 0.15, 4.5)

    matrix = score_matrix(home_rate, away_rate, config.max_goals)
    draw_boost = feature_edges["rivalry_draw_boost"]
    model_probs = result_probabilities(matrix, draw_boost=draw_boost)
    market_probs = devig_three_way(fixture.odds_home, fixture.odds_draw, fixture.odds_away)
    final_probs = blend_probabilities(model_probs, market_probs, config.market_weight)

    return PredictionResult(
        match_id=fixture.match_id,
        home_team=home.name,
        away_team=away.name,
        expected_goals_home=home_rate,
        expected_goals_away=away_rate,
        model_probabilities=model_probs,
        market_probabilities=market_probs,
        final_probabilities=final_probs,
        top_scores=top_scorelines(matrix),
        feature_edges=feature_edges,
        notes=fixture.notes,
    )


def calculate_feature_edges(
    home: TeamProfile,
    away: TeamProfile,
    fixture: Fixture,
    config: ModelConfig,
) -> dict[str, float]:
    elo_edge = clamp((home.elo - away.elo) / 400.0, -1.5, 1.5) * config.strength_weight
    rank_edge = clamp((away.fifa_rank - home.fifa_rank) / 100.0, -1.0, 1.0) * config.rank_weight
    host_edge = 0.0
    if not fixture.neutral_site:
        host_edge += config.host_weight
    host_edge += clamp(home.host_factor - away.host_factor, -1.0, 1.0) * config.host_weight

    rest_edge = clamp((fixture.rest_days_home - fixture.rest_days_away) / 5.0, -1.0, 1.0) * config.rest_weight
    travel_edge = clamp((fixture.travel_km_away - fixture.travel_km_home) / 6000.0, -1.0, 1.0) * config.travel_weight

    group_need_edge = clamp(fixture.must_win_home - fixture.must_win_away, -1.0, 1.0)
    group_position_edge = clamp(
        ((fixture.group_points_away - fixture.group_points_home) / 6.0)
        + ((fixture.group_goal_diff_away - fixture.group_goal_diff_home) / 12.0),
        -1.0,
        1.0,
    )
    group_edge = (0.7 * group_need_edge + 0.3 * group_position_edge) * config.group_weight

    rotation_edge = clamp(
        fixture.rotation_risk_away - fixture.rotation_risk_home,
        -1.0,
        1.0,
    ) * config.rotation_weight
    h2h_edge = fixture.h2h_edge_home * config.h2h_weight
    country_edge = fixture.country_relation_home_edge * config.country_relation_weight
    commercial_edge = fixture.commercial_incentive_home_edge * config.commercial_weight
    rivalry_draw_boost = fixture.rivalry_intensity * config.draw_rivalry_weight

    return {
        "elo_edge": elo_edge,
        "fifa_rank_edge": rank_edge,
        "host_edge": host_edge,
        "rest_edge": rest_edge,
        "travel_edge": travel_edge,
        "group_context_edge": group_edge,
        "rotation_edge": rotation_edge,
        "h2h_edge": h2h_edge,
        "country_relation_edge": country_edge,
        "commercial_incentive_edge": commercial_edge,
        "rivalry_draw_boost": rivalry_draw_boost,
        "country_relation_raw_edge": fixture.country_relation_home_edge,
        "commercial_raw_edge": fixture.commercial_incentive_home_edge,
    }


def _safe_ratio(numerator: float, denominator: float) -> float:
    return clamp(numerator, 0.2, 2.5) / clamp(denominator, 0.2, 2.5)
