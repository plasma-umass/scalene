"""
This is bound very closely to the current implementation of 
the tests in `test/line_attribution_tests. 

The two things that matter are the number of loops, the size
of the allocations, and the exact line numbers. 


"""

expected_md5_sums = {
    "line_attribution_tests/loop_below_threshold.py": "7664a7dcc0f4ab94a44e431448b5f348",
    "line_attribution_tests/loop_with_one_alloc.py": "da9ff0aa223123c956049e940c3ef093",
    "line_attribution_tests/loop_with_multiple_lines.py": "48ce0e8693fe43b1ebb7eb75a0fd5832",
    "line_attribution_tests/loop_with_two_allocs.py": "71f337140aa25383525e56a6167cabf8",
    "line_attribution_tests/line_after_final_alloc.py": "ca8cdd44ea6e4a9c286c05facae6a721"
}

import subprocess
import tempfile
import sys
from typing import List
from pathlib import Path
from hashlib import md5
from scalene.scalene_json import ScaleneJSONSchema

N_LOOPS = 31
LOOP_ALLOC_LINENO = 5  #
OUT_OF_LOOP_ALLOC_LINENO = 9

def check_for_changes():
    errors = []
    for fname, expected_sum in expected_md5_sums.items():
        with open(fname, 'rb') as f:
            digest = md5(f.read()).hexdigest()
        if digest != expected_sum:
            errors.append(fname)
    assert len(errors) == 0, f'Detected change in file(s) {",".join(errors)}'

def get_line(scalene_profile: ScaleneJSONSchema, lineno: int):
    files = list(scalene_profile.files.keys())
    assert len(files) == 1
    filename = files[0]
    return scalene_profile.files[filename].lines[lineno - 1]




def get_profile(test_stem, outdir_p, test_dir):
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "scalene",
            "--cli", 
            "--json",
            "--outfile",
            outdir_p / f"{test_stem}.json",
            test_dir / f"{test_stem}.py",
        ],
        capture_output=True,
        check=True,
    )
    with open(outdir_p / f"{test_stem}.json", "r") as f:
        profile = ScaleneJSONSchema.model_validate_json(f.read())
    return (test_stem, profile)


def main():
    test_dir = Path(__file__).parent / "line_attribution_tests"
    with tempfile.TemporaryDirectory() as outdir:
        outdir_p = Path(outdir)
        one_alloc = get_profile("loop_with_one_alloc", outdir_p, test_dir)
        two_on_one_line = get_profile("loop_with_two_allocs", outdir_p, test_dir)
        below_threshold = get_profile("loop_below_threshold", outdir_p, test_dir)
        line_after_final_alloc = get_profile(
            "line_after_final_alloc", outdir_p, test_dir
        )
    errors = []
    for stem, profile in [one_alloc, two_on_one_line, line_after_final_alloc]:
        line = get_line(profile, LOOP_ALLOC_LINENO)
        if not line.n_mallocs == N_LOOPS:
            errors.append(f"Expected {N_LOOPS} distinct lines on {stem}, got {line.n_mallocs} on line {LOOP_ALLOC_LINENO}")

    bt_stem, bt_prof = below_threshold
    bt_line = get_line(bt_prof, LOOP_ALLOC_LINENO)
    if not bt_line.n_mallocs < N_LOOPS:
       errors.append(f"{bt_stem} makes smaller allocations than the allocation sampling window, so fewer than {N_LOOPS} allocations on {LOOP_ALLOC_LINENO} should be reported. Got {bt_line.n_mallocs} mallocs")

    for stem, profile in [one_alloc, two_on_one_line, below_threshold, line_after_final_alloc]:
        line = get_line(profile, OUT_OF_LOOP_ALLOC_LINENO)
        if not line.n_mallocs == 1:
            errors.append(f'Line {OUT_OF_LOOP_ALLOC_LINENO} in {stem} makes a large allocation, so it should be reported.')
    
    if len(errors) > 0:
        for error in errors:
            print(f'ERROR: {error}')
        for profile in [one_alloc, two_on_one_line, below_threshold, line_after_final_alloc]:
            print("\n\n\n\n")
            print(profile[1].model_dump_json(indent=4))
        exit(1)
    else:
        print("PASS")
        exit(0)
    
if __name__ == '__main__':
    main()