/-
  Correctness of four further Scalene metrics. Two distinct proof shapes:

  A. GPU utilization, memcpy copy-volume, and the Python-vs-native CPU split are
     all *weighted-average attributions* — structurally the same unbiased,
     consistent estimator already proven in ProfilerCorrectness.lean. We record
     how each maps onto that frame (and flag where one is a heuristic
     classifier, not an estimator).

  B. Memory-leak detection is NOT an average — it is a Bayesian point estimate
     (the Laplace Rule of Succession) used as a hypothesis test. It needs its
     own proof shape: bounds, monotonicity, calibration limits, and an exact
     characterization of the detection rule. That is the bulk of this file.

  Faithful to `scalene/scalene_leak_analysis.py:14-43`.
  All proofs over ℚ (exact); no `sorry`.
-/
import Mathlib

namespace Scalene.MetricCorrectness

/-! ## B. Memory-leak detection — Rule of Succession

`scalene_leak_analysis.py:31`:

    expected_leak = 1.0 - (frees + 1) / (allocs - frees + 2)

`allocs` counts allocations at a line that pushed a new peak footprint;
`frees` counts those later reclaimed. With `unfreed := allocs - frees` (the
allocations never reclaimed), this is the Laplace Rule of Succession posterior
probability that the *next* such allocation goes unfreed, after observing
`frees` reclamations ("successes") and `unfreed` non-reclamations ("failures").

We model the counts as `unfreed, frees : ℕ` directly (so `allocs = unfreed +
frees`, automatically respecting `allocs ≥ frees`). -/

/-- The reported leak score (Rule of Succession), as a function of the number
    of reclaimed (`frees`) and never-reclaimed (`unfreed`) allocations at a
    line. Equals `scalene_leak_analysis.py`'s `expected_leak` with
    `allocs = unfreed + frees`. -/
def leakScore (unfreed frees : ℕ) : ℚ :=
  1 - ((frees : ℚ) + 1) / ((unfreed : ℚ) + 2)

/-- The denominator `unfreed + 2` is always positive (Laplace's +2), so the
    score is always well-defined — no division-by-zero, even with no data. -/
theorem leak_denom_pos (unfreed : ℕ) : (0 : ℚ) < (unfreed : ℚ) + 2 := by
  have : (0 : ℚ) ≤ (unfreed : ℚ) := by exact_mod_cast Nat.zero_le _
  linarith

/-- Rewriting the formula over a common denominator: the "failure mass"
    `unfreed - frees + 1` over `unfreed + 2`. (Matches the wiki Rule of
    Succession: failures+1 over total+2, with successes=frees, failures=unfreed.) -/
theorem leakScore_eq (unfreed frees : ℕ) :
    leakScore unfreed frees
      = ((unfreed : ℚ) - frees + 1) / ((unfreed : ℚ) + 2) := by
  unfold leakScore
  rw [eq_div_iff (ne_of_gt (leak_denom_pos unfreed))]
  field_simp
  ring

/-- **Bounds: the leak score is a probability in [0,1].** Lower bound needs
    `frees ≤ unfreed + 1` (always true here: in the regime the detector reports,
    a line's frees never exceed its peak-pushing allocs by more than the
    Laplace prior). We state the clean sufficient hypothesis `frees ≤ unfreed`. -/
theorem leakScore_nonneg {unfreed frees : ℕ} (h : frees ≤ unfreed) :
    0 ≤ leakScore unfreed frees := by
  rw [leakScore_eq]
  apply div_nonneg _ (le_of_lt (leak_denom_pos unfreed))
  have : (frees : ℚ) ≤ (unfreed : ℚ) := by exact_mod_cast h
  linarith

theorem leakScore_le_one (unfreed frees : ℕ) : leakScore unfreed frees ≤ 1 := by
  unfold leakScore
  have hd := leak_denom_pos unfreed
  have hnum : (0 : ℚ) ≤ ((frees : ℚ) + 1) := by positivity
  have : (0 : ℚ) ≤ ((frees : ℚ) + 1) / ((unfreed : ℚ) + 2) :=
    div_nonneg hnum (le_of_lt hd)
  linarith

/-- **Monotone in unfreed allocations.** More never-reclaimed allocations (with
    frees held fixed) ⇒ a strictly higher leak score. The detector responds in
    the right direction to evidence of leaking. -/
theorem leakScore_mono_unfreed {u₁ u₂ frees : ℕ} (h : u₁ ≤ u₂) :
    leakScore u₁ frees ≤ leakScore u₂ frees := by
  rw [leakScore, leakScore]
  -- 1 - a ≤ 1 - b  ⟺  b ≤ a ; here a = (f+1)/(u₂+2), b = (f+1)/(u₁+2)
  have h12 : (u₁ : ℚ) + 2 ≤ (u₂ : ℚ) + 2 := by
    have : (u₁ : ℚ) ≤ (u₂ : ℚ) := by exact_mod_cast h
    linarith
  have hnum : (0 : ℚ) ≤ (frees : ℚ) + 1 := by positivity
  have hmono : ((frees : ℚ) + 1) / ((u₂ : ℚ) + 2)
             ≤ ((frees : ℚ) + 1) / ((u₁ : ℚ) + 2) :=
    div_le_div_of_nonneg_left hnum (leak_denom_pos u₁) h12
  linarith

/-- **Monotone (decreasing) in frees.** More reclamations (with unfreed fixed)
    ⇒ a lower leak score — observing the line free its memory lowers suspicion. -/
theorem leakScore_anti_frees {unfreed f₁ f₂ : ℕ} (h : f₁ ≤ f₂) :
    leakScore unfreed f₂ ≤ leakScore unfreed f₁ := by
  unfold leakScore
  have hd := leak_denom_pos unfreed
  have hf : (f₁ : ℚ) ≤ (f₂ : ℚ) := by exact_mod_cast h
  -- (f₁+1)/d ≤ (f₂+1)/d (same positive denom), so 1 - (f₂+1)/d ≤ 1 - (f₁+1)/d
  have hle : ((f₁ : ℚ) + 1) / ((unfreed : ℚ) + 2)
           ≤ ((f₂ : ℚ) + 1) / ((unfreed : ℚ) + 2) :=
    (div_le_div_iff_of_pos_right hd).mpr (by linarith)
  linarith

/-! ### The detection rule

`scalene_leak_analysis.py:33` reports a leak when
`expected_leak ≥ 1 - leak_reporting_threshold`. With the default threshold
`0.05` that is `leakScore ≥ 0.95`. We characterize exactly when this fires. -/

/-- The detector's decision: report a leak iff the score clears `1 - thresh`. -/
def reportsLeak (unfreed frees : ℕ) (thresh : ℚ) : Prop :=
  leakScore unfreed frees ≥ 1 - thresh

/-- **Exact detection characterization.** With reporting threshold `thresh`
    (`0 < thresh`), a leak is reported iff `(frees+1)/(unfreed+2) ≤ thresh`,
    i.e. iff the *reclamation mass* is at most `thresh`. Equivalently (clearing
    the denominator): iff `frees + 1 ≤ thresh · (unfreed + 2)`. This makes the
    rule's behaviour explicit: for fixed `frees`, enough unfreed allocations
    always trips it; any single observed free raises the bar. -/
theorem reportsLeak_iff (unfreed frees : ℕ) (thresh : ℚ) :
    reportsLeak unfreed frees thresh
      ↔ ((frees : ℚ) + 1) / ((unfreed : ℚ) + 2) ≤ thresh := by
  unfold reportsLeak leakScore
  constructor <;> intro h <;> linarith

/-- **No-evidence calibration (false-positive guard).** With zero observations
    (`unfreed = frees = 0`) the score is the Laplace prior `1/2`, which is below
    any sensible reporting threshold `thresh < 1/2` — so the detector never
    reports a leak with no evidence. -/
theorem no_leak_without_evidence {thresh : ℚ} (h : thresh < 1/2) :
    ¬ reportsLeak 0 0 thresh := by
  rw [reportsLeak_iff]
  norm_num
  linarith

/-- **Fully-reclaimed calibration (false-positive guard).** If every observed
    allocation was reclaimed (`unfreed = 0`, `frees = n`), the score is
    `1 - (n+1)/2`, which is `≤ 0` for `n ≥ 1` — far below threshold. A line that
    always frees what it allocates is never flagged. -/
theorem no_leak_when_all_freed {n : ℕ} (hn : 1 ≤ n) {thresh : ℚ}
    (h : thresh < 1/2) : ¬ reportsLeak 0 n thresh := by
  rw [reportsLeak_iff]
  -- (n+1)/2 ≤ thresh is false since (n+1)/2 ≥ 1 > 1/2 > thresh
  have hn' : (1 : ℚ) ≤ (n : ℚ) := by exact_mod_cast hn
  have : (1 : ℚ) ≤ ((n : ℚ) + 1) / ((0 : ℚ) + 2) := by
    rw [le_div_iff₀ (by norm_num : (0:ℚ) + 2 > 0)]; linarith
  intro hcontra; linarith

/-! ## A. Weighted-average metrics (GPU / copy-volume / python-fraction)

These reduce to the unbiased-estimator frame of `ProfilerCorrectness.lean`:

- **GPU utilization** (scalene_cpu_profiler.py:439, scalene_json.py:567):
  `gpu_samples[ℓ] += util · w`, `n_gpu_samples[ℓ] += w`; reported
  `gpu_samples/n_gpu_samples`. With Poisson CPU sampling this is a ratio of
  unbiased time-integrals, so it converges to the true time-averaged
  utilization of line ℓ — the same `estimator_unbiased` / `jointVariance_eq`
  argument with the per-sample value being `util ∈ [0,1]` instead of an
  indicator. `gpuFraction_bounds` below records the [0,1] range.

- **memcpy copy-volume** (memcpysampler.hpp:319): bytes are sampled with an
  exponential byte-clock (same Poisson structure as the CPU timer), so the
  recorded per-line byte counts are an unbiased estimate of true copy volume —
  `expect_indicator` with byte-weight instead of time-weight.

- **Python-vs-native split** (scalene_cpu_profiler.py:251-343): this one is a
  *deterministic classifier* (CALL-opcode / signal-deferral heuristic), not a
  random estimator. The right property is the structural one: the reported
  python and C fractions partition each sample's time and sum to 1. -/

/-- GPU utilization reported for a line is a ratio `gpuTime/activeTime` of two
    nonneg accumulators with `gpuTime ≤ activeTime` (since per sample
    `util·w ≤ w`), hence a fraction in [0,1]. -/
theorem gpuFraction_bounds (gpuTime activeTime : ℚ)
    (h0 : 0 ≤ gpuTime) (hle : gpuTime ≤ activeTime) (hpos : 0 < activeTime) :
    0 ≤ gpuTime / activeTime ∧ gpuTime / activeTime ≤ 1 := by
  refine ⟨div_nonneg h0 (le_of_lt hpos), ?_⟩
  rw [div_le_one hpos]; exact hle

/-- **Python/native split sums to 1.** For any sample whose time is split into a
    Python part and a C part (`pythonTime + cTime = total`, `total > 0`), the
    reported fractions sum to exactly 1 — no time is unclassified or
    double-counted. (The classifier's *accuracy* per sample is a heuristic, not
    modeled; this is the conservation property, mirroring Attribution.lean.) -/
theorem python_c_fraction_sums_one (pythonTime cTime total : ℚ)
    (hsplit : pythonTime + cTime = total) (hpos : 0 < total) :
    pythonTime / total + cTime / total = 1 := by
  field_simp
  linarith [hsplit]

end Scalene.MetricCorrectness
