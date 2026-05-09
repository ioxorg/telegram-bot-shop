from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)

_LOCALES_DIR = Path(__file__).parent.parent / "locales"
_SUPPORTED = ("en", "fa")
_cache: dict[str, dict[str, str]] = {}


def _load_locale(lang: str) -> dict[str, str]:
    path = _LOCALES_DIR / f"{lang}.cfg"
    strings: dict[str, str] = {}
    with open(path, encoding="utf-8") as f:
        for raw_line in f:
            line = raw_line.strip()
            if not line or line.startswith("#"):
                continue
            if "=" not in line:
                continue
            key, _, value = line.partition("=")
            strings[key.strip()] = value.strip().replace("\\n", "\n")
    return strings


def _load_all() -> None:
    for lang in _SUPPORTED:
        try:
            _cache[lang] = _load_locale(lang)
            logger.debug("Loaded locale %s (%d keys)", lang, len(_cache[lang]))
        except FileNotFoundError:
            logger.warning("Locale file missing: locales/%s.cfg", lang)
            _cache[lang] = {}


_load_all()


def t(key: str, lang: str, **kwargs) -> str:
    text = _cache.get(lang, {}).get(key) or _cache.get("en", {}).get(key, key)
    return text.format(**kwargs) if kwargs else text
