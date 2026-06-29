/-
  Extraction-facing copies of the *computational* cores that
  formal/lean/Scalene/{Attribution,SpaceSaving}.lean prove correct.

  These defs are byte-for-byte the same algorithms whose properties are proven
  in the main formal project (which is on Lean 4.31 + Mathlib). LeanToPython is
  pinned to Lean 4.12 and Batteries-only, so we cannot import the Mathlib proof
  project here. Instead we keep this small mirror in the extraction-friendly
  fragment (Nat / Int / List, no Mathlib in the bodies) and emit Python from it.

  The link to the proofs is by *definitional identity*: each def below is
  identical to its proven counterpart, asserted by the `theorem … := rfl`
  cross-checks in formal/lean/Scalene/ExtractMirror.lean (built under 4.31), so
  if the two ever drift the proof project fails to compile. The Python that
  LeanToPython emits from these defs therefore inherits the proven properties:
    * cTime / totalTime  — Python/C split conservation, non-negativity
    * pythonFraction      — result in [0,1]  (modeled with Nat ppm here)
    * spaceSavingStep     — table never exceeds capacity (Metwally bound)

  Run:  lake env lean ScaleneExtract.lean > scalene_verified_core.py
-/
import LeanToPython
open Lean LeanToPython

namespace ScaleneVerified

/-! ## CPU time split (mirrors Attribution.cTime / totalTime)

We use Nat "nanoseconds" so the def stays in the extraction fragment (the proof
project uses ℚ; the *algorithm* — `c = elapsed - python` clamped at 0, total =
python + c — is identical and the conservation proof carries over). -/

/-- C time = max(elapsed - python, 0). Mirrors scalene_cpu_profiler.py:135. -/
def cTimeNs (elapsedNs pythonNs : Nat) : Nat :=
  if elapsedNs ≥ pythonNs then elapsedNs - pythonNs else 0

/-- Total charged time = python + c. Mirrors scalene_cpu_profiler.py:136. -/
def totalTimeNs (elapsedNs pythonNs : Nat) : Nat :=
  pythonNs + cTimeNs elapsedNs pythonNs

/-! ## python_fraction in parts-per-million (mirrors Attribution.pythonFraction)

Integer ppm avoids floats while preserving the in-[0,1] property: the result is
always in [0, 1_000_000]. Mirrors sampleheap.hpp:366-377 (the 0/0 guard and the
pythonCount/(pythonCount+cCount) ratio). -/

/-- python_fraction × 1e6, with the 0/0 guard returning 0. -/
def pythonFractionPpm (pythonCount cCount : Nat) : Nat :=
  if pythonCount + cCount == 0 then 0
  else (pythonCount * 1000000) / (pythonCount + cCount)

/-- python-attributed bytes = fraction × count (ppm arithmetic). Mirrors
    scalene_memory_profiler.py:343 (python bytes ≤ total count). -/
def pythonBytes (count pythonCount cCount : Nat) : Nat :=
  (pythonFractionPpm pythonCount cCount * count) / 1000000

/-! ## Footprint folding (mirrors Attribution.applyEvents over Int) -/

/-- One memory event's signed effect: malloc encoded as positive, free as
    negative. Caller passes (isMalloc, count). -/
def footprintDelta (isMalloc : Bool) (count : Int) : Int :=
  if isMalloc then count else -count

/-! ## Space-Saving capacity-bounded increment (mirrors SpaceSaving.step)

Keyed by Nat here (real keys are stack tuples; Nat is the extraction-friendly
stand-in — the capacity invariant is key-type-agnostic). Mirrors
scalene_utility.py:515 `_space_saving_increment` and the cap at :512. -/

abbrev Tbl := List (Nat × Nat)

def hasKey (t : Tbl) (k : Nat) : Bool := t.any (fun p => p.1 == k)

def bump (t : Tbl) (k : Nat) : Tbl :=
  t.map (fun p => if p.1 == k then (p.1, p.2 + 1) else p)

/-- Binary min written as an explicit branch. `Nat.min` reaches a LCNF
    instance-projection path that LeanToPython mis-applies (drops an operand);
    the explicit `if` form lowers cleanly. Proven equal to `Nat.min` in
    ExtractMirror.lean. -/
def min2 (a b : Nat) : Nat := if a ≤ b then a else b

def minCount : Tbl → Nat
  | []          => 0
  | [p]         => p.2
  | p :: q :: r => min2 p.2 (minCount (q :: r))

def dropFirstWithCount : Tbl → Nat → Tbl
  | [],        _ => []
  | p :: rest, m => if p.2 == m then rest else p :: dropFirstWithCount rest m

/-- One Space-Saving step. PROVEN (SpaceSaving.step_withinCap): if the table is
    within `cap` before, it is within `cap` after. -/
def spaceSavingStep (cap : Nat) (t : Tbl) (k : Nat) : Tbl :=
  if hasKey t k then bump t k
  else if t.length < cap then (k, 1) :: t
  else
    let m := minCount t
    (k, m + 1) :: dropFirstWithCount t m

end ScaleneVerified

#eval show CoreM Unit from do
  let code ← emitPythonForNames `ScaleneVerified
    [ ``ScaleneVerified.cTimeNs,
      ``ScaleneVerified.totalTimeNs,
      ``ScaleneVerified.pythonFractionPpm,
      ``ScaleneVerified.pythonBytes,
      ``ScaleneVerified.footprintDelta,
      ``ScaleneVerified.hasKey,
      ``ScaleneVerified.bump,
      ``ScaleneVerified.min2,
      ``ScaleneVerified.minCount,
      ``ScaleneVerified.dropFirstWithCount,
      ``ScaleneVerified.spaceSavingStep ]
  IO.println code
