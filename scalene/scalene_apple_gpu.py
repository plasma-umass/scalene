import platform
import ctypes
import time
from typing import Tuple

# ---------------------------------------------------------------------------
# 1. Define the needed IOKit / CoreFoundation constants and function signatures
# ---------------------------------------------------------------------------
iokit = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/IOKit.framework/IOKit")
corefoundation = ctypes.cdll.LoadLibrary("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")

CFTypeRef = ctypes.c_void_p
CFAllocatorRef = ctypes.c_void_p
IOOptionBits = ctypes.c_uint32
io_iterator_t = ctypes.c_void_p
io_registry_entry_t = ctypes.c_void_p
mach_port_t = ctypes.c_void_p

try:
    # On Intel Macs, kIOMasterPortDefault might be defined; on Apple Silicon, it may just be 0.
    kIOMasterPortDefault = ctypes.c_void_p.in_dll(iokit, 'kIOMasterPortDefault')
except ValueError:
    kIOMasterPortDefault = mach_port_t(0)

IOServiceMatching = iokit.IOServiceMatching
IOServiceMatching.argtypes = [ctypes.c_char_p]
IOServiceMatching.restype = CFTypeRef

IOServiceGetMatchingServices = iokit.IOServiceGetMatchingServices
IOServiceGetMatchingServices.argtypes = [
    mach_port_t,
    CFTypeRef,
    ctypes.POINTER(io_iterator_t),
]
IOServiceGetMatchingServices.restype = ctypes.c_int  # kern_return_t

IOIteratorNext = iokit.IOIteratorNext
IOIteratorNext.argtypes = [io_iterator_t]
IOIteratorNext.restype = io_registry_entry_t

IOObjectRelease = iokit.IOObjectRelease
IOObjectRelease.argtypes = [io_registry_entry_t]
IOObjectRelease.restype = ctypes.c_int  # kern_return_t

IORegistryEntryCreateCFProperties = iokit.IORegistryEntryCreateCFProperties
IORegistryEntryCreateCFProperties.argtypes = [
    io_registry_entry_t,
    ctypes.POINTER(CFTypeRef),
    CFAllocatorRef,
    IOOptionBits,
]
IORegistryEntryCreateCFProperties.restype = CFTypeRef

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

CFNumberGetType = corefoundation.CFNumberGetType
CFNumberGetType.argtypes = [CFTypeRef]
CFNumberGetType.restype = ctypes.c_int

CFShow = corefoundation.CFShow
CFShow.argtypes = [CFTypeRef]

kCFNumberSInt64Type = 4  # 64-bit integers

def cfstr(py_str: str) -> CFTypeRef:
    """Helper to create a CFString from a Python string."""
    return CFStringCreateWithCString(None, py_str.encode('utf-8'), 0)

def _read_apple_gpu_stats_and_cores() -> Tuple[float, float, int]:
    """
    Reads from IOService class "IOAccelerator" and returns:
      (device_util, in_use_mem, gpu_core_count)
    where:
      - device_util is a fraction [0..1].
      - in_use_mem is in megabytes.
      - gpu_core_count is an integer from top-level "gpu-core-count".
    """
    matching_dict = IOServiceMatching(b"IOAccelerator")
    if not matching_dict:
        # debug_print("[DEBUG] Could not create matching dictionary.")
        return (0.0, 0.0, 0)

    service_iterator = io_iterator_t()
    kr = IOServiceGetMatchingServices(kIOMasterPortDefault, matching_dict, ctypes.byref(service_iterator))
    if kr != 0:
        # debug_print(f"[DEBUG] IOServiceGetMatchingServices returned kr={kr}. Possibly no services found.")
        return (0.0, 0.0, 0)

    device_util = 0.0
    in_use_mem = 0.0
    gpu_core_count = 0

    while True:
        service_object = IOIteratorNext(service_iterator)
        if not service_object:
            # No more services
            break

        props_ref = CFTypeRef()
        IORegistryEntryCreateCFProperties(service_object, ctypes.byref(props_ref), None, 0)

        # The top-level dictionary:
        if props_ref and CFGetTypeID(props_ref) == CFDictionaryGetTypeID():
            # 1. Grab "gpu-core-count" at the top level
            top_key_cores = cfstr("gpu-core-count")
            core_val_ref = CFDictionaryGetValue(props_ref, top_key_cores)
            if core_val_ref and (CFGetTypeID(core_val_ref) == CFNumberGetTypeID()):
                val_container_64 = ctypes.c_longlong(0)
                success = CFNumberGetValue(core_val_ref, kCFNumberSInt64Type, ctypes.byref(val_container_64))
                if success:
                    gpu_core_count = val_container_64.value
            IOObjectRelease(top_key_cores)

            # 2. Check for sub-dictionary "PerformanceStatistics"
            performance_key = cfstr("PerformanceStatistics")
            performance_dict_ref = CFDictionaryGetValue(props_ref, performance_key)
            IOObjectRelease(performance_key)

            if performance_dict_ref and (CFGetTypeID(performance_dict_ref) == CFDictionaryGetTypeID()):
                cf_key_util = cfstr("Device Utilization %")
                cf_key_mem = cfstr("In use system memory")

                # Device Utilization
                util_val_ref = CFDictionaryGetValue(performance_dict_ref, cf_key_util)
                if util_val_ref and (CFGetTypeID(util_val_ref) == CFNumberGetTypeID()):
                    val_container_64 = ctypes.c_longlong(0)
                    success = CFNumberGetValue(util_val_ref, kCFNumberSInt64Type, ctypes.byref(val_container_64))
                    if success:
                        device_util = val_container_64.value / 100.0

                # In use system memory
                mem_val_ref = CFDictionaryGetValue(performance_dict_ref, cf_key_mem)
                if mem_val_ref and (CFGetTypeID(mem_val_ref) == CFNumberGetTypeID()):
                    val_container_64 = ctypes.c_longlong(0)
                    success = CFNumberGetValue(mem_val_ref, kCFNumberSInt64Type, ctypes.byref(val_container_64))
                    if success:
                        in_use_mem = float(val_container_64.value) / 1048576.0

                IOObjectRelease(cf_key_util)
                IOObjectRelease(cf_key_mem)

            IOObjectRelease(props_ref)

        IOObjectRelease(service_object)

        if (device_util > 0.0 or in_use_mem > 0.0) and gpu_core_count > 0:
            # Success, break
            break

    IOObjectRelease(service_iterator)
    return (device_util, in_use_mem, gpu_core_count)


class ScaleneAppleGPU:
    """Wrapper class for Apple integrated GPU statistics, using direct IOKit calls."""

    def __init__(self, sampling_frequency: int = 100) -> None:
        assert platform.system() == "Darwin"
        self.gpu_sampling_frequency = sampling_frequency
        self.core_count = self._get_num_cores()

    def gpu_device(self) -> str:
        return "GPU"

    def has_gpu(self) -> bool:
        """Return True if the system likely has an Apple integrated GPU."""
        return True

    def reinit(self) -> None:
        """No-op for compatibility with other GPU wrappers."""
        pass

    def get_num_cores(self) -> int:
        return self.core_count

    def get_stats(self) -> Tuple[float, float]:
        """Returns a tuple of (utilization%, memory in use in megabytes)."""
        if not self.has_gpu():
            return (0.0, 0.0)
        try:
            util, in_use, _ = _read_apple_gpu_stats_and_cores()
            return (util, in_use)
        except Exception as ex:
            return (0.0, 0.0)
        
    def _get_num_cores(self) -> int:
        """
        Retrieves the 'gpu-core-count' property from the top-level dictionary.
        Returns 0 if not found.
        """
        # We reuse the same function that gathers utilization & memory
        _, _, core_count = _read_apple_gpu_stats_and_cores()
        return core_count
    
if __name__ == "__main__":
    gpu = ScaleneAppleGPU()
    while True:
        util, mem = gpu.get_stats()
        cores = gpu.get_num_cores()
        print(
            f"GPU Utilization: {util*100:.1f}%, "
            f"In-Use GPU Memory: {mem} megabytes, "
            f"GPU Core Count: {cores}"
        )
        time.sleep(2)
