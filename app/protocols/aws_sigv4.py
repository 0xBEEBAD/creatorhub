"""Small, dependency-free AWS SigV4 and streaming CRC32 implementation."""
from __future__ import annotations

import hashlib
import hmac
import urllib.parse
import zlib
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Iterable, Mapping


@dataclass(frozen=True)
class AwsCredentials:
    access_key_id: str
    secret_access_key: str
    session_token: str = ""


@dataclass(frozen=True)
class SigV4Request:
    method: str
    host: str
    path: str = "/"
    query: Mapping[str, object] | Iterable[tuple[str, object]] = ()
    body: bytes = b""
    region: str = "cn-north-1"
    service: str = "vod"


def _encode(value: object) -> str:
    return urllib.parse.quote(str(value), safe="-_.~")


def canonical_query(query: Mapping[str, object] | Iterable[tuple[str, object]]) -> str:
    items = query.items() if isinstance(query, Mapping) else query
    encoded = [(_encode(key), _encode(value)) for key, value in items]
    encoded.sort()
    return "&".join(f"{key}={value}" for key, value in encoded)


def sha256_hex(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def crc32_hex(chunks: bytes | bytearray | memoryview | Iterable[bytes]) -> str:
    if isinstance(chunks, (bytes, bytearray, memoryview)):
        chunks = (bytes(chunks),)
    checksum = 0
    for chunk in chunks:
        checksum = zlib.crc32(chunk, checksum)
    return f"{checksum & 0xFFFFFFFF:08x}"


def _hmac(key: bytes, value: str) -> bytes:
    return hmac.new(key, value.encode("utf-8"), hashlib.sha256).digest()


def sign_sigv4(request: SigV4Request, credentials: AwsCredentials, *,
               now: datetime | None = None) -> dict[str, str]:
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now = now.astimezone(timezone.utc)
    amz_date = now.strftime("%Y%m%dT%H%M%SZ")
    date_stamp = now.strftime("%Y%m%d")
    payload_hash = sha256_hex(request.body)
    token = credentials.session_token
    canonical_headers = f"x-amz-date:{amz_date}\n"
    signed_headers = "x-amz-date"
    if token:
        canonical_headers += f"x-amz-security-token:{token}\n"
        signed_headers += ";x-amz-security-token"
    path = request.path if request.path.startswith("/") else "/" + request.path
    canonical_request = "\n".join((
        request.method.upper(), urllib.parse.quote(path, safe="/-_.~"),
        canonical_query(request.query), canonical_headers,
        signed_headers, payload_hash,
    ))
    scope = f"{date_stamp}/{request.region}/{request.service}/aws4_request"
    string_to_sign = "\n".join((
        "AWS4-HMAC-SHA256", amz_date, scope,
        sha256_hex(canonical_request.encode("utf-8")),
    ))
    k_date = _hmac(("AWS4" + credentials.secret_access_key).encode(), date_stamp)
    k_region = _hmac(k_date, request.region)
    k_service = _hmac(k_region, request.service)
    k_signing = _hmac(k_service, "aws4_request")
    signature = hmac.new(
        k_signing, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()
    headers = {
        "x-amz-date": amz_date,
        "X-Amz-Content-Sha256": payload_hash,
        "Authorization": (
            "AWS4-HMAC-SHA256 "
            f"Credential={credentials.access_key_id}/{scope}, "
            f"SignedHeaders={signed_headers}, Signature={signature}"
        ),
    }
    if token:
        headers["x-amz-security-token"] = token
    return headers
