"""TraceConfig must not leak references to its Python arguments (issue #1116).

Each ``setup_trace_config`` / ``register_files_to_profile`` call replaces the
global TraceConfig. The constructor used to Py_IncRef the profile list and
base path and never release them, so every replacement leaked a reference to
each. Runs in a subprocess because it replaces process-global native state.
"""

import subprocess
import sys
import textwrap

import pytest

pytestmark = pytest.mark.skipif(
    sys.platform == "win32", reason="exercises the POSIX pywhere build"
)

PROBE = textwrap.dedent("""
    import os, sys
    from scalene import pywhere

    items = ["foo", "bar"]
    base = os.path.abspath("some-base-path-for-test")
    pkg = os.path.abspath("some-pkg-path-for-test")
    before = (sys.getrefcount(items), sys.getrefcount(base), sys.getrefcount(pkg))
    for _ in range(50):
        pywhere.setup_trace_config(items, base, False, pkg)
        try:
            pywhere.register_files_to_profile(items, base, False, pkg)
        except Exception:
            pass  # "Unable to find p_whereInPython" without libscalene
    after = (sys.getrefcount(items), sys.getrefcount(base), sys.getrefcount(pkg))
    print(before, after)
    assert before == after, (before, after)
    print("OK")
    """)


def test_trace_config_replacement_does_not_leak_references():
    proc = subprocess.run(
        [sys.executable, "-c", PROBE], capture_output=True, text=True, timeout=60
    )
    assert proc.returncode == 0, f"{proc.stdout}\n{proc.stderr}"
    assert "OK" in proc.stdout
