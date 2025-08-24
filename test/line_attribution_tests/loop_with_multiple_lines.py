def main():
    accum = bytes()
    for i in range(31):
        accum += bytes(2 * 10485767)  # 2x the allocation sampling window
        bogus = None

    asdf = bytes(2 * 10485767)


if __name__ == "__main__":
    main()
