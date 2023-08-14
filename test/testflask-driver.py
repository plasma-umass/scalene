import os
import time

from random import random
from requests import get

iter = 1
while True:
    print(iter)
    iter += 1
    get(f"http://localhost:5000/{random()}")
