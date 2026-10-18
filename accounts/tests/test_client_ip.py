"""Client IP behind nginx: anonymous throttles and Turnstile.

nginx is the only proxy (``proxy_set_header X-Forwarded-For
$proxy_add_x_forwarded_for``): it *appends* the peer it saw to whatever the
client sent, so only the last entry is trustworthy. Without ``NUM_PROXIES``,
DRF used the whole header as the throttle identity, and a forged
X-Forwarded-For per request reset every anonymous limit.
"""

from rest_framework.settings import api_settings
from rest_framework.test import APIRequestFactory
from rest_framework.throttling import AnonRateThrottle

from accounts.turnstile import get_remote_ip


def make_request(xff=None):
    headers = {"REMOTE_ADDR": "127.0.0.1"}
    if xff is not None:
        headers["HTTP_X_FORWARDED_FOR"] = xff
    return APIRequestFactory().post("/api/v1/auth/login/", **headers)


def ident(xff=None):
    return AnonRateThrottle().get_ident(make_request(xff))


def test_a_single_proxy_is_declared():
    assert api_settings.NUM_PROXIES == 1


def test_forged_x_forwarded_for_does_not_change_the_throttle_ident():
    genuine = ident("203.0.113.7")
    forged = ident("1.2.3.4, 203.0.113.7")
    other_forgery = ident("5.6.7.8, 9.9.9.9, 203.0.113.7")
    assert genuine == forged == other_forgery == "203.0.113.7"


def test_without_header_the_socket_address_is_used():
    assert ident() == "127.0.0.1"


def test_turnstile_gets_the_address_nginx_saw_not_the_client_one():
    assert get_remote_ip(make_request("1.2.3.4, 203.0.113.7")) == "203.0.113.7"
    assert get_remote_ip(make_request("203.0.113.7")) == "203.0.113.7"
    assert get_remote_ip(make_request()) == "127.0.0.1"
