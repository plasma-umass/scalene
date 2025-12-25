import sys
import traceback


def main() -> None:
    try:
        from scalene import scalene_profiler

        scalene_profiler.Scalene.main()
    except SystemExit:
        raise
    except Exception as exc:
        sys.stderr.write(f"ERROR: Calling Scalene main function failed: {exc}\n")
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
