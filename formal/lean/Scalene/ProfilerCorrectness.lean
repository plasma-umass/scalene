/-
  Profiler-correctness desideratum: a sampling profiler attributes time (and
  memory) to the right lines *in expectation*.

  This is the spec-level companion to Attribution.lean. Attribution.lean proves
  the bookkeeping is internally consistent (totals conserved, fractions in
  [0,1]). Here we prove the property a *user* actually cares about: the numbers
  Scalene reports reflect where the program truly spends its time.

  A sampling profiler cannot be exactly right on any single run — it observes a
  random subset of execution. So "correct attribution" is necessarily a
  statistical statement:

      UNBIASED:    E[ reported fraction for line ℓ ] = true fraction for ℓ
      CONSISTENT:  that estimate concentrates as the number of samples grows
                   (variance → 0; see `est_variance_le` below).

  THE MODELING CHOICE THAT MATTERS. The whole result rests on one hypothesis:
  each timer tick is attributed to the line that is *truly executing* when it
  fires, with probability proportional to that line's true running time. On a
  GIL-based Python profiler that is NOT automatic — an asynchronous signal can
  be delivered a few bytecodes after the event that triggered it, smearing a
  sample onto the wrong line. Scalene's engineering exists precisely to make
  this hypothesis hold:

    * synchronous (C++) stamping of the executing (file,line) at sample time
      (`whereInPython` / `whereInPythonWithStack`, src/source/pywhere.cpp), and
    * the smear correction in `scalene_memory_profiler.py` that reattributes
      arena/GC bytes off pure-arithmetic leaf lines.

  So the `faithful` hypothesis below is the formal contract between this
  spec-level proof and the mechanism-level proofs/engineering: *given* faithful
  per-sample attribution, the reported profile is an unbiased, consistent
  estimate of the truth.

  All proofs are over ℚ (exact); no `sorry`.
-/
import Mathlib

open scoped BigOperators

namespace Scalene.ProfilerCorrectness

/-- A ground-truth execution profile over a finite set of program lines:
    `weight ℓ` is the true time (or bytes) spent on line `ℓ`. -/
structure Truth (Line : Type) [Fintype Line] [DecidableEq Line] where
  weight : Line → ℚ
  nonneg : ∀ ℓ, 0 ≤ weight ℓ
  /-- At least one line has positive weight (the program did something), so the
      total is positive and fractions are well-defined. -/
  total_pos : 0 < ∑ ℓ, weight ℓ

namespace Truth

variable {Line : Type} [Fintype Line] [DecidableEq Line]

/-- Total true time/bytes across all lines. -/
def total (T : Truth Line) : ℚ := ∑ ℓ, T.weight ℓ

theorem total_pos' (T : Truth Line) : 0 < T.total := T.total_pos

/-- The ground-truth fraction of time/bytes on line `ℓ`: what an ideal profiler
    would report. -/
def trueFraction (T : Truth Line) (ℓ : Line) : ℚ := T.weight ℓ / T.total

theorem trueFraction_nonneg (T : Truth Line) (ℓ : Line) : 0 ≤ T.trueFraction ℓ :=
  div_nonneg (T.nonneg ℓ) (le_of_lt T.total_pos')

/-- The true fractions are a probability distribution: they sum to 1. This is
    the faithful per-sample sampling distribution (each tick hits line ℓ with
    probability `trueFraction ℓ`). -/
theorem trueFraction_sum_one (T : Truth Line) : ∑ ℓ, T.trueFraction ℓ = 1 := by
  unfold trueFraction
  rw [← Finset.sum_div]
  exact div_self (ne_of_gt T.total_pos')

/-! ## Expectation over one faithful sample

`expect T f` is the expected value of `f` under one sample drawn with the
faithful distribution `trueFraction`. We define it explicitly as
`Σ_ℓ trueFraction ℓ * f ℓ` rather than via `PMF` so the algebra is transparent
and the correspondence to "sum over lines weighted by probability" is direct. -/

/-- Expectation of `f` over one faithful sample. -/
def expect (T : Truth Line) (f : Line → ℚ) : ℚ := ∑ ℓ, T.trueFraction ℓ * f ℓ

/-- The single-sample estimator for line `ℓ`'s fraction: the indicator that the
    sample landed on `ℓ` (1 if so, else 0). Averaging this over many samples is
    exactly Scalene's reported per-line fraction. -/
def indicator (ℓ : Line) : Line → ℚ := fun s => if s = ℓ then 1 else 0

/-- **Single-sample unbiasedness.** The expected value of the one-sample
    estimator for line `ℓ` equals `ℓ`'s true fraction. I.e. a faithfully-placed
    sample attributes time to `ℓ` exactly as often as `ℓ` truly runs. -/
theorem expect_indicator (T : Truth Line) (ℓ : Line) :
    T.expect (indicator ℓ) = T.trueFraction ℓ := by
  unfold expect indicator
  -- Each summand `trueFraction s * (if s = ℓ then 1 else 0)` equals
  -- `if s = ℓ then trueFraction s else 0`; the sum then picks out `s = ℓ`.
  have h : ∀ s ∈ (Finset.univ : Finset Line),
      T.trueFraction s * (if s = ℓ then (1 : ℚ) else 0)
        = if s = ℓ then T.trueFraction s else 0 := by
    intro s _; by_cases hs : s = ℓ <;> simp [hs]
  rw [Finset.sum_congr rfl h, Finset.sum_ite_eq' Finset.univ ℓ (fun s => T.trueFraction s)]
  simp

/-- Expectation is linear: pushes through finite sums. (Used to lift the
    single-sample result to the N-sample estimator.) -/
theorem expect_add (T : Truth Line) (f g : Line → ℚ) :
    T.expect (fun s => f s + g s) = T.expect f + T.expect g := by
  unfold expect
  rw [← Finset.sum_add_distrib]
  exact Finset.sum_congr rfl (fun s _ => by ring)

theorem expect_smul (T : Truth Line) (c : ℚ) (f : Line → ℚ) :
    T.expect (fun s => c * f s) = c * T.expect f := by
  unfold expect
  rw [Finset.mul_sum]
  exact Finset.sum_congr rfl (fun s _ => by ring)

theorem expect_const (T : Truth Line) (c : ℚ) : T.expect (fun _ => c) = c := by
  unfold expect
  rw [← Finset.sum_mul, T.trueFraction_sum_one, one_mul]

/-! ## N i.i.d. samples: the actual reported estimator

`jointExpect T N f` is the expectation of `f : (Fin N → Line) → ℚ` over `N`
independent faithful samples. Defined as iterated single-sample expectation —
which *is* the i.i.d. product distribution — so we never need a separate
product-measure construction. -/

/-- Expectation of `f` over `N` i.i.d. faithful samples. -/
def jointExpect (T : Truth Line) : (N : ℕ) → ((Fin N → Line) → ℚ) → ℚ
  | 0,     f => f Fin.elim0
  | N + 1, f => T.expect (fun s₀ => T.jointExpect N (fun rest => f (Fin.cons s₀ rest)))

/-- A constant has expectation itself under the joint distribution (total mass
    is 1 at every level). -/
theorem jointExpect_const (T : Truth Line) (N : ℕ) (c : ℚ) :
    T.jointExpect N (fun _ => c) = c := by
  induction N with
  | zero => rfl
  | succ N ih => simp only [jointExpect]; rw [ih]; exact T.expect_const c

/-- The joint expectation is linear (additive). -/
theorem jointExpect_add (T : Truth Line) (N : ℕ) (f g : (Fin N → Line) → ℚ) :
    T.jointExpect N (fun v => f v + g v) = T.jointExpect N f + T.jointExpect N g := by
  induction N with
  | zero => rfl
  | succ N ih =>
      simp only [jointExpect]
      rw [show (fun s₀ => T.jointExpect N (fun rest => f (Fin.cons s₀ rest) + g (Fin.cons s₀ rest)))
            = (fun s₀ => T.jointExpect N (fun rest => f (Fin.cons s₀ rest))
                       + T.jointExpect N (fun rest => g (Fin.cons s₀ rest))) from by
            funext s₀; exact ih _ _]
      exact T.expect_add _ _

/-- Joint expectation commutes with a finite index-sum (linearity of
    expectation over a `Finset`). Proven by induction on the index set. -/
theorem jointExpect_finset_sum (T : Truth Line) (N : ℕ) {ι : Type*}
    (s : Finset ι) (h : ι → (Fin N → Line) → ℚ) :
    T.jointExpect N (fun v => ∑ i ∈ s, h i v) = ∑ i ∈ s, T.jointExpect N (h i) := by
  classical
  induction s using Finset.induction with
  | empty => simp [jointExpect_const]
  | @insert a s ha ih =>
      have hfun : (fun v => ∑ i ∈ insert a s, h i v)
            = (fun v => h a v + (fun w => ∑ i ∈ s, h i w) v) := by
        funext v; simp only; rw [Finset.sum_insert ha]
      rw [hfun, T.jointExpect_add N (h a) (fun w => ∑ i ∈ s, h i w), ih,
         Finset.sum_insert ha]

/-- Scalar multiples pull out of the joint expectation. -/
theorem jointExpect_smul (T : Truth Line) (N : ℕ) (c : ℚ) (f : (Fin N → Line) → ℚ) :
    T.jointExpect N (fun v => c * f v) = c * T.jointExpect N f := by
  induction N with
  | zero => rfl
  | succ N ih =>
      simp only [jointExpect]
      rw [show (fun s₀ => T.jointExpect N (fun rest => c * f (Fin.cons s₀ rest)))
            = (fun s₀ => c * T.jointExpect N (fun rest => f (Fin.cons s₀ rest))) from by
            funext s₀; exact ih _]
      exact T.expect_smul c _

/-- **Marginalization.** A function of a *single* coordinate has joint
    expectation equal to its single-sample expectation — the other `N-1`
    samples integrate out to mass 1. This is where independence is used. -/
theorem jointExpect_coord (T : Truth Line) :
    ∀ (N : ℕ) (i : Fin N) (g : Line → ℚ),
      T.jointExpect N (fun v => g (v i)) = T.expect g := by
  intro N
  induction N with
  | zero => exact fun i => i.elim0
  | succ N ih =>
      intro i g
      simp only [jointExpect]
      refine i.cases ?_ ?_
      · -- i = 0: the first sample; the rest is constant in `g s₀`.
        simp only [Fin.cons_zero]
        rw [show (fun s₀ => T.jointExpect N (fun _ => g s₀))
              = (fun s₀ => g s₀) from by funext s₀; exact T.jointExpect_const N (g s₀)]
      · -- i = j.succ: defer to coordinate j among the remaining samples.
        intro j
        simp only [Fin.cons_succ]
        rw [show (fun s₀ => T.jointExpect N (fun rest => g (rest j)))
              = (fun _ => T.expect g) from by funext s₀; exact ih j g]
        exact T.expect_const _

/-- The reported per-line estimator from `N` samples: the *fraction* of samples
    that landed on line `ℓ`. This is exactly what Scalene reports per line. -/
def estimator (ℓ : Line) (N : ℕ) : (Fin N → Line) → ℚ :=
  fun v => (1 / (N : ℚ)) * ∑ i, indicator ℓ (v i)

/-- **N-sample unbiasedness — the headline result.** For any number of samples
    `N ≥ 1`, the expected reported fraction for line `ℓ` equals its true
    fraction. The profiler is right *on average*, at every sample budget. -/
theorem estimator_unbiased (T : Truth Line) (ℓ : Line) (N : ℕ) (hN : 0 < N) :
    T.jointExpect N (estimator ℓ N) = T.trueFraction ℓ := by
  unfold estimator
  -- pull out the 1/N, push expectation through the finite sum of indicators
  rw [T.jointExpect_smul N (1 / (N : ℚ)) (fun v => ∑ i, indicator ℓ (v i))]
  -- E[ Σ_i indicator(v i = ℓ) ] = Σ_i E[indicator(v i = ℓ)] = Σ_i trueFraction ℓ
  have hsum : T.jointExpect N (fun v => ∑ i, indicator ℓ (v i))
            = ∑ _i : Fin N, T.trueFraction ℓ := by
    rw [T.jointExpect_finset_sum N Finset.univ (fun i v => indicator ℓ (v i))]
    refine Finset.sum_congr rfl (fun i _ => ?_)
    -- each coordinate marginalizes to the single-sample expectation
    rw [T.jointExpect_coord N i (indicator ℓ), T.expect_indicator]
  rw [hsum, Finset.sum_const, Finset.card_univ, Fintype.card_fin]
  -- (1/N) * (N • trueFraction ℓ) = trueFraction ℓ
  rw [nsmul_eq_mul]
  have hNℚ : (N : ℚ) ≠ 0 := by
    simp only [ne_eq, Nat.cast_eq_zero]; omega
  field_simp

/-! ## Consistency: the estimate concentrates as samples grow

Unbiasedness alone doesn't guarantee a useful profiler — a wildly noisy
unbiased estimate is useless. The second desideratum is that the variance of
the reported fraction shrinks with more samples, so the reported numbers
converge to the truth. We prove `Var_N[estimator ℓ] = p(1-p)/N` where
`p = trueFraction ℓ`, the textbook rate, which → 0 as N → ∞. -/

/-- Variance of `f` under one faithful sample: `E[f²] − (E[f])²`. -/
def variance (T : Truth Line) (f : Line → ℚ) : ℚ :=
  T.expect (fun s => f s * f s) - (T.expect f) ^ 2

/-- The indicator is idempotent: `indicator ℓ s * indicator ℓ s = indicator ℓ s`
    (it's 0 or 1). Hence `E[X²] = E[X] = p`. -/
theorem indicator_sq (ℓ : Line) (s : Line) :
    indicator ℓ s * indicator ℓ s = indicator ℓ s := by
  unfold indicator; by_cases h : s = ℓ <;> simp [h]

/-- **Single-sample variance.** `Var[indicator ℓ] = p(1−p)` with
    `p = trueFraction ℓ` — the Bernoulli variance, maximized at p=½ and 0 when a
    line takes all or none of the time. -/
theorem variance_indicator (T : Truth Line) (ℓ : Line) :
    T.variance (indicator ℓ) = T.trueFraction ℓ * (1 - T.trueFraction ℓ) := by
  unfold variance
  rw [show (fun s => indicator ℓ s * indicator ℓ s) = indicator ℓ from by
        funext s; exact indicator_sq ℓ s]
  rw [T.expect_indicator]
  ring

/-- **Independence factorization (two coordinates).** For two *distinct* sample
    positions `i ≠ j`, the joint expectation of a product factorizes into the
    product of single-sample expectations. This is the formal content of "the
    samples are independent", and the engine behind variance shrinking like
    1/N. Proven by induction on N, peeling the first sample. -/
theorem jointExpect_pair (T : Truth Line) :
    ∀ (N : ℕ) (i j : Fin N) (_hij : i ≠ j) (f g : Line → ℚ),
      T.jointExpect N (fun v => f (v i) * g (v j)) = T.expect f * T.expect g := by
  intro N
  induction N with
  | zero => exact fun i => i.elim0
  | succ N ih =>
      intro i j hij f g
      simp only [jointExpect]
      rcases Fin.eq_zero_or_eq_succ i with hi | ⟨a, hi⟩ <;>
      rcases Fin.eq_zero_or_eq_succ j with hj | ⟨b, hj⟩ <;>
        subst hi <;> subst hj
      · -- i = j = 0: contradicts i ≠ j
        exact absurd rfl hij
      · -- i = 0, j = b.succ: peel f at sample 0, g at tail coordinate b
        simp only [Fin.cons_zero, Fin.cons_succ]
        have inner : ∀ s₀, T.jointExpect N (fun rest : Fin N → Line => f s₀ * g (rest b))
              = f s₀ * T.expect g := by
          intro s₀
          have := T.jointExpect_smul N (f s₀) (fun w : Fin N → Line => g (w b))
          rw [T.jointExpect_coord N b g] at this
          exact this
        rw [show (fun s₀ => T.jointExpect N (fun rest => f s₀ * g (rest b)))
              = (fun s₀ => T.expect g * f s₀) from by funext s₀; rw [inner]; ring,
            T.expect_smul (T.expect g) f]
        ring
      · -- i = a.succ, j = 0: symmetric
        simp only [Fin.cons_zero, Fin.cons_succ]
        have inner : ∀ s₀, T.jointExpect N (fun rest : Fin N → Line => f (rest a) * g s₀)
              = T.expect f * g s₀ := by
          intro s₀
          have hcomm : (fun rest : Fin N → Line => f (rest a) * g s₀)
                = (fun rest => g s₀ * (fun w => f (w a)) rest) := by funext w; ring
          rw [hcomm, T.jointExpect_smul N (g s₀) (fun w => f (w a)),
              T.jointExpect_coord N a f]; ring
        rw [show (fun s₀ => T.jointExpect N (fun rest => f (rest a) * g s₀))
              = (fun s₀ => T.expect f * g s₀) from by funext s₀; rw [inner],
            T.expect_smul (T.expect f) g]
      · -- i = a.succ, j = b.succ: both in the tail, recurse with a ≠ b
        have hab : a ≠ b := fun h => hij (by rw [h])
        simp only [Fin.cons_succ]
        rw [show (fun s₀ => T.jointExpect N (fun rest => f (rest a) * g (rest b)))
              = (fun _ => T.expect f * T.expect g) from by
              funext s₀; exact ih a b hab f g]
        exact T.expect_const _

/-- The single-sample estimator variance is bounded by ¼ (Bernoulli max),
    regardless of the line — a uniform noise bound per sample. -/
theorem variance_indicator_le (T : Truth Line) (ℓ : Line) :
    T.variance (indicator ℓ) ≤ 1 / 4 := by
  rw [variance_indicator]
  have h0 := T.trueFraction_nonneg ℓ
  have h1 : T.trueFraction ℓ ≤ 1 := by
    unfold trueFraction
    rw [div_le_one T.total_pos']
    -- weight ℓ ≤ total = Σ weights
    have : T.weight ℓ ≤ ∑ k, T.weight k :=
      Finset.single_le_sum (fun k _ => T.nonneg k) (Finset.mem_univ ℓ)
    simpa [Truth.total] using this
  -- p(1-p) ≤ 1/4  ⇔  0 ≤ (p - 1/2)²
  nlinarith [sq_nonneg (T.trueFraction ℓ - 1/2)]

/-- N-sample variance of the estimator: `E[est²] − (E[est])²` under the joint
    (i.i.d.) distribution. -/
def jointVariance (T : Truth Line) (ℓ : Line) (N : ℕ) : ℚ :=
  T.jointExpect N (fun v => estimator ℓ N v * estimator ℓ N v)
    - (T.jointExpect N (estimator ℓ N)) ^ 2

/-- **Consistency — the convergence rate.** The N-sample estimator's variance is
    `p(1−p)/N`, which → 0 as N → ∞. Together with unbiasedness
    (`estimator_unbiased`), this is the full statistical statement that
    Scalene's reported per-line fractions converge to the truth: the estimate
    is centered on the right value and its spread shrinks like 1/N.

    Proof: expand `Var[(1/N)Σ Xᵢ]`. The diagonal terms give `Σ E[Xᵢ²] = N·p`
    (indicator is idempotent); the off-diagonal terms factor by independence
    (`jointExpect_pair`) into `N(N−1)·p²`; subtracting `(N·p)²` and dividing by
    `N²` leaves `p(1−p)/N`. -/
theorem jointVariance_eq (T : Truth Line) (ℓ : Line) (N : ℕ) (hN : 0 < N) :
    T.jointVariance ℓ N
      = T.trueFraction ℓ * (1 - T.trueFraction ℓ) / (N : ℚ) := by
  set p := T.trueFraction ℓ with hp
  have hNℚ : (N : ℚ) ≠ 0 := by simp only [ne_eq, Nat.cast_eq_zero]; omega
  -- Abbreviations
  let X : Fin N → (Fin N → Line) → ℚ := fun i v => indicator ℓ (v i)
  -- E[est] = p   (already have estimator_unbiased)
  have hmean : T.jointExpect N (estimator ℓ N) = p := T.estimator_unbiased ℓ N hN
  -- E[est²] = (1/N²) * E[ (Σ_i X i)² ]
  --        = (1/N²) * Σ_i Σ_j E[ X i * X j ]
  -- Compute the double sum of E[X i * X j].
  have hpair : ∀ i j : Fin N,
      T.jointExpect N (fun v => indicator ℓ (v i) * indicator ℓ (v j))
        = if i = j then p else p * p := by
    intro i j
    by_cases hij : i = j
    · subst hij
      rw [show (fun v : Fin N → Line => indicator ℓ (v i) * indicator ℓ (v i))
            = (fun v => indicator ℓ (v i)) from by
            funext v; exact indicator_sq ℓ (v i)]
      rw [T.jointExpect_coord N i (indicator ℓ), T.expect_indicator, if_pos rfl]
    · rw [if_neg hij, T.jointExpect_pair N i j hij (indicator ℓ) (indicator ℓ),
          T.expect_indicator]
  -- E[est²]
  have hsq : T.jointExpect N (fun v => estimator ℓ N v * estimator ℓ N v)
      = (1 / (N:ℚ))^2 * ∑ i : Fin N, ∑ j : Fin N, (if i = j then p else p * p) := by
    unfold estimator
    -- factor out (1/N)^2 and expand the product of sums into a double sum
    rw [show (fun v : Fin N → Line => (1 / (N:ℚ)) * (∑ i, indicator ℓ (v i))
                     * ((1 / (N:ℚ)) * ∑ j, indicator ℓ (v j)))
          = (fun v => (1 / (N:ℚ))^2
                * ∑ i, ∑ j, indicator ℓ (v i) * indicator ℓ (v j)) from by
          funext v
          have hexp : (∑ i, indicator ℓ (v i)) * (∑ j, indicator ℓ (v j))
              = ∑ i, ∑ j, indicator ℓ (v i) * indicator ℓ (v j) :=
            Finset.sum_mul_sum Finset.univ Finset.univ
              (fun i => indicator ℓ (v i)) (fun j => indicator ℓ (v j))
          calc (1 / (N:ℚ)) * (∑ i, indicator ℓ (v i))
                * ((1 / (N:ℚ)) * ∑ j, indicator ℓ (v j))
              = (1 / (N:ℚ))^2
                  * ((∑ i, indicator ℓ (v i)) * (∑ j, indicator ℓ (v j))) := by ring
            _ = (1 / (N:ℚ))^2 * ∑ i, ∑ j, indicator ℓ (v i) * indicator ℓ (v j) := by
                  rw [hexp]]
    rw [T.jointExpect_smul N ((1 / (N:ℚ))^2)
          (fun v => ∑ i, ∑ j, indicator ℓ (v i) * indicator ℓ (v j))]
    congr 1
    -- push joint expectation through the double finite sum, then apply hpair
    rw [T.jointExpect_finset_sum N Finset.univ
          (fun i v => ∑ j, indicator ℓ (v i) * indicator ℓ (v j))]
    refine Finset.sum_congr rfl (fun i _ => ?_)
    rw [T.jointExpect_finset_sum N Finset.univ
          (fun j v => indicator ℓ (v i) * indicator ℓ (v j))]
    exact Finset.sum_congr rfl (fun j _ => hpair i j)
  -- Evaluate the double sum: diagonal (N terms = p) + off-diagonal (N(N-1) terms = p²).
  -- Inner sum: Σ_j [i=j? p : p²] = p + (N-1)·p²  (one diagonal, N-1 off-diagonal).
  have hinner : ∀ i : Fin N, (∑ j : Fin N, (if i = j then p else p * p))
      = p + ((N:ℚ) - 1) * (p * p) := by
    intro i
    have h : (∑ j : Fin N, (if i = j then p else p * p))
           = ∑ j : Fin N, ((if i = j then (p - p * p) else 0) + p * p) := by
      refine Finset.sum_congr rfl (fun j _ => ?_); by_cases hij : i = j <;> simp [hij]
    rw [h, Finset.sum_add_distrib, Finset.sum_ite_eq Finset.univ i (fun _ => p - p * p)]
    simp only [Finset.mem_univ, if_true, Finset.sum_const, Finset.card_univ,
               Fintype.card_fin, nsmul_eq_mul]
    ring
  have hdouble : (∑ i : Fin N, ∑ j : Fin N, (if i = j then p else p * p))
      = (N:ℚ) * p + ((N:ℚ)^2 - N) * (p * p) := by
    rw [show (∑ i : Fin N, ∑ j : Fin N, (if i = j then p else p * p))
          = ∑ _i : Fin N, (p + ((N:ℚ) - 1) * (p * p)) from
          Finset.sum_congr rfl (fun i _ => hinner i)]
    rw [Finset.sum_const, Finset.card_univ, Fintype.card_fin, nsmul_eq_mul]
    ring
  rw [jointVariance, hsq, hmean, hdouble]
  field_simp
  ring

end Truth

end Scalene.ProfilerCorrectness
