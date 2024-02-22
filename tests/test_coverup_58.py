# file scalene/get_module_details.py:21-94
# lines [21, 22, 23, 24, 26, 27, 28, 29, 31, 32, 33, 37, 38, 40, 42, 43, 44, 46, 47, 50, 52, 54, 55, 56, 60, 61, 62, 63, 64, 66, 67, 68, 69, 70, 71, 72, 73, 74, 75, 76, 77, 78, 79, 80, 82, 84, 85, 86, 88, 89, 90, 91, 92, 93, 94]
# branches ['26->27', '26->28', '29->31', '29->54', '37->40', '37->42', '43->44', '43->54', '61->62', '61->66', '67->68', '67->69', '69->70', '69->82', '70->71', '70->72', '76->77', '76->78', '84->85', '84->88', '92->93', '92->94']

import importlib.util
import sys
from types import ModuleType
from importlib.abc import SourceLoader
from importlib.machinery import ModuleSpec
from types import CodeType
from typing import Tuple, Type
import pytest

class MockLoader(SourceLoader):
    def get_code(self, fullname):
        if fullname == "no_code_object":
            return None
        return compile("", "<string>", "exec")

    def get_source(self, fullname):
        return ""

    def get_data(self, path):
        return b''

    def get_filename(self, fullname):
        return "<mock>"

def test_get_module_details_relative_name_error():
    from scalene.get_module_details import _get_module_details
    with pytest.raises(ImportError):
        _get_module_details(".relative")

def test_get_module_details_namespace_package_error():
    from scalene.get_module_details import _get_module_details
    mod_name = "namespace_package"
    spec = ModuleSpec(name=mod_name, loader=None, origin="namespace origin")
    sys.modules[mod_name] = ModuleType(mod_name)
    sys.modules[mod_name].__spec__ = spec
    with pytest.raises(ImportError):
        _get_module_details(mod_name)
    del sys.modules[mod_name]

def test_get_module_details_no_code_object_error():
    from scalene.get_module_details import _get_module_details
    mod_name = "no_code_object"
    spec = ModuleSpec(name=mod_name, loader=MockLoader(), origin="no code origin")
    sys.modules[mod_name] = ModuleType(mod_name)
    sys.modules[mod_name].__spec__ = spec
    with pytest.raises(ImportError):
        _get_module_details(mod_name)
    del sys.modules[mod_name]

def test_get_module_details_package_as_main_error():
    from scalene.get_module_details import _get_module_details
    mod_name = "__main__"
    spec = ModuleSpec(name=mod_name, loader=MockLoader(), origin="main origin")
    spec.submodule_search_locations = []
    sys.modules[mod_name] = ModuleType(mod_name)
    sys.modules[mod_name].__spec__ = spec
    with pytest.raises(ImportError):
        _get_module_details(mod_name)
    del sys.modules[mod_name]

def test_get_module_details_already_imported_warning():
    from scalene.get_module_details import _get_module_details
    mod_name = "already.imported"
    pkg_name = "already"
    sys.modules[pkg_name] = ModuleType(pkg_name)
    sys.modules[mod_name] = ModuleType(mod_name)
    spec = ModuleSpec(name=mod_name, loader=MockLoader(), origin="already imported origin")
    sys.modules[mod_name].__spec__ = spec
    with pytest.warns(RuntimeWarning):
        _get_module_details(mod_name)
    del sys.modules[mod_name]
    del sys.modules[pkg_name]

def test_get_module_details_find_spec_error():
    from scalene.get_module_details import _get_module_details
    mod_name = "nonexistent.module"
    with pytest.raises(ImportError):
        _get_module_details(mod_name)

def test_get_module_details_success():
    from scalene.get_module_details import _get_module_details
    mod_name = "successful.module"
    spec = ModuleSpec(name=mod_name, loader=MockLoader(), origin="success origin")
    sys.modules[mod_name] = ModuleType(mod_name)
    sys.modules[mod_name].__spec__ = spec
    result_mod_name, result_spec, result_code = _get_module_details(mod_name)
    assert result_mod_name == mod_name
    assert result_spec == spec
    assert isinstance(result_code, CodeType)
    del sys.modules[mod_name]
