"""A GPU reading on macOS must free the statistics dictionary IOKit gives it.

IORegistryEntryCreateCFProperty returns a CF object, which is freed with
CFRelease. The reader used IOObjectRelease, which fails for a CF object, so
every reading leaked the dictionary (about 800 bytes).
"""

import ctypes
import sys

import pytest

pytestmark = pytest.mark.skipif(sys.platform != "darwin", reason="macOS only")


def test_reading_frees_the_statistics_dictionary(monkeypatch) -> None:
    from scalene import scalene_apple_gpu as g

    gpu = g.ScaleneAppleGPU()
    if not gpu.has_gpu():
        pytest.skip("no Apple GPU")

    cf = g.corefoundation
    cf.CFRetain.argtypes = [ctypes.c_void_p]
    cf.CFRetain.restype = ctypes.c_void_p
    cf.CFGetRetainCount.argtypes = [ctypes.c_void_p]
    cf.CFGetRetainCount.restype = ctypes.c_long

    created_objects = []
    create = g.IORegistryEntryCreateCFProperty  # the real one, saved before patching

    def create_and_keep(*args):
        obj = create(*args)

        # add our own owner, so we can look at retain counter
        cf.CFRetain(obj)
        owners = cf.CFGetRetainCount(obj)
        assert owners >= 2

        created_objects.append(obj)
        return obj

    monkeypatch.setattr(g, "IORegistryEntryCreateCFProperty", create_and_keep)
    g._read_perf_stats(gpu._service_obj)

    [dictionary] = created_objects
    owners = cf.CFGetRetainCount(dictionary)
    cf.CFRelease(dictionary)
    assert owners == 1  # only our owner is left (it means release works)
