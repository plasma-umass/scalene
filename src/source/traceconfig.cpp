#include "traceconfig.hpp"

TraceConfig* TraceConfig::_instance = 0;
std::mutex TraceConfig::_instanceMutex;
std::mutex TraceConfig::_memoizeMutex;
std::unordered_map<std::string, bool> TraceConfig::_memoize;
