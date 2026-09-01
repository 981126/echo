"""纯逻辑（无第三方依赖）：阿里云 REST 签名构造（HMAC-SHA1）。

阿里云录音文件识别（FileTrans）签名算法：
  StringToSign = HTTPMethod + "\n" + Accept + "\n" + Content-MD5 + "\n"
                 + Content-Type + "\n" + Date + "\n"
                 + CanonicalizedHeaders + CanonicalizedResource
  Signature = Base64( HMAC-SHA1( AccessKeySecret, StringToSign ) )
"""
import base64
import hashlib
import hmac
from datetime import datetime, timezone
from urllib.parse import quote


def utcnow_rfc1123() -> str:
    """当前 UTC 时间的 RFC1123 格式（阿里云 Date 头）。"""
    return datetime.now(timezone.utc).strftime("%a, %d %b %Y %H:%M:%S GMT")


def content_md5(body: bytes) -> str:
    if not body:
        return ""
    return base64.b64encode(hashlib.md5(body).digest()).decode()


def _quote(value: str) -> str:
    return quote(value, safe="~")


def build_canonicalized_query(params: dict) -> str:
    """按 key 升序拼接 URL 查询串。"""
    if not params:
        return ""
    parts = []
    for key in sorted(params):
        value = params[key]
        if value is None:
            continue
        if isinstance(value, bool):
            value = "true" if value else "false"
        parts.append(f"{_quote(str(key))}={_quote(str(value))}")
    return "&".join(parts)


def build_string_to_sign(
    method: str,
    accept: str,
    body: bytes,
    content_type: str,
    date: str,
    canonicalized_headers: str,
    canonicalized_resource: str,
) -> str:
    md5 = content_md5(body)
    return "\n".join(
        [method.upper(), accept, md5, content_type, date, canonicalized_headers, canonicalized_resource]
    )


def hmac_sha1_sign(secret: str, string_to_sign: str) -> str:
    digest = hmac.new(secret.encode("utf-8"), string_to_sign.encode("utf-8"), hashlib.sha1).digest()
    return base64.b64encode(digest).decode()
