from setuptools import setup, find_packages
from setuptools.extension import Extension
from os import path, environ
import sys
import sysconfig
from pathlib import Path

# needed for isolated environment
sys.path.insert(0, str(Path(__file__).parent.resolve()))
from scalene.scalene_config import scalene_version
sys.path.pop(0)


if sys.platform == 'darwin':
    import sysconfig
    mdt = 'MACOSX_DEPLOYMENT_TARGET'
    target = environ[mdt] if mdt in environ else sysconfig.get_config_var(mdt)
    # target >= 10.9 is required for gcc/clang to find libstdc++ headers
    if [int(n) for n in target.split('.')] < [10, 9]:
        from os import execve
        newenv = environ.copy()
        newenv[mdt] = '10.9'
        execve(sys.executable, [sys.executable] + sys.argv, newenv)


def compiler_archs(compiler: str):
    """Discovers what platforms the given compiler supports; intended for MacOS use"""
    import tempfile
    import subprocess

    print(f"Compiler: {compiler}")
    arch_flags = []

    # see also the architectures tested for in .github/workflows/build-and-upload.yml
    for arch in ['x86_64', 'arm64', 'arm64e']:
        with tempfile.TemporaryDirectory() as tmpdir:
            cpp = Path(tmpdir) / 'test.cxx'; cpp.write_text('int main() {return 0;}\n')
            out = Path(tmpdir) / 'a.out'
            p = subprocess.run([compiler, "-arch", arch, str(cpp), "-o", str(out)], capture_output=True)
            if p.returncode == 0:
                arch_flags += ['-arch', arch]

    print(f"Discovered {compiler} arch flags: {arch_flags}")
    return arch_flags

def extra_compile_args():
    """Returns extra compiler args for platform."""
    if sys.platform == 'win32':
        return ['/std:c++14'] # for Visual Studio C++

    return ['-std=c++14']

def make_command():
#    return 'nmake' if sys.platform == 'win32' else 'make'  # 'nmake' isn't found on github actions' VM
    return 'make'

def dll_suffix():
    """Returns the file suffix ("extension") of a DLL"""
    if (sys.platform == 'win32'): return '.dll'
    if (sys.platform == 'darwin'): return '.dylib'
    return '.so'

def read_file(name):
    """Returns a file's contents"""
    with open(path.join(path.dirname(__file__), name), encoding="utf-8") as f:
        return f.read()

import setuptools.command.egg_info
class EggInfoCommand(setuptools.command.egg_info.egg_info):
    """Custom command to download vendor libs before creating the egg_info."""
    def run(self):
        if sys.platform != 'win32':
            self.spawn([make_command(), 'vendor-deps'])
        super().run()

# Force building platform-specific wheel to avoid the Windows wheel
# (which doesn't include libscalene, and thus would be considered "pure")
# being used for other platforms.
try:
    from wheel.bdist_wheel import bdist_wheel
    class BdistWheelCommand(bdist_wheel):
        def finalize_options(self):
            super().finalize_options()
            self.root_is_pure = False
except (ImportError, ModuleNotFoundError):
    # Disable wheel if `wheel` not installed.
    print("If this installation does not work, run `pip install setuptools wheel` and try again.")
    BdistWheelCommand = None

import setuptools.command.build_ext
class BuildExtCommand(setuptools.command.build_ext.build_ext):
    """Custom command that runs 'make' to generate libscalene, and also does MacOS
       supported --arch flag discovery."""

    def build_extensions(self):
        arch_flags = []
        if sys.platform == 'darwin':
            # The only sure way to tell which compiler build_ext is going to use
            # seems to be to customize a build_ext and look at its internal flags :(
            # Also, note that self.plat_name here isn't "...-universal2" even if that
            # is what we're building; that's only in bdist_wheel.plat_name.
            arch_flags += compiler_archs(self.compiler.compiler_cxx[0])
            for ext in self.extensions:
                # While the flags _could_ be different between the programs used for
                # C and C++ compilation and linking, we have no way to adapt them here,
                # so it seems best to just use them and let it error out if not recognized.
                ext.extra_compile_args += arch_flags
                ext.extra_link_args += arch_flags

        super().build_extensions()

        # No build of DLL for Windows currently.
        if sys.platform != 'win32':
            self.build_libscalene(arch_flags)   # XXX should we pass compiler_cxx here?

    def build_libscalene(self, arch_flags):
        scalene_temp = path.join(self.build_temp, 'scalene')
        scalene_lib = path.join(self.build_lib, 'scalene')
        libscalene = 'libscalene' + dll_suffix()
        self.mkpath(scalene_temp)
        self.mkpath(scalene_lib)
        self.spawn([make_command(), 'OUTDIR=' + scalene_temp,
                   'ARCH=' + ' '.join(arch_flags)])
        self.copy_file(path.join(scalene_temp, libscalene),
                       path.join(scalene_lib, libscalene))

    def copy_extensions_to_source(self):
        # self.inplace is temporarily overridden while running build_extensions,
        # so inplace copying (for pip install -e, setup.py develop) must be done here.

        super().copy_extensions_to_source()

        if sys.platform != 'win32':
            scalene_lib = path.join(self.build_lib, 'scalene')
            inplace_dir = self.get_finalized_command('build_py').get_package_dir('scalene')
            libscalene = 'libscalene' + dll_suffix()
            self.copy_file(path.join(scalene_lib, libscalene),
                           path.join(inplace_dir, libscalene))

get_line_atomic = Extension('scalene.get_line_atomic',
    include_dirs=['.', 'vendor/Heap-Layers', 'vendor/Heap-Layers/utility'],
    sources=['src/source/get_line_atomic.cpp'],
    extra_compile_args=extra_compile_args(),
    py_limited_api=True, # for binary compatibility
    language="c++"
)

pywhere = Extension('scalene.pywhere',
    include_dirs=['.', 'src', 'src/include'],
    depends = ['src/include/traceconfig.hpp'],
    sources = ['src/source/pywhere.cpp', 'src/source/traceconfig.cpp'],
    extra_compile_args=extra_compile_args(),
    py_limited_api=False,
    language="c++")

crdp = Extension('scalene.crdp',
    include_dirs=[],
    sources = ['vendor/crdp/crdp.c'],
    py_limited_api=True,
    language="c")

# If we're testing packaging, build using a ".devN" suffix in the version number,
# so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
# Numbering scheme: https://www.python.org/dev/peps/pep-0440
dev_build = ('.dev' + environ['DEV_BUILD']) if 'DEV_BUILD' in environ else ''

def bdist_wheel_options():
    if sys.platform == 'darwin':
        # Build universal wheels on MacOS.
        # ---
        # On MacOS >= 11, all builds are compatible within a major MacOS version, so Python "floors"
        # all minor versions to 0, leading to tags like like "macosx_11_0_universal2". If you use
        # the actual (non-0) minor name in the build platform, it isn't recognized.
        # ---
        # It would be nice to check whether we're actually building multi-architecture,
        # but that depends on the platforms supported by the compiler build_ext wants to use,
        # which is hard to obtain (see BuildExtCommand above).
        import platform
        v = platform.mac_ver()[0]
        major = int(v.split('.')[0])
        if major >= 11:
            v = f"{major}.0"
        return {'plat_name': f"macosx-{v}-universal2"}

    return {}

setup(
    version=scalene_version + dev_build,
    packages=find_packages(),
    cmdclass={
        'bdist_wheel': BdistWheelCommand,
        'egg_info': EggInfoCommand,
        'build_ext': BuildExtCommand,
    },
    ext_modules=([get_line_atomic, pywhere, crdp] if sys.platform != 'win32' else []),
    include_package_data=True,
    options={'bdist_wheel': bdist_wheel_options()},
)
