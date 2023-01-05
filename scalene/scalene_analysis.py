import ast

class ScaleneAnalysis:

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
            if isinstance(node, ast.Import):
                # Iterate through the imported modules in the statement
                for alias in node.names:
                    # If the module has an alias, add the alias to the list
                    if alias.asname:
                        imported_modules.append(f"import {alias.name} as {alias.asname}")
                    else:
                        # Add the module name to the list
                        imported_modules.append(f"import {alias.name}")
            # Check if the node represents an import from statement
            elif isinstance(node, ast.ImportFrom):
                # Add the module name to the list
                imported_modules.append(f"import {node.module}")

        return imported_modules

   
    @staticmethod
    def find_regions(src):
        """This function collects the start and end lines of all loops and functions in the AST, and then uses these to determine the narrowest region containing each line in the source code (that is, loops take precedence over functions."""
        srclines = src.split("\n")
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
    
