from setuptools import setup, find_packages

from os import path
this_directory = path.abspath(path.dirname(__file__))
with open(path.join(this_directory, 'README.md'), encoding='utf-8') as f:
    long_description = f.read()
    
setup(name='scalene',
      version='0.6.3',
      description='Scalene: A high-resolution, low-overhead CPU and memory profiler for Python',
      long_description=long_description,
      long_description_content_type='text/markdown',
      url='https://github.com/emeryberger/scalene',
      author='Emery Berger',
      author_email='emery@cs.umass.edu',
      license='Apache License 2.0',
          classifiers=[
         "Programming Language :: Python :: 3",
         "License :: OSI Approved :: Apache Software License",
         "Operating System :: OS Independent",
     ],
      packages=find_packages()
)
