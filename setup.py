from setuptools import setup, find_packages
from setuptools.extension import Extension
from scalene.scalene_version import scalene_version
from os import path, environ
import platform
import sys

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

def clang_version():
    import re
    pat = re.compile('Clang ([0-9]+)')
    match = pat.search(platform.python_compiler())
    version = int(match.group(1))
    return version

def multiarch_args():
    """Returns args requesting multi-architecture support, if applicable."""
    # On MacOS we build "universal2" packages, for both x86_64 and arm64/M1
    if sys.platform == 'darwin':
        args = ['-arch', 'x86_64']
        # ARM support was added in XCode 12, which requires MacOS 10.15.4
        if clang_version() >= 12: # XCode 12
            if [int(n) for n in platform.mac_ver()[0].split('.')] >= [10, 15, 4]:
                args += ['-arch', 'arm64', '-arch', 'arm64e']
        return args
    return []

def extra_compile_args():
    """Returns extra compiler args for platform."""
    if sys.platform == 'win32':
        return ['/std:c++14'] # for Visual Studio C++

    return ['-std=c++14'] + multiarch_args()

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
from wheel.bdist_wheel import bdist_wheel as orig_bdist_wheel
class BdistWheelCommand(orig_bdist_wheel):
    def finalize_options(self):
        orig_bdist_wheel.finalize_options(self)
        self.root_is_pure = False

import setuptools.command.build_ext
class BuildExtCommand(setuptools.command.build_ext.build_ext):
    """Custom command that runs 'make' to generate libscalene."""
    def run(self):
        super().run()
        # No build of DLL for Windows currently.
        if sys.platform != 'win32':
            self.build_libscalene()

    def build_libscalene(self):
        scalene_temp = path.join(self.build_temp, 'scalene')
        scalene_lib = path.join(self.build_lib, 'scalene')
        libscalene = 'libscalene' + dll_suffix()
        self.mkpath(scalene_temp)
        self.mkpath(scalene_lib)
        self.spawn([make_command(), 'OUTDIR=' + scalene_temp,
                    'ARCH=' + ' '.join(multiarch_args())])
        self.copy_file(path.join(scalene_temp, libscalene),
                       path.join(scalene_lib, libscalene))
        if self.inplace:
            self.copy_file(path.join(scalene_lib, libscalene),
                           path.join('scalene', libscalene))

get_line_atomic = Extension('scalene.get_line_atomic',
    include_dirs=['.', 'vendor/Heap-Layers', 'vendor/Heap-Layers/utility'],
    sources=['src/source/get_line_atomic.cpp'],
    extra_compile_args=extra_compile_args(),
    extra_link_args=multiarch_args(),
    py_limited_api=True, # for binary compatibility
    language="c++"
)

pywhere = Extension('scalene.pywhere',
    include_dirs=['.', 'src', 'src/include'],
    sources = ['src/source/pywhere.cpp'],
    extra_compile_args=extra_compile_args(),
    extra_link_args=multiarch_args(),
    py_limited_api=False,
    language="c++")

# If we're testing packaging, build using a ".devN" suffix in the version number,
# so that we can upload new files (as testpypi/pypi don't allow re-uploading files with
# the same name as previously uploaded).
# Numbering scheme: https://www.python.org/dev/peps/pep-0440
dev_build = ('.dev' + environ['DEV_BUILD']) if 'DEV_BUILD' in environ else ''

setup(
    name="scalene",
    version=scalene_version + dev_build,
    description="Scalene: A high-resolution, low-overhead CPU, GPU, and memory profiler for Python",
    keywords="performance memory profiler",
    long_description=read_file("README.md"),
    long_description_content_type="text/markdown",
    url="https://github.com/plasma-umass/scalene",
    author="Emery Berger",
    author_email="emery@cs.umass.edu",
    license="Apache License 2.0",
    classifiers=[
        "Development Status :: 5 - Production/Stable",
        "Framework :: IPython",
        "Framework :: Jupyter",
        "Intended Audience :: Developers",
        "Intended Audience :: Science/Research",
        "Topic :: Software Development",
        "Topic :: Software Development :: Debuggers",
        "Programming Language :: Python",
        "Programming Language :: Python :: 3 :: Only",
        "Programming Language :: Python :: 3",
        "Programming Language :: Python :: 3.8",
        "Programming Language :: Python :: 3.9",
        "Programming Language :: Python :: 3.10",
        "License :: OSI Approved :: Apache Software License",
        "Operating System :: POSIX :: Linux",
        "Operating System :: MacOS :: MacOS X",
        "Operating System :: Microsoft :: Windows :: Windows 10"
    ],
    packages=find_packages(),
    cmdclass={
        'bdist_wheel': BdistWheelCommand,
        'egg_info': EggInfoCommand,
        'build_ext': BuildExtCommand,
    },
    install_requires=[
        "rich>=9.2.0",
        "cloudpickle>=1.5.0",
        "nvidia-ml-py>=11.450.51,<375.99999",
        "numpy"
    ],
    ext_modules=([get_line_atomic, pywhere] if sys.platform != 'win32' else []),
    setup_requires=['setuptools_scm'],
    include_package_data=True,
    entry_points={"console_scripts": ["scalene = scalene.__main__:main"]},
    python_requires=">=3.8",
)
