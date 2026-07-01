# Formalizing Scalene — handoff / follow-up notes

Working doc so this can be picked up after a context reset. Captures what the
formal-verification effort has produced, the *method* (including a hard-won
lesson), what's merged vs. open, and concrete next steps.

Last updated: 2026-07-01.

---

## 0. The point of this effort (don't lose this framing)

We formalize Scalene's guarantees in Lean 4 (+ TLA+ for interleavings) for two
reasons, in priority order:

1. **Find and fix real bugs.** Formalizing forces every implicit assumption to
   be named. Where the code doesn't enforce what a proof needs, that's a
   finding — a real defect or an undocumented invariant. This has already paid
   off (four production bugs, see §4).
2. **Establish correctness** of the properties a profiler's *user* relies on.

**THE METHODOLOGICAL LESSON (most important thing in this doc):** a proof whose
hypotheses mirror the code's *implicit* assumptions validates the **model**, not
the **code**. Early models did exactly this and were therefore blind to real
bugs. Example: the leak model used `unfreed, frees : ℕ` with
`allocs = unfreed + frees`, which *hardcodes* `frees ≤ allocs` — so it could
never have caught the unguarded divide-by-zero that assumption protects against.

**Rule going forward:** treat every modeling hypothesis (`0 < total`,
`frees ≤ allocs`, `interval > 0`, `pythonTime + cTime = total`, every
denominator) as a *claim to verify against the implementation*. If the code
doesn't enforce it → that's a finding, not something to assume away. Audit
models adversarially, don't just prove them.

---

## 1. Where the artifacts live

```
formal/
  README.md              # full writeup: §1–§14, source mappings, boundaries, repro
  STATUS.md              # subsystem status map (proven / partial / unproven)
  HANDOFF.md             # this file
  tla/                   # TLA+ specs (model-checked with TLC)
    SignalSafety.tla + _Fix.cfg / _Bug.cfg
    Deadlock.tla + .cfg
  lean/                  # Lean 4 project (lake); Mathlib dep; toolchain v4.31.0
    Scalene.lean         # top-level: imports all modules below
    Scalene/*.lean       # see §2
  extract/
    ScaleneExtract.lean          # extraction-friendly defs (built under LeanToPython, Lean 4.12)
    scalene_verified_core.py     # GENERATED Python oracle (committed)
tests/
  test_verified_space_saving.py       # differential test: prod vs verified oracle
  test_leak_velocity_zero_elapsed.py  # regression for bug #1 (§4)
```

**Build:** `cd formal/lean && lake exe cache get && lake build` (needs
`~/.elan/bin` on PATH; Mathlib cache ~7GB, gitignored).
**TLC:** Java + `tla2tools.jar`. Ran on the `cloudnew` box (has Java 21);
`java -cp tla2tools.jar tlc2.TLC -config X.cfg X.tla`.
**All Lean proofs: no `sorry`; depend only on `propext, Classical.choice,
Quot.sound`** (verify with `#print axioms <thm>`).

`cloudnew` = a Linux dev box (192 cores) reachable via `ssh cloudnew`. Used for:
TLC model-checking (Java there), building the C++ native ext, and reproducing
free-threaded (3.13t/3.14t) behavior. Has `~/scalene-debug` checkout + uv venvs
`.venv-313t` / `.venv-314t`, and `~/tla/tla2tools.jar`. LeanToPython checkout is
at `/tmp/LeanToPython` locally (Lean 4.12).

---

## 2. What's proven (Lean modules) — each maps to real code in README

| Module | Property | Key theorems |
|---|---|---|
| `Attribution.lean` | CPU/mem bookkeeping conserved; fractions in [0,1] | `totalTime_eq_split`, `cpu_distribution_conserved`, `pythonFraction_le_one`, `footprint_conserved` |
| `SignalSafety.lean` | `list(...)` snapshot decouples output-iteration from concurrent inserts | `snapshot_stable`, `snapshot_sound` (no axioms) |
| `SpaceSaving.lean` | `combined_stacks` table never exceeds capacity; evicts min | `step_withinCap`, `fold_withinCap`, `minCount_le` |
| `ProfilerCorrectness.lean` | **headline**: reported per-line profile is unbiased + consistent | `estimator_unbiased`, `jointVariance_eq` (=p(1−p)/N), `jointExpect_pair` |
| `ExponentialSampler.lean` | sampler is Poisson ⇒ discharges the i.i.d. hypothesis | `sample_le_iff` (inverse-CDF), `survival_memoryless` |
| `MetricCorrectness.lean` | GPU/copy/python-split (weighted-avg) + leak detection (Bayesian test) | `gpuFraction_bounds`, `python_c_fraction_sums_one`, `leakScore_*`, `reportsLeak_iff`, `no_leak_without_evidence` |
| `MemorySampler.lean` | threshold sampler conserves net exactly; Poisson unbiased; **two-counter bisimulation** | `threshold_conserves`, `threshold_residual_bounded`, `threshold2_conserves`, `step_bisim`, `poisson_unbiased` |
| `PerLineAttribution.lean` | per-line byte fraction faithful under sampling | `fraction_of_expectations`, `recorded_fraction_exact` |
| `PoissonArrivals.lean` | **PASTA (discrete)**: uniform arrival lands on ℓ with prob = ℓ's time fraction; realizes the assumed `trueFraction` sampling law → discharges the ProfilerCorrectness hypothesis | `uniform_landing_eq_timeFraction`, `uniform_realizes_trueFraction`, `sum_timeFraction` |
| `CopyVolumeWiring.lean` | **copy volume end-to-end (C++↔Python)**: emitter/reader state machines; reported volume = observed − residual | `flushed_add_residual`, `python_total_eq_flushed`, `roundtrip_conservation`, `foreign_pid_dropped` |
| `MallocFootprintWiring.lean` | **malloc footprint end-to-end (C++↔Python)**: reuses ThresholdSampler; models the free-side `max(0,·)` clamp honestly (conserves in safe regime; only over-reports otherwise) | `emit_records_sum`, `clamp_is_identity_of_safe`, `roundtrip_conservation_of_safe`, `clamp_only_raises` |
| `PythonNativeClassifier.lean` | **Python/native classifier conserves the CPU budget in every branch** (total function); per-branch split characterized; branch-choice accuracy is the heuristic (conditional correctness only) | `charge_total`, `classified_conserves`, `split_atCall`/`split_together`, `charge_nonneg`, `branchA_exact_if_in_call` |
| `PerLineMallocAttribution.lean` | **per-line malloc bookkeeping**: Σ per-line bytes = grand total; python-share ≤ bytes; high-water dominates & monotone | `perline_conserves`, `python_le_malloc`, `highwater_ge_current`, `highwater_monotone` |
| `ClassifierAccuracy.lean` | **classifier accuracy, both paths**: worker + main-branch-A exact under CPython signal-delivery hypothesis; the two paths agree in the shared regime; deferral route characterized; error quantified when the hypothesis fails | `worker_classifier_correct`, `main_branchA_correct`, `main_worker_agree`, `deferral_route_iff`, `misclassified_when_unsound` |
| `LeakTrackerAudit.lean` | proves the leak formula's *unguarded* denominator is safe (`frees ≤ allocs`) | `run_frees_le_allocs`, `denom_pos_reachable` |
| `LeakTrackerConcurrency.lean` | `frees ≤ allocs` survives sig-queue/main-thread interleaving + fork; RLock atomicity & joint fork-reset shown *necessary* | `interleave_preserves_inv`, `torn_free_breaks_inv`, `fork_reset_inv`, `partial_fork_reset_breaks_inv` |
| TLA+ `SignalSafety` | the combined_stacks race is reachable (bug cfg) / impossible (fix cfg) | 4-state counterexample; 99 states clean |
| TLA+ `Deadlock` | no deadlock; handler never blocks on a lock; output liveness | 72 states clean |

The "profiler correctness" chain: **faithful per-sample attribution ⇒ unbiased,
consistent reported profile**. Faithfulness is delivered by (a) the exponential
sampler (§`ExponentialSampler`, Poisson + PASTA), (b) synchronous C++ stamping
(`whereInPython`, `pywhere.cpp` — engineering, not yet Lean-proven), and (c) the
conservation invariants (`Attribution`).

---

## 3. Merged to master (all green)

Formal + the CI/bug work that unblocked it:
- **#1068** formal models (TLA+ + Lean core)
- **#1070** SpaceSaving capacity proof + proof→production extraction pipeline
- **#1072** profiler-correctness desideratum (unbiased + consistent)
- **#1073** regenerate oracle w/ upstream-fixed LeanToPython (dropped `min2`)
- **#1075** Poisson sampler + GPU/copy/python-split/leak + memory-sampler
- Enabling fixes: **#1066** (test `sys.executable` leak — the original
  root-cause), **#1067** (combined_stacks race), **#1069/#1071/#1074** (CI
  timing flakes), **#1065** (`_scalene_unwind` GIL declaration).
- **emeryberger/LeanToPython#1** (MERGED): fixed two transpiler bugs
  (Bool-param branch inversion; binary `min`/`max` operand drop) found while
  extracting Scalene's defs. Local checkout: `/tmp/LeanToPython`.

Also merged 2026-07-01:
- **#1077** the two production bug fixes from §4 (leak-velocity div-by-zero +
  sampling-window clamp).
- **#1076** two-counter bisimulation + per-line attribution +
  `LeakTrackerAudit.lean` + `LeakTrackerConcurrency.lean` (leak-tracker
  concurrency/fork gap) + README "bugs found".
- **#1078** §4 bugs #3 (unguarded per-stack CPU normalization divide) and #4
  (CLI-renderer twin of the leak-velocity divide) + two regression tests.
- **#1080** PASTA (`PoissonArrivals.lean`) + two metrics end-to-end across the
  C++/Python boundary (`CopyVolumeWiring.lean`, `MallocFootprintWiring.lean`) +
  `STATUS.md` + README proof roundup + "why two engines" rationale.

## 3b. OPEN PRs (need driving to merge)

None — all formal PRs merged as of 2026-07-01.

---

## 4. Bugs the formalization found (#1, #2 FIXED in #1077; #3, #4 in #1078)

1. **ZeroDivisionError, leak velocity.** `scalene_json.py` ~line 1255:
   `"velocity_mb_s": leak_velocity / stats.elapsed_time` was unguarded.
   `compute_leaks` (`scalene_leak_analysis.py`) gates on allocation *growth
   rate*, NOT wall-clock time, so a leak can be reported when `elapsed_time`
   is still `0.0` (sub-ms run) → crash. Sibling `elapsed_time` divides
   (~637, ~1186) were already guarded. Fixed + regression test.
2. **Sampling window = 0 from bad env var.** `sampleheap.hpp`:
   `atol(getenv("SCALENE_ALLOCATION_SAMPLING_WINDOW"))` returns 0 for `"0"` /
   unparseable → ThresholdSampler triggers on *every* alloc (`incr >= decr+0`),
   catastrophic overhead. Violates `interval > 0` (proved necessary in
   `MemorySampler.lean`). Fixed by clamping ≤0 to the default. Verified on
   cloudnew: `WINDOW=0` run now completes.

3. **ZeroDivisionError, per-stack CPU normalization.** `scalene_json.py`, the
   `stats.stacks` normalization loop dividing by `cpu_stats.total_cpu_samples`
   was unguarded. `total_cpu_samples` can be `0.0` while `stats.stacks` is
   non-empty — a **memory-only run with `--stacks`** records stack entries but
   never a CPU sample, and it is *memory* activity (not CPU) that passes the
   "nothing to output" gate. Sibling CPU normalizations (~556, ~1259, ~1337)
   were already guarded; this one was missed → crash. Same class as #1. Found
   by re-running the §0 "every denominator is a claim" audit across the output
   path. Fixed + regression test (`tests/test_stacks_zero_cpu_samples.py`,
   drives the full `output_profiles` path). PR **#1078**.
4. **CLI-renderer twin of #1.** `scalene_output.py:699` (the `scalene view
   --cli` leak report) had the identical unguarded `leak[2] /
   stats.elapsed_time` that #1077 fixed only in `scalene_json.py`. Scalene has
   three separate renderers (Scalene-Debugging.md) — fixing one doesn't cover
   the others. Found by auditing the CLI path's divides. Fixed + regression
   test (`tests/test_cli_leak_velocity_zero_elapsed.py`). Also PR **#1078**.

Additional finding (no bug, but was implicit): the leak formula
`1 − (frees+1)/(allocs−frees+2)` has NO denominator guard; safety rests on
`frees ≤ allocs`, which is non-obvious (two separate increment sites,
`scalene_memory_profiler.py:236` and `:401`). `LeakTrackerAudit.lean` now
*proves* it from the single-shot armed-trigger discipline.

---

## 5. CI notes (so flakes don't waste a session)

Matrix uses `fail-fast: true`, so one red job cancels the rest. Four wall-clock/
signal timing flakes were hardened at the source (#1069/#1071/#1074) — parity
contention-ratio (now non-gating), HyperLogLog hash-seed (now deterministic ints),
`test_mac_sampler` (poll-not-sleep), `test_off_then_on_via_signal` (placeholder
SIGILL handler + retry). Remaining transient: `vendor/libunwind` download can
500. **When a formal-only PR shows red: check whether the failing step is
`Build scalene` (transient download) or a known flake test — if so, just re-run
`gh run rerun <id> --failed`.** `ubuntu-latest, 3.13t` runs ~40 min (compiles
deps from source; no cp313t wheels) — near the 45-min cap but passes.

Oracle test (`test_verified_space_saving.py`) skips on Python < 3.10 (the
generated `X | Y` unions need 3.10+).

---

## 6. Known modeling gaps / caveats (be honest about these)

- **Faithful sampling is assumed, not proven.** §ProfilerCorrectness proves
  "faithful sampling ⇒ correct profile". It does NOT prove the C++ stamping
  *establishes* faithful sampling (needs modeling signal delivery + CPython
  loop). Discharged by engineering + §Attribution, not Lean.
- **PASTA is cited, not formalized** (needs continuous-time stochastic-process
  dev). It's the step connecting Poisson sampling to the `trueFraction`
  distribution.
- **`LeakTrackerAudit` models the increment *discipline*, not the literal
  code.** It assumes single-shot arm/disarm. The sig-queue/main-thread
  interleaving and `fork` gap that was flagged here is now **closed** by
  `LeakTrackerConcurrency.lean` (§2, §11 in README): interleaving safety under
  the RLock, plus proofs that RLock atomicity and joint fork-reset are
  *necessary* (`torn_free_breaks_inv`, `partial_fork_reset_breaks_inv`). What
  remains assumed: that each `process_malloc_free_samples` call really is atomic
  w.r.t. the others (the RLock + join discipline the code implements) — the
  model takes step-atomicity as given rather than deriving it from the queue's
  operational semantics.
- **Python/native split**: only the *conservation* (fractions sum to 1) is
  proven, NOT the per-sample *accuracy* of the CALL-opcode/signal-deferral
  classifier heuristic.
- **The extraction oracle is a differential guard, not a drop-in.** Production
  still has its own `_space_saving_increment`; the test checks they agree.
- **C++→Python wiring** (native counters → `ScaleneStatistics`) is not modeled.
- TLC results are bounded (`Keys={k1,k2,k3}`, `N=3`, `MaxHandler=2`) — exhaustive
  within bounds, not a general proof.

---

## 7. Concrete next steps (roughly ranked)

1. ~~Merge #1077, #1076, #1078, #1080~~ **DONE** (2026-07-01). All four bug
   fixes, the concurrency proof, PASTA, and the two end-to-end wiring modules
   are on master. No formal PRs open.
2. ~~Audit `LeakTrackerAudit`'s faithfulness under concurrency/fork~~ **DONE**
   — `LeakTrackerConcurrency.lean` models the sig-queue/main-thread interleaving
   and fork reset explicitly, proves the invariant survives every interleaving,
   and proves the RLock atomicity + joint fork-reset are *necessary*. Residual:
   step-atomicity is taken as a modeling axiom (justified by the RLock + thread
   join in the code) rather than derived from the queue's operational semantics
   — a TLA+ spec of `ScaleneSigQueue.run` could discharge that too.
3. **Keep auditing hypotheses adversarially** (the §0 method): every `0 <`,
   every denominator, every counter that could underflow. This is paying off —
   re-running the sweep across the output path found bug #3 (§4) after #1077.
   Divide sites in `scalene_json.py` are now all guarded/try-excepted (audited
   2026-07-01: ~556, ~583, ~585, ~592, ~621/632/637, ~659, ~759, ~779 (fixed
   #3), ~1186, ~1259, ~1337 — all guarded). `scalene_output.py` (the CLI
   renderer) also audited 2026-07-01 — found bug #4 at :699 (now fixed); its
   other divides (~339, ~379, ~416, ~657) are guarded. NEXT untouched surfaces:
   the third renderer's path + `sparkline.py` / `runningstats.py` variance/stddev
   denominators. Lesson reinforced by #4: audit ALL THREE renderers, not one.
4. ~~Formalize PASTA (discrete-time analogue)~~ **DONE** —
   `PoissonArrivals.lean`. Uniform-arrival-over-M-slots lands on ℓ with prob =
   time fraction, and realizes the `trueFraction` law ProfilerCorrectness
   assumes (`uniform_realizes_trueFraction`). Residual: continuous-time
   order-statistics proof still not formalized (discrete form is the operative
   content for a tick-sampled profiler).
5. ~~Prove/characterize the python/native classifier~~ **DONE** —
   `PythonNativeClassifier.lean` (conservation, totality) + `ClassifierAccuracy.lean`
   (accuracy). The accuracy module makes CPython signal-delivery an *explicit
   hypothesis* (`SigDeliverySound`: `atCall ⇔ truly in a C call`) and proves BOTH
   code paths exact under it — the worker-thread bytecode classifier
   (`_update_thread_stats`) and the main-thread branch A — plus that the two
   paths agree in their shared regime and diverge only where the virtual timer
   can measure deferral. STILL OPEN (the honest residual): `SigDeliverySound`
   itself, a CPython-runtime + synchronous-stamping property. Discharging it
   would need modeling the eval loop's signal-check + `f_lasti` semantics, or a
   differential test harness that stress-checks `atCall` against ground truth.
6. **Wire the verified oracle into production directly** (have
   `_space_saving_increment` call the extracted core) rather than only
   differential-testing it — closes the proof→production loop tighter.
7. ~~Model columns end-to-end incl. the C++→Python wiring~~ **DONE (×2)** +
   ~~per-line malloc attribution~~ **DONE** — `CopyVolumeWiring.lean` (memcpy),
   `MallocFootprintWiring.lean` (footprint total), and
   `PerLineMallocAttribution.lean` (the per-line `memory_malloc_samples`/
   `memory_python_samples`/high-water bookkeeping). NEXT such target: GPU
   acquisition, or the per-line *free*/leak-credit bookkeeping.
8. **A committed status map** lives at `formal/STATUS.md` — keep it current when
   modules land.

---

## 8. Repro cheatsheet

```bash
# Lean (local)
cd formal/lean && lake exe cache get && lake build          # 0 sorry
echo 'import Scalene
#print axioms Scalene.ProfilerCorrectness.Truth.estimator_unbiased' > /tmp/a.lean
lake env lean /tmp/a.lean                                    # standard axioms only

# TLA+ (on cloudnew, has Java)
scp formal/tla/* cloudnew:~/tla/scalene/
ssh cloudnew 'cd ~/tla/scalene && java -cp ~/tla/tla2tools.jar tlc2.TLC \
  -config SignalSafety_Fix.cfg SignalSafety.tla'            # no error, 99 states

# Regenerate the extracted oracle (needs /tmp/LeanToPython, Lean 4.12)
cp formal/extract/ScaleneExtract.lean /tmp/LeanToPython/
cd /tmp/LeanToPython && lake env lean ScaleneExtract.lean > scalene_verified_core.py

# The bug-finding regression test
python3 -m pytest tests/test_leak_velocity_zero_elapsed.py -q
```
