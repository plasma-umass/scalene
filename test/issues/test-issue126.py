import sys
import os.path
print(sys.executable)
print()

assert os.path.isabs(sys.executable)
assert os.path.exists(sys.executable)

import platform
print(platform.platform())

x = 0
for _ in range(1_000_000):
    x += 1
