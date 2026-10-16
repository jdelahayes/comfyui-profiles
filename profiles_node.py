"""Node « Workflow profiles » : déclare, dans un workflow, les profils dont il a besoin.

Le node ne sert qu'à porter cette information avec le workflow : il n'a ni entrée reliable ni
sortie et n'est pas un node de sortie (OUTPUT_NODE), donc ComfyUI ne l'exécute jamais, même s'il
fait partie du prompt envoyé. Dans un ComfyUI sans ce plugin, il apparaît comme node manquant :
c'est l'indication qu'il faut installer comfyui-profiles.

- profiles : noms des profils, séparés par des virgules (comme en ligne de commande) ;
- source (optionnel) : URL du fichier de profils qui les définit, pour qui ne les a pas
  (un nom de profil n'a de sens que dans un fichier de profils donné).
"""


class WorkflowProfiles:
    CATEGORY = "utils"
    DESCRIPTION = ("Profiles this workflow needs (comfyui-profiles). Never executed: it only "
                   "carries this information with the workflow.")
    RETURN_TYPES = ()
    FUNCTION = "noop"

    @classmethod
    def INPUT_TYPES(cls):
        return {
            "required": {
                "profiles": ("STRING", {
                    "default": "",
                    "tooltip": "Profile names, comma-separated (e.g. krea2, essential-nodes).",
                }),
            },
            "optional": {
                "source": ("STRING", {
                    "default": "",
                    "tooltip": "URL of the profiles file that defines them (e.g. a raw GitHub "
                               "link), for users who don't have these profiles.",
                }),
            },
        }

    def noop(self, profiles, source=""):
        return ()


NODE_CLASS_MAPPINGS = {"WorkflowProfiles": WorkflowProfiles}
NODE_DISPLAY_NAME_MAPPINGS = {"WorkflowProfiles": "Workflow profiles"}
