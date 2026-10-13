import pytest

from statswin import moving_average


def test_basic_windows():
    assert moving_average([1, 2, 3, 4], 2) == [1.5, 2.5, 3.5]


def test_window_of_one_is_identity():
    assert moving_average([5, 7, 9], 1) == [5.0, 7.0, 9.0]


def test_full_length_window_single_value():
    assert moving_average([2, 4, 6], 3) == [4.0]


def test_bad_k_raises():
    with pytest.raises(ValueError):
        moving_average([1, 2], 0)
