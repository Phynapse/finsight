"""Tests for the numeric primitives every analyser is built on.

If these are wrong, every figure FinSight reports is wrong, so they are tested
directly rather than only through an analyser.
"""

from __future__ import annotations

import pandas as pd
import pytest

from app.analytics.base import (
    absolute_change,
    direction_of,
    month_range,
    optional_float,
    percent_of_total,
    safe_average,
    safe_percentage,
    safe_percentage_change,
)
from app.models.enums import Direction


class TestSafePercentage:
    def test_matches_the_catalogued_formula(self):
        # gross_profit / revenue * 100
        assert safe_percentage(8_000.0, 10_000.0) == 80.0

    def test_rounds_to_two_decimal_places(self):
        assert safe_percentage(1, 3) == 33.33

    @pytest.mark.parametrize("denominator", [0, 0.0])
    def test_zero_denominator_is_none_not_zero(self, denominator):
        assert safe_percentage(100.0, denominator) is None

    def test_missing_denominator_is_none(self):
        assert safe_percentage(100.0, float("nan")) is None

    def test_negative_denominator_keeps_the_sign(self):
        assert safe_percentage(-100.0, 400.0) == -25.0


class TestSafeAverage:
    def test_divides_and_rounds(self):
        assert safe_average(10.0, 4.0) == 2.5

    def test_zero_count_is_none(self):
        assert safe_average(10.0, 0) is None

    def test_missing_count_is_none(self):
        assert safe_average(10.0, float("nan")) is None


class TestSafePercentageChange:
    def test_uses_the_previous_value_as_the_base(self):
        assert safe_percentage_change(120.0, 100.0) == 20.0

    def test_uses_absolute_previous_value(self):
        # A credit memo shrinking in magnitude must not flip the sign.
        assert safe_percentage_change(-50.0, -100.0) == 50.0

    def test_zero_base_is_none(self):
        assert safe_percentage_change(50.0, 0.0) is None

    def test_missing_base_is_none(self):
        assert safe_percentage_change(50.0, float("nan")) is None


class TestAbsoluteChangeAndDirection:
    def test_change_is_current_minus_previous(self):
        assert absolute_change(120.0, 100.0) == 20.0

    def test_change_is_none_without_a_base(self):
        assert absolute_change(120.0, float("nan")) is None

    @pytest.mark.parametrize(
        ("current", "previous", "expected"),
        [
            (120.0, 100.0, Direction.INCREASE),
            (80.0, 100.0, Direction.DECREASE),
            (100.0, 100.0, Direction.FLAT),
            (100.005, 100.0, Direction.FLAT),
            (120.0, None, Direction.UNKNOWN),
            (None, 100.0, Direction.UNKNOWN),
        ],
    )
    def test_direction_respects_the_tolerance(self, current, previous, expected):
        assert direction_of(current, previous) is expected


class TestPercentOfTotal:
    def test_share_of_total(self):
        assert percent_of_total(25.0, 100.0) == 25.0

    def test_zero_total_is_none(self):
        assert percent_of_total(25.0, 0.0) is None


class TestMonthRange:
    def test_quarter_maps_to_its_three_months(self):
        assert month_range("2024-Q4") == ["2024-10", "2024-11", "2024-12"]

    def test_first_quarter_starts_in_january(self):
        assert month_range("2023-Q1") == ["2023-01", "2023-02", "2023-03"]


class TestOptionalFloat:
    @pytest.mark.parametrize("value", [None, float("nan"), pd.NA])
    def test_missing_values_become_none(self, value):
        assert optional_float(value) is None

    def test_numeric_values_are_rounded(self):
        assert optional_float(1.005) == 1.0

    def test_strings_that_are_not_numbers_become_none(self):
        assert optional_float("not a number") is None