#!/usr/bin/env python3
import unittest

from orgo_bash import OrgoBashError, check_bash_result


class OrgoBashParseTests(unittest.TestCase):
    def test_ok(self) -> None:
        self.assertEqual(check_bash_result({"exit_code": 0, "success": True}, "hi"), "hi")

    def test_exit_code(self) -> None:
        with self.assertRaises(OrgoBashError):
            check_bash_result({"exit_code": 1, "output": "fail"}, "fail")

    def test_error_field(self) -> None:
        with self.assertRaises(OrgoBashError):
            check_bash_result({"error": "boom"}, "")


if __name__ == "__main__":
    unittest.main()
