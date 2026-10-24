""""Profiles" panel in ComfyUI: lists the usage profiles (profiles.json), shows what is already
installed, starts (or stops) a sync, an uninstall or the size computation with its live logs,
edits, imports or exports the profiles file, sets the download options and restarts ComfyUI.

This module adds HTTP routes to the ComfyUI server, a sidebar tab (web/profiles.js) and a
single node, "Workflow profiles" (profiles_node.py), never executed, which declares in a
workflow the profiles it needs. All the work is delegated to comfy_profiles.py (next to this
file, also usable from the command line), run as a subprocess with ComfyUI's Python: pip
packages are thus installed in the right venv, and an error in the script (sys.exit, pip...)
cannot bring the server down. The script gets the paths of this ComfyUI (base, models,
custom_nodes, user) from the environment: it therefore works in the same place as the server,
however ComfyUI was started (--base-directory, --user-directory...).

COMFY_PROFILES_READONLY=1: read-only panel (no install, no uninstall, no change to the profiles
file, no restart; dry-run is still possible).

Language: the panel sends ComfyUI's language in the Comfy-Profiles-Lang header; the error
messages of the routes and of the script (COMFY_PROFILES_LANG) follow it. See profiles_i18n.py.
"""
import asyncio
import codecs
import functools
import hashlib
import json
import logging
import os
import re
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path

import aiohttp
import folder_paths
from aiohttp import web
from server import PromptServer

from . import profiles_i18n as i18n
from .profiles_merge import MergeError, compare, merge, update
from .profiles_node import NODE_CLASS_MAPPINGS, NODE_DISPLAY_NAME_MAPPINGS

WEB_DIRECTORY = "./web"

SCRIPT = Path(os.environ.get("COMFY_PROFILES_SCRIPT") or Path(__file__).parent / "comfy_profiles.py")
API = "/comfy-profiles"
EVENT = "comfy-profiles.log"
# A profile, optionally with variants: krea2-turbo, krea2-raw[int8,bf16], krea2-raw[] (common
# items only), see comfy_profiles.py.
PROFILE_NAME = re.compile(r"[\w.-]+(\[([\w.-]+(,[\w.-]+)*)?\])?")
MAX_LOG_LINES = 5000
ACTIONS = ("sync", "uninstall", "sizes")
# After SIGINT (clean stop), delay before killing the script and its subprocesses.
STOP_TIMEOUT = 15
# Import from a URL: maximum size of the profiles file.
MAX_CONFIG_BYTES = 5 * 1024 * 1024
# Import from a URL: the last URLs used, most recent first, in <user>/__comfy_profiles/remotes.json.
REMOTES_NAME = "remotes.json"
MAX_REMOTES = 10
READONLY = os.environ.get("COMFY_PROFILES_READONLY", "").lower() in ("1", "true", "yes")

LANG_HEADER = "Comfy-Profiles-Lang"

routes = PromptServer.instance.routes
log = logging.getLogger("comfy-profiles")
t = i18n.t  # server messages (logs): language of the environment


def request_lang(request):
    """Language of the panel making the request, otherwise that of the environment."""
    return i18n.normalize(request.headers.get(LANG_HEADER)) or i18n.detect()


def tr(request):
    return i18n.translator(request_lang(request))


def cli_env(lang=None):
    """Environment of the scripts: the paths of this ComfyUI, as the server sees them, and the
    language of the messages."""
    return {
        **os.environ,
        **({"COMFY_PROFILES_LANG": lang} if lang else {}),
        "PYTHONUNBUFFERED": "1",
        "COMFY_HOME": folder_paths.base_path,
        "COMFY_MODELS_DIR": folder_paths.models_dir,
        "COMFY_CUSTOM_NODES_DIR": folder_paths.get_folder_paths("custom_nodes")[0],
        "COMFY_USER_DIR": folder_paths.get_user_directory(),
        # Folders of each model type, extra_model_paths.yaml included, in ComfyUI's order: a
        # model is found wherever ComfyUI sees it.
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
    """Route that changes the installation or the profiles file: refused when read-only."""
    @functools.wraps(handler)
    async def guarded(request):
        if READONLY:
            return json_error(403, tr(request)("read-only panel (COMFY_PROFILES_READONLY)"))
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
    """Error message of the script: its "!! ..." lines, otherwise the end of stderr."""
    lines = [l.strip() for l in stderr.splitlines() if l.strip()]
    errors = [l.removeprefix("!!").strip() for l in lines if l.startswith("!!")]
    return "\n".join(errors or lines[-5:]) or translate("unknown error")


async def cli_json(*args, request, config=None):
    """Runs the script with --json, in the language of the panel making the request."""
    lang = request_lang(request)
    code, out, err = await run_cli(*args, "--json", config=config, lang=lang)
    if code != 0:
        raise bad_request(cli_error(err, i18n.translator(lang)))
    return json.loads(out)


def profile_names(value, request):
    # Commas separate the profiles, except between brackets (variants).
    names = value if isinstance(value, list) else re.split(r",(?![^\[]*\])", str(value or ""))
    names = [re.sub(r"\s+", "", str(n)) for n in names if str(n).strip()]
    if not names or not all(PROFILE_NAME.fullmatch(n) for n in names):
        raise bad_request(tr(request)("invalid profile names"))
    return names


# --- Lecture ------------------------------------------------------------------------------

@routes.get(f"{API}/lang/{{code}}")
async def lang_catalog(request):
    """Translations for the panel: {English message: translation} ({} for English)."""
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


@routes.get(f"{API}/uninstall-check")
async def uninstall_check(request):
    """For each profile, what uninstalling it alone would remove, in short (uninstall --each)."""
    names = profile_names(request.query.get("profiles"), request)
    return web.json_response(await cli_json("uninstall", ",".join(names), "--each", request=request))


@routes.post(f"{API}/adopt")
@writes
async def adopt(request):
    """Takes over what is already there for some profiles (see comfy_profiles.cmd_adopt)."""
    if job.running:
        return json_error(409, tr(request)("an action is already running"))
    names = profile_names((await request.json()).get("profiles"), request)
    result = await cli_json("adopt", ",".join(names), request=request)
    log.info("[comfy-profiles] %s", t("{names}: {n} item(s) taken over",
                                      names=",".join(names), n=len(result["adopted"])))
    return web.json_response(result)


# --- Sync / uninstall ---------------------------------------------------------------------

class Job:
    """A single action (sync or uninstall) at a time. Logs are kept on the server side so that a
    panel opened along the way (or after a page reload) finds them again."""

    def __init__(self):
        self.proc = None
        self.action = "sync"
        self.stopping = False
        self.profiles = []
        self.dry_run = False
        self.force = False
        self.returncode = None
        self.lines = {}  # index -> text; a progress bar rewrites its index
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
            "force": self.force,
            "returncode": self.returncode,
            "lines": sorted(self.lines.items()),
        }

    def emit(self, index, text):
        self.lines[index] = text
        for old in [i for i in self.lines if i <= index - MAX_LOG_LINES]:
            del self.lines[old]
        PromptServer.instance.send_sync(EVENT, {"index": index, "text": text})

    async def start(self, action, profiles, dry_run, with_extends=False, lang=None, force=False):
        self.action, self.profiles, self.dry_run, self.force = action, profiles, dry_run, force
        self.returncode, self.lines, self.stopping = None, {}, False
        if action == "sizes":  # all profiles, writes the sizes into the profiles file
            # force: also queries again the files whose size is already known.
            cmd = [SCRIPT, "sizes"] + (["--dry-run"] if dry_run else []) + (["--force"] if force else [])
        else:
            cmd = [SCRIPT, action, ",".join(profiles)] + (["--dry-run"] if dry_run else [])
            if action == "uninstall" and with_extends:
                cmd.append("--with-extends")
            if action == "sync" and force:  # also updates what changed at the source
                cmd.append("--update")
        self.proc = await asyncio.create_subprocess_exec(
            sys.executable, *map(str, cmd),
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.STDOUT,
            env=cli_env(lang),
            # Separate process group: as a last resort, git, pip... are killed too.
            start_new_session=True)
        asyncio.create_task(self.pump())

    def stop(self):
        # SIGINT to the script alone: KeyboardInterrupt, it stops the current step cleanly
        # (partial clone removed, downloads keep their .part) and subprocess.run kills the
        # command it was waiting for.
        self.stopping = True
        self.proc.send_signal(signal.SIGINT)
        asyncio.create_task(self.kill_after_timeout(self.proc))

    async def kill_after_timeout(self, proc):
        try:
            await asyncio.wait_for(proc.wait(), STOP_TIMEOUT)
        except asyncio.TimeoutError:
            log.warning("[comfy-profiles] %s", t("clean stop took too long, processes killed"))
            try:
                os.killpg(proc.pid, signal.SIGKILL)
            except ProcessLookupError:
                pass

    async def pump(self):
        # Splits on \n and \r: progress lines (downloads, pip) rewrite themselves with \r, so
        # the current line is replaced instead of adding a new one.
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
                                                "action": self.action, "dry_run": self.dry_run,
                                                "force": self.force})


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
        return json_error(400, _("unknown action: {action}", action=action))
    if job.running:
        return json_error(409, _("an action is already running"))
    dry_run = bool(body.get("dry_run"))
    if READONLY and not (dry_run and action != "sizes"):
        return json_error(403, _("read-only panel (COMFY_PROFILES_READONLY): dry-run only"))
    profiles = [] if action == "sizes" else profile_names(body.get("profiles"), request)
    await job.start(action, profiles, dry_run, bool(body.get("with_extends")), request_lang(request),
                    force=bool(body.get("force")))
    return web.json_response(job.state())


@routes.post(f"{API}/stop")
async def sync_stop(request):
    if not job.running:
        return json_error(409, tr(request)("no action running"))
    if not job.stopping:
        job.stop()
    return web.json_response(job.state())


# --- Fichier de profils -------------------------------------------------------------------

async def config_info(request):
    """Active profiles file, its origin (option, env, user, seed) and where to save it."""
    # `where` does not read the file: an invalid file can thus be fixed or replaced.
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
    """Validates `text` on a copy, then replaces the writable profiles file (the user's one when
    the template was active)."""
    try:
        profiles = json.loads(text).get("profiles") or {}
        # Each profile with all its variants, so that all their items are checked.
        names = [f"{name}[{','.join(p['variants'])}]"
                 if isinstance(p, dict) and isinstance(p.get("variants"), list) and p["variants"] else name
                 for name, p in profiles.items()]
    except (json.JSONDecodeError, AttributeError, TypeError) as e:
        return json_error(400, tr(request)("Invalid JSON: {error}", error=e))
    _, _, path = await config_info(request)
    path.parent.mkdir(parents=True, exist_ok=True)
    # `list` checks the profile keys, `show` of all the profiles checks the extends and each
    # model / custom node.
    tmp = path.with_name(f".{path.name}.edit")
    tmp.write_text(text)
    try:
        await cli_json("list", config=tmp, request=request)
        if names:
            await cli_json("show", ",".join(names), config=tmp, request=request)
        tmp.replace(path)
    finally:
        tmp.unlink(missing_ok=True)
    log.info("[comfy-profiles] %s", t("{path} updated ({origin})", path=path, origin=origin))
    return web.json_response({"ok": True, "path": str(path)})


@routes.put(f"{API}/config")
@writes
async def put_config(request):
    body = await request.json()
    return await save_config(body.get("text", ""), body.get("origin") or t("edited in the panel"), request)


async def fetch_config(url, request):
    """Text of a profiles file published at `url` (e.g. a raw GitHub or gist link)."""
    _ = tr(request)
    if not url.startswith(("https://", "http://")):
        raise bad_request(_("http(s) URL expected"))
    try:
        timeout = aiohttp.ClientTimeout(total=30)
        # github.com/.../raw/... answers with a Content-Security-Policy header over aiohttp's
        # default limit (8190 bytes) before redirecting to raw.githubusercontent.com.
        async with aiohttp.ClientSession(timeout=timeout, max_line_size=65536,
                                         max_field_size=65536) as session:
            async with session.get(url, headers={"User-Agent": "comfyui-profiles"}) as resp:
                if resp.status != 200:
                    raise bad_request(f"{url} : HTTP {resp.status}")
                # read(n) returns what has arrived (at most n bytes), not n bytes: read up to EOF
                body = b""
                while len(body) <= MAX_CONFIG_BYTES:
                    chunk = await resp.content.read(MAX_CONFIG_BYTES + 1 - len(body))
                    if not chunk:
                        break
                    body += chunk
    except (aiohttp.ClientError, asyncio.TimeoutError) as e:
        raise bad_request(f"{url} : {e or type(e).__name__}")
    if len(body) > MAX_CONFIG_BYTES:
        raise bad_request(_("{url}: file too large (over {size})", url=url,
                            size=i18n.human_size(MAX_CONFIG_BYTES, _)))
    return body.decode("utf-8", errors="replace")


def remotes_file():
    return Path(folder_paths.get_user_directory()) / "__comfy_profiles" / REMOTES_NAME


def load_remotes():
    """[{"url", "date"}] of the last imports from a URL, most recent first ([] if unreadable)."""
    try:
        remotes = json.loads(remotes_file().read_text())
        return [r for r in remotes if isinstance(r, dict) and isinstance(r.get("url"), str)]
    except (OSError, ValueError, TypeError):
        return []


def save_remotes(remotes):
    path = remotes_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(f".{path.name}.tmp")
    tmp.write_text(json.dumps(remotes[:MAX_REMOTES], indent=2))
    tmp.replace(path)


@routes.get(f"{API}/config/remotes")
async def get_remotes(_request):
    return web.json_response({"remotes": load_remotes()})


@routes.delete(f"{API}/config/remotes")
@writes
async def delete_remote(request):
    """Forgets a URL of the list (all of them without `url`)."""
    url = (await request.json()).get("url")
    remotes = [r for r in load_remotes() if url is not None and r["url"] != url]
    save_remotes(remotes)
    return web.json_response({"remotes": remotes})


def digest(text):
    return hashlib.sha256(text.encode()).hexdigest()


@routes.post(f"{API}/config/compare-url")
async def compare_config_url(request):
    """What importing the file published at `url` would change: profiles new, different (item
    by item), identical, and only in the local file. `sha256` is to be sent back to
    /config/import-url, which refuses the import if the remote file has changed meanwhile."""
    url = str((await request.json()).get("url") or "").strip()
    source = await fetch_config(url, request)
    path, origin, _ = await config_info(request)
    try:
        result = compare(path.read_text(), source, tr(request))
    except MergeError as e:
        return json_error(400, str(e))
    return web.json_response({**result, "url": url, "sha256": digest(source), "source": origin})


@routes.post(f"{API}/config/import-url")
@writes
async def import_config_url(request):
    """mode "replace" (default): the remote file replaces the profiles file; "merge": only the
    `profiles` listed are taken from it (added, or replacing the local version)."""
    body = await request.json()
    url = str(body.get("url") or "").strip()
    text = await fetch_config(url, request)
    if body.get("sha256") and body["sha256"] != digest(text):
        return json_error(409, tr(request)("{url} changed since the comparison: compare again", url=url))
    result = {}
    if body.get("mode") == "merge":
        path, _, _ = await config_info(request)
        try:
            text, result = update(path.read_text(), text, profile_names(body.get("profiles"), request),
                                  tr(request))
        except MergeError as e:
            return json_error(400, str(e))
        origin = t("merge from {url}", url=url)
    else:
        origin = t("import from {url}", url=url)
    response = await save_config(text, origin, request)
    if response.status == 200:
        date = datetime.now(timezone.utc).isoformat(timespec="seconds")
        save_remotes([{"url": url, "date": date}, *(r for r in load_remotes() if r["url"] != url)])
        response = web.json_response({**json.loads(response.text), **result})
    return response


@routes.post(f"{API}/config/add-from-url")
@writes
async def add_profiles_from_url(request):
    """Adds to the profiles file some profiles (and those they inherit from) taken from the one
    published at a URL, without replacing anything: the source declared by a workflow's
    "Workflow profiles" node. See profiles_merge.py."""
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
        response = await save_config(text, t("profiles added from {url}", url=url), request)
        if response.status != 200:
            return response
    return web.json_response(result)


@routes.delete(f"{API}/config")
@writes
async def reset_config(request):
    """Back to the template: the user's file is set aside as profiles.json.bak."""
    path, source, _ = await config_info(request)
    if source != "user":
        return json_error(409, tr(request)(
            "the active file is not the user's file, nothing to reset"))
    backup = path.with_name(f"{path.name}.bak")
    path.replace(backup)
    log.info("[comfy-profiles] %s", t("back to the template, old file kept as {path}", path=backup))
    return web.json_response({"ok": True, "backup": str(backup)})


# --- Download settings --------------------------------------------------------------------

@routes.get(f"{API}/settings")
async def get_settings(request):
    """Effective, saved and default settings, versions of huggingface_hub / hf_xet and partial
    downloads (see comfy_profiles.cmd_settings)."""
    return web.json_response(await cli_json("settings", request=request))


@routes.put(f"{API}/settings")
@writes
async def put_settings(request):
    """Saves settings ({key: value}, null: back to the default); they apply to the next sync."""
    values = (await request.json()).get("values")
    if not isinstance(values, dict):
        return json_error(400, tr(request)("JSON object expected"))
    result = await cli_json("settings", "--set", json.dumps(values), request=request)
    log.info("[comfy-profiles] %s", t("download settings updated: {values}",
                                      values=json.dumps(result["saved"])))
    return web.json_response(result)


@routes.delete(f"{API}/settings")
@writes
async def reset_settings(request):
    return web.json_response(await cli_json("settings", "--reset", request=request))


@routes.post(f"{API}/settings/clean-partials")
@writes
async def clean_partials(request):
    """Deletes the partial downloads: never during an action, which may resume them."""
    if job.running:
        return json_error(409, tr(request)("an action is already running"))
    return web.json_response(await cli_json("settings", "--clean-partials", request=request))


# --- Restart ------------------------------------------------------------------------------

def restart():
    """Like ComfyUI-Manager's restart: under comfy-cli, the restart is signaled and the process
    exits (comfy-cli starts it again); otherwise, same PID (exec): a container whose main process
    is ComfyUI stays alive."""
    log.info("[comfy-profiles] %s", t("restarting ComfyUI"))
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass
    if "__COMFY_CLI_SESSION__" in os.environ:
        Path(os.environ["__COMFY_CLI_SESSION__"] + ".reboot").touch()
        os._exit(0)
    argv = [a for a in sys.argv if a != "--windows-standalone-build"]
    if argv[0].endswith("__main__.py"):  # run as a module (python -m ...)
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
        return json_error(409, tr(request)("action running, restart refused"))
    # Let the response go out before replacing the process.
    asyncio.get_running_loop().call_later(0.5, restart)
    return web.json_response({"ok": True})
