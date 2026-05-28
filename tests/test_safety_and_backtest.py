import math
import tempfile
import unittest
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from worldcup_predictor.backtest import (
    brier_score,
    log_loss,
    max_drawdown,
    performance_metrics,
    settle_prediction_payload,
)
from worldcup_predictor.betting import BetRecommendation, PaperPortfolio, build_recommendations
from worldcup_predictor.auto_predict import (
    MIN_VALID_RECENT_MATCHES,
    _neutral_site_for_fixture,
    _profile_from_api,
    _validate_pre_match_fixture,
    _valid_recent_matches,
)
from worldcup_predictor.api_football import ApiTeam
from worldcup_predictor.data_quality import apply_quality_gate, build_data_quality_report
from worldcup_predictor.market import MarketSnapshot
from worldcup_predictor.models import PredictionResult
from worldcup_predictor.storage import (
    connect,
    get_api_snapshot,
    market_quotes_for_snapshot,
    recent_predictions,
    record_api_snapshot,
    record_match_result,
    record_prediction,
)
from worldcup_predictor.web_server import _form_series_payload, _is_pre_match_fixture, run_sample_prediction, today_fixture_options


class SafetyAndBacktestTest(unittest.TestCase):
    def test_recent_form_uses_90_minute_scores_and_requires_five_valid_matches(self):
        rows = []
        for index in range(MIN_VALID_RECENT_MATCHES):
            rows.append(
                {
                    "fixture": {"id": index, "status": {"short": "FT"}, "date": f"2026-05-{index + 1:02d}"},
                    "league": {"name": "1. Division", "country": "Kazakhstan"},
                    "teams": {"home": {"id": 10, "name": "Astana II"}, "away": {"id": 20, "name": "Khan Tengri"}},
                    "score": {"fulltime": {"home": 2, "away": 1}},
                }
            )
        rows.append(
            {
                "fixture": {"id": 99, "status": {"short": "NS"}},
                "teams": {"home": {"id": 10}, "away": {"id": 20}},
                "score": {"fulltime": {"home": None, "away": None}},
            }
        )

        recent = _valid_recent_matches(rows, 10)
        profile = _profile_from_api(ApiTeam(id=10, name="A"), None, recent)

        self.assertEqual(len(recent), MIN_VALID_RECENT_MATCHES)
        self.assertEqual(recent[0]["goals_for"], 2)
        self.assertEqual(recent[0]["opponent_zh"], "汗腾格里")
        self.assertEqual(recent[0]["league_zh"], "哈萨克斯坦足球甲级联赛")
        self.assertGreater(profile.attack_rating, 1.0)

        processed = _form_series_payload("Astana II", "主队", recent)
        self.assertEqual(processed["validCount"], MIN_VALID_RECENT_MATCHES)
        self.assertAlmostEqual(processed["pointsPerGame"], 3.0)
        self.assertEqual(processed["matches"][-1]["cumulativePoints"], 15)

    def test_non_world_cup_match_is_not_assumed_neutral(self):
        self.assertFalse(_neutral_site_for_fixture({"name": "Serie A"}))
        self.assertFalse(_neutral_site_for_fixture({"name": "World Cup - Qualification"}))
        self.assertTrue(_neutral_site_for_fixture({"name": "World Cup"}))

    def test_prediction_snapshot_must_be_created_before_kickoff(self):
        now = datetime(2026, 5, 26, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        _validate_pre_match_fixture(
            {"date": "2026-05-27T12:00:00+08:00", "status": {"short": "NS"}},
            now=now,
        )
        with self.assertRaises(ValueError):
            _validate_pre_match_fixture(
                {"date": "2026-05-25T12:00:00+08:00", "status": {"short": "FT"}},
                now=now,
            )

    def test_random_today_filter_allows_only_future_pre_match_fixtures(self):
        now = datetime(2026, 5, 22, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))
        future = (now + timedelta(hours=2)).isoformat()
        past = (now - timedelta(hours=2)).isoformat()

        self.assertTrue(_is_pre_match_fixture({"fixture": {"date": future, "status": {"short": "NS"}}}, now))
        self.assertFalse(_is_pre_match_fixture({"fixture": {"date": future, "status": {"short": "FT"}}}, now))
        self.assertFalse(_is_pre_match_fixture({"fixture": {"date": past, "status": {"short": "NS"}}}, now))

    def test_today_first_division_options_use_future_fixture_and_chinese_league(self):
        now = datetime(2026, 5, 26, 12, 0, tzinfo=ZoneInfo("Asia/Shanghai"))

        class FixtureClient:
            def fixtures_by_date(self, date):
                return [
                    {
                        "fixture": {"id": 1, "date": "2026-05-26T20:00:00+08:00", "status": {"short": "NS"}},
                        "league": {"name": "1. Division", "country": "Kazakhstan"},
                        "teams": {"home": {"name": "Astana II"}, "away": {"name": "Khan Tengri"}},
                    },
                    {
                        "fixture": {"id": 2, "date": "2026-05-26T21:00:00+08:00", "status": {"short": "NS"}},
                        "league": {"name": "League Two", "country": "China"},
                        "teams": {"home": {"name": "A"}, "away": {"name": "B"}},
                    },
                ]

        result = today_fixture_options("2026-05-26", client=FixtureClient(), now=now)

        self.assertEqual(result["count"], 1)
        self.assertEqual(result["fixtures"][0]["leagueZh"], "哈萨克斯坦足球甲级联赛")
        self.assertEqual(result["fixtures"][0]["homeZh"], "阿斯塔纳二队")

    def test_match_result_preserves_away_win_score(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            record_match_result(888, 1, 3, db_path=db_path)

            with connect(db_path) as conn:
                row = conn.execute(
                    "SELECT home_goals_90, away_goals_90 FROM match_results WHERE fixture_id = ?",
                    ("888",),
                ).fetchone()

            self.assertEqual((row["home_goals_90"], row["away_goals_90"]), (1, 3))

    def test_quality_cap_for_missing_team_rating_downgrades_buy(self):
        market = MarketSnapshot(
            bookmakers_count=8,
            match_winner={"home_win": 2.2, "draw": 3.2, "away_win": 3.4},
            totals={2.5: {"over": 1.95, "under": 1.9}},
            handicaps={-0.5: {"home": 2.05, "away": 1.85}},
        )
        quality = build_data_quality_report(
            market,
            fixture_id=100,
            team_rating_score=0.45,
            context_score=0.75,
            lineup_score=0.0,
            min_quality=0.60,
            max_score=0.59,
        )
        recommendation = BetRecommendation(
            market="胜平负",
            selection="主胜",
            line=None,
            odds=2.2,
            model_probability=0.52,
            market_probability=0.45,
            edge=0.07,
            expected_value_per_unit=0.14,
            stake=10,
            action="BUY",
            reason="正期望。",
        )
        portfolio = PaperPortfolio(1000, 10, 1, 10, 990, 1.4, 1001.4)

        adjusted, gated = apply_quality_gate([recommendation], portfolio, quality, enforce=True)

        self.assertLess(quality.score, quality.min_quality)
        self.assertEqual(adjusted[0].action, "WATCH")
        self.assertEqual(gated.active_bets, 0)
        self.assertIn("近期有效比赛准入条件", " ".join(quality.notes))

    def test_missing_market_has_no_allocated_stake(self):
        result = PredictionResult(
            match_id="empty-market",
            home_team="A",
            away_team="B",
            expected_goals_home=1.0,
            expected_goals_away=1.0,
            model_probabilities={"home_win": 0.35, "draw": 0.30, "away_win": 0.35},
            market_probabilities=None,
            final_probabilities={"home_win": 0.35, "draw": 0.30, "away_win": 0.35},
            top_scores=[],
            feature_edges={},
        )
        recommendations, portfolio = build_recommendations(
            result,
            {},
            MarketSnapshot(),
            bankroll=1000,
            unit_stake=10,
        )

        self.assertTrue(all(item.action == "NO_MARKET" and item.stake == 0 for item in recommendations))
        self.assertEqual(portfolio.total_stake, 0)

    def test_api_snapshot_can_be_recorded_and_read(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            snapshot_id = record_api_snapshot(
                fixture_id=123,
                home_team="A",
                away_team="B",
                source="API-Football",
                fixture={"fixture": {"id": 123}},
                odds=[{"bookmakers": []}],
                team_stats={"home": {"fixtures": {}}, "away": None},
                h2h=[],
                notes=["赔率数据不可用"],
                db_path=db_path,
            )
            snapshot = get_api_snapshot(snapshot_id, db_path=db_path)

            self.assertEqual(snapshot["fixture_id"], "123")
            self.assertEqual(snapshot["fixture_json"]["fixture"]["id"], 123)
            self.assertIn("赔率数据不可用", snapshot["notes"])

    def test_prediction_records_snapshot_id(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = run_sample_prediction(match_id="MEX-USA")
            payload["snapshotId"] = 77

            record_prediction(payload, db_path=db_path)
            recent = recent_predictions(db_path=db_path)

            self.assertEqual(recent[0]["snapshot_id"], 77)

    def test_structured_market_quotes_are_recorded_for_snapshot(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            snapshot_id = record_api_snapshot(
                fixture_id=321,
                home_team="A",
                away_team="B",
                source="API-Football",
                fixture={"fixture": {"id": 321, "date": "2099-06-01T12:00:00+00:00"}},
                odds=[],
                team_stats={},
                h2h=[],
                market=MarketSnapshot(
                    fixture_id=321,
                    required_bookmaker="Pinnacle",
                    selected_bookmaker="Pinnacle",
                    captured_at="2026-05-25T00:00:00+00:00",
                    match_winner={"home_win": 2.0, "draw": 3.2, "away_win": 3.8},
                    totals={2.5: {"over": 1.91, "under": 1.95}},
                    handicaps={-0.5: {"home": 2.05, "away": 1.85}},
                ),
                kickoff_at="2099-06-01T12:00:00+00:00",
                model_version="pbase_test",
                db_path=db_path,
            )

            quotes = market_quotes_for_snapshot(snapshot_id, db_path=db_path)

            self.assertEqual(len(quotes), 7)
            self.assertTrue(all(item["bookmaker"] == "Pinnacle" for item in quotes))
            self.assertTrue(any(item["selection_key"] == "321:FT:1X2:-:home_win" for item in quotes))

    def test_backtest_probability_metrics_are_correct(self):
        probabilities = {"home_win": 0.7, "draw": 0.2, "away_win": 0.1}

        self.assertAlmostEqual(brier_score(probabilities, "home_win"), 0.14)
        self.assertAlmostEqual(log_loss(probabilities, "home_win"), -math.log(0.7))

    def test_backtest_roi_and_drawdown_use_profit_and_stake(self):
        metrics = performance_metrics(
            [
                {"totalBets": 1, "winningBets": 1, "totalStake": 10, "totalProfit": 10, "brierScore": 0.1, "logLoss": 0.2},
                {"totalBets": 1, "winningBets": 0, "totalStake": 5, "totalProfit": -5, "brierScore": 0.3, "logLoss": 0.4},
            ]
        )

        self.assertAlmostEqual(metrics["roi"], 5 / 15)
        self.assertAlmostEqual(metrics["maxDrawdown"], 5)
        self.assertAlmostEqual(metrics["brierScore"], 0.2)
        self.assertAlmostEqual(metrics["logLoss"], 0.3)

    def test_settle_prediction_payload_handles_1x2_buy(self):
        payload = {
            "runId": 1,
            "match": {"id": "100", "home": "Mexico", "away": "USA", "homeZh": "墨西哥", "awayZh": "美国"},
            "probabilities": {"model": {"home_win": 0.5, "draw": 0.3, "away_win": 0.2}},
            "recommendations": [
                {
                    "market": "胜平负",
                    "selection": "墨西哥 胜",
                    "stake": 10,
                    "odds": 2.2,
                    "action": "BUY",
                }
            ],
        }

        settled = settle_prediction_payload(payload, 1, 0)

        self.assertEqual(settled["totalBets"], 1)
        self.assertAlmostEqual(settled["totalProfit"], 12.0)
        self.assertAlmostEqual(settled["roi"], 1.2)


if __name__ == "__main__":
    unittest.main()
