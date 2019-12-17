from setuptools import setup, find_packages

setup(name='scale',
      version='0.1',
      description='Scale: A Profiler for Python',
      url='https://github.com/emeryberger/scale',
      author='Emery Berger',
      author_email='emery@cs.umass.edu',
      license='Apache License 2.0',
          classifiers=[
         "Programming Language :: Python :: 3",
         "License :: OSI Approved :: Apache License 2.0",
         "Operating System :: OS Independent",
     ],
      packages=find_packages()
)
