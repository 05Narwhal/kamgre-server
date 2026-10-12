"""Web Push subscriptions (one per browser install) and the reminders/trips they watch."""
from django.db import models


class PushSubscription(models.Model):
    endpoint = models.URLField(max_length=1024, unique=True)
    p256dh = models.CharField(max_length=200)
    auth = models.CharField(max_length=64)
    language = models.CharField(max_length=2, default='sl')
    created = models.DateTimeField(auto_now_add=True)
    last_ok = models.DateTimeField(null=True, blank=True)
    # Consecutive failed sends (not "gone"); reset by a successful one.
    failures = models.PositiveIntegerField(default=0)

    def info(self) -> dict:
        return {'endpoint': self.endpoint, 'keys': {'p256dh': self.p256dh, 'auth': self.auth}}


class Watch(models.Model):
    KINDS = [('journey', 'journey'), ('departure', 'departure')]

    subscription = models.ForeignKey(PushSubscription, on_delete=models.CASCADE, related_name='watches')
    client_id = models.CharField(max_length=200)
    kind = models.CharField(max_length=10, choices=KINDS)
    notify_at = models.DateTimeField()
    title = models.CharField(max_length=120)
    body = models.CharField(max_length=300)
    url = models.CharField(max_length=500)
    trip_ids = models.JSONField(default=list, blank=True)
    stop_id = models.CharField(max_length=200, blank=True, default='')
    scheduled_at = models.DateTimeField(null=True, blank=True)
    # Last delay (s) and status ('ok' | 'canceled') the user was told about; empty until first seen.
    last_delay = models.IntegerField(null=True, blank=True)
    last_status = models.CharField(max_length=10, blank=True, default='')
    last_sent = models.DateTimeField(null=True, blank=True)
    sent_reminder = models.BooleanField(default=False)
    expires_at = models.DateTimeField()

    class Meta:
        constraints = [models.UniqueConstraint(fields=['subscription', 'client_id'], name='prestop_push_watch_unique_client_id')]
        indexes = [models.Index(fields=['expires_at'])]
