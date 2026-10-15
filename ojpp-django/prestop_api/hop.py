"""Hop: send a route to a phone nearby that has KamGre open. No accounts, nothing in Postgres: presence and messages
live in Redis with short TTLs, and the app polls (gunicorn is WSGI, no sockets).

- Presence (POST /hop/presence, every ~15 s while the app is visible and Hop is on) keeps a device listed for
  PRESENCE_TTL. Its answer carries the device's 4-character code and the hops waiting for it, which are deleted as
  they are handed over.
- Nearby means the same public IP (as the traffic guard resolves it) or the same or an adjacent geohash-7 cell
  (~150 m) the app sends only when location permission was already granted. An IP shared by more than CGNAT_LIMIT
  devices (a mobile network's CGNAT, a campus) counts only peers that also match by cell.
- Peers are listed under per-viewer opaque tokens, never their device ids; a code works from anywhere while its
  device is present.
- A hop carries only an app object (a journey's share code, a stop, a line with its date, a vehicle): no free text
  and no URLs, at most MAX_BODY bytes. It waits MESSAGE_TTL; a device sends at most SEND_PER_MINUTE a minute and a
  receiver holds at most INBOX_LIMIT.

Device ids, IPs and cells appear in keys only as salted hashes, and none of them is logged.
"""
import functools
import hashlib
import json
import re
import secrets
import time
import unicodedata
from typing import Optional

import redis
from django.conf import settings

PRESENCE_TTL = 45
CODE_TTL = 3600  # s a device keeps its code between visits (it only works while the device is present)
PEER_TTL = 120  # s a listed peer token stays valid for sending
MESSAGE_TTL = 300
SEND_PER_MINUTE = 10
INBOX_LIMIT = 3
CGNAT_LIMIT = 8
MAX_PEERS = 12
MAX_BODY = 4096
CODE_ALPHABET = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # no 0/O, 1/I
CODE = re.compile(f'^[{CODE_ALPHABET}]{{4}}$')
DEVICE = re.compile(r'^[0-9a-fA-F-]{32,36}$')
GEOHASH = '0123456789bcdefghjkmnpqrstuvwxyz'
CELL = re.compile(f'^[{GEOHASH}]{{7}}$')
QUALIFIED = re.compile(r'^[A-Za-z0-9_.-]{1,40}:[^\s/:?#]{1,160}$')
SHARE_CODE = re.compile(r'^[A-Za-z0-9_-]{4,1500}$')
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}$')


class HopError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code = status, code


def _redis():
    return _client(getattr(settings, 'PRESTOP_HOP_REDIS_URL', '') or settings.CACHES['default']['LOCATION'])


@functools.lru_cache(maxsize=4)
def _client(url: str):
    return redis.Redis.from_url(url, socket_timeout=0.5, socket_connect_timeout=0.5, decode_responses=True)


def _hash(kind: str, value: str) -> str:
    return hashlib.sha256(f'{settings.SECRET_KEY}|hop|{kind}|{value}'.encode()).hexdigest()[:24]


# ---------------------------------------------------------------- validation

def nickname_ok(name) -> bool:
    """The app's validateNickname: trimmed, 2-20 characters, letters (any script), marks, digits, space and -_."""
    if not isinstance(name, str) or name != name.strip() or not 2 <= len(name) <= 20:
        return False
    return all(c in ' _.-' or unicodedata.category(c)[0] in 'LMN' for c in name)


def device_of(body: dict) -> str:
    device = body.get('device')
    if not isinstance(device, str) or not DEVICE.match(device):
        raise HopError(422, 'INVALID_DEVICE', 'device must be the app\'s random id')
    return _hash('device', device.lower())


def item_of(raw) -> dict:
    """The app object a hop carries, rebuilt from known fields only (anything else is refused, not dropped)."""
    if not isinstance(raw, dict):
        raise HopError(422, 'INVALID_ITEM', 'item must be an object')
    kind = raw.get('kind')
    fields = {'journey': {'code'}, 'stop': {'id'}, 'line': {'id', 'date', 'trip'}, 'vehicle': {'id'}}.get(kind)
    if fields is None or not set(raw) - {'kind'} <= fields:
        raise HopError(422, 'INVALID_ITEM', 'item must be a journey, stop, line or vehicle and nothing else')
    if kind == 'journey':
        if not isinstance(raw.get('code'), str) or not SHARE_CODE.match(raw['code']):
            raise HopError(422, 'INVALID_ITEM', 'a journey is its share code')
        return {'kind': kind, 'code': raw['code']}
    if not isinstance(raw.get('id'), str) or not QUALIFIED.match(raw['id']):
        raise HopError(422, 'INVALID_ITEM', 'an id is feed:id')
    item = {'kind': kind, 'id': raw['id']}
    if kind == 'line':
        if raw.get('date') is not None:
            if not isinstance(raw['date'], str) or not DATE.match(raw['date']):
                raise HopError(422, 'INVALID_ITEM', 'date is YYYY-MM-DD')
            item['date'] = raw['date']
        if raw.get('trip') is not None:
            if not isinstance(raw['trip'], str) or not QUALIFIED.match(raw['trip']):
                raise HopError(422, 'INVALID_ITEM', 'trip is feed:id')
            item['trip'] = raw['trip']
    return item


# ---------------------------------------------------------------- geohash cells

def _decode(cell: str) -> tuple[float, float, float, float]:
    """Centre latitude and longitude of a geohash, and its height and width in degrees."""
    lat, lon, even = [-90.0, 90.0], [-180.0, 180.0], True
    for ch in cell:
        bits = GEOHASH.index(ch)
        for shift in range(4, -1, -1):
            pair = lon if even else lat
            mid = (pair[0] + pair[1]) / 2
            pair[0 if bits >> shift & 1 else 1] = mid
            even = not even
    return (lat[0] + lat[1]) / 2, (lon[0] + lon[1]) / 2, lat[1] - lat[0], lon[1] - lon[0]


def _encode(lat: float, lon: float, length: int) -> str:
    lat_r, lon_r, even, bits, out, value = [-90.0, 90.0], [-180.0, 180.0], True, 0, '', 0
    while len(out) < length:
        pair, x = (lon_r, lon) if even else (lat_r, lat)
        mid = (pair[0] + pair[1]) / 2
        value = value << 1 | (x >= mid)
        pair[0 if x >= mid else 1] = mid
        even, bits = not even, bits + 1
        if bits == 5:
            out, bits, value = out + GEOHASH[value], 0, 0
    return out


def cells_around(cell: str) -> list[str]:
    """The cell and its eight neighbours."""
    lat, lon, height, width = _decode(cell)
    return sorted({_encode(max(-89.99, min(89.99, lat + dy * height)), (lon + dx * width + 180) % 360 - 180, len(cell))
                   for dy in (-1, 0, 1) for dx in (-1, 0, 1)})


# ---------------------------------------------------------------- presence

def _code(r, me: str) -> str:
    """This device's code: kept for CODE_TTL between visits, new when that ran out."""
    code = r.get(f'hop:mycode:{me}')
    if code and r.get(f'hop:code:{code}') == me:
        r.expire(f'hop:mycode:{me}', CODE_TTL)
        r.expire(f'hop:code:{code}', CODE_TTL)
        return code
    for _ in range(20):
        code = ''.join(secrets.choice(CODE_ALPHABET) for _ in range(4))
        if r.set(f'hop:code:{code}', me, nx=True, ex=CODE_TTL):
            r.set(f'hop:mycode:{me}', code, ex=CODE_TTL)
            return code
    raise HopError(503, 'NO_CODE', 'No free code right now. Please try again.')


def presence(body: dict, ip: str, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    r = _redis()
    me = device_of(body)
    if body.get('leave') is True:  # the app is hidden or the person turned Hop off: gone at once
        leave(r, me)
        return {'code': None, 'incoming': []}
    nickname = body.get('nickname')
    if not nickname_ok(nickname):
        raise HopError(422, 'INVALID_NICKNAME', 'nickname: 2-20 letters, digits, spaces or -_.')
    cell = body.get('cell')
    if cell is not None and (not isinstance(cell, str) or not CELL.match(cell)):
        raise HopError(422, 'INVALID_CELL', 'cell is a geohash of 7 characters')
    ip_key = f'hop:ip:{_hash("ip", ip)}'
    cell_key = f'hop:cell:{_hash("cell", cell)}' if cell else ''
    # The groups to look in for peers: this cell and its neighbours, hashed like the cell (the raw cell is not kept).
    around = ','.join(f'hop:cell:{_hash("cell", c)}' for c in cells_around(cell)) if cell else ''
    previous = r.hgetall(f'hop:p:{me}')
    code = _code(r, me)
    pipe = r.pipeline(transaction=False)
    # Moved to another network or cell: leave the old groups at once.
    for old, new in ((previous.get('ip'), ip_key), (previous.get('cell'), cell_key)):
        if old and old != new:
            pipe.zrem(old, me)
    pipe.delete(f'hop:p:{me}')
    pipe.hset(f'hop:p:{me}', mapping={'nick': nickname, 'ip': ip_key, 'cell': cell_key, 'around': around, 'code': code})
    pipe.expire(f'hop:p:{me}', PRESENCE_TTL)
    for key in filter(None, (ip_key, cell_key)):
        pipe.zadd(key, {me: now}).zremrangebyscore(key, '-inf', now - PRESENCE_TTL).expire(key, PRESENCE_TTL + 15)
    pipe.execute()
    return {'code': code, 'incoming': _deliver(r, me, now)}


def leave(r, me: str) -> None:
    state = r.hgetall(f'hop:p:{me}')
    pipe = r.pipeline(transaction=False)
    for key in filter(None, (state.get('ip'), state.get('cell'))):
        pipe.zrem(key, me)
    pipe.delete(f'hop:p:{me}', f'hop:peers:{me}')
    pipe.execute()


def _present(r, key: str, now: float) -> list[str]:
    return r.zrangebyscore(key, now - PRESENCE_TTL, '+inf') if key else []


def _near(r, me: str, state: dict, now: float) -> list[str]:
    """Devices near `me`: same IP (all of them unless the IP is a crowd) or same/adjacent cell."""
    by_cell = {d for key in filter(None, (state.get('around') or '').split(',')) for d in _present(r, key, now)}
    by_ip = set(_present(r, state.get('ip') or '', now))
    if len(by_ip) > CGNAT_LIMIT:
        by_ip &= by_cell
    near = (by_ip | by_cell) - {me}
    alive = [d for d in near if r.exists(f'hop:p:{d}')]
    return alive[:MAX_PEERS * 2]


def nearby(device: str, now: Optional[float] = None) -> list[dict]:
    """The peers a present device may send to: [{peer, nickname}], `peer` a token only this device can use."""
    now = time.time() if now is None else now
    r = _redis()
    me = device_of({'device': device})
    state = r.hgetall(f'hop:p:{me}')
    if not state:
        return []
    peers = []
    for other in _near(r, me, state, now):
        nick = r.hget(f'hop:p:{other}', 'nick')
        if nick:
            peers.append({'peer': hashlib.sha256(f'{settings.SECRET_KEY}|peer|{me}|{other}'.encode()).hexdigest()[:16], 'nickname': nick, '_d': other})
    peers.sort(key=lambda p: p['nickname'].casefold())
    peers = peers[:MAX_PEERS]
    if peers:
        r.pipeline(transaction=False).hset(f'hop:peers:{me}', mapping={p['peer']: p['_d'] for p in peers}).expire(f'hop:peers:{me}', PEER_TTL).execute()
    return [{'peer': p['peer'], 'nickname': p['nickname']} for p in peers]


# ---------------------------------------------------------------- sending

def send(body: dict, now: Optional[float] = None) -> dict:
    now = time.time() if now is None else now
    r = _redis()
    me = device_of(body)
    nick = r.hget(f'hop:p:{me}', 'nick')
    if not nick:
        raise HopError(409, 'NOT_PRESENT', 'Turn Hop on to send.')
    item = item_of(body.get('item'))
    to = body.get('to')
    if not isinstance(to, str):
        raise HopError(422, 'INVALID_TARGET', 'to is a peer or a code')
    target = r.get(f'hop:code:{to.upper()}') if CODE.match(to.upper()) else r.hget(f'hop:peers:{me}', to)
    if not target or target == me or not r.exists(f'hop:p:{target}'):
        raise HopError(404, 'PEER_GONE', 'That phone is not reachable right now.')
    rate = f'hop:rate:{me}:{int(now // 60)}'
    sent, _ = r.pipeline(transaction=False).incr(rate).expire(rate, 120).execute()
    if sent > SEND_PER_MINUTE:
        raise HopError(429, 'RATE_LIMITED', 'Too many hops. Please wait a minute.')
    inbox = f'hop:inbox:{target}'
    r.zremrangebyscore(inbox, '-inf', now)
    if r.zcard(inbox) >= INBOX_LIMIT:
        raise HopError(429, 'INBOX_FULL', 'That phone has hops waiting already.')
    message = {'id': secrets.token_hex(8), 'from': nick, 'item': item, 'sentAt': int(now)}
    pipe = r.pipeline(transaction=False)
    pipe.set(f'hop:msg:{message["id"]}', json.dumps(message), ex=MESSAGE_TTL)
    pipe.zadd(inbox, {message['id']: now + MESSAGE_TTL}).expire(inbox, MESSAGE_TTL)
    pipe.execute()
    return {'sent': True}


def _deliver(r, me: str, now: float) -> list[dict]:
    """The hops waiting for this device, oldest first; each is deleted as it is handed over."""
    inbox = f'hop:inbox:{me}'
    ids = r.zrangebyscore(inbox, now, '+inf')
    if not ids:
        return []
    keys = [f'hop:msg:{i}' for i in ids]
    pipe = r.pipeline(transaction=True)  # two polls at once hand each hop over only once
    for key in keys:
        pipe.get(key)
    pipe.delete(*keys).zrem(inbox, *ids)
    raw = pipe.execute()[:-2]
    return sorted((json.loads(m) for m in raw if m), key=lambda m: m['sentAt'])
