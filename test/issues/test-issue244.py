import sys
import subprocess

modname = "test.testme"

print(
    "\n"
    f"Both `scalene {sys.argv[0]}` and `scalene -m {modname}` "
    f"should run and profile the {modname} module."
    "\n"
)

subprocess.run([sys.executable, "-m", modname])
