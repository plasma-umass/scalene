import ast
import importlib
import os
import sys

from typing import cast, Any, Dict, List, Tuple

if sys.version_info < (3, 9):
    # ast.unparse only supported as of 3.9
    import astunparse

    ast.unparse = astunparse.unparse


class ScaleneAnalysis:
    @staticmethod
    def is_native(package_name: str) -> bool:
        """
        Returns whether a package is native or not.
        """
        result = False
        try:
            package = importlib.import_module(package_name)
            if package.__file__:
                package_dir = os.path.dirname(package.__file__)
                for root, dirs, files in os.walk(package_dir):
                    for filename in files:
                        if filename.endswith(".so") or filename.endswith(".pyd"):
                            return True
            result = False
        except ImportError:
            result = False
        except AttributeError:
            # No __file__, meaning it's built-in. Let's call it native.
            result = True
        except TypeError:
            # __file__ is there, but empty (os.path.dirname() returns TypeError).  Let's call it native.
            result = True
        except ModuleNotFoundError:
            # This module is not installed; fail gracefully.
            result = False
        return result

    @staticmethod
    def get_imported_modules(source: str) -> List[str]:
        """
        Extracts a list of imported modules from the given source code.

        Parameters:
        - source (str): The source code to be analyzed.

        Returns:
        - imported_modules (list[str]): A list of import statements.
        """

        # Parse the source code into an abstract syntax tree
        source = ScaleneAnalysis.strip_magic_line(source)
        tree = ast.parse(source)
        imported_modules = []

        # Iterate through the nodes in the syntax tree
        for node in ast.walk(tree):
            # Check if the node represents an import statement
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported_modules.append(ast.unparse(node))

        return imported_modules

    @staticmethod
    def get_native_imported_modules(source: str) -> List[str]:
        """
        Extracts a list of **native** imported modules from the given source code.

        Parameters:
        - source (str): The source code to be analyzed.

        Returns:
        - imported_modules (list[str]): A list of import statements.
        """

        # Parse the source code into an abstract syntax tree
        source = ScaleneAnalysis.strip_magic_line(source)
        tree = ast.parse(source)
        imported_modules = []

        # Add the module name to the list if it's native.
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                # Iterate through the imported modules in the statement
                for alias in node.names:
                    if ScaleneAnalysis.is_native(alias.name):
                        imported_modules.append(ast.unparse(node))
            # Check if the node represents an import from statement
            elif isinstance(node, ast.ImportFrom):
                node.module = cast(str, node.module)
                if ScaleneAnalysis.is_native(node.module):
                    imported_modules.append(ast.unparse(node))

        return imported_modules

    @staticmethod
    def find_regions(src: str) -> Dict[int, Tuple[int, int]]:
        """This function collects the start and end lines of all loops and functions in the AST, and then uses these to determine the narrowest region containing each line in the source code (that is, loops take precedence over functions."""
        # Filter out the first line if in a Jupyter notebook and it starts with a magic (% or %%).
        src = ScaleneAnalysis.strip_magic_line(src)
        srclines = src.split("\n")
        tree = ast.parse(src)
        regions = {}
        loops = {}
        functions = {}
        classes = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.ClassDef):
                assert node.end_lineno
                for line in range(node.lineno, node.end_lineno + 1):
                    classes[line] = (node.lineno, node.end_lineno)
            if isinstance(node, (ast.For, ast.While)):
                assert node.end_lineno
                for line in range(node.lineno, node.end_lineno + 1):
                    loops[line] = (node.lineno, node.end_lineno)
            if isinstance(node, ast.FunctionDef):
                assert node.end_lineno
                for line in range(node.lineno, node.end_lineno + 1):
                    functions[line] = (node.lineno, node.end_lineno)
        for lineno, _ in enumerate(srclines, 1):
            if lineno in loops:
                regions[lineno] = loops[lineno]
            elif lineno in functions:
                regions[lineno] = functions[lineno]
            elif lineno in classes:
                regions[lineno] = classes[lineno]
            else:
                regions[lineno] = (lineno, lineno)
        return regions

    @staticmethod
    def find_outermost_loop(src: str) -> Dict[int, Tuple[int, int]]:
        # Filter out the first line if in a Jupyter notebook and it starts with a magic (% or %%).
        src = ScaleneAnalysis.strip_magic_line(src)
        srclines = src.split("\n")
        tree = ast.parse(src)
        regions = {}

        def walk(node : ast.AST, current_outermost_region : Any, outer_class : Any) -> None:
            nonlocal regions
            if isinstance(
                node, (ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)
            ) or (
                isinstance(node, (ast.For, ast.While, ast.AsyncFor, ast.If))
                and (
                    outer_class is ast.FunctionDef
                    or outer_class is ast.AsyncFunctionDef
                    or outer_class is ast.ClassDef
                    or outer_class is None
                )
            ):
                current_outermost_region = (node.lineno, node.end_lineno)
                outer_class = node.__class__

            for child_node in ast.iter_child_nodes(node):
                walk(child_node, current_outermost_region, outer_class)
            if isinstance(node, ast.stmt):
                outermost_is_loop = outer_class in [
                    ast.For,
                    ast.AsyncFor,
                    ast.While,
                ]
                curr_is_block_not_loop = node.__class__ in [
                    ast.With,
                    ast.If,
                    ast.ClassDef,
                    ast.FunctionDef,
                    ast.AsyncFunctionDef,
                ]

                assert node.end_lineno
                for line in range(node.lineno, node.end_lineno + 1):
                    # NOTE: we update child nodes first (in the recursive call),
                    # so what we want this statement to do is attribute any lines that we haven't already
                    # attributed a region to.
                    if line not in regions:
                        if current_outermost_region and outermost_is_loop:
                            # NOTE: this additionally accounts for the case in which `node`
                            # is a loop. Any loop within another loop should take on the entirety of the
                            # outermost loop too
                            regions[line] = current_outermost_region
                        elif (
                            curr_is_block_not_loop
                            and len(srclines[line - 1].strip()) > 0
                        ):
                            # This deals with the case in which the current block is the header of another block, like
                            # a function or a class. Since the children are iterated over beforehand, if they're not
                            # in a loop, they are already in the region table.
                            regions[line] = (node.lineno, node.end_lineno)
                        else:
                            regions[line] = (line, line)

        walk(tree, None, None)
        for lineno, line in enumerate(srclines, 1):
            regions[lineno] = regions.get(lineno, (lineno, lineno))

        return regions

    @staticmethod
    def strip_magic_line(source: str) -> str:
        # Filter out any magic lines (starting with %) if in a Jupyter notebook
        import re

        srclines = map(lambda x: re.sub(r"^\%.*", "", x), source.split("\n"))
        source = "\n".join(srclines)
        return source
