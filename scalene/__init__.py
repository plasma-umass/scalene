# Work around this bug: https://github.com/NVIDIA/cuda-python/issues/29
import os
os.environ["LC_ALL"] = "POSIX"

# Jupyter support

from scalene.scalene_magics import *
