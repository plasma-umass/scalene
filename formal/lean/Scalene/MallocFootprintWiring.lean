/-
  Malloc/free FOOTPRINT metric, END TO END across the C++/Python boundary.

  Companion to CopyVolumeWiring.lean, for the harder of the two memory paths.
  It spans the native/Python line for the *current footprint* number Scalene
  reports (and its max, the headline "peak memory"): the C++ `SampleHeap`
  emitter (src/include/sampleheap.hpp:183-316) feeding the Python reader
  `process_malloc_free_samples` (scalene/scalene_memory_profiler.py:102-228).

  ── THE C++ SIDE (sampleheap.hpp) ─────────────────────────────────────────────
    register_malloc(n): _allocationSampler.increment(n,...); on trigger,
      process_malloc emits a record with action 'M' and count = the sampled
      byte excess the sampler returns.
    register_free(n):  _allocationSampler.decrement(n,...); on trigger,
      process_free emits 'F'/'f' with count = the sampled excess.
  `_allocationSampler` is the ThresholdSampler ALREADY MODELLED in
  MemorySampler.lean, whose `threshold_conserves` proves: reported-net + residual
  = true-net. We reuse that; the `emit*` bridge below shows the *records* the C++
  side writes sum (signed) to exactly that reported net.

  ── THE PYTHON SIDE (scalene_memory_profiler.py:194-228) ──────────────────────
    before = max(current_footprint, 0)
    for each same-pid record (NEWLINE markers, count == NEWLINE+1, skipped):
      count = item.count / BYTES_PER_MB
      if malloc: current_footprint += count
      else:      current_footprint  = max(0, current_footprint - count)   # CLAMP
    after = current_footprint

  ── THE SUBTLETY THE AUDIT METHOD FORBIDS ASSUMING AWAY ───────────────────────
  The `max(0, ·)` clamp on every free BREAKS pure conservation: if frees drive
  the running footprint below 0 (Scalene can miss allocations at startup — see
  the code comment at :215), the clamp silently adds bytes back. So "Python
  footprint delta = C++ reported net" is NOT unconditional. We model the clamp
  literally and prove the honest, conditional statements:

    * `clamp_is_identity_of_safe`: while the running footprint stays ≥ 0, the
      clamp is a no-op and the Python side is EXACTLY additive (delta =
      Σ record-net / BYTES_PER_MB).
    * `emit_records_sum`: the records the C++ ThresholdSampler writes sum
      (signed) to its `reported` net — the bridge to MemorySampler.
    * `roundtrip_conservation_of_safe` (headline): composing the two with
      `threshold_conserves`, the Python-reported footprint delta =
      (true-net − residual) / BYTES_PER_MB. Native truth → Python number.
    * `clamp_only_raises`: WITHOUT the non-negativity assumption, the clamp can
      only push the footprint UP, so the reported footprint is always ≥ the
      purely-additive value — the estimate errs toward over-reporting live
      memory, never under. A bound, stated honestly.
    * `foreign_pid_dropped`, `newline_marker_skipped`: the pid filter (:145) and
      the NEWLINE `continue` (:199) faithfully drop records that must not count.

  All over ℚ / ℤ / ℕ; no `sorry`.
-/
import Mathlib
import Scalene.MemorySampler

open scoped BigOperators
open Scalene.MemorySampler

namespace Scalene.MallocFootprintWiring

/-! ## The record stream crossing the boundary -/

inductive Action where
  | malloc
  | free
deriving DecidableEq

/-- A record as emitted by `writeCount` and parsed by the Python reader: an
    action, the sampled byte `count`, and the emitting `pid`. -/
structure Rec where
  action : Action
  count  : ℕ
  pid    : ℕ

/-- Signed byte contribution of one record: +count for malloc, −count for free —
    what the Python loop adds to `current_footprint` before the clamp. -/
def recNet : Rec → ℤ
  | ⟨.malloc, n, _⟩ => (n : ℤ)
  | ⟨.free,   n, _⟩ => -(n : ℤ)

/-- Signed byte total of a record stream. -/
def totalRecNet (rs : List Rec) : ℤ := (rs.map recNet).sum

@[simp] theorem totalRecNet_nil : totalRecNet [] = 0 := rfl

@[simp] theorem totalRecNet_cons (r : Rec) (rs : List Rec) :
    totalRecNet (r :: rs) = recNet r + totalRecNet rs := by
  simp [totalRecNet]

/-! ## The Python footprint fold, WITH the max(0,·) clamp -/

/-- One iteration of the Python footprint loop (in MB): malloc adds, free
    subtracts then clamps at 0. -/
def stepFootprint (bytesPerMB : ℚ) (fp : ℚ) : Rec → ℚ
  | ⟨.malloc, n, _⟩ => fp + (n : ℚ) / bytesPerMB
  | ⟨.free,   n, _⟩ => max 0 (fp - (n : ℚ) / bytesPerMB)

def runFootprint (bytesPerMB : ℚ) (fp : ℚ) : List Rec → ℚ
  | []      => fp
  | r :: rs => runFootprint bytesPerMB (stepFootprint bytesPerMB fp r) rs

/-- The purely-additive footprint (no clamp): the reference "conserved" value,
    in closed form — starting footprint plus the signed record total in MB. -/
def additiveFootprint (bytesPerMB : ℚ) (fp : ℚ) (rs : List Rec) : ℚ :=
  fp + (totalRecNet rs : ℚ) / bytesPerMB

/-- The running footprint stays "safe" (no clamp needed) if every free keeps the
    pre-clamp value ≥ 0. This is the precise regime in which the clamp is inert. -/
def Safe (bytesPerMB : ℚ) (fp : ℚ) : List Rec → Prop
  | []                    => True
  | ⟨.malloc, n, _⟩ :: rs => Safe bytesPerMB (fp + (n : ℚ) / bytesPerMB) rs
  | ⟨.free,   n, _⟩ :: rs => 0 ≤ fp - (n : ℚ) / bytesPerMB
                             ∧ Safe bytesPerMB (fp - (n : ℚ) / bytesPerMB) rs

/-! ## 1. Non-negative regime ⇒ clamp is inert ⇒ exact additivity -/

/-- **In the safe regime the clamp vanishes.** If the running footprint never
    needs clamping, the Python fold equals the closed-form additive footprint:
    the reported footprint delta is exactly the signed record total (in MB). -/
theorem clamp_is_identity_of_safe (bytesPerMB : ℚ) :
    ∀ (rs : List Rec) (fp : ℚ), Safe bytesPerMB fp rs →
      runFootprint bytesPerMB fp rs = additiveFootprint bytesPerMB fp rs := by
  intro rs
  induction rs with
  | nil => intro fp _; simp [runFootprint, additiveFootprint]
  | cons r rs ih =>
      intro fp hsafe
      cases r with
      | mk action n pid =>
          cases action with
          | malloc =>
              simp only [runFootprint, stepFootprint, Safe] at hsafe ⊢
              rw [ih _ hsafe]
              simp only [additiveFootprint, totalRecNet_cons, recNet]
              push_cast
              ring
          | free =>
              simp only [runFootprint, stepFootprint, Safe] at hsafe ⊢
              obtain ⟨hnn, hrest⟩ := hsafe
              rw [max_eq_right hnn, ih _ hrest]
              simp only [additiveFootprint, totalRecNet_cons, recNet]
              push_cast
              ring

/-! ## 2. Without the assumption: the clamp only raises the footprint -/

/-- **The clamp can only over-report.** Unconditionally, the clamped Python fold
    is ≥ the purely-additive footprint. So even when the non-negativity regime
    fails, Scalene's reported live memory is never *below* the conserved value —
    the error is one-sided (toward over-reporting), never a silent undercount. -/
theorem clamp_only_raises (bytesPerMB : ℚ) :
    ∀ (rs : List Rec) (fp : ℚ),
      additiveFootprint bytesPerMB fp rs ≤ runFootprint bytesPerMB fp rs := by
  intro rs
  induction rs with
  | nil => intro fp; simp [runFootprint, additiveFootprint]
  | cons r rs ih =>
      intro fp
      cases r with
      | mk action n pid =>
          cases action with
          | malloc =>
              -- equality on a malloc step; chain through the IH
              simp only [runFootprint, stepFootprint]
              refine le_trans ?_ (ih (fp + (n : ℚ) / bytesPerMB))
              simp only [additiveFootprint, totalRecNet_cons, recNet]
              apply le_of_eq; push_cast; ring
          | free =>
              simp only [runFootprint, stepFootprint]
              refine le_trans ?_ (ih (max 0 (fp - (n : ℚ) / bytesPerMB)))
              -- additive(fp, free::rs) ≤ additive(max 0 (fp - n/b), rs)
              simp only [additiveFootprint, totalRecNet_cons, recNet]
              have hle : fp - (n : ℚ) / bytesPerMB ≤ max 0 (fp - (n : ℚ) / bytesPerMB) :=
                le_max_right _ _
              set M := max 0 (fp - (n : ℚ) / bytesPerMB) with hM
              set T := (totalRecNet rs : ℚ) / bytesPerMB with hT
              -- LHS = fp + ↑(-n + Σrs)/b ; RHS = M + Σrs/b = M + T
              have hlhs : fp + ((-(n : ℤ) + totalRecNet rs : ℤ) : ℚ) / bytesPerMB
                    = (fp - (n : ℚ) / bytesPerMB) + T := by
                rw [hT]; push_cast; ring
              rw [hlhs]
              linarith [hle]

/-! ## 3. Bridge to the ThresholdSampler: emitted records sum to `reported`

The C++ side emits a record exactly when the sampler triggers, with `count` =
the reported byte excess. We model that emitter and prove its records sum
(signed) to the sampler's `reported` net — connecting this file to
MemorySampler.threshold_conserves. -/

/-- One step of the emitter: run the ThresholdSampler step AND emit the record
    it would write (a singleton list on trigger, empty otherwise), tagged `pid`.
    Faithful to process_malloc / process_free: on a malloc trigger the record's
    count is the positive reported excess `bal'`; on a free trigger it is the
    magnitude `-bal'` with action free. -/
def emitStep (I : ℤ) (pid : ℕ) (s : St) : Event → St × List Rec
  | .alloc m =>
      let bal' := s.bal + (m : ℤ)
      if bal' ≥ I then
        (⟨0, s.reported + bal'⟩, [⟨.malloc, bal'.toNat, pid⟩])
      else (⟨bal', s.reported⟩, [])
  | .free m =>
      let bal' := s.bal - (m : ℤ)
      if bal' ≤ -I then
        (⟨0, s.reported + bal'⟩, [⟨.free, (-bal').toNat, pid⟩])
      else (⟨bal', s.reported⟩, [])

/-- The emitter's state projection is exactly `stepThreshold` — the emitter adds
    records without changing the sampler's state evolution. -/
theorem emitStep_state (I : ℤ) (pid : ℕ) (s : St) (e : Event) :
    (emitStep I pid s e).1 = stepThreshold I s e := by
  cases e with
  | alloc m => simp only [emitStep, stepThreshold]; split <;> rfl
  | free m => simp only [emitStep, stepThreshold]; split <;> rfl

/-- Run the emitter over an event list, collecting all records. -/
def emitRun (I : ℤ) (pid : ℕ) (s : St) : List Event → St × List Rec
  | []      => (s, [])
  | e :: es =>
      let (s', rs1) := emitStep I pid s e
      let (s'', rs2) := emitRun I pid s' es
      (s'', rs1 ++ rs2)

/-- The emitter's final state equals the plain `runThreshold`. -/
theorem emitRun_state (I : ℤ) (pid : ℕ) (s : St) (es : List Event) :
    (emitRun I pid s es).1 = runThreshold I s es := by
  induction es generalizing s with
  | nil => rfl
  | cons e es ih =>
      simp only [emitRun, runThreshold]
      rw [← emitStep_state I pid s e]
      exact ih (emitStep I pid s e).1

/-- **One emitted record carries its reported excess.** For a triggering step the
    record's signed net equals the change in `reported`; for a non-trigger there
    is no record and `reported` is unchanged. Needs `0 < I` so the triggered
    `bal'` has the right sign for the ℕ `count` cast to round-trip. -/
theorem emitStep_records_sum (I : ℤ) (hI : 0 < I) (pid : ℕ) (s : St) (e : Event) :
    totalRecNet (emitStep I pid s e).2
      = (emitStep I pid s e).1.reported - s.reported := by
  cases e with
  | alloc m =>
      simp only [emitStep]
      by_cases h : s.bal + (m : ℤ) ≥ I
      · rw [if_pos h]
        have hpos : (0 : ℤ) ≤ s.bal + (m : ℤ) := le_trans (le_of_lt hI) h
        simp only [totalRecNet, recNet, List.map_cons, List.map_nil, List.sum_cons,
                   List.sum_nil, add_zero]
        rw [Int.toNat_of_nonneg hpos]; ring
      · rw [if_neg h]; simp [totalRecNet]
  | free m =>
      simp only [emitStep]
      by_cases h : s.bal - (m : ℤ) ≤ -I
      · rw [if_pos h]
        have hneg : s.bal - (m : ℤ) ≤ 0 := le_trans h (by linarith)
        have hnn : (0 : ℤ) ≤ -(s.bal - (m : ℤ)) := by linarith
        simp only [totalRecNet, recNet, List.map_cons, List.map_nil, List.sum_cons,
                   List.sum_nil, add_zero]
        rw [Int.toNat_of_nonneg hnn]; ring
      · rw [if_neg h]; simp [totalRecNet]

/-- **The emitted records sum to the sampler's reported net.** Over any event
    sequence from empty counters, the signed total of the records the C++ side
    writes equals `reported` — so the Python-side `Σ record-net` is exactly the
    native reported footprint. -/
theorem emit_records_sum (I : ℤ) (hI : 0 < I) (pid : ℕ) (es : List Event) :
    totalRecNet (emitRun I pid ⟨0, 0⟩ es).2 = (runThreshold I ⟨0, 0⟩ es).reported := by
  suffices H : ∀ (s : St), totalRecNet (emitRun I pid s es).2
      = (runThreshold I s es).reported - s.reported by
    have := H ⟨0, 0⟩; simpa using this
  intro s
  induction es generalizing s with
  | nil => simp [emitRun, runThreshold]
  | cons e es ih =>
      simp only [emitRun, runThreshold]
      rw [totalRecNet, List.map_append, List.sum_append, ← totalRecNet, ← totalRecNet]
      rw [ih (emitStep I pid s e).1, emitStep_records_sum I hI pid s e,
          emitStep_state I pid s e]
      ring

/-! ## 4. End to end: Python footprint delta = (true net − residual) / bytesPerMB -/

/-- **Round-trip conservation (headline).** Compose the pieces: with the records
    the C++ ThresholdSampler emits (from empty counters), and provided the Python
    running footprint stays non-negative (the clamp inert), the footprint delta
    Python reports equals the true net allocation minus the sub-threshold
    residual, divided by BYTES_PER_MB. This is the malloc-footprint metric proven
    end to end across the native/Python boundary — the number `scalene view`
    shows for memory faithfully reflects observed allocation, up to the bounded
    sampler residual, exactly when startup misses don't force the clamp. -/
theorem roundtrip_conservation_of_safe (bytesPerMB : ℚ) (_hb : 0 < bytesPerMB)
    (I : ℤ) (hI : 0 < I) (pid : ℕ) (fp0 : ℚ) (es : List Event)
    (hsafe : Safe bytesPerMB fp0 (emitRun I pid ⟨0, 0⟩ es).2) :
    runFootprint bytesPerMB fp0 (emitRun I pid ⟨0, 0⟩ es).2 - fp0
      = (trueNet es - (runThreshold I ⟨0, 0⟩ es).bal : ℚ) / bytesPerMB := by
  set rs := (emitRun I pid ⟨0, 0⟩ es).2 with hrs
  -- Python side is additive in the safe regime.
  rw [clamp_is_identity_of_safe bytesPerMB rs fp0 hsafe]
  simp only [additiveFootprint, add_sub_cancel_left]
  -- The records sum to the sampler's reported net, and reported = trueNet − bal.
  have hsum : (totalRecNet rs : ℚ) = ((runThreshold I ⟨0, 0⟩ es).reported : ℚ) := by
    rw [hrs]; exact_mod_cast emit_records_sum I hI pid es
  have hcons : (runThreshold I ⟨0, 0⟩ es).reported
             = trueNet es - (runThreshold I ⟨0, 0⟩ es).bal := by
    have := threshold_conserves I es; simp only at this; linarith [this]
  rw [hsum, hcons]
  push_cast
  ring

/-! ## 5. The filters that drop records which must not count -/

/-- The Python reader restricted to same-pid records (the `curr_pid != pid`
    guard, scalene_memory_profiler.py:145). -/
def pidFilter (curr_pid : ℕ) (rs : List Rec) : List Rec :=
  rs.filter (fun r => r.pid = curr_pid)

/-- **Foreign-pid records are dropped** — a child process writing to a shared
    mapfile does not affect this process's footprint fold. -/
theorem foreign_pid_dropped (curr_pid other : ℕ) (h : other ≠ curr_pid)
    (rs : List Rec) (r : Rec) (hr : r.pid = other) :
    pidFilter curr_pid (r :: rs) = pidFilter curr_pid rs := by
  unfold pidFilter
  have : ¬ (r.pid = curr_pid) := by rw [hr]; exact h
  simp [this]

/-- **NEWLINE boundary markers don't move the footprint.** The Python reader
    `continue`s on `count == NEWLINE+1` (scalene_memory_profiler.py:199), so such
    a record leaves the footprint unchanged. We model the skip as filtering by a
    predicate on the count; skipping is exactly not folding it. -/
theorem newline_marker_skipped (rs : List Rec)
    (newline1 : ℕ) (r : Rec) (hr : r.count = newline1)
    (skip : Rec → Bool) (hskip : ∀ x, skip x = true ↔ x.count = newline1) :
    (r :: rs).filter (fun x => ! skip x) = rs.filter (fun x => ! skip x) := by
  have : skip r = true := (hskip r).mpr hr
  simp [this]

end Scalene.MallocFootprintWiring
