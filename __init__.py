"""Panneau « Profils » dans ComfyUI : liste les profils d'utilisation (profiles.json), montre ce
qui est déjà installé, lance (ou arrête) une synchronisation, une désinstallation ou le calcul
des tailles avec ses logs en direct, édite, importe ou exporte le fichier de profils et
redémarre ComfyUI.

Ce module ajoute des routes HTTP au serveur ComfyUI, un onglet dans la barre latérale
(web/profiles.js) et un seul node, « Workflow profiles » (profiles_node.py), jamais exécuté, qui
déclare dans un workflow les profils dont il a besoin. Tout le travail est délégué à
comfy_profiles.py (à côté de ce fichier, utilisable aussi en ligne de commande), lancé en
sous-processus avec le Python de ComfyUI : les paquets pip
s'installent ainsi dans le bon venv, et une erreur du script (sys.exit, pip...) ne peut pas
faire tomber le serveur. Le script reçoit les chemins de ce ComfyUI (base, models, custom_nodes,
user) par l'environnement : il travaille donc au même endroit que le serveur, quelle que soit la
façon dont ComfyUI a été lancé (--base-directory, --user-directory...).

COMFY_PROFILES_READONLY=1 : panneau en lecture seule (ni installation, ni désinstallation, ni
modification du fichier de profils, ni redémarrage ; le dry-run reste possible).

Langue : le panneau envoie celle de ComfyUI dans l'en-tête Comfy-Profiles-Lang ; les messages
d'erreur des routes et ceux du script (COMFY_PROFILES_LANG) suivent. Voir profiles_i18n.py.
"""
import asyncio
import codecs
import functools
import json
import logging
import os
import re
import signal
import sys
from pathlib import Path

import aiohttp
import folder_paths
from aiohttp import web
from server import PromptServer

from . import profiles_i18n as i18n
from .profiles_merge import MergeError, merge
from .profiles_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

SCRIPT = Path(os.environ.get("COMFY_PROFILES_SCRIPT") or Path(__file__).parent / "comfy_profiles.py")
SIZES_SCRIPT = Path(__file__).parent / "profile_sizes.py"
API = "/comfy-profiles"
EVENT = "comfy-profiles.log"
PROFILE_NAME = re.compile(r"[\w.-]+")
MAX_LOG_LINES = 5000
ACTIONS = ("sync", "uninstall", "sizes")
# Après SIGINT (arrêt propre), délai avant de tuer le script et ses sous-processus.
STOP_TIMEOUT = 15
# Import depuis une URL : taille maximale du fichier de profils.
MAX_CONFIG_BYTES = 5 * 1024 * 1024
READONLY = os.environ.get("COMFY_PROFILES_READONLY", "").lower() in ("1", "true", "yes")

LANG_HEADER = "Comfy-Profiles-Lang"

routes = PromptServer.instance.routes
log = logging.getLogger("comfy-profiles")
t = i18n.t  # messages du serveur (logs) : langue de l'environnement


def request_lang(request):
    """Langue du panneau qui fait la requête, sinon celle de l'environnement."""
    return i18n.normalize(request.headers.get(LANG_HEADER)) or i18n.detect()


def tr(request):
    return i18n.translator(request_lang(request))


def cli_env(lang=None):
    """Environnement des scripts : les chemins de ce ComfyUI, tels que le serveur les voit, et
    la langue des messages."""
    return {
        **os.environ,
        **({"COMFY_PROFILES_LANG": lang} if lang else {}),
        "PYTHONUNBUFFERED": "1",
        "COMFY_HOME": folder_paths.base_path,
        "COMFY_MODELS_DIR": folder_paths.models_dir,
        "COMFY_CUSTOM_NODES_DIR": folder_paths.get_folder_paths("custom_nodes")[0],
        "COMFY_USER_DIR": folder_paths.get_user_directory(),
        # Dossiers de chaque type de modèle, extra_model_paths.yaml compris, dans l'ordre de
        # ComfyUI : un modèle est trouvé où que ComfyUI le voie.
        "COMFY_MODEL_FOLDERS": json.dumps({
            name: folder_paths.get_folder_paths(name)
            for name in folder_paths.folder_names_and_paths if name != "custom_nodes"
        }),
    }


def json_error(status, message):
    return web.json_response({"error": message}, status=status)


def bad_request(message):
    return web.HTTPBadRequest(text=json.dumps({"error": message}), content_type="application/json")


def writes(handler):
    """Route qui modifie l'installation ou le fichier de profils : refusée en lecture seule."""
    @functools.wraps(handler)
    async def guarded(request):
        if READONLY:
            return json_error(403, tr(request)("panneau en lecture seule (COMFY_PROFILES_READONLY)"))
        return await handler(request)
    return guarded


async def run_cli(*args, config=None, lang=None):
    cmd = [sys.executable, str(SCRIPT)]
    if config:
        cmd += ["--config", str(config)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE, env=cli_env(lang))
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


def cli_error(stderr, translate=t):
    """Message d'erreur du script : ses lignes « !! ... », sinon la fin de stderr."""
    lines = [l.strip() for l in stderr.splitlines() if l.strip()]
    errors = [l.removeprefix("!!").strip() for l in lines if l.startswith("!!")]
    return "\n".join(errors or lines[-5:]) or translate("erreur inconnue")


async def cli_json(*args, request, config=None):
    """Lance le script avec --json, dans la langue du panneau qui fait la requête."""
    lang = request_lang(request)
    code, out, err = await run_cli(*args, "--json", config=config, lang=lang)
    if code != 0:
        raise bad_request(cli_error(err, i18n.translator(lang)))
    return json.loads(out)


def profile_names(value, request):
    names = value if isinstance(value, list) else str(value or "").split(",")
    names = [n.strip() for n in names if n.strip()]
    if not names or not all(PROFILE_NAME.fullmatch(n) for n in names):
        raise bad_request(tr(request)("noms de profils invalides"))
    return names


# --- Lecture ------------------------------------------------------------------------------

@routes.get(f"{API}/lang/{{code}}")
async def lang_catalog(request):
    """Traductions pour le panneau : {message français: traduction} ({} pour le français)."""
    code = i18n.normalize(request.match_info["code"]) or i18n.DEFAULT_LANG
    messages = {k: v for k, v in i18n.catalog(code).items() if not k.startswith("__doc__:")}
    return web.json_response({"lang": code, "messages": messages})


@routes.get(f"{API}/profiles")
async def list_profiles(request):
    return web.json_response({**await cli_json("list", request=request), "readonly": READONLY})


@routes.get(f"{API}/status")
async def profile_status(request):
    names = profile_names(request.query.get("profiles"), request)
    return web.json_response(await cli_json("show", ",".join(names), request=request))


@routes.get(f"{API}/uninstall-plan")
async def uninstall_plan(request):
    names = profile_names(request.query.get("profiles"), request)
    extends = ["--with-extends"] if request.query.get("with_extends") in ("1", "true") else []
    return web.json_response(await cli_json("uninstall", ",".join(names), *extends, request=request))


@routes.post(f"{API}/adopt")
@writes
async def adopt(request):
    """Prend en charge ce qui est déjà présent pour des profils (voir comfy_profiles.cmd_adopt)."""
    if job.running:
        return json_error(409, tr(request)("une action est déjà en cours"))
    names = profile_names((await request.json()).get("profiles"), request)
    result = await cli_json("adopt", ",".join(names), request=request)
    log.info("[comfy-profiles] %s", t("{names} : {n} élément(s) pris en charge",
                                      names=",".join(names), n=len(result["adopted"])))
    return web.json_response(result)


# --- Synchronisation / désinstallation -----------------------------------------------------

class Job:
    """Une seule action (sync ou uninstall) à la fois. Les logs sont gardés côté serveur pour
    qu'un panneau ouvert en cours de route (ou après un rechargement de la page) les retrouve."""

    def __init__(self):
        self.proc = None
        self.action = "sync"
        self.stopping = False
        self.profiles = []
        self.dry_run = False
        self.returncode = None
        self.lines = {}  # index -> texte ; une barre de progression réécrit son index
        self.next_index = 0

    @property
    def running(self):
        return self.proc is not None and self.returncode is None

    def state(self):
        return {
            "running": self.running,
            "action": self.action,
            "stopping": self.stopping,
            "profiles": self.profiles,
            "dry_run": self.dry_run,
            "returncode": self.returncode,
            "lines": sorted(self.lines.items()),
        }

    def emit(self, index, text):
        self.lines[index] = text
        for old in [i for i in self.lines if i <= index - MAX_LOG_LINES]:
            del self.lines[old]
        PromptServer.instance.send_sync(EVENT, {"index": index, "text": text})

    async def start(self, action, profiles, dry_run, with_extends=False, lang=None, force=False):
        self.action, self.profiles, self.dry_run = action, profiles, dry_run
        self.returncode, self.lines, self.stopping = None, {}, False
        if action == "sizes":  # tous les profils, écrit les tailles dans le fichier de profils
            # force : réinterroge aussi les fichiers dont la taille est déjà connue.
            cmd = [SIZES_SCRIPT] + (["--dry-run"] if dry_run else []) + (["--force"] if force else [])
        else:
            cmd = [SCRIPT, action, ",".join(profiles)] + (["--dry-run"] if dry_run else [])
            if action == "uninstall" and with_extends:
                cmd.append("--with-extends")
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, *map(str, cmd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=cli_env(lang),
            # Groupe de processus à part : en dernier recours, on tue aussi git, pip...
            start_new_session=True)
        asyncio.create_task(self.pump())

    def stop(self):
        # SIGINT au seul script : KeyboardInterrupt, il abandonne proprement l'étape en cours
        # (fichiers .part, clone partiel...) et subprocess.run tue la commande qu'il attendait.
        self.stopping = True
        self.proc.send_signal(signal.SIGINT)
        asyncio.create_task(self.kill_after_timeout(self.proc))

    async def kill_after_timeout(self, proc):
        try:
            await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("[comfy-profiles] %s", t("arrêt propre trop long, processus tués"))
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def pump(self):
        # Découpe sur \n et \r : les barres de progression (téléchargements HF, pip) se
        # réécrivent avec \r, on remplace alors la ligne en cours au lieu d'en ajouter une.
        decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
        buffer = ""
        while True:
            chunk = await self.proc.stdout.read(65536)
            buffer += decoder.decode(chunk, final=not chunk)
            while True:
                match = re.search(r"\r\n|\r|\n", buffer)
                if not match:
                    break
                text, sep, buffer = buffer[:match.start()], match.group(), buffer[match.end():]
                if sep == "\r":
                    if text:
                        self.emit(self.next_index, text)
                else:
                    self.emit(self.next_index, text)
                    self.next_index += 1
            if not chunk:
                break
        if buffer:
            self.emit(self.next_index, buffer)
            self.next_index += 1
        self.returncode = await self.proc.wait()
        PromptServer.instance.send_sync(EVENT, {"done": True, "returncode": self.returncode,
                                                "action": self.action, "dry_run": self.dry_run})


job = Job()


@routes.get(f"{API}/sync")
async def sync_state(_request):
    return web.json_response(job.state())


@routes.post(f"{API}/sync")
async def sync_start(request):
    _ = tr(request)
    body = await request.json()
    action = body.get("action", "sync")
    if action not in ACTIONS:
        return json_error(400, _("action inconnue : {action}", action=action))
    if job.running:
        return json_error(409, _("une action est déjà en cours"))
    dry_run = bool(body.get("dry_run"))
    if READONLY and not (dry_run and action != "sizes"):
        return json_error(403, _("panneau en lecture seule (COMFY_PROFILES_READONLY) : dry-run seulement"))
    profiles = [] if action == "sizes" else profile_names(body.get("profiles"), request)
    await job.start(action, profiles, dry_run, bool(body.get("with_extends")), request_lang(request),
                    force=bool(body.get("force")))
    return web.json_response(job.state())


@routes.post(f"{API}/stop")
async def sync_stop(request):
    if not job.running:
        return json_error(409, tr(request)("aucune action en cours"))
    if not job.stopping:
        job.stop()
    return web.json_response(job.state())


# --- Fichier de profils -------------------------------------------------------------------

async def config_info(request):
    """Fichier de profils actif, son origine (option, env, user, seed) et où l'enregistrer."""
    # `where` ne lit pas le fichier : un fichier invalide peut ainsi être corrigé ou remplacé.
    lang = request_lang(request)
    code, out, err = await run_cli("where", lang=lang)
    if code != 0:
        raise bad_request(cli_error(err, i18n.translator(lang)))
    data = json.loads(out)
    return Path(data["config"]), data["source"], Path(data["writable"])


@routes.get(f"{API}/config")
async def get_config(request):
    path, source, writable = await config_info(request)
    return web.json_response({
        "path": str(path),
        "source": source,
        "writable": str(writable),
        "text": path.read_text(),
    })


async def save_config(text, origin, request):
    """Valide `text` sur une copie, puis remplace le fichier de profils modifiable (celui de
    l'utilisateur quand le modèle était actif)."""
    try:
        names = list(json.loads(text).get("profiles") or {})
    except (json.JSONDecodeError, AttributeError) as e:
        return json_error(400, tr(request)("JSON invalide : {error}", error=e))
    _, _, path = await config_info(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    # `list` vérifie les clés des profils, `show` de tous les profils vérifie les extends et
    # chaque modèle / custom node.
    tmp = path.with_name(f".{path.name}.edit")
    tmp.write_text(text)
    try:
        await cli_json("list", config=tmp, request=request)
        if names:
            await cli_json("show", ",".join(names), config=tmp, request=request)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("[comfy-profiles] %s", t("{path} mis à jour ({origin})", path=path, origin=origin))
    return web.json_response({"ok": True, "path": str(path)})


@routes.put(f"{API}/config")
@writes
async def put_config(request):
    body = await request.json()
    return await save_config(body.get("text", ""), body.get("origin") or t("édition dans le panneau"), request)


async def fetch_config(url, request):
    """Texte d'un fichier de profils publié à `url` (ex. lien raw GitHub ou gist)."""
    _ = tr(request)
    if not url.startswith(("https://", "http://")):
        raise bad_request(_("URL http(s) attendue"))
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, headers={"User-Agent": "comfyui-profiles"}) as resp:
                if resp.status != 200:
                    raise bad_request(f"{url} : HTTP {resp.status}")
                body = await resp.content.read(MAX_CONFIG_BYTES + 1)
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise bad_request(f"{url} : {e or type(e).__name__}")
    if len(body) > MAX_CONFIG_BYTES:
        raise bad_request(_("{url} : fichier trop gros (plus de {size})", url=url,
                            size=i18n.human_size(MAX_CONFIG_BYTES, _)))
    return body.decode("utf-8", errors="replace")


@routes.post(f"{API}/config/import-url")
@writes
async def import_config_url(request):
    url = str((await request.json()).get("url") or "").strip()
    text = await fetch_config(url, request)
    return await save_config(text, t("import de {url}", url=url), request)


@routes.post(f"{API}/config/add-from-url")
@writes
async def add_profiles_from_url(request):
    """Ajoute au fichier de profils des profils (et ceux dont ils héritent) pris dans celui
    publié à une URL, sans rien remplacer : la source déclarée par le node « Workflow
    profiles » d'un workflow. Voir profiles_merge.py."""
    body = await request.json()
    url = str(body.get("url") or "").strip()
    names = profile_names(body.get("profiles"), request)
    source = await fetch_config(url, request)
    path, _, _ = await config_info(request)
    try:
        text, result = merge(path.read_text(), source, names, tr(request))
    except MergeError as e:
        return json_error(400, str(e))
    if result["added"]:
        response = await save_config(text, t("profils ajoutés depuis {url}", url=url), request)
        if response.status != 200:
            return response
    return web.json_response(result)


@routes.delete(f"{API}/config")
@writes
async def reset_config(request):
    """Revient au modèle : le fichier de l'utilisateur est mis de côté en profiles.json.bak."""
    path, source, _ = await config_info(request)
    if source != "user":
        return json_error(409, tr(request)(
            "le fichier actif n'est pas celui de l'utilisateur, rien à réinitialiser"))
    backup = path.with_name(f"{path.name}.bak")
    path.replace(backup)
    log.info("[comfy-profiles] %s", t("retour au modèle, ancien fichier gardé en {path}", path=backup))
    return web.json_response({"ok": True, "backup": str(backup)})


# --- Redémarrage --------------------------------------------------------------------------

def restart():
    """Comme le redémarrage de ComfyUI-Manager : sous comfy-cli, on signale le redémarrage et on
    quitte (comfy-cli relance) ; sinon, même PID (exec) : un conteneur dont ComfyUI est le
    processus principal reste en vie."""
    log.info("[comfy-profiles] %s", t("redémarrage de ComfyUI"))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    if "__COMFY_CLI_SESSION__" in os.environ:
        Path(os.environ["__COMFY_CLI_SESSION__"] + ".reboot").touch()
        os._exit(0)
    argv = [a for a in sys.argv if a != "--windows-standalone-build"]
    if argv[0].endswith("__main__.py"):  # lancé en module (python -m ...)
        cmd = [sys.executable, "-m", Path(argv[0]).parent.name, *argv[1:]]
    elif sys.platform.startswith("win32"):
        cmd = [f'"{sys.executable}"', f'"{argv[0]}"', *argv[1:]]
    else:
        cmd = [sys.executable, *argv]
    os.execv(sys.executable, cmd)


@routes.post(f"{API}/restart")
@writes
async def restart_comfy(request):
    if job.running:
        return json_error(409, tr(request)("action en cours, redémarrage refusé"))
    # Laisse partir la réponse avant de remplacer le processus.
    asyncio.get_running_loop().call_later(0.5, restart)
    return web.json_response({"ok": True})
