import json
import os
import sys
import unittest
from unittest.mock import patch, MagicMock

# Ensure kse-monitor directory is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import main
import server


class TestDuplicateCheck(unittest.TestCase):
    def setUp(self):
        self.sample_data_1 = {
            "kse100": {
                "symbol": "KSE100",
                "name": "KSE 100 Index",
                "price": 100000.0,
                "change": 150.0,
                "change_pct": 0.15,
                "volume": 5000000,
                "high": 100500.0,
                "low": 99800.0,
            },
            "stocks": [
                {
                    "symbol": "HTL",
                    "name": "HTL",
                    "price": 50.0,
                    "change": 1.0,
                    "change_pct": 2.04,
                    "volume": 10000,
                    "high": 51.0,
                    "low": 49.0,
                },
                {
                    "symbol": "YOUW",
                    "name": "YOUW",
                    "price": 10.0,
                    "change": -0.5,
                    "change_pct": -4.76,
                    "volume": 20000,
                    "high": 10.5,
                    "low": 9.8,
                },
            ],
        }

        self.sample_data_2_changed = {
            "kse100": {
                "symbol": "KSE100",
                "name": "KSE 100 Index",
                "price": 100100.0,  # Changed price
                "change": 250.0,
                "change_pct": 0.25,
                "volume": 5500000,
                "high": 100500.0,
                "low": 99800.0,
            },
            "stocks": [
                {
                    "symbol": "HTL",
                    "name": "HTL",
                    "price": 50.0,
                    "change": 1.0,
                    "change_pct": 2.04,
                    "volume": 10000,
                    "high": 51.0,
                    "low": 49.0,
                },
                {
                    "symbol": "YOUW",
                    "name": "YOUW",
                    "price": 10.0,
                    "change": -0.5,
                    "change_pct": -4.76,
                    "volume": 20000,
                    "high": 10.5,
                    "low": 9.8,
                },
            ],
        }

        self.sample_data_error = {
            "kse100": {
                "symbol": "KSE100",
                "name": "KSE 100 Index",
                "error": "Could not fetch KSE 100 data",
            },
            "stocks": [],
        }

        self.test_state_file = os.path.join(
            os.path.dirname(os.path.abspath(__file__)), "state", "test_last_check.json"
        )

    def tearDown(self):
        if os.path.exists(self.test_state_file):
            os.remove(self.test_state_file)

    def test_has_errors(self):
        self.assertFalse(main.has_errors(self.sample_data_1))
        self.assertTrue(main.has_errors(self.sample_data_error))
        self.assertTrue(main.has_errors(None))
        self.assertTrue(main.has_errors({}))
        self.assertTrue(
            main.has_errors(
                {
                    "kse100": {"symbol": "KSE100"},
                    "stocks": [{"symbol": "HTL", "error": "Failed"}],
                }
            )
        )

    def test_is_duplicate_data(self):
        # Identical copies
        data_1_copy = json.loads(json.dumps(self.sample_data_1))
        self.assertTrue(main.is_duplicate_data(self.sample_data_1, data_1_copy))

        # Changed data
        self.assertFalse(
            main.is_duplicate_data(self.sample_data_1, self.sample_data_2_changed)
        )

        # Empty last_data
        self.assertFalse(main.is_duplicate_data(self.sample_data_1, {}))

        # Data with errors
        self.assertFalse(
            main.is_duplicate_data(self.sample_data_1, self.sample_data_error)
        )

    @patch("main._last_check_path")
    def test_load_and_save_last_check(self, mock_path):
        mock_path.return_value = self.test_state_file
        self.assertEqual(main._load_last_check(), {})

        main._save_last_check(self.sample_data_1)
        loaded = main._load_last_check()
        self.assertEqual(
            loaded["kse100"]["price"], self.sample_data_1["kse100"]["price"]
        )

    @patch("main.fetch_all")
    @patch("main.send_ntfy")
    @patch("main._load_last_check")
    @patch("main._save_last_check")
    @patch("main.load_config")
    @patch("main._is_market_hours", return_value=True)
    def test_main_interval_duplicate_skipped(
        self, mock_mh, mock_cfg, mock_save, mock_load, mock_send, mock_fetch
    ):
        mock_cfg.return_value = {
            "market": {"timezone": "Asia/Karachi"},
            "stocks": [],
            "ntfy": {"server": "https://ntfy.sh", "topic": "test"},
        }
        mock_fetch.return_value = self.sample_data_1
        mock_load.return_value = self.sample_data_1  # Exact match -> duplicate

        test_args = ["main.py", "--mode", "interval"]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main.main()
            self.assertEqual(cm.exception.code, 0)

        mock_send.assert_not_called()
        mock_save.assert_not_called()

    @patch("main.fetch_all")
    @patch("main.send_ntfy", return_value=True)
    @patch("main._load_last_check")
    @patch("main._save_last_check")
    @patch("main.load_config")
    @patch("main._is_market_hours", return_value=True)
    def test_main_interval_new_data_sent(
        self, mock_mh, mock_cfg, mock_save, mock_load, mock_send, mock_fetch
    ):
        mock_cfg.return_value = {
            "market": {"timezone": "Asia/Karachi"},
            "stocks": [],
            "ntfy": {"server": "https://ntfy.sh", "topic": "test"},
        }
        mock_fetch.return_value = self.sample_data_2_changed
        mock_load.return_value = self.sample_data_1  # Previous data differs

        test_args = ["main.py", "--mode", "interval"]
        with patch.object(sys, "argv", test_args):
            main.main()

        mock_send.assert_called_once()
        mock_save.assert_called_once_with(self.sample_data_2_changed)

    @patch("main.fetch_all")
    @patch("main.send_ntfy", return_value=True)
    @patch("main._load_last_check")
    @patch("main._save_last_check")
    @patch("main.load_config")
    @patch("main._is_market_hours", return_value=True)
    def test_main_interval_force_sends_even_if_duplicate(
        self, mock_mh, mock_cfg, mock_save, mock_load, mock_send, mock_fetch
    ):
        mock_cfg.return_value = {
            "market": {"timezone": "Asia/Karachi"},
            "stocks": [],
            "ntfy": {"server": "https://ntfy.sh", "topic": "test"},
        }
        mock_fetch.return_value = self.sample_data_1
        mock_load.return_value = self.sample_data_1  # Duplicate

        test_args = ["main.py", "--mode", "interval", "--force"]
        with patch.object(sys, "argv", test_args):
            main.main()

        mock_send.assert_called_once()
        mock_save.assert_called_once()

    @patch("main.fetch_all")
    @patch("main.send_ntfy")
    @patch("main._load_last_check")
    @patch("main._save_last_check")
    @patch("main.load_config")
    @patch("main._is_market_hours", return_value=True)
    def test_main_interval_error_skipped(
        self, mock_mh, mock_cfg, mock_save, mock_load, mock_send, mock_fetch
    ):
        mock_cfg.return_value = {
            "market": {"timezone": "Asia/Karachi"},
            "stocks": [],
            "ntfy": {"server": "https://ntfy.sh", "topic": "test"},
        }
        mock_fetch.return_value = self.sample_data_error

        test_args = ["main.py", "--mode", "interval"]
        with patch.object(sys, "argv", test_args):
            with self.assertRaises(SystemExit) as cm:
                main.main()
            self.assertEqual(cm.exception.code, 0)

        mock_send.assert_not_called()
        mock_save.assert_not_called()

    @patch("server.fetch_all")
    @patch("server.send_ntfy", return_value=True)
    @patch("server._load_last_check")
    @patch("server._save_last_check")
    def test_server_interval_duplicate(
        self, mock_save, mock_load, mock_send, mock_fetch
    ):
        mock_fetch.return_value = self.sample_data_1
        mock_load.return_value = self.sample_data_1

        client = server.app.test_client()
        response = client.get("/interval")
        data = response.get_json()

        self.assertEqual(data["status"], "skipped")
        self.assertEqual(data["reason"], "duplicate_data")
        mock_send.assert_not_called()

    @patch("server.fetch_all")
    @patch("server.send_ntfy", return_value=True)
    @patch("server._load_last_check")
    @patch("server._save_last_check")
    def test_server_interval_error(
        self, mock_save, mock_load, mock_send, mock_fetch
    ):
        mock_fetch.return_value = self.sample_data_error

        client = server.app.test_client()
        response = client.get("/interval")
        data = response.get_json()

        self.assertEqual(data["status"], "skipped")
        self.assertEqual(data["reason"], "fetch_error")
        mock_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
