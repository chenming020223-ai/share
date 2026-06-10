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
    run_auto_prediction,
)
from worldcup_predictor.api_football import ApiTeam
from worldcup_predictor.data_quality import apply_quality_gate, build_data_quality_report
from worldcup_predictor.market import MarketSnapshot
from worldcup_predictor.models import PredictionResult
from worldcup_predictor.paper_bankroll import build_paper_bankroll_timeline
from worldcup_predictor.review import (
    _line_key,
    _market_line_key,
    _selection_display,
    build_daily_review,
    build_daily_review_excel,
)
from worldcup_predictor.storage import (
    connect,
    get_api_snapshot,
    market_quotes_for_snapshot,
    recent_predictions,
    record_api_snapshot,
    record_batch_prediction,
    record_match_result,
    record_prediction,
    settle_open_paper_ledger,
)
from worldcup_predictor.web_server import (
    _batch_portfolio_plan,
    _batch_recommendation_summary,
    _classify_batch_failure,
    _form_series_payload,
    _is_pre_match_fixture,
    _parse_fixture_ids,
    run_sample_prediction,
    today_fixture_options,
)


class DeepFixtureClient:
    def __init__(self):
        self.logical_requests = 0
        self.http_attempts = 0
        self.statistics_calls = 0

    def _count(self):
        self.logical_requests += 1
        self.http_attempts += 1

    def fixture_by_id(self, fixture_id):
        self._count()
        return {
            "fixture": {
                "id": fixture_id,
                "date": "2099-06-01T12:00:00+00:00",
                "status": {"short": "NS"},
                "venue": {"name": "Test Stadium", "city": "Test City"},
            },
            "league": {"id": 1, "season": 2099, "name": "1. Division", "country": "Kazakhstan"},
            "teams": {"home": {"id": 10, "name": "Home FC"}, "away": {"id": 20, "name": "Away FC"}},
        }

    def odds(self, fixture_id):
        self._count()
        return []

    def team_last_fixtures(self, team_id, limit, timezone="Asia/Shanghai"):
        self._count()
        opponent_id = 30 if team_id == 10 else 40
        rows = []
        for index in range(5):
            rows.append(
                {
                    "fixture": {"id": team_id * 100 + index, "status": {"short": "FT"}, "date": f"2099-05-{index + 1:02d}T12:00:00+00:00"},
                    "league": {"name": "1. Division", "country": "Kazakhstan"},
                    "teams": {"home": {"id": team_id, "name": "Home FC" if team_id == 10 else "Away FC"}, "away": {"id": opponent_id, "name": "Opponent"}},
                    "score": {"fulltime": {"home": 2, "away": 1}},
                }
            )
        return rows

    def team_statistics(self, league_id, season, team_id):
        self._count()
        return {"fixtures": {"played": {"total": 10}, "wins": {"total": 5}, "draws": {"total": 2}}, "goals": {"for": {"average": {"total": "1.5"}}, "against": {"average": {"total": "1.0"}}}}

    def last_head_to_head(self, team_a_id, team_b_id):
        self._count()
        return []

    def fixture_statistics(self, fixture_id):
        self._count()
        self.statistics_calls += 1
        return [
            {
                "team": {"id": fixture_id // 100},
                "statistics": [
                    {"type": "Total Shots", "value": 12},
                    {"type": "Shots on Goal", "value": 5},
                    {"type": "Ball Possession", "value": "58%"},
                    {"type": "Expected Goals", "value": "1.42"},
                ],
            },
            {
                "team": {"id": 9999},
                "statistics": [{"type": "Expected Goals", "value": "0.91"}],
            },
        ]

    def fixture_events(self, fixture_id):
        self._count()
        return [
            {"team": {"id": fixture_id // 100}, "type": "Card", "detail": "Red Card"},
            {"team": {"id": fixture_id // 100}, "type": "Goal", "detail": "Penalty"},
        ]


class SafetyAndBacktestTest(unittest.TestCase):
    def test_deep_mode_enriches_recent_matches_with_fixture_statistics(self):
        client = DeepFixtureClient()

        result = run_auto_prediction(
            "Home FC",
            "Away FC",
            fixture_id=999,
            collection_mode="deep",
            client=client,
        )
        home_recent = result.raw_snapshot["recent_form"]["home"]

        self.assertEqual(result.collection_mode, "deep")
        self.assertGreater(result.deep_stats_matches, 0)
        self.assertEqual(home_recent[0]["shots"], 12)
        self.assertEqual(home_recent[0]["shots_on_target"], 5)
        self.assertEqual(home_recent[0]["possession_pct"], 58)
        self.assertEqual(home_recent[0]["red_cards"], 1)

    def test_fast_mode_skips_deep_fixture_statistics(self):
        client = DeepFixtureClient()

        result = run_auto_prediction(
            "Home FC",
            "Away FC",
            fixture_id=999,
            collection_mode="fast",
            client=client,
        )

        self.assertEqual(result.collection_mode, "fast")
        self.assertEqual(result.deep_stats_matches, 0)
        self.assertEqual(client.statistics_calls, 0)

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

    def test_batch_fixture_ids_accept_mixed_separators_and_deduplicate(self):
        self.assertEqual(_parse_fixture_ids("1378240, 1527836\n1378240，1529001 bad"), [1378240, 1527836, 1529001])
        self.assertEqual(_parse_fixture_ids([1539000, "1489730", 1539000, "bad"]), [1539000, 1489730])
        self.assertEqual(_parse_fixture_ids(""), [])

    def test_batch_recommendation_summary_prefers_strong_active_signal(self):
        payload = {
            "match": {"home": "Napoli", "away": "Udinese"},
            "recommendations": [
                {
                    "market": "胜平负",
                    "selection": "Napoli 胜",
                    "action": "WATCH",
                    "model_probability": 0.58,
                    "expected_value_per_unit": 0.01,
                    "conservative_expected_value_per_unit": -0.02,
                    "reason": "优势不足。",
                },
                {
                    "market": "大小球",
                    "selection": "大 2.5",
                    "action": "BUY",
                    "odds": 2.05,
                    "model_probability": 0.56,
                    "market_probability": 0.49,
                    "expected_value_per_unit": 0.14,
                    "conservative_expected_value_per_unit": 0.06,
                    "reason": "通过保守 EV 闸门。",
                },
            ],
        }

        summary = _batch_recommendation_summary(payload)

        self.assertEqual(summary["action"], "BUY")
        self.assertEqual(summary["market"], "大小球")
        self.assertIn("大 2.5", summary["summary"])
        self.assertAlmostEqual(summary["conservativeExpectedValue"], 0.06)

    def test_batch_failure_classification_has_clear_labels(self):
        self.assertEqual(_classify_batch_failure("fixture has already started")["type"], "NOT_PRE_MATCH")
        self.assertEqual(_classify_batch_failure("没有可用的 1X2 欧赔")["type"], "NO_MARKET")
        self.assertEqual(_classify_batch_failure("近期有效样本不足")["type"], "INSUFFICIENT_SAMPLE")

    def test_batch_portfolio_plan_caps_single_batch_exposure(self):
        rows = [
            {
                "runId": index + 1,
                "league": "测试甲级联赛",
                "recommendationAction": "BUY",
                "recommendationMarket": "胜平负",
                "qualityScore": 0.82,
                "conservativeExpectedValue": 0.06 - index * 0.005,
                "expectedValue": 0.10,
                "totalStake": 200.0,
                "expectedProfit": 12.0,
            }
            for index in range(4)
        ]

        plan = _batch_portfolio_plan(rows, bankroll=1000.0)

        self.assertEqual(plan["candidateCount"], 4)
        self.assertEqual(plan["selectedCount"], 2)
        self.assertEqual(plan["plannedStake"], 400.0)
        self.assertIn("避免单批资金占用超过 50%", " ".join(plan["warnings"]))

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

    def test_daily_review_summarizes_settled_prediction_and_ev_candidate(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "mode": "auto",
                "match": {"id": "100", "home": "A", "away": "B", "homeZh": "A队", "awayZh": "B队"},
                "meta": {"leagueName": "Friendlies", "leagueCountry": "World", "leagueNameZh": "国际友谊赛", "kickoffBeijing": "2026-06-03 20:00 北京时间"},
                "probabilities": {
                    "display": {"home_win": 0.62, "draw": 0.2, "away_win": 0.18},
                    "pbase": {"home_win": 0.64, "draw": 0.2, "away_win": 0.16},
                    "market": {"home_win": 0.55, "draw": 0.25, "away_win": 0.2},
                },
                "dataQuality": {"score": 0.9, "gradeLabel": "高"},
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "total_stake": 0, "expected_profit": 0},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "A队 胜",
                        "odds": 1.8,
                        "model_probability": 0.64,
                        "market_probability": 0.55,
                        "expected_value_per_unit": 0.152,
                        "conservative_expected_value_per_unit": 0.062,
                        "action": "WATCH",
                        "ev_status": "RESEARCH_ONLY",
                        "reason": "测试候选",
                    }
                ],
            }
            run_id = record_prediction(payload, db_path=db_path)
            record_match_result("100", 2, 0, db_path=db_path)
            batch_id = record_batch_prediction(
                {
                    "date": "2026-06-03",
                    "scope": "first_division",
                    "fixtureIds": [100],
                    "collectedCount": 1,
                    "batchSummary": {"success": 1, "failed": 0, "portfolioPlan": {}},
                    "collected": [{"runId": run_id}],
                },
                db_path=db_path,
            )

            review = build_daily_review(date="2026-06-03", batch_id=batch_id, db_path=db_path)

            self.assertEqual(review["summary"]["settledMatches"], 1)
            self.assertEqual(review["summary"]["hitCount"], 1)
            self.assertEqual(review["settled"][0]["score90"], "2-0")
            self.assertAlmostEqual(review["evCandidates"][0]["actualNetPerUnit"], 0.8)
            self.assertEqual(review["summary"]["highEvAnomalyCount"], 1)
            self.assertEqual(review["highEvAnomalies"][0]["anomalyType"], "高EV复核")
            self.assertEqual(review["evAnomalyGroups"][0]["market"], "胜平负")

    def test_daily_review_groups_total_and_handicap_by_line(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "mode": "auto",
                "match": {"id": "101", "home": "A", "away": "B", "homeZh": "A队", "awayZh": "B队"},
                "meta": {"leagueName": "Friendlies", "leagueCountry": "World", "leagueNameZh": "国际友谊赛", "kickoffBeijing": "2026-06-03 21:00 北京时间"},
                "probabilities": {
                    "display": {"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
                    "pbase": {"home_win": 0.55, "draw": 0.25, "away_win": 0.20},
                    "market": {"home_win": 0.50, "draw": 0.27, "away_win": 0.23},
                },
                "expectedGoals": {"home": 1.4, "away": 1.1},
                "dataQuality": {"score": 0.82, "gradeLabel": "高"},
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "total_stake": 0, "expected_profit": 0},
                "recommendations": [
                    {
                        "market": "大小球",
                        "selection": "大 2.5",
                        "line": 2.5,
                        "odds": 1.95,
                        "model_probability": 0.62,
                        "market_probability": 0.51,
                        "expected_value_per_unit": 0.20,
                        "conservative_expected_value_per_unit": 0.08,
                        "action": "WATCH",
                        "ev_status": "RESEARCH_ONLY",
                        "reason": "测试大小球候选",
                    },
                    {
                        "market": "让球",
                        "selection": "A队 -0.5",
                        "line": -0.5,
                        "odds": 2.0,
                        "model_probability": 0.56,
                        "market_probability": 0.49,
                        "expected_value_per_unit": 0.12,
                        "conservative_expected_value_per_unit": 0.04,
                        "action": "WATCH",
                        "ev_status": "RESEARCH_ONLY",
                        "reason": "测试让球候选",
                    },
                ],
            }
            run_id = record_prediction(payload, db_path=db_path)
            record_match_result("101", 2, 1, db_path=db_path)
            batch_id = record_batch_prediction(
                {
                    "date": "2026-06-03",
                    "scope": "first_division",
                    "fixtureIds": [101],
                    "collectedCount": 1,
                    "batchSummary": {"success": 1, "failed": 0, "portfolioPlan": {}},
                    "collected": [{"runId": run_id}],
                },
                db_path=db_path,
            )

            review = build_daily_review(date="2026-06-03", batch_id=batch_id, db_path=db_path)
            backtest = review["marketLineBacktest"]
            line_groups = {(row["market"], row["lineKey"]): row for row in backtest["lineGroups"]}
            ev_rows = {row["market"]: row for row in review["evCandidates"]}

            self.assertEqual(backtest["summary"]["settledCandidates"], 2)
            self.assertEqual(backtest["summary"]["approvalStatus"], "research_only")
            self.assertIn(("大小球", "2.5"), line_groups)
            self.assertIn(("让球", "-0.5"), line_groups)
            self.assertEqual(line_groups[("大小球", "2.5")]["status"], "SAMPLE_TOO_SMALL")
            self.assertAlmostEqual(line_groups[("大小球", "2.5")]["netPerUnit"], 0.95)
            self.assertAlmostEqual(line_groups[("让球", "-0.5")]["netPerUnit"], 1.0)
            self.assertEqual(ev_rows["大小球"]["selectionDisplay"], "大 2.5")
            self.assertEqual(ev_rows["让球"]["selectionDisplay"], "A队 -0.5")
            score_backtest = review["scoreDistributionBacktest"]
            score_summary = score_backtest["summary"]
            self.assertEqual(score_summary["settledMatches"], 1)
            self.assertEqual(score_summary["marketAttributionCount"], 2)
            self.assertEqual(score_summary["approvalStatus"], "research_only")
            self.assertGreater(score_backtest["scoreRows"][0]["actualScoreProbability"], 0)
            self.assertIn("大 2.5", {row["selectionDisplay"] for row in score_backtest["marketRows"]})
            self.assertIn("A队 -0.5", {row["selectionDisplay"] for row in score_backtest["marketRows"]})
            self.assertGreater(len(build_daily_review_excel(review)), 1000)

    def test_market_line_key_ignores_team_name_noise(self):
        self.assertEqual(_line_key("British Virgin Islands +1.5"), "+1.5")
        self.assertEqual(_line_key("大 2/2.5"), "2.25")
        self.assertEqual(_line_key("A队 -1/-1.5"), "-1.25")
        self.assertEqual(_market_line_key({"market": "让球", "selection": "British Virgin Islands +1.5", "line": -1.5}), "+1.5")
        self.assertEqual(
            _selection_display(
                {"home_team": "Dominican Republic", "away_team": "British Virgin Islands"},
                {"home": "Dominican Republic", "away": "British Virgin Islands"},
                "让球",
                {"selection": "British Virgin Islands +1.5", "line": -1.5},
            ),
            "British Virgin Islands +1.5",
        )

    def test_open_paper_ledger_is_settled_after_result_arrives(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "mode": "auto",
                "match": {"id": "200", "home": "A", "away": "B"},
                "market": {"selectedBookmakers": {"1X2": "Pinnacle"}},
                "portfolio": {"bankroll": 1000, "unit_stake": 100, "active_bets": 1, "total_stake": 100, "expected_profit": 15},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "A 胜",
                        "odds": 2.0,
                        "model_probability": 0.58,
                        "market_probability": 0.5,
                        "expected_value_per_unit": 0.16,
                        "stake": 100,
                        "action": "PAPER_BUY",
                        "reason": "测试纸上买入",
                    }
                ],
            }
            record_prediction(payload, db_path=db_path)
            record_match_result("200", 1, 0, db_path=db_path)

            result = settle_open_paper_ledger(db_path=db_path)

            with connect(db_path) as conn:
                row = conn.execute("SELECT status, profit, result_score FROM paper_bankroll_ledger").fetchone()
            timeline = build_paper_bankroll_timeline(db_path=db_path)

            self.assertEqual(result["settledCount"], 1)
            self.assertEqual(row["status"], "SETTLED")
            self.assertAlmostEqual(row["profit"], 100.0)
            self.assertEqual(row["result_score"], "1-0")
            self.assertEqual(timeline["summary"]["ledgerCount"], 1)
            self.assertEqual(timeline["summary"]["settledCount"], 1)
            self.assertAlmostEqual(timeline["summary"]["realizedPnl"], 100.0)
            self.assertAlmostEqual(timeline["summary"]["cash"], 1100.0)
            self.assertEqual([event["eventType"] for event in timeline["events"]], ["RESERVE", "SETTLE"])


if __name__ == "__main__":
    unittest.main()
