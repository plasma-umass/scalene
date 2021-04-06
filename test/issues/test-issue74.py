import gevent

def calc(a):
    x = 0
    for i in range(1000000):
        x += 1
    gevent.sleep(a)

g1 = gevent.spawn(calc, 1)
g2 = gevent.spawn(calc, 2)
g3 = gevent.spawn(calc, 3)
g1.start()
g2.start()
g3.start()
g1.join()
g2.join()
g3.join()
