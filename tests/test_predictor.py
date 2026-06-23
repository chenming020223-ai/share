import math
import unittest

from worldcup_predictor.models import Fixture, ModelConfig, PredictionResult, TeamProfile
from worldcup_predictor.odds import devig_three_way, devig_two_way
from worldcup_predictor.predictor import predict_match
from worldcup_predictor.market import MarketSnapshot, parse_api_football_odds
from worldcup_predictor.poisson import score_matrix
from worldcup_predictor.risk import build_match_risk_context
from worldcup_predictor.bankroll import dynamic_unit_stake
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

    def test_exp_edge_audit_matches_raw_expected_goals(self):
        home = TeamProfile(name="A", elo=1700, fifa_rank=30, attack_rating=1.18, defense_rating=1.08)
        away = TeamProfile(name="B", elo=1580, fifa_rank=70, attack_rating=0.96, defense_rating=0.92)
        fixture = Fixture(
            match_id="A-B",
            home_team="A",
            away_team="B",
            neutral_site=False,
            rest_days_home=6,
            rest_days_away=4,
            h2h_edge_home=0.2,
        )

        result = predict_match(home, away, fixture, ModelConfig(market_weight=0))

        self.assertIsNotNone(result.base_expected_goals_home)
        self.assertIsNotNone(result.base_expected_goals_away)
        self.assertIsNotNone(result.log_edge)
        self.assertAlmostEqual(result.home_exp_multiplier, math.exp(result.log_edge), places=12)
        self.assertAlmostEqual(result.away_exp_multiplier, math.exp(-result.log_edge), places=12)
        self.assertAlmostEqual(
            result.raw_expected_goals_home,
            result.base_expected_goals_home * result.home_exp_multiplier,
            places=12,
        )
        self.assertAlmostEqual(
            result.raw_expected_goals_away,
            result.base_expected_goals_away * result.away_exp_multiplier,
            places=12,
        )

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

    def test_bookmaker_priority_falls_back_without_cross_market_averaging(self):
        rows = [
            {
                "fixture": {"id": 101},
                "update": "2026-05-25T00:00:00+00:00",
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
                    },
                    {
                        "name": "Bet365",
                        "bets": [
                            {
                                "name": "Match Winner",
                                "values": [
                                    {"value": "Home", "odd": "2.10"},
                                    {"value": "Draw", "odd": "3.30"},
                                    {"value": "Away", "odd": "3.60"},
                                ],
                            },
                            {
                                "name": "Goals Over/Under",
                                "values": [
                                    {"value": "Over 2.5", "odd": "1.90"},
                                    {"value": "Under 2.5", "odd": "1.96"},
                                ],
                            },
                        ],
                    },
                ],
            }
        ]

        snapshot = parse_api_football_odds(rows, required_bookmaker=None, bookmaker_priority=["Pinnacle", "Bet365"])

        self.assertEqual(snapshot.selected_bookmakers["1X2"], "Bet365")
        self.assertEqual(snapshot.selected_bookmakers["OU"], "Bet365")
        self.assertEqual(snapshot.match_winner["home_win"], 2.10)
        self.assertTrue(any("回退使用 Bet365" in item for item in snapshot.warnings))

    def test_total_market_never_pairs_different_bookmakers(self):
        rows = [
            {
                "fixture": {"id": 102},
                "bookmakers": [
                    {
                        "name": "Bet365",
                        "bets": [
                            {
                                "name": "Goals Over/Under",
                                "values": [{"value": "Over 2.5", "odd": "1.91"}],
                            }
                        ],
                    },
                    {
                        "name": "Betfair",
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

        snapshot = parse_api_football_odds(rows, required_bookmaker=None, bookmaker_priority=["Bet365", "Betfair"])

        self.assertIsNone(snapshot.best_total_line())
        self.assertNotIn("OU", snapshot.selected_bookmakers)

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

    def test_zero_unit_stake_uses_dynamic_five_part_bankroll_plan(self):
        plan = dynamic_unit_stake(1000)

        self.assertEqual(plan.unit_stake, 200)
        self.assertEqual(dynamic_unit_stake(1200).unit_stake, 220)
        self.assertEqual(dynamic_unit_stake(800).unit_stake, 160)

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
        self.assertIn("模型分歧异常", recommendations[0].reason)
        self.assertEqual(portfolio.active_bets, 0)

    def test_pinnacle_1x2_model_divergence_suspends_match_winner_only(self):
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

        self.assertEqual(recommendations[0].signal_status, "SUSPENDED")
        self.assertEqual(recommendations[0].ev_status, "MODEL_MARKET_CONFLICT")
        self.assertIsNone(recommendations[0].expected_value_per_unit)
        self.assertAlmostEqual(recommendations[0].audit_expected_value_per_unit, 0.6314326233)
        self.assertAlmostEqual(recommendations[0].ev_pbase_research, 0.6314326233)
        self.assertIsNone(recommendations[0].ev_pfinal_exec)
        self.assertIn("胜平负 EV 暂停计算", recommendations[0].reason)
        self.assertIn("MATCH_WINNER_MODEL_MARKET_DIVERGENCE", recommendations[1].risk_flags)
        self.assertEqual(recommendations[1].action, "PAPER_BUY")
        self.assertEqual(recommendations[1].signal_status, "PAPER_BUY")
        self.assertEqual(recommendations[1].ev_status, "PAPER_OBSERVATION")
        self.assertIsNotNone(recommendations[1].expected_value_per_unit)
        self.assertIsNotNone(recommendations[1].paper_expected_value_per_unit)
        self.assertEqual(recommendations[1].stake, 10)
        self.assertEqual(recommendations[2].signal_status, "SUSPENDED")
        self.assertEqual(recommendations[2].ev_status, "MODEL_MARKET_CONFLICT")
        self.assertEqual(portfolio.active_bets, 1)
        self.assertEqual(portfolio.total_stake, 10)

    def test_single_market_probability_gap_suspends_that_market_ev_only(self):
        result = PredictionResult(
            match_id="1548442",
            home_team="Kosovo U21",
            away_team="Luxembourg U21",
            expected_goals_home=2.77,
            expected_goals_away=1.40,
            model_probabilities={
                "home_win": 0.6606957400993966,
                "draw": 0.16610935701704246,
                "away_win": 0.173194902883561,
            },
            market_probabilities=None,
            final_probabilities={
                "home_win": 0.5945934556788263,
                "draw": 0.20827924339090786,
                "away_win": 0.19712730093026581,
            },
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(
            selected_bookmaker="Pinnacle",
            match_winner={"home_win": 1.78, "draw": 3.52, "away_win": 4.04},
            totals={2.5: {"over": 1.83, "under": 1.96}},
            handicaps={-0.5: {"home": 1.79, "away": 2.01}},
        )

        recommendations, portfolio = build_recommendations(
            result,
            score_matrix(result.expected_goals_home, result.expected_goals_away, 8),
            market,
            unit_stake=10,
        )

        total_goals = recommendations[1]
        self.assertEqual(total_goals.market, "大小球")
        self.assertEqual(total_goals.action, "WATCH")
        self.assertEqual(total_goals.signal_status, "SUSPENDED")
        self.assertEqual(total_goals.ev_status, "MODEL_MARKET_CONFLICT")
        self.assertIsNone(total_goals.expected_value_per_unit)
        self.assertGreater(total_goals.audit_expected_value_per_unit, 0.40)
        self.assertGreater(abs(total_goals.edge), 0.15)
        self.assertIn("异常观察池", total_goals.reason)
        self.assertNotEqual(recommendations[0].ev_status, "MODEL_MARKET_CONFLICT")
        self.assertEqual(portfolio.active_bets, 0)

    def test_youth_friendly_missing_stats_blocks_score_markets(self):
        result = PredictionResult(
            match_id="1548442",
            home_team="Kosovo U21",
            away_team="Luxembourg U21",
            expected_goals_home=2.77,
            expected_goals_away=1.40,
            model_probabilities={
                "home_win": 0.6606957400993966,
                "draw": 0.16610935701704246,
                "away_win": 0.173194902883561,
            },
            market_probabilities=None,
            final_probabilities={
                "home_win": 0.5945934556788263,
                "draw": 0.20827924339090786,
                "away_win": 0.19712730093026581,
            },
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(
            selected_bookmaker="Pinnacle",
            match_winner={"home_win": 1.78, "draw": 3.52, "away_win": 4.04},
            totals={2.5: {"over": 1.83, "under": 1.96}},
            handicaps={-0.5: {"home": 1.79, "away": 2.01}},
        )
        risk_context = build_match_risk_context(
            home_team="Kosovo U21",
            away_team="Luxembourg U21",
            league_name="International Friendlies",
            collection_mode="deep",
            deep_stats_matches=0,
            home_recent_matches=10,
            away_recent_matches=10,
        )

        recommendations, portfolio = build_recommendations(
            result,
            score_matrix(result.expected_goals_home, result.expected_goals_away, 10),
            market,
            unit_stake=10,
            risk_context=risk_context,
        )

        self.assertEqual(recommendations[0].action, "WATCH")
        self.assertLessEqual(recommendations[0].shrink_k, 0.0)
        self.assertEqual(recommendations[1].decision_status, "MODEL_MARKET_CONFLICT")
        self.assertEqual(recommendations[2].decision_status, "SUSPENDED")
        self.assertIn("U21_RISK_DISCOUNT", recommendations[1].risk_flags)
        self.assertIn("EXTREME_TOTAL_GOALS_LAMBDA", recommendations[1].risk_flags)
        self.assertIn("HANDICAP_MARGIN_DISTRIBUTION_NOT_CALIBRATED", recommendations[2].risk_flags)
        self.assertEqual(portfolio.total_stake, 0)

    def test_betting_probability_helpers_are_bounded(self):
        matrix = score_matrix(1.4, 1.1, 8)

        over_probability = asian_total_positive_return_probability(matrix, 2.5, "over")
        home_cover_probability = asian_handicap_positive_return_probability(matrix, -0.5, "home")

        self.assertTrue(0.0 <= over_probability <= 1.0)
        self.assertTrue(0.0 <= home_cover_probability <= 1.0)

    def test_1x2_ev_calculation_path_is_auditable(self):
        result = PredictionResult(
            match_id="103",
            home_team="Napoli",
            away_team="Udinese",
            expected_goals_home=1.99,
            expected_goals_away=1.32,
            model_probabilities={"home_win": 0.58, "draw": 0.19, "away_win": 0.23},
            market_probabilities=None,
            final_probabilities={"home_win": 0.58, "draw": 0.19, "away_win": 0.23},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(match_winner={"home_win": 1.45, "draw": 4.0, "away_win": 7.56})

        recommendations, _ = build_recommendations(result, {}, market, unit_stake=10)
        calculation = recommendations[0].ev_calculation

        self.assertEqual(recommendations[0].selection, "Napoli 胜")
        self.assertAlmostEqual(recommendations[0].expected_value_per_unit, -0.159)
        self.assertAlmostEqual(recommendations[0].ev_pbase_research, -0.159)
        self.assertIsNone(recommendations[0].ev_pfinal_exec)
        self.assertEqual(recommendations[0].ev_layer, "pbase_research")
        self.assertEqual(recommendations[0].model_probability_label, "模型胜率")
        self.assertEqual(recommendations[0].ev_probability_basis, "pbase_result_probability")
        self.assertEqual(calculation["evLayer"], "pbase_research")
        self.assertEqual(calculation["modelProbabilityLabel"], "模型胜率")
        self.assertEqual(calculation["evProbabilityBasis"], "pbase_result_probability")
        self.assertFalse(calculation["formalExecutionEnabled"])
        self.assertEqual(calculation["formula"], "EV = pbase × odds - 1")
        self.assertAlmostEqual(calculation["winStakeFraction"], 0.58)
        self.assertAlmostEqual(calculation["lossStakeFraction"], 0.42)
        self.assertAlmostEqual(calculation["breakEvenOdds"], 1 / 0.58)
        self.assertTrue(any(gate["key"] == "model_probability" and gate["passed"] for gate in calculation["gates"]))
        self.assertTrue(any(gate["key"] == "max_odds" and gate["passed"] for gate in calculation["gates"]))
        self.assertTrue(any(gate["key"] == "ev" and not gate["passed"] for gate in calculation["gates"]))

    def test_high_odds_1x2_direction_is_research_watch_only(self):
        result = PredictionResult(
            match_id="106",
            home_team="A",
            away_team="B",
            expected_goals_home=1.1,
            expected_goals_away=1.7,
            model_probabilities={"home_win": 0.42, "draw": 0.25, "away_win": 0.33},
            market_probabilities=None,
            final_probabilities={"home_win": 0.42, "draw": 0.25, "away_win": 0.33},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(match_winner={"home_win": 4.60, "draw": 4.00, "away_win": 4.20})

        recommendations, portfolio = build_recommendations(result, {}, market, unit_stake=100)
        match_winner = recommendations[0]

        self.assertEqual(match_winner.selection, "A 胜")
        self.assertEqual(match_winner.action, "WATCH")
        self.assertEqual(match_winner.ev_status, "RESEARCH_ONLY")
        self.assertEqual(match_winner.stake, 0.0)
        self.assertIn("高于高赔率复核上限", match_winner.reason)
        self.assertTrue(any(gate["key"] == "max_odds" and not gate["passed"] for gate in match_winner.ev_calculation["gates"]))
        self.assertEqual(portfolio.active_bets, 0)

    def test_asian_total_ev_path_splits_half_loss_and_break_even_odds(self):
        result = PredictionResult(
            match_id="104",
            home_team="A",
            away_team="B",
            expected_goals_home=1.0,
            expected_goals_away=1.0,
            model_probabilities={"home_win": 0.34, "draw": 0.30, "away_win": 0.36},
            market_probabilities=None,
            final_probabilities={"home_win": 0.34, "draw": 0.30, "away_win": 0.36},
            top_scores=[],
            feature_edges={},
        )
        score_probs = {
            (3, 0): 0.50,
            (2, 0): 0.25,
            (1, 0): 0.25,
        }
        market = MarketSnapshot(totals={2.25: {"over": 2.0, "under": 2.0}})

        recommendations, _ = build_recommendations(result, score_probs, market, unit_stake=10)
        total = recommendations[1]
        settlement = total.ev_calculation["settlement"]

        self.assertEqual(total.selection, "大 2.25")
        self.assertEqual(total.action, "WATCH")
        self.assertEqual(total.signal_status, "RESEARCH_WATCH")
        self.assertEqual(total.decision_status, "RESEARCH_OBSERVATION")
        self.assertEqual(total.model_probability_label, "正收益概率")
        self.assertEqual(total.ev_probability_basis, "asian_settlement_weight")
        self.assertEqual(total.ev_calculation["modelProbabilityLabel"], "正收益概率")
        self.assertEqual(total.ev_calculation["evProbabilityBasis"], "asian_settlement_weight")
        self.assertAlmostEqual(total.expected_value_per_unit, 0.125)
        self.assertAlmostEqual(total.paper_expected_value_per_unit, 0.05625)
        self.assertAlmostEqual(total.adjusted_probability, 0.50)
        self.assertAlmostEqual(total.shrink_k, 0.45)
        self.assertEqual(total.stake, 0.0)
        self.assertEqual(total.ev_calculation["evLayer"], "pbase_research")
        self.assertAlmostEqual(total.ev_calculation["paperExpectedValue"], 0.05625)
        self.assertFalse(total.ev_calculation["paperSimulationEnabled"])
        self.assertEqual(total.ev_calculation["evDecisionLayer"], "paper_research_open")
        self.assertTrue(any(gate["key"] == "paper_ev" and gate["enabled"] for gate in total.ev_calculation["gates"]))
        self.assertAlmostEqual(total.ev_calculation["positiveReturnProbability"], 0.50)
        self.assertAlmostEqual(settlement["fullWinProbability"], 0.50)
        self.assertAlmostEqual(settlement["halfLossProbability"], 0.25)
        self.assertAlmostEqual(settlement["fullLossProbability"], 0.25)
        self.assertAlmostEqual(total.ev_calculation["winStakeFraction"], 0.50)
        self.assertAlmostEqual(total.ev_calculation["lossStakeFraction"], 0.375)
        self.assertAlmostEqual(total.ev_calculation["breakEvenOdds"], 1.75)

    def test_score_markets_enter_paper_simulation_when_force_picks(self):
        result = PredictionResult(
            match_id="105",
            home_team="A",
            away_team="B",
            expected_goals_home=1.4,
            expected_goals_away=1.2,
            model_probabilities={"home_win": 0.45, "draw": 0.25, "away_win": 0.30},
            market_probabilities=None,
            final_probabilities={"home_win": 0.45, "draw": 0.25, "away_win": 0.30},
            top_scores=[],
            feature_edges={},
        )
        market = MarketSnapshot(
            match_winner={"home_win": 2.30, "draw": 3.50, "away_win": 3.20},
            totals={2.5: {"over": 1.95, "under": 1.95}},
            handicaps={0.0: {"home": 1.95, "away": 1.95}},
        )

        recommendations, portfolio = build_recommendations(
            result,
            score_matrix(1.4, 1.2, 8),
            market,
            bankroll=1000,
            unit_stake=200,
            force_picks=True,
        )

        active = [item for item in recommendations if item.action in {"BUY", "PAPER_BUY"}]
        self.assertEqual(len(active), 3)
        self.assertEqual(recommendations[1].decision_status, "PAPER_OBSERVATION")
        self.assertEqual(recommendations[2].decision_status, "PAPER_OBSERVATION")
        self.assertEqual(recommendations[1].action, "PAPER_BUY")
        self.assertEqual(recommendations[2].action, "PAPER_BUY")
        self.assertIsNotNone(recommendations[1].paper_expected_value_per_unit)
        self.assertIsNotNone(recommendations[2].paper_expected_value_per_unit)
        self.assertAlmostEqual(portfolio.total_stake, 400.0)
        self.assertAlmostEqual(recommendations[0].stake, 400.0 / 3)
        self.assertAlmostEqual(recommendations[1].stake, 400.0 / 3)
        self.assertAlmostEqual(recommendations[2].stake, 400.0 / 3)
        expected_profit = sum(item.stake * (item.paper_expected_value_per_unit or 0.0) for item in active)
        self.assertAlmostEqual(portfolio.expected_profit, expected_profit)


if __name__ == "__main__":
    unittest.main()
