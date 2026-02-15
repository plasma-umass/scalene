"""Current version of Scalene; reported by --version."""

scalene_version = "2.1.4"
scalene_date = "2026.02.15"

# Port to use for Scalene UI
SCALENE_PORT = 11235

# Must equal src/include/sampleheap.hpp NEWLINE *minus 1*
NEWLINE_TRIGGER_LENGTH = 98820  # SampleHeap<...>::NEWLINE-1

# Maximum number of memory footprint samples to retain (via reservoir sampling).
# Used for both global and per-line memory sparklines.
MEMORY_FOOTPRINT_RESERVOIR_SIZE = 100

# Maximum number of CPU wallclock timestamp samples to retain per line
# (via reservoir sampling). Bounds memory when CPU profiling runs for
# a long time. See https://github.com/plasma-umass/scalene/issues/991
CPU_SAMPLES_RESERVOIR_SIZE = 500
