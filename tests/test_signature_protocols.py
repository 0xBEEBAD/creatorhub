import hashlib
import hmac
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone

from app.platforms.xhs import creator_sign
from app.protocols.aws_sigv4 import (
    AwsCredentials,
    SigV4Request,
    canonical_query,
    crc32_hex,
    sign_sigv4,
)
from app.transport_matrix import transport_spec


def test_crc32_matches_standard_vector_and_streaming_chunks():
    assert crc32_hex(b"123456789") == "cbf43926"
    assert crc32_hex([b"123", b"456", b"789"]) == "cbf43926"


def test_sigv4_matches_independent_reference_calculation():
    now = datetime(2026, 10, 28, 4, 5, 6, tzinfo=timezone.utc)
    request = SigV4Request(
        method="POST", host="vod.bytedanceapi.com", path="/",
        query={"Version": "2020-11-19", "Action": "CommitUploadInner",
               "SpaceName": "fixture"}, body=b'{"SessionKey":"fixture"}',
    )
    credentials = AwsCredentials("AKID", "SECRET", "TOKEN")
    headers = sign_sigv4(request, credentials, now=now)

    query = canonical_query(request.query)
    payload = hashlib.sha256(request.body).hexdigest()
    canonical_headers = "x-amz-date:20261028T040506Z\nx-amz-security-token:TOKEN\n"
    canonical = "\n".join((
        "POST", "/", query, canonical_headers,
        "x-amz-date;x-amz-security-token", payload,
    ))
    scope = "20261028/cn-north-1/vod/aws4_request"
    to_sign = "\n".join((
        "AWS4-HMAC-SHA256", "20261028T040506Z", scope,
        hashlib.sha256(canonical.encode()).hexdigest(),
    ))
    digest = lambda key, text: hmac.new(key, text.encode(), hashlib.sha256).digest()
    signing = digest(digest(digest(digest(b"AWS4SECRET", "20261028"),
                                        "cn-north-1"), "vod"), "aws4_request")
    signature = hmac.new(signing, to_sign.encode(), hashlib.sha256).hexdigest()
    assert headers["Authorization"].endswith("Signature=" + signature)
    assert headers["X-Amz-Content-Sha256"] == payload


def test_xhs_persistent_signer_reuses_one_node_process():
    creator_sign.close_signers()
    one = creator_sign.generate_xsc_main(
        "a1fixture", "/api/sns/web/v1/user_posted?num=30", "", "GET")
    worker = creator_sign._WORKERS["xhs_main_260411.js"]
    pid = worker._process.pid
    two = creator_sign.generate_xsc_main(
        "a1fixture", "/api/sns/web/v1/user_posted?num=30", "", "GET")
    assert worker is creator_sign._WORKERS["xhs_main_260411.js"]
    assert worker._process.pid == pid
    assert one["x-s"] and two["x-s"]
    creator_sign.close_signers()


def test_xhs_persistent_signer_serializes_concurrent_callers():
    creator_sign.close_signers()
    with ThreadPoolExecutor(max_workers=4) as pool:
        rows = list(pool.map(
            lambda index: creator_sign.generate_xsc_main(
                "a1fixture", f"/api/sns/web/v1/user_posted?num={index}",
                "", "GET"),
            range(1, 9),
        ))
    assert all(row["x-s"] and row["x-t"] for row in rows)
    assert len(creator_sign._WORKERS) == 1
    creator_sign.close_signers()


def test_xhs_persistent_signer_restarts_after_worker_exit():
    creator_sign.close_signers()
    creator_sign.generate_xsc_main("a1fixture", "/api/test", "", "GET")
    old = creator_sign._WORKERS["xhs_main_260411.js"]
    old_pid = old._process.pid
    old.close()
    result = creator_sign.generate_xsc_main(
        "a1fixture", "/api/test?again=1", "", "GET")
    current = creator_sign._WORKERS["xhs_main_260411.js"]
    assert result["x-s"]
    assert current._process.pid != old_pid
    creator_sign.close_signers()


def test_transport_matrix_exposes_auth_and_wire_protocols():
    xhs = transport_spec("xhs", "public_monitor")
    assert xhs["auth_protocol"].startswith("x-s / x-t")
    assert xhs["signer_runtime"] == "persistent_node"
    dm = transport_spec("douyin", "dm_send")
    assert dm["wire_protocol"] == "imapi protobuf"
    channels = transport_spec("shipinhao", "account_management")
    assert "X-WECHAT-UIN" in channels["auth_protocol"]
