"""/api/v1/push: register a browser for Web Push and the reminders it watches.

The browser's push endpoint is the only identity: whoever holds it can manage its
watches, which is what the app needs and reveals nothing about anybody else."""
import json
import re
from datetime import datetime, timedelta

from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.views.decorators.csrf import csrf_exempt
from django.views.decorators.http import require_http_methods, require_POST

from prestop_api.views import ApiError, api

from . import sender
from .models import PushSubscription, Watch

MAX_WATCHES = 50
MAX_TRIPS = 10
B64URL = re.compile(r'^[A-Za-z0-9_-]+=*$')
QUALIFIED = re.compile(r'^[^:\s]+:\S+$')
# Watches end this long after the trip is due (journey arrival, else the departure).
KEEP_AFTER = timedelta(minutes=30)


def _body(request) -> dict:
    try:
        body = json.loads(request.body or b'{}')
    except ValueError:
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON body')
    if not isinstance(body, dict):
        raise ApiError(422, 'INVALID_REQUEST', 'Expected a JSON object')
    return body


def _endpoint(value) -> str:
    if not isinstance(value, str) or len(value) > 1024 or not sender.allowed(value):
        raise ApiError(422, 'INVALID_ENDPOINT', 'endpoint must be an https:// URL of a browser push service')
    return value


def _subscription(endpoint) -> PushSubscription:
    sub = PushSubscription.objects.filter(endpoint=_endpoint(endpoint)).first()
    if not sub:
        raise ApiError(404, 'UNKNOWN_SUBSCRIPTION', 'Subscribe this browser first')
    return sub


def _text(body: dict, name: str, limit: int, required=True) -> str:
    value = body.get(name)
    if value is None and not required:
        return ''
    if not isinstance(value, str) or (required and not value.strip()) or len(value) > limit:
        raise ApiError(422, 'INVALID_WATCH', f'{name} must be a string of at most {limit} characters')
    return value


def _time(body: dict, name: str, required=True):
    value = body.get(name)
    if value is None and not required:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    except ValueError:
        raise ApiError(422, 'INVALID_WATCH', f'{name} must be an ISO date-time')
    if parsed.tzinfo is None:
        raise ApiError(422, 'INVALID_WATCH', f'{name} needs a time zone')
    return parsed


@csrf_exempt
@require_http_methods(['POST', 'DELETE'])
@api
def subscriptions(request):
    body = _body(request)
    endpoint = _endpoint(body.get('endpoint'))
    if request.method == 'DELETE':
        PushSubscription.objects.filter(endpoint=endpoint).delete()
        return HttpResponse(status=204)
    keys = body.get('keys') if isinstance(body.get('keys'), dict) else {}
    p256dh, auth = keys.get('p256dh'), keys.get('auth')
    if not (isinstance(p256dh, str) and 80 <= len(p256dh) <= 100 and B64URL.match(p256dh)
            and isinstance(auth, str) and 16 <= len(auth) <= 30 and B64URL.match(auth)):
        raise ApiError(422, 'INVALID_KEYS', 'keys.p256dh and keys.auth must be the base64url keys from PushSubscription.toJSON()')
    language = body.get('language') if body.get('language') in ('sl', 'en') else 'sl'
    sub, _ = PushSubscription.objects.update_or_create(endpoint=endpoint, defaults={'p256dh': p256dh, 'auth': auth, 'language': language, 'failures': 0})
    # The browser rotated its subscription (pushsubscriptionchange): the reminders move along.
    previous = body.get('previousEndpoint')
    if isinstance(previous, str) and previous != endpoint:
        old = PushSubscription.objects.filter(endpoint=previous).first()
        if old:
            taken = set(sub.watches.values_list('client_id', flat=True))
            old.watches.exclude(client_id__in=taken).update(subscription=sub)
            old.delete()
    return JsonResponse({'id': sub.pk}, status=201)


@csrf_exempt
@require_POST
@api
def watches(request):
    body = _body(request)
    sub = _subscription(body.get('endpoint'))
    client_id = _text(body, 'id', 200)
    kind = body.get('kind')
    if kind not in ('journey', 'departure'):
        raise ApiError(422, 'INVALID_WATCH', "kind must be 'journey' or 'departure'")
    url = _text(body, 'url', 500)
    if not url.startswith('/') or url.startswith('//'):
        raise ApiError(422, 'INVALID_WATCH', 'url must be a path within the app')
    trip_ids = body.get('tripIds') or []
    if not isinstance(trip_ids, list) or len(trip_ids) > MAX_TRIPS or not all(isinstance(t, str) and QUALIFIED.match(t) and len(t) <= 200 for t in trip_ids):
        raise ApiError(422, 'INVALID_WATCH', f'tripIds must be at most {MAX_TRIPS} feed-qualified ids')
    stop_id = _text(body, 'stopId', 200, required=False)
    exit_stop_id = _text(body, 'exitStopId', 200, required=False)
    notify_at = _time(body, 'notifyAt')
    scheduled_at = _time(body, 'scheduledAt', required=False)
    ends_at = _time(body, 'endsAt', required=False)
    if not Watch.objects.filter(subscription=sub, client_id=client_id).exists() and sub.watches.count() >= MAX_WATCHES:
        raise ApiError(422, 'TOO_MANY_WATCHES', f'At most {MAX_WATCHES} reminders per device')
    Watch.objects.update_or_create(subscription=sub, client_id=client_id, defaults={
        'kind': kind, 'notify_at': notify_at, 'title': _text(body, 'title', 120), 'body': _text(body, 'body', 300), 'url': url,
        'trip_ids': trip_ids, 'stop_id': stop_id, 'exit_stop_id': exit_stop_id, 'scheduled_at': scheduled_at,
        'expires_at': max(t for t in (ends_at, scheduled_at, notify_at) if t) + KEEP_AFTER,
        # A changed reminder starts over.
        'sent_reminder': False, 'last_delay': None, 'last_status': '', 'last_sent': None, 'journey_state': {},
    })
    return JsonResponse({'id': client_id}, status=201)


@csrf_exempt
@require_http_methods(['DELETE'])
@api
def watch_detail(request, client_id):
    sub = _subscription(request.GET.get('endpoint'))
    Watch.objects.filter(subscription=sub, client_id=client_id).delete()
    return HttpResponse(status=204)


@csrf_exempt
@require_POST
@api
def test(request):
    """Sends a test notification to this browser, so the user sees push works with the app closed."""
    sub = _subscription(_body(request).get('endpoint'))
    if not settings.PRESTOP_VAPID_PRIVATE_KEY:
        raise ApiError(503, 'PUSH_UNAVAILABLE', 'Push notifications are not configured on this server')
    text = {'sl': ('KamGre', 'Obvestila delujejo, tudi ko je aplikacija zaprta.'), 'en': ('KamGre', 'Notifications work, even when the app is closed.')}
    title, message = text.get(sub.language, text['sl'])
    result = sender.send(sub, {'title': title, 'body': message, 'url': '/settings', 'tag': 'test', 'kind': 'test', 'renotify': True}, urgent=True)
    if result == 'gone':
        sub.delete()
    return JsonResponse({'result': result})
