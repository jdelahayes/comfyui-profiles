#!/usr/bin/env python3
"""ComfyUI usage profiles: each profile describes the models, custom nodes, workflows and pip
packages it needs. `sync` installs what is missing and never touches what is already there —
safe to run again and again (for instance at each container startup, for the profiles in
COMFY_PROFILES).

Usage:
  comfy_profiles.py [--config FILE] list [--json]
  comfy_profiles.py [--config FILE] where
  comfy_profiles.py [--config FILE] show PROFILE[,PROFILE...] [--json]
  comfy_profiles.py [--config FILE] sync [PROFILE[,PROFILE...]] [--update] [--jobs N] [--dry-run]
  comfy_profiles.py [--config FILE] uninstall PROFILE[,PROFILE...] [--with-extends] [--dry-run] [--json]
  comfy_profiles.py [--config FILE] adopt PROFILE[,PROFILE...] [--dry-run] [--json]
  comfy_profiles.py [--config FILE] sizes [--env FILE] [--force] [--dry-run]
  comfy_profiles.py settings [--set JSON] [--reset] [--clean-partials] [--json]

Profiles file, the first one found:
  1. --config FILE
  2. $COMFY_PROFILES_CONFIG (if missing, the template is copied there first)
  3. <user>/__comfy_profiles/profiles.json: the one written by editing and importing in the panel
  4. the template, read-only: $COMFY_PROFILES_SEED, otherwise examples/profiles.example.json
Profiles synced by default: $COMFY_PROFILES (comma-separated).
Variants: a profile declaring "variants" (e.g. int8, fp8, bf16) is named with the ones to
install between brackets: krea2-turbo[int8], krea2-raw[int8,bf16]. Without brackets, its
"default_variant" is installed, or only its common items (those without "variant") if it has
none.
`sync --update` also updates what the manager installed or took over (see Manifest), if it
changed at the source: git custom nodes (latest commit of their branch) or Drive ones (different
zip), models and workflows (Hugging Face or HTTP ETag; never CivitAI, whose files don't change),
pip packages (--upgrade). A custom node modified in place is left alone.
`uninstall` removes the models, workflows and custom nodes of the profiles themselves (with
--with-extends: also those of the profiles they inherit from), except those still needed by
another installed profile and those the manager did not install itself. pip packages stay in
the venv.
Downloads: models and workflows are downloaded several at a time (--jobs, otherwise the `jobs`
setting, see `settings`), custom nodes and pip packages first, one by one. An interrupted
CivitAI, GitHub, URL or Drive download leaves a .part file, resumed where it stopped by the
next sync; a network drop is resumed right away. Hugging Face goes through huggingface_hub
(Xet), which starts over.
Ctrl+C (SIGINT) stops `sync`: the current clone is abandoned without leaving an incomplete
folder, downloads keep their .part.
`settings`: download settings, in <user>/__comfy_profiles/settings.json (edited by the panel,
see DOWNLOAD_SETTINGS), and partial downloads (--clean-partials: deletes them). Result as JSON.
`sizes`: queries the size of each file at its source (Hugging Face, CivitAI, HTTP), without
downloading anything, and writes it in the profiles file with each profile's total (one per
variant), into the user's file when the config is the template; also the sha256 of the models
when the source gives it (Hugging Face LFS, CivitAI), then reports the same file installed in
two places. Only the files without a size (or without a sha256 the source gives) are queried
(--force: all of them). Tokens: $HF_TOKEN (otherwise the one from
`hf auth login`) and $CIVITAI_TOKEN, otherwise those of the --env file (a deployment .env).
--json (list, show, uninstall): result as JSON on stdout, information messages on stderr (used
by the Profiles panel in ComfyUI).

Destinations (the panel passes ComfyUI's own paths; on the command line they are derived from
$COMFY_HOME, otherwise from the ComfyUI this repository is a custom node of):
  models       -> $COMFY_MODELS_DIR/<type>/            (default: $COMFY_HOME/models)
  custom nodes -> $COMFY_PROFILES_NODES_STORE/<name>, linked in $COMFY_CUSTOM_NODES_DIR/
                  (default: directly in $COMFY_HOME/custom_nodes/); cloned from git, or
                  extracted from a public zip on Google Drive (encrypted or not: password in
                  $GDRIVE_ZIP_PASSWORD)
  workflows    -> $COMFY_USER_DIR/default/workflows/   (default: $COMFY_HOME/user)
Python dependencies (custom nodes, pip) are installed in the Python running this script and
recorded in its environment (venv): a new container reinstalls them, even if the custom nodes
are already on a persistent volume.

Messages language: $COMFY_PROFILES_LANG, otherwise $LC_ALL, $LC_MESSAGES or $LANG (en, fr).
"""
import argparse
import collections
import concurrent.futures
import contextlib
import errno
import functools
import hashlib
import http.client
import importlib.metadata
import inspect
import json
import os
import re
import shutil
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path

from profiles_i18n import doc, human_size, t

HERE = Path(__file__).resolve().parent
EXAMPLE_CONFIG = HERE / "examples" / "profiles.example.json"
# ComfyUI "System User" folder (__ prefix): never served by its HTTP routes (/api/userdata...),
# only this module reads and writes there. Holds the user's profiles file and the manifest of
# what was installed.
DATA_DIR_NAME = "__comfy_profiles"
CONFIG_NAME = "profiles.json"
MANIFEST_NAME = "installed.json"
VERSIONS_NAME = "versions.json"
SETTINGS_NAME = "settings.json"
SECTIONS = ("custom_nodes", "pip", "models", "workflows")
# "size": total computed by `sizes` (informative, ignored by sync).
PROFILE_KEYS = {"description", "size", "extends", "variants", "default_variant", *SECTIONS}
# Reference to a profile: its name, optionally followed by the variants to install between
# brackets (krea2-turbo[int8], krea2-raw[int8,bf16]; krea2-raw[]: common items only).
PROFILE_REF = re.compile(r"([\w.-]+)(?:\[([\w.,\s-]*)\])?")
VARIANT_NAME = re.compile(r"[\w.-]+")
SOURCES = ("hf", "github", "url", "civitai")
# Cloudflare (in front of civitai.com notably) rejects urllib's default User-Agent.
USER_AGENT = "comfyui-profiles"
# HTTP downloads (CivitAI, GitHub, URL, Drive): retries after a network drop.
HTTP_RETRIES = 5
# In the venv, hence specific to this container: a new container reinstalls the dependencies.
MARKER_DIR = Path(sys.prefix) / ".comfy-profiles"


class ConfigError(Exception):
    pass


def env_path(name, default):
    return Path(os.environ.get(name) or default)


def default_comfy_home():
    """The ComfyUI this repository is a custom node of (<ComfyUI>/custom_nodes/comfyui-profiles)."""
    return HERE.parent.parent if HERE.parent.name == "custom_nodes" else None


class Paths:
    def __init__(self):
        home = os.environ.get("COMFY_HOME") or default_comfy_home()
        if not home:
            sys.exit("!! " + t("Unknown ComfyUI folder: set it in COMFY_HOME"))
        self.comfy_home = Path(home)
        self.models = env_path("COMFY_MODELS_DIR", self.comfy_home / "models")
        self.custom_nodes = env_path("COMFY_CUSTOM_NODES_DIR", self.comfy_home / "custom_nodes")
        # Somewhere other than custom_nodes/ (e.g. a persistent volume): each node is cloned
        # there, then linked in custom_nodes/.
        self.custom_nodes_store = env_path("COMFY_PROFILES_NODES_STORE", self.custom_nodes)
        self.user = env_path("COMFY_USER_DIR", self.comfy_home / "user")
        self.workflows = self.user / "default" / "workflows"
        self.data = self.user / DATA_DIR_NAME
        # Outside the <type>/ subfolders: never scanned by ComfyUI.
        self.staging = self.models / ".staging"
        self.model_folders = model_folders(self)

    def model_path(self, type_, name):
        """Path of a model of type `type_` (e.g. loras, diffusion_models/krea2): where it already
        is, in one of the folders ComfyUI scans for this type (extra_model_paths.yaml
        included), otherwise in the first of these folders named after the type (e.g.
        comfyModels/diffusion_models rather than comfyModels/unet), otherwise in the first one."""
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
        """Top-level model folders (never removed, even when empty)."""
        return {self.models, *(Path(b) for paths in self.model_folders.values() for b in paths)}


# Legacy model folder names, as in ComfyUI (folder_paths.map_legacy).
LEGACY_FOLDERS = {"unet": "diffusion_models", "clip": "text_encoders"}
# ComfyUI default folders that are not simply named models/<type>.
DEFAULT_MODEL_SUBDIRS = {"diffusion_models": ["unet", "diffusion_models"],
                         "text_encoders": ["text_encoders", "clip"],
                         "controlnet": ["controlnet", "t2i_adapter"]}


def model_folders(paths):
    """{type: [folders, in ComfyUI's order]}. From the panel: the server's own list
    ($COMFY_MODEL_FOLDERS). On the command line: the default folders, completed by
    <ComfyUI>/extra_model_paths.yaml and $COMFY_EXTRA_MODEL_PATHS (files separated by ":", like
    --extra-model-paths-config), read the way ComfyUI does."""
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
        print("!! " + t("pyyaml not installed: {files} ignored", files=", ".join(map(str, configs))),
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
    """Template profiles file: the one provided by the environment (e.g. a Docker image),
    otherwise this repository's example."""
    return Path(os.environ.get("COMFY_PROFILES_SEED") or EXAMPLE_CONFIG)


def config_source(arg):
    """(profiles file, origin); origin: option (--config), env (COMFY_PROFILES_CONFIG), user
    (<user>/__comfy_profiles) or seed (template, read-only)."""
    if arg:
        return Path(arg), "option"
    if os.environ.get("COMFY_PROFILES_CONFIG"):
        return Path(os.environ["COMFY_PROFILES_CONFIG"]), "env"
    user = Paths().data / CONFIG_NAME
    if user.is_file():
        return user, "user"
    return seed_config(), "seed"


def writable_config(path, source):
    """Where to save a change: never in the template, but in the user's file, which then takes
    over."""
    return Paths().data / CONFIG_NAME if source == "seed" else path


def is_comment(key):
    return key.startswith("//")


def load_profiles(path, source="option"):
    if not path.is_file():
        seed = seed_config()
        if source in ("option", "env") and path != seed and seed.is_file():
            path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy(seed, path)
            print(">> " + t("{path} missing: copying the template ({seed}).", path=path, seed=seed))
        else:
            sys.exit("!! " + t("Config file not found: {path}", path=path))
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as e:
        sys.exit("!! " + t("{path}: invalid JSON ({error})", path=path, error=e))
    profiles = data.get("profiles")
    if not isinstance(profiles, dict) or not profiles:
        sys.exit("!! " + t("{path}: 'profiles' object missing or empty", path=path))
    for name, profile in profiles.items():
        unknown = {k for k in profile if not is_comment(k)} - PROFILE_KEYS
        if unknown:
            sys.exit("!! " + t("Profile '{name}': unknown key(s) {keys} (expected: {expected})",
                               name=name, keys=sorted(unknown), expected=", ".join(sorted(PROFILE_KEYS))))
        check_variants(name, profile)
    return profiles


# --- Variants -----------------------------------------------------------------------------
# A profile may declare variants (e.g. int8, fp8, bf16 of the same models): "variants" lists
# them, each item tagged with "variant" (a name or a list of names) belongs to these variants
# only, the others are common to all of them. "default_variant": the variant installed when the
# profile is named without brackets; without it, only the common items are.

def item_variants(item):
    tags = item.get("variant") if isinstance(item, dict) else None
    return [tags] if isinstance(tags, str) else list(tags or [])


def check_variants(name, profile):
    variants = profile.get("variants", [])
    if (not isinstance(variants, list) or len(set(variants)) != len(variants)
            or not all(isinstance(v, str) and VARIANT_NAME.fullmatch(v) for v in variants)):
        sys.exit("!! " + t("Profile '{name}': 'variants' must be a list of distinct names", name=name))
    default = profile.get("default_variant")
    if default is not None and default not in variants:
        sys.exit("!! " + t("Profile '{name}': default_variant '{variant}' is not in 'variants'",
                           name=name, variant=default))
    for section in SECTIONS:
        for item in profile.get(section, []):
            unknown = [v for v in item_variants(item) if v not in variants]
            if unknown:
                sys.exit("!! " + t("Profile '{name}': unknown variant(s) {variants} in {section} "
                                   "(declared: {available})", name=name, variants=", ".join(map(str, unknown)),
                                   section=section, available=", ".join(variants) or "-"))


def split_names(value):
    """Profile references separated by commas, except those between brackets."""
    return [n.strip() for n in re.split(r",(?![^\[]*\])", value or "") if n.strip()]


def parse_ref(ref):
    """(profile name, variants between brackets, or None without brackets)."""
    match = PROFILE_REF.fullmatch(ref.strip())
    if not match:
        return ref, None
    if match.group(2) is None:
        return match.group(1), None
    return match.group(1), [v.strip() for v in match.group(2).split(",") if v.strip()]


def make_ref(name, variants):
    return f"{name}[{','.join(variants)}]"


def selected(profiles, ref):
    """(profile name, variants to install, in the declared order): those of the reference,
    otherwise the default variant (none without default_variant: common items only)."""
    name, variants = parse_ref(ref)
    if name not in profiles:
        sys.exit("!! " + t("Unknown profile: '{name}' (available: {available})",
                           name=name, available=", ".join(profiles)))
    profile = profiles[name]
    declared = profile.get("variants", [])
    if variants is None:
        return name, [profile["default_variant"]] if profile.get("default_variant") else []
    unknown = [v for v in variants if v not in declared]
    if unknown:
        sys.exit("!! " + t("Profile '{name}': unknown variant(s) {variants} (available: {available})",
                           name=name, variants=", ".join(unknown), available=", ".join(declared) or "-"))
    return name, [v for v in declared if v in variants]


def parent_ref(profiles, parent, name, variants):
    """Reference of a profile `name` inherits from (extends), `variants` being those selected
    for it. A parent named without brackets that declares variants follows the child's ones
    (those it has: krea2-raw[bf16] -> its parent's bf16), provided the child has variants;
    otherwise, it gets its own default variant. Brackets in `extends` take precedence."""
    parent_name, explicit = parse_ref(parent)
    if (explicit is not None or not profiles[name].get("variants")
            or parent_name not in profiles or not profiles[parent_name].get("variants")):
        return parent
    return make_ref(parent_name, [v for v in profiles[parent_name]["variants"] if v in variants])


def canonical(profiles, ref):
    """Same reference with its variants written out: krea2-turbo -> krea2-turbo[int8]."""
    name, variants = selected(profiles, ref)
    return make_ref(name, variants) if profiles[name].get("variants") else name


def all_variants(profiles, name):
    """The profile with all its variants."""
    variants = profiles[name].get("variants")
    return make_ref(name, variants) if variants else name


def variant_refs(profiles):
    """What can be installed on its own: each profile, each variant for a profile with
    variants."""
    for name, profile in profiles.items():
        if profile.get("variants"):
            yield from (make_ref(name, [v]) for v in profile["variants"])
        else:
            yield name


def units(profiles, refs):
    """(profile, variant) parts of some references, None for the common items."""
    found = set()
    for ref in refs:
        name, variants = selected(profiles, ref)
        found.update([(name, None), *((name, v) for v in variants)])
    return found


def own_part(profiles, name, variants, section, common=True):
    """(label, item) written in the profile itself for these variants: the common items (unless
    `common` is false) labelled with its name, those of the variants with name[variant]."""
    for item in profiles[name].get(section, []):
        tags = item_variants(item)
        if not tags:
            if common:
                yield name, item
        elif hits := [v for v in variants if v in tags]:
            yield make_ref(name, hits), item


def resolve(profiles, names):
    """Merges the requested profiles (references, see selected) and their `extends` (parents
    first, each part once)."""
    merged = {section: [] for section in SECTIONS}
    visited = set()  # (profile, variant or None for the common items)

    def visit(ref, stack):
        name, _ = parse_ref(ref)
        if name in stack:
            sys.exit("!! " + t("Cycle in 'extends': {cycle}", cycle=" -> ".join([*stack, name])))
        _, variants = selected(profiles, ref)
        first = (name, None) not in visited
        variants = [v for v in variants if (name, v) not in visited]
        visited.update([(name, None), *((name, v) for v in variants)])
        for parent in profiles[name].get("extends", []):
            # Each time: new variants of the profile may bring new variants of its parents.
            if first or variants:
                visit(parent_ref(profiles, parent, name, variants), [*stack, name])
        for section in SECTIONS:
            merged[section] += own_part(profiles, name, variants, section, common=first)

    for name in names:
        visit(name, [])
    return merged


# --- Downloads ----------------------------------------------------------------------------

def source_of(item, where):
    found = [k for k in SOURCES if k in item]
    if len(found) != 1:
        raise ConfigError(t("{where}: exactly one source expected among {sources}",
                             where=where, sources=", ".join(SOURCES)))
    if found[0] in ("hf", "github") and not item.get("file"):
        raise ConfigError(t("{where}: 'file' (path in the repository) required with '{source}'",
                             where=where, source=found[0]))
    if found[0] == "github":
        github_repo(item["github"], where)
    return found[0]


def github_repo(value, where=""):
    """'owner/repo' from 'owner/repo' or a GitHub repository URL."""
    repo = re.sub(r"^(https?://)?github\.com/", "", value.strip()).rstrip("/").removesuffix(".git")
    if not re.fullmatch(r"[\w.-]+/[\w.-]+", repo):
        raise ConfigError(t("{where}: 'github' must be 'owner/repo' or the URL of a GitHub repository",
                             where=where))
    return repo


def github_file_url(item):
    """URL of a single file of the repository (without cloning it). /raw/ on github.com redirects
    to raw.githubusercontent.com, or to media.githubusercontent.com for a Git LFS file."""
    rev = item.get("revision") or "HEAD"
    path = urllib.parse.quote(item["file"].lstrip("/"))
    return f"https://github.com/{github_repo(item['github'])}/raw/{rev}/{path}"


def web_repo_url(url):
    """Web page of a git repository: https://host/owner/repo for git@host:owner/repo.git..."""
    url = re.sub(r"^git\+", "", url.strip())
    url = re.sub(r"^[^@/:]+@([^:/]+):", r"https://\1/", url)  # git@host:owner/repo
    return url.rstrip("/").removesuffix(".git")


def source_link(item):
    """(site, URL of the source page) of a model, workflow or custom node, for the panel: the
    repository or file on Hugging Face or GitHub, the version on CivitAI, the file on Google
    Drive, or the URL itself. None if no link can be made from it."""
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
    """(site, URL) of a pip package: its PyPI page, or the repository of a git+URL spec."""
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
    raise ConfigError(t("{where}: 'name' (local file name) required for a url/civitai source",
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


# Output shared by the parallel downloads (see out and Progress).
_output_lock = threading.RLock()
# Ctrl+C during the parallel downloads: HTTP ones stop at the next block.
CANCEL = threading.Event()
# File being downloaded in this thread (name shown by the Hugging Face progress).
_current = threading.local()


class Progress:
    """A single progress line for all the running downloads: cumulative percentage and size,
    throughput (average over the last seconds), file names. At most one update per second,
    rewritten with \\r: the panel then replaces the line. Several tqdm bars at once would be
    unreadable in the panel, and both tqdm and huggingface_hub hide them by default without a
    terminal (panel, container logs)."""

    INTERVAL = 1.0
    WINDOW = 5.0
    NAMES_WIDTH = 80

    def __init__(self):
        self.tasks = {}  # id -> [name, bytes written, total or None]
        self.next_id = 0
        self.shown = 0  # length of the line shown, 0 if none
        self.last = 0.0
        self.received = 0  # bytes written since the start, all files together
        self.samples = collections.deque()  # (instant, received)

    def start(self, name, total=None, done=0):
        with _output_lock:
            self.next_id += 1
            self.tasks[self.next_id] = [name, done, total]
            return self.next_id

    def update(self, task, done, total=None):
        with _output_lock:
            entry = self.tasks.get(task)
            if entry is None:
                return
            self.received += max(0, done - entry[1])
            entry[1] = done
            entry[2] = total or entry[2]
            self.render()

    def finish(self, task):
        with _output_lock:
            self.tasks.pop(task, None)
            if not self.tasks:
                self.clear()

    def clear(self):
        """Clears the progress line, before writing something else."""
        if self.shown:
            sys.stdout.write("\r" + " " * self.shown + "\r")
            sys.stdout.flush()
            self.shown = 0
            self.last = 0.0  # shown again at the next update

    def render(self):
        now = time.monotonic()
        if not self.tasks or now - self.last < self.INTERVAL:
            return
        self.last = now
        self.samples.append((now, self.received))
        while now - self.samples[0][0] > self.WINDOW:
            self.samples.popleft()
        since, before = self.samples[0]
        rate = (self.received - before) / (now - since) if now > since else 0
        tasks = list(self.tasks.values())
        done = sum(task[1] for task in tasks)
        totals = [task[2] for task in tasks]
        parts = [tasks[0][0] if len(tasks) == 1 else t("{n} files", n=len(tasks))]
        if all(totals):
            total = sum(totals)
            parts.append(f"{done * 100 // total}% {human_size(done)}/{human_size(total)}")
        else:
            parts.append(human_size(done))
        if rate:
            parts.append(t("{size}/s", size=human_size(int(rate))))
        if len(tasks) > 1:
            names = ", ".join(task[0] for task in tasks)
            parts.append(names if len(names) <= self.NAMES_WIDTH else names[:self.NAMES_WIDTH - 1] + "…")
        line = "   ↓ " + " · ".join(parts)
        sys.stdout.write("\r" + line.ljust(self.shown))
        sys.stdout.flush()
        self.shown = len(line)


PROGRESS = Progress()


def out(text="", err=False):
    """print() that first clears the downloads' progress line."""
    with _output_lock:
        PROGRESS.clear()
        print(text, file=sys.stderr if err else sys.stdout, flush=True)


class _Discard:
    def write(self, _text):
        pass

    def flush(self):
        pass


@functools.cache
def hub_progress_class():
    """tqdm class passed to hf_hub_download: it feeds PROGRESS instead of showing a bar. For Xet,
    huggingface_hub opens two per file: only the first one opened in the thread counts, the file
    reconstruction (bytes written, with the total). None without tqdm."""
    try:
        from tqdm import tqdm
    except ImportError:
        return None

    class HubProgress(tqdm):
        def __init__(self, *args, **kwargs):
            for key in ("disable", "position", "name", "file"):
                kwargs.pop(key, None)
            kwargs.setdefault("mininterval", 1)
            super().__init__(*args, file=_Discard(), **kwargs)
            self.task = None
            if not getattr(_current, "busy", False):
                _current.busy = True
                self.task = PROGRESS.start(getattr(_current, "name", "?"), self.total, self.n)

        def update(self, n=1):
            displayed = super().update(n)
            if self.task:
                PROGRESS.update(self.task, self.n, self.total)
            return displayed

        def close(self):
            if getattr(self, "task", None):
                PROGRESS.finish(self.task)
                self.task = None
                _current.busy = False
            super().close()

    return HubProgress


class IncompleteDownload(Exception):
    pass


def retryable(error):
    """Transient error of an HTTP download, worth resuming right away."""
    if isinstance(error, urllib.error.HTTPError):
        return error.code >= 500 or error.code == 429
    if isinstance(error, OSError) and error.errno in (errno.ENOSPC, errno.EDQUOT, errno.EACCES, errno.EROFS):
        return False
    return isinstance(error, (OSError, http.client.HTTPException, IncompleteDownload))


def part_info(part):
    """Source version of the content of a .part, noted next to it (hidden, and not as .json: the
    workflows folder lists the .json files)."""
    return part.with_name(f".{part.name}-info")


def response_validator(headers):
    """If-Range value of a response: strong ETag, otherwise Last-Modified, otherwise None."""
    etag = headers.get("ETag")
    if etag and not etag.startswith("W/"):
        return etag
    return headers.get("Last-Modified")


def fetch_part(url, part, task):
    """One attempt at downloading `url` into `part`, after what it already holds if the server
    accepts partial requests (Range) and the file has not changed at the source (If-Range);
    otherwise from the start."""
    info = part_info(part)
    offset = part.stat().st_size if part.exists() else 0
    validator = info.read_text().strip() if offset and info.is_file() else None
    headers = {"User-Agent": USER_AGENT}
    if offset and validator:
        headers |= {"Range": f"bytes={offset}-", "If-Range": validator}
    try:
        resp = urllib.request.urlopen(urllib.request.Request(url, headers=headers), timeout=60)
    except urllib.error.HTTPError as e:
        if e.code == 416 and offset:  # .part longer than the file: start over
            part.unlink()
            return fetch_part(url, part, task)
        raise
    with resp:
        match = re.fullmatch(r"bytes (\d+)-\d+/(\d+)", resp.headers.get("Content-Range") or "")
        if resp.status == 206 and match and int(match[1]) == offset:
            mode, total = "ab", int(match[2])
        else:  # the whole file: no resume possible, or it changed at the source
            offset, mode = 0, "wb"
            total = int(resp.headers.get("Content-Length") or 0) or None
            validator = response_validator(resp.headers)
            if validator:
                info.write_text(validator + "\n")
            else:
                info.unlink(missing_ok=True)
        done = offset
        PROGRESS.update(task, done, total)
        with part.open(mode) as out_file:
            while chunk := resp.read(1024 * 1024):
                if CANCEL.is_set():
                    raise KeyboardInterrupt
                out_file.write(chunk)
                done += len(chunk)
                PROGRESS.update(task, done, total)
    if total and done != total:
        raise IncompleteDownload(t("incomplete download ({done} of {total} bytes)", done=done, total=total))


def fetch_url(url, dest):
    """Downloads `url` into `dest`, through `dest`.part. A .part left by an interrupted download
    (stop, network drop, container stopped) is resumed where it stopped (see fetch_part); a drop
    along the way is resumed right away, up to HTTP_RETRIES times."""
    part = dest.with_name(dest.name + ".part")
    task = PROGRESS.start(dest.name)
    try:
        for attempt in range(HTTP_RETRIES + 1):
            try:
                fetch_part(url, part, task)
                break
            except Exception as e:
                if attempt == HTTP_RETRIES or not retryable(e):
                    raise
                delay = min(2 ** attempt, 30)
                out("   " + t("{name}: {error}, retrying in {delay} s", name=dest.name, error=e, delay=delay))
                if CANCEL.wait(delay):
                    raise KeyboardInterrupt
        part.replace(dest)
        part_info(part).unlink(missing_ok=True)
    finally:
        PROGRESS.finish(task)
        if part.exists() and not part.stat().st_size:
            part.unlink()


def fetch(item, dest, paths):
    dest.parent.mkdir(parents=True, exist_ok=True)
    _current.name, _current.busy = dest.name, False
    if "hf" in item:
        from huggingface_hub import hf_hub_download  # reads HF_TOKEN by itself

        # One folder per file: several downloads run at the same time. Emptied before (leftover
        # of a killed download: huggingface_hub cannot resume it) and after.
        key = hashlib.sha256(describe_source(item).encode()).hexdigest()[:12]
        work = paths.staging / f"hf-{key}"
        shutil.rmtree(work, ignore_errors=True)
        work.mkdir(parents=True)
        options = {}
        if "tqdm_class" in inspect.signature(hf_hub_download).parameters and hub_progress_class():
            options["tqdm_class"] = hub_progress_class()
        try:
            downloaded = hf_hub_download(
                repo_id=item["hf"],
                filename=item["file"],
                revision=item.get("revision"),
                local_dir=work,
                **options,
            )
            shutil.move(downloaded, dest)
        finally:
            shutil.rmtree(work, ignore_errors=True)
    elif "civitai" in item:
        url = f"https://civitai.com/api/download/models/{item['civitai']}"
        # Token as a parameter rather than a header: CivitAI redirects to an S3 storage that
        # rejects an Authorization header on top of its own signature.
        token = os.environ.get("CIVITAI_TOKEN")
        fetch_url(f"{url}?token={token}" if token else url, dest)
    elif "github" in item:
        fetch_url(github_file_url(item), dest)
    else:
        fetch_url(item["url"], dest)


# --- Update (sync --update) ---------------------------------------------------------------

class Versions:
    """Source version of each model or workflow downloaded or checked, in
    <user>/__comfy_profiles/versions.json. An entry only holds while the local file has not
    changed (same size, same date): it avoids computing the checksum of a big model again at
    each `sync --update`. Written by several downloads at once: locked."""

    def __init__(self, paths):
        self.file = paths.data / VERSIONS_NAME
        self.lock = threading.Lock()
        try:
            self.items = json.loads(self.file.read_text())
        except (OSError, json.JSONDecodeError):
            self.items = {}

    def get(self, path):
        entry = self.items.get(str(path))
        try:
            st = path.stat()
        except OSError:
            return None
        if isinstance(entry, dict) and entry.get("size") == st.st_size and entry.get("mtime") == st.st_mtime_ns:
            return entry.get("remote")
        return None

    def set(self, path, remote):
        st = path.stat()
        with self.lock:
            self.items[str(path)] = {"remote": remote, "size": st.st_size, "mtime": st.st_mtime_ns}
            self.file.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.file.with_name(f".{self.file.name}.tmp")
            tmp.write_text(json.dumps(self.items, ensure_ascii=False, indent=1) + "\n")
            tmp.replace(self.file)


def remote_version(item):
    """(source version, size in bytes or None), without downloading anything: Hugging Face ETag
    (sha256 of an LFS file, git blob sha1 otherwise), or HTTP ETag / Last-Modified. None for
    CivitAI: the file of a model version never changes."""
    if "civitai" in item:
        return None
    if "hf" in item:
        from huggingface_hub import get_hf_file_metadata, hf_hub_url

        meta = get_hf_file_metadata(hf_hub_url(item["hf"], item["file"], revision=item.get("revision")))
        return meta.etag, meta.size
    url = github_file_url(item) if "github" in item else item["url"]
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as resp:
        version = resp.headers.get("ETag") or resp.headers.get("Last-Modified")
        return version, int(resp.headers.get("Content-Length") or 0) or None


def remember_version(item, dest, versions):
    """Notes the source version of a file just downloaded (cannot fail: failing that, the next
    check compares the file itself)."""
    try:
        remote = remote_version(item)
        if remote and remote[0]:
            versions.set(dest, remote[0])
    except Exception:
        pass


def file_digest(path, h):
    with path.open("rb") as f:
        while chunk := f.read(8 * 1024 * 1024):
            h.update(chunk)
    return h.hexdigest()


def hf_local_etag(path, etag):
    """Checksum of the local file comparable to the Hugging Face ETag `etag`, or None."""
    if len(etag) == 64:
        return file_digest(path, hashlib.sha256())
    if len(etag) == 40:
        return file_digest(path, hashlib.sha1(f"blob {path.stat().st_size}\0".encode()))
    return None


def refresh_file(item, dest, paths, versions):
    """Downloads `dest` again if it changed at the source. Without a noted version (file
    installed before this version of the script, or modified since), the file itself is
    compared: checksum for Hugging Face, size otherwise (same size: considered up to date)."""
    version, size = remote_version(item)
    known = versions.get(dest)
    if version and known == version:
        changed = False
    elif size is not None and size != dest.stat().st_size:
        changed = True
    elif "hf" in item and version:
        out("   " + t("computing the checksum of {name}", name=dest.name))
        changed = hf_local_etag(dest, version) not in (None, version)
    else:
        changed = bool(version and known and known != version)
    if not changed:
        if version:
            versions.set(dest, version)
        out("   " + t("{name}: already up to date", name=dest.name))
        return
    fetch(item, dest, paths)
    if version:
        versions.set(dest, version)
    out("   " + t("{name}: updated", name=dest.name))


def locally_modified(store):
    """True if the git-tracked files of a custom node were modified in place."""
    out = git(store, "status", "--porcelain", "--untracked-files=no", capture_output=True, text=True)
    return out.returncode != 0 or bool(out.stdout.strip())


def update_git(store, ref):
    """Brings a cloned custom node to the latest version of `ref` (a branch; a tag or a commit
    don't move), otherwise of the repository's default branch."""
    def head():
        return git(store, "rev-parse", "--short", "HEAD", capture_output=True, text=True).stdout.strip()

    before = head()
    if ref:
        checkout_ref(store, ref)
    else:
        shallow = git(store, "rev-parse", "--is-shallow-repository", capture_output=True, text=True)
        depth = ["--depth", "1"] if shallow.stdout.strip() == "true" else []
        git(store, "fetch", *depth, "origin", "HEAD", check=True)
        git(store, "reset", "--hard", "FETCH_HEAD", check=True)
    after = head()
    print("   " + (t("already up to date ({rev})", rev=after) if after == before
                   else t("updated: {old} -> {new}", old=before, new=after)))


# --- Python dependencies ------------------------------------------------------------------

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
    """`record`: (path, kind) to add to the manifest once the step succeeded. `parallel`:
    download or check of a file, `name`, run several at a time (see run_steps)."""

    def __init__(self, label, run, record=None, name=None, parallel=False):
        self.label = label
        self.run = run
        self.record = record
        self.name = name or label
        self.parallel = parallel


class Manifest:
    """What the manager installed itself (custom nodes, models, workflows), in
    <user>/__comfy_profiles/installed.json. Only these items are removed by `uninstall`, and
    only these custom nodes change version when `ref` changes: a file or a node already there
    before (installed by hand, shipped with ComfyUI or a Docker image) is never touched.

    Without a manifest (first use of this version), if custom nodes are stored separately
    (COMFY_PROFILES_NODES_STORE), what is already there for the profiles of the file is taken
    over: that storage is only filled by the manager, and this was the behavior of the previous
    versions. Otherwise, it starts from an empty manifest."""

    def __init__(self, paths, profiles):
        self.file = paths.data / MANIFEST_NAME
        self.adopted = False
        if self.file.is_file():
            try:
                self.items = json.loads(self.file.read_text()).get("items") or {}
            except (json.JSONDecodeError, AttributeError) as e:
                sys.exit("!! " + t("{path}: invalid JSON ({error})", path=self.file, error=e))
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
            targets = installed_by(resolve(profiles, [all_variants(profiles, name)]), paths)
        except (ConfigError, SystemExit):
            continue
        for path, (kind, _, link) in targets.items():
            if present(path, link):
                items[str(path)] = kind
    return items


def file_dest(item, where, section, paths):
    """Local path of a model or a workflow."""
    source_of(item, where)
    if section == "workflows":
        return paths.workflows / target_name(item, where)
    if not item.get("type"):
        raise ConfigError(t("{where}: 'type' (subfolder, e.g. loras) required", where=where))
    return paths.model_path(item["type"], target_name(item, where))


def file_label(item, section, dest):
    return f"{item['type']}/{dest.name}" if section == "models" else f"workflow/{dest.name}"


def plan_file(item, dest, kind, paths, versions, update=False, managed=False):
    """Download of a missing file; with `update`, check at the source of a file installed or
    taken over by the manager (except CivitAI, see remote_version)."""
    if not dest.exists():
        def install():
            fetch(item, dest, paths)
            remember_version(item, dest, versions)

        return Step(f"{describe_source(item)} -> {dest}", install, record=(dest, kind),
                    name=dest.name, parallel=True)
    if update and managed and "civitai" not in item:
        return Step(t("{source}: checking {path}", source=describe_source(item), path=dest),
                    lambda: refresh_file(item, dest, paths, versions), name=dest.name, parallel=True)
    return None


def git(store, *args, **kwargs):
    """git in the repository of the custom node `store`, never in a parent repository: without
    .git (node installed from the Comfy Registry), git would otherwise go up to the ComfyUI
    clone."""
    env = {**os.environ, "GIT_CEILING_DIRECTORIES": str(Path(store).absolute().parent)}
    return subprocess.run(["git", "-C", str(store), *args], env=env, **kwargs)


def at_ref(store, ref):
    """True if the local repository is already on `ref` (checked without network access)."""
    def rev(r):
        out = git(store, "rev-parse", "--verify", "--quiet", f"{r}^{{commit}}",
                  capture_output=True, text=True)
        return out.stdout.strip() if out.returncode == 0 else None

    head = rev("HEAD")
    return head is not None and head == rev(ref)


def checkout_ref(store, ref):
    """Switches an already cloned custom node to `ref` (branch, tag or commit)."""
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


# File written in a custom node extracted from a zip: Drive id it comes from.
GDRIVE_MARKER = ".comfy-profiles-gdrive"


def gdrive_id(value, where):
    """Id of a Drive file, from the id itself or a share link."""
    match = re.search(r"/d/([\w-]+)", value) or re.search(r"[?&]id=([\w-]+)", value)
    if match:
        return match.group(1)
    if re.fullmatch(r"[\w-]{20,}", value):
        return value
    raise ConfigError(t("{where}: 'gdrive' must be a Google Drive share link or a file id",
                         where=where))


def extract_encrypted_zip(archive, dest, file_id):
    """Encrypted zip (AES, e.g. 7-Zip, or ZipCrypto): zipfile cannot read AES, pyzipper can."""
    password = os.environ.get("GDRIVE_ZIP_PASSWORD")
    if not password:
        raise RuntimeError(t("Drive zip {id} is encrypted: password expected in GDRIVE_ZIP_PASSWORD",
                             id=file_id))
    try:
        import pyzipper
    except ImportError:  # not installed beforehand: only needed for encrypted zips
        pip_install(["pyzipper"])
        import pyzipper
    with pyzipper.AESZipFile(archive) as zf:
        zf.setpassword(password.encode())
        try:
            zf.extractall(dest)  # same path protection as zipfile
        except RuntimeError as e:
            raise RuntimeError(t("Drive zip {id}: cannot decrypt (wrong GDRIVE_ZIP_PASSWORD?): {error}",
                                 id=file_id, error=e)) from None


def gdrive_marker(store):
    """(Drive id, zip sha256 or None) a custom node comes from, or (None, None)."""
    try:
        fields = (store / GDRIVE_MARKER).read_text().split()
    except OSError:
        return None, None
    return (fields[0] if fields else None), (fields[1] if len(fields) > 1 else None)


def install_gdrive_zip(file_id, store, paths, update=False):
    """Downloads a public zip from Drive and extracts it into `store` (replaced if it exists).
    `update`: leaves `store` as is if the zip is the one it already comes from."""
    work = paths.staging / f"gdrive-{file_id}"
    archive = work / "node.zip"
    work.mkdir(parents=True, exist_ok=True)
    try:
        # confirm=t: skips the "file too large for the virus scan" warning page.
        fetch_url(f"https://drive.usercontent.google.com/download?id={file_id}&export=download&confirm=t",
                  archive)
        if not zipfile.is_zipfile(archive):
            raise RuntimeError(t("Drive file {id} is not a zip (not public, or Drive download "
                                 "quota exceeded?)", id=file_id))
        digest = file_digest(archive, hashlib.sha256())
        if update and gdrive_marker(store) == (file_id, digest):
            print("   " + t("already up to date"))
            return
        extracted = work / "extracted"
        with zipfile.ZipFile(archive) as zf:
            encrypted = any(info.flag_bits & 0x1 for info in zf.infolist())
            if not encrypted:
                zf.extractall(extracted)  # neutralizes absolute paths and `..`
        if encrypted:
            extract_encrypted_zip(archive, extracted, file_id)
        # Zip of a folder: take its content; otherwise the files are at the root of the zip.
        entries = [e for e in extracted.iterdir() if e.name != "__MACOSX"]
        root = entries[0] if len(entries) == 1 and entries[0].is_dir() else extracted
        (root / GDRIVE_MARKER).write_text(f"{file_id}\n{digest}\n")
        shutil.rmtree(store, ignore_errors=True)
        store.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root), str(store))
        if update:
            print("   " + t("updated"))
    finally:
        # Only an interrupted download is left (node.zip.part), resumed next time.
        shutil.rmtree(work / "extracted", ignore_errors=True)
        archive.unlink(missing_ok=True)
        with contextlib.suppress(OSError):
            work.rmdir()


def custom_node_name(item, where):
    if item.get("name"):
        return item["name"]
    if not item.get("git"):
        raise ConfigError(t("{where}: exactly one source expected among {sources}",
                            where=where, sources="git, gdrive"))
    return item["git"].rstrip("/").removesuffix(".git").rsplit("/", 1)[-1]


def normalize_repo_url(url):
    """github.com/owner/repo for https://github.com/Owner/Repo.git, git@github.com:owner/repo..."""
    url = re.sub(r"^(git\+)?[a-z]+://", "", url.strip().lower())
    url = re.sub(r"^[^@/]+@([^:/]+):", r"\1/", url)  # git@host:owner/repo
    url = re.sub(r"^[^@/]+@", "", url).removeprefix("www.")
    return url.rstrip("/").removesuffix(".git")


def node_repo_url(path):
    """Repository of a custom node: origin remote of its own .git (not that of a parent
    repository), otherwise Repository of its pyproject.toml (node installed from the Comfy
    Registry, without .git)."""
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
    """Custom nodes present, by lowercase name and by repository (read once per command, before
    any installation)."""
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
    """The same custom node already in custom_nodes/ under another name, for instance installed
    by ComfyUI-Manager from the Comfy Registry (comfyui-kjnodes for ComfyUI-KJNodes): same name
    up to case, or same repository. Left as is: cloning it a 2nd time would load it twice."""
    if (paths.custom_nodes / name).exists() or (paths.custom_nodes_store / name).exists():
        return None
    index = installed_nodes(paths.custom_nodes)
    found = index.get(("name", name.lower()))
    if not found and item.get("git"):
        found = index.get(("url", normalize_repo_url(item["git"])))
    return found


def foreign_node(name, paths):
    """Custom node already in custom_nodes/ as a real folder while the manager stores its own
    elsewhere (COMFY_PROFILES_NODES_STORE): shipped with a Docker image or installed by hand.
    Never touched, and ignored in the profiles' state."""
    link, store = paths.custom_nodes / name, paths.custom_nodes_store / name
    return link.exists() and not link.is_symlink() and link != store


def plan_custom_node(item, where, paths, manifest, update=False):
    url = item.get("git")
    drive = item.get("gdrive")
    if bool(url) == bool(drive):
        raise ConfigError(t("{where}: exactly one source expected among {sources}",
                            where=where, sources="git, gdrive"))
    if drive:
        if not item.get("name"):
            raise ConfigError(t("{where}: 'name' (custom node folder name) required with 'gdrive'",
                                where=where))
        if item.get("ref"):
            raise ConfigError(t("{where}: 'ref' only applies to a 'git' source", where=where))
        file_id = gdrive_id(drive, where)
    name = custom_node_name(item, where)
    store = paths.custom_nodes_store / name
    link = paths.custom_nodes / name
    steps = []

    if foreign_node(name, paths):
        print(f"   [{name}] " + t("already present ({path}), not managed: profile version ignored",
                                path=link))
        return name, steps

    alias = installed_elsewhere(name, item, paths)
    if alias:
        if alias in manifest:
            message = t("already installed as {alias} ({path}), managed: left as is",
                        alias=alias.name, path=alias)
        else:
            message = t("already installed as {alias} ({path}), not managed: left as is",
                        alias=alias.name, path=alias)
        print(f"   [{name}] {message}")
        return name, steps

    ref = item.get("ref")
    managed = store in manifest
    record = (store, "custom_node")
    if drive:
        installed_id = gdrive_marker(store)[0]
        if not store.exists():
            steps.append(Step(t("gdrive:{id} (zip) -> {path}", id=file_id, path=store),
                              lambda: install_gdrive_zip(file_id, store, paths), record))
        elif not managed or (installed_id is None and not update):
            print(f"   [{name}] " + t("{path} exists but was not installed from Drive by the "
                                "manager, left as is", path=store))
        elif update:  # replaced only if the zip is not the one it comes from
            steps.append(Step(t("gdrive:{id} (zip): updating {path}", id=file_id, path=store),
                              lambda: install_gdrive_zip(file_id, store, paths, update=True), record))
        elif installed_id != file_id:
            steps.append(Step(t("gdrive:{id} (zip, new file) replaces {path}", id=file_id, path=store),
                              lambda: install_gdrive_zip(file_id, store, paths), record))
    elif update and store.exists():
        if not managed:
            print(f"   [{name}] " + t("{path} was not installed by the manager: not updated (adopt "
                                "to take it over)", path=store))
        elif not (store / ".git").exists():
            print(f"   [{name}] " + t("{path} is not a git clone (installed from the Comfy "
                                "Registry?): not updated, use the Manager", path=store))
        elif locally_modified(store):
            print(f"   [{name}] " + t("{path}: files modified in place, not updated", path=store))
        else:
            steps.append(Step(t("git: updating {path}{ref}", path=store,
                                ref=f" ({ref})" if ref else ""),
                              lambda: update_git(store, ref)))
    elif not store.exists():
        def clone():
            try:
                git_clone()
            except BaseException:  # failure or interruption: a partial clone would pass for installed
                shutil.rmtree(store, ignore_errors=True)
                raise

        def git_clone():
            if ref:
                # Branch or tag: shallow clone. A commit is not accepted by --branch, hence the
                # fallback to a full clone followed by a checkout.
                shallow = subprocess.run(
                    ["git", "clone", "--depth", "1", "--branch", ref, url, str(store)])
                if shallow.returncode != 0:
                    shutil.rmtree(store, ignore_errors=True)
                    subprocess.run(["git", "clone", url, str(store)], check=True)
                    subprocess.run(["git", "-C", str(store), "checkout", ref], check=True)
            else:
                subprocess.run(["git", "clone", "--depth", "1", url, str(store)], check=True)

        steps.append(Step(f"git clone {url}{'@' + ref if ref else ''} -> {store}", clone, record))
    elif ref and not (store / ".git").exists():
        print(f"   [{name}] " + t("{path} is not a git clone (installed from the Comfy Registry?): "
                            "ref {ref} ignored", path=store, ref=ref))
    elif ref and not at_ref(store, ref):
        if managed:
            steps.append(Step(t("git checkout {ref} in {path}", ref=ref, path=store),
                              lambda: checkout_ref(store, ref)))
        else:
            print(f"   [{name}] " + t("{path} was not installed by the manager: ref {ref} ignored",
                                path=store, ref=ref))

    if link != store and not link.is_symlink():
        def make_link():
            if not store.exists():  # clone or extraction failed just before: no dead link
                raise RuntimeError(t("{path} missing, link not created", path=store))
            link.parent.mkdir(parents=True, exist_ok=True)
            link.symlink_to(store)

        steps.append(Step(t("link {link} -> {path}", link=link, path=store), make_link))

    # Dependencies are only known once the repository is cloned: they are evaluated at run time.
    def deps():
        requirements = store / "requirements.txt"
        if requirements.is_file():
            m = marker("req", name, requirements.read_text())
            if not m.exists():
                print(f">> [{name}] " + t("installing requirements.txt"))
                pip_install(["-r", str(requirements)])
                touch(m)
        install_py = store / "install.py"
        if install_py.is_file():
            m = marker("install", name, install_py.read_text())
            if not m.exists():
                print(f">> [{name}] " + t("running install.py"))
                subprocess.run([sys.executable, "install.py"], cwd=store, check=True)
                touch(m)

    # The dependencies of a node the manager did not install (Manager, by hand...) remain the
    # business of whoever installed it.
    deps_pending = bool(steps) or managed and any(
        f.is_file() and not marker(kind, name, f.read_text()).exists()
        for kind, f in (("req", store / "requirements.txt"), ("install", store / "install.py"))
    )
    if deps_pending:
        steps.append(Step(t("dependencies of {name} (requirements.txt / install.py)", name=name), deps))
    return name, steps


def build_plan(merged, paths, manifest, update=False):
    """Returns (steps to run, state of each item: (kind, name, to install?, profile declaring it,
    declared size in bytes or None, source page or None: see source_link)). An item declared by
    several profiles goes to the first one in resolve() order, hence to the inherited profile
    rather than the one inheriting from it. Validates the whole config before acting. `update`
    (sync --update): adds the update of what the manager installed or took over (see
    plan_custom_node, plan_file) and `pip install --upgrade`."""
    steps, status, seen = [], [], set()
    versions = Versions(paths)

    for profile, item in merged["custom_nodes"]:
        where = f"[{profile}] custom_nodes"
        name, node_steps = plan_custom_node(item, where, paths, manifest, update)
        if name in seen:
            continue
        seen.add(name)
        steps += node_steps
        status.append(("custom_node", name, bool(node_steps), profile, None, source_link(item)))

    specs = {}  # spec -> first profile declaring it
    for profile, spec in merged["pip"]:
        specs.setdefault(spec, profile)
    missing_specs = [s for s in specs if not marker("pip", "spec", s).exists()]
    for spec, profile in specs.items():
        status.append(("pip", spec, spec in missing_specs, profile, None, pip_link(spec)))
    to_install = list(specs) if update else missing_specs
    if to_install:
        def install_specs():
            pip_install((["--upgrade"] if update else []) + to_install)
            for s in to_install:
                touch(marker("pip", "spec", s))

        steps.append(Step(f"pip install {'--upgrade ' if update else ''}{' '.join(to_install)}", install_specs))

    unmanaged = 0
    for section in ("models", "workflows"):
        for profile, item in merged[section]:
            dest = file_dest(item, f"[{profile}] {section}", section, paths)
            if dest in seen:
                continue
            seen.add(dest)
            managed = dest in manifest
            unmanaged += update and dest.exists() and not managed
            step = plan_file(item, dest, section[:-1], paths, versions, update, managed)
            size = item.get("size") if isinstance(item, dict) else None
            size = size if isinstance(size, int) and not isinstance(size, bool) else None
            status.append((section[:-1], file_label(item, section, dest), not dest.exists(), profile, size,
                           source_link(item)))
            if step:
                steps.append(step)
    if unmanaged:
        print("   " + t("{n} file(s) present but not managed: not updated (adopt to take them over)", n=unmanaged))

    return steps, status


# --- Settings -----------------------------------------------------------------------------

# Download settings, in <user>/__comfy_profiles/settings.json (edited by the panel):
# {"downloads": {key: value}}. Saved value, otherwise environment variable, otherwise default.
#   jobs                 files (models, workflows) downloaded at a time
#   hf_high_performance  Hugging Face: Xet high performance mode (HF_XET_HIGH_PERFORMANCE)
DOWNLOAD_SETTINGS = {
    "jobs": ("COMFY_PROFILES_JOBS", 3),
    "hf_high_performance": ("HF_XET_HIGH_PERFORMANCE", True),
}
MAX_JOBS = 16


def parse_setting(key, value):
    """Valid value of the setting `key` (text of an environment variable accepted), otherwise
    ConfigError."""
    if key == "jobs":
        try:
            jobs = int(value) if isinstance(value, str) or type(value) is int else None
        except ValueError:
            jobs = None
        if jobs is None or not 1 <= jobs <= MAX_JOBS:
            raise ConfigError(t("jobs: integer from 1 to {max} expected", max=MAX_JOBS))
        return jobs
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    if not isinstance(value, bool):
        raise ConfigError(t("{key}: true or false expected", key=key))
    return value


def saved_settings(paths):
    try:
        data = json.loads((paths.data / SETTINGS_NAME).read_text())
    except (OSError, json.JSONDecodeError):
        return {}
    downloads = data.get("downloads") if isinstance(data, dict) else None
    return {k: v for k, v in (downloads or {}).items() if k in DOWNLOAD_SETTINGS} if isinstance(downloads, dict) else {}


def download_settings(paths):
    """{key: value} of the effective settings; an invalid value (file or variable) is ignored."""
    saved = saved_settings(paths)
    values = {}
    for key, (var, default) in DOWNLOAD_SETTINGS.items():
        values[key] = default
        for value in (os.environ.get(var), saved.get(key)):
            if value is not None:
                with contextlib.suppress(ConfigError):
                    values[key] = parse_setting(key, value)
    return values


def apply_download_settings(values):
    """Before any import of huggingface_hub: hf_xet reads its mode at startup."""
    os.environ["HF_XET_HIGH_PERFORMANCE"] = "1" if values["hf_high_performance"] else "0"


def package_version(*names):
    for name in names:
        with contextlib.suppress(importlib.metadata.PackageNotFoundError):
            return importlib.metadata.version(name)
    return None


def partial_downloads(paths):
    """Interrupted downloads: .part files (resumed by the next sync, see fetch_url) and leftovers
    of the staging folder."""
    roots = {paths.models, paths.workflows,
             *(Path(folder) for folders in paths.model_folders.values() for folder in folders)}
    found = set()
    for root in roots:
        if root.is_dir():
            found.update(p for p in root.rglob("*.part") if p.is_file())
    if paths.staging.is_dir():
        found = {p for p in found if paths.staging not in p.parents} | set(paths.staging.iterdir())
    return sorted(found)


def cmd_settings(args):
    paths = Paths()
    file = paths.data / SETTINGS_NAME
    if args.reset:
        file.unlink(missing_ok=True)
    if args.set:
        try:
            changes = json.loads(args.set)
            if not isinstance(changes, dict):
                raise ConfigError(t("JSON object expected"))
            saved = saved_settings(paths)
            for key, value in changes.items():
                if key not in DOWNLOAD_SETTINGS:
                    raise ConfigError(t("unknown setting: {key}", key=key))
                if value is None:
                    saved.pop(key, None)
                else:
                    saved[key] = parse_setting(key, value)
        except (json.JSONDecodeError, ConfigError) as e:
            sys.exit(f"!! {e}")
        file.parent.mkdir(parents=True, exist_ok=True)
        tmp = file.with_name(f".{file.name}.tmp")
        tmp.write_text(json.dumps({"downloads": saved}, ensure_ascii=False, indent=1) + "\n")
        tmp.replace(file)
    removed = None
    if args.clean_partials:
        partials = partial_downloads(paths)
        removed = {"count": len(partials), "size": sum(disk_size(p) for p in partials)}
        for path in partials:
            if path.is_dir() and not path.is_symlink():
                shutil.rmtree(path, ignore_errors=True)
            else:
                path.unlink(missing_ok=True)
                part_info(path).unlink(missing_ok=True)
    partials = partial_downloads(paths)
    print_json({
        "file": str(file),
        "values": download_settings(paths),
        "saved": saved_settings(paths),
        "defaults": {key: default for key, (_, default) in DOWNLOAD_SETTINGS.items()},
        "env": {key: f"{var}={os.environ[var]}" for key, (var, _) in DOWNLOAD_SETTINGS.items()
                if os.environ.get(var) is not None},
        "max_jobs": MAX_JOBS,
        "huggingface_hub": package_version("huggingface_hub", "huggingface-hub"),
        "hf_xet": package_version("hf-xet", "hf_xet"),
        "partials": {"count": len(partials), "size": sum(disk_size(p) for p in partials)},
        **({"removed": removed} if removed else {}),
    })


# --- Commands -----------------------------------------------------------------------------

def print_json(data):
    print(json.dumps(data, ensure_ascii=False))


def profile_state(profiles, ref, paths, memo=None):
    """State of a profile reference (see selected). installed: everything is there, extends
    included. Otherwise, the state depends on the
    profile's own items (those it does not already inherit from a parent): partial if one of
    them is present, missing otherwise. An installed parent (e.g. comfyui-common, shared by
    many) therefore does not make the profiles inheriting from it "partial". A profile without
    items of its own, which only groups other profiles (e.g. minimax-h3-all), is judged on the
    items of its parents outside the base they all share (e.g. minimax-h3-common): it is thus
    consistent with each of them. Failing that (a single parent), it takes the state of its
    direct parents: partial if one of them is installed or partial. empty: installs no file (pip
    only, or only custom nodes outside the manager, see foreign_node). error: invalid config.
    For a variant, the profile's common items count as inherited: another variant already
    installed does not make it "partial"."""
    memo = {} if memo is None else memo
    key = ref
    if key in memo:
        return memo[key]
    try:
        name, variants = selected(profiles, ref)
        ref = canonical(profiles, ref)
        everything = installed_by(resolve(profiles, [ref]), paths)
        inherited = set()
        for parent in ancestors(profiles, [ref]) - {ref} | ({make_ref(name, [])} if variants else set()):
            inherited.update(installed_by(resolve(profiles, [parent]), paths))
    except (ConfigError, SystemExit):
        return memo.setdefault(key, "error")
    own = {path: target for path, target in everything.items() if path not in inherited}
    # Parents with the variants they get from this reference (see parent_ref).
    extends = [parent_ref(profiles, p, name, variants) for p in profiles[name].get("extends", [])]
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
    return memo.setdefault(key, state)


def overall_state(states):
    """State of a profile with variants, from those of its variants: installed if one of them
    is."""
    for state in ("installed", "partial"):
        if state in states:
            return state
    for state in ("error", "empty"):
        if states and all(s == state for s in states):
            return state
    return "missing"


def profile_total(profiles, name, paths=None):
    """Of a profile reference: (total size of the files in bytes, number of files of unknown size), extends included,
    each file counted once. Custom nodes and pip packages don't count. With `paths`, only the
    missing files: what installing the profile would add."""
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


def profile_items(profiles, name):
    """Names of a profile's items, extends and all variants included, each one once (for the
    panel's filter): custom nodes, pip packages, "type/file" of models and workflows."""
    try:
        merged = resolve(profiles, [all_variants(profiles, name)])
        names = [custom_node_name(item, f"[{profile}] custom_nodes")
                 for profile, item in merged["custom_nodes"]]
        names += [spec for _, spec in merged["pip"]]
        for section in ("models", "workflows"):
            for profile, item in merged[section]:
                where = f"[{profile}] {section}"
                file = target_name(item, where)
                names.append(f"{item['type']}/{file}" if section == "models" and item.get("type")
                             else file)
    except (ConfigError, SystemExit):
        return []
    return list(dict.fromkeys(str(n) for n in names))


def own_models(profiles, name):
    """A profile's own models, "type/file" and their variants ([]: common to all of them), for
    the panel's dialog matching the workflow's model fields to profiles."""
    models = []
    for item in profiles[name].get("models", []):
        try:
            models.append({"name": f"{item['type']}/{target_name(item, f'[{name}] models')}",
                           "variants": item_variants(item)})
        except (ConfigError, KeyError):
            continue
    return models


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
    """Items present for these profiles (extends included) that the manager did not install
    itself: {path: (kind, name, link)}. `uninstall` leaves them in place; `adopt` takes them
    over."""
    targets = installed_by(resolve(profiles, names), paths)
    return {path: target for path, target in targets.items()
            if present(path, target[2]) and path not in manifest}


def count_unmanaged(profiles, name, paths, manifest):
    try:
        return len(unmanaged_items(profiles, [all_variants(profiles, name)], paths, manifest))
    except (ConfigError, SystemExit):
        return 0


def sizes_json(profiles, ref, paths):
    # Total computed from the file sizes, to show it in the panel's language ("size" is the text
    # written by `sizes`), and the share of it that installing would add (missing files).
    return {**dict(zip(("total", "unknown"), safe_total(profiles, ref))),
            **dict(zip(("todo", "todo_unknown"), safe_total(profiles, ref, paths)))}


def profile_json(profiles, name, paths, manifest, states):
    profile = profiles[name]
    entry = {
        "description": profile.get("description", ""),
        "size": profile.get("size", ""),
        **sizes_json(profiles, name, paths),
        "extends": profile.get("extends", []),
        "items": profile_items(profiles, name),
        "models": own_models(profiles, name),
        "counts": {s: len(profile.get(s, [])) for s in SECTIONS},
        "state": profile_state(profiles, name, paths, states),
        "unmanaged": count_unmanaged(profiles, name, paths, manifest),
    }
    if profile.get("variants"):
        # Each variant: its own state and size (common items and extends included).
        entry["variants"] = [
            {"name": v, "state": profile_state(profiles, make_ref(name, [v]), paths, states),
             **sizes_json(profiles, make_ref(name, [v]), paths)}
            for v in profile["variants"]
        ]
        entry["default_variant"] = profile.get("default_variant")
        # The profile named without brackets (common items, and the default variant if any),
        # and its common items alone (name[]).
        entry["ref_state"] = entry["state"]
        entry["common_state"] = profile_state(profiles, make_ref(name, []), paths, states)
        entry["state"] = overall_state([v["state"] for v in entry["variants"]])
    return entry


def cmd_list(profiles, args):
    if args.json:
        paths, states = Paths(), {}
        manifest = Manifest(paths, profiles)
        print_json({
            **config_location(args.config),
            "default": split_names(os.environ.get("COMFY_PROFILES")),
            "profiles": {name: profile_json(profiles, name, paths, manifest, states) for name in profiles},
        })
        return
    for name, profile in profiles.items():
        extends = profile.get("extends", [])
        counts = ", ".join(f"{len(profile.get(s, []))} {s}" for s in SECTIONS if profile.get(s))
        suffix = f"  (extends: {', '.join(extends)})" if extends else ""
        print(f"- {name}{suffix}")
        if profile.get("variants"):
            default = profile.get("default_variant")
            print("    " + t("variants: {variants}", variants=", ".join(
                f"{v} ({t('default')})" if v == default else v for v in profile["variants"])))
        size = profile.get("size")
        if isinstance(size, dict):
            size = ", ".join(f"{v}: {text}" for v, text in size.items())
        if size:
            print("    " + t("size: {size}", size=size))
        if profile.get("description"):
            print(f"    {profile['description']}")
        if counts:
            print("    " + t("own: {counts}", counts=counts))


def cmd_show(profiles, args):
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! " + t("Give at least one profile (see `list`)"))
    try:
        # build_plan's messages (custom nodes left as is...) must not pollute the JSON.
        with contextlib.redirect_stdout(sys.stderr if args.json else sys.stdout):
            paths = Paths()
            manifest = Manifest(paths, profiles)
            _, status = build_plan(resolve(profiles, names), paths, manifest)
            unmanaged = {(kind, label) for kind, label, _ in unmanaged_items(profiles, names, paths, manifest).values()}
    except ConfigError as e:
        sys.exit(f"!! {e}")
    # Grouped by the profile (or variant: profile[variant]) declaring them: the requested ones
    # first, then the inherited profiles in resolve() order (parents before children).
    requested = list(dict.fromkeys(parse_ref(n)[0] for n in names))
    order = list(dict.fromkeys(st[3] for st in status))

    def rank(label):
        base = parse_ref(label)[0]
        return requested.index(base) if base in requested else len(requested), order.index(label)

    status = sorted(status, key=lambda st: rank(st[3]))
    if args.json:
        print_json([{"kind": kind, "name": name, "missing": missing, "profile": profile,
                     "inherited": parse_ref(profile)[0] not in requested, "unmanaged": (kind, name) in unmanaged,
                     "size": size, "link": link and {"site": link[0], "url": link[1]}}
                    for kind, name, missing, profile, size, link in status])
        return
    lines, current = [], None
    for kind, name, missing, profile, size, _ in status:
        if profile != current:
            current = profile
            lines.append(f"[{profile}]" + ("" if parse_ref(profile)[0] in requested else " " + t("(inherited)")))
        todo = t("to download") if kind in ("model", "workflow") else t("to install")
        state = (todo if missing else t("present, not managed") if (kind, name) in unmanaged
                 else t("present"))
        shown = (human_size(size) if size is not None else "?") if kind in ("model", "workflow") else ""
        lines.append(f"  {kind:<12} {name:<40} {shown:>9}  {state}")
    print("\n".join(lines) or t("(empty profile)"))


def run_steps(steps, manifest, jobs, finished):
    """Runs the plan: first, one by one, the steps that are not downloads (custom nodes, pip:
    their output, that of git and pip, must not get mixed), then the file downloads and checks,
    `jobs` at a time. A failed step does not block the following ones. `finished` receives the
    completed steps; returns the labels of the failed ones. Ctrl+C during the downloads: HTTP
    ones stop (CANCEL), waits a little, then KeyboardInterrupt."""
    total = len(steps)
    numbered = list(enumerate(steps, 1))
    failures = []

    def done(i, step, error):
        finished.append(step)
        if error is not None:
            out(f"!! ({i}/{total}) " + t("Failed: {error}", error=error), err=True)
            failures.append(step.label)
        elif step.record:
            manifest.add(*step.record)
            manifest.save()

    for i, step in (n for n in numbered if not n[1].parallel):
        out(f">> ({i}/{total}) {step.label}")
        try:
            step.run()
        except Exception as e:
            done(i, step, e)
        else:
            done(i, step, None)

    def run(i, step):
        out(f">> ({i}/{total}) {step.label}")
        step.run()

    downloads = [n for n in numbered if n[1].parallel]
    pool = concurrent.futures.ThreadPoolExecutor(max_workers=jobs, thread_name_prefix="download")
    futures = {pool.submit(run, i, step): (i, step) for i, step in downloads}
    try:
        for future in concurrent.futures.as_completed(futures):
            i, step = futures[future]
            done(i, step, future.exception())
            if future.exception() is None and jobs > 1 and len(downloads) > 1:
                out(f">> ({i}/{total}) " + t("done: {name}", name=step.name))
    except KeyboardInterrupt:
        CANCEL.set()
        pool.shutdown(wait=False, cancel_futures=True)
        # Only the running ones: wait() never sees a future cancelled this way finish.
        concurrent.futures.wait([f for f in futures if not f.cancelled()], timeout=5)
        raise
    pool.shutdown()
    return failures


def cmd_sync(profiles, args):
    names = split_names(args.profiles or os.environ.get("COMFY_PROFILES"))
    if not names:
        print(">> " + t("No profile requested (argument or COMFY_PROFILES), nothing to do."))
        return 0
    paths = Paths()
    manifest = Manifest(paths, profiles)
    if args.update:
        print(">> " + t("Update: what the manager installed or took over is compared with its "
                        "source."))
    try:
        steps, _ = build_plan(resolve(profiles, names), paths, manifest, args.update)
    except ConfigError as e:
        sys.exit(f"!! {e}")

    print(">> " + t("Profiles: {names} — {n} action(s) to do", names=", ".join(names), n=len(steps)))
    print(">> " + t("Models -> {path}", path=paths.models))
    if not steps:
        return 0
    if args.dry_run:
        for step in steps:
            print(f"   [dry-run] {step.label}")
        return 0
    if manifest.adopted:
        manifest.save()
        print(">> " + t("{path} created: {n} item(s) already present taken over.",
                        path=manifest.file, n=len(manifest.items)))
    print(">> " + (t("HF_TOKEN found.") if os.environ.get("HF_TOKEN")
                   else t("No HF_TOKEN: anonymous HF downloads.")))
    settings = download_settings(paths)
    apply_download_settings(settings)
    jobs = args.jobs or settings["jobs"]
    if any(step.parallel for step in steps):
        print(">> " + t("Downloads: {n} at a time", n=jobs) +
              (", " + t("Hugging Face in high performance mode") if settings["hf_high_performance"] else ""),
              flush=True)

    finished = []
    try:
        failures = run_steps(steps, manifest, jobs, finished)
    except KeyboardInterrupt:
        out("!! " + t("Sync interrupted ({done}/{total} action(s) done).",
                      done=len(finished), total=len(steps)), err=True)
        if not CANCEL.is_set():
            return 130
        # A Hugging Face download cannot be interrupted from outside: exit without waiting for
        # the threads running it.
        os._exit(130)

    if failures:
        print("!! " + t("{n} failure(s) out of {total}:", n=len(failures), total=len(steps)), file=sys.stderr)
        for label in failures:
            print(f"   - {label}", file=sys.stderr)
        return 1
    print(">> " + t("Sync complete."))
    return 0


# --- Take over ----------------------------------------------------------------------------

def mark_deps_installed(name, store):
    """The node already worked: its dependencies (requirements.txt, install.py) are noted as
    installed in this venv, otherwise sync would want to install them again."""
    for kind, f in (("req", store / "requirements.txt"), ("install", store / "install.py")):
        if f.is_file():
            touch(marker(kind, name, f.read_text()))


def cmd_adopt(profiles, args):
    """Adds to the manifest what is already present for some profiles (extends included)
    without having been installed by the manager: `uninstall` can then remove it, and `sync`
    change the version (ref) of its custom nodes. Custom nodes shipped with an image
    (foreign_node) stay excluded."""
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! " + t("Give at least one profile (see `list`)"))
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
        print(">> " + t("{names}: {n} item(s) would be taken over", names=", ".join(names), n=len(items)))
    else:
        print(">> " + t("{names}: {n} item(s) taken over", names=", ".join(names), n=len(items)))
    for kind, label, _ in items.values():
        print(f"   {'[dry-run] ' if args.dry_run else ''}{kind:<12} {label}")
    if items and not args.dry_run:
        print(">> " + t("Uninstalling these profiles can now remove them."))
    return 0


# --- Uninstall ----------------------------------------------------------------------------

def installed_by(merged, paths):
    """What some profiles install: {path: (kind, name, custom node link or None)}. Custom nodes
    outside the manager (foreign_node) are not part of it."""
    targets = {}
    for profile, item in merged["custom_nodes"]:
        name = custom_node_name(item, f"[{profile}] custom_nodes")
        if foreign_node(name, paths):
            continue
        alias = installed_elsewhere(name, item, paths)
        if alias:  # never in the manifest: counts as present, never removed
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
    """Something to remove (even a custom node half in place)."""
    return path.exists() or (link is not None and link.is_symlink())


def installed(path, link):
    """Actually usable: for a custom node, the folder and its link in ComfyUI."""
    return path.exists() and (link is None or link.exists())


def ancestors(profiles, names):
    """The profiles and everything they inherit from (extends), as canonical references."""
    found = set()

    def visit(ref):
        if parse_ref(ref)[0] not in profiles:
            return
        name, variants = selected(profiles, ref)
        ref = canonical(profiles, ref)
        if ref not in found:
            found.add(ref)
            for parent in profiles[name].get("extends", []):
                visit(parent_ref(profiles, parent, name, variants))

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
    # Model subfolders that became empty (e.g. diffusion_models/krea2).
    roots = paths.model_roots()
    parent = path.parent
    while (parent not in roots and parent.parent not in roots and roots & set(parent.parents)
           and not any(parent.iterdir())):  # models/<type>/ stays, even empty
        parent.rmdir()
        parent = parent.parent


def own_items(profiles, names):
    """Like resolve(), but only the items written in the profiles themselves (common ones and
    those of the requested variants), without those they inherit from (extends)."""
    resolve(profiles, names)  # validates the names and the extends
    merged = {section: [] for section in SECTIONS}
    for ref in names:
        name, variants = selected(profiles, ref)
        for section in SECTIONS:
            merged[section] += own_part(profiles, name, variants, section)
    return merged


def plan_uninstall(profiles, names, paths, manifest, with_extends=False):
    """What uninstalling `names` removes. An item is kept if it is still used by a profile that
    stays: a profile of COMFY_PROFILES (reinstalled at each startup), or another fully installed
    profile. What the manager did not install (missing from the manifest) stays.

    By default, only the items of `names` themselves go: the profiles they inherit from
    (extends) are kept profiles like the others. With `with_extends`, these inherited profiles
    are uninstalled too (so they protect nothing): their items go, unless another kept profile
    uses them.

    Profiles with variants: each variant counts as a profile of its own, along with the
    profile's common items. Uninstalling one variant thus keeps the common items as long as
    another variant stays installed. A variant a profile only has through extends (no item of
    its own for it, e.g. krea2-styles[bf16] whose bf16 files are those of krea2-turbo) only
    keeps the profile's own items: otherwise it would forbid uninstalling the variant it
    inherits (krea2-turbo[bf16]). And nothing at all when that profile is being uninstalled:
    its other variants are the same items (krea2-styles[int8] and [bf16] differ only by
    krea2-turbo)."""
    startup = split_names(os.environ.get("COMFY_PROFILES"))
    targets = installed_by((resolve if with_extends else own_items)(profiles, names), paths)
    requested = units(profiles, names)
    removing = units(profiles, ancestors(profiles, names)) if with_extends else requested

    def leaving(ref, among):
        try:
            return units(profiles, [ref]) <= among
        except SystemExit:  # invalid reference in COMFY_PROFILES: ignored
            return True

    def inherited_only(ref):
        name, variants = selected(profiles, ref)
        return bool(variants) and not any(
            True for section in SECTIONS for _ in own_part(profiles, name, variants, section, common=False))

    keep = [ref for ref in startup if not leaving(ref, requested)]
    implied = set()  # kept variants a profile only has through extends
    uninstalled = {name for name, _ in removing}
    for ref in variant_refs(profiles):
        if ref in keep or leaving(ref, removing):
            continue
        if inherited_only(ref) and parse_ref(ref)[0] in uninstalled:
            continue
        try:
            theirs = installed_by(resolve(profiles, [ref]), paths)
        except (ConfigError, SystemExit):
            continue
        if theirs and all(installed(path, link) for path, (_, _, link) in theirs.items()):
            keep.append(ref)
            if inherited_only(ref):
                implied.add(ref)

    needed = {}  # path -> kept profiles using it
    for name in keep:
        items = own_items(profiles, [name]) if name in implied else resolve(profiles, [name])
        for path in installed_by(items, paths):
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
        # Only those actually protecting something.
        "keep_profiles": [n for n in keep if any(n in k["by"] for k in kept)],
        # Those of COMFY_PROFILES uninstalled entirely: reinstalled at the next startup.
        "startup": [ref for ref in startup if parse_ref(ref)[0] in profiles and leaving(ref, requested)],
        "with_extends": with_extends,
        # Profiles inherited by the uninstalled ones: left in place without with_extends.
        "extends": sorted(ancestors(profiles, names) - {canonical(profiles, n) for n in names}),
    }


def cmd_uninstall(profiles, args):
    names = split_names(args.profiles)
    if not names:
        sys.exit("!! " + t("Give at least one profile (see `list`)"))
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
        print(">> " + t("Uninstall: {names} (including extends) — {n} item(s), {size}", **values))
    else:
        print(">> " + t("Uninstall: {names} — {n} item(s), {size}", **values))
    if plan["extends"] and not args.with_extends:
        print(">> " + t("Inherited profiles left in place: {names} (--with-extends to include them)",
                        names=", ".join(plan["extends"])))
    if plan["keep_profiles"]:
        print(">> " + t("Kept profiles (their items are not removed): {names}",
                        names=", ".join(plan["keep_profiles"])))
    kept = t("kept")
    for k in plan["kept"]:
        print(f"   {kept}  {k['kind']:<12} {k['name']}  " + t("(used by {names})", names=", ".join(k["by"])))
    for u in plan["unmanaged"]:
        print(f"   {kept}  {u['kind']:<12} {u['name']}  " + t("(not installed by the manager)"))
    for name in plan["startup"]:
        print("!! " + t("{name} is in COMFY_PROFILES: it will be reinstalled at the next startup.", name=name))
    if not removed:
        print(">> " + t("Nothing to remove."))
        return 0
    if manifest.adopted and not args.dry_run:
        manifest.save()

    for i, r in enumerate(removed, 1):
        label = f"{r['kind']:<12} {r['name']}  ({human_size(r['size'])})"
        if args.dry_run:
            print("   [dry-run] " + t("remove {item}", item=label))
            continue
        print(f">> ({i}/{len(removed)}) " + t("remove {item}", item=label), flush=True)
        try:
            remove(r["path"], r["link"], paths)
            manifest.discard(r["path"])
            manifest.save()
        except KeyboardInterrupt:
            print("!! " + t("Uninstall interrupted ({done}/{total} removed).",
                            done=i - 1, total=len(removed)), file=sys.stderr)
            return 130
        except OSError as e:
            print("!! " + t("Failed: {error}", error=e), file=sys.stderr)
            return 1
    if args.dry_run:
        return 0
    print(">> " + t("Uninstall complete: {size} freed.", size=human_size(freed)))
    if any(r["kind"] == "custom_node" for r in removed):
        print(">> " + t("Custom nodes were removed: restart ComfyUI to unload them."))
    print(">> " + t("The pip packages installed for these profiles stay in the venv."))
    return 0


# --- Sizes --------------------------------------------------------------------------------
# `sizes` queries the actual size of each file (models, workflows) at its source, without
# downloading anything: Hugging Face API (paths-info), CivitAI API (model-versions), or the
# Content-Length header for a direct URL or a file in a GitHub repository. Only the files
# without "size" are queried, and the models without "sha256" whose source gives it (--force:
# all of them). Then writes in the profiles file "size" (bytes) and "sha256" on each file, and
# "size" (human-readable) on each profile, see profile_total; for a profile with variants, one
# per variant ({"int8": "18.9 GB", "bf16": "35.7 GB"}). The sha256 (Hugging Face LFS files,
# CivitAI) shows the same file installed in two places, see same_files.

# Sources whose API gives the sha256 of a file.
SHA256_SOURCES = ("hf", "civitai")

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


def http_json(url, data=None, token=None):
    headers = {"User-Agent": USER_AGENT}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    body = urllib.parse.urlencode(data, doseq=True).encode() if data else None
    for _ in range(5):
        req = urllib.request.Request(url, data=body, headers=headers)
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                return json.load(resp)
        except urllib.error.HTTPError as e:
            # urllib does not follow a 307/308 for a POST: a renamed Hugging Face repository
            # answers paths-info that way.
            if e.code not in (307, 308) or not e.headers.get("Location"):
                raise
            url = urllib.parse.urljoin(url, e.headers["Location"])
    raise LookupError(t("too many redirects"))


def hf_token():
    if os.environ.get("HF_TOKEN"):
        return os.environ["HF_TOKEN"]
    token_file = Path(os.environ.get("HF_HOME", Path.home() / ".cache" / "huggingface")) / "token"
    return token_file.read_text().strip() if token_file.is_file() else None


def hf_sizes(repo, revision, files):
    """{path: (size, sha256 or None)} of a batch of files from the same repository/revision,
    in one request. The sha256 is that of an LFS file (the oid of a plain git file is a sha1)."""
    url = (
        f"https://huggingface.co/api/models/{repo}/paths-info/"
        f"{urllib.parse.quote(revision or 'main', safe='')}"
    )
    entries = http_json(url, data={"paths": files}, token=hf_token())
    # A path that does not exist is simply missing from the response.
    return {e["path"]: ((e.get("lfs") or {}).get("size", e.get("size")), (e.get("lfs") or {}).get("oid"))
            for e in entries}


def civitai_size(version_id):
    """(size, sha256 or None) of the file served by /api/download/models/<id>: the primary
    file."""
    token = os.environ.get("CIVITAI_TOKEN")
    url = f"https://civitai.com/api/v1/model-versions/{version_id}"
    data = http_json(f"{url}?token={token}" if token else url)
    files = data.get("files") or []
    primary = next((f for f in files if f.get("primary")), files[0] if files else None)
    if not primary or primary.get("sizeKB") is None:
        raise LookupError(t("no file in this version"))
    sha256 = (primary.get("hashes") or {}).get("SHA256")
    return round(primary["sizeKB"] * 1024), sha256.lower() if sha256 else None


def url_size(url):
    req = urllib.request.Request(url, method="HEAD", headers={"User-Agent": USER_AGENT})
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


def set_size(item, size, sha256=None):
    """item["size"], and item["sha256"] right after it when known (format_config writes the
    keys in their order)."""
    if not sha256:
        item["size"] = size
        return
    fields = {}
    for key, value in item.items():
        if key != "sha256":
            fields[key] = value
        if key == "size":
            fields["sha256"] = sha256
    fields["size"] = size
    fields.setdefault("sha256", sha256)
    item.clear()
    item.update(fields)


def fetch_sizes(items):
    """items: list of (where, item). Fills in item["size"] (and item["sha256"] when the source
    gives it), returns the failures."""
    failures = []
    hf_groups = {}
    for where, item in items:
        source = source_of(item, where)
        if source == "hf":
            hf_groups.setdefault((item["hf"], item.get("revision")), []).append((where, item))
            continue
        try:
            if source == "civitai":
                set_size(item, *civitai_size(item["civitai"]))
            else:
                set_size(item, url_size(github_file_url(item) if source == "github" else item["url"]))
        except Exception as e:
            failures.append(f"{where} {describe_source(item)} : {error_text(e)}")

    for (repo, revision), group in hf_groups.items():
        try:
            sizes = hf_sizes(repo, revision, sorted({item["file"] for _, item in group}))
        except Exception as e:
            failures += [f"{where} {describe_source(item)} : {error_text(e)}" for where, item in group]
            continue
        for where, item in group:
            if sizes.get(item["file"]) is None:
                failures.append(f"{where} {describe_source(item)} : " + t("file not found in the repository"))
            else:
                set_size(item, *sizes[item["file"]])
    return failures


def same_files(profiles):
    """{sha256: [destination, ...]} of the models whose same file (same sha256) is installed at
    several destinations (<type>/<name>): to put in a shared folder."""
    places = {}
    for name, profile in profiles.items():
        for i, item in enumerate(profile.get("models", [])):
            if isinstance(item, dict) and item.get("sha256") and item.get("type"):
                try:
                    dest = f"{item['type'].strip('/')}/{target_name(item, f'[{name}] models[{i}]')}"
                except ConfigError:
                    continue
                places.setdefault(item["sha256"], {}).setdefault(dest, []).append(name)
    return {sha: dests for sha, dests in places.items() if len(dests) > 1}


def profile_size_text(total, unknown):
    text = human_size(total)
    return text + " " + t("+ {n} file(s) of unknown size", n=unknown) if unknown else text


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


def cmd_sizes(path, source, args):
    """Written to the user's file when the config is the template (read-only); the file's
    layout (one file per line, blank lines between profiles) is preserved."""
    load_env_tokens(args.env)
    text = path.read_text()
    data = json.loads(text)
    profiles = data["profiles"]  # same objects as those modified below

    items = [
        (f"[{name}] {section}", item)
        for name, profile in profiles.items()
        for section in ("models", "workflows")
        for item in profile.get(section, [])
        if args.force or not isinstance(item.get("size"), int)
        or (section == "models" and not item.get("sha256") and any(k in item for k in SHA256_SOURCES))
    ]
    print(">> " + t("{n} size(s) to fetch", n=len(items)) + (" (--force)" if args.force else ""))
    try:
        failures = fetch_sizes(items)
    except ConfigError as e:
        sys.exit(f"!! {e}")
    except KeyboardInterrupt:  # panel's Stop button: the file is only written at the end
        print("!! " + t("Size calculation interrupted, file not modified."), file=sys.stderr)
        return 130

    for name in list(profiles):
        variants = profiles[name].get("variants")
        if variants:  # a size per variant: {"int8": "18.9 GB", ...}
            size = {v: profile_size_text(*profile_total(profiles, make_ref(name, [v])))
                    for v in variants}
            shown = ", ".join(f"{v}: {text}" for v, text in size.items())
        else:
            total, unknown = profile_total(profiles, name)
            if not total and not unknown:  # only custom nodes / pip packages
                profiles[name].pop("size", None)
                continue
            size = shown = profile_size_text(total, unknown)
        profiles[name] = with_profile_size(profiles[name], size)
        print(f"   {name:<24} {shown}")

    duplicates = same_files(profiles)
    if duplicates:
        print("?? " + t("{n} file(s) installed in several places (same sha256), to put in a shared "
                        "folder:", n=len(duplicates)), file=sys.stderr)
        for sha, dests in duplicates.items():
            print(f"   {sha[:12]}", file=sys.stderr)
            for dest, names in dests.items():
                print(f"      {dest} <- {', '.join(dict.fromkeys(names))}", file=sys.stderr)

    if failures:
        print("!! " + t("{n} size(s) not found:", n=len(failures)), file=sys.stderr)
        for failure in failures:
            print(f"   - {failure}", file=sys.stderr)

    if args.dry_run:
        print(">> " + t("--dry-run: file not modified."))
    else:
        blank_before = set(re.findall(r'\n[ \t]*\n[ \t]*"([^"]+)"\s*:\s*\{', text))
        out = writable_config(path, source)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(format_config(data, blank_before), newline="\n")
        print(">> " + (t("{path} updated.", path=out) if out == path
                       else t("{path} created (the template {seed} is left as is).", path=out, seed=path)))
    return 1 if failures else 0


def main():
    parser = argparse.ArgumentParser(
        description=doc(__doc__, "comfy_profiles"),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--config", help=t("profiles file (default: $COMFY_PROFILES_CONFIG, "
                                           "<user>/__comfy_profiles/profiles.json, otherwise the "
                                           "template)"))
    sub = parser.add_subparsers(dest="command", required=True)
    lst = sub.add_parser("list", help=t("list the available profiles"))
    lst.add_argument("--json", action="store_true", help=t("JSON output"))
    sub.add_parser("where", help=t("profiles file in use, where it comes from and where to save it (JSON, without reading it)"))
    show = sub.add_parser("show", help=t("detail what profiles install, and what is already there"))
    show.add_argument("profiles")
    show.add_argument("--json", action="store_true", help=t("JSON output"))
    sync = sub.add_parser("sync", help=t("install what profiles are missing"))
    sync.add_argument("profiles", nargs="?", help=t("default: $COMFY_PROFILES"))
    sync.add_argument("--dry-run", action="store_true", help=t("show the actions without doing anything"))
    sync.add_argument("--update", action="store_true",
                      help=t("also updates what the manager installed or took over, if it changed "
                             "at the source"))
    sync.add_argument("--jobs", type=int, choices=range(1, MAX_JOBS + 1), metavar="N",
                      help=t("files downloaded at a time (default: jobs setting, see settings)"))
    adopt = sub.add_parser("adopt", help=t("take over what is already present for profiles "
                                           "(uninstall can then remove it)"))
    adopt.add_argument("profiles")
    adopt.add_argument("--dry-run", action="store_true", help=t("show what would be taken over"))
    adopt.add_argument("--json", action="store_true", help=t("JSON output"))
    uninstall = sub.add_parser("uninstall", help=t("remove what profiles installed (except what is still in use)"))
    uninstall.add_argument("profiles")
    uninstall.add_argument("--dry-run", action="store_true", help=t("show what would be removed"))
    uninstall.add_argument("--with-extends", action="store_true",
                           help=t("also uninstall the profiles they inherit from (extends)"))
    uninstall.add_argument("--json", action="store_true", help=t("JSON output (implies --dry-run)"))
    settings = sub.add_parser("settings", help=t("download settings and partial downloads (JSON)"))
    settings.add_argument("--set", metavar="JSON",
                          help=t("settings to save, e.g. '{\"jobs\": 4}' (null: back to the default)"))
    settings.add_argument("--reset", action="store_true", help=t("back to the default settings"))
    settings.add_argument("--clean-partials", action="store_true",
                          help=t("deletes partial downloads (not during a sync)"))
    settings.add_argument("--json", action="store_true", help=t("JSON output (always)"))
    sizes = sub.add_parser("sizes", help=t("query the file sizes (and sha256) at the source and write them, "
                                           "with the profile totals, in the profiles file"))
    sizes.add_argument("--env", help=t(".env file to read HF_TOKEN / CIVITAI_TOKEN from"))
    sizes.add_argument("--force", action="store_true",
                       help=t("also query the files whose size is already known"))
    sizes.add_argument("--dry-run", action="store_true", help=t("show the sizes without writing the file"))
    args = parser.parse_args()
    if args.command == "where":
        print_json(config_location(args.config))
        return
    if args.command == "settings":
        cmd_settings(args)
        return

    path, source = config_source(args.config)
    as_json = getattr(args, "json", False)
    note = " " + t("(template, read-only)") if source == "seed" else ""
    print(">> " + t("Config: {path}", path=path) + note, file=sys.stderr if as_json else sys.stdout)
    with contextlib.redirect_stdout(sys.stderr if as_json else sys.stdout):
        profiles = load_profiles(path, source)
    if args.command == "sizes":
        sys.exit(cmd_sizes(path, source, args))
    commands = {"list": cmd_list, "show": cmd_show, "sync": cmd_sync, "uninstall": cmd_uninstall,
                "adopt": cmd_adopt}
    sys.exit(commands[args.command](profiles, args) or 0)


if __name__ == "__main__":
    main()
