import time
import argparse

def do_work_fn(x, i):
    return (x >> 2) | (i & x)

def inline_loop(x, its):
    for i in range(its): # 9500000
        x = x | (x >> 2) | (i & x)
    return x

def fn_call_loop(x, its):
    for i in range(its): # 500000):
        x = x | do_work_fn(x, i)
    return x

def main():
    parser = argparse.ArgumentParser(description='Test time breakdown.')
    parser.add_argument('--inline', dest='inline', type=int, default=9500000, help="inline iterations")
    parser.add_argument('--fn_call', dest='fn_call', type=int, default=500000, help="function call iterations")
    args = parser.parse_args()

    x = 0
    start_fn_call = time.perf_counter()
    x = fn_call_loop(x, args.fn_call)
    elapsed_fn_call = time.perf_counter() - start_fn_call
    print(f"elapsed fn call = {elapsed_fn_call}")
    start_inline_loop = time.perf_counter()
    x = inline_loop(x, args.inline)
    elapsed_inline_loop = time.perf_counter() - start_inline_loop
    print(f"elapsed inline loop = {elapsed_inline_loop}")
    print(f"ratio fn_call/total = {100*(elapsed_fn_call/(elapsed_fn_call+elapsed_inline_loop)):.2f}%")
    print(f"ratio inline/total = {100*(elapsed_inline_loop/(elapsed_fn_call+elapsed_inline_loop)):.2f}%")

if __name__ == '__main__':
    main()
#    prof = pprofile.StatisticalProfile()


    #with prof():
    #    main()

    # prof.print_stats()
    # prof.callgrind(sys.stdout)
