"""Scalene replacement for asyncio event loop instrumentation.

Follows the existing replacement_*.py pattern using @Scalene.shim.
When async profiling is enabled, this module activates the
ScaleneAsync instrumentation (sys.monitoring on 3.12+, polling on older).
"""

from scalene.scalene_profiler import Scalene


@Scalene.shim
def replacement_asyncio(scalene: Scalene) -> None:  # type: ignore[arg-type]
    """Activate async profiling instrumentation when --async is enabled.

    This is called during profiler initialization. The actual enable/disable
    is controlled by Scalene.__init__ based on the --async flag.
    ScaleneAsync.enable() installs sys.monitoring callbacks on 3.12+.
    On 3.9-3.11, polling via asyncio.all_tasks() is used instead,
    triggered from the signal queue processor.
    """
    # Nothing to do here - activation is handled by the profiler
    # based on the --async flag. This module exists as a placeholder
    # following the replacement_*.py convention, and can be extended
    # with additional event loop wrapping if needed.
    pass
