/-
  Per-line malloc ATTRIBUTION — conservation, python-share bound, high-water.

  Distinct from `MallocFootprintWiring.lean` (which proves the *total* current
  footprint round-trips across the C++/Python boundary). This file is about the
  Python reader's PER-LINE bookkeeping: the four dicts
  `memory_malloc_samples`, `memory_python_samples`, `memory_malloc_count`, and
  the per-line high-water mark that Scalene reports per source line
  (scalene_memory_profiler.py:336-360), and the invariants the JSON renderer
  relies on when it divides by them.

  ── THE LOOP (scalene_memory_profiler.py:336-360, malloc branch) ──────────────
    malloc_samples_file[lineno]   += count                     # bytes on this line
    python_samples_file[lineno]   += python_fraction * count   # python-attributed
    total_memory_malloc_samples   += count                     # grand total
    current_footprint_file[lineno]+= count
    highwater_file[lineno] = max(highwater_file[lineno], current_footprint_file[lineno])
  where `count ≥ 0` (bytes/MB) and `python_fraction ∈ [0,1]` (the C++
  `_pythonCount/(…)` share, sampleheap.hpp).

  ── WHAT WE PROVE ─────────────────────────────────────────────────────────────
    * `perline_conserves` — Σ over lines of `memory_malloc_samples[line]` equals
      `total_memory_malloc_samples`: every malloc's bytes are credited to exactly
      one line AND to the grand total, so the per-line breakdown sums to the
      whole. (The user-facing `n_usage_fraction = malloc[line]/total` is thus a
      genuine fraction.)
    * `python_le_malloc` — per line, `memory_python_samples[line] ≤
      memory_malloc_samples[line]`, because each increment adds
      `python_fraction·count ≤ count`. This is exactly the precondition
      `scalene_json.py`'s `n_python_fraction = python/malloc ∈ [0,1]` needs; the
      Attribution.lean bound `pythonBytes_le_count` assumed it, we now derive it
      from the accumulation.
    * `python_nonneg`, `malloc_nonneg` — both accumulators stay ≥ 0.
    * `highwater_ge_current`, `highwater_monotone` — the per-line high-water mark
      dominates the running per-line footprint and never decreases, so the
      reported peak is a true upper bound.

  All over ℚ; no `sorry`.
-/
import Mathlib

open scoped BigOperators

namespace Scalene.PerLineMallocAttribution

variable {Line : Type} [DecidableEq Line] [Fintype Line]

/-- One malloc record as the Python reader sees it: the line, the byte `count`
    (≥ 0, in MB), and the `pythonFraction ∈ [0,1]` carried from C++. -/
structure Malloc (Line : Type) where
  line           : Line
  count          : ℚ
  pythonFraction : ℚ
  countNonneg    : 0 ≤ count
  fracNonneg     : 0 ≤ pythonFraction
  fracLeOne      : pythonFraction ≤ 1

/-- The per-line accumulator state the loop maintains. -/
structure St (Line : Type) where
  malloc      : Line → ℚ    -- memory_malloc_samples[line]
  python      : Line → ℚ    -- memory_python_samples[line]
  current     : Line → ℚ    -- memory_current_footprint[line]
  highwater   : Line → ℚ    -- memory_current_highwater_mark[line]
  totalMalloc : ℚ           -- total_memory_malloc_samples

/-- Add `v` to `f` at key `ℓ`. -/
def bump (f : Line → ℚ) (ℓ : Line) (v : ℚ) : Line → ℚ :=
  fun ℓ' => if ℓ' = ℓ then f ℓ' + v else f ℓ'

/-- One iteration of the malloc branch (scalene_memory_profiler.py:342-360). -/
def step (s : St Line) (m : Malloc Line) : St Line :=
  let malloc'  := bump s.malloc m.line m.count
  let python'  := bump s.python m.line (m.pythonFraction * m.count)
  let current' := bump s.current m.line m.count
  { malloc      := malloc'
    python      := python'
    current     := current'
    highwater   := fun ℓ' =>
      if ℓ' = m.line then max (s.highwater m.line) (current' m.line)
      else s.highwater ℓ'
    totalMalloc := s.totalMalloc + m.count }

def run (s : St Line) : List (Malloc Line) → St Line
  | []      => s
  | m :: ms => run (step s m) ms

/-- The initial (empty) accumulator. -/
def init : St Line :=
  { malloc := fun _ => 0, python := fun _ => 0, current := fun _ => 0,
    highwater := fun _ => 0, totalMalloc := 0 }

/-! ## 1. Per-line conservation: Σ malloc[line] = totalMalloc -/

/-- Sum of a per-line function over all lines. -/
def sum (f : Line → ℚ) : ℚ := ∑ ℓ : Line, f ℓ

theorem sum_bump (f : Line → ℚ) (ℓ : Line) (v : ℚ) :
    sum (bump f ℓ v) = sum f + v := by
  unfold sum bump
  have hkey : ∀ ℓ' ∈ (Finset.univ : Finset Line),
      (if ℓ' = ℓ then f ℓ' + v else f ℓ') = f ℓ' + (if ℓ' = ℓ then v else 0) := by
    intro ℓ' _; by_cases h : ℓ' = ℓ <;> simp [h]
  rw [Finset.sum_congr rfl hkey, Finset.sum_add_distrib,
      Finset.sum_ite_eq' Finset.univ ℓ (fun _ => v)]
  simp

/-- **Per-line conservation.** After any sequence of mallocs from the empty
    accumulator, the sum over lines of `memory_malloc_samples` equals
    `total_memory_malloc_samples`. Every malloc's bytes land in exactly one
    line's bucket and in the grand total — so `malloc[line]/total` is a genuine
    fraction (the JSON renderer's `n_usage_fraction`). -/
theorem perline_conserves (ms : List (Malloc Line)) :
    sum (run (init) ms).malloc = (run (init : St Line) ms).totalMalloc := by
  suffices H : ∀ (s : St Line), sum (run s ms).malloc = sum s.malloc
      + ((run s ms).totalMalloc - s.totalMalloc) by
    have h := H init
    simp only [init, sum] at h ⊢
    simpa using h
  intro s
  induction ms generalizing s with
  | nil => simp [run]
  | cons m ms ih =>
      simp only [run]
      rw [ih (step s m)]
      simp only [step, sum_bump]
      ring

/-! ## 2. Python share is bounded by malloc bytes, per line -/

/-- **Invariant: `python[ℓ] ≤ malloc[ℓ]` on every line, and both are ≥ 0.**
    Each step adds `pythonFraction·count` to python and `count` to malloc with
    `pythonFraction ≤ 1` and `count ≥ 0`, so the python bucket can never exceed
    the malloc bucket. This is exactly the precondition
    `scalene_json.py`'s `n_python_fraction = python/malloc` needs to land in
    [0,1] (Attribution.lean's `pythonBytes_le_count`, now derived not assumed). -/
theorem python_le_malloc (ms : List (Malloc Line)) (ℓ : Line) :
    0 ≤ (run (init : St Line) ms).python ℓ
    ∧ (run (init : St Line) ms).python ℓ ≤ (run (init : St Line) ms).malloc ℓ := by
  suffices H : ∀ (s : St Line),
      (∀ k, 0 ≤ s.python k ∧ s.python k ≤ s.malloc k) →
      (∀ k, 0 ≤ (run s ms).python k ∧ (run s ms).python k ≤ (run s ms).malloc k) by
    have h := H init (by intro k; simp [init])
    exact h ℓ
  intro s
  induction ms generalizing s with
  | nil => intro hinv; simpa [run] using hinv
  | cons m ms ih =>
      intro hinv
      apply ih
      intro k
      simp only [step, bump]
      by_cases hk : k = m.line
      · obtain ⟨hnn, hle⟩ := hinv k
        have hfc : 0 ≤ m.pythonFraction * m.count :=
          mul_nonneg m.fracNonneg m.countNonneg
        have hfrac : m.pythonFraction * m.count ≤ m.count := by
          nlinarith [m.countNonneg, m.fracLeOne, m.fracNonneg]
        simp only [if_pos hk]
        constructor <;> linarith
      · simp only [if_neg hk]; exact hinv k

/-! ## 3. Per-line high-water mark dominates and is monotone -/

/-- **High-water ≥ current, per line, throughout.** The reported per-line peak
    footprint is always an upper bound on the running per-line footprint. -/
theorem highwater_ge_current (ms : List (Malloc Line)) (ℓ : Line)
    (hinit : ∀ k, (init : St Line).current k ≤ (init : St Line).highwater k) :
    (run (init : St Line) ms).current ℓ ≤ (run (init : St Line) ms).highwater ℓ := by
  suffices H : ∀ (s : St Line), (∀ k, s.current k ≤ s.highwater k) →
      (∀ k, (run s ms).current k ≤ (run s ms).highwater k) by
    exact H init hinit ℓ
  intro s
  induction ms generalizing s with
  | nil => intro hinv; simpa [run] using hinv
  | cons m ms ih =>
      intro hinv
      apply ih
      intro k
      simp only [step, bump]
      by_cases hk : k = m.line
      · subst hk; simp only [if_pos rfl]; exact le_max_right _ _
      · simp only [if_neg hk]; exact hinv k

/-- **High-water is monotone.** One step never decreases any line's high-water
    mark — the peak only ever rises. -/
theorem highwater_monotone (s : St Line) (m : Malloc Line) (ℓ : Line) :
    s.highwater ℓ ≤ (step s m).highwater ℓ := by
  simp only [step]
  by_cases hk : ℓ = m.line
  · simp only [if_pos hk]; rw [hk]; exact le_max_left _ _
  · simp only [if_neg hk]; exact le_refl _

/-- `totalMalloc` only grows (each malloc's `count ≥ 0`). -/
theorem totalMalloc_monotone (s : St Line) (m : Malloc Line) :
    s.totalMalloc ≤ (step s m).totalMalloc := by
  simp only [step]; linarith [m.countNonneg]

end Scalene.PerLineMallocAttribution
