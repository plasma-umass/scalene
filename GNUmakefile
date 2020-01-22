LIBNAME = scalene
PYTHON = python3

include heaplayers-make.mk

upload: # to pypi
	rm -rf dist/*
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/* 

benchmark:
	$(PYTHON) benchmarks/benchmark.py 
