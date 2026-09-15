import unittest
from types import SimpleNamespace

from app.security import same_origin_request


class DummyHeaders(dict):
    def get(self,key,default=None):
        return super().get(key.lower(),default)


class SecurityOriginTests(unittest.TestCase):
    def req(self, headers, *, scheme="https"):
        h={k.lower():v for k,v in headers.items()}
        return SimpleNamespace(
            headers=DummyHeaders(h),
            url=SimpleNamespace(netloc=h.get("host",""), scheme=scheme),
        )

    def test_same_origin_from_origin_header(self):
        self.assertTrue(same_origin_request(self.req({"host":"example.com","origin":"https://example.com"})))

    def test_cross_origin_is_rejected(self):
        self.assertFalse(same_origin_request(self.req({"host":"example.com","origin":"https://evil.example"})))

    def test_same_origin_from_referer(self):
        self.assertTrue(same_origin_request(self.req({"host":"example.com","referer":"https://example.com/admin"})))

    def test_missing_origin_is_not_browser_safe(self):
        self.assertFalse(same_origin_request(self.req({"host":"example.com"})))

    def test_scheme_is_part_of_same_origin_contract(self):
        self.assertFalse(same_origin_request(self.req({"host":"example.com","origin":"http://example.com"})))

    def test_default_https_port_is_canonicalized(self):
        self.assertTrue(same_origin_request(self.req({"host":"example.com:443","origin":"https://example.com"})))

    def test_non_default_port_mismatch_is_rejected(self):
        self.assertFalse(same_origin_request(self.req({"host":"example.com:8443","origin":"https://example.com"})))

    def test_cross_site_fetch_metadata_is_rejected(self):
        self.assertFalse(same_origin_request(self.req({
            "host":"example.com",
            "origin":"https://example.com",
            "sec-fetch-site":"cross-site",
        })))

    def test_origin_with_userinfo_is_rejected(self):
        self.assertFalse(same_origin_request(self.req({
            "host":"example.com",
            "origin":"https://user@example.com",
        })))


if __name__=="__main__":
    unittest.main()
