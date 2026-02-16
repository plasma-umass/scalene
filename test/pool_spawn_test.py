import multiprocessing


def worker(n):
    total = 0
    for i in range(n):
        total += i * i
    return total


if __name__ == "__main__":
    # Do enough computation in the main process to be reliably sampled.
    # Use list comprehensions (like testme.py) to ensure sufficient time.
    for _ in range(10):
        x = [i * i for i in range(200000)]
    ctx = multiprocessing.get_context("spawn")
    with ctx.Pool(2) as pool:
        results = pool.map(worker, [200000] * 4)
    print(sum(results))
