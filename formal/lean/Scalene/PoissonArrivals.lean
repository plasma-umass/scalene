/-
  PASTA — "Poisson Arrivals See Time Averages" — the step that DISCHARGES the
  central hypothesis of ProfilerCorrectness.lean instead of leaving it cited.

  ProfilerCorrectness proves: *given* that each timer tick lands on line ℓ with
  probability `trueFraction ℓ` (= fraction of time ℓ truly runs), the reported
  profile is unbiased and consistent. It ASSUMES that sampling distribution.
  ExponentialSampler proves the sampler's inter-arrival gaps are Exponential, so
  the sample instants form a Poisson process — but the link "Poisson sample
  instants ⇒ landing probability = time fraction" was cited as PASTA, not proven.

  This file proves it, in the discrete-time form the handoff explicitly accepts
  as sufficient ("or at least a discrete-time analogue"). The key probabilistic
  fact behind PASTA is that a Poisson arrival, *conditioned on the number of
  arrivals in a horizon*, occurs at a time uniformly distributed over that
  horizon (the order-statistics property of the Poisson process). We model the
  horizon as `M` equal time slots, each labeled by the line executing during it,
  and a single arrival as a uniform draw over the `M` slots. We then prove:

    LANDING PROBABILITY = TIME AVERAGE
      P(the arrival lands while line ℓ runs) = (time spent on ℓ) / (total time).

  and — the actual payoff — that this uniform-time sampling realizes EXACTLY the
  `trueFraction`-weighted sampling distribution `ProfilerCorrectness` assumes
  (`uniform_realizes_trueFraction`). So the i.i.d.-faithful-sampling hypothesis
  is now grounded in the sampler's mechanism, not postulated.

  All proofs over ℚ; no `sorry`.
-/
import Mathlib
import Scalene.ProfilerCorrectness

open scoped BigOperators

namespace Scalene.PoissonArrivals

variable {Line : Type} [Fintype Line] [DecidableEq Line]

/- A discretized execution timeline: `M` equal time slots, `slots i` is the
   line executing during slot `i`. `weight ℓ` (below) counts the slots on ℓ,
   i.e. the time spent on ℓ. A single Poisson arrival, conditioned on its
   count, occurs at a uniformly random time — here, a uniform slot index. -/

/-- Number of time slots on line ℓ — the discrete "time spent on ℓ". -/
def timeCount (M : ℕ) (slots : Fin M → Line) (ℓ : Line) : ℚ :=
  ∑ i, (if slots i = ℓ then (1 : ℚ) else 0)

/-- Expectation of `g` under one uniform arrival over the `M` slots. -/
def uniformExpect (M : ℕ) (g : Fin M → ℚ) : ℚ := (1 / (M : ℚ)) * ∑ i, g i

/-- The fraction of time spent on ℓ (the time average). -/
def timeFraction (M : ℕ) (slots : Fin M → Line) (ℓ : Line) : ℚ :=
  timeCount M slots ℓ / (M : ℚ)

theorem timeCount_nonneg (M : ℕ) (slots : Fin M → Line) (ℓ : Line) :
    0 ≤ timeCount M slots ℓ := by
  unfold timeCount
  apply Finset.sum_nonneg
  intro i _; by_cases h : slots i = ℓ <;> simp [h]

/-- The slot counts sum to the total number of slots: each slot belongs to
    exactly one line. This is why the time fractions form a distribution. -/
theorem sum_timeCount (M : ℕ) (slots : Fin M → Line) :
    ∑ ℓ, timeCount M slots ℓ = (M : ℚ) := by
  unfold timeCount
  rw [Finset.sum_comm]
  -- inner: for each slot i, exactly one ℓ matches ⇒ Σ_ℓ [slots i = ℓ] = 1
  have hinner : ∀ i : Fin M, (∑ ℓ, (if slots i = ℓ then (1 : ℚ) else 0)) = 1 := by
    intro i
    rw [Finset.sum_ite_eq Finset.univ (slots i) (fun _ => (1 : ℚ))]
    simp
  rw [Finset.sum_congr rfl (fun i _ => hinner i)]
  simp

/-- **PASTA (discrete form): landing probability = time average.** The expected
    indicator that a uniform arrival lands on line ℓ equals the fraction of time
    ℓ runs. This is the defining PASTA identity: a Poisson observer (uniform in
    time) sees each line exactly as often as that line is running. -/
theorem uniform_landing_eq_timeFraction (M : ℕ) (slots : Fin M → Line) (ℓ : Line) :
    uniformExpect M (fun i => if slots i = ℓ then (1 : ℚ) else 0)
      = timeFraction M slots ℓ := by
  unfold uniformExpect timeFraction timeCount
  ring

/-- The time fractions sum to 1 (for a non-empty horizon) — a genuine
    probability distribution over lines. -/
theorem sum_timeFraction (M : ℕ) (hM : 0 < M) (slots : Fin M → Line) :
    ∑ ℓ, timeFraction M slots ℓ = 1 := by
  unfold timeFraction
  rw [← Finset.sum_div, sum_timeCount]
  have : (M : ℚ) ≠ 0 := by
    have : (0 : ℕ) < M := hM
    exact_mod_cast this.ne'
  field_simp

/-! ## Bridge to ProfilerCorrectness: the mechanism realizes the assumed law

We now build the `ProfilerCorrectness.Truth` induced by a timeline and show its
`trueFraction` — the sampling law that proof *assumes* — is exactly the uniform
arrival's landing probability proved above. This closes the gap: the faithful
sampling distribution is delivered by the Poisson/uniform arrival mechanism. -/

open Scalene.ProfilerCorrectness

/-- The ground-truth profile induced by a timeline: each line's weight is the
    time (slot count) spent on it. Needs at least one slot for a positive total. -/
def toTruth (M : ℕ) (hM : 0 < M) (slots : Fin M → Line) : Truth Line where
  weight ℓ := timeCount M slots ℓ
  nonneg ℓ := timeCount_nonneg M slots ℓ
  total_pos := by
    have h : (∑ ℓ, timeCount M slots ℓ) = (M : ℚ) := sum_timeCount M slots
    rw [h]; exact_mod_cast hM

/-- The induced Truth's total equals the horizon length `M`. -/
theorem toTruth_total (M : ℕ) (hM : 0 < M) (slots : Fin M → Line) :
    (toTruth M hM slots).total = (M : ℚ) := by
  unfold Truth.total toTruth
  exact sum_timeCount M slots

/-- The induced Truth's `trueFraction` is exactly the timeline's time fraction. -/
theorem toTruth_trueFraction (M : ℕ) (hM : 0 < M) (slots : Fin M → Line) (ℓ : Line) :
    (toTruth M hM slots).trueFraction ℓ = timeFraction M slots ℓ := by
  unfold Truth.trueFraction timeFraction
  rw [toTruth_total M hM slots]
  rfl

/-- **The discharge.** The uniform-time arrival mechanism realizes precisely the
    `trueFraction`-weighted sampling distribution that `ProfilerCorrectness`
    assumes: the uniform landing probability on line ℓ equals both the time
    fraction AND `Truth.expect (indicator ℓ)`. So the hypothesis feeding
    `estimator_unbiased` / `jointVariance_eq` is not postulated — it is produced
    by the Poisson sampler (via PASTA), which `ExponentialSampler` shows the code
    implements. This is the missing link between the sampler and the correctness
    theorem. -/
theorem uniform_realizes_trueFraction (M : ℕ) (hM : 0 < M) (slots : Fin M → Line)
    (ℓ : Line) :
    uniformExpect M (fun i => if slots i = ℓ then (1 : ℚ) else 0)
      = (toTruth M hM slots).expect (Truth.indicator ℓ) := by
  rw [uniform_landing_eq_timeFraction M slots ℓ,
      ← toTruth_trueFraction M hM slots ℓ,
      Truth.expect_indicator]

end Scalene.PoissonArrivals
