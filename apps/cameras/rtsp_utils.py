from urllib.parse import quote, urlsplit, urlunsplit


def build_authenticated_rtsp_url(rtsp_url: str, username: str = "", password: str = "") -> str:
    raw = (rtsp_url or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if parsed.scheme.lower() not in {"rtsp", "rtsps"}:
        return raw

    if parsed.username is not None:
        return raw

    username = "" if username is None else str(username)
    password = "" if password is None else str(password)
    if not username:
        return raw

    auth = quote(username, safe="")
    if password:
        auth += ":" + quote(password, safe="")

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"

    return urlunsplit(
        (
            parsed.scheme,
            f"{auth}@{host}",
            parsed.path,
            parsed.query,
            parsed.fragment,
        )
    )


def camera_rtsp_url(camera) -> str:
    return build_authenticated_rtsp_url(
        getattr(camera, "rtsp_url", ""),
        getattr(camera, "username", ""),
        getattr(camera, "password", ""),
    )


def safe_rtsp_url(rtsp_url: str) -> str:
    raw = (rtsp_url or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if parsed.username is None:
        return raw

    host = parsed.hostname or ""
    if ":" in host and not host.startswith("["):
        host = f"[{host}]"
    if parsed.port is not None:
        host = f"{host}:{parsed.port}"

    return urlunsplit(
        (parsed.scheme, host, parsed.path, parsed.query, parsed.fragment)
    )
