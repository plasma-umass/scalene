LIBNAME = scalene
include heaplayers-make.mk

upload: # to pypi
	rm -rf dist/*
	python3 setup.py sdist bdist_wheel
	python3 -m twine upload dist/* 
