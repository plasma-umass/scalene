import sys


def main():
    try:
        from scalene import entrypoint
        entrypoint.Scalene.main()
    except Exception as exc:
        sys.stderr.write("ERROR: Calling scalene main function failed: %s\n" % exc)
        sys.exit(1)


if __name__ == "__main__":
    main()
