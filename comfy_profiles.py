#!/usr/bin/env python3
"""Profils d'utilisation ComfyUI (minimax-h3-all-pruned_int8, flux2-klein-9b, ...) : chaque profil décrit les
modèles, custom nodes, workflows et paquets pip dont il a besoin. `sync` installe ce qui
manque et ne touche jamais à ce qui est déjà présent — relançable à volonté (c'est ce que fait
entrypoint.sh à chaque démarrage du pod pour les profils de COMFY_PROFILES).

Usage:
  comfy_profiles.py [--config FICHIER] list [--json]
  comfy_profiles.py [--config FICHIER] show PROFIL[,PROFIL...] [--json]
  comfy_profiles.py [--config FICHIER] sync [PROFIL[,PROFIL...]] [--dry-run]
  comfy_profiles.py [--config FICHIER] uninstall PROFIL[,PROFIL...] [--dry-run] [--json]

Fichier de config : --config, sinon $COMFY_PROFILES_CONFIG, sinon /opt/scripts/profiles.json
(embarqué dans l'image). S'il pointe vers un fichier absent (ex: sur le Network Volume), la
config de l'image y est d'abord copiée, pour être éditée ensuite.
Profils synchronisés par défaut : $COMFY_PROFILES (séparés par des virgules).
`uninstall` supprime les modèles, workflows et custom nodes de profils, sauf ceux dont a encore
besoin un autre profil installé (voir cmd_uninstall). Les paquets pip restent dans le venv.
Ctrl+C (SIGINT) interrompt proprement `sync` : le téléchargement ou le clone en cours est
abandonné sans laisser de fichier incomplet, la prochaine synchro le reprendra.
--json (list, show, uninstall) : résultat en JSON sur stdout, messages d'information sur stderr (utilisé
par le panneau Profils dans ComfyUI, voir __init__.py).

Destinations :
  modèles      -> $MODELS_VOLUME_DIR/<type>/  (ou $COMFY_HOME/models/<type>/ sans volume)
  custom nodes -> <volume>/custom_nodes/<nom>, lié dans $COMFY_HOME/custom_nodes/
                  (ou directement dans $COMFY_HOME/custom_nodes/ sans volume) ; clonés depuis
                  git, ou extraits d'un zip public sur Google Drive (chiffré ou non : mot de
                  passe dans $GDRIVE_ZIP_PASSWORD)
  workflows    -> $COMFY_HOME/user/default/workflows/
Les dépendances Python (custom nodes, pip) vivent dans le venv du conteneur : elles sont
réinstallées automatiquement sur un nouveau pod, même si le volume est déjà peuplé.
"""
import argparse
import contextlib
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

DEFAULT_CONFIG = Path("/opt/scripts/profiles.json")
SECTIONS = ("custom_nodes", "pip", "models", "workflows")
# "size" : total calculé par profile_sizes.py (informatif, ignoré par sync).
PROFILE_KEYS = {"description", "size", "extends", *SECTIONS}
SOURCES = ("hf", "github", "url", "civitai")
# Cloudflare (devant civitai.com notamment) rejette le User-Agent par défaut de urllib.
USER_AGENT = "runpod-comfy-profiles"
# Dans le venv, donc propre à ce conteneur : un nouveau pod réinstalle les dépendances.
MARKER_DIR = Path(sys.prefix) / ".comfy-profiles"


class ConfigError(Exception):
    pass


def env_path(name, default):
    return Path(os.environ.get(name) or default)


class Paths:
    def __init__(self):
        self.comfy_home = env_path("COMFY_HOME", "/workspace/ComfyUI")
        models_volume = env_path("MODELS_VOLUME_DIR", "/runpod-volume/models")
        volume_root = models_volume.parent
        has_volume = volume_root.is_dir()
        self.models = models_volume if has_volume else self.comfy_home / "models"
        self.custom_nodes = self.comfy_home / "custom_nodes"
        self.custom_nodes_store = volume_root / "custom_nodes" if has_volume else self.custom_nodes
        self.workflows = self.comfy_home / "user" / "default" / "workflows"
        # Hors des sous-dossiers <type>/ : jamais scanné par ComfyUI ni lié par entrypoint.sh.
        self.staging = self.models / ".staging"


# --- Config -------------------------------------------------------------------------------

def config_path(arg):
    return Path(arg or os.environ.get("COMFY_PROFILES_CONFIG") or DEFAULT_CONFIG)


def is_comment(key):
    return key.startswith("//")


def load_profiles(path):
    if not path.is_file():
        if path != DEFAULT_CONFIG and DEFAULT_CONFIG.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(DEFAULT_CONFIG, path)
            print(f">> {path} absent : copie de la config par défaut de l'image ({DEFAULT_CONFIG}).")
        else:
            sys.exit(f"!! Fichier de config introuvable : {path}")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit(f"!! {path} : JSON invalide ({e})")
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        sys.exit(f"!! {path} : objet 'profiles' manquant ou vide")
    for name, profile in profiles.items():
        unknown = {k for k in profile if not is_comment(k)} - PROFILE_KEYS
        if unknown:
            sys.exit(
                f"!! Profil '{name}' : clé(s) inconnue(s) {sorted(unknown)} "
                f"(attendues : {', '.join(sorted(PROFILE_KEYS))})"
            )
    return profiles


def split_names(value):
    return [n.strip() for n in (value or "").split(",") if n.strip()]


def resolve(profiles, names):
    """Fusionne les profils demandés et leurs `extends` (parents d'abord, chacun une fois)."""
    merged = {section: [] for section in SECTIONS}
    visited = set()

    def visit(name, stack):
        if name in stack:
            sys.exit(f"!! Cycle dans 'extends' : {' -> '.join([*stack, name])}")
        if name not in profiles:
            sys.exit(f"!! Profil inconnu : '{name}' (disponibles : {', '.join(profiles)})")
        if name in visited:
            return
        visited.add(name)
        profile = profiles[name]
        for parent in profile.get("extends", []):
            visit(parent, [*stack, name])
        for section in SECTIONS:
            for item in profile.get(section, []):
                merged[section].append((name, item))

    for name in names:
        visit(name, [])
    return merged


# --- Téléchargements ----------------------------------------------------------------------

def source_of(item, where):
    found = [k for k in SOURCES if k in item]
    if len(found) != 1:
        raise ConfigError(f"{where} : une (et une seule) source attendue parmi {', '.join(SOURCES)}")
    if found[0] in ("hf", "github") and not item.get("file"):
        raise ConfigError(f"{where} : 'file' (chemin dans le dépôt) requis avec '{found[0]}'")
    if found[0] == "github":
        github_repo(item["github"], where)
    return found[0]


def github_repo(value, where=""):
    """'owner/repo' à partir de 'owner/repo' ou d'une URL de dépôt GitHub."""
    repo = re.sub(r"^(https?://)?github\.com/", "", value.strip()).rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ConfigError(f"{where} : 'github' doit être 'owner/depot' ou l'URL d'un dépôt GitHub")
    return repo


def github_file_url(item):
    """URL d'un seul fichier du dépôt (sans le cloner). /raw/ sur github.com redirige vers
    raw.githubusercontent.com, ou vers media.githubusercontent.com pour un fichier Git LFS."""
    rev = item.get("revision") or "HEAD"
    path = urllib.parse.quote(item["file"].lstrip("/"))
    return f"https://github.com/{github_repo(item['github'])}/raw/{rev}/{path}"


def target_name(item, where):
    if item.get("name"):
        return item["name"]
    if "hf" in item or "github" in item:
        return Path(item["file"]).name
    raise ConfigError(f"{where} : 'name' (nom du fichier local) requis pour une source url/civitai")


def describe_source(item):
    if "hf" in item:
        rev = f"@{item['revision']}" if item.get("revision") else ""
        return f"hf:{item['hf']}{rev}/{item['file']}"
    if "github" in item:
        rev = f"@{item['revision']}" if item.get("revision") else ""
        return f"github:{github_repo(item['github'])}{rev}/{item['file']}"
    if "civitai" in item:
        return f"civitai:{item['civitai']}"
    return item["url"]


def fetch_url(url, dest):
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:
            shutil.copyfileobj(resp, out, 16 * 1024 * 1024)
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def fetch(item, dest, paths):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if "hf" in item:
        from huggingface_hub import hf_hub_download  # lit HF_TOKEN tout seul

        paths.staging.mkdir(parents=True, exist_ok=True)
        try:
            downloaded = hf_hub_download(
                repo_id=item["hf"],
                filename=item["file"],
                revision=item.get("revision"),
                local_dir=paths.staging,
            )
            shutil.move(downloaded, dest)
        finally:
            shutil.rmtree(paths.staging, ignore_errors=True)
    elif "civitai" in item:
        url = f"https://civitai.com/api/download/models/{item['civitai']}"
        # Token en paramètre plutôt qu'en en-tête : CivitAI redirige vers un stockage S3 qui
        # refuse un en-tête Authorization en plus de sa propre signature.
        token = os.environ.get("CIVITAI_TOKEN")
        fetch_url(f"{url}?token={token}" if token else url, dest)
    elif "github" in item:
        fetch_url(github_file_url(item), dest)
    else:
        fetch_url(item["url"], dest)


# --- Dépendances Python -------------------------------------------------------------------

def marker(kind, key, content):
    digest = hashlib.sha256(content.encode()).hexdigest()[:12]
    return MARKER_DIR / f"{kind}-{key}-{digest}"


def pip_install(args):
    if shutil.which("uv"):
        cmd = ["uv", "pip", "install", "--python", sys.executable, *args]
    else:
        cmd = [sys.executable, "-m", "pip", "install", *args]
    subprocess.run(cmd, check=True)


def touch(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.touch()


# --- Plan ---------------------------------------------------------------------------------

class Step:
    def __init__(self, label, run):
        self.label = label
        self.run = run


def file_dest(item, where, section, paths):
    """Chemin local d'un modèle ou d'un workflow."""
    source_of(item, where)
    if section == "workflows":
        return paths.workflows / target_name(item, where)
    if not item.get("type"):
        raise ConfigError(f"{where} : 'type' (sous-dossier, ex: loras) requis")
    return paths.models / item["type"] / target_name(item, where)


def file_label(item, section, dest):
    return f"{item['type']}/{dest.name}" if section == "models" else f"workflow/{dest.name}"


def plan_file(item, dest, paths):
    if dest.exists():
        return None
    return Step(f"{describe_source(item)} -> {dest}", lambda: fetch(item, dest, paths))


def git(store, *args, **kwargs):
    return subprocess.run(["git", "-C", str(store), *args], **kwargs)


def at_ref(store, ref):
    """Vrai si le dépôt local est déjà sur `ref` (vérifié sans accès réseau)."""
    def rev(r):
        out = git(store, "rev-parse", "--verify", "--quiet", f"{r}^{{commit}}",
                  capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None

    head = rev("HEAD")
    return head is not None and head == rev(ref)


def checkout_ref(store, ref):
    """Bascule un custom node déjà cloné sur `ref` (branche, tag ou commit)."""
    shallow = git(store, "rev-parse", "--is-shallow-repository", capture_output=True, text=True)
    fetch = ["fetch", "--tags", "origin", "+refs/heads/*:refs/remotes/origin/*"]
    if shallow.stdout.strip() == "true":
        fetch.insert(1, "--unshallow")
    git(store, *fetch, check=True)
    if git(store, "rev-parse", "--verify", "--quiet", f"refs/remotes/origin/{ref}",
           capture_output=True).returncode == 0:
        git(store, "checkout", "-B", ref, f"origin/{ref}", check=True)
    else:
        git(store, "checkout", ref, check=True)


# Fichier écrit dans un custom node extrait d'un zip : id Drive dont il provient.
GDRIVE_MARKER = ".comfy-profiles-gdrive"


def gdrive_id(value, where):
    """Id d'un fichier Drive, à partir de l'id lui-même ou d'un lien de partage."""
    match = re.search(r"/d/([\w-]+)", value) or re.search(r"[?&]id=([\w-]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[\w-]{20,}", value):
        return value
    raise ConfigError(f"{where} : 'gdrive' doit être un lien de partage Google Drive ou un id de fichier")


def extract_encrypted_zip(archive, dest, file_id):
    """Zip chiffré (AES, ex. 7-Zip, ou ZipCrypto) : zipfile ne sait pas lire l'AES, pyzipper si."""
    password = os.environ.get("GDRIVE_ZIP_PASSWORD")
    if not password:
        raise RuntimeError(f"le zip Drive {file_id} est chiffré : mot de passe attendu dans "
                           "GDRIVE_ZIP_PASSWORD (secret RunPod gdrive_zip_password)")
    try:
        import pyzipper
    except ImportError:  # image antérieure à l'ajout de pyzipper dans le Dockerfile
        pip_install(["pyzipper"])
        import pyzipper
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(password.encode())
        try:
            zf.extractall(dest)  # même protection des chemins que zipfile
        except RuntimeError as e:
            raise RuntimeError(f"zip Drive {file_id} : déchiffrement impossible "
                               f"(GDRIVE_ZIP_PASSWORD erroné ?) : {e}") from None


def install_gdrive_zip(file_id, store, paths):
    """Télécharge un zip public sur Drive et l'extrait dans `store` (remplacé s'il existe)."""
    paths.staging.mkdir(parents=True, exist_ok=True)
    work = paths.staging / f"gdrive-{file_id}"
    try:
        archive = work / "node.zip"
        work.mkdir()
        # confirm=t : saute la page d'avertissement « fichier trop gros pour l'antivirus ».
        fetch_url(f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
                  archive)
        if not zipfile.is_zipfile(archive):
            raise RuntimeError(f"le fichier Drive {file_id} n'est pas un zip (non public, ou quota "
                               "de téléchargement Drive dépassé ?)")
        extracted = work / "extracted"
        with zipfile.ZipFile(archive) as zf:
            encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
            if not encrypted:
                zf.extractall(extracted)  # neutralise les chemins absolus et les `..`
        if encrypted:
            extract_encrypted_zip(archive, extracted, file_id)
        # Zip d'un dossier : on prend son contenu ; sinon les fichiers sont à la racine du zip.
        entries = [e for e in extracted.iterdir() if e.name != "__MACOSX"]
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else extracted
        (root / GDRIVE_MARKER).write_text(file_id)
        shutil.rmtree(store, ignore_errors=True)
        store.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root), str(store))
    finally:
        shutil.rmtree(paths.staging, ignore_errors=True)


def custom_node_name(item, where):
    if item.get("name"):
        return item["name"]
    if not item.get("git"):
        raise ConfigError(f"{where} : une (et une seule) source attendue parmi git, gdrive")
    return item["git"].rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]


def in_image(name, paths):
    """Custom node livré avec l'image (dossier réel, pas un lien vers le volume)."""
    link, store = paths.custom_nodes / name, paths.custom_nodes_store / name
    return link.exists() and not link.is_symlink() and link != store


def plan_custom_node(item, where, paths):
    url = item.get("git")
    drive = item.get("gdrive")
    if bool(url) == bool(drive):
        raise ConfigError(f"{where} : une (et une seule) source attendue parmi git, gdrive")
    if drive:
        if not item.get("name"):
            raise ConfigError(f"{where} : 'name' (nom du dossier du custom node) requis avec 'gdrive'")
        if item.get("ref"):
            raise ConfigError(f"{where} : 'ref' ne s'applique qu'à une source 'git'")
        file_id = gdrive_id(drive, where)
    name = custom_node_name(item, where)
    store = paths.custom_nodes_store / name
    link = paths.custom_nodes / name
    steps = []

    if in_image(name, paths):
        print(f"   [{name}] déjà présent dans l'image ({link}), version du profil ignorée")
        return name, steps

    ref = item.get("ref")
    if drive:
        installed = store / GDRIVE_MARKER
        if not store.exists():
            steps.append(Step(f"gdrive:{file_id} (zip) -> {store}",
                              lambda: install_gdrive_zip(file_id, store, paths)))
        elif not installed.is_file():
            print(f"   [{name}] {store} existe mais ne vient pas d'un zip Drive, laissé tel quel")
        elif installed.read_text().strip() != file_id:
            steps.append(Step(f"gdrive:{file_id} (zip, nouveau fichier) remplace {store}",
                              lambda: install_gdrive_zip(file_id, store, paths)))
    elif not store.exists():
        def clone():
            try:
                git_clone()
            except BaseException:  # échec ou interruption : un clone partiel passerait pour installé
                shutil.rmtree(store, ignore_errors=True)
                raise

        def git_clone():
            if ref:
                # Branche ou tag : clone superficiel. Un commit n'est pas accepté par --branch,
                # d'où le repli sur un clone complet suivi d'un checkout.
                shallow = subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", ref, url, str(store)])
                if shallow.returncode != 0:
                    shutil.rmtree(store, ignore_errors=True)
                    subprocess.run(["git", "clone", url, str(store)], check=True)
                    subprocess.run(["git", "-C", str(store), "checkout", ref], check=True)
            else:
                subprocess.run(["git", "clone", "--depth", "1", url, str(store)], check=True)

        steps.append(Step(f"git clone {url}{'@' + ref if ref else ''} -> {store}", clone))
    elif ref and not at_ref(store, ref):
        steps.append(Step(f"git checkout {ref} dans {store}", lambda: checkout_ref(store, ref)))

    if link != store and not link.is_symlink():
        def make_link():
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(store)

        steps.append(Step(f"lien {link} -> {store}", make_link))

    # Les dépendances ne sont connues qu'une fois le dépôt cloné : on les évalue à l'exécution.
    def deps():
        requirements = store / "requirements.txt"
        if requirements.is_file():
            m = marker("req", name, requirements.read_text())
            if not m.exists():
                print(f">> [{name}] installation de requirements.txt")
                pip_install(["-r", str(requirements)])
                touch(m)
        install_py = store / "install.py"
        if install_py.is_file():
            m = marker("install", name, install_py.read_text())
            if not m.exists():
                print(f">> [{name}] exécution de install.py")
                subprocess.run([sys.executable, "install.py"], cwd=store, check=True)
                touch(m)

    deps_pending = bool(steps) or any(
        f.is_file() and not marker(kind, name, f.read_text()).exists()
        for kind, f in (("req", store / "requirements.txt"), ("install", store / "install.py"))
    )
    if deps_pending:
        steps.append(Step(f"dépendances de {name} (requirements.txt / install.py)", deps))
    return name, steps


def build_plan(merged, paths):
    """Retourne (étapes à exécuter, état de chaque élément : (genre, nom, à installer ?)).
    Valide toute la config avant d'agir."""
    steps, status, seen = [], [], set()

    for profile, item in merged["custom_nodes"]:
        where = f"[{profile}] custom_nodes"
        name, node_steps = plan_custom_node(item, where, paths)
        if name in seen:
            continue
        seen.add(name)
        steps += node_steps
        status.append(("custom_node", name, bool(node_steps)))

    specs = []
    for profile, spec in merged["pip"]:
        if spec not in specs:
            specs.append(spec)
    missing_specs = [s for s in specs if not marker("pip", "spec", s).exists()]
    for spec in specs:
        status.append(("pip", spec, spec in missing_specs))
    if missing_specs:
        def install_specs():
            pip_install(missing_specs)
            for s in missing_specs:
                touch(marker("pip", "spec", s))

        steps.append(Step(f"pip install {' '.join(missing_specs)}", install_specs))

    for section in ("models", "workflows"):
        for profile, item in merged[section]:
            dest = file_dest(item, f"[{profile}] {section}", section, paths)
            if dest in seen:
                continue
            seen.add(dest)
            step = plan_file(item, dest, paths)
            status.append((section[:-1], file_label(item, section, dest), bool(step)))
            if step:
                steps.append(step)

    return steps, status


# --- Commandes ----------------------------------------------------------------------------

def print_json(data):
    print(json.dumps(data, ensure_ascii=False))


def profile_state(profiles, name, paths, memo=None):
    """installed : tout est là, extends compris. Sinon, l'état dépend des éléments propres au
    profil (ceux qu'il n'hérite pas déjà d'un parent) : partial si l'un d'eux est présent,
    missing sinon. Un parent installé (ex. comfyui-common, partagé par beaucoup) ne rend donc
    pas « partiels » les profils qui en héritent. Un profil sans élément propre, qui ne fait
    que regrouper d'autres profils (ex. minimax-h3-all-*), est partial si l'un de ses parents
    directs est installé ou partiel. empty : n'installe aucun fichier (pip seul, ou seulement
    des custom nodes de l'image). error : config invalide."""
    memo = {} if memo is None else memo
    if name in memo:
        return memo[name]
    try:
        everything = installed_by(resolve(profiles, [name]), paths)
        inherited = set()
        for parent in ancestors(profiles, [name]) - {name}:
            inherited.update(installed_by(resolve(profiles, [parent]), paths))
    except (ConfigError, SystemExit):
        return memo.setdefault(name, "error")
    own = {path: target for path, target in everything.items() if path not in inherited}
    if not everything:
        state = "empty"
    elif all(installed(path, link) for path, (_, _, link) in everything.items()):
        state = "installed"
    elif own:
        state = "partial" if any(present(path, link) for path, (_, _, link) in own.items()) else "missing"
    else:
        parents = [profile_state(profiles, p, paths, memo) for p in profiles[name].get("extends", [])]
        state = "partial" if any(s in ("installed", "partial") for s in parents) else "missing"
    return memo.setdefault(name, state)


def cmd_list(profiles, args):
    if args.json:
        paths, states = Paths(), {}
        print_json({
            "config": str(config_path(args.config).absolute()),
            "default": split_names(os.environ.get("COMFY_PROFILES")),
            "profiles": {
                name: {
                    "description": profile.get("description", ""),
                    "size": profile.get("size", ""),
                    "extends": profile.get("extends", []),
                    "counts": {s: len(profile.get(s, [])) for s in SECTIONS},
                    "state": profile_state(profiles, name, paths, states),
                }
                for name, profile in profiles.items()
            },
        })
        return
    for name, profile in profiles.items():
        extends = profile.get("extends", [])
        counts = ", ".join(f"{len(profile.get(s, []))} {s}" for s in SECTIONS if profile.get(s))
        suffix = f"  (extends: {', '.join(extends)})" if extends else ""
        print(f"- {name}{suffix}")
        if profile.get("size"):
            print(f"    taille : {profile['size']}")
        if profile.get("description"):
            print(f"    {profile['description']}")
        if counts:
            print(f"    propre : {counts}")


def cmd_show(profiles, args):
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! Indique au moins un profil (voir `list`)")
    try:
        # Les messages de build_plan (custom nodes laissés tels quels...) ne doivent pas
        # polluer le JSON.
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            _, status = build_plan(resolve(profiles, names), Paths())
    except ConfigError as e:
        sys.exit(f"!! {e}")
    if args.json:
        print_json([{"kind": kind, "name": name, "missing": missing} for kind, name, missing in status])
        return
    lines = []
    for kind, name, missing in status:
        todo = "à télécharger" if kind in ("model", "workflow") else "à installer"
        lines.append(f"{kind:<12} {name:<40} {todo if missing else 'présent'}")
    print("\n".join(lines) or "(profil vide)")


def cmd_sync(profiles, args):
    names = split_names(args.profiles or os.environ.get("COMFY_PROFILES"))
    if not names:
        print(">> Aucun profil demandé (argument ou COMFY_PROFILES), rien à faire.")
        return 0
    paths = Paths()
    try:
        steps, _ = build_plan(resolve(profiles, names), paths)
    except ConfigError as e:
        sys.exit(f"!! {e}")

    print(f">> Profils : {', '.join(names)} — {len(steps)} action(s) à faire")
    print(f">> Modèles -> {paths.models}")
    if not steps:
        return 0
    if args.dry_run:
        for step in steps:
            print(f"   [dry-run] {step.label}")
        return 0
    print(">> HF_TOKEN détecté." if os.environ.get("HF_TOKEN") else ">> Pas de HF_TOKEN : téléchargements HF anonymes.")

    failures = []
    for i, step in enumerate(steps, 1):
        print(f">> ({i}/{len(steps)}) {step.label}", flush=True)
        try:
            step.run()
        except KeyboardInterrupt:
            print(f"!! Synchronisation interrompue ({i - 1}/{len(steps)} action(s) faite(s)).",
                  file=sys.stderr)
            return 130
        except Exception as e:  # une étape ratée ne doit pas bloquer les suivantes
            print(f"!! Échec : {e}", file=sys.stderr)
            failures.append(step.label)

    if failures:
        print(f"!! {len(failures)} échec(s) sur {len(steps)} :", file=sys.stderr)
        for label in failures:
            print(f"   - {label}", file=sys.stderr)
        return 1
    print(">> Synchronisation terminée.")
    return 0


# --- Désinstallation ----------------------------------------------------------------------

def installed_by(merged, paths):
    """Ce qu'installent des profils : {chemin: (genre, nom, lien du custom node ou None)}.
    Les custom nodes de l'image n'en font pas partie : jamais supprimés."""
    targets = {}
    for profile, item in merged["custom_nodes"]:
        name = custom_node_name(item, f"[{profile}] custom_nodes")
        if not in_image(name, paths):
            targets.setdefault(paths.custom_nodes_store / name,
                               ("custom_node", name, paths.custom_nodes / name))
    for section in ("models", "workflows"):
        for profile, item in merged[section]:
            dest = file_dest(item, f"[{profile}] {section}", section, paths)
            targets.setdefault(dest, (section[:-1], file_label(item, section, dest), None))
    return targets


def present(path, link):
    """Quelque chose à supprimer (même un custom node à moitié en place)."""
    return path.exists() or (link is not None and link.is_symlink())


def installed(path, link):
    """Réellement utilisable : pour un custom node, le dossier et son lien dans ComfyUI."""
    return path.exists() and (link is None or link.exists())


def ancestors(profiles, names):
    """Les profils et tout ce dont ils héritent (extends)."""
    found = set()

    def visit(name):
        if name in profiles and name not in found:
            found.add(name)
            for parent in profiles[name].get("extends", []):
                visit(parent)

    for name in names:
        visit(name)
    return found


def disk_size(path):
    if path.is_symlink() or path.is_file():
        return path.lstat().st_size
    return sum(f.lstat().st_size for f in path.rglob("*") if f.is_file() and not f.is_symlink())


def human_size(size):
    for unit, factor in (("To", 1e12), ("Go", 1e9), ("Mo", 1e6), ("Ko", 1e3)):
        if size >= factor:
            return f"{size / factor:.1f} {unit}".replace(".", ",")
    return f"{size} o"


def remove(path, link, paths):
    if link is not None and link.is_symlink():
        link.unlink()
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    # Sous-dossiers de models/ devenus vides (ex. diffusion_models/krea2).
    parent = path.parent
    while parent != paths.models and paths.models in parent.parents and not any(parent.iterdir()):
        parent.rmdir()
        parent = parent.parent


def plan_uninstall(profiles, names, paths):
    """Ce que supprime la désinstallation de `names`. Un élément est conservé s'il sert encore à
    un profil qu'on garde : un profil de COMFY_PROFILES (réinstallé à chaque démarrage), ou un
    autre profil complètement installé. Les profils dont héritent ceux qu'on désinstalle ne
    comptent pas (ils sont forcément installés) : leurs éléments partent, sauf s'ils servent à
    un profil gardé."""
    startup = split_names(os.environ.get("COMFY_PROFILES"))
    inherited = ancestors(profiles, names)
    targets = installed_by(resolve(profiles, names), paths)

    keep = [n for n in profiles if n not in names and n in startup]
    for name in profiles:
        if name in names or name in keep or name in inherited:
            continue
        theirs = installed_by(resolve(profiles, [name]), paths)
        if theirs and all(installed(path, link) for path, (_, _, link) in theirs.items()):
            keep.append(name)

    needed = {}  # chemin -> profils gardés qui l'utilisent
    for name in keep:
        for path in installed_by(resolve(profiles, [name]), paths):
            needed.setdefault(path, []).append(name)

    removed, kept = [], []
    for path, (kind, label, link) in targets.items():
        if not present(path, link):
            continue
        if path in needed:
            kept.append({"kind": kind, "name": label, "by": needed[path]})
        else:
            removed.append({"kind": kind, "name": label, "size": disk_size(path),
                            "path": path, "link": link})
    return {
        "remove": removed,
        "kept": kept,
        # Seulement ceux qui protègent effectivement quelque chose.
        "keep_profiles": [n for n in keep if any(n in k["by"] for k in kept)],
        "startup": [n for n in names if n in startup],
    }


def cmd_uninstall(profiles, args):
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! Indique au moins un profil (voir `list`)")
    paths = Paths()
    try:
        plan = plan_uninstall(profiles, names, paths)
    except ConfigError as e:
        sys.exit(f"!! {e}")
    removed = plan["remove"]
    freed = sum(r["size"] for r in removed)

    if args.json:
        print_json({
            **plan,
            "remove": [{k: r[k] for k in ("kind", "name", "size")} for r in removed],
            "freed": freed,
        })
        return 0

    print(f">> Désinstallation : {', '.join(names)} — {len(removed)} élément(s), {human_size(freed)}")
    if plan["keep_profiles"]:
        print(f">> Profils gardés (leurs éléments ne sont pas supprimés) : {', '.join(plan['keep_profiles'])}")
    for k in plan["kept"]:
        print(f"   conservé  {k['kind']:<12} {k['name']}  (utilisé par {', '.join(k['by'])})")
    for name in plan["startup"]:
        print(f"!! {name} est dans COMFY_PROFILES : il sera réinstallé au prochain démarrage du pod.")
    if not removed:
        print(">> Rien à supprimer.")
        return 0

    for i, r in enumerate(removed, 1):
        label = f"{r['kind']:<12} {r['name']}  ({human_size(r['size'])})"
        if args.dry_run:
            print(f"   [dry-run] supprimer {label}")
            continue
        print(f">> ({i}/{len(removed)}) supprimer {label}", flush=True)
        try:
            remove(r["path"], r["link"], paths)
        except KeyboardInterrupt:
            print(f"!! Désinstallation interrompue ({i - 1}/{len(removed)} supprimé(s)).", file=sys.stderr)
            return 130
        except OSError as e:
            print(f"!! Échec : {e}", file=sys.stderr)
            return 1
    if args.dry_run:
        return 0
    print(f">> Désinstallation terminée : {human_size(freed)} libérés.")
    if any(r["kind"] == "custom_node" for r in removed):
        print(">> Des custom nodes ont été supprimés : redémarre ComfyUI pour les décharger.")
    print(">> Les paquets pip installés pour ces profils restent dans le venv.")
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--config", help="fichier de profils (défaut : $COMFY_PROFILES_CONFIG ou la config de l'image)")
    sub = parser.add_subparsers(dest="command", required=True)
    lst = sub.add_parser("list", help="liste les profils disponibles")
    lst.add_argument("--json", action="store_true", help="sortie JSON")
    show = sub.add_parser("show", help="détaille ce qu'installent des profils, et ce qui est déjà là")
    show.add_argument("profiles")
    show.add_argument("--json", action="store_true", help="sortie JSON")
    sync = sub.add_parser("sync", help="installe ce qui manque pour des profils")
    sync.add_argument("profiles", nargs="?", help="défaut : $COMFY_PROFILES")
    sync.add_argument("--dry-run", action="store_true", help="affiche les actions sans rien faire")
    uninstall = sub.add_parser("uninstall", help="supprime ce qu'ont installé des profils (sauf ce qui sert encore)")
    uninstall.add_argument("profiles")
    uninstall.add_argument("--dry-run", action="store_true", help="affiche ce qui serait supprimé")
    uninstall.add_argument("--json", action="store_true", help="sortie JSON (implique --dry-run)")
    args = parser.parse_args()

    path = config_path(args.config)
    as_json = getattr(args, "json", False)
    print(f">> Config : {path}", file=sys.stderr if as_json else sys.stdout)
    with contextlib.redirect_stdout(sys.stderr if as_json else sys.stdout):
        profiles = load_profiles(path)
    commands = {"list": cmd_list, "show": cmd_show, "sync": cmd_sync, "uninstall": cmd_uninstall}
    sys.exit(commands[args.command](profiles, args) or 0)


if __name__ == "__main__":
    main()
