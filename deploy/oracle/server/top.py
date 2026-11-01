#!/usr/bin/env python3
"""prestop-top: a live, tabbed view of the KamGre server, with graphs (q quits, ? lists the keys).

    sudo prestop-top [seconds between updates, default 2] [tab]
    sudo prestop-top --once [tab]          print one frame of each tab (or one tab) and exit

Tabs: overview, system, services, traffic, data, learning, logs. Python standard library only, so it runs on
the server's own python3 (no venv), and top-remote.sh can send it over SSH before the next deploy.

Read-only: it reads /proc, systemd, journald, Redis, PostgreSQL, vnstat and /api/v1/health. The month's
outbound data is worked out the way egress-guard.sh does it, from the guard's counter file, without running
the guard. Every clock and date on screen is in Slovenian time.
"""
import curses
import glob
import json
import locale
import os
import pwd
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from collections import deque
from datetime import datetime, time as dtime, timedelta, timezone
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

TZ = ZoneInfo('Europe/Ljubljana')
ENV_FILE = '/etc/prestop/prestop.env'
STATE_DIR = '/var/lib/prestop'
BACKUP_DIR = '/var/backups/prestop'
HEALTH_URL = 'http://127.0.0.1:8066/api/v1/health'
API_PORT = 8066
SERVICES = ['prestop-web', 'prestop-collector', 'prestop-push', 'prestop-ingest', 'caddy', 'cloudflared', 'postgresql', 'redis-server']
TIMERS = ['prestop-egress', 'prestop-watchdog', 'prestop-szpdf', 'prestop-nightly', 'prestop-backup']
TABS = [('overview', 'Overview'), ('system', 'System'), ('services', 'Services'), ('traffic', 'Traffic'),
        ('data', 'Data'), ('learning', 'Learning'), ('logs', 'Logs')]
HISTORY = 900          # samples kept for the graphs (30 min at 2 s)
ACTIVE_WINDOW = 15     # minutes of the traffic guard's active-visitor tally (prestop_api/traffic.py)
GIB = 1024 ** 3

# ---------------------------------------------------------------- settings from /etc/prestop/prestop.env


def read_env():
    out = {}
    try:
        with open(ENV_FILE, encoding='utf-8', errors='replace') as f:
            for raw in f:
                m = re.match(r'([A-Za-z_][A-Za-z0-9_]*)=(.*)', raw.rstrip('\n'))
                if m:
                    out[m[1]] = re.sub('[\r"\']', '', m[2])
    except OSError:
        pass
    return out


ENV = read_env()


def env_int(name, default):
    m = re.match(r'\d+', ENV.get(name, ''))
    return int(m[0]) if m else default


REDIS_URL = ENV.get('REDIS_URL') or 'redis://127.0.0.1:6379/1'
MAX_ACTIVE = env_int('PRESTOP_TRAFFIC_MAX_ACTIVE', 3000)
HOURLY_BYTES = env_int('PRESTOP_TRAFFIC_HOURLY_MB', 30000) * 1_000_000
TRAFFIC_DIR = ENV.get('PRESTOP_TRAFFIC_STATE_DIR') or STATE_DIR + '/traffic'

# ---------------------------------------------------------------- small helpers


def sh(cmd, timeout=6, **kw):
    r = subprocess.run(cmd, capture_output=True, text=True, errors='replace', timeout=timeout, **kw)
    if r.returncode != 0:
        msg = (r.stderr or r.stdout).strip().splitlines()
        raise RuntimeError(msg[0][:120] if msg else f'{cmd[0]} exited {r.returncode}')
    return r.stdout


def read(path, default=''):
    try:
        with open(path, encoding='utf-8', errors='replace') as f:
            return f.read()
    except OSError:
        return default


def parse_iso(s):
    try:
        return datetime.fromisoformat(str(s).replace('Z', '+00:00')).timestamp()
    except (TypeError, ValueError):
        return None


def dur(s):
    s = int(max(0, s or 0))
    if s < 60:
        return f'{s}s'
    if s < 3600:
        return f'{s // 60}m'
    if s < 86400:
        return f'{s // 3600}h {s % 3600 // 60:02d}m'
    return f'{s // 86400}d {s % 86400 // 3600}h'


def ago(ts):
    return dur(time.time() - ts) + ' ago' if ts else 'never'


def size(b, unit='B'):
    b = float(b or 0)
    for u in ('', 'K', 'M', 'G', 'T'):
        if abs(b) < 1024 or u == 'T':
            return f'{b:.0f} {u}{unit}' if u == '' else f'{b:.1f} {u}{unit}'
        b /= 1024
    return ''


def rate(b):
    return '…' if b is None else size(b, 'B/s')


def short(b):
    """Compact axis label: 980, 1.2K, 34M, 1.1G."""
    b = float(b or 0)
    for u in ('', 'K', 'M', 'G', 'T'):
        if abs(b) < 1000 or u == 'T':
            return f'{b:.0f}{u}' if b >= 10 or u == '' else f'{b:.1f}{u}'
        b /= 1024
    return ''


def clock(ts, fmt='%H:%M'):
    return datetime.fromtimestamp(ts, TZ).strftime(fmt) if ts else '–'


def day_label(d):
    return f'{d:%a} {d.day} {d:%b}'


def pct(a, b):
    return a * 100 / b if b else 0

# ---------------------------------------------------------------- colours
# name: (fg 256, bg 256, fg 8, bg 8, flags)  b = bold, d = dim (only when the terminal has 8 colours)


STYLES = {
    'text': (252, -1, 7, -1, ''), 'dim': (245, -1, 7, -1, 'd'), 'faint': (239, -1, 7, -1, 'd'),
    'border': (240, -1, 7, -1, 'd'), 'bold': (255, -1, 7, -1, 'b'), 'title': (117, -1, 6, -1, 'b'),
    'accent': (117, -1, 6, -1, ''), 'accentb': (117, -1, 6, -1, 'b'),
    'ok': (114, -1, 2, -1, ''), 'warn': (221, -1, 3, -1, ''), 'bad': (210, -1, 1, -1, 'b'),
    'rx': (80, -1, 6, -1, ''), 'tx': (177, -1, 5, -1, ''), 'purple': (141, -1, 5, -1, ''),
    'hdr': (252, 236, 7, 4, ''), 'hdrb': (117, 236, 7, 4, 'b'), 'hdrdim': (245, 236, 7, 4, ''),
    'hdrok': (114, 236, 2, 4, 'b'), 'hdrwarn': (221, 236, 3, 4, 'b'), 'hdrbad': (210, 236, 1, 4, 'b'),
    'tab': (247, 235, 7, 0, ''), 'tabkey': (117, 235, 6, 0, ''), 'tabon': (234, 117, 0, 6, 'b'),
    'tabwarn': (221, 235, 3, 0, 'b'), 'tabbad': (210, 235, 1, 0, 'b'),
    'foot': (245, 235, 7, 0, ''), 'footkey': (117, 235, 6, 0, 'b'), 'footwarn': (221, 235, 3, 0, 'b'),
}
LEVEL = {'ok': 0, 'warn': 1, 'bad': 2}


def level_style(p, warn=70, bad=90):
    return 'bad' if p >= bad else 'warn' if p >= warn else 'ok'


def status_style(s):
    return {'live': 'ok', 'ready': 'ok', 'active': 'ok', 'success': 'ok', 'stale': 'warn', 'activating': 'warn',
            'reloading': 'warn', 'deactivating': 'warn'}.get(s, 'bad')

# ---------------------------------------------------------------- lines: a line is a list of (text, style)


def merge(segs):
    out = []
    for t, s in segs:
        if out and out[-1][1] == s:
            out[-1] = (out[-1][0] + t, s)
        elif t:
            out.append((t, s))
    return out


def L(*parts):
    return [(p, 'text') if isinstance(p, str) else p for p in parts]


def width(line):
    return sum(len(t) for t, _ in line)


def fit(line, w, fill='text'):
    out, n = [], 0
    for t, s in line:
        if n >= w:
            break
        t = t[:w - n]
        out.append((t, s))
        n += len(t)
    if n < w:
        out.append((' ' * (w - n), fill))
    return out


def cell(text, w, style='text', right=False):
    text = str(text)[:w]
    return (text.rjust(w) if right else text.ljust(w), style)


def blank(w=0):
    return [(' ' * w, 'text')]


def panel(title, body, w, note='', note_style='dim'):
    iw = max(1, w - 4)
    t, n = f' {title} ', f' {note} ' if note else ''
    fill = w - 4 - len(t) - len(n)
    if fill < 0:
        n, fill = '', max(0, w - 4 - len(t))
        t = t[:w - 4]
    out = [[('╭─', 'border'), (t, 'title'), ('─' * fill, 'border'), (n, note_style), ('─╮', 'border')]]
    for line in body:
        out.append([('│ ', 'border')] + fit(line, iw) + [(' │', 'border')])
    out.append([('╰' + '─' * (w - 2) + '╯', 'border')])
    return out


def hjoin(left, lw, right, rw, gap=1):
    rows = max(len(left), len(right))
    out = []
    for i in range(rows):
        a = fit(left[i], lw) if i < len(left) else blank(lw)
        b = fit(right[i], rw) if i < len(right) else blank(rw)
        out.append(a + blank(gap) + b)
    return out


def columns(w, left, right, min_w=104):
    """Panels (functions of a width) in two columns when the window is wide enough, else one under the other."""
    if w < min_w:
        return [line for f in left + right for line in f(w)]
    lw = (w - 1) // 2
    rw = w - 1 - lw
    return hjoin([x for f in left for x in f(lw)], lw, [x for f in right for x in f(rw)], rw)


def kv(label, *parts, lw=11):
    return [(label.ljust(lw)[:lw], 'dim')] + L(*parts)


def unavailable(name):
    e = POLL[name].error if name in POLL else None
    return [L(('unavailable', 'bad'), ('  ' + e if e else '', 'dim'))] if e else [L(('collecting…', 'dim'))]

# ---------------------------------------------------------------- charts


BLOCKS = ' ▁▂▃▄▅▆▇█'


def meter(p, w, style=None, marker=None):
    """A bar for a percentage; marker draws a tick at another percentage (the month's pace)."""
    if p is None:
        return [('measuring…'.ljust(w)[:w], 'faint')]
    p = max(0.0, min(100.0, p))
    f = int(round(p * w / 100))
    st = style or level_style(p)
    cells = [('━', st)] * f + [('─', 'faint')] * (w - f)
    if marker is not None and w > 0:
        i = max(0, min(w - 1, int(marker * w / 100)))
        cells[i] = ('┃', 'accentb')
    return merge(cells)


def spark(values, w, hi=None, style='accent', by_level=False):
    vals = list(values)[-w:] if w > 0 else []
    top = hi or max([v for v in vals if v is not None] or [0]) or 1
    out = [(' ' * (w - len(vals)), 'text')]
    for v in vals:
        v = v or 0
        n = max(0, min(8, int(round(v / top * 8))))
        st = level_style(v / top * 100) if by_level else style
        out.append((BLOCKS[n] if n else '▁', st if v else 'faint'))
    return merge(out)


def area(values, w, h, hi=None, style='accent', by_level=False, label=lambda v: f'{v:.0f}'):
    """A filled graph, h rows high, of the last values that fit; the y axis is labelled at the top, middle and 0."""
    lab = 6
    cw = max(1, w - lab - 1)
    vals = [v or 0 for v in list(values)[-cw:]]
    top = hi or (max(vals, default=0) * 1.15) or 1
    lines = []
    for r in range(h - 1, -1, -1):
        if r == h - 1:
            tag = label(top)
        elif r == 0:
            tag = label(0)
        elif h >= 5 and r == h // 2:
            tag = label(top * (r + 0.5) / h)
        else:
            tag = ''
        row = [(tag[:lab].rjust(lab), 'faint'), ('┤' if tag else '│', 'faint'), (' ' * (cw - len(vals)), 'text')]
        rs = level_style((r + 0.5) / h * 100) if by_level else style
        for v in vals:
            n = max(0, min(8, int(round(v / top * h * 8)) - r * 8))
            row.append((BLOCKS[n], rs) if n else ((' ', 'text') if r else ('▁', 'faint')))
        lines.append(merge(row))
    return lines


def bars(values, w, h, labels=(), hi=None, style='accent', label=lambda v: f'{v:.0f}'):
    """Vertical bars, one per value, with optional x labels under them; style may be a function of the index."""
    lab = 6
    n = max(1, len(values))
    colw = max(1, min(6, (w - lab - 1) // n - 1))
    gap = 1 if (colw + 1) * n <= w - lab - 1 else 0
    top = hi or max(values, default=0) or 1
    lines = []
    for r in range(h - 1, -1, -1):
        tag = label(top) if r == h - 1 else label(0) if r == 0 else ''
        row = [(tag[:lab].rjust(lab), 'faint'), ('┤' if tag else '│', 'faint')]
        for i, v in enumerate(values):
            k = max(0, min(8, int(round((v or 0) / top * h * 8)) - r * 8))
            st = style(i) if callable(style) else style
            row.append(((BLOCKS[k] if k else (' ' if r else '▁')) * colw, st if k else 'faint'))
            row.append((' ' * gap, 'text'))
        lines.append(merge(row))
    if labels:
        chars = [' '] * (lab + 1 + n * (colw + gap) + 8)
        last = -1
        for i, t in enumerate(labels):
            x = lab + 1 + i * (colw + gap)
            if t and x > last + 1:
                for j, ch in enumerate(t):
                    if x + j < len(chars):
                        chars[x + j] = ch
                last = x + len(t)
        lines.append([(''.join(chars).rstrip(), 'faint')])
    return lines

# ---------------------------------------------------------------- data collection


class Poller(threading.Thread):
    """Runs one collector in the background every `every()` seconds and keeps its last value or error."""

    def __init__(self, name, fn, every):
        super().__init__(daemon=True, name=name)
        self.fn, self.every = fn, every
        self.value = self.error = None
        self.at = 0.0
        self.wake = threading.Event()

    def once(self):
        try:
            self.value, self.error = self.fn(), None
        except Exception as e:  # shown in its panel; never stops the view
            self.error = (str(e) or type(e).__name__).splitlines()[0][:120]
        self.at = time.time()
        CHANGED.set()

    def run(self):
        while True:
            start = time.time()
            if not UI['paused']:
                self.once()
            self.wake.wait(max(0.2, self.every() - (time.time() - start)))
            self.wake.clear()


CHANGED = threading.Event()
UI = {'interval': 2, 'paused': False}
POLL = {}


def val(name):
    p = POLL.get(name)
    return p.value if p else None


def systemctl_show(units, props):
    """{unit id: {property: value}} from one `systemctl show` call; timestamps as epoch seconds."""
    def parse(out):
        res, cur = {}, {}
        for line in out.splitlines() + ['']:
            if not line.strip():
                if cur.get('Id'):
                    res[cur['Id']] = cur
                cur = {}
                continue
            k, _, v = line.partition('=')
            cur[k] = v
        return res
    try:
        return parse(sh(['systemctl', 'show', '--timestamp=unix', '-p', props, *units]))
    except RuntimeError:  # an older systemd without --timestamp: no times
        return parse(sh(['systemctl', 'show', '-p', props, *units]))


def ts_of(v):
    m = re.match(r'@(\d+(?:\.\d+)?)', v or '')
    return float(m[1]) if m and float(m[1]) > 0 else None


def num(v):
    return int(v) if v and v.isdigit() and int(v) < 2 ** 63 else None


def pg_unit():
    try:
        for line in sh(['systemctl', 'list-units', 'postgresql@*', '--plain', '--no-legend']).splitlines():
            if line.split():
                return line.split()[0].removesuffix('.service')
    except Exception:
        pass
    return 'postgresql'


class Sampler:
    """The fast numbers, every interval: CPU, memory, disk, network, services, processes, API connections."""

    def __init__(self):
        self.h = {k: deque(maxlen=HISTORY) for k in ('cpu', 'mem', 'rx', 'tx', 'conn', 'dr', 'dw')}
        self.svc = {s: deque(maxlen=HISTORY) for s in SERVICES}
        self.prev = {}
        self.users = {}
        self.iface = self.default_iface()
        self.pg = None
        self.clk = os.sysconf('SC_CLK_TCK')
        self.page = os.sysconf('SC_PAGE_SIZE')
        self.cores = os.cpu_count() or 1

    @staticmethod
    def default_iface():
        for line in read('/proc/net/route').splitlines()[1:]:
            p = line.split()
            if len(p) > 2 and p[1] == '00000000':
                return p[0]
        return ''

    def unit(self, s):
        if s == 'postgresql':
            if self.pg is None:
                self.pg = pg_unit()
            return self.pg
        return s

    def delta(self, key, value, t):
        """Change per second of a counter since the last sample, or None for the first one."""
        old = self.prev.get(key)
        self.prev[key] = (value, t)
        if not old or t <= old[1] or value < old[0]:
            return None
        return (value - old[0]) / (t - old[1])

    def cpu(self, t):
        out = []
        for line in read('/proc/stat').splitlines():
            if not line.startswith('cpu'):
                break
            p = line.split()
            us, ni, sy, idle, io, irq, si, st = (int(x) for x in p[1:9])
            busy, total = us + ni + sy + irq + si + st, us + ni + sy + idle + io + irq + si + st
            old = self.prev.get(p[0])
            self.prev[p[0]] = (busy, total)
            out.append(pct(busy - old[0], total - old[1]) if old and total > old[1] else None)
        return out

    def processes(self, t):
        rows, seen = [], {}
        for pid in os.listdir('/proc'):
            if not pid.isdigit():
                continue
            try:
                with open(f'/proc/{pid}/stat', 'rb') as f:
                    data = f.read().decode('utf-8', 'replace')
                r = data.rfind(')')
                comm, rest = data[data.find('(') + 1:r], data[r + 2:].split()
                ticks, rss = int(rest[11]) + int(rest[12]), int(rest[21]) * self.page
                uid = os.stat(f'/proc/{pid}').st_uid
            except (OSError, ValueError, IndexError):
                continue
            seen[pid] = ticks
            old = self.prev.get('p' + pid)
            c = (ticks - old[0]) / self.clk / (t - old[1]) * 100 if old and t > old[1] else 0.0
            rows.append({'pid': int(pid), 'uid': uid, 'cpu': c, 'rss': rss, 'comm': comm})
        for k in [k for k in self.prev if k[0] == 'p' and k[1:] not in seen]:
            del self.prev[k]
        for pid, ticks in seen.items():
            self.prev['p' + pid] = (ticks, t)
        rows.sort(key=lambda r: (r['cpu'], r['rss']), reverse=True)
        top = rows[:15]
        for r in top:
            if r['uid'] not in self.users:
                try:
                    self.users[r['uid']] = pwd.getpwuid(r['uid']).pw_name
                except KeyError:
                    self.users[r['uid']] = str(r['uid'])
            r['user'] = self.users[r['uid']]
            args = read(f'/proc/{r["pid"]}/cmdline').split('\0')
            args = [a for a in args if a]
            r['cmd'] = ' '.join([os.path.basename(args[0])] + args[1:]) if args else f'[{r["comm"]}]'
        return top, len(rows)

    def api_connections(self):
        n = 0
        for path in ('/proc/net/tcp', '/proc/net/tcp6'):
            for line in read(path).splitlines()[1:]:
                p = line.split()
                if len(p) > 3 and p[3] == '01' and p[1].rsplit(':', 1)[-1] == f'{API_PORT:04X}':
                    n += 1
        return n

    def __call__(self):
        t = time.time()
        cpus = self.cpu(t)
        mem = {}
        for line in read('/proc/meminfo').splitlines():
            k, _, v = line.partition(':')
            if v.split():
                mem[k] = int(v.split()[0]) * 1024
        total, avail = mem.get('MemTotal', 0), mem.get('MemAvailable', 0)
        du = shutil.disk_usage('/')
        rx = tx = rx_total = tx_total = None
        for line in read('/proc/net/dev').splitlines():
            name, _, rest = line.partition(':')
            if name.strip() == self.iface and rest.split():
                f = rest.split()
                rx_total, tx_total = int(f[0]), int(f[8])
                rx, tx = self.delta('rx', rx_total, t), self.delta('tx', tx_total, t)
        sr = sw = 0
        for line in read('/proc/diskstats').splitlines():
            f = line.split()
            if len(f) > 9 and re.fullmatch(r'(sd[a-z]+|vd[a-z]+|xvd[a-z]+|nvme\d+n\d+)', f[2]):
                sr, sw = sr + int(f[5]) * 512, sw + int(f[9]) * 512
        dr, dw = self.delta('dr', sr, t), self.delta('dw', sw, t)
        units = [self.unit(s) for s in SERVICES]
        try:
            info = systemctl_show(units, 'Id,ActiveState,SubState,CPUUsageNSec,MemoryCurrent,NRestarts,ActiveEnterTimestamp,TasksCurrent')
            svc_error = None
        except Exception as e:  # the rest of the sample still counts
            info, svc_error = {}, str(e).splitlines()[0][:120] if str(e) else type(e).__name__
        services = {}
        for s, u in zip(SERVICES, units):
            d = info.get(u + '.service', {})
            ns = num(d.get('CPUUsageNSec'))
            c = self.delta('svc:' + s, ns / 1e9, t) if ns is not None else None
            c = c * 100 if c is not None else None
            if not UI['paused']:
                self.svc[s].append(c or 0)
            services[s] = {'unit': u, 'state': d.get('ActiveState') or 'unknown', 'sub': d.get('SubState', ''),
                           'cpu': c, 'mem': num(d.get('MemoryCurrent')), 'restarts': num(d.get('NRestarts')),
                           'since': ts_of(d.get('ActiveEnterTimestamp')), 'tasks': num(d.get('TasksCurrent'))}
        procs, nprocs = self.processes(t)
        conn = self.api_connections()
        load = read('/proc/loadavg').split()[:3]
        mem_used = total - avail
        sample = {
            't': t, 'cpu': cpus[0] if cpus else None, 'cores': cpus[1:], 'load': load, 'nproc': self.cores,
            'uptime': float((read('/proc/uptime').split() or [0])[0]),
            'mem': {'total': total, 'used': mem_used, 'avail': avail, 'cached': mem.get('Cached', 0) + mem.get('SReclaimable', 0),
                    'buffers': mem.get('Buffers', 0), 'swap_total': mem.get('SwapTotal', 0),
                    'swap_used': mem.get('SwapTotal', 0) - mem.get('SwapFree', 0)},
            'disk': {'total': du.total, 'used': du.used}, 'dr': dr, 'dw': dw,
            'rx': rx, 'tx': tx, 'rx_total': rx_total, 'tx_total': tx_total,
            'conn': conn, 'services': services if not svc_error else {}, 'svc_error': svc_error, 'procs': procs, 'nprocs': nprocs,
        }
        for k, v in (('cpu', sample['cpu']), ('mem', pct(mem_used, total)), ('rx', rx), ('tx', tx), ('conn', conn), ('dr', dr), ('dw', dw)):
            if v is not None:
                self.h[k].append(v)
        return sample


SAMPLER = Sampler()

# ---- Redis (the traffic guard's tallies), spoken directly so no redis-cli is needed


class RedisError(Exception):
    pass


def redis(*commands):
    u = urlsplit(REDIS_URL)
    pre = []
    if u.password:
        pre.append(['AUTH', u.username, u.password] if u.username else ['AUTH', u.password])
    db = u.path.strip('/')
    if db.isdigit():
        pre.append(['SELECT', db])
    every = pre + [list(c) for c in commands]
    payload = b''
    for c in every:
        payload += b'*%d\r\n' % len(c) + b''.join(b'$%d\r\n%s\r\n' % (len(a.encode()), a.encode()) for a in map(str, c))
    with socket.create_connection((u.hostname or '127.0.0.1', u.port or 6379), timeout=2) as s:
        s.sendall(payload)
        f = s.makefile('rb')

        def reply():
            line = f.readline()
            if not line:
                raise RedisError('connection closed')
            kind, body = line[:1], line[1:-2].decode('utf-8', 'replace')
            if kind == b'+':
                return body
            if kind == b'-':
                return RedisError(body)
            if kind == b':':
                return int(body)
            if kind == b'$':
                n = int(body)
                return None if n < 0 else f.read(n + 2)[:-2].decode('utf-8', 'replace')
            if kind == b'*':
                n = int(body)
                return None if n < 0 else [reply() for _ in range(n)]
            raise RedisError(f'unexpected reply {line[:20]!r}')
        out = [reply() for _ in every]
    for r in out[:len(pre)]:
        if isinstance(r, RedisError):
            raise r
    return out[len(pre):]


USERS_HIST = deque(maxlen=HISTORY)


def traffic():
    now = time.time()
    minute, hour = int(now // 60), int(now // 3600)
    keys = [f'traffic:active:{minute - i}' for i in range(ACTIVE_WINDOW)]
    replies = redis(['PFCOUNT', *keys], ['PFCOUNT', *keys[:5]], ['PFCOUNT', keys[0]],
                    *[['PFCOUNT', k] for k in reversed(keys)], ['MGET', f'traffic:bytes:{hour}', f'traffic:bytes:{hour - 1}'])
    for r in replies:
        if isinstance(r, RedisError):
            raise r
    this_hour, last_hour = (int(x or 0) for x in replies[-1])
    sent = this_hour + last_hour * (1 - (now % 3600) / 3600)
    if not UI['paused']:
        USERS_HIST.append(replies[0])
    return {'u15': replies[0], 'u5': replies[1], 'u1': replies[2], 'per_minute': replies[3:-1], 'hour_bytes': sent,
            'busy': os.path.exists(TRAFFIC_DIR + '/busy'), 'stopped': os.path.exists(TRAFFIC_DIR + '/stopped')}


HEALTH_MS = deque(maxlen=HISTORY)


def health():
    t = time.time()
    try:
        with urllib.request.urlopen(HEALTH_URL, timeout=5) as r:
            body = r.read()
    except urllib.error.HTTPError as e:  # 503 while the database is down still has the body
        body = e.read()
    ms = (time.time() - t) * 1000
    if not UI['paused']:
        HEALTH_MS.append(ms)
    data = json.loads(body)
    data['_ms'] = ms
    return data


def egress():
    """This month's outbound data as egress-guard.sh counts it: the larger of vnstat and the guard's own counter."""
    iface = SAMPLER.iface
    limit = min(env_int('EGRESS_LIMIT_GB', 8000), 9000)
    busy_at = min(env_int('EGRESS_BUSY_GB', 6000), limit)
    now = datetime.now(timezone.utc)
    month = now.strftime('%Y-%m')
    vn_tx, days, hours, vn_err = 0, [], [], None
    try:
        traffic_ = json.loads(sh(['vnstat', '--json', '-i', iface], timeout=8))['interfaces'][0]['traffic']
        for m in traffic_.get('month', []):
            if f"{m['date']['year']}-{m['date']['month']:02d}" == month:
                vn_tx = m.get('tx', 0)
        for d in traffic_.get('day', []):
            if f"{d['date']['year']}-{d['date']['month']:02d}" == month:
                days.append((d['date']['day'], d.get('tx', 0), d.get('rx', 0)))
        for hh in traffic_.get('hour', [])[-24:]:
            hours.append((hh.get('time', {}).get('hour', 0), hh.get('tx', 0), hh.get('rx', 0)))
    except Exception as e:
        vn_err = str(e)[:80]
    own = 0
    parts = read(STATE_DIR + '/egress-counter').split()
    cur = int((read(f'/sys/class/net/{iface}/statistics/tx_bytes') or '0').strip() or 0)
    boot = read('/proc/sys/kernel/random/boot_id').strip()
    if len(parts) == 4:
        c_month, c_boot, c_last, c_sum = parts[0], parts[1], int(parts[2]), int(parts[3])
        delta = cur - c_last if c_boot == boot and c_last <= cur else cur
        own = c_sum + delta if c_month == month else delta
    used = max(vn_tx, own)
    start = datetime(now.year, now.month, 1, tzinfo=timezone.utc)
    nxt = datetime(now.year + (now.month == 12), now.month % 12 + 1, 1, tzinfo=timezone.utc)
    span, gone = (nxt - start).total_seconds(), (now - start).total_seconds()
    pace = limit * (gone + 86400) / span
    stage = ('stopped' if read(STATE_DIR + '/egress-tripped').strip() == month
             else 'busy' if os.path.exists(TRAFFIC_DIR + '/busy') else 'normal')
    days.sort()
    return {'used_gb': used / 1e9, 'limit': limit, 'busy_at': busy_at, 'pace': pace, 'stage': stage,
            'forecast': used / 1e9 * span / gone if gone > 6 * 3600 else None, 'days': days, 'hours': hours,
            'month': now.strftime('%B'), 'days_in_month': int(span // 86400), 'vnstat_error': vn_err}


def pg_conn_args():
    args = []
    for flag, name in (('-h', 'POSTGRES_HOST'), ('-p', 'POSTGRES_PORT'), ('-U', 'POSTGRES_USER'), ('-d', 'POSTGRES_DB')):
        if ENV.get(name):
            args += [flag, ENV[name]]
    return args


def psql(sql, timeout=8):
    out = sh(['runuser', '-u', 'prestop', '--', 'env', 'PGCONNECT_TIMEOUT=3', f'PGPASSWORD={ENV.get("POSTGRES_PASSWORD", "")}',
              'psql', '-XAtq', '-F|', '-v', 'ON_ERROR_STOP=1', *pg_conn_args(), '-c', sql], timeout=timeout, cwd='/tmp')
    return [r for r in out.splitlines() if r]


PG_SQL = r"""
select 'size', pg_database_size(current_database())::bigint, ''
union all select 'conn', count(*)::bigint, coalesce(state, 'other') from pg_stat_activity where datname = current_database() group by state
union all select 'max', setting::bigint, '' from pg_settings where name = 'max_connections'
union all select 'xact', (xact_commit + xact_rollback)::bigint, '' from pg_stat_database where datname = current_database()
union all select 'hit', blks_hit::bigint, blks_read::text from pg_stat_database where datname = current_database()
union all (select 'tbl', pg_total_relation_size(c.oid)::bigint, c.relname::text from pg_class c
           where c.relkind = 'r' and c.relnamespace = 'public'::regnamespace order by 2 desc limit 8)
union all (select 'long', extract(epoch from now() - query_start)::bigint, regexp_replace(left(query, 160), '\s+', ' ', 'g')
           from pg_stat_activity where state = 'active' and pid <> pg_backend_pid() and datname = current_database() order by 2 desc limit 1)
union all select 'ver', 0, current_setting('server_version')
"""
DB_HIST = {'tps': deque(maxlen=240), 'ops': deque(maxlen=240)}
DB_PREV = {}


def databases():
    out = {'pg': None, 'pg_error': None, 'redis': None, 'redis_error': None}
    t = time.time()
    try:
        pg = {'conn': {}, 'tables': [], 'long': None}
        for row in psql(PG_SQL):
            k, a, b = (row.split('|', 2) + ['', ''])[:3]
            a = int(a or 0)
            if k == 'conn':
                pg['conn'][b] = a
            elif k == 'tbl':
                pg['tables'].append((b, a))
            elif k == 'long':
                pg['long'] = (a, b)
            elif k == 'hit':
                pg['hit'] = pct(a, a + int(b or 0))
            elif k == 'ver':
                pg['version'] = b.split()[0] if b else ''
            else:
                pg[k] = a
        old = DB_PREV.get('xact')
        DB_PREV['xact'] = (pg.get('xact', 0), t)
        pg['tps'] = (pg.get('xact', 0) - old[0]) / (t - old[1]) if old and t > old[1] else None
        if pg['tps'] is not None and not UI['paused']:
            DB_HIST['tps'].append(pg['tps'])
        out['pg'] = pg
    except Exception as e:
        out['pg_error'] = str(e)[:120]
    try:
        text, = redis(['INFO'])
        if isinstance(text, RedisError):
            raise text
        info = dict(line.split(':', 1) for line in text.splitlines() if ':' in line and not line.startswith('#'))
        hits, misses = int(info.get('keyspace_hits', 0)), int(info.get('keyspace_misses', 0))
        ops = int(info.get('instantaneous_ops_per_sec', 0))
        if not UI['paused']:
            DB_HIST['ops'].append(ops)
        keys = {}
        for k, v in info.items():
            if re.fullmatch(r'db\d+', k):
                keys[k] = int(dict(x.split('=') for x in v.split(',')).get('keys', 0))
        out['redis'] = {'mem': int(info.get('used_memory', 0)), 'peak': int(info.get('used_memory_peak', 0)),
                        'maxmem': int(info.get('maxmemory', 0)), 'clients': int(info.get('connected_clients', 0)), 'ops': ops,
                        'hit': pct(hits, hits + misses), 'keys': keys, 'version': info.get('redis_version', ''),
                        'uptime': int(info.get('uptime_in_seconds', 0)), 'evicted': int(info.get('evicted_keys', 0))}
    except Exception as e:
        out['redis_error'] = str(e)[:120]
    return out


def timers():
    rows = {t: {} for t in TIMERS}
    try:
        for t in json.loads(sh(['systemctl', 'list-timers', '--all', '-o', 'json'])):
            name = (t.get('unit') or '').removesuffix('.timer')
            if name in rows:
                rows[name]['next'] = (t.get('next') or 0) / 1e6 or None
                rows[name]['last'] = (t.get('last') or 0) / 1e6 or None
    except Exception:
        pass
    info = systemctl_show([t + '.timer' for t in TIMERS] + [t + '.service' for t in TIMERS],
                          'Id,ActiveState,Result,ExecMainStatus,LastTriggerUSec,NextElapseUSecRealtime,ExecMainStartTimestamp,ExecMainExitTimestamp')
    for t in TIMERS:
        tm, sv = info.get(t + '.timer', {}), info.get(t + '.service', {})
        r = rows[t]
        r.setdefault('last', ts_of(tm.get('LastTriggerUSec')))
        r.setdefault('next', ts_of(tm.get('NextElapseUSecRealtime')))
        r['timer'] = tm.get('ActiveState') or 'unknown'
        r['state'] = sv.get('ActiveState') or 'unknown'
        r['result'] = sv.get('Result') or ''
        r['status'] = sv.get('ExecMainStatus') or ''
        start, end = ts_of(sv.get('ExecMainStartTimestamp')), ts_of(sv.get('ExecMainExitTimestamp'))
        r['took'] = end - start if start and end and end >= start else None
    files = sorted(glob.glob(BACKUP_DIR + '/prestop-*.dump'), key=lambda p: os.path.getmtime(p))
    backups = [(os.path.basename(p), os.path.getsize(p), os.path.getmtime(p)) for p in files]
    return {'timers': rows, 'backups': backups}


def logs():
    units = [SAMPLER.unit(s) for s in SERVICES] + [t for t in TIMERS]
    cmd = ['journalctl', '--no-pager', '-o', 'json', '-p', 'warning', '--since', '24 hours ago', '-n', '500']
    for u in units:
        cmd += ['-u', u + '.service']
    entries = []
    for raw in sh(cmd, timeout=15).splitlines():
        try:
            e = json.loads(raw)
        except ValueError:
            continue
        msg = e.get('MESSAGE', '')
        if isinstance(msg, list):
            msg = bytes(msg).decode('utf-8', 'replace')
        unit = (e.get('_SYSTEMD_UNIT') or e.get('SYSLOG_IDENTIFIER') or '?').removesuffix('.service')
        entries.append({'t': int(e.get('__REALTIME_TIMESTAMP') or 0) / 1e6, 'p': int(e.get('PRIORITY') or 6),
                        'unit': unit.removeprefix('prestop-'), 'msg': str(msg).replace('\t', '  ')})
    entries.reverse()
    return entries


# Stay-on learning (prestop_statistics/stays.py). A day counts for a feed when the collector recorded FULL_DAY (95 %)
# of it and the feed had vehicles for FEED_SECONDS; GATE_DAYS of them in a row within the last 56 days open the feed,
# and the nightly job then learns it. Keep the numbers in step with stays.py.
FULL_DAY, FEED_SECONDS, GATE_DAYS, BUDGET = 82080, 3600, 7, 4320


def learning():
    today = datetime.now(TZ).date()
    elapsed = time.time() - datetime.combine(today, dtime(0), TZ).timestamp()
    rows = psql(f"""
      select 'd', '{today}'::date - day, feed, seconds::bigint from prestop_statistics_recorderday
        where day > '{today}'::date - 57 and version >= 2
      union all select 's', 0, feed || ' ' || level, count(*) from prestop_statistics_staydeparture where level <> '' group by feed, level
      union all select 'l', '{today}'::date - max(learned_on), '', 0 from prestop_statistics_staydeparture having count(*) > 0
      union all select 'c', sum(misses), level, sum(hits) from prestop_statistics_staycheck where day >= '{today}'::date - 14 group by level""")
    col, fs, feeds, lv, hits, miss, learned = {}, {}, set(), {}, {}, {}, None
    for r in rows:
        k, a, b, c = (r.split('|') + ['', '', ''])[:4]
        a, c = int(a or 0), int(c or 0)
        if k == 'd':
            if b == '*':
                col[a] = c
            else:
                fs[b, a] = c
                feeds.add(b)
        elif k == 's':
            f, _, level = b.partition(' ')
            lv[f, level] = c
        elif k == 'l':
            learned = a
        elif k == 'c':
            hits[b], miss[b] = c, a
    down = max(0, elapsed - col.get(0, 0))
    if 0 not in col and elapsed > 600:
        status = ('bad', 'collector is not recording')
    elif down > BUDGET:
        status = ('bad', 'today will not count')
    elif down > BUDGET * 0.7:
        status = ('warn', 'at risk')
    else:
        status = ('ok', 'on track')
    today_ok = status[0] != 'bad'

    def counted(f, d):
        return col.get(d, 0) >= FULL_DAY and fs.get((f, d), 0) >= FEED_SECONDS
    out = []
    for f in sorted(feeds):
        run, opened = 0, False
        for d in range(56, 0, -1):
            if counted(f, d):
                run += 1
                opened = opened or run >= GATE_DAYS
            else:
                run = 0
        at = GATE_DAYS - run if today_ok else GATE_DAYS + 1
        out.append({'feed': f, 'open': opened, 'run': run, 'opens': today + timedelta(days=at),
                    'sure': lv.get((f, 'sure'), 0), 'likely': lv.get((f, 'likely'), 0),
                    'days': [counted(f, d) for d in range(14, 0, -1)]})
    hour = datetime.now(TZ).hour
    return {'today': today, 'share': pct(col.get(0, 0), elapsed), 'down': down, 'status': status, 'feeds': out,
            'nightly_missing': any(f['open'] for f in out) and hour >= 5 and (learned is None or learned > 0),
            'checks': {lvl: (hits[lvl], hits[lvl] + miss[lvl]) for lvl in ('sure', 'likely') if lvl in hits},
            'collector': [(today - timedelta(days=d), col.get(d, 0) / 86400) for d in range(14, 0, -1)]}


def start_pollers():
    every = lambda: UI['interval']  # noqa: E731
    for name, fn, ev in (('sample', SAMPLER, every), ('traffic', traffic, every), ('health', health, lambda: max(3, UI['interval'])),
                         ('egress', egress, lambda: 30), ('db', databases, lambda: 10), ('timers', timers, lambda: 15),
                         ('logs', logs, lambda: 15), ('learning', learning, lambda: 60)):
        POLL[name] = Poller(name, fn, ev)
    for p in POLL.values():
        p.start()

# ---------------------------------------------------------------- what needs a look


def alerts():
    """(level, tab, text) for everything worth a look, worst first."""
    out = []
    s, h, e, t, lr, tm, lg = (val(n) for n in ('sample', 'health', 'egress', 'traffic', 'learning', 'timers', 'logs'))
    if s:
        if s['svc_error']:
            out.append(('bad', 'services', f'systemd: {s["svc_error"]}'))
        for name, d in s['services'].items():
            if d['state'] != 'active':
                out.append(('bad' if d['state'] in ('failed', 'inactive', 'unknown') else 'warn', 'services', f'{name} is {d["state"]}'))
        dp = pct(s['disk']['used'], s['disk']['total'])
        if dp >= 80:
            out.append((level_style(dp, 80, 90), 'system', f'disk {dp:.0f} % full'))
        mp = pct(s['mem']['used'], s['mem']['total'])
        if mp >= 85:
            out.append((level_style(mp, 85, 95), 'system', f'memory {mp:.0f} % used'))
        recent = list(SAMPLER.h['cpu'])[-30:]
        if len(recent) >= 10 and sum(recent) / len(recent) >= 85:
            out.append(('warn', 'system', f'CPU busy {sum(recent) / len(recent):.0f} % for the last {dur(len(recent) * UI["interval"])}'))
    if h is None and POLL['health'].error:
        out.append(('bad', 'data', f'health check failed: {POLL["health"].error}'))
    elif h:
        if h.get('database') != 'ready':
            out.append(('bad', 'data', f'database {h.get("database")}'))
        c = h.get('collector') or {}
        if c.get('status') and c['status'] != 'live':
            out.append((status_style(c['status']), 'data', f'delay collector {c["status"]}'))
        for o in h.get('outages') or []:
            out.append(('bad', 'data', f'SŽ {o.get("id")} {o.get("status")} for {o.get("minutes")} min'))
        cov = h.get('coverage')
        if cov and cov.get('unexplained'):
            out.append(('warn', 'data', f'{cov["unexplained"]} buses left out unexplained (yarn coverage)'))
        if h.get('maintenance'):
            out.append(('warn', 'data', 'maintenance notice is on'))
    if e:
        if e['stage'] == 'stopped':
            out.append(('bad', 'traffic', 'egress limit reached: public traffic stopped'))
        elif e['stage'] == 'busy':
            out.append(('warn', 'traffic', 'egress guard is turning new visitors away'))
        elif e['used_gb'] > e['pace']:
            out.append(('warn', 'traffic', 'outbound data ahead of the month\'s pace'))
    elif POLL['egress'].error:
        out.append(('warn', 'traffic', f'egress: {POLL["egress"].error}'))
    if t and t['u15'] > MAX_ACTIVE * 0.8:
        out.append(('warn', 'traffic', f'{t["u15"]} visitors in 15 min (busy at {MAX_ACTIVE})'))
    if t is None and POLL['traffic'].error:
        out.append(('warn', 'traffic', f'Redis: {POLL["traffic"].error}'))
    if lr:
        if lr['status'][0] != 'ok':
            out.append((lr['status'][0], 'learning', f'learning: {lr["status"][1]}'))
        if lr['nightly_missing']:
            out.append(('bad', 'learning', 'nightly learning has not run today'))
    elif POLL['learning'].error:
        out.append(('warn', 'learning', f'learning: {POLL["learning"].error}'))
    if tm:
        for name, r in tm['timers'].items():
            if r['result'] and r['result'] != 'success':
                out.append(('bad', 'services', f'{name.removeprefix("prestop-")} last run failed ({r["result"]})'))
        b = tm['backups']
        if not b:
            out.append(('warn', 'services', 'no database backup found'))
        elif time.time() - b[-1][2] > 30 * 3600:
            out.append(('warn', 'services', f'last backup {ago(b[-1][2])}'))
    if lg:
        n = sum(1 for x in lg if x['p'] <= 3 and x['t'] > time.time() - 3600)
        if n:
            out.append(('warn', 'logs', f'{n} error{"s" * (n != 1)} logged in the last hour'))
    out.sort(key=lambda a: -LEVEL[a[0]])
    return out

# ---------------------------------------------------------------- tabs


def svc_name(s):
    return s.removeprefix('prestop-')


def tab_overview(w):
    s = val('sample')

    def resources(iw):
        if not s:
            return unavailable('sample')
        H, m, d = SAMPLER.h, s['mem'], s['disk']
        mw = max(8, min(26, iw // 4))
        sw = iw - 9 - mw - 2 - 16 - 1

        def row(label, p, value, hist, hi=100, style='accent', by_level=True):
            line = [(f'{label:<9}', 'dim')] + meter(p, mw) + [('  ' + value.ljust(16)[:16] + ' ', 'text')]
            return line + (spark(hist, sw, hi=hi, style=style, by_level=by_level) if hist is not None and sw >= 6 else [])
        cpu = s['cpu']
        lines = [row('CPU', cpu, f'{cpu:.0f} % busy' if cpu is not None else '', H['cpu']),
                 row('Memory', pct(m['used'], m['total']), f'{m["used"] / GIB:.1f} / {m["total"] / GIB:.1f} GB', H['mem'])]
        if m['swap_total']:
            lines.append(row('Swap', pct(m['swap_used'], m['swap_total']), f'{m["swap_used"] / GIB:.1f} / {m["swap_total"] / GIB:.1f} GB', None))
        lines.append(row('Disk', pct(d['used'], d['total']), f'{d["used"] / GIB:.0f} / {d["total"] / GIB:.0f} GB', None))
        net = [('Network  ', 'dim'), ('↓ ', 'rx'), (rate(s['rx']).ljust(11), 'text'), ('↑ ', 'tx'), (rate(s['tx']).ljust(11), 'text')]
        net = fit(net, 9 + mw + 2 + 16 + 1)
        if sw >= 13:
            half = (sw - 1) // 2
            net += spark(H['rx'], half, style='rx') + blank(1) + spark(H['tx'], sw - half - 1, style='tx')
        lines.append(net)
        lines.append(kv('Load', ' '.join(s['load']), ('  ·  ', 'faint'), f'{s["nproc"]} cores', ('  ·  ', 'faint'),
                        f'up {dur(s["uptime"])}', lw=9))
        return lines

    def traffic_(iw):
        t, e = val('traffic'), val('egress')
        mw = max(8, min(26, iw // 4))
        lines = []
        if t:
            lines.append([('Visitors ', 'dim')] + meter(pct(t['u15'], MAX_ACTIVE), mw) +
                         L(('  ' + f'{t["u15"]} in 15 min'.ljust(16), 'bold'), (f'now {t["u1"]} · 5 min {t["u5"]} · busy at {MAX_ACTIVE}', 'dim')))
            lines.append([('API out  ', 'dim')] + meter(pct(t['hour_bytes'], HOURLY_BYTES), mw) +
                         L(('  ' + f'{size(t["hour_bytes"])} / hour'.ljust(16), 'text'), (f'of {HOURLY_BYTES / 1e9:.0f} GB an hour', 'dim')))
        else:
            lines += unavailable('traffic')
        if s:
            sw = iw - 9 - mw - 2 - 16
            lines.append(kv('API', f'{s["conn"]} open connections'.ljust(mw + 2 + 16)[:mw + 18], lw=9) +
                         (spark(SAMPLER.h['conn'], sw, style='purple') if sw >= 6 else []))
        if e:
            lines.append([('Egress   ', 'dim')] + meter(pct(e['used_gb'], e['limit']), mw, marker=pct(e['pace'], e['limit'])) +
                         L(('  ' + f'{e["used_gb"]:.0f} / {e["limit"]} GB'.ljust(16), 'bold'),
                           (e['stage'], status_style({'normal': 'live', 'busy': 'stale'}.get(e['stage'], 'x'))),
                           (f' · pace {e["pace"]:.0f}' + (f' · month ≈ {e["forecast"]:.0f}' if e['forecast'] else ''), 'dim')))
        else:
            lines += [kv('Egress', *unavailable('egress')[0], lw=9)]
        return lines

    def services(iw):
        if not s:
            return unavailable('sample')
        if s['svc_error']:
            return [L(('unavailable', 'bad'), ('  ' + s['svc_error'], 'dim'))]
        out = []
        for name, d in s['services'].items():
            c = d['cpu']
            out.append(L(('● ', status_style(d['state'])), cell(svc_name(name), 13), cell(d['state'], 11, status_style(d['state'])),
                         cell(f'{c:.1f}%' if c is not None else '–', 6, 'text', True), cell(size(d['mem']) if d['mem'] else '–', 10, 'text', True),
                         ('   up ' + dur(time.time() - d['since']) if d['state'] == 'active' and d['since'] else '', 'dim')))
        return out

    def health_(iw):
        h = val('health')
        if not h:
            return unavailable('health')
        c = h.get('collector') or {}
        srcs = h.get('sources') or []
        live = sum(1 for x in srcs if x.get('status') == 'live')
        down = [x['id'] for x in srcs if x.get('status') != 'live']
        cov = h.get('coverage')
        lines = [kv('API', ('● ', status_style(h.get('api'))), f'{h.get("api")} · {h["_ms"]:.0f} ms  ') +
                 spark(HEALTH_MS, max(0, iw - 30), style='accent'),
                 kv('Database', ('● ', status_style(h.get('database'))), str(h.get('database'))),
                 kv('Collector', ('● ', status_style(c.get('status'))), str(c.get('status', '?')),
                    (f' · {ago(parse_iso(c["updatedAt"]))}' if c.get('updatedAt') else '', 'dim')),
                 kv('Sources', ('● ', 'ok' if not down else 'warn'), f'{live}/{len(srcs)} live',
                    ('  ' + ', '.join(down[:4]) + (' …' if len(down) > 4 else '') if down else '', 'dim'))]
        if cov:
            parts = []
            if cov.get('map'):
                parts.append(f'map {cov["map"].get("drawn")}/{cov["map"].get("inFeed")}')
            if cov.get('boards'):
                parts.append(f'boards {cov["boards"].get("shown")}/{cov["boards"].get("checked")}')
            lines.append(kv('Coverage', ('● ', 'warn' if cov.get('unexplained') else 'ok'),
                            ' · '.join(parts + [f'{cov.get("unexplained", 0)} unexplained']),
                            (f' · {ago(parse_iso(cov.get("sampledAt")))}', 'dim')))
        else:
            lines.append(kv('Coverage', ('no sample in the last 45 min', 'dim')))
        lr = val('learning')
        if lr:
            n = sum(1 for f in lr['feeds'] if f['open'])
            lines.append(kv('Learning', ('● ', lr['status'][0]), f'{lr["share"]:.1f} % of today recorded · {lr["status"][1]}',
                            (f' · {n}/{len(lr["feeds"])} feeds open', 'dim')))
        tm = val('timers')
        if tm:
            b = tm['backups']
            lines.append(kv('Backup', ('● ', 'ok' if b and time.time() - b[-1][2] < 30 * 3600 else 'warn'),
                            f'{ago(b[-1][2])} · {size(b[-1][1])}' if b else 'none found'))
            nxt = sorted((r['next'], n) for n, r in tm['timers'].items() if r.get('next'))
            if nxt:
                lines.append(kv('Next', *sum(([(svc_name(n), 'text'), (f' in {dur(t - time.time())}   ', 'dim')] for t, n in nxt[:3]), [])))
        return lines

    def alerts_(iw):
        a = alerts()
        if not a:
            return [L(('● ', 'ok'), ('Everything looks fine.', 'ok'), ('  Nothing needs a look right now.', 'dim'))]
        return [L(('● ', lvl), (text, 'bad' if lvl == 'bad' else 'text'), (f'   → {tab}', 'faint')) for lvl, tab, text in a]

    a = alerts()
    worst = max((LEVEL[x[0]] for x in a), default=0)
    note = ['all clear', f'{len(a)} to check', f'{len(a)} to check'][worst]
    return (panel('Needs a look' if a else 'Status', alerts_(w - 4), w, note, ['ok', 'warn', 'bad'][worst]) +
            columns(w, [lambda cw: panel('Resources', resources(cw - 4), cw, f'last {dur(len(SAMPLER.h["cpu"]) * UI["interval"])}'),
                        lambda cw: panel('Traffic', traffic_(cw - 4), cw)],
                    [lambda cw: panel('Services', services(cw - 4), cw),
                     lambda cw: panel('Health', health_(cw - 4), cw)]))


def tab_system(w):
    s = val('sample')
    if not s:
        return panel('System', unavailable('sample'), w)
    H, m = SAMPLER.h, s['mem']
    span = f'last {dur(len(H["cpu"]) * UI["interval"])}'

    def cpu(cw):
        iw = cw - 4
        body = area(H['cpu'], iw, 7, hi=100, by_level=True, label=lambda v: f'{v:.0f}%')
        cores = s['cores']
        per = max(1, (iw + 2) // max(1, min(len(cores), 4)) - 2)
        row, rows = [], []
        for i, c in enumerate(cores):
            row += [(f'cpu{i} ', 'dim')] + meter(c, max(4, per - 11)) + [(f' {c or 0:3.0f}%  ', 'text')]
            if (i + 1) % 4 == 0:
                rows.append(row)
                row = []
        if row:
            rows.append(row)
        load = s['load']
        return panel('CPU', body + [[]] + rows + [kv('load', f'{load[0]}  {load[1]}  {load[2]}', ('  (1, 5, 15 min)', 'dim'), lw=5)],
                     cw, f'{s["cpu"] or 0:.0f} % · {span}')

    def memory(cw):
        iw = cw - 4
        body = area(H['mem'], iw, 5, hi=100, by_level=True, label=lambda v: f'{v:.0f}%')
        tot = m['total'] or 1
        mw = max(6, iw - 32)
        body.append([])
        for label, v, st in (('used', m['used'], 'accent'), ('cache', m['cached'] + m['buffers'], 'purple'), ('free', m['avail'], 'ok')):
            body.append(kv(label, ) + meter(pct(v, tot), mw, st) + L((f'  {v / GIB:6.2f} GB  {pct(v, tot):3.0f} %', 'text')))
        if m['swap_total']:
            body.append(kv('swap') + meter(pct(m['swap_used'], m['swap_total']), mw) + L((f'  {m["swap_used"] / GIB:6.2f} GB of {m["swap_total"] / GIB:.1f}', 'text')))
        return panel('Memory', body, cw, f'{m["used"] / GIB:.1f} of {m["total"] / GIB:.1f} GB')

    def network(cw):
        iw = cw - 4
        body = [L(('↓ in   ', 'rx'), (rate(s['rx']).ljust(12), 'bold'), (f'peak {rate(max(H["rx"], default=0))}', 'dim'),
                  (f' · since boot {size(s["rx_total"])}', 'dim'))]
        body += area(H['rx'], iw, 4, style='rx', label=short)
        body += [L(('↑ out  ', 'tx'), (rate(s['tx']).ljust(12), 'bold'), (f'peak {rate(max(H["tx"], default=0))}', 'dim'),
                   (f' · since boot {size(s["tx_total"])}', 'dim'))]
        body += area(H['tx'], iw, 4, style='tx', label=short)
        return panel('Network', body, cw, SAMPLER.iface or '?')

    def disk(cw):
        iw = cw - 4
        d = s['disk']
        mw = max(6, iw - 30)
        sw = max(0, iw - 22)
        return panel('Disk', [kv('root /', lw=8) + meter(pct(d['used'], d['total']), mw) +
                              L((f'  {d["used"] / GIB:.0f} / {d["total"] / GIB:.0f} GB  {pct(d["used"], d["total"]):.0f} %', 'text')),
                              kv('read', (rate(s['dr']).ljust(14), 'text'), lw=8) + spark(H['dr'], sw, style='rx'),
                              kv('write', (rate(s['dw']).ljust(14), 'text'), lw=8) + spark(H['dw'], sw, style='tx')], cw)

    def procs(cw):
        iw = cw - 4
        rows = [L(cell('PID', 7, 'dim', True), ('  ', 'dim'), cell('USER', 10, 'dim'), cell('CPU', 7, 'dim', True), cell('MEM', 10, 'dim', True),
                  ('   ', 'dim'), ('COMMAND', 'dim'))]
        for p in s['procs'][:12]:
            rows.append(L(cell(p['pid'], 7, 'faint', True), ('  ', 'text'), cell(p['user'], 10, 'dim'),
                          cell(f'{p["cpu"]:.1f}%', 7, level_style(p['cpu'], 50, 90), True), cell(size(p['rss']), 10, 'text', True),
                          ('   ', 'text'), (p['cmd'], 'text')))
        return panel('Processes', rows, cw, f'top {min(12, len(s["procs"]))} of {s["nprocs"]} by CPU')
    return columns(w, [cpu, memory], [network, disk]) + procs(w)


def tab_services(w):
    s, tm = val('sample'), val('timers')
    out = []
    if s and s['svc_error']:
        out += panel('Services', [L(('unavailable', 'bad'), ('  ' + s['svc_error'], 'dim'))], w)
    elif s:
        iw = w - 4
        stw = 27 if iw >= 110 else 13
        sw = max(0, iw - 61 - stw)
        rows = [L(('  ', 'dim'), cell('SERVICE', 13, 'dim'), cell('STATE', stw, 'dim'), cell('UP FOR', 10, 'dim'), cell('RESTARTS', 9, 'dim', True),
                  cell('CPU', 8, 'dim', True), ('  ', 'dim'), cell('CPU HISTORY' if sw >= 8 else '', sw, 'dim'),
                  cell('MEMORY', 10, 'dim', True), cell('TASKS', 7, 'dim', True))]
        for name, d in s['services'].items():
            st = status_style(d['state'])
            up = dur(time.time() - d['since']) if d['state'] == 'active' and d['since'] else '–'
            rows.append(L(('● ', st), cell(svc_name(name), 13, 'bold'), cell(f'{d["state"]} ({d["sub"]})' if d['sub'] and stw > 13 else d['state'], stw, st),
                          cell(up, 10, 'text'), cell(d['restarts'] if d['restarts'] is not None else '–', 9, 'warn' if d['restarts'] else 'faint', True),
                          cell(f'{d["cpu"]:.1f}%' if d['cpu'] is not None else '–', 8, 'text', True), ('  ', 'text'),
                          *(spark(SAMPLER.svc[name], sw, style='accent') if sw >= 8 else [cell('', sw)]),
                          cell(size(d['mem']) if d['mem'] else '–', 10, 'text', True), cell(d['tasks'] if d['tasks'] is not None else '–', 7, 'dim', True)))
        out += panel('Services', rows, w, f'{sum(1 for d in s["services"].values() if d["state"] == "active")}/{len(s["services"])} running')
    else:
        out += panel('Services', unavailable('sample'), w)
    if tm:
        rows = [L(('  ', 'dim'), cell('TIMER', 12, 'dim'), cell('LAST RUN', 22, 'dim'), cell('RESULT', 16, 'dim'), cell('TOOK', 9, 'dim'), ('NEXT RUN', 'dim'))]
        for name, r in tm['timers'].items():
            running = r['state'] in ('activating', 'active') and r['state'] != 'inactive'
            res = 'running now' if running else (r['result'] or '–') + (f' ({r["status"]})' if r['result'] not in ('success', '') and r['status'] else '')
            st = 'accent' if running else status_style(r['result']) if r['result'] else 'faint'
            last = f'{clock(r["last"], "%a %H:%M")}  {ago(r["last"])}' if r.get('last') else 'never'
            nxt = f'{clock(r["next"], "%a %H:%M")}  in {dur(r["next"] - time.time())}' if r.get('next') else '–'
            rows.append(L(('● ', status_style(r['timer']) if r['timer'] != 'unknown' else 'faint'), cell(svc_name(name), 12, 'bold'), cell(last, 22, 'text'),
                          cell(res, 16, st), cell(dur(r['took']) if r['took'] is not None else '–', 9, 'dim'), (nxt, 'text')))
        out += panel('Timers', rows, w)
        b = tm['backups']
        if b:
            iw = w - 4
            sizes = [x[1] for x in b]
            body = [kv('latest', (b[-1][0], 'bold'), f'  {size(b[-1][1])}', (f'  ·  {clock(b[-1][2], "%a %d %b %H:%M")}  ({ago(b[-1][2])})', 'dim')),
                    kv('kept', f'{len(b)} dumps · {size(sum(sizes))}', ('  in ' + BACKUP_DIR, 'dim'))]
            body += [[]] + bars(sizes, min(iw, 8 + len(b) * 7), 3, labels=[clock(x[2], '%d %b') for x in b], label=short,
                                style=lambda i: 'accent' if i == len(b) - 1 else 'purple')
            out += panel('Backups', body, w, 'pg_dump nightly at 03:00')
        else:
            out += panel('Backups', [L(('no dumps in ' + BACKUP_DIR, 'warn'))], w)
    else:
        out += panel('Timers', unavailable('timers'), w)
    return out


def tab_traffic(w):
    t, e, s = val('traffic'), val('egress'), val('sample')
    out = []

    def visitors(cw):
        iw = cw - 4
        if not t:
            return panel('Visitors', unavailable('traffic'), cw)
        body = [L(('now ', 'dim'), (str(t['u1']), 'bold'), ('    5 min ', 'dim'), (str(t['u5']), 'bold'),
                  ('    15 min ', 'dim'), (str(t['u15']), 'bold'), (f'  of {MAX_ACTIVE} before busy', 'dim')),
                [('busy   ', 'dim')] + meter(pct(t['u15'], MAX_ACTIVE), max(6, iw - 14)) + L((f' {pct(t["u15"], MAX_ACTIVE):4.1f} %', 'text')), [],
                L(('new visitors per minute', 'dim'))]
        body += bars(t['per_minute'], iw, 5, labels=[f'-{ACTIVE_WINDOW - 1 - i}m' if i % 5 == 4 else '' for i in range(ACTIVE_WINDOW - 1)] + ['now'],
                     style=lambda i: 'accent' if i == ACTIVE_WINDOW - 1 else 'purple')
        if len(USERS_HIST) > 2:
            body += [[], L(('visitors in 15 min, since this view opened', 'dim'))] + area(USERS_HIST, iw, 4, style='accent')
        return panel('Visitors', body, cw, 'hashed IPs, traffic guard')

    def api(cw):
        iw = cw - 4
        body = []
        if s:
            body += [L(('open connections ', 'dim'), (str(s['conn']), 'bold'), (f'  peak {max(SAMPLER.h["conn"], default=0)}', 'dim'))]
            body += area(SAMPLER.h['conn'], iw, 4, style='purple')
        if t:
            body += [[], L(('sent in the last hour ', 'dim'), (size(t['hour_bytes']), 'bold'), (f'  of {HOURLY_BYTES / 1e9:.0f} GB', 'dim')),
                     meter(pct(t['hour_bytes'], HOURLY_BYTES), iw)]
            flags = [x for x, on in (('busy', t['busy']), ('stopped', t['stopped'])) if on]
            body += [L(('guard ', 'dim'), (', '.join(flags) if flags else 'letting everyone in', 'warn' if flags else 'ok'))]
        return panel('API', body or unavailable('traffic'), cw, f':{API_PORT}')

    out += columns(w, [visitors], [api])
    iw = w - 4
    if e:
        body = [L((f'{e["used_gb"]:.1f} GB', 'bold'), (f' of {e["limit"]} GB sent in {e["month"]}', 'dim'), ('   stage ', 'dim'),
                  (e['stage'], {'normal': 'ok', 'busy': 'warn'}.get(e['stage'], 'bad'))),
                meter(pct(e['used_gb'], e['limit']), iw, marker=pct(e['pace'], e['limit'])),
                L(('┃', 'accentb'), (f' pace {e["pace"]:.0f} GB', 'dim'), ('   busy at ', 'dim'), (f'{e["busy_at"]} GB', 'text'),
                  ('   stop at ', 'dim'), (f'{e["limit"]} GB', 'text'), ('   Oracle bills above 10000 GB', 'faint'))]
        if e['forecast']:
            body.append(L(('at this rate ', 'dim'), (f'≈ {e["forecast"]:.0f} GB', level_style(pct(e['forecast'], e['limit']), 60, 90)),
                          (' by the end of the month', 'dim')))
        if e['days']:
            per = {d: tx for d, tx, _ in e['days']}
            vals = [per.get(d, 0) for d in range(1, e['days_in_month'] + 1)]
            today = datetime.now(timezone.utc).day
            body += [[], L(('sent per day (vnstat)', 'dim'))]
            body += bars(vals, iw, 5, labels=[str(d) if d == 1 or d % 5 == 0 else '' for d in range(1, len(vals) + 1)], label=short,
                         style=lambda i: 'accent' if i + 1 == today else 'purple')
        if e['hours']:
            body += [[], L(('sent per hour, last 24 h', 'dim'))]
            body += bars([x[1] for x in e['hours']], iw, 4, labels=[f'{x[0]:02d}' if x[0] % 3 == 0 else '' for x in e['hours']],
                         label=short, style='tx')
        if e['vnstat_error']:
            body.append(L(('vnstat: ', 'dim'), (e['vnstat_error'], 'warn')))
        out += panel('Outbound data', body, w, 'egress guard, every 5 min')
    else:
        out += panel('Outbound data', unavailable('egress'), w)
    return out


def tab_data(w):
    h, db = val('health'), val('db')

    def api(cw):
        iw = cw - 4
        if not h:
            return panel('API health', unavailable('health'), cw)
        c = h.get('collector') or {}
        body = [kv('API', ('● ', status_style(h.get('api'))), str(h.get('api')), (f'  {h["_ms"]:.0f} ms', 'bold'), ('  /api/v1/health', 'faint')),
                kv('Database', ('● ', status_style(h.get('database'))), str(h.get('database'))),
                kv('Collector', ('● ', status_style(c.get('status'))), str(c.get('status', '?')),
                   (f'  last success {ago(parse_iso(c.get("updatedAt")))}' if c.get('updatedAt') else '', 'dim'))]
        mt = h.get('maintenance')
        if mt:
            body.append(kv('Maintenance', ('on ', 'warn'), (f'until {clock(parse_iso(mt.get("until")))}', 'dim')))
        body += [[], L(('response time', 'dim'))] + area(HEALTH_MS, iw, 4, style='accent', label=lambda v: f'{v:.0f}ms')
        cov = h.get('coverage')
        body.append([])
        if cov:
            mp, bd = cov.get('map') or {}, cov.get('boards') or {}
            if mp:
                body.append(kv('Map', f'{mp.get("drawn")}/{mp.get("inFeed")} buses drawn', lw=13))
            if bd:
                body.append(kv('Boards', f'{bd.get("shown")}/{bd.get("checked")} shown at {bd.get("stops")} stops', lw=13))
            body.append(kv('Unexplained', (str(cov.get('unexplained', 0)), 'warn' if cov.get('unexplained') else 'ok'),
                           (f'  sampled {ago(parse_iso(cov.get("sampledAt")))} · details: yarn coverage', 'dim'), lw=13))
        else:
            body.append(kv('Coverage', ('no sample in the last 45 min', 'dim')))
        sz = h.get('sz') or {}
        if sz:
            body.append([])
            if sz.get('sources'):
                body.append(kv('SŽ delays', ' · '.join(f'{k} {v}' for k, v in sz['sources'].items()), ('  trains by source', 'dim')))
            for pair, n in (sz.get('pairs') or {}).items():
                body.append(kv('', (pair, 'dim'), f'  {n.get("differ", 0)} of {n.get("checked", 0)} differ by > 2 min'))
            rt = sz.get('rt') or {}
            if rt:
                body.append(kv('ijpp-rt', ('● ', status_style(rt.get('status'))), str(rt.get('status')),
                               (f'  since {clock(parse_iso(rt.get("since")), "%d %b %H:%M")}' if rt.get('since') else '', 'dim')))
        for o in h.get('outages') or []:
            body.append(kv('Outage', ('● ', 'bad'), (f'{o.get("id")} {o.get("status")} for {o.get("minutes")} min', 'bad'),
                           (f'  last answer {clock(parse_iso(o["since"]), "%d %b %H:%M")}' if o.get('since') else '  no answer since start', 'dim')))
        return panel('API health', body, cw)

    def sources(cw):
        iw = cw - 4
        if not h:
            return panel('Sources', unavailable('health'), cw)
        srcs = sorted(h.get('sources') or [], key=lambda x: (x.get('status') == 'live', x.get('id', '')))
        rows = []
        for x in srcs:
            st = x.get('status', '?')
            when = parse_iso(x.get('updatedAt'))
            rows.append(L(('● ', status_style(st)), cell(x.get('id', '?'), 26, 'text'), cell(st, 12, status_style(st)),
                          cell(ago(when) if when else '–', 12, 'dim'), (x.get('name', ''), 'faint')))
        live = sum(1 for x in srcs if x.get('status') == 'live')
        return panel('Sources', rows or [L(('none listed', 'dim'))], cw, f'{live}/{len(srcs)} live')

    def postgres(cw):
        iw = cw - 4
        if not db or not db.get('pg'):
            return panel('PostgreSQL', [L(('unavailable', 'bad'), ('  ' + (db or {}).get('pg_error', '') if db else '', 'dim'))] if db else unavailable('db'), cw)
        pg = db['pg']
        conn = pg['conn']
        total = sum(conn.values())
        body = [kv('size', (size(pg.get('size')), 'bold'), (f'   cache hit {pg.get("hit", 0):.2f} %', 'text')),
                kv('connections', lw=13) + meter(pct(total, pg.get('max', 100)), max(6, iw - 40)) +
                L((f'  {total}/{pg.get("max", "?")}  ', 'text'), (' · '.join(f'{k} {v}' for k, v in sorted(conn.items())), 'dim')),
                kv('commits', (f'{pg["tps"]:.1f}/s  ' if pg.get('tps') is not None else '…  ', 'text')) +
                spark(DB_HIST['tps'], max(0, iw - 22), style='purple')]
        if pg.get('long') and pg['long'][0] >= 1:
            secs, q = pg['long']
            body.append(kv('longest', (f'{dur(secs)}  ', level_style(secs, 30, 300)), (q, 'faint')))
        if pg['tables']:
            body += [[], L(('largest tables', 'dim'))]
            top = max(x[1] for x in pg['tables']) or 1
            bw = max(4, iw - 52)
            for name, n in pg['tables']:
                body.append(L(cell(name, 40, 'text'), cell(size(n), 10, 'text', True), ('  ', 'text'), *meter(pct(n, top), bw, 'purple')))
        return panel('PostgreSQL', body, cw, pg.get('version', ''))

    def redis_(cw):
        iw = cw - 4
        if not db or not db.get('redis'):
            return panel('Redis', [L(('unavailable', 'bad'), ('  ' + (db or {}).get('redis_error', '') if db else '', 'dim'))] if db else unavailable('db'), cw)
        r = db['redis']
        body = [kv('memory', (size(r['mem']), 'bold'), (f'   peak {size(r["peak"])}' + (f' · max {size(r["maxmem"])}' if r['maxmem'] else ''), 'dim')),
                kv('clients', str(r['clients']), ('   hit rate ', 'dim'), f'{r["hit"]:.1f} %', ('   evicted ', 'dim'), str(r['evicted'])),
                kv('keys', ' · '.join(f'{k} {v}' for k, v in r['keys'].items()) or '0'),
                kv('ops', (f'{r["ops"]}/s  ', 'text')) + spark(DB_HIST['ops'], max(0, iw - 22), style='rx')]
        return panel('Redis', body, cw, f'{r["version"]} · up {dur(r["uptime"])}')
    return columns(w, [api], [sources]) + columns(w, [postgres], [redis_])


def tab_learning(w):
    lr = val('learning')
    if not lr:
        return panel('Stay-on learning', unavailable('learning'), w)
    iw = w - 4
    st, text = lr['status']
    mw = max(8, min(40, iw - 46))
    out = panel('Today', [
        [('recorded  ', 'dim')] + meter(lr['share'], mw, 'ok' if lr['share'] >= 95 else 'warn') +
        L((f'  {lr["share"]:5.1f} %', 'bold'), ('  of today so far · a day counts at 95 %', 'dim')),
        [('downtime  ', 'dim')] + meter(pct(lr['down'], BUDGET), mw) +
        L((f'  {lr["down"] / 60:3.0f} of {BUDGET // 60} min', 'bold'), ('  allowed today   ', 'dim'), ('● ', st), (text, st))],
        w, 'prestop_statistics/stays.py')

    colw = max(3, min(6, (iw - 4) // 14))
    strip, wk, dn = [], [], []
    for d, share in lr['collector']:
        p = share * 100
        sty = 'ok' if share * 86400 >= FULL_DAY else 'warn' if p >= 70 else 'bad' if p > 0 else 'faint'
        strip.append(('█' * (colw - 1) + ' ', sty))
        wk.append((f'{d:%a}'[:colw - 1].ljust(colw), 'dim'))
        dn.append((f'{d.day}'.ljust(colw), 'faint'))
    out += panel('Collector, last 14 days', [merge(strip), merge(strip), wk, dn,
                 L(('█ ', 'ok'), ('counts (≥ 95 %)   ', 'dim'), ('█ ', 'warn'), ('≥ 70 %   ', 'dim'), ('█ ', 'bad'), ('less   ', 'dim'), ('█ ', 'faint'), ('none', 'dim'))],
                 w, f'{sum(1 for _, s in lr["collector"] if s * 86400 >= FULL_DAY)}/14 days counted')

    rows = [L(cell('FEED', 16, 'dim'), cell('LAST 14 DAYS', 30, 'dim'), ('STATUS', 'dim'))]
    for f in lr['feeds']:
        days = merge([('■ ', 'ok' if ok else 'faint') for ok in f['days']])
        if f['open']:
            status = [('open', 'ok'), (f'  sure {f["sure"]} · likely {f["likely"]}', 'dim')]
        else:
            status = [(f'{f["run"]}/{GATE_DAYS}', 'warn' if f['run'] else 'faint'), ('  → opens ', 'dim'), (day_label(f['opens']), 'text')]
        rows.append(L(('● ', 'ok' if f['open'] else 'warn' if f['run'] else 'faint'), cell(f['feed'], 14, 'bold')) + fit(days, 30) + L(*status))
    if not lr['feeds']:
        rows.append(L(('no feeds recorded yet', 'dim')))
    if lr['nightly_missing']:
        rows += [[], L(('● ', 'bad'), ('nightly learning has not run today', 'bad'))]
    opened = sum(1 for f in lr['feeds'] if f['open'])
    out += panel('Feeds', rows, w, f'{opened}/{len(lr["feeds"])} open · {GATE_DAYS} counted days in a row open a feed')

    if lr['checks']:
        rows = []
        for lvl, (ok, total) in lr['checks'].items():
            p = pct(ok, total)
            bad = lvl == 'sure' and ok < total
            rows.append(L(cell(lvl, 8, 'bold')) + meter(p, max(6, iw - 40), 'bad' if bad else 'ok') +
                        L((f'  {ok}/{total} right', 'bad' if bad else 'text'), (f'  {p:.1f} %', 'dim')))
        out += panel('Nightly check, last 14 days', rows, w)
    return out


LOGS = {'errors_only': False, 'wrap': False}


def tab_logs(w):
    lg = val('logs')
    if lg is None:
        return panel('Logs', unavailable('logs'), w)
    iw = w - 4
    now = time.time()
    shown = [x for x in lg if x['p'] <= 3] if LOGS['errors_only'] else lg
    counts = {}
    for x in lg:
        c = counts.setdefault(x['unit'], [0, 0])
        c[0 if x['p'] <= 3 else 1] += 1
    head = []
    if counts:
        top = max(a + b for a, b in counts.values()) or 1
        bw = max(6, iw - 18 - 32)
        for unit, (er, wa) in sorted(counts.items(), key=lambda kv_: -sum(kv_[1])):
            fe, fw = int(round(er * bw / top)), int(round(wa * bw / top))
            fe = max(fe, 1 if er else 0)
            fw = max(fw, 1 if wa else 0)
            head.append(L(cell(unit, 18, 'text'), ('█' * fe, 'bad'), ('█' * fw, 'warn'), ('·' * max(0, bw - fe - fw), 'faint'),
                          (f'  {er:4d} errors', 'bad' if er else 'faint'), (f'  {wa:4d} warnings', 'warn' if wa else 'faint')))
    else:
        head.append(L(('● ', 'ok'), ('no warnings or errors from the KamGre services in 24 h', 'ok')))
    out = panel('Last 24 hours', head, w, f'{len(lg)} entries' + (' (newest 500)' if len(lg) >= 500 else ''))
    rows = []
    pri = {0: ('EMERG', 'bad'), 1: ('ALERT', 'bad'), 2: ('CRIT ', 'bad'), 3: ('ERROR', 'bad'), 4: ('WARN ', 'warn')}
    for x in shown:
        tag, sty = pri.get(x['p'], ('INFO ', 'dim'))
        when = clock(x['t'], '%H:%M:%S') if now - x['t'] < 86400 and datetime.fromtimestamp(x['t'], TZ).date() == datetime.now(TZ).date() \
            else clock(x['t'], '%d %b %H:%M')
        prefix = L(cell(when, 13, 'dim'), (tag, sty), ('  ', 'text'), cell(x['unit'], 14, 'accent'))
        pw = width(prefix)
        lines = x['msg'].splitlines() or ['']
        if LOGS['wrap']:
            mw = max(10, iw - pw)
            chunks = [ln[i:i + mw] for ln in lines for i in range(0, max(1, len(ln)), mw)]
            rows.append(prefix + [(chunks[0], 'text')])
            rows += [blank(pw) + [(c, 'text')] for c in chunks[1:]]
        else:
            rows.append(prefix + [(lines[0] + (' …' if len(lines) > 1 else ''), 'bad' if x['p'] <= 3 else 'text')])
    if not rows:
        rows.append(L(('nothing to show', 'dim')))
    flt = 'errors only' if LOGS['errors_only'] else 'warnings and errors'
    return out + panel('Journal', rows, w, f'{flt} · newest first · e filter · w wrap')


TAB_FUNCS = {'overview': tab_overview, 'system': tab_system, 'services': tab_services, 'traffic': tab_traffic,
             'data': tab_data, 'learning': tab_learning, 'logs': tab_logs}

HELP = [
    ('← → / Tab', 'switch tabs (or click a tab)'), ('1 … 7', 'jump to a tab'), ('↑ ↓ PgUp PgDn', 'scroll (or the mouse wheel)'),
    ('Home End', 'top / bottom'), ('p or space', 'pause / resume updates'), ('+ -', 'update faster / slower'),
    ('r', 'refresh everything now'), ('e  w', 'logs: errors only · wrap long lines'), ('?', 'this help'), ('q  Esc', 'quit'),
]

# ---------------------------------------------------------------- screen


def header(w, tab):
    a = alerts()
    worst = max((LEVEL[x[0]] for x in a), default=0)
    pill = [('● all good', 'hdrok'), (f'● {len(a)} to check', 'hdrwarn'), (f'● {len(a)} to check', 'hdrbad')][worst]
    s = val('sample')
    left = [(' ◆ KamGre server ', 'hdrb'), (socket.gethostname() + '  ', 'hdrdim'), (pill[0], pill[1])]
    now = datetime.now(TZ)
    right = []
    if UI['paused']:
        right.append((' PAUSED ', 'hdrwarn'))
    if s:
        right.append((f' up {dur(s["uptime"])} ', 'hdrdim'))
    right += [(f' {now:%a} {now.day} {now:%b} ', 'hdrdim'), (f'{now:%H:%M:%S} ', 'hdr'), (f'· every {UI["interval"]}s ', 'hdrdim')]
    gap = w - width(left) - width(right)
    return merge(left + [(' ' * max(1, gap), 'hdr')] + right) if gap > 0 else fit(left, w, 'hdr')


TAB_X = []


def tabbar(w, tab):
    marks = {}
    for lvl, t, _ in alerts():
        marks[t] = max(marks.get(t, 0), LEVEL[lvl])
    line, x = [(' ', 'tab')], 1
    TAB_X.clear()
    for i, (key, name) in enumerate(TABS):
        on = key == tab
        seg = [(f' {i + 1} ', 'tabon' if on else 'tabkey'), (f'{name} ', 'tabon' if on else 'tab')]
        if key in marks:
            seg.append(('●', 'tabon' if on else ['tab', 'tabwarn', 'tabbad'][marks[key]]))
            seg.append((' ', 'tabon' if on else 'tab'))
        n = width(seg)
        TAB_X.append((x, x + n, i))
        line += seg + [(' ', 'tab')]
        x += n + 1
    return fit(line, w, 'tab')


def footer(w, more_up, more_down):
    keys = [('←→', 'tabs'), ('↑↓', 'scroll'), ('p', 'pause'), ('+/-', 'speed'), ('r', 'refresh'), ('?', 'help'), ('q', 'quit')]
    line = [(' ', 'foot')]
    for k, d in keys:
        line += [(k, 'footkey'), (f' {d}   ', 'foot')]
    if more_up or more_down:
        line += [(('▲' if more_up else ' ') + ('▼' if more_down else ' ') + ' more', 'footwarn')]
    return fit(line, w, 'foot')


def frame(w, h, view):
    tab = TABS[view['tab']][0]
    body = [[('', 'text')]] + (panel('Keys', [L(cell(k, 18, 'accentb'), (d, 'text')) for k, d in HELP], min(w, 64))
                               if view['help'] else TAB_FUNCS[tab](w))
    room = max(1, h - 3)
    view['scroll'] = max(0, min(view['scroll'], len(body) - room))
    shown = body[view['scroll']:view['scroll'] + room]
    return ([header(w, tab), tabbar(w, tab)] + [fit(x, w) for x in shown] + [blank(w)] * (room - len(shown)) +
            [footer(w, view['scroll'] > 0, view['scroll'] + room < len(body))])


class CursesOut:
    def __init__(self, scr):
        self.scr = scr
        self.c256 = curses.has_colors() and curses.COLORS >= 256
        self.pairs, self.cache = {}, {}

    def attr(self, style):
        if style in self.cache:
            return self.cache[style]
        fg, bg, f8, b8, flags = STYLES.get(style, STYLES['text'])
        a = 0
        if curses.has_colors():
            key = (fg, bg) if self.c256 else (f8, b8)
            if key not in self.pairs and len(self.pairs) + 1 < curses.COLOR_PAIRS:
                curses.init_pair(len(self.pairs) + 1, *key)
                self.pairs[key] = len(self.pairs) + 1
            a = curses.color_pair(self.pairs.get(key, 0))
            if 'd' in flags and not self.c256:
                a |= curses.A_DIM
        elif style.startswith(('hdr', 'tabon', 'foot')):
            a = curses.A_REVERSE
        if 'b' in flags:
            a |= curses.A_BOLD
        self.cache[style] = a
        return a

    def paint(self, lines, w, h):
        self.scr.erase()
        for y, line in enumerate(lines[:h]):
            x = 0
            for text, style in line:
                if x >= w:
                    break
                text = text[:w - x]
                try:
                    self.scr.addstr(y, x, text, self.attr(style))
                except curses.error:  # the bottom-right cell
                    pass
                x += len(text)
        self.scr.noutrefresh()
        curses.doupdate()


def run(scr, start_tab):
    curses.curs_set(0)
    if curses.has_colors():
        curses.start_color()
        curses.use_default_colors()
    curses.mousemask(curses.ALL_MOUSE_EVENTS | getattr(curses, 'REPORT_MOUSE_POSITION', 0))
    curses.mouseinterval(0)
    scr.timeout(200)
    scr.keypad(True)
    out = CursesOut(scr)
    view = {'tab': start_tab, 'scroll': 0, 'help': False}
    scrolls = {}
    last = 0.0
    while True:
        h, w = scr.getmaxyx()
        if CHANGED.is_set() or time.time() - last >= 1:
            CHANGED.clear()
            out.paint(frame(w, h, view), w, h)
            last = time.time()
        try:
            k = scr.get_wch()
        except curses.error:
            continue
        except KeyboardInterrupt:
            return
        if k == '\x1b':  # Esc alone, or the start of a key sequence this terminal's terminfo does not know
            k = escape(scr)
        room = max(1, h - 3)
        old_tab = view['tab']
        if k is None:
            pass
        elif k in ('q', 'Q', '\x1b', '\x03'):
            if view['help'] and k == '\x1b':
                view['help'] = False
            else:
                return
        elif k in (curses.KEY_RIGHT, '\t', 'l'):
            view['tab'] = (view['tab'] + 1) % len(TABS)
        elif k in (curses.KEY_LEFT, curses.KEY_BTAB, 'h'):
            view['tab'] = (view['tab'] - 1) % len(TABS)
        elif isinstance(k, str) and k.isdigit() and 1 <= int(k) <= len(TABS):
            view['tab'] = int(k) - 1
        elif k in (curses.KEY_DOWN, 'j'):
            view['scroll'] += 1
        elif k in (curses.KEY_UP, 'k'):
            view['scroll'] -= 1
        elif k == curses.KEY_NPAGE:
            view['scroll'] += room - 1
        elif k == curses.KEY_PPAGE:
            view['scroll'] -= room - 1
        elif k == curses.KEY_HOME:
            view['scroll'] = 0
        elif k == curses.KEY_END:
            view['scroll'] = 10 ** 6
        elif k in ('p', ' '):
            UI['paused'] = not UI['paused']
        elif k in ('+', '='):
            UI['interval'] = max(1, UI['interval'] - 1)
            wake_all()
        elif k in ('-', '_'):
            UI['interval'] = min(60, UI['interval'] + 1)
        elif k in ('r', 'R'):
            UI['paused'] = False
            wake_all()
        elif k == '?':
            view['help'] = not view['help']
        elif k == 'e' and TABS[view['tab']][0] == 'logs':
            LOGS['errors_only'] = not LOGS['errors_only']
        elif k == 'w' and TABS[view['tab']][0] == 'logs':
            LOGS['wrap'] = not LOGS['wrap']
        elif k == curses.KEY_MOUSE:
            try:
                _, mx, my, _, b = curses.getmouse()
            except curses.error:
                continue
            if b & curses.BUTTON4_PRESSED:
                view['scroll'] -= 3
            elif b & getattr(curses, 'BUTTON5_PRESSED', 0):
                view['scroll'] += 3
            elif my == 1 and b & (curses.BUTTON1_CLICKED | curses.BUTTON1_PRESSED | curses.BUTTON1_RELEASED):
                for x0, x1, i in TAB_X:
                    if x0 <= mx < x1:
                        view['tab'] = i
        elif k == curses.KEY_RESIZE:
            curses.update_lines_cols()
        if view['tab'] != old_tab:
            scrolls[old_tab] = view['scroll']
            view['scroll'] = scrolls.get(view['tab'], 0)
            view['help'] = False
        view['scroll'] = max(0, view['scroll'])
        CHANGED.set()


ESCAPES = {'[H': curses.KEY_HOME, '[1~': curses.KEY_HOME, 'OH': curses.KEY_HOME, '[F': curses.KEY_END, '[4~': curses.KEY_END,
           'OF': curses.KEY_END, '[5~': curses.KEY_PPAGE, '[6~': curses.KEY_NPAGE, '[A': curses.KEY_UP, '[B': curses.KEY_DOWN,
           '[C': curses.KEY_RIGHT, '[D': curses.KEY_LEFT, '[Z': curses.KEY_BTAB}


def escape(scr):
    """Esc on its own quits; a sequence that follows at once is a key: mapped when known, else ignored (None)."""
    seq = ''
    scr.timeout(30)
    try:
        while len(seq) < 8:
            try:
                ch = scr.get_wch()
            except curses.error:
                break
            if not isinstance(ch, str):
                break
            seq += ch
            if seq in ESCAPES or (len(seq) > 1 and (ch.isalpha() or ch == '~')):
                break
    finally:
        scr.timeout(200)
    return '\x1b' if not seq else ESCAPES.get(seq)


def wake_all():
    for p in POLL.values():
        p.wake.set()


def ansi(lines):
    out = []
    for line in lines:
        s = ''
        for text, style in line:
            fg, bg, _, _, flags = STYLES.get(style, STYLES['text'])
            s += '\033[0' + (';1' if 'b' in flags else '') + f';38;5;{fg}' + (f';48;5;{bg}' if bg >= 0 else '') + 'm' + text
        out.append(s.rstrip() + '\033[0m')
    return '\n'.join(out)


def once(tabs):
    """One frame of each tab, printed (two samples a second apart, so rates have something to compare)."""
    for name, fn, _ in (('sample', SAMPLER, 0), ('traffic', traffic, 0), ('health', health, 0), ('egress', egress, 0),
                        ('db', databases, 0), ('timers', timers, 0), ('logs', logs, 0), ('learning', learning, 0)):
        POLL[name] = Poller(name, fn, lambda: 0)
    for p in POLL.values():
        p.once()
    time.sleep(1)
    POLL['sample'].once()
    POLL['db'].once()
    w = min(shutil.get_terminal_size((120, 40)).columns, 160)
    for i, (key, _) in enumerate(TABS):
        if key in tabs:
            print(ansi([header(w, key), tabbar(w, key)] + [fit(x, w) for x in TAB_FUNCS[key](w)]) + '\n')


def main(argv):
    for name in ('C.UTF-8', 'C.utf8', ''):
        try:
            locale.setlocale(locale.LC_ALL, name)
            break
        except locale.Error:
            continue
    os.environ.setdefault('ESCDELAY', '25')
    names = [k for k, _ in TABS]
    start, single = 0, None
    for a in argv:
        if a.isdigit():
            UI['interval'] = max(1, min(60, int(a)))
        elif a.lower() in names:
            start = names.index(a.lower())
            single = a.lower()
        elif a in ('--once', '-1'):
            UI['once'] = True
        elif a in ('-h', '--help'):
            print(__doc__)
            return 0
        else:
            print(f'Unknown argument {a!r}. Usage: prestop-top [seconds] [{"|".join(names)}] [--once]', file=sys.stderr)
            return 2
    if UI.get('once'):
        once([single] if single else names)
        return 0
    if not sys.stdout.isatty():
        print('prestop-top needs a terminal (use --once to print a frame).', file=sys.stderr)
        return 2
    start_pollers()
    try:
        curses.wrapper(run, start)
    except KeyboardInterrupt:
        pass
    return 0


if __name__ == '__main__':
    sys.exit(main(sys.argv[1:]))
