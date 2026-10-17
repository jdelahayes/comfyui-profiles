// "Profiles" tab of the ComfyUI sidebar: see __init__.py for the routes it calls.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const API = "/comfy-profiles";
const EVENT = "comfy-profiles.log";
const MAX_LOG_LINES = 5000;
const LANG_HEADER = "Comfy-Profiles-Lang";

// Translations: messages are in English in the code and serve as keys; the server provides
// {English message: translation} for ComfyUI's language (see profiles_i18n.py).
let LANG = "en";
let MESSAGES = {};

function t(message, values = {}) {
  const text = MESSAGES[message] || message;
  return text.replace(/\{(\w+)\}/g, (all, key) => (key in values ? String(values[key]) : all));
}

// Language of the ComfyUI interface (Comfy.Locale setting), otherwise the browser's.
async function loadMessages() {
  const wanted = app.extensionManager?.setting?.get?.("Comfy.Locale") || navigator.language || "en";
  try {
    const resp = await api.fetchApi(`${API}/lang/${encodeURIComponent(wanted)}`);
    const data = await resp.json();
    LANG = data.lang;
    MESSAGES = data.messages || {};
  } catch (e) {
    console.warn("[comfy-profiles]", e);
  }
}

const STYLE = `
.cprof { display: flex; flex-direction: column; gap: 10px; padding: 10px; height: 100%;
  min-height: 0; overflow-y: auto; box-sizing: border-box; font-size: 13px;
  color: var(--fg-color); }
.cprof h3 { margin: 0; font-size: 15px; }
.cprof h4 { margin: 4px 0 0; font-size: 13px; border-bottom: 1px solid var(--border-color); }
.cprof .field { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; cursor: pointer; }
.cprof input.num { width: 64px; padding: 3px 5px; border-radius: 4px; border: 1px solid var(--border-color);
  background: var(--comfy-input-bg); color: var(--input-text); }
.cprof .muted { color: var(--descrip-text, #999); font-size: 12px; }
.cprof .warn { color: #e0a030; font-size: 12px; }
.cprof .error { color: #e05050; white-space: pre-wrap; font-size: 12px; }
.cprof .bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.cprof button { background: var(--comfy-input-bg); color: var(--input-text, var(--fg-color));
  border: 1px solid var(--border-color); border-radius: 4px; padding: 4px 10px; cursor: pointer;
  font-size: 12px; }
.cprof button:hover:not(:disabled) { filter: brightness(1.2); }
.cprof button:disabled { opacity: .5; cursor: default; }
.cprof button.icon { padding: 2px 5px; font-size: 11px; line-height: 1; }
.cprof .actions { display: flex; gap: 3px; }
.cprof button.primary { background: var(--p-primary-color, #2a6fd6); color: #fff; border-color: transparent; }
.cprof button.danger { background: #b83a3a; color: #fff; border-color: transparent; }
.cprof .filters { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; }
.cprof .filter { display: flex; align-items: center; gap: 4px; cursor: pointer; }
.cprof .search { width: 100%; box-sizing: border-box; padding: 4px 6px; border-radius: 4px;
  border: 1px solid var(--border-color); background: var(--comfy-input-bg); color: var(--input-text); }
.cprof .match { font-family: monospace; word-break: break-all; }
.cprof .list { display: flex; flex-direction: column; gap: 4px; }
.cprof .profile { border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 8px; }
.cprof .profile.selected { border-color: var(--p-primary-color, #2a6fd6); }
.cprof .profile.installed { background: rgba(58, 154, 90, .16); }
.cprof .profile.partial { background: rgba(224, 160, 48, .16); }
.cprof .profile.error { background: rgba(224, 80, 80, .16); }
.cprof .legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--descrip-text, #999); }
.cprof .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px;
  margin-right: 4px; vertical-align: -1px; border-radius: 2px; border: 1px solid var(--border-color); }
.cprof .legend .state { cursor: pointer; padding: 0 4px; border-radius: 4px; border: 1px solid transparent; }
.cprof .legend .state:hover { color: var(--input-text); }
.cprof .legend .chip.state { border-radius: 8px; border-color: #e0a030; }
.cprof .legend .chip.state.active { border-style: solid; border-color: var(--p-primary-color, #2a6fd6); }
.cprof .legend .state.active { color: var(--input-text); border-color: var(--p-primary-color, #2a6fd6); }
.cprof .legend .installed::before { background: rgba(58, 154, 90, .5); }
.cprof .legend .partial::before { background: rgba(224, 160, 48, .5); }
.cprof .head { display: flex; gap: 8px; align-items: center; }
.cprof .head label { flex: 1; min-width: 0; display: flex; gap: 6px; align-items: center; cursor: pointer;
  font-weight: 600; overflow-wrap: anywhere; }
.cprof .chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 3px 0 2px; }
.cprof .chip { font-size: 11px; padding: 0 6px; border-radius: 8px; white-space: nowrap;
  background: var(--comfy-input-bg); border: 1px solid var(--border-color); }
.cprof .chip.default { border-color: #3a9a5a; color: #3a9a5a; }
.cprof .chip.download { border-color: #3a7abf; color: #3a7abf; }
.cprof .chip.unmanaged { border-color: #e0a030; color: #e0a030; border-style: dashed; }
.cprof .legend .chip::before { display: none; }
.cprof .details { margin-top: 6px; display: flex; flex-direction: column; gap: 2px; }
.cprof .item { display: flex; gap: 6px; font-size: 12px; font-family: monospace; }
.cprof .details .group { margin-top: 6px; font-size: 12px; font-weight: 600;
  border-bottom: 1px solid var(--border-color); }
.cprof .details .group ~ .item { margin-left: 8px; }
.cprof .item .name { flex: 1; word-break: break-all; }
.cprof .item .size { white-space: nowrap; }
.cprof .item .link { flex: none; width: 16px; text-align: center; color: inherit; opacity: .7;
  text-decoration: none; }
.cprof .item a.link:hover { opacity: 1; color: var(--p-primary-color, #6cf); }
.cprof .ok { color: #3a9a5a; }
.cprof .todo { color: #e0a030; }
.cprof .log { background: var(--comfy-input-bg); border: 1px solid var(--border-color);
  border-radius: 4px; padding: 6px; font-family: monospace; font-size: 11px; white-space: pre-wrap;
  word-break: break-all; max-height: 320px; min-height: 80px; overflow-y: auto; }
.cprof .workflow { border: 1px solid var(--border-color); border-left: 3px solid #3a7abf;
  border-radius: 6px; padding: 6px 8px; display: flex; flex-direction: column; gap: 4px; }
.cprof .workflow.done { border-left-color: #3a9a5a; }
.cprof .need { display: flex; gap: 6px; align-items: center; font-size: 12px; }
.cprof .need .name { flex: 1; min-width: 0; font-family: monospace; word-break: break-all; cursor: pointer; }
.cprof .need .name:hover { text-decoration: underline; }
.cprof textarea { width: 100%; min-height: 400px; box-sizing: border-box; resize: vertical;
  font-family: monospace; font-size: 12px; background: var(--comfy-input-bg);
  color: var(--input-text, var(--fg-color)); border: 1px solid var(--border-color); border-radius: 4px; }
`;

function el(tag, attrs = {}, ...children) {
  const node = document.createElement(tag);
  for (const [key, value] of Object.entries(attrs)) {
    if (key === "class") node.className = value;
    else if (key.startsWith("on")) node.addEventListener(key.slice(2), value);
    else if (value !== false && value != null) node.setAttribute(key, value === true ? "" : value);
  }
  node.append(...children.flat(Infinity).filter((c) => c != null && c !== false));
  return node;
}

async function request(method, path, body) {
  const options = { method, headers: { [LANG_HEADER]: LANG } };
  if (body !== undefined) {
    options.headers["Content-Type"] = "application/json";
    options.body = JSON.stringify(body);
  }
  const resp = await api.fetchApi(`${API}${path}`, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

function toast(severity, summary, detail, life = 5000) {
  app.extensionManager?.toast?.add({ severity, summary, detail, life });
}

// --- Profiles declared by the open workflow -------------------------------------------------

// "Workflow profiles" node (profiles_node.py): profiles the workflow needs, and URL of the
// profiles file that defines them.
const WORKFLOW_NODE = "WorkflowProfiles";
const PROFILE_NAME = /^[\w.-]+$/;
// States where the profile has nothing to install for the workflow (see STATES).
const SATISFIED = new Set(["installed", "empty"]);

// [{name, source, valid}] of the "Workflow profiles" nodes of the open workflow, subgraphs
// included; for a profile declared several times, the first non-empty source.
function workflowNeeds() {
  const graph = app.rootGraph ?? app.graph;
  if (!graph) return [];
  const subgraphs = [...(graph.subgraphs?.values?.() ?? [])];
  const needs = new Map();
  for (const node of [graph, ...subgraphs].flatMap((g) => g.nodes ?? [])) {
    if (node.type !== WORKFLOW_NODE) continue;
    const value = (name) => String(node.widgets?.find((w) => w.name === name)?.value ?? "").trim();
    const source = value("source");
    for (const name of value("profiles").split(",").map((n) => n.trim()).filter(Boolean)) {
      if (!needs.get(name)) needs.set(name, source);
    }
  }
  return [...needs].map(([name, source]) => ({ name, source, valid: PROFILE_NAME.test(name) }));
}

// Declared profile: its `list --json` entry, or null if it is not in the profiles file.
function declared(profiles, need) {
  return need.valid && Object.hasOwn(profiles, need.name) ? profiles[need.name] : null;
}

// Last alert shown, so as not to repeat it at each reload of the same graph (undo / redo, back
// to a tab).
let lastAlert = "";

// When a workflow opens: alert if profiles it declares are missing.
async function checkWorkflow() {
  const needs = workflowNeeds();
  panel?.render();
  if (!needs.length) return;
  let profiles;
  try {
    profiles = panel?.data?.profiles ?? (await request("GET", "/profiles")).profiles;
  } catch (e) {
    console.warn("[comfy-profiles]", e);
    return;
  }
  const missing = needs.flatMap((need) => {
    const p = declared(profiles, need);
    if (p && SATISFIED.has(p.state)) return [];
    const state = !need.valid ? t("invalid name")
      : p ? t(STATES[p.state]?.label ?? STATES.missing.label) : t("not in the profiles file");
    return [`${need.name} (${state.toLowerCase()})`];
  });
  const key = missing.join(", ");
  if (key && key !== lastAlert) {
    toast("warn", t("Profiles"),
      t("This workflow needs profiles: {names}. See the Profiles panel.", { names: key }), 10000);
  }
  lastAlert = key;
}

class ProfilesPanel {
  constructor() {
    this.root = el("div", { class: "cprof" });
    this.data = null;          // result of `list --json`
    this.selected = new Set();
    this.expanded = new Map();  // profile -> state (`show --json`), or null while loading
    this.leavesOnly = loadSetting(LEAVES_KEY) === "1";  // only the profiles at the end of the tree
    this.namesOnly = loadSetting(NAMES_KEY) === "1";    // text filter on the profile names only
    this.grouped = loadSetting(GROUPED_KEY) === "1";    // profils finaux : aussi ceux d'un regroupement
    // Filter on the state (keys of STATE_FILTERS); empty: all profiles.
    this.states = new Set((loadSetting(STATES_KEY) || "").split(",").filter((k) => k in STATE_FILTERS));
    this.unmanagedOnly = loadSetting(UNMANAGED_KEY) === "1";  // profiles with unmanaged items
    // Text filter: a single field, kept from one render to the next (see render()).
    this.search = el("input", {
      type: "search", class: "search", placeholder: t("Filter: profile or item (model, custom node…)"),
      oninput: () => this.render(),
    });
    this.sync = { running: false };
    this.logLines = new Map();  // index -> element
    this.editing = null;        // { path, source, writable, text } in edit mode
    this.uninstall = null;      // { profiles, plan } en attente de confirmation
    this.settings = null;       // download settings (`settings`) in settings mode
    this.error = "";
    this.logBox = el("div", { class: "log" });
    api.addEventListener(EVENT, (e) => this.onLog(e.detail));
  }

  async load() {
    try {
      const [data, sync] = await Promise.all([request("GET", "/profiles"), request("GET", "/sync")]);
      this.data = data;
      this.error = "";
      this.setSync(sync);
      for (const name of this.expanded.keys()) this.expand(name, true);
    } catch (e) {
      this.error = t("Profiles unavailable: {error}", { error: e.message });
    }
    this.render();
  }

  setSync(sync) {
    this.sync = sync;
    if (sync.running) this.selected = new Set(sync.profiles);
    this.logBox.replaceChildren();
    this.logLines.clear();
    for (const [index, text] of sync.lines || []) this.setLine(index, text);
  }

  setLine(index, text) {
    let line = this.logLines.get(index);
    if (!line) {
      line = el("div");
      this.logLines.set(index, line);
      this.logBox.append(line);
      for (const old of this.logLines.keys()) {
        if (old > index - MAX_LOG_LINES) break;
        this.logLines.get(old).remove();
        this.logLines.delete(old);
      }
    }
    const atBottom = this.logBox.scrollHeight - this.logBox.scrollTop - this.logBox.clientHeight < 30;
    line.textContent = text;
    if (atBottom) this.logBox.scrollTop = this.logBox.scrollHeight;
  }

  onLog(detail) {
    if (!detail.done) {
      if (!this.sync.running) {
        // Sync started from another tab: catch up with it.
        this.sync = { running: true, profiles: [], lines: [] };
        this.render();
      }
      this.setLine(detail.index, detail.text);
      return;
    }
    const { action, dry_run: dryRun, force, returncode } = detail;
    this.sync = { ...this.sync, running: false, stopping: false, action, dry_run: dryRun, force, returncode };
    const what = dryRun && action === "sync" ? "Dry-run" : actionLabel(action, force);
    if (returncode === 0) toast("success", t("Profiles"), t("{action}: done.", { action: what }));
    else if (returncode === 130) toast("warn", t("Profiles"), t("{action}: stopped.", { action: what }));
    else toast("error", t("Profiles"), t("{action}: incomplete, see the logs.", { action: what }));
    // Models added or removed: node lists updated right away.
    if (!dryRun && action !== "sizes") app.refreshComboInNodes?.();
    // Profile states (and expanded details) up to date after the action.
    this.load();
  }

  async expand(name, refresh = false) {
    if (this.expanded.has(name) && !refresh) {
      this.expanded.delete(name);
      this.render();
      return;
    }
    this.expanded.set(name, null);
    this.render();
    try {
      this.expanded.set(name, await request("GET", `/status?profiles=${encodeURIComponent(name)}`));
    } catch (e) {
      this.expanded.set(name, { error: e.message });
    }
    if (this.expanded.has(name)) this.render();
  }

  // force: for "sizes", also queries again the files whose size is known; for "sync", also
  // updates what changed at the source.
  async startSync(dryRun, action = "sync", profiles = [...this.selected], withExtends = false, force = false) {
    try {
      this.setSync(await request("POST", "/sync",
        { action, profiles, dry_run: dryRun, with_extends: withExtends, force }));
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    this.render();
  }

  async stop() {
    if (!confirm(t("Stop the running action? The current step is cleanly abandoned; the next " +
                   "sync will resume it."))) return;
    try {
      const { running, stopping } = await request("POST", "/stop");
      this.sync = { ...this.sync, running, stopping };
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    this.render();
  }

  // withExtends: also uninstall the profiles they inherit from (otherwise only their own
  // items).
  async prepareUninstall(profiles = [...this.selected], withExtends = false) {
    try {
      const plan = await request("GET",
        `/uninstall-plan?profiles=${encodeURIComponent(profiles.join(","))}&with_extends=${withExtends ? 1 : 0}`);
      this.uninstall = { profiles, plan, withExtends };
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    this.render();
  }

  // Takes over what is already there for the profile: uninstalling can then remove it.
  async adopt(name, count) {
    if (!confirm(t("Take over {n} item(s) already present for {name} (including extends)?",
                   { n: count, name }) + "\n\n" +
                 t("Uninstalling can then remove them, including custom nodes installed with the " +
                   "Manager or models copied by hand."))) return;
    try {
      const { adopted } = await request("POST", "/adopt", { profiles: [name] });
      toast("success", t("Profiles"), t("{name}: {n} item(s) taken over.", { name, n: adopted.length }));
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    await this.load();
  }

  confirmUninstall() {
    const { profiles, withExtends } = this.uninstall;
    this.uninstall = null;
    this.startSync(false, "uninstall", profiles, withExtends);
  }

  async restart() {
    if (!confirm(t("Restart ComfyUI? Running generations will be interrupted."))) return;
    try {
      await request("POST", "/restart");
      toast("info", t("Profiles"), t("Restarting ComfyUI… the page reconnects by itself."));
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
  }

  async edit() {
    try {
      this.editing = await request("GET", "/config");
      this.editError = "";
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    this.render();
  }

  async save(text) {
    try {
      await request("PUT", "/config", { text });
      this.editing = null;
      toast("success", t("Profiles"), t("profiles.json saved."));
      await this.load();
    } catch (e) {
      this.editError = e.message;
      this.editing.text = text;
      this.render();
    }
  }

  // Replaces the profiles file with a file picked on this computer (same validation as
  // editing: nothing is replaced if the file is invalid).
  importFile() {
    const input = el("input", { type: "file", accept: ".json,application/json" });
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file || !confirm(t("Replace the profiles file with {file}?", { file: file.name }))) return;
      try {
        await request("PUT", "/config", { text: await file.text(), origin: `import ${file.name}` });
        toast("success", t("Profiles"), t("{file} imported.", { file: file.name }));
        await this.load();
      } catch (e) {
        toast("error", t("Profiles"), e.message);
      }
    });
    input.click();
  }

  async importUrl() {
    const url = prompt(t("URL of the profiles file (e.g. a raw GitHub or gist link):"));
    if (!url?.trim()) return;
    try {
      await request("POST", "/config/import-url", { url: url.trim() });
      toast("success", t("Profiles"), t("Profiles file imported."));
      await this.load();
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
  }

  async exportFile() {
    try {
      const { text } = await request("GET", "/config");
      const link = el("a", {
        href: URL.createObjectURL(new Blob([text], { type: "application/json" })),
        download: "profiles.json",
      });
      link.click();
      setTimeout(() => URL.revokeObjectURL(link.href), 1000);
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
  }

  async resetToSeed() {
    if (!confirm(t("Go back to the template? Your profiles file is kept as profiles.json.bak."))) return;
    try {
      const { backup } = await request("DELETE", "/config");
      toast("success", t("Profiles"), t("Template restored, old file: {path}", { path: backup }));
      await this.load();
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
  }

  async openSettings() {
    try {
      this.settings = await request("GET", "/settings");
      this.settingsError = "";
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    this.render();
  }

  // values: {setting: value} to save; those that don't change are not sent, to keep the
  // default value or the environment's.
  async saveSettings(values) {
    try {
      await request("PUT", "/settings", { values });
      this.settings = null;
      toast("success", t("Profiles"), t("Settings saved: they apply to the next sync."));
    } catch (e) {
      this.settingsError = e.message;
    }
    this.render();
  }

  async resetSettings() {
    if (!confirm(t("Go back to the default settings?"))) return;
    try {
      this.settings = await request("DELETE", "/settings");
      this.settingsError = "";
    } catch (e) {
      this.settingsError = e.message;
    }
    this.render();
  }

  async cleanPartials() {
    const { count, size } = this.settings.partials;
    if (!confirm(t("Delete {n} partial download(s) ({size})? They will start over.",
                   { n: count, size: humanSize(size) }))) return;
    try {
      this.settings = await request("POST", "/settings/clean-partials");
      const { removed } = this.settings;
      toast("success", t("Profiles"), t("{n} partial download(s) deleted, {size} freed.",
        { n: removed?.count ?? 0, size: humanSize(removed?.size ?? 0) }));
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    this.render();
  }

  // Checkbox of a filter, remembered in this browser.
  toggle(prop, key, label, title) {
    return el("label", { class: "muted filter", title },
      el("input", {
        type: "checkbox", checked: this[prop],
        onchange: (e) => {
          this[prop] = e.target.checked;
          saveSetting(key, this[prop] ? "1" : "0");
          this.render();
        },
      }),
      label);
  }

  render() {
    // Rendering rebuilds the whole panel: give the filter field its focus and cursor back.
    const focused = document.activeElement === this.search;
    const { selectionStart, selectionEnd } = this.search;
    this.root.replaceChildren(
      this.editing ? this.renderEditor() : this.settings ? this.renderSettings()
        : this.uninstall ? this.renderUninstall() : this.renderMain());
    if (focused && this.search.isConnected) {
      this.search.focus();
      this.search.setSelectionRange(selectionStart, selectionEnd);
    }
  }

  renderUninstall() {
    const { profiles, plan, withExtends } = this.uninstall;
    const item = (kind, name, extra) => el("div", { class: "item" },
      el("span", { class: "muted" }, kind), el("span", { class: "name" }, name),
      extra && el("span", { class: "muted" }, extra));
    return el("div", { style: "display:flex;flex-direction:column;gap:8px" },
      el("h3", {}, t("Uninstall: {names}", { names: profiles.join(", ") })),
      plan.extends.length > 0 && el("label", { class: "bar", style: "cursor:pointer" },
        el("input", { type: "checkbox", checked: withExtends,
                      onchange: (e) => this.prepareUninstall(profiles, e.target.checked) }),
        t("Include the inherited profiles ({names})", { names: plan.extends.join(", ") })),
      plan.extends.length > 0 && !withExtends && el("div", { class: "muted" },
        t("Only the items of these profiles themselves are removed; inherited profiles stay installed.")),
      plan.remove.length
        ? el("div", {}, t("{n} item(s) removed, {size} freed:",
          { n: plan.remove.length, size: humanSize(plan.freed) }))
        : el("div", { class: "muted" }, plan.extends.length && !withExtends
          ? t("Nothing of its own to remove: tick “Include the inherited profiles” for a profile that only groups others.")
          : t("Nothing to remove: everything is missing or still in use.")),
      el("div", { class: "details" }, plan.remove.map((r) => item(r.kind, r.name, humanSize(r.size)))),
      plan.kept.length > 0 && el("div", { class: "muted" },
        t("Kept, because used by {names}:", { names: plan.keep_profiles.join(", ") })),
      plan.kept.length > 0 && el("div", { class: "details" },
        plan.kept.map((k) => item(k.kind, k.name, k.by.join(", ")))),
      plan.startup.length > 0 && el("div", { class: "warn" },
        t("{names}: in COMFY_PROFILES, reinstalled at the next startup.", { names: plan.startup.join(", ") })),
      plan.unmanaged.length > 0 && el("div", { class: "muted" },
        t("Left in place, because not installed by the manager:")),
      plan.unmanaged.length > 0 && el("div", { class: "details" },
        plan.unmanaged.map((u) => item(u.kind, u.name))),
      plan.remove.some((r) => r.kind === "custom_node") && el("div", { class: "warn" },
        t("Custom nodes will be removed: restart ComfyUI afterwards to unload them.")),
      el("div", { class: "muted" }, t("The pip packages installed for these profiles stay in place.")),
      el("div", { class: "bar" },
        el("button", { class: "danger", disabled: !plan.remove.length, onclick: () => this.confirmUninstall() },
          t("Uninstall")),
        el("button", { onclick: () => { this.uninstall = null; this.render(); } }, t("Cancel"))),
    );
  }

  renderEditor() {
    const area = el("textarea", { spellcheck: "false" });
    area.value = this.editing.text;
    return el("div", { class: "cprof-editor", style: "display:flex;flex-direction:column;gap:8px" },
      el("h3", {}, t("Edit profiles")),
      el("div", { class: "muted" }, this.editing.path),
      this.editing.source === "seed" && el("div", { class: "warn" },
        t("This is the read-only template: saving creates your profiles file ({path}), used from " +
          "then on instead.", { path: this.editing.writable })),
      area,
      this.editError && el("div", { class: "error" }, this.editError),
      el("div", { class: "bar" },
        el("button", { class: "primary", onclick: () => this.save(area.value) }, t("Save")),
        el("button", { onclick: () => { this.editing = null; this.render(); } }, t("Cancel"))),
    );
  }

  // Download settings: saved value, otherwise the environment's, otherwise the default (see
  // DOWNLOAD_SETTINGS in comfy_profiles.py).
  renderSettings() {
    const s = this.settings;
    const locked = !!this.data?.readonly;
    // Where the value shown comes from, when it is not saved.
    const origin = (key) => key in s.saved ? null
      : el("span", { class: "muted" }, s.env[key] ? t("(from {var})", { var: s.env[key] }) : t("(default)"));
    const jobs = el("input", { type: "number", class: "num", min: 1, max: s.max_jobs, step: 1,
                               value: s.values.jobs, disabled: locked });
    const hfPerf = el("input", { type: "checkbox", checked: s.values.hf_high_performance, disabled: locked });
    const save = () => {
      const wanted = { jobs: Number(jobs.value), hf_high_performance: hfPerf.checked };
      const values = Object.fromEntries(Object.entries(wanted)
        .filter(([key, value]) => key in s.saved || value !== s.values[key]));
      if (Object.keys(values).length) this.saveSettings(values);
      else { this.settings = null; this.render(); }
    };
    const { count, size } = s.partials;
    return el("div", { style: "display:flex;flex-direction:column;gap:8px" },
      el("h3", {}, t("Settings")),
      el("div", { class: "muted" }, s.file),
      locked && el("div", { class: "warn" }, t("Read-only (COMFY_PROFILES_READONLY): settings cannot be changed.")),
      el("h4", {}, t("Downloads")),
      el("label", { class: "field" }, t("Files downloaded at a time"), jobs, origin("jobs")),
      el("div", { class: "muted" },
        t("Models and workflows, from 1 to {max}; custom nodes and pip packages go first, one by one.",
          { max: s.max_jobs })),
      el("label", { class: "field", style: "flex-wrap:nowrap" }, hfPerf,
        el("span", {}, t("Hugging Face: high performance mode (Xet)"), " ", origin("hf_high_performance"))),
      el("div", { class: "muted" },
        t("More connections and memory for each file (HF_XET_HIGH_PERFORMANCE).")),
      s.hf_xet
        ? el("div", { class: "muted" }, `huggingface_hub ${s.huggingface_hub ?? "?"} · hf_xet ${s.hf_xet}`)
        : el("div", { class: "warn" },
          t("hf_xet not installed: Hugging Face downloads without Xet, more slowly (pip install hf_xet).")),
      el("div", { class: "muted" },
        t("An interrupted CivitAI, GitHub, URL or Google Drive download resumes where it " +
          "stopped; Hugging Face starts over (huggingface_hub cannot resume).")),
      el("h4", {}, t("Partial downloads")),
      el("div", { class: "bar" },
        el("span", { class: "muted" }, count
          ? t("{n} file(s), {size}, resumed by the next sync", { n: count, size: humanSize(size) })
          : t("None")),
        count > 0 && el("button", {
          disabled: locked || this.sync.running, onclick: () => this.cleanPartials(),
          title: t("Deletes the .part files and the staging folder (not during an action)"),
        }, t("Delete"))),
      this.settingsError && el("div", { class: "error" }, this.settingsError),
      el("div", { class: "bar" },
        el("button", { class: "primary", disabled: locked, onclick: save }, t("Save")),
        el("button", { onclick: () => { this.settings = null; this.render(); } }, t("Cancel")),
        Object.keys(s.saved).length > 0 && el("button", { disabled: locked, onclick: () => this.resetSettings() },
          t("Defaults"))),
      el("div", { class: "muted" },
        t("Settings apply to the following syncs, from the panel as well as at container startup.")),
    );
  }

  renderMain() {
    const running = this.sync.running;
    const header = el("div", {},
      el("div", { class: "head" },
        el("h3", { style: "flex:1" }, t("Profiles")),
        iconButton("pi-cog", t("Settings"), false, () => this.openSettings())),
      this.data && el("div", { class: "muted", title: this.data.config },
        `${SOURCES[this.data.source] ? t(SOURCES[this.data.source]) : this.data.source} : ${this.data.config}`),
      this.data?.readonly && el("div", { class: "warn" },
        t("Read-only (COMFY_PROFILES_READONLY): only dry-run is possible.")),
      this.error && el("div", { class: "error" }, this.error));
    // Invalid profiles file: it can still be fixed, replaced, or reset to the template.
    if (!this.data) {
      return el("div", { style: "display:flex;flex-direction:column;gap:10px" }, header,
        el("div", { class: "bar" }, el("button", { onclick: () => this.load() }, t("Reload"))),
        this.configBar(running, null));
    }
    const locked = running || this.data.readonly;

    // Profiles at the end of the dependency tree: no other profile extends them. With
    // this.grouped, a profile extended only by grouping profiles (e.g. minimax-h3-all-*) also
    // counts as final. A selected profile stays shown, so as not to act on an invisible
    // selection.
    const parents = new Set(Object.values(this.data.profiles)
      .filter((p) => !(this.grouped && isGroup(p))).flatMap((p) => p.extends));
    const entries = Object.entries(this.data.profiles);
    // Text filter: profile name, otherwise names of its items (extends included).
    const query = this.search.value.trim().toLowerCase();
    const matches = new Map();  // profile -> matching items ([]: the name matches)
    for (const [name, p] of entries) {
      if (!query || name.toLowerCase().includes(query)) matches.set(name, []);
      else {
        const items = this.namesOnly ? [] : (p.items || []).filter((i) => i.toLowerCase().includes(query));
        if (items.length) matches.set(name, items);
      }
    }
    const states = new Set([...this.states].flatMap((k) => STATE_FILTERS[k]));
    const shown = entries.filter(([name, p]) => this.selected.has(name) ||
      (matches.has(name) && (!this.leavesOnly || !parents.has(name)) && (!states.size || states.has(p.state)) &&
      (!this.unmanagedOnly || p.unmanaged > 0)));
    const hidden = entries.length - shown.length;
    const profiles = shown.map(([name, p]) => {
      const detail = this.expanded.get(name);
      const state = STATES[p.state] || STATES.missing;
      const label = t(state.label);
      const size = profileSize(p);
      const todo = todoSize(p);
      return el("div", { class: `profile ${p.state}${this.selected.has(name) ? " selected" : ""}`, title: label },
        el("div", { class: "head" },
          el("label", {},
            el("input", {
              type: "checkbox", checked: this.selected.has(name), disabled: running,
              onchange: (e) => {
                e.target.checked ? this.selected.add(name) : this.selected.delete(name);
                this.render();
              },
            }),
            name),
          el("div", { class: "actions" },
            p.unmanaged > 0 && iconButton("pi-link",
              t("Take over the {n} item(s) of {name} already present…", { n: p.unmanaged, name }),
              locked, () => this.adopt(name, p.unmanaged)),
            iconButton("pi-download",
              state.install ? t("Install {name} (what is missing)", { name }) : `${name} : ${label.toLowerCase()}`,
              locked || !state.install, () => this.startSync(false, "sync", [name])),
            iconButton("pi-trash",
              state.uninstall ? t("Uninstall {name}…", { name }) : `${name} : ${label.toLowerCase()}`,
              locked || !state.uninstall, () => this.prepareUninstall([name])),
            iconButton(this.expanded.has(name) ? "pi-chevron-down" : "pi-chevron-right",
              this.expanded.has(name) ? t("Hide details") : t("Show what is installed"),
              false, () => this.expand(name)))),
        // Chips under the name: on the same line, they would squash it in the sidebar.
        (this.data.default.includes(name) || size || todo || p.unmanaged > 0) && el("div", { class: "chips" },
          this.data.default.includes(name) &&
            el("span", { class: "chip default", title: t("In COMFY_PROFILES: synced at every startup") },
              t("startup")),
          size && el("span", { class: "chip", title: t("Total size of the profile's files, extends included") }, size),
          todo && el("span", {
            class: "chip download",
            title: t("Missing files that installing the profile would add (custom nodes and pip packages not counted)"),
          }, todo),
          p.unmanaged > 0 && el("span", {
            class: "chip unmanaged",
            title: t("{n} item(s) present, including extends, but not installed by the manager " +
                     "(Manager, copied by hand...): uninstalling leaves them in place.", { n: p.unmanaged }),
          }, t("{n} not managed", { n: p.unmanaged }))),
        p.description && el("div", { class: "muted" }, p.description),
        p.extends.length > 0 && el("div", { class: "muted" }, `extends : ${p.extends.join(", ")}`),
        matches.get(name)?.length > 0 && el("div", { class: "muted match" },
          t("Contains: {items}", { items: matches.get(name).slice(0, 3).join(", ") +
            (matches.get(name).length > 3 ? ` (+${matches.get(name).length - 3})` : "") })),
        this.expanded.has(name) && this.renderDetail(detail));
    });

    const selection = [...this.selected];
    const what = actionLabel(this.sync.action, this.sync.force);
    const target = (this.sync.profiles || []).join(", ");
    const last = what.toLowerCase();
    const status = running
      ? (this.sync.stopping ? t("{action} stopping", { action: what }) : t("{action} running", { action: what })) +
        `${target ? ` : ${target}` : ""}${this.sync.dry_run ? " (dry-run)" : ""}`
      : this.sync.returncode == null ? ""
      : this.sync.returncode === 0 ? t("Last action ({action}): OK", { action: last })
      : this.sync.returncode === 130 ? t("Last action ({action}): stopped", { action: last })
      : t("Last action ({action}): failed (code {code})", { action: last, code: this.sync.returncode });

    return el("div", { style: "display:flex;flex-direction:column;gap:10px" },
      header,
      this.renderWorkflow(locked),
      el("div", { class: "bar" },
        el("button", { onclick: () => this.load() }, t("Reload")),
        el("button", {
          onclick: () => this.startSync(false, "sizes", []), disabled: locked,
          title: t("Queries Hugging Face / CivitAI / GitHub (without downloading anything) for " +
                   "files without a size, and saves the size of each profile in profiles.json"),
        }, t("Recalculate sizes")),
        el("button", {
          disabled: locked,
          onclick: () => confirm(t("Query the source of every file again, even those whose size " +
                                   "is already known? This may take a while.")) &&
            this.startSync(false, "sizes", [], false, true),
          title: t("Like “Recalculate sizes”, but also queries the files whose size is already " +
                   "known again (after a file changed at the source)"),
        }, t("Recalculate all")),
        el("button", { onclick: () => this.restart(), disabled: locked }, t("Restart ComfyUI"))),
      this.configBar(locked, this.data),
      el("div", { class: "legend" },
        // Each state is also a filter: a click adds or removes it (several possible).
        Object.entries(STATE_FILTERS).map(([key]) => el("span", {
          class: `state ${key}${this.states.has(key) ? " active" : ""}`,
          title: this.states.has(key) ? t("Click to stop filtering on this state")
            : t("Click to show only the profiles in this state"),
          onclick: () => {
            this.states.has(key) ? this.states.delete(key) : this.states.add(key);
            saveSetting(STATES_KEY, [...this.states].join(","));
            this.render();
          },
        }, t({ installed: "installed", partial: "partially installed", missing: "not installed" }[key]))),
        el("span", {
          class: `chip unmanaged state${this.unmanagedOnly ? " active" : ""}`,
          title: `${t(UNMANAGED_HINT)}\n` + (this.unmanagedOnly ? t("Click to stop filtering on this state")
            : t("Click to show only the profiles with unmanaged items")),
          onclick: () => {
            this.unmanagedOnly = !this.unmanagedOnly;
            saveSetting(UNMANAGED_KEY, this.unmanagedOnly ? "1" : "0");
            this.render();
          },
        }, t("not managed"))),
      this.search,
      el("div", { class: "filters" },
        this.toggle("namesOnly", NAMES_KEY, t("Search in profile names only"),
          t("The text filter does not search the profiles' items (models, custom nodes…)")),
        this.toggle("leavesOnly", LEAVES_KEY, t("Show final profiles only"),
          t("Hides profiles extended by others (e.g. the *-common profiles), installed along with them")),
        this.leavesOnly && this.toggle("grouped", GROUPED_KEY, t("Also show grouped profiles"),
          t("Also shows final profiles extended by a group profile (one with no items of its own " +
            "that only combines other profiles, e.g. minimax-h3-all-*)")),
        hidden > 0 && el("span", { class: "muted" }, t("({n} hidden)", { n: hidden }))),
      el("div", { class: "list" }, profiles),
      el("div", { class: "bar" },
        el("button", { class: "primary", disabled: locked || !selection.length,
                       onclick: () => this.startSync(false) },
          selection.length ? t("Sync ({n})", { n: selection.length }) : t("Sync")),
        el("button", { disabled: running || !selection.length, onclick: () => this.startSync(true) }, "Dry-run"),
        el("button", {
          disabled: locked || !selection.length, onclick: () => this.startSync(false, "sync", selection, false, true),
          title: t("Installs what is missing and updates what the manager installed or took " +
                   "over, if it changed at the source (custom nodes, models, workflows, pip " +
                   "packages)"),
        }, selection.length ? t("Update ({n})", { n: selection.length }) : t("Update")),
        el("button", { disabled: locked || !selection.length, onclick: () => this.prepareUninstall() },
          t("Uninstall…")),
        running && el("button", { class: "danger", disabled: this.sync.stopping, onclick: () => this.stop() },
          this.sync.stopping ? t("Stopping…") : t("Stop"))),
      el("div", { class: "muted" },
        t("New models: visible right away. New custom nodes: restart ComfyUI.")),
      status && el("div", { class: this.sync.returncode ? "error" : "muted" }, status),
      this.logBox,
    );
  }

  // Profiles declared by the open workflow ("Workflow profiles" node): state, install, and
  // adding those missing from the profiles file from the declared source.
  renderWorkflow(locked) {
    const needs = workflowNeeds();
    if (!needs.length) return null;
    const profiles = this.data.profiles;
    const toInstall = needs.filter((n) => {
      const p = declared(profiles, n);
      return p && !SATISFIED.has(p.state) && STATES[p.state]?.install;
    }).map((n) => n.name);
    const done = needs.every((n) => SATISFIED.has(declared(profiles, n)?.state));
    const rows = needs.map((need) => {
      const p = declared(profiles, need);
      const state = p && (STATES[p.state] || STATES.missing);
      const status = !need.valid ? el("span", { class: "error" }, t("invalid name"))
        : !p ? el("span", { class: "warn" }, t("not in the profiles file"))
        : el("span", { class: SATISFIED.has(p.state) ? "ok" : "todo" }, t(state.label));
      return el("div", { class: "need" },
        el("span", { class: SATISFIED.has(p?.state) ? "ok" : "todo" }, SATISFIED.has(p?.state) ? "✓" : "✗"),
        el("span", {
          class: "name", title: t("Show this profile in the list"),
          onclick: () => { this.search.value = need.name; this.render(); },
        }, need.name),
        status,
        el("div", { class: "actions" },
          p && state.install && !SATISFIED.has(p.state) && iconButton("pi-download",
            t("Install {name} (what is missing)", { name: need.name }), locked,
            () => this.startSync(false, "sync", [need.name])),
          !p && need.valid && need.source && iconButton("pi-plus",
            t("Add {name} from {url}", { name: need.name, url: need.source }), locked,
            () => this.addFromSource(need.source, [need.name])),
          !p && need.valid && !need.source && el("span", {
            class: "muted", title: t("The node gives no source: import the profiles file that defines it."),
          }, t("no source"))));
    });
    return el("div", { class: `workflow${done ? " done" : ""}` },
      el("div", { class: "bar" },
        el("strong", {}, t("This workflow")),
        el("span", { class: "muted" }, t("profiles declared by its “Workflow profiles” node"))),
      rows,
      done ? el("div", { class: "ok" }, t("All the profiles of this workflow are installed."))
        : toInstall.length > 1 && el("div", { class: "bar" },
          el("button", { class: "primary", disabled: locked, onclick: () => this.startSync(false, "sync", toInstall) },
            t("Install the workflow's profiles ({n})", { n: toInstall.length }))));
  }

  // Adds to the profiles file some profiles (and those they inherit from) taken from the file
  // published at `url`, without replacing those already there.
  async addFromSource(url, names) {
    if (!confirm(t("Add {names} (and the profiles they extend) to your profiles file, from " +
                   "{url}? Profiles already there are not changed.",
                   { names: names.join(", "), url }))) return;
    try {
      const { added, conflicts } = await request("POST", "/config/add-from-url", { url, profiles: names });
      toast("success", t("Profiles"), added.length ? t("Profiles added: {names}", { names: added.join(", ") })
        : t("Nothing to add: these profiles are already in your file."));
      if (conflicts.length) {
        toast("warn", t("Profiles"), t("Already in your file with different content, kept as they are: {names}",
          { names: conflicts.join(", ") }), 10000);
      }
    } catch (e) {
      toast("error", t("Profiles"), e.message);
    }
    await this.load();
  }

  // `data`: result of `list --json`, or null if the profiles file is unreadable.
  configBar(locked, data) {
    return el("div", { class: "bar" },
      el("span", { class: "muted" }, "profiles.json :"),
      el("button", { onclick: () => this.edit(), disabled: locked }, t("Edit")),
      el("button", { onclick: () => this.importFile(), disabled: locked,
                     title: t("Replaces the profiles file with a file from your computer") }, t("Import…")),
      el("button", { onclick: () => this.importUrl(), disabled: locked,
                     title: t("Replaces the profiles file with the one at a URL") }, t("From a URL…")),
      el("button", { onclick: () => this.exportFile() }, t("Export")),
      (!data || data.source === "user") && el("button", {
        onclick: () => this.resetToSeed(), disabled: locked,
        title: data ? t("Puts the template back in use ({path})", { path: data.seed }) : t("Puts the template back in use"),
      }, t("Back to template")));
  }

  renderDetail(detail) {
    if (detail === null || detail === undefined) return el("div", { class: "details muted" }, t("Loading…"));
    if (detail.error) return el("div", { class: "details error" }, detail.error);
    if (!detail.length) return el("div", { class: "details muted" }, t("(empty profile)"));
    const missing = detail.filter((i) => i.missing).length;
    // Items grouped by the profile declaring them (the profile itself, then those it inherits
    // from): `show --json` already returns them in this order.
    const groups = [];
    for (const item of detail) {
      if (groups.at(-1)?.profile !== item.profile) {
        groups.push({ profile: item.profile, inherited: item.inherited, items: [] });
      }
      groups.at(-1).items.push(item);
    }
    const titled = groups.length > 1 || groups[0]?.inherited;
    return el("div", { class: "details" },
      el("div", { class: missing ? "todo" : "ok" },
        missing ? t("{n} of {total} item(s) to install", { n: missing, total: detail.length })
          : t("Everything is installed")),
      groups.map((group) => [
        titled && el("div", { class: "group" },
          group.inherited ? t("Inherited from {name}", { name: group.profile }) : t("Profile's own"),
          el("span", { class: "muted" }, ` · ${group.items.filter((i) => !i.missing).length}/${group.items.length}`)),
        group.items.map((item) => this.renderItem(item)),
      ]));
  }

  renderItem(item) {
    return el("div", { class: "item" },
      el("span", { class: item.missing ? "todo" : "ok" }, item.missing ? "✗" : "✓"),
      el("span", { class: "muted" }, item.kind),
      el("span", { class: "name" }, item.name),
      FILE_KINDS.has(item.kind) && el("span", {
        class: "size muted",
        title: item.size == null ? t("Unknown size: “Recalculate sizes” queries it at the source")
          : t("{n} bytes", { n: item.size }),
      }, item.size == null ? "?" : humanSize(item.size)),
      item.unmanaged && el("span", { class: "chip unmanaged", title: t(UNMANAGED_HINT) }, t("not managed")),
      this.renderLink(item.link));
  }

  renderLink(link) {
    if (!/^https?:\/\//.test(link?.url || "")) return el("span", { class: "link" });
    const site = LINK_SITES[link.site] || LINK_SITES.url;
    return el("a", {
      class: "link", href: link.url, target: "_blank", rel: "noopener noreferrer",
      title: `${t(site.label)} : ${link.url}`,
    }, site.text ?? el("i", { class: site.icon }));
  }
}

// Link to the source of an item: PrimeIcons icon, or text when there is none.
const LINK_SITES = {
  hf: { label: "Hugging Face", text: "🤗" },
  github: { label: "GitHub", icon: "pi pi-github" },
  civitai: { label: "CivitAI", text: "C" },
  gdrive: { label: "Google Drive", icon: "pi pi-google" },
  pypi: { label: "PyPI", icon: "pi pi-box" },
  git: { label: "Git repository", icon: "pi pi-code" },  // translated when shown
  url: { label: "Source", icon: "pi pi-external-link" },
};

// Only files have a declared size (not custom nodes nor pip packages).
const FILE_KINDS = new Set(["model", "workflow"]);

const UNMANAGED_HINT = "Present, but not installed by the manager: uninstalling leaves it in place";

// Same format as human_size() on the Python side: "20.9 GB", "20,9 Go".
function humanSize(size) {
  for (const [unit, factor] of [["TB", 1e12], ["GB", 1e9], ["MB", 1e6], ["KB", 1e3]]) {
    if (size >= factor) return `${(size / factor).toFixed(1).replace(".", t("."))} ${t(unit)}`;
  }
  return `${size} ${t("B")}`;
}

// Size of a profile (`list --json`): total of its files, in the panel's language; failing that,
// the text written in profiles.json by "Recalculate sizes".
function profileSize(p) {
  if (!p.total && !p.unknown) return p.size || "";
  const total = humanSize(p.total || 0);
  return p.unknown ? `${total} ${t("+ {n} file(s) of unknown size", { n: p.unknown })}` : total;
}

// Size of the files installing the profile would add; empty if nothing is missing.
function todoSize(p) {
  if (!p.todo && !p.todo_unknown) return "";
  const size = t("{size} to download", { size: humanSize(p.todo || 0) });
  return p.todo_unknown ? `${size} ${t("+ {n} file(s) of unknown size", { n: p.todo_unknown })}` : size;
}

// Panel settings specific to this browser; storage may be unavailable.
const LEAVES_KEY = "comfy-profiles.leavesOnly";
const NAMES_KEY = "comfy-profiles.namesOnly";
const GROUPED_KEY = "comfy-profiles.grouped";
const STATES_KEY = "comfy-profiles.states";
const UNMANAGED_KEY = "comfy-profiles.unmanagedOnly";

// State filters of the legend -> profile states (`list --json`) they show.
const STATE_FILTERS = {
  installed: ["installed"],
  partial: ["partial"],
  missing: ["missing", "empty"],
};

// Grouping profile: no items of its own, it only gathers other profiles.
function isGroup(p) {
  return p.extends.length > 1 && Object.values(p.counts).every((n) => n === 0);
}

function loadSetting(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function saveSetting(key, value) {
  try { localStorage.setItem(key, value); } catch { /* setting simply not remembered */ }
}

// force ("sync" action): update of what changed at the source (sync --update).
function actionLabel(action, force = false) {
  if (action === "sync" && force) return t("Update job");
  return t({ uninstall: "Uninstall job", sizes: "Size calculation" }[action] || "Sync job");
}

// Install state of a profile (`list --json`): label, and allowed actions.
const STATES = {
  installed: { label: "Installed", install: false, uninstall: true },
  partial: { label: "Partially installed", install: true, uninstall: true },
  missing: { label: "Not installed", install: true, uninstall: false },
  empty: { label: "No file to install (pip, or custom nodes already present outside the manager)", install: true, uninstall: false },
  error: { label: "Invalid config", install: false, uninstall: false },
};

// Origin of the active profiles file (`list --json`).
const SOURCES = {
  option: "File (--config)",
  env: "File (COMFY_PROFILES_CONFIG)",
  user: "Your file",
  seed: "Template (read-only)",
};

// Small icon-only button (PrimeIcons, provided by the ComfyUI frontend); the action is shown on
// hover.
function iconButton(icon, hint, disabled, onclick) {
  return el("button", { class: "icon", title: hint, "aria-label": hint, disabled, onclick },
    el("i", { class: `pi ${icon}` }));
}

let panel = null;
// Translations: loaded at init, because the last workflow is reopened before setup.
let messagesLoaded = null;

app.registerExtension({
  name: "comfyui-profiles.panel",
  init() {
    messagesLoaded = loadMessages();
  },
  async afterConfigureGraph() {
    await messagesLoaded;
    await checkWorkflow();
  },
  async setup() {
    if (!app.extensionManager?.registerSidebarTab) {
      console.warn("[comfy-profiles] registerSidebarTab not available in this frontend");
      return;
    }
    await messagesLoaded;
    document.head.append(el("style", {}, STYLE));
    app.extensionManager.registerSidebarTab({
      id: "comfy-profiles",
      icon: "pi pi-box",
      title: t("Profiles"),
      tooltip: t("Usage profiles (models, custom nodes)"),
      type: "custom",
      render: (container) => {
        if (!panel) {
          panel = new ProfilesPanel();
          panel.load();
        }
        // The open workflow may have changed since the last display.
        panel.render();
        container.replaceChildren(panel.root);
      },
    });
  },
});
