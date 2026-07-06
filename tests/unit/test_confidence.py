"""Tests for confidence aggregation utilities."""

from __future__ import annotations

import pytest

from virtualcell.core.confidence import combine_confidences, mean_confidence


def test_combine_empty_is_zero() -> None:
    assert combine_confidences([]) == 0.0


def test_combine_grows_with_evidence() -> None:
    single = combine_confidences([0.5])
    double = combine_confidences([0.5, 0.5])
    assert single == 0.5
    assert double > single
    assert double <= 1.0


def test_mean_confidence() -> None:
    assert mean_confidence([0.2, 0.4]) == pytest.approx(0.3)
    assert mean_confidence([]) == 0.0
