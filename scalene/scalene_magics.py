import contextlib
import sys
import textwrap
from typing import TYPE_CHECKING, Any, Callable, TypeVar

F = TypeVar("F", bound=Callable[..., Any])

if TYPE_CHECKING:
    # Minimal stubs so mypy doesn't see Anys
    class Magics:  # pragma: no cover - type-checking only
        pass

    def line_cell_magic(func: F) -> F: ...  # type: ignore[override,unused-ignore]
    def line_magic(func: F) -> F: ...  # type: ignore[override,unused-ignore]
    def magics_class(cls: type) -> type: ...  # type: ignore[override,unused-ignore]


with contextlib.suppress(Exception):

    from scalene import scalene_profiler
    from scalene.scalene_arguments import ScaleneArguments
    from scalene.scalene_parseargs import ScaleneParseArgs

    if not TYPE_CHECKING:
        with contextlib.suppress(Exception):
            from IPython.core.magic import (
                Magics,
                line_cell_magic,
                line_magic,
                magics_class,
            )

    @magics_class
    class ScaleneMagics(Magics):  # type: ignore[no-any-unimported,unused-ignore]
        """IPython (Jupyter) support for magics for Scalene (%scrun and %%scalene)."""

        def run_code(self, args: ScaleneArguments, code: str) -> None:
            import IPython

            # Create a file to hold the supplied code.
            # We encode the cell number in the string for later recovery.
            # The length of the history buffer lets us find the most recent string (this one).
            filename = f"_ipython-input-{len(IPython.get_ipython().history_manager.input_hist_raw)-1}-profile"  # type: ignore[no-untyped-call,unused-ignore]
            with open(filename, "w+") as tmpfile:
                tmpfile.write(code)
            args.memory = (
                False  # full Scalene is not yet working, force to not profile memory
            )
            scalene_profiler.Scalene.set_initialized()
            scalene_profiler.Scalene.run_profiler(args, [filename], is_jupyter=True)

        @line_cell_magic
        def scalene(self, line: str, cell: str = "") -> None:
            """%%scalene magic: see https://github.com/plasma-umass/scalene for usage info."""
            if line:
                # Strip "run" if user included it (we add it automatically)
                parts = line.split()
                if parts and parts[0] == "run":
                    parts = parts[1:]
                sys.argv = ["scalene", "run", "--ipython", *parts]
                args, _left = ScaleneParseArgs.parse_args()
                # print(f"{args=}, {_left=}")
            else:
                args = ScaleneArguments()
                # print(f"{args=}")
            if args and cell:
                # Preface with a "\n" to drop the first line (%%scalene).
                self.run_code(args, "\n" + cell)  # type: ignore
                # print(f"{cell=}")

        @line_magic
        def scrun(self, line: str = "") -> None:
            """%scrun magic: see https://github.com/plasma-umass/scalene for usage info."""
            if line:
                # Strip "run" if user included it (we add it automatically)
                parts = line.split()
                if parts and parts[0] == "run":
                    parts = parts[1:]
                sys.argv = ["scalene", "run", "--ipython", *parts]
                args, left = ScaleneParseArgs.parse_args()
                if args:
                    self.run_code(args, " ".join(left))  # type: ignore

    def load_ipython_extension(ip: Any) -> None:
        ip.register_magics(ScaleneMagics)
        with contextlib.suppress(Exception):
            # For some reason, this isn't loading correctly on the web.
            with open("scalene-usage.txt") as usage:
                usage_str = usage.read()
            ScaleneMagics.scrun.__doc__ = usage_str
            ScaleneMagics.scalene.__doc__ = usage_str
        print(
            "\n".join(
                textwrap.wrap(
                    "Scalene extension successfully loaded. Note: Scalene currently only supports CPU+GPU profiling inside Jupyter notebooks. For full Scalene profiling, use the command line version. To profile in line mode, use `%scrun [options] statement`. To profile in cell mode, use `%%scalene [options]` followed by your code."
                )
            )
        )
        if sys.platform == "darwin":
            print()
            print(
                "\n".join(
                    textwrap.wrap(
                        "NOTE: in Jupyter notebook on MacOS, Scalene cannot profile child processes. Do not run to try Scalene with multiprocessing in Jupyter Notebook."
                    )
                )
            )
