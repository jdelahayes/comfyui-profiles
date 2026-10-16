"""Ajout à un fichier de profils de profils pris dans un autre (ex. la source déclarée par le
node « Workflow profiles » d'un workflow), avec les profils dont ils héritent.

Rien n'est remplacé : un profil déjà présent est gardé tel quel (signalé s'il diffère de la
source). Les profils ajoutés sont insérés à la fin de l'objet "profiles", sans toucher à la mise
en forme du reste du fichier ; si l'insertion ne donne pas exactement le résultat attendu,
le fichier est réécrit entièrement (JSON indenté).
"""
import json
import re


def untranslated(message, **values):
    return message.format(**values)


class MergeError(ValueError):
    pass


def profiles_of(text, what, _):
    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise MergeError(_("{what} : JSON invalide ({error})", what=what, error=e))
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict):
        raise MergeError(_("{what} : objet 'profiles' manquant", what=what))
    return data, profiles


def with_extends(profiles, names, _):
    """`names` et les profils dont ils héritent, dans `profiles` (chacun une fois)."""
    found = []

    def visit(name):
        if name in found:
            return
        if name not in profiles:
            raise MergeError(_("Profil absent de la source : '{name}'", name=name))
        found.append(name)
        for parent in profiles[name].get("extends", []):
            visit(parent)

    for name in names:
        visit(name)
    return found


def format_profile(name, profile, indent):
    """Un profil dans le style des fichiers d'exemple : un élément de liste par ligne."""
    pad, inner = " " * indent, " " * (indent + 2)
    fields = []
    for key, value in profile.items():
        head = f"{inner}{json.dumps(key, ensure_ascii=False)}: "
        if isinstance(value, list) and any(isinstance(v, dict) for v in value):
            items = ",\n".join(f"{inner}  {json.dumps(v, ensure_ascii=False)}" for v in value)
            fields.append(f"{head}[\n{items}\n{inner}]")
        else:
            fields.append(head + json.dumps(value, ensure_ascii=False))
    body = ",\n".join(fields)
    return f"{pad}{json.dumps(name, ensure_ascii=False)}: {{\n{body}\n{pad}}}"


def insert(text, data, current, added):
    """`text` avec les profils `added` ajoutés à la fin de "profiles" ; None si l'insertion
    ne retombe pas exactement sur le contenu attendu."""
    expected = {**data, "profiles": {**current, **added}}
    first = next(iter(current), None)
    match = first and re.search(r"\n([ \t]+)" + re.escape(json.dumps(first, ensure_ascii=False)) + r"\s*:", text)
    indent = len(match.group(1).expandtabs(2)) if match else 4
    entries = ",\n\n".join(format_profile(n, p, indent) for n, p in added.items())
    # Fin de l'objet "profiles" : l'une des dernières accolades fermantes (il est en général
    # la dernière clé du fichier) ; la vérification écarte les mauvaises.
    closing = [m.start() for m in re.finditer(r"\}", text)][-3:]
    for pos in reversed(closing):
        before = text[:pos].rstrip()
        sep = "" if before.endswith("{") else ","
        candidate = f"{before}{sep}\n\n{entries}\n{' ' * max(indent - 2, 0)}{text[pos:]}"
        try:
            if json.loads(candidate) == expected:
                return candidate
        except json.JSONDecodeError:
            pass
    return None


def merge(current_text, source_text, names, _=untranslated):
    """(nouveau texte, {"added", "same", "conflicts"}) : ajoute à `current_text` les profils
    `names` de `source_text` et ceux dont ils héritent, s'ils n'y sont pas déjà."""
    data, current = profiles_of(current_text, _("fichier de profils"), _)
    source = profiles_of(source_text, _("source"), _)[1]
    result = {"added": [], "same": [], "conflicts": []}
    for name in with_extends(source, names, _):
        if name not in current:
            result["added"].append(name)
        else:
            result["same" if current[name] == source[name] else "conflicts"].append(name)
    if not result["added"]:
        return current_text, result
    added = {n: source[n] for n in result["added"]}
    text = insert(current_text, data, current, added)
    if text is None:
        text = json.dumps({**data, "profiles": {**current, **added}}, indent=2, ensure_ascii=False) + "\n"
    return text, result
