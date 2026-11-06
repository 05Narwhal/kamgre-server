from django.conf import settings
from django.http import HttpResponse, JsonResponse
from django.test import RequestFactory, SimpleTestCase, TestCase

from prestop_api.etag import StableEtagMiddleware


class ConditionalGetTests(TestCase):
    """GET answers carry an ETag, and an unchanged one is a bodiless 304 (the app's polls and refocus refetches)."""

    def test_middleware_order(self):
        order = settings.MIDDLEWARE
        guard = order.index('prestop_api.traffic.TrafficGuardMiddleware')
        conditional = order.index('django.middleware.http.ConditionalGetMiddleware')
        stable = order.index('prestop_api.etag.StableEtagMiddleware')
        # The guard refuses first; the ETag is set (inner) before ConditionalGet (outer) looks at it; CORS is further in.
        self.assertLess(guard, conditional)
        self.assertLess(conditional, stable)
        self.assertLess(stable, order.index('corsheaders.middleware.CorsMiddleware'))

    def test_unchanged_answer_is_a_304(self):
        first = self.client.get('/api/v1/rail/lines')
        self.assertEqual(first.status_code, 200)
        etag = first['ETag']
        self.assertTrue(etag)
        again = self.client.get('/api/v1/rail/lines', HTTP_IF_NONE_MATCH=etag)
        self.assertEqual(again.status_code, 304)
        self.assertEqual(again.content, b'')
        self.assertEqual(again['ETag'], etag)

    def test_other_validator_gets_the_whole_answer(self):
        other = self.client.get('/api/v1/rail/lines', HTTP_IF_NONE_MATCH='"not-this-one"')
        self.assertEqual(other.status_code, 200)
        self.assertTrue(other.content)


def envelope(generated_at, updated='2026-11-06T22:24:46Z', data=()):
    """The shape `views.envelope` writes: the data, and meta with the second it was made and each source's stamp."""
    return {'data': list(data), 'meta': {'generatedAt': generated_at, 'sourceUpdatedAt': updated, 'status': 'live',
                                         'sources': [{'id': 'x', 'updatedAt': updated}]}}


class StableEtagTests(SimpleTestCase):
    def etag(self, response, path='/api/v1/vehicles', method='get'):
        request = getattr(RequestFactory(), method)(path)
        return StableEtagMiddleware(lambda _: response)(request).get('ETag')

    def test_the_second_it_was_made_is_not_part_of_the_validator(self):
        a = self.etag(JsonResponse(envelope('2026-11-06T22:30:03Z')))
        b = self.etag(JsonResponse(envelope('2026-11-06T22:30:07Z')))
        self.assertTrue(a)
        self.assertEqual(a, b)

    def test_changed_data_or_source_stamp_changes_it(self):
        base = self.etag(JsonResponse(envelope('2026-11-06T22:30:03Z')))
        moved = self.etag(JsonResponse(envelope('2026-11-06T22:30:03Z', data=[{'id': 'a', 'delaySeconds': 60}])))
        newer = self.etag(JsonResponse(envelope('2026-11-06T22:30:03Z', updated='2026-11-06T22:30:00Z')))
        self.assertNotEqual(base, moved)
        self.assertNotEqual(base, newer)

    def test_only_json_gets_of_the_api(self):
        body = envelope('2026-11-06T22:30:03Z')
        self.assertIsNone(self.etag(JsonResponse(body), path='/admin/'))
        self.assertIsNone(self.etag(JsonResponse(body), method='post'))
        self.assertIsNone(self.etag(HttpResponse(b'x', content_type='text/plain')))
        self.assertIsNone(self.etag(JsonResponse({}, status=404)))
