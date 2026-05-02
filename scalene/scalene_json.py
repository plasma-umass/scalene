import copy
import linecache
import math
import random
import re
from collections import defaultdict
from dataclasses import dataclass
from enum import Enum
from operator import itemgetter
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

from pydantic import (
    BaseModel,
    Field,
    NonNegativeFloat,
    NonNegativeInt,
    PositiveInt,
    StrictBool,
    ValidationError,
    model_validator,
)

from scalene.scalene_analysis import ScaleneAnalysis
from scalene.scalene_leak_analysis import ScaleneLeakAnalysis
from scalene.scalene_statistics import (
    CombinedStackKey,
    Filename,
    LineNumber,
    NativeFrameKey,
    PyFrameKey,
    ScaleneStatistics,
    StackStats,
)

# Python `def` header regex shared between CPU- and memory-stack name
# resolution. Captures the leading indent and the function name.
_DEF_RE = re.compile(r"^(\s*)(?:async\s+)?def\s+([A-Za-z_][A-Za-z_0-9]*)\s*\(")


# C++ symbol demangling. Uses ctypes to call __cxa_demangle from libc++abi
# (macOS) or libstdc++ (Linux). Falls back to returning the mangled name if
# demangling fails or is unavailable.
_demangle_fn: Optional[Callable[[bytes], Optional[str]]] = None


def _init_demangler() -> Optional[Callable[[bytes], Optional[str]]]:
    """Initialize the C++ demangler by locating __cxa_demangle."""
    import ctypes
    import ctypes.util
    import sys

    # Try common library names for __cxa_demangle
    lib_names: List[str] = []
    if sys.platform == "darwin":
        lib_names = ["libc++abi.dylib", "libc++abi.1.dylib"]
    else:
        # Linux: try libstdc++ first, then libc++abi
        lib_names = ["libstdc++.so.6", "libc++abi.so.1", "libc++abi.so"]

    for lib_name in lib_names:
        try:
            lib = ctypes.CDLL(lib_name)
            demangle = lib.__cxa_demangle
            demangle.argtypes = [
                ctypes.c_char_p,  # mangled_name
                ctypes.c_char_p,  # output_buffer (NULL for malloc)
                ctypes.POINTER(ctypes.c_size_t),  # length (NULL)
                ctypes.POINTER(ctypes.c_int),  # status
            ]
            demangle.restype = ctypes.c_char_p

            def _demangle(mangled: bytes) -> Optional[str]:
                status = ctypes.c_int()
                result = demangle(mangled, None, None, ctypes.byref(status))
                if status.value == 0 and result:
                    return result.decode("utf-8", errors="replace")
                return None

            return _demangle
        except (OSError, AttributeError):
            continue
    return None


def demangle_symbol(symbol: str) -> str:
    """Demangle a C++ symbol name. Returns the original if demangling fails."""
    global _demangle_fn
    if not symbol:
        return symbol
    # Only attempt demangling for mangled C++ symbols (start with _Z)
    if not symbol.startswith("_Z"):
        return symbol
    if _demangle_fn is None:
        _demangle_fn = _init_demangler()
        if _demangle_fn is None:
            # Demangling not available, return original
            return symbol
    try:
        result = _demangle_fn(symbol.encode("utf-8"))
        return result if result else symbol
    except Exception:
        return symbol


class CombinedStackTimelineEvent(BaseModel):
    """One run-length-encoded entry in the JSON-serialized stitched-stacks
    timeline. ``t_sec`` is the start time of the run, normalized to seconds
    since the first sample. ``stack_index`` is an index into
    ``ScaleneJSONSchema.combined_stacks``. ``count`` is the number of CPU
    samples that fired this same stack consecutively.
    """

    t_sec: NonNegativeFloat
    stack_index: NonNegativeInt
    count: PositiveInt


@dataclass(frozen=True)
class _ResolvedNativeFrame:
    """A native stack frame after IP resolution. Used internally by the
    native_stacks and combined_stacks serializers; not part of the public
    JSON schema (the public JSON shape uses CombinedStackFrame for combined
    stacks, and an inline list-of-dicts for native_stacks).

    Frozen so instances are hashable / safely shareable from the IP cache.
    A plain dataclass rather than Pydantic BaseModel because this type is
    instantiated per native frame in hot serialization loops and never
    crosses the JSON boundary directly — Pydantic validation overhead is
    pure cost here.
    """

    __slots__ = ("module", "symbol", "ip", "offset")
    module: str
    symbol: str
    ip: int
    offset: int


class CombinedStackFrame(BaseModel):
    """One frame inside a serialized stitched stack
    (ScaleneJSONSchema.combined_stacks). Either ``kind == "py"`` (with line
    info) or ``kind == "native"`` (with ip/offset).

    Note: prior versions carried a ``code_line`` field with the source text
    at the py frame's ``(filename, line)``. The GUI now looks that up on
    demand from the already-emitted ``files[filename].lines`` section so
    the string isn't duplicated for every frame appearance.
    """

    kind: str  # "py" or "native"
    display_name: str
    filename_or_module: str
    line: Optional[int]
    ip: Optional[int]
    offset: Optional[int]


class GPUDevice(str, Enum):
    nvidia = "GPU"
    neuron = "Neuron"
    no_gpu = ""


# Native-frame trimming helpers used when serializing native_stacks.
#
# Each frame is a _ResolvedNativeFrame (module, symbol, ip, offset).
# We strip two kinds of noise:
#   1. Scalene's own signal-handler / kernel-trampoline frames at the
#      innermost (leaf) end of the stack.
#   2. CPython interpreter / runtime / process-entry frames at the
#      outermost (root) end of the stack.
#
# Stacks come back from the unwinder leaf-first, i.e. index 0 is the
# innermost frame and index -1 is the outermost.

_CPYTHON_RUNTIME_SYMBOLS = frozenset(
    {
        # interpreter eval loop
        "Py_RunMain",
        "Py_BytesMain",
        "Py_Main",
        "PyEval_EvalCode",
        "_PyEval_EvalFrameDefault",
        "_PyEval_Vector",
        # generic call dispatch
        "call_method",
        "slot_tp_init",
        "type_call",
        "builtin_exec",
        "run_mod",
        # process entry points beneath Py_RunMain
        "_start",
        "__libc_start_main",
        "__libc_start_call_main",
    }
)

_CPYTHON_RUNTIME_SYMBOL_PREFIXES = (
    "PyObject_Vectorcall",
    "_PyObject_Vectorcall",
    "pymain_",
)



def _is_scalene_handler_frame(frame: _ResolvedNativeFrame) -> bool:
    if frame.symbol and "scalene_signal_unwinder" in frame.symbol:
        return True
    if frame.symbol in ("_sigtramp", "__restore_rt"):
        return True
    return bool(frame.module and "_scalene_unwind" in frame.module)


def _is_cpython_runtime_frame(frame: _ResolvedNativeFrame) -> bool:
    symbol = frame.symbol
    if not symbol:
        return False
    if symbol in _CPYTHON_RUNTIME_SYMBOLS:
        return True
    return bool(symbol.startswith(_CPYTHON_RUNTIME_SYMBOL_PREFIXES))


# Symbols that indicate a stack is from a background/worker thread rather than
# the main Python thread. These appear at the root (outermost) of stacks from
# threads spawned by libraries like OpenMP, pthread pools, etc.
_BACKGROUND_THREAD_ROOT_SYMBOLS = frozenset(
    {
        # pthread thread entry points
        "start_thread",
        "_pthread_start",
        "pthread_create",
        "__pthread_create_2_1",
        # macOS thread entry
        "thread_start",
        "_pthread_body",
        # common worker pool patterns
        "worker_thread",
        "threadpool_thread",
        # OpenMP runtime
        "__kmp_launch_worker",
        "__kmp_fork_barrier",
        # Intel TBB
        "tbb_thread_routine",
    }
)

_BACKGROUND_THREAD_ROOT_PREFIXES = (
    "__kmp_",  # OpenMP/Intel runtime
    "gomp_",   # GNU OpenMP
    "tbb_",    # Intel TBB
)


def _is_background_thread_stack(frames: List[_ResolvedNativeFrame]) -> bool:
    """Check if this stack appears to be from a background/worker thread.

    Background thread stacks have thread-pool or pthread entry points at
    their root (outermost frame). These stacks shouldn't be stitched to
    the main Python thread's frame chain.
    """
    if not frames:
        return False
    # Check the outermost frames (last in the list after trimming, since
    # frames are leaf-first and we reversed them)
    for frame in frames[-3:]:  # Check last 3 frames (outermost)
        symbol = frame.symbol
        if not symbol:
            continue
        if symbol in _BACKGROUND_THREAD_ROOT_SYMBOLS:
            return True
        if symbol.startswith(_BACKGROUND_THREAD_ROOT_PREFIXES):
            return True
    return False


def _trim_native_stack(
    frames: List[_ResolvedNativeFrame],
) -> List[_ResolvedNativeFrame]:
    """Drop the signal-handler entry frames at the leaf end and the
    CPython runtime / process-entry frames at the root end. Operates on
    a copy and returns a new list so callers can keep the originals.
    """
    out = list(frames)
    while out and _is_scalene_handler_frame(out[0]):
        out.pop(0)
    while out and _is_cpython_runtime_frame(out[-1]):
        out.pop()
    return out


class FunctionDetail(BaseModel):
    line: str
    lineno: LineNumber
    memory_samples: List[List[Any]]
    n_avg_mb: NonNegativeFloat
    n_copy_mb_s: NonNegativeFloat
    n_core_utilization: float = Field(..., ge=0, le=1)
    cpu_samples_list: List[float]
    n_cpu_percent_c: float = Field(..., ge=0, le=100)
    n_cpu_percent_python: float = Field(..., ge=0, le=100)
    n_gpu_avg_memory_mb: NonNegativeFloat
    n_gpu_peak_memory_mb: NonNegativeFloat
    n_gpu_percent: float = Field(..., ge=0, le=100)
    n_growth_mb: NonNegativeFloat
    n_peak_mb: NonNegativeFloat
    n_malloc_mb: NonNegativeFloat
    n_mallocs: NonNegativeInt
    n_python_fraction: float = Field(..., ge=0, le=1)
    n_sys_percent: float = Field(..., ge=0, le=100)
    n_usage_fraction: float = Field(..., ge=0, le=1)
    n_async_await_percent: float = Field(0, ge=0, le=100)
    n_async_concurrency_mean: float = Field(0, ge=0)
    n_async_concurrency_peak: float = Field(0, ge=0)
    async_task_names: List[str] = Field(default_factory=list)
    is_coroutine: StrictBool = False

    @model_validator(mode="after")
    def check_cpu_percentages(self) -> Any:
        total_cpu_usage = math.floor(
            self.n_cpu_percent_c + self.n_cpu_percent_python + self.n_sys_percent
        )
        if total_cpu_usage > 100:
            raise ValueError(
                f"The sum of n_cpu_percent_c, n_cpu_percent_python, and n_sys_percent must be <= 100 but is {total_cpu_usage}"
            )
        return self

    @model_validator(mode="after")
    def check_gpu_memory(self) -> Any:
        if self.n_gpu_avg_memory_mb > self.n_gpu_peak_memory_mb:
            raise ValueError(
                "n_gpu_avg_memory_mb must be less than or equal to n_gpu_peak_memory_mb"
            )
        return self

    @model_validator(mode="after")
    def check_cpu_memory(self) -> Any:
        if self.n_avg_mb > self.n_peak_mb:
            raise ValueError("n_avg_mb must be less than or equal to n_peak_mb")
        return self


class LineDetail(FunctionDetail):
    start_outermost_loop: PositiveInt
    end_outermost_loop: PositiveInt
    start_region_line: PositiveInt
    end_region_line: PositiveInt
    start_function_line: NonNegativeInt = 0
    end_function_line: NonNegativeInt = 0


class LeakInfo(BaseModel):
    likelihood: NonNegativeFloat
    velocity_mb_s: NonNegativeFloat


class FileDetail(BaseModel):
    functions: List[FunctionDetail]
    imports: List[str]
    leaks: Dict[str, LeakInfo]
    lines: List[LineDetail]
    percent_cpu_time: NonNegativeFloat


# The combined_stacks / memory_stacks wire shape is a list of [frames, count]
# pairs, where `frames` is itself a list of CombinedStackFrame dicts. Pydantic
# v2 deserializes tuples from JSON arrays and treats nested BaseModels as
# first-class validators, so declaring the type as Tuple[List[...], int]
# pins both the outer arity and the inner frame shape. The count payload
# differs per section: CPU combined_stacks uses integer hit counts; memory
# flame chart uses float MB. Both must be non-negative.
CombinedStackEntry = Tuple[List[CombinedStackFrame], NonNegativeInt]
MemoryStackEntry = Tuple[List[CombinedStackFrame], NonNegativeFloat]


class ScaleneJSONSchema(BaseModel):
    alloc_samples: NonNegativeInt
    args: Optional[List[str]] = None
    async_profile: StrictBool = False
    elapsed_time_sec: NonNegativeFloat
    start_time_absolute: NonNegativeFloat
    start_time_perf: NonNegativeFloat
    entrypoint_dir: str
    filename: str
    files: Dict[str, FileDetail]
    gpu: StrictBool
    gpu_device: GPUDevice
    growth_rate: float
    max_footprint_fname: Optional[str]
    max_footprint_lineno: Optional[PositiveInt]
    max_footprint_mb: NonNegativeFloat
    max_footprint_python_fraction: NonNegativeFloat
    memory: StrictBool
    program: str
    samples: List[List[NonNegativeFloat]]
    stacks: List[List[Any]]
    memory_stacks: List[MemoryStackEntry] = Field(default_factory=list)
    # Stitched Python+native call stacks (emitted when --stacks is set).
    # Each entry validates its inner frames via CombinedStackFrame, so a
    # profile with a malformed frame (wrong kind, missing filename, etc.)
    # raises ValidationError at load time rather than crashing the GUI
    # at render time.
    combined_stacks: List[CombinedStackEntry] = Field(default_factory=list)
    # Run-length-encoded timeline of stitched stacks. CombinedStackTimelineEvent
    # pins the wire shape (t_sec, stack_index, count).
    combined_stacks_timeline: List[CombinedStackTimelineEvent] = Field(
        default_factory=list
    )
    # Top-level aggregates emitted by the JSON writer but previously not
    # declared in the schema. Making them explicit lets pydantic enforce the
    # types (and catches regressions if future emitters drop or rename them).
    native_allocations_mb: NonNegativeFloat = 0.0


class ScaleneJSON:
    @staticmethod
    def memory_consumed_str(size_in_mb: float) -> str:
        """Return a string corresponding to amount of memory consumed."""
        gigabytes = size_in_mb // 1024
        terabytes = gigabytes // 1024
        if terabytes > 0:
            return f"{(size_in_mb / 1048576):3.3f} TB"
        elif gigabytes > 0:
            return f"{(size_in_mb / 1024):3.3f} GB"
        else:
            return f"{size_in_mb:3.3f} MB"

    @staticmethod
    def time_consumed_str(time_in_ms: float) -> str:
        hours = time_in_ms // 3600000
        minutes = (time_in_ms % 3600000) // 60000
        seconds = (time_in_ms % 60000) // 1000
        hours_exact = time_in_ms / 3600000
        minutes_exact = (time_in_ms % 3600000) / 60000
        seconds_exact = (time_in_ms % 60000) / 1000
        if hours > 0:
            return f"{hours_exact:.0f}h:{minutes_exact:.0f}m:{seconds_exact:3.3f}s"
        elif minutes > 0:
            return f"{minutes_exact:.0f}m:{seconds_exact:3.3f}s"
        elif seconds > 0:
            return f"{seconds_exact:3.3f}s"
        else:
            return f"{time_in_ms:3.3f}ms"

    # Default threshold for percent of CPU time to report a file.
    cpu_percent_threshold = 1

    # Default threshold for number of mallocs to report a file.
    malloc_threshold = 1  # 100

    # Fraction of the maximum footprint to use as granularity for memory timelines
    # (used for compression). E.g., 10 => 1/10th of the max.
    memory_granularity_fraction = 10

    # Maximum number of sparkline samples.
    max_sparkline_samples = 100

    def __init__(self) -> None:
        # where we write profile info
        self.output_file = ""

        # if we are on a GPU or not
        self.gpu = False
        self.gpu_device = ""

    def compress_samples(self, samples: List[Any], max_footprint: float) -> Any:
        if len(samples) <= self.max_sparkline_samples:
            return samples

        new_samples = sorted(
            random.sample(list(map(tuple, samples)), self.max_sparkline_samples)
        )
        return new_samples

    # Profile output methods
    def output_profile_line(
        self,
        *,
        fname: Filename,
        fname_print: Filename,
        line_no: LineNumber,
        line: str,
        stats: ScaleneStatistics,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        profile_memory: bool = False,
        profile_async: bool = False,
        force_print: bool = False,
    ) -> Dict[str, Any]:
        """Print at most one line of the profile (true == printed one)."""

        # Check if this line has PyTorch profiler timing (for JIT-compiled code)
        torch_cpu_time_sec = stats.cpu_stats.torch_cpu_time[fname][line_no]
        torch_gpu_time_sec = stats.cpu_stats.torch_gpu_time[fname][line_no]
        has_torch_timing = torch_cpu_time_sec > 0 or torch_gpu_time_sec > 0

        if (
            not force_print
            and not profile_this_code(fname, line_no)
            and not has_torch_timing
        ):
            return {
                "lineno": line_no,
                "line": line,
                "cpu_samples_list": [],
                "n_core_utilization": 0,
                "n_cpu_percent_c": 0,
                "n_cpu_percent_python": 0,
                "n_sys_percent": 0,
                "n_gpu_percent": 0,
                "n_gpu_avg_memory_mb": 0,
                "n_gpu_peak_memory_mb": 0,
                "n_peak_mb": 0,
                "n_growth_mb": 0,
                "n_avg_mb": 0,
                "n_mallocs": 0,
                "n_malloc_mb": 0,
                "n_usage_fraction": 0,
                "n_python_fraction": 0,
                "n_copy_mb_s": 0,
                "n_async_await_percent": 0,
                "n_async_concurrency_mean": 0,
                "n_async_concurrency_peak": 0,
                "async_task_names": [],
                "is_coroutine": False,
                "memory_samples": [],
            }

        # Prepare output values.
        n_cpu_samples_c = stats.cpu_stats.cpu_samples_c[fname][line_no]
        # Correct for negative CPU sample counts. This can happen
        # because of floating point inaccuracies, since we perform
        # subtraction to compute it.
        n_cpu_samples_c = max(0, n_cpu_samples_c)
        n_cpu_samples_python = stats.cpu_stats.cpu_samples_python[fname][line_no]
        n_gpu_samples = stats.gpu_stats.gpu_samples[fname][line_no]
        n_gpu_mem_samples = stats.gpu_stats.gpu_mem_samples[fname][line_no]

        # torch_time_sec was already fetched above for the early return check

        # Compute percentages of CPU time (from signal-based sampling).
        if stats.cpu_stats.total_cpu_samples:
            n_cpu_percent_c = n_cpu_samples_c * 100 / stats.cpu_stats.total_cpu_samples
            n_cpu_percent_python = (
                n_cpu_samples_python * 100 / stats.cpu_stats.total_cpu_samples
            )
        else:
            n_cpu_percent_c = 0
            n_cpu_percent_python = 0

        if True:
            if stats.gpu_stats.n_gpu_samples[fname][line_no]:
                n_gpu_percent = (
                    n_gpu_samples * 100 / stats.gpu_stats.n_gpu_samples[fname][line_no]
                )  # total_gpu_samples
            else:
                n_gpu_percent = 0

        # Now, memory stats.
        # Total volume of memory allocated.
        n_malloc_mb = stats.memory_stats.memory_malloc_samples[fname][line_no]
        # Number of distinct allocation calls (those from the same line are counted as 1).
        n_mallocs = stats.memory_stats.memory_malloc_count[fname][line_no]
        # Total volume of memory allocated by Python (not native code).
        n_python_malloc_mb = stats.memory_stats.memory_python_samples[fname][line_no]

        n_usage_fraction = (
            0
            if not stats.memory_stats.total_memory_malloc_samples
            else n_malloc_mb / stats.memory_stats.total_memory_malloc_samples
        )
        n_python_fraction = 0 if not n_malloc_mb else n_python_malloc_mb / n_malloc_mb

        # Average memory consumed by this line.
        n_avg_mb = (
            stats.memory_stats.memory_aggregate_footprint[fname][line_no]
            if n_mallocs == 0
            else stats.memory_stats.memory_aggregate_footprint[fname][line_no]
            / n_mallocs
        )

        # Peak memory consumed by this line.
        n_peak_mb = stats.memory_stats.memory_max_footprint[fname][line_no]

        # Force the reporting of average to be no more than peak.
        # In principle, this should never happen, but...
        # assert n_avg_mb <= n_peak_mb
        if n_avg_mb > n_peak_mb:
            n_avg_mb = n_peak_mb

        n_cpu_percent = n_cpu_percent_c + n_cpu_percent_python

        # Adjust CPU time by utilization (for signal-based sampling).
        mean_cpu_util = stats.cpu_stats.cpu_utilization[fname][line_no].mean()
        mean_core_util = stats.cpu_stats.core_utilization[fname][line_no].mean()
        n_sys_percent = n_cpu_percent * (1.0 - mean_cpu_util)
        n_cpu_percent_python *= mean_cpu_util
        n_cpu_percent_c *= mean_cpu_util
        del mean_cpu_util

        # Add PyTorch profiler timing for lines that have NO signal-based samples.
        # This provides attribution for lines inside JIT-compiled functions that
        # the signal sampler never sees. We only add torch timing when there are
        # no signal samples to avoid double-counting (the call site already
        # accounts for the time spent in the JIT function via signal sampling).
        has_signal_samples = n_cpu_samples_c > 0 or n_cpu_samples_python > 0
        if stats.elapsed_time > 0 and torch_cpu_time_sec > 0 and not has_signal_samples:
            torch_cpu_percent = (torch_cpu_time_sec / stats.elapsed_time) * 100
            n_cpu_percent_c = min(torch_cpu_percent, 100.0)

        # Add PyTorch GPU timing for lines that have NO signal-based GPU samples.
        # Similar to CPU timing, this attributes GPU time to JIT-compiled code.
        has_gpu_signal_samples = n_gpu_samples > 0
        if (
            stats.elapsed_time > 0
            and torch_gpu_time_sec > 0
            and not has_gpu_signal_samples
        ):
            torch_gpu_percent = (torch_gpu_time_sec / stats.elapsed_time) * 100
            n_gpu_percent = min(torch_gpu_percent, 100.0)

        n_copy_b = stats.memory_stats.memcpy_samples[fname][line_no]
        if stats.elapsed_time:
            n_copy_mb_s = n_copy_b / (1024 * 1024 * stats.elapsed_time)
        else:
            n_copy_mb_s = 0

        per_line_samples = self.compress_samples(
            stats.memory_stats.per_line_footprint_samples[fname][line_no].reservoir,
            stats.memory_stats.max_footprint,
        )

        # Compute async await percentage and concurrency
        n_async_await_percent = 0.0
        n_async_concurrency_mean = 0.0
        n_async_concurrency_peak = 0.0
        async_task_names_list: list[str] = []
        is_coroutine_fn = False
        if profile_async and stats.async_stats.total_async_await_samples > 0:
            n_async_await_samples = stats.async_stats.async_await_samples[fname][
                line_no
            ]
            n_async_await_percent = (
                n_async_await_samples
                * 100
                / stats.async_stats.total_async_await_samples
            )
            concurrency = stats.async_stats.async_concurrency[fname][line_no]
            if concurrency.size() > 0:
                n_async_concurrency_mean = concurrency.mean()
                n_async_concurrency_peak = concurrency.peak()
            task_names = stats.async_stats.async_task_names[fname][line_no]
            if task_names:
                async_task_names_list = sorted(task_names)
        # Check if the function at this line is a coroutine
        fn_name = stats.function_map.get(fname, {}).get(line_no, "")
        if fn_name:
            is_coroutine_fn = stats.async_stats.is_coroutine.get(str(fn_name), False)

        payload = {
            "line": line,
            "lineno": line_no,
            "memory_samples": per_line_samples,
            "cpu_samples_list": stats.cpu_stats.cpu_samples_list[fname][
                line_no
            ].reservoir,
            "n_avg_mb": n_avg_mb,
            "n_copy_mb_s": n_copy_mb_s,
            "n_core_utilization": mean_core_util,
            "n_cpu_percent_c": n_cpu_percent_c,
            "n_cpu_percent_python": n_cpu_percent_python,
            "n_gpu_avg_memory_mb": n_gpu_mem_samples.mean(),
            "n_gpu_peak_memory_mb": n_gpu_mem_samples.peak(),
            "n_gpu_percent": n_gpu_percent,
            "n_growth_mb": n_peak_mb,  # For backwards compatibility
            "n_peak_mb": n_peak_mb,
            "n_malloc_mb": n_malloc_mb,
            "n_mallocs": n_mallocs,
            "n_python_fraction": n_python_fraction,
            "n_sys_percent": n_sys_percent,
            "n_usage_fraction": n_usage_fraction,
            "n_async_await_percent": n_async_await_percent,
            "n_async_concurrency_mean": n_async_concurrency_mean,
            "n_async_concurrency_peak": n_async_concurrency_peak,
            "async_task_names": async_task_names_list,
            "is_coroutine": is_coroutine_fn,
        }
        try:
            FunctionDetail(**payload)
        except ValidationError as e:
            print("Warning: JSON failed validation:")
            print(e)
        return payload

    def output_profiles(
        self,
        program: Filename,
        stats: ScaleneStatistics,
        pid: int,
        profile_this_code: Callable[[Filename, LineNumber], bool],
        python_alias_dir: Path,
        program_path: Filename,
        entrypoint_dir: Filename,
        program_args: Optional[List[str]],
        profile_memory: bool = True,
        reduced_profile: bool = False,
        profile_async: bool = False,
    ) -> Dict[str, Any]:
        """Write the profile out."""
        # Get the children's stats, if any.
        if not pid:
            stats.merge_stats(python_alias_dir)
        # If we've collected any samples, dump them.
        if (
            not stats.cpu_stats.total_cpu_samples
            and not stats.memory_stats.total_memory_malloc_samples
            and not stats.memory_stats.total_memory_free_samples
            and not stats.gpu_stats.n_gpu_samples[program]
            and not (profile_async and stats.async_stats.total_async_await_samples)
        ):
            # Nothing to output.
            return {}
        # Collect all instrumented filenames.
        file_keys = (
            list(stats.cpu_stats.cpu_samples_python.keys())
            + list(stats.cpu_stats.cpu_samples_c.keys())
            + list(stats.cpu_stats.torch_cpu_time.keys())
            + list(stats.cpu_stats.torch_gpu_time.keys())
            + list(stats.memory_stats.memory_free_samples.keys())
            + list(stats.memory_stats.memory_malloc_samples.keys())
            + list(stats.gpu_stats.gpu_samples.keys())
        )
        if profile_async:
            file_keys += list(stats.async_stats.async_await_samples.keys())
        all_instrumented_files: List[Filename] = list(set(file_keys))
        if not all_instrumented_files:
            # We didn't collect samples in source files.
            return {}
        growth_rate = 0.0
        if profile_memory:
            compressed_footprint_samples = self.compress_samples(
                stats.memory_stats.memory_footprint_samples.reservoir,
                stats.memory_stats.max_footprint,
            )
            # Compute growth rate (slope), between 0 and 1.
            if stats.memory_stats.allocation_velocity[1] > 0:
                growth_rate = (
                    100.0
                    * stats.memory_stats.allocation_velocity[0]
                    / stats.memory_stats.allocation_velocity[1]
                )

        # Adjust the program name if it was a Jupyter cell.
        result = re.match(r"_ipython-input-([0-9]+)-.*", program)
        if result:
            program = Filename("[" + result.group(1) + "]")

        # Process the stacks to normalize by total number of CPU samples.
        for stk in stats.stacks:
            stack_stats = stats.stacks[stk]
            stats.stacks[stk] = StackStats(
                stack_stats.count,
                stack_stats.python_time / stats.cpu_stats.total_cpu_samples,
                stack_stats.c_time / stats.cpu_stats.total_cpu_samples,
                stack_stats.cpu_samples / stats.cpu_stats.total_cpu_samples,
            )

        # Convert stacks into a representation suitable for JSON dumping.
        stks = []
        for stk in stats.stacks:
            this_stk: List[str] = []
            this_stk.extend(str(frame) for frame in stk)
            stack_stats = stats.stacks[stk]
            # Convert StackStats to a dictionary
            stack_stats_dict = {
                "count": stack_stats.count,
                "python_time": stack_stats.python_time,
                "c_time": stack_stats.c_time,
                "cpu_samples": stack_stats.cpu_samples,
            }
            stks.append((this_stk, stack_stats_dict))

        # Note: a standalone ``native_stacks`` section used to be emitted
        # here (raw IP tuples resolved + trimmed into a list of (frames,
        # hits) entries). It was fully redundant with ``combined_stacks``
        # below — every native stack captured alongside a Python chain
        # already appears in the stitched view, and no GUI or CLI consumer
        # read ``native_stacks`` independently. See P6 in the
        # overhead-reduction work. The underlying ``stats.native_stacks``
        # aggregate is still populated at sample time and still
        # round-trips through the cloudpickle payload, but the JSON wire
        # format no longer duplicates it.

        # Stitched Python+native stacks. stats.combined_stacks is keyed by
        # CombinedStackKey: a tuple of PyFrameKey | NativeFrameKey instances
        # (outermost-first). Resolve native IPs and trim contiguous CPython
        # runtime frames at the seam (i.e. between Python and native
        # segments) so the visible stack ends with real C/C++ user code
        # rather than _PyEval_*.
        combined_stks: List[Tuple[List[CombinedStackFrame], int]] = []
        combined_stks_timeline: List[Dict[str, Any]] = []
        if stats.combined_stacks:
            try:
                from scalene import _scalene_unwind  # type: ignore

                resolve = _scalene_unwind.resolve_ip
            except ImportError:
                resolve = None

            ip_cache_combined: Dict[int, _ResolvedNativeFrame] = {}

            # Source lines used to be embedded in every py frame as a
            # ``code_line`` field. The GUI now resolves source text on the
            # fly from the ``files[filename].lines`` section already present
            # in the profile, so the per-frame copy (often the same 45-char
            # string repeated dozens of times per profile) is no longer
            # needed. See P5 in the overhead-reduction work.

            def _resolve(ip: int) -> _ResolvedNativeFrame:
                cached = ip_cache_combined.get(ip)
                if cached is not None:
                    return cached
                info = resolve(ip) if resolve is not None else None
                if info is None:
                    rep = _ResolvedNativeFrame(module="", symbol="", ip=ip, offset=0)
                else:
                    module, symbol, offset = info
                    # Demangle C++ symbols for better readability
                    symbol = demangle_symbol(symbol)
                    rep = _ResolvedNativeFrame(
                        module=module, symbol=symbol, ip=ip, offset=offset
                    )
                ip_cache_combined[ip] = rep
                return rep

            # Aggregate by the resolved + trimmed display key so that two raw
            # samples that landed on different IPs but resolved to the same
            # (symbol, module) frames collapse into one entry. Without this,
            # near-identical stacks appear as duplicates because sample-time
            # aggregation in stats.combined_stacks is keyed by raw IPs.
            #
            # The dedup key is a tuple of (kind, display_name, location, line)
            # quadruples — same shape as a CombinedStackFrame's user-visible
            # fields, but as a hashable tuple. Native ip/offset are excluded
            # so different instructions in the same function collapse.
            DedupFrame = Tuple[str, str, str, Optional[int]]
            DedupKey = Tuple[DedupFrame, ...]
            combined_aggregated: Dict[
                DedupKey, Tuple[List[CombinedStackFrame], int]
            ] = {}
            # Map each raw stack key (as stored in stats.combined_stacks and
            # in stats.combined_stacks_timeline) to its dedup_key so the
            # timeline can later be emitted as indices into the final
            # combined_stks list.
            raw_to_dedup_key: Dict[CombinedStackKey, DedupKey] = {}
            for stk, hits in stats.combined_stacks.items():
                # Find the seam: index of first native frame.
                seam = next(
                    (
                        i
                        for i, frame in enumerate(stk)
                        if isinstance(frame, NativeFrameKey)
                    ),
                    len(stk),
                )
                # Slicing a tuple yields a tuple; the type narrows imperfectly
                # so we cast at use sites with isinstance checks below.
                py_segment = stk[:seam]
                native_segment_raw = stk[seam:]

                # Resolve native IPs, then trim handler/runtime frames using
                # the existing helpers. The native segment as stored is
                # outermost-first (entry -> leaf), but _trim_native_stack
                # expects leaf-first, so reverse before trimming and back
                # after.
                resolved_leaf_first: List[_ResolvedNativeFrame] = []
                for native_frame in native_segment_raw:
                    if not isinstance(native_frame, NativeFrameKey):
                        continue
                    resolved_leaf_first.append(_resolve(native_frame.ip))
                resolved_leaf_first.reverse()
                trimmed_leaf_first = _trim_native_stack(resolved_leaf_first)

                # Skip stacks that appear to be from background/worker threads
                # (e.g., OpenMP workers, pthread pools). These have thread-pool
                # entry points at their root and shouldn't be stitched to the
                # main Python thread's frame chain.
                if _is_background_thread_stack(trimmed_leaf_first):
                    continue

                trimmed = list(reversed(trimmed_leaf_first))

                out_frames: List[CombinedStackFrame] = []
                for py_frame in py_segment:
                    if not isinstance(py_frame, PyFrameKey):
                        continue
                    out_frames.append(
                        CombinedStackFrame(
                            kind="py",
                            display_name=py_frame.function,
                            filename_or_module=py_frame.filename,
                            line=py_frame.line,
                            ip=None,
                            offset=None,
                        )
                    )
                for native in trimmed:
                    out_frames.append(
                        CombinedStackFrame(
                            kind="native",
                            display_name=native.symbol,
                            filename_or_module=native.module,
                            line=None,
                            ip=native.ip,
                            offset=native.offset,
                        )
                    )
                if not out_frames:
                    continue
                dedup_key: DedupKey = tuple(
                    (
                        frame.kind,
                        frame.display_name,
                        frame.filename_or_module,
                        frame.line,
                    )
                    for frame in out_frames
                )
                existing = combined_aggregated.get(dedup_key)
                if existing is None:
                    combined_aggregated[dedup_key] = (out_frames, hits)
                else:
                    combined_aggregated[dedup_key] = (
                        existing[0],
                        existing[1] + hits,
                    )
                raw_to_dedup_key[stk] = dedup_key
            # combined_stks order matches insertion order of combined_aggregated.
            dedup_to_index: Dict[DedupKey, int] = {
                k: i for i, k in enumerate(combined_aggregated.keys())
            }
            combined_stks.extend(combined_aggregated.values())

            # Build the run-length-encoded timeline of stitched stacks for
            # the experimental timeline view. Each emitted event is a
            # CombinedStackTimelineEvent — t_sec is normalized relative to
            # the first sample so the GUI can place events on a
            # [0, elapsed_time] axis; stack_index references combined_stks.
            if stats.combined_stacks_timeline and combined_stks:
                t0 = stats.combined_stacks_timeline[0].timestamp
                for run in stats.combined_stacks_timeline:
                    run_dedup_key = raw_to_dedup_key.get(run.stack_key)
                    if run_dedup_key is None:
                        continue
                    idx = dedup_to_index.get(run_dedup_key)
                    if idx is None:
                        continue
                    # Two adjacent runs may have collapsed to the same
                    # dedup_key (different raw IPs in the same function).
                    # Merge them so the wire format stays compact.
                    if (
                        combined_stks_timeline
                        and combined_stks_timeline[-1]["stack_index"] == idx
                    ):
                        combined_stks_timeline[-1]["count"] += run.count
                    else:
                        event = CombinedStackTimelineEvent(
                            t_sec=round(run.timestamp - t0, 6),
                            stack_index=idx,
                            count=run.count,
                        )
                        combined_stks_timeline.append(event.model_dump())

        # Aggregate bytes from native-thread allocations that have no
        # Python frame (see pywhere.cpp <native> sentinel). These are not
        # attributable to any source line, so surface them at the top level.
        native_samples = stats.memory_stats.memory_malloc_samples.get(
            Filename("<native>"), {}
        )
        native_allocations_mb = sum(native_samples.values())

        # Serialize memory_stacks: Python call stacks captured at malloc-
        # sample time, weighted by MB attributed to each sample. Reuses the
        # combined_stacks wire shape (list of (frames, weight)) with only
        # kind="py" frames so the GUI's flame-tree builder works unchanged.
        #
        # Function names are resolved here (at JSON serialization time)
        # rather than during sample processing, because name resolution
        # requires reading source files — if we did it on the sigqueue
        # thread, the resulting allocations would be captured by the
        # interposer and show up as artifacts in the user's profile.
        memory_stks: List[Tuple[List[Dict[str, Any]], float]] = []
        if stats.memory_stacks:
            # We still read each source file up to once, but only to
            # resolve enclosing-def names for ``display_name``. The
            # per-frame ``code_line`` string is no longer emitted (the GUI
            # looks it up on demand from ``files[filename].lines`` — see
            # P5). ``_mem_source_load`` populates the cache; callers ask
            # ``_mem_source_lines`` for the cached list.
            mem_source_cache: Dict[str, Optional[List[str]]] = {}

            def _mem_source_load(filename: str) -> Optional[List[str]]:
                if filename in mem_source_cache:
                    return mem_source_cache[filename]
                lines: Optional[List[str]] = None
                try:
                    with open(filename, encoding="utf-8") as src:
                        lines = src.readlines()
                except (OSError, UnicodeDecodeError):
                    cached = linecache.getlines(filename)
                    if cached:
                        lines = cached
                mem_source_cache[filename] = lines
                return lines

            def _enclosing_function(filename: str, lineno: int) -> Optional[str]:
                """Find the enclosing `def` name for (filename, lineno) by
                scanning source text. Returns None if no enclosing function
                (i.e. module scope). Mirrors the rule used for CPU stacks:
                a def encloses the line iff its body indent is strictly less
                than the target line's indent."""
                lines_list = _mem_source_load(filename)
                if not lines_list or lineno < 1 or lineno > len(lines_list):
                    return None
                target_line = lines_list[lineno - 1]
                stripped = target_line.lstrip()
                if not stripped or stripped.startswith("#"):
                    return None
                target_indent = len(target_line) - len(stripped)
                if target_indent <= 0:
                    return None
                for i in range(lineno - 2, -1, -1):
                    line = lines_list[i]
                    m = _DEF_RE.match(line)
                    if m:
                        header_indent = len(m.group(1))
                        if header_indent < target_indent:
                            return m.group(2)
                        continue
                    ls = line.lstrip()
                    if not ls or ls.startswith("#"):
                        continue
                    ind = len(line) - len(ls)
                    if ind < target_indent:
                        if ind == 0:
                            return None
                        target_indent = ind
                return None

            name_cache: Dict[Tuple[str, int], Optional[str]] = {}

            def _resolved_name(filename: str, lineno: int) -> str:
                key = (filename, lineno)
                if key in name_cache:
                    cached_name = name_cache[key]
                else:
                    cached_name = _enclosing_function(filename, lineno)
                    name_cache[key] = cached_name
                return cached_name if cached_name else "<module>"

            for stk, mb in stats.memory_stacks.items():
                frames: List[Dict[str, Any]] = []
                for sf in stk:
                    display = (
                        sf.function_name
                        if sf.function_name
                        else (_resolved_name(sf.filename, sf.line_number))
                    )
                    frames.append(
                        {
                            "kind": "py",
                            "display_name": display,
                            "filename_or_module": sf.filename,
                            "line": sf.line_number,
                            "ip": None,
                            "offset": None,
                        }
                    )
                if frames and mb > 0:
                    memory_stks.append((frames, round(mb, 6)))

        output: Dict[str, Any] = {
            "program": program,
            "entrypoint_dir": entrypoint_dir,
            "args": program_args,
            "filename": program_path,
            "alloc_samples": stats.memory_stats.alloc_samples,
            "elapsed_time_sec": stats.elapsed_time,
            "start_time_absolute": stats.start_time_absolute,
            "start_time_perf": stats.start_time_perf,
            "growth_rate": growth_rate,
            "max_footprint_mb": stats.memory_stats.max_footprint,
            "native_allocations_mb": native_allocations_mb,
            "max_footprint_python_fraction": stats.memory_stats.max_footprint_python_fraction,
            "max_footprint_fname": (
                stats.memory_stats.max_footprint_loc[0]
                if stats.memory_stats.max_footprint_loc
                else None
            ),
            "max_footprint_lineno": (
                stats.memory_stats.max_footprint_loc[1]
                if (
                    stats.memory_stats.max_footprint_loc
                    and stats.memory_stats.max_footprint_loc[1] > 0
                )
                else None
            ),
            "files": {},
            "gpu": self.gpu,
            "gpu_device": self.gpu_device,
            "memory": profile_memory,
            "async_profile": profile_async,
            "samples": compressed_footprint_samples if profile_memory else [],
            "stacks": stks,
            # _ResolvedNativeFrame is a dataclass, not a dict; reshape into
            # the on-wire [module, symbol, ip, offset] list at the output
            # boundary (preserves the existing JSON layout).
            # ``native_stacks`` was previously emitted here as a list of
            # resolved-and-trimmed native-frame tuples. It was redundant
            # with ``combined_stacks`` (see comment above at the deleted
            # native_stks construction) and no consumer read it. Dropped
            # from the JSON wire format; the in-process aggregate at
            # ``stats.native_stacks`` is unchanged.
            # Pydantic CombinedStackFrame instances aren't JSON-serializable
            # directly; convert to plain dicts at the output boundary.
            "combined_stacks": [
                ([frame.model_dump() for frame in frames], hits)
                for frames, hits in combined_stks
            ],
            "combined_stacks_timeline": combined_stks_timeline,
            # Memory-weighted Python stacks for the memory flame chart.
            # Each entry is (frames, mb). Only populated when --stacks and
            # --memory are both enabled.
            "memory_stacks": memory_stks,
        }

        # Build a list of files we will actually report on.
        report_files: List[Filename] = []
        # Sort in descending order of CPU cycles, and then ascending order by filename
        for fname in sorted(
            all_instrumented_files,
            key=lambda f: (-(stats.cpu_stats.cpu_samples[f]), f),
        ):
            fname = Filename(fname)
            try:
                percent_cpu_time = (
                    100
                    * stats.cpu_stats.cpu_samples[fname]
                    / stats.elapsed_time
                    # 100 * stats.cpu_samples[fname] / stats.total_cpu_samples
                )
            except ZeroDivisionError:
                percent_cpu_time = 0

            # Ignore files responsible for less than some percent of execution time and fewer than a threshold # of mallocs.
            if (
                sum(stats.memory_stats.memory_malloc_samples[fname].values())
                < self.malloc_threshold
                and percent_cpu_time < self.cpu_percent_threshold
            ):
                continue

            report_files.append(fname)

        # Don't actually output the profile if we are a child process.
        # Instead, write info to disk for the main process to collect.
        if pid:
            stats.output_stats(pid, python_alias_dir)
            # Return a value to indicate that the stats were successfully
            # output to the proper directory
            return {"is_child": True}

        if len(report_files) == 0:
            return {}

        for fname in report_files:

            # If the file was actually a Jupyter (IPython) cell,
            # restore its name, as in "[12]".
            fname_print = fname

            result = re.match(r"_ipython-input-([0-9]+)-.*", fname_print)
            if result:
                fname_print = Filename("[" + result.group(1) + "]")

            # Leak analysis
            # First, compute AVERAGE memory consumption.
            avg_mallocs: Dict[LineNumber, float] = defaultdict(float)
            for line_no in stats.memory_stats.memory_malloc_count[fname]:
                n_malloc_mb = stats.memory_stats.memory_aggregate_footprint[fname][
                    line_no
                ]
                count = stats.memory_stats.memory_malloc_count[fname][line_no]
                if count:
                    avg_mallocs[line_no] = n_malloc_mb / count
                else:
                    # Setting to n_malloc_mb addresses the edge case where this allocation is the last line executed.
                    avg_mallocs[line_no] = n_malloc_mb

            avg_mallocs = dict(
                sorted(avg_mallocs.items(), key=itemgetter(1), reverse=True)
            )

            # Now only report potential leaks if the allocation
            # velocity (growth rate) is above some threshold.
            leaks = ScaleneLeakAnalysis.compute_leaks(
                growth_rate, stats, avg_mallocs, fname
            )

            # Sort in descending order by least likelihood
            leaks = sorted(leaks, key=itemgetter(1), reverse=True)

            reported_leaks = {}

            for leak_lineno, leak_likelihood, leak_velocity in leaks:
                reported_leaks[str(leak_lineno)] = {
                    "likelihood": leak_likelihood,
                    "velocity_mb_s": leak_velocity / stats.elapsed_time,
                }

            # Print header.
            if not stats.cpu_stats.total_cpu_samples:
                percent_cpu_time = 0
            else:
                percent_cpu_time = (
                    100
                    * stats.cpu_stats.cpu_samples[fname]
                    / stats.cpu_stats.total_cpu_samples
                )

            # Print out the the profile for the source, line by line.
            # First try to read from the filesystem
            full_fname = fname
            code_lines = None
            try:
                with open(full_fname, encoding="utf-8") as source_file:
                    code_lines = source_file.readlines()
            except (FileNotFoundError, OSError):
                # For exec'd code, the source may be in linecache
                # (e.g., files named <exec_N> or <eval_N>)
                cached_lines = linecache.getlines(fname)
                if cached_lines:
                    code_lines = cached_lines
            if code_lines is None:
                continue
            # Find all enclosing regions (loops or function defs) for each line of code.

            code_str = "".join(code_lines)

            enclosing_regions = ScaleneAnalysis.find_regions(code_str)
            outer_loop = ScaleneAnalysis.find_outermost_loop(code_str)
            function_boundaries = ScaleneAnalysis.find_functions(code_str)
            imports = ScaleneAnalysis.get_native_imported_modules(code_str)

            output["files"][fname_print] = {
                "percent_cpu_time": percent_cpu_time,
                "lines": [],
                "leaks": reported_leaks,
                "imports": imports,
            }

            # First pass: collect all line profile data
            line_profiles = []
            for lineno, line in enumerate(code_lines, start=1):
                # Protect against JS 'injection' in Python comments by replacing some characters with Unicode.
                # This gets unescaped in scalene-gui.js.
                line = line.replace("&", "\\u0026")
                line = line.replace("<", "\\u003c")
                line = line.replace(">", "\\u003e")
                profile_line = self.output_profile_line(
                    fname=fname,
                    fname_print=fname_print,
                    line_no=LineNumber(lineno),
                    line=line,
                    stats=stats,
                    profile_this_code=profile_this_code,
                    profile_memory=profile_memory,
                    profile_async=profile_async,
                    force_print=False,
                )
                if profile_line:
                    profile_line["start_region_line"] = enclosing_regions[lineno][0]
                    profile_line["end_region_line"] = enclosing_regions[lineno][1]
                    profile_line["start_outermost_loop"] = outer_loop[lineno][0]
                    profile_line["end_outermost_loop"] = outer_loop[lineno][1]
                    profile_line["start_function_line"] = function_boundaries[lineno][0]
                    profile_line["end_function_line"] = function_boundaries[lineno][1]
                    line_profiles.append(profile_line)

            # Second pass: normalize CPU percentages to sum to <= 100%
            # This handles cases where torch profiler timing overlaps with
            # signal-sampled timing (e.g., JIT function internals + call site)
            total_cpu = sum(
                p.get("n_cpu_percent_c", 0)
                + p.get("n_cpu_percent_python", 0)
                + p.get("n_sys_percent", 0)
                for p in line_profiles
            )
            if total_cpu > 100.0:
                scale_factor = 100.0 / total_cpu
                for profile_line in line_profiles:
                    profile_line["n_cpu_percent_c"] *= scale_factor
                    profile_line["n_cpu_percent_python"] *= scale_factor
                    profile_line["n_sys_percent"] *= scale_factor

            # Third pass: validate and add to output
            for profile_line in line_profiles:
                try:
                    LineDetail(**profile_line)
                except ValidationError as e:
                    print("Warning: JSON failed validation:")
                    print(e)

                # When reduced-profile set, only output if the payload for the line is non-zero.
                if reduced_profile:
                    profile_line_copy = copy.copy(profile_line)
                    del profile_line_copy["line"]
                    del profile_line_copy["lineno"]
                    if not any(profile_line_copy.values()):
                        continue
                output["files"][fname_print]["lines"].append(profile_line)

            fn_stats = stats.build_function_stats(fname)
            # Check CPU samples and memory samples.
            print_fn_summary = False
            all_samples = set()
            all_samples |= set(fn_stats.cpu_stats.cpu_samples_python.keys())
            all_samples |= set(fn_stats.cpu_stats.cpu_samples_c.keys())
            all_samples |= set(fn_stats.cpu_stats.torch_cpu_time.keys())
            all_samples |= set(fn_stats.cpu_stats.torch_gpu_time.keys())
            all_samples |= set(fn_stats.memory_stats.memory_malloc_samples.keys())
            all_samples |= set(fn_stats.memory_stats.memory_free_samples.keys())
            all_samples |= set(fn_stats.gpu_stats.gpu_samples.keys())
            print_fn_summary = any(fn != fname for fn in all_samples)
            output["files"][fname_print]["functions"] = []
            if print_fn_summary:
                for fn_name in sorted(
                    all_samples,
                    key=lambda k: stats.firstline_map[k],
                ):
                    if fn_name == fname:
                        continue
                    profile_line = self.output_profile_line(
                        fname=fn_name,
                        fname_print=fn_name,
                        # line 1 is where function stats are
                        # accumulated; see
                        # ScaleneStatistics.build_function_stats
                        line_no=LineNumber(1),
                        line=fn_name,  # Set the source line to just the function name.
                        stats=fn_stats,
                        profile_this_code=profile_this_code,
                        profile_memory=profile_memory,
                        profile_async=profile_async,
                        force_print=True,
                    )
                    if profile_line:
                        # Fix the line number to point to the first line of the function.
                        profile_line["lineno"] = stats.firstline_map[fn_name]
                        output["files"][fname_print]["functions"].append(profile_line)

        # Validate the schema
        try:
            ScaleneJSONSchema(**output)
        except ValidationError as e:
            print("Warning: JSON failed validation:")
            print(e)
        return output
