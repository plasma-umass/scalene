
def main():
    accum = bytes()
    for i in range(31):
        accum += bytes(10485767 // 4) # far below the allocation sampling window

    print(len(accum))

    asdf = bytes(2 * 10485767)

    
if __name__ == '__main__':
    main()