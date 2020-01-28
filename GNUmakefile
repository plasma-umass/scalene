LIBNAME = scalene
PYTHON = python3

include heaplayers-make.mk

upload: # to pypi
	-rm -rf build dist *egg-info
	@status=$$(git status --porcelain); \
	if [ -z "$${status}" ]; then \
		$(PYTHON) setup.py bdist_wheel sdist; \
		$(PYTHON) twine upload dist/*; \
	else \
		echo Working directory is dirty >&2; \
	fi;
