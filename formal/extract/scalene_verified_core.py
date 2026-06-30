# ============================================================================
# GENERATED — DO NOT EDIT BY HAND.
#
# Extracted from formal/extract/ScaleneExtract.lean via LeanToPython
# (https://github.com/emeryberger/LeanToPython) from Lean defs that are PROVEN
# CORRECT in formal/lean/Scalene/{Attribution,SpaceSaving}.lean:
#   space_saving_step  -> capacity bound (SpaceSaving.step_withinCap/fold_withinCap)
#   c_time_ns/total_*  -> CPU Python/C split conservation (Attribution)
#   python_fraction_ppm-> result in [0,1]              (Attribution.pythonFraction_*)
#   python_bytes       -> python bytes <= total count  (Attribution.pythonBytes_le_count)
#   footprint_delta    -> footprint conservation        (Attribution.footprint_conserved)
#
# Regenerate:  (in a LeanToPython checkout, with ScaleneExtract.lean copied in)
#   lake env lean ScaleneExtract.lean > scalene_verified_core.py
#
# Used by tests/test_verified_space_saving.py as a verified reference ORACLE
# that the production scalene_utility._space_saving_increment is checked against.
# ============================================================================

# Generated from ScaleneVerified

from __future__ import annotations
from dataclasses import dataclass
import functools
from typing import Any, Callable

@dataclass
class isFalse:
    field_0: Any

@dataclass
class isTrue:
    field_0: Any

Decidable = isFalse | isTrue

@dataclass
class List_nil:
    pass

@dataclass
class List_cons:
    field_0: Any
    field_1: Any

List = List_nil | List_cons

# Lean: ScaleneVerified.cTimeNs
def c_time_ns(elapsed_ns: int, python_ns: int) -> int:
    _x_176 = python_ns <= elapsed_ns
    if _x_176:
        _x_185 = elapsed_ns - python_ns
        return _x_185
    else:
        _x_178 = 0
        return 0

# Lean: ScaleneVerified.totalTimeNs
def total_time_ns(elapsed_ns_0: int, python_ns_1: int) -> int:
    _x_191 = c_time_ns(elapsed_ns_0, python_ns_1)
    _x_192 = python_ns_1 + _x_191
    return _x_192

# Lean: ScaleneVerified.pythonFractionPpm
def python_fraction_ppm(python_count: int, c_count: int) -> int:
    _x_199 = python_count + c_count
    _x_200 = 0
    _x_203 = _x_199 == 0
    _x_204 = True
    if _x_203:
        return 0
    else:
        _x_213 = 1000000
        _x_216 = python_count * 1000000
        _x_217 = _x_216 // _x_199
        return _x_217

# Lean: ScaleneVerified.pythonBytes
def python_bytes(count: int, python_count_2: int, c_count_3: int) -> int:
    _x_227 = python_fraction_ppm(python_count_2, c_count_3)
    _x_228 = _x_227 * count
    _x_229 = 1000000
    _x_232 = _x_228 // 1000000
    return _x_232

# Lean: ScaleneVerified.footprintDelta
def footprint_delta(is_malloc: bool, count_4: int) -> int:
    _x_234 = True
    if is_malloc:
        return count_4
    else:
        _x_239 = -count_4
        return _x_239

# Lean: ScaleneVerified.hasKey
def has_key(t: list[tuple[int, int]], k: int) -> bool:
    def _f_247(p: tuple[int, int]):
        _x_245 = p[0]
        _x_246 = _x_245 == k
        return _x_246
    _x_248 = any(_f_247(x) for x in t)
    return _x_248

# Lean: ScaleneVerified.bump
def bump(t_5: list[tuple[int, int]], k_6: int) -> list[tuple[int, int]]:
    def _f_268(p_7: tuple[int, int]):
        _x_252 = p_7[0]
        _x_253 = _x_252 == k_6
        _x_254 = True
        if _x_253:
            _x_261 = p_7[1]
            _x_262 = 1
            _x_265 = _x_261 + 1
            _x_266 = (_x_252, _x_265)
            return _x_266
        else:
            return p_7
    _x_269 = [_f_268(x) for x in t_5]
    return _x_269

# Lean: ScaleneVerified.minCount
def min_count(x_271: list[tuple[int, int]]) -> int:
    def _f_275():
        _x_272 = 0
        return 0
    _alt_276 = _f_275
    def _f_278(p_8: tuple[int, int]):
        _x_277 = p_8[1]
        return _x_277
    _alt_279 = _f_278
    def _f_284(p_9: tuple[int, int], q: tuple[int, int], r: list[tuple[int, int]]):
        _x_280 = p_9[1]
        _x_281 = [q] + r
        _x_282 = min_count(_x_281)
        _x_283 = min(_x_280, _x_282)
        return _x_283
    _alt_285 = _f_284
    if len(x_271) == 0:
        _x_287 = _alt_276()
        return _x_287
    else:
        head_288 = x_271[0]
        tail_289 = x_271[1:]
        if len(tail_289) == 0:
            _x_290 = _alt_279(head_288)
            return _x_290
        else:
            head_291 = tail_289[0]
            tail_292 = tail_289[1:]
            _x_293 = _alt_285(head_288, head_291, tail_292)
            return _x_293

# Lean: ScaleneVerified.dropFirstWithCount
def drop_first_with_count(x_297: list[tuple[int, int]], x_298: int) -> list[tuple[int, int]]:
    def _f_301(x_299: int):
        _x_300 = []
        return _x_300
    _alt_302 = _f_301
    def _f_314(p_10: tuple[int, int], rest: list[tuple[int, int]], m: int):
        _x_305 = p_10[1]
        _x_306 = _x_305 == m
        _x_307 = True
        if _x_306:
            return rest
        else:
            _x_310 = drop_first_with_count(rest, m)
            _x_311 = [p_10] + _x_310
            return _x_311
    _alt_315 = _f_314
    if len(x_297) == 0:
        _x_316 = _alt_302(x_298)
        return _x_316
    else:
        head_317 = x_297[0]
        tail_318 = x_297[1:]
        _x_319 = _alt_315(head_317, tail_318, x_298)
        return _x_319

# Lean: ScaleneVerified.spaceSavingStep
def space_saving_step(cap: int, t_11: list[tuple[int, int]], k_12: int) -> list[tuple[int, int]]:
    _x_322 = has_key(t_11, k_12)
    _x_323 = True
    if _x_322:
        _x_348 = bump(t_11, k_12)
        return _x_348
    else:
        _x_326 = len(t_11)
        _x_327 = _x_326 < cap
        if _x_327:
            _x_341 = 1
            _x_344 = (k_12, 1)
            _x_345 = [_x_344] + t_11
            return _x_345
        else:
            _x_329 = min_count(t_11)
            _x_333 = 1
            _x_336 = _x_329 + 1
            _x_337 = (k_12, _x_336)
            _x_338 = drop_first_with_count(t_11, _x_329)
            _x_339 = [_x_337] + _x_338
            return _x_339


