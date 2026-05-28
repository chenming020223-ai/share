import unittest

from worldcup_predictor.betting import BetRecommendation, PaperPortfolio
from worldcup_predictor.model_governance import api_model_governance, apply_formal_ev_gate
from worldcup_predictor.web_server import run_sample_prediction


class ModelGovernanceTest(unittest.TestCase):
    def test_api_candidate_signal_is_blocked_until_pfinal_is_validated(self):
        recommendation = BetRecommendation(
            market="胜平负",
            selection="客胜",
            line=None,
            odds=7.56,
            model_probability=0.23,
            market_probability=0.13,
            edge=0.10,
            expected_value_per_unit=0.7388,
            stake=10,
            action="BUY",
            reason="通过候选 EV 门槛。",
        )
        portfolio = PaperPortfolio(1000, 10, 1, 10, 990, 7.388, 1007.388)

        adjusted, gated = apply_formal_ev_gate(
            [recommendation],
            portfolio,
            api_model_governance(),
            enforce=True,
        )

        self.assertEqual(adjusted[0].action, "WATCH")
        self.assertIn("pshr/pfinal", adjusted[0].reason)
        self.assertEqual(adjusted[0].stake, 0)
        self.assertEqual(gated.active_bets, 0)
        self.assertEqual(gated.total_stake, 0)

    def test_payload_identifies_display_probability_as_not_pfinal(self):
        payload = run_sample_prediction(match_id="MEX-USA")

        self.assertEqual(payload["probabilities"]["display"], payload["probabilities"]["final"])
        self.assertEqual(payload["probabilities"]["pbase"], payload["probabilities"]["model"])
        self.assertEqual(payload["probabilities"]["qmkt"], payload["probabilities"]["market"])
        self.assertFalse(payload["modelGovernance"]["formalEvEnabled"])
        self.assertEqual(payload["modelGovernance"]["gateLabel"], "本地演示")


if __name__ == "__main__":
    unittest.main()
