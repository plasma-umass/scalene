#ifndef PYPTR_H
#define PYPTR_H

#pragma once

#include <Python.h>

// Implements a mini smart pointer to PyObject.
// Manages a "strong" reference to the object... to use with a weak reference,
// Py_IncRef it first. Unfortunately, not all PyObject subclasses (e.g.,
// PyFrameObject) are declared as such, so we need to make this a template and
// cast.
template <class O = PyObject>
class PyPtr {
 public:
  PyPtr(O* o) : _obj(o) {}

  O* operator->() { return _obj; }

  operator O*() { return _obj; }

  PyPtr& operator=(O* o) {
    Py_DecRef((PyObject*)_obj);
    _obj = o;
    return *this;
  }

  PyPtr& operator=(PyPtr& ptr) {
    Py_IncRef((PyObject*)ptr._obj);
    *this = ptr._obj;
    return *this;
  }

  ~PyPtr() { Py_DecRef((PyObject*)_obj); }

 private:
  O* _obj;
};

#endif
