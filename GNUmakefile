LIBNAME = scalene
PYTHON = python3
SOURCES = scalene/scalene.py scalene/sparkline.py scalene/adaptive.py
include heaplayers-make.mk

mypy:
	-mypy $(SOURCES)

black:
	-black $(SOURCES)

upload: # to pypi
	-rm -rf build dist *egg-info
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
