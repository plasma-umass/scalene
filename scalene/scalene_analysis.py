import ast
import importlib
import os
import sys

if sys.version_info < (3,9):
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
            package_dir = os.path.dirname(package.__file__)
            for root, dirs, files in os.walk(package_dir):
                for filename in files:
                    if filename.endswith('.so') or filename.endswith('.pyd'):
                        return True
            result = False
        except ImportError:
            result = False
        except AttributeError:
            # No __file__, meaning it's built-in. Let's call it native.
            result = True
        except ModuleNotFoundError:
            # This module is not installed; fail gracefully.
            result = False
        
    
    @staticmethod
    def get_imported_modules(source):
        """
        Extracts a list of imported modules from the given source code.

        Parameters:
        - source (str): The source code to be analyzed.

        Returns:
        - imported_modules (list[str]): A list of import statements.
        """

        # Parse the source code into an abstract syntax tree
        tree = ast.parse(source)
        imported_modules = []

        # Iterate through the nodes in the syntax tree
        for node in ast.walk(tree):
            # Check if the node represents an import statement
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                imported_modules.append(ast.unparse(node))

        return imported_modules


    @staticmethod
    def get_native_imported_modules(source):
        """
        Extracts a list of **native** imported modules from the given source code.

        Parameters:
        - source (str): The source code to be analyzed.

        Returns:
        - imported_modules (list[str]): A list of import statements.
        """

        # Parse the source code into an abstract syntax tree
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
                if ScaleneAnalysis.is_native(node.module):
                    imported_modules.append(ast.unparse(node))

        return imported_modules
    
   
    @staticmethod
    def find_regions(src):
        """This function collects the start and end lines of all loops and functions in the AST, and then uses these to determine the narrowest region containing each line in the source code (that is, loops take precedence over functions."""
        srclines = src.split("\n")
        # Filter out the first line if in a Jupyter notebook and it starts with a magic (% or %%).
        if "ipykernel" in sys.modules and srclines[0][0] == '%':
            srclines.pop(0)
            src = ''.join(srclines)
        tree = ast.parse(src)
        regions = {}
        loops = {}
        functions = {}
        for node in ast.walk(tree):
            if isinstance(node, (ast.For, ast.While)):
                for line in range(node.lineno, node.end_lineno+1):
                    loops[line] = (node.lineno, node.end_lineno)
            if isinstance(node, ast.FunctionDef):
                for line in range(node.lineno, node.end_lineno+1):
                    functions[line] = (node.lineno, node.end_lineno)
        for lineno, line in enumerate(srclines, 1):
            if lineno in loops:
                regions[lineno] = loops[lineno]
            elif lineno in functions:
                regions[lineno] = functions[lineno]
            else:
                regions[lineno] = (lineno, lineno)
        return regions
    
