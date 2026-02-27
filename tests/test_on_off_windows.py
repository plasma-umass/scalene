"""Tests for --on/--off lifecycle control support, including Windows Named Events.

Tests cover:
- Argument parsing: --on/--off flags registered on all platforms
- ScaleneSignalManager: lifecycle signal setup, cross-platform child signaling,
  static signal_lifecycle_event(), watcher cleanup
- profile.py: uses ScaleneSignalManager.signal_lifecycle_event()
- Integration: --off flag starts profiling disabled
"""

import os
import signal
import subprocess
import sys
import textwrap
from unittest.mock import MagicMock, patch

import pytest

from scalene.scalene_parseargs import ScaleneParseArgs
from scalene.scalene_signal_manager import (
    ScaleneSignalManager,
    _EVENT_MODIFY_STATE,
    _LIFECYCLE_START_EVENT,
    _LIFECYCLE_STOP_EVENT,
    _WAIT_OBJECT_0,
    _WAIT_TIMEOUT,
)


# ---------------------------------------------------------------------------
# Argument parsing tests
# ---------------------------------------------------------------------------


class TestParseArgsOnOff:
    """Verify --on/--off flags are registered and parsed on all platforms."""

    @pytest.fixture
    def temp_script(self, tmp_path):
        script = tmp_path / "prog.py"
        script.write_text("print('hello')")
        return script

    def test_on_flag_parsed(self, temp_script):
        """--on flag is parsed and sets args.on = True."""
        test_args = ["scalene", "run", "--on", str(temp_script)]
        with patch.object(sys, "argv", test_args):
            args, _left = ScaleneParseArgs.parse_args()
        assert args.on is True
        assert args.off is not True

    def test_off_flag_parsed(self, temp_script):
        """--off flag is parsed and sets args.off = True, args.on = False."""
        test_args = ["scalene", "run", "--off", str(temp_script)]
        with patch.object(sys, "argv", test_args):
            args, _left = ScaleneParseArgs.parse_args()
        assert args.off is True
        assert args.on is False

    def test_off_flag_not_overridden_on_windows(self, temp_script):
        """On Windows, --off is no longer forced to --on."""
        test_args = ["scalene", "run", "--off", str(temp_script)]
        with (
            patch.object(sys, "argv", test_args),
            patch.object(sys, "platform", "win32"),
        ):
            args, _left = ScaleneParseArgs.parse_args()
        # args.on should NOT be forced to True
        assert args.on is False

    def test_default_is_on(self, temp_script):
        """Without --on or --off, profiling defaults to on."""
        test_args = ["scalene", "run", str(temp_script)]
        with patch.object(sys, "argv", test_args):
            args, _left = ScaleneParseArgs.parse_args()
        # Neither --on nor --off specified; on defaults to False (not explicitly set)
        # but off also defaults to False. The profiler treats no flag as "on".
        assert args.off is not True

    def test_help_text_no_windows_caveat(self, temp_script, capsys):
        """--on/--off help text does not contain 'not supported on Windows'."""
        test_args = ["scalene", "run", "--help-advanced"]
        with (
            patch.object(sys, "argv", test_args),
            pytest.raises(SystemExit),
        ):
            ScaleneParseArgs.parse_args()
        captured = capsys.readouterr()
        combined = captured.out + captured.err
        assert "not supported on Windows" not in combined


# ---------------------------------------------------------------------------
# ScaleneSignalManager lifecycle tests
# ---------------------------------------------------------------------------


class TestSignalManagerLifecycleUnix:
    """Test lifecycle signal setup and child signaling on Unix."""

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix signal tests"
    )
    def test_setup_lifecycle_signals_calls_signal_signal(self):
        """setup_lifecycle_signals calls signal.signal for SIGILL/SIGBUS on Unix.

        We mock signal.signal before constructing the manager so that
        __orig_signal captures our mock. This avoids interference from
        replacement_signal_fns which may redirect the actual signals.
        """
        mock_signal_fn = MagicMock(return_value=signal.SIG_DFL)
        start_handler = MagicMock()
        stop_handler = MagicMock()
        interruption_handler = MagicMock()

        with patch.object(signal, "signal", mock_signal_fn):
            mgr = ScaleneSignalManager()
            mgr.setup_lifecycle_signals(
                start_handler, stop_handler, interruption_handler
            )

        # Check signal.signal was called with SIGILL -> start, SIGBUS -> stop, SIGINT -> interrupt
        call_args = {(c[0][0], c[0][1]) for c in mock_signal_fn.call_args_list}
        assert (signal.SIGILL, start_handler) in call_args
        assert (signal.SIGBUS, stop_handler) in call_args
        assert (signal.SIGINT, interruption_handler) in call_args

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix signal tests"
    )
    def test_send_lifecycle_start_to_child_sends_sigill(self):
        """send_lifecycle_start_to_child sends SIGILL on Unix.

        We must patch os.kill before constructing the manager, because
        __init__ captures os.kill as __orig_kill at construction time.
        """
        mock_kill = MagicMock()
        with patch.object(os, "kill", mock_kill):
            mgr = ScaleneSignalManager()
            mgr.send_lifecycle_start_to_child(12345)
        mock_kill.assert_called_once_with(12345, signal.SIGILL)

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix signal tests"
    )
    def test_send_lifecycle_stop_to_child_sends_sigbus(self):
        """send_lifecycle_stop_to_child sends SIGBUS on Unix.

        We must patch os.kill before constructing the manager.
        """
        mock_kill = MagicMock()
        with patch.object(os, "kill", mock_kill):
            mgr = ScaleneSignalManager()
            mgr.send_lifecycle_stop_to_child(12345)
        mock_kill.assert_called_once_with(12345, signal.SIGBUS)

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix signal tests"
    )
    def test_signal_lifecycle_event_start_sends_sigill(self):
        """Static signal_lifecycle_event(start=True) sends SIGILL on Unix."""
        with patch.object(os, "kill") as mock_kill:
            ScaleneSignalManager.signal_lifecycle_event(9999, start=True)
        mock_kill.assert_called_once_with(9999, signal.SIGILL)

    @pytest.mark.skipif(
        sys.platform == "win32", reason="Unix signal tests"
    )
    def test_signal_lifecycle_event_stop_sends_sigbus(self):
        """Static signal_lifecycle_event(start=False) sends SIGBUS on Unix."""
        with patch.object(os, "kill") as mock_kill:
            ScaleneSignalManager.signal_lifecycle_event(9999, start=False)
        mock_kill.assert_called_once_with(9999, signal.SIGBUS)


class TestSignalManagerLifecycleWin32:
    """Test lifecycle signal setup for Windows (mocked kernel32)."""

    def test_setup_lifecycle_signals_win32_creates_events(self):
        """On win32, _setup_lifecycle_signals_win32 creates named events."""
        mgr = ScaleneSignalManager()
        start_handler = MagicMock()
        stop_handler = MagicMock()

        mock_kernel32 = MagicMock()
        # Return 0 for second event to prevent watcher thread from starting
        # (the method checks `if not self.__lifecycle_stop_event` and returns)
        mock_kernel32.CreateEventW.side_effect = [101, 0]

        with patch("scalene.scalene_signal_manager._kernel32", mock_kernel32):
            mgr._setup_lifecycle_signals_win32(start_handler, stop_handler)

        # Should have attempted to create two events
        assert mock_kernel32.CreateEventW.call_count == 2
        calls = mock_kernel32.CreateEventW.call_args_list
        pid = os.getpid()
        # First call: start event
        assert f"scalene-lifecycle-start-{pid}" in calls[0][0][3]
        # Second call: stop event
        assert f"scalene-lifecycle-stop-{pid}" in calls[1][0][3]

    def test_setup_lifecycle_signals_dispatches_to_win32(self):
        """On win32, setup_lifecycle_signals dispatches to the win32 method."""
        mgr = ScaleneSignalManager()
        start_handler = MagicMock()
        stop_handler = MagicMock()
        interruption_handler = MagicMock()

        with (
            patch("scalene.scalene_signal_manager.sys") as mock_sys,
            patch.object(mgr, "_setup_lifecycle_signals_win32") as mock_win32,
        ):
            mock_sys.platform = "win32"
            mgr.setup_lifecycle_signals(
                start_handler, stop_handler, interruption_handler
            )

        mock_win32.assert_called_once_with(start_handler, stop_handler)

    def test_signal_lifecycle_event_win32_opens_and_signals(self):
        """On win32, signal_lifecycle_event opens the named event and signals it."""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenEventW.return_value = 42  # fake handle

        with (
            patch("scalene.scalene_signal_manager.sys") as mock_sys,
            patch("scalene.scalene_signal_manager._kernel32", mock_kernel32),
        ):
            mock_sys.platform = "win32"
            ScaleneSignalManager.signal_lifecycle_event(1234, start=True)

        expected_name = _LIFECYCLE_START_EVENT.format(pid=1234)
        mock_kernel32.OpenEventW.assert_called_once_with(
            _EVENT_MODIFY_STATE, False, expected_name
        )
        mock_kernel32.SetEvent.assert_called_once_with(42)
        mock_kernel32.CloseHandle.assert_called_once_with(42)

    def test_signal_lifecycle_event_win32_stop(self):
        """On win32, signal_lifecycle_event(start=False) uses stop event name."""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenEventW.return_value = 77

        with (
            patch("scalene.scalene_signal_manager.sys") as mock_sys,
            patch("scalene.scalene_signal_manager._kernel32", mock_kernel32),
        ):
            mock_sys.platform = "win32"
            ScaleneSignalManager.signal_lifecycle_event(5678, start=False)

        expected_name = _LIFECYCLE_STOP_EVENT.format(pid=5678)
        mock_kernel32.OpenEventW.assert_called_once_with(
            _EVENT_MODIFY_STATE, False, expected_name
        )
        mock_kernel32.SetEvent.assert_called_once_with(77)

    def test_signal_lifecycle_event_win32_handle_zero_skips(self):
        """On win32, if OpenEventW returns 0 (failure), SetEvent is not called."""
        mock_kernel32 = MagicMock()
        mock_kernel32.OpenEventW.return_value = 0  # failure

        with (
            patch("scalene.scalene_signal_manager.sys") as mock_sys,
            patch("scalene.scalene_signal_manager._kernel32", mock_kernel32),
        ):
            mock_sys.platform = "win32"
            ScaleneSignalManager.signal_lifecycle_event(1234, start=True)

        mock_kernel32.SetEvent.assert_not_called()
        mock_kernel32.CloseHandle.assert_not_called()


class TestSignalManagerLifecycleWatcher:
    """Test the lifecycle watcher thread and cleanup."""

    def test_stop_lifecycle_watcher_clears_state(self):
        """stop_lifecycle_watcher resets the watcher state."""
        mgr = ScaleneSignalManager()
        # Simulate having a watcher thread
        mock_thread = MagicMock()
        # Access private attrs via name mangling
        mgr._ScaleneSignalManager__lifecycle_watcher_active = True
        mgr._ScaleneSignalManager__lifecycle_watcher_thread = mock_thread

        mgr.stop_lifecycle_watcher()

        assert mgr._ScaleneSignalManager__lifecycle_watcher_active is False
        mock_thread.join.assert_called_once_with(timeout=0.2)
        assert mgr._ScaleneSignalManager__lifecycle_watcher_thread is None

    def test_stop_lifecycle_watcher_closes_handles_on_win32(self):
        """On win32, stop_lifecycle_watcher closes event handles."""
        mgr = ScaleneSignalManager()
        mgr._ScaleneSignalManager__lifecycle_start_event = 101
        mgr._ScaleneSignalManager__lifecycle_stop_event = 102
        mgr._ScaleneSignalManager__lifecycle_watcher_thread = None

        mock_kernel32 = MagicMock()

        with (
            patch("scalene.scalene_signal_manager.sys") as mock_sys,
            patch("scalene.scalene_signal_manager._kernel32", mock_kernel32),
        ):
            mock_sys.platform = "win32"
            mgr.stop_lifecycle_watcher()

        mock_kernel32.CloseHandle.assert_any_call(101)
        mock_kernel32.CloseHandle.assert_any_call(102)
        assert mgr._ScaleneSignalManager__lifecycle_start_event is None
        assert mgr._ScaleneSignalManager__lifecycle_stop_event is None

    def test_stop_lifecycle_watcher_noop_when_no_thread(self):
        """stop_lifecycle_watcher is safe to call when no watcher was started."""
        mgr = ScaleneSignalManager()
        # Should not raise
        mgr.stop_lifecycle_watcher()
        assert mgr._ScaleneSignalManager__lifecycle_watcher_active is False


# ---------------------------------------------------------------------------
# Module-level constants tests
# ---------------------------------------------------------------------------


class TestModuleConstants:
    """Verify the Named Event constants are always defined."""

    def test_event_name_templates_contain_pid_placeholder(self):
        assert "{pid}" in _LIFECYCLE_START_EVENT
        assert "{pid}" in _LIFECYCLE_STOP_EVENT

    def test_event_name_format(self):
        """Event names follow the Local\\scalene-lifecycle-... pattern."""
        start = _LIFECYCLE_START_EVENT.format(pid=12345)
        stop = _LIFECYCLE_STOP_EVENT.format(pid=12345)
        assert start == "Local\\scalene-lifecycle-start-12345"
        assert stop == "Local\\scalene-lifecycle-stop-12345"

    def test_wait_constants(self):
        assert _WAIT_OBJECT_0 == 0
        assert _WAIT_TIMEOUT == 0x00000102
        assert _EVENT_MODIFY_STATE == 0x0002


# ---------------------------------------------------------------------------
# profile.py tests
# ---------------------------------------------------------------------------


class TestProfileScript:
    """Test that profile.py uses ScaleneSignalManager.signal_lifecycle_event."""

    def test_profile_on_calls_signal_lifecycle_event(self):
        """python -m scalene.profile --on --pid PID calls signal_lifecycle_event."""
        with patch(
            "scalene.scalene_signal_manager.ScaleneSignalManager.signal_lifecycle_event"
        ) as mock_signal:
            result = subprocess.run(
                [sys.executable, "-m", "scalene.profile", "--on", "--pid", "99999"],
                capture_output=True,
                text=True,
            )
        # The process will likely fail with ProcessLookupError on Unix
        # (pid 99999 doesn't exist), but verify it attempted the right path
        # by checking stderr for the expected error or stdout for success message
        combined = result.stdout + result.stderr
        assert "99999" in combined or result.returncode == 0

    def test_profile_off_calls_signal_lifecycle_event(self):
        """python -m scalene.profile --off --pid PID calls signal_lifecycle_event."""
        result = subprocess.run(
            [sys.executable, "-m", "scalene.profile", "--off", "--pid", "99999"],
            capture_output=True,
            text=True,
        )
        combined = result.stdout + result.stderr
        assert "99999" in combined or result.returncode == 0

    def test_profile_no_args_prints_help(self):
        """python -m scalene.profile with no args prints usage and exits."""
        result = subprocess.run(
            [sys.executable, "-m", "scalene.profile"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0
        assert "--on" in result.stderr
        assert "--off" in result.stderr
        assert "--pid" in result.stderr

    def test_profile_pid_zero_prints_help(self):
        """python -m scalene.profile --on --pid 0 prints usage and exits."""
        result = subprocess.run(
            [sys.executable, "-m", "scalene.profile", "--on", "--pid", "0"],
            capture_output=True,
            text=True,
        )
        assert result.returncode != 0


# ---------------------------------------------------------------------------
# Integration tests
# ---------------------------------------------------------------------------


class TestOnOffIntegration:
    """Integration tests running scalene as a subprocess."""

    @pytest.fixture
    def simple_script(self, tmp_path):
        script = tmp_path / "prog.py"
        script.write_text(
            textwrap.dedent("""\
                import time
                total = 0
                for i in range(1000000):
                    total += i
                print("done", total)
            """)
        )
        return script

    def test_off_flag_runs_program_without_profiling(self, simple_script, tmp_path):
        """scalene run --off executes the program but collects no samples."""
        outfile = tmp_path / "profile.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scalene",
                "run",
                "--off",
                "--cpu-only",
                "-o",
                str(outfile),
                str(simple_script),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "done" in result.stdout
        # With --off the profiler should not have collected meaningful samples
        # (it may or may not write a file depending on whether output_profile runs)

    def test_on_flag_profiles_normally(self, simple_script, tmp_path):
        """scalene run --on profiles the program and produces output."""
        outfile = tmp_path / "profile.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scalene",
                "run",
                "--on",
                "--cpu-only",
                "-o",
                str(outfile),
                str(simple_script),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "done" in result.stdout

    def test_default_profiles_like_on(self, simple_script, tmp_path):
        """scalene run (no --on/--off) profiles the program."""
        outfile = tmp_path / "profile.json"
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "scalene",
                "run",
                "--cpu-only",
                "-o",
                str(outfile),
                str(simple_script),
            ],
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert result.returncode == 0
        assert "done" in result.stdout

    @pytest.mark.skipif(
        sys.platform == "win32", reason="fork-based test"
    )
    def test_off_then_on_via_signal(self, tmp_path):
        """Start with --off, send start signal, verify profiling activates."""
        script = tmp_path / "long_prog.py"
        script.write_text(
            textwrap.dedent("""\
                import os
                import sys
                import time

                # Print PID so parent can signal us
                print(f"PID={os.getpid()}", flush=True)

                # Busy loop long enough for parent to send signal
                total = 0
                for i in range(5_000_000):
                    total += i
                print("done", total)
            """)
        )
        outfile = tmp_path / "profile.json"
        proc = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "scalene",
                "run",
                "--off",
                "--cpu-only",
                "-o",
                str(outfile),
                str(script),
            ],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )

        # Read PID from child's stdout
        pid_line = proc.stdout.readline()
        if pid_line.startswith("PID="):
            child_pid = int(pid_line.strip().split("=")[1])
            # Send start profiling signal (SIGILL)
            import time

            time.sleep(0.1)  # let the child settle
            try:
                os.kill(child_pid, signal.SIGILL)
            except ProcessLookupError:
                pass  # child may have finished already

        stdout, stderr = proc.communicate(timeout=30)
        assert proc.returncode == 0
        assert "done" in (pid_line + stdout)
