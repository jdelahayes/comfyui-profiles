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
  color: var(--fg-color);
  /* Palette: one color per meaning, tints derived from it. */
  --cp-ok: #10b981; --cp-warn: #f59e0b; --cp-err: #ef4444; --cp-info: #3b82f6;
  /* Partially installed: bright yellow, never as a background tint (it turns brown on a dark
     surface), only for the bars and dots. */
  --cp-partial: #facc15;
  --cp-accent: var(--p-primary-color, #6366f1);
  --cp-surface: var(--comfy-menu-bg, #1e1e1e); --cp-radius: 8px; }
.cprof h3 { margin: 0; font-size: 15px; }
.cprof h4 { margin: 4px 0 0; font-size: 13px; border-bottom: 1px solid var(--border-color); }
.cprof .field { display: flex; flex-wrap: wrap; align-items: center; gap: 6px; cursor: pointer; }
.cprof input.num { width: 64px; padding: 3px 5px; border-radius: 6px; border: 1px solid var(--border-color);
  background: var(--comfy-input-bg); color: var(--input-text); }
.cprof .muted { color: var(--descrip-text, #999); font-size: 12px; }
.cprof .warn { color: var(--cp-warn); font-size: 12px; }
.cprof .error { color: var(--cp-err); white-space: pre-wrap; font-size: 12px; }
.cprof .bar { display: flex; flex-wrap: wrap; gap: 6px; align-items: center; }
.cprof button { background: var(--comfy-input-bg); color: var(--input-text, var(--fg-color));
  border: 1px solid var(--border-color); border-radius: 6px; padding: 4px 10px; cursor: pointer;
  font-size: 12px; transition: filter .15s, background .15s; }
.cprof button:hover:not(:disabled) { filter: brightness(1.2); }
.cprof button:disabled { opacity: .45; cursor: default; }
.cprof button.icon { padding: 3px 6px; font-size: 11px; line-height: 1; }
.cprof .actions { display: flex; gap: 3px; }
.cprof button.primary { background: var(--cp-accent); color: #fff; border-color: transparent; }
.cprof button.danger { background: var(--cp-err); color: #fff; border-color: transparent; }
.cprof .filters { display: flex; flex-wrap: wrap; align-items: center; gap: 4px 12px; }
.cprof .filter { display: flex; align-items: center; gap: 4px; cursor: pointer; }
.cprof .search { width: 100%; box-sizing: border-box; padding: 5px 8px; border-radius: 6px;
  border: 1px solid var(--border-color); background: var(--comfy-input-bg); color: var(--input-text); }
.cprof .search:focus { outline: none; border-color: var(--cp-accent); }
.cprof .match { font-family: monospace; word-break: break-all; }
.cprof .list { display: flex; flex-direction: column; gap: 6px; }
/* Profile card: state given by a colored bar on the left and a light tint. */
.cprof .profile { --state: var(--border-color); border: 1px solid var(--border-color);
  border-left: 3px solid var(--state); border-radius: var(--cp-radius); padding: 6px 8px;
  background: var(--cp-surface); }
.cprof .profile.installed { --state: var(--cp-ok);
  background: linear-gradient(color-mix(in srgb, var(--cp-ok) 9%, transparent), color-mix(in srgb, var(--cp-ok) 9%, transparent)), var(--cp-surface); }
.cprof .profile.partial { --state: var(--cp-partial); }
.cprof .profile.error { --state: var(--cp-err);
  background: linear-gradient(color-mix(in srgb, var(--cp-err) 9%, transparent), color-mix(in srgb, var(--cp-err) 9%, transparent)), var(--cp-surface); }
.cprof .profile.selected { border-color: var(--cp-accent); border-left-color: var(--state);
  box-shadow: 0 0 0 1px var(--cp-accent); }
.cprof .legend { display: flex; flex-wrap: wrap; gap: 10px; font-size: 11px; color: var(--descrip-text, #999); }
.cprof .legend span::before { content: ""; display: inline-block; width: 8px; height: 8px;
  margin-right: 5px; vertical-align: 0; border-radius: 50%; background: var(--border-color); }
.cprof .legend .state { cursor: pointer; padding: 1px 6px; border-radius: 999px; border: 1px solid transparent; }
.cprof .legend .state:hover { color: var(--input-text); }
.cprof .legend .state.active { color: var(--input-text); border-color: var(--cp-accent); }
.cprof .legend .installed::before { background: var(--cp-ok); }
.cprof .legend .partial::before { background: var(--cp-partial); }
.cprof .head { display: flex; gap: 8px; align-items: center; }
.cprof .head label { flex: 1; min-width: 0; display: flex; gap: 6px; align-items: center; cursor: pointer;
  font-weight: 600; overflow-wrap: anywhere; }
/* Chips: pills tinted with their color. */
.cprof .chips { display: flex; flex-wrap: wrap; gap: 4px; margin: 4px 0 2px; }
.cprof .chip { --tone: var(--descrip-text, #999); font-size: 11px; padding: 1px 8px; border-radius: 999px;
  white-space: nowrap; color: var(--input-text, var(--fg-color)); background: var(--comfy-input-bg);
  border: 1px solid transparent; }
.cprof .chip.default, .cprof .chip.download, .cprof .chip.unmanaged {
  color: var(--tone); background: color-mix(in srgb, var(--tone) 14%, transparent); }
.cprof .chip.default { --tone: var(--cp-ok); }
.cprof .chip.download { --tone: var(--cp-info); }
.cprof .chip.unmanaged { --tone: var(--cp-warn); border-color: color-mix(in srgb, var(--cp-warn) 45%, transparent);
  border-style: dashed; }
.cprof .legend .chip.unmanaged.active { border-style: solid; border-color: var(--cp-accent); }
.cprof .legend .chip::before { display: none; }
/* Variant chips: dot of the variant's state, ring when ticked. */
.cprof .chip.variant { display: inline-flex; align-items: center; gap: 5px; cursor: pointer;
  border-color: var(--border-color); background: var(--cp-surface); }
.cprof .chip.variant::before { content: ""; width: 7px; height: 7px; border-radius: 50%;
  background: var(--border-color); }
.cprof .chip.variant.installed::before { background: var(--cp-ok); }
.cprof .chip.variant.partial::before { background: var(--cp-partial); }
.cprof .chip.variant.error::before { background: var(--cp-err); }
.cprof .chip.variant.installed { background: color-mix(in srgb, var(--cp-ok) 14%, var(--cp-surface)); }
.cprof .chip.variant input { display: none; }
.cprof .chip.variant .pick { font-size: 9px; }
/* Ticked: solid accent ring if already installed (✓); dashed blue if the card's sync will
   install it (download icon). */
.cprof .chip.variant.chosen { border-color: var(--cp-accent); box-shadow: 0 0 0 1px var(--cp-accent); }
.cprof .chip.variant.chosen .pick { color: var(--cp-accent); }
.cprof .chip.variant.chosen.pending { border: 1px dashed var(--cp-info); box-shadow: none;
  background: color-mix(in srgb, var(--cp-info) 14%, var(--cp-surface)); }
.cprof .chip.variant.chosen.pending .pick { color: var(--cp-info); }
.cprof .details { margin-top: 6px; display: flex; flex-direction: column; gap: 2px; }
.cprof .item { display: flex; gap: 6px; font-size: 12px; font-family: monospace; }
.cprof .details .group { margin-top: 6px; font-size: 12px; font-weight: 600;
  border-bottom: 1px solid var(--border-color); }
.cprof .details .group ~ .item { margin-left: 8px; }
/* Items of a variant or of an inherited profile, in the details: a block of their own, colored
   by its state (opaque, so as not to take the card's color). */
.cprof .details .block { --state: var(--border-color); border: 1px solid var(--border-color);
  border-left: 3px solid var(--state); border-radius: 6px; padding: 0 6px 4px; margin-top: 6px;
  background: var(--cp-surface); }
.cprof .details .block .group { margin-top: 3px; }
.cprof .details .block.installed { --state: var(--cp-ok);
  background: color-mix(in srgb, var(--cp-ok) 12%, var(--cp-surface)); }
.cprof .details .block.partial { --state: var(--cp-partial); }
.cprof .details .block.error { --state: var(--cp-err);
  background: color-mix(in srgb, var(--cp-err) 12%, var(--cp-surface)); }
.cprof .item .name { flex: 1; word-break: break-all; }
.cprof .item .size { white-space: nowrap; }
.cprof .item .link { flex: none; width: 16px; text-align: center; color: inherit; opacity: .7;
  text-decoration: none; }
.cprof .item a.link:hover { opacity: 1; color: var(--cp-accent); }
.cprof .ok { color: var(--cp-ok); }
.cprof .todo { color: var(--cp-warn); }
.cprof .log { background: var(--comfy-input-bg); border: 1px solid var(--border-color);
  border-radius: 6px; padding: 6px; font-family: monospace; font-size: 11px; white-space: pre-wrap;
  word-break: break-all; max-height: 320px; min-height: 80px; overflow-y: auto; }
.cprof .workflow { border: 1px solid var(--border-color); border-left: 3px solid var(--cp-info);
  border-radius: var(--cp-radius); padding: 6px 8px; display: flex; flex-direction: column; gap: 4px;
  background: color-mix(in srgb, var(--cp-info) 7%, var(--cp-surface)); }
.cprof .workflow.none { border-left-color: var(--cp-warn);
  background: color-mix(in srgb, var(--cp-warn) 6%, var(--cp-surface)); }
.cprof .workflow.done { border-left-color: var(--cp-ok);
  background: color-mix(in srgb, var(--cp-ok) 7%, var(--cp-surface)); }
.cprof .need { display: flex; gap: 6px; align-items: center; font-size: 12px; }
.cprof .need .name { flex: 1; min-width: 0; font-family: monospace; word-break: break-all; cursor: pointer; }
.cprof .need .name:hover { text-decoration: underline; }
/* Dialog over the page (models of the workflow). */
.cprof-backdrop { position: fixed; inset: 0; z-index: 3000; background: rgb(0 0 0 / .55);
  display: flex; align-items: center; justify-content: center; padding: 16px; }
.cprof.cprof-dialog { height: auto; max-height: 85vh; width: min(860px, 100%);
  background: var(--comfy-menu-bg, #1e1e1e); border: 1px solid var(--border-color);
  border-radius: 10px; box-shadow: 0 12px 40px rgb(0 0 0 / .5); padding: 14px 16px; }
.cprof-dialog .body { display: flex; flex-direction: column; gap: 10px; min-height: 0; }
.cprof-dialog .fields { display: flex; flex-direction: column; gap: 6px; overflow-y: auto; }
.cprof-dialog .field-row { --state: var(--border-color); border: 1px solid var(--border-color);
  border-left: 3px solid var(--state); border-radius: 6px; padding: 6px 8px;
  display: flex; flex-direction: column; gap: 4px; background: var(--cp-surface); }
.cprof-dialog .field-row.ok { --state: var(--cp-ok); }
.cprof-dialog .field-row.other { --state: var(--cp-info); }
.cprof-dialog .field-row.missing { --state: var(--cp-err); }
.cprof-dialog .where { display: flex; gap: 8px; align-items: center; font-weight: 600; font-size: 12px; }
.cprof-dialog .where span:first-child { flex: 1; min-width: 0; overflow-wrap: anywhere; }
.cprof-dialog .tag { font-weight: normal; font-size: 11px; padding: 0 7px; border-radius: 999px;
  --tone: var(--descrip-text, #999); color: var(--tone); background: color-mix(in srgb, var(--tone) 14%, transparent); }
.cprof-dialog .tag.ok { --tone: var(--cp-ok); }
.cprof-dialog .tag.other { --tone: var(--cp-info); }
.cprof-dialog .tag.missing { --tone: var(--cp-err); }
.cprof-dialog .value { font-family: monospace; font-size: 12px; word-break: break-all; }
.cprof-dialog .field-row.missing .value { color: var(--cp-err); text-decoration: line-through; }
.cprof-dialog .choice { display: flex; gap: 6px; align-items: center; }
.cprof-dialog .providers { display: flex; flex-wrap: wrap; gap: 4px; align-items: center; font-size: 11px; }
.cprof-dialog .provider { font-size: 11px; padding: 1px 8px; border-radius: 999px; font-family: monospace; }
.cprof-dialog .provider i { font-size: 9px; }
.cprof-dialog .cover { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; padding: 8px 10px;
  border-radius: 8px; border: 1px solid color-mix(in srgb, var(--cp-info) 45%, transparent);
  background: color-mix(in srgb, var(--cp-info) 12%, var(--cp-surface)); font-size: 12px; }
.cprof-dialog .cover.ok { border-color: color-mix(in srgb, var(--cp-ok) 45%, transparent);
  background: color-mix(in srgb, var(--cp-ok) 12%, var(--cp-surface)); color: var(--cp-ok); }
.cprof-dialog .cover button i { font-size: 10px; }
.cprof-dialog span.provider.ok { color: var(--cp-ok); background: color-mix(in srgb, var(--cp-ok) 14%, transparent); }
.cprof-dialog select { flex: 1; min-width: 0; padding: 3px 5px; border-radius: 6px; font-family: monospace;
  font-size: 12px; border: 1px solid var(--border-color); background: var(--comfy-input-bg); color: var(--input-text); }
.cprof textarea { width: 100%; min-height: 400px; box-sizing: border-box; resize: vertical;
  font-family: monospace; font-size: 12px; background: var(--comfy-input-bg);
  color: var(--input-text, var(--fg-color)); border: 1px solid var(--border-color); border-radius: 6px; }
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
// A profile, optionally with variants between brackets: krea2-raw[int8,bf16].
const PROFILE_NAME = /^[\w.-]+(\[([\w.-]+(,[\w.-]+)*)?\])?$/;
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
    for (const name of splitRefs(value("profiles"))) {
      if (!needs.get(name)) needs.set(name, source);
    }
  }
  return [...needs].map(([name, source]) => ({ name, source, valid: PROFILE_NAME.test(name) }));
}

// Nodes of the open workflow, subgraphs included: all of them, and the "Workflow profiles" ones.
function workflowNodes() {
  const graph = app.rootGraph ?? app.graph;
  const all = graph ? [graph, ...(graph.subgraphs?.values?.() ?? [])].flatMap((g) => g.nodes ?? []) : [];
  return { all, declaring: all.filter((n) => n.type === WORKFLOW_NODE) };
}

// Room for a new node of `size` in the part of the canvas visible beside the panel, without
// overlapping the other nodes, as close as possible to its center: its position, or null.
function freeSpot(graph, size) {
  const canvas = app.canvas?.canvas;
  const ds = app.canvas?.ds;
  if (!canvas || !ds?.convertOffsetToCanvas) return null;
  const rect = canvas.getBoundingClientRect();
  // The sidebar panel can cover the left of the canvas; margins for the toolbars.
  const side = document.querySelector(".cprof")?.getBoundingClientRect();
  const left = side && side.right > rect.left && side.right < rect.right ? side.right : rect.left;
  const toGraph = (x, y) => ds.convertOffsetToCanvas([x - rect.left, y - rect.top]);
  const [x0, y0] = toGraph(left + 30, rect.top + 90);
  const [x1, y1] = toGraph(rect.right - 30, rect.bottom - 90);
  const title = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
  const margin = 30;
  const [w, h] = size;
  const boxes = (graph?.nodes ?? []).map((n) =>
    n.boundingRect ? [...n.boundingRect] : [n.pos[0], n.pos[1] - title, n.size[0], n.size[1] + title]);
  const fits = (x, y) => x >= x0 && x + w <= x1 && y - title >= y0 && y + h <= y1;
  const free = (x, y) => boxes.every(([bx, by, bw, bh]) =>
    x + w + margin <= bx || bx + bw + margin <= x || y + h + margin <= by || by + bh + margin <= y - title);
  // Square rings around the center, nearest first.
  const cx = (x0 + x1 - w) / 2, cy = (y0 + y1 - h + title) / 2;
  const step = 40 / (ds.scale || 1);
  const rings = Math.ceil(Math.max(x1 - x0, y1 - y0) / step / 2);
  for (let r = 0; r <= rings; r++) {
    for (let i = -r; i <= r; i++) {
      for (const [dx, dy] of [[i, -r], [i, r], [-r, i], [r, i]]) {
        const x = cx + dx * step, y = cy + dy * step;
        if (fits(x, y) && free(x, y)) return [x, y];
      }
    }
  }
  return null;
}

// Position just above all the nodes of the graph, at the left of them.
function aboveGraph(graph, size) {
  const nodes = graph?.nodes ?? [];
  if (!nodes.length) return [0, 0];
  const title = globalThis.LiteGraph?.NODE_TITLE_HEIGHT ?? 30;
  const minX = Math.min(...nodes.map((n) => n.pos[0]));
  const minY = Math.min(...nodes.map((n) => n.pos[1] - title));
  return [minX, minY - size[1] - 60];
}

// Profile references separated by commas, except those between brackets (variants).
function splitRefs(text) {
  return text.split(/,(?![^\[]*\])/).map((n) => n.replace(/\s+/g, "")).filter(Boolean);
}

// "krea2-raw[int8,bf16]" -> { name: "krea2-raw", variants: ["int8", "bf16"] }; variants: null
// without brackets.
function parseRef(ref) {
  const [, name, inner] = ref.match(/^([^[]*)(?:\[(.*)\])?$/);
  return { name, variants: inner === undefined ? null : inner.split(",").filter(Boolean) };
}

// Declared profile: its `list --json` entry, or null if it is not in the profiles file.
function declared(profiles, need) {
  const { name } = parseRef(need.name);
  return need.valid && Object.hasOwn(profiles, name) ? profiles[name] : null;
}

// State of a profile reference: that of the profile, or of the requested variants (installed
// if all of them are); without brackets, that of the profile named alone (common items and
// default variant). "unknown" for a variant the profile does not have.
function refState(p, ref) {
  if (!p.variants) return p.state;
  const { variants } = parseRef(ref);
  if (variants === null) return p.ref_state;
  const states = variants.map((v) => p.variants.find((pv) => pv.name === v)?.state ?? "unknown");
  if (states.includes("unknown")) return "unknown";
  if (states.every((s) => SATISFIED.has(s))) return "installed";
  return states.some((s) => s === "installed" || s === "partial") ? "partial" : "missing";
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
    const ps = p && refState(p, need.name);
    if (p && SATISFIED.has(ps)) return [];
    const state = !need.valid ? t("invalid name") : !p ? t("not in the profiles file")
      : ps === "unknown" ? t("unknown variant") : t(STATES[ps]?.label ?? STATES.missing.label);
    return [`${need.name} (${state.toLowerCase()})`];
  });
  const key = missing.join(", ");
  if (key && key !== lastAlert) {
    toast("warn", t("Profiles"),
      t("This workflow needs profiles: {names}. See the Profiles panel.", { names: key }), 10000);
  }
  lastAlert = key;
}

// --- Models of the workflow -----------------------------------------------------------------
// Dialog listing the model fields of the open workflow (loaders: unet_name, vae_name...),
// those pointing to a file that is not there, and for each one the files of the profiles that
// could replace it (another folder, another variant, another version), with the profiles
// providing them, to declare in the "Workflow profiles" node. Nothing changes until
// "Apply": one workflow then serves all the variants of a profile, and works whatever the
// subfolder its models are installed in.

const MODEL_FILE = /\.(safetensors|sft|ckpt|pt|pth|bin|gguf|onnx)$/i;
// Precision / quantization marks, removed to recognize the same model in another variant:
// flux3-image-klein-int8-convrot and flux3-image-klein-bf16 are the same model.
const PRECISION = /(^|[-_.])(int[48]|fp(4|8|16|32)(mixed)?|bf16|nvfp4|mxfp4|w4a8|w8a8|convrot|scaled|e4m3fn|e5m2|q\d(_k)?(_[sml])?|f16|f32)(?=$|[-_.])/gi;
// Version numbers (v2, v1.3, 2.1), removed to recognize another version of the same model.
const VERSION = /(^|[-_.])(v\d+(\.\d+)*|\d+(\.\d+)+)(?=$|[-_.])/gi;
// Folder of the files a field lists, from its name, for the files not installed yet (those
// installed are recognized in the field's list itself).
const FIELD_FOLDERS = { unet_name: "diffusion_models", ckpt_name: "checkpoints", vae_name: "vae",
  lora_name: "loras", control_net_name: "controlnet", style_model_name: "style_models",
  clip_vision_name: "clip_vision", upscale_model_name: "upscale_models" };
const FOLDER_ALIASES = { clip: "text_encoders", unet: "diffusion_models" };

const slashes = (path) => String(path).replace(/\\/g, "/");
const baseName = (path) => slashes(path).split("/").pop().toLowerCase();
const stripAll = (s, re) => { for (let prev = null; prev !== s;) [prev, s] = [s, s.replace(re, "")]; return s; };
const words = (s) => s.replace(/[-_.]+/g, "_").replace(/^_|_$/g, "");
// Model name without extension nor precision marks; loosely: nor version.
function stem(path) {
  return words(stripAll(baseName(path).replace(MODEL_FILE, ""), PRECISION));
}
function looseStem(path) {
  return words(stripAll(stripAll(baseName(path).replace(MODEL_FILE, ""), PRECISION), VERSION));
}
function fieldFolder(name) {
  return FIELD_FOLDERS[name] ?? (/^clip_name\d*$/.test(name) ? "text_encoders" : null);
}

// Model fields of the workflow, subgraphs included: [{node, widget, value, values, key}].
function modelFields() {
  const fields = [];
  for (const node of workflowNodes().all) {
    for (const widget of node.widgets ?? []) {
      // Field fed by a link (e.g. inside a subgraph, by the widget promoted on the subgraph
      // node): its own value is not used, the one to fix is upstream.
      if (node.inputs?.some((i) => i.widget?.name === widget.name && i.link != null)) continue;
      const values = widget.options?.values;
      if (widget.type !== "combo" || !Array.isArray(values) || typeof widget.value !== "string") continue;
      if (!MODEL_FILE.test(widget.value) && !values.some((v) => MODEL_FILE.test(String(v)))) continue;
      fields.push({ node, widget, value: widget.value, values: new Set(values.map(slashes)),
                    key: `${node.graph?.id ?? ""}:${node.id}:${widget.name}` });
    }
  }
  return fields;
}

// Models of all the profiles of the file: [{folder, rel, profile, variants}] (rel: name as a
// field lists it, subfolder included; variants: [] for an item common to all of them).
function profileFiles(profiles) {
  return Object.entries(profiles).flatMap(([profile, p]) => (p.models ?? []).map((m) => {
    const [folder, ...rest] = slashes(m.name).split("/");
    return { folder: FOLDER_ALIASES[folder] ?? folder, rel: rest.join("/"), profile, variants: m.variants };
  }));
}

// Files the profiles declared by the workflow install (rel), extends included.
async function declaredRels(profiles) {
  const refs = workflowNeeds().filter((need) => {
    const p = declared(profiles, need);
    return p && refState(p, need.name) !== "unknown";
  }).map((need) => need.name);
  if (!refs.length) return new Set();
  const items = await request("GET", `/status?profiles=${encodeURIComponent(refs.join(","))}`);
  return new Set(items.filter((i) => i.kind === "model").map((i) => slashes(i.name).split("/").slice(1).join("/")));
}

// Reference to declare `name` (the profile of a file or one including it) for the file. For a
// profile with variants, always with one: among those the file belongs to (all of them for a
// common file), the one already declared for this profile, otherwise one the workflow declares
// for another profile (krea2-turbo[int8] -> int8), otherwise the default one, otherwise the
// first one.
function fileRef(profiles, name, file) {
  const p = profiles[name];
  const own = (p?.variants ?? []).map((v) => v.name);
  const variants = file.variants.length ? file.variants.filter((v) => own.includes(v)) : own;
  if (!variants.length) return name;
  const declaredVariants = (ref) => {
    const { name: n, variants: vs } = parseRef(ref);
    return vs ?? (profiles[n]?.default_variant ? [profiles[n].default_variant] : []);
  };
  const needs = workflowNeeds().filter((n) => n.valid);
  const mine = needs.filter((n) => parseRef(n.name).name === name).flatMap((n) => declaredVariants(n.name));
  const others = needs.flatMap((n) => declaredVariants(n.name));
  const v = variants.find((x) => mine.includes(x)) ?? variants.find((x) => others.includes(x)) ??
    (variants.includes(p.default_variant) ? p.default_variant : variants[0]);
  return `${name}[${v}]`;
}

// Precision marks of a file name ("int8,convrot"), to prefer the same precision.
function precision(path) {
  return (baseName(path).replace(MODEL_FILE, "").match(PRECISION) ?? [])
    .map((m) => m.replace(/^[-_.]/, "")).sort().join(",");
}

// Score of a file for a field: 4 same file (in another folder), 3 same model in another
// variant, 2 another version, 1 similar name, 0 same kind of model only; + 0.5 for another
// version or a similar name in the same precision.
function matchScore(rel, value) {
  if (baseName(rel) === baseName(value)) return 4;
  if (stem(rel) === stem(value)) return 3;
  const bonus = precision(rel) === precision(value) ? 0.5 : 0;
  if (looseStem(rel) === looseStem(value)) return 2 + bonus;
  const a = new Set(looseStem(value).split("_"));
  const shared = looseStem(rel).split("_").filter((w) => a.has(w)).length;
  return shared / Math.max(a.size, 1) >= 0.5 ? 1 + bonus : 0;
}

// Profiles as a tree: files of each one, extends included (all variants), and the profiles
// including a given one (itself and those extending it, directly or not).
function profileTree(profiles) {
  const own = new Map(Object.entries(profiles).map(([name, p]) =>
    [name, new Set((p.models ?? []).map((m) => slashes(m.name).split("/").slice(1).join("/")))]));
  const parents = (name) => (profiles[name]?.extends ?? []).map((r) => parseRef(r).name).filter((n) => n in profiles);
  const memo = new Map();
  const files = (name, seen = new Set()) => {
    if (memo.has(name)) return memo.get(name);
    seen.add(name);
    const all = new Set(own.get(name));
    for (const parent of parents(name)) if (!seen.has(parent)) for (const f of files(parent, seen)) all.add(f);
    memo.set(name, all);
    return all;
  };
  const ancestors = (name, out = new Set()) => {
    for (const parent of parents(name)) if (!out.has(parent)) { out.add(parent); ancestors(parent, out); }
    return out;
  };
  const including = (owner) => Object.keys(profiles).filter((n) => n === owner || ancestors(n).has(owner));
  return { files, including };
}

// For a field: the files it can take, best first (one entry per file, with the profiles
// providing it).
function candidates(field, files, covered) {
  const value = slashes(field.value);
  // Folder of the field: from its name, otherwise that of a profile file it lists.
  const folder = fieldFolder(field.widget.name) ?? files.find((f) => field.values.has(f.rel))?.folder;
  const byRel = new Map();
  for (const f of files) {
    const score = matchScore(f.rel, value);
    if (!(field.values.has(f.rel) || (folder && folder === f.folder) || score >= 2)) continue;
    const entry = byRel.get(f.rel) ?? { rel: f.rel, score, installed: field.values.has(f.rel),
                                        declared: covered.has(f.rel), providers: [] };
    entry.providers.push(f);
    byRel.set(f.rel, entry);
  }
  return [...byRel.values()].sort((a, b) => b.score - a.score || b.declared - a.declared ||
    b.installed - a.installed || a.rel.localeCompare(b.rel));
}

// The separator of the field's own list (backslash on Windows).
function asListed(field, rel) {
  const windows = [...field.widget.options.values].some((v) => String(v).includes("\\"));
  return windows ? rel.replace(/\//g, "\\") : rel;
}

// Adds a profile reference to the workflow's "Workflow profiles" node (merging the variants
// of a profile already declared), or creates the node.
function declareProfile(profiles, ref) {
  const node = workflowNodes().declaring[0];
  if (!node) return addWorkflowNode([ref]);
  const widget = node.widgets?.find((w) => w.name === "profiles");
  if (!widget) return null;
  const { name, variants } = parseRef(ref);
  const refs = splitRefs(String(widget.value ?? ""));
  const i = refs.findIndex((r) => parseRef(r).name === name);
  if (i < 0) refs.push(ref);
  else {
    const p = profiles[name];
    const old = parseRef(refs[i]).variants ?? (p?.default_variant ? [p.default_variant] : []);
    const merged = [...new Set([...old, ...(variants ?? [])])];
    refs[i] = variants ? `${name}[${merged.join(",")}]` : refs[i];
  }
  const old = widget.value;
  widget.value = refs.join(", ");
  widget.callback?.(widget.value, app.canvas, node);
  node.onWidgetChanged?.(widget.name, widget.value, old, widget);
  node.setDirtyCanvas?.(true, true);
  app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
  return node;
}

// Adds a "Workflow profiles" node declaring `refs`, where it is visible without overlapping
// other nodes.
function addWorkflowNode(refs) {
  const node = globalThis.LiteGraph?.createNode(WORKFLOW_NODE);
  if (!node) {
    toast("error", t("Profiles"), t("“Workflow profiles” node unavailable: restart ComfyUI."));
    return null;
  }
  const graph = app.canvas?.graph ?? app.graph;
  const spot = freeSpot(graph, node.size);
  node.pos = spot ?? aboveGraph(graph, node.size);
  graph.add(node);
  // Outside the visible part (no free room there): the view goes to it.
  if (!spot) app.canvas?.centerOnNode?.(node);
  const widget = node.widgets?.find((w) => w.name === "profiles");
  if (widget && refs.length) widget.value = refs.join(", ");
  app.canvas?.selectNode?.(node);
  graph.setDirtyCanvas?.(true, true);
  app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
  return node;
}

// ComfyUI's list of missing models (red frame of the nodes, errors tab), checked again against
// the files present. reloadDefs: also reload the model lists from the server.
async function refreshMissingModels(reloadDefs) {
  try {
    await app.refreshMissingModels?.({ silent: true, reloadDefs });
  } catch (e) {
    console.warn("[comfy-profiles]", e);
  }
}

async function refreshModelLists() {
  await app.refreshComboInNodes?.();
  await refreshMissingModels(false);
}

let modelDialog = null;

async function openModelDialog() {
  modelDialog?.remove();
  const close = () => { modelDialog?.remove(); modelDialog = null; document.removeEventListener("keydown", onKey); };
  const onKey = (e) => { if (e.key === "Escape") close(); };
  const body = el("div", { class: "body" }, el("div", { class: "muted" }, t("Loading…")));
  const box = el("div", { class: "cprof cprof-dialog", role: "dialog", "aria-modal": "true" },
    el("div", { class: "head" },
      el("h3", { style: "flex:1" }, t("Models of the workflow")),
      iconButton("pi-times", t("Close"), false, close)),
    body);
  modelDialog = el("div", { class: "cprof-backdrop", onmousedown: (e) => { if (e.target === modelDialog) close(); } }, box);
  document.body.append(modelDialog);
  document.addEventListener("keydown", onKey);
  // Choice of each field (rel, null: keep), kept when the dialog is redrawn.
  const choices = new Map();

  const render = async () => {
    let profiles, fields, files, covered;
    try {
      profiles = panel?.data?.profiles ?? (await request("GET", "/profiles")).profiles;
      fields = modelFields();
      files = profileFiles(profiles);
      covered = await declaredRels(profiles);
    } catch (e) {
      body.replaceChildren(el("div", { class: "error" }, e.message));
      return;
    }
    if (!fields.length) {
      body.replaceChildren(el("div", { class: "muted" }, t("This workflow has no model field.")));
      return;
    }
    const tree = profileTree(profiles);
    const rows = fields.map((field) => {
      const value = slashes(field.value);
      const present = field.values.has(value);
      const options = candidates(field, files, covered);
      const state = !present ? "missing" : covered.has(value) ? "ok" : "other";
      return { ...field, value, state, options };
    });
    // File each field would point to: the chosen one, otherwise the current one if present.
    const target = (r) => choices.get(r.key) ?? (r.values.has(r.value) ? r.value : null);
    // Profiles that can provide a file: those declaring it and those including them; the
    // best ones provide the most files of the workflow (then: the fewest files in all).
    const coverage = new Map();
    const covering = (name) => {
      if (!coverage.has(name)) {
        const all = tree.files(name);
        coverage.set(name, rows.filter((r) => all.has(target(r) ?? (r.options[0]?.rel ?? ""))).length);
      }
      return coverage.get(name);
    };
    const providers = (entry) => {
      const names = [...new Set(entry.providers.flatMap((f) => tree.including(f.profile)))];
      return names.sort((a, b) => covering(b) - covering(a) || tree.files(a).size - tree.files(b).size);
    };
    // Options ranked: good matches (same file, same model or another version) first, among
    // them those of the declared profiles first (declaring krea2-turbo[bf16] turns an int8
    // field to its bf16 file); then score, installed, and how many fields of the workflow
    // their best profile provides. Proposed only when clear: a good match ranked first on its
    // own.
    const key = (o) => [+(o.score >= 2), +o.declared, o.score, +o.installed, covering(providers(o)[0])];
    const compare = (x, y) => {
      const [a, b] = [key(x), key(y)];
      const i = a.findIndex((v, j) => v !== b[j]);
      return i < 0 ? 0 : b[i] - a[i];
    };
    for (const r of rows) {
      r.options.sort(compare);
      if (choices.has(r.key)) continue;
      const [first, second] = r.options;
      const clear = r.state !== "ok" && first?.score >= 2 && (!second || compare(first, second) < 0);
      choices.set(r.key, clear && first.rel !== r.value ? first.rel : null);
    }
    const labels = { ok: t("from the declared profiles"), other: t("present, not from the declared profiles"),
                     missing: t("file not found") };
    const kinds = { 4: t("same file"), 3: t("other variant"), 2: t("other version") };
    const option = (o, r) => el("option", { value: o.rel, selected: o.rel === choices.get(r.key) },
      o.rel + (kinds[o.score] ? ` · ${kinds[o.score]}` : "") + (o.installed ? "" : ` · ${t("not installed")}`));
    const table = el("div", { class: "fields" }, rows.map((r) => {
      const ofDeclared = r.options.filter((o) => o.declared);
      const others = r.options.filter((o) => !o.declared);
      const select = el("select", {
        onchange: (e) => { choices.set(r.key, e.target.value || null); render(); },
      },
        el("option", { value: "" }, t("Keep")),
        ofDeclared.length > 0 && el("optgroup", { label: t("Declared profiles") }, ofDeclared.map((o) => option(o, r))),
        others.length > 0 && el("optgroup", { label: t("Other profiles") }, others.map((o) => option(o, r))));
      // Profiles providing the chosen file (or the current one): to declare in the node.
      const shown = slashes(choices.get(r.key) ?? r.value);
      const entry = r.options.find((o) => o.rel === shown);
      // Already provided by a declared profile: that one; otherwise up to 3 profiles, those
      // providing the most files of the workflow first.
      const names = entry ? providers(entry) : [];
      const declaredNames = workflowNeeds().map((n) => n.name)
        .filter((ref) => names.includes(parseRef(ref).name) && tree.files(parseRef(ref).name).has(entry.rel));
      const refs = entry?.declared && declaredNames.length ? declaredNames
        : [...new Set(names.slice(0, 3).map((name) =>
            fileRef(profiles, name, entry.providers.find((f) => tree.including(f.profile).includes(name)))))];
      return el("div", { class: `field-row ${r.state}` },
        el("div", { class: "where" },
          el("span", {}, `${r.node.title || r.node.type} › ${r.widget.label || r.widget.name}`),
          el("span", { class: `tag ${r.state}` }, labels[r.state])),
        el("div", { class: "value" }, r.value),
        r.options.length ? el("div", { class: "choice" }, el("span", { class: "muted" }, "→"), select)
          : r.state !== "ok" && el("div", { class: "muted" }, t("No file of the profiles fits.")),
        refs.length > 0 && el("div", { class: "providers" },
          el("span", { class: "muted" }, t("Provided by:")),
          refs.map((ref) => entry.declared
            ? el("span", { class: "provider ok", title: t("Already declared by the workflow") }, `✓ ${ref}`)
            : el("button", {
                class: "provider", title: t("Add {name} to the “Workflow profiles” node", { name: ref }),
                onclick: async () => { declareProfile(profiles, ref); panel?.render(); await render(); },
              }, el("i", { class: "pi pi-plus" }), ` ${ref}`))));
    }));
    const changes = rows.filter((r) => choices.get(r.key) && choices.get(r.key) !== slashes(r.value));

    // Every field pointing (once applied) to a file of a profile: the fewest profiles providing
    // them all, to declare at once from the header.
    const targets = rows.map(target);
    const allMatched = targets.every((rel) => rel && files.some((f) => f.rel === rel));
    let cover = null;
    if (allMatched) {
      let remaining = new Set(targets.filter((rel) => !covered.has(rel)));
      const names = [...new Set(files.filter((f) => remaining.has(f.rel))
        .flatMap((f) => tree.including(f.profile)))];
      const picked = [];
      while (remaining.size) {
        const gain = (n) => [...remaining].filter((rel) => tree.files(n).has(rel)).length;
        const best = names.reduce((a, b) => !a || gain(b) > gain(a) ||
          (gain(b) === gain(a) && tree.files(b).size < tree.files(a).size) ? b : a, null);
        if (!best || !gain(best)) break;
        // Variants: those of the files it provides (one reference per profile).
        const provided = [...remaining].filter((rel) => tree.files(best).has(rel));
        const variants = new Set(provided.flatMap((rel) => {
          const file = files.find((f) => f.rel === rel && tree.including(f.profile).includes(best));
          return file?.variants.length ? [parseRef(fileRef(profiles, best, file)).variants?.[0]] : [];
        }).filter(Boolean));
        const any = files.find((f) => tree.including(f.profile).includes(best) && provided.includes(f.rel));
        picked.push(variants.size ? `${best}[${[...variants].join(",")}]` : fileRef(profiles, best, any));
        remaining = new Set([...remaining].filter((rel) => !tree.files(best).has(rel)));
      }
      cover = remaining.size ? null : picked;
    }
    const banner = !allMatched ? null
      : cover && !cover.length
        ? el("div", { class: "cover ok" }, `✓ ${t("All the models of the workflow are provided by its declared profiles.")}`)
        : cover && el("div", { class: "cover" },
            el("span", { style: "flex:1" }, t("All the models of the workflow are provided by: {names}",
              { names: cover.join(", ") })),
            el("button", { class: "primary", onclick: async () => {
              for (const ref of cover) declareProfile(profiles, ref);
              panel?.render();
              await render();
            } }, el("i", { class: "pi pi-plus" }), ` ${t("Declare in the workflow")}`));
    const pending = changes.filter((r) => !r.values.has(choices.get(r.key))).length;
    const undeclared = changes.filter((r) => !covered.has(choices.get(r.key))).length;
    const apply = el("button", { class: "primary", disabled: !changes.length, onclick: async () => {
      for (const r of changes) {
        const old = r.widget.value;
        r.widget.value = asListed(r, choices.get(r.key));
        r.widget.callback?.(r.widget.value, app.canvas, r.node);
        // As a change by hand: ComfyUI clears the error of the field (red frame of the node).
        r.node.onWidgetChanged?.(r.widget.name, r.widget.value, old, r.widget);
      }
      app.graph?.setDirtyCanvas?.(true, true);
      app.extensionManager?.workflow?.activeWorkflow?.changeTracker?.checkState?.();
      toast("success", t("Profiles"), t("{n} model field(s) updated.", { n: changes.length }));
      close();
      // Missing models checked again: only the fields whose file is still not installed stay
      // flagged.
      await refreshMissingModels(false);
    } }, t("Apply ({n})", { n: changes.length }));
    body.replaceChildren(...[
      banner,
      el("div", { class: "muted" }, t("Files taken from all the profiles of your file, best match first; only the clear ones are preselected. “+ profile” declares it in the workflow's “Workflow profiles” node. Nothing changes in the fields before “Apply” (Ctrl+Z undoes it).")),
      table,
      undeclared > 0 && el("div", { class: "warn" },
        t("{n} chosen file(s) from profiles the workflow does not declare yet: add them with “+”.", { n: undeclared })),
      pending > 0 && el("div", { class: "warn" },
        t("{n} chosen file(s) not installed yet: install the workflow's profiles.", { n: pending })),
      // Profiles are declared in the node right away (“+”): with no field to change, the
      // dialog is only closed.
      changes.length
        ? el("div", { class: "bar" }, apply, el("button", { onclick: close }, t("Cancel")))
        : el("div", { class: "bar" },
            el("button", { class: "primary", onclick: close }, t("Close")),
            el("span", { class: "muted" }, t("No model field to change."))),
    ].filter(Boolean));
  };
  await render();
}

class ProfilesPanel {
  constructor() {
    this.root = el("div", { class: "cprof" });
    this.data = null;          // result of `list --json`
    this.selected = new Set();
    // Profile with variants -> variants ticked on its card (default: its default_variant).
    this.variants = new Map();
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
    if (sync.running) {
      this.selected = new Set(sync.profiles.map((ref) => parseRef(ref).name));
      for (const ref of sync.profiles) {
        const { name, variants } = parseRef(ref);
        if (variants) this.variants.set(name, new Set(variants));
      }
    }
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
    // Done: the profiles it applied to are unticked (card and variants), so that nothing stays
    // ticked for an action already made (an uninstalled variant would show as to install).
    if (returncode === 0 && !dryRun && (action === "sync" || action === "uninstall")) {
      for (const ref of this.sync.profiles ?? []) {
        const { name } = parseRef(ref);
        this.selected.delete(name);
        this.variants.delete(name);
      }
    }
    // Models added or removed: node lists, and the nodes flagged for a missing model, updated
    // right away.
    if (!dryRun && action !== "sizes") refreshModelLists();
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
      // All the variants of the profile, grouped by variant.
      const ref = this.data?.profiles[name] ? allVariants(name, this.data.profiles[name]) : name;
      this.expanded.set(name, await request("GET", `/status?profiles=${encodeURIComponent(ref)}`));
    } catch (e) {
      this.expanded.set(name, { error: e.message });
    }
    if (this.expanded.has(name)) this.render();
  }

  // Variants ticked on the card of a profile with variants: none until clicked (its actions
  // then stay inactive).
  chosen(name) {
    return this.variants.get(name) ?? new Set();
  }

  // Profile with variants none of which is ticked: nothing for its actions to apply to.
  unticked(name) {
    return Boolean(this.data?.profiles[name]?.variants) && !this.chosen(name).size;
  }

  // What the actions on a profile apply to: name[ticked variants] for a profile with variants
  // (name[]: its common items only), otherwise its name.
  ref(name) {
    const p = this.data?.profiles[name];
    if (!p?.variants) return name;
    const chosen = this.chosen(name);
    return `${name}[${p.variants.map((v) => v.name).filter((v) => chosen.has(v)).join(",")}]`;
  }

  // force: for "sizes", also queries again the files whose size is known; for "sync", also
  // updates what changed at the source.
  async startSync(dryRun, action = "sync", profiles = [...this.selected].map((n) => this.ref(n)),
                  withExtends = false, force = false) {
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
  async prepareUninstall(profiles = [...this.selected].map((n) => this.ref(n)), withExtends = false) {
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
      const { adopted } = await request("POST", "/adopt",
        { profiles: [allVariants(name, this.data.profiles[name])] });
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
    // this.grouped, a profile extended only by grouping profiles (e.g. minimax-h3-all) also
    // counts as final. A selected profile stays shown, so as not to act on an invisible
    // selection.
    const parents = new Set(Object.values(this.data.profiles)
      .filter((p) => !(this.grouped && isGroup(p))).flatMap((p) => p.extends.map((r) => parseRef(r).name)));
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
      const label = t((STATES[p.state] || STATES.missing).label);
      // Actions of the card: on the ticked variants for a profile with variants.
      const ref = this.ref(name);
      const state = STATES[p.variants ? actionState(p, this.chosen(name)) : p.state] || STATES.missing;
      const untickedHint = t("Tick the variants the card's actions apply to");
      const none = this.unticked(name);
      // Size: per variant, on its chip, for a profile with variants.
      const size = !p.variants && profileSize(p);
      const todo = !p.variants && todoSize(p);
      const startup = this.data.default.filter((r) => parseRef(r).name === name);
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
              none ? untickedHint
                : state.install ? t("Install {name} (what is missing)", { name: ref }) : `${ref} : ${t(state.label).toLowerCase()}`,
              locked || none || !state.install, () => this.startSync(false, "sync", [ref])),
            iconButton("pi-trash",
              none ? untickedHint
                : state.uninstall ? t("Uninstall {name}…", { name: ref }) : `${ref} : ${t(state.label).toLowerCase()}`,
              locked || none || !state.uninstall, () => this.prepareUninstall([ref])),
            iconButton(this.expanded.has(name) ? "pi-chevron-down" : "pi-chevron-right",
              this.expanded.has(name) ? t("Hide details") : t("Show what is installed"),
              false, () => this.expand(name)))),
        // Chips under the name: on the same line, they would squash it in the sidebar.
        p.variants && this.renderVariants(name, p, running),
        (startup.length || size || todo || p.unmanaged > 0) && el("div", { class: "chips" },
          startup.length > 0 &&
            el("span", { class: "chip default", title: t("In COMFY_PROFILES: synced at every startup") +
                (p.variants ? ` (${startup.join(", ")})` : "") },
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

    const selection = [...this.selected].map((n) => this.ref(n));
    const unticked = [...this.selected].filter((n) => this.unticked(n));
    const blocked = !selection.length || unticked.length > 0;
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
            "that only combines other profiles, e.g. minimax-h3-all)")),
        hidden > 0 && el("span", { class: "muted" }, t("({n} hidden)", { n: hidden }))),
      el("div", { class: "list" }, profiles),
      el("div", { class: "bar" },
        el("button", { class: "primary", disabled: locked || blocked,
                       onclick: () => this.startSync(false) },
          selection.length ? t("Sync ({n})", { n: selection.length }) : t("Sync")),
        el("button", { disabled: running || blocked, onclick: () => this.startSync(true) }, "Dry-run"),
        el("button", {
          disabled: locked || blocked, onclick: () => this.startSync(false, "sync", selection, false, true),
          title: t("Installs what is missing and updates what the manager installed or took " +
                   "over, if it changed at the source (custom nodes, models, workflows, pip " +
                   "packages)"),
        }, selection.length ? t("Update ({n})", { n: selection.length }) : t("Update")),
        el("button", { disabled: locked || blocked, onclick: () => this.prepareUninstall() },
          t("Uninstall…")),
        running && el("button", { class: "danger", disabled: this.sync.stopping, onclick: () => this.stop() },
          this.sync.stopping ? t("Stopping…") : t("Stop"))),
      unticked.length > 0 && el("div", { class: "warn" },
        t("Tick at least one variant of: {names}", { names: unticked.join(", ") })),
      el("div", { class: "muted" },
        t("New models: visible right away. New custom nodes: restart ComfyUI.")),
      status && el("div", { class: this.sync.returncode ? "error" : "muted" }, status),
      this.logBox,
    );
  }

  // Variants of a profile: a chip each (state, size), ticked for the card's actions.
  renderVariants(name, p, running) {
    const chosen = this.chosen(name);
    return el("div", { class: "chips" },
      p.variants.map((v) => {
        const isDefault = v.name === p.default_variant;
        const state = t((STATES[v.state] || STATES.missing).label);
        const todo = todoSize(v);
        const picked = chosen.has(v.name);
        // Ticked but not (fully) installed: what the card's sync will install.
        const pending = picked && !SATISFIED.has(v.state);
        return el("label", {
          class: `chip variant ${v.state}${picked ? " chosen" : ""}${pending ? " pending" : ""}`,
          title: [`${name}[${v.name}] : ${state.toLowerCase()}`, isDefault && t("Default variant"),
                  todo, pending ? t("Ticked: installed by the card's sync")
                    : picked ? t("Ticked: already installed")
                    : t("Tick the variants the card's actions apply to")].filter(Boolean).join("\n"),
        },
          el("input", {
            type: "checkbox", checked: chosen.has(v.name), disabled: running,
            onchange: (e) => {
              const next = new Set(chosen);
              e.target.checked ? next.add(v.name) : next.delete(v.name);
              this.variants.set(name, next);
              this.render();
            },
          }),
          `${v.name}${isDefault ? " ★" : ""} · ${profileSize(v) || "?"}`,
          pending && el("i", { class: "pick pi pi-download" }));
      }));
  }

  // Profiles declared by the open workflow ("Workflow profiles" node): state, install, and
  // adding those missing from the profiles file from the declared source.
  renderWorkflow(locked) {
    const needs = workflowNeeds();
    if (!needs.length) return this.renderNoDeclaration();
    const profiles = this.data.profiles;
    // State of each declared profile (of its requested variants), null if not in the file.
    const stateOf = (need) => {
      const p = declared(profiles, need);
      return p && refState(p, need.name);
    };
    const toInstall = needs.filter((n) => {
      const s = stateOf(n);
      return s && !SATISFIED.has(s) && STATES[s]?.install;
    }).map((n) => n.name);
    const done = needs.every((n) => SATISFIED.has(stateOf(n)));
    const rows = needs.map((need) => {
      const p = declared(profiles, need);
      const ps = stateOf(need);
      const state = p && (STATES[ps] || STATES.missing);
      const status = !need.valid ? el("span", { class: "error" }, t("invalid name"))
        : !p ? el("span", { class: "warn" }, t("not in the profiles file"))
        : ps === "unknown" ? el("span", { class: "error" }, t("unknown variant"))
        : el("span", { class: SATISFIED.has(ps) ? "ok" : "todo" }, t(state.label));
      return el("div", { class: "need" },
        el("span", { class: SATISFIED.has(ps) ? "ok" : "todo" }, SATISFIED.has(ps) ? "✓" : "✗"),
        el("span", {
          class: "name", title: t("Show this profile in the list"),
          onclick: () => { this.search.value = parseRef(need.name).name; this.render(); },
        }, need.name),
        status,
        el("div", { class: "actions" },
          p && ps !== "unknown" && state.install && !SATISFIED.has(ps) && iconButton("pi-download",
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
        el("span", { class: "muted", style: "flex:1" }, t("profiles declared by its “Workflow profiles” node")),
        iconButton("pi-sliders-h", t("Check the workflow's models…"), false, () => openModelDialog())),
      rows,
      done ? el("div", { class: "ok" }, t("All the profiles of this workflow are installed."))
        : toInstall.length > 1 && el("div", { class: "bar" },
          el("button", { class: "primary", disabled: locked, onclick: () => this.startSync(false, "sync", toInstall) },
            t("Install the workflow's profiles ({n})", { n: toInstall.length }))));
  }

  // Open workflow without declared profiles: says so, and offers to add a "Workflow profiles"
  // node (filled with the ticked profiles, if any).
  renderNoDeclaration() {
    const nodes = workflowNodes();
    if (!nodes.all.length) return null;  // empty graph
    const present = nodes.declaring.length > 0;
    const refs = [...this.selected].map((name) => this.ref(name));
    return el("div", { class: "workflow none" },
      el("div", { class: "bar" },
        el("strong", {}, t("This workflow")),
        el("span", { class: "muted", style: "flex:1" }, present
          ? t("its “Workflow profiles” node declares no profile yet")
          : t("declares no profile: no “Workflow profiles” node")),
        !present && iconButton("pi-plus", refs.length
          ? t("Add a “Workflow profiles” node declaring the ticked profiles ({names})", { names: refs.join(", ") })
          : t("Add a “Workflow profiles” node (tick profiles first to fill it in)"),
          false, () => this.addWorkflowNode(refs)),
        iconButton("pi-sliders-h", t("Check the workflow's models…"), false, () => openModelDialog())),
      el("div", { class: "muted" }, t("Declaring its profiles lets whoever opens the workflow install what it needs.")));
  }

  addWorkflowNode(refs) {
    addWorkflowNode(refs);
    this.render();
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
      groups.map((group) => {
        const { variants } = parseRef(group.profile);
        const content = [
          titled && el("div", { class: "group" },
            group.inherited ? t("Inherited from {name}", { name: group.profile })
              : variants ? t("Variant {name}", { name: variants.join(", ") })
              : groups.some((g) => parseRef(g.profile).variants) ? t("Common to all variants") : t("Profile's own"),
            el("span", { class: "muted" }, ` · ${group.items.filter((i) => !i.missing).length}/${group.items.length}`)),
          group.items.map((item) => this.renderItem(item)),
        ];
        // Items of a variant, common to the variants, or of an inherited profile: in a block
        // colored by its own state, that of the profile declaring them.
        const owner = this.data?.profiles[parseRef(group.profile).name];
        const state = !owner ? null
          : variants && owner.variants ? actionState(owner, new Set(variants))
          // Common items of a profile with variants (this one or an inherited one).
          : owner.variants ? owner.common_state
          // Inherited profile without variants; the profile's own items are the card itself.
          : group.inherited ? owner.state : null;
        return state ? el("div", { class: `block ${state}` }, content) : content;
      }));
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
    const a = el("a", {
      class: "link", href: link.url, target: "_blank", rel: "noopener noreferrer",
      title: `${t(site.label)} : ${link.url}`,
    }, site.svg ? null : site.text ?? el("i", { class: site.icon }));
    if (site.svg) a.innerHTML = site.svg;  // constant markup, see LINK_SITES
    return a;
  }
}

// Link to the source of an item: PrimeIcons icon, or text when there is none.
const LINK_SITES = {
  hf: { label: "Hugging Face", text: "🤗" },
  github: { label: "GitHub", icon: "pi pi-github" },
  // No CivitAI icon in PrimeIcons: its hexagon logo, drawn inline.
  civitai: {
    label: "CivitAI",
    svg: '<svg viewBox="0 0 24 24" width="13" height="13" style="vertical-align:-2px">' +
      '<path d="M12 1.5 21.1 6.75v10.5L12 22.5 2.9 17.25V6.75z" fill="none" stroke="#3b82f6" stroke-width="2.2" stroke-linejoin="round"/>' +
      '<path d="M15.6 9.2A4.2 4.2 0 1 0 15.6 14.8" fill="none" stroke="#3b82f6" stroke-width="2.4" stroke-linecap="round"/></svg>',
  },
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

// The profile with all its variants (details, take over).
function allVariants(name, p) {
  return p.variants ? `${name}[${p.variants.map((v) => v.name).join(",")}]` : name;
}

// State the card's actions follow, for the variants ticked on a profile with variants: that of
// its common items when none is ticked.
function actionState(p, chosen) {
  const states = p.variants.filter((v) => chosen.has(v.name)).map((v) => v.state);
  if (!states.length) return p.common_state;
  if (states.every((s) => s === "installed")) return "installed";
  if (states.some((s) => s === "installed" || s === "partial")) return "partial";
  return states.every((s) => s === "error") ? "error" : "missing";
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
  // "Workflow profiles" node: button opening the models dialog. Not saved with the workflow,
  // nor sent with the prompt.
  nodeCreated(node) {
    if (node.comfyClass !== WORKFLOW_NODE) return;
    const button = node.addWidget("button", t("Check the workflow's models…"), null, () => openModelDialog());
    button.serialize = false;
    button.options = { ...button.options, serialize: false };
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
