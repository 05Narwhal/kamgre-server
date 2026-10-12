#!/usr/bin/env python3
"""Utilization floor for an OCI Always Free A1 instance.

Oracle may reclaim an Always Free instance when, over 7 days, its 95th-percentile CPU,
network and (A1 only) memory utilization all stay under 20%. This daemon keeps CPU and
memory at or above a floor (default 25%) by topping up only what the real workload
leaves free:

- CPU: one burner process per core, scheduled SCHED_IDLE at nice 19, so any real work
  (gunicorn, Postgres, the collector) preempts it instantly. Every interval the
  controller measures the system's CPU use without the burners and sets their duty
  cycle to fill the gap; when real use is above the floor the burners stop.
- Memory: a ballast of touched anonymous pages sized so total use stays at the floor.
  It shrinks as real use grows, is released at once when available memory runs low,
  and the unit gives this process the highest OOM score so the kernel kills it first.

Standard library only. Configuration by environment (see floor.env.example).
"""
import argparse
import json
import logging
import mmap
import multiprocessing as mp
import os
import signal
import time

CHUNK = 64 * 1024 * 1024
log = logging.getLogger('prestop-floor')


def env_float(name, default):
    try:
        return float(os.environ.get(name, default))
    except ValueError:
        return float(default)


def cpu_ticks():
    """(busy, total) jiffies over all CPUs. guest time is already counted in user."""
    with open('/proc/stat') as f:
        values = [int(v) for v in f.readline().split()[1:9]]
    idle = values[3] + values[4]  # idle + iowait
    total = sum(values)
    return total - idle, total


def process_ticks(pid):
    """utime + stime of one process, in the same jiffies as /proc/stat."""
    try:
        with open(f'/proc/{pid}/stat') as f:
            fields = f.read().rsplit(')', 1)[1].split()
        return int(fields[11]) + int(fields[12])
    except (FileNotFoundError, ProcessLookupError, IndexError):
        return 0


def meminfo():
    info = {}
    with open('/proc/meminfo') as f:
        for line in f:
            key, value = line.split(':', 1)
            info[key] = int(value.split()[0]) * 1024
    return info['MemTotal'], info['MemAvailable']


def burner(duty, period=0.1):
    """Spins for `duty` of every period. SCHED_IDLE: it only ever gets CPU nobody else wants."""
    signal.signal(signal.SIGTERM, signal.SIG_DFL)
    signal.signal(signal.SIGINT, signal.SIG_IGN)
    try:
        os.sched_setscheduler(0, os.SCHED_IDLE, os.sched_param(0))
    except (AttributeError, OSError):
        pass
    try:
        os.nice(19)
    except OSError:
        pass
    x = 1
    while True:
        d = duty.value
        start = time.perf_counter()
        if d > 0:
            until = start + d * period
            while time.perf_counter() < until:
                for _ in range(2000):
                    x = (x * 1103515245 + 12345) & 0x7FFFFFFF
        rest = start + period - time.perf_counter()
        if rest > 0:
            time.sleep(rest)


class CpuFloor:
    def __init__(self, target, max_duty):
        self.target = target
        self.max_duty = max_duty
        self.cores = os.cpu_count() or 1
        self.duty = mp.Value('d', 0.0, lock=False)
        self.workers = [mp.Process(target=burner, args=(self.duty,), daemon=True, name=f'floor-burner-{i}') for i in range(self.cores)]
        for w in self.workers:
            w.start()
        self.last = cpu_ticks()
        self.last_own = self.own_ticks()
        self.other = None   # smoothed CPU share used by everything except the burners
        self.gain = 1.0     # learned: burner CPU share per unit of duty
        self.total = self.filler = 0.0

    def own_ticks(self):
        return sum(process_ticks(w.pid) for w in self.workers)

    def step(self):
        busy, total = cpu_ticks()
        own = self.own_ticks()
        d_total = total - self.last[1]
        if d_total <= 0:
            return
        self.total = (busy - self.last[0]) / d_total
        self.filler = max(0.0, (own - self.last_own) / d_total)
        self.last, self.last_own = (busy, total), own
        other = max(0.0, self.total - self.filler)
        # React at once when real load rises; relax more slowly when it falls.
        if self.other is None or other > self.other:
            self.other = other
        else:
            self.other = 0.5 * self.other + 0.5 * other
        if self.duty.value > 0.02 and self.filler > 0:
            self.gain = min(1.5, max(0.3, 0.8 * self.gain + 0.2 * self.filler / self.duty.value))
        need = self.target - self.other
        self.duty.value = min(self.max_duty, max(0.0, need / self.gain)) if need > 0 else 0.0

    def stop(self):
        self.duty.value = 0.0
        for w in self.workers:
            if w.is_alive():
                w.terminate()
        for w in self.workers:
            w.join(timeout=2)


class MemoryFloor:
    def __init__(self, target, max_share, reserve):
        self.target = target
        self.max_share = max_share
        self.reserve = reserve
        self.chunks = []
        self.used = 0.0

    @property
    def ballast(self):
        return len(self.chunks) * CHUNK

    def grow(self):
        chunk = mmap.mmap(-1, CHUNK, flags=mmap.MAP_PRIVATE | mmap.MAP_ANONYMOUS)
        chunk.write(b'\x01' * CHUNK)  # touch every page so it is resident and counted as used
        self.chunks.append(chunk)

    def shrink(self):
        self.chunks.pop().close()

    def step(self):
        total, available = meminfo()
        # Give memory back first: never let the floor push available memory under the reserve.
        while self.chunks and available < self.reserve * total:
            self.shrink()
            total, available = meminfo()
        used = total - available
        other = used - self.ballast
        want = min(self.max_share * total, max(0.0, self.target * total - other))
        while self.ballast + CHUNK <= want and available - CHUNK > self.reserve * total:
            self.grow()
            available -= CHUNK
        while self.chunks and self.ballast > want + CHUNK:
            self.shrink()
        total, available = meminfo()
        self.used = (total - available) / total

    def stop(self):
        while self.chunks:
            self.shrink()


def main():
    parser = argparse.ArgumentParser(description=__doc__.split('\n\n')[0])
    parser.add_argument('--verbose', action='store_true', help='log every interval')
    parser.add_argument('--run-for', type=float, default=0, help='exit after this many seconds (testing)')
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO, format='%(message)s')

    interval = env_float('FLOOR_INTERVAL', 2)
    cpu_target = env_float('FLOOR_CPU_TARGET', 25) / 100
    mem_target = env_float('FLOOR_MEM_TARGET', 25) / 100
    status_file = os.environ.get('FLOOR_STATUS_FILE', '')
    report_every = env_float('FLOOR_REPORT_SECONDS', 300)

    cpu = CpuFloor(cpu_target, env_float('FLOOR_CPU_MAX_DUTY', 60) / 100) if cpu_target > 0 else None
    mem = MemoryFloor(mem_target, env_float('FLOOR_MEM_MAX_SHARE', 35) / 100, env_float('FLOOR_MEM_RESERVE', 15) / 100) if mem_target > 0 else None
    log.info('floor: cpu %.0f%% on %s cores, memory %.0f%%, every %ss', cpu_target * 100, cpu.cores if cpu else 0, mem_target * 100, interval)

    running = True

    def stop(*_):
        nonlocal running
        running = False

    signal.signal(signal.SIGTERM, stop)
    signal.signal(signal.SIGINT, stop)

    started = last_report = time.monotonic()
    try:
        while running:
            time.sleep(interval)
            if cpu:
                cpu.step()
            if mem:
                mem.step()
            status = {
                'time': int(time.time()),
                'cpu_total': round(cpu.total * 100, 1) if cpu else None,
                'cpu_workload': round((cpu.other or 0) * 100, 1) if cpu else None,
                'cpu_filler_duty': round(cpu.duty.value * 100, 1) if cpu else None,
                'mem_used': round(mem.used * 100, 1) if mem else None,
                'mem_ballast_mb': mem.ballast // 2**20 if mem else None,
            }
            now = time.monotonic()
            if args.verbose or now - last_report >= report_every:
                log.info('cpu %s%% (workload %s%%, filler duty %s%%) · memory %s%% (ballast %s MB)',
                         status['cpu_total'], status['cpu_workload'], status['cpu_filler_duty'], status['mem_used'], status['mem_ballast_mb'])
                last_report = now
            if status_file:
                tmp = status_file + '.tmp'
                with open(tmp, 'w') as f:
                    json.dump(status, f)
                os.replace(tmp, status_file)
            if args.run_for and now - started >= args.run_for:
                break
    finally:
        if cpu:
            cpu.stop()
        if mem:
            mem.stop()
        log.info('floor stopped')


if __name__ == '__main__':
    main()
