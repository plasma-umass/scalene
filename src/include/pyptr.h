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

  PyPtr(const PyPtr& ptr) : _obj(ptr._obj) { Py_IncRef((PyObject*)_obj); }

  // "explicit" to help avoid surprises
  explicit operator O*() { return _obj; }

  PyPtr& operator=(const PyPtr& ptr) {
    if (this != &ptr) {  // self-assignment is a no-op
      Py_IncRef((PyObject*)ptr._obj);
      Py_DecRef((PyObject*)_obj);
      _obj = ptr._obj;
    }
    return *this;
  }

  ~PyPtr() { Py_DecRef((PyObject*)_obj); }

 private:
  O* _obj;
};

#endif
