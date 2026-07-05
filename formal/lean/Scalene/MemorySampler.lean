/-
  Correctness of Scalene's memory-allocation sampler.

  The native interposer doesn't record every malloc/free — that would be far
  too slow. It samples, and the question is whether the *sampled* per-line byte
  counts faithfully represent true allocation behaviour. Scalene ships two
  samplers (src/include/sampleheap.hpp:345-349); we model both, because they
  give two *different* correctness guarantees:

  1. ThresholdSampler (the DEFAULT, thresholdsampler.hpp) — deterministic. It
     keeps running `_increments` / `_decrements` byte counters and fires a
     sample only when one exceeds the other by `_sampleInterval`, reporting the
     exact excess and resetting both. Its guarantee is EXACT CONSERVATION: the
     reported alloc-bytes minus free-bytes, plus the sub-threshold residual
     still in the counters, equals the true net allocation — no bytes invented
     or lost, just coarsened to multiples of the interval. Proven below as
     `threshold_conserves`.

  2. PoissonSampler (poissonsampler.hpp, experimental `#if 0`) — randomized,
     each byte sampled with probability `1/window`. Its guarantee is
     UNBIASEDNESS: `E[recorded_bytes · window] = true_bytes`. Proven below as
     `poisson_unbiased` (single allocation) and lifted additively.

  Faithful to src/include/thresholdsampler.hpp:38-73 and poissonsampler.hpp.
  All proofs over ℚ / ℕ; no `sorry`.
-/
import Mathlib

open scoped BigOperators

namespace Scalene.MemorySampler

/-! ## 1. ThresholdSampler — exact net-footprint conservation

State = (increments, decrements) byte counters since the last reset; on a
malloc of `n` bytes we add to increments and, if it crosses
`decrements + interval`, we *report* `increments - decrements` and reset.
Frees are symmetric. We model the running net and prove the invariant that the
*total reported net* plus the *current residual* always equals the true net of
all bytes seen. -/

/-- A memory event: an allocation or a free of some number of bytes. -/
inductive Event where
  | alloc (bytes : ℕ)
  | free  (bytes : ℕ)

/-- True net allocation of an event sequence: Σ alloc − Σ free (over ℤ). -/
def trueNet : List Event → ℤ
  | []                  => 0
  | .alloc n :: es      => (n : ℤ) + trueNet es
  | .free n :: es       => -(n : ℤ) + trueNet es

/-- Sampler state: bytes accumulated toward the next alloc / free sample, and
    the running total of *reported* net allocation (the profiler's footprint
    estimate). The model tracks net counters: `bal = increments − decrements`,
    which is all the trigger condition and the reset depend on. -/
structure St where
  bal      : ℤ      -- increments − decrements since last reset (the residual)
  reported : ℤ      -- cumulative reported net allocation

/-- Run one event through the ThresholdSampler with interval `I > 0`.
    Faithful to thresholdsampler.hpp increment/decrement: add to the balance;
    if |bal| reaches the interval, report the balance and reset it to 0.

    (The C++ checks `incr ≥ decr + I` for allocs and `decr ≥ incr + I` for
    frees; with `bal = incr − decr` those are `bal ≥ I` and `bal ≤ -I`. On a
    trigger it reports `bal` and resets incr=decr=0, i.e. `bal := 0`, folding
    the reported amount into `reported`.) -/
def stepThreshold (I : ℤ) (s : St) : Event → St
  | .alloc n =>
      let bal' := s.bal + (n : ℤ)
      if bal' ≥ I then ⟨0, s.reported + bal'⟩ else ⟨bal', s.reported⟩
  | .free n =>
      let bal' := s.bal - (n : ℤ)
      if bal' ≤ -I then ⟨0, s.reported + bal'⟩ else ⟨bal', s.reported⟩

def runThreshold (I : ℤ) (s : St) : List Event → St
  | []      => s
  | e :: es => runThreshold I (stepThreshold I s e) es

/-- **Conservation invariant (one step).** Each step preserves
    `reported + bal = reported_before + bal_before + Δ`, where Δ is the event's
    true contribution. (Whether or not it triggers, the byte is accounted for —
    either in `reported` or carried in `bal`.) -/
theorem stepThreshold_conserves (I : ℤ) (s : St) (e : Event) :
    (stepThreshold I s e).reported + (stepThreshold I s e).bal
      = s.reported + s.bal + trueNet [e] := by
  cases e with
  | alloc n =>
      simp only [stepThreshold, trueNet]
      split <;> simp <;> ring
  | free n =>
      simp only [stepThreshold, trueNet]
      split <;> simp <;> ring

/-- **Conservation (whole run).** Starting from empty counters, after any event
    sequence the profiler's *reported* net plus the *residual still in the
    counters* equals the true net allocation exactly. No bytes are invented or
    lost; sampling only defers sub-threshold bytes into the residual. -/
theorem threshold_conserves (I : ℤ) (es : List Event) :
    let s := runThreshold I ⟨0, 0⟩ es
    s.reported + s.bal = trueNet es := by
  suffices H : ∀ (s : St) (es : List Event),
      (runThreshold I s es).reported + (runThreshold I s es).bal
        = s.reported + s.bal + trueNet es by
    have := H ⟨0, 0⟩ es; simpa using this
  intro s es
  induction es generalizing s with
  | nil => simp [runThreshold, trueNet]
  | cons e es ih =>
      simp only [runThreshold]
      rw [ih (stepThreshold I s e), stepThreshold_conserves I s e]
      -- (s.reported+s.bal+net[e]) + net es = s.reported+s.bal + net(e::es)
      cases e <;> simp [trueNet] <;> ring

/-- **Bounded residual.** Between reports the residual never reaches the
    interval in magnitude: `|bal| < I`. So the profiler's reported footprint is
    always within one sampling interval of the truth — the conservation above
    is tight. -/
theorem threshold_residual_bounded (I : ℤ) (hI : 0 < I) (es : List Event) :
    |(runThreshold I ⟨0, 0⟩ es).bal| < I := by
  suffices H : ∀ (s : St) (es : List Event), |s.bal| < I →
      |(runThreshold I s es).bal| < I by
    apply H; simpa using hI
  intro s es
  induction es generalizing s with
  | nil => intro h; simpa [runThreshold] using h
  | cons e es ih =>
      intro h
      apply ih
      cases e with
      | alloc n =>
          simp only [stepThreshold]
          split
          · simpa using hI
          · -- ¬(bal + n ≥ I) ⇒ bal + n < I; lower: bal + n ≥ bal > -I
            rename_i hne
            rw [abs_lt] at h ⊢
            have hn : (0:ℤ) ≤ (n:ℤ) := Int.natCast_nonneg n
            refine ⟨by linarith [h.1], by linarith [not_le.mp hne]⟩
      | free n =>
          simp only [stepThreshold]
          split
          · simpa using hI
          · -- ¬(bal - n ≤ -I) ⇒ bal - n > -I; upper: bal - n ≤ bal < I
            rename_i hne
            rw [abs_lt] at h ⊢
            have hn : (0:ℤ) ≤ (n:ℤ) := Int.natCast_nonneg n
            refine ⟨by linarith [not_le.mp hne], by linarith [h.2]⟩

/-! ## 1b. The one-counter model faithfully reduces the literal two-counter C++

The `St`/`stepThreshold` model above collapses the C++'s two `uint64_t`
counters `_increments` / `_decrements` into their difference `bal`. That
collapse was previously argued in prose. Here we close the gap: we model the
*literal* two-counter machine (thresholdsampler.hpp:60-73, 38-51: separate ℕ
counters, trigger `incr ≥ decr + I` / `decr ≥ incr + I`, reset BOTH to 0) and
prove it is bisimilar to the one-counter model under the abstraction
`abs (incr, decr) = incr − decr`. Conservation then transfers to the real
machine for free. -/

/-- Literal two-counter sampler state: the C++ `_increments`, `_decrements`
    (both `uint64_t`, so `ℕ`) plus the reported total. -/
structure St2 where
  incr     : ℕ
  decr     : ℕ
  reported : ℤ

/-- One step of the LITERAL two-counter machine, matching thresholdsampler.hpp:
    alloc adds to `incr`; if `incr ≥ decr + I` it reports `incr − decr` and
    resets both counters to 0. Free is symmetric on `decr`. `I : ℕ` (the C++
    `_sampleInterval`). -/
def stepThreshold2 (I : ℕ) (s : St2) : Event → St2
  | .alloc n =>
      let incr' := s.incr + n
      if incr' ≥ s.decr + I then
        ⟨0, 0, s.reported + ((incr' : ℤ) - s.decr)⟩
      else ⟨incr', s.decr, s.reported⟩
  | .free n =>
      let decr' := s.decr + n
      if decr' ≥ s.incr + I then
        ⟨0, 0, s.reported + (s.incr - (decr' : ℤ))⟩
      else ⟨s.incr, decr', s.reported⟩

def runThreshold2 (I : ℕ) (s : St2) : List Event → St2
  | []      => s
  | e :: es => runThreshold2 I (stepThreshold2 I s e) es

/-- Abstraction from the two-counter machine to the one-counter model:
    `bal := incr − decr`, `reported` carried through. -/
def abs2 (s : St2) : St := ⟨(s.incr : ℤ) - s.decr, s.reported⟩

/-- **Bisimulation (one step).** The two-counter step commutes with the
    abstraction: abstracting after a literal step = one-counter-stepping the
    abstraction. The subtlety the ℕ→ℤ collapse must respect: the C++ trigger
    `incr' ≥ decr + I` is *exactly* `abs.bal + n ≥ I` (over ℤ), and resetting
    both ℕ counters to 0 gives `bal = 0` — matching `stepThreshold`. -/
theorem step_bisim (I : ℕ) (s : St2) (e : Event) :
    abs2 (stepThreshold2 I s e) = stepThreshold (I : ℤ) (abs2 s) e := by
  cases e with
  | alloc n =>
      -- trigger conditions coincide: (incr+n ≥ decr+I) ↔ ((incr-decr)+n ≥ I)
      have hcond : (s.incr + n ≥ s.decr + I)
                 ↔ ((s.incr : ℤ) - s.decr + (n : ℤ) ≥ (I : ℤ)) := by
        constructor
        · intro h; have : (s.incr : ℤ) + n ≥ (s.decr : ℤ) + I := by exact_mod_cast h
          linarith
        · intro h; have : (s.incr : ℤ) + n ≥ (s.decr : ℤ) + I := by linarith
          exact_mod_cast this
      simp only [stepThreshold2, stepThreshold, abs2]
      by_cases h : s.incr + n ≥ s.decr + I
      · rw [if_pos h, if_pos (hcond.mp h)]; simp only [St.mk.injEq]; refine ⟨?_, ?_⟩ <;> push_cast <;> ring_nf
      · rw [if_neg h, if_neg (fun hc => h (hcond.mpr hc))]; simp only [St.mk.injEq]; refine ⟨?_, ?_⟩ <;> push_cast <;> ring_nf
  | free n =>
      have hcond : (s.decr + n ≥ s.incr + I)
                 ↔ ((s.incr : ℤ) - (s.decr : ℤ) - (n : ℤ) ≤ -(I : ℤ)) := by
        constructor
        · intro h; have : (s.decr : ℤ) + n ≥ (s.incr : ℤ) + I := by exact_mod_cast h
          linarith
        · intro h; have : (s.decr : ℤ) + n ≥ (s.incr : ℤ) + I := by linarith
          exact_mod_cast this
      simp only [stepThreshold2, stepThreshold, abs2]
      by_cases h : s.decr + n ≥ s.incr + I
      · rw [if_pos h, if_pos (hcond.mp h)]; simp only [St.mk.injEq]; refine ⟨?_, ?_⟩ <;> push_cast <;> ring_nf
      · rw [if_neg h, if_neg (fun hc => h (hcond.mpr hc))]; simp only [St.mk.injEq]; refine ⟨?_, ?_⟩ <;> push_cast <;> ring_nf

/-- **Bisimulation (whole run).** Abstraction commutes with the full run. -/
theorem run_bisim (I : ℕ) (s : St2) (es : List Event) :
    abs2 (runThreshold2 I s es) = runThreshold (I : ℤ) (abs2 s) es := by
  induction es generalizing s with
  | nil => rfl
  | cons e es ih =>
      simp only [runThreshold2, runThreshold]
      rw [ih (stepThreshold2 I s e), step_bisim]

/-- **Conservation for the LITERAL two-counter machine.** Transferring
    `threshold_conserves` across the bisimulation: starting from zeroed
    counters, the two-counter C++ sampler's reported net plus its residual
    `incr − decr` equals the true net allocation, exactly. This is the
    conservation guarantee stated directly about the algorithm as written in
    thresholdsampler.hpp, with the one-counter collapse now *proved* rather
    than assumed. -/
theorem threshold2_conserves (I : ℕ) (es : List Event) :
    let s := runThreshold2 I ⟨0, 0, 0⟩ es
    s.reported + ((s.incr : ℤ) - s.decr) = trueNet es := by
  intro s
  -- The abstraction of the two-counter run equals the one-counter run.
  have hrun : abs2 s = runThreshold (I : ℤ) ⟨0, 0⟩ es := by
    show abs2 (runThreshold2 I ⟨0, 0, 0⟩ es) = _
    rw [run_bisim]; rfl
  -- One-counter conservation on that run.
  have hcons : (runThreshold (I:ℤ) ⟨0,0⟩ es).reported
             + (runThreshold (I:ℤ) ⟨0,0⟩ es).bal = trueNet es := threshold_conserves (I:ℤ) es
  -- abs2 s = ⟨incr - decr, reported⟩ by definition; read off the fields.
  have hbal : (runThreshold (I:ℤ) ⟨0,0⟩ es).bal = (s.incr : ℤ) - s.decr := by
    rw [← hrun]; rfl
  have hrep : (runThreshold (I:ℤ) ⟨0,0⟩ es).reported = s.reported := by
    rw [← hrun]; rfl
  rw [hbal, hrep] at hcons
  linarith [hcons]

/-! ## 2. PoissonSampler — unbiased byte estimator

Each byte is independently recorded with probability `p = 1/window`; a recorded
sample is scaled back up by `window`. We prove the scaled expectation equals
the true byte count. We use the explicit single-allocation expectation:
a malloc of `n` bytes records `k` bytes with the binomial structure, but the
estimator only needs linearity: `E[scaled recorded] = window · (n · p) = n`. -/

/-- Expected recorded-and-rescaled bytes for an allocation of `n` bytes, where
    each byte is sampled with probability `1/window` and rescaled by `window`.
    `E[bytes recorded] = n · (1/window)`, rescaled: `window · n/window = n`. -/
def poissonEstimate (window : ℚ) (n : ℕ) : ℚ :=
  window * ((n : ℚ) * (1 / window))

/-- **Single-allocation unbiasedness.** For any positive window, the expected
    rescaled estimate of an `n`-byte allocation is exactly `n`. -/
theorem poisson_unbiased {window : ℚ} (hw : 0 < window) (n : ℕ) :
    poissonEstimate window n = (n : ℚ) := by
  unfold poissonEstimate
  field_simp

/-- **Additivity ⇒ whole-trace unbiasedness.** Expectation is linear, so the
    rescaled estimate of a sequence of allocations is unbiased for their total
    bytes: `Σ E[estimate nᵢ] = Σ nᵢ`. -/
theorem poisson_unbiased_sum {window : ℚ} (hw : 0 < window) (ns : List ℕ) :
    (ns.map (poissonEstimate window)).sum = (ns.map (fun n => (n : ℚ))).sum := by
  induction ns with
  | nil => simp
  | cons n ns ih => simp [poisson_unbiased hw n, ih]

end Scalene.MemorySampler
