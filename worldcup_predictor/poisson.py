from __future__ import annotations

import math


def poisson_pmf(k: int, rate: float) -> float:
    if rate <= 0:
        return 1.0 if k == 0 else 0.0
    return math.exp(-rate) * rate**k / math.factorial(k)


def score_matrix(home_rate: float, away_rate: float, max_goals: int) -> dict[tuple[int, int], float]:
    matrix: dict[tuple[int, int], float] = {}
    for home_goals in range(max_goals + 1):
        home_prob = poisson_pmf(home_goals, home_rate)
        for away_goals in range(max_goals + 1):
            matrix[(home_goals, away_goals)] = home_prob * poisson_pmf(away_goals, away_rate)

    total = sum(matrix.values())
    if total > 0:
        matrix = {score: prob / total for score, prob in matrix.items()}
    return matrix


def score_matrix_probability_sum(home_rate: float, away_rate: float, max_goals: int) -> float:
    retained = 0.0
    for home_goals in range(max_goals + 1):
        home_prob = poisson_pmf(home_goals, home_rate)
        for away_goals in range(max_goals + 1):
            retained += home_prob * poisson_pmf(away_goals, away_rate)
    return retained


def result_probabilities(matrix: dict[tuple[int, int], float], draw_boost: float = 0.0) -> dict[str, float]:
    probs = {"home_win": 0.0, "draw": 0.0, "away_win": 0.0}
    for (home_goals, away_goals), probability in matrix.items():
        if home_goals > away_goals:
            probs["home_win"] += probability
        elif home_goals == away_goals:
            probs["draw"] += probability * (1.0 + draw_boost)
        else:
            probs["away_win"] += probability

    total = sum(probs.values())
    return {key: value / total for key, value in probs.items()}


def top_scorelines(matrix: dict[tuple[int, int], float], limit: int = 8) -> list[tuple[str, float]]:
    ranked = sorted(matrix.items(), key=lambda item: item[1], reverse=True)
    return [(f"{home}-{away}", probability) for (home, away), probability in ranked[:limit]]
