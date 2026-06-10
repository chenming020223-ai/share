import tempfile
import unittest

from worldcup_predictor.live_readiness import build_live_readiness_status
from worldcup_predictor.storage import storage_health


class LiveReadinessTest(unittest.TestCase):
    def test_empty_project_is_blocked_for_real_money(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            status = build_live_readiness_status(db_path=db_path)

        self.assertEqual(status["status"], "BLOCKED")
        self.assertFalse(status["canUseRealMoney"])
        self.assertIn("禁止真实下注", status["realMoneyLabel"])
        self.assertIn("正式 pfinal 概率", status["blockingReasons"])
        self.assertIn("大小球/让球专项校准", status["blockingReasons"])

    def test_ready_gate_still_requires_manual_real_money_switch(self):
        model_validation = {
            "status": "ELIGIBLE_FOR_REVIEW",
            "statusLabel": "待人工审批",
            "formalEvEnabled": True,
            "pfinalStatus": "approved",
            "eligibleSamples": 120,
            "distinctFixtures": 120,
        }
        storage = {
            "market_quotes": 1500,
            "prediction_runs": 120,
            "api_snapshots": 120,
            "match_results": 120,
        }
        bankroll_timeline = {
            "summary": {"openCount": 0, "riskMode": "normal", "riskLabel": "正常"},
            "events": [
                {
                    "eventType": "SETTLE",
                    "stake": 100,
                    "profit": 5,
                    "drawdownPct": 0.03,
                }
                for _ in range(60)
            ],
        }
        status = build_live_readiness_status(
            model_validation=model_validation,
            storage=storage,
            bankroll_timeline=bankroll_timeline,
        )

        self.assertEqual(status["status"], "BLOCKED")
        self.assertFalse(status["canUseRealMoney"])
        self.assertIn("大小球/让球专项校准", status["blockingReasons"])

    def test_storage_health_can_be_used_as_input(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            health = storage_health(db_path=db_path)
            status = build_live_readiness_status(storage=health)

        self.assertEqual(status["storage"]["prediction_runs"], 0)


if __name__ == "__main__":
    unittest.main()
