LIBNAME = scalene
PYTHON = python3
PYTHON_SOURCES = scalene/scalene_profiler.py scalene/sparkline.py scalene/adaptive.py scalene/runningstats.py scalene/syntaxline.py scalene/leak_analysis.py scalene/replacement*.py
C_SOURCES = libscalene.cpp include/*.h*

.PHONY: black clang-format

include heaplayers-make.mk

mypy:
	-mypy $(PYTHON_SOURCES)

format: black clang-format

clang-format:
	-clang-format -i $(C_SOURCES) --style=google

black:
	-black -l 79 $(PYTHON_SOURCES)

upload: # to pypi
	-cp libscalene.so libscalene.dylib scalene/
	-rm -rf build dist *egg-info
	$(PYTHON) setup.py sdist bdist_wheel
	$(PYTHON) -m twine upload dist/*
