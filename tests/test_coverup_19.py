# file scalene/scalene_analysis.py:16-42
# lines [21, 22, 23, 24, 25, 26, 27, 28, 29, 30, 31, 32, 33, 35, 36, 38, 39, 41, 42]
# branches ['24->25', '24->30', '26->27', '26->30', '27->26', '27->28', '28->27', '28->29']

import os
import pytest
import tempfile
import shutil
import sys
from scalene.scalene_analysis import ScaleneAnalysis

@pytest.fixture
def create_native_package():
    # Create a temporary directory to simulate a native package with a .so file
    temp_dir = tempfile.mkdtemp()
    package_name = "native_package"
    package_dir = os.path.join(temp_dir, package_name)
    os.makedirs(package_dir)
    init_file = os.path.join(package_dir, "__init__.py")
    so_file = os.path.join(package_dir, "module.so")
    with open(init_file, "w") as f:
        f.write("# This is a simulated native package")
    with open(so_file, "w") as f:
        f.write("This is a simulated shared object file")
    # Add the temporary directory to sys.path so it can be imported
    sys.path.append(temp_dir)
    yield package_name
    # Cleanup
    sys.path.remove(temp_dir)
    shutil.rmtree(temp_dir)

def test_is_native(create_native_package):
    package_name = create_native_package
    assert ScaleneAnalysis.is_native(package_name) == True

def test_is_not_native():
    non_existent_package = "non_existent_package"
    assert ScaleneAnalysis.is_native(non_existent_package) == False

def test_is_builtin():
    builtin_package = "sys"
    assert ScaleneAnalysis.is_native(builtin_package) == True

def test_is_python_package():
    python_package = "json"
    assert ScaleneAnalysis.is_native(python_package) == False
