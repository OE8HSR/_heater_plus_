#!/usr/bin/env python3
"""
Sync English metadata from allsky_heaterplussettings.py into postprocessing_periodic.json.
Preserves user arguments (saved settings). Fixes German GUI texts caused by cached JSON.
"""
import json
import sys

MODULE_PATH = "/home/pi/allsky/scripts/modules/allsky_heaterplussettings.py"
JSON_PATH = "/home/pi/allsky/config/modules/postprocessing_periodic.json"


def load_module_metadata():
    # Mock allsky_shared so we can import the module
    import types
    mock_s = types.ModuleType("allsky_shared")
    mock_s.log = lambda *a, **k: None
    sys.modules["allsky_shared"] = mock_s
    try:
        import importlib.util
        spec = importlib.util.spec_from_file_location("allsky_heaterplussettings", MODULE_PATH)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod.metaData
    finally:
        sys.modules.pop("allsky_shared", None)


def main():
    with open(JSON_PATH, "r", encoding="utf-8") as f:
        data = json.load(f)

    if "heaterplussettings" not in data:
        print("heaterplussettings not found in JSON")
        sys.exit(1)

    module_meta = load_module_metadata()

    # Build new metadata: use module's name, description, argumentdetails (English)
    # but preserve user arguments from JSON
    block = data["heaterplussettings"]
    old_meta = block.get("metadata", {})

    new_meta = {
        "name": module_meta["name"],
        "description": module_meta["description"],
        "module": module_meta["module"],
        "events": old_meta.get("events", module_meta.get("events", {"0": "periodic"})),
        "arguments": old_meta.get("arguments", {}),  # preserve user values
        "argumentdetails": module_meta["argumentdetails"],
    }
    if "experimental" in old_meta:
        new_meta["experimental"] = old_meta["experimental"]

    block["metadata"] = new_meta

    with open(JSON_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

    print("postprocessing_periodic.json updated with English metadata from module.")


if __name__ == "__main__":
    main()
