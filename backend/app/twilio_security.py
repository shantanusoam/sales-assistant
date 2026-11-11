"""Twilio webhook request authentication (X-Twilio-Signature).

Twilio signs every webhook request with HMAC-SHA1 over the full request URL
(including its query string) followed by each POST parameter sorted alphabetically.
Validating this on /api/twilio/twiml stops anyone who discovers the URL from
spinning up media streams on our Twilio account and burning STT credits.
"""
from __future__ import annotations

import base64
import hashlib
import hmac


def validate_twilio_signature(auth_token: str, url: str, params: dict[str, str], signature: str) -> bool:
    if not auth_token or not signature:
        return False
    mac = hmac.new(auth_token.encode("utf-8"), url.encode("utf-8"), hashlib.sha1)
    for key in sorted(params or {}):
        mac.update(f"{key}{params[key]}".encode("utf-8"))
    expected = base64.b64encode(mac.digest()).decode("ascii")
    return hmac.compare_digest(expected, signature)
