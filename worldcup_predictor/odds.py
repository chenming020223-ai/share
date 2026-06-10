from __future__ import annotations

from .models import clamp

TWO_WAY_IMPLIED_MIN = 0.98
TWO_WAY_IMPLIED_MAX = 1.25


def devig_three_way(
    home_odds: float,
    draw_odds: float,
    away_odds: float,
    margin_method: str = "proportional",
) -> dict[str, float] | None:
    """Convert decimal 1X2 odds into no-margin probabilities."""
    if margin_method != "proportional":
        return None
    if home_odds <= 1.0 or draw_odds <= 1.0 or away_odds <= 1.0:
        return None

    implied = {
        "home_win": 1.0 / home_odds,
        "draw": 1.0 / draw_odds,
        "away_win": 1.0 / away_odds,
    }
    total = sum(implied.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in implied.items()}


def two_way_implied_sum(first_odds: float, second_odds: float) -> float | None:
    if first_odds <= 1.0 or second_odds <= 1.0:
        return None
    return (1.0 / first_odds) + (1.0 / second_odds)


def is_reasonable_two_way_market(
    first_odds: float,
    second_odds: float,
    min_sum: float = TWO_WAY_IMPLIED_MIN,
    max_sum: float = TWO_WAY_IMPLIED_MAX,
) -> bool:
    implied_sum = two_way_implied_sum(first_odds, second_odds)
    return implied_sum is not None and min_sum <= implied_sum <= max_sum


def devig_two_way(
    first_odds: float,
    second_odds: float,
    first_key: str = "first",
    second_key: str = "second",
    margin_method: str = "proportional",
) -> dict[str, float] | None:
    """Convert decimal two-way odds into no-margin probabilities."""
    if margin_method != "proportional":
        return None
    if first_odds <= 1.0 or second_odds <= 1.0:
        return None

    implied = {
        first_key: 1.0 / first_odds,
        second_key: 1.0 / second_odds,
    }
    total = sum(implied.values())
    if total <= 0:
        return None
    return {key: value / total for key, value in implied.items()}


def blend_probabilities(
    model_probs: dict[str, float],
    market_probs: dict[str, float] | None,
    market_weight: float,
) -> dict[str, float]:
    if not market_probs:
        return dict(model_probs)

    weight = clamp(market_weight, 0.0, 0.95)
    blended = {
        key: (1.0 - weight) * model_probs[key] + weight * market_probs[key]
        for key in ("home_win", "draw", "away_win")
    }
    total = sum(blended.values())
    return {key: value / total for key, value in blended.items()}
