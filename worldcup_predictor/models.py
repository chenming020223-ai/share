from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


def as_float(value: Any, default: float = 0.0) -> float:
    if value is None:
        return default
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip()
    if not text:
        return default
    try:
        return float(text)
    except ValueError:
        return default


def as_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    text = str(value).strip().lower()
    if not text:
        return default
    return text in {"1", "true", "yes", "y", "是", "主场", "host"}


def clamp(value: float, low: float, high: float) -> float:
    return max(low, min(high, value))


@dataclass(frozen=True)
class TeamProfile:
    name: str
    elo: float = 1500.0
    fifa_rank: float = 80.0
    attack_rating: float = 1.0
    defense_rating: float = 1.0
    squad_depth: float = 1.0
    coach_rating: float = 1.0
    market_value_eur_m: float = 0.0
    host_factor: float = 0.0

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "TeamProfile":
        return cls(
            name=str(row.get("team") or row.get("name") or "").strip(),
            elo=as_float(row.get("elo"), 1500.0),
            fifa_rank=as_float(row.get("fifa_rank"), 80.0),
            attack_rating=as_float(row.get("attack_rating"), 1.0),
            defense_rating=as_float(row.get("defense_rating"), 1.0),
            squad_depth=as_float(row.get("squad_depth"), 1.0),
            coach_rating=as_float(row.get("coach_rating"), 1.0),
            market_value_eur_m=as_float(row.get("market_value_eur_m"), 0.0),
            host_factor=as_float(row.get("host_factor"), 0.0),
        )


@dataclass(frozen=True)
class Fixture:
    match_id: str
    home_team: str
    away_team: str
    neutral_site: bool = True
    rest_days_home: float = 5.0
    rest_days_away: float = 5.0
    travel_km_home: float = 0.0
    travel_km_away: float = 0.0
    group_points_home: float = 0.0
    group_points_away: float = 0.0
    group_goal_diff_home: float = 0.0
    group_goal_diff_away: float = 0.0
    must_win_home: float = 0.0
    must_win_away: float = 0.0
    rotation_risk_home: float = 0.0
    rotation_risk_away: float = 0.0
    h2h_edge_home: float = 0.0
    rivalry_intensity: float = 0.0
    country_relation_home_edge: float = 0.0
    commercial_incentive_home_edge: float = 0.0
    odds_home: float = 0.0
    odds_draw: float = 0.0
    odds_away: float = 0.0
    notes: str = ""
    extras: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_row(cls, row: dict[str, Any]) -> "Fixture":
        known = {
            "match_id",
            "home_team",
            "away_team",
            "neutral_site",
            "rest_days_home",
            "rest_days_away",
            "travel_km_home",
            "travel_km_away",
            "group_points_home",
            "group_points_away",
            "group_goal_diff_home",
            "group_goal_diff_away",
            "must_win_home",
            "must_win_away",
            "rotation_risk_home",
            "rotation_risk_away",
            "h2h_edge_home",
            "rivalry_intensity",
            "country_relation_home_edge",
            "commercial_incentive_home_edge",
            "odds_home",
            "odds_draw",
            "odds_away",
            "notes",
        }
        return cls(
            match_id=str(row.get("match_id") or "").strip(),
            home_team=str(row.get("home_team") or "").strip(),
            away_team=str(row.get("away_team") or "").strip(),
            neutral_site=as_bool(row.get("neutral_site"), True),
            rest_days_home=as_float(row.get("rest_days_home"), 5.0),
            rest_days_away=as_float(row.get("rest_days_away"), 5.0),
            travel_km_home=as_float(row.get("travel_km_home"), 0.0),
            travel_km_away=as_float(row.get("travel_km_away"), 0.0),
            group_points_home=as_float(row.get("group_points_home"), 0.0),
            group_points_away=as_float(row.get("group_points_away"), 0.0),
            group_goal_diff_home=as_float(row.get("group_goal_diff_home"), 0.0),
            group_goal_diff_away=as_float(row.get("group_goal_diff_away"), 0.0),
            must_win_home=clamp(as_float(row.get("must_win_home"), 0.0), 0.0, 1.0),
            must_win_away=clamp(as_float(row.get("must_win_away"), 0.0), 0.0, 1.0),
            rotation_risk_home=clamp(as_float(row.get("rotation_risk_home"), 0.0), 0.0, 1.0),
            rotation_risk_away=clamp(as_float(row.get("rotation_risk_away"), 0.0), 0.0, 1.0),
            h2h_edge_home=clamp(as_float(row.get("h2h_edge_home"), 0.0), -1.0, 1.0),
            rivalry_intensity=clamp(as_float(row.get("rivalry_intensity"), 0.0), 0.0, 1.0),
            country_relation_home_edge=clamp(as_float(row.get("country_relation_home_edge"), 0.0), -1.0, 1.0),
            commercial_incentive_home_edge=clamp(
                as_float(row.get("commercial_incentive_home_edge"), 0.0), -1.0, 1.0
            ),
            odds_home=as_float(row.get("odds_home"), 0.0),
            odds_draw=as_float(row.get("odds_draw"), 0.0),
            odds_away=as_float(row.get("odds_away"), 0.0),
            notes=str(row.get("notes") or "").strip(),
            extras={key: str(value) for key, value in row.items() if key not in known},
        )


@dataclass(frozen=True)
class ModelConfig:
    base_goals: float = 1.28
    max_goals: int = 8
    market_weight: float = 0.45
    strength_weight: float = 0.36
    rank_weight: float = 0.16
    host_weight: float = 0.11
    rest_weight: float = 0.055
    travel_weight: float = 0.045
    group_weight: float = 0.10
    rotation_weight: float = 0.09
    h2h_weight: float = 0.055
    country_relation_weight: float = 0.025
    commercial_weight: float = 0.035
    draw_rivalry_weight: float = 0.08


@dataclass(frozen=True)
class PredictionResult:
    match_id: str
    home_team: str
    away_team: str
    expected_goals_home: float
    expected_goals_away: float
    model_probabilities: dict[str, float]
    market_probabilities: dict[str, float] | None
    final_probabilities: dict[str, float]
    top_scores: list[tuple[str, float]]
    feature_edges: dict[str, float]
    notes: str = ""
