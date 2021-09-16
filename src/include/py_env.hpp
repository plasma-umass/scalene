#include <vector>
#include <Python.h>
#include <mutex>
#include "printf.h"

class PyStringPtrList {
public:
    PyStringPtrList(PyObject* list_wrapper, bool profile_all_b) {
        // Assumes that each item is a bytes object
        owner = list_wrapper;
        Py_INCREF(owner);
        profile_all = profile_all_b;
        auto size = PyList_Size(owner);
        items.reserve(size);
        for(int i = 0; i < size; i++) {
            auto item = PyList_GetItem(owner, i);
            
            items.push_back(PyBytes_AsString(PyUnicode_AsASCIIString(item)));
        }
        is_initialized = true;
    }
    PyStringPtrList() {
        is_initialized = false;
    }
    ~PyStringPtrList() {
        if (is_initialized)
            Py_DECREF(owner);
    }
    bool initialized() {
        return is_initialized;
    }
    bool should_trace(char* filename) {
        if (strstr(filename, "site-packages") || strstr(filename, "/lib/python")) {
            return false;
        }
        if (*filename == '<' && strstr(filename, "<ipython")) {
            return true;
        }
        if (strstr(filename, "scalene/scalene")) {
            return false;
        }
        if (owner != nullptr) {
            for(char* traceable : items) {
                if(strstr(filename, traceable)) {
                    return true;
                }
            }
        }
        return profile_all;
    }
    void print() {
        printf("Profile all? %d\nitems {", profile_all);
        for(auto c : items) {
            printf("\t%s\n", c);
        }
        printf("}\n");
    }
private:    
    std::vector<char*> items;
    // This is to keep the object in scope so that 
    // the data pointers are always valid
    PyObject* owner;
    bool profile_all;
    bool is_initialized;
};

static std::mutex _mx;
static PyStringPtrList py_string_ptr_list;

static void set_py_string_ptr_list(PyObject* p, bool trace_all) {
    std::lock_guard g(_mx);
    printf_("Trace all? %d\n", trace_all);
    py_string_ptr_list = PyStringPtrList{p, trace_all};
}