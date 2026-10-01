"""Exercise the release proxy using real HTTPS requests and a Cookie jar."""

import io
import base64
import hashlib
import hmac
import json
import os
import ssl
import sys
import urllib.error
import urllib.request
import zipfile
from http.cookiejar import CookieJar
from xml.etree import ElementTree

BASE = os.environ.get("RELEASE_BASE_URL", "https://127.0.0.1:8443")
DATE = "2026-07-15"
STORE_ID = 1


def client() -> urllib.request.OpenerDirector:
    # Only the ephemeral self-signed release proxy is trusted here.
    return urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(CookieJar()),
        urllib.request.HTTPSHandler(context=ssl._create_unverified_context()),
    )


def request(opener, path, method="GET", payload=None, expected=200):
    body = json.dumps(payload).encode() if payload is not None else None
    req = urllib.request.Request(
        BASE + path,
        data=body,
        method=method,
        headers={"Content-Type": "application/json"} if body is not None else {},
    )
    try:
        response = opener.open(req, timeout=20)
    except urllib.error.HTTPError as error:
        response = error
    with response:
        assert response.status == expected, (
            path,
            response.status,
            response.read()[:300],
        )
        data = response.read()
        return response.headers, data


def login(opener):
    headers, data = request(
        opener,
        "/api/auth/login",
        "POST",
        {
            "username": os.environ["AUTOLAVA_BOOTSTRAP_USERNAME"],
            "password": os.environ["AUTOLAVA_BOOTSTRAP_PASSWORD"],
        },
    )
    assert "Secure" in headers.get("Set-Cookie", "")
    assert json.loads(data)["username"] == os.environ["AUTOLAVA_BOOTSTRAP_USERNAME"]
    request(opener, "/api/auth/me")


def verify_export(data):
    with zipfile.ZipFile(io.BytesIO(data)) as workbook:
        strings = b"".join(
            workbook.read(name)
            for name in workbook.namelist()
            if name.startswith("xl/worksheets/") or name == "xl/sharedStrings.xml"
        )
        assert b"150" in strings, "Export workbook does not contain the recorded amount"
        assert ElementTree.fromstring(workbook.read("xl/workbook.xml")) is not None


def main():
    phase = sys.argv[1]
    opener = client()
    login(opener)
    if phase == "setup":
        _, data = request(
            opener,
            "/api/admin/stores",
            "POST",
            {
                "name": "Release Store",
                "address": "Isolated test",
                "latitude": 45.0,
                "longitude": 9.0,
                "timezone": "Europe/Rome",
            },
            201,
        )
        assert json.loads(data)["id"] == STORE_ID
        assert (
            json.loads(request(opener, "/api/stores/accessible")[1])[0]["id"]
            == STORE_ID
        )
        request(
            opener,
            "/api/admin/users",
            "POST",
            {
                "username": "release-outsider",
                "password": os.environ["AUTOLAVA_BOOTSTRAP_PASSWORD"] + "-user",
                "role": "user",
                "store_ids": [],
            },
            201,
        )
        outsider = client()
        request(
            outsider,
            "/api/auth/login",
            "POST",
            {
                "username": "release-outsider",
                "password": os.environ["AUTOLAVA_BOOTSTRAP_PASSWORD"] + "-user",
            },
        )
        request(outsider, f"/api/ledger/{STORE_ID}/{DATE}", expected=404)
        request(
            outsider, f"/api/charts/{STORE_ID}?start={DATE}&end={DATE}", expected=404
        )
    elif phase == "legacy":
        _, data = request(opener, "/api/admin/stores")
        assert json.loads(data)[0]["name"] == "Legacy Store"
        assert json.loads(request(opener, "/api/stores/accessible")[1])[0]["id"] == 1
        _, data = request(opener, "/api/ledger/1/2026-07-28")
        record = json.loads(data)
        assert record["daily_revenue"] == 940
        assert record["weather"] == "旧版任意天气" and record["weather_legacy"]
        assert (
            record["created_by"] == 1
            and record["items"][0]["category_name"] == "Old category"
        )
        _, data = request(
            opener, "/api/database/1/export.xlsx?start=2026-07-28&end=2026-07-28"
        )
        with zipfile.ZipFile(io.BytesIO(data)) as workbook:
            assert b"Old category" in b"".join(
                workbook.read(name)
                for name in workbook.namelist()
                if name.startswith("xl/")
            )
        # A token in the pre-session numeric-user format must remain invalid.
        from datetime import datetime, timedelta, timezone

        def encoded(value):
            return base64.urlsafe_b64encode(
                json.dumps(value, separators=(",", ":")).encode()
            ).rstrip(b"=")

        claim = {
            "sub": "1",
            "exp": int((datetime.now(timezone.utc) + timedelta(minutes=5)).timestamp()),
        }
        signing_input = encoded({"alg": "HS256", "typ": "JWT"}) + b"." + encoded(claim)
        signature = hmac.new(
            os.environ["AUTOLAVA_JWT_SECRET"].encode(), signing_input, hashlib.sha256
        ).digest()
        token = (
            signing_input + b"." + base64.urlsafe_b64encode(signature).rstrip(b"=")
        ).decode()
        req = urllib.request.Request(
            BASE + "/api/auth/me", headers={"Cookie": "access_token=" + token}
        )
        try:
            urllib.request.urlopen(
                req, context=ssl._create_unverified_context(), timeout=20
            )
        except urllib.error.HTTPError as error:
            assert error.code == 401
        else:
            raise AssertionError("Legacy numeric-user token was accepted")
    else:
        _, data = request(opener, f"/api/ledger/{STORE_ID}/{DATE}")
        record = json.loads(data)
        assert record["daily_revenue"] == 150 and record["wash_count"] == 3
        _, data = request(opener, f"/api/charts/{STORE_ID}?start={DATE}&end={DATE}")
        charts = json.loads(data)
        assert charts["kpis"]["total_revenue"] == 150
        assert charts["kpis"]["average_ticket"] == 50
        _, data = request(
            opener, f"/api/database/{STORE_ID}/export.xlsx?start={DATE}&end={DATE}"
        )
        verify_export(data)
        if phase == "verify":
            # A stale identity/revision must not overwrite a committed record.
            request(
                opener,
                f"/api/ledger/{STORE_ID}/{DATE}",
                "PUT",
                {
                    "expected_identity": "stale",
                    "expected_revision": 1,
                    "expected_config_revision": record["config_revision"],
                    "is_open": "营业",
                    "daily_revenue": 999,
                    "items": [],
                },
                409,
            )
            _, unchanged = request(opener, f"/api/ledger/{STORE_ID}/{DATE}")
            assert json.loads(unchanged)["daily_revenue"] == 150
    request(opener, "/api/auth/logout", "POST", expected=204)
    request(opener, "/api/auth/me", expected=401)
    print(f"HTTPS Cookie and public HTTP {phase}: passed")


if __name__ == "__main__":
    main()
