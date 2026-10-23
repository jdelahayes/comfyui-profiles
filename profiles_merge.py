"""Adds to a profiles file some profiles taken from another one (e.g. the source declared by a
workflow's "Workflow profiles" node), along with the profiles they inherit from.

Nothing is replaced: a profile already there is kept as is (reported if it differs from the
source). Added profiles are inserted at the end of the "profiles" object, without touching the
formatting of the rest of the file; if the insertion does not give exactly the expected result,
the whole file is rewritten (indented JSON).

compare() and update(): import from a URL in "merge" mode. compare() lists the profiles of the
remote file that are new or different (item by item), update() adds or replaces those chosen.
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


# --- Comparison with a remote file and partial update ------------------------------------

SECTIONS = ("custom_nodes", "pip", "models", "workflows")


def item_label(item):
    """What identifies an item in a section: its source (and its variant), not its size or ref."""
    if not isinstance(item, dict):
        return str(item)
    if "git" in item:
        source = item["git"]
    elif "hf" in item or "github" in item:
        repo = "hf" if "hf" in item else "github"
        source = f"{repo}:{item[repo]}/{item.get('file', '')}"
    elif "civitai" in item:
        source = f"civitai:{item['civitai']}"
    else:
        source = item.get("url") or item.get("gdrive") or item.get("name") or json.dumps(item, sort_keys=True)
    return f"[{item['variant']}] {source}" if item.get("variant") else source


def profile_diff(local, remote):
    """{"fields": [other keys that differ], "sections": {section: {"added", "removed",
    "changed"}}}: what taking the `remote` version of a profile changes."""
    local, remote = (p if isinstance(p, dict) else {} for p in (local, remote))
    sections = {}
    for section in SECTIONS:
        before = {item_label(i): i for i in local.get(section) or []}
        after = {item_label(i): i for i in remote.get(section) or []}
        diff = {"added": [l for l in after if l not in before],
                "removed": [l for l in before if l not in after],
                "changed": [l for l in after if l in before and after[l] != before[l]]}
        if any(diff.values()):
            sections[section] = diff
    fields = [k for k in dict.fromkeys([*local, *remote])
              if k not in SECTIONS and local.get(k) != remote.get(k)]
    return {"fields": fields, "sections": sections}


def compare(current_text, source_text, _=untranslated):
    """Profiles of `source_text` new, different, identical, and those only in `current_text`."""
    data, current = profiles_of(current_text, _("profiles file"), _)
    source_data, source = profiles_of(source_text, _("source"), _)
    result = {"added": [], "changed": [], "same": [], "removed": [],
              "other_keys": [k for k in dict.fromkeys([*data, *source_data])
                             if k != "profiles" and data.get(k) != source_data.get(k)]}
    for name, profile in source.items():
        if name not in current:
            description = profile.get("description") if isinstance(profile, dict) else None
            result["added"].append({"name": name, "description": description,
                                    "diff": profile_diff({}, profile)})
        elif current[name] == profile:
            result["same"].append(name)
        else:
            result["changed"].append({"name": name, "diff": profile_diff(current[name], profile)})
    result["removed"] = [name for name in current if name not in source]
    return result


def format_file(data):
    """The whole file in the style of the example files (one profile item per line)."""
    lines = []
    for key, value in data.items():
        if key == "profiles":
            body = ",\n\n".join(format_profile(n, p, 4) for n, p in value.items())
            lines.append(f'  "profiles": {{\n{body}\n  }}' if body else '  "profiles": {}')
        else:
            lines.append(f"  {json.dumps(key, ensure_ascii=False)}: {json.dumps(value, ensure_ascii=False)}")
    return "{\n" + ",\n".join(lines) + "\n}\n"


def update(current_text, source_text, names, _=untranslated):
    """(new text, {"added", "replaced", "inherited"}): `current_text` with the `names` profiles
    of `source_text`, added or replacing the local version, plus the profiles they inherit from
    that are missing locally (added, the local ones are never replaced for them)."""
    data, current = profiles_of(current_text, _("profiles file"), _)
    source = profiles_of(source_text, _("source"), _)[1]
    wanted = list(dict.fromkeys(names))
    for name in wanted:
        if name not in source:
            raise MergeError(_("Profile not in the source: '{name}'", name=name))
    inherited = [n for n in with_extends(source, wanted, _) if n not in wanted and n not in current]
    result = {"added": [n for n in wanted if n not in current],
              "replaced": [n for n in wanted if n in current and current[n] != source[n]],
              "inherited": inherited}
    changes = [*result["added"], *result["replaced"], *inherited]
    if not changes:
        return current_text, result
    profiles = {**current, **{n: source[n] for n in changes}}
    text = None
    if not result["replaced"]:  # additions only: the rest of the file keeps its formatting
        text = insert(current_text, data, current, {n: source[n] for n in changes})
    if text is None:
        text = format_file({**data, "profiles": profiles})
    return text, result
