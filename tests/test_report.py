import unittest

from worldcup_predictor.report import build_chinese_report, build_excel_report, build_pdf_report
from worldcup_predictor.web_server import run_sample_prediction


class ReportTest(unittest.TestCase):
    def test_chinese_report_contains_core_sections(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["runId"] = 1

        report = build_chinese_report(payload)

        self.assertIn("世界杯预测报告", report)
        self.assertIn("预测口径：90 分钟赛果", report)
        self.assertIn("模拟舱", report)
        self.assertIn("数据质量与市场完整性", report)
        self.assertIn("展示融合概率（非 pfinal）", report)
        self.assertIn("正式 EV 状态", report)
        self.assertIn("胜平负", report)
        self.assertIn("墨西哥", report)
        self.assertIn("美国", report)
        self.assertIn("国际友谊赛", report)
        self.assertIn("北京时间", report)

    def test_report_exports_excel_and_pdf(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["runId"] = 1

        excel_bytes = build_excel_report(payload)
        pdf_bytes = build_pdf_report(payload)

        self.assertTrue(excel_bytes.startswith(b"PK"))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))
        self.assertGreater(len(excel_bytes), 1000)
        self.assertGreater(len(pdf_bytes), 1000)

    def test_report_relocalizes_old_payload_names(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["match"] = {
            "id": 1,
            "home": "Osipovichy",
            "away": "Minsk II",
            "homeZh": "Osipovichy",
            "awayZh": "Minsk II",
        }
        payload["meta"]["leagueName"] = "1. Division"
        payload["meta"]["leagueNameZh"] = "1. Division"
        payload["meta"]["leagueCountry"] = "Belarus"

        report = build_chinese_report(payload)

        self.assertIn("奥西波维奇", report)
        self.assertIn("明斯克二队", report)
        self.assertIn("白俄罗斯足球甲级联赛", report)
        self.assertNotIn("Osipovichy vs Minsk II", report)

    def test_report_restores_unmapped_api_names_from_old_placeholders(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["match"] = {
            "id": 2,
            "home": "Novosibirsk",
            "away": "Veles",
            "homeZh": "主队（名称待核定）",
            "awayZh": "客队（名称待核定）",
        }
        payload["meta"]["leagueName"] = "Second League A"
        payload["meta"]["leagueNameZh"] = "赛事名称待核定"
        payload["dataProcessing"] = {
            "home": {"rawName": "Novosibirsk", "displayName": "主队（名称待核定）", "matches": []},
            "away": {"rawName": "Veles", "displayName": "客队（名称待核定）", "matches": []},
        }
        payload["notes"] = ["近期比赛有效覆盖：主队（名称待核定） 10/10 场，客队（名称待核定） 10/10 场。"]

        report = build_chinese_report(payload)

        self.assertIn("Novosibirsk vs Veles", report)
        self.assertIn("Second League A", report)
        self.assertNotIn("名称待核定", report)

    def test_report_distinguishes_priority_and_received_bookmaker(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["meta"]["requiredBookmaker"] = "Pinnacle"
        payload["meta"]["bookmakerPriority"] = ["Pinnacle"]
        payload["meta"]["selectedBookmakers"] = {}
        payload["meta"]["bookmaker"] = "未取得"
        payload["market"]["requiredBookmaker"] = "Pinnacle"
        payload["market"]["bookmakerPriority"] = ["Pinnacle"]
        payload["market"]["selectedBookmakers"] = {}
        payload["market"]["selectedBookmaker"] = None

        report = build_chinese_report(payload)

        self.assertIn("庄家优先级：Pinnacle", report)
        self.assertIn("实际盘口庄家：未取得", report)

    def test_report_includes_data_processing_audit_when_available(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["dataProcessing"] = {
            "home": {
                "displayName": "墨西哥",
                "validCount": 5,
                "pointsPerGame": 2.0,
                "goalsForAverage": 1.6,
                "goalsAgainstAverage": 0.8,
                "attackRating": 1.44,
                "defenseRating": 1.19,
                "matches": [],
            },
            "away": {
                "displayName": "美国",
                "validCount": 5,
                "pointsPerGame": 1.6,
                "goalsForAverage": 1.2,
                "goalsAgainstAverage": 1.0,
                "attackRating": 1.22,
                "defenseRating": 1.10,
                "matches": [],
            },
            "oddsTrend": {"message": "仅保存单次赛前赔率快照，不能形成真实赔率走势曲线。"},
        }

        report = build_chinese_report(payload)

        self.assertIn("数据处理审计", report)
        self.assertIn("仅保存单次赛前赔率快照", report)
        self.assertIn("| 墨西哥 | 5 |", report)
        self.assertIn("| 美国 | 5 |", report)

    def test_report_hides_suspended_ev_and_keeps_audit_appendix(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        item = payload["recommendations"][0]
        item["ev_status"] = "SUSPENDED_MODEL_DIVERGENCE"
        item["audit_expected_value_per_unit"] = 0.6314
        item["audit_conservative_expected_value_per_unit"] = 0.5129
        item["expected_value_per_unit"] = None
        item["conservative_expected_value_per_unit"] = None
        payload["modelAudit"] = {"statusLabel": "模型分歧异常", "evSuspended": True}

        report = build_chinese_report(payload)
        excel_bytes = build_excel_report(payload)
        pdf_bytes = build_pdf_report(payload)

        self.assertIn("模型分歧状态：模型分歧异常", report)
        self.assertIn("模型异常审计附录", report)
        self.assertIn("暂停", report)
        self.assertIn("63.1%", report)
        self.assertTrue(excel_bytes.startswith(b"PK"))
        self.assertTrue(pdf_bytes.startswith(b"%PDF"))

    def test_report_reclassifies_historical_divergent_payload_without_mutating_source(self):
        payload = run_sample_prediction(match_id="MEX-USA", bankroll=1000, unit_stake=10)
        payload["match"] = {
            "id": "1545408",
            "home": "Saint Etienne",
            "away": "Nice",
            "homeZh": "Saint Etienne",
            "awayZh": "Nice",
        }
        payload["recommendations"][0]["selection"] = "Saint Etienne 胜"
        payload["meta"]["requiredBookmaker"] = "Pinnacle"
        payload["probabilities"]["pbase"] = {"home_win": 0.6884, "draw": 0.1776, "away_win": 0.1340}
        payload["probabilities"]["qmkt"] = {"home_win": 0.4061, "draw": 0.2814, "away_win": 0.3125}
        payload["recommendations"][0]["expected_value_per_unit"] = 0.6314
        payload["recommendations"][0]["conservative_expected_value_per_unit"] = 0.5129

        report = build_chinese_report(payload)

        self.assertIn("模型分歧状态：模型分歧异常", report)
        self.assertIn("模型异常审计附录", report)
        self.assertIn("圣埃蒂安 胜", report)
        self.assertIn("暂停", report)
        self.assertEqual(payload["recommendations"][0]["expected_value_per_unit"], 0.6314)


if __name__ == "__main__":
    unittest.main()
