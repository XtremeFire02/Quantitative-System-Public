"""
API key authentication dependency for write endpoints.

Usage:
    from app.middleware.auth import require_api_key
    from fastapi import Depends

    @router.post("/some/endpoint", dependencies=[Depends(require_api_key)])
    def my_endpoint(): ...

Behaviour:
- If API_KEY is not set (empty string), auth is disabled — useful for local dev.
- If API_KEY is set, the request must include the header: X-Api-Key: <key>
- Returns HTTP 403 on missing or incorrect key.
"""
from fastapi import Header, HTTPException

from app.config import API_KEY


def require_api_key(x_api_key: str = Header(default="")) -> None:
    if not API_KEY:
        return  # dev mode: auth disabled
    if x_api_key != API_KEY:
        raise HTTPException(status_code=403, detail="Invalid or missing X-Api-Key header")
