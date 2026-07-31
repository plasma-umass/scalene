"""Regression test for issue #1063: non-ASCII --profile-only crashes (SIGSEGV).

Issue: https://github.com/plasma-umass/scalene/issues/1063

The ``pywhere`` extension's ``TraceConfig`` constructor converted each
``--profile-only`` pattern with ``PyUnicode_AsASCIIString`` and fed the
result straight into ``PyBytes_AsString`` without a NULL check. For a
non-ASCII value like ``é`` the ASCII conversion returns NULL, so the
unchecked ``PyBytes_AsString(NULL)`` dereference crashed the whole
process with SIGSEGV (the issue's native repro was
``pywhere.register_files_to_profile(["é"], ".", True, None)``).

The fix decodes patterns as UTF-8 via ``PyUnicode_AsUTF8AndSize`` and
skips items that fail to decode instead of dereferencing NULL.

These tests drive the same ``TraceConfig`` constructor through
``pywhere.setup_trace_config`` (the CPU-only registration entry point,
which unlike ``register_files_to_profile`` does not require libscalene
to be preloaded). Running it in-process means a regression reappears as
a hard crash of the test process / interpreter SIGSEGV — exactly the
failure mode from the bug report — rather than a flaky sampling result.
"""

import pytest

pywhere = pytest.importorskip("scalene.pywhere")


@pytest.mark.parametrize(
    "patterns",
    [
        ["é"],  # the exact value from the issue
        ["foo", "héllo", "bar"],  # non-ASCII mixed with ASCII
        ["日本語", "🎉"],  # multibyte / emoji
        ["ascii"],  # ASCII control
        [],  # empty list
    ],
)
def test_setup_trace_config_accepts_non_ascii(patterns):
    """Non-ASCII --profile-only patterns must not crash TraceConfig setup."""
    # A regression here dereferences NULL inside the extension and takes
    # down the whole interpreter, so reaching the assertion at all means
    # the crash is fixed.
    pywhere.setup_trace_config(patterns, ".", True, None)
    pywhere.setup_trace_config(patterns, ".", False, None)
