import tempfile
import unittest

from worldcup_predictor.storage import (
    connect,
    get_batch_prediction_payload,
    mark_official_batch,
    official_batch_for_date,
    recent_batch_predictions,
    recent_predictions,
    record_batch_prediction,
    record_prediction,
    storage_health,
    update_batch_metadata,
)
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

    def test_only_active_paper_buys_are_written_to_ledger(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "mode": "auto",
                "match": {"id": "100", "home": "A", "away": "B"},
                "market": {"selectedBookmakers": {"1X2": "Bet365"}},
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "active_bets": 1, "total_stake": 200, "expected_profit": 12},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "A 胜",
                        "line": None,
                        "odds": 2.1,
                        "model_probability": 0.55,
                        "market_probability": 0.48,
                        "expected_value_per_unit": 0.155,
                        "ev_pbase_research": 0.155,
                        "stake": 200,
                        "action": "BUY",
                        "signal_status": "MODEL_CANDIDATE",
                        "reason": "测试",
                    },
                    {
                        "market": "大小球",
                        "selection": "大 2.5",
                        "line": 2.5,
                        "odds": 1.95,
                        "model_probability": 0.55,
                        "market_probability": 0.50,
                        "expected_value_per_unit": 0.0725,
                        "ev_pbase_research": 0.0725,
                        "stake": 200,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                        "reason": "纸上模拟",
                    },
                    {"market": "大小球", "selection": "观望", "stake": 0, "action": "WATCH"},
                ],
            }

            record_prediction(payload, db_path=db_path)

            with connect(db_path) as conn:
                rows = conn.execute(
                    "SELECT market, bookmaker, stake, signal_status, ev_pbase_research FROM paper_bankroll_ledger"
                ).fetchall()

            self.assertEqual(len(rows), 1)
            self.assertEqual(rows[0]["market"], "大小球")
            self.assertEqual(rows[0]["bookmaker"], "")
            self.assertEqual(rows[0]["stake"], 200)
            self.assertEqual(rows[0]["signal_status"], "PAPER_BUY")
            self.assertAlmostEqual(rows[0]["ev_pbase_research"], 0.0725)

    def test_batch_prediction_payload_can_be_recorded_and_restored(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "date": "2026-06-03",
                "scope": "first_division",
                "fixtureIds": [101, 102],
                "collectedCount": 1,
                "failedCount": 1,
                "batchSummary": {
                    "success": 1,
                    "failed": 1,
                    "signalCount": 1,
                    "expectedProfit": 18.0,
                    "portfolioPlan": {
                        "plannedStake": 200.0,
                        "expectedProfit": 18.0,
                    },
                },
                "collected": [{"runId": 7, "home": "A", "away": "B"}],
                "failed": [{"fixtureId": 102, "failureLabel": "盘口缺失"}],
            }

            batch_id = record_batch_prediction(payload, db_path=db_path)
            recent = recent_batch_predictions(db_path=db_path)
            restored = get_batch_prediction_payload(batch_id, db_path=db_path)
            health = storage_health(db_path=db_path)

            self.assertGreater(batch_id, 0)
            self.assertEqual(payload["batchRunId"], batch_id)
            self.assertEqual(recent[0]["id"], batch_id)
            self.assertEqual(recent[0]["collected_count"], 1)
            self.assertEqual(recent[0]["signal_count"], 1)
            self.assertEqual(restored["batchRunId"], batch_id)
            self.assertEqual(restored["failed"][0]["failureLabel"], "盘口缺失")
            self.assertEqual(health["batch_runs"], 1)

            updated = update_batch_metadata(batch_id, "0603 今日甲级批次", "盘口优先级完整，后续复盘。", db_path=db_path)
            recent_after_update = recent_batch_predictions(db_path=db_path)
            restored_after_update = get_batch_prediction_payload(batch_id, db_path=db_path)

            self.assertEqual(updated["batchTitle"], "0603 今日甲级批次")
            self.assertEqual(recent_after_update[0]["title"], "0603 今日甲级批次")
            self.assertEqual(recent_after_update[0]["notes"], "盘口优先级完整，后续复盘。")
            self.assertEqual(restored_after_update["batchTitle"], "0603 今日甲级批次")
            self.assertEqual(restored_after_update["batchNotes"], "盘口优先级完整，后续复盘。")

    def test_only_one_official_batch_per_date_and_scope(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            first = record_batch_prediction(
                {
                    "date": "2026-06-03",
                    "scope": "first_division",
                    "fixtureIds": [101],
                    "collectedCount": 1,
                    "batchSummary": {"success": 1, "failed": 0, "portfolioPlan": {}},
                    "collected": [{"runId": 1}],
                },
                db_path=db_path,
            )
            second = record_batch_prediction(
                {
                    "date": "2026-06-03",
                    "scope": "first_division",
                    "fixtureIds": [102],
                    "collectedCount": 1,
                    "batchSummary": {"success": 1, "failed": 0, "portfolioPlan": {}},
                    "collected": [{"runId": 2}],
                },
                db_path=db_path,
            )

            mark_official_batch(first, db_path=db_path)
            mark_official_batch(second, db_path=db_path)

            official = official_batch_for_date("2026-06-03", scope="first_division", db_path=db_path)
            recent = recent_batch_predictions(limit=2, db_path=db_path)

            self.assertEqual(official["batchRunId"], second)
            self.assertTrue(recent[0]["is_official"])
            self.assertFalse(recent[1]["is_official"])


if __name__ == "__main__":
    unittest.main()
