import tempfile
import unittest

from worldcup_predictor.backtest import sync_completed_results
from worldcup_predictor.calibration import CalibrationPolicy, build_model_validation_status
from worldcup_predictor.market import MarketSnapshot
from worldcup_predictor.storage import record_api_snapshot, record_match_result, record_prediction


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


if __name__ == "__main__":
    unittest.main()
