# comfyui-profiles

Panneau **Profils** pour ComfyUI : installe, vérifie et désinstalle des *profils d'utilisation*
depuis la barre latérale. Un profil décrit tout ce dont un usage a besoin (modèles, custom
nodes, workflows, paquets pip) dans un fichier `profiles.json`.

Conçu pour l'image [runpod-comfy-blackwell](https://github.com/jdelahayes/runpod-comfy-blackwell),
qui l'embarque et fournit le `profiles.json` (format et exemples : voir son README, section
*Profils d'utilisation*).

## Contenu

- `comfy_profiles.py` : le gestionnaire de profils, utilisable seul en ligne de commande.
- `__init__.py` : routes HTTP `/comfy-profiles/*` ajoutées au serveur ComfyUI ; elles lancent
  `comfy_profiles.py` en sous-processus, avec le Python de ComfyUI.
- `web/profiles.js` : l'onglet de la barre latérale.

Aucun node n'est ajouté au graphe.

## Panneau

- Liste des profils : description, taille, `extends`, badge *démarrage* pour ceux de
  `COMFY_PROFILES`. La couleur de fond donne l'état : vert installé (tout est là, `extends`
  compris), orange partiel, neutre non installé. Seuls les éléments propres au profil comptent
  pour « partiel », pas ceux hérités ; un profil qui ne fait que regrouper d'autres profils
  est partiel si l'un d'eux est installé ou partiel.
- Boutons par profil : installer (s'il n'est pas complètement installé), désinstaller (s'il
  l'est, même partiellement), détail de ce qui est présent ou non.
- Synchronisation, dry-run ou désinstallation des profils cochés, avec les logs en direct.
  Une seule action à la fois ; **Arrêter** l'interrompt proprement (le téléchargement ou le
  clone en cours est abandonné sans laisser de fichier incomplet).
- Édition de `profiles.json`, validée avant d'être enregistrée.
- Redémarrage de ComfyUI (même processus relancé), nécessaire après l'installation de
  nouveaux custom nodes.

Toute personne qui a accès à l'UI peut installer des profils, modifier leur config et
redémarrer ComfyUI.

## Ligne de commande

```bash
comfy_profiles.py [--config FICHIER] list [--json]
comfy_profiles.py [--config FICHIER] show PROFIL[,PROFIL...] [--json]
comfy_profiles.py [--config FICHIER] sync [PROFIL[,PROFIL...]] [--dry-run]
comfy_profiles.py [--config FICHIER] uninstall PROFIL[,PROFIL...] [--dry-run] [--json]
```

`sync` installe ce qui manque et ne touche jamais à ce qui est déjà présent. `uninstall`
supprime les modèles, workflows et custom nodes des profils, `extends` compris, sauf ce qui
sert encore à un profil gardé (un profil de `COMFY_PROFILES`, ou un autre profil complètement
installé). Les custom nodes livrés avec l'image et les paquets pip ne sont jamais supprimés.

## Variables d'environnement

| Variable | Rôle | Défaut |
|---|---|---|
| `COMFY_PROFILES_CONFIG` | fichier de profils (copié depuis le défaut s'il n'existe pas) | `/opt/scripts/profiles.json` |
| `COMFY_PROFILES` | profils synchronisés par `sync` sans argument (badge *démarrage*) | — |
| `COMFY_HOME` | dossier de ComfyUI | `/workspace/ComfyUI` |
| `MODELS_VOLUME_DIR` | modèles sur le volume persistant (ignoré si son parent n'existe pas) | `/runpod-volume/models` |
| `HF_TOKEN`, `CIVITAI_TOKEN` | téléchargements authentifiés | — |
| `GDRIVE_ZIP_PASSWORD` | zips chiffrés des custom nodes `gdrive` | — |
| `COMFY_PROFILES_SCRIPT` | autre `comfy_profiles.py` à utiliser par le panneau | celui de ce dépôt |
