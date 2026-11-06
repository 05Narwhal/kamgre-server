"""Validators for /api/v1 answers (request budget, spec N16).

Django's ConditionalGetMiddleware turns an unchanged answer into a bodiless 304, but it hashes the whole body, and every
envelope (`envelope()` in views.py) carries `meta.generatedAt`, the second the answer was made. That alone changes the hash on
every call, so nothing ever matched. This middleware sets the ETag first, from the body without that one stamp: the same data
and the same source stamps (`meta.sources[].updatedAt`, which are in the hash) give the same ETag. The client does not read
`generatedAt` (it is only in the contract), so a browser that reuses its copy after a 304 shows nothing older than before.
"""
import hashlib
import re

# `"generatedAt": "2026-11-06T22:30:03Z"` as JsonResponse writes it, with its separator.
GENERATED_AT = re.compile(rb'"generatedAt": "[^"]*",? ?')


class StableEtagMiddleware:
    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        response = self.get_response(request)
        if (request.method == 'GET' and response.status_code == 200 and not response.streaming and not response.has_header('ETag')
                and request.path.startswith('/api/v1/') and response.get('Content-Type', '').startswith('application/json')):
            digest = hashlib.md5(GENERATED_AT.sub(b'', response.content), usedforsecurity=False).hexdigest()
            response['ETag'] = f'"{digest}"'
        return response
