"""Sends one VAPID-signed Web Push message straight to the browser's push service."""
import json
import logging
from typing import Literal

from django.conf import settings
from pywebpush import WebPushException, webpush

logger = logging.getLogger(__name__)

Result = Literal['ok', 'gone', 'error']


def send(sub, payload: dict, urgent: bool = False) -> Result:
    """'gone' means the browser revoked the subscription (HTTP 404/410): delete it, never retry."""
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
