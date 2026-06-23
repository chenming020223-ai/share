import json
import os
import tempfile
import time
import unittest
from unittest.mock import patch

from worldcup_predictor.data_layer import CachedApiFootballClient


class FakeCachedClient(CachedApiFootballClient):
    def __init__(self, payloads, *args, **kwargs):
        self.payloads = list(payloads)
        self.fetches = 0
        super().__init__(*args, **kwargs)

    def _open_with_retry(self, url: str) -> str:
        self.fetches += 1
        return json.dumps(self.payloads.pop(0))


class DataLayerCacheTest(unittest.TestCase):
    def test_dynamic_cache_uses_ttl(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.dict(os.environ, {"WORLDCUP_DATA_CACHE_TTL_FIXTURES_SECONDS": "1"}):
                client = FakeCachedClient(
                    [{"response": [{"fixture": {"id": 1}}]}, {"response": [{"fixture": {"id": 2}}]}],
                    api_key="test-key",
                    cache_dir=tmpdir,
                    retries=0,
                )
                params = {"team": 1548, "last": 10, "timezone": "Asia/Shanghai"}

                first = client.get("fixtures", params)
                second = client.get("fixtures", params)
                self.assertEqual(first, second)
                self.assertEqual(client.fetches, 1)
                self.assertEqual(client.cache_hits, 1)

                cache_path = client._cache_path("fixtures", params)
                old_time = time.time() - 10
                os.utime(cache_path, (old_time, old_time))

                refreshed = client.get("fixtures", params)
                self.assertEqual(refreshed["response"][0]["fixture"]["id"], 2)
                self.assertEqual(client.fetches, 2)


if __name__ == "__main__":
    unittest.main()
