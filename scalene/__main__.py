import sys
import traceback

from scalene import scalene_profiler


def should_trace(s: str) -> bool:
    if scalene_profiler.Scalene.is_done():
        return False
    return scalene_profiler.Scalene.should_trace(s)


def main() -> None:
    try:
        from scalene import scalene_profiler

        scalene_profiler.Scalene.main()
    except Exception as exc:
        sys.stderr.write(f"ERROR: Calling Scalene main function failed: {exc}\n")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
