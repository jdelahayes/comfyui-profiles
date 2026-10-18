""""Workflow profiles" node: declares, in a workflow, the profiles it needs.

The node only carries this information with the workflow: it has no linkable input, no output
and is not an output node (OUTPUT_NODE), so ComfyUI never executes it, even when it is part of
the submitted prompt. In a ComfyUI without this plugin, it shows up as a missing node: the hint
that comfyui-profiles must be installed.

- profiles: profile names, comma-separated (as on the command line); variants between brackets
  (krea2-turbo[int8], krea2-raw[int8,bf16]), otherwise the profile's default variant;
- source (optional): URL of the profiles file that defines them, for users who don't have them
  (a profile name only makes sense within a given profiles file).
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
                    "tooltip": "Profile names, comma-separated (e.g. krea2-turbo, essential-nodes). "
                               "Variants between brackets: krea2-turbo[int8], krea2-raw[int8,bf16]; "
                               "without brackets, the profile's default variant.",
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
