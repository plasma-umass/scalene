import pytest

from scalene.sparkline import SparkLine


@pytest.fixture(name="sl")
def sparkline() -> SparkLine:
    return SparkLine()


def test_get_bar(sl):
    bar = sl._get_bars()

    assert bar == "▁▂▃▄▅▆▇█"


def test_get_bar___in_wsl(sl, monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Some WSL distro name")
    bar = sl._get_bars()

    assert bar == "▄▄■■■▀▀▀"


def test_get_bar__in_wsl_and_windows_terminal(sl, monkeypatch):
    monkeypatch.setenv("WSL_DISTRO_NAME", "Some WSL distro name")
    monkeypatch.setenv("WT_PROFILE_ID", "Some Windows Terminal id")
    bar = sl._get_bars()

    assert bar == "▁▂▃▄▅▆▇█"


def test_create(sl):
    numbers = [1, 2, 3, 4, 5, 6, 7, 8]

    result = sl.create(numbers)

    assert result == (1, 8, "▁▂▃▄▅▆▇█")


def test_create__up_and_down(sl):
    numbers = [1, 2, 3, 4, 5, 6, 7, 8, 7, 6, 5, 4, 3, 2, 1]

    result = sl.create(numbers)

    assert result == (1, 8, "▁▂▃▄▅▆▇█▇▆▅▄▃▂▁")


def test_create__with_min(sl):
    numbers = [1, 2, 3, 4, 5, 6, 7, 8]

    result = sl.create(numbers, fixed_min=0)

    assert result == (0, 8.0, '▂▃▄▅▆▇██')


def test_create__with_max(sl):
    numbers = [1, 2, 3, 4, 5, 6, 7, 8]

    result = sl.create(numbers, fixed_max=6)

    assert result == (1.0, 8, '▁▂▃▄▅▆▇█')


def test_create__with_max_below_actual_max(sl):
    numbers = [1, 2, 3, 4, 5, 6, 7, 8]

    result = sl.create(numbers, fixed_max=6)

    assert result == (1.0, 6, '▁▂▄▅▇███')
