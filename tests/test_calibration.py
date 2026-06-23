import tempfile
import unittest

from worldcup_predictor.backtest import sync_completed_results
from worldcup_predictor.calibration import CalibrationPolicy, build_model_validation_status
from worldcup_predictor.market import MarketSnapshot
from worldcup_predictor.score_calibration import (
    ScoreDistributionCalibrationPolicy,
    apply_score_market_settlement_calibration,
    build_score_distribution_calibration_status,
    market_paper_ev_enabled,
)
from worldcup_predictor.storage import record_api_snapshot, record_match_result, record_prediction
from worldcup_predictor.total_calibration import (
    TotalGoalsCalibrationPolicy,
    apply_total_goals_settlement_calibration,
    build_total_goals_calibration_status,
)


class _CompletedFixtureClient:
    def fixture_by_id(self, fixture_id):
        return {
            "fixture": {"id": fixture_id, "status": {"short": "FT"}},
            "score": {"fulltime": {"home": 2, "away": 1}},
        }


class CalibrationTest(unittest.TestCase):
    def test_time_split_pipeline_excludes_post_kickoff_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/calibration.sqlite3"
            for index in range(5):
                self._record_settled_prediction(db_path, f"F{index}", f"2099-06-{index + 1:02d}T12:00:00+00:00")
            self._record_settled_prediction(db_path, "LEAK", "2000-01-01T12:00:00+00:00")

            status = build_model_validation_status(
                db_path=db_path,
                policy=CalibrationPolicy(
                    min_eligible_samples=5,
                    min_distinct_fixtures=5,
                    min_calibration_samples=1,
                    min_validation_samples=1,
                ),
            )

            self.assertEqual(status["eligibleSamples"], 5)
            self.assertEqual(status["excluded"]["post_kickoff_or_future_odds"], 1)
            self.assertIsNotNone(status["fittedMarketWeight"])
            self.assertEqual(status["split"]["validation"], 1)
            self.assertFalse(status["formalEvEnabled"])

    def test_pshr_candidate_uses_outcome_bias_calibration_not_market_clone(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/pshr.sqlite3"
            for index in range(10):
                self._record_settled_prediction(db_path, f"P{index}", f"2099-06-{index + 1:02d}T12:00:00+00:00")

            status = build_model_validation_status(
                db_path=db_path,
                policy=CalibrationPolicy(
                    min_eligible_samples=10,
                    min_distinct_fixtures=10,
                    min_calibration_samples=2,
                    min_validation_samples=2,
                ),
            )

            parameters = status["pshrParameters"]
            self.assertEqual(parameters["formula"], "outcome_bias_calibrated_pbase")
            self.assertEqual(status["fittedMarketWeight"], 0.0)
            self.assertIsNotNone(status["rawCalibrationMarketWeight"])
            self.assertGreater(parameters["outcome_factors"]["home_win"], 1.0)
            self.assertFalse(status["formalEvEnabled"])

    def test_sync_completed_results_only_uses_existing_pre_match_prediction(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/sync.sqlite3"
            snapshot_id = self._record_prediction(db_path, "991", "2099-07-01T12:00:00+00:00")

            result = sync_completed_results(client=_CompletedFixtureClient(), db_path=db_path)
            status = build_model_validation_status(
                db_path=db_path,
                policy=CalibrationPolicy(
                    min_eligible_samples=1,
                    min_distinct_fixtures=1,
                    min_calibration_samples=1,
                    min_validation_samples=1,
                ),
            )

            self.assertGreater(snapshot_id, 0)
            self.assertEqual(result["synced"], ["991"])
            self.assertEqual(status["eligibleSamples"], 1)

    def test_total_goals_calibration_shrinks_over_when_settled_sample_misses(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/ou.sqlite3"
            for index in range(4):
                fixture_id = f"OU{index}"
                self._record_total_prediction(db_path, fixture_id, "大 2.5", "over", 2.5, 1.90)
                record_match_result(fixture_id, 1, 0, db_path=db_path)

            status = build_total_goals_calibration_status(
                db_path=db_path,
                policy=TotalGoalsCalibrationPolicy(min_total_samples=4, min_side_samples=4),
            )

            over = status["sides"]["over"]
            self.assertEqual(status["sampleCount"], 4)
            self.assertLess(over["positiveFactor"], 1.0)
            self.assertGreater(over["lossFactor"], 1.0)
            self.assertGreater(over["modelBias"], 0)
            self.assertFalse(status["formalEvEnabled"])

    def test_total_goals_calibration_reduces_ev_and_keeps_raw_audit(self):
        status = {
            "version": "test",
            "status": "RESEARCH_READY",
            "sides": {
                "over": {
                    "sideLabel": "大球",
                    "sampleCount": 20,
                    "positiveFactor": 0.80,
                    "winFactor": 0.75,
                    "lossFactor": 1.20,
                    "credibility": 1.0,
                    "actualPositiveRate": 0.48,
                    "meanModelPositiveProbability": 0.60,
                    "modelBias": 0.12,
                }
            },
        }
        settlement = {
            "positive": 0.60,
            "ev": 0.20,
            "win_fraction": 0.60,
            "loss_fraction": 0.30,
            "full_win": 0.55,
            "half_win": 0.05,
            "push": 0.10,
            "half_loss": 0.05,
            "full_loss": 0.25,
            "break_even_odds": 1.50,
        }

        calibrated = apply_total_goals_settlement_calibration(settlement, 1.90, "over", status)

        self.assertLess(calibrated["ev"], settlement["ev"])
        self.assertEqual(calibrated["raw_ev"], settlement["ev"])
        self.assertEqual(calibrated["calibration"]["sideLabel"], "大球")
        self.assertTrue(calibrated["calibration"]["applied"])

    def test_score_distribution_calibration_extracts_ou_and_ah_samples(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/score.sqlite3"
            cases = [
                ("S0", "over", "home", 3, 1),
                ("S1", "under", "away", 0, 1),
                ("S2", "over", "away", 2, 2),
                ("S3", "under", "home", 1, 0),
                ("S4", "over", "home", 2, 1),
                ("S5", "under", "away", 0, 0),
            ]
            for index, (fixture_id, total_side, handicap_side, home_goals, away_goals) in enumerate(cases):
                self._record_score_prediction(
                    db_path,
                    fixture_id,
                    index,
                    total_side,
                    handicap_side,
                    home_goals,
                    away_goals,
                )

            status = build_score_distribution_calibration_status(
                db_path=db_path,
                policy=ScoreDistributionCalibrationPolicy(
                    min_market_samples=6,
                    min_calibration_samples=4,
                    min_validation_samples=2,
                    min_side_samples=2,
                ),
            )

            self.assertEqual(status["sampleCount"], 12)
            self.assertEqual(status["markets"]["OU"]["sampleCount"], 6)
            self.assertEqual(status["markets"]["AH"]["sampleCount"], 6)
            self.assertEqual(status["markets"]["OU"]["split"], {"calibration": 4, "validation": 2})
            self.assertEqual(status["markets"]["AH"]["split"], {"calibration": 4, "validation": 2})
            self.assertNotEqual(status["markets"]["OU"]["status"], "INSUFFICIENT_DATA")
            self.assertNotEqual(status["markets"]["AH"]["status"], "INSUFFICIENT_DATA")
            self.assertFalse(status["formalEvEnabled"])

    def test_score_distribution_paper_ev_opens_only_for_approved_market(self):
        status = {
            "version": "test_score",
            "markets": {
                "OU": {
                    "status": "PAPER_READY",
                    "statusLabel": "大小球独立校准通过",
                    "paperEvEnabled": True,
                    "sides": {
                        "over": {
                            "sideLabel": "大球",
                            "sampleCount": 24,
                            "positiveFactor": 0.80,
                            "winFactor": 0.75,
                            "lossFactor": 1.20,
                        }
                    },
                },
                "AH": {
                    "status": "REJECTED",
                    "statusLabel": "让球独立校准未通过",
                    "paperEvEnabled": False,
                    "sides": {
                        "home": {
                            "sideLabel": "主队让球侧",
                            "sampleCount": 24,
                            "positiveFactor": 0.90,
                            "winFactor": 0.90,
                            "lossFactor": 1.10,
                        }
                    },
                },
            },
        }
        settlement = {
            "positive": 0.60,
            "ev": 0.20,
            "win_fraction": 0.60,
            "loss_fraction": 0.30,
            "full_win": 0.55,
            "half_win": 0.05,
            "push": 0.10,
            "half_loss": 0.05,
            "full_loss": 0.25,
            "break_even_odds": 1.50,
        }

        calibrated = apply_score_market_settlement_calibration(settlement, 1.90, "OU", "over", status)

        self.assertTrue(market_paper_ev_enabled(status, "大小球"))
        self.assertFalse(market_paper_ev_enabled(status, "让球"))
        self.assertLess(calibrated["ev"], settlement["ev"])
        self.assertEqual(calibrated["raw_ev"], settlement["ev"])
        self.assertTrue(calibrated["calibration"]["paperApproved"])
        self.assertFalse(calibrated["calibration"]["formalApproved"])

    def test_rejected_score_distribution_calibration_does_not_rewrite_live_settlement(self):
        status = {
            "version": "test_score",
            "markets": {
                "OU": {
                    "status": "REJECTED",
                    "statusLabel": "大小球独立校准未通过",
                    "paperEvEnabled": False,
                    "sides": {
                        "over": {
                            "sideLabel": "大球",
                            "sampleCount": 24,
                            "positiveFactor": 0.70,
                            "winFactor": 0.70,
                            "lossFactor": 1.30,
                        }
                    },
                },
            },
        }
        settlement = {
            "positive": 0.60,
            "ev": 0.20,
            "win_fraction": 0.60,
            "loss_fraction": 0.30,
            "full_win": 0.55,
            "half_win": 0.05,
            "push": 0.10,
            "half_loss": 0.05,
            "full_loss": 0.25,
            "break_even_odds": 1.50,
        }

        calibrated = apply_score_market_settlement_calibration(settlement, 1.90, "OU", "over", status)

        self.assertEqual(calibrated, settlement)

    def _record_settled_prediction(self, db_path, fixture_id, kickoff):
        self._record_prediction(db_path, fixture_id, kickoff)
        record_match_result(fixture_id, 2, 1, db_path=db_path)

    def _record_prediction(self, db_path, fixture_id, kickoff):
        market = MarketSnapshot(
            fixture_id=None,
            required_bookmaker="Pinnacle",
            selected_bookmaker="Pinnacle",
            captured_at="2026-05-25T00:00:00+00:00",
            match_winner={"home_win": 2.0, "draw": 3.2, "away_win": 3.8},
        )
        snapshot_id = record_api_snapshot(
            fixture_id=fixture_id,
            home_team="A",
            away_team="B",
            source="API-Football",
            fixture={"fixture": {"id": fixture_id, "date": kickoff}},
            odds=[],
            team_stats={},
            h2h=[],
            market=market,
            kickoff_at=kickoff,
            model_version="pbase_test",
            db_path=db_path,
        )
        payload = {
            "mode": "auto",
            "snapshotId": snapshot_id,
            "match": {"id": fixture_id, "home": "A", "away": "B"},
            "probabilities": {
                "pbase": {"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
                "qmkt": {"home_win": 0.48, "draw": 0.30, "away_win": 0.22},
            },
            "portfolio": {"bankroll": 1000, "unit_stake": 10},
        }
        record_prediction(payload, db_path=db_path)
        return snapshot_id

    def _record_total_prediction(self, db_path, fixture_id, selection, side, line, odds):
        kickoff = "2099-07-01T12:00:00+00:00"
        market = MarketSnapshot(
            fixture_id=None,
            required_bookmaker="Pinnacle",
            selected_bookmaker="Pinnacle",
            captured_at="2026-05-25T00:00:00+00:00",
            match_winner={"home_win": 2.0, "draw": 3.2, "away_win": 3.8},
            totals={line: {"over": 1.90, "under": 1.95}},
        )
        snapshot_id = record_api_snapshot(
            fixture_id=fixture_id,
            home_team="A",
            away_team="B",
            source="API-Football",
            fixture={"fixture": {"id": fixture_id, "date": kickoff}},
            odds=[],
            team_stats={},
            h2h=[],
            market=market,
            kickoff_at=kickoff,
            model_version="pbase_test",
            db_path=db_path,
        )
        payload = {
            "mode": "auto",
            "snapshotId": snapshot_id,
            "match": {"id": fixture_id, "home": "A", "away": "B"},
            "probabilities": {
                "pbase": {"home_win": 0.45, "draw": 0.25, "away_win": 0.30},
                "qmkt": {"home_win": 0.42, "draw": 0.28, "away_win": 0.30},
            },
            "recommendations": [
                {
                    "market": "大小球",
                    "selection": selection,
                    "line": line,
                    "odds": odds,
                    "model_probability": 0.70,
                    "market_probability": 0.50,
                    "expected_value_per_unit": 0.33,
                    "ev_pbase_research": 0.33,
                    "action": "WATCH",
                    "signal_status": "RESEARCH_WATCH",
                    "ev_calculation": {
                        "type": "OU",
                        "positiveReturnProbability": 0.70,
                        "winStakeFraction": 0.70,
                        "lossStakeFraction": 0.30,
                        "expectedValue": 0.33,
                    },
                }
            ],
            "portfolio": {"bankroll": 1000, "unit_stake": 10},
        }
        record_prediction(payload, db_path=db_path)
        return snapshot_id

    def _record_score_prediction(
        self,
        db_path,
        fixture_id,
        index,
        total_side,
        handicap_side,
        home_goals,
        away_goals,
    ):
        kickoff = f"2099-07-{index + 1:02d}T12:00:00+00:00"
        market = MarketSnapshot(
            fixture_id=None,
            required_bookmaker="Pinnacle",
            selected_bookmaker="Pinnacle",
            captured_at="2026-05-25T00:00:00+00:00",
            match_winner={"home_win": 2.0, "draw": 3.2, "away_win": 3.8},
            totals={2.5: {"over": 1.90, "under": 1.95}},
            handicaps={-0.5: {"home": 1.90, "away": 1.95}},
        )
        snapshot_id = record_api_snapshot(
            fixture_id=fixture_id,
            home_team="A",
            away_team="B",
            source="API-Football",
            fixture={"fixture": {"id": fixture_id, "date": kickoff}},
            odds=[],
            team_stats={},
            h2h=[],
            market=market,
            kickoff_at=kickoff,
            model_version="pbase_test",
            db_path=db_path,
        )
        total_selection = "大 2.5" if total_side == "over" else "小 2.5"
        handicap_selection = "A -0.5" if handicap_side == "home" else "B +0.5"
        payload = {
            "mode": "auto",
            "snapshotId": snapshot_id,
            "match": {"id": fixture_id, "home": "A", "away": "B"},
            "probabilities": {
                "pbase": {"home_win": 0.45, "draw": 0.25, "away_win": 0.30},
                "qmkt": {"home_win": 0.42, "draw": 0.28, "away_win": 0.30},
            },
            "recommendations": [
                {
                    "market": "大小球",
                    "selection": total_selection,
                    "line": 2.5,
                    "odds": 1.90 if total_side == "over" else 1.95,
                    "model_probability": 0.62,
                    "market_probability": 0.51,
                    "expected_value_per_unit": 0.18,
                    "ev_pbase_research": 0.18,
                    "action": "WATCH",
                    "signal_status": "RESEARCH_WATCH",
                    "ev_calculation": {
                        "type": "OU",
                        "positiveReturnProbability": 0.62,
                        "winStakeFraction": 0.62,
                        "lossStakeFraction": 0.38,
                        "expectedValue": 0.18,
                    },
                },
                {
                    "market": "让球",
                    "selection": handicap_selection,
                    "line": -0.5,
                    "odds": 1.90 if handicap_side == "home" else 1.95,
                    "model_probability": 0.58,
                    "market_probability": 0.50,
                    "expected_value_per_unit": 0.10,
                    "ev_pbase_research": 0.10,
                    "action": "WATCH",
                    "signal_status": "RESEARCH_WATCH",
                    "ev_calculation": {
                        "type": "AH",
                        "positiveReturnProbability": 0.58,
                        "winStakeFraction": 0.58,
                        "lossStakeFraction": 0.42,
                        "expectedValue": 0.10,
                    },
                },
            ],
            "portfolio": {"bankroll": 1000, "unit_stake": 10},
        }
        record_prediction(payload, db_path=db_path)
        record_match_result(fixture_id, home_goals, away_goals, db_path=db_path)
        return snapshot_id


if __name__ == "__main__":
    unittest.main()
