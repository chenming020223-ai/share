import unittest

from worldcup_predictor.betting import BetRecommendation, PaperPortfolio
from worldcup_predictor.data_quality import (
    apply_quality_gate,
    build_data_quality_report,
    market_availability,
)
from worldcup_predictor.market import MarketSnapshot


class DataQualityTest(unittest.TestCase):
    def test_market_availability_detects_complete_markets(self):
        market = MarketSnapshot(
            bookmakers_count=4,
            match_winner={"home_win": 2.0, "draw": 3.2, "away_win": 3.8},
            totals={2.5: {"over": 1.91, "under": 1.95}},
            handicaps={-0.5: {"home": 2.05, "away": 1.85}},
        )

        statuses = market_availability(market)

        self.assertEqual([item.status for item in statuses], ["available", "available", "available"])

    def test_data_quality_score_reflects_missing_markets(self):
        market = MarketSnapshot(
            bookmakers_count=0,
            match_winner={"home_win": 2.0},
        )

        report = build_data_quality_report(
            market,
            fixture_id=100,
            team_rating_score=0.45,
            context_score=0.45,
            lineup_score=0.0,
            min_quality=0.60,
        )

        self.assertLess(report.score, 0.60)
        self.assertEqual(report.grade, "VERY_LOW")
        self.assertEqual(report.markets[0].status, "incomplete")
        self.assertEqual(report.markets[1].status, "missing")

    def test_low_quality_gate_downgrades_buy(self):
        recommendation = BetRecommendation(
            market="胜平负",
            selection="主胜",
            line=None,
            odds=2.2,
            model_probability=0.5,
            market_probability=0.45,
            edge=0.05,
            expected_value_per_unit=0.1,
            stake=10,
            action="BUY",
            reason="正期望。",
        )
        portfolio = PaperPortfolio(
            bankroll=1000,
            unit_stake=10,
            active_bets=1,
            total_stake=10,
            bankroll_after_stakes=990,
            expected_profit=1,
            expected_bankroll=1001,
        )
        quality = build_data_quality_report(
            MarketSnapshot(bookmakers_count=0),
            fixture_id=100,
            team_rating_score=0.45,
            context_score=0.45,
            min_quality=0.60,
        )

        adjusted, gated_portfolio = apply_quality_gate([recommendation], portfolio, quality, enforce=True)

        self.assertEqual(adjusted[0].action, "WATCH")
        self.assertEqual(adjusted[0].stake, 0)
        self.assertEqual(gated_portfolio.active_bets, 0)
        self.assertEqual(gated_portfolio.total_stake, 0)

    def test_required_bookmaker_must_be_present(self):
        market = MarketSnapshot(
            required_bookmaker="Pinnacle",
            selected_bookmaker=None,
            bookmakers_count=0,
        )

        report = build_data_quality_report(
            market,
            fixture_id=100,
            team_rating_score=1.0,
            context_score=0.75,
        )

        self.assertEqual(report.factors["bookmaker_quality"], 0.0)
        self.assertTrue(any("未取得指定庄家 Pinnacle" in note for note in report.notes))


if __name__ == "__main__":
    unittest.main()
