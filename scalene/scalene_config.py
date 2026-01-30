"""Current version of Scalene; reported by --version."""

scalene_version = "2.1.2"
scalene_date = "2026.01.30"

# Port to use for Scalene UI
SCALENE_PORT = 11235

# Must equal src/include/sampleheap.hpp NEWLINE *minus 1*
NEWLINE_TRIGGER_LENGTH = 98820  # SampleHeap<...>::NEWLINE-1

# Maximum number of memory footprint samples to retain (via reservoir sampling).
# Used for both global and per-line memory sparklines.
MEMORY_FOOTPRINT_RESERVOIR_SIZE = 100
