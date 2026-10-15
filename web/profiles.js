// Onglet « Profils » de la barre latérale ComfyUI : voir __init__.py pour les routes appelées.
import { app } from "../../scripts/app.js";
import { api } from "../../scripts/api.js";

const API = "/comfy-profiles";
const EVENT = "comfy-profiles.log";
const MAX_LOG_LINES = 5000;

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
.cprof .list { display: flex; flex-direction: column; gap: 4px; }
.cprof .profile { border: 1px solid var(--border-color); border-radius: 6px; padding: 6px 8px; }
.cprof .profile.selected { border-color: var(--p-primary-color, #2a6fd6); }
.cprof .profile.installed { background: rgba(58, 154, 90, .16); }
.cprof .profile.partial { background: rgba(224, 160, 48, .16); }
.cprof .profile.error { background: rgba(224, 80, 80, .16); }
.cprof .legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--descrip-text, #999); }
.cprof .legend span::before { content: ""; display: inline-block; width: 10px; height: 10px;
  margin-right: 4px; vertical-align: -1px; border-radius: 2px; border: 1px solid var(--border-color); }
.cprof .legend .installed::before { background: rgba(58, 154, 90, .5); }
.cprof .legend .partial::before { background: rgba(224, 160, 48, .5); }
.cprof .head { display: flex; gap: 8px; align-items: center; }
.cprof .head label { flex: 1; display: flex; gap: 6px; align-items: center; cursor: pointer;
  font-weight: 600; word-break: break-all; }
.cprof .chip { font-size: 11px; padding: 0 6px; border-radius: 8px; white-space: nowrap;
  background: var(--comfy-input-bg); border: 1px solid var(--border-color); }
.cprof .chip.default { border-color: #3a9a5a; color: #3a9a5a; }
.cprof .details { margin-top: 6px; display: flex; flex-direction: column; gap: 2px; }
.cprof .item { display: flex; gap: 6px; font-size: 12px; font-family: monospace; }
.cprof .item .name { flex: 1; word-break: break-all; }
.cprof .ok { color: #3a9a5a; }
.cprof .todo { color: #e0a030; }
.cprof .log { background: var(--comfy-input-bg); border: 1px solid var(--border-color);
  border-radius: 4px; padding: 6px; font-family: monospace; font-size: 11px; white-space: pre-wrap;
  word-break: break-all; max-height: 320px; min-height: 80px; overflow-y: auto; }
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
  node.append(...children.flat().filter((c) => c != null && c !== false));
  return node;
}

async function request(method, path, body) {
  const options = { method };
  if (body !== undefined) {
    options.headers = { "Content-Type": "application/json" };
    options.body = JSON.stringify(body);
  }
  const resp = await api.fetchApi(`${API}${path}`, options);
  const data = await resp.json().catch(() => ({}));
  if (!resp.ok) throw new Error(data.error || `HTTP ${resp.status}`);
  return data;
}

function toast(severity, summary, detail) {
  app.extensionManager?.toast?.add({ severity, summary, detail, life: 5000 });
}

class ProfilesPanel {
  constructor() {
    this.root = el("div", { class: "cprof" });
    this.data = null;          // résultat de `list --json`
    this.selected = new Set();
    this.expanded = new Map();  // profil -> état (`show --json`), ou null pendant le chargement
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
      this.error = `Profils indisponibles : ${e.message}`;
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
    const { action, dry_run: dryRun, returncode } = detail;
    this.sync = { ...this.sync, running: false, stopping: false, action, dry_run: dryRun, returncode };
    const what = dryRun && action === "sync" ? "Dry-run" : actionLabel(action);
    if (returncode === 0) toast("success", "Profils", `${what} : terminé.`);
    else if (returncode === 130) toast("warn", "Profils", `${what} : arrêté.`);
    else toast("error", "Profils", `${what} : incomplet, voir les logs.`);
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

  async startSync(dryRun, action = "sync", profiles = [...this.selected], withExtends = false) {
    try {
      this.setSync(await request("POST", "/sync",
        { action, profiles, dry_run: dryRun, with_extends: withExtends }));
    } catch (e) {
      toast("error", "Profils", e.message);
    }
    this.render();
  }

  async stop() {
    if (!confirm("Arrêter l'action en cours ? L'étape en cours est abandonnée proprement, " +
                 "une prochaine synchronisation la reprendra.")) return;
    try {
      const { running, stopping } = await request("POST", "/stop");
      this.sync = { ...this.sync, running, stopping };
    } catch (e) {
      toast("error", "Profils", e.message);
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
      toast("error", "Profils", e.message);
    }
    this.render();
  }

  confirmUninstall() {
    const { profiles, withExtends } = this.uninstall;
    this.uninstall = null;
    this.startSync(false, "uninstall", profiles, withExtends);
  }

  async restart() {
    if (!confirm("Redémarrer ComfyUI ? Les générations en cours seront interrompues.")) return;
    try {
      await request("POST", "/restart");
      toast("info", "Profils", "Redémarrage de ComfyUI… la page se reconnecte toute seule.");
    } catch (e) {
      toast("error", "Profils", e.message);
    }
  }

  async edit() {
    try {
      this.editing = await request("GET", "/config");
      this.editError = "";
    } catch (e) {
      toast("error", "Profils", e.message);
    }
    this.render();
  }

  async save(text) {
    try {
      await request("PUT", "/config", { text });
      this.editing = null;
      toast("success", "Profils", "profiles.json enregistré.");
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
      if (!file || !confirm(`Remplacer le fichier de profils par ${file.name} ?`)) return;
      try {
        await request("PUT", "/config", { text: await file.text(), origin: `import de ${file.name}` });
        toast("success", "Profils", `${file.name} importé.`);
        await this.load();
      } catch (e) {
        toast("error", "Profils", e.message);
      }
    });
    input.click();
  }

  async importUrl() {
    const url = prompt("URL du fichier de profils (ex. lien raw GitHub ou gist) :");
    if (!url?.trim()) return;
    try {
      await request("POST", "/config/import-url", { url: url.trim() });
      toast("success", "Profils", "Fichier de profils importé.");
      await this.load();
    } catch (e) {
      toast("error", "Profils", e.message);
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
      toast("error", "Profils", e.message);
    }
  }

  async resetToSeed() {
    if (!confirm("Revenir au modèle ? Ton fichier de profils est gardé en profiles.json.bak.")) return;
    try {
      const { backup } = await request("DELETE", "/config");
      toast("success", "Profils", `Modèle rétabli, ancien fichier : ${backup}`);
      await this.load();
    } catch (e) {
      toast("error", "Profils", e.message);
    }
  }

  render() {
    this.root.replaceChildren(
      this.editing ? this.renderEditor() : this.uninstall ? this.renderUninstall() : this.renderMain());
  }

  renderUninstall() {
    const { profiles, plan, withExtends } = this.uninstall;
    const item = (kind, name, extra) => el("div", { class: "item" },
      el("span", { class: "muted" }, kind), el("span", { class: "name" }, name),
      extra && el("span", { class: "muted" }, extra));
    return el("div", { style: "display:flex;flex-direction:column;gap:8px" },
      el("h3", {}, `Désinstaller : ${profiles.join(", ")}`),
      plan.extends.length > 0 && el("label", { class: "bar", style: "cursor:pointer" },
        el("input", { type: "checkbox", checked: withExtends,
                      onchange: (e) => this.prepareUninstall(profiles, e.target.checked) }),
        `Inclure les profils hérités (${plan.extends.join(", ")})`),
      plan.extends.length > 0 && !withExtends && el("div", { class: "muted" },
        "Seuls les éléments propres à ce(s) profil(s) partent ; les profils hérités restent installés."),
      plan.remove.length
        ? el("div", {}, `${plan.remove.length} élément(s) supprimé(s), ${formatSize(plan.freed)} libérés :`)
        : el("div", { class: "muted" }, plan.extends.length && !withExtends
          ? "Rien à supprimer en propre : coche « Inclure les profils hérités » pour un profil qui ne fait que les regrouper."
          : "Rien à supprimer : tout est absent ou encore utilisé."),
      el("div", { class: "details" }, plan.remove.map((r) => item(r.kind, r.name, formatSize(r.size)))),
      plan.kept.length > 0 && el("div", { class: "muted" },
        `Conservés, car utilisés par ${plan.keep_profiles.join(", ")} :`),
      plan.kept.length > 0 && el("div", { class: "details" },
        plan.kept.map((k) => item(k.kind, k.name, k.by.join(", ")))),
      plan.startup.length > 0 && el("div", { class: "warn" },
        `${plan.startup.join(", ")} : dans COMFY_PROFILES, réinstallé(s) au prochain démarrage.`),
      plan.unmanaged.length > 0 && el("div", { class: "muted" },
        "Laissés en place, car pas installés par le gestionnaire :"),
      plan.unmanaged.length > 0 && el("div", { class: "details" },
        plan.unmanaged.map((u) => item(u.kind, u.name))),
      plan.remove.some((r) => r.kind === "custom_node") && el("div", { class: "warn" },
        "Des custom nodes seront supprimés : redémarre ComfyUI ensuite pour les décharger."),
      el("div", { class: "muted" }, "Les paquets pip installés pour ces profils restent en place."),
      el("div", { class: "bar" },
        el("button", { class: "danger", disabled: !plan.remove.length, onclick: () => this.confirmUninstall() },
          "Désinstaller"),
        el("button", { onclick: () => { this.uninstall = null; this.render(); } }, "Annuler")),
    );
  }

  renderEditor() {
    const area = el("textarea", { spellcheck: "false" });
    area.value = this.editing.text;
    return el("div", { class: "cprof-editor", style: "display:flex;flex-direction:column;gap:8px" },
      el("h3", {}, "Éditer les profils"),
      el("div", { class: "muted" }, this.editing.path),
      this.editing.source === "seed" && el("div", { class: "warn" },
        `C'est le modèle, en lecture seule : l'enregistrement crée ton fichier de profils ` +
        `(${this.editing.writable}), utilisé ensuite à sa place.`),
      area,
      this.editError && el("div", { class: "error" }, this.editError),
      el("div", { class: "bar" },
        el("button", { class: "primary", onclick: () => this.save(area.value) }, "Enregistrer"),
        el("button", { onclick: () => { this.editing = null; this.render(); } }, "Annuler")),
    );
  }

  renderMain() {
    const running = this.sync.running;
    const header = el("div", {},
      el("h3", {}, "Profils"),
      this.data && el("div", { class: "muted", title: this.data.config },
        `${SOURCES[this.data.source] || this.data.source} : ${this.data.config}`),
      this.data?.readonly && el("div", { class: "warn" },
        "Lecture seule (COMFY_PROFILES_READONLY) : seul le dry-run est possible."),
      this.error && el("div", { class: "error" }, this.error));
    // Fichier de profils invalide : on peut encore le corriger, le remplacer ou revenir au modèle.
    if (!this.data) {
      return el("div", { style: "display:flex;flex-direction:column;gap:10px" }, header,
        el("div", { class: "bar" }, el("button", { onclick: () => this.load() }, "Recharger")),
        this.configBar(running, null));
    }
    const locked = running || this.data.readonly;

    const profiles = Object.entries(this.data.profiles).map(([name, p]) => {
      const detail = this.expanded.get(name);
      const state = STATES[p.state] || STATES.missing;
      return el("div", { class: `profile ${p.state}${this.selected.has(name) ? " selected" : ""}`, title: state.label },
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
          this.data.default.includes(name) &&
            el("span", { class: "chip default", title: "Dans COMFY_PROFILES : synchronisé à chaque démarrage" }, "démarrage"),
          p.size && el("span", { class: "chip" }, p.size),
          el("div", { class: "actions" },
            iconButton("pi-download",
              state.install ? `Installer ${name} (ce qui manque)` : `${name} : ${state.label.toLowerCase()}`,
              locked || !state.install, () => this.startSync(false, "sync", [name])),
            iconButton("pi-trash",
              state.uninstall ? `Désinstaller ${name}…` : `${name} : ${state.label.toLowerCase()}`,
              locked || !state.uninstall, () => this.prepareUninstall([name])),
            iconButton(this.expanded.has(name) ? "pi-chevron-down" : "pi-chevron-right",
              this.expanded.has(name) ? "Masquer le détail" : "Voir ce qui est installé",
              false, () => this.expand(name)))),
        p.description && el("div", { class: "muted" }, p.description),
        p.extends.length > 0 && el("div", { class: "muted" }, `extends : ${p.extends.join(", ")}`),
        this.expanded.has(name) && this.renderDetail(detail));
    });

    const selection = [...this.selected];
    const what = actionLabel(this.sync.action);
    const target = (this.sync.profiles || []).join(", ");
    const status = running
      ? `${what} ${this.sync.stopping ? "en cours d'arrêt" : "en cours"}` +
        `${target ? ` : ${target}` : ""}${this.sync.dry_run ? " (dry-run)" : ""}`
      : this.sync.returncode == null ? ""
      : this.sync.returncode === 0 ? `Dernière action (${what.toLowerCase()}) : OK`
      : this.sync.returncode === 130 ? `Dernière action (${what.toLowerCase()}) : arrêtée`
      : `Dernière action (${what.toLowerCase()}) : échec (code ${this.sync.returncode})`;

    return el("div", { style: "display:flex;flex-direction:column;gap:10px" },
      header,
      el("div", { class: "bar" },
        el("button", { onclick: () => this.load() }, "Recharger"),
        el("button", {
          onclick: () => this.startSync(false, "sizes", []), disabled: locked,
          title: "Interroge Hugging Face / CivitAI / GitHub (sans rien télécharger) pour les " +
                 "fichiers sans taille, et enregistre la taille de chaque profil dans profiles.json",
        }, "Recalculer les tailles"),
        el("button", { onclick: () => this.restart(), disabled: locked }, "Redémarrer ComfyUI")),
      this.configBar(locked, this.data),
      el("div", { class: "legend" },
        el("span", { class: "installed" }, "installé"),
        el("span", { class: "partial" }, "partiellement installé"),
        el("span", {}, "non installé")),
      el("div", { class: "list" }, profiles),
      el("div", { class: "bar" },
        el("button", { class: "primary", disabled: locked || !selection.length,
                       onclick: () => this.startSync(false) },
          selection.length ? `Synchroniser (${selection.length})` : "Synchroniser"),
        el("button", { disabled: running || !selection.length, onclick: () => this.startSync(true) }, "Dry-run"),
        el("button", { disabled: locked || !selection.length, onclick: () => this.prepareUninstall() },
          "Désinstaller…"),
        running && el("button", { class: "danger", disabled: this.sync.stopping, onclick: () => this.stop() },
          this.sync.stopping ? "Arrêt…" : "Arrêter")),
      el("div", { class: "muted" },
        "Nouveaux modèles : visibles directement. Nouveaux custom nodes : redémarrer ComfyUI."),
      status && el("div", { class: this.sync.returncode ? "error" : "muted" }, status),
      this.logBox,
    );
  }

  // `data` : résultat de `list --json`, ou null si le fichier de profils est illisible.
  configBar(locked, data) {
    return el("div", { class: "bar" },
      el("span", { class: "muted" }, "profiles.json :"),
      el("button", { onclick: () => this.edit(), disabled: locked }, "Éditer"),
      el("button", { onclick: () => this.importFile(), disabled: locked,
                     title: "Remplace le fichier de profils par un fichier de ton poste" }, "Importer…"),
      el("button", { onclick: () => this.importUrl(), disabled: locked,
                     title: "Remplace le fichier de profils par celui d'une URL" }, "Depuis une URL…"),
      el("button", { onclick: () => this.exportFile() }, "Exporter"),
      (!data || data.source === "user") && el("button", {
        onclick: () => this.resetToSeed(), disabled: locked,
        title: data ? `Remet en service le modèle (${data.seed})` : "Remet en service le modèle",
      }, "Revenir au modèle"));
  }

  renderDetail(detail) {
    if (detail === null || detail === undefined) return el("div", { class: "details muted" }, "Chargement…");
    if (detail.error) return el("div", { class: "details error" }, detail.error);
    if (!detail.length) return el("div", { class: "details muted" }, "(profil vide)");
    const missing = detail.filter((i) => i.missing).length;
    return el("div", { class: "details" },
      el("div", { class: missing ? "todo" : "ok" },
        missing ? `${missing} élément(s) à installer sur ${detail.length}` : "Tout est installé"),
      detail.map((item) => el("div", { class: "item" },
        el("span", { class: item.missing ? "todo" : "ok" }, item.missing ? "✗" : "✓"),
        el("span", { class: "muted" }, item.kind),
        el("span", { class: "name" }, item.name))));
  }
}

function actionLabel(action) {
  return { uninstall: "Désinstallation", sizes: "Calcul des tailles" }[action] || "Synchronisation";
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

function formatSize(bytes) {
  for (const [unit, factor] of [["To", 1e12], ["Go", 1e9], ["Mo", 1e6], ["Ko", 1e3]]) {
    if (bytes >= factor) return `${(bytes / factor).toFixed(1).replace(".", ",")} ${unit}`;
  }
  return `${bytes} o`;
}

let panel = null;

app.registerExtension({
  name: "comfyui-profiles.panel",
  setup() {
    if (!app.extensionManager?.registerSidebarTab) {
      console.warn("[comfy-profiles] registerSidebarTab indisponible dans ce frontend");
      return;
    }
    document.head.append(el("style", {}, STYLE));
    app.extensionManager.registerSidebarTab({
      id: "comfy-profiles",
      icon: "pi pi-box",
      title: "Profils",
      tooltip: "Profils d'utilisation (modèles, custom nodes)",
      type: "custom",
      render: (container) => {
        if (!panel) {
          panel = new ProfilesPanel();
          panel.render();
          panel.load();
        }
        container.replaceChildren(panel.root);
      },
    });
  },
});
