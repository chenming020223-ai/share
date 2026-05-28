import unittest

from worldcup_predictor.models import Fixture, ModelConfig, PredictionResult, TeamProfile
from worldcup_predictor.odds import devig_three_way, devig_two_way
from worldcup_predictor.predictor import predict_match
from worldcup_predictor.market import MarketSnapshot, parse_api_football_odds
from worldcup_predictor.poisson import score_matrix
from worldcup_predictor.betting import (
    asian_handicap_positive_return_probability,
    asian_total_positive_return_probability,
    build_recommendations,
)


class PredictorTest(unittest.TestCase):
    def test_devig_three_way_sums_to_one(self):
        probs = devig_three_way(2.4, 3.2, 3.0)
        self.assertIsNotNone(probs)
        self.assertLess(abs(sum(probs.values()) - 1.0), 1e-9)

    def test_devig_two_way_sums_to_one(self):
        probs = devig_two_way(1.9, 1.9, "over", "under")
        self.assertIsNotNone(probs)
        self.assertLess(abs(sum(probs.values()) - 1.0), 1e-9)

    def test_stronger_team_gets_higher_win_probability_without_market(self):
        home = TeamProfile(name="A", elo=1850, fifa_rank=5, attack_rating=1.2, defense_rating=1.15)
        away = TeamProfile(name="B", elo=1600, fifa_rank=55, attack_rating=0.95, defense_rating=0.95)
        fixture = Fixture(match_id="A-B", home_team="A", away_team="B")

        result = predict_match(home, away, fixture, ModelConfig(market_weight=0))

        self.assertGreater(result.final_probabilities["home_win"], result.final_probabilities["away_win"])
        self.assertTrue(0.99 < sum(result.final_probabilities.values()) < 1.01)

    def test_parse_api_football_odds_snapshot(self):
        rows = [
            {
                "fixture": {"id": 100},
                "bookmakers": [
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Match Winner",
                                "values": [
                                    {"value": "Home", "odd": "2.00"},
                                    {"value": "Draw", "odd": "3.20"},
                                    {"value": "Away", "odd": "3.80"},
                                ],
                            },
                            {
                                "name": "Goals Over/Under",
                                "values": [
                                    {"value": "Over 2.5", "odd": "1.91"},
                                    {"value": "Under 2.5", "odd": "1.95"},
                                ],
                            },
                            {
                                "name": "Asian Handicap",
                                "values": [
                                    {"value": "Home -0.5", "odd": "2.05"},
                                    {"value": "Away -0.5", "odd": "1.85"},
                                ],
                            },
                        ]
                    }
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows)

        self.assertEqual(snapshot.fixture_id, 100)
        self.assertEqual(snapshot.match_winner["home_win"], 2.00)
        self.assertEqual(snapshot.best_total_line()[0], 2.5)
        self.assertEqual(snapshot.best_handicap_line()[0], -0.5)

    def test_total_market_requires_same_bookmaker_pair(self):
        rows = [
            {
                "fixture": {"id": 100},
                "bookmakers": [
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Goals Over/Under",
                                "values": [{"value": "Over 2.5", "odd": "1.91"}],
                            }
                        ],
                    },
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Goals Over/Under",
                                "values": [{"value": "Under 2.5", "odd": "1.95"}],
                            }
                        ],
                    },
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows)

        self.assertIsNone(snapshot.best_total_line())
        self.assertTrue(any("缺少同公司成对赔率" in item for item in snapshot.warnings))

    def test_match_winner_requires_complete_bookmaker_prices(self):
        rows = [
            {
                "fixture": {"id": 100},
                "bookmakers": [
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Match Winner",
                                "values": [
                                    {"value": "Home", "odd": "2.00"},
                                    {"value": "Away", "odd": "3.80"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows)

        self.assertEqual(snapshot.match_winner, {})
        self.assertTrue(any("缺少完整 1X2" in item for item in snapshot.warnings))

    def test_abnormal_two_way_market_is_excluded(self):
        rows = [
            {
                "fixture": {"id": 100},
                "bookmakers": [
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Goals Over/Under",
                                "values": [
                                    {"value": "Over 2.5", "odd": "4.85"},
                                    {"value": "Under 2.5", "odd": "2.78"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows)

        self.assertIsNone(snapshot.best_total_line())
        self.assertTrue(any("盘口水位异常" in item for item in snapshot.warnings))

    def test_only_pinnacle_full_time_markets_are_accepted(self):
        rows = [
            {
                "fixture": {"id": 100},
                "update": "2026-05-25T00:00:00+00:00",
                "bookmakers": [
                    {
                        "name": "Other Bookmaker",
                        "bets": [
                            {
                                "name": "Match Winner",
                                "values": [
                                    {"value": "Home", "odd": "9.00"},
                                    {"value": "Draw", "odd": "9.00"},
                                    {"value": "Away", "odd": "9.00"},
                                ],
                            }
                        ],
                    },
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Match Winner",
                                "values": [
                                    {"value": "Home", "odd": "2.00"},
                                    {"value": "Draw", "odd": "3.20"},
                                    {"value": "Away", "odd": "3.80"},
                                ],
                            },
                            {
                                "name": "Asian Handicap First Half",
                                "values": [
                                    {"value": "Home -0.5", "odd": "2.30"},
                                    {"value": "Away -0.5", "odd": "1.60"},
                                ],
                            },
                            {
                                "name": "Cards Over/Under",
                                "values": [
                                    {"value": "Over 2.5", "odd": "3.50"},
                                    {"value": "Under 2.5", "odd": "1.30"},
                                ],
                            },
                            {
                                "name": "Asian Handicap",
                                "values": [
                                    {"value": "Home -0.5", "odd": "1.91"},
                                    {"value": "Away -0.5", "odd": "1.95"},
                                ],
                            },
                            {
                                "name": "Goals Over/Under",
                                "values": [
                                    {"value": "Over 2.5", "odd": "1.92"},
                                    {"value": "Under 2.5", "odd": "1.94"},
                                ],
                            },
                        ],
                    },
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows)

        self.assertEqual(snapshot.selected_bookmaker, "Pinnacle")
        self.assertEqual(snapshot.captured_at, "2026-05-25T00:00:00+00:00")
        self.assertEqual(snapshot.match_winner["home_win"], 2.00)
        self.assertEqual(snapshot.best_handicap_line()[1]["home"], 1.91)
        self.assertEqual(snapshot.best_total_line()[1]["over"], 1.92)

    def test_main_handicap_line_uses_balanced_full_time_pair(self):
        rows = [
            {
                "fixture": {"id": 1378240},
                "bookmakers": [
                    {
                        "name": "Pinnacle",
                        "bets": [
                            {
                                "name": "Asian Handicap",
                                "values": [
                                    {"value": "Home -1.25", "odd": "2.09"},
                                    {"value": "Away -1.25", "odd": "1.85"},
                                    {"value": "Home +0", "odd": "1.17"},
                                    {"value": "Away +0", "odd": "5.68"},
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows)

        self.assertEqual(snapshot.best_handicap_line()[0], -1.25)
        self.assertEqual(snapshot.best_handicap_line()[1], {"home": 2.09, "away": 1.85})

    def test_conservative_ev_gate_blocks_thin_1x2_signal(self):
        result = PredictionResult(
            match_id="100",
            home_team="Preston Lions",
            away_team="Oakleigh Cannons",
            expected_goals_home=1.61,
            expected_goals_away=1.87,
            model_probabilities={"home_win": 0.336, "draw": 0.222, "away_win": 0.442},
            market_probabilities=None,
            final_probabilities={"home_win": 0.336, "draw": 0.222, "away_win": 0.442},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(
            bookmakers_count=1,
            match_winner={"home_win": 3.18, "draw": 3.46, "away_win": 1.98},
        )

        recommendations, portfolio = build_recommendations(result, {}, market, unit_stake=100)

        self.assertEqual(recommendations[0].market, "胜平负")
        self.assertEqual(recommendations[0].action, "WATCH")
        self.assertLess(recommendations[0].conservative_expected_value_per_unit, 0)
        self.assertEqual(portfolio.active_bets, 0)

    def test_low_probability_1x2_direction_is_never_buy_signal(self):
        result = PredictionResult(
            match_id="101",
            home_team="A",
            away_team="B",
            expected_goals_home=1.4,
            expected_goals_away=1.1,
            model_probabilities={"home_win": 0.39, "draw": 0.27, "away_win": 0.34},
            market_probabilities=None,
            final_probabilities={"home_win": 0.39, "draw": 0.27, "away_win": 0.34},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(match_winner={"home_win": 3.00, "draw": 3.40, "away_win": 2.40})

        recommendations, portfolio = build_recommendations(result, {}, market, unit_stake=10)

        self.assertEqual(recommendations[0].selection, "A 胜")
        self.assertEqual(recommendations[0].action, "WATCH")
        self.assertIn("低于胜平负研究方向下限", recommendations[0].reason)
        self.assertEqual(portfolio.active_bets, 0)

    def test_excessive_probability_gap_requires_review_instead_of_buy(self):
        result = PredictionResult(
            match_id="102",
            home_team="A",
            away_team="B",
            expected_goals_home=1.0,
            expected_goals_away=1.6,
            model_probabilities={"home_win": 0.22, "draw": 0.22, "away_win": 0.56},
            market_probabilities=None,
            final_probabilities={"home_win": 0.22, "draw": 0.22, "away_win": 0.56},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(match_winner={"home_win": 2.00, "draw": 3.20, "away_win": 4.80})

        recommendations, portfolio = build_recommendations(result, {}, market, unit_stake=10)

        self.assertEqual(recommendations[0].selection, "B 胜")
        self.assertEqual(recommendations[0].action, "WATCH")
        self.assertIn("复核上限", recommendations[0].reason)
        self.assertEqual(portfolio.active_bets, 0)

    def test_pinnacle_1x2_model_divergence_suspends_ev_for_all_markets(self):
        result = PredictionResult(
            match_id="1545408",
            home_team="Saint Etienne",
            away_team="Nice",
            expected_goals_home=2.3813571334,
            expected_goals_away=0.9555227870,
            model_probabilities={"home_win": 0.6883681955, "draw": 0.1775775971, "away_win": 0.1340542074},
            market_probabilities=None,
            final_probabilities={"home_win": 0.6883681955, "draw": 0.1775775971, "away_win": 0.1340542074},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(
            required_bookmaker="Pinnacle",
            selected_bookmaker="Pinnacle",
            match_winner={"home_win": 2.37, "draw": 3.42, "away_win": 3.08},
            totals={2.5: {"over": 1.85, "under": 2.02}},
            handicaps={-0.25: {"home": 2.05, "away": 1.85}},
        )

        recommendations, portfolio = build_recommendations(
            result,
            score_matrix(result.expected_goals_home, result.expected_goals_away, 8),
            market,
            unit_stake=10,
        )

        self.assertTrue(all(item.action == "WATCH" for item in recommendations))
        self.assertTrue(all(item.ev_status == "SUSPENDED_MODEL_DIVERGENCE" for item in recommendations))
        self.assertTrue(all(item.expected_value_per_unit is None for item in recommendations))
        self.assertAlmostEqual(recommendations[0].audit_expected_value_per_unit, 0.6314326233)
        self.assertIn("本场所有市场 EV 暂停计算", recommendations[1].reason)
        self.assertEqual(portfolio.total_stake, 0)

    def test_betting_probability_helpers_are_bounded(self):
        matrix = score_matrix(1.4, 1.1, 8)

        over_probability = asian_total_positive_return_probability(matrix, 2.5, "over")
        home_cover_probability = asian_handicap_positive_return_probability(matrix, -0.5, "home")

        self.assertTrue(0.0 <= over_probability <= 1.0)
        self.assertTrue(0.0 <= home_cover_probability <= 1.0)


if __name__ == "__main__":
    unittest.main()
