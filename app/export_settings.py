"""
Export settings (P1.4): turn a clip's embedded WanGP metadata back into the
settings JSON WanGP saves with "Export Settings to File" and loads with
"Load Settings From Media File / Json / Zip".

WanGP's export is `prepare_inputs_dict("metadata", settings)` plus
`model_type` / `model_filename` (wgp.py `collect_current_model_settings`) -
the same dict it embeds in each video. Its loader (`get_settings_from_file`)
merges the JSON over the model's defaults and picks the model from
`model_type`, falling back to `base_model_type` then `model_filename`. So the
export is the embedded blob minus this browser's own `_*` keys and the
per-render bookkeeping WanGP adds only when it writes a video.
"""

import json
import random
import re

# Written by WanGP when it records a finished render, not part of a setting.
RUN_ONLY_KEYS = ("generation_time", "creation_date", "creation_timestamp",
                 "output_filename", "output_role")
MAX_SEED = 999_999_999  # WanGP draws random seeds from 0..999999999


class NotExportable(ValueError):
    pass


def is_wangp(meta):
    return bool(meta) and (meta.get("_source") == "wangp" or "WanGP" in str(meta.get("type", "")))


def build(meta, new_seed=False, rng=None):
    """Return the WanGP-loadable settings dict for a clip's metadata."""
    if not is_wangp(meta or {}):
        raise NotExportable("this clip has no WanGP settings to export")
    settings = {k: v for k, v in meta.items() if not str(k).startswith("_") and k not in RUN_ONLY_KEYS}
    if not (settings.get("model_type") or settings.get("base_model_type") or settings.get("model_filename")):
        raise NotExportable("WanGP metadata names no model")
    if new_seed:
        settings["seed"] = (rng or random.SystemRandom()).randint(0, MAX_SEED)
    return settings


def filename(entry, settings):
    model = str(settings.get("model_type") or settings.get("base_model_type") or "wangp")
    stamp = (entry.get("filename_info") or {}).get("date") or ""
    time = ((entry.get("filename_info") or {}).get("time") or "").replace(":", "")
    name = "_".join(part for part in (model, stamp + ("-" + time if time else ""), f"seed{settings.get('seed')}") if part)
    return re.sub(r"[^A-Za-z0-9._-]+", "_", name)[:120] + ".json"


def export(entry, new_seed=False):
    """(bytes, filename) for /api/export/<id>."""
    settings = build((entry or {}).get("meta") or {}, new_seed=new_seed)
    return json.dumps(settings, indent=4).encode("utf-8"), filename(entry, settings)
