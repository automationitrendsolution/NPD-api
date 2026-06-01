"""
SP-API client for Brand Analytics reports.

Responsibilities
----------------
1. LWA token exchange  — trade a refresh_token for a short-lived access_token.
2. AWS SigV4 signing   — every SP-API request must be signed with AWS credentials.
3. Reports API calls   — create, poll, download Brand Analytics reports.

How the SP-API authentication works
-------------------------------------
Amazon's Selling Partner API uses TWO layers of authentication:

Layer 1 — LWA (Login with Amazon)
    Your app has a client_id + client_secret + refresh_token.
    You POST to Amazon's OAuth endpoint to get a short-lived access_token (1 hour).
    This token goes in the x-amz-access-token header of every SP-API request.

Layer 2 — AWS SigV4
    You also have an IAM user with AWS_ACCESS_KEY_ID + AWS_SECRET_ACCESS_KEY.
    Every HTTP request must be signed using these credentials.
    The signature proves the request hasn't been tampered with in transit.
    It goes in the Authorization header.

Both layers are required. SigV4 alone is not enough; the LWA token is also needed.

Required environment variables (add to your .env file)
-------------------------------------------------------
    SP_API_CLIENT_ID        # From your SP-API app in Seller Central
    SP_API_CLIENT_SECRET    # From your SP-API app in Seller Central
    SP_API_REFRESH_TOKEN    # From the SP-API app authorization step
    SP_API_MARKETPLACE_ID   # e.g. ATVPDKIKX0DER (US), A1F83G8C2ARO7P (UK)
    AWS_ACCESS_KEY_ID       # IAM user key (from AWS console)
    AWS_SECRET_ACCESS_KEY   # IAM user secret (from AWS console)
    AWS_REGION              # Default: us-east-1
"""

import gzip
import hashlib
import hmac
import io
import json
import os
from datetime import datetime, timezone
from pathlib import Path

import requests


# ── Env loading (same pattern as search/scraper.py) ───────────────────────────

def _load_dotenv():
    env_path = Path(__file__).resolve().parents[2] / ".env"
    if not env_path.exists():
        return
    for raw_line in env_path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


_load_dotenv()

SP_ENDPOINT = "https://sellingpartnerapi-na.amazon.com"
LWA_TOKEN_URL = "https://api.amazon.com/auth/o2/token"
AWS_SERVICE = "execute-api"


def _get_env(key: str) -> str:
    """Returns an env var or raises a clear error if it's missing."""
    val = os.getenv(key, "").strip()
    if not val:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            f"Add it to your .env file and restart the server."
        )
    return val


# ── LWA token exchange ────────────────────────────────────────────────────────

def get_access_token() -> str:
    """
    Exchanges the LWA refresh_token for a short-lived access_token.

    The access_token expires in 1 hour. In production you'd cache it,
    but for a job that runs weekly, a fresh exchange per run is fine.

    Returns
    -------
    str
        The LWA access token to use in x-amz-access-token header.
    """
    response = requests.post(
        LWA_TOKEN_URL,
        data={
            "grant_type": "refresh_token",
            "refresh_token": _get_env("SP_API_REFRESH_TOKEN"),
            "client_id": _get_env("SP_API_CLIENT_ID"),
            "client_secret": _get_env("SP_API_CLIENT_SECRET"),
        },
        timeout=30,
    )
    response.raise_for_status()
    return response.json()["access_token"]


# ── AWS SigV4 signing ─────────────────────────────────────────────────────────
#
# SigV4 is Amazon's request-signing standard. It works by:
#   1. Building a "canonical request" — a normalized string of all request parts.
#   2. Building a "string to sign" — a hash of the canonical request plus metadata.
#   3. Computing a signature using HMAC-SHA256 with a derived signing key.
#   4. Attaching the signature in the Authorization header.
#
# This implementation uses only stdlib (hmac, hashlib) — no boto3 needed.

def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _hmac_sha256(key: bytes, msg: str) -> bytes:
    return hmac.new(key, msg.encode("utf-8"), hashlib.sha256).digest()


def _derive_signing_key(secret_key: str, date_stamp: str, region: str, service: str) -> bytes:
    """
    Derives the signing key by chaining 4 HMAC operations.

    The date, region, and service are folded into the key so the key is
    scoped: a signature made with this key is only valid for this specific
    date / region / service combination.
    """
    k_date    = _hmac_sha256(("AWS4" + secret_key).encode("utf-8"), date_stamp)
    k_region  = _hmac_sha256(k_date, region)
    k_service = _hmac_sha256(k_region, service)
    k_signing = _hmac_sha256(k_service, "aws4_request")
    return k_signing


def _sign_request(
    method: str,
    url: str,
    headers: dict,
    payload: bytes = b"",
    region: str = "us-east-1",
    service: str = "execute-api",
) -> dict:
    """
    Adds SigV4 signing headers to the supplied headers dict.

    Returns the headers dict with Authorization and x-amz-date added.

    Parameters
    ----------
    method : str
        HTTP method in uppercase, e.g. "GET", "POST".
    url : str
        Full URL including query string.
    headers : dict
        Existing headers. Must already include x-amz-access-token.
    payload : bytes
        Raw request body (empty for GET requests).
    region : str
        AWS region, typically "us-east-1" for NA SP-API.
    service : str
        AWS service name. SP-API uses "execute-api".
    """
    from urllib.parse import urlparse, urlencode, quote

    now = datetime.now(timezone.utc)
    amz_date  = now.strftime("%Y%m%dT%H%M%SZ")   # e.g. 20260601T120000Z
    date_stamp = now.strftime("%Y%m%d")            # e.g. 20260601

    parsed = urlparse(url)
    host   = parsed.netloc
    path   = parsed.path or "/"

    # Canonical query string: sort params alphabetically
    if parsed.query:
        params = sorted(parsed.query.split("&"))
        canonical_qs = "&".join(params)
    else:
        canonical_qs = ""

    # Add required headers for signing
    headers["x-amz-date"] = amz_date
    headers["host"] = host

    # Canonical headers: lowercase names, sorted alphabetically, trimmed values
    signed_header_names = sorted(k.lower() for k in headers)
    canonical_headers = "".join(
        f"{k}:{headers[next(hk for hk in headers if hk.lower() == k)].strip()}\n"
        for k in signed_header_names
    )
    signed_headers_str = ";".join(signed_header_names)

    # Hash the request body (empty string hash for GET)
    payload_hash = _sha256(payload)

    # Step 1: canonical request
    canonical_request = "\n".join([
        method.upper(),
        quote(path, safe="/-_.~"),
        canonical_qs,
        canonical_headers,
        signed_headers_str,
        payload_hash,
    ])

    # Step 2: string to sign
    credential_scope = f"{date_stamp}/{region}/{service}/aws4_request"
    string_to_sign = "\n".join([
        "AWS4-HMAC-SHA256",
        amz_date,
        credential_scope,
        _sha256(canonical_request.encode("utf-8")),
    ])

    # Step 3: signature
    access_key = _get_env("AWS_ACCESS_KEY_ID")
    secret_key = _get_env("AWS_SECRET_ACCESS_KEY")
    signing_key = _derive_signing_key(secret_key, date_stamp, region, service)
    signature = hmac.new(signing_key, string_to_sign.encode("utf-8"), hashlib.sha256).hexdigest()

    # Step 4: Authorization header
    headers["Authorization"] = (
        f"AWS4-HMAC-SHA256 "
        f"Credential={access_key}/{credential_scope}, "
        f"SignedHeaders={signed_headers_str}, "
        f"Signature={signature}"
    )

    return headers


def _sp_api_request(method: str, path: str, body: dict = None, params: dict = None) -> dict:
    """
    Makes a signed SP-API request and returns the parsed JSON response.

    This is the internal helper used by all public functions below.
    It handles LWA token fetching, SigV4 signing, and error translation.

    Parameters
    ----------
    method : str
        "GET" or "POST".
    path : str
        SP-API path, e.g. "/reports/2021-06-30/reports".
    body : dict
        JSON body for POST requests (None for GET).
    params : dict
        URL query parameters for GET requests.
    """
    region = os.getenv("AWS_REGION", "us-east-1")
    access_token = get_access_token()

    payload_bytes = json.dumps(body).encode("utf-8") if body else b""
    content_type = "application/json" if body else ""

    headers = {"x-amz-access-token": access_token}
    if content_type:
        headers["Content-Type"] = content_type

    # Build full URL with query string
    from urllib.parse import urlencode
    url = SP_ENDPOINT + path
    if params:
        url += "?" + urlencode(params)

    # Sign the request (adds Authorization + x-amz-date + host headers)
    headers = _sign_request(
        method=method,
        url=url,
        headers=headers,
        payload=payload_bytes,
        region=region,
        service=AWS_SERVICE,
    )

    response = requests.request(
        method=method,
        url=url,
        headers=headers,
        data=payload_bytes if payload_bytes else None,
        timeout=60,
    )

    if not response.ok:
        raise RuntimeError(
            f"SP-API {method} {path} failed: "
            f"HTTP {response.status_code} — {response.text[:500]}"
        )

    return response.json()


# ── Reports API — public functions ────────────────────────────────────────────

def create_search_terms_report(
    data_start_date: str,
    data_end_date: str,
    report_period: str = "MONTH",
) -> str:
    """
    Requests a new Brand Analytics Search Terms report from SP-API.

    The report covers a date range and is built asynchronously. This call
    returns a reportId immediately; you then poll get_report_status() until
    the report is ready.

    Parameters
    ----------
    data_start_date : str
        ISO 8601 date string, e.g. "2026-05-01T00:00:00Z"
    data_end_date : str
        ISO 8601 date string, e.g. "2026-05-31T23:59:59Z"
    report_period : str
        "MONTH", "WEEK", or "DAY". Controls how the data is aggregated.
        MONTH is cheapest and most useful for weekly ingestion.

    Returns
    -------
    str
        The reportId to pass to get_report_status().
    """
    marketplace_id = _get_env("SP_API_MARKETPLACE_ID")

    result = _sp_api_request(
        method="POST",
        path="/reports/2021-06-30/reports",
        body={
            "reportType": "GET_BRAND_ANALYTICS_SEARCH_TERMS_REPORT",
            "dataStartTime": data_start_date,
            "dataEndTime": data_end_date,
            "reportOptions": {"reportPeriod": report_period},
            "marketplaceIds": [marketplace_id],
        },
    )

    return result["reportId"]


def get_report_status(report_id: str) -> dict:
    """
    Polls the status of a previously requested report.

    Call this in a loop (with a sleep between calls) until
    processingStatus is "DONE", "CANCELLED", or "FATAL".

    Returns
    -------
    dict with keys:
        processingStatus : str
            "IN_QUEUE", "IN_PROGRESS", "DONE", "CANCELLED", "FATAL"
        reportDocumentId : str | None
            Present only when processingStatus == "DONE".
            Pass this to get_report_document_url().
        dataStartTime, dataEndTime, reportType, etc.
    """
    return _sp_api_request("GET", f"/reports/2021-06-30/reports/{report_id}")


def get_report_document_url(report_document_id: str) -> tuple[str, bool]:
    """
    Retrieves the pre-signed S3 download URL for a completed report.

    Parameters
    ----------
    report_document_id : str
        The reportDocumentId from get_report_status().

    Returns
    -------
    (url, is_gzip) : (str, bool)
        url     — pre-signed S3 URL, valid for a short time (~5 min).
        is_gzip — True if the file must be decompressed before parsing.
    """
    result = _sp_api_request(
        "GET", f"/reports/2021-06-30/documents/{report_document_id}"
    )
    url = result["url"]
    is_gzip = result.get("compressionAlgorithm", "").upper() == "GZIP"
    return url, is_gzip


def download_and_decompress(url: str, is_gzip: bool) -> str:
    """
    Downloads the report file and returns its content as a UTF-8 string.

    The S3 URL is pre-signed — no auth headers needed for this request.

    Parameters
    ----------
    url : str
        Pre-signed S3 URL from get_report_document_url().
    is_gzip : bool
        If True, the response body is gzip-compressed and must be decompressed.

    Returns
    -------
    str
        The raw TSV text of the report, ready for parsing.
    """
    response = requests.get(url, timeout=120)
    response.raise_for_status()

    raw_bytes = response.content

    if is_gzip:
        with gzip.open(io.BytesIO(raw_bytes), "rt", encoding="utf-8") as f:
            return f.read()

    return raw_bytes.decode("utf-8")
