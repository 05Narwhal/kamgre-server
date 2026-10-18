"""Sends one VAPID-signed Web Push message straight to the browser's push service."""
import json
import logging
import re
from typing import Literal
from urllib.parse import urlsplit

from django.conf import settings
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

Result = Literal['ok', 'gone', 'error']
# The browsers' push services (Chrome/Android/Samsung/Opera: FCM; Firefox: Mozilla; Safari: Apple; Edge: WNS).
# The server sends to nothing else: an endpoint is a URL the browser hands over, and the server POSTs to it, so
# without this anyone could make the server send requests anywhere (spec 2026-10-18 A6).
PUSH_HOSTS = re.compile(r'^(?:fcm\.googleapis\.com|android\.googleapis\.com|(?:updates\.)?push\.services\.mozilla\.com'
                        r'|(?:[a-z0-9-]+\.)*push\.apple\.com|[a-z0-9-]+\.notify\.windows\.com)$')


def allowed(endpoint: str) -> bool:
    """An https URL on a known push service, on the standard port."""
    try:
        parts = urlsplit(endpoint)
        port = parts.port
    except ValueError:
        return False
    return parts.scheme == 'https' and port in (None, 443) and not parts.username and bool(PUSH_HOSTS.match((parts.hostname or '').lower()))


def send(sub, payload: dict, urgent: bool = False) -> Result:
    """'gone' means the browser revoked the subscription (HTTP 404/410): delete it, never retry."""
    if not allowed(sub.endpoint):
        return 'gone'  # stored before push services were checked: never sent to, and removed
    try:
        webpush(
            subscription_info=sub.info(),
            data=json.dumps(payload, ensure_ascii=False),
            vapid_private_key=settings.PRESTOP_VAPID_PRIVATE_KEY,
            # pywebpush adds aud/exp to the claims dict it is given, so pass a fresh one.
            vapid_claims={'sub': settings.PRESTOP_VAPID_SUBJECT},
            ttl=300,
            headers={'Urgency': 'high' if urgent else 'normal'},
            timeout=10,
        )
    except WebPushException as e:
        status = getattr(e.response, 'status_code', None)
        if status in (404, 410):
            return 'gone'
        logger.warning('Push to %s failed: %s', sub.endpoint[:60], status or e)
        return 'error'
    except Exception as e:  # network errors from requests
        logger.warning('Push to %s failed: %r', sub.endpoint[:60], e)
        return 'error'
    return 'ok'
