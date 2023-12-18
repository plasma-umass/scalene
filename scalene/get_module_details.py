import importlib
import sys

from importlib.abc import SourceLoader
from importlib.machinery import ModuleSpec
from types import CodeType, FrameType
from typing import (
    Any,
    Callable,
    Dict,
    List,
    Optional,
    Set,
    Tuple,
    Type,
    Union,
    cast,
)


def _get_module_details(
    mod_name: str,
    error: Type[Exception] = ImportError,
) -> Tuple[str, ModuleSpec, CodeType]:
    """Copy of `runpy._get_module_details`, but not private."""
    if mod_name.startswith("."):
        raise error("Relative module names not supported")
    pkg_name, _, _ = mod_name.rpartition(".")
    if pkg_name:
        # Try importing the parent to avoid catching initialization errors
        try:
            __import__(pkg_name)
        except ImportError as e:
            # If the parent or higher ancestor package is missing, let the
            # error be raised by find_spec() below and then be caught. But do
            # not allow other errors to be caught.
            if e.name is None or (
                e.name != pkg_name and not pkg_name.startswith(e.name + ".")
            ):
                raise
        # Warn if the module has already been imported under its normal name
        existing = sys.modules.get(mod_name)
        if existing is not None and not hasattr(existing, "__path__"):
            from warnings import warn

            msg = (
                "{mod_name!r} found in sys.modules after import of "
                "package {pkg_name!r}, but prior to execution of "
                "{mod_name!r}; this may result in unpredictable "
                "behaviour".format(mod_name=mod_name, pkg_name=pkg_name)
            )
            warn(RuntimeWarning(msg))

    try:
        spec = importlib.util.find_spec(mod_name)
    except (ImportError, AttributeError, TypeError, ValueError) as ex:
        # This hack fixes an impedance mismatch between pkgutil and
        # importlib, where the latter raises other errors for cases where
        # pkgutil previously raised ImportError
        msg = "Error while finding module specification for {!r} ({}: {})"
        if mod_name.endswith(".py"):
            msg += (
                f". Try using '{mod_name[:-3]}' instead of "
                f"'{mod_name}' as the module name."
            )
        raise error(msg.format(mod_name, type(ex).__name__, ex)) from ex
    if spec is None:
        raise error("No module named %s" % mod_name)
    if spec.submodule_search_locations is not None:
        if mod_name == "__main__" or mod_name.endswith(".__main__"):
            raise error("Cannot use package as __main__ module")
        try:
            pkg_main_name = mod_name + ".__main__"
            return _get_module_details(pkg_main_name, error)
        except error as e:
            if mod_name not in sys.modules:
                raise  # No module loaded; being a package is irrelevant
            raise error(
                ("%s; %r is a package and cannot " + "be directly executed")
                % (e, mod_name)
            )
    loader = spec.loader
    # use isinstance instead of `is None` to placate mypy
    if not isinstance(loader, SourceLoader):
        raise error(
            "%r is a namespace package and cannot be executed" % mod_name
        )
    try:
        code = loader.get_code(mod_name)
    except ImportError as e:
        raise error(format(e)) from e
    if code is None:
        raise error("No code object available for %s" % mod_name)
    return mod_name, spec, code
