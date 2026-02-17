# Debugging Patterns for Scalene

## Signal Handler Debugging

The CPU signal handler (`cpu_signal_handler`) receives `this_frame` as the raw frame parameter. The `compute_frames_to_record()` function filters this down to user-only frames via `_should_trace()`.

**Critical gotcha**: When the main thread is idle in the event loop (the exact case async profiling needs to detect), there are NO user frames — asyncio/selector frames are all filtered out. So `frames` from `compute_frames_to_record()` is empty. Must use `this_frame` directly for event loop detection.

## Async Profiling Debugging

To verify async profiling is working:
1. Create a test program with known behavior (fast I/O, slow I/O, CPU-bound)
2. Profile: `python3 -m scalene run --async test/test_async_demo.py`
3. Check JSON: `python3 -m scalene view --cli` should show Await % column
4. Verify proportions: slow_io >> mixed_work >> fast_io, cpu_work = 0% await

To debug zero-await-data:
- Check `is_in_event_loop()` returns True when event loop is idle
- Check `_poll_suspended_tasks()` finds tasks
- Verify the signal handler is using `this_frame`, not filtered `frames`

## Profile Output Pipeline

There are **three separate renderers** for profile output. All must be updated when adding new columns:

- **JSON output**: `scalene_json.py:output_profiles()` → `output_profile_line()`
- **CLI viewer**: `scalene_parseargs.py:_display_profile_cli()` — used by `scalene view --cli`
- **HTML/GUI output**: `scalene_output.py:output_profiles()` — used by `scalene view --html`
- **GUI (browser)**: `scalene-gui.ts:makeProfileLine()` → embedded Vega-Lite charts via `vegaEmbed()`
- **Standalone HTML**: `scalene_utility.py:generate_html(standalone=True)` embeds all assets inline

Note: `_display_profile_cli()` in `scalene_parseargs.py` is completely separate from `scalene_output.py`. This is easy to miss.

## Unbounded Growth Prevention

Any dict or set that accumulates per-sample data must be bounded:

- **Dicts keyed by (filename, lineno)**: Inherently bounded by source code size — OK.
- **Sets of names/strings**: Must be capped (e.g., `async_task_names` capped at 100 per location).
- **Tracking dicts** (e.g., `_suspended_tasks`): Must be capped and cleared when exceeded.
- **`RunningStats`**: Fixed-size (count, mean, M2) — OK.
- **`ScaleneSigQueue`**: Uses `SimpleQueue` with continuous consumer drain — OK.
