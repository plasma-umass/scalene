from __future__ import print_function
from sys import getsizeof, stderr
from itertools import chain
from collections import deque
try:
    from reprlib import repr
except ImportError:
    pass

def total_size(o, handlers={}, verbose=False):
    """ Returns the approximate memory footprint an object and all of its contents.

    Automatically finds the contents of the following builtin containers and
    their subclasses:  tuple, list, deque, dict, set and frozenset.
    To search other containers, add handlers to iterate over their contents:

        handlers = {SomeContainerClass: iter,
                    OtherContainerClass: OtherContainerClass.get_elements}

    """
    dict_handler = lambda d: chain.from_iterable(d.items())
    all_handlers = {tuple: iter,
                    list: iter,
                    deque: iter,
                    dict: dict_handler,
                    set: iter,
                    frozenset: iter,
                   }
    all_handlers.update(handlers)     # user handlers take precedence
    seen = set()                      # track which object id's have already been seen
    default_size = getsizeof(0)       # estimate sizeof object without __sizeof__

    def sizeof(o):
        if id(o) in seen:       # do not double count the same object
            return 0
        seen.add(id(o))
        s = getsizeof(o, default_size)

        if verbose:
            print(s, type(o), repr(o), file=stderr)

        for typ, handler in all_handlers.items():
            if isinstance(o, typ):
                s += sum(map(sizeof, handler(o)))
                break
        return s

    return sizeof(o)

#@profile
def doit():
    print("HERE WE GO")
    q1 = list(range(0,2000))
    q2 = list(range(0,20000))
    q3 = list(range(0,200000))
    r = range(0,2000000)
    q4 = []
    for i in r:
        q4.append(i)
    # q4 = list(r)
    z = 2000000 * getsizeof(1)
    print(z)
    print("q4", total_size(q4)/(1024*1024))
    del q4
    #print("q1", total_size(q1)/(1024*1024))
    #print("q2", total_size(q2)/(1024*1024))
    #print("q3", total_size(q3)/(1024*1024))

for i in range(12):
    doit()
