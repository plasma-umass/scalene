from multiprocessing import Pool, cpu_count, freeze_support

def process_xref_file_worker(x):
    import time
    time.sleep(1)

if __name__ == '__main__':
    freeze_support()
    with Pool(processes=cpu_count()) as pool:
        for res in pool.map(process_xref_file_worker, range(10)):
            pass
    
