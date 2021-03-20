import argparse
import os
import sys
from textwrap import dedent
from scalene.scalene_signals import ScaleneSignals

usage = dedent("""Turn Scalene profiling on or off for a specific process.""")

parser = argparse.ArgumentParser(
    prog="scalene.profile",
    description=usage,
    formatter_class=argparse.RawTextHelpFormatter,
    allow_abbrev=False,
)
parser.add_argument(
    "--pid", dest="pid", type=int, default=0, help="process ID"
)
group = parser.add_mutually_exclusive_group(required=True)
group.add_argument("--on", action="store_true", help="turn profiling on")
group.add_argument("--off", action="store_false", help="turn profiling off")

args, left = parser.parse_known_args()
if len(sys.argv) == 1 or args.pid == 0:
    parser.print_help(sys.stderr)
    sys.exit(-1)

try:
    if args.on:
        os.kill(args.pid, ScaleneSignals.start_profiling_signal)
        print("Scalene: profiling turned on.")
    else:
        os.kill(args.pid, ScaleneSignals.stop_profiling_signal)
        print("Scalene: profiling turned off.")

except ProcessLookupError:
    print("Process " + str(args.pid) + " not found.")
