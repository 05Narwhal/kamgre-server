import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec
from django.core.management import BaseCommand


def b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b'=').decode()


class Command(BaseCommand):
    help = "Print a new VAPID key pair as env lines (PRESTOP_VAPID_PUBLIC_KEY / PRESTOP_VAPID_PRIVATE_KEY)."

    def handle(self, **options):
        key = ec.generate_private_key(ec.SECP256R1())
        private = key.private_numbers().private_value.to_bytes(32, 'big')
        public = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
        self.stdout.write(f'PRESTOP_VAPID_PUBLIC_KEY={b64url(public)}')
        self.stdout.write(f'PRESTOP_VAPID_PRIVATE_KEY={b64url(private)}')
