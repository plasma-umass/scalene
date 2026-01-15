import ctypes
import platform
from typing import Tuple

from scalene.scalene_accelerator import ScaleneAccelerator

# ---------------------------------------------------------------------------
# 1. Define the needed IOKit / CoreFoundation constants and function signatures
# ---------------------------------------------------------------------------
iokit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
corefoundation = ctypes.cdll.LoadLibrary(
    "/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation"
)

CFTypeRef = ctypes.c_void_p
CFAllocatorRef = ctypes.c_void_p
IOOptionBits = ctypes.c_uint32
io_registry_entry_t = ctypes.c_void_p
mach_port_t = ctypes.c_void_p

try:
    # On Intel Macs, kIOMasterPortDefault might be defined; on Apple Silicon, it may just be 0.
    kIOMasterPortDefault = ctypes.c_void_p.in_dll(iokit, "kIOMasterPortDefault")
except ValueError:
    kIOMasterPortDefault = mach_port_t(0)

# --- IOKit (service) APIs
IOServiceMatching = iokit.IOServiceMatching
IOServiceMatching.argtypes = [ctypes.c_char_p]
IOServiceMatching.restype = CFTypeRef

IOServiceGetMatchingService = iokit.IOServiceGetMatchingService
IOServiceGetMatchingService.argtypes = [mach_port_t, CFTypeRef]
IOServiceGetMatchingService.restype = io_registry_entry_t

IOObjectRelease = iokit.IOObjectRelease
IOObjectRelease.argtypes = [io_registry_entry_t]
IOObjectRelease.restype = ctypes.c_int  # kern_return_t

# --- IOKit (registry) APIs
IORegistryEntryCreateCFProperty = iokit.IORegistryEntryCreateCFProperty
IORegistryEntryCreateCFProperty.argtypes = [
    io_registry_entry_t,  # entry
    CFTypeRef,  # key
    CFAllocatorRef,  # allocator
    IOOptionBits,  # options
]
IORegistryEntryCreateCFProperty.restype = CFTypeRef

# --- CF APIs
CFGetTypeID = corefoundation.CFGetTypeID
CFGetTypeID.argtypes = [CFTypeRef]
CFGetTypeID.restype = ctypes.c_long

CFDictionaryGetTypeID = corefoundation.CFDictionaryGetTypeID
CFDictionaryGetTypeID.argtypes = []
CFDictionaryGetTypeID.restype = ctypes.c_long

CFStringCreateWithCString = corefoundation.CFStringCreateWithCString
CFStringCreateWithCString.argtypes = [CFAllocatorRef, ctypes.c_char_p, ctypes.c_uint32]
CFStringCreateWithCString.restype = CFTypeRef

CFDictionaryGetValue = corefoundation.CFDictionaryGetValue
CFDictionaryGetValue.argtypes = [CFTypeRef, CFTypeRef]
CFDictionaryGetValue.restype = CFTypeRef

CFNumberGetTypeID = corefoundation.CFNumberGetTypeID
CFNumberGetTypeID.argtypes = []
CFNumberGetTypeID.restype = ctypes.c_long

CFNumberGetValue = corefoundation.CFNumberGetValue
CFNumberGetValue.argtypes = [CFTypeRef, ctypes.c_int, ctypes.c_void_p]
CFNumberGetValue.restype = ctypes.c_bool

kCFNumberSInt64Type = 4  # 64-bit integers

# --- Pre-create CFStrings for keys to avoid repeated creation
cf_str_gpu_core_count = CFStringCreateWithCString(None, b"gpu-core-count", 0)
cf_str_perf_stats = CFStringCreateWithCString(None, b"PerformanceStatistics", 0)
cf_str_device_util = CFStringCreateWithCString(None, b"Device Utilization %", 0)
cf_str_inuse_mem = CFStringCreateWithCString(None, b"In use system memory", 0)


def _find_apple_gpu_service() -> io_registry_entry_t:
    """
    Grabs the first service matching "IOAccelerator" (integrated GPU).
    Returns None if not found.
    """
    matching = IOServiceMatching(b"IOAccelerator")
    if not matching:
        return None  # type: ignore[return-value]

    service_obj = IOServiceGetMatchingService(kIOMasterPortDefault, matching)
    # service_obj is automatically retained if found.
    # No need to release 'matching' (it is CFTypeRef, but handled by the system).
    return service_obj  # type: ignore[no-any-return]


def _read_gpu_core_count(service_obj: io_registry_entry_t) -> int:
    """
    Reads the top-level "gpu-core-count" from the service.
    (Only needed once, as it shouldn't change.)
    """
    if not service_obj:
        return 0
    cf_core_count = IORegistryEntryCreateCFProperty(
        service_obj, cf_str_gpu_core_count, None, 0
    )
    if not cf_core_count or (CFGetTypeID(cf_core_count) != CFNumberGetTypeID()):
        if cf_core_count:
            IOObjectRelease(cf_core_count)
        return 0

    val_container_64 = ctypes.c_longlong(0)
    success = CFNumberGetValue(
        cf_core_count, kCFNumberSInt64Type, ctypes.byref(val_container_64)
    )
    IOObjectRelease(cf_core_count)
    return val_container_64.value if success else 0


def _read_perf_stats(service_obj: io_registry_entry_t) -> Tuple[float, float]:
    """
    Returns (utilization [0..1], in_use_mem_MB).
    Reads the "PerformanceStatistics" sub-dict via IORegistryEntryCreateCFProperty.
    """
    if not service_obj:
        return (0.0, 0.0)

    # Grab the PerformanceStatistics dictionary
    perf_dict_ref = IORegistryEntryCreateCFProperty(
        service_obj, cf_str_perf_stats, None, 0
    )
    if not perf_dict_ref or (CFGetTypeID(perf_dict_ref) != CFDictionaryGetTypeID()):
        if perf_dict_ref:
            IOObjectRelease(perf_dict_ref)
        return (0.0, 0.0)

    # Device Utilization
    device_util = 0.0
    util_val_ref = CFDictionaryGetValue(perf_dict_ref, cf_str_device_util)
    if util_val_ref and (CFGetTypeID(util_val_ref) == CFNumberGetTypeID()):
        val64 = ctypes.c_longlong(0)
        if CFNumberGetValue(util_val_ref, kCFNumberSInt64Type, ctypes.byref(val64)):
            device_util = val64.value / 100.0

    # In-use memory
    in_use_mem = 0.0
    mem_val_ref = CFDictionaryGetValue(perf_dict_ref, cf_str_inuse_mem)
    if mem_val_ref and (CFGetTypeID(mem_val_ref) == CFNumberGetTypeID()):
        val64 = ctypes.c_longlong(0)
        if CFNumberGetValue(mem_val_ref, kCFNumberSInt64Type, ctypes.byref(val64)):
            in_use_mem = float(val64.value) / 1048576.0  # convert bytes -> MB

    IOObjectRelease(perf_dict_ref)
    return (device_util, in_use_mem)


class ScaleneAppleGPU(ScaleneAccelerator):
    """Wrapper for Apple integrated GPU stats, using direct IOKit calls.

    For accurate per-process GPU timing, this class integrates with PyTorch's
    MPS timing. Without PyTorch MPS, GPU metrics are not reported to avoid
    showing misleading system-wide metrics.
    """

    def __init__(self) -> None:
        assert platform.system() == "Darwin", "Only works on macOS."
        # Cache the single service object if found:
        self._service_obj = _find_apple_gpu_service()
        # Cache the number of cores:
        self._core_count = _read_gpu_core_count(self._service_obj)
        # Per-process MPS timing from PyTorch (when available)
        self._torch_mps_time: float = 0.0
        self._has_per_process_timing: bool = False

    def gpu_device(self) -> str:
        return "GPU"

    def has_gpu(self) -> bool:
        """Return True if we found an Apple integrated GPU service."""
        return bool(self._service_obj)

    def reinit(self) -> None:
        """No-op for compatibility with other GPU wrappers."""
        pass

    def get_num_cores(self) -> int:
        return self._core_count

    def set_torch_mps_time(self, time_seconds: float) -> None:
        """Set per-process MPS GPU time from PyTorch profiler.

        This is called by the profiler after the torch profiler stops,
        passing the MPS GPU time measured via torch.mps.synchronize().
        """
        self._torch_mps_time = time_seconds
        self._has_per_process_timing = time_seconds > 0

    def has_per_process_timing(self) -> bool:
        """Return True if per-process GPU timing is available.

        Per-process timing requires PyTorch MPS to be used by the profiled program.
        """
        return self._has_per_process_timing

    def get_stats(self) -> Tuple[float, float]:
        """Return (gpu_time_seconds, memory_in_use_MB).

        Only returns non-zero values when per-process MPS timing is available.
        This avoids showing misleading system-wide metrics for non-GPU programs.
        """
        if not self.has_gpu():
            return (0.0, 0.0)

        # Only report GPU stats when we have per-process timing
        # (i.e., the program actually used PyTorch MPS)
        if not self._has_per_process_timing:
            return (0.0, 0.0)

        try:
            # Memory from IOKit (useful as context when GPU is being used)
            _, mem = _read_perf_stats(self._service_obj)
            return (self._torch_mps_time, mem)
        except Exception:
            return (0.0, 0.0)

    def __del__(self) -> None:
        """Release the service object if it exists."""
        if self._service_obj:
            IOObjectRelease(self._service_obj)
            self._service_obj = None  # type: ignore[assignment]


if __name__ == "__main__":
    import time

    gpu = ScaleneAppleGPU()
    while True:
        start = time.perf_counter()
        util, mem = gpu.get_stats()
        stop = time.perf_counter()
        print(f"Elapsed time: {stop - start:.6f} seconds.")
        cores = gpu.get_num_cores()
        print(
            f"GPU Utilization: {util*100:.1f}%, "
            f"In-Use GPU Memory: {mem:.2f} MB, "
            f"GPU Core Count: {cores}"
        )
        time.sleep(0.5)
