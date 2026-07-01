# Scalene formal-verification status

Where the correctness effort stands, by subsystem. Two engines: **Lean 4**
(16 modules, 133 theorems, no `sorry`, standard axioms only) for mathematical
properties, and **TLA+** (2 specs, model-checked with TLC) for concurrency and
interleavings.

Each row is marked **✅ Proven**, **⚠️ Partial**, or **❌ Unproven**. "Proven"
means a machine-checked Lean theorem or an exhaustive TLC model-check (within
stated bounds); the mapping to source lives in `README.md`.

Last updated: 2026-07-01.

---

## Why two engines (and why we keep both)

Lean and TLA+/TLC are **complementary, not redundant** — each proves a class of
property the other can't reach ergonomically.

- **Lean → unbounded, quantitative correctness.** Theorems hold for *all* inputs:
  `estimator_unbiased` for every sample budget N, `frees ≤ allocs` for any event
  sequence, conservation over any trace, variance = p(1−p)/N. This is where the
  statistical guarantees and algebraic invariants live. TLC cannot state "for all
  N".
- **TLC → bounded interleaving-existence and liveness.** Push-button exploration
  of the full state space of a concurrent design. It gave a **concrete 4-state
  counterexample** for the `combined_stacks` race (`SignalSafety.tla`) — Lean
  would make you hand-construct the bad schedule. And it checks **liveness under
  fairness** (`Deadlock.tla`: no circular wait, output makes progress, handler
  never blocks) — temporal properties Lean has no comfortable story for.

The split: **use Lean for what must hold universally and quantitatively; use TLC
for finding bad schedules and for liveness.** One overlap is deliberate and
honest — `LeakTrackerConcurrency.lean` proves an interleaving-safety property in
Lean but *assumes step-atomicity as an axiom* (justified by the RLock + thread
join). Deriving that atomicity from the sig-queue's operational semantics is the
natural next **TLA+** job, not a Lean one (see the open item in `HANDOFF.md`).

So: **no, we should not fold TLC into Lean.** Retiring the TLC specs would drop
the counterexample-search and liveness coverage with nothing to replace them.

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
| **Python/native classifier conserves the sample's CPU budget in every branch** | ✅ | `PythonNativeClassifier.charge_total`, `classified_conserves` (+ `charge_nonneg`, per-branch `split_*`) — §15 |
| C++ stamping *establishes* faithful placement (signal→bytecode) | ⚠️ | engineering (`pywhere.cpp`); not modeled |
| Python-vs-native classifier per-sample *branch-choice* accuracy | ⚠️ | conditional correctness proven (`branchA_exact_if_in_call`); which branch is *right* is the CALL-opcode heuristic, not formalized |

**Verdict:** the statistical guarantee is proven, and the sampler→correctness
link that used to be *cited* (PASTA) is now proven in discrete-time form. The
classifier's *bookkeeping* is now proven conserving; the open items are the
signal-delivery physics and which-branch-is-right (the CALL-opcode heuristic).

## 2. Memory profiling

| Aspect | Status | Where |
|---|---|---|
| Threshold sampler conserves net bytes exactly | ✅ | `MemorySampler.threshold_conserves`, `threshold_residual_bounded` |
| Poisson memory sampler unbiased | ✅ | `MemorySampler.poisson_unbiased` |
| Literal two-counter sampler ≡ abstract model (bisimulation) | ✅ | `MemorySampler.step_bisim`, `threshold2_conserves` |
| Per-line byte fraction faithful under sampling | ✅ | `PerLineAttribution.fraction_of_expectations`, `recorded_fraction_exact` |
| Footprint conservation over a batch | ✅ | `Attribution.footprint_conserved` |
| **Malloc footprint C++→Python wiring, end-to-end** | ✅ | `MallocFootprintWiring.roundtrip_conservation_of_safe` (+ `emit_records_sum`, `clamp_only_raises`) — see §4b |
| **Per-line malloc attribution**: Σ per-line bytes = grand total; python-share ≤ bytes; high-water dominates & is monotone | ✅ | `PerLineMallocAttribution.perline_conserves`, `python_le_malloc`, `highwater_ge_current`, `highwater_monotone` — §16 |

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

## 4b. Malloc footprint — **end to end (C++↔Python), the harder path**

| Aspect | Status | Where |
|---|---|---|
| C++ ThresholdSampler emitted records sum (signed) to `reported` net | ✅ | `MallocFootprintWiring.emit_records_sum` |
| Python fold is exactly additive while footprint stays ≥ 0 (clamp inert) | ✅ | `MallocFootprintWiring.clamp_is_identity_of_safe` |
| **Round-trip (safe regime)**: reported footprint delta = (true-net − residual)/MB | ✅ | `MallocFootprintWiring.roundtrip_conservation_of_safe` |
| The `max(0,·)` clamp can *only* over-report (one-sided error, never undercount) | ✅ | `MallocFootprintWiring.clamp_only_raises` |
| Foreign-pid records dropped; NEWLINE markers skipped | ✅ | `foreign_pid_dropped`, `newline_marker_skipped` |

**Verdict:** the current-footprint / peak-memory number proven end-to-end,
reusing `MemorySampler.threshold_conserves` for the C++ half. The honest
subtlety — the free-side `max(0,·)` clamp breaks pure conservation — is *modeled,
not assumed away*: exact conservation holds in the non-negative regime, and
outside it the clamp only raises the reported footprint (never a silent
undercount). This is the audit method applied to a metric that a naive model
would have "proven" conserved by ignoring the clamp.

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
conservation laws — including the Python/native classifier's budget and the
per-line malloc attribution bookkeeping — **two metrics end-to-end across the
C++/Python boundary** (copy volume and malloc footprint, the latter modeling the
free-side clamp honestly), bounded-structure capacity, and the signal/deadlock
safety topology. **Not proven:** the signal-delivery physics, *which* classifier
branch is correct per sample (the CALL-opcode heuristic — only conservation and
conditional correctness are proven), the remaining device plumbing (GPU
acquisition), output rendering, and floating-point.
