import argparse
import os
import platform
import signal
import struct
import subprocess
import sys


class ScalenePreload:
    @staticmethod
    def setup_preload(args: argparse.Namespace) -> bool:
        # Return true iff we had to preload libraries and run another process.

        # First, check that we are on a supported platform.
        # (x86-64 and ARM only for now.)
        if not args.cpu_only and (
            (
                platform.machine() != "x86_64"
                and platform.machine() != "arm64"
                and platform.machine() != "aarch64"
            )
            or struct.calcsize("P") * 8 != 64
        ):
            args.cpu_only = True
            print(
                "Scalene warning: currently only 64-bit x86-64 and ARM platforms are supported for memory and copy profiling."
            )

        # Load shared objects (that is, interpose on malloc, memcpy and friends)
        # unless the user specifies "--cpu-only" at the command-line.

        if args.cpu_only:
            return False

        try:
            from IPython import get_ipython

            if get_ipython():
                sys.exit = Scalene.clean_exit  # type: ignore
        except:
            pass
        # Load the shared object on Linux.
        if sys.platform == "linux":
            if ("LD_PRELOAD" not in os.environ) and (
                "PYTHONMALLOC" not in os.environ
            ):
                os.environ["LD_PRELOAD"] = os.path.join(
                    os.path.dirname(__file__), "libscalene.so"
                )
                os.environ["PYTHONMALLOC"] = "malloc"
                new_args = [
                    os.path.basename(sys.executable),
                    "-m",
                    "scalene",
                ] + sys.argv[1:]
                result = subprocess.Popen(
                    new_args, close_fds=True, shell=False
                )
                try:
                    # If running in the background, print the PID.
                    if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                        # In the background.
                        print(f"Scalene now profiling process {result.pid}")
                        print(
                            f"  to disable profiling: python3 -m scalene.profile --off --pid {result.pid}"
                        )
                        print(
                            f"  to resume profiling:  python3 -m scalene.profile --on  --pid {result.pid}"
                        )
                except:
                    pass
                result.wait()
                if result.returncode < 0:
                    print(
                        "Scalene error: received signal",
                        signal.Signals(-result.returncode).name,
                    )
                sys.exit(result.returncode)

        # Similar logic, but for Mac OS X.
        if sys.platform == "darwin":
            if (
                ("DYLD_INSERT_LIBRARIES" not in os.environ)
                and ("PYTHONMALLOC" not in os.environ)
            ) or "OBJC_DISABLE_INITIALIZE_FORK_SAFETY" not in os.environ:
                os.environ["DYLD_INSERT_LIBRARIES"] = os.path.join(
                    os.path.dirname(__file__), "libscalene.dylib"
                )
                os.environ["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"
                os.environ["PYTHONMALLOC"] = "malloc"
                new_args = [
                    os.path.basename(sys.executable),
                    "-m",
                    "scalene",
                ] + sys.argv[1:]
                result = subprocess.Popen(
                    new_args, close_fds=True, shell=False
                )
                # If running in the background, print the PID.
                try:
                    if os.getpgrp() != os.tcgetpgrp(sys.stdout.fileno()):
                        # In the background.
                        print(f"Scalene now profiling process {result.pid}")
                        print(
                            f"  to disable profiling: python3 -m scalene.profile --off --pid {result.pid}"
                        )
                        print(
                            f"  to resume profiling:  python3 -m scalene.profile --on  --pid {result.pid}"
                        )
                except:
                    pass
                result.wait()
                if result.returncode < 0:
                    print(
                        "Scalene error: received signal",
                        signal.Signals(-result.returncode).name,
                    )
                sys.exit(result.returncode)
        return True
