import os
from typing import List, Tuple, Optional


"""Produces a sparkline, as in ▁▁▁▁▁▂▃▂▄▅▄▆█▆█▆

From https://rosettacode.org/wiki/Sparkline_in_unicode#Python
"""


def generate(
    arr: List[float],
    minimum: Optional[float] = None,
    maximum: Optional[float] = None,
) -> Tuple[float, float, str]:
    all_zeros = all(i == 0 for i in arr)
    if all_zeros:
        return 0, 0, ""

    # Prevent negative memory output due to sampling error.
    samples = [i if i > 0 else 0 for i in arr]
    return _create(samples[0 : len(arr)], minimum, maximum)


def _create(
    numbers: List[float],
    fixed_min: Optional[float] = None,
    fixed_max: Optional[float] = None,
) -> Tuple[float, float, str]:
    min_ = fixed_min if fixed_min is not None else float(min(numbers))
    max_ = fixed_max if fixed_max is not None else float(max(numbers))
    extent = _get_extent(max_, min_)
    spark = "".join(
        __bars[
            min(
                [
                    __bar_count - 1,
                    int((n - min_) / extent * __bar_count),
                ]
            )
        ]
        for n in numbers
    )
    return min_, max_, spark


def _get_extent(max_: float, min_: float) -> float:
    extent = max_ - min_
    if extent == 0:
        extent = 1
    return extent


def _in_wsl() -> bool:
    """Are we in Windows Subsystem for Linux?"""
    return "WSL_DISTRO_NAME" in os.environ


def _in_windows_terminal() -> bool:
    """Are we in Windows Terminal?

    https://aka.ms/windowsterminal
    """
    return "WT_PROFILE_ID" in os.environ


def _get_bars() -> str:
    if _in_wsl() and not _in_windows_terminal():
        # We are running in the Windows Subsystem for Linux Display, a
        # crappy version of the sparkline because the Windows console
        # *still* only properly displays IBM Code page 437 by default.
        # ▄▄■■■■▀▀
        return chr(0x2584) * 2 + chr(0x25A0) * 3 + chr(0x2580) * 3
    else:
        # Reasonable system. Use Unicode characters.
        # Unicode: 9601, 9602, 9603, 9604, 9605, 9606, 9607, 9608
        # ▁▂▃▄▅▆▇█
        return "".join([chr(i) for i in range(9601, 9609)])


__bars = _get_bars()
__bar_count = len(__bars)
