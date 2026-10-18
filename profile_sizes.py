#!/usr/bin/env python3
"""Computes the size of usage profiles and saves it in the profiles file.

Queries the actual size of each file (models, workflows) at its source, without downloading
anything: Hugging Face API (paths-info), CivitAI API (model-versions), or the Content-Length
header for a direct URL or a file in a GitHub repository. Only files without "size" are
queried, unless --force queries them all again. Then writes in the config:
  - "size" (bytes) on each file;
  - "size" (human-readable, e.g. "89.4 GB") on each profile: total of its files, extends
    included, each file counted once; for a profile with variants, one per variant
    ({"int8": "18.9 GB", "bf16": "35.7 GB"}). Custom nodes and pip packages are not counted (a profile
    with only those has no size).

Usage:
  profile_sizes.py [--config FILE] [--env FILE] [--force] [--dry-run]

Config file: same rule as comfy_profiles.py (--config, $COMFY_PROFILES_CONFIG, the user's file,
the template). When it is the template (read-only), the result is written to the user's file
(<user>/__comfy_profiles/profiles.json), which then takes over.
Hugging Face token (gated repositories): $HF_TOKEN, otherwise the one in the --env file (a
deployment .env for instance), otherwise the one from `hf auth login`. CivitAI token:
$CIVITAI_TOKEN, otherwise the one in the --env file.
The file's layout (one file per line, blank lines between profiles) is preserved.
Also run by the “Recalculate sizes” button of the Profiles panel.
"""
import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

import comfy_profiles as cp
from profiles_i18n import doc, human_size, t

FILE_SECTIONS = ("models", "workflows")
TOKEN_KEYS = ("HF_TOKEN", "CIVITAI_TOKEN")


def load_env_tokens(env_file):
    """Takes the tokens from a .env file (outside the pod), without overriding the environment."""
    if not env_file:
        return
    env_file = Path(env_file)
    if not env_file.is_file():
        sys.exit("!! " + t("--env file not found: {path}", path=env_file))
    for line in env_file.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if sep and key in TOKEN_KEYS and value and not os.environ.get(key):
            os.environ[key] = value


# --- Sizes at the source -------------------------------------------------------------------

def http_json(url, data=None, token=None):
    headers = {"User-Agent": cp.USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data, doseq=True).encode() if data else None
    req = urllib.request.Request(url, data=body, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.load(resp)


def hf_token():
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    token_file = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "token"
    return token_file.read_text().strip() if token_file.is_file() else None


def hf_sizes(repo, revision, files):
    """Sizes of a batch of files from the same repository/revision, in one request."""
    url = (
        f"https://huggingface.co/api/models/{repo}/paths-info/"
        f"{urllib.parse.quote(revision or 'main', safe='')}"
    )
    entries = http_json(url, data={"paths": files}, token=hf_token())
    # A path that does not exist is simply missing from the response.
    return {e["path"]: (e.get("lfs") or {}).get("size", e.get("size")) for e in entries}


def civitai_size(version_id):
    """Size of the file served by /api/download/models/<id>: the primary file."""
    token = os.environ.get("CIVITAI_TOKEN")
    url = f"https://civitai.com/api/v1/model-versions/{version_id}"
    data = http_json(f"{url}?token={token}" if token else url)
    files = data.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary or primary.get("sizeKB") is None:
        raise LookupError(t("no file in this version"))
    return round(primary["sizeKB"] * 1024)


def url_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": cp.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        length = resp.headers.get("Content-Length")
    if length is None:
        raise LookupError(t("no Content-Length header"))
    return int(length)


def error_text(e):
    if isinstance(e, urllib.error.HTTPError):
        hint = " " + t("(gated/private repository: HF_TOKEN required, license accepted?)") if e.code in (401, 403) else ""
        return f"HTTP {e.code}{hint}"
    return str(e)


def fetch_sizes(items):
    """items: list of (where, item). Fills in item["size"], returns the failures."""
    failures = []
    hf_groups = {}
    for where, item in items:
        source = cp.source_of(item, where)
        if source == "hf":
            hf_groups.setdefault((item["hf"], item.get("revision")), []).append((where, item))
            continue
        try:
            if source == "civitai":
                item["size"] = civitai_size(item["civitai"])
            else:
                item["size"] = url_size(cp.github_file_url(item) if source == "github" else item["url"])
        except Exception as e:
            failures.append(f"{where} {cp.describe_source(item)} : {error_text(e)}")

    for (repo, revision), group in hf_groups.items():
        try:
            sizes = hf_sizes(repo, revision, sorted({item["file"] for _, item in group}))
        except Exception as e:
            failures += [f"{where} {cp.describe_source(item)} : {error_text(e)}" for where, item in group]
            continue
        for where, item in group:
            if sizes.get(item["file"]) is None:
                failures.append(f"{where} {cp.describe_source(item)} : " + t("file not found in the repository"))
            else:
                item["size"] = sizes[item["file"]]
    return failures


# --- Totaux par profil --------------------------------------------------------------------

def profile_size_text(total, unknown):
    text = human_size(total)
    return text + " " + t("+ {n} file(s) of unknown size", n=unknown) if unknown else text


# --- Writing (formatting kept) -----------------------------------------------------------

def dumps_inline(value):
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def format_config(data, blank_before):
    """Same style as profiles.json: one profile per block, one list item per line."""
    lines = ["{"]
    top = [k for k in data if k != "profiles"]
    for key in top:
        lines.append(f"  {json.dumps(key)}: {dumps_inline(data[key])},")
    lines.append('  "profiles": {')
    names = list(data["profiles"])
    for i, name in enumerate(names):
        if i and name in blank_before:
            lines.append("")
        lines.append(f"    {json.dumps(name, ensure_ascii=False)}: {{")
        profile = data["profiles"][name]
        keys = list(profile)
        for j, key in enumerate(keys):
            value = profile[key]
            comma = "," if j < len(keys) - 1 else ""
            if isinstance(value, list) and value and all(isinstance(v, dict) for v in value):
                lines.append(f"      {json.dumps(key)}: [")
                lines += [
                    f"        {dumps_inline(v)}{',' if k < len(value) - 1 else ''}"
                    for k, v in enumerate(value)
                ]
                lines.append(f"      ]{comma}")
            else:
                lines.append(f"      {json.dumps(key)}: {dumps_inline(value)}{comma}")
        lines.append(f"    }}{',' if i < len(names) - 1 else ''}")
    lines += ["  }", "}"]
    return "\n".join(lines) + "\n"


def with_profile_size(profile, size):
    """Puts "size" right after "description" (or first), replacing the previous value."""
    out = {}
    if "description" not in profile:
        out["size"] = size
    for key, value in profile.items():
        if key == "size":
            continue
        out[key] = value
        if key == "description":
            out["size"] = size
    return out


def main():
    parser = argparse.ArgumentParser(
        description=doc(__doc__, "profile_sizes"), formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", help=t("profiles file to update"))
    parser.add_argument("--env", help=t(".env file to read HF_TOKEN / CIVITAI_TOKEN from"))
    parser.add_argument("--force", action="store_true",
                        help=t("also query the files whose size is already known"))
    parser.add_argument("--dry-run", action="store_true", help=t("show the sizes without writing the file"))
    args = parser.parse_args()

    load_env_tokens(args.env)
    path, source = cp.config_source(args.config)
    print(">> " + t("Config: {path}", path=path))
    profiles = cp.load_profiles(path, source)
    text = path.read_text()
    data = json.loads(text)
    profiles = data["profiles"]  # same objects as those modified below

    items = [
        (f"[{name}] {section}", item)
        for name, profile in profiles.items()
        for section in FILE_SECTIONS
        for item in profile.get(section, [])
        if args.force or not isinstance(item.get("size"), int)
    ]
    print(">> " + t("{n} size(s) to fetch", n=len(items)) + (" (--force)" if args.force else ""))
    try:
        failures = fetch_sizes(items)
    except cp.ConfigError as e:
        sys.exit(f"!! {e}")

    for name in list(profiles):
        variants = profiles[name].get("variants")
        if variants:  # a size per variant: {"int8": "18.9 GB", ...}
            size = {v: profile_size_text(*cp.profile_total(profiles, cp.make_ref(name, [v])))
                    for v in variants}
            shown = ", ".join(f"{v}: {text}" for v, text in size.items())
        else:
            total, unknown = cp.profile_total(profiles, name)
            if not total and not unknown:  # only custom nodes / pip packages
                profiles[name].pop("size", None)
                continue
            size = shown = profile_size_text(total, unknown)
        profiles[name] = with_profile_size(profiles[name], size)
        print(f"   {name:<24} {shown}")

    if failures:
        print("!! " + t("{n} size(s) not found:", n=len(failures)), file=sys.stderr)
        for failure in failures:
            print(f"   - {failure}", file=sys.stderr)

    if args.dry_run:
        print(">> " + t("--dry-run: file not modified."))
    else:
        blank_before = set(re.findall(r'\n[ \t]*\n[ \t]*"([^"]+)"\s*:\s*\{', text))
        out = cp.writable_config(path, source)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(format_config(data, blank_before), newline="\n")
        print(">> " + (t("{path} updated.", path=out) if out == path
                       else t("{path} created (the template {seed} is left as is).", path=out, seed=path)))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # panel's Stop button: the file is only written at the end
        print("!! " + t("Size calculation interrupted, file not modified."), file=sys.stderr)
        sys.exit(130)
