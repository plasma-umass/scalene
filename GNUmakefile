LIBNAME = scalene
include heaplayers-make.mk

upload: # to pypi
	-rm -rf build dist *egg-info
	@status=$$(git status --porcelain); \
	if [ -z "$${status}" ]; then \
		python3 setup.py bdist_wheel sdist; \
		python3 twine upload dist/*; \
	else \
		echo Working directory is dirty >&2; \
	fi;
