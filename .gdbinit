add-auto-load-safe-path /home/runner/work/scalene/scalene/.gdbinit
set env LD_PRELOAD=/home/runner/work/scalene/scalene/scalene/libscalene.so
set args -m scalene ./test/testme.py
handle all nostop noprint pass
catch signal SIGSEGV
catch signal SIGABRT
catch signal SIGKILL
