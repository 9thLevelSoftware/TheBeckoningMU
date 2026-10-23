"""Build the static site's public routing value from Django deployment settings."""

import ipaddress
import json
import re
from pathlib import Path
from urllib.parse import urlsplit

DEFAULT_CONFIG_PATH = Path(__file__).resolve().parent / "VampSite" / "assets" / "js" / "site-config.js"
_HOST_LABEL = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\Z", re.IGNORECASE)
_INVALID_ORIGIN = "PUBLIC_GAME_BASE_URL must be an HTTPS origin, or HTTP localhost/127.0.0.1/[::1], without credentials, path, query or fragment."


def public_game_origin(value):
    """Return a canonical origin or an empty, unavailable configuration."""
    if not isinstance(value, str) or any(ord(char) < 32 or ord(char) == 127 or char == "\\" for char in value):
        raise ValueError(_INVALID_ORIGIN)
    raw = value.strip()
    if not raw:
        return ""
    try:
        parsed = urlsplit(raw)
        port = parsed.port
        hostname = parsed.hostname
        if (
            not hostname
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path not in ("", "/")
            or "?" in raw
            or "#" in raw
            or any(char.isspace() for char in raw)
        ):
            raise ValueError(_INVALID_ORIGIN)
        if ":" in hostname:
            if not re.fullmatch(r"\[[0-9a-fA-F:.]+\](?::[0-9]+)?", parsed.netloc):
                raise ValueError(_INVALID_ORIGIN)
            hostname = str(ipaddress.IPv6Address(hostname))
            host = f"[{hostname}]"
        else:
            hostname = hostname.encode("idna").decode("ascii").lower()
            labels = hostname.rstrip(".").split(".")
            if len(hostname) > 253 or any(not _HOST_LABEL.fullmatch(label) for label in labels):
                raise ValueError(_INVALID_ORIGIN)
            if labels[-1].isdigit():
                hostname = str(ipaddress.IPv4Address(hostname))
            elif re.fullmatch(r"0x[0-9a-f]+", labels[-1], re.IGNORECASE):
                raise ValueError(_INVALID_ORIGIN)
            host = hostname
        scheme = parsed.scheme.lower()
        if scheme != "https" and not (scheme == "http" and hostname in {"localhost", "127.0.0.1", "::1"}):
            raise ValueError(_INVALID_ORIGIN)
        if parsed.netloc.endswith(":"):
            raise ValueError(_INVALID_ORIGIN)
    except (ValueError, UnicodeError) as error:
        raise ValueError(_INVALID_ORIGIN) from error
    default_port = 443 if scheme == "https" else 80
    suffix = f":{port}" if port is not None and port != default_port else ""
    return f"{scheme}://{host}{suffix}"


def render_public_config(value):
    origin = public_game_origin(value)
    # JSON string syntax is valid JavaScript; escape HTML delimiters as well so
    # this public asset remains safe if a deployment later embeds it in HTML.
    literal = (
        json.dumps(origin, ensure_ascii=True).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    )
    return (
        "// Generated from Django PUBLIC_GAME_BASE_URL; empty keeps chargen unavailable.\n"
        + f"window.PUBLIC_GAME_BASE_URL = {literal};\n"
    )
