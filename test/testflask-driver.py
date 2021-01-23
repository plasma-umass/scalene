import os
import time

seconds = 0.2

for i in range(500):
    s = str(i)
    os.system("curl 127.0.0.1:5000/" + s + " > /dev/null");
    time.sleep(seconds)
