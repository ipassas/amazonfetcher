import os
import tempfile
import unittest

from amazon_finder import settings as settings_store
from amazon_finder.web import app


class AuthAndSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        os.environ["HISTORY_DB"] = os.path.join(self.tmp, "h.db")
        for k in ("ACCESS_CODE", "RAPIDAPI_KEY", "RAINFOREST_API_KEY", "PROVIDER"):
            os.environ.pop(k, None)
        app.config["TESTING"] = True
        self.client = app.test_client()

    def tearDown(self):
        os.environ.pop("HISTORY_DB", None)

    # -- auth gate ---------------------------------------------------------
    def test_open_when_no_code(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_healthz_always_open(self):
        os.environ["ACCESS_CODE"] = "1234"
        try:
            self.assertEqual(self.client.get("/healthz").status_code, 200)
        finally:
            os.environ.pop("ACCESS_CODE", None)

    def test_redirects_when_locked(self):
        os.environ["ACCESS_CODE"] = "1234"
        try:
            r = self.client.get("/")
            self.assertEqual(r.status_code, 302)
            self.assertIn("/login", r.headers["Location"])
        finally:
            os.environ.pop("ACCESS_CODE", None)

    def test_login_flow_with_env_code(self):
        os.environ["ACCESS_CODE"] = "1234"
        try:
            self.assertEqual(self.client.post("/login", data={"code": "nope"}).status_code, 401)
            ok = self.client.post("/login", data={"code": "1234"})
            self.assertEqual(ok.status_code, 302)
            self.assertEqual(self.client.get("/").status_code, 200)
        finally:
            os.environ.pop("ACCESS_CODE", None)

    # -- settings ----------------------------------------------------------
    def test_set_code_via_settings(self):
        r = self.client.post("/settings", data={"action": "code", "code": "abcd", "confirm": "abcd"})
        self.assertEqual(r.status_code, 200)
        self.assertTrue(settings_store.verify_access_code("abcd"))
        self.assertEqual(settings_store.access_code_source(), "ui")

    def test_code_mismatch_rejected(self):
        self.client.post("/settings", data={"action": "code", "code": "abcd", "confirm": "xyz"})
        self.assertFalse(settings_store.has_access_code())

    def test_set_api_key_via_settings(self):
        self.client.post("/settings", data={"action": "key", "provider": "rapidapi", "api_key": "SECRET123"})
        self.assertEqual(settings_store.get_api_key("rapidapi"), "SECRET123")
        self.assertEqual(settings_store.api_key_source("rapidapi"), "ui")
        self.assertEqual(settings_store.mask("SECRET123"), "••••T123")

    def test_db_key_overrides_env(self):
        os.environ["RAPIDAPI_KEY"] = "ENVKEY"
        try:
            self.assertEqual(settings_store.get_api_key("rapidapi"), "ENVKEY")
            settings_store.set_api_key("rapidapi", "UIKEY")
            self.assertEqual(settings_store.get_api_key("rapidapi"), "UIKEY")
        finally:
            os.environ.pop("RAPIDAPI_KEY", None)


if __name__ == "__main__":
    unittest.main()
