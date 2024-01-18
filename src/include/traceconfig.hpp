#pragma once

#ifndef __TRACECONFIG_H
#define __TRACECONFIG_H

#include <Python.h>
#include <mutex>
#include <string>
#include <unordered_map>
#include <vector>

class TraceConfig {
 public:
  TraceConfig(PyObject* list_wrapper, PyObject* base_path, bool profile_all_b) {
    // Assumes that each item is a bytes object
    owner = list_wrapper;
    path_owner = base_path;
    Py_IncRef(owner);
    Py_IncRef(path_owner);
    profile_all = profile_all_b;
    auto size = PyList_Size(owner);
    items.reserve(size);
    for (int i = 0; i < size; i++) {
      auto item = PyList_GetItem(owner, i);
      auto unic = PyUnicode_AsASCIIString(item);
      auto s = PyBytes_AsString(unic);
      items.push_back(s);
    }
    scalene_base_path = PyBytes_AsString(PyUnicode_AsASCIIString(base_path));
  }

  bool should_trace(char* filename) {
    if (!filename) {
      // Defensive programming.
      return false;
    }
    
    auto res = _memoize.find(filename);
    if ( res != _memoize.end()) {
      return res->second;
    }
    // Return false if filename contains paths corresponding to the native Python libraries.
    // This is to avoid profiling the Python interpreter itself.
    // Also exclude site-packages and any IPython files.

#if defined(_WIN32)
    // If on Windows, use \\ as the path separator.
    const auto PATH_SEP = "\\";
#else
    // Assume all others are POSIX.
    const auto PATH_SEP = "/";
#endif

    if (!profile_all) {

      auto python_lib = std::string("lib") + std::string(PATH_SEP) + std::string("python");
      auto scalene_lib = std::string("scalene") + std::string(PATH_SEP) + std::string("scalene");
      auto anaconda_lib = std::string("anaconda3") + std::string(PATH_SEP) + std::string("lib");
      
      if (strstr(filename, python_lib.c_str()) ||
	  strstr(filename, scalene_lib.c_str()) ||
	  strstr(filename, anaconda_lib.c_str()) ||
	  //        strstr(filename, "site-packages") != nullptr ||
	  (strstr(filename, "<") && (strstr(filename, "<ipython") || strstr(filename, "<frozen")))) {
	_memoize.insert(std::pair<std::string, bool>(std::string(filename), false));
	return false;
      }
    }
    
    if (owner != nullptr) {
      for (char* traceable : items) {
        if (strstr(filename, traceable)) {
          _memoize.insert(std::pair<std::string, bool>(std::string(filename), true));
          return true;
        }
      }
    }

    // Temporarily change the current working directory to the original program
    // path.
    char original_cwd_buf[PATH_MAX];
#ifdef _WIN32
    auto oldcwd = _getcwd(original_cwd_buf, PATH_MAX);
#else
    auto oldcwd = getcwd(original_cwd_buf, PATH_MAX);
#endif
    chdir(scalene_base_path);
    char resolved_path[PATH_MAX];

    // Check to see if the file we are profiling is in the original path.
    bool did_resolve_path = realpath(filename, resolved_path);
    bool result = false;
    if (did_resolve_path) {
      // True if we found this file in the original path.
      result = (strstr(resolved_path, scalene_base_path) != nullptr);
    }

    // Now change back to the original current working directory.
    chdir(oldcwd);
    _memoize.insert(std::pair<std::string, bool>(std::string(filename), result));
    return result;
  }

  void print() {
    printf("Profile all? %d\nitems {", profile_all);
    for (auto c : items) {
      printf("\t%s\n", c);
    }
    printf("}\n");
  }

  static void setInstance(TraceConfig* instance) {
    std::lock_guard<decltype(_instanceMutex)> g(_instanceMutex);
    delete _instance;
    _instance = instance;
  }

  static TraceConfig* getInstance() {
    std::lock_guard<decltype(_instanceMutex)> g(_instanceMutex);
    return _instance;
  }

 private:
  std::vector<char*> items;
  char* scalene_base_path;
  // This is to keep the object in scope so that
  // the data pointers are always valid
  PyObject* owner;
  PyObject* path_owner;
  bool profile_all;

  static std::mutex _instanceMutex;
  static TraceConfig* _instance;
  static std::unordered_map<std::string, bool> _memoize;
};

#endif
