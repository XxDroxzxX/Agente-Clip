"""Conversión del token de usuario de Facebook al token de página (sin red)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agente.publish import facebook  # noqa: E402


def _resp(data):
    r = mock.Mock()
    r.json.return_value = data
    return r


class NormalizeTokenTest(unittest.TestCase):
    def test_page_from_business_portfolio(self):
        """/me/accounts vacío (página en un portafolio comercial): se usa el id que trae el propio token."""
        def get(url, params=None, timeout=None):
            if url.endswith("/me/accounts"):
                return _resp({"data": []})
            if "debug_token" in url:
                return _resp({"data": {"type": "USER", "granular_scopes": [
                    {"scope": "pages_show_list", "target_ids": ["123"]},
                    {"scope": "instagram_basic", "target_ids": []}]}})
            if url.endswith("/123"):
                return _resp({"id": "123", "name": "Mi Página", "access_token": "PAGE"})
            return _resp({"expires_in": 0})

        with mock.patch.object(facebook.requests, "get", side_effect=get):
            token, note = facebook.normalize_token("USER", "v24.0")
        self.assertEqual(token, "PAGE")
        self.assertIn("Mi Página", note)

    def test_page_token_is_kept(self):
        def get(url, params=None, timeout=None):
            if url.endswith("/me/accounts"):
                return _resp({"error": {"code": 100, "message": "no es un usuario"}})
            return _resp({})

        with mock.patch.object(facebook.requests, "get", side_effect=get):
            self.assertEqual(facebook.normalize_token("PAGE", "v24.0")[0], "PAGE")


if __name__ == "__main__":
    unittest.main()
