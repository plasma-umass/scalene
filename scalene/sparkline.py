from typing import List, Tuple

# Sparkline stuff
# Unicode: 9601, 9602, 9603, 9604, 9605, 9606, 9607, 9608
bar = "▁▂▃▄▅▆▇█"
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
