"""Regression fixture: pure-arithmetic hot loops must not be credited
with C-side allocation traffic from CPython internals.

The workload alternates two phases per outer iteration:

  * ``do_allocs`` runs three list comprehensions of increasing size.
    Those lines (15, 16, 17) genuinely allocate via Python bytecode
    that has CALL (``range``) and ``BUILD_LIST`` / ``LIST_APPEND``
    on it. They are the legitimate attribution target for bytes.

  * ``hot_arith`` runs a tight ``while`` loop whose body is only
    ``LOAD_FAST`` / ``BINARY_OP`` / ``STORE_FAST`` — no CALL, no
    container-building opcode, no way to invoke a C-side allocator
    from user code. Yet during this loop CPython internals (arena
    resizes, GC, scalene's own bookkeeping under the GIL) emit raw
    ``malloc`` calls. Pre-fix, those bytes were credited to whichever
    arithmetic line the eval loop happened to be on — hundreds of MB
    of phantom traffic on ``z = z * z``.

Sized so Scalene reliably samples it: ``do_allocs`` retains a few
hundred MB of transient buffer activity per outer iteration, and the
outer loop runs long enough that the malloc sampler fires many times.
"""


def do_allocs():
    """Real allocator work — list comprehensions on lines 15-17 have
    CALL (``range``) and BUILD_LIST opcodes, so they are eligible
    targets for byte attribution."""
    a = [i * i for i in range(0, 100_000)][99_999]   # line 15
    b = [i * i for i in range(0, 200_000)][199_999]  # line 16
    c = [i for i in range(0, 300_000)][299_999]      # line 17
    return a + b + c


def hot_arith(x):
    """Pure float arithmetic — no CALL, no BUILD_*, no allocator
    opcode on lines 24-27. Any byte attribution that lands on these
    lines is smear from CPython internals running under the GIL."""
    z = 0.1
    i = 0
    while i < 100_000:
        z = z * z       # line 24
        z = x * x       # line 25
        z = z * z       # line 26
        z = z * z       # line 27
        i += 1          # line 28
    return z


def run():
    x = 1.01
    for _ in range(9):
        for _ in range(9):
            do_allocs()       # line 36 — legitimate alloc caller
            hot_arith(x)      # line 37 — smear target (caller of the
                              # pure-arith loop; redirected smear lands here)
    return x


if __name__ == "__main__":
    run()
