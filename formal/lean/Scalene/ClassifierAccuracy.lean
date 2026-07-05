/-
  Python/native classifier ACCURACY — the branch-correctness question.

  `PythonNativeClassifier.lean` proved the classifier *conserves* the CPU budget
  in every branch, but left the accuracy question — is the branch it picks the
  *right* one? — as an engineering heuristic (HANDOFF §7 step 5). This file
  models that question honestly. Accuracy cannot be a bare theorem: which branch
  is correct depends on where the program truly was when the timer fired, which
  is unobservable *except* through one operational fact about CPython. So we:

    1. State that fact as an explicit hypothesis (CPython signal-delivery
       semantics), the classifiers' shared proof obligation.
    2. Prove each classifier is EXACTLY correct relative to it.
    3. Compare the TWO code paths — the main-thread hybrid
       (scalene_cpu_profiler.py:251-341) and the worker-thread pure-bytecode
       classifier (`_update_thread_stats`, :458-466) — proving where they agree
       and characterizing where they deliberately diverge.

  ── THE OPERATIONAL FACT (the honest hypothesis) ──────────────────────────────
  CPython runs a Python-level signal handler only at a bytecode boundary. So if
  the sampling timer expires *inside* a C call, the handler runs when the call
  returns, with `f_lasti` pointing at the CALL opcode; if it expires while
  executing Python, `f_lasti` points at a non-CALL opcode. Hence the observable
  `atCall := is_call_function(frame.f_lasti)` satisfies

      atCall = true   ↔   the timer truly fired while suspended in a C call.

  We call this `SigDeliverySound`. It is NOT proved here (it is a property of the
  CPython runtime + the interposer's synchronous stamping); it is the precise
  contract the accuracy proofs rest on — stated, not hidden.

  ── WHAT WE PROVE ─────────────────────────────────────────────────────────────
    * `worker_classifier_correct` — the worker-thread classifier (native iff
      atCall) attributes to native EXACTLY the samples that truly landed in a C
      call, under SigDeliverySound. Perfectly accurate given the hypothesis.
    * `main_branchA_correct` — the main-thread branch A (at-CALL, wall-clock /
      thread-sampled mode) is likewise exact under SigDeliverySound.
    * `main_worker_agree` — in the SHARED regime (`use_call_attribution` true:
      wall-clock or Apple-SME thread-sampled), the two paths make the SAME
      Python/native decision for the same sample. One classifier, two call sites.
    * `deferral_route_iff` / `deferral_formula_exact` — in virtual-time mode the
      main path instead uses the interval-deferral formula
      (`c_time = elapsed − interval`); we characterize exactly when that route is
      taken and prove it exact under the *deferral* hypothesis (native time = the
      measured excess). This is why the paths differ: only a thread with its own
      virtual timer can measure deferral, so the worker path cannot use it.
    * `misclassified_when_unsound` / `missed_when_unsound` — if SigDeliverySound
      fails (a smeared sample: at a CALL opcode but not truly in a call, or vice
      versa), the bytecode classifier is wrong — pinning down the two-sided error
      the hypothesis rules out.

  All over ℚ; no `sorry`.
-/
import Mathlib

namespace Scalene.ClassifierAccuracy

/-- The true execution state when the sampling timer fired. -/
inductive ExecState where
  | inPython   -- executing a Python bytecode
  | inCall     -- suspended inside a native (C) call
deriving DecidableEq

/-- A CPU sample's ground truth: the true state, the total CPU time to attribute
    (`cpu ≥ 0`), and the observable `atCall` bit the handler reads from
    `f_lasti` (`is_call_function`). -/
structure Sample where
  state  : ExecState
  cpu    : ℚ
  atCall : Bool
  cpuNonneg : 0 ≤ cpu

/-- **The true native time of a sample**: all of `cpu` if the timer truly fired
    inside a C call, else 0. (The bytecode classifiers are binary — a sample is
    wholly native or wholly Python — so the ground truth is too.) -/
def trueNative (s : Sample) : ℚ :=
  match s.state with
  | .inCall   => s.cpu
  | .inPython => 0

def truePython (s : Sample) : ℚ := s.cpu - trueNative s

/-- **CPython signal-delivery soundness** — the operational hypothesis. The
    observable at-CALL bit is set iff the timer truly fired inside a C call.
    This is the property of the runtime that the whole accuracy argument rests
    on; discharged by CPython's bytecode-boundary signal delivery + synchronous
    C++ stamping, not proved here. -/
def SigDeliverySound (s : Sample) : Prop :=
  s.atCall = true ↔ s.state = .inCall

/-! ## 1. The worker-thread classifier (`_update_thread_stats`, :458-466)

Pure bytecode test: charge all `normalized_time` to native iff the frame is at a
CALL opcode; else all Python. No interval, no deferral formula. -/

/-- Native time the worker classifier charges. -/
def workerNative (s : Sample) : ℚ := if s.atCall then s.cpu else 0

def workerPython (s : Sample) : ℚ := if s.atCall then 0 else s.cpu

/-- **The worker classifier is exactly correct — given signal-delivery
    soundness.** It attributes to native precisely the samples that truly landed
    in a C call. No approximation: under the hypothesis, `workerNative =
    trueNative` and `workerPython = truePython`. -/
theorem worker_classifier_correct (s : Sample) (h : SigDeliverySound s) :
    workerNative s = trueNative s ∧ workerPython s = truePython s := by
  unfold SigDeliverySound at h
  cases hst : s.state with
  | inCall =>
      have hac : s.atCall = true := h.mpr hst
      simp [workerNative, workerPython, trueNative, truePython, hac, hst]
  | inPython =>
      have hac : s.atCall = false := by
        by_contra hne
        have htrue : s.atCall = true := by cases s.atCall <;> simp_all
        rw [h.mp htrue] at hst; exact absurd hst (by simp)
      simp [workerNative, workerPython, trueNative, truePython, hac, hst]

/-! ## 2. The main-thread branch A (:256-275), wall-clock / thread-sampled mode

`use_call_attribution = (not use_virtual_time) ∨ thread_sampled`. When that
holds AND the frame is at a CALL, branch A charges ALL `cpu` to native — the
same decision as the worker classifier. -/

/-- Whether the main path uses the at-CALL (bytecode) route, mirroring
    `use_call_attribution` (:256-257). -/
def useCallAttribution (useVirtualTime threadSampled : Bool) : Bool :=
  (! useVirtualTime) || threadSampled

/-- Native time the main path charges *when it takes the at-CALL route*
    (branch A if atCall, else the deferral formula handles it — modeled in §3).
    Here we model the branch-A decision: all-native iff atCall. -/
def mainCallRouteNative (s : Sample) : ℚ := if s.atCall then s.cpu else 0

/-- **Main-thread branch A is exact under soundness** — identical statement to
    the worker classifier, because branch A makes the identical decision. -/
theorem main_branchA_correct (s : Sample) (h : SigDeliverySound s) :
    mainCallRouteNative s = trueNative s := by
  have := (worker_classifier_correct s h).1
  unfold workerNative at this
  unfold mainCallRouteNative
  exact this

/-! ## 3. Comparing the two paths -/

/-- **The two paths agree in the shared regime.** Whenever the main path uses
    the call-attribution route (wall-clock or Apple-SME thread-sampled mode), its
    at-CALL native decision is byte-for-byte the worker classifier's. So Scalene
    runs *one* classifier from two call sites in that regime — no inconsistency
    between how main-thread and worker-thread native time are decided. -/
theorem main_worker_agree (s : Sample) (useVirtualTime threadSampled : Bool)
    (_hmode : useCallAttribution useVirtualTime threadSampled = true) :
    mainCallRouteNative s = workerNative s := by
  unfold mainCallRouteNative workerNative
  rfl

/-- Corollary: in the shared regime, since the main branch-A decision equals the
    worker's and (under soundness) the worker's is exact, the main path is exact
    there too — one correctness proof covers both call sites. -/
theorem main_worker_both_exact (s : Sample) (useVirtualTime threadSampled : Bool)
    (_hmode : useCallAttribution useVirtualTime threadSampled = true)
    (h : SigDeliverySound s) :
    mainCallRouteNative s = trueNative s ∧ workerNative s = trueNative s :=
  ⟨main_branchA_correct s h, (worker_classifier_correct s h).1⟩

/-! ## 4. Why the paths diverge: the virtual-time deferral formula

In virtual-time mode (`use_call_attribution = false`) the main path does NOT use
the bytecode bit; it uses the interval-deferral formula
(scalene_cpu_profiler.py:134-135): `python_time = interval`,
`c_time = max(elapsed − interval, 0)`. A worker thread has no virtual timer to
measure `elapsed − interval` against, so it *cannot* take this route — the
divergence is by design, not inconsistency. -/

/-- The deferral formula's native charge: the CPU time beyond the timer interval,
    which (when signals were deferred during a C call) is native time that
    accrued while the handler was pending. `interval, elapsed ≥ 0`. -/
def deferralNative (interval elapsed : ℚ) : ℚ := max (elapsed - interval) 0

/-- **The deferral route is taken exactly in virtual-time, non-thread-sampled
    mode.** `use_call_attribution = false` forces `useVirtualTime = true` and
    `threadSampled = false` — the only configuration in which the main path uses
    the interval formula instead of the bytecode bit. This characterizes *when*
    the two paths diverge: precisely when a real virtual timer is available (so
    deferral can be measured) and no helper thread is sampling. -/
theorem deferral_route_iff (useVirtualTime threadSampled : Bool) :
    useCallAttribution useVirtualTime threadSampled = false
      ↔ useVirtualTime = true ∧ threadSampled = false := by
  unfold useCallAttribution
  cases useVirtualTime <;> cases threadSampled <;> simp

/-- **Deferral formula is exact under the deferral hypothesis.** If the true
    native time equals the measured excess `elapsed − interval` (i.e. the timer
    genuinely fired during a C call and stayed pending for exactly that excess),
    and the excess is non-negative, then `deferralNative` reports it exactly.
    This is the virtual-time counterpart to bytecode accuracy: the interval
    formula is right precisely when native time shows up as timer-deferral. -/
theorem deferral_formula_exact (interval elapsed trueNat : ℚ)
    (hdefer : trueNat = elapsed - interval) (hexcess : interval ≤ elapsed) :
    deferralNative interval elapsed = trueNat := by
  unfold deferralNative
  rw [hdefer, max_eq_left (by linarith)]

/-- If the excess is negative (the signal fired while Python was running, so no
    deferral occurred), the deferral formula reports 0 native time — which is
    exactly right *when* there was truly no native call. This is the
    complementary exact case, and also the blind spot the code comments note
    (:127-129): native time that occurred earlier but wasn't deferred is missed
    by this route — which is why wall-clock mode adds the bytecode test. -/
theorem deferral_formula_zero_when_no_excess (interval elapsed : ℚ)
    (hno : elapsed ≤ interval) :
    deferralNative interval elapsed = 0 := by
  unfold deferralNative
  exact max_eq_right (by linarith)

/-! ## 5. What accuracy costs when the hypothesis fails

Signal-delivery soundness is a hypothesis. If it fails — a *smeared* sample that
lands at a CALL opcode without truly being in a call (or vice versa) — the
bytecode classifier is wrong. We pin the exact error, so the reliance on the
hypothesis is explicit and quantified. -/

/-- **Without soundness, the bytecode classifier can be wrong.** A sample at a
    CALL opcode (`atCall = true`) but truly executing Python (`inPython`) is
    charged fully native by the worker/main classifier, while its true native
    time is 0 — an error of the whole `cpu`. This is the precise failure mode
    the SigDeliverySound hypothesis rules out. -/
theorem misclassified_when_unsound :
    ∃ s : Sample, ¬ SigDeliverySound s ∧ workerNative s ≠ trueNative s := by
  refine ⟨⟨.inPython, 1, true, by norm_num⟩, ?_, ?_⟩
  · unfold SigDeliverySound; simp
  · unfold workerNative trueNative; simp

/-- Symmetric failure: truly in a call but the bytecode says otherwise
    (`atCall = false`) — the whole `cpu` is charged to *Python* when it should be
    native, so `workerPython` overshoots `truePython`. Together with the above,
    this shows soundness is exactly the two-sided condition the classifier needs:
    a false positive misattributes to native, a false negative to Python. -/
theorem missed_when_unsound :
    ∃ s : Sample, ¬ SigDeliverySound s ∧ workerPython s ≠ truePython s := by
  refine ⟨⟨.inCall, 1, false, by norm_num⟩, ?_, ?_⟩
  · unfold SigDeliverySound; simp
  · unfold workerPython truePython trueNative; simp

end Scalene.ClassifierAccuracy
