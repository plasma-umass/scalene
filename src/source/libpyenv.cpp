#include <mutex>
#include "py_env.hpp"


static std::mutex _mx;
static PyStringPtrList py_string_ptr_list;

static void set_py_string_ptr_list(PyObject* p, PyObject* base_path,
                                   bool trace_all) {
  std::lock_guard<decltype(_mx)> g(_mx);
  py_string_ptr_list = PyStringPtrList{p, base_path, trace_all};
}

static PyStringPtrList* get_py_string_ptr_list() {
    return &py_string_ptr_list;
}