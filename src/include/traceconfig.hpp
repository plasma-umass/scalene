#pragma once

#ifndef __TRACECONFIG_H
#define __TRACECONFIG_H

#include <Python.h>

#if defined(_WIN32)
#ifndef WIN32_LEAN_AND_MEAN
#define WIN32_LEAN_AND_MEAN
#endif
#include <windows.h>
#include <direct.h>
#include <stdlib.h>
#define PATH_MAX _MAX_PATH
#define realpath(N,R) _fullpath((R),(N),_MAX_PATH)
#define chdir _chdir
#define getcwd _getcwd
#else
#include <unistd.h>
#include <limits.h>
#endif

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
    scalene_base_path = PyBytes_AsString(PyUnicode_AsEncodedString(base_path, "utf-8", "strict"));
  }

  bool should_trace(char* filename) {
    if (!filename) {
      // Defensive programming.
      return false;
    }

    {
      std::lock_guard<std::mutex> lock(_memoizeMutex);
      auto res = _memoize.find(filename);
      if (res != _memoize.end()) {
        return res->second;
      }
    }
    // Return false if filename contains paths corresponding to the native
    // Python libraries. This is to avoid profiling the Python interpreter
    // itself. Also exclude site-packages and any IPython files.

#if defined(_WIN32)
    // If on Windows, use \\ as the path separator.
    const auto PATH_SEP = "\\";
#else
    // Assume all others are POSIX.
    const auto PATH_SEP = "/";
#endif

    // Always exclude Scalene's own files, regardless of profile_all
    auto scalene_lib = std::string("scalene") + std::string(PATH_SEP) +
                       std::string("scalene");
    if (strstr(filename, scalene_lib.c_str())) {
      std::lock_guard<std::mutex> lock(_memoizeMutex);
      _memoize.insert(
          std::pair<std::string, bool>(std::string(filename), false));
      return false;
    }

    if (!profile_all) {
      auto python_lib =
          std::string("lib") + std::string(PATH_SEP) + std::string("python");
      auto anaconda_lib =
          std::string("anaconda3") + std::string(PATH_SEP) + std::string("lib");

      if (strstr(filename, python_lib.c_str()) ||
          strstr(filename, anaconda_lib.c_str()) ||
          strstr(filename, "site-packages") != nullptr ||
          (strstr(filename, "<") &&
           (strstr(filename, "<ipython") || strstr(filename, "<frozen")))) {
        std::lock_guard<std::mutex> lock(_memoizeMutex);
        _memoize.insert(
            std::pair<std::string, bool>(std::string(filename), false));
        return false;
      }
    }

    if (owner != nullptr) {
      for (char* traceable : items) {
        if (strstr(filename, traceable)) {
          std::lock_guard<std::mutex> lock(_memoizeMutex);
          _memoize.insert(
              std::pair<std::string, bool>(std::string(filename), true));
          return true;
        }
      }
    }

    // Resolve relative filenames against the original program path.
    // We avoid chdir() because it mutates process-wide state and is
    // unsafe in free-threaded Python where multiple threads profile.
    char resolved_path[PATH_MAX];
    bool did_resolve_path = false;

    if (filename[0] == '/' || filename[0] == '\\') {
      // Absolute path — resolve directly
      did_resolve_path = realpath(filename, resolved_path);
    } else {
      // Relative path — prepend scalene_base_path
      std::string full_path = std::string(scalene_base_path) + "/" + filename;
      did_resolve_path = realpath(full_path.c_str(), resolved_path);
    }

    bool result = false;
    if (did_resolve_path) {
      // True if we found this file in the original path.
      result = (strstr(resolved_path, scalene_base_path) != nullptr);
    }

    std::lock_guard<std::mutex> lock(_memoizeMutex);
    _memoize.insert(
        std::pair<std::string, bool>(std::string(filename), result));
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
  static std::mutex _memoizeMutex;
  static TraceConfig* _instance;
  static std::unordered_map<std::string, bool> _memoize;
};

#endif
