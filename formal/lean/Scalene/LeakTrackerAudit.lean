/-
  AUDIT: does the leak detector's divide-by-zero-safety actually hold in the
  code, or did MetricCorrectness.lean assume it away?

  MetricCorrectness models the leak score with `unfreed, frees : ℕ` and
  `allocs = unfreed + frees`, which *hardcodes* `frees ≤ allocs`. But the
  Python computes (scalene_leak_analysis.py:31)

      expected_leak = 1.0 - (frees + 1) / (allocs - frees + 2)

  with NO guard on the denominator, over two counters incremented at *separate*
  sites (scalene_memory_profiler.py:401 `allocs += 1`, :236 `frees += 1`). If
  `frees` could reach `allocs + 2`, the denominator is ≤ 0 → division by zero or
  a negative "probability". So the model's `frees ≤ allocs` assumption is a
  genuine *safety contract* that must be discharged from the actual increment
  discipline, not assumed. This file models the raw two-counter tracker and
  proves (or would refute) that contract.

  THE INCREMENT DISCIPLINE (from the code):
    * A malloc that pushes a new peak footprint arms `last_malloc_triggered` to
      that line AND does `allocs += 1` for it (memory_profiler.py:398-401) — the
      two happen together, same line.
    * When that armed trigger is later freed, `frees += 1` is credited to the
      armed line, and the trigger is IMMEDIATELY disarmed (:236, :237-241).
    * `frees += 1` only fires while a trigger is armed (`this_ln != 0`, :234).

  So per line, a `free` credit is always preceded by an `alloc` credit that
  armed the trigger, and the trigger is single-shot (disarmed on free). We model
  exactly this and prove `frees ≤ allocs` per line — hence `allocs−frees+2 ≥ 2 >
  0`, so the production formula is divide-by-zero-safe.
-/
import Mathlib

namespace Scalene.LeakTrackerAudit

/-- Per-line leak counters, as stored in `leak_score[fn][ln]`. -/
structure Counts where
  allocs : ℕ
  frees  : ℕ

/-- Global tracker state: the per-line counts, and the single armed trigger
    line (`none` = disarmed, i.e. the code's `last_malloc_triggered.ln == 0`). -/
structure Tracker (Line : Type) where
  count : Line → Counts
  armed : Option Line

/-- The events that drive the counters, mirroring the two code sites. -/
inductive Ev (Line : Type) where
  | allocPeak (ℓ : Line)   -- a malloc pushed a new peak on line ℓ (:398-401)
  | freeTrigger            -- the armed trigger was freed (:230-241)
  | other                  -- any malloc/free that doesn't touch leak_score

variable {Line : Type} [DecidableEq Line]

/-- One step of the raw tracker, faithful to the code:
    - allocPeak ℓ: `allocs[ℓ] += 1` and arm the trigger to ℓ.
    - freeTrigger: if armed at ℓ, `frees[ℓ] += 1` and disarm; else no-op.
    - other: unchanged. -/
def step (t : Tracker Line) : Ev Line → Tracker Line
  | .allocPeak ℓ =>
      { count := fun k => if k = ℓ then ⟨(t.count k).allocs + 1, (t.count k).frees⟩
                          else t.count k,
        armed := some ℓ }
  | .freeTrigger =>
      match t.armed with
      | some ℓ =>
          { count := fun k => if k = ℓ then ⟨(t.count k).allocs, (t.count k).frees + 1⟩
                              else t.count k,
            armed := none }
      | none => t
  | .other => t

def run (t : Tracker Line) : List (Ev Line) → Tracker Line
  | []      => t
  | e :: es => run (step t e) es

/-- The safety invariant we need: per line `frees ≤ allocs`, AND the armed line
    (if any) has strictly more allocs than frees — it is "owed" a free. The
    second conjunct is the strengthening that makes the induction go through:
    an armed trigger guarantees room for the free it will receive. -/
def Inv (t : Tracker Line) : Prop :=
  (∀ ℓ, (t.count ℓ).frees ≤ (t.count ℓ).allocs) ∧
  (∀ ℓ, t.armed = some ℓ → (t.count ℓ).frees < (t.count ℓ).allocs)

/-- The initial (empty) tracker satisfies the invariant. -/
theorem inv_init : Inv (Line := Line) ⟨fun _ => ⟨0, 0⟩, none⟩ := by
  constructor
  · intro ℓ; simp
  · intro ℓ h; simp at h

/-- **The invariant is preserved by every event.** This is the heart of the
    audit: from the actual increment discipline, `frees ≤ allocs` can never be
    violated. -/
theorem step_preserves_inv (t : Tracker Line) (e : Ev Line) (h : Inv t) :
    Inv (step t e) := by
  obtain ⟨hle, harm⟩ := h
  cases e with
  | allocPeak ℓ =>
      constructor
      · -- frees ≤ allocs after allocs[ℓ]++ : untouched lines unchanged; ℓ gains an alloc
        intro k
        simp only [step]
        by_cases hk : k = ℓ
        · rw [if_pos hk]; have := hle k; simp only; omega
        · rw [if_neg hk]; exact hle k
      · -- newly armed line ℓ now has allocs+1 > frees (since frees ≤ allocs before)
        intro k hk
        simp only [step] at hk ⊢
        -- armed = some ℓ, so k = ℓ
        rw [Option.some.injEq] at hk
        subst hk
        have hb := hle ℓ
        simp only [if_true, ite_true]
        omega
  | freeTrigger =>
      cases harmed : t.armed with
      | none => simpa [step, harmed] using ⟨hle, harm⟩
      | some ℓ =>
          -- ℓ is armed ⇒ frees[ℓ] < allocs[ℓ]; after frees[ℓ]++, still ≤; disarmed.
          have hstrict := harm ℓ harmed
          constructor
          · intro k
            simp only [step, harmed]
            by_cases hk : k = ℓ
            · subst hk; simp; omega
            · simp [hk]; exact hle k
          · intro k hk
            simp only [step, harmed] at hk
            -- armed is now none, contradiction
            exact absurd hk (by simp)
  | other => simpa [step] using ⟨hle, harm⟩

/-- **Whole-run safety.** After ANY sequence of events from the empty tracker,
    every line satisfies `frees ≤ allocs`. -/
theorem run_frees_le_allocs (es : List (Ev Line)) (ℓ : Line) :
    ((run (⟨fun _ => ⟨0, 0⟩, none⟩ : Tracker Line) es).count ℓ).frees
      ≤ ((run ⟨fun _ => ⟨0, 0⟩, none⟩ es).count ℓ).allocs := by
  have : Inv (run (⟨fun _ => ⟨0, 0⟩, none⟩ : Tracker Line) es) := by
    have hstep : ∀ (t : Tracker Line) (es : List (Ev Line)), Inv t → Inv (run t es) := by
      intro t es
      induction es generalizing t with
      | nil => intro h; simpa [run] using h
      | cons e es ih => intro h; simp only [run]; exact ih _ (step_preserves_inv t e h)
    exact hstep _ es inv_init
  exact this.1 ℓ

/-- **Therefore the production formula is divide-by-zero-safe.** With the counts
    reachable by the real tracker, `allocs − frees + 2 ≥ 2 > 0`, so
    `scalene_leak_analysis.py:31`'s unguarded denominator is always positive and
    the score is a genuine value in the range MetricCorrectness proves. -/
theorem denom_pos_reachable (es : List (Ev Line)) (ℓ : Line) :
    let c := (run (⟨fun _ => ⟨0, 0⟩, none⟩ : Tracker Line) es).count ℓ
    (0 : ℤ) < (c.allocs : ℤ) - (c.frees : ℤ) + 2 := by
  intro c
  have h := run_frees_le_allocs es ℓ
  have : (c.frees : ℤ) ≤ (c.allocs : ℤ) := by exact_mod_cast h
  linarith

end Scalene.LeakTrackerAudit
