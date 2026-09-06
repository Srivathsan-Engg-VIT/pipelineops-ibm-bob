#!/usr/bin/env python
# render_queue.py
# Old studio render farm dispatcher. Written years ago, nobody wants to touch it.
# No types, no tests, global state, hardcoded paths. Works... mostly.

import time
import random

QUEUE = []
WORKERS = ["farm01", "farm02", "farm03"]  # only 3 workers, no GPU cluster support
JOB_LOG = "/tmp/render_log.txt"
worker_status = {}

for w in WORKERS:
    worker_status[w] = "idle"

def add_job(shot_name, frames, priority):
    job = {}
    job["shot"] = shot_name
    job["frames"] = frames
    job["priority"] = priority
    job["status"] = "queued"
    job["worker"] = None
    QUEUE.append(job)
    print("added job: " + shot_name)

def get_next_job():
    best = None
    for j in QUEUE:
        if j["status"] == "queued":
            if best is None or j["priority"] > best["priority"]:
                best = j
    return best

def find_idle_worker():
    for w in WORKERS:
        if worker_status[w] == "idle":
            return w
    return None

def dispatch():
    job = get_next_job()
    if job is None:
        return
    worker = find_idle_worker()
    if worker is None:
        print("no workers free")
        return
    job["status"] = "running"
    job["worker"] = worker
    worker_status[worker] = "busy"
    print(worker + " picked up " + job["shot"])
    time.sleep(0.1)
    success = random.random() > 0.1
    if success:
        job["status"] = "done"
    else:
        job["status"] = "queued"
    worker_status[worker] = "idle"
    log_line = job["shot"] + "," + job["status"] + "," + worker
    f = open(JOB_LOG, "a")
    f.write(log_line + "\n")
    f.close()

def run_loop(n):
    for i in range(n):
        dispatch()

if __name__ == "__main__":
    add_job("SH010_comp", 120, 5)
    add_job("SH020_lighting", 240, 3)
    add_job("SH030_fx", 80, 8)
    run_loop(10)
