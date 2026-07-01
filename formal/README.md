# Formal models of Scalene's concurrency & correctness

This directory contains machine-checked formal models of Scalene's runtime,
plus a **proof→production pipeline** that extracts the proven algorithms to
Python and differentially tests the real profiler against them.

## Proof roundup — where the correctness effort stands, by subsystem

**Lean 4:** 16 modules, 133 theorems, no `sorry`, standard axioms only.
**TLA+/TLC:** 2 specs, exhaustively model-checked. Verdicts: **✅ Proven**,
**⚠️ Partial**, **❌ Unproven**. This is the narrative view; [`STATUS.md`](STATUS.md)
has the granular per-aspect table, and the numbered sections below (§1–§14) give
the full statements with source mappings.

**1. CPU profiling — the headline.** The reported per-line profile is an
**unbiased, consistent** estimator of the truth: ✅ `estimator_unbiased` (right
on average at any sample budget N), ✅ `jointVariance_eq` (variance = p(1−p)/N →
0). The i.i.d. hypothesis this rests on is discharged, not assumed: ✅ the
sampler is Poisson (`ExponentialSampler`, inverse-CDF + memorylessness) and ✅
**PASTA** now links Poisson instants to time-fraction landing
(`PoissonArrivals.uniform_realizes_trueFraction`, §12). ✅ the Python/native
classifier *conserves* each sample's CPU budget in every branch
(`PythonNativeClassifier.charge_total`, §15). ⚠️ that the C++ stamping
*establishes* faithful placement is engineering, not Lean-proven; ⚠️ *which*
classifier branch is right is the CALL-opcode heuristic (conditional
correctness proven, `branchA_exact_if_in_call`; the detection itself not
formalized).

**2. Memory sampling.** ✅ the default ThresholdSampler conserves true net
allocation exactly with bounded residual (`threshold_conserves`,
`threshold_residual_bounded`), ✅ proven bisimilar to the literal two-counter C++
(`step_bisim`), ✅ the Poisson sampler is unbiased, ✅ per-line byte fractions
are faithful (`PerLineAttribution`). ✅ the per-line reader bookkeeping conserves
(Σ per-line bytes = grand total), keeps the python-share ≤ total bytes, and
reports a monotone high-water peak (`PerLineMallocAttribution`, §16).

**3. Memory-leak detection — fully closed, incl. concurrency.** ✅ the leak score
is a Rule-of-Succession probability in [0,1] with monotonicity and an exact
decision rule (`MetricCorrectness`); ✅ its unguarded denominator is safe
(`LeakTrackerAudit`, `frees ≤ allocs`); ✅ that safety survives the sig-queue /
main-thread interleaving and `fork`, and the serialization is shown *necessary*
(`LeakTrackerConcurrency`). The audit that built this found production bugs
(below).

**4. Metrics end-to-end across the C++/Python boundary.** ✅ **copy volume**
(`CopyVolumeWiring`, §13) and ✅ **malloc footprint / peak memory**
(`MallocFootprintWiring`, §14) — the reported number equals what the native
interposer observed, up to a bounded sampler residual. The footprint model
handles the free-side `max(0,·)` clamp *honestly*: exact in the non-negative
regime, and outside it the clamp can only over-report (`clamp_only_raises`),
never silently undercount. ✅ GPU/copy/python-split arithmetic bounds; ❌
GPU/accelerator device-acquisition paths.

**5. Concurrency & signal safety (TLA+).** ✅ the `combined_stacks` race is
reachable in the bug config (concrete 4-state counterexample) and impossible in
the fix (`SignalSafety.tla`); ✅ no deadlock, the handler never blocks on a lock,
output makes progress under fairness (`Deadlock.tla`). ✅ the snapshot algebra
that underlies the fix (`SignalSafety.lean`). ⚠️ TLC is exhaustive only within
bounds (`N=3`, `MaxHandler=2`).

**6. Bounded data structures.** ✅ the Space-Saving `combined_stacks` table never
exceeds capacity and evicts a minimum (`SpaceSaving`), and ✅ this is wired to
production: the proven Lean defs are extracted to Python via
[LeanToPython](https://github.com/emeryberger/LeanToPython) and differentially
tested against the real `_space_saving_increment`
(`tests/test_verified_space_saving.py`).

**Not modeled:** output rendering (the three renderers — guarded by tests, where
the four divide-by-zero bugs below were found), CLI/arg parsing, the
`replacement_*` modules, floating-point rounding (proofs use exact ℚ), and the
Jupyter/AI-provider GUI.

---

Two complementary tools are used, each where it is strongest:

| Tool | Directory | Verifies | Method |
|------|-----------|----------|--------|
| **TLA+ / TLC** | [`tla/`](tla/) | interleaving safety, deadlock freedom, liveness | exhaustive model checking |
| **Lean 4** | [`lean/`](lean/) | conservation/bounds arithmetic, snapshot algebra | machine-checked proof |

> **Why both?** Race/deadlock properties are about *interleavings* — TLC
> exhaustively explores them and produces concrete counterexample traces, and it
> checks *liveness* under fairness (progress, no starvation), which Lean has no
> comfortable story for. Conservation/bounds are about *arithmetic over all
> inputs* — Lean proves them for unbounded quantities, which a model checker
> cannot. The engines are complementary, not redundant: retiring the TLC specs
> would drop counterexample-search and liveness coverage with nothing to replace
> them. One overlap is deliberate — `LeakTrackerConcurrency.lean` proves an
> interleaving property in Lean but *assumes step-atomicity as an axiom*
> (justified by the RLock + thread join); deriving that atomicity from the
> sig-queue's operational semantics is a natural next TLA+ job. See
> [`STATUS.md`](STATUS.md) § "Why two engines".

All TLA+ runs and Lean proofs reproduce from a clean checkout (commands below).
The Lean proofs contain **no `sorry`/`admit`** and depend only on Lean's three
standard axioms (`propext`, `Classical.choice`, `Quot.sound`).

## Bugs the formalization found

Formalizing forces every implicit assumption to be named, which surfaces places
where the code doesn't enforce what a proof needs. Auditing the models'
hypotheses against the code (see `lean/Scalene/LeakTrackerAudit.lean` and the
audit notes below) turned up four real defects, all since fixed:

1. **Unguarded divide-by-zero in leak-velocity reporting**
   (`scalene_json.py`, the `velocity_mb_s: leak_velocity / stats.elapsed_time`
   site). `compute_leaks` gates on allocation *growth rate*, not wall-clock
   time, so a leak can be reported on a run short enough that `elapsed_time` is
   still `0.0` → `ZeroDivisionError`. Sibling `elapsed_time` divisions were
   already guarded; this one was missed. Fixed + regression test
   (`tests/test_leak_velocity_zero_elapsed.py`).
2. **Zero/negative memory-sampling window from an unvalidated env var**
   (`sampleheap.hpp`: `atol(getenv("SCALENE_ALLOCATION_SAMPLING_WINDOW"))`).
   `atol` returns 0 for `"0"` or any unparseable string; a 0 interval makes the
   sampler trigger on *every* allocation — and violates the `interval > 0`
   precondition `MemorySampler.lean` proves necessary. Fixed by clamping to the
   default when ≤ 0.
3. **Unguarded divide-by-zero in per-stack CPU normalization**
   (`scalene_json.py`, the `stats.stacks` normalization loop dividing by
   `stats.cpu_stats.total_cpu_samples`). Same class as #1, found by re-running
   the "every denominator is a claim to verify" audit across the output path:
   `total_cpu_samples` can be `0.0` while `stats.stacks` is non-empty — a
   **memory-only run with `--stacks`** records stack entries but never a CPU
   sample, and it is *memory* activity (not CPU) that passes the
   "nothing to output" gate. The sibling per-file/per-line CPU normalizations
   (`~556`, `~1259`, `~1337`) were already guarded; this one was missed → crash.
   Fixed + regression test (`tests/test_stacks_zero_cpu_samples.py`).
4. **The CLI-renderer twin of #1.** Scalene has *three separate output
   renderers* (see `Scalene-Debugging.md`). The #1 fix touched only the JSON
   renderer; `scalene_output.py` (the `scalene view --cli` path) carried the
   identical unguarded `leak[2] / stats.elapsed_time` in its leak report — same
   reachability (`compute_leaks` gates on growth rate, not time). Found by
   re-running the audit across the CLI path. Fixed + regression test
   (`tests/test_cli_leak_velocity_zero_elapsed.py`). A reminder that a fix in
   one renderer does not cover its siblings.

Additionally, `LeakTrackerAudit.lean` discharges an *implicit* safety contract:
the leak formula `1 − (frees+1)/(allocs−frees+2)` has **no** guard on its
denominator, relying entirely on the invariant `frees ≤ allocs`. That invariant
is not obvious — `allocs`/`frees` are incremented at separate code sites — so we
model the raw two-counter increment discipline and *prove* `frees ≤ allocs`
holds, hence `allocs−frees+2 ≥ 2 > 0`. (No bug, but the safety was previously
implicit and unverified.)

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

## 4. Bounded heavy-hitter accounting — `lean/Scalene/SpaceSaving.lean`

Models `scalene_utility.py:_space_saving_increment` (the bounded
`combined_stacks` table) as a pure `step : Table → Key → Table` over an
association list, matching the three Python branches (present→bump, room→insert,
full→evict-min). Proves:

- **`step_withinCap` / `fold_withinCap`** — the table never exceeds capacity,
  for any sequence of inserts (the bound the whole design exists to guarantee,
  `_COMBINED_STACKS_MAX_KEYS`).
- **`minCount_le`** — eviction always targets a minimum-count entry (Metwally's
  rule), so heavy hitters survive.
- **`present_keeps_size` / `insert_grows_by_one` / `evict_keeps_size`** — the
  per-branch size behavior.

## 5. Proof → production: extracting verified Python

The computational cores proven above are extracted to Python with
[LeanToPython](https://github.com/emeryberger/LeanToPython) and wired back into
Scalene as a **verified oracle**:

```
formal/lean/Scalene/{Attribution,SpaceSaving}.lean   ← proofs (Lean 4.31 + Mathlib)
        │  (same algorithms, extraction-friendly fragment)
formal/extract/ScaleneExtract.lean                   ← Nat/List defs, no Mathlib
        │  lake env lean ScaleneExtract.lean  (LeanToPython, Lean 4.12)
formal/extract/scalene_verified_core.py              ← generated Python (committed)
        │  imported as a reference oracle
tests/test_verified_space_saving.py                  ← differential test vs the
                                                        real _space_saving_increment
```

- **`formal/lean/Scalene/ExtractMirror.lean`** is the machine-checked integrity
  bridge: it re-states the extraction defs and proves them equal to / satisfying
  the proven ones (`minCountX_eq`, `totalTimeNs_eq_elapsed`,
  `pythonFractionPpm_le`). If `ScaleneExtract.lean` drifts from the proven
  model, this file fails to compile — so the extracted Python can't silently
  diverge from what was proven.
- **`tests/test_verified_space_saving.py`** runs Scalene's production
  `_space_saving_increment` and the extracted oracle on the same random key
  streams and asserts the proven capacity bound holds on the real code, and the
  count multiset matches the oracle (victim *identity* may differ — production
  breaks min-count ties by dict order, the oracle by list order; tie-break is
  not part of the proven spec).

**LeanToPython fixes upstreamed for this.** Extracting Scalene's defs surfaced
two transpiler bugs, both **fixed upstream** in
[emeryberger/LeanToPython#1](https://github.com/emeryberger/LeanToPython/pull/1):
1. **Bool-typed-parameter branch inversion** — `if isMalloc then a else b`
   lowered to a `Decidable` cases whose discriminant name the heuristic didn't
   recognize, swapping the branches. Fixed by tracking each fvar's LCNF `Bool`
   type and resolving through the alias map, instead of guessing from the name.
   (Also fixed the previously-broken `mod_pow` corpus case.)
2. **Binary `min`/`max` operand drop** — `Nat.min a b` extracted to `min(b)`,
   dropping the first operand. Fixed in `stdlibFnToPython?`'s wrapper emitter.
   `ScaleneExtract.minCount` now uses `Nat.min` directly, extracting cleanly to
   `min(a, b)`; `ExtractMirror.minCountX_eq` confirms it equals the proven
   `minCount`.

---

## 6. Profiler correctness — `lean/Scalene/ProfilerCorrectness.lean`

Sections 3–5 prove the *bookkeeping* is sound (totals conserved, fractions in
range, table bounded). This section proves the property a **user** cares about:
*the numbers Scalene reports reflect where the program actually spends its time
and memory.*

A sampling profiler cannot be exactly right on any single run — it observes a
random subset of execution — so "correct attribution" is necessarily a
*statistical* statement. We prove both halves:

| Lean theorem | Statement |
|---|---|
| `expect_indicator` | **Single-sample unbiasedness**: one faithfully-placed sample attributes time to line ℓ with probability exactly `trueFraction ℓ`. |
| `estimator_unbiased` | **N-sample unbiasedness** (headline): for *every* sample budget `N ≥ 1`, the expected reported fraction for line ℓ equals its true fraction. The profiler is right on average at any N. |
| `variance_indicator` | Single-sample variance is the Bernoulli `p(1−p)`. |
| `variance_indicator_le` | …bounded by ¼ — a uniform per-sample noise bound. |
| `jointExpect_pair` | **Independence factorization**: distinct samples are independent (`E[XᵢXⱼ] = E[Xᵢ]E[Xⱼ]`, i≠j). |
| `jointVariance_eq` | **Consistency** (headline): the N-sample estimator's variance is exactly `p(1−p)/N` → 0. So the reported numbers *converge* to the truth as samples accumulate. |

Together: the reported per-line profile is an **unbiased, consistent estimator**
of the ground-truth time/memory distribution. All over ℚ (exact); no `sorry`;
standard axioms only.

### The desideratum → mechanism bridge

Everything rests on one hypothesis, made explicit in the `Truth` structure's
sampling distribution: **each timer tick is attributed to the line truly
executing when it fires, with probability proportional to that line's true
running time** (`trueFraction`). On a signal-based Python profiler this is *not*
automatic — an asynchronous signal can be delivered a few bytecodes after the
event that triggered it, smearing a sample onto the wrong line.

This is exactly the gap Scalene's engineering closes, and it ties this
spec-level proof back to the mechanism-level work:

- **synchronous (C++) stamping** of the executing `(file, line)` at sample time
  (`whereInPython` / `whereInPythonWithStack`, `src/source/pywhere.cpp`) — so
  the sample is attributed to the line actually running, not wherever the
  Python-level handler happens to resume;
- the **smear correction** in `scalene_memory_profiler.py` that reattributes
  arena/GC bytes off pure-arithmetic leaf lines;
- and the conservation/bounds of §3 (`Attribution.lean`), which guarantee the
  per-sample attribution that unbiasedness sums over is itself well-formed
  (fractions in [0,1], totals preserved).

So the chain is: *faithful per-sample attribution* (engineering + §3) **⇒**
*unbiased, consistent reported profile* (§6). The `faithful` hypothesis is the
formal contract between them.

### What this does *not* yet prove

- **That the hypothesis holds.** We prove "faithful sampling ⇒ correct profile";
  we do not formally prove Scalene's C++ stamping *establishes* faithful
  sampling (that would require modeling signal delivery + the CPython
  interpreter loop). The hypothesis is discharged by engineering + the §3
  invariants, not by a Lean proof.
- **i.i.d. sampling — discharged by the code, see §7.** The model assumes
  independent, identically-distributed samples (`jointExpect` = product
  distribution). This is *not* an idealization gap: Scalene draws each
  inter-sample interval from an Exponential distribution
  (`_generate_exponential_sample`, `scalene_profiler.py:1108`), making the
  sample instants a Poisson process — memoryless (hence independent) and, by
  PASTA, landing on each line proportionally to its true time (the
  `trueFraction` distribution). §7 (`ExponentialSampler.lean`) proves the
  sampler transform is a correct inverse-CDF for the Exponential and is
  memoryless. (PASTA itself is cited, not formalized — it needs a continuous-
  time stochastic-process development.)
- **GPU / copy-volume / python-split / leak / memory-sampling — §8–§10.**
  §8 (`MetricCorrectness.lean`) covers GPU utilization, memcpy copy-volume,
  the Python-vs-native split, and memory-leak detection; §9
  (`MemorySampler.lean`) covers the allocation sampler (now including a proved
  bisimulation to the literal two-counter C++); §10 (`PerLineAttribution.lean`)
  ties byte sampling to the per-line fraction. What remains unmodeled: the
  per-sample *accuracy* of the python/native classifier heuristic, and the
  end-to-end wiring from the C++ counters into the Python statistics objects.

---

## 7. The sampler is Poisson — `lean/Scalene/ExponentialSampler.lean`

§6's unbiasedness/consistency rests on i.i.d. samples drawn proportionally to
true time. That is exactly what Scalene's sampler delivers, and §7 proves the
sampler transform correct rather than assuming it.

`scalene_profiler.py:1108` draws each inter-sample interval as
`-scale · log(1 − u)`, `u ~ Uniform[0,1)` — the inverse-CDF transform for the
Exponential distribution.

| Lean theorem | Statement |
|---|---|
| `sample_le_iff` | **Inverse-CDF correctness**: `sample ≤ t ↔ u ≤ 1 − exp(−t/scale)`. Since `u` is uniform, `P(sample ≤ t) = 1 − exp(−t/scale)` — the sampler output is Exponential(mean `scale`). |
| `sample_nonneg` | a sampled delay is never negative. |
| `survival_memoryless` | `S(s+t) = S(s)·S(t)` — the Exponential is memoryless, so the next sample instant is independent of the past. |
| `expCDF_zero`, `expCDF_lt_one` | basic CDF sanity. |

**Why this matters.** Exponential gaps ⇒ the sample times are a *Poisson
process*. Memorylessness gives the **independence** §6 assumes; and by PASTA
("Poisson Arrivals See Time Averages") a Poisson sample lands on a line with
probability equal to its true time fraction — the `trueFraction` distribution.
Fixed-rate sampling would not give this (it can alias with periodic program
behaviour); the exponential draw is precisely the design choice that makes the
§6 hypotheses hold. (PASTA is cited, not formalized.)

## 8. Four more metrics — `lean/Scalene/MetricCorrectness.lean`

Two proof shapes, because the metrics are not all averages:

**Weighted-average attributions** (same frame as §6):
- **GPU utilization** (`scalene_cpu_profiler.py:439`, `scalene_json.py:567`):
  `gpuFraction_bounds` — the reported `gpu_samples/n_gpu_samples` is a ratio of
  nonneg time-integrals with `util·w ≤ w`, hence a fraction in `[0,1]`; with
  Poisson sampling it converges to true time-averaged utilization.
- **memcpy copy-volume** (`memcpysampler.hpp:319`): bytes sampled on an
  exponential byte-clock, so per-line counts are unbiased for true copy volume
  — the §6 argument with byte-weight instead of time-weight.
- **Python-vs-native split** (`scalene_cpu_profiler.py:251-343`):
  `python_c_fraction_sums_one` — the reported python and C fractions partition
  each sample and sum to 1. (This metric is a *deterministic classifier*, not a
  random estimator; we prove the conservation property, not per-sample
  classifier accuracy.)

**Memory-leak detection — a Bayesian hypothesis test** (the different one,
`scalene_leak_analysis.py:31`). The reported score is the Laplace Rule of
Succession `leakScore = 1 − (frees+1)/(unfreed+2)`:

| Lean theorem | Statement |
|---|---|
| `leakScore_eq` | matches the Rule of Succession `(unfreed−frees+1)/(unfreed+2)`. |
| `leakScore_nonneg`, `leakScore_le_one` | the score is a probability in `[0,1]`. |
| `leakScore_mono_unfreed` | more never-freed allocations ⇒ strictly higher score. |
| `leakScore_anti_frees` | more reclamations ⇒ lower score. |
| `reportsLeak_iff` | **exact decision rule**: reports a leak iff the reclamation mass `(frees+1)/(unfreed+2) ≤ threshold`. |
| `no_leak_without_evidence`, `no_leak_when_all_freed` | **false-positive guards**: with no evidence the score is the prior ½ (below any threshold `< ½`); a line that frees everything it allocates is never flagged. |

## 9. The memory sampler — `lean/Scalene/MemorySampler.lean`

Scalene ships two allocation samplers (`sampleheap.hpp:345-349`); we model both:

- **ThresholdSampler** (the default): deterministic; fires when net
  alloc/free bytes cross `_sampleInterval`, reporting the exact excess and
  resetting. `threshold_conserves` — reported net + sub-threshold residual =
  *true* net allocation, exactly (no bytes invented/lost; sampling only coarsens
  to interval multiples). `threshold_residual_bounded` — the residual is always
  `< interval`, so the reported footprint is within one interval of the truth.
- **PoissonSampler** (experimental, `#if 0`): each byte sampled w.p.
  `1/window`, rescaled by `window`. `poisson_unbiased` /
  `poisson_unbiased_sum` — the rescaled estimate is unbiased for true bytes,
  per allocation and summed over a trace.

**Faithful to the *literal* two-counter C++ (`§1b` in the file).** The model
above collapses the C++'s two `uint64_t` counters (`_increments`,
`_decrements`) into their difference `bal`; that reduction was previously only
argued in prose. `step_bisim` / `run_bisim` now *prove* the literal two-counter
machine (separate ℕ counters, trigger `incr ≥ decr + I`, reset both to 0) is
bisimilar to the one-counter model under `abs (incr, decr) = incr − decr`, and
`threshold2_conserves` transfers exact conservation to the two-counter machine
as written. So "faithful to the C++" is a theorem, not an assumption.

## 10. Per-line attribution under sampling — `lean/Scalene/PerLineAttribution.lean`

§9 proves the sampler unbiased for *total* bytes per line; this ties that back
to §6's per-line *fraction* story, so memory sampling inherits the attribution
guarantee. A profiler reports `recorded[ℓ] / Σ recorded` — a ratio of two
unbiased estimators, which is not *exactly* unbiased (`E[X/Y] ≠ E[X]/E[Y]`). We
prove what actually holds and is what a user relies on:

- `fraction_of_expectations` — the fraction formed from the *expected* recorded
  counts equals the true per-line byte fraction: the sampling window cancels top
  and bottom, so there is **no systematic scale bias** in the breakdown.
- `recorded_fraction_exact` — whenever per-line counts are proportional to true
  bytes (the deterministic threshold limit / large-sample Poisson limit), the
  reported fraction equals the true fraction *exactly*, independent of the
  sampling rate.
- `trueFraction_nonneg` / `trueFraction_sum_one` — the per-line memory breakdown
  is a probability distribution over lines, exactly like the CPU one (§6).

---

## 11. Leak tracker under concurrency & fork — `lean/Scalene/LeakTrackerConcurrency.lean`

`LeakTrackerAudit.lean` (§ "Bugs the formalization found") proves `frees ≤ allocs`
for a single *sequential* event stream. But in the code the two increment sites
run on a background sig-queue thread while the shutdown drain runs on the main
thread, and the whole tracker state is duplicated across `fork`. This section
discharges that gap — and, per the audit method, proves the disciplines the code
relies on are *necessary*, not merely present.

**What the code actually does** (verified against the sources):

| Model element | Scalene source | Meaning |
|---|---|---|
| both increments are one `step` | `scalene_memory_profiler.py:236` (free-credit) and `:401` (alloc-credit) are two spots in the *same* function `process_malloc_free_samples` | there is no state at which one applied without the other |
| each invocation is atomic | `scalene_sigqueue.py:48` `with self.lock:` around `self.process(*item)` (an `RLock`) | invocations never interleave with each other |
| the drain never overlaps the thread | `scalene_profiler.py:1591` drain runs after `stop()` → `_disable_signals()` → `stop_signal_queues()` joins the thread (`scalene_sigqueue.py:37`) | the shutdown step is one more atomic step in the sequence |
| fork quiesces then resets both fields | `before_fork` (`:541`) joins the queue; `after_fork_in_child` (`:522`) → `stats.clear()` resets `leak_score` **and** `last_malloc_triggered` together (`scalene_statistics.py:456-457`) | the child restarts from the initial state |

**What is proven:**

- `interleave_preserves_inv` / `sigqueue_then_drain_safe` — **interleaving
  safety.** With each invocation atomic (the RLock), *every* shuffle of the
  sig-queue thread's steps with the main-thread drain preserves `frees ≤ allocs`.
  The scheduler order is irrelevant — which is exactly what the lock buys.
- `torn_free_breaks_inv` — **atomicity is necessary.** Model the lost-disarm race
  that dropping the lock would permit (a free credited *without* its disarm): two
  torn frees double-credit one armed trigger, giving `frees = allocs + 1`. So the
  invariant genuinely depends on the RLock; it is load-bearing.
- `fork_reset_inv` — the child process starts safe: whatever the parent's state,
  the reset lands in the initial tracker.
- `partial_fork_reset_breaks_inv` — **both fields must reset together.** A reset
  that zeroed the counters but left the trigger armed (clearing `leak_score`
  without `last_malloc_triggered`) breaks the invariant immediately — the armed
  line owes a free it has no room for. This is why `scalene_statistics.py:457`
  resets `last_malloc_triggered` alongside `leak_score`.

Together with `LeakTrackerAudit.run_frees_le_allocs`, this closes the loop: the
divide-by-zero-safety of `scalene_leak_analysis.py`'s leak formula holds for the
real concurrent + forking execution, *provided* the RLock atomicity and joint
fork reset are in place — both of which are shown here to be required.

---

## 12. PASTA: the sampler→correctness link — `lean/Scalene/PoissonArrivals.lean`

§6 (`ProfilerCorrectness`) *assumes* each timer tick lands on line ℓ with
probability `trueFraction ℓ`. §7 (`ExponentialSampler`) proves the sampler's
inter-arrival gaps are Exponential, so the sample instants form a Poisson
process — but the step "Poisson instants ⇒ landing probability = time fraction"
was cited as PASTA, not proven. This module proves it, in the discrete-time form
the effort targeted.

Model the horizon as `M` equal time slots, `slots i` = the line running during
slot `i`. A Poisson arrival, conditioned on its count, occurs at a uniformly
random time (the order-statistics property) — here, a uniform slot.

- `uniform_landing_eq_timeFraction` — **PASTA identity**: the expected indicator
  that a uniform arrival lands on ℓ equals ℓ's fraction of time (`timeCount ℓ / M`).
- `sum_timeFraction` — the time fractions form a probability distribution.
- `uniform_realizes_trueFraction` — **the discharge**: build the
  `ProfilerCorrectness.Truth` induced by the timeline; its `trueFraction` (the
  assumed sampling law) equals both the time fraction and
  `Truth.expect (indicator ℓ)`. So the hypothesis feeding `estimator_unbiased` /
  `jointVariance_eq` is produced by the sampler mechanism, not postulated.

Boundary: this is the discrete-time analogue (uniform-over-slots). The
continuous-time order-statistics theorem for the Poisson process is not
formalized; the discrete form is the operative content for a tick-sampled
profiler.

## 13. Copy volume end-to-end (C++↔Python) — `lean/Scalene/CopyVolumeWiring.lean`

Every other Lean module stops on one side of the native/Python line. This one
spans it, modeling both the C++ `MemcpySampler` accumulator/flush state machine
(`src/include/memcpysampler.hpp:319-361`) and the Python reader
(`process_memcpy_samples`, `scalene_memory_profiler.py:56-99`).

**Source mapping**

| Model element | Scalene source | Meaning |
|---|---|---|
| `cppStep .copy n ℓ` | `incrementMemoryOps`: `_memcpyOps += n` | accumulate bytes, no trigger |
| `cppStep .copyFlush n ℓ` | `sample(n)` triggers → `writeCount()` emits `_memcpyOps`, then `_memcpyOps = 0` | flush accumulator to a record on line ℓ, reset |
| `Record.pid` | `getpid()` in `writeCount` (`snprintf` `%d`) | records tagged with the emitting pid |
| `pythonTotal` filter | `if int(curr_pid) != int(pid): continue` (`:82`) | Python drops foreign-pid records |
| `+= count` | `memcpy_samples[file][line] += count` (`:98`) | Python accumulates per line |

**Theorems**

- `flushed_add_residual` — C++ conservation: bytes written to records + the
  unflushed accumulator = total bytes observed. Nothing invented or lost.
- `python_total_eq_flushed` — the mapfile transfer + pid filter neither drop nor
  double-count in-process bytes (records carry the running pid, proven via
  `cppRun_records_pid`).
- `roundtrip_conservation` — **headline**: the copy volume Python reports equals
  the bytes C++ observed minus the in-flight residual. `scalene view`'s
  copy-volume column faithfully reflects observed memcpy traffic.
- `foreign_pid_dropped` — a child process's records don't pollute this process's
  total.
- `residual_zero_after_flush` — a flush resets the accumulator, so the residual
  is bounded by one sampling interval; the round-trip discrepancy is at most the
  sampling granularity, not arbitrary.

Boundary: models the emitter/reader state machines and the byte accounting, not
the mapfile's low-level byte-format parsing or partial-read handling.

---

## 14. Malloc footprint end-to-end (C++↔Python) — `lean/Scalene/MallocFootprintWiring.lean`

The harder memory path: the *current footprint* / peak-memory number, spanning
the C++ `SampleHeap` emitter (`sampleheap.hpp:183-316`) and the Python reader
`process_malloc_free_samples` (`scalene_memory_profiler.py:102-228`). The C++
half reuses the ThresholdSampler already proven in `MemorySampler.lean`.

**The subtlety, modeled not assumed.** The Python free path clamps the running
footprint to `max(0, current − count)` on every free (`:218`). That clamp
*breaks* pure conservation: if frees drive the footprint below 0 (startup
misses, per the code comment), it silently adds bytes back. A naive model that
ignored the clamp would "prove" conservation falsely. So we prove the honest,
conditional statements:

| Model element | Scalene source | Meaning |
|---|---|---|
| `emitStep`/`emitRun` | `process_malloc`/`process_free` emit on sampler trigger | records carry the reported byte excess, action M/F, pid |
| `stepFootprint` with `max 0 (·)` | `current_footprint = max(0, current − count)` (`:218`) | the free-side clamp, modeled literally |
| `Safe` predicate | "Scalene can miss some initial allocations" (`:215`) | the regime where the clamp is inert |
| `pidFilter` | `if int(curr_pid) != int(pid): continue` (`:145`) | per-process filter |

**Theorems**

- `emit_records_sum` — the records the C++ ThresholdSampler emits sum (signed)
  to its `reported` net (bridge to `MemorySampler.threshold_conserves`).
- `clamp_is_identity_of_safe` — while the footprint stays ≥ 0, the clamp is a
  no-op and the Python fold is exactly additive.
- `roundtrip_conservation_of_safe` — **headline**: in that regime the reported
  footprint delta = (true net − sampler residual) / BYTES_PER_MB. End to end.
- `clamp_only_raises` — *without* the non-negativity assumption, the clamp can
  only push the footprint **up**: the reported footprint is always ≥ the
  additive value, so the error is one-sided (over-reporting live memory), never
  a silent undercount. The honest unconditional bound.
- `foreign_pid_dropped`, `newline_marker_skipped` — the pid filter and NEWLINE
  `continue` faithfully drop records that must not count.

Boundary: reuses the sampler model for the C++ half; models the footprint fold
and clamp, not the mapfile byte-format parsing.

---

## 15. Python/native classifier — `lean/Scalene/PythonNativeClassifier.lean`

The heuristic that splits each CPU sample's time between Python and native code
(`scalene_cpu_profiler.py:251-341`). It picks one of four branches from the
bytecode position: (A) at a CALL → all time native on this line; (B) c_time > 0
with a preceding CALL on a different line → c_time native there, python_time
Python here; (C) same line / not found → together; (D) else → as computed.

We separate the **theorem** from the **heuristic**:

- `charge_total` / `classified_conserves` — **conservation**: in *every* branch
  the total time charged across all `(line, python|native)` buckets equals the
  sample's `cpu = python_time + c_time`. The classification only *moves* a fixed
  budget between buckets; it never invents or drops time.
- `split_atCall`, `split_together`, `split_splitToCall` — the native/Python
  split each branch decides (all-native for A; `c_time`/`python_time` for B/C/D),
  characterizing the classifier's per-branch behaviour.
- `charge_nonneg` — every bucket charge is ≥ 0 (from `python_time, c_time ≥ 0`,
  which the code guarantees via `c_time = max(elapsed − python, 0)`).
- `classify_total` — the branch selector is a total function of the observable
  facts: exactly one branch fires for any input, so attribution is always
  defined over the whole input space.

The heuristic boundary, stated not hidden: *which* branch is correct depends on
whether the async signal was deferred inside a C call — unobservable from the
sample. `branchA_exact_if_in_call` proves the conditional (if the sample truly
landed in native code, branch A is exactly right); the CALL-opcode detection
that is supposed to establish that hypothesis is engineering, not formalized.

## 16. Per-line malloc attribution — `lean/Scalene/PerLineMallocAttribution.lean`

The Python reader's per-line bookkeeping (`scalene_memory_profiler.py:336-360`),
distinct from §14's footprint *total*: the `memory_malloc_samples`,
`memory_python_samples`, and per-line high-water dicts the profile reports per
source line, and the invariants the JSON renderer's divides depend on.

- `perline_conserves` — **per-line conservation**: Σ over lines of
  `memory_malloc_samples[line]` = `total_memory_malloc_samples`. Every malloc's
  bytes are credited to exactly one line and the grand total, so
  `n_usage_fraction = malloc[line]/total` is a genuine fraction.
- `python_le_malloc` — per line `0 ≤ memory_python_samples ≤
  memory_malloc_samples`, because each step adds `python_fraction·count ≤ count`
  (`python_fraction ∈ [0,1]`). This *derives* the bound `Attribution.lean`
  assumed (`pythonBytes_le_count`) — exactly the precondition
  `scalene_json.py`'s `n_python_fraction = python/malloc ∈ [0,1]` needs.
- `highwater_ge_current`, `highwater_monotone` — the per-line high-water mark
  dominates the running per-line footprint and never decreases: the reported
  peak is a true, monotone upper bound.

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
- **PASTA is now proven in discrete-time form** (`PoissonArrivals.lean`): a
  uniform arrival over `M` time slots lands on line ℓ with probability equal to
  ℓ's time fraction, and this realizes exactly the `trueFraction` sampling law
  `ProfilerCorrectness` assumes. The continuous-time order-statistics proof is
  still not formalized, but the sampler→correctness link is no longer merely
  cited.
- **Copy volume is now modeled end-to-end across the C++/Python boundary**
  (`CopyVolumeWiring.lean`): the emitter accumulator/flush state machine and the
  Python reader, with round-trip conservation. This is the first metric proven
  across the native boundary.
- **Out of scope (not yet modeled):** the C++ allocator's internal thread-local
  `_pythonCount`/`_cCount` accounting; the mapfile IPC *byte-format* parsing
  (the copy-volume model abstracts records, not their on-disk encoding); fork()
  lock-state hazards beyond the stop/join discipline; GPU/accelerator device
  paths; the per-sample Python/native classifier heuristic accuracy.

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
      SpaceSaving.lean           # bounded combined_stacks capacity proof
      ExtractMirror.lean         # proven == extracted integrity bridge
      ProfilerCorrectness.lean   # unbiased + consistent attribution (the user-facing spec)
      ExponentialSampler.lean    # sampler is Poisson: inverse-CDF + memorylessness (§7)
      MetricCorrectness.lean     # GPU / copy-volume / python-split / leak detection (§8)
      MemorySampler.lean         # threshold + Poisson sampler; two-counter bisimulation (§9)
      PerLineAttribution.lean    # per-line byte fraction under sampling (§10)
  extract/
    ScaleneExtract.lean         # extraction-friendly defs (Lean 4.12, LeanToPython)
    scalene_verified_core.py    # GENERATED Python oracle (committed)
```

The differential test that ties the oracle to production lives at
`tests/test_verified_space_saving.py`.

### Regenerating the extracted Python

Requires a [LeanToPython](https://github.com/emeryberger/LeanToPython) checkout
(Lean 4.12). Copy `formal/extract/ScaleneExtract.lean` into it and:

```bash
lake env lean ScaleneExtract.lean > scalene_verified_core.py
```

Then re-run `tests/test_verified_space_saving.py`. (The two transpiler fixes
described above are merged into LeanToPython `main`, so a current checkout
extracts the Bool-branch and `min`/`max` cases correctly with no patching.)
