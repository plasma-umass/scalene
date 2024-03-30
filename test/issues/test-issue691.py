import sys
import subprocess
import tempfile

dir = tempfile.TemporaryDirectory()
cmd = [sys.executable, "-m", "scalene", "--cli", "--outfile", dir.name, "../testme.py", "--cpu-only"]

print(cmd)
print(f'If bug 691 is fixed, you will see \n    scalene: error: outfile {dir.name} is a directory')
proc = subprocess.run(cmd)