# Scalene Profiler Refactoring Plan

## Goal
Refactor `scalene/scalene_profiler.py` into multiple files with clear separation of concerns.

## Status: ✅ COMPLETE

All verification checks pass:
- `pytest tests/` - 147 tests passed
- `mypy scalene` - No issues found
- `ruff check scalene` - All checks passed

## File Sizes

| File | Lines |
|------|-------|
| `scalene_profiler.py` | 1,584 (was 1,885) |
| `scalene_cpu_profiler.py` | 228 (new) |
| `scalene_tracing.py` | 225 (new) |
| `scalene_lifecycle.py` | 198 (new) |

**Net reduction**: ~300 lines from main profiler, with reusable logic extracted

## New Modules Created

### 1. `scalene_cpu_profiler.py` ✅
- **Class**: `ScaleneCPUProfiler`
- **Purpose**: CPU profiling sample processing
- **Key methods**:
  - `process_cpu_sample` - Main CPU sample handler
  - `_update_main_thread_stats` - Main thread statistics
  - `_update_thread_stats` - Other thread statistics

### 2. `scalene_tracing.py` ✅
- **Class**: `ScaleneTracing`
- **Purpose**: Tracing decisions and file filtering with `lru_cache`
- **Key methods**:
  - `should_trace` - Main entry point (cached)
  - `_passes_exclusion_rules` - Library exclusions
  - `_should_trace_by_location` - Path-based filtering
  - `_is_system_library` - System library detection

### 3. `scalene_lifecycle.py` ✅
- **Class**: `ScaleneLifecycle`
- **Purpose**: Profiler lifecycle management (prepared for future use)

## Architecture

```
scalene_profiler.py (Scalene class)
    ├── ScaleneCPUProfiler (CPU sample processing)
    ├── ScaleneTracing (file/function filtering)
    ├── ScaleneMemoryProfiler (already existed)
    └── ScaleneSignalManager (already existed)
```

## Completed Tasks

- [x] Extracted CPU profiling logic (~150 lines)
- [x] Extracted tracing/filtering logic (~150 lines)
- [x] Created lifecycle module for future use
- [x] Updated type signatures to use `Filename` consistently
- [x] Applied proper `lru_cache` usage
- [x] All tests passing (147/147)
- [x] Type checking passing (mypy)
- [x] Linting passing (ruff)
