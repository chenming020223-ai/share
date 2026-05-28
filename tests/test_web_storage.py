import tempfile
import unittest

from worldcup_predictor.storage import recent_predictions, record_prediction, storage_health
from worldcup_predictor.web_server import run_sample_prediction


class WebStorageTest(unittest.TestCase):
    def test_sample_prediction_payload_can_be_recorded(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)

            run_id = record_prediction(payload, db_path=db_path)
            recent = recent_predictions(db_path=db_path)
            health = storage_health(db_path=db_path)

            self.assertGreater(run_id, 0)
            self.assertEqual(len(recent), 1)
            self.assertEqual(recent[0]["home_team"], "Mexico")
            self.assertEqual(payload["match"]["homeZh"], "墨西哥")
            self.assertEqual(payload["match"]["awayZh"], "美国")
            self.assertEqual(payload["meta"]["leagueNameZh"], "国际友谊赛")
            self.assertIn("北京时间", payload["meta"]["kickoffBeijing"])
            self.assertEqual(payload["dataQuality"]["grade"], "DEMO")
            self.assertEqual(len(payload["dataQuality"]["markets"]), 3)
            self.assertEqual(health["prediction_runs"], 1)


if __name__ == "__main__":
    unittest.main()
