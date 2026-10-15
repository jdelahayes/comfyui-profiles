#!/usr/bin/env python3
"""Profils d'utilisation ComfyUI : chaque profil décrit les
modèles, custom nodes, workflows et paquets pip dont il a besoin. `sync` installe ce qui
manque et ne touche jamais à ce qui est déjà présent — relançable à volonté (par exemple à
chaque démarrage d'un conteneur, pour les profils de COMFY_PROFILES).

Usage:
  comfy_profiles.py [--config FICHIER] list [--json]
  comfy_profiles.py [--config FICHIER] where
  comfy_profiles.py [--config FICHIER] show PROFIL[,PROFIL...] [--json]
  comfy_profiles.py [--config FICHIER] sync [PROFIL[,PROFIL...]] [--dry-run]
  comfy_profiles.py [--config FICHIER] uninstall PROFIL[,PROFIL...] [--with-extends] [--dry-run] [--json]
  comfy_profiles.py [--config FICHIER] adopt PROFIL[,PROFIL...] [--dry-run] [--json]

Fichier de profils, le premier trouvé :
  1. --config FICHIER
  2. $COMFY_PROFILES_CONFIG (s'il est absent, le modèle y est d'abord copié)
  3. <user>/__comfy_profiles/profiles.json : celui qu'écrivent l'édition et l'import du panneau
  4. le modèle, en lecture seule : $COMFY_PROFILES_SEED, sinon examples/profiles.example.json
Profils synchronisés par défaut : $COMFY_PROFILES (séparés par des virgules).
`uninstall` supprime les modèles, workflows et custom nodes propres à des profils (avec
--with-extends : aussi ceux des profils dont ils héritent), sauf ceux dont a encore besoin un
autre profil installé (voir plan_uninstall) et ceux que le gestionnaire n'a pas installés
lui-même (voir Manifest). Les paquets pip restent dans le venv.
Ctrl+C (SIGINT) interrompt proprement `sync` : le téléchargement ou le clone en cours est
abandonné sans laisser de fichier incomplet, la prochaine synchro le reprendra.
--json (list, show, uninstall) : résultat en JSON sur stdout, messages d'information sur stderr (utilisé
par le panneau Profils dans ComfyUI, voir __init__.py).

Destinations (le panneau passe les chemins de ComfyUI lui-même ; en ligne de commande, ils se
déduisent de $COMFY_HOME, sinon du ComfyUI dont ce dépôt est un custom node) :
  modèles      -> $COMFY_MODELS_DIR/<type>/            (défaut : $COMFY_HOME/models)
  custom nodes -> $COMFY_PROFILES_NODES_STORE/<nom>, lié dans $COMFY_CUSTOM_NODES_DIR/
                  (défaut : directement dans $COMFY_HOME/custom_nodes/) ; clonés depuis git,
                  ou extraits d'un zip public sur Google Drive (chiffré ou non : mot de passe
                  dans $GDRIVE_ZIP_PASSWORD)
  workflows    -> $COMFY_USER_DIR/default/workflows/   (défaut : $COMFY_HOME/user)
Les dépendances Python (custom nodes, pip) sont installées dans le Python qui lance ce script
et notées dans son environnement (venv) : un nouveau conteneur les réinstalle, même si les
custom nodes sont déjà sur un volume persistant.

Langue des messages : $COMFY_PROFILES_LANG, sinon $LC_ALL, $LC_MESSAGES ou $LANG (en, fr).
"""
import argparse
import contextlib
import functools
import hashlib
import inspect
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

from profiles_i18n import doc, human_size, t

HERE = Path(__file__).resolve().parent
EXAMPLE_CONFIG = HERE / "examples" / "profiles.example.json"
# Dossier « System User » de ComfyUI (préfixe __) : jamais servi par ses routes HTTP
# (/api/userdata...), seul ce module y lit et écrit. Contient le fichier de profils de
# l'utilisateur et le manifeste de ce qui a été installé.
DATA_DIR_NAME = "__comfy_profiles"
CONFIG_NAME = "profiles.json"
MANIFEST_NAME = "installed.json"
SECTIONS = ("custom_nodes", "pip", "models", "workflows")
# "size" : total calculé par profile_sizes.py (informatif, ignoré par sync).
PROFILE_KEYS = {"description", "size", "extends", *SECTIONS}
SOURCES = ("hf", "github", "url", "civitai")
# Cloudflare (devant civitai.com notamment) rejette le User-Agent par défaut de urllib.
USER_AGENT = "comfyui-profiles"
# Dans le venv, donc propre à ce conteneur : un nouveau conteneur réinstalle les dépendances.
MARKER_DIR = Path(sys.prefix) / ".comfy-profiles"


class ConfigError(Exception):
    pass


def env_path(name, default):
    return Path(os.environ.get(name) or default)


def default_comfy_home():
    """Le ComfyUI dont ce dépôt est un custom node (<ComfyUI>/custom_nodes/comfyui-profiles)."""
    return HERE.parent.parent if HERE.parent.name == "custom_nodes" else None


class Paths:
    def __init__(self):
        home = os.environ.get("COMFY_HOME") or default_comfy_home()
        if not home:
            sys.exit("!! " + t("Dossier de ComfyUI inconnu : indique-le dans COMFY_HOME"))
        self.comfy_home = Path(home)
        self.models = env_path("COMFY_MODELS_DIR", self.comfy_home / "models")
        self.custom_nodes = env_path("COMFY_CUSTOM_NODES_DIR", self.comfy_home / "custom_nodes")
        # Ailleurs que custom_nodes/ (ex. un volume persistant) : chaque node y est cloné puis
        # lié dans custom_nodes/.
        self.custom_nodes_store = env_path("COMFY_PROFILES_NODES_STORE", self.custom_nodes)
        self.user = env_path("COMFY_USER_DIR", self.comfy_home / "user")
        self.workflows = self.user / "default" / "workflows"
        self.data = self.user / DATA_DIR_NAME
        # Hors des sous-dossiers <type>/ : jamais scanné par ComfyUI.
        self.staging = self.models / ".staging"
        self.model_folders = model_folders(self)

    def model_path(self, type_, name):
        """Chemin d'un modèle de type `type_` (ex. loras, diffusion_models/krea2) : là où il est
        déjà, dans l'un des dossiers que ComfyUI parcourt pour ce type (extra_model_paths.yaml
        compris), sinon dans le premier de ces dossiers qui porte le nom du type (ex.
        comfyModels/diffusion_models plutôt que comfyModels/unet), sinon dans le premier."""
        folder, _, sub = type_.partition("/")
        bases = [Path(b) for b in self.model_folders.get(LEGACY_FOLDERS.get(folder, folder), [])]
        default = self.models / type_ / name
        candidates = [base / sub / name for base in bases]
        for path in [*candidates, default]:
            if path.exists() or path.is_symlink():
                return path
        preferred = next((b for b in bases if b.name == folder), bases[0] if bases else None)
        return preferred / sub / name if preferred else default

    def model_roots(self):
        """Dossiers de modèles de premier niveau (jamais supprimés, même vides)."""
        return {self.models, *(Path(b) for paths in self.model_folders.values() for b in paths)}


# Noms historiques de dossiers de modèles, comme dans ComfyUI (folder_paths.map_legacy).
LEGACY_FOLDERS = {"unet": "diffusion_models", "clip": "text_encoders"}
# Dossiers par défaut de ComfyUI qui ne s'appellent pas simplement models/<type>.
DEFAULT_MODEL_SUBDIRS = {"diffusion_models": ["unet", "diffusion_models"],
                         "text_encoders": ["text_encoders", "clip"],
                         "controlnet": ["controlnet", "t2i_adapter"]}


def model_folders(paths):
    """{type: [dossiers, dans l'ordre de ComfyUI]}. Depuis le panneau : la liste du serveur
    lui-même ($COMFY_MODEL_FOLDERS). En ligne de commande : les dossiers par défaut complétés
    par <ComfyUI>/extra_model_paths.yaml et $COMFY_EXTRA_MODEL_PATHS (fichiers séparés par
    « : », comme --extra-model-paths-config), lus comme le fait ComfyUI."""
    if os.environ.get("COMFY_MODEL_FOLDERS"):
        return json.loads(os.environ["COMFY_MODEL_FOLDERS"])
    configs = [paths.comfy_home / "extra_model_paths.yaml",
               *map(Path, filter(None, os.environ.get("COMFY_EXTRA_MODEL_PATHS", "").split(os.pathsep)))]
    configs = [c for c in configs if c.is_file()]
    folders = {}
    if not configs:
        return folders
    try:
        import yaml
    except ImportError:
        print("!! " + t("pyyaml absent : {files} ignoré(s)", files=", ".join(map(str, configs))),
              file=sys.stderr)
        return folders

    def add(folder, path, is_default):  # folder_paths.add_model_folder_path
        folder = LEGACY_FOLDERS.get(folder, folder)
        known = folders.setdefault(folder, [
            str(paths.models / d) for d in DEFAULT_MODEL_SUBDIRS.get(folder, [folder])])
        if path in known:
            if is_default and known[0] != path:
                known.remove(path)
                known.insert(0, path)
        elif is_default:
            known.insert(0, path)
        else:
            known.append(path)

    for config in configs:  # utils/extra_config.load_extra_path_config
        data = yaml.safe_load(config.read_text(encoding="utf-8")) or {}
        yaml_dir = config.resolve().parent
        for conf in data.values():
            if not conf:
                continue
            conf = dict(conf)
            base = conf.pop("base_path", None)
            if base:
                base = os.path.expandvars(os.path.expanduser(base))
                base = base if os.path.isabs(base) else os.path.abspath(yaml_dir / base)
            is_default = conf.pop("is_default", False)
            for folder, value in conf.items():
                for line in str(value).split("\n"):
                    if not line:
                        continue
                    full = os.path.join(base, line) if base else (
                        line if os.path.isabs(line) else os.path.abspath(yaml_dir / line))
                    add(folder, os.path.normpath(full), is_default)
    return folders


# --- Config -------------------------------------------------------------------------------

def seed_config():
    """Modèle de fichier de profils : celui que fournit l'environnement (ex. une image Docker),
    sinon l'exemple de ce dépôt."""
    return Path(os.environ.get("COMFY_PROFILES_SEED") or EXAMPLE_CONFIG)


def config_source(arg):
    """(fichier de profils, origine) ; origine : option (--config), env
    (COMFY_PROFILES_CONFIG), user (<user>/__comfy_profiles) ou seed (modèle, lecture seule)."""
    if arg:
        return Path(arg), "option"
    if os.environ.get("COMFY_PROFILES_CONFIG"):
        return Path(os.environ["COMFY_PROFILES_CONFIG"]), "env"
    user = Paths().data / CONFIG_NAME
    if user.is_file():
        return user, "user"
    return seed_config(), "seed"


def writable_config(path, source):
    """Où enregistrer une modification : jamais dans le modèle, mais dans le fichier de
    l'utilisateur, qui prend alors le relais."""
    return Paths().data / CONFIG_NAME if source == "seed" else path


def is_comment(key):
    return key.startswith("//")


def load_profiles(path, source="option"):
    if not path.is_file():
        seed = seed_config()
        if source in ("option", "env") and path != seed and seed.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(seed, path)
            print(">> " + t("{path} absent : copie du modèle ({seed}).", path=path, seed=seed))
        else:
            sys.exit("!! " + t("Fichier de config introuvable : {path}", path=path))
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit("!! " + t("{path} : JSON invalide ({error})", path=path, error=e))
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        sys.exit("!! " + t("{path} : objet 'profiles' manquant ou vide", path=path))
    for name, profile in profiles.items():
        unknown = {k for k in profile if not is_comment(k)} - PROFILE_KEYS
        if unknown:
            sys.exit("!! " + t("Profil '{name}' : clé(s) inconnue(s) {keys} (attendues : {expected})",
                               name=name, keys=sorted(unknown), expected=", ".join(sorted(PROFILE_KEYS))))
    return profiles


def split_names(value):
    return [n.strip() for n in (value or "").split(",") if n.strip()]


def resolve(profiles, names):
    """Fusionne les profils demandés et leurs `extends` (parents d'abord, chacun une fois)."""
    merged = {section: [] for section in SECTIONS}
    visited = set()

    def visit(name, stack):
        if name in stack:
            sys.exit("!! " + t("Cycle dans 'extends' : {cycle}", cycle=" -> ".join([*stack, name])))
        if name not in profiles:
            sys.exit("!! " + t("Profil inconnu : '{name}' (disponibles : {available})",
                               name=name, available=", ".join(profiles)))
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
        raise ConfigError(t("{where} : une (et une seule) source attendue parmi {sources}",
                             where=where, sources=", ".join(SOURCES)))
    if found[0] in ("hf", "github") and not item.get("file"):
        raise ConfigError(t("{where} : 'file' (chemin dans le dépôt) requis avec '{source}'",
                             where=where, source=found[0]))
    if found[0] == "github":
        github_repo(item["github"], where)
    return found[0]


def github_repo(value, where=""):
    """'owner/repo' à partir de 'owner/repo' ou d'une URL de dépôt GitHub."""
    repo = re.sub(r"^(https?://)?github\.com/", "", value.strip()).rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ConfigError(t("{where} : 'github' doit être 'owner/depot' ou l'URL d'un dépôt GitHub",
                             where=where))
    return repo


def github_file_url(item):
    """URL d'un seul fichier du dépôt (sans le cloner). /raw/ sur github.com redirige vers
    raw.githubusercontent.com, ou vers media.githubusercontent.com pour un fichier Git LFS."""
    rev = item.get("revision") or "HEAD"
    path = urllib.parse.quote(item["file"].lstrip("/"))
    return f"https://github.com/{github_repo(item['github'])}/raw/{rev}/{path}"


def web_repo_url(url):
    """Page web d'un dépôt git : https://host/owner/repo pour git@host:owner/repo.git..."""
    url = re.sub(r"^git\+", "", url.strip())
    url = re.sub(r"^[^@/:]+@([^:/]+):", r"https://\1/", url)  # git@host:owner/repo
    return url.rstrip("/").removesuffix(".git")


def source_link(item):
    """(site, URL de la page de la source) d'un modèle, workflow ou custom node, pour le
    panneau : le dépôt ou le fichier sur Hugging Face ou GitHub, la version sur CivitAI, le
    fichier sur Google Drive, ou l'URL elle-même. None si on ne sait pas en faire un lien."""
    if not isinstance(item, dict):
        return None
    try:
        if item.get("hf"):
            repo = item["hf"].strip("/")
            if item.get("file"):
                path = urllib.parse.quote(item["file"].lstrip("/"))
                return "hf", f"https://huggingface.co/{repo}/blob/{item.get('revision') or 'main'}/{path}"
            return "hf", f"https://huggingface.co/{repo}"
        if item.get("github"):
            repo = github_repo(item["github"])
            if item.get("file"):
                path = urllib.parse.quote(item["file"].lstrip("/"))
                return "github", f"https://github.com/{repo}/blob/{item.get('revision') or 'HEAD'}/{path}"
            return "github", f"https://github.com/{repo}"
        if item.get("civitai"):
            return "civitai", f"https://civitai.com/model-versions/{item['civitai']}"
        if item.get("gdrive"):
            return "gdrive", f"https://drive.google.com/file/d/{gdrive_id(item['gdrive'], '')}/view"
        if item.get("git"):
            url = web_repo_url(item["git"])
            if not url.startswith(("https://", "http://")):
                return None
            site = "github" if "://github.com/" in url else "git"
            if item.get("ref") and site == "github":
                url += f"/tree/{urllib.parse.quote(item['ref'])}"
            return site, url
        if item.get("url"):
            return "url", item["url"]
    except ConfigError:
        pass
    return None


def pip_link(spec):
    """(site, URL) d'un paquet pip : sa page PyPI, ou le dépôt d'une spécification git+URL."""
    match = re.search(r"(?:git\+)?(https?://[^\s@#]+)", spec)
    if match:
        url = web_repo_url(match.group(1))
        return ("github" if "://github.com/" in url else "url"), url
    match = re.match(r"[A-Za-z0-9][A-Za-z0-9._-]*", spec.strip())
    return ("pypi", f"https://pypi.org/project/{match.group(0)}/") if match else None


def target_name(item, where):
    if item.get("name"):
        return item["name"]
    if "hf" in item or "github" in item:
        return Path(item["file"]).name
    raise ConfigError(t("{where} : 'name' (nom du fichier local) requis pour une source url/civitai",
                         where=where))


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


def progress_class():
    """Barre de progression tqdm toujours affichée. Sans terminal (panneau, logs du conteneur),
    tqdm et huggingface_hub la masquent d'office : le téléchargement d'un gros fichier ne
    montrerait rien pendant des minutes. Une mise à jour par seconde au plus ; le panneau
    réécrit la ligne à chaque \r. Une seule barre à la fois, sur une seule ligne : la première
    ouverte (huggingface_hub en ouvre deux pour Xet, la reconstruction du fichier en premier,
    avec le pourcentage). None si tqdm n'est pas installé."""
    try:
        from tqdm import tqdm
    except ImportError:
        return None

    class Progress(tqdm):
        active = False

        def __init__(self, *args, **kwargs):
            kwargs.pop("disable", None)
            kwargs.pop("position", None)  # pas de déplacement du curseur (\x1b[A)
            kwargs.setdefault("mininterval", 1)
            kwargs.setdefault("ncols", 100)
            self.owner = not Progress.active
            Progress.active = True
            super().__init__(*args, disable=not self.owner, **kwargs)

        def close(self):
            super().close()
            if getattr(self, "owner", False):
                self.owner = Progress.active = False

    return Progress


def fetch_url(url, dest):
    part = dest.with_name(dest.name + ".part")
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(req, timeout=60) as resp, part.open("wb") as out:
            bar_class = progress_class()
            total = int(resp.headers.get("Content-Length") or 0) or None
            bar = bar_class(total=total, unit="B", unit_scale=True, unit_divisor=1024,
                            desc=dest.name) if bar_class else None
            try:
                while chunk := resp.read(1024 * 1024):
                    out.write(chunk)
                    if bar:
                        bar.update(len(chunk))
            finally:
                if bar:
                    bar.close()
        part.replace(dest)
    finally:
        part.unlink(missing_ok=True)


def fetch(item, dest, paths):
    dest.parent.mkdir(parents=True, exist_ok=True)
    if "hf" in item:
        from huggingface_hub import hf_hub_download  # lit HF_TOKEN tout seul

        paths.staging.mkdir(parents=True, exist_ok=True)
        options = {}
        if "tqdm_class" in inspect.signature(hf_hub_download).parameters and progress_class():
            options["tqdm_class"] = progress_class()
        try:
            downloaded = hf_hub_download(
                repo_id=item["hf"],
                filename=item["file"],
                revision=item.get("revision"),
                local_dir=paths.staging,
                **options,
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
    """`record` : (chemin, genre) à inscrire au manifeste une fois l'étape réussie."""

    def __init__(self, label, run, record=None):
        self.label = label
        self.run = run
        self.record = record


class Manifest:
    """Ce que le gestionnaire a installé lui-même (custom nodes, modèles, workflows), dans
    <user>/__comfy_profiles/installed.json. Seuls ces éléments sont supprimés par `uninstall`,
    et seuls ces custom nodes changent de version quand `ref` change : un fichier ou un node déjà
    là avant (installé à la main, livré avec ComfyUI ou une image Docker) n'est jamais touché.

    Sans manifeste (première utilisation de cette version), si les custom nodes sont rangés à
    part (COMFY_PROFILES_NODES_STORE), ce qui est déjà présent pour les profils du fichier est
    repris : ce stockage n'est rempli que par le gestionnaire, et c'était le comportement des
    versions précédentes. Sinon, on part d'un manifeste vide."""

    def __init__(self, paths, profiles):
        self.file = paths.data / MANIFEST_NAME
        self.adopted = False
        if self.file.is_file():
            try:
                self.items = json.loads(self.file.read_text()).get("items") or {}
            except (json.JSONDecodeError, AttributeError) as e:
                sys.exit("!! " + t("{path} : JSON invalide ({error})", path=self.file, error=e))
        else:
            self.items = adopt_existing(profiles, paths) if paths.custom_nodes_store != paths.custom_nodes else {}
            self.adopted = bool(self.items)

    def __contains__(self, path):
        return str(path) in self.items

    def add(self, path, kind):
        self.items[str(path)] = kind

    def discard(self, path):
        self.items.pop(str(path), None)

    def save(self):
        self.file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.file.with_name(f".{self.file.name}.tmp")
        tmp.write_text(json.dumps({"version": 1, "items": dict(sorted(self.items.items()))},
                                  ensure_ascii=False, indent=1) + "\n")
        tmp.replace(self.file)


def adopt_existing(profiles, paths):
    items = {}
    for name in profiles:
        try:
            targets = installed_by(resolve(profiles, [name]), paths)
        except (ConfigError, SystemExit):
            continue
        for path, (kind, _, link) in targets.items():
            if present(path, link):
                items[str(path)] = kind
    return items


def file_dest(item, where, section, paths):
    """Chemin local d'un modèle ou d'un workflow."""
    source_of(item, where)
    if section == "workflows":
        return paths.workflows / target_name(item, where)
    if not item.get("type"):
        raise ConfigError(t("{where} : 'type' (sous-dossier, ex: loras) requis", where=where))
    return paths.model_path(item["type"], target_name(item, where))


def file_label(item, section, dest):
    return f"{item['type']}/{dest.name}" if section == "models" else f"workflow/{dest.name}"


def plan_file(item, dest, kind, paths):
    if dest.exists():
        return None
    return Step(f"{describe_source(item)} -> {dest}", lambda: fetch(item, dest, paths),
                record=(dest, kind))


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
    raise ConfigError(t("{where} : 'gdrive' doit être un lien de partage Google Drive ou un id de fichier",
                         where=where))


def extract_encrypted_zip(archive, dest, file_id):
    """Zip chiffré (AES, ex. 7-Zip, ou ZipCrypto) : zipfile ne sait pas lire l'AES, pyzipper si."""
    password = os.environ.get("GDRIVE_ZIP_PASSWORD")
    if not password:
        raise RuntimeError(t("le zip Drive {id} est chiffré : mot de passe attendu dans GDRIVE_ZIP_PASSWORD",
                             id=file_id))
    try:
        import pyzipper
    except ImportError:  # pas installé d'avance : seulement utile aux zips chiffrés
        pip_install(["pyzipper"])
        import pyzipper
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(password.encode())
        try:
            zf.extractall(dest)  # même protection des chemins que zipfile
        except RuntimeError as e:
            raise RuntimeError(t("zip Drive {id} : déchiffrement impossible (GDRIVE_ZIP_PASSWORD erroné ?) : {error}",
                                 id=file_id, error=e)) from None


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
            raise RuntimeError(t("le fichier Drive {id} n'est pas un zip (non public, ou quota de "
                                 "téléchargement Drive dépassé ?)", id=file_id))
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
        raise ConfigError(t("{where} : une (et une seule) source attendue parmi {sources}",
                            where=where, sources="git, gdrive"))
    return item["git"].rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]


def normalize_repo_url(url):
    """github.com/owner/repo pour https://github.com/Owner/Repo.git, git@github.com:owner/repo..."""
    url = re.sub(r"^(git\+)?[a-z]+://", "", url.strip().lower())
    url = re.sub(r"^[^@/]+@([^:/]+):", r"\1/", url)  # git@host:owner/repo
    url = re.sub(r"^[^@/]+@", "", url).removeprefix("www.")
    return url.rstrip("/").removesuffix(".git")


def node_repo_url(path):
    """Dépôt d'un custom node : remote origin de son propre .git (pas celui d'un dépôt parent),
    sinon Repository de son pyproject.toml (node installé depuis le Comfy Registry, sans .git)."""
    git_config = path / ".git" / "config"
    if git_config.is_file():
        match = re.search(r'\[remote "origin"\][^\[]*?^\s*url\s*=\s*(\S+)',
                          git_config.read_text(errors="replace"), re.M)
        if match:
            return match.group(1)
    pyproject = path / "pyproject.toml"
    if pyproject.is_file():
        match = re.search(r'^\s*Repository\s*=\s*"([^"]+)"', pyproject.read_text(errors="replace"),
                          re.M | re.I)
        if match:
            return match.group(1)
    return None


@functools.cache
def installed_nodes(custom_nodes):
    """Custom nodes présents, par nom en minuscules et par dépôt (lu une fois par commande,
    avant toute installation)."""
    index = {}
    if custom_nodes.is_dir():
        for entry in sorted(custom_nodes.iterdir()):
            if not entry.is_dir() or entry.name.startswith((".", "__")):
                continue
            index.setdefault(("name", entry.name.lower()), entry)
            url = node_repo_url(entry)
            if url:
                index.setdefault(("url", normalize_repo_url(url)), entry)
    return index


def installed_elsewhere(name, item, paths):
    """Le même custom node déjà dans custom_nodes/ sous un autre nom, par exemple installé par
    ComfyUI-Manager depuis le Comfy Registry (comfyui-kjnodes pour ComfyUI-KJNodes) : même nom à
    la casse près, ou même dépôt. Laissé tel quel : le cloner une 2e fois le chargerait deux fois."""
    if (paths.custom_nodes / name).exists() or (paths.custom_nodes_store / name).exists():
        return None
    index = installed_nodes(paths.custom_nodes)
    found = index.get(("name", name.lower()))
    if not found and item.get("git"):
        found = index.get(("url", normalize_repo_url(item["git"])))
    return found


def foreign_node(name, paths):
    """Custom node déjà dans custom_nodes/ en vrai dossier alors que le gestionnaire range les
    siens ailleurs (COMFY_PROFILES_NODES_STORE) : livré avec une image Docker ou installé à la
    main. Jamais touché, et ignoré dans l'état des profils."""
    link, store = paths.custom_nodes / name, paths.custom_nodes_store / name
    return link.exists() and not link.is_symlink() and link != store


def plan_custom_node(item, where, paths, manifest):
    url = item.get("git")
    drive = item.get("gdrive")
    if bool(url) == bool(drive):
        raise ConfigError(t("{where} : une (et une seule) source attendue parmi {sources}",
                            where=where, sources="git, gdrive"))
    if drive:
        if not item.get("name"):
            raise ConfigError(t("{where} : 'name' (nom du dossier du custom node) requis avec 'gdrive'",
                                where=where))
        if item.get("ref"):
            raise ConfigError(t("{where} : 'ref' ne s'applique qu'à une source 'git'", where=where))
        file_id = gdrive_id(drive, where)
    name = custom_node_name(item, where)
    store = paths.custom_nodes_store / name
    link = paths.custom_nodes / name
    steps = []

    if foreign_node(name, paths):
        print(f"   [{name}] " + t("déjà présent ({path}), hors gestionnaire : version du profil ignorée",
                                path=link))
        return name, steps

    alias = installed_elsewhere(name, item, paths)
    if alias:
        if alias in manifest:
            message = t("déjà installé sous {alias} ({path}), pris en charge : laissé tel quel",
                        alias=alias.name, path=alias)
        else:
            message = t("déjà installé sous {alias} ({path}), hors gestionnaire : laissé tel quel",
                        alias=alias.name, path=alias)
        print(f"   [{name}] {message}")
        return name, steps

    ref = item.get("ref")
    managed = store in manifest
    record = (store, "custom_node")
    if drive:
        installed = store / GDRIVE_MARKER
        if not store.exists():
            steps.append(Step(t("gdrive:{id} (zip) -> {path}", id=file_id, path=store),
                              lambda: install_gdrive_zip(file_id, store, paths), record))
        elif not installed.is_file() or not managed:
            print(f"   [{name}] " + t("{path} existe mais n'a pas été installé depuis Drive par le gestionnaire, "
                                "laissé tel quel", path=store))
        elif installed.read_text().strip() != file_id:
            steps.append(Step(t("gdrive:{id} (zip, nouveau fichier) remplace {path}", id=file_id, path=store),
                              lambda: install_gdrive_zip(file_id, store, paths), record))
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

        steps.append(Step(f"git clone {url}{'@' + ref if ref else ''} -> {store}", clone, record))
    elif ref and not at_ref(store, ref):
        if managed:
            steps.append(Step(t("git checkout {ref} dans {path}", ref=ref, path=store),
                              lambda: checkout_ref(store, ref)))
        else:
            print(f"   [{name}] " + t("{path} n'a pas été installé par le gestionnaire : ref {ref} ignorée",
                                path=store, ref=ref))

    if link != store and not link.is_symlink():
        def make_link():
            if not store.exists():  # clone ou extraction raté juste avant : pas de lien mort
                raise RuntimeError(t("{path} absent, lien non créé", path=store))
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(store)

        steps.append(Step(t("lien {link} -> {path}", link=link, path=store), make_link))

    # Les dépendances ne sont connues qu'une fois le dépôt cloné : on les évalue à l'exécution.
    def deps():
        requirements = store / "requirements.txt"
        if requirements.is_file():
            m = marker("req", name, requirements.read_text())
            if not m.exists():
                print(f">> [{name}] " + t("installation de requirements.txt"))
                pip_install(["-r", str(requirements)])
                touch(m)
        install_py = store / "install.py"
        if install_py.is_file():
            m = marker("install", name, install_py.read_text())
            if not m.exists():
                print(f">> [{name}] " + t("exécution de install.py"))
                subprocess.run([sys.executable, "install.py"], cwd=store, check=True)
                touch(m)

    # Les dépendances d'un node que le gestionnaire n'a pas installé (Manager, à la main...)
    # restent l'affaire de celui qui l'a installé.
    deps_pending = bool(steps) or managed and any(
        f.is_file() and not marker(kind, name, f.read_text()).exists()
        for kind, f in (("req", store / "requirements.txt"), ("install", store / "install.py"))
    )
    if deps_pending:
        steps.append(Step(t("dépendances de {name} (requirements.txt / install.py)", name=name), deps))
    return name, steps


def build_plan(merged, paths, manifest):
    """Retourne (étapes à exécuter, état de chaque élément : (genre, nom, à installer ?, profil
    qui le déclare, taille déclarée en octets ou None, page de la source ou None : voir
    source_link)). Un élément déclaré par plusieurs profils revient au premier dans l'ordre
    de resolve(), donc au profil hérité plutôt qu'à celui qui en hérite. Valide toute la config
    avant d'agir."""
    steps, status, seen = [], [], set()

    for profile, item in merged["custom_nodes"]:
        where = f"[{profile}] custom_nodes"
        name, node_steps = plan_custom_node(item, where, paths, manifest)
        if name in seen:
            continue
        seen.add(name)
        steps += node_steps
        status.append(("custom_node", name, bool(node_steps), profile, None, source_link(item)))

    specs = {}  # spécification -> premier profil qui la déclare
    for profile, spec in merged["pip"]:
        specs.setdefault(spec, profile)
    missing_specs = [s for s in specs if not marker("pip", "spec", s).exists()]
    for spec, profile in specs.items():
        status.append(("pip", spec, spec in missing_specs, profile, None, pip_link(spec)))
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
            step = plan_file(item, dest, section[:-1], paths)
            size = item.get("size") if isinstance(item, dict) else None
            size = size if isinstance(size, int) and not isinstance(size, bool) else None
            status.append((section[:-1], file_label(item, section, dest), bool(step), profile, size,
                           source_link(item)))
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
    que regrouper d'autres profils (ex. minimax-h3-all-*), est jugé sur les éléments de ses
    parents hors de la base qu'ils ont tous en commun (ex. minimax-h3-common-*) : il est ainsi
    cohérent avec chacun d'eux. À défaut (un seul parent), il reprend l'état de ses parents
    directs : partial si l'un d'eux est installé ou partiel. empty : n'installe aucun fichier (pip seul, ou seulement
    des custom nodes hors gestionnaire, voir foreign_node). error : config invalide."""
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
    extends = profiles[name].get("extends", [])
    if not own and len(extends) > 1:
        base = set.intersection(*(ancestors(profiles, [p]) for p in extends))
        shared = set()
        for parent in base:
            shared.update(installed_by(resolve(profiles, [parent]), paths))
        own = {path: target for path, target in everything.items() if path not in shared}
    if not everything:
        state = "empty"
    elif all(installed(path, link) for path, (_, _, link) in everything.items()):
        state = "installed"
    elif own:
        state = "partial" if any(present(path, link) for path, (_, _, link) in own.items()) else "missing"
    else:
        parents = [profile_state(profiles, p, paths, memo) for p in extends]
        state = "partial" if any(s in ("installed", "partial") for s in parents) else "missing"
    return memo.setdefault(name, state)


def profile_total(profiles, name, paths=None):
    """(total en octets des fichiers, nb de fichiers de taille inconnue), extends compris,
    chaque fichier compté une fois. Les custom nodes et paquets pip ne comptent pas. Avec
    `paths`, seulement les fichiers absents : ce qu'ajouterait l'installation du profil."""
    merged = resolve(profiles, [name])
    total, unknown, seen = 0, 0, set()
    for section in ("models", "workflows"):
        for profile, item in merged[section]:
            where = f"[{profile}] {section}"
            key = (section, item.get("type"), target_name(item, where))
            if key in seen:
                continue
            seen.add(key)
            if paths is not None and file_dest(item, where, section, paths).exists():
                continue
            size = item.get("size")
            if isinstance(size, int) and not isinstance(size, bool):
                total += size
            else:
                unknown += 1
    return total, unknown


def safe_total(profiles, name, paths=None):
    try:
        return profile_total(profiles, name, paths)
    except (ConfigError, SystemExit):
        return 0, 0


def config_location(arg):
    path, source = config_source(arg)
    return {
        "config": str(path.absolute()),
        "source": source,
        "writable": str(writable_config(path, source).absolute()),
        "seed": str(seed_config().absolute()),
    }


def unmanaged_items(profiles, names, paths, manifest):
    """Éléments présents pour ces profils (extends compris) que le gestionnaire n'a pas installés
    lui-même : {chemin: (genre, nom, lien)}. `uninstall` les laisse en place ; `adopt` les prend
    en charge."""
    targets = installed_by(resolve(profiles, names), paths)
    return {path: target for path, target in targets.items()
            if present(path, target[2]) and path not in manifest}


def count_unmanaged(profiles, name, paths, manifest):
    try:
        return len(unmanaged_items(profiles, [name], paths, manifest))
    except (ConfigError, SystemExit):
        return 0


def cmd_list(profiles, args):
    if args.json:
        paths, states = Paths(), {}
        manifest = Manifest(paths, profiles)
        print_json({
            **config_location(args.config),
            "default": split_names(os.environ.get("COMFY_PROFILES")),
            "profiles": {
                name: {
                    "description": profile.get("description", ""),
                    "size": profile.get("size", ""),
                    # Total calculé à partir des tailles des fichiers, pour l'afficher dans la
                    # langue du panneau ; "size" est le texte écrit par profile_sizes.py.
                    **dict(zip(("total", "unknown"), safe_total(profiles, name))),
                    # Part de ce total que l'installation du profil ajouterait (fichiers absents).
                    **dict(zip(("todo", "todo_unknown"), safe_total(profiles, name, paths))),
                    "extends": profile.get("extends", []),
                    "counts": {s: len(profile.get(s, [])) for s in SECTIONS},
                    "state": profile_state(profiles, name, paths, states),
                    "unmanaged": count_unmanaged(profiles, name, paths, manifest),
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
            print("    " + t("taille : {size}", size=profile["size"]))
        if profile.get("description"):
            print(f"    {profile['description']}")
        if counts:
            print("    " + t("propre : {counts}", counts=counts))


def cmd_show(profiles, args):
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! " + t("Indique au moins un profil (voir `list`)"))
    try:
        # Les messages de build_plan (custom nodes laissés tels quels...) ne doivent pas
        # polluer le JSON.
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            paths = Paths()
            manifest = Manifest(paths, profiles)
            _, status = build_plan(resolve(profiles, names), paths, manifest)
            unmanaged = {(kind, label) for kind, label, _ in unmanaged_items(profiles, names, paths, manifest).values()}
    except ConfigError as e:
        sys.exit(f"!! {e}")
    # Regroupés par profil qui les déclare : ceux demandés d'abord, puis les profils hérités
    # dans l'ordre de resolve() (parents avant enfants).
    order = list(dict.fromkeys([*names, *(st[3] for st in status)]))
    status = sorted(status, key=lambda st: order.index(st[3]))
    if args.json:
        print_json([{"kind": kind, "name": name, "missing": missing, "profile": profile,
                     "inherited": profile not in names, "unmanaged": (kind, name) in unmanaged,
                     "size": size, "link": link and {"site": link[0], "url": link[1]}}
                    for kind, name, missing, profile, size, link in status])
        return
    lines, current = [], None
    for kind, name, missing, profile, size, _ in status:
        if profile != current:
            current = profile
            lines.append(f"[{profile}]" + ("" if profile in names else " " + t("(hérité)")))
        todo = t("à télécharger") if kind in ("model", "workflow") else t("à installer")
        state = (todo if missing else t("présent, non pris en charge") if (kind, name) in unmanaged
                 else t("présent"))
        shown = (human_size(size) if size is not None else "?") if kind in ("model", "workflow") else ""
        lines.append(f"  {kind:<12} {name:<40} {shown:>9}  {state}")
    print("\n".join(lines) or t("(profil vide)"))


def cmd_sync(profiles, args):
    names = split_names(args.profiles or os.environ.get("COMFY_PROFILES"))
    if not names:
        print(">> " + t("Aucun profil demandé (argument ou COMFY_PROFILES), rien à faire."))
        return 0
    paths = Paths()
    manifest = Manifest(paths, profiles)
    try:
        steps, _ = build_plan(resolve(profiles, names), paths, manifest)
    except ConfigError as e:
        sys.exit(f"!! {e}")

    print(">> " + t("Profils : {names} — {n} action(s) à faire", names=", ".join(names), n=len(steps)))
    print(">> " + t("Modèles -> {path}", path=paths.models))
    if not steps:
        return 0
    if args.dry_run:
        for step in steps:
            print(f"   [dry-run] {step.label}")
        return 0
    if manifest.adopted:
        manifest.save()
        print(">> " + t("{path} créé : {n} élément(s) déjà présent(s) repris.",
                        path=manifest.file, n=len(manifest.items)))
    print(">> " + (t("HF_TOKEN détecté.") if os.environ.get("HF_TOKEN")
                   else t("Pas de HF_TOKEN : téléchargements HF anonymes.")))

    failures = []
    for i, step in enumerate(steps, 1):
        print(f">> ({i}/{len(steps)}) {step.label}", flush=True)
        try:
            step.run()
            if step.record:
                manifest.add(*step.record)
                manifest.save()
        except KeyboardInterrupt:
            print("!! " + t("Synchronisation interrompue ({done}/{total} action(s) faite(s)).",
                            done=i - 1, total=len(steps)), file=sys.stderr)
            return 130
        except Exception as e:  # une étape ratée ne doit pas bloquer les suivantes
            print("!! " + t("Échec : {error}", error=e), file=sys.stderr)
            failures.append(step.label)

    if failures:
        print("!! " + t("{n} échec(s) sur {total} :", n=len(failures), total=len(steps)), file=sys.stderr)
        for label in failures:
            print(f"   - {label}", file=sys.stderr)
        return 1
    print(">> " + t("Synchronisation terminée."))
    return 0


# --- Prise en charge ----------------------------------------------------------------------

def mark_deps_installed(name, store):
    """Le node fonctionnait déjà : ses dépendances (requirements.txt, install.py) sont notées
    comme installées dans ce venv, sans quoi sync voudrait les réinstaller."""
    for kind, f in (("req", store / "requirements.txt"), ("install", store / "install.py")):
        if f.is_file():
            touch(marker(kind, name, f.read_text()))


def cmd_adopt(profiles, args):
    """Inscrit au manifeste ce qui est déjà présent pour des profils (extends compris) sans
    avoir été installé par le gestionnaire : `uninstall` pourra ensuite le supprimer, et `sync`
    changer la version (ref) de ses custom nodes. Les custom nodes livrés avec une image
    (foreign_node) restent exclus."""
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! " + t("Indique au moins un profil (voir `list`)"))
    paths = Paths()
    manifest = Manifest(paths, profiles)
    try:
        items = unmanaged_items(profiles, names, paths, manifest)
    except ConfigError as e:
        sys.exit(f"!! {e}")
    if not args.dry_run and items:
        for path, (kind, label, _) in items.items():
            manifest.add(path, kind)
            if kind == "custom_node":
                mark_deps_installed(label, path)
        manifest.save()
    if args.json:
        print_json({"adopted": [{"kind": kind, "name": label} for kind, label, _ in items.values()],
                    "dry_run": args.dry_run})
        return 0
    if args.dry_run:
        print(">> " + t("{names} : {n} élément(s) seraient pris en charge", names=", ".join(names), n=len(items)))
    else:
        print(">> " + t("{names} : {n} élément(s) pris en charge", names=", ".join(names), n=len(items)))
    for kind, label, _ in items.values():
        print(f"   {'[dry-run] ' if args.dry_run else ''}{kind:<12} {label}")
    if items and not args.dry_run:
        print(">> " + t("La désinstallation de ces profils pourra désormais les supprimer."))
    return 0


# --- Désinstallation ----------------------------------------------------------------------

def installed_by(merged, paths):
    """Ce qu'installent des profils : {chemin: (genre, nom, lien du custom node ou None)}.
    Les custom nodes hors gestionnaire (foreign_node) n'en font pas partie."""
    targets = {}
    for profile, item in merged["custom_nodes"]:
        name = custom_node_name(item, f"[{profile}] custom_nodes")
        if foreign_node(name, paths):
            continue
        alias = installed_elsewhere(name, item, paths)
        if alias:  # jamais dans le manifeste : compte comme présent, jamais supprimé
            targets.setdefault(alias, ("custom_node", name, None))
        else:
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


def remove(path, link, paths):
    if link is not None and link.is_symlink():
        link.unlink()
    if path.is_dir() and not path.is_symlink():
        shutil.rmtree(path)
    else:
        path.unlink(missing_ok=True)
    # Sous-dossiers de modèles devenus vides (ex. diffusion_models/krea2).
    roots = paths.model_roots()
    parent = path.parent
    while (parent not in roots and parent.parent not in roots and roots & set(parent.parents)
           and not any(parent.iterdir())):  # models/<type>/ reste, même vide
        parent.rmdir()
        parent = parent.parent


def own_items(profiles, names):
    """Comme resolve(), mais seulement les éléments écrits dans les profils eux-mêmes, sans
    ceux dont ils héritent (extends)."""
    resolve(profiles, names)  # valide les noms et les extends
    return {section: [(name, item) for name in names for item in profiles[name].get(section, [])]
            for section in SECTIONS}


def plan_uninstall(profiles, names, paths, manifest, with_extends=False):
    """Ce que supprime la désinstallation de `names`. Un élément est conservé s'il sert encore à
    un profil qu'on garde : un profil de COMFY_PROFILES (réinstallé à chaque démarrage), ou un
    autre profil complètement installé. Ce que le gestionnaire n'a pas installé (absent du
    manifeste) reste.

    Par défaut, seuls les éléments propres à `names` partent : les profils dont ils héritent
    (extends) sont des profils gardés comme les autres. Avec `with_extends`, ces profils
    hérités sont désinstallés aussi (ils ne protègent donc rien) : leurs éléments partent,
    sauf s'ils servent à un autre profil gardé."""
    startup = split_names(os.environ.get("COMFY_PROFILES"))
    if with_extends:
        inherited = ancestors(profiles, names)
        targets = installed_by(resolve(profiles, names), paths)
    else:
        inherited = set(names)
        targets = installed_by(own_items(profiles, names), paths)

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

    removed, kept, unmanaged = [], [], []
    for path, (kind, label, link) in targets.items():
        if not present(path, link):
            continue
        if path in needed:
            kept.append({"kind": kind, "name": label, "by": needed[path]})
        elif path not in manifest:
            unmanaged.append({"kind": kind, "name": label})
        else:
            removed.append({"kind": kind, "name": label, "size": disk_size(path),
                            "path": path, "link": link})
    return {
        "remove": removed,
        "kept": kept,
        "unmanaged": unmanaged,
        # Seulement ceux qui protègent effectivement quelque chose.
        "keep_profiles": [n for n in keep if any(n in k["by"] for k in kept)],
        "startup": [n for n in names if n in startup],
        "with_extends": with_extends,
        # Profils dont héritent ceux qu'on désinstalle : laissés en place sans with_extends.
        "extends": sorted(ancestors(profiles, names) - set(names)),
    }


def cmd_uninstall(profiles, args):
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! " + t("Indique au moins un profil (voir `list`)"))
    paths = Paths()
    manifest = Manifest(paths, profiles)
    try:
        plan = plan_uninstall(profiles, names, paths, manifest, args.with_extends)
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

    values = {"names": ", ".join(names), "n": len(removed), "size": human_size(freed)}
    if args.with_extends:
        print(">> " + t("Désinstallation : {names} (extends compris) — {n} élément(s), {size}", **values))
    else:
        print(">> " + t("Désinstallation : {names} — {n} élément(s), {size}", **values))
    if plan["extends"] and not args.with_extends:
        print(">> " + t("Profils hérités laissés en place : {names} (--with-extends pour les inclure)",
                        names=", ".join(plan["extends"])))
    if plan["keep_profiles"]:
        print(">> " + t("Profils gardés (leurs éléments ne sont pas supprimés) : {names}",
                        names=", ".join(plan["keep_profiles"])))
    kept = t("conservé")
    for k in plan["kept"]:
        print(f"   {kept}  {k['kind']:<12} {k['name']}  " + t("(utilisé par {names})", names=", ".join(k["by"])))
    for u in plan["unmanaged"]:
        print(f"   {kept}  {u['kind']:<12} {u['name']}  " + t("(pas installé par le gestionnaire)"))
    for name in plan["startup"]:
        print("!! " + t("{name} est dans COMFY_PROFILES : il sera réinstallé au prochain démarrage.", name=name))
    if not removed:
        print(">> " + t("Rien à supprimer."))
        return 0
    if manifest.adopted and not args.dry_run:
        manifest.save()

    for i, r in enumerate(removed, 1):
        label = f"{r['kind']:<12} {r['name']}  ({human_size(r['size'])})"
        if args.dry_run:
            print("   [dry-run] " + t("supprimer {item}", item=label))
            continue
        print(f">> ({i}/{len(removed)}) " + t("supprimer {item}", item=label), flush=True)
        try:
            remove(r["path"], r["link"], paths)
            manifest.discard(r["path"])
            manifest.save()
        except KeyboardInterrupt:
            print("!! " + t("Désinstallation interrompue ({done}/{total} supprimé(s)).",
                            done=i - 1, total=len(removed)), file=sys.stderr)
            return 130
        except OSError as e:
            print("!! " + t("Échec : {error}", error=e), file=sys.stderr)
            return 1
    if args.dry_run:
        return 0
    print(">> " + t("Désinstallation terminée : {size} libérés.", size=human_size(freed)))
    if any(r["kind"] == "custom_node" for r in removed):
        print(">> " + t("Des custom nodes ont été supprimés : redémarre ComfyUI pour les décharger."))
    print(">> " + t("Les paquets pip installés pour ces profils restent dans le venv."))
    return 0


def main():
    parser = argparse.ArgumentParser(
        description=doc(__doc__, "comfy_profiles"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", help=t("fichier de profils (défaut : $COMFY_PROFILES_CONFIG, "
                                           "<user>/__comfy_profiles/profiles.json, sinon le modèle)"))
    sub = parser.add_subparsers(dest="command", required=True)
    lst = sub.add_parser("list", help=t("liste les profils disponibles"))
    lst.add_argument("--json", action="store_true", help=t("sortie JSON"))
    sub.add_parser("where", help=t("fichier de profils utilisé, son origine et où l'enregistrer (JSON, sans le lire)"))
    show = sub.add_parser("show", help=t("détaille ce qu'installent des profils, et ce qui est déjà là"))
    show.add_argument("profiles")
    show.add_argument("--json", action="store_true", help=t("sortie JSON"))
    sync = sub.add_parser("sync", help=t("installe ce qui manque pour des profils"))
    sync.add_argument("profiles", nargs="?", help=t("défaut : $COMFY_PROFILES"))
    sync.add_argument("--dry-run", action="store_true", help=t("affiche les actions sans rien faire"))
    adopt = sub.add_parser("adopt", help=t("prend en charge ce qui est déjà présent pour des profils "
                                           "(uninstall pourra le supprimer)"))
    adopt.add_argument("profiles")
    adopt.add_argument("--dry-run", action="store_true", help=t("affiche ce qui serait pris en charge"))
    adopt.add_argument("--json", action="store_true", help=t("sortie JSON"))
    uninstall = sub.add_parser("uninstall", help=t("supprime ce qu'ont installé des profils (sauf ce qui sert encore)"))
    uninstall.add_argument("profiles")
    uninstall.add_argument("--dry-run", action="store_true", help=t("affiche ce qui serait supprimé"))
    uninstall.add_argument("--with-extends", action="store_true",
                           help=t("désinstalle aussi les profils dont ils héritent (extends)"))
    uninstall.add_argument("--json", action="store_true", help=t("sortie JSON (implique --dry-run)"))
    args = parser.parse_args()
    if args.command == "where":
        print_json(config_location(args.config))
        return

    path, source = config_source(args.config)
    as_json = getattr(args, "json", False)
    note = " " + t("(modèle, lecture seule)") if source == "seed" else ""
    print(">> " + t("Config : {path}", path=path) + note, file=sys.stderr if as_json else sys.stdout)
    with contextlib.redirect_stdout(sys.stderr if as_json else sys.stdout):
        profiles = load_profiles(path, source)
    commands = {"list": cmd_list, "show": cmd_show, "sync": cmd_sync, "uninstall": cmd_uninstall,
                "adopt": cmd_adopt}
    sys.exit(commands[args.command](profiles, args) or 0)


if __name__ == "__main__":
    main()
