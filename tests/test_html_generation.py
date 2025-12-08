#!/usr/bin/env python3
"""Test for HTML profile generation from CLI."""
import json
import os
import pathlib
import subprocess
import sys
import tempfile


def create_test_script(tmppath: pathlib.Path) -> pathlib.Path:
    """Create a simple test script that generates enough work to profile."""
    test_script = tmppath / "test_script.py"
    test_script.write_text("""
def work():
    total = 0
    # Reduced iteration count for faster tests while still generating profile data
    for i in range(1000000):
        total += i
    return total

if __name__ == "__main__":
    result = work()
    print(f"Result: {result}")
""")
    return test_script


def test_html_generation_with_outfile():
    """Test that --html --outfile generates both HTML and JSON files correctly."""
    with tempfile.TemporaryDirectory(prefix="scalene_test_") as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        outfile = tmppath / "profile.html"
        jsonfile = tmppath / "profile.json"
        
        test_script = create_test_script(tmppath)
        
        # Run scalene with --html --outfile
        cmd = [
            sys.executable,
            "-m",
            "scalene",
            "--no-browser",
            "--html",
            "--outfile",
            str(outfile),
            "---",
            "python",
            str(test_script),
        ]
        
        proc = subprocess.run(cmd, capture_output=True, timeout=60)
        stdout = proc.stdout.decode("utf-8")
        stderr = proc.stderr.decode("utf-8")
        
        # Check that the command succeeded
        if proc.returncode != 0:
            print("STDOUT:", stdout)
            print("STDERR:", stderr)
            raise AssertionError(f"scalene exited with code {proc.returncode}")
        
        # Check that the HTML file was created
        assert outfile.exists(), f"HTML file {outfile} was not created"
        
        # Check that the HTML file is not empty and contains expected content
        html_content = outfile.read_text()
        assert len(html_content) > 1000, "HTML file is too small"
        assert "<!DOCTYPE html>" in html_content or "scalene" in html_content.lower(), \
            "HTML file doesn't appear to be valid HTML"
        assert "test_script.py" in html_content, "HTML file doesn't contain script name"
        
        # Check that the JSON file was also created as an intermediate
        assert jsonfile.exists(), f"JSON file {jsonfile} was not created"
        
        # Verify JSON is valid
        json_content = jsonfile.read_text()
        profile_data = json.loads(json_content)
        assert len(profile_data) > 0, "JSON profile is empty"
        
        print("✓ HTML generation test passed")


def test_html_generation_without_outfile():
    """Test that --html without --outfile generates profile.html in current directory."""
    with tempfile.TemporaryDirectory(prefix="scalene_test_") as tmpdir:
        tmppath = pathlib.Path(tmpdir)
        
        test_script = create_test_script(tmppath)
        
        # Change to temp directory to avoid polluting the working directory
        original_cwd = os.getcwd()
        try:
            os.chdir(tmppath)
            
            # Run scalene with --html but no --outfile
            cmd = [
                sys.executable,
                "-m",
                "scalene",
                "--no-browser",
                "--html",
                str(test_script),
            ]
            
            proc = subprocess.run(cmd, capture_output=True, timeout=60)
            stdout = proc.stdout.decode("utf-8")
            stderr = proc.stderr.decode("utf-8")
            
            # Check that the command succeeded
            if proc.returncode != 0:
                print("STDOUT:", stdout)
                print("STDERR:", stderr)
                raise AssertionError(f"scalene exited with code {proc.returncode}")
            
            # Check that profile.html was created in current directory
            profile_html = tmppath / "profile.html"
            assert profile_html.exists(), "profile.html was not created in current directory"
            
            # Check that the HTML file contains expected content
            html_content = profile_html.read_text()
            assert len(html_content) > 1000, "HTML file is too small"
            
            print("✓ HTML generation without outfile test passed")
        finally:
            os.chdir(original_cwd)


if __name__ == "__main__":
    test_html_generation_with_outfile()
    test_html_generation_without_outfile()
    print("\nAll HTML generation tests passed!")
