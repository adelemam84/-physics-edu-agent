import unittest
from types import SimpleNamespace

from app.security import same_origin_request


class DummyHeaders(dict):
    def get(self,key,default=None):
        return super().get(key.lower(),default)


class SecurityOriginTests(unittest.TestCase):
    def req(self, headers):
        h={k.lower():v for k,v in headers.items()}
        return SimpleNamespace(headers=DummyHeaders(h),url=SimpleNamespace(netloc=h.get("host","")))

    def test_same_origin_from_origin_header(self):
        self.assertTrue(same_origin_request(self.req({"host":"example.com","origin":"https://example.com"})))

    def test_cross_origin_is_rejected(self):
        self.assertFalse(same_origin_request(self.req({"host":"example.com","origin":"https://evil.example"})))

    def test_same_origin_from_referer(self):
        self.assertTrue(same_origin_request(self.req({"host":"example.com","referer":"https://example.com/admin"})))

    def test_missing_origin_is_not_browser_safe(self):
        self.assertFalse(same_origin_request(self.req({"host":"example.com"})))


if __name__=="__main__":
    unittest.main()
