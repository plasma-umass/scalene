import multiprocessing


def worker(n):
    total = 0
    for i in range(n):
        total += i * i
    return total


if __name__ == "__main__":
    # Do enough computation in the main process to be reliably sampled
    total = 0
    for i in range(5000000):
        total += i * i
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(2) as pool:
        results = pool.map(worker, [200000] * 4)
    print(total + sum(results))
