import hashlib
import hmac
import json
import secrets

def generate_api_key()->str:
    return f"rk_live_{secrets.token_hex(16)}"

def generate_signing_secret()->str:
    return f"whsec_{secrets.token_hex(24)}"

def sign_webhook_payload(secret_key:str, timestamp:int, payload:dict)->str:
    canonical_body = json.dumps(payload, separators=(",", ":"), sort_keys=True)
    signed_content = f"{timestamp}.{canonical_body}".encode("utf-8")

    digest = hmac.new(
        key=secret_key.encode("utf-8"),
        msg=signed_content,
        digestmod=hashlib.sha256,
    ).hexdigest()

    return f"t={timestamp},v1={digest}"