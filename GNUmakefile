LIBNAME = scalene
PYTHON = python3
SOURCES = scalene/scalene_profiler.py scalene/sparkline.py scalene/adaptive.py scalene/runningstats.py scalene/syntaxline.py scalene/leak_analysis.py scalene/replacement*.py

include heaplayers-make.mk

mypy:
	-mypy $(SOURCES)

black:
	-black -l 79 $(SOURCES)

upload: # to pypi
	-cp libscalene.so libscalene.dylib scalene/
	-rm -rf build dist *egg-info
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
