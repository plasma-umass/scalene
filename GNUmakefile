LIBNAME = scalene
PYTHON = python3
SOURCES = scalene/scalene.py scalene/sparkline.py scalene/adaptive.py scalene/runningstats.py
include heaplayers-make.mk

mypy:
	-mypy $(SOURCES)

black:
	-black $(SOURCES)

upload: # to pypi
	-cp libscalene.so libscalene.dylib scalene/
	-rm -rf build dist *egg-info
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
