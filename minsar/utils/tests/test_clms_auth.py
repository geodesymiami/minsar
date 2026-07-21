#!/usr/bin/env python3
"""Unit tests for minsar.utils.clms_auth (mocked HTTP; no live CLMS)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

from minsar.utils.clms_auth import (
    default_clms_service_key_path,
    get_access_token,
    load_clms_service_key_path,
    load_service_key,
    request_token_response,
    resolve_clms_service_key_path,
)


def _minimal_service_key() -> dict:
    # RSA private key not needed when build_jwt_grant is mocked
    return {
        "private_key": "-----BEGIN PRIVATE KEY-----\nDUMMY\n-----END PRIVATE KEY-----\n",
        "client_id": "test-client",
        "user_id": "test-user",
        "token_uri": "https://land.copernicus.eu/@@oauth2-token",
    }


class TestLoadServiceKey(unittest.TestCase):
    def test_missing_field(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump({"client_id": "x"}, f)
            path = Path(f.name)
        try:
            with self.assertRaises(ValueError) as ctx:
                load_service_key(path)
            self.assertIn("private_key", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)


class TestResolveServiceKeyPath(unittest.TestCase):
    def test_default_path_helper(self):
        with patch("minsar.utils.clms_auth.Path.home", return_value=Path("/home/testuser")):
            self.assertEqual(default_clms_service_key_path(), Path("/home/testuser/accounts/clms_service_key.json"))

    def test_resolve_delegates_to_load_without_cli_override(self):
        expected = Path("/tmp/clms_service_key.json")
        with patch("minsar.utils.clms_auth.load_clms_service_key_path", return_value=expected):
            self.assertEqual(resolve_clms_service_key_path(), expected)

    def test_fallback_to_default_accounts_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            key_file = home / "accounts" / "clms_service_key.json"
            key_file.parent.mkdir(parents=True)
            key_file.write_text("{}", encoding="utf-8")
            with patch("minsar.utils.clms_auth.Path.home", return_value=home):
                with patch("minsar.utils.clms_auth.importlib.util.spec_from_file_location", return_value=None):
                    self.assertEqual(load_clms_service_key_path(), key_file)


class TestRequestToken(unittest.TestCase):
    def test_get_access_token_success(self):
        key = _minimal_service_key()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(key, f)
            path = Path(f.name)

        mock_resp = MagicMock()
        mock_resp.ok = True
        mock_resp.json.return_value = {
            "access_token": "tok-abc",
            "expires_in": 3600,
            "token_type": "Bearer",
        }
        mock_resp.text = json.dumps(mock_resp.json.return_value)

        try:
            with patch("minsar.utils.clms_auth.build_jwt_grant", return_value="fake.jwt.grant"):
                with patch("requests.post", return_value=mock_resp) as post:
                    token = get_access_token(path)
            self.assertEqual(token, "tok-abc")
            post.assert_called_once()
            kwargs = post.call_args.kwargs
            self.assertEqual(kwargs["data"]["grant_type"], "urn:ietf:params:oauth:grant-type:jwt-bearer")
            self.assertEqual(kwargs["data"]["assertion"], "fake.jwt.grant")
        finally:
            path.unlink(missing_ok=True)

    def test_http_error(self):
        key = _minimal_service_key()
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            json.dump(key, f)
            path = Path(f.name)

        mock_resp = MagicMock()
        mock_resp.ok = False
        mock_resp.status_code = 400
        mock_resp.text = '{"error":"invalid_grant"}'

        try:
            with patch("minsar.utils.clms_auth.build_jwt_grant", return_value="expired.grant"):
                with patch("requests.post", return_value=mock_resp):
                    with self.assertRaises(RuntimeError) as ctx:
                        request_token_response(path)
            self.assertIn("400", str(ctx.exception))
        finally:
            path.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
