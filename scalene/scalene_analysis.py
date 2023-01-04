import ast

class ScaleneAnalysis:

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
    
