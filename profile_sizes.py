#!/usr/bin/env python3
"""Calcule la taille des profils d'utilisation et l'enregistre dans le fichier de profils.

Interroge la taille réelle de chaque fichier (modèles, workflows) à la source, sans rien
télécharger : API Hugging Face (paths-info), API CivitAI (model-versions), ou en-tête
Content-Length pour une URL directe ou un fichier d'un dépôt GitHub. Seuls les fichiers sans "size" sont interrogés, sauf avec
--force qui les réinterroge tous. Écrit ensuite dans la config :
  - "size" (octets) sur chaque fichier ;
  - "size" (lisible, ex: "89,4 Go") sur chaque profil : total de ses fichiers, `extends`
    compris, chaque fichier compté une fois. Les custom nodes et paquets pip ne sont pas comptés
    (un profil qui n'a qu'eux n'a pas de taille).

Usage:
  profile_sizes.py [--config FICHIER] [--env FICHIER] [--force] [--dry-run]

Fichier de config : même règle que comfy_profiles.py (--config, $COMFY_PROFILES_CONFIG, fichier
de l'utilisateur, modèle). Quand c'est le modèle (lecture seule), le résultat est écrit dans le
fichier de l'utilisateur (<user>/__comfy_profiles/profiles.json), qui prend alors le relais.
Token Hugging Face (dépôts gated) : $HF_TOKEN, sinon celui du fichier --env (un .env de
déploiement par exemple), sinon celui de `hf auth login`. Token CivitAI : $CIVITAI_TOKEN, sinon
celui du fichier --env.
La mise en forme du fichier (un fichier par ligne, lignes vides entre profils) est conservée.
Aussi lancé par le bouton « Recalculer les tailles » du panneau Profils.
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
    """Reprend les tokens d'un fichier .env (hors du pod), sans écraser l'environnement."""
    if not env_file:
        return
    env_file = Path(env_file)
    if not env_file.is_file():
        sys.exit("!! " + t("Fichier --env introuvable : {path}", path=env_file))
    for line in env_file.read_text().splitlines():
        key, sep, value = line.strip().partition("=")
        key, value = key.strip(), value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        if sep and key in TOKEN_KEYS and value and not os.environ.get(key):
            os.environ[key] = value


# --- Tailles à la source ------------------------------------------------------------------

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
    """Tailles d'un lot de fichiers d'un même dépôt/révision, en une requête."""
    url = (
        f"https://huggingface.co/api/models/{repo}/paths-info/"
        f"{urllib.parse.quote(revision or 'main', safe='')}"
    )
    entries = http_json(url, data={"paths": files}, token=hf_token())
    # Un chemin inexistant est simplement absent de la réponse.
    return {e["path"]: (e.get("lfs") or {}).get("size", e.get("size")) for e in entries}


def civitai_size(version_id):
    """Taille du fichier que sert /api/download/models/<id> : le fichier principal."""
    token = os.environ.get("CIVITAI_TOKEN")
    url = f"https://civitai.com/api/v1/model-versions/{version_id}"
    data = http_json(f"{url}?token={token}" if token else url)
    files = data.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary or primary.get("sizeKB") is None:
        raise LookupError(t("aucun fichier dans la version"))
    return round(primary["sizeKB"] * 1024)


def url_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": cp.USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as resp:
        length = resp.headers.get("Content-Length")
    if length is None:
        raise LookupError(t("pas d'en-tête Content-Length"))
    return int(length)


def error_text(e):
    if isinstance(e, urllib.error.HTTPError):
        hint = " " + t("(dépôt gated/privé : HF_TOKEN requis, licence acceptée ?)") if e.code in (401, 403) else ""
        return f"HTTP {e.code}{hint}"
    return str(e)


def fetch_sizes(items):
    """items : liste de (où, élément). Renseigne element["size"], retourne les échecs."""
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
                failures.append(f"{where} {cp.describe_source(item)} : " + t("fichier introuvable dans le dépôt"))
            else:
                item["size"] = sizes[item["file"]]
    return failures


# --- Totaux par profil --------------------------------------------------------------------

def profile_size_text(total, unknown):
    text = human_size(total)
    return text + " " + t("+ {n} fichier(s) de taille inconnue", n=unknown) if unknown else text


# --- Écriture (mise en forme conservée) ---------------------------------------------------

def dumps_inline(value):
    return json.dumps(value, ensure_ascii=False, separators=(", ", ": "))


def format_config(data, blank_before):
    """Même style que profiles.json : un profil par bloc, un élément de liste par ligne."""
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
    """Place "size" juste après "description" (ou en tête), en remplaçant l'ancienne valeur."""
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
    parser.add_argument("--config", help=t("fichier de profils à mettre à jour"))
    parser.add_argument("--env", help=t("fichier .env d'où reprendre HF_TOKEN / CIVITAI_TOKEN"))
    parser.add_argument("--force", action="store_true",
                        help=t("réinterroge aussi les fichiers dont la taille est déjà connue"))
    parser.add_argument("--dry-run", action="store_true", help=t("affiche les tailles sans écrire le fichier"))
    args = parser.parse_args()

    load_env_tokens(args.env)
    path, source = cp.config_source(args.config)
    print(">> " + t("Config : {path}", path=path))
    profiles = cp.load_profiles(path, source)
    text = path.read_text()
    data = json.loads(text)
    profiles = data["profiles"]  # mêmes objets que ceux modifiés ci-dessous

    items = [
        (f"[{name}] {section}", item)
        for name, profile in profiles.items()
        for section in FILE_SECTIONS
        for item in profile.get(section, [])
        if args.force or not isinstance(item.get("size"), int)
    ]
    print(">> " + t("{n} taille(s) à récupérer", n=len(items)) + (" (--force)" if args.force else ""))
    try:
        failures = fetch_sizes(items)
    except cp.ConfigError as e:
        sys.exit(f"!! {e}")

    for name in list(profiles):
        total, unknown = cp.profile_total(profiles, name)
        if not total and not unknown:  # que des custom nodes / paquets pip
            profiles[name].pop("size", None)
            continue
        size = profile_size_text(total, unknown)
        profiles[name] = with_profile_size(profiles[name], size)
        print(f"   {name:<24} {size}")

    if failures:
        print("!! " + t("{n} taille(s) introuvable(s) :", n=len(failures)), file=sys.stderr)
        for failure in failures:
            print(f"   - {failure}", file=sys.stderr)

    if args.dry_run:
        print(">> " + t("--dry-run : fichier non modifié."))
    else:
        blank_before = set(re.findall(r'\n[ \t]*\n[ \t]*"([^"]+)"\s*:\s*\{', text))
        out = cp.writable_config(path, source)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(format_config(data, blank_before), newline="\n")
        print(">> " + (t("{path} mis à jour.", path=out) if out == path
                       else t("{path} créé (le modèle {seed} reste tel quel).", path=out, seed=path)))
    return 1 if failures else 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:  # bouton Arrêter du panneau : le fichier n'est écrit qu'à la fin
        print("!! " + t("Calcul des tailles interrompu, fichier non modifié."), file=sys.stderr)
        sys.exit(130)
