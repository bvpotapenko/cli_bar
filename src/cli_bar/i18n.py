"""CLI-local i18n: t(), available_languages(), set_language().

Locale files: src/cli_bar/locales/{lang}.yaml
Key format: flat dotted keys ("menu.show_plan")
Values: str.format_map() placeholders ({name}), Rich markup embedded.
Fallback: current lang → en → key itself.
"""
from __future__ import annotations

from pathlib import Path

_current_lang: str = "en"
_catalogs: dict[str, dict] = {}


def _locales_dir() -> Path:
    return Path(__file__).parent / "locales"


def _load_catalog(lang: str) -> dict:
    if lang not in _catalogs:
        path = _locales_dir() / f"{lang}.yaml"
        if path.exists():
            try:
                import yaml

                with open(path, encoding="utf-8") as fh:
                    _catalogs[lang] = yaml.safe_load(fh) or {}
            except Exception:
                _catalogs[lang] = {}
        else:
            _catalogs[lang] = {}
    return _catalogs[lang]


def available_languages() -> list[str]:
    """Return sorted list of language codes discovered from locales/ dir."""
    langs = sorted(p.stem for p in _locales_dir().glob("*.yaml"))
    return langs if langs else ["en"]


def set_language(lang: str) -> None:
    global _current_lang
    _current_lang = lang if lang in available_languages() else "en"


def t(key: str, **kwargs: object) -> str:
    """Translate key with optional format placeholders."""
    catalog = _load_catalog(_current_lang)
    value = catalog.get(key)
    if value is None and _current_lang != "en":
        value = _load_catalog("en").get(key)
    if value is None:
        return key
    if kwargs:
        try:
            return str(value).format_map(kwargs)
        except (KeyError, ValueError):
            return str(value)
    return str(value)
