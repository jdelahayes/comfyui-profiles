# comfyui-profiles

Panneau **Profils** pour ComfyUI : installe, vérifie et désinstalle des *profils d'utilisation*
depuis la barre latérale. Un profil décrit tout ce dont un usage a besoin (modèles, custom
nodes, workflows, paquets pip) dans un fichier `profiles.json`.

Fonctionne avec n'importe quel ComfyUI (installation manuelle, comfy-cli, image Docker). Pour
un exemple d'intégration dans une image Docker, voir
[runpod-comfy-blackwell](https://github.com/jdelahayes/runpod-comfy-blackwell).

## Installation

```bash
cd ComfyUI/custom_nodes
git clone https://github.com/jdelahayes/comfyui-profiles.git
```

puis redémarrer ComfyUI. L'onglet **Profils** apparaît dans la barre latérale. Aucun node n'est
ajouté au graphe.

## Contenu

- `comfy_profiles.py` : le gestionnaire de profils, utilisable seul en ligne de commande.
- `profile_sizes.py` : calcule la taille de chaque profil à la source (Hugging Face, CivitAI,
  GitHub, URL), sans rien télécharger, et l'enregistre dans le fichier de profils.
- `__init__.py` : routes HTTP `/comfy-profiles/*` ajoutées au serveur ComfyUI ; elles lancent
  `comfy_profiles.py` et `profile_sizes.py` en sous-processus, avec le Python de ComfyUI et
  ses chemins.
- `web/profiles.js` : l'onglet de la barre latérale.
- `profiles_i18n.py` et `lang/` : traductions (voir [Langue](#langue)).
- `examples/profiles.example.json` : petit fichier de profils, utilisé tant qu'aucun autre
  n'est fourni.
- `profiles.schema.json` : schéma JSON du fichier de profils (validation et autocomplétion
  dans un éditeur, via `"$schema"`).

## Fichier de profils

Le fichier utilisé est le premier trouvé parmi :

1. `--config FICHIER` (ligne de commande) ;
2. `COMFY_PROFILES_CONFIG` : s'il n'existe pas encore, le modèle y est d'abord copié ;
3. `ComfyUI/user/__comfy_profiles/profiles.json` : **ton fichier**, celui qu'écrivent
   l'édition, l'import et le calcul des tailles du panneau ;
4. le **modèle**, en lecture seule : `COMFY_PROFILES_SEED` (fourni par exemple par une image
   Docker), sinon `examples/profiles.example.json`.

Tant que tu n'as rien modifié, c'est donc le modèle qui sert, et ses mises à jour sont prises
en compte. La première modification crée ton fichier, qui prend le relais. **Revenir au
modèle** le met de côté (`profiles.json.bak`).

`user/__comfy_profiles/` est un dossier « System User » de ComfyUI (préfixe `__`) : ComfyUI ne
le sert jamais par ses routes HTTP (`/api/userdata`...), seul ce panneau y lit et écrit, après
validation.

Depuis le panneau : **Éditer**, **Importer…** (fichier du poste), **Depuis une URL…** (ex. lien
raw GitHub ou gist : pratique pour garder ses profils dans un dépôt), **Exporter**. Un fichier
invalide est refusé avant de remplacer quoi que ce soit.

### Format

```jsonc
{
  "$schema": "https://raw.githubusercontent.com/jdelahayes/comfyui-profiles/main/profiles.schema.json",
  "profiles": {
    "mon-profil": {
      "description": "Texte libre, affiché dans le panneau et par `list`.",
      "extends": ["krea2"],              // hérite de tout le contenu d'autres profils
      "models": [
        // type = sous-dossier de ComfyUI/models (loras, vae, diffusion_models, checkpoints...)
        {"type": "loras", "hf": "org/depot", "file": "chemin/dans/le/depot.safetensors"},
        {"type": "loras", "hf": "org/depot", "file": "x.safetensors", "revision": "main", "name": "renomme.safetensors"},
        {"type": "checkpoints", "civitai": 123456, "name": "mon_modele.safetensors"},   // id de VERSION du modèle
        {"type": "vae", "github": "https://github.com/madebyollin/taehv.git", "file": "safetensors/taeh3.safetensors"},  // un seul fichier du dépôt
        {"type": "upscale_models", "url": "https://exemple.com/4x.pth", "name": "4x.pth"}
      ],
      "custom_nodes": [
        {"git": "https://github.com/auteur/ComfyUI-Truc.git"},
        {"git": "https://github.com/auteur/ComfyUI-Machin.git", "ref": "v1.2.0", "name": "Machin"},
        // zip public sur Google Drive (lien de partage ou id du fichier)
        {"gdrive": "https://drive.google.com/file/d/1AbC.../view?usp=sharing", "name": "ComfyUI-Bidule"}
      ],
      "workflows": [
        {"url": "https://exemple.com/workflow.json", "name": "mon_workflow.json"}
      ],
      "pip": ["onnxruntime-gpu"]
    }
  }
}
```

(Le vrai fichier est du JSON strict, sans commentaires. Les clés qui commencent par `//` sont
ignorées et peuvent servir de commentaires.)

- **Sources** (modèles et workflows) : une seule par élément parmi `hf` (+ `file`, et
  optionnellement `revision`), `github` (dépôt public `owner/depot` ou son URL, + `file`, et
  optionnellement `revision` : branche, tag ou commit), `civitai` (id de version, utilise
  `CIVITAI_TOKEN`) ou `url`. Avec `github`, seul le fichier est téléchargé, sans cloner le
  dépôt (Git LFS compris). `name` fixe le nom du fichier local. Il est obligatoire pour
  `civitai` et `url`, et vaut par défaut le nom de `file` pour `hf` et `github`.
- **Destinations** : modèles dans les dossiers de leur type tels que ComfyUI les voit,
  `extra_model_paths.yaml` compris (voir ci-dessous) ; custom nodes dans `custom_nodes/` (ou
  dans `COMFY_PROFILES_NODES_STORE`, puis liés dans `custom_nodes/`) ; workflows dans
  `user/default/workflows/`.
- **Dossiers de modèles** : un modèle est trouvé dans n'importe lequel des dossiers que ComfyUI
  parcourt pour son type (ex. `unet/` ou `diffusion_models/`, et ceux de
  `extra_model_paths.yaml`). S'il manque, il est téléchargé dans le premier de ces dossiers, dans
  l'ordre de ComfyUI (un chemin `is_default: true` passe donc en tête), en préférant celui qui
  porte le nom du type : `diffusion_models/` plutôt que `unet/`. Un sous-dossier dans `type`
  (`diffusion_models/krea2`) fait partie du nom du modèle pour ComfyUI : un fichier rangé
  ailleurs dans le dossier du type n'est pas reconnu.
- **Dépendances Python** : le `requirements.txt` et le `install.py` des custom nodes, ainsi que
  les paquets `pip`, sont installés dans l'environnement Python de ComfyUI. Ce qui a été
  installé est noté dans cet environnement : un nouveau conteneur réinstalle les dépendances,
  même si les custom nodes sont déjà sur un volume persistant.
- **Version des custom nodes** : `ref` (optionnel) fixe une branche, un tag ou un commit. Sans
  `ref`, la branche par défaut est clonée une fois puis jamais mise à jour. Si `ref` change, le
  prochain `sync` bascule le clone existant dessus (seulement pour un node installé par le
  gestionnaire). Une branche n'est pas remise à jour tant que `ref` reste le même.
- **Custom nodes en zip sur Google Drive** : `gdrive` (lien de partage ou id du fichier, partagé
  en « Tous les utilisateurs disposant du lien ») et `name` (nom du dossier, obligatoire). Le
  zip est extrait dans `custom_nodes/<name>` ; s'il contient un unique dossier racine, c'est son
  contenu qui est pris. Il n'est retéléchargé que si `gdrive` change : pour mettre à jour le
  node, publie le nouveau zip comme un nouveau fichier Drive (ou supprime le dossier). Pour
  protéger le contenu d'un lien public, chiffre le zip (7-Zip : format zip, chiffrement
  AES-256) avec le mot de passe `GDRIVE_ZIP_PASSWORD`. Le chiffrement est détecté
  automatiquement ; un zip non chiffré s'extrait sans mot de passe.
- Une clé inconnue (faute de frappe) fait échouer la commande avant toute action.

## Ce qui est installé, ce qui est supprimé

`sync` installe ce qui manque et ne touche jamais à ce qui est déjà présent. Ce que le
gestionnaire installe lui-même est noté dans `user/__comfy_profiles/installed.json`, et
`uninstall` ne supprime **que** ces éléments : un modèle copié à la main, un custom node déjà
là (installé avec le Manager, livré avec une image Docker...) n'est jamais supprimé, ni changé
de version, même si un profil le cite. Ses dépendances Python restent aussi l'affaire de celui
qui l'a installé.

Un custom node déjà installé **sous un autre nom** est reconnu et laissé tel quel, au lieu d'être
cloné une seconde fois (ComfyUI le chargerait deux fois) : même nom à la casse près, ou même
dépôt (remote `origin` de son `.git`, ou `Repository` de son `pyproject.toml`). C'est le cas
des nodes installés par ComfyUI-Manager depuis le Comfy Registry, rangés sous leur id du
registry : `comfyui-kjnodes` pour `ComfyUI-KJNodes`.

`uninstall` supprime les modèles, workflows et custom nodes **propres** aux profils, sauf ce
qui sert encore à un profil gardé : un profil de `COMFY_PROFILES`, ou un autre profil
complètement installé, y compris ceux dont ils héritent. Exemple : désinstaller `krea2` (qui
hérite de `krea2-common`) supprime son modèle de diffusion, mais garde le text encoder et le
VAE de `krea2-common`. Avec `--with-extends` (case « Inclure les profils hérités » dans le
panneau), les profils hérités sont désinstallés aussi : c'est ce qu'il faut pour un profil qui
ne fait que regrouper d'autres profils. Les paquets pip ne sont jamais supprimés.

Pour qu'`uninstall` puisse quand même supprimer ce qui était déjà là, **prends-le en charge** :
`adopt PROFIL` (bouton « lien » du profil dans le panneau) inscrit au manifeste tout ce qui
est présent pour le profil, `extends` compris. Les dépendances de ses custom nodes sont
considérées comme déjà installées (le node fonctionnait déjà) : `sync` ne les relance pas. Le panneau signale ce qui n'est pas encore pris
en charge : pastille orange « N non pris en charge » sur le profil, et mention sur chaque
élément dans son détail.

Mise à jour depuis une version sans manifeste : si les custom nodes sont rangés à part
(`COMFY_PROFILES_NODES_STORE`), ce qui est déjà présent pour les profils du fichier est repris
dans le manifeste à la première utilisation (ce stockage n'est rempli que par le gestionnaire).

## Langue

Le panneau, les messages du script et les erreurs du serveur sont en français ou en anglais.
Le panneau suit la langue de ComfyUI (réglage *Langue*) ; en ligne de commande, c'est
`COMFY_PROFILES_LANG`, sinon `LC_ALL`, `LC_MESSAGES` ou `LANG`. L'anglais est la langue par
défaut, et celle d'une langue non traduite. Changer la langue de ComfyUI demande de recharger
la page.

Pour ajouter une langue : copier `lang/en.json` en `lang/<code>.json` (ex. `de.json`) et
traduire les valeurs. Les clés sont les messages français du code ; les `{variables}` doivent
rester telles quelles. Un message absent reste en français.

## Panneau

- Liste des profils : description, taille, `extends`, badge *démarrage* pour ceux de
  `COMFY_PROFILES`. Pour un profil qui n'est pas entièrement installé, un badge bleu
  *… à télécharger* donne la taille des fichiers absents, que son installation ajouterait
  (`extends` compris ; les custom nodes et paquets pip ne sont pas comptés). La couleur de
  fond donne l'état : vert installé (tout est là, `extends` compris), orange partiel, neutre non installé. Seuls les éléments propres au profil comptent
  pour « partiel », pas ceux hérités ; un profil qui ne fait que regrouper d'autres profils
  est jugé sur leurs éléments hors de la base qu'ils ont tous en commun (pour
  `minimax-h3-all-bf16` : les modèles fl2va et ref2va, pas `minimax-h3-common-bf16`).
- Filtres de la liste, mémorisés dans le navigateur : texte sur le nom des profils et de leurs
  éléments (`extends` compris), ou sur le nom des profils seulement ; profils finaux seulement
  (ceux qu'aucun autre profil n'étend), avec en option ceux qu'étend seulement un profil de
  regroupement (sans élément propre, ex. `minimax-h3-all-*`) ; état, en cliquant sur
  *installé*, *partiellement installé* ou *non installé* dans la légende (plusieurs à la fois
  possibles), et *non pris en charge* pour les profils qui ont des éléments non pris en charge. Un profil coché reste affiché.
- Boutons par profil : installer (s'il n'est pas complètement installé), désinstaller (s'il
  l'est, même partiellement), prendre en charge (s'il a des éléments non pris en charge),
  détail de ce qui est présent ou non, regroupé par profil qui déclare chaque élément (le
  profil lui-même, puis chaque profil hérité), avec la taille de chaque fichier (`?` tant
  qu'elle n'est pas connue : « Recalculer les tailles » l'interroge à la source) et une
  icône qui ouvre sa source (Hugging Face, GitHub, CivitAI, Google Drive, PyPI ou l'URL).
- Synchronisation, dry-run ou désinstallation des profils cochés, avec les logs en direct.
  Une seule action à la fois ; **Arrêter** l'interrompt proprement (le téléchargement ou le
  clone en cours est abandonné sans laisser de fichier incomplet).
- Fichier de profils : édition, import (fichier ou URL), export, retour au modèle.
- **Recalculer les tailles** : lance `profile_sizes.py` sur le fichier de profils (seuls les
  fichiers sans taille sont interrogés) ; **Tout recalculer** réinterroge aussi ceux dont la
  taille est connue (`--force`).
- Redémarrage de ComfyUI, nécessaire après l'installation de nouveaux custom nodes : même
  processus relancé, ou relance par comfy-cli quand ComfyUI tourne sous `comfy launch`.

Toute personne qui a accès à l'UI peut installer des profils, modifier leur fichier et
redémarrer ComfyUI. Sur une instance partagée, `COMFY_PROFILES_READONLY=1` limite le panneau à
la consultation et au dry-run.

## Ligne de commande

```bash
comfy_profiles.py [--config FICHIER] list [--json]
comfy_profiles.py [--config FICHIER] where                    # fichier utilisé et son origine (JSON)
comfy_profiles.py [--config FICHIER] show PROFIL[,PROFIL...] [--json]
comfy_profiles.py [--config FICHIER] sync [PROFIL[,PROFIL...]] [--dry-run]
comfy_profiles.py [--config FICHIER] uninstall PROFIL[,PROFIL...] [--with-extends] [--dry-run] [--json]
comfy_profiles.py [--config FICHIER] adopt PROFIL[,PROFIL...] [--dry-run] [--json]
profile_sizes.py [--config FICHIER] [--env FICHIER] [--force] [--dry-run]
```

À lancer avec le Python de ComfyUI (les dépendances s'y installent). Le dossier de ComfyUI est
`COMFY_HOME`, sinon celui dont ce dépôt est un custom node. Exemple : synchroniser des profils
au démarrage d'un conteneur, avant de lancer ComfyUI :

```bash
COMFY_PROFILES=krea2,flux2-klein-9b python custom_nodes/comfyui-profiles/comfy_profiles.py sync
```

`profile_sizes.py` n'interroge que les fichiers sans taille (`--force` : tous) et conserve la
mise en forme du fichier. `--env` reprend `HF_TOKEN` / `CIVITAI_TOKEN` d'un fichier `.env`
quand ils ne sont pas dans l'environnement. Il fonctionne aussi hors de tout ComfyUI avec
`--config`, par exemple sur le `profiles.json` d'un dépôt.

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `COMFY_PROFILES_SEED` | modèle de fichier de profils (lecture seule) | `examples/profiles.example.json` |
| `COMFY_PROFILES_CONFIG` | fichier de profils imposé (copié depuis le modèle s'il n'existe pas) | — |
| `COMFY_PROFILES` | profils synchronisés par `sync` sans argument (badge *démarrage*) | — |
| `COMFY_PROFILES_NODES_STORE` | dossier où cloner les custom nodes, liés ensuite dans `custom_nodes/` (ex. un volume persistant) | `custom_nodes/` |
| `COMFY_PROFILES_READONLY` | `1` : panneau en lecture seule | — |
| `COMFY_HOME` | dossier de ComfyUI (ligne de commande) | le ComfyUI parent de ce dépôt |
| `COMFY_MODELS_DIR`, `COMFY_CUSTOM_NODES_DIR`, `COMFY_USER_DIR` | chemins de ComfyUI (passés par le panneau) | sous `COMFY_HOME` |
| `COMFY_MODEL_FOLDERS` | dossiers de chaque type de modèle, en JSON (passés par le panneau) | dossiers par défaut + `extra_model_paths.yaml` |
| `COMFY_EXTRA_MODEL_PATHS` | autres fichiers `extra_model_paths` (séparés par `:`), comme `--extra-model-paths-config` (ligne de commande) | — |
| `HF_TOKEN`, `CIVITAI_TOKEN` | téléchargements authentifiés | — |
| `GDRIVE_ZIP_PASSWORD` | zips chiffrés des custom nodes `gdrive` | — |
| `COMFY_PROFILES_SCRIPT` | autre `comfy_profiles.py` à utiliser par le panneau | celui de ce dépôt |

## Intégration dans une image Docker

Le minimum :

```dockerfile
RUN git clone --branch v0.4.1 --depth 1 https://github.com/jdelahayes/comfyui-profiles.git \
      "${COMFY_HOME}/custom_nodes/comfyui-profiles"
COPY profiles.json /opt/profiles.json
ENV COMFY_PROFILES_SEED=/opt/profiles.json
```

- Les profils de l'image servent de modèle, et ceux que l'utilisateur modifie vivent dans
  `user/`. Si `user/` est sur un volume persistant, son fichier de profils et le manifeste le
  sont aussi.
- Avec des custom nodes sur un volume : `COMFY_PROFILES_NODES_STORE=<volume>/custom_nodes`.
  Les custom nodes copiés dans l'image (de vrais dossiers dans `custom_nodes/`) ne sont alors
  jamais touchés.
- Synchronisation au démarrage : `comfy_profiles.py sync` dans l'entrypoint, avec
  `COMFY_PROFILES`.

## Publication sur le Comfy Registry

`pyproject.toml` décrit le node pour le [Comfy Registry](https://registry.comfy.org). Le
workflow **Publish to Comfy registry** (manuel) publie la version de `pyproject.toml` ; il faut
un publisher sur le registry (`PublisherId`) et son token dans le secret
`REGISTRY_ACCESS_TOKEN`. Penser à aligner `version` sur le tag git.

## Licence

MIT, voir [LICENSE](LICENSE).
