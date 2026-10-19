"""Sends due reminders and live changes of watched trips (run by `manage.py run_push`).

A watch is a reminder set in the app (journey or departure). At `notify_at` the reminder
is pushed with the trip's current departure. From 30 minutes before that until the vehicle
leaves the watched stop, the trip is checked on every tick and a change is pushed under the
same tag, so it replaces the earlier notification: a cancellation (or its reversal) always,
a delay change of at least 2 minutes at most once every 3 minutes (10 for a journey). The first look at a trip
only records where it stands; the user already saw that in the app. A journey's later rides, changes and the
disruptions on its way are watched too once its reminder went out (journey.py), at most one message per 10 minutes,
except "get off next", which goes out when due.
"""
import logging
from datetime import datetime, timedelta
from typing import Optional
from zoneinfo import ZoneInfo

from django.utils import timezone

from prestop_api.upstream import UpstreamError

from . import journey, sender
from .models import PushSubscription, Watch

logger = logging.getLogger(__name__)

LOCAL = ZoneInfo('Europe/Ljubljana')
LOOKAHEAD = timedelta(minutes=30)
MIN_CHANGE = 120
MIN_GAP = timedelta(minutes=3)
JOURNEY_GAP = timedelta(minutes=10)  # a journey gets at most one message this often (cancellations still go at once)
REMINDER_GRACE = timedelta(minutes=10)
MAX_FAILURES = 30
TEXT = {
    'sl': {'canceled': 'Odpovedano', 'on_time': 'točno', 'in': 'čez {} min', 'now': 'zdaj'},
    'en': {'canceled': 'Canceled', 'on_time': 'on time', 'in': 'in {} min', 'now': 'now'},
}


def load_trips(ids: list[str]) -> dict[str, dict]:
    """tripId -> trip in the API contract (without geometry); {} when the timetable is unreachable."""
    from prestop_api import trips
    try:
        found = trips.load_trips(ids)
    except UpstreamError as e:
        logger.warning('Trips for push watches unavailable: %r', e)
        return {}
    return {i: trips.build_trip(found[i], {}, geometry=False) for i in ids if i in found}


def load_alerts(language: str) -> list[dict]:
    from prestop_api import sources
    try:
        return sources.alerts(language)
    except UpstreamError as e:
        logger.warning('Alerts for push watches unavailable: %r', e)
        return []


def _parse(value: Optional[str]) -> Optional[datetime]:
    return datetime.fromisoformat(value.replace('Z', '+00:00')) if value else None


def trip_state(watch: Watch, trips: dict) -> Optional[dict]:
    """Delay (s, None without realtime), status and departure at the watched stop of the first known trip."""
    trip = next((trips[i] for i in watch.trip_ids if i in trips), None)
    if not trip or not trip.get('stops'):
        return None
    stop = next((s for s in trip['stops'] if s['stopId'] == watch.stop_id), trip['stops'][0])
    scheduled, effective = _parse(stop['scheduledDeparture']), _parse(stop.get('effectiveDeparture'))
    return {
        'delay': round((effective - scheduled).total_seconds()) if effective and scheduled else None,
        'status': 'canceled' if stop.get('canceled') else 'ok',
        'stop': stop['name'], 'departs': effective or scheduled,
    }


def summary(state: dict, language: str, now: datetime) -> str:
    """'Bavarski dvor 10:23 (+3 min) · in 9 min' in the subscriber's language."""
    text = TEXT.get(language, TEXT['sl'])
    at = state['departs'].astimezone(LOCAL).strftime('%H:%M')
    if state['status'] == 'canceled':
        return f"{text['canceled']}: {state['stop']} {at}"
    minutes = round((state['delay'] or 0) / 60)
    late = text['on_time'] if minutes == 0 else f'{minutes:+d} min'.replace('-', '−')
    until = max(0, round((state['departs'] - now).total_seconds() / 60))
    return f"{state['stop']} {at} ({late}) · {text['in'].format(until) if until else text['now']}"


def _payload(watch: Watch, body: str, kind: str, renotify: bool) -> dict:
    return {'title': watch.title, 'body': body, 'url': watch.url, 'tag': watch.client_id, 'kind': kind, 'renotify': renotify}


def _change(watch: Watch, state: dict, now: datetime) -> Optional[bool]:
    """None: nothing to tell; else whether the change should alert again (renotify)."""
    if state['status'] != (watch.last_status or 'ok'):
        return True
    if state['delay'] is None or abs(state['delay'] - (watch.last_delay or 0)) < MIN_CHANGE:
        return None
    if watch.last_sent and now - watch.last_sent < (JOURNEY_GAP if watch.kind == 'journey' else MIN_GAP):
        return None
    return False


def tick(now: Optional[datetime] = None) -> int:
    """One pass over all watches; returns the number of pushes sent."""
    now = now or timezone.now()
    Watch.objects.filter(expires_at__lte=now).delete()
    watches = list(Watch.objects.select_related('subscription').filter(notify_at__lte=now + LOOKAHEAD).order_by('notify_at'))
    ids = list(dict.fromkeys(i for w in watches for i in w.trip_ids))
    trips = load_trips(ids) if ids else {}
    alerts = None  # loaded when a journey needs them
    sent, gone = 0, set()
    for watch in watches:
        sub = watch.subscription
        if sub.pk in gone:
            continue
        state = trip_state(watch, trips)
        language = sub.language
        payload, urgent = None, False
        if not watch.sent_reminder and watch.notify_at <= now:
            if now - watch.notify_at > REMINDER_GRACE:
                watch.sent_reminder = True  # Too late to be useful; never deliver a stale reminder.
            else:
                body = summary(state, language, now) if state else watch.body
                payload, urgent = _payload(watch, body, 'reminder', True), True
        elif state and state['departs'] > now:
            if watch.last_delay is None and not watch.last_status:
                watch.last_delay, watch.last_status = state['delay'], state['status']
            else:
                renotify = _change(watch, state, now)
                if renotify is not None:
                    payload, urgent = _payload(watch, summary(state, language, now), 'update', renotify), renotify
        told = None
        canceled = bool(state) and state['status'] != (watch.last_status or 'ok')
        if watch.kind == 'journey' and watch.sent_reminder and trips and not canceled and (not payload or payload['kind'] == 'update'):
            # Later rides, changes and disruptions on the way (journey.py); worse news than a plain delay update
            # replaces it (a cancellation never).
            if alerts is None:
                alerts = load_alerts(language)
            current = journey.state(watch, trips, alerts, now.timestamp())
            if not watch.journey_state.get('seen'):
                watch.journey_state = journey.baseline(current)
            else:
                # Within the gap only "get off next" goes out (journey.news).
                quiet = not (payload or not watch.last_sent or now - watch.last_sent >= JOURNEY_GAP)
                found = journey.news(watch.journey_state, current, language, quiet)
                if found and (not payload or found[1]):
                    body, urgent, told = found
                    payload = _payload(watch, body, 'update', urgent)
        if payload:
            result = sender.send(sub, payload, urgent=urgent)
            if result == 'gone':
                gone.add(sub.pk)
                sub.delete()
                continue
            if result == 'error':
                sub.failures += 1
                if sub.failures >= MAX_FAILURES:
                    gone.add(sub.pk)
                    sub.delete()
                    continue
                PushSubscription.objects.filter(pk=sub.pk).update(failures=sub.failures)
            else:
                sent += 1
                sub.failures, sub.last_ok = 0, now
                PushSubscription.objects.filter(pk=sub.pk).update(failures=0, last_ok=now)
                watch.last_sent = now
                if payload['kind'] == 'reminder':
                    watch.sent_reminder = True
                if told:
                    watch.journey_state = journey.told(watch.journey_state, told)
                if state:
                    watch.last_status = state['status']
                    if state['delay'] is not None:
                        watch.last_delay = state['delay']
        watch.save()
    return sent
