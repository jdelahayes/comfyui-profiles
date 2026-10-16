// Onglet « Profils » de la barre latérale ComfyUI : voir __init__.py pour les routes appelées.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const API = "/comfy-profiles";
const EVENT = "comfy-profiles.log";
const MAX_LOG_LINES = 5000;
const LANG_HEADER = "Comfy-Profiles-Lang";

// Traductions : les messages sont en français dans le code et servent de clés ; le serveur
// fournit {message français: traduction} pour la langue de ComfyUI (voir profiles_i18n.py).
let LANG = "fr";
let MESSAGES = {};

function t(message, values = {}) {
  const text = MESSAGES[message] || message;
  return text.replace(/\{(\w+)\}/g, (all, key) => (key in values ? String(values[key]) : all));
}

// Langue de l'interface de ComfyUI (réglage Comfy.Locale), sinon celle du navigateur.
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

// --- Profils déclarés par le workflow ouvert ------------------------------------------------

// Node « Workflow profiles » (profiles_node.py) : profils dont le workflow a besoin, et URL du
// fichier de profils qui les définit.
const WORKFLOW_NODE = "WorkflowProfiles";
const PROFILE_NAME = /^[\w.-]+$/;
// États où le profil n'a rien à installer pour le workflow (voir STATES).
const SATISFIED = new Set(["installed", "empty"]);

// [{name, source, valid}] des nodes « Workflow profiles » du workflow ouvert, sous-graphes
// compris ; pour un profil déclaré plusieurs fois, la première source non vide.
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

// Profil déclaré : sa ligne de `list --json`, ou null s'il n'est pas dans le fichier de profils.
function declared(profiles, need) {
  return need.valid && Object.hasOwn(profiles, need.name) ? profiles[need.name] : null;
}

// Dernière alerte affichée, pour ne pas la répéter à chaque rechargement du même graphe
// (annuler / rétablir, retour sur un onglet).
let lastAlert = "";

// À l'ouverture d'un workflow : alerte si des profils qu'il déclare manquent.
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
    const state = !need.valid ? t("nom invalide")
      : p ? t(STATES[p.state]?.label ?? STATES.missing.label) : t("absent du fichier de profils");
    return [`${need.name} (${state.toLowerCase()})`];
  });
  const key = missing.join(", ");
  if (key && key !== lastAlert) {
    toast("warn", t("Profils"),
      t("Ce workflow a besoin de profils : {names}. Voir le panneau Profils.", { names: key }), 10000);
  }
  lastAlert = key;
}

class ProfilesPanel {
  constructor() {
    this.root = el("div", { class: "cprof" });
    this.data = null;          // résultat de `list --json`
    this.selected = new Set();
    this.expanded = new Map();  // profil -> état (`show --json`), ou null pendant le chargement
    this.leavesOnly = loadSetting(LEAVES_KEY) === "1";  // seulement les profils au bout de l'arbre
    this.namesOnly = loadSetting(NAMES_KEY) === "1";    // filtre texte sur le nom des profils seul
    this.grouped = loadSetting(GROUPED_KEY) === "1";    // profils finaux : aussi ceux d'un regroupement
    // Filtre sur l'état (clés de STATE_FILTERS) ; vide : tous les profils.
    this.states = new Set((loadSetting(STATES_KEY) || "").split(",").filter((k) => k in STATE_FILTERS));
    this.unmanagedOnly = loadSetting(UNMANAGED_KEY) === "1";  // profils avec des éléments non pris en charge
    // Filtre texte : un seul champ, gardé d'un rendu à l'autre (voir render()).
    this.search = el("input", {
      type: "search", class: "search", placeholder: t("Filtrer : profil ou élément (modèle, custom node…)"),
      oninput: () => this.render(),
    });
    this.sync = { running: false };
    this.logLines = new Map();  // index -> élément
    this.editing = null;        // { path, source, writable, text } en mode édition
    this.uninstall = null;      // { profiles, plan } en attente de confirmation
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
      this.error = t("Profils indisponibles : {error}", { error: e.message });
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
        // Synchronisation lancée depuis un autre onglet : on la rattrape.
        this.sync = { running: true, profiles: [], lines: [] };
        this.render();
      }
      this.setLine(detail.index, detail.text);
      return;
    }
    const { action, dry_run: dryRun, force, returncode } = detail;
    this.sync = { ...this.sync, running: false, stopping: false, action, dry_run: dryRun, force, returncode };
    const what = dryRun && action === "sync" ? "Dry-run" : actionLabel(action, force);
    if (returncode === 0) toast("success", t("Profils"), t("{action} : terminé.", { action: what }));
    else if (returncode === 130) toast("warn", t("Profils"), t("{action} : arrêté.", { action: what }));
    else toast("error", t("Profils"), t("{action} : incomplet, voir les logs.", { action: what }));
    // Modèles ajoutés ou supprimés : listes des nodes mises à jour tout de suite.
    if (!dryRun && action !== "sizes") app.refreshComboInNodes?.();
    // États des profils (et détails dépliés) à jour après l'action.
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

  // force : pour « sizes », réinterroge aussi les fichiers dont la taille est connue ; pour
  // « sync », met aussi à jour ce qui a changé à la source.
  async startSync(dryRun, action = "sync", profiles = [...this.selected], withExtends = false, force = false) {
    try {
      this.setSync(await request("POST", "/sync",
        { action, profiles, dry_run: dryRun, with_extends: withExtends, force }));
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
    this.render();
  }

  async stop() {
    if (!confirm(t("Arrêter l'action en cours ? L'étape en cours est abandonnée proprement, " +
                   "une prochaine synchronisation la reprendra."))) return;
    try {
      const { running, stopping } = await request("POST", "/stop");
      this.sync = { ...this.sync, running, stopping };
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
    this.render();
  }

  // withExtends : désinstaller aussi les profils dont ils héritent (sinon seulement leurs
  // éléments propres).
  async prepareUninstall(profiles = [...this.selected], withExtends = false) {
    try {
      const plan = await request("GET",
        `/uninstall-plan?profiles=${encodeURIComponent(profiles.join(","))}&with_extends=${withExtends ? 1 : 0}`);
      this.uninstall = { profiles, plan, withExtends };
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
    this.render();
  }

  // Prend en charge ce qui est déjà présent pour le profil : la désinstallation pourra le
  // supprimer.
  async adopt(name, count) {
    if (!confirm(t("Prendre en charge {n} élément(s) déjà présent(s) pour {name} (extends compris) ?",
                   { n: count, name }) + "\n\n" +
                 t("La désinstallation pourra ensuite les supprimer, y compris des custom nodes " +
                   "installés avec le Manager ou des modèles copiés à la main."))) return;
    try {
      const { adopted } = await request("POST", "/adopt", { profiles: [name] });
      toast("success", t("Profils"), t("{name} : {n} élément(s) pris en charge.", { name, n: adopted.length }));
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
    await this.load();
  }

  confirmUninstall() {
    const { profiles, withExtends } = this.uninstall;
    this.uninstall = null;
    this.startSync(false, "uninstall", profiles, withExtends);
  }

  async restart() {
    if (!confirm(t("Redémarrer ComfyUI ? Les générations en cours seront interrompues."))) return;
    try {
      await request("POST", "/restart");
      toast("info", t("Profils"), t("Redémarrage de ComfyUI… la page se reconnecte toute seule."));
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
  }

  async edit() {
    try {
      this.editing = await request("GET", "/config");
      this.editError = "";
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
    this.render();
  }

  async save(text) {
    try {
      await request("PUT", "/config", { text });
      this.editing = null;
      toast("success", t("Profils"), t("profiles.json enregistré."));
      await this.load();
    } catch (e) {
      this.editError = e.message;
      this.editing.text = text;
      this.render();
    }
  }

  // Remplace le fichier de profils par un fichier choisi sur le poste (même validation que
  // l'édition : rien n'est remplacé si le fichier est invalide).
  importFile() {
    const input = el("input", { type: "file", accept: ".json,application/json" });
    input.addEventListener("change", async () => {
      const file = input.files[0];
      if (!file || !confirm(t("Remplacer le fichier de profils par {file} ?", { file: file.name }))) return;
      try {
        await request("PUT", "/config", { text: await file.text(), origin: `import ${file.name}` });
        toast("success", t("Profils"), t("{file} importé.", { file: file.name }));
        await this.load();
      } catch (e) {
        toast("error", t("Profils"), e.message);
      }
    });
    input.click();
  }

  async importUrl() {
    const url = prompt(t("URL du fichier de profils (ex. lien raw GitHub ou gist) :"));
    if (!url?.trim()) return;
    try {
      await request("POST", "/config/import-url", { url: url.trim() });
      toast("success", t("Profils"), t("Fichier de profils importé."));
      await this.load();
    } catch (e) {
      toast("error", t("Profils"), e.message);
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
      toast("error", t("Profils"), e.message);
    }
  }

  async resetToSeed() {
    if (!confirm(t("Revenir au modèle ? Ton fichier de profils est gardé en profiles.json.bak."))) return;
    try {
      const { backup } = await request("DELETE", "/config");
      toast("success", t("Profils"), t("Modèle rétabli, ancien fichier : {path}", { path: backup }));
      await this.load();
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
  }

  // Case à cocher d'un filtre, mémorisée dans ce navigateur.
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
    // Le rendu reconstruit tout le panneau : on rend au champ de filtre le focus et le curseur.
    const focused = document.activeElement === this.search;
    const { selectionStart, selectionEnd } = this.search;
    this.root.replaceChildren(
      this.editing ? this.renderEditor() : this.uninstall ? this.renderUninstall() : this.renderMain());
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
      el("h3", {}, t("Désinstaller : {names}", { names: profiles.join(", ") })),
      plan.extends.length > 0 && el("label", { class: "bar", style: "cursor:pointer" },
        el("input", { type: "checkbox", checked: withExtends,
                      onchange: (e) => this.prepareUninstall(profiles, e.target.checked) }),
        t("Inclure les profils hérités ({names})", { names: plan.extends.join(", ") })),
      plan.extends.length > 0 && !withExtends && el("div", { class: "muted" },
        t("Seuls les éléments propres à ce(s) profil(s) partent ; les profils hérités restent installés.")),
      plan.remove.length
        ? el("div", {}, t("{n} élément(s) supprimé(s), {size} libérés :",
          { n: plan.remove.length, size: humanSize(plan.freed) }))
        : el("div", { class: "muted" }, plan.extends.length && !withExtends
          ? t("Rien à supprimer en propre : coche « Inclure les profils hérités » pour un profil qui ne fait que les regrouper.")
          : t("Rien à supprimer : tout est absent ou encore utilisé.")),
      el("div", { class: "details" }, plan.remove.map((r) => item(r.kind, r.name, humanSize(r.size)))),
      plan.kept.length > 0 && el("div", { class: "muted" },
        t("Conservés, car utilisés par {names} :", { names: plan.keep_profiles.join(", ") })),
      plan.kept.length > 0 && el("div", { class: "details" },
        plan.kept.map((k) => item(k.kind, k.name, k.by.join(", ")))),
      plan.startup.length > 0 && el("div", { class: "warn" },
        t("{names} : dans COMFY_PROFILES, réinstallé(s) au prochain démarrage.", { names: plan.startup.join(", ") })),
      plan.unmanaged.length > 0 && el("div", { class: "muted" },
        t("Laissés en place, car pas installés par le gestionnaire :")),
      plan.unmanaged.length > 0 && el("div", { class: "details" },
        plan.unmanaged.map((u) => item(u.kind, u.name))),
      plan.remove.some((r) => r.kind === "custom_node") && el("div", { class: "warn" },
        t("Des custom nodes seront supprimés : redémarre ComfyUI ensuite pour les décharger.")),
      el("div", { class: "muted" }, t("Les paquets pip installés pour ces profils restent en place.")),
      el("div", { class: "bar" },
        el("button", { class: "danger", disabled: !plan.remove.length, onclick: () => this.confirmUninstall() },
          t("Désinstaller")),
        el("button", { onclick: () => { this.uninstall = null; this.render(); } }, t("Annuler"))),
    );
  }

  renderEditor() {
    const area = el("textarea", { spellcheck: "false" });
    area.value = this.editing.text;
    return el("div", { class: "cprof-editor", style: "display:flex;flex-direction:column;gap:8px" },
      el("h3", {}, t("Éditer les profils")),
      el("div", { class: "muted" }, this.editing.path),
      this.editing.source === "seed" && el("div", { class: "warn" },
        t("C'est le modèle, en lecture seule : l'enregistrement crée ton fichier de profils " +
          "({path}), utilisé ensuite à sa place.", { path: this.editing.writable })),
      area,
      this.editError && el("div", { class: "error" }, this.editError),
      el("div", { class: "bar" },
        el("button", { class: "primary", onclick: () => this.save(area.value) }, t("Enregistrer")),
        el("button", { onclick: () => { this.editing = null; this.render(); } }, t("Annuler"))),
    );
  }

  renderMain() {
    const running = this.sync.running;
    const header = el("div", {},
      el("h3", {}, t("Profils")),
      this.data && el("div", { class: "muted", title: this.data.config },
        `${SOURCES[this.data.source] ? t(SOURCES[this.data.source]) : this.data.source} : ${this.data.config}`),
      this.data?.readonly && el("div", { class: "warn" },
        t("Lecture seule (COMFY_PROFILES_READONLY) : seul le dry-run est possible.")),
      this.error && el("div", { class: "error" }, this.error));
    // Fichier de profils invalide : on peut encore le corriger, le remplacer ou revenir au modèle.
    if (!this.data) {
      return el("div", { style: "display:flex;flex-direction:column;gap:10px" }, header,
        el("div", { class: "bar" }, el("button", { onclick: () => this.load() }, t("Recharger"))),
        this.configBar(running, null));
    }
    const locked = running || this.data.readonly;

    // Profils au bout de l'arbre des dépendances : aucun autre profil ne les étend. Avec
    // this.grouped, un profil étendu seulement par des profils de regroupement (ex.
    // minimax-h3-all-*) compte aussi comme final. Un profil sélectionné reste affiché, pour ne
    // pas agir sur une sélection invisible.
    const parents = new Set(Object.values(this.data.profiles)
      .filter((p) => !(this.grouped && isGroup(p))).flatMap((p) => p.extends));
    const entries = Object.entries(this.data.profiles);
    // Filtre texte : nom du profil, sinon noms de ses éléments (extends compris).
    const query = this.search.value.trim().toLowerCase();
    const matches = new Map();  // profil -> éléments qui correspondent ([] : le nom correspond)
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
              t("Prendre en charge les {n} élément(s) déjà présent(s) de {name}…", { n: p.unmanaged, name }),
              locked, () => this.adopt(name, p.unmanaged)),
            iconButton("pi-download",
              state.install ? t("Installer {name} (ce qui manque)", { name }) : `${name} : ${label.toLowerCase()}`,
              locked || !state.install, () => this.startSync(false, "sync", [name])),
            iconButton("pi-trash",
              state.uninstall ? t("Désinstaller {name}…", { name }) : `${name} : ${label.toLowerCase()}`,
              locked || !state.uninstall, () => this.prepareUninstall([name])),
            iconButton(this.expanded.has(name) ? "pi-chevron-down" : "pi-chevron-right",
              this.expanded.has(name) ? t("Masquer le détail") : t("Voir ce qui est installé"),
              false, () => this.expand(name)))),
        // Pastilles sous le nom : sur la même ligne, elles l'écraseraient dans la barre latérale.
        (this.data.default.includes(name) || size || todo || p.unmanaged > 0) && el("div", { class: "chips" },
          this.data.default.includes(name) &&
            el("span", { class: "chip default", title: t("Dans COMFY_PROFILES : synchronisé à chaque démarrage") },
              t("démarrage")),
          size && el("span", { class: "chip", title: t("Taille totale des fichiers du profil, extends compris") }, size),
          todo && el("span", {
            class: "chip download",
            title: t("Fichiers absents, que l'installation du profil ajouterait (custom nodes et paquets pip non comptés)"),
          }, todo),
          p.unmanaged > 0 && el("span", {
            class: "chip unmanaged",
            title: t("{n} élément(s) présent(s), extends compris, mais pas installé(s) par le gestionnaire " +
                     "(Manager, copie à la main...) : la désinstallation les laisse en place.", { n: p.unmanaged }),
          }, t("{n} non pris en charge", { n: p.unmanaged }))),
        p.description && el("div", { class: "muted" }, p.description),
        p.extends.length > 0 && el("div", { class: "muted" }, `extends : ${p.extends.join(", ")}`),
        matches.get(name)?.length > 0 && el("div", { class: "muted match" },
          t("Contient : {items}", { items: matches.get(name).slice(0, 3).join(", ") +
            (matches.get(name).length > 3 ? ` (+${matches.get(name).length - 3})` : "") })),
        this.expanded.has(name) && this.renderDetail(detail));
    });

    const selection = [...this.selected];
    const what = actionLabel(this.sync.action, this.sync.force);
    const target = (this.sync.profiles || []).join(", ");
    const last = what.toLowerCase();
    const status = running
      ? (this.sync.stopping ? t("{action} en cours d'arrêt", { action: what }) : t("{action} en cours", { action: what })) +
        `${target ? ` : ${target}` : ""}${this.sync.dry_run ? " (dry-run)" : ""}`
      : this.sync.returncode == null ? ""
      : this.sync.returncode === 0 ? t("Dernière action ({action}) : OK", { action: last })
      : this.sync.returncode === 130 ? t("Dernière action ({action}) : arrêtée", { action: last })
      : t("Dernière action ({action}) : échec (code {code})", { action: last, code: this.sync.returncode });

    return el("div", { style: "display:flex;flex-direction:column;gap:10px" },
      header,
      this.renderWorkflow(locked),
      el("div", { class: "bar" },
        el("button", { onclick: () => this.load() }, t("Recharger")),
        el("button", {
          onclick: () => this.startSync(false, "sizes", []), disabled: locked,
          title: t("Interroge Hugging Face / CivitAI / GitHub (sans rien télécharger) pour les " +
                   "fichiers sans taille, et enregistre la taille de chaque profil dans profiles.json"),
        }, t("Recalculer les tailles")),
        el("button", {
          disabled: locked,
          onclick: () => confirm(t("Réinterroger la source de tous les fichiers, même ceux dont la taille " +
                                   "est déjà connue ? Cela peut prendre un moment.")) &&
            this.startSync(false, "sizes", [], false, true),
          title: t("Comme « Recalculer les tailles », mais réinterroge aussi les fichiers dont la taille " +
                   "est déjà connue (après un changement de fichier à la source)"),
        }, t("Tout recalculer")),
        el("button", { onclick: () => this.restart(), disabled: locked }, t("Redémarrer ComfyUI"))),
      this.configBar(locked, this.data),
      el("div", { class: "legend" },
        // Chaque état est aussi un filtre : un clic l'ajoute ou le retire (plusieurs possibles).
        Object.entries(STATE_FILTERS).map(([key]) => el("span", {
          class: `state ${key}${this.states.has(key) ? " active" : ""}`,
          title: this.states.has(key) ? t("Cliquer pour ne plus filtrer sur cet état")
            : t("Cliquer pour n'afficher que les profils dans cet état"),
          onclick: () => {
            this.states.has(key) ? this.states.delete(key) : this.states.add(key);
            saveSetting(STATES_KEY, [...this.states].join(","));
            this.render();
          },
        }, t({ installed: "installé", partial: "partiellement installé", missing: "non installé" }[key]))),
        el("span", {
          class: `chip unmanaged state${this.unmanagedOnly ? " active" : ""}`,
          title: `${t(UNMANAGED_HINT)}\n` + (this.unmanagedOnly ? t("Cliquer pour ne plus filtrer sur cet état")
            : t("Cliquer pour n'afficher que les profils avec des éléments non pris en charge")),
          onclick: () => {
            this.unmanagedOnly = !this.unmanagedOnly;
            saveSetting(UNMANAGED_KEY, this.unmanagedOnly ? "1" : "0");
            this.render();
          },
        }, t("non pris en charge"))),
      this.search,
      el("div", { class: "filters" },
        this.toggle("namesOnly", NAMES_KEY, t("Chercher dans le nom des profils seulement"),
          t("Le filtre texte ne cherche pas dans les éléments des profils (modèles, custom nodes…)")),
        this.toggle("leavesOnly", LEAVES_KEY, t("Afficher seulement les profils finaux"),
          t("Masque les profils étendus par d'autres (ex. les profils *-common), installés avec eux")),
        this.leavesOnly && this.toggle("grouped", GROUPED_KEY, t("Afficher aussi les profils regroupés"),
          t("Affiche aussi les profils finaux étendus par un profil de regroupement (sans élément propre, " +
            "qui ne fait que réunir d'autres profils, ex. minimax-h3-all-*)")),
        hidden > 0 && el("span", { class: "muted" }, t("({n} masqué(s))", { n: hidden }))),
      el("div", { class: "list" }, profiles),
      el("div", { class: "bar" },
        el("button", { class: "primary", disabled: locked || !selection.length,
                       onclick: () => this.startSync(false) },
          selection.length ? t("Synchroniser ({n})", { n: selection.length }) : t("Synchroniser")),
        el("button", { disabled: running || !selection.length, onclick: () => this.startSync(true) }, "Dry-run"),
        el("button", {
          disabled: locked || !selection.length, onclick: () => this.startSync(false, "sync", selection, false, true),
          title: t("Installe ce qui manque et met à jour ce que le gestionnaire a installé ou pris en charge, " +
                   "s'il a changé à la source (custom nodes, modèles, workflows, paquets pip)"),
        }, selection.length ? t("Mettre à jour ({n})", { n: selection.length }) : t("Mettre à jour")),
        el("button", { disabled: locked || !selection.length, onclick: () => this.prepareUninstall() },
          t("Désinstaller…")),
        running && el("button", { class: "danger", disabled: this.sync.stopping, onclick: () => this.stop() },
          this.sync.stopping ? t("Arrêt…") : t("Arrêter"))),
      el("div", { class: "muted" },
        t("Nouveaux modèles : visibles directement. Nouveaux custom nodes : redémarrer ComfyUI.")),
      status && el("div", { class: this.sync.returncode ? "error" : "muted" }, status),
      this.logBox,
    );
  }

  // Profils déclarés par le workflow ouvert (node « Workflow profiles ») : état, installation,
  // ajout depuis la source déclarée de ceux qui manquent au fichier de profils.
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
      const status = !need.valid ? el("span", { class: "error" }, t("nom invalide"))
        : !p ? el("span", { class: "warn" }, t("absent du fichier de profils"))
        : el("span", { class: SATISFIED.has(p.state) ? "ok" : "todo" }, t(state.label));
      return el("div", { class: "need" },
        el("span", { class: SATISFIED.has(p?.state) ? "ok" : "todo" }, SATISFIED.has(p?.state) ? "✓" : "✗"),
        el("span", {
          class: "name", title: t("Afficher ce profil dans la liste"),
          onclick: () => { this.search.value = need.name; this.render(); },
        }, need.name),
        status,
        el("div", { class: "actions" },
          p && state.install && !SATISFIED.has(p.state) && iconButton("pi-download",
            t("Installer {name} (ce qui manque)", { name: need.name }), locked,
            () => this.startSync(false, "sync", [need.name])),
          !p && need.valid && need.source && iconButton("pi-plus",
            t("Ajouter {name} depuis {url}", { name: need.name, url: need.source }), locked,
            () => this.addFromSource(need.source, [need.name])),
          !p && need.valid && !need.source && el("span", {
            class: "muted", title: t("Le node ne donne pas de source : importe le fichier de profils qui le définit."),
          }, t("sans source"))));
    });
    return el("div", { class: `workflow${done ? " done" : ""}` },
      el("div", { class: "bar" },
        el("strong", {}, t("Ce workflow")),
        el("span", { class: "muted" }, t("profils déclarés par son node « Profils du workflow »"))),
      rows,
      done ? el("div", { class: "ok" }, t("Tous les profils de ce workflow sont installés."))
        : toInstall.length > 1 && el("div", { class: "bar" },
          el("button", { class: "primary", disabled: locked, onclick: () => this.startSync(false, "sync", toInstall) },
            t("Installer les profils du workflow ({n})", { n: toInstall.length }))));
  }

  // Ajoute au fichier de profils des profils (et ceux dont ils héritent) pris dans le fichier
  // publié à `url`, sans remplacer ceux qui y sont déjà.
  async addFromSource(url, names) {
    if (!confirm(t("Ajouter {names} (et les profils dont ils héritent) à ton fichier de profils, " +
                   "depuis {url} ? Les profils déjà présents ne sont pas modifiés.",
                   { names: names.join(", "), url }))) return;
    try {
      const { added, conflicts } = await request("POST", "/config/add-from-url", { url, profiles: names });
      toast("success", t("Profils"), added.length ? t("Profils ajoutés : {names}", { names: added.join(", ") })
        : t("Rien à ajouter : ces profils sont déjà dans ton fichier."));
      if (conflicts.length) {
        toast("warn", t("Profils"), t("Déjà dans ton fichier avec un autre contenu, gardés tels quels : {names}",
          { names: conflicts.join(", ") }), 10000);
      }
    } catch (e) {
      toast("error", t("Profils"), e.message);
    }
    await this.load();
  }

  // `data` : résultat de `list --json`, ou null si le fichier de profils est illisible.
  configBar(locked, data) {
    return el("div", { class: "bar" },
      el("span", { class: "muted" }, "profiles.json :"),
      el("button", { onclick: () => this.edit(), disabled: locked }, t("Éditer")),
      el("button", { onclick: () => this.importFile(), disabled: locked,
                     title: t("Remplace le fichier de profils par un fichier de ton poste") }, t("Importer…")),
      el("button", { onclick: () => this.importUrl(), disabled: locked,
                     title: t("Remplace le fichier de profils par celui d'une URL") }, t("Depuis une URL…")),
      el("button", { onclick: () => this.exportFile() }, t("Exporter")),
      (!data || data.source === "user") && el("button", {
        onclick: () => this.resetToSeed(), disabled: locked,
        title: data ? t("Remet en service le modèle ({path})", { path: data.seed }) : t("Remet en service le modèle"),
      }, t("Revenir au modèle")));
  }

  renderDetail(detail) {
    if (detail === null || detail === undefined) return el("div", { class: "details muted" }, t("Chargement…"));
    if (detail.error) return el("div", { class: "details error" }, detail.error);
    if (!detail.length) return el("div", { class: "details muted" }, t("(profil vide)"));
    const missing = detail.filter((i) => i.missing).length;
    // Éléments regroupés par profil qui les déclare (le profil lui-même, puis ceux dont il
    // hérite) : `show --json` les renvoie déjà dans cet ordre.
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
        missing ? t("{n} élément(s) à installer sur {total}", { n: missing, total: detail.length })
          : t("Tout est installé")),
      groups.map((group) => [
        titled && el("div", { class: "group" },
          group.inherited ? t("Hérité de {name}", { name: group.profile }) : t("Propre au profil"),
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
        title: item.size == null ? t("Taille inconnue : « Recalculer les tailles » l'interroge à la source")
          : t("{n} octets", { n: item.size }),
      }, item.size == null ? "?" : humanSize(item.size)),
      item.unmanaged && el("span", { class: "chip unmanaged", title: t(UNMANAGED_HINT) }, t("non pris en charge")),
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

// Lien vers la source d'un élément : icône PrimeIcons, ou texte quand il n'y en a pas.
const LINK_SITES = {
  hf: { label: "Hugging Face", text: "🤗" },
  github: { label: "GitHub", icon: "pi pi-github" },
  civitai: { label: "CivitAI", text: "C" },
  gdrive: { label: "Google Drive", icon: "pi pi-google" },
  pypi: { label: "PyPI", icon: "pi pi-box" },
  git: { label: "Dépôt git", icon: "pi pi-code" },  // traduit à l'affichage
  url: { label: "Source", icon: "pi pi-external-link" },
};

// Seuls les fichiers ont une taille déclarée (pas les custom nodes ni les paquets pip).
const FILE_KINDS = new Set(["model", "workflow"]);

const UNMANAGED_HINT = "Présent, mais pas installé par le gestionnaire : la désinstallation le laisse en place";

// Même format que human_size() côté Python : « 20,9 Go », « 20.9 GB ».
function humanSize(size) {
  for (const [unit, factor] of [["To", 1e12], ["Go", 1e9], ["Mo", 1e6], ["Ko", 1e3]]) {
    if (size >= factor) return `${(size / factor).toFixed(1).replace(".", t(","))} ${t(unit)}`;
  }
  return `${size} ${t("o")}`;
}

// Taille d'un profil (`list --json`) : total de ses fichiers, dans la langue du panneau ; à
// défaut, le texte écrit dans profiles.json par « Recalculer les tailles ».
function profileSize(p) {
  if (!p.total && !p.unknown) return p.size || "";
  const total = humanSize(p.total || 0);
  return p.unknown ? `${total} ${t("+ {n} fichier(s) de taille inconnue", { n: p.unknown })}` : total;
}

// Taille des fichiers que l'installation du profil ajouterait ; vide si rien ne manque.
function todoSize(p) {
  if (!p.todo && !p.todo_unknown) return "";
  const size = t("{size} à télécharger", { size: humanSize(p.todo || 0) });
  return p.todo_unknown ? `${size} ${t("+ {n} fichier(s) de taille inconnue", { n: p.todo_unknown })}` : size;
}

// Réglages du panneau propres à ce navigateur ; le stockage peut être indisponible.
const LEAVES_KEY = "comfy-profiles.leavesOnly";
const NAMES_KEY = "comfy-profiles.namesOnly";
const GROUPED_KEY = "comfy-profiles.grouped";
const STATES_KEY = "comfy-profiles.states";
const UNMANAGED_KEY = "comfy-profiles.unmanagedOnly";

// Filtres d'état de la légende -> états des profils (`list --json`) qu'ils affichent.
const STATE_FILTERS = {
  installed: ["installed"],
  partial: ["partial"],
  missing: ["missing", "empty"],
};

// Profil de regroupement : aucun élément propre, il ne fait que réunir d'autres profils.
function isGroup(p) {
  return p.extends.length > 1 && Object.values(p.counts).every((n) => n === 0);
}

function loadSetting(key) {
  try { return localStorage.getItem(key); } catch { return null; }
}

function saveSetting(key, value) {
  try { localStorage.setItem(key, value); } catch { /* réglage simplement non mémorisé */ }
}

// force (action « sync ») : mise à jour de ce qui a changé à la source (sync --update).
function actionLabel(action, force = false) {
  if (action === "sync" && force) return t("Mise à jour");
  return t({ uninstall: "Désinstallation", sizes: "Calcul des tailles" }[action] || "Synchronisation");
}

// État d'installation d'un profil (`list --json`) : libellé, et actions permises.
const STATES = {
  installed: { label: "Installé", install: false, uninstall: true },
  partial: { label: "Partiellement installé", install: true, uninstall: true },
  missing: { label: "Non installé", install: true, uninstall: false },
  empty: { label: "Aucun fichier à installer (pip, ou custom nodes déjà présents hors gestionnaire)", install: true, uninstall: false },
  error: { label: "Config invalide", install: false, uninstall: false },
};

// Origine du fichier de profils actif (`list --json`).
const SOURCES = {
  option: "Fichier (--config)",
  env: "Fichier (COMFY_PROFILES_CONFIG)",
  user: "Ton fichier",
  seed: "Modèle (lecture seule)",
};

// Petit bouton icône seule (PrimeIcons, fournies par le frontend ComfyUI) ; l'action est
// indiquée au survol.
function iconButton(icon, hint, disabled, onclick) {
  return el("button", { class: "icon", title: hint, "aria-label": hint, disabled, onclick },
    el("i", { class: `pi ${icon}` }));
}

let panel = null;
// Traductions : chargées dès init, car le dernier workflow est rouvert avant setup.
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
      console.warn("[comfy-profiles] registerSidebarTab indisponible dans ce frontend");
      return;
    }
    await messagesLoaded;
    document.head.append(el("style", {}, STYLE));
    app.extensionManager.registerSidebarTab({
      id: "comfy-profiles",
      icon: "pi pi-box",
      title: t("Profils"),
      tooltip: t("Profils d'utilisation (modèles, custom nodes)"),
      type: "custom",
      render: (container) => {
        if (!panel) {
          panel = new ProfilesPanel();
          panel.load();
        }
        // Le workflow ouvert a pu changer depuis le dernier affichage.
        panel.render();
        container.replaceChildren(panel.root);
      },
    });
  },
});
