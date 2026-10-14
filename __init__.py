"""Panneau « Profils » dans ComfyUI : liste les profils d'utilisation (scripts/profiles.json),
montre ce qui est déjà installé, lance (ou arrête) une synchronisation ou une désinstallation
avec ses logs en direct, édite le fichier de profils et redémarre ComfyUI.

Aucun node dans le graphe : ce module ne fait qu'ajouter des routes HTTP au serveur ComfyUI et
un onglet dans la barre latérale (web/profiles.js). Tout le travail est délégué à
comfy_profiles.py (à côté de ce fichier, utilisable aussi en ligne de commande), lancé en
sous-processus avec le Python de ComfyUI : les paquets pip
s'installent ainsi dans le bon venv, et une erreur du script (sys.exit, pip...) ne peut pas
faire tomber le serveur.
"""
import asyncio
import codecs
import json
import logging
import os
import re
import signal
import sys
from pathlib import Path

from aiohttp import web
from server import PromptServer

NODE_CLASS_MAPPINGS = {}  # sans ça, ComfyUI ignore le module (et donc WEB_DIRECTORY)
WEB_DIRECTORY = "./web"

SCRIPT = Path(os.environ.get("COMFY_PROFILES_SCRIPT") or Path(__file__).parent / "comfy_profiles.py")
IMAGE_CONFIG = Path("/opt/scripts/profiles.json")
API = "/comfy-profiles"
EVENT = "comfy-profiles.log"
PROFILE_NAME = re.compile(r"[\w.-]+")
MAX_LOG_LINES = 5000
ACTIONS = ("sync", "uninstall")
# Après SIGINT (arrêt propre), délai avant de tuer le script et ses sous-processus.
STOP_TIMEOUT = 15

routes = PromptServer.instance.routes
log = logging.getLogger("comfy-profiles")


async def run_cli(*args, config=None):
    cmd = [sys.executable, str(SCRIPT)]
    if config:
        cmd += ["--config", str(config)]
    proc = await asyncio.create_subprocess_exec(
        *cmd, *args, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
    out, err = await proc.communicate()
    return proc.returncode, out.decode(errors="replace"), err.decode(errors="replace")


def cli_error(stderr):
    """Message d'erreur du script : ses lignes « !! ... », sinon la fin de stderr."""
    lines = [l.strip() for l in stderr.splitlines() if l.strip()]
    errors = [l.removeprefix("!!").strip() for l in lines if l.startswith("!!")]
    return "\n".join(errors or lines[-5:]) or "erreur inconnue"


async def cli_json(*args, config=None):
    code, out, err = await run_cli(*args, "--json", config=config)
    if code != 0:
        raise web.HTTPBadRequest(text=json.dumps({"error": cli_error(err)}),
                                 content_type="application/json")
    return json.loads(out)


def profile_names(value):
    names = value if isinstance(value, list) else str(value or "").split(",")
    names = [n.strip() for n in names if n.strip()]
    if not names or not all(PROFILE_NAME.fullmatch(n) for n in names):
        raise web.HTTPBadRequest(text=json.dumps({"error": "noms de profils invalides"}),
                                 content_type="application/json")
    return names


# --- Lecture ------------------------------------------------------------------------------

@routes.get(f"{API}/profiles")
async def list_profiles(_request):
    return web.json_response(await cli_json("list"))


@routes.get(f"{API}/status")
async def profile_status(request):
    names = profile_names(request.query.get("profiles"))
    return web.json_response(await cli_json("show", ",".join(names)))


@routes.get(f"{API}/uninstall-plan")
async def uninstall_plan(request):
    names = profile_names(request.query.get("profiles"))
    return web.json_response(await cli_json("uninstall", ",".join(names)))


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

    async def start(self, action, profiles, dry_run):
        self.action, self.profiles, self.dry_run = action, profiles, dry_run
        self.returncode, self.lines, self.stopping = None, {}, False
        args = [action, ",".join(profiles)] + (["--dry-run"] if dry_run else [])
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, str(SCRIPT), *args,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env={**os.environ, "PYTHONUNBUFFERED": "1"},
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
            log.warning("[comfy-profiles] arrêt propre trop long, processus tués")
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
    body = await request.json()
    action = body.get("action", "sync")
    if action not in ACTIONS:
        return web.json_response({"error": f"action inconnue : {action}"}, status=400)
    if job.running:
        return web.json_response({"error": "une action est déjà en cours"}, status=409)
    await job.start(action, profile_names(body.get("profiles")), bool(body.get("dry_run")))
    return web.json_response(job.state())


@routes.post(f"{API}/stop")
async def sync_stop(_request):
    if not job.running:
        return web.json_response({"error": "aucune action en cours"}, status=409)
    if not job.stopping:
        job.stop()
    return web.json_response(job.state())


# --- Fichier de profils -------------------------------------------------------------------

async def config_file():
    # `list` crée au passage le fichier de COMFY_PROFILES_CONFIG s'il n'existe pas encore
    # (copie de la config de l'image), on peut donc ensuite le lire.
    return Path((await cli_json("list"))["config"])


@routes.get(f"{API}/config")
async def get_config(_request):
    path = await config_file()
    return web.json_response({
        "path": str(path),
        "in_image": path.resolve() == IMAGE_CONFIG,
        "text": path.read_text(),
    })


@routes.put(f"{API}/config")
async def put_config(request):
    text = (await request.json()).get("text", "")
    try:
        names = list(json.loads(text).get("profiles") or {})
    except (json.JSONDecodeError, AttributeError) as e:
        return web.json_response({"error": f"JSON invalide : {e}"}, status=400)
    path = await config_file()
    # Validé sur une copie avant de remplacer le fichier : `list` vérifie les clés des profils,
    # `show` de tous les profils vérifie les extends et chaque modèle / custom node.
    tmp = path.with_name(f".{path.name}.edit")
    tmp.write_text(text)
    try:
        await cli_json("list", config=tmp)
        if names:
            await cli_json("show", ",".join(names), config=tmp)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("[comfy-profiles] %s mis à jour depuis l'interface", path)
    return web.json_response({"ok": True, "path": str(path)})


# --- Redémarrage --------------------------------------------------------------------------

def restart():
    # Même PID (exec) : ComfyUI est le processus principal du conteneur (exec dans
    # entrypoint.sh), le pod reste donc en vie ; SSH et JupyterLab ne sont pas touchés.
    log.info("[comfy-profiles] redémarrage de ComfyUI")
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    os.execv(sys.executable, [sys.executable, *sys.argv])


@routes.post(f"{API}/restart")
async def restart_comfy(_request):
    if job.running:
        return web.json_response({"error": "action en cours, redémarrage refusé"}, status=409)
    # Laisse partir la réponse avant de remplacer le processus.
    asyncio.get_running_loop().call_later(0.5, restart)
    return web.json_response({"ok": True})
