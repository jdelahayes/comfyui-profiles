"""Adds to a profiles file some profiles taken from another one (e.g. the source declared by a
workflow's "Workflow profiles" node), along with the profiles they inherit from.

Nothing is replaced: a profile already there is kept as is (reported if it differs from the
source). Added profiles are inserted at the end of the "profiles" object, without touching the
formatting of the rest of the file; if the insertion does not give exactly the expected result,
the whole file is rewritten (indented JSON).
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
        raise MergeError(_("{what}: invalid JSON ({error})", what=what, error=e))
    profiles = data.get("profiles") if isinstance(data, dict) else None
    if not isinstance(profiles, dict):
        raise MergeError(_("{what}: 'profiles' object missing", what=what))
    return data, profiles


def with_extends(profiles, names, _):
    """`names` and the profiles they inherit from, in `profiles` (each one once). A profile
    with variants comes whole, whatever variants are asked (krea2-raw[int8] -> krea2-raw)."""
    found = []

    def visit(name):
        name = name.split("[", 1)[0].strip()
        if name in found:
            return
        if name not in profiles:
            raise MergeError(_("Profile not in the source: '{name}'", name=name))
        found.append(name)
        for parent in profiles[name].get("extends", []):
            visit(parent)

    for name in names:
        visit(name)
    return found


def format_profile(name, profile, indent):
    """A profile in the style of the example files: one list item per line."""
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
    """`text` with the `added` profiles added at the end of "profiles"; None if the insertion
    does not give exactly the expected content."""
    expected = {**data, "profiles": {**current, **added}}
    first = next(iter(current), None)
    match = first and re.search(r"\n([ \t]+)" + re.escape(json.dumps(first, ensure_ascii=False)) + r"\s*:", text)
    indent = len(match.group(1).expandtabs(2)) if match else 4
    entries = ",\n\n".join(format_profile(n, p, indent) for n, p in added.items())
    # End of the "profiles" object: one of the last closing braces (it is usually the last key
    # of the file); the check rules out the wrong ones.
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
    """(new text, {"added", "same", "conflicts"}): adds to `current_text` the `names` profiles
    of `source_text` and those they inherit from, if they are not already there."""
    data, current = profiles_of(current_text, _("profiles file"), _)
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
