import tempfile
import unittest
from datetime import datetime, timezone

from worldcup_predictor.paper_bankroll import build_paper_ledger_book
from worldcup_predictor.payload_governance import apply_current_score_validation_to_payload
from worldcup_predictor.replay import build_history_replay_ledger, build_prediction_replay
from worldcup_predictor.storage import (
    connect,
    get_batch_prediction_payload,
    mark_official_batch,
    official_batch_for_date,
    recent_batch_predictions,
    recent_predictions,
    record_batch_prediction,
    record_match_result,
    record_prediction,
    storage_health,
    update_batch_metadata,
)
from worldcup_predictor.web_server import run_sample_prediction


class WebStorageTest(unittest.TestCase):
    def test_score_market_paper_ev_snapshot_is_preserved_for_current_display(self):
        payload = {
            "portfolio": {
                "bankroll": 1000,
                "unit_stake": 200,
                "active_bets": 1,
                "total_stake": 200,
                "expected_profit": 10,
                "expected_bankroll": 1010,
            },
            "recommendations": [
                {
                    "market": "大小球",
                    "selection": "小 2.5",
                    "odds": 2.02,
                    "model_probability": 0.39,
                    "market_probability": 0.48,
                    "edge": -0.09,
                    "expected_value_per_unit": -0.217,
                    "paper_expected_value_per_unit": -0.093,
                    "adjusted_probability": 0.45,
                    "shrink_k": 0.35,
                    "stake": 200,
                    "action": "PAPER_BUY",
                    "signal_status": "PAPER_BUY",
                    "ev_calculation": {
                        "expectedValue": -0.217,
                        "paperExpectedValue": -0.093,
                        "adjustedProbability": 0.45,
                        "shrinkK": 0.35,
                        "rawExpectedValue": 0.087,
                        "rawPositiveReturnProbability": 0.538,
                        "rawWinStakeFraction": 0.538,
                        "rawLossStakeFraction": 0.462,
                        "marketProbability": 0.48,
                        "settlement": {
                            "positiveReturnProbability": 0.39,
                            "rawPositiveReturnProbability": 0.538,
                            "fullWinProbability": 0.37,
                            "rawFullWinProbability": 0.50,
                            "pushProbability": 0.0,
                            "rawPushProbability": 0.0,
                            "fullLossProbability": 0.61,
                            "rawFullLossProbability": 0.46,
                        },
                        "scoreDistributionCalibration": {
                            "applied": True,
                            "status": "PAPER_READY",
                            "statusLabel": "大小球独立校准通过",
                            "positiveFactor": 0.73,
                            "rawExpectedValue": 0.087,
                            "rawPositiveReturnProbability": 0.538,
                        },
                    },
                }
            ],
        }
        score_validation = {
            "status": "NOT_READY",
            "markets": {
                "OU": {
                    "status": "REJECTED",
                    "statusLabel": "大小球独立校准未通过",
                    "paperEvEnabled": False,
                }
            },
        }

        current = apply_current_score_validation_to_payload(payload, score_validation)
        item = current["recommendations"][0]
        calc = item["ev_calculation"]

        self.assertEqual(item["action"], "PAPER_BUY")
        self.assertEqual(item["stake"], 200)
        self.assertEqual(current["portfolio"]["active_bets"], 1)
        self.assertEqual(current["portfolio"]["total_stake"], 200)
        self.assertAlmostEqual(item["paper_expected_value_per_unit"], -0.093)
        self.assertAlmostEqual(item["adjusted_probability"], 0.45)
        self.assertAlmostEqual(item["shrink_k"], 0.35)
        self.assertAlmostEqual(item["expected_value_per_unit"], -0.217)
        self.assertAlmostEqual(item["model_probability"], 0.39)
        self.assertAlmostEqual(item["edge"], -0.09)
        self.assertTrue(calc["scoreDistributionCalibration"]["applied"])
        self.assertEqual(current["scoreDistributionValidation"], score_validation)

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

    def test_paper_ledger_book_only_shows_unique_simulated_bets(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            watch_payload = {
                "mode": "auto",
                "match": {"id": "300", "home": "Mexico", "away": "South Africa", "homeZh": "墨西哥", "awayZh": "南非"},
                "meta": {
                    "fixtureId": 300,
                    "leagueName": "World Cup",
                    "leagueCountry": "World",
                    "leagueNameZh": "国际足联世界杯",
                    "kickoff": "2099-06-12T19:00:00+00:00",
                    "kickoffBeijing": "2099-06-13 03:00 北京时间",
                    "bookmaker": "Pinnacle",
                    "oddsCapturedAt": "2099-06-11T19:00:00+00:00",
                },
                "portfolio": {"bankroll": 1000, "unit_stake": 200},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "墨西哥 胜",
                        "odds": 2.1,
                        "model_probability": 0.52,
                        "market_probability": 0.48,
                        "expected_value_per_unit": 0.09,
                        "ev_pbase_research": 0.09,
                        "stake": 0,
                        "action": "WATCH",
                        "signal_status": "RESEARCH_WATCH",
                        "reason": "仅研究观察",
                    }
                ],
            }
            buy_payload = {
                "mode": "auto",
                "match": {"id": "301", "home": "A", "away": "B"},
                "meta": {
                    "fixtureId": 301,
                    "leagueName": "World Cup",
                    "leagueCountry": "World",
                    "kickoff": "2099-06-12T22:00:00+00:00",
                    "bookmaker": "Pinnacle",
                },
                "market": {"selectedBookmakers": {"OU": "Pinnacle"}},
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "active_bets": 1, "total_stake": 200},
                "recommendations": [
                    {
                        "market": "大小球",
                        "selection": "大 2.5",
                        "line": 2.5,
                        "odds": 1.95,
                        "model_probability": 0.58,
                        "market_probability": 0.50,
                        "paper_expected_value_per_unit": 0.05,
                        "ev_pbase_research": 0.13,
                        "stake": 200,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                        "reason": "旧版纸上模拟",
                    }
                ],
            }

            record_prediction(watch_payload, db_path=db_path)
            record_prediction(buy_payload, db_path=db_path)
            record_prediction(buy_payload, db_path=db_path)

            with connect(db_path) as conn:
                stored_count = conn.execute("SELECT COUNT(*) AS count FROM paper_bankroll_ledger").fetchone()["count"]

            book = build_paper_ledger_book(
                db_path=db_path,
                now=datetime(2026, 6, 16, tzinfo=timezone.utc),
            )

            self.assertEqual(stored_count, 1)
            self.assertEqual(book["summary"]["preMatchCount"], 0)
            self.assertEqual(book["summary"]["ledgerCount"], 1)
            self.assertEqual(book["summary"]["duplicateCount"], 0)
            self.assertEqual(book["summary"]["startingBankroll"], 1000.0)
            self.assertEqual(book["timeline"][0]["date"], "起始")
            self.assertEqual(book["timeline"][0]["bankroll"], 1000.0)
            self.assertEqual(book["preMatch"], [])
            self.assertEqual(book["summary"]["liveCabinCount"], 1)
            self.assertEqual(len(book["liveCabin"]), 1)
            self.assertEqual(book["liveCabin"][0]["status"], "OPEN")
            self.assertEqual(book["liveCabin"][0]["phaseLabel"], "等待开赛")
            self.assertFalse(book["ledger"][0]["duplicateFlag"])

    def test_paper_ledger_live_cabin_excludes_started_open_rows(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "mode": "auto",
                "match": {"id": "302", "home": "A", "away": "B", "homeZh": "甲队", "awayZh": "乙队"},
                "meta": {
                    "fixtureId": 302,
                    "leagueName": "World Cup",
                    "leagueCountry": "World",
                    "leagueNameZh": "国际足联世界杯",
                    "kickoff": "2026-06-12T19:00:00+00:00",
                    "bookmaker": "Pinnacle",
                },
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "active_bets": 1, "total_stake": 200},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "甲队 胜",
                        "odds": 1.9,
                        "model_probability": 0.56,
                        "market_probability": 0.51,
                        "expected_value_per_unit": 0.06,
                        "ev_pbase_research": 0.06,
                        "stake": 200,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                    }
                ],
            }

            record_prediction(payload, db_path=db_path)
            book = build_paper_ledger_book(
                db_path=db_path,
                now=datetime(2026, 6, 13, tzinfo=timezone.utc),
            )

            self.assertEqual(book["summary"]["openCount"], 1)
            self.assertEqual(book["summary"]["liveCabinCount"], 0)
            self.assertEqual(book["liveCabin"], [])

    def test_paper_ledger_live_cabin_uses_rolling_equity(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            settled_payload = {
                "mode": "auto",
                "match": {"id": "351", "home": "A", "away": "B", "homeZh": "甲队", "awayZh": "乙队"},
                "meta": {
                    "fixtureId": 351,
                    "leagueName": "World Cup",
                    "leagueCountry": "World",
                    "leagueNameZh": "国际足联世界杯",
                    "kickoff": "2026-06-12T19:00:00+00:00",
                    "bookmaker": "Pinnacle",
                },
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "active_bets": 1, "total_stake": 200},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "甲队 胜",
                        "odds": 3.79,
                        "model_probability": 0.56,
                        "market_probability": 0.51,
                        "expected_value_per_unit": 0.06,
                        "ev_pbase_research": 0.06,
                        "stake": 200,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                    }
                ],
            }
            open_payload = {
                **settled_payload,
                "match": {"id": "352", "home": "C", "away": "D", "homeZh": "丙队", "awayZh": "丁队"},
                "meta": {
                    **settled_payload["meta"],
                    "fixtureId": 352,
                    "kickoff": "2026-06-20T19:00:00+00:00",
                },
                "recommendations": [
                    {
                        "market": "大小球",
                        "selection": "大 2.5",
                        "line": 2.5,
                        "odds": 1.93,
                        "model_probability": 0.62,
                        "market_probability": 0.50,
                        "expected_value_per_unit": 0.04,
                        "paper_expected_value_per_unit": 0.04,
                        "ev_pbase_research": 0.19,
                        "stake": 200,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                    }
                ],
            }

            record_prediction(settled_payload, db_path=db_path)
            with connect(db_path) as conn:
                conn.execute(
                    """
                    UPDATE paper_bankroll_ledger
                    SET status = 'SETTLED',
                        created_at = '2026-06-12T12:00:00+00:00',
                        settled_at = '2026-06-13T12:00:00+00:00',
                        profit = 558,
                        result_score = '2-0'
                    """
                )
                conn.commit()
            record_prediction(open_payload, db_path=db_path)

            book = build_paper_ledger_book(
                db_path=db_path,
                now=datetime(2026, 6, 16, tzinfo=timezone.utc),
            )
            live = book["liveCabin"][0]

            self.assertEqual(book["summary"]["equity"], 1558.0)
            self.assertEqual(book["summary"]["cash"], 1358.0)
            self.assertEqual(live["currentEquity"], 1558.0)
            self.assertEqual(live["bankrollBefore"], 1558.0)
            self.assertEqual(live["cashAfterStake"], 1358.0)

    def test_prediction_replay_settles_original_and_current_modes(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            payload = {
                "mode": "auto",
                "match": {"id": "401", "home": "A", "away": "B", "homeZh": "甲队", "awayZh": "乙队"},
                "meta": {
                    "fixtureId": 401,
                    "leagueName": "World Cup",
                    "leagueCountry": "World",
                    "leagueNameZh": "国际足联世界杯",
                    "kickoff": "2026-06-12T19:00:00+00:00",
                    "bookmaker": "Pinnacle",
                },
                "portfolio": {"bankroll": 1000, "unit_stake": 200, "active_bets": 1, "total_stake": 200},
                "recommendations": [
                    {
                        "market": "大小球",
                        "selection": "大 2.5",
                        "line": 2.5,
                        "odds": 1.90,
                        "model_probability": 0.60,
                        "market_probability": 0.50,
                        "edge": 0.10,
                        "expected_value_per_unit": 0.14,
                        "paper_expected_value_per_unit": 0.05,
                        "ev_pbase_research": 0.14,
                        "stake": 200,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                        "reason": "纸上模拟",
                    },
                    {
                        "market": "让球",
                        "selection": "甲队 -0.5",
                        "line": -0.5,
                        "odds": 1.95,
                        "model_probability": 0.58,
                        "market_probability": 0.50,
                        "edge": 0.08,
                        "expected_value_per_unit": 0.13,
                        "paper_expected_value_per_unit": 0.04,
                        "ev_pbase_research": 0.13,
                        "stake": 0,
                        "action": "WATCH",
                        "signal_status": "RESEARCH_WATCH",
                        "reason": "让球观察",
                    },
                ],
            }

            run_id = record_prediction(payload, db_path=db_path)
            record_match_result("401", 2, 1, db_path=db_path)
            replay = build_prediction_replay(run_id, db_path=db_path)

            original = replay["modes"]["original"]
            current = replay["modes"]["current"]
            self.assertEqual(replay["result"]["scoreLabel"], "2-1")
            self.assertEqual(original["summary"]["selectedCount"], 1)
            self.assertAlmostEqual(original["summary"]["totalProfit"], 180.0)
            self.assertTrue(original["rows"][0]["selected"])
            self.assertEqual(original["rows"][0]["settlementLabel"], "命中")
            handicap_rows = [row for row in current["rows"] if row["market"] == "让球"]
            self.assertEqual(handicap_rows[0]["eligibility"], "CURRENT_PAPER_SELECTED")
            self.assertTrue(handicap_rows[0]["selected"])

    def test_history_replay_ledger_dedupes_fixture_and_builds_bankroll_curve(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = f"{tmpdir}/runs.sqlite3"
            old_payload = {
                "mode": "auto",
                "match": {"id": "501", "home": "A", "away": "B", "homeZh": "甲队", "awayZh": "乙队"},
                "meta": {"fixtureId": 501, "leagueName": "World Cup", "leagueCountry": "World"},
                "portfolio": {"bankroll": 1000, "unit_stake": 100, "active_bets": 1, "total_stake": 100},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "乙队 胜",
                        "odds": 2.0,
                        "model_probability": 0.55,
                        "market_probability": 0.48,
                        "edge": 0.07,
                        "expected_value_per_unit": 0.10,
                        "ev_pbase_research": 0.10,
                        "stake": 100,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                        "reason": "旧预测",
                    }
                ],
            }
            latest_payload = {
                **old_payload,
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "甲队 胜",
                        "odds": 2.0,
                        "model_probability": 0.56,
                        "market_probability": 0.49,
                        "edge": 0.07,
                        "expected_value_per_unit": 0.12,
                        "ev_pbase_research": 0.12,
                        "stake": 100,
                        "action": "PAPER_BUY",
                        "signal_status": "PAPER_BUY",
                        "reason": "最新预测",
                    }
                ],
            }
            second_payload = {
                "mode": "auto",
                "match": {"id": "502", "home": "C", "away": "D", "homeZh": "丙队", "awayZh": "丁队"},
                "meta": {"fixtureId": 502, "leagueName": "World Cup", "leagueCountry": "World"},
                "portfolio": {"bankroll": 1000, "unit_stake": 100, "active_bets": 0, "total_stake": 0},
                "recommendations": [
                    {
                        "market": "胜平负",
                        "selection": "丙队 胜",
                        "odds": 1.8,
                        "model_probability": 0.44,
                        "market_probability": 0.52,
                        "edge": -0.08,
                        "expected_value_per_unit": -0.20,
                        "ev_pbase_research": -0.20,
                        "stake": 0,
                        "action": "WATCH",
                        "signal_status": "RESEARCH_WATCH",
                        "reason": "不入选",
                    }
                ],
            }

            record_prediction(old_payload, db_path=db_path)
            latest_run = record_prediction(latest_payload, db_path=db_path)
            record_prediction(second_payload, db_path=db_path)
            record_match_result("501", 1, 0, db_path=db_path)
            record_match_result("502", 0, 0, db_path=db_path)

            ledger = build_history_replay_ledger(db_path=db_path, starting_bankroll=1000)
            original = ledger["modes"]["original"]

            self.assertEqual(ledger["settledRuns"], 2)
            self.assertEqual(ledger["duplicatesExcluded"], 1)
            self.assertEqual(ledger["rows"][0]["runId"], latest_run)
            self.assertEqual(original["summary"]["selectedCount"], 1)
            self.assertAlmostEqual(original["summary"]["totalProfit"], 100.0)
            self.assertAlmostEqual(original["summary"]["endingBankroll"], 1100.0)
            self.assertEqual(original["timeline"][-1]["bankroll"], 1100.0)

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
