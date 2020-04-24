LIBNAME = scalene
PYTHON = python3

include heaplayers-make.mk

mypy:
	mypy --check-untyped-defs scalene/scalene.py

upload: # to pypi
	-black scalene/scalene.py
	-rm -rf build dist *egg-info
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
