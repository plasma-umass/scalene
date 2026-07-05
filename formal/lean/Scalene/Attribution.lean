/-
  Scalene attribution-correctness model.

  Proves the *conservation* and *bounds* invariants that Scalene's sampling
  attribution must satisfy.  We model the arithmetic faithfully (rationals,
  matching Python floats' role as exact accounting quantities here) and prove:

    1. CPU conservation: when one CPU sample's `total_time` is split across the
       sampled stack frames, the per-frame attributions sum back to exactly
       `total_time` -- no time is lost or double-counted.
       Faithful to scalene/scalene_cpu_profiler.py:145 (total_time / total_frames
       distributed over frames) and :411 (total_cpu_samples += total_time).

    2. Python/C split conservation: `python_time + c_time = total_time`, with
       both non-negative, where `c_time := max(elapsed - python_time, 0)`.
       Faithful to scalene/scalene_cpu_profiler.py:134-136.

    3. python_fraction bounds: the C++ interposer's
       `python_fraction = _pythonCount / (_pythonCount + _cCount)`
       lies in [0,1].  Faithful to src/include/sampleheap.hpp:377 and the
       0/0 guard at :366.

    4. Memory split bound: `memory_python_samples ≤ memory_malloc_samples`
       per line, because python bytes = python_fraction * count with
       python_fraction ≤ 1.  Faithful to scalene/scalene_memory_profiler.py:342-343.

    5. Footprint conservation: current_footprint after a batch of malloc/free
       events equals the starting footprint plus (Σ mallocs − Σ frees).
       Faithful to scalene/scalene_memory_profiler.py:194-228,389.

  We use ℚ (exact rationals) rather than floats: the properties are about
  conservation/bounds of accounting quantities, which floats approximate but
  the *intended* invariant is exact.  All proofs are complete (no `sorry`).
-/
import Mathlib

namespace Scalene

/-! ## 1 & 2. CPU time: Python/C split and per-frame distribution -/

/-- A single CPU sample, as produced by `cpu_signal_handler`.
    `pythonTime` is the known interval spent in Python this tick;
    `elapsed` is the measured virtual time since the previous sample.
    Mirrors `last_cpu_interval` and `elapsed.virtual`
    (scalene_cpu_profiler.py:97,134). -/
structure CpuSample where
  pythonTime : Rat
  elapsed    : Rat
  hpy  : 0 ≤ pythonTime
  hel  : 0 ≤ elapsed
  -- The handler only fires after at least `pythonTime` of virtual time elapsed,
  -- so the measured elapsed dominates the Python interval (else c_time clamps).

/-- C time, as computed at scalene_cpu_profiler.py:135:
    `c_time = max(elapsed - python_time, 0)`. -/
def cTime (s : CpuSample) : Rat := max (s.elapsed - s.pythonTime) 0

/-- The total time charged for this sample (scalene_cpu_profiler.py:136). -/
def totalTime (s : CpuSample) : Rat := s.pythonTime + cTime s

/-- C time is always non-negative (the `max _ 0` clamp). -/
theorem cTime_nonneg (s : CpuSample) : 0 ≤ cTime s := le_max_right _ _

/-- Python time is always non-negative. -/
theorem pythonTime_nonneg (s : CpuSample) : 0 ≤ s.pythonTime := s.hpy

/-- **Split conservation**: total = python + c, and total ≥ python ≥ 0. -/
theorem totalTime_eq_split (s : CpuSample) :
    totalTime s = s.pythonTime + cTime s := rfl

theorem totalTime_nonneg (s : CpuSample) : 0 ≤ totalTime s := by
  have := pythonTime_nonneg s
  have := cTime_nonneg s
  unfold totalTime
  linarith

/-- When the program actually spent ≥ `pythonTime` of virtual time in this
    interval (`pythonTime ≤ elapsed`, the common case), the clamp is inert and
    `totalTime` equals the measured `elapsed` exactly -- no time invented, none
    dropped. -/
theorem totalTime_eq_elapsed (s : CpuSample) (h : s.pythonTime ≤ s.elapsed) :
    totalTime s = s.elapsed := by
  unfold totalTime cTime
  rw [max_eq_left (by linarith)]
  ring

/-! ### Per-frame distribution (scalene_cpu_profiler.py:145, loop :356-402)

`normalized_time = total_time / total_frames` is added to each sampled frame.
We prove the distributed amounts sum back to `total_time`. -/

/-- Sum of a list of rationals. -/
def sum : List Rat → Rat
  | []      => 0
  | x :: xs => x + sum xs

@[simp] theorem sum_nil : sum [] = 0 := rfl
@[simp] theorem sum_cons (x : Rat) (xs : List Rat) : sum (x :: xs) = x + sum xs := rfl

/-- A constant `c` summed over a list of length `n` equals `n * c`. -/
theorem sum_replicate (n : Nat) (c : Rat) : sum (List.replicate n c) = (n : Rat) * c := by
  induction n with
  | zero => simp [List.replicate]
  | succ k ih =>
      simp only [List.replicate, sum_cons, ih]
      push_cast
      ring

/-- **CPU conservation across frames.**  Distributing `totalTime s` evenly over
    `frames` frames (each getting `totalTime s / frames`) and summing the
    per-frame charges recovers `totalTime s` exactly, provided there is at
    least one frame (there always is: the interrupted frame).  This is the
    invariant behind `total_cpu_samples += total_time` (scalene_cpu_profiler.py:411)
    matching the per-line sums. -/
theorem cpu_distribution_conserved (s : CpuSample) (frames : Nat) (h : frames ≠ 0) :
    sum (List.replicate frames (totalTime s / (frames : Rat))) = totalTime s := by
  rw [sum_replicate]
  have hframes : (frames : Rat) ≠ 0 := by exact_mod_cast h
  field_simp

/-! ## 3. python_fraction bounds (sampleheap.hpp:366-377) -/

/-- `python_fraction = pythonCount / (pythonCount + cCount)`, with the C++
    guard that returns 0 when both counts are 0 (sampleheap.hpp:366). -/
def pythonFraction (pythonCount cCount : Rat) : Rat :=
  if pythonCount + cCount = 0 then 0 else pythonCount / (pythonCount + cCount)

/-- **python_fraction ≥ 0** (lower half of the [0,1] bound). -/
theorem pythonFraction_nonneg (p c : Rat) (hp : 0 ≤ p) (hc : 0 ≤ c) :
    0 ≤ pythonFraction p c := by
  unfold pythonFraction
  split
  · exact le_refl 0
  · rename_i hne
    have hsum : 0 < p + c := lt_of_le_of_ne (by linarith) (by intro h; exact hne h.symm)
    exact div_nonneg hp (le_of_lt hsum)

/-- **python_fraction ≤ 1** (upper half of the [0,1] bound). -/
theorem pythonFraction_le_one (p c : Rat) (hp : 0 ≤ p) (hc : 0 ≤ c) :
    pythonFraction p c ≤ 1 := by
  unfold pythonFraction
  split
  · exact zero_le_one
  · rename_i hne
    have hsum : 0 < p + c := lt_of_le_of_ne (by linarith) (by intro h; exact hne h.symm)
    rw [div_le_one hsum]
    linarith

/-! ## 4. Memory split bound (scalene_memory_profiler.py:342-343) -/

/-- Python-attributed bytes for one malloc sample: `python_fraction * count`. -/
def pythonBytes (count p c : Rat) : Rat :=
  pythonFraction p c * count

/-- **Memory split bound**: the python-attributed bytes for a sample never
    exceed the sample's total `count` (since python_fraction ≤ 1), and are
    non-negative.  Hence per line `memory_python_samples ≤ memory_malloc_samples`. -/
theorem pythonBytes_le_count (count p c : Rat)
    (hp : 0 ≤ p) (hc : 0 ≤ c) (hcount : 0 ≤ count) :
    pythonBytes count p c ≤ count := by
  unfold pythonBytes
  calc pythonFraction p c * count
      ≤ 1 * count := by
        apply mul_le_mul_of_nonneg_right (pythonFraction_le_one p c hp hc) hcount
    _ = count := one_mul count

theorem pythonBytes_nonneg (count p c : Rat)
    (hp : 0 ≤ p) (hc : 0 ≤ c) (hcount : 0 ≤ count) :
    0 ≤ pythonBytes count p c :=
  mul_nonneg (pythonFraction_nonneg p c hp hc) hcount

/-! ## 5. Footprint conservation (scalene_memory_profiler.py:194-228,389) -/

/-- A memory event from the mapfile: either a malloc (+count) or free (−count). -/
inductive MemEvent where
  | malloc (count : Rat)
  | free   (count : Rat)

/-- Net effect of one event on the current footprint
    (malloc: +count at :331; free: −count at :369). -/
def delta : MemEvent → Rat
  | .malloc c => c
  | .free c   => -c

/-- Apply a batch of events to a starting footprint, folding left as the
    `process_malloc_free_samples` loop does. -/
def applyEvents (start : Rat) : List MemEvent → Rat
  | []      => start
  | e :: es => applyEvents (start + delta e) es

/-- Total malloc'd bytes in a batch. -/
def totalMalloc : List MemEvent → Rat
  | []              => 0
  | .malloc c :: es => c + totalMalloc es
  | .free _ :: es   => totalMalloc es

/-- Total freed bytes in a batch. -/
def totalFree : List MemEvent → Rat
  | []            => 0
  | .free c :: es => c + totalFree es
  | .malloc _ :: es => totalFree es

/-- **Footprint conservation**: after processing a batch of events, the
    current footprint equals the start plus (Σ mallocs − Σ frees), exactly.
    This is the `after = before + (mallocs − frees)` invariant the profiler
    relies on (scalene_memory_profiler.py:389-391). -/
theorem footprint_conserved (start : Rat) (es : List MemEvent) :
    applyEvents start es = start + (totalMalloc es - totalFree es) := by
  induction es generalizing start with
  | nil => simp [applyEvents, totalMalloc, totalFree]
  | cons e es ih =>
      cases e with
      | malloc c =>
          simp only [applyEvents, delta, totalMalloc, totalFree, ih]
          ring
      | free c =>
          simp only [applyEvents, delta, totalMalloc, totalFree, ih]
          ring

end Scalene
