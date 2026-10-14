#!/usr/bin/env python3
"""Unit tests for Honcho ops helpers (no live API)."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import feina_honcho as h


class WorkspaceListTests(unittest.TestCase):
    def test_workspace_exists_true(self) -> None:
        def fake_list(token: str) -> list[dict]:
            return [{"id": "feina-acme"}, {"id": "other"}]

        with patch.object(h, "list_all_workspaces", fake_list):
            self.assertTrue(h.workspace_exists("tok", "feina-acme"))

    def test_workspace_exists_false_on_405_get_not_used(self) -> None:
        with patch.object(h, "list_all_workspaces", return_value=[]):
            self.assertFalse(h.workspace_exists("tok", "feina-missing"))

    def test_workspace_id_field(self) -> None:
        with patch.object(h, "list_all_workspaces", return_value=[{"workspace_id": "feina-x"}]):
            self.assertTrue(h.workspace_exists("tok", "feina-x"))


class ProvisionStateTests(unittest.TestCase):
    def test_strip_none_client_key_id(self) -> None:
        saved = {"client_key": "hch_test", "client_key_id": None}
        kid = (saved.get("client_key_id") or "").strip() or None
        self.assertIsNone(kid)


if __name__ == "__main__":
    unittest.main()
