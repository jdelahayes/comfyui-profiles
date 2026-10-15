"""Traductions des messages du gestionnaire de profils (script, serveur et panneau).

Les messages sont écrits en français dans le code et servent eux-mêmes de clés : une langue
est un fichier lang/<code>.json qui associe chaque message français à sa traduction (voir
lang/en.json). Un message absent du fichier reste en français. Les variables s'écrivent
{nom} dans le message et sont passées en arguments nommés : t("{n} élément(s)", n=3).

Langue : $COMFY_PROFILES_LANG (que le panneau règle sur la langue de ComfyUI), sinon
$LC_ALL, $LC_MESSAGES ou $LANG ; anglais par défaut, et pour une langue sans fichier.
"""
import json
import os
import re
from pathlib import Path

LANG_DIR = Path(__file__).resolve().parent / "lang"
SOURCE_LANG = "fr"
DEFAULT_LANG = "en"


def available():
    """Codes des langues disponibles (la langue des sources comprise)."""
    return sorted({SOURCE_LANG, *(p.stem for p in LANG_DIR.glob("*.json"))})


def normalize(value):
    """Code de langue pris en charge pour « fr_FR.UTF-8 », « en-US », « zh »... ; None si
    `value` ne désigne pas de langue (vide, C, POSIX)."""
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
    """{message français: traduction} de la langue `lang` (vide pour le français)."""
    if lang not in _catalogs:
        path = LANG_DIR / f"{lang}.json"
        try:
            data = json.loads(path.read_text(encoding="utf-8")) if lang != SOURCE_LANG else {}
        except (OSError, json.JSONDecodeError):
            data = {}
        _catalogs[lang] = {k: v for k, v in data.items() if isinstance(v, str) and v}
    return _catalogs[lang]


def fill(text, values):
    """Remplace les {nom} connus ; laisse le reste (accolades d'un JSON...) tel quel."""
    if not values:
        return text
    return re.sub(r"\{(\w+)\}",
                  lambda m: str(values[m.group(1)]) if m.group(1) in values else m.group(0), text)


def translator(lang):
    """Fonction de traduction pour une langue donnée (ex. celle du panneau qui fait la requête)."""
    messages = catalog(lang)

    def translate(message, **values):
        return fill(messages.get(message, message), values)

    translate.lang = lang
    return translate


t = translator(detect())


def doc(text, key, translate=None):
    """Aide d'un script (son docstring) : traduite en entier sous la clé « __doc__:<key> »."""
    translated = (translate or t)(f"__doc__:{key}")
    return text if translated == f"__doc__:{key}" else translated


def human_size(size, translate=None):
    """« 20,9 Go » en français, « 20.9 GB » en anglais."""
    translate = translate or t
    for unit, factor in (("To", 1e12), ("Go", 1e9), ("Mo", 1e6), ("Ko", 1e3)):
        if size >= factor:
            number = f"{size / factor:.1f}".replace(".", translate(","))
            return f"{number} {translate(unit)}"
    return f"{size} {translate('o')}"
