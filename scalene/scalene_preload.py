import argparse
import os
import platform
import scalene
import signal
import struct
import subprocess
import sys

from typing import Dict

class ScalenePreload:
    @staticmethod
    def get_preload_environ(args: argparse.Namespace) -> Dict[str, str]:
        env = dict()

        if sys.platform == "linux":
            if not args.cpu_only:
                env["LD_PRELOAD"] = os.path.join(scalene.__path__[0], "libscalene.so")
                env["PYTHONMALLOC"] = "malloc"

        elif sys.platform == "darwin":
            if not args.cpu_only:
                env["DYLD_INSERT_LIBRARIES"] = os.path.join(scalene.__path__[0], "libscalene.dylib")
                env["PYTHONMALLOC"] = "malloc"
            # required for multiprocessing support, even without libscalene
            env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

        elif sys.platform == "win32":
            # Force CPU only on Windows for now.
            args.cpu_only = True

        return env

    @staticmethod
    def setup_preload(args: argparse.Namespace) -> bool:
        """
        Ensures that Scalene runs with libscalene preloaded, if necessary,
        as well as any other required environment variables.
        Returns true iff we had to run another process.
        """

        # First, check that we are on a supported platform.
        # (x86-64 and ARM only for now.)
        if not args.cpu_only and (
            (
                platform.machine() != "x86_64"
                and platform.machine() != "AMD64"
                and platform.machine() != "arm64"
                and platform.machine() != "aarch64"
            )
            or struct.calcsize("P") * 8 != 64
        ):
            args.cpu_only = True
            print(
                "Scalene warning: currently only 64-bit x86-64 and ARM platforms are supported for memory and copy profiling."
            )

        try:
            from IPython import get_ipython

            if get_ipython():
                sys.exit = Scalene.clean_exit  # type: ignore
                sys._exit = Scalene.clean_exit
        except:
            pass

        # Start a subprocess with the required environment variables,
        # which may include preloading libscalene
        req_env = ScalenePreload.get_preload_environ(args)
        if not all(k_v in os.environ.items() for k_v in req_env.items()):
            os.environ.update(req_env)

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
            return True

        return False
