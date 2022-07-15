import heapq
import numpy as np
from itertools import product
from bisect import bisect as bisect

rng = np.random.default_rng(seed = 314)

def writeCFileFmt(filename, array):
    with open(filename, 'w') as fp:
        shp = np.shape(array)
        if len(shp) > 2:
            print ("Cannot save arrays with dimensions greater than 2")
            exit(11)
        total = ""
        col = 0
        for t in shp:
            total = str(t) + "," + total
        fp.writelines(total[:-1])
        fp.writelines("\n")
        print("TOTAL " + str(total[:-1]))
        total = ""
        for x in array.flatten():
            total = str(x) + "," +  total
            col += 1
            if col == shp[-1]:
                fp.writelines(total[:-1])
                fp.writelines("\n")
                col = 0
                total = ""

def default_comm_delay(source, dest):
    #return 1
    return int(np.round(max(1,500 + 200*(rng.random() - .5))))

def default_compute_delay(node):
    #return 100
    return int(np.round(max(1,500 + 500*(rng.random() - .5))))
    #return int(np.round(500 + 200*(.95-.5) + 500 + 500*(.9-.5)))

def kacz_solve(A,b,x, iterations = 100, eps = None):
    while True:
        rows = rng.integers(low = 0, high = A.shape[0], size = iterations)
        for i in rows:
            ai = A[i,:]
            x = x+  (b[i] - np.dot(x,ai))/(np.dot(ai,ai))*ai
        # Norm is a norm_2?
        kacz_error = np.linalg.norm(np.matmul(A,x) - b)
        if eps == None or kacz_error < eps: ### Exit condition ? why repeat if the error is low?
           break

    #print("Kaczman Error", kacz_error)
    return x

def async_solve(M,x, partition = None, eps = 10**(-9), comm_delay = None, compute_delay = None, kacz_updates = 100, method = 'kacz', max_updates = 100000):
    if comm_delay == None:
        comm_delay = default_comm_delay
    if compute_delay == None:
        compute_delay = default_compute_delay

    # Assume M is square, no error checking for conformability
    print(M.shape)
    n = M.shape[0]
    if partition == None:
        partition = 4
    if isinstance(partition, (int,float)):
        partition = int(partition)
        s = n//partition
        partition = [ list(range(i*s,(i+1)*s)) for i in range(partition-1)] + [list(range((partition-1)*s,n))]
        # partition is a list of global indexes
    
    # k is the number of parts in the partition
    k = len(partition)
    b = np.matmul(M,x)

    x_star = {i : x[partition[i]] for i in range(k)}

    # collecting square blocks from b and M 

    b_block = {i : b[partition[i]] for i in range(k)}
    M_block = {(i,j) : M[np.ix_(partition[i],partition[j])] for (i,j) in product(range(k),repeat = 2)}
    # Python 3.10 allows for keys for bisect, but this will work in either version
    x_hist = { i :  [np.array([0]*len(partition[i])), np.array([0]*len(partition[i]))] for i in range(k)}

    x_time = { i : [float('-inf'),float('-inf')] for i in range(k)}
    
    heap = [(0,i) for i in range(k)]
    heapq.heapify(heap)
    ## hist, time and heap are used to simulate the parallelism

    iteration = 0
    moved = [True]*k
    #print ("MOVED ", moved)
    while iteration < max_updates:
        iteration += 1
        (time, proc) = heapq.heappop(heap)
        ### It seems that this one of the two places for global communication
        tilde_b = b_block[proc] - sum(np.matmul(M_block[(proc,j)],x_hist[j][bisect(x_time[j],time - comm_delay(j,proc))-1]) for j in range(k) if not j == proc)
        if method == 'kacz':
            x_new = kacz_solve(M_block[(proc,proc)],tilde_b,x_hist[proc][-1],iterations = kacz_updates)
        else:
            x_new = np.linalg.solve(M_block[(proc,proc)],tilde_b)

        tprime = time + compute_delay(proc)

        heapq.heappush(heap,(tprime,proc))

        x_step = np.linalg.norm(x_new - x_hist[proc][-1])/np.linalg.norm(x_new)
        x_hist[proc].append(x_new)
        x_time[proc].append(tprime)
        if iteration > 5*k: ## Another multi node strategy? wait for no one else to move and then break? Another possible global communication point
            if x_step < eps:
                moved[proc] = False
            else:
                moved = [True]*k
            if not any(moved):
                break
    return np.hstack([x_hist[p][-1] for p in range(k)]), iteration

        
            
        

if __name__ == '__main__':
    
    n = 1000
    trials = 5
    parts = 20

    rel_sol_error = {'kacz' : [], 'exact' : []}
    rel_error = {'kacz' : [], 'exact' : []}
    iterations = {'kacz' : [], 'exact' : []}
    for i in range(trials):
        print("Iteration", i)
        rng = np.random.default_rng(seed = i)
        M = (2/n)*rng.random((n,n)) #why 2/n * rng[0,1]
        M = (max(sum(M[i][j] for j in range(n)) for i in range(n)))*np.eye(n) - M
        x = rng.random(n)
        b = np.matmul(M,x)
        x_norm = np.linalg.norm(x)
        b_norm = np.linalg.norm(b)
        filenameM = "inputs/M_" + str(i) + ".txt"
        filenamex = "inputs/x_" + str(i) + ".txt"
        filenameb = "inputs/b_" + str(i) + ".txt"
        #writeCFileFmt(filenameM, M)
        #writeCFileFmt(filenamex, x)
        #writeCFileFmt(filenameb, b)

        for method in ['kacz','exact']:
            x_star, steps = async_solve(M,x,partition = parts, method = method)
            rel_sol_error[method].append( np.linalg.norm(x_star - x)/x_norm)
            rel_error[method].append( np.linalg.norm(np.matmul(M,x_star) - b)/b_norm)
            iterations[method].append(steps)
    import shutil
    import os
    shutil.copyfile(f'/proc/{os.getpid()}/maps', f'/people/ster443/files/tmp/proc-{os.getpid()}')
    print(f"MAP FILE AT /people/ster443/files/tmp/proc-{os.getpid()}")

#    fig, ax = plt.subplots(3, sharex = True)
#    ax[0].plot(rel_error['kacz'], color = 'orange', label = 'Kaczmanz')
#    ax[0].plot(rel_error['exact'], color = 'blue', label = 'Exact')
#    ax[0].legend()
#    ax[0].set_title("Relative Error")

#    ax[1].plot(rel_sol_error['kacz'], color = 'orange', label = 'Kaczmanz')
#    ax[1].plot(rel_sol_error['exact'], color = 'blue', label = 'Exact')
#    ax[1].legend()
#    ax[1].set_title("Relative Solution Error")

#    ax[2].plot(iterations['kacz'], color = 'orange', label = 'Kaczmanz')
#    ax[2].plot(iterations['exact'], color = 'blue', label = 'Exact')
#    ax[2].legend()
#    ax[2].set_title("Block Updates")
#    ax[2].set(xlabel = 'Random Seed')

#    plt.show()

