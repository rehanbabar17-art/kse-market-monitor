import copy
import datetime
import unittest
from unittest.mock import patch

from main import (
    MARKET_TIMEZONE,
    _decide_auto,
    _interval_signature,
    _interval_was_sent,
    _mark_interval_sent,
)
import pytz


SAMPLE_DATA = {
    "kse100": {
        "price": 169969.32,
        "change": 368.92,
        "change_pct": 0.22,
        "volume": 123456,
        "high": 171492.52,
        "low": 169872.13,
    },
    "stocks": [
        {
            "symbol": "HTL",
            "name": "HTL",
            "price": 37.43,
            "change": 0.04,
            "change_pct": 0.11,
        },
        {
            "symbol": "YOUW",
            "name": "YOUW",
            "price": 5.30,
            "change": 0.38,
            "change_pct": 7.72,
        },
    ],
}


class IntervalDeduplicationTests(unittest.TestCase):
    def test_same_snapshot_has_same_signature_even_without_timestamp(self):
        first = _interval_signature(SAMPLE_DATA, "2026-09-30")
        second = _interval_signature(copy.deepcopy(SAMPLE_DATA), "2026-09-30")
        self.assertEqual(first, second)

    def test_price_change_has_new_signature(self):
        changed = copy.deepcopy(SAMPLE_DATA)
        changed["stocks"][0]["price"] = 37.44
        self.assertNotEqual(
            _interval_signature(SAMPLE_DATA, "2026-09-30"),
            _interval_signature(changed, "2026-09-30"),
        )

    def test_daily_metadata_change_does_not_trigger_alert(self):
        changed = copy.deepcopy(SAMPLE_DATA)
        changed["kse100"].update({
            "change": 0,
            "change_pct": 0,
            "volume": 999999,
            "high": 171500,
            "low": 169800,
        })
        changed["stocks"][0].update({"name": "HTL Limited", "change": 0})
        self.assertEqual(
            _interval_signature(SAMPLE_DATA, "2026-09-30"),
            _interval_signature(changed, "2026-09-30"),
        )

    def test_symbol_change_has_new_signature(self):
        changed = copy.deepcopy(SAMPLE_DATA)
        changed["stocks"][0]["symbol"] = "OGDC"
        self.assertNotEqual(
            _interval_signature(SAMPLE_DATA, "2026-09-30"),
            _interval_signature(changed, "2026-09-30"),
        )

    def test_same_snapshot_is_allowed_again_on_a_new_day(self):
        state = {}
        signature = _interval_signature(SAMPLE_DATA, "2026-09-30")
        _mark_interval_sent(state, "2026-09-30", signature)
        self.assertTrue(_interval_was_sent(state, "2026-09-30", signature))
        self.assertFalse(_interval_was_sent(state, "2026-10-01", signature))


class AutoScheduleTests(unittest.TestCase):
    def test_auto_skips_after_market_close(self):
        tz = pytz.timezone(MARKET_TIMEZONE)
        after_close = tz.localize(datetime.datetime(2026, 10, 1, 17, 1))
        with patch("main.datetime.datetime") as datetime_class:
            datetime_class.now.return_value = after_close
            with self.assertRaisesRegex(StopIteration, "outside market hours"):
                _decide_auto({})


if __name__ == "__main__":
    unittest.main()
