# Jupyter support

try:
    from IPython.core.magic import (Magics, magics_class, line_magic, cell_magic, line_cell_magic)
    from IPython.core.page import page
    from scalene.scalene_arguments import ScaleneArguments
    import os
    import tempfile
    import textwrap
    
    @magics_class
    class ScaleneMagics(Magics):

        @cell_magic
        def scalene(self, line, cell=None) -> None:
            # TODO: parse arguments from line
            if cell:
                from scalene import scalene_profiler
                args = ScaleneArguments()
                args.cpu_only = True # full Scalene is not yet working
                # Create a temporary file to hold the supplied code.
                code = cell # "def execution_cell():\n" + textwrap.indent(cell, "\t") + "\nexecution_cell()"
                tmpfile = tempfile.NamedTemporaryFile(mode="w+", delete=False, prefix="scalene_", suffix=".py")
                tmpfile.write(code)
                tmpfile.close()
                # For now, only profile the temporary file (that is, the current cell).
                args.profile_only = os.path.basename(tmpfile.name)
                profiler = scalene_profiler.Scalene(args, tmpfile.name)
                profiler.run_profiler(args, [tmpfile.name])

    def load_ipython_extension(ip):
        ip.register_magics(ScaleneMagics)
except:
    pass

