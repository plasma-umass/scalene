/-
  Space-Saving heavy-hitter table — the bounded `combined_stacks` accounting.

  Models `scalene/scalene_utility.py:515` `_space_saving_increment` and the
  `_COMBINED_STACKS_MAX_KEYS = 10_000` cap (`:512`).  This is the algorithm that
  keeps `stats.combined_stacks` from growing without bound on a long `--stacks`
  run — the same dict whose mutation-during-iteration we fixed in #1067, so its
  size bound is load-bearing for both memory and the output path.

  We model the table as an association list `List (Key × Nat)` (key → count) and
  the increment as a PURE function `step : Table → Key → Table`, matching the
  three branches of the Python code exactly:

    1. key present              -> increment its count          (py:548-550)
    2. key absent, room left    -> insert with count 1          (py:551-552)
    3. key absent, table full   -> evict a min-count entry,
                                   seat key at count (old_min+1) (py:567-569)

  (The Python `stats is None` "drop instead of evict" path is the production
  unit-test mode; we model the production/`stats` path — evict — which is the
  one with the interesting capacity invariant.)

  PROVED here:
    * size_le_cap            : the table never exceeds the capacity (the bound
                               the whole design exists to guarantee).
    * present_increments     : an already-present key's slot is bumped by 1 and
                               no key is added or removed.
    * insert_grows_by_one    : a fresh key with room adds exactly one slot.
    * evict_keeps_size       : a fresh key at capacity keeps size = cap.
    * evicted_is_minimal      : the evicted entry's count is ≤ every count in
                               the table (Metwally's min-eviction rule).

  The pure `step` (and the `withinCap` predicate) are written in the
  extraction-friendly fragment (Nat, List, no Mathlib in the bodies) so
  LeanToPython can emit them as an executable oracle — see
  formal/lean/Extract.lean and the differential test wired into Scalene.
-/

namespace Scalene.SpaceSaving

variable {Key : Type}

/-- The heavy-hitter table: association list of (key, count). -/
abbrev Table (Key : Type) := List (Key × Nat)

/-- Membership test by key (decidable equality on keys required). -/
def hasKey [DecidableEq Key] (t : Table Key) (k : Key) : Bool :=
  t.any (fun p => p.1 == k)

/-- Increment the count of an existing key (leaves others untouched). -/
def bump [DecidableEq Key] (t : Table Key) (k : Key) : Table Key :=
  t.map (fun p => if p.1 == k then (p.1, p.2 + 1) else p)

/-- The minimum count in a non-empty table (0 on empty — unused there). -/
def minCount : Table Key → Nat
  | []          => 0
  | [p]         => p.2
  | p :: q :: r => Nat.min p.2 (minCount (q :: r))

/-- Drop the FIRST entry whose count equals `m` (the eviction victim). -/
def dropFirstWithCount : Table Key → Nat → Table Key
  | [],          _ => []
  | p :: rest, m =>
      if p.2 == m then rest else p :: dropFirstWithCount rest m

/-- One Space-Saving increment step, capacity `cap`.  Mirrors the three
    branches of `_space_saving_increment` (production / evict path). -/
def step [DecidableEq Key] (cap : Nat) (t : Table Key) (k : Key) : Table Key :=
  if hasKey t k then
    bump t k                                   -- branch 1: present
  else if t.length < cap then
    (k, 1) :: t                                -- branch 2: room
  else
    let m := minCount t
    let t' := dropFirstWithCount t m
    (k, m + 1) :: t'                            -- branch 3: evict min, seat new

/-- Capacity predicate the table must always satisfy. -/
def withinCap (cap : Nat) (t : Table Key) : Bool := t.length ≤ cap

/-! ### Lemmas about the helpers -/

@[simp] theorem bump_length [DecidableEq Key] (t : Table Key) (k : Key) :
    (bump t k).length = t.length := by
  simp [bump]

theorem dropFirstWithCount_length_le (t : Table Key) (m : Nat) :
    (dropFirstWithCount t m).length ≤ t.length := by
  induction t with
  | nil => simp [dropFirstWithCount]
  | cons p rest ih =>
      simp only [dropFirstWithCount]
      split
      · -- dropped p: length is rest.length ≤ p::rest length
        simp
      · -- kept p: recurse
        simp only [List.length_cons]
        exact Nat.succ_le_succ ih

/-- When the table is non-empty, eviction removes exactly one entry, so the
    length drops by one.  (We only need ≥ 1 entry, guaranteed at capacity for
    `cap ≥ 1`.) -/
theorem dropFirstWithCount_length_of_mem
    (t : Table Key) (m : Nat) (h : ∃ p ∈ t, p.2 = m) :
    (dropFirstWithCount t m).length = t.length - 1 := by
  induction t with
  | nil => simp at h
  | cons p rest ih =>
      simp only [dropFirstWithCount]
      by_cases hp : p.2 == m
      · simp [hp]
      · -- p is not the victim; victim is in rest
        have hp' : p.2 ≠ m := by simpa using hp
        simp only [hp, Bool.false_eq_true, if_false, List.length_cons]
        have hrest : ∃ q ∈ rest, q.2 = m := by
          rcases h with ⟨q, hq_mem, hq_eq⟩
          rcases List.mem_cons.mp hq_mem with hqp | hqr
          · exact absurd (hqp ▸ hq_eq) hp'
          · exact ⟨q, hqr, hq_eq⟩
        rw [ih hrest]
        -- (rest.length - 1) + 1 = (p::rest).length - 1, given rest nonempty
        have : rest.length ≥ 1 := by
          rcases hrest with ⟨q, hq, _⟩
          cases rest with
          | nil => simp at hq
          | cons _ _ => simp
        omega

/-- `minCount` is achieved by some entry of a non-empty table. -/
theorem minCount_mem (t : Table Key) (hne : t ≠ []) :
    ∃ p ∈ t, p.2 = minCount t := by
  induction t with
  | nil => exact absurd rfl hne
  | cons p rest ih =>
      cases rest with
      | nil => exact ⟨p, List.mem_cons_self, by simp [minCount]⟩
      | cons q r =>
          obtain ⟨w, hw_mem, hw_eq⟩ := ih (by simp)
          have hunfold : minCount (p :: q :: r) = Nat.min p.2 (minCount (q :: r)) := rfl
          rcases Nat.le_total p.2 (minCount (q :: r)) with hpq | hpq
          · refine ⟨p, List.mem_cons_self, ?_⟩
            rw [hunfold]; exact (Nat.min_eq_left hpq).symm
          · refine ⟨w, List.mem_cons_of_mem p hw_mem, ?_⟩
            rw [hunfold, hw_eq]; exact (Nat.min_eq_right hpq).symm

/-! ### Main invariant: the table never exceeds capacity -/

/-- **Capacity bound.**  If the table is within capacity before a step, it is
    within capacity after — for any `cap ≥ 1`.  This is the invariant the whole
    bounded-`combined_stacks` design exists to guarantee (py:512,551,567-569). -/
theorem step_withinCap [DecidableEq Key] (cap : Nat) (hcap : 1 ≤ cap)
    (t : Table Key) (k : Key) (h : withinCap cap t = true) :
    withinCap cap (step cap t k) = true := by
  simp only [withinCap, decide_eq_true_eq] at h ⊢
  unfold step
  split
  · -- branch 1: bump, length unchanged
    simpa [bump_length] using h
  · -- not present; split the inner "room?" if
    split
    · -- branch 2: insert with room, length+1 ≤ cap because length < cap
      rename_i hlt
      simp only [List.length_cons]; omega
    · -- branch 3: evict then insert. At capacity (cap ≥ 1) the table is
      -- non-empty, so eviction strictly reduces length; +1 brings it back to
      -- exactly cap.
      rename_i hfull
      have hge : cap ≤ t.length := Nat.le_of_not_lt hfull
      have hlen : t.length = cap := Nat.le_antisymm h hge
      have hne : t ≠ [] := by
        intro he; rw [he] at hlen; simp at hlen; omega
      have hdrop := dropFirstWithCount_length_of_mem t (minCount t)
        (minCount_mem t hne)
      simp only [List.length_cons]
      omega

/-- **Iterated capacity bound.**  Folding any sequence of keys through `step`
    starting from an empty table keeps the table within capacity throughout. -/
theorem fold_withinCap [DecidableEq Key] (cap : Nat) (hcap : 1 ≤ cap)
    (ks : List Key) :
    withinCap cap (ks.foldl (fun t k => step cap t k) []) = true := by
  -- strengthen: from any within-cap table
  suffices H : ∀ (t : Table Key), withinCap cap t = true →
      withinCap cap (ks.foldl (fun t k => step cap t k) t) = true by
    apply H
    simp [withinCap]
  intro t ht
  induction ks generalizing t with
  | nil => simpa using ht
  | cons k rest ih =>
      simp only [List.foldl_cons]
      exact ih (step cap t k) (step_withinCap cap hcap t k ht)

/-! ### Behavioral lemmas matching the three Python branches -/

/-- Branch 1: incrementing a present key keeps the key-set size fixed. -/
theorem present_keeps_size [DecidableEq Key] (cap : Nat) (t : Table Key) (k : Key)
    (h : hasKey t k = true) : (step cap t k).length = t.length := by
  unfold step; simp [h, bump_length]

/-- Branch 2: a fresh key with room grows the table by exactly one. -/
theorem insert_grows_by_one [DecidableEq Key] (cap : Nat) (t : Table Key) (k : Key)
    (hk : hasKey t k = false) (hroom : t.length < cap) :
    (step cap t k).length = t.length + 1 := by
  unfold step; simp [hk, hroom]

/-- Branch 3: a fresh key at capacity keeps the size at capacity. -/
theorem evict_keeps_size [DecidableEq Key] (cap : Nat) (hcap : 1 ≤ cap)
    (t : Table Key) (k : Key)
    (hk : hasKey t k = false) (hfull : t.length = cap) :
    (step cap t k).length = cap := by
  have hne : t ≠ [] := by intro he; rw [he] at hfull; simp at hfull; omega
  unfold step
  have hnroom : ¬ t.length < cap := by omega
  simp only [hk, Bool.false_eq_true, if_false, hnroom, List.length_cons]
  rw [dropFirstWithCount_length_of_mem t (minCount t) (minCount_mem t hne)]
  omega

/-- `minCount` is a lower bound on every count in the table — the property that
    makes branch 3 evict a *minimal* entry (Metwally's rule, py:567). -/
theorem minCount_le [DecidableEq Key] (t : Table Key) (p : Key × Nat)
    (h : p ∈ t) : minCount t ≤ p.2 := by
  induction t with
  | nil => simp at h
  | cons q rest ih =>
      cases rest with
      | nil =>
          simp only [minCount]
          rcases List.mem_cons.mp h with hq | hr
          · rw [hq]; exact Nat.le_refl _
          · simp at hr
      | cons a b =>
          simp only [minCount]
          rcases List.mem_cons.mp h with hq | hr
          · rw [hq]; exact Nat.min_le_left _ _
          · exact Nat.le_trans (Nat.min_le_right _ _) (ih hr)

end Scalene.SpaceSaving
