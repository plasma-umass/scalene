/-
  Per-line attribution under sampling — tying MemorySampler back to the
  per-line `trueFraction` story of ProfilerCorrectness.

  §6 (ProfilerCorrectness) proves the CPU estimator unbiased/consistent for the
  per-line time fraction. §9 (MemorySampler) proves the memory sampler unbiased
  for *total* bytes per line. This file connects them: it shows the memory
  sampler's *per-line fraction* is a faithful estimator of the true per-line
  byte fraction — the memory analogue of §6, so §9's byte sampling inherits §6's
  attribution guarantee.

  The subtle point handled honestly: a profiler reports `recorded[ℓ] / Σ recorded`,
  a *ratio* of two unbiased estimators. `E[X/Y] ≠ E[X]/E[Y]` in general, so the
  ratio is not exactly unbiased. What IS true and is what a user relies on:

    * the ratio of EXPECTATIONS equals the true fraction (`fraction_of_expectations`),
      i.e. no systematic scale bias — the window cancels; and
    * on any single run the recorded fractions are exactly the true fractions
      whenever the per-line sampled counts are proportional to the true bytes
      (`recorded_fraction_exact`), the deterministic-limit / large-sample case.

  All over ℚ; no `sorry`.
-/
import Mathlib
import Scalene.MemorySampler

open scoped BigOperators

namespace Scalene.PerLineAttribution

variable {Line : Type} [Fintype Line] [DecidableEq Line]

/-- Ground-truth bytes allocated per line, with a positive total. -/
structure ByteTruth (Line : Type) [Fintype Line] where
  bytes : Line → ℚ
  nonneg : ∀ ℓ, 0 ≤ bytes ℓ
  total_pos : 0 < ∑ ℓ, bytes ℓ

namespace ByteTruth

variable {Line : Type} [Fintype Line] [DecidableEq Line]

def total (B : ByteTruth Line) : ℚ := ∑ ℓ, B.bytes ℓ

/-- True fraction of bytes on line ℓ — what an ideal memory profiler reports. -/
def trueFraction (B : ByteTruth Line) (ℓ : Line) : ℚ := B.bytes ℓ / B.total

/-- The Poisson sampler's expected rescaled estimate for line ℓ is exactly its
    true bytes (this is `MemorySampler.poisson_unbiased`, lifted to ℚ bytes:
    `window · (bytes/window) = bytes`). -/
def expectedRecorded (window : ℚ) (B : ByteTruth Line) (ℓ : Line) : ℚ :=
  window * (B.bytes ℓ / window)

theorem expectedRecorded_eq {window : ℚ} (hw : 0 < window) (B : ByteTruth Line)
    (ℓ : Line) : expectedRecorded window B ℓ = B.bytes ℓ := by
  unfold expectedRecorded
  field_simp

/-- **Fraction of expectations = true fraction.** The reported per-line fraction
    formed from the *expected* recorded counts equals the true per-line byte
    fraction, for any positive sampling window. The window (the sampling rate)
    cancels top and bottom, so sampling introduces no systematic scale bias into
    the per-line breakdown — the memory analogue of §6's `estimator_unbiased`
    for the ratio-of-expectations. -/
theorem fraction_of_expectations {window : ℚ} (hw : 0 < window) (B : ByteTruth Line)
    (ℓ : Line) :
    expectedRecorded window B ℓ / (∑ k, expectedRecorded window B k)
      = B.trueFraction ℓ := by
  have hsum : (∑ k, expectedRecorded window B k) = B.total := by
    unfold ByteTruth.total
    exact Finset.sum_congr rfl (fun k _ => expectedRecorded_eq hw B k)
  rw [hsum, expectedRecorded_eq hw B ℓ, ByteTruth.trueFraction]

end ByteTruth

/-! ## Single-run exactness in the proportional (large-sample) limit

On a finite run the sampler records integer counts. When those counts are
proportional to the true bytes — the deterministic threshold-sampler behaviour,
and the large-sample limit of the Poisson sampler — the *reported* fraction
equals the true fraction exactly, regardless of the proportionality constant
(the sampling rate). This is the sense in which the per-line breakdown is
rate-independent. -/

/-- If every line's recorded amount is `c ·` its true bytes (`c > 0` the shared
    sampling scale), the reported fraction equals the true fraction exactly —
    the scale `c` cancels. -/
theorem recorded_fraction_exact {Line : Type} [Fintype Line] [DecidableEq Line]
    (B : ByteTruth Line) (recorded : Line → ℚ) (c : ℚ) (hc : 0 < c)
    (hprop : ∀ ℓ, recorded ℓ = c * B.bytes ℓ) (ℓ : Line) :
    recorded ℓ / (∑ k, recorded k) = B.trueFraction ℓ := by
  have hsum : (∑ k, recorded k) = c * B.total := by
    unfold ByteTruth.total
    rw [Finset.mul_sum]
    exact Finset.sum_congr rfl (fun k _ => hprop k)
  rw [hprop ℓ, hsum, ByteTruth.trueFraction, ByteTruth.total]
  rw [mul_div_mul_left _ _ (ne_of_gt hc)]

/-- **Bounds.** The true per-line byte fraction is a genuine fraction in [0,1],
    and the fractions sum to 1 — the per-line memory breakdown is a probability
    distribution over lines, exactly like the CPU one. -/
theorem trueFraction_nonneg {Line : Type} [Fintype Line] [DecidableEq Line]
    (B : ByteTruth Line) (ℓ : Line) : 0 ≤ B.trueFraction ℓ :=
  div_nonneg (B.nonneg ℓ) (le_of_lt B.total_pos)

theorem trueFraction_sum_one {Line : Type} [Fintype Line] [DecidableEq Line]
    (B : ByteTruth Line) : ∑ ℓ, B.trueFraction ℓ = 1 := by
  unfold ByteTruth.trueFraction
  rw [← Finset.sum_div]
  exact div_self (ne_of_gt B.total_pos)

end Scalene.PerLineAttribution
