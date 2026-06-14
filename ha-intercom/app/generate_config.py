"""Generates go2rtc.yaml at runtime from the add-on options."""
import json
import os
import yaml

OPTIONS_PATH = os.environ.get("OPTIONS_PATH", "/data/options.json")
OUTPUT_PATH = "/data/go2rtc.yaml"
TEMPLATE_PATH = "/etc/go2rtc.yaml"

with open(TEMPLATE_PATH) as f:
    config = yaml.safe_load(f)

try:
    with open(OPTIONS_PATH) as f:
        options = json.load(f)
    log_level = options.get("log_level", "info")
except (FileNotFoundError, json.JSONDecodeError):
    log_level = "info"

config["log"] = {"level": log_level}

with open(OUTPUT_PATH, "w") as f:
    yaml.dump(config, f, default_flow_style=False)

print(f"go2rtc config written to {OUTPUT_PATH}")
