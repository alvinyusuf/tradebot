"""Read only explicitly named Demo credentials without logging their values."""

from os import environ
from pathlib import Path

_NAMES = ("BINANCE_DEMO_API_KEY", "BINANCE_DEMO_API_SECRET")


def demo_credentials(env_file: Path | None = None) -> tuple[str, str]:
    values = {}
    if env_file is not None:
        for line in env_file.read_text(encoding="utf-8-sig").splitlines():
            name, separator, value = line.partition("=")
            name = name.strip().removeprefix("export ").strip()
            if not separator or name not in _NAMES:
                continue
            if name in values:
                raise ValueError(f"Variabel Demo duplikat: {name}")
            value = value.strip()
            if value.startswith(("'", '"')):
                if len(value) < 2 or not value.endswith(value[0]):
                    raise ValueError(
                        f"Kutipan pada variabel Demo tidak lengkap: {name}"
                    )
                value = value[1:-1]
            values[name] = value
    key, secret = (environ.get(name, values.get(name, "")).strip() for name in _NAMES)
    if not key or not secret or key.startswith("#") or secret.startswith("#"):
        raise ValueError(
            "BINANCE_DEMO_API_KEY dan BINANCE_DEMO_API_SECRET belum tersedia"
        )
    return key, secret
