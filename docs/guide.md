# comfyui-profiles: user guide

This guide walks you through comfyui-profiles step by step: install it, write your first
profiles, use them from the **Profiles** panel or from the command line, and set up the
tokens it needs. The [README](../README.md) is the complete reference. Come back to it for
details.

- [1. The idea in two minutes](#1-the-idea-in-two-minutes)
- [2. Installation](#2-installation)
- [3. First steps in the panel](#3-first-steps-in-the-panel)
- [4. Writing your profiles](#4-writing-your-profiles)
- [5. Variants (int8, fp8, bf16...)](#5-variants-int8-fp8-bf16)
- [6. The panel in detail](#6-the-panel-in-detail)
- [7. Sharing a workflow with its profiles](#7-sharing-a-workflow-with-its-profiles)
- [8. Secrets: tokens and passwords](#8-secrets-tokens-and-passwords)
- [9. Command line](#9-command-line)
- [10. Docker and cloud pods](#10-docker-and-cloud-pods)
- [11. Troubleshooting](#11-troubleshooting)

## 1. The idea in two minutes

A ComfyUI workflow rarely works on its own. It needs a diffusion model, a text encoder, a
VAE, a few LoRAs, two or three custom nodes, sometimes a pip package. All of them must be
found, downloaded and put in the right folder.

A **profile** writes this list down once, in a `profiles.json` file:

```json
"krea2-turbo": {
  "description": "Krea 2 Turbo (text to image, 8 steps).",
  "extends": ["krea2-common"],
  "models": [
    {"type": "diffusion_models/krea2", "hf": "Comfy-Org/Krea-2", "file": "diffusion_models/krea2_turbo_int8_convrot.safetensors"}
  ]
}
```

comfyui-profiles then does the rest:

- **install** what a profile needs, skipping what is already there (`sync`);
- **show** what is installed, partially installed or missing;
- **uninstall** a profile without breaking the others (shared files are kept);
- **update** what changed at the source.

You can do all of this from the **Profiles** tab of ComfyUI or from the command line, for
instance at container startup.

![The Profiles panel](images/panel-overview.png)

## 2. Installation

From ComfyUI-Manager: search for **comfyui-profiles**. Or by hand:

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/jdelahayes/comfyui-profiles.git
```

Then restart ComfyUI. Two things appear:

- the **Profiles** tab in the left sidebar (box icon);
- the **Workflow profiles** node, in the *utils* category (see
  [section 7](#7-sharing-a-workflow-with-its-profiles)).

Its only dependency is `huggingface_hub`, which ComfyUI already uses. `pyzipper` is installed
on demand, the first time an encrypted Google Drive zip is extracted.

## 3. First steps in the panel

On first launch, the panel shows the profiles of the **template**:
`examples/profiles.example.json`. Its profiles install for real and show every feature of the
format (all the sources, variants, `extends`, comments): a good starting point for your own
file. To install one of them:

1. Open the **Profiles** tab.
2. Tick the profile, for instance `taesd-previews`.
3. Click **Dry-run**: the log shows what would be downloaded, and where, without doing it.
4. Click **Sync**: the files are downloaded, with live progress in the log.
5. The card turns green: the profile is installed.

![Dry-run of two profiles](images/panel-dryrun.png)

New **models** are visible in ComfyUI right away (refresh the node lists with `R` if needed).
New **custom nodes** only load after a restart: click **Restart ComfyUI**.

Color code of the cards:

| Color | Meaning |
|---|---|
| green | installed: everything is there, inherited profiles included |
| yellow | partially installed: some of the profile's own items are missing |
| neutral | not installed |
| orange dashed *N not managed* chip | items already present but not installed by comfyui-profiles (copied by hand, ComfyUI-Manager...): uninstalling leaves them in place |

Under the card, a blue *… to download* chip gives the size still to download, and a
*startup* chip marks the profiles synced at every startup (`COMFY_PROFILES`, see
[section 10](#10-docker-and-cloud-pods)).

## 4. Writing your profiles

### Where the file lives

As long as you have not changed anything, the panel uses the read-only template. The first
change (**Edit**, **Import…**, **From a URL…**, **Recalculate sizes**) creates **your file**:

```
ComfyUI/user/__comfy_profiles/profiles.json
```

From then on, this file is the one used. **Back to template** sets it aside
(`profiles.json.bak`) and goes back to the template.

![Editing the profiles file in the panel](images/panel-editor.png)

Editing in the panel is handy for a quick fix. For more work, edit the file in a code editor:
the `$schema` line gives validation and completion in VS Code. Then import it with
**Import…**, or put it straight in `user/__comfy_profiles/` and click **Reload**. A file kept in
a Git repository can be loaded with **From a URL…** (raw GitHub or gist link). The panel
remembers the last URLs imported: after a push, **Sync** next to the URL shows what changed,
profile by profile, and you choose: **Merge** the ticked profiles into your file, or
**Replace all**.

### A first profile, step by step

Let's write a profile for a text-to-image setup that needs a custom node, a diffusion model,
a text encoder, a VAE and a LoRA from CivitAI.

**1. The skeleton.** Each profile is a key under `profiles`:

```json
{
  "$schema": "https://raw.githubusercontent.com/jdelahayes/comfyui-profiles/main/profiles.schema.json",
  "profiles": {
    "my-txt2img": {
      "description": "My text to image setup."
    }
  }
}
```

**2. Custom nodes**, from their Git repository:

```json
"custom_nodes": [
  {"git": "https://github.com/rgthree/rgthree-comfy.git"},
  {"git": "https://github.com/kijai/ComfyUI-KJNodes.git", "ref": "main"}
]
```

`ref` (optional) pins a branch, a tag or a commit. The node's `requirements.txt` is installed
in ComfyUI's Python environment.

**3. Models.** `type` is the subfolder of `ComfyUI/models` where the file goes
(`checkpoints`, `loras`, `vae`, `diffusion_models`, `text_encoders`...). A subfolder can be
added (`loras/styles`). Then exactly one source:

```json
"models": [
  {"type": "diffusion_models", "hf": "Comfy-Org/Krea-2", "file": "diffusion_models/krea2_turbo_int8_convrot.safetensors"},
  {"type": "text_encoders", "hf": "Comfy-Org/Krea-2", "file": "text_encoders/qwen3vl_4b_int8_convrot.safetensors"},
  {"type": "vae", "hf": "Comfy-Org/Krea-2", "file": "vae/qwen_image_vae.safetensors"},
  {"type": "loras", "civitai": 123456, "name": "my_style_lora.safetensors"}
]
```

| Source | Keys | Example |
|---|---|---|
| Hugging Face | `hf` (repository), `file` (path in the repository), optional `revision` | `{"hf": "Comfy-Org/Krea-2", "file": "vae/qwen_image_vae.safetensors"}` |
| CivitAI | `civitai` (the **version** id, in the page URL `?modelVersionId=`), `name` | `{"civitai": 123456, "name": "lora.safetensors"}` |
| GitHub | `github` (repository), `file`, optional `revision` | `{"github": "madebyollin/taehv", "file": "safetensors/taeh3.safetensors"}` |
| URL | `url`, `name` | `{"url": "https://example.com/4x.pth", "name": "4x.pth"}` |

`name` sets the local file name. It is required for CivitAI and URLs.

**4. Workflows and pip packages** (optional):

```json
"workflows": [
  {"url": "https://example.com/my_workflow.json", "name": "my_workflow.json"}
],
"pip": ["onnxruntime-gpu"]
```

Workflows go to `user/default/workflows/` and appear in ComfyUI's workflow browser.

**5. Sizes.** Click **Recalculate sizes**: the panel asks each source for the size of its
files (without downloading anything) and writes them in the file, with the `sha256` of the
models when the source gives it (Hugging Face, CivitAI). The card then shows the total size,
and how much is left to download.

### Sharing items between profiles: `extends`

Several profiles often share the same base. Put it in its own profile and inherit from it:

```json
"essential-nodes": {
  "custom_nodes": [{"git": "https://github.com/rgthree/rgthree-comfy.git"}]
},
"krea2-common": {
  "extends": ["essential-nodes"],
  "models": [{"type": "vae/krea2", "hf": "Comfy-Org/Krea-2", "file": "vae/qwen_image_vae.safetensors"}]
},
"krea2-turbo": {
  "extends": ["krea2-common"],
  "models": [{"type": "diffusion_models/krea2", "hf": "Comfy-Org/Krea-2", "file": "diffusion_models/krea2_turbo_int8_convrot.safetensors"}]
}
```

Installing `krea2-turbo` installs `krea2-common` and `essential-nodes` too. Uninstalling
`krea2-turbo` only removes its own diffusion model: the VAE and the custom node stay, because
other profiles may need them.

A profile can also only group others, without items of its own:

```json
"krea2-all": {"extends": ["krea2-turbo", "krea2-styles"]}
```

## 5. Variants (int8, fp8, bf16...)

The same model often exists in several precisions: `int8` (small), `fp8`, `bf16` (large,
best quality). Instead of one profile per precision, a single profile declares
**variants**, and each model says which variant it belongs to:

```json
"krea2-turbo": {
  "extends": ["krea2-common"],
  "variants": ["int8", "fp8", "bf16"],
  "default_variant": "int8",
  "models": [
    {"variant": "int8", "type": "diffusion_models/krea2", "hf": "Comfy-Org/Krea-2", "file": "diffusion_models/krea2_turbo_int8_convrot.safetensors"},
    {"variant": "fp8",  "type": "diffusion_models/krea2", "hf": "Comfy-Org/Krea-2", "file": "diffusion_models/krea2_turbo_fp8_scaled.safetensors"},
    {"variant": "bf16", "type": "diffusion_models/krea2", "hf": "Comfy-Org/Krea-2", "file": "diffusion_models/krea2_turbo_bf16.safetensors"},
    {"type": "loras/krea2", "hf": "Comfy-Org/Krea-2", "file": "loras/krea2_darkbrush.safetensors"}
  ]
}
```

- An item with `"variant": "int8"` only belongs to `int8`. An item shared by some variants
  takes a list: `"variant": ["fp8", "bf16"]`.
- An item **without** `variant` (the LoRA above) is common to all the variants.

The variants to install go between brackets, everywhere a profile name is expected (panel,
command line, `COMFY_PROFILES`, `extends`, Workflow profiles node):

| You write | Installed |
|---|---|
| `krea2-turbo[int8]` | the common items + those of `int8` |
| `krea2-turbo[int8,bf16]` | the common items + those of `int8` and `bf16` |
| `krea2-turbo` | the common items + those of `default_variant` (only the common items without one) |
| `krea2-turbo[]` | only the common items |

In the panel, a profile with variants keeps **one card**, with one chip per variant (its
state color and its size, ★ for the default variant). Click the chips the card's buttons apply
to: none is ticked at first, and these buttons stay inactive until you tick one (same for the
Sync, Dry-run, Update and Uninstall buttons under the list, for a checked profile).

- solid outline: ticked, and already installed (green dot);
- **⤓** (blue dashed outline): ticked and not installed yet: the next sync installs it.

The details (chevron button) group the items by variant. Each block takes the color of its
own state. Below, `int8` and `bf16` are ticked and not fully installed: a sync of the card
would install both. In the details, the LoRAs common to all variants are partially installed
(yellow), the `int8` files inherited from `krea2-turbo` are there (green), those of `fp8` and
`bf16` are not.

![A profile with variants, with its details](images/panel-variants.png)

## 6. The panel in detail

### Sync, Dry-run, Update

Tick one or several profiles, then:

- **Sync**: installs what is missing, never touches what is there;
- **Dry-run**: shows what Sync would do, without doing it;
- **Update**: like Sync, and also updates what changed at the source (new commit of a custom
  node, new version of a Hugging Face file...);
- **Stop**: interrupts the running action. Interrupted downloads resume where they stopped
  at the next Sync (except Hugging Face, which starts over).

The download and trash icons on each card do the same for that profile alone.

### Uninstall

**Uninstall…** first shows what will be removed, and how much space this frees. Nothing is
removed before you confirm.

![Uninstall plan](images/panel-uninstall.png)

- Only what comfyui-profiles installed itself is removed. A model copied by hand or a custom
  node installed with ComfyUI-Manager stays in place.
- Items still needed by another installed profile are kept.
- **Include the inherited profiles** also removes the profiles it extends (useful for a
  profile that only groups others).
- pip packages are never removed.

To let comfyui-profiles remove items that were there before (copied by hand, for instance),
**take them over** first: the link icon on a card with a *not managed* chip.

### Filters

The text field searches the profile names and their items (a model or custom node name). The
legend chips (*installed*, *partially installed*, *not installed*, *not managed*) are filters
too: click them to show only those profiles. **Show final profiles only** hides the base
profiles (`*-common`), installed along with the others anyway.

### Settings

The gear icon opens the download settings: number of files downloaded at a time, Hugging Face
high performance mode, and the partial downloads left by an interrupted sync (with a button to
delete them).

![Settings](images/panel-settings.png)

## 7. Sharing a workflow with its profiles

A workflow can say which profiles it needs: whoever opens it sees what is missing and installs
it in one click. And one workflow can serve every variant of a profile (int8, bf16…), the
panel fixing its model fields for you.

### Declare the profiles

The **Workflow profiles** node (*utils* category) carries the declaration:

![The Workflow profiles node](images/node-workflow-profiles.png)

- **profiles**: the profiles the workflow needs, comma-separated, with their variants between
  brackets, e.g. `flux3-klein[int8], flux2-klein-9b`;
- **source** (optional): the URL of the profiles file that defines them, for instance a raw
  GitHub link to your `profiles.json`, for those who do not have these profiles.

The node is never executed and changes nothing in the result: it only travels with the
workflow.

You do not need to look for it in the node list. When the open workflow has no such node, the
**This workflow** section of the panel says so:

![A workflow without declared profiles](images/panel-no-declaration.png)

- **+** adds the node, filled with the profiles ticked in the panel. It is placed in the
  visible part of the canvas, without covering other nodes;
- the second icon opens the check of the workflow's models (below), which can also fill the
  node for you.

### What whoever opens the workflow sees

A notification lists the declared profiles that are missing, and the **This workflow** section
gives their state:

![The "This workflow" section](images/panel-workflow.png)

- the download icon installs a missing profile, **Install the workflow's profiles** installs
  all of them;
- **+** on a profile missing from your file adds it, taken from the node's source (with the
  profiles it extends). Your other profiles are left as they are.

### Check and fix the workflow's models

A workflow downloaded from the internet often points to models by a name that does not match
your installation: another folder (`flux2-vae.safetensors` where your profile installs
`flux3-klein/flux2-vae.safetensors`), another precision (int8 instead of bf16), another version
(`v2` instead of `v3.1`). ComfyUI then frames these nodes in red.

Click **Check the workflow's models…** (on the node, or the sliders icon of the **This
workflow** section). A dialog lists every model field of the workflow, with its state (red:
file not found; blue: present but outside the declared profiles; green: provided by them), and
for each one the files of your profiles that can replace it, best match first:

![Models of a workflow downloaded from Hugging Face](images/models-dialog.png)

- **same file**: the file the field asks for, in another folder;
- **other variant**: the same model in another precision;
- **other version**: another version of the model, in the same precision if possible;
- then the files with a similar name, and the other files of the same kind.

Only the clear matches are preselected; the others stay on **Keep**, and the list lets you
pick. **Provided by** shows the profiles providing the chosen file: **+** declares one in the
node. When all the models of the workflow are provided by profiles, the banner at the top
gives the fewest profiles needed: **Declare in the workflow** adds them at once.

Nothing changes in the fields before **Apply**; Ctrl+Z undoes it. The red frames go away for
the fields whose file is installed; for the others, once you install the workflow's profiles.

### One workflow for every variant

To use a workflow in another precision, click the variant you want next to **Variant**, at the
top of the dialog: it is declared in the node in place of the previous one, and the fields are
preselected again for its files. With `bf16` clicked, the official int8 workflow of FLUX.3
[klein] is turned to the bf16 files:

![The same workflow turned to the bf16 variant](images/models-dialog-variant.png)

Apply, install `flux3-klein[bf16]` from the **This workflow** section, and the workflow runs in
bf16. Your profiles can thus point to the original workflows of a model, without keeping a copy
for each variant or folder layout.

## 8. Secrets: tokens and passwords

Some sources need credentials:

| Source | Variable | When |
|---|---|---|
| Hugging Face | `HF_TOKEN` (or `hf auth login` once) | gated or private repositories (accept the license on the model page first) |
| CivitAI | `CIVITAI_TOKEN` | models whose download requires an account |
| Google Drive | `GDRIVE_ZIP_PASSWORD` | encrypted zips of custom nodes |
| GitHub, URL | — | public files only |

Create the tokens at <https://huggingface.co/settings/tokens> (read access is enough) and in
your CivitAI account settings (*API Keys*).

**The panel neither asks for nor stores any secret.** It runs the download script with the
environment of the ComfyUI server. So the variables must be set **before ComfyUI starts**: a
variable set afterwards is only seen after a restart of ComfyUI (a real one: **Restart
ComfyUI** in the panel keeps the same environment).

### A `.env` file

The simplest way is to keep everything in a `.env` file next to ComfyUI:

```dotenv
# Secrets: never commit this file (add it to .gitignore)
HF_TOKEN=hf_xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
CIVITAI_TOKEN=xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx
GDRIVE_ZIP_PASSWORD=my-zip-password

# Optional: profiles synced at startup, settings
COMFY_PROFILES=essential-nodes,krea2-turbo[int8]
COMFY_PROFILES_JOBS=4
```

Write values without quotes and without spaces around `=`: this format is read the same way
by bash, Docker and the Windows scripts below.

### Linux / macOS

Load the `.env` file, then start ComfyUI from the same shell:

```bash
cd ~/ComfyUI
chmod 600 .env                 # readable by you only
set -a; source .env; set +a    # set -a: every variable is exported
python main.py
```

Or a small launcher, `start-comfyui.sh`:

```bash
#!/usr/bin/env bash
cd "$(dirname "$0")"
set -a; source .env; set +a
exec python main.py --listen "$@"
```

For a single variable and a single launch: `HF_TOKEN=hf_xxx python main.py`.

With a systemd service: `EnvironmentFile=/home/me/ComfyUI/.env` in the `[Service]` section.

### Windows

**Portable ComfyUI**: create `run_with_env.bat` next to `run_nvidia_gpu.bat`, and the `.env`
file in the same folder:

```bat
@echo off
cd /d "%~dp0"
for /f "usebackq eol=# tokens=1,* delims==" %%a in (".env") do set "%%a=%%b"
.\python_embeded\python.exe -s ComfyUI\main.py --windows-standalone-build
pause
```

Start ComfyUI with this file from now on.

**PowerShell** (manual installation in a venv): load the `.env` file then start ComfyUI in the
same window:

```powershell
Get-Content .env | ForEach-Object {
  if ($_ -match '^\s*([A-Za-z_]\w*)\s*=\s*(.*)$') {
    Set-Item "Env:$($Matches[1])" $Matches[2].Trim()
  }
}
python main.py
```

**ComfyUI Desktop**, or any launch from the Start menu: set user environment variables, once
(*Settings › System › About › Advanced system settings › Environment Variables*, or `setx`):

```powershell
setx HF_TOKEN "hf_xxx"
setx CIVITAI_TOKEN "xxx"
setx GDRIVE_ZIP_PASSWORD "xxx"
```

`setx` only applies to programs started afterwards: quit ComfyUI Desktop completely (also from
the notification area) and start it again.

In a `.bat` file, a `%` in a value must be doubled (`%%`).

### Good practices

- Never put a secret in `profiles.json`, a workflow, or a Docker image (`ENV`, `ARG`).
- Everything running in ComfyUI, custom nodes included, can read its environment: on an
  instance holding tokens, only install custom nodes you trust.
- On a shared instance, `COMFY_PROFILES_READONLY=1` limits the panel to browsing and dry-run.

## 9. Command line

Everything the panel does is available with `comfy_profiles.py`. Run it with **ComfyUI's
Python** (the one of its venv, or `python_embeded\python.exe` on Windows portable): Python
dependencies of custom nodes are installed there. When the script is in
`ComfyUI/custom_nodes/comfyui-profiles/`, it finds ComfyUI by itself; otherwise set
`COMFY_HOME`.

```bash
cd ~/ComfyUI
set -a; source .env; set +a           # tokens, see section 8
alias cprof="python custom_nodes/comfyui-profiles/comfy_profiles.py"
```

On Windows portable:

```bat
python_embeded\python.exe ComfyUI\custom_nodes\comfyui-profiles\comfy_profiles.py list
```

### List and inspect

```console
$ cprof list
>> Config: /opt/ComfyUI/user/__comfy_profiles/profiles.json
- essential-nodes
    Commonly used custom nodes (rgthree, KJNodes).
    own: 2 custom_nodes
- krea2-turbo  (extends: krea2-common)
    variants: int8 (default), fp8, bf16
    size: int8: 18.6 GB, fp8: 18.6 GB, bf16: 35.4 GB
    Krea 2 Turbo (text to image, 8 steps).
    own: 6 models
...

$ cprof show "krea2-turbo[int8,bf16]"
[krea2-turbo[int8]]
  model        text_encoders/krea2/qwen3vl_4b_int8_convrot.safetensors    4.9 GB  present
  model        diffusion_models/krea2/krea2_turbo_int8_convrot.safetensors   13.5 GB  present
[krea2-turbo[bf16]]
  model        text_encoders/krea2/qwen3vl_4b_bf16.safetensors    8.9 GB  to download
  model        diffusion_models/krea2/krea2_turbo_bf16.safetensors   26.3 GB  to download
[essential-nodes] (inherited)
  custom_node  rgthree-comfy                                       present
  custom_node  ComfyUI-KJNodes                                     present
[krea2-common] (inherited)
  model        vae/krea2/qwen_image_vae.safetensors      253.8 MB  present
```

Quote the names with brackets: in bash and zsh, `[...]` is a filename pattern.

### Install

```console
$ cprof sync "krea2-styles[int8]" --dry-run
>> Profiles: krea2-styles[int8] — 2 action(s) to do
>> Models -> /opt/ComfyUI/models
   [dry-run] hf:Comfy-Org/Krea-2/loras/krea2_neondrip.safetensors -> /opt/ComfyUI/models/loras/krea2/style/krea2_neondrip.safetensors
   [dry-run] hf:Comfy-Org/Krea-2/loras/krea2_softwatercolor.safetensors -> /opt/ComfyUI/models/loras/krea2/style/krea2_softwatercolor.safetensors

$ cprof sync "krea2-styles[int8]"               # install
$ cprof sync "krea2-styles[int8]" --update      # install and update what changed
$ cprof sync "krea2-turbo[int8]" --jobs 6       # 6 files at a time
$ COMFY_PROFILES="essential-nodes,krea2-turbo[int8]" cprof sync   # profiles of COMFY_PROFILES
```

`Ctrl+C` stops a sync cleanly; the next one resumes the interrupted downloads.

### Uninstall and take over

```console
$ cprof uninstall "krea2-styles[int8]" --dry-run
>> Uninstall: krea2-styles[int8] — 1 item(s), 469.3 MB
>> Inherited profiles left in place: essential-nodes, krea2-common, krea2-turbo[int8] (--with-extends to include them)
   [dry-run] remove model        loras/krea2/style/krea2_darkbrush.safetensors  (469.3 MB)

$ cprof uninstall "krea2-styles[int8]"                  # remove
$ cprof uninstall krea2-all --with-extends              # a grouping profile and what it groups
$ cprof adopt taesd-previews                            # take over files copied by hand
```

### Sizes, settings, other files

```bash
cprof sizes                       # query the sizes of the files without one, write them
cprof sizes --force --dry-run     # query everything again, only show the result
cprof settings --set '{"jobs": 4}'
cprof settings --clean-partials   # delete the partial downloads
cprof where                       # which profiles file is used, and why
cprof --config ~/my-profiles/profiles.json list   # work on another file
```

`sizes` also works outside ComfyUI, for instance on the `profiles.json` of a Git repository,
with tokens taken from a `.env` file:

```bash
python comfy_profiles.py --config profiles.json sizes --env deploy/.env
```

With the `sha256`, `sizes` also reports the same file installed in two places: two families
that ship the same text encoder or VAE (same sha256, under another folder). Put it in a shared
profile that both extend, with a single `type`, e.g. `vae/flux2`, so that it is downloaded once.

`python comfy_profiles.py --help` and `python comfy_profiles.py <command> --help` list all the
options. Messages follow `COMFY_PROFILES_LANG` (`en`, `fr`), otherwise the system language.

## 10. Docker and cloud pods

In a container, the usual pattern is to sync the profiles at startup, then start ComfyUI.

`entrypoint.sh`:

```bash
#!/usr/bin/env bash
set -e
cd /opt/ComfyUI
# Profiles of COMFY_PROFILES: installs what is missing (fast when everything is there).
python custom_nodes/comfyui-profiles/comfy_profiles.py sync || echo "!! profile sync failed"
exec python main.py --listen 0.0.0.0 --port 8188
```

`docker-compose.yml`:

```yaml
services:
  comfyui:
    image: my-comfyui-image
    ports: ["8188:8188"]
    env_file: .env                      # HF_TOKEN, CIVITAI_TOKEN, COMFY_PROFILES...
    environment:
      COMFY_PROFILES_SEED: /opt/profiles.json         # template shipped in the image
    volumes:
      - ./models:/opt/ComfyUI/models                  # models survive the container
      - ./user:/opt/ComfyUI/user                      # your profiles file and the manifest
```

Or with `docker run`:

```bash
docker run --env-file .env -e COMFY_PROFILES="krea2-turbo[int8]" -p 8188:8188 \
  -v "$PWD/models:/opt/ComfyUI/models" -v "$PWD/user:/opt/ComfyUI/user" my-comfyui-image
```

Useful variables (all in the [README](../README.md#environment-variables)):

| Variable | Role |
|---|---|
| `COMFY_PROFILES` | profiles synced by `sync` without argument, *startup* chip in the panel |
| `COMFY_PROFILES_SEED` | template profiles file shipped with the image |
| `COMFY_PROFILES_NODES_STORE` | custom nodes cloned on a persistent volume, linked in `custom_nodes/` |
| `COMFY_PROFILES_READONLY` | `1`: panel limited to browsing and dry-run |
| `COMFY_PROFILES_JOBS` | files downloaded at a time |

On RunPod and similar services, store the tokens as **secrets** of the platform and reference
them in the template environment (`HF_TOKEN={{ RUNPOD_SECRET_hf_token }}`): they never appear
in clear. For a complete example (Docker image, RunPod template, secrets, sync at startup), see
[runpod-comfy-blackwell](https://github.com/jdelahayes/runpod-comfy-blackwell).

## 11. Troubleshooting

| Symptom | Cause and fix |
|---|---|
| `HTTP 401` or `403` on a Hugging Face file | gated repository: accept the license on the model page, and set `HF_TOKEN` (or `hf auth login`) before starting ComfyUI |
| CivitAI download refused (`HTTP 401` or `403`) | `CIVITAI_TOKEN` missing or wrong; also check that `civitai` is a model **version** id |
| `Drive zip … is encrypted: password expected in GDRIVE_ZIP_PASSWORD` | set `GDRIVE_ZIP_PASSWORD`, then restart ComfyUI |
| A token was added but the panel does not see it | the variables are read when ComfyUI starts: quit it completely and start it again from an environment that has them |
| New custom node missing from the node list | click **Restart ComfyUI** |
| New model missing from a node's list | press `R` in ComfyUI to refresh the lists |
| A file stays "not managed" and uninstall leaves it | it was there before: take it over (link icon, or `adopt`) |
| Size `?` on an item | **Recalculate sizes** |
| `Profile 'x': unknown key(s)` | typo in `profiles.json`: the file is checked before any action |
| The panel only allows dry-run | `COMFY_PROFILES_READONLY=1` is set |
| A sync was interrupted | run it again: CivitAI, GitHub, URL and Drive downloads resume, Hugging Face starts over |
