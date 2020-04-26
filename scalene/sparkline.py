from typing import List, Tuple
from os import environ

# Sparkline stuff

# Check if we are in Windows Subsystem for Linux and *not* using
# the highly recommended Windows Terminal
# (https://aka.ms/windowsterminal)
if "WSL_DISTRO_NAME" in environ and "WT_PROFILE_ID" not in environ:
    # We are running in the Windows Subsystem for Linux Display, a
    # crappy version of the sparkline because the Windows console
    # *still* only properly displays IBM Code page 437 by default.
    # ▄▄■■■■▀▀
    bar = chr(0x2584) * 2 + chr(0x25A0) * 3 + chr(0x2580) * 3
else:
    # Reasonable system. Use Unicode characters.
    # Unicode: 9601, 9602, 9603, 9604, 9605, 9606, 9607, 9608
    # ▁▂▃▄▅▆▇█
    bar = "".join([chr(i) for i in range(9601, 9609)])

barcount = len(bar)

# From https://rosettacode.org/wiki/Sparkline_in_unicode#Python
def sparkline(
    numbers: List[float], fixed_min: float = -1, fixed_max: float = -1
) -> Tuple[float, float, str]:
    if fixed_min == -1:
        mn = float(min(numbers))
    else:
        mn = fixed_min
    if fixed_max == -1:
        mx = float(max(numbers))
    else:
        mx = fixed_max
    # print(numbers)
    # mn, mx = min(numbers), max(numbers)
    extent = mx - mn
    if extent == 0:
        extent = 1
    # print("mn, mx = " + str(mn) + ", " + str(mx) + " extent = " + str(extent))
    sparkstr = "".join(
        bar[min([barcount - 1, int((n - mn) / extent * barcount)])] for n in numbers
    )
    return mn, mx, sparkstr
