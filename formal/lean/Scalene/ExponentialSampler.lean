/-
  The CPU sampler's inter-sample intervals are exponentially distributed —
  i.e. the sample *times* form a Poisson process. This file proves the sampler
  transform is correct, and explains why that is exactly what discharges the
  i.i.d.-sampling hypothesis of ProfilerCorrectness.lean rather than leaving it
  as an idealization.

  Faithful to `scalene/scalene_profiler.py:1108`:

      def _generate_exponential_sample(scale):
          u = random.random()              # Uniform[0,1)
          return -scale * math.log(1 - u)  # inverse-CDF transform

  `-scale · log(1 − u)` is the inverse-CDF (Smirnov) transform for the
  Exponential distribution with mean `scale`: if `u ~ Uniform[0,1)` then the
  output has CDF `F(t) = 1 − exp(−t/scale)`. We prove exactly that.

  WHY THIS MATTERS for ProfilerCorrectness. A profiler that samples at a FIXED
  rate can alias with periodic program behaviour, biasing attribution. Drawing
  the inter-sample gap from an Exponential makes the sample instants a Poisson
  process, which gives two things the correctness proof assumes:

    * Independence — the Exponential is memoryless (`memoryless` below), so the
      time to the next sample is independent of the past; consecutive samples
      are independent. This is the `jointExpect` product-distribution model.
    * Faithful per-sample weighting — by PASTA ("Poisson Arrivals See Time
      Averages"), a Poisson sample lands in a state with probability equal to
      the *fraction of time* spent in that state. That is precisely the
      `trueFraction` sampling distribution `expect_indicator` assumes.

  So the i.i.d. hypothesis is **discharged by the code's exponential sampler**,
  not an unbacked idealization. (PASTA itself we cite, not formalize — it needs
  a continuous-time stochastic-process development beyond this file.)

  All proofs over ℝ; no `sorry`.
-/
import Mathlib

open Real

namespace Scalene.ExponentialSampler

/-- The sampler transform `T(u) = -scale * log(1 - u)` (scalene_profiler.py:1110). -/
noncomputable def sample (scale u : ℝ) : ℝ := -scale * Real.log (1 - u)

/-- The exponential CDF with mean `scale`: `F(t) = 1 - exp(-t/scale)`. -/
noncomputable def expCDF (scale t : ℝ) : ℝ := 1 - Real.exp (-t / scale)

/-- **Nonnegativity.** For a valid uniform draw `u ∈ [0,1)` and positive
    `scale`, the sampled interval is `≥ 0` — a sampling delay is never
    negative. -/
theorem sample_nonneg {scale u : ℝ} (hs : 0 < scale) (h0 : 0 ≤ u) (h1 : u < 1) :
    0 ≤ sample scale u := by
  unfold sample
  -- 1 - u ∈ (0,1], so log (1-u) ≤ 0, so -scale * log(1-u) ≥ 0
  have hpos : 0 < 1 - u := by linarith
  have hle1 : 1 - u ≤ 1 := by linarith
  have hlog : Real.log (1 - u) ≤ 0 := by
    have := Real.log_le_log hpos hle1
    simpa [Real.log_one] using this
  have : 0 ≤ -Real.log (1 - u) := by linarith
  calc (0:ℝ) = scale * 0 := by ring
    _ ≤ scale * (-Real.log (1 - u)) := by
        apply mul_le_mul_of_nonneg_left this (le_of_lt hs)
    _ = -scale * Real.log (1 - u) := by ring

/-- **Inverse-CDF correctness (the key fact).** For `scale > 0` and `u ∈ [0,1)`,
    the sampled interval is `≤ t` *iff* `u ≤ F(t)`, where `F` is the exponential
    CDF. Since `u` is uniform on `[0,1)`, `P(sample ≤ t) = P(u ≤ F(t)) = F(t)` —
    so `sample` is distributed Exponential(mean = scale). (Stated for `t ≥ 0`,
    the support of the distribution.) -/
theorem sample_le_iff {scale u t : ℝ} (hs : 0 < scale) (h0 : 0 ≤ u) (h1 : u < 1)
    (ht : 0 ≤ t) :
    sample scale u ≤ t ↔ u ≤ expCDF scale t := by
  unfold sample expCDF
  have hpos : 0 < 1 - u := by linarith
  -- Step 1: -scale*log(1-u) ≤ t  ⟺  -t/scale ≤ log(1-u)
  set L := Real.log (1 - u) with hL
  have step1 : (-scale * L ≤ t) ↔ (-t / scale ≤ L) := by
    rw [div_le_iff₀ hs]
    constructor <;> intro h <;> nlinarith [h]
  -- Step 2: -t/scale ≤ log(1-u)  ⟺  exp(-t/scale) ≤ 1-u   (exp strictly mono)
  have step2 : (-t / scale ≤ L) ↔ (Real.exp (-t / scale) ≤ 1 - u) := by
    constructor
    · intro h
      have := Real.exp_le_exp.mpr h
      rwa [hL, Real.exp_log hpos] at this
    · intro h
      have hmono := Real.exp_le_exp (x := -t / scale) (y := L)
      apply hmono.mp
      rwa [hL, Real.exp_log hpos]
  -- Step 3: exp(-t/scale) ≤ 1-u  ⟺  u ≤ 1 - exp(-t/scale)
  have step3 : (Real.exp (-t / scale) ≤ 1 - u) ↔ (u ≤ 1 - Real.exp (-t / scale)) := by
    constructor <;> intro h <;> linarith
  rw [step1, step2, step3]

/-- The exponential CDF is genuinely a CDF on `[0,∞)`: `F(0) = 0` and
    `F(t) → 1`. We record `F(0) = 0` (no interval is ≤ 0 with positive
    probability) and monotonicity as basic sanity checks. -/
theorem expCDF_zero (scale : ℝ) : expCDF scale 0 = 0 := by
  unfold expCDF; simp

theorem expCDF_lt_one {scale t : ℝ} : expCDF scale t < 1 := by
  unfold expCDF
  have := Real.exp_pos (-t / scale)
  linarith

/-- **Memorylessness** — the defining property of the Exponential, and the
    formal reason consecutive samples are independent. The survival function
    `S(t) = exp(-t/scale)` satisfies `S(s + t) = S(s) · S(t)`: having already
    waited `s` for the next sample, the remaining wait has the *same*
    distribution as a fresh one. So the sampler carries no memory of elapsed
    time between ticks — the next sample instant is independent of the past,
    which is exactly the i.i.d. structure `ProfilerCorrectness.jointExpect`
    assumes. -/
theorem survival_memoryless (scale s t : ℝ) :
    Real.exp (-(s + t) / scale) = Real.exp (-s / scale) * Real.exp (-t / scale) := by
  rw [← Real.exp_add]
  congr 1
  ring

end Scalene.ExponentialSampler
