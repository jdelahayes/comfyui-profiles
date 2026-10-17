"""Translations of the profile manager's messages (script, server and panel).

Messages are written in English in the code and are their own keys: a language is a
lang/<code>.json file that maps each English message to its translation (see lang/fr.json).
A message missing from the file stays in English. Variables are written {name} in the
message and passed as keyword arguments: t("{n} item(s)", n=3).

Language: $COMFY_PROFILES_LANG (which the panel sets to ComfyUI's language), otherwise
$LC_ALL, $LC_MESSAGES or $LANG; English by default, and for a language without a file.
"""
import json
import os
import re
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parent / "lang"
SOURCE_LANG = "en"
DEFAULT_LANG = "en"


def available():
    """Codes of the available languages (the source language included)."""
    return sorted({SOURCE_LANG, *(p.stem for p in LANG_DIR.glob("*.json"))})


def normalize(value):
    """Supported language code for "fr_FR.UTF-8", "en-US", "zh"...; None if `value` names no
    language (empty, C, POSIX)."""
    code = re.split(r"[_.@-]", (value or "").strip().lower(), maxsplit=1)[0]
    if code in ("", "c", "posix"):
        return None
    return code if code in available() else DEFAULT_LANG


def detect():
    for var in ("COMFY_PROFILES_LANG", "LC_ALL", "LC_MESSAGES", "LANG"):
        code = normalize(os.environ.get(var))
        if code:
            return code
    return DEFAULT_LANG


_catalogs = {}


def catalog(lang):
    """{English message: translation} for language `lang` (empty for English)."""
    if lang not in _catalogs:
        path = LANG_DIR / f"{lang}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if lang != SOURCE_LANG else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        _catalogs[lang] = {k: v for k, v in data.items() if isinstance(v, str) and v}
    return _catalogs[lang]


def fill(text, values):
    """Replaces the known {name}s; leaves the rest (braces of some JSON...) as is."""
    if not values:
        return text
    return re.sub(r"\{(\w+)\}",
                  lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def translator(lang):
    """Translation function for a given language (e.g. that of the panel making the request)."""
    messages = catalog(lang)

    def translate(message, **values):
        return fill(messages.get(message, message), values)

    translate.lang = lang
    return translate


t = translator(detect())


def doc(text, key, translate=None):
    """Help of a script (its docstring): translated as a whole under the key "__doc__:<key>"."""
    translated = (translate or t)(f"__doc__:{key}")
    return text if translated == f"__doc__:{key}" else translated


def human_size(size, translate=None):
    """"20.9 GB" in English, "20,9 Go" in French."""
    translate = translate or t
    for unit, factor in (("TB", 1e12), ("GB", 1e9), ("MB", 1e6), ("KB", 1e3)):
        if size >= factor:
            number = f"{size / factor:.1f}".replace(".", translate("."))
            return f"{number} {translate(unit)}"
    return f"{size} {translate('B')}"
