"""External observation labels based on real Cloudflare Access redirect shapes."""

from backend.external_probe import classify_response


def test_cloudflare_team_login_redirect_is_recognized():
    hostname = "sa-gui-e2e-1024-122f4b.woowtech.io"
    location = (
        "https://woowtech.cloudflareaccess.com/cdn-cgi/access/login/"
        + hostname + "?kid=example"
    )
    assert classify_response(302, location, hostname, "cloudflare") == "login_required"


def test_similar_looking_redirect_does_not_claim_access_protection():
    hostname = "sa-gui-e2e-1024-122f4b.woowtech.io"
    path = "/cdn-cgi/access/login/" + hostname
    assert classify_response(302, "https://woowtech.cloudflareaccess.com.evil.test" + path,
                             hostname, "cloudflare") == "undetermined"
    assert classify_response(302, "http://woowtech.cloudflareaccess.com" + path,
                             hostname, "cloudflare") == "undetermined"
    assert classify_response(302, "https://woowtech.cloudflareaccess.com" + path,
                             hostname, "nginx") == "undetermined"


def test_anonymous_200_remains_public_response():
    assert classify_response(200, "", "ha.example.com", "cloudflare") == "public_response"
