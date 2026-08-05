import hmac

from fastapi import HTTPException, Request, status

from app.config import Settings


def validate_api_key(request: Request, settings: Settings) -> None:
    if settings.allow_insecure or settings.testing:
        return
    supplied = request.query_params.get("apikey", "")
    expected = settings.bridge_api_key.get_secret_value()
    if not supplied or not hmac.compare_digest(supplied, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="API key inválida")


def valid_login(username: str, password: str, settings: Settings) -> bool:
    if settings.allow_insecure or settings.testing:
        return True
    return hmac.compare_digest(username, settings.bridge_username) and hmac.compare_digest(
        password, settings.bridge_password.get_secret_value()
    )
