"""Attribute comparison is type-strict: a bool is never a number."""

import pytest

from osiki.models.base import attributes_equal


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ({"a": 1}, {"a": True}),
        ({"a": 0}, {"a": False}),
        ({"a": 1}, {"a": 1.0}),
        ({"a": [1]}, {"a": [True]}),
        ({"a": [1]}, {"a": [1.0]}),
        ({"a": 1}, {"a": "1"}),
        ({"a": None}, {"a": False}),
        ({"a": 1}, {"b": 1}),
        ({"a": 1}, {"a": 1, "b": 2}),
        ({"a": [1, 2]}, {"a": [2, 1]}),
    ],
)
def test_differing_attributes_are_not_equal(left: dict, right: dict) -> None:
    assert not attributes_equal(left, right)
    assert not attributes_equal(right, left)


@pytest.mark.parametrize(
    ("left", "right"),
    [
        ({}, {}),
        ({"a": 1, "b": "x"}, {"b": "x", "a": 1}),
        ({"a": True, "b": [1, 2.5, "s"]}, {"b": [1, 2.5, "s"], "a": True}),
        ({"a": None}, {"a": None}),
    ],
)
def test_identical_attributes_are_equal_regardless_of_key_order(
    left: dict, right: dict
) -> None:
    assert attributes_equal(left, right)
