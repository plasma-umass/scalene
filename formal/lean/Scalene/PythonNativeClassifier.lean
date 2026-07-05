/-
  The Python-vs-native CPU classifier — conservation & attribution correctness.

  HANDOFF §6 listed this as an open gap: "only *conservation* (fractions sum to
  1) proven, not the per-sample accuracy of the CALL-opcode/signal-deferral
  classifier heuristic." This file proves the part that is a *theorem* — the
  classifier is a total function that conserves the sample's CPU time exactly,
  in every branch — and states honestly the part that is a *heuristic* (which
  branch is "right") with the precise assumption under which it is exact.

  ── THE CLASSIFIER (scalene_cpu_profiler.py:251-341) ──────────────────────────
  Given one CPU sample carrying `python_time` (= last timer interval) and
  `c_time` (= excess CPU beyond it), with `cpu = python_time + c_time`, and the
  bytecode position, it charges buckets `(line, {python|native})` one of 4 ways:

    (A) at a CALL and call-attribution mode → ALL `cpu` to NATIVE on this line;
        the sample landed inside the C call, so even `python_time` was in C.
    (B) c_time > 0 and a preceding CALL on a DIFFERENT line → SPLIT:
        `c_time` native on the CALL line, `python_time` Python on this line.
    (C) c_time > 0, CALL on same line / not found → together on this line:
        `python_time` Python + `c_time` native.
    (D) else → as computed: `python_time` Python + `c_time` native, this line.

  ── WHAT WE PROVE ─────────────────────────────────────────────────────────────
  Model the output as a finite map from `(Line × Kind)` buckets to ℚ time. Then:
    * `charge_total` — in EVERY branch the total time charged equals the
      sample's `cpu = python_time + c_time`. No time invented or lost by the
      classification: it only *moves* a fixed budget between buckets.
    * `attribute_native_split` — the native-vs-Python split of the charged total
      is exactly (c_time-or-cpu, python_time-or-0) per branch — characterizing
      what each branch decides.
    * `charge_nonneg` — every bucket gets a non-negative charge (needs
      `0 ≤ python_time`, `0 ≤ c_time`, which the code guarantees:
      `c_time = max(elapsed − python_time, 0)`).
    * `classify_total` — the branch selector is a total function: exactly one of
      A/B/C/D fires for any input, so attribution is always defined.

  ── THE HEURISTIC BOUNDARY (stated, not hidden) ───────────────────────────────
  Which branch is *correct* depends on whether the async signal was deferred
  during a C call — unobservable from the sample alone. We prove
  `branchA_exact_if_in_call`: IF the sample truly landed in native code
  (`trueNative = cpu`), branch A's all-native charge is exactly right. The
  heuristic is the hypothesis `is_at_call ⇒ trueNative = cpu`; the code's
  engineering (CALL-opcode detection) is what makes it hold in practice, and
  that is not formalized here — only the conditional correctness is.

  All over ℚ; no `sorry`.
-/
import Mathlib

open scoped BigOperators

namespace Scalene.PythonNativeClassifier

/-- Time is charged to a line as either Python or native. -/
inductive Kind where
  | python
  | native
deriving DecidableEq

variable {Line : Type} [DecidableEq Line]

/-- The classifier's output: how much CPU time each `(line, kind)` bucket gets
    charged for one sample. A finite association modeled as a function. -/
abbrev Charge (Line : Type) := Line → Kind → ℚ

/-- The empty charge. -/
def noCharge : Charge Line := fun _ _ => 0

/-- Add `t` to bucket `(ℓ, k)`. -/
def add (c : Charge Line) (ℓ : Line) (k : Kind) (t : ℚ) : Charge Line :=
  fun ℓ' k' => if ℓ' = ℓ ∧ k' = k then c ℓ' k' + t else c ℓ' k'

/-- One sample: `python_time`, `c_time` (both ≥ 0), the current `line`, and the
    classification facts the code computes from the bytecode. -/
structure Sample (Line : Type) where
  pythonTime : ℚ
  cTime      : ℚ
  line       : Line
  pythonNonneg : 0 ≤ pythonTime
  cNonneg      : 0 ≤ cTime

namespace Sample

variable {Line : Type} [DecidableEq Line]

/-- The sample's total CPU time — the budget the classifier must conserve. -/
def cpu (s : Sample Line) : ℚ := s.pythonTime + s.cTime

/-- The four branches, as the code selects them (:256-341). `callLine?` is the
    preceding-CALL line from `find_preceding_call_line` (none if not found). -/
inductive Branch (Line : Type) where
  | atCall                        -- (A) is_at_call ∧ call-attribution mode
  | splitToCall (callLine : Line) -- (B) c_time>0, preceding CALL on a diff line
  | together                      -- (C) c_time>0, same line / not found
  | asComputed                    -- (D) else

/-- The attribution for a sample under a chosen branch, mirroring each
    `_update_main_thread_stats` call in scalene_cpu_profiler.py. -/
def charge (s : Sample Line) : Branch Line → Charge Line
  | .atCall =>
      -- (A) all cpu time to native on this line (:263-275, python arg = 0.0)
      add noCharge s.line .native s.cpu
  | .splitToCall callLine =>
      -- (B) c_time native on the CALL line; python_time Python on this line
      add (add noCharge callLine .native s.cTime) s.line .python s.pythonTime
  | .together =>
      -- (C) python_time Python + c_time native, this line (:316-328)
      add (add noCharge s.line .python s.pythonTime) s.line .native s.cTime
  | .asComputed =>
      -- (D) same shape as (C) (:331-341)
      add (add noCharge s.line .python s.pythonTime) s.line .native s.cTime

/-- Total time charged across all buckets of a `Charge`. Sums the python and
    native components over all (finitely many) lines. -/
def total [Fintype Line] (c : Charge Line) : ℚ :=
  ∑ ℓ : Line, (c ℓ .python + c ℓ .native)

end Sample

open Sample

variable [Fintype Line]

/-- `add` increases the total by exactly `t` — it touches exactly one bucket. -/
theorem total_add (c : Charge Line) (ℓ : Line) (k : Kind) (t : ℚ) :
    Sample.total (add c ℓ k t) = Sample.total c + t := by
  unfold Sample.total add
  -- Rewrite each summand as (old summand) + (t only at ℓ), then split the sum.
  have hkey : ∀ ℓ' ∈ (Finset.univ : Finset Line),
      (if ℓ' = ℓ ∧ Kind.python = k then c ℓ' .python + t else c ℓ' .python)
        + (if ℓ' = ℓ ∧ Kind.native = k then c ℓ' .native + t else c ℓ' .native)
      = (c ℓ' .python + c ℓ' .native)
        + (if ℓ' = ℓ then t else 0) := by
    intro ℓ' _
    by_cases hℓ : ℓ' = ℓ
    · subst hℓ
      cases k <;> (simp; ring)
    · simp [hℓ]
  rw [Finset.sum_congr rfl hkey, Finset.sum_add_distrib,
      Finset.sum_ite_eq' Finset.univ ℓ (fun _ => t)]
  simp

/-- `total noCharge = 0`. -/
@[simp] theorem total_noCharge : Sample.total (noCharge : Charge Line) = 0 := by
  unfold Sample.total noCharge; simp

/-! ## Conservation: every branch charges exactly the sample's CPU budget -/

/-- **Attribution conservation.** For any sample and any branch the classifier
    could pick, the total time charged across all buckets equals the sample's
    `cpu = pythonTime + cTime`. The classification only *moves* a fixed budget
    between (line, python/native) buckets — it never invents or loses time. -/
theorem charge_total (s : Sample Line) (b : Branch Line) :
    Sample.total (s.charge b) = s.cpu := by
  cases b with
  | atCall =>
      simp only [Sample.charge, total_add, total_noCharge, zero_add]
  | splitToCall callLine =>
      simp only [Sample.charge, total_add, total_noCharge, zero_add]
      unfold Sample.cpu; ring
  | together =>
      simp only [Sample.charge, total_add, total_noCharge, zero_add]
      unfold Sample.cpu; ring
  | asComputed =>
      simp only [Sample.charge, total_add, total_noCharge, zero_add]
      unfold Sample.cpu; ring

/-! ## The native / Python split each branch decides -/

/-- Total native time charged (sum of the `.native` component over all lines). -/
def totalNative (c : Charge Line) : ℚ := ∑ ℓ : Line, c ℓ .native

/-- Total Python time charged. -/
def totalPython (c : Charge Line) : ℚ := ∑ ℓ : Line, c ℓ .python

theorem totalNative_add_native (c : Charge Line) (ℓ : Line) (t : ℚ) :
    totalNative (add c ℓ .native t) = totalNative c + t := by
  unfold totalNative add
  have hkey : ∀ ℓ' ∈ (Finset.univ : Finset Line),
      (if ℓ' = ℓ ∧ Kind.native = Kind.native then c ℓ' .native + t else c ℓ' .native)
      = c ℓ' .native + (if ℓ' = ℓ then t else 0) := by
    intro ℓ' _; by_cases h : ℓ' = ℓ <;> simp [h]
  rw [Finset.sum_congr rfl hkey, Finset.sum_add_distrib,
      Finset.sum_ite_eq' Finset.univ ℓ (fun _ => t)]; simp

theorem totalNative_add_python (c : Charge Line) (ℓ : Line) (t : ℚ) :
    totalNative (add c ℓ .python t) = totalNative c := by
  unfold totalNative add
  apply Finset.sum_congr rfl
  intro ℓ' _; by_cases h : ℓ' = ℓ <;> simp [h]

theorem totalPython_add_python (c : Charge Line) (ℓ : Line) (t : ℚ) :
    totalPython (add c ℓ .python t) = totalPython c + t := by
  unfold totalPython add
  have hkey : ∀ ℓ' ∈ (Finset.univ : Finset Line),
      (if ℓ' = ℓ ∧ Kind.python = Kind.python then c ℓ' .python + t else c ℓ' .python)
      = c ℓ' .python + (if ℓ' = ℓ then t else 0) := by
    intro ℓ' _; by_cases h : ℓ' = ℓ <;> simp [h]
  rw [Finset.sum_congr rfl hkey, Finset.sum_add_distrib,
      Finset.sum_ite_eq' Finset.univ ℓ (fun _ => t)]; simp

theorem totalPython_add_native (c : Charge Line) (ℓ : Line) (t : ℚ) :
    totalPython (add c ℓ .native t) = totalPython c := by
  unfold totalPython add
  apply Finset.sum_congr rfl
  intro ℓ' _; by_cases h : ℓ' = ℓ <;> simp [h]

@[simp] theorem totalNative_noCharge : totalNative (noCharge : Charge Line) = 0 := by
  unfold totalNative noCharge; simp

@[simp] theorem totalPython_noCharge : totalPython (noCharge : Charge Line) = 0 := by
  unfold totalPython noCharge; simp

/-- **The native/Python split, branch A (at CALL).** All `cpu` charged native,
    nothing to Python — the sample is deemed entirely inside the C call. -/
theorem split_atCall (s : Sample Line) :
    totalNative (s.charge .atCall) = s.cpu
    ∧ totalPython (s.charge .atCall) = 0 := by
  constructor <;>
    simp only [Sample.charge, totalNative_add_native, totalPython_add_native,
               totalNative_noCharge, totalPython_noCharge, zero_add]

/-- **The native/Python split, branches B/C/D.** Exactly `cTime` native and
    `pythonTime` Python — the interval-formula split, whether kept on one line
    (C/D) or split across the CALL line and this line (B). -/
theorem split_together (s : Sample Line) :
    totalNative (s.charge .together) = s.cTime
    ∧ totalPython (s.charge .together) = s.pythonTime := by
  constructor <;>
    simp only [Sample.charge, totalNative_add_native, totalNative_add_python,
               totalPython_add_native, totalPython_add_python,
               totalNative_noCharge, totalPython_noCharge, zero_add]

theorem split_splitToCall (s : Sample Line) (callLine : Line) :
    totalNative (s.charge (.splitToCall callLine)) = s.cTime
    ∧ totalPython (s.charge (.splitToCall callLine)) = s.pythonTime := by
  constructor <;>
    simp only [Sample.charge, totalNative_add_native, totalNative_add_python,
               totalPython_add_native, totalPython_add_python,
               totalNative_noCharge, totalPython_noCharge, zero_add]

/-! ## Non-negativity: every bucket charge is ≥ 0 -/

/-- **Every bucket gets a non-negative charge.** Relies on `0 ≤ pythonTime` and
    `0 ≤ cTime`, which the code guarantees (`c_time = max(elapsed − python, 0)`,
    `python_time = interval ≥ 0`). So no branch can produce a negative time. -/
theorem charge_nonneg (s : Sample Line) (b : Branch Line) (ℓ : Line) (k : Kind) :
    0 ≤ s.charge b ℓ k := by
  have hp := s.pythonNonneg
  have hc := s.cNonneg
  have hcpu : 0 ≤ s.cpu := by unfold Sample.cpu; linarith
  cases b <;>
    simp only [Sample.charge, add, noCharge] <;>
    (repeat' split) <;> first | linarith | simp

/-! ## The branch selector is total (exactly one branch always fires)

The code's `if/elif/elif/else` picks exactly one branch from the observable
facts. We model the selector and prove it is a genuine total function of those
facts, so `attribute` is always defined — there is no unclassified sample. -/

/-- The observable classification facts the code reads: whether the sample is at
    a CALL under call-attribution mode, whether c_time > 0, and the preceding
    CALL line (if found and on a different line). -/
structure Facts (Line : Type) where
  useCallAtCall : Bool          -- use_call_attribution ∧ is_at_call
  cPositive     : Bool          -- average_c_time > 0
  precedingDiff : Option Line   -- preceding CALL line, if found ∧ ≠ this line

/-- The branch the code selects (:256-341), as a total function of the facts and
    the sample's line. -/
def classify (s : Sample Line) (f : Facts Line) : Branch Line :=
  if f.useCallAtCall then .atCall
  else if f.cPositive then
    match f.precedingDiff with
    | some cl => .splitToCall cl
    | none    => .together
  else .asComputed

/-- **The selector is total.** `classify` returns a branch for every possible
    combination of facts — there is no input the code leaves unclassified. (This
    is definitional totality; we record it so the conservation theorems above
    are known to cover the *whole* input space, not a subset.) -/
theorem classify_total (s : Sample Line) (f : Facts Line) :
    ∃ b : Branch Line, classify s f = b := ⟨classify s f, rfl⟩

/-- Consequently, **conservation holds for the actually-selected branch**, for
    every sample and every fact combination — the end-to-end statement. -/
theorem classified_conserves (s : Sample Line) (f : Facts Line) :
    Sample.total (s.charge (classify s f)) = s.cpu :=
  charge_total s (classify s f)

/-! ## The heuristic boundary, stated honestly

Which branch is *correct* depends on whether the signal was deferred inside a C
call — not observable from the sample. We prove the conditional: IF the sample
truly landed in native code, branch A is exactly right. The classifier's
accuracy is the (unformalized, engineering) hypothesis that `is_at_call` detects
exactly that case. -/

/-- If the sample's true attribution is entirely native (`trueNative = cpu`),
    then branch A charges exactly the truth: all `cpu` to native, none to
    Python. So branch A is *correct* precisely when the at-CALL detection
    correctly identifies an in-native sample — the heuristic's proof obligation,
    isolated. -/
theorem branchA_exact_if_in_call (s : Sample Line) (trueNative : ℚ)
    (h : trueNative = s.cpu) :
    totalNative (s.charge .atCall) = trueNative
    ∧ totalPython (s.charge .atCall) = 0 := by
  obtain ⟨hn, hp⟩ := split_atCall s
  exact ⟨by rw [hn, h], hp⟩

end Scalene.PythonNativeClassifier
