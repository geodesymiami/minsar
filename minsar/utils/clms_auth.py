"""CLMS (Copernicus Land Monitoring Service) OAuth2 JWT bearer authentication.

Service key JSON (from land.copernicus.eu profile → API Tokens) contains
``private_key``, ``client_id``, ``user_id``, and ``token_uri``. A short-lived
JWT grant is signed and exchanged at ``token_uri`` for a Bearer ``access_token``
(typically valid ~1 hour). The grant itself also expires after ~1 hour; rebuild
it with fresh ``iat``/``exp`` when refreshing.
"""

from __future__ import annotations

import importlib.util
import json
import os
import time
from pathlib import Path
from typing import Any


def default_clms_service_key_path() -> Path:
    """Standard location for the CLMS service key JSON file."""
    return Path.home() / "accounts" / "clms_service_key.json"


def load_clms_service_key_path() -> Path:
    """Return CLMS service key path from password_config or ~/accounts/clms_service_key.json."""
    ssara = os.getenv("SSARAHOME")
    search_dirs: list[Path] = []
    if ssara:
        search_dirs.append(Path(ssara))
    search_dirs.append(Path.home() / "accounts")
    minsar_home = os.getenv("MINSAR_HOME")
    if minsar_home:
        search_dirs.append(Path(minsar_home) / "tools" / "ssara_client")
        search_dirs.append(Path(minsar_home) / "minsar" / "utils" / "ssara_ASF")
    here = Path(__file__).resolve()
    repo = here.parents[2]
    search_dirs.extend([repo / "tools" / "ssara_client", repo / "minsar" / "utils" / "ssara_ASF"])

    seen: set[Path] = set()
    last_err: Exception | None = None
    for d in search_dirs:
        d = d.resolve() if d.exists() else d
        if d in seen:
            continue
        seen.add(d)
        cfg = d / "password_config.py"
        if not cfg.is_file():
            continue
        try:
            spec = importlib.util.spec_from_file_location("_minsar_password_config_clms", cfg)
            if spec is None or spec.loader is None:
                continue
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            key_path = getattr(mod, "clms_service_key", None)
            if not key_path:
                last_err = AttributeError(f"{cfg} has no clms_service_key=...")
                continue
            path = Path(os.path.expanduser(str(key_path))).expanduser()
            if not path.is_file():
                raise FileNotFoundError(f"clms_service_key file not found: {path}")
            return path
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            continue

    default_path = default_clms_service_key_path()
    if default_path.is_file():
        return default_path

    msg = (
        "Could not load CLMS service key. Set clms_service_key in password_config.py, "
        f"place the key at {default_path}, or pass --service-key PATH."
    )
    if last_err:
        raise RuntimeError(f"{msg} Last error: {last_err}") from last_err
    raise RuntimeError(msg)


def resolve_clms_service_key_path(service_key: str | Path | None = None) -> Path:
    """Return CLMS service key path from CLI override, password_config, or default file."""
    if service_key:
        path = Path(os.path.expanduser(str(service_key))).expanduser()
        if not path.is_file():
            raise FileNotFoundError(f"Service key not found: {path}")
        return path
    return load_clms_service_key_path()


def load_service_key(service_key_path: Path | str) -> dict[str, Any]:
    """Load and validate CLMS service key JSON."""
    path = Path(service_key_path)
    with path.open("rb") as f:
        service_key = json.load(f)
    for key in ("private_key", "client_id", "user_id", "token_uri"):
        if key not in service_key:
            raise ValueError(f"Service key missing '{key}': {path}")
    return service_key


def build_jwt_grant(service_key: dict[str, Any], *, lifetime_s: int = 3600) -> str:
    """Sign a JWT assertion for CLMS jwt-bearer grant exchange."""
    try:
        import jwt  # PyJWT
    except ImportError as exc:
        raise RuntimeError("PyJWT is required for CLMS auth. Install with: pip install PyJWT") from exc

    private_key = service_key["private_key"].encode("utf-8")
    now = int(time.time())
    claim_set = {
        "iss": service_key["client_id"],
        "sub": service_key["user_id"],
        "aud": service_key["token_uri"],
        "iat": now,
        "exp": now + lifetime_s,
    }
    return jwt.encode(claim_set, private_key, algorithm="RS256")


def request_token_response(service_key_path: Path | str, *, grant_lifetime_s: int = 3600) -> dict[str, Any]:
    """Exchange service key for OAuth token response (access_token, expires_in, ...)."""
    import requests

    service_key = load_service_key(service_key_path)
    grant = build_jwt_grant(service_key, lifetime_s=grant_lifetime_s)
    result = requests.post(
        service_key["token_uri"],
        headers={"Accept": "application/json", "Content-Type": "application/x-www-form-urlencoded"},
        data={"grant_type": "urn:ietf:params:oauth:grant-type:jwt-bearer", "assertion": grant},
        timeout=60,
    )
    if not result.ok:
        detail = result.text[:500]
        raise RuntimeError(f"CLMS token request failed ({result.status_code}): {detail}")
    data = result.json()
    if not data.get("access_token"):
        raise RuntimeError(f"No access_token in OAuth response: {result.text[:500]}")
    return data


def get_access_token(service_key_path: Path | str) -> str:
    """Exchange CLMS service key JSON for a short-lived Bearer access token."""
    return str(request_token_response(service_key_path)["access_token"])


def auth_headers(access_token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {access_token}", "Accept": "application/json"}
