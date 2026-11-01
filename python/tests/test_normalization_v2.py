"""Independent synthetic language coverage; never derived from public-test labels."""
from decimal import Decimal
import unittest

from lifemate.arguments import ArgumentRejection, normalize_arguments
from lifemate.numbers import duration_seconds, number, quantity
from lifemate.temporal import temporal

CONTEXT = {"current_time": "2026-12-31T23:45:00+07:00", "timezone": "Asia/Ho_Chi_Minh"}


class NormalizationV2Tests(unittest.TestCase):
    def test_spoken_decimal_coefficients_before_explicit_scales(self):
        for text, expected in (("một phẩy năm triệu", 1500000),
                               ("hai phẩy không năm triệu", 2050000),
                               ("âm một phẩy năm triệu", -1500000),
                               ("1.234 triệu", 1234000), ("1,234 triệu", 1234000),
                               ("một phẩy năm triệu hai trăm nghìn", 1700000)):
            with self.subTest(text=text):
                self.assertEqual(number(text), expected)

    def test_separators_depend_on_numeric_field(self):
        self.assertEqual(quantity("500.000", "amount", numeric_type="integer"), 500000)
        self.assertEqual(quantity("1.234", "temperature"), 1.234)
        self.assertEqual(quantity("0.125", "value"), 0.125)
        self.assertEqual(quantity("1,25", "value"), 1.25)
        self.assertEqual(number("1.234.567,5"), Decimal("1234567.5"))
        for value in ("1.234", "500,000"):
            with self.subTest(value=value), self.assertRaises(ValueError):
                number(value)
        with self.assertRaises(ValueError):
            quantity("500,000", "amount", numeric_type="integer")
        with self.assertRaises(ValueError):
            quantity("1.234", "count", numeric_type="integer")
        schema = {"parameters": {"type": "object", "properties": {"temperature": {"type": "integer"}}}}
        with self.assertRaises(ArgumentRejection):
            normalize_arguments({"temperature": "1.234"}, schema, CONTEXT)

    def test_compound_durations_and_halves(self):
        for text, seconds in (("một giờ ba mươi phút", 5400),
                              ("một giờ và ba mươi phút", 5400),
                              ("nửa tiếng", 1800), ("một tiếng rưỡi", 5400),
                              ("hai giờ năm phút mười giây", 7510),
                              ("một ngày hai giờ", 93600), ("nửa phút", 30)):
            with self.subTest(text=text):
                self.assertEqual(duration_seconds(text), seconds)
        self.assertEqual(quantity("một giờ ba mươi phút", "minutes"), 90)
        self.assertEqual(quantity("nửa tiếng", "delay_minutes"), 30)

    def test_invalid_durations_are_rejected_in_full(self):
        for text in ("âm một giờ", "một giờ âm ba phút", "một phút hai giờ", "một giờ hai tiếng",
                     "một giờ và", "một giờ x", "nửa giờ rưỡi", "một", "một tháng"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                duration_seconds(text)

    def test_compound_relative_delays_cross_year(self):
        for text, expected in (("sau nửa tiếng", "2027-01-01T00:15:00+07:00"),
                               ("sau một giờ ba mươi phút", "2027-01-01T01:15:00+07:00"),
                               ("sau một tiếng rưỡi", "2027-01-01T01:15:00+07:00")):
            with self.subTest(text=text):
                self.assertEqual(temporal(text, "date-time", CONTEXT), expected)

    def test_natural_clocks_and_explicit_seconds(self):
        for text, expected in (("bảy giờ mười lăm sáng", "07:15"),
                               ("7 giờ 15 buổi tối", "19:15"), ("7:15 tối", "19:15"),
                               ("bảy giờ mười lăm phút sáng", "07:15"),
                               ("bảy giờ mười lăm phút hai giây sáng", "07:15:02"),
                               ("mười hai giờ đêm", "00:00"), ("không giờ sáng", "00:00")):
            with self.subTest(text=text):
                self.assertEqual(temporal(text, "time", CONTEXT), expected)
        self.assertEqual(temporal("bảy giờ mười lăm sáng mai", "date-time", CONTEXT), "2027-01-01T07:15:00+07:00")

    def test_clock_ambiguity_and_overflow_still_reject(self):
        for text in ("bảy giờ mười lăm", "bảy giờ sáu mươi sáng", "25 giờ 00", "13 giờ chiều",
                     "không giờ trưa", "bảy giờ ba mươi phút sáu mươi giây sáng"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                temporal(text, "time", CONTEXT)

    def test_spoken_full_dates(self):
        for text, expected in (("ngày mùng năm tháng mười một năm hai nghìn không trăm hai mươi sáu", "2026-11-05"),
                               ("mồng một tháng một năm hai nghìn hai mươi bảy", "2027-01-01"),
                               ("ngày 5 tháng 11 năm 2026", "2026-11-05"),
                               ("hai mươi chín tháng hai năm hai nghìn hai mươi tám", "2028-02-29")):
            with self.subTest(text=text):
                self.assertEqual(temporal(text, "date", CONTEXT), expected)
        text = "ngày mùng năm tháng mười một năm hai nghìn hai mươi sáu lúc bảy giờ mười lăm sáng"
        self.assertEqual(temporal(text, "date-time", CONTEXT), "2026-11-05T07:15:00+07:00")

    def test_month_boundaries_and_leap_year(self):
        for text, expected in (("đầu tháng này", "2026-12-01"), ("cuối tháng này", "2026-12-31"),
                               ("đầu tháng sau", "2027-01-01"), ("cuối tháng sau", "2027-01-31")):
            with self.subTest(text=text):
                self.assertEqual(temporal(text, "date", CONTEXT), expected)
        leap = {**CONTEXT, "current_time": "2028-02-01T00:00:00+07:00"}
        self.assertEqual(temporal("cuối tháng này", "date", leap), "2028-02-29")

    def test_invalid_dates_and_unsettled_week_boundaries_reject(self):
        for text in ("mùng năm tháng mười một", "ba mươi mốt tháng hai năm hai nghìn hai mươi sáu",
                     "cuối tuần", "đầu tuần", "cuối tháng", "đầu tháng"):
            with self.subTest(text=text), self.assertRaises(ValueError):
                temporal(text, "date", CONTEXT)
