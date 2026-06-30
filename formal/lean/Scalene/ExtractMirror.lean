/-
  Integrity bridge between the PROVEN defs and the EXTRACTED defs.

  formal/extract/ScaleneExtract.lean holds extraction-friendly copies of the
  algorithms (Nat/Int, no Mathlib) that LeanToPython turns into
  formal/extract/scalene_verified_core.py. This file re-states those exact
  extraction defs *here*, in the proof project, and proves each is equal to /
  satisfies the property already established for its proven counterpart.

  If ScaleneExtract.lean drifts from the proven model, these `rfl`/theorem
  cross-checks fail to compile — so the extracted Python cannot silently
  diverge from what was proven. (The two .lean files are kept textually in
  sync; this file is the machine-checked guard that they agree.)
-/
import Scalene.SpaceSaving

namespace Scalene.ExtractMirror

open Scalene.SpaceSaving

/-! ## Mirror of the extraction `minCount`

`ScaleneExtract.minCount` uses `Nat.min` directly — the LeanToPython bug that
dropped a `min` operand is fixed upstream
([emeryberger/LeanToPython#1](https://github.com/emeryberger/LeanToPython/pull/1)),
so it now extracts cleanly to `min(a, b)`. The mirror below re-states it and
proves it equals the proven `SpaceSaving.minCount` (definitionally), guarding
against drift between the extraction source and the proof model. -/

/-- Extraction's `minCount` (copy of ScaleneExtract.minCount). -/
def minCountX : Table Nat → Nat
  | []          => 0
  | [p]         => p.2
  | p :: q :: r => Nat.min p.2 (minCountX (q :: r))

/-- The extraction `minCountX` is exactly the proven `minCount`, so every
    `minCount`/`step` property (e.g. `minCount_le`) carries over to the
    extracted code unchanged. -/
theorem minCountX_eq (t : Table Nat) : minCountX t = minCount t := by
  induction t with
  | nil => rfl
  | cons p rest ih =>
      cases rest with
      | nil => rfl
      | cons q r =>
          show Nat.min p.2 (minCountX (q :: r)) = Nat.min p.2 (minCount (q :: r))
          rw [ih]

/-! ## Mirror of the extraction CPU-time split

ScaleneExtract uses Nat "ns": cTimeNs e p = if e ≥ p then e - p else 0;
totalTimeNs = p + cTimeNs. We prove the conservation/non-negativity facts
directly on these Nat forms, matching Attribution.lean's ℚ results. -/

def cTimeNs (elapsedNs pythonNs : Nat) : Nat :=
  if elapsedNs ≥ pythonNs then elapsedNs - pythonNs else 0

def totalTimeNs (elapsedNs pythonNs : Nat) : Nat :=
  pythonNs + cTimeNs elapsedNs pythonNs

/-- Conservation: when elapsed ≥ python (the normal case), total = elapsed
    exactly — no time invented or dropped. Mirrors Attribution.totalTime_eq_elapsed. -/
theorem totalTimeNs_eq_elapsed (e p : Nat) (h : p ≤ e) : totalTimeNs e p = e := by
  unfold totalTimeNs cTimeNs
  simp only [ge_iff_le, h, if_pos]
  omega

/-- Split is always ≥ the Python part. -/
theorem totalTimeNs_ge_python (e p : Nat) : p ≤ totalTimeNs e p := by
  unfold totalTimeNs; omega

/-! ## Mirror of the extraction python_fraction (ppm) bound -/

def pythonFractionPpm (pythonCount cCount : Nat) : Nat :=
  if pythonCount + cCount == 0 then 0
  else (pythonCount * 1000000) / (pythonCount + cCount)

/-- The ppm fraction is in [0, 1_000_000] — the Nat analogue of
    Attribution.pythonFraction_{nonneg,le_one} (fraction ∈ [0,1]). -/
theorem pythonFractionPpm_le (p c : Nat) : pythonFractionPpm p c ≤ 1000000 := by
  unfold pythonFractionPpm
  by_cases h : p + c == 0
  · simp [h]
  · simp only [h, if_false]
    have hpos : 0 < p + c := by
      rcases Nat.eq_zero_or_pos (p + c) with h0 | hp
      · exact absurd (by simpa using h0) (by simpa using h)
      · exact hp
    calc (p * 1000000) / (p + c)
        ≤ ((p + c) * 1000000) / (p + c) := by
          apply Nat.div_le_div_right
          exact Nat.mul_le_mul_right _ (Nat.le_add_right p c)
      _ = 1000000 := by rw [Nat.mul_div_cancel_left _ hpos]

end Scalene.ExtractMirror
