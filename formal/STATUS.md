# Scalene formal-verification status

Where the correctness effort stands, by subsystem. Two engines: **Lean 4**
(13 modules, 105 theorems, no `sorry`, standard axioms only) for mathematical
properties, and **TLA+** (2 specs, model-checked with TLC) for concurrency and
interleavings.

Each row is marked **✅ Proven**, **⚠️ Partial**, or **❌ Unproven**. "Proven"
means a machine-checked Lean theorem or an exhaustive TLC model-check (within
stated bounds); the mapping to source lives in `README.md`.

Last updated: 2026-07-01.

---

## 1. CPU profiling — the headline

| Aspect | Status | Where |
|---|---|---|
| Reported per-line profile is **unbiased** (E[reported] = truth, any N≥1) | ✅ | `ProfilerCorrectness.estimator_unbiased` |
| Profile is **consistent** — variance = p(1−p)/N → 0 | ✅ | `ProfilerCorrectness.jointVariance_eq` |
| Distinct samples independent (factorization) | ✅ | `ProfilerCorrectness.jointExpect_pair` |
| Sampler inter-arrivals are **Exponential** (⇒ Poisson process) | ✅ | `ExponentialSampler.sample_le_iff`, `survival_memoryless` |
| **PASTA**: Poisson sample lands on ℓ with prob = ℓ's time fraction — *discharges the faithful-sampling hypothesis* | ✅ (discrete form) | `PoissonArrivals.uniform_realizes_trueFraction` |
| Python/C time split conserved & non-negative | ✅ | `Attribution.totalTime_eq_split`, `cpu_distribution_conserved` |
| C++ stamping *establishes* faithful placement (signal→bytecode) | ⚠️ | engineering (`pywhere.cpp`); not modeled |
| Python-vs-native per-sample **classifier heuristic** accuracy | ❌ | only conservation proven, not heuristic accuracy |

**Verdict:** the statistical guarantee is proven, and the sampler→correctness
link that used to be *cited* (PASTA) is now proven in discrete-time form. The
open items are the signal-delivery physics and the CALL-opcode classifier.

## 2. Memory profiling

| Aspect | Status | Where |
|---|---|---|
| Threshold sampler conserves net bytes exactly | ✅ | `MemorySampler.threshold_conserves`, `threshold_residual_bounded` |
| Poisson memory sampler unbiased | ✅ | `MemorySampler.poisson_unbiased` |
| Literal two-counter sampler ≡ abstract model (bisimulation) | ✅ | `MemorySampler.step_bisim`, `threshold2_conserves` |
| Per-line byte fraction faithful under sampling | ✅ | `PerLineAttribution.fraction_of_expectations`, `recorded_fraction_exact` |
| Footprint conservation over a batch | ✅ | `Attribution.footprint_conserved` |
| Malloc/free C++→Python counter wiring | ⚠️ | leak-tracker slice modeled (§3); general malloc/free wiring not |

## 3. Memory-leak detection

| Aspect | Status | Where |
|---|---|---|
| Leak score = Rule-of-Succession prob, ∈[0,1], monotone; exact decision rule | ✅ | `MetricCorrectness.leakScore_*`, `reportsLeak_iff`, `no_leak_without_evidence` |
| Unguarded denominator safe (`frees ≤ allocs`) | ✅ | `LeakTrackerAudit.run_frees_le_allocs`, `denom_pos_reachable` |
| Safety survives sig-queue/main-thread interleaving + fork | ✅ | `LeakTrackerConcurrency.interleave_preserves_inv` |
| The serialization is *necessary* (lock + joint fork-reset) | ✅ | `torn_free_breaks_inv`, `partial_fork_reset_breaks_inv` |

**Verdict:** the most thoroughly closed subsystem — including its concurrency
model. The audit that built it found production bugs (see `README.md`).

## 4. Copy-volume (memcpy) — **end to end across C++/Python**

| Aspect | Status | Where |
|---|---|---|
| C++ conservation: flushed bytes = observed − accumulator residual | ✅ | `CopyVolumeWiring.flushed_add_residual` |
| Python transfer faithful (mapfile + pid filter neither drop nor dup) | ✅ | `CopyVolumeWiring.python_total_eq_flushed` |
| **Round-trip**: Python-reported volume = C++-observed − residual | ✅ | `CopyVolumeWiring.roundtrip_conservation` |
| Foreign-pid records dropped | ✅ | `CopyVolumeWiring.foreign_pid_dropped` |
| Residual bounded by one sampling interval | ✅ | `CopyVolumeWiring.residual_zero_after_flush` |

**Verdict:** the first metric proven **across the native/Python boundary** — the
number `scalene view` shows for copy volume faithfully reflects the bytes the
C++ interposer observed, up to a bounded in-flight residual.

## 5. Other metrics (GPU / python-split)

| Aspect | Status | Where |
|---|---|---|
| GPU fraction bounds; weighted-average splits sum to 1 | ✅ | `MetricCorrectness.gpuFraction_bounds`, `python_c_fraction_sums_one` |
| GPU/accelerator device-acquisition paths | ❌ | out of scope (NVIDIA/Apple/Neuron) |

## 6. Concurrency & signal safety

| Aspect | Status | Where |
|---|---|---|
| `list(...)` snapshot decouples output iteration from concurrent inserts | ✅ | `SignalSafety.snapshot_stable`, `snapshot_sound` (Lean) |
| `combined_stacks` race reachable in bug cfg / impossible in fix cfg | ✅ | TLA+ `SignalSafety` (4-state CEX / 99 clean) |
| No deadlock; handler never blocks on a lock; output liveness | ✅ | TLA+ `Deadlock` (72 states clean) |
| Step-atomicity derived from queue operational semantics | ⚠️ | taken as modeling axiom (justified by RLock + join) |

## 7. Bounded data structures

| Aspect | Status | Where |
|---|---|---|
| `combined_stacks` table never exceeds capacity; evicts min | ✅ | `SpaceSaving.step_withinCap`, `fold_withinCap`, `minCount_le` |
| Verified core ↔ production agree (proof→production) | ✅ + tested | `ExtractMirror.lean` + `tests/test_verified_space_saving.py` |

---

## No formal coverage yet

- **Output rendering** (`scalene_json.py`, `scalene_output.py`, HTML/GUI) — the
  three renderers; guarded by tests, not proofs. This is where the adversarial
  denominator audit found all four divide-by-zero bugs (see `README.md`).
- **CLI/argument parsing, config, signal setup.**
- **Replacement modules** (`replacement_*.py`).
- **Floating-point rounding** — all Lean proofs use exact ℚ.
- **Jupyter integration, AI-provider GUI.**

## Honest boundaries (carried from README §"What is assumed")

- Lean proofs are over exact ℚ/ℕ; floating-point error is a separate concern.
- TLC results are exhaustive only within bounds (`N=3`, `MaxHandler=2`, etc.).
- PASTA is proven in **discrete-time** form (uniform arrival over M slots), the
  analogue the effort targeted; the continuous-time order-statistics proof is
  not formalized.
- `CopyVolumeWiring` models the emitter/reader **state machines and the byte
  accounting**; it does not model the mapfile's low-level byte-format parsing or
  partial-read/corruption handling.

---

## Where we stand, in one line

**Proven:** the statistical heart (CPU unbiased+consistent *with the PASTA link
now closed*, memory sampling, leak detection incl. concurrency), the
conservation laws, one metric (**copy volume**) end-to-end across the C++/Python
boundary, bounded-structure capacity, and the signal/deadlock safety topology.
**Not proven:** the signal-delivery physics, the native/Python classifier
heuristic, the remaining C++/IPC/device plumbing, output rendering, and
floating-point.
