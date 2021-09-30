#include <Python.h>
#include "py_env.hpp"
static PyObject *register_files_to_profile(PyObject *self, PyObject *args) {
  PyObject *a_list;
  PyObject *base_path;
  int profile_all;
  if (!PyArg_ParseTuple(args, "OOp", &a_list, &base_path, &profile_all))
    return NULL;
  auto is_list = PyList_Check(a_list);
  if (!is_list) {
    PyErr_SetString(PyExc_Exception, "Requires list or list-like object");
  }
  set_py_string_ptr_list(a_list, base_path, profile_all);
  Py_RETURN_NONE;
}

static PyObject *print_files_to_profile(PyObject *self, PyObject *args) {
  py_string_ptr_list.print();
  Py_RETURN_NONE;
}

static PyMethodDef EmbMethods[] = {
    {"register_files_to_profile", register_files_to_profile, METH_VARARGS,
     "Provides list of things into allocator"},
    {"print_files_to_profile", print_files_to_profile, METH_NOARGS,
     "printing for debug"},
    {NULL, NULL, 0, NULL}};

static PyModuleDef EmbedModule = {PyModuleDef_HEAD_INIT,
                                  "register_files_to_profile",
                                  NULL,
                                  -1,
                                  EmbMethods,
                                  NULL,
                                  NULL,
                                  NULL,
                                  NULL};

PyMODINIT_FUNC PyInit_register_files_to_profile() {
  return PyModule_Create(&EmbedModule);
}

