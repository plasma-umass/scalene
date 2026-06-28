# Formal models of Scalene's concurrency & correctness

This directory contains machine-checked formal models of three properties of
Scalene's runtime:

1. **Signal / iteration safety** — the profile-output loop never faults from a
   concurrent signal-handler mutation of the shared stacks dictionaries.
2. **Deadlock freedom & signal-safety** — Scalene's lock/queue topology cannot
   deadlock, and no signal handler ever blocks on a lock.
3. **Attribution correctness** — CPU time and memory bytes are conserved
   (attributed exactly once, totals preserved) and the Python/C split fractions
   stay in `[0, 1]`.

Two complementary tools are used, each where it is strongest:

| Tool | Directory | Verifies | Method |
|------|-----------|----------|--------|
| **TLA+ / TLC** | [`tla/`](tla/) | interleaving safety, deadlock freedom, liveness | exhaustive model checking |
| **Lean 4** | [`lean/`](lean/) | conservation/bounds arithmetic, snapshot algebra | machine-checked proof |

> **Why both?** Race/deadlock properties are about *interleavings* — TLC
> exhaustively explores them and produces concrete counterexample traces.
> Conservation/bounds are about *arithmetic over all inputs* — Lean proves them
> for unbounded quantities, which a model checker cannot.

All TLA+ runs and Lean proofs reproduce from a clean checkout (commands below).
The Lean proofs contain **no `sorry`/`admit`** and depend only on Lean's three
standard axioms (`propext`, `Classical.choice`, `Quot.sound`).

---

## 1. Signal / iteration safety — `tla/SignalSafety.tla`

Models the CPU-sampling signal handler racing with the profile-output iterator
over `stats.combined_stacks`.

**Source mapping**

| Model element | Scalene source | Meaning |
|---|---|---|
| `HandlerFire(k)` | `scalene_cpu_profiler.py:177` (`add_combined_stack`), reached from `scalene_profiler.py:885` `cpu_signal_handler` | the signal handler appends a stack key, **synchronously in signal context** |
| `IterStepLive` (bug) | pre-fix `scalene_json.py` `for … in stats.combined_stacks.items()` | iterating the live dict |
| `IterStepSnapshot` (fix) | `scalene_json.py:884` `for stk, hits in list(stats.combined_stacks.items())` | iterating a snapshot |
| `outPC = "fault"` | CPython `RuntimeError: dictionary changed size during iteration` | the crash this models |

**Results**

- `SignalSafety_Bug.cfg` (`UseSnapshot = FALSE`): TLC reports
  **`Invariant NoIterationFault is violated`** with a 4-state counterexample —
  *OutputStart → HandlerFire(k1) → IterStepLive → fault* — exactly reproducing
  the bug fixed in PR #1067.
- `SignalSafety_Fix.cfg` (`UseSnapshot = TRUE`): **no error, 99 distinct
  states.** `NoIterationFault`, `SnapshotSound`, and `SnapshotComplete` all
  hold: the snapshot iterator never faults, only ever visits keys present at
  loop entry, and finishes having visited exactly those keys (concurrent
  appends are correctly deferred to the next output cycle).

## 2. Deadlock freedom & signal-safety — `tla/Deadlock.tla`

Models Scalene's lock/queue topology: `N = 3` background `ScaleneSigQueue`
threads (alloc / memcpy / async), each holding **only its own** `RLock`; the
main output thread acquiring **all** locks in a fixed global order; and a signal
handler that only does a lock-free `queue.put`.

**Source mapping**

| Model element | Scalene source | Meaning |
|---|---|---|
| `owner[i] = "worker"` | `scalene_sigqueue.py:14,48` `self.lock = RLock()` / `with self.lock:` | a sigqueue thread holds its own lock while processing one item |
| `OutputAcquire` (fixed order 1..N) | `scalene_profiler.py` output path acquiring all sigqueue locks | the main thread takes every lock, in list order, before flushing |
| `HandlerFire` (always enabled, lock-free) | `scalene_profiler.py:684,775,794` malloc/free/memcpy handlers → `sigq.put(...)` over `queue.SimpleQueue` (`scalene_sigqueue.py:11`) | a handler never acquires a lock |

**Results** — `Deadlock.cfg` (`N = 3`): **no error, 72 distinct states.**

- **No deadlock** (TLC `CHECK_DEADLOCK`): fixed-order acquisition + single-lock
  workers ⇒ no circular wait.
- `MutualExclusion`: a holding worker's lock is owned by that worker.
- `HandlerNeverBlocks`: the handler step's enabledness never depends on lock
  state — a handler interrupting a lock holder still makes progress. (Contrast:
  were a handler to take a lock, this would fail — the property that makes the
  lock-free `put` design signal-safe.)
- `OutputMakesProgress` (temporal, weak/strong fairness): once the output
  thread starts acquiring it eventually reaches its critical section — no
  starvation.

## 3. Attribution correctness — `lean/Scalene/Attribution.lean`

Proves the conservation and bounds invariants over `ℚ` (exact rationals — the
invariants are *intended* to be exact; floats merely approximate them).

**Source mapping**

| Lean theorem | Scalene source | Statement |
|---|---|---|
| `totalTime_eq_split`, `totalTime_nonneg` | `scalene_cpu_profiler.py:135-136` `c_time = max(elapsed − python_time, 0)`; `total = python + c` | the Python/C split is conserved and non-negative |
| `totalTime_eq_elapsed` | same | when `python_time ≤ elapsed`, total = measured elapsed exactly (no time invented/dropped) |
| `cpu_distribution_conserved` | `scalene_cpu_profiler.py:145` distribute `total_time / total_frames` per frame; `:411` `total_cpu_samples += total_time` | per-frame charges sum back to `total_time` (≥ 1 frame) |
| `pythonFraction_nonneg`, `pythonFraction_le_one` | `src/include/sampleheap.hpp:185-197` `_pythonCount`/`_cCount`; the `0/0`-guarded `python_fraction` | `python_fraction ∈ [0, 1]` |
| `pythonBytes_le_count`, `pythonBytes_nonneg` | `scalene_memory_profiler.py:336-337` `memory_python_samples`/`memory_malloc_samples`; python bytes = fraction · count | per line `memory_python_samples ≤ memory_malloc_samples` |
| `footprint_conserved` | `scalene_memory_profiler.py` malloc `+count` / free `−count`; `after = before + (Σmalloc − Σfree)` | footprint conservation over a batch |

## Signal / iteration safety (algebra) — `lean/Scalene/SignalSafety.lean`

The data-structure companion to the TLA+ interleaving model. Proves that the
`list(...)` snapshot is value-decoupled from later inserts: `snapshot_stable` /
`snapshot_length_fixed` (the iterator's bound is fixed at entry, so "changed
size during iteration" cannot arise), `snapshot_sound` / `fresh_key_deferred`
(only entry-time keys are visited; fresh keys deferred), `insert_preserves_old`
(no captured key is ever dropped). `snapshot_sound` depends on **no axioms**.

---

## What is *assumed* (model boundary)

These models abstract, and the abstractions are the assumptions:

- **Atomic steps.** Each TLA+ action (one handler append, one iteration step,
  one lock op) is atomic. Faithful for CPython: a Python-level signal handler
  runs between bytecodes, so it cannot tear a single dict mutation — but it
  *can* interleave between iteration steps, which is exactly what we model.
- **`ℚ`, not float.** The Lean proofs use exact rationals. They establish the
  *intended* conservation/bounds; floating-point rounding in the real code is a
  separate (numerical) concern not modeled here.
- **Bounded constants for TLC.** `Keys = {k1,k2,k3}`, `N = 3`, `MaxHandler = 2`.
  These bounds make checking exhaustive and finite; the Lean snapshot lemmas
  generalize the safety argument to unbounded inputs.
- **Out of scope (not yet modeled):** the C++ allocator's internal thread-local
  `_pythonCount`/`_cCount` accounting; the mapfile IPC byte protocol; fork()
  lock-state hazards beyond the stop/join discipline; GPU/accelerator paths.

---

## Reproducing

### Lean (proofs) — runs locally

```bash
cd formal/lean
lake exe cache get      # fetch prebuilt Mathlib oleans (first time only)
lake build              # builds Scalene.Attribution + Scalene.SignalSafety; 0 sorry
```

Verify the proofs rest only on standard axioms:

```bash
echo 'import Scalene
open Scalene
#print axioms cpu_distribution_conserved
#print axioms footprint_conserved
#print axioms pythonFraction_le_one' > /tmp/ax.lean
lake env lean /tmp/ax.lean
# => each depends only on [propext, Classical.choice, Quot.sound]
```

### TLA+ (model checking) — run with TLC

Requires Java + `tla2tools.jar`. (Checked on `cloudnew`, which has Java 21;
download tla2tools from the TLA+ releases page.)

```bash
cd formal/tla
J=path/to/tla2tools.jar
java -cp $J tlc2.TLC -config SignalSafety_Fix.cfg SignalSafety.tla   # no error, 99 states
java -cp $J tlc2.TLC -config SignalSafety_Bug.cfg SignalSafety.tla   # violates NoIterationFault (counterexample)
java -XX:+UseParallelGC -cp $J tlc2.TLC -config Deadlock.cfg Deadlock.tla  # no error, 72 states
```

---

## Layout

```
formal/
  README.md                     # this file
  tla/
    SignalSafety.tla            # handler-vs-iterator race
    SignalSafety_Fix.cfg        # snapshot fix: all invariants hold
    SignalSafety_Bug.cfg        # live iteration: NoIterationFault violated
    Deadlock.tla                # lock/queue topology
    Deadlock.cfg                # deadlock-free + signal-safe + liveness
  lean/
    lakefile.toml               # Mathlib dependency
    lean-toolchain              # leanprover/lean4:v4.31.0
    Scalene.lean                # top-level import
    Scalene/
      Attribution.lean          # CPU/memory conservation + fraction bounds
      SignalSafety.lean          # snapshot-iteration algebra
```
