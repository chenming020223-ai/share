import unittest

from worldcup_predictor.api_football import ApiTeam
from worldcup_predictor.auto_predict import _profile_from_api, _valid_recent_matches
from worldcup_predictor.models import Fixture, ModelConfig
from worldcup_predictor.predictor import predict_match
from worldcup_predictor.team_strength import team_strength_prior


class TeamStrengthTest(unittest.TestCase):
    def test_country_prior_resolves_youth_suffix(self):
        prior = team_strength_prior("Luxembourg U21")

        self.assertIsNotNone(prior)
        self.assertLess(prior.elo, team_strength_prior("Luxembourg").elo)
        self.assertIn("youth_adjusted", prior.source)

    def test_recent_form_is_adjusted_by_opponent_strength(self):
        rows = [
            {
                "fixture": {"id": 1, "status": {"short": "FT"}, "date": "2026-05-01T00:00:00+00:00"},
                "league": {"name": "Friendlies", "country": "World"},
                "teams": {"home": {"id": 10, "name": "Cayman Islands"}, "away": {"id": 20, "name": "Anguilla"}},
                "score": {"fulltime": {"home": 3, "away": 0}},
            },
            {
                "fixture": {"id": 2, "status": {"short": "FT"}, "date": "2026-04-01T00:00:00+00:00"},
                "league": {"name": "Friendlies", "country": "World"},
                "teams": {"home": {"id": 30, "name": "Jamaica"}, "away": {"id": 10, "name": "Cayman Islands"}},
                "score": {"fulltime": {"home": 2, "away": 0}},
            },
        ]

        recent = _valid_recent_matches(rows, 10)

        self.assertEqual(recent[0]["opponent_strength_source"], "internal_strength_prior_v1")
        self.assertLess(recent[0]["opponent_strength_elo"], recent[1]["opponent_strength_elo"])

    def test_strength_prior_prevents_low_anchor_team_from_becoming_false_favorite(self):
        gibraltar_recent = [
            {"goals_for": 0, "goals_against": 2, "points": 0, "opponent": "Greece"},
            {"goals_for": 0, "goals_against": 3, "points": 0, "opponent": "Netherlands"},
            {"goals_for": 1, "goals_against": 0, "points": 3, "opponent": "Andorra"},
            {"goals_for": 0, "goals_against": 4, "points": 0, "opponent": "France"},
            {"goals_for": 1, "goals_against": 3, "points": 0, "opponent": "Scotland"},
            {"goals_for": 0, "goals_against": 1, "points": 0, "opponent": "Ireland"},
            {"goals_for": 1, "goals_against": 2, "points": 0, "opponent": "Georgia"},
            {"goals_for": 2, "goals_against": 0, "points": 3, "opponent": "Liechtenstein"},
            {"goals_for": 1, "goals_against": 1, "points": 1, "opponent": "Faroe Islands"},
            {"goals_for": 0, "goals_against": 1, "points": 0, "opponent": "Croatia"},
        ]
        cayman_recent = [
            {"goals_for": 3, "goals_against": 0, "points": 3, "opponent": "Anguilla"},
            {"goals_for": 2, "goals_against": 1, "points": 3, "opponent": "British Virgin Islands"},
            {"goals_for": 1, "goals_against": 1, "points": 1, "opponent": "US Virgin Islands"},
            {"goals_for": 2, "goals_against": 0, "points": 3, "opponent": "Bermuda"},
            {"goals_for": 1, "goals_against": 0, "points": 3, "opponent": "Anguilla"},
            {"goals_for": 0, "goals_against": 1, "points": 0, "opponent": "Jamaica"},
            {"goals_for": 1, "goals_against": 2, "points": 0, "opponent": "Trinidad and Tobago"},
            {"goals_for": 2, "goals_against": 2, "points": 1, "opponent": "Puerto Rico"},
            {"goals_for": 1, "goals_against": 0, "points": 3, "opponent": "Dominican Republic"},
            {"goals_for": 0, "goals_against": 0, "points": 1, "opponent": "Bermuda"},
        ]
        home = _profile_from_api(
            ApiTeam(id=1, name="Gibraltar"),
            None,
            gibraltar_recent,
            prior_recent_weight=0.15,
        )
        away = _profile_from_api(
            ApiTeam(id=2, name="Cayman Islands"),
            None,
            cayman_recent,
            prior_recent_weight=0.15,
        )

        result = predict_match(
            home,
            away,
            Fixture(match_id="friendly-strength-prior", home_team="Gibraltar", away_team="Cayman Islands", neutral_site=False),
            ModelConfig(market_weight=0, lambda_shrink_factor=0.7),
        )

        self.assertGreater(result.model_probabilities["home_win"], 0.55)
        self.assertLess(result.model_probabilities["away_win"], 0.20)


if __name__ == "__main__":
    unittest.main()
