import os
from typing import List, Tuple, Optional


class SparkLine:
    """Produces a sparkline, as in ▁▁▁▁▁▂▃▂▄▅▄▆█▆█▆

    From https://rosettacode.org/wiki/Sparkline_in_unicode#Python
    """
    def __init__(self):
        self.__bars = self._get_bars()
        self.__bar_count = len(self.__bars)

    def create(
        self,
        numbers: List[float],
        fixed_min: Optional[float] = None,
        fixed_max: Optional[float] = None,
    ) -> Tuple[float, float, str]:
        min_ = fixed_min if fixed_min is not None else float(min(numbers))
        max_ = fixed_max if fixed_max is not None else float(max(numbers))
        extent = self._get_extent(max_, min_)
        spark = "".join(
            self.__bars[
                min([self.__bar_count - 1, int((n - min_) / extent * self.__bar_count)])
            ]
            for n in numbers
        )
        return min_, max_, spark

    def _get_extent(self, max_, min_):
        extent = max_ - min_
        if extent == 0:
            extent = 1
        return extent

    def _get_bars(self) -> str:
        if self._in_wsl() and not self._in_windows_terminal():
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

    def _in_wsl(self) -> bool:
        """Are we in Windows Subsystem for Linux?"""
        return "WSL_DISTRO_NAME" in os.environ

    def _in_windows_terminal(self) -> bool:
        """Are we in Windows Terminal?

        https://aka.ms/windowsterminal
        """
        return "WT_PROFILE_ID" in os.environ
