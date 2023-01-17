import argparse
import contextlib
import os
import platform
import signal
import struct
import subprocess
import sys
from typing import Dict

import scalene


class ScalenePreload:
    @staticmethod
    def get_preload_environ(args: argparse.Namespace) -> Dict[str, str]:
        env = {
            "SCALENE_ALLOCATION_SAMPLING_WINDOW": str(
                args.allocation_sampling_window
            )
        }

        # Set environment variables for loading the Scalene dynamic library,
        # which interposes on allocation and copying functions.
        if sys.platform == "darwin":
            if args.memory:
                env["DYLD_INSERT_LIBRARIES"] = os.path.join(
                    scalene.__path__[0], "libscalene.dylib"
                )
                # Disable command-line specified PYTHONMALLOC.
                if "PYTHONMALLOC" in env:
                    del env["PYTHONMALLOC"]
            # required for multiprocessing support, even without libscalene
            env["OBJC_DISABLE_INITIALIZE_FORK_SAFETY"] = "YES"

        elif sys.platform == "linux":
            if args.memory:
                # Prepend the Scalene library to the LD_PRELOAD list, if any
                new_ld_preload = os.path.join(
                    scalene.__path__[0].replace(" ", r"\ "), "libscalene.so"
                )
                if "LD_PRELOAD" in env:
                    old_ld_preload = env["LD_PRELOAD"]
                    env["LD_PRELOAD"] = new_ld_preload + ":" + old_ld_preload
                else:
                    env["LD_PRELOAD"] = new_ld_preload
                # Disable command-line specified PYTHONMALLOC.
                if "PYTHONMALLOC" in env:
                    del env["PYTHONMALLOC"]

        elif sys.platform == "win32":
            # Force no memory profiling on Windows for now.
            args.memory = False

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
        if args.memory and (
            platform.machine() not in ["x86_64", "AMD64", "arm64", "aarch64"]
            or struct.calcsize("P") != 8
        ):
            args.memory = False
            print(
                "Scalene warning: currently only 64-bit x86-64 and ARM platforms are supported for memory and copy profiling."
            )

        with contextlib.suppress(Exception):
            from IPython import get_ipython

            if get_ipython():
                sys.exit = Scalene.clean_exit  # type: ignore
                sys._exit = Scalene.clean_exit  # type: ignore

        # Start a subprocess with the required environment variables,
        # which may include preloading libscalene
        req_env = ScalenePreload.get_preload_environ(args)
        if any(k_v not in os.environ.items() for k_v in req_env.items()):
            os.environ.update(req_env)
            new_args = [
                sys.executable,
                "-m",
                "scalene",
            ] + sys.argv[1:]
            result = subprocess.Popen(new_args, close_fds=True, shell=False)
            with contextlib.suppress(Exception):
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
            try:
                result.wait()
            except KeyboardInterrupt:
                result.returncode = 0
            if result.returncode < 0:
                print(
                    "Scalene error: received signal",
                    signal.Signals(-result.returncode).name,
                )
            sys.exit(result.returncode)
            return True

        return False
