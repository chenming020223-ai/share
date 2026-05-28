import os
import unittest
from unittest.mock import patch

from worldcup_predictor.settings import env_bool
from worldcup_predictor.web_server import _api_key_from_request, health_payload


class DeploymentConfigTest(unittest.TestCase):
    def test_public_mode_uses_server_api_key_only(self):
        with patch.dict(os.environ, {"WORLDCUP_PUBLIC_MODE": "true"}, clear=False):
            self.assertIsNone(_api_key_from_request({"apiKey": "visitor-secret"}))
            self.assertTrue(env_bool("WORLDCUP_PUBLIC_MODE"))

    def test_local_mode_accepts_temporary_page_api_key(self):
        with patch.dict(os.environ, {"WORLDCUP_PUBLIC_MODE": "false"}, clear=False):
            self.assertEqual(_api_key_from_request({"apiKey": "local-key"}), "local-key")

    def test_health_reports_protected_public_deployment_without_secret(self):
        with patch.dict(
            os.environ,
            {
                "WORLDCUP_PUBLIC_MODE": "true",
                "WORLDCUP_ACCESS_PASSWORD": "do-not-return-this",
            },
            clear=False,
        ):
            health = health_payload()

        self.assertTrue(health["deployment"]["publicMode"])
        self.assertTrue(health["deployment"]["accessProtected"])
        self.assertNotIn("do-not-return-this", str(health))


if __name__ == "__main__":
    unittest.main()
