import argparse
import contextlib
import os
import platform
import signal
import struct
import subprocess
import sys
import warnings
from typing import Dict

import scalene


class ScalenePreload:
    @staticmethod
    def get_preload_environ(args: argparse.Namespace) -> Dict[str, str]:
        env = {
            "SCALENE_ALLOCATION_SAMPLING_WINDOW": str(args.allocation_sampling_window)
        }

        # Disable JITting in PyTorch and JAX to improve profiling,
        # unless the environment variables are already set.
        # JAX_DISABLE_JIT: https://jax.readthedocs.io/en/latest/debugging/flags.html#id1
        # PYTORCH_JIT: https://pytorch.org/docs/stable/jit.html#disable-jit-for-debugging
        jit_flags = [
            ("JAX_DISABLE_JIT", "1"),  # truthy => disable JIT
            ("PYTORCH_JIT", "0"),
        ]  # falsy => disable JIT

        try:
            # If we are running on Neuron, we don't disable the JITs
            # because it leads to unacceptably high overheads.
            from scalene.scalene_neuron import ScaleneNeuron

            accelerator = ScaleneNeuron()
            on_neuron = accelerator.has_gpu()
        except Exception:
            on_neuron = False
        if not on_neuron:
            for name, val in jit_flags:
                if name not in os.environ:
                    env[name] = val

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

                library_path = scalene.__path__[0]

                # NOTE: you can't use escape sequences inside an f-string pre-3.12 either

                # We use this function in two places:
                # 1. in `setup_preload`
                # 2. when calling into `redirect_python`
                if "LD_LIBRARY_PATH" not in os.environ:
                    env["LD_LIBRARY_PATH"] = library_path
                elif library_path not in os.environ["LD_LIBRARY_PATH"]:
                    env["LD_LIBRARY_PATH"] = (
                        f'{library_path}:{os.environ["LD_LIBRARY_PATH"]}'
                    )

                new_ld_preload = "libscalene.so"
                if "LD_PRELOAD" not in os.environ:
                    env["LD_PRELOAD"] = new_ld_preload
                elif new_ld_preload not in os.environ["LD_PRELOAD"].split(":"):
                    env["LD_PRELOAD"] = f'{new_ld_preload}:{os.environ["LD_PRELOAD"]}'
                # Disable command-line specified PYTHONMALLOC.
                if "PYTHONMALLOC" in os.environ:
                    # Since the environment dict is updated
                    # with a `.update` call, we need to make sure
                    # that there's some value for PYTHONMALLOC in
                    # what we return if we want to squash an anomalous
                    # value
                    env["PYTHONMALLOC"] = "default"

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
            warnings.warn(
                "Scalene warning: currently only 64-bit x86-64 and ARM platforms are supported for memory and copy profiling."
            )

        with contextlib.suppress(Exception):
            from IPython import get_ipython

            if get_ipython():  # type: ignore[no-untyped-call,unused-ignore]
                sys.exit = scalene.Scalene.clean_exit  # type: ignore
                sys._exit = scalene.Scalene.clean_exit  # type: ignore

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
            except subprocess.TimeoutExpired:
                print("Scalene failure. Please try again.")
                return False
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
