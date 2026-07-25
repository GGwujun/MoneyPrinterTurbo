#!/usr/bin/env python3
"""
MoneyPrinterTurbo Desktop — Config Helper

Set or read keys in config.toml from the command line.
Used by Electron onboarding to write LLM provider / API key settings.

Usage:
  python set_config.py set <key> <value> [--config <path>]
  python set_config.py get <key> [--config <path>]
  python set_config.py test-llm --provider <id> [--config <path>]
"""

import argparse
import os
import shutil
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.environ.get("MPT_ROOT_DIR", os.path.dirname(os.path.dirname(HERE)))
CONFIG_FILE = os.environ.get("MPT_CONFIG_FILE", os.path.join(ROOT, "config.toml"))
EXAMPLE_FILE = os.path.join(ROOT, "config.example.toml")


def _ensure_config():
    if not os.path.isfile(CONFIG_FILE):
        if os.path.isfile(EXAMPLE_FILE):
            shutil.copyfile(EXAMPLE_FILE, CONFIG_FILE)
            return
        raise FileNotFoundError(f"No config file at {CONFIG_FILE} or {EXAMPLE_FILE}")


def _load():
    _ensure_config()
    sys.path.insert(0, ROOT)
    import toml

    try:
        return toml.load(CONFIG_FILE)
    except Exception:
        with open(CONFIG_FILE, "r", encoding="utf-8-sig") as f:
            return toml.loads(f.read())


def _save(cfg):
    import toml

    serialized = toml.dumps(cfg)
    tmp = CONFIG_FILE + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        f.write(serialized)
        f.flush()
        os.fsync(f.fileno())
    os.replace(tmp, CONFIG_FILE)


def cmd_set(args):
    cfg = _load()

    # Support dotted keys like "app.llm_provider" → cfg["app"]["llm_provider"]
    if "." in args.key:
        section, key = args.key.split(".", 1)
        if section not in cfg:
            cfg[section] = {}
        cfg[section][key] = args.value
    elif args.key.startswith("__section__."):
        # Special: set multiple keys under a section at once
        # Format: --key __section__.app --value "llm_provider=moonshot\nmoonshot_api_key=sk-xxx"
        section = args.key.split(".", 1)[1]
        if section not in cfg:
            cfg[section] = {}
        for line in args.value.strip().split("\n"):
            line = line.strip()
            if not line or "=" not in line:
                continue
            k, v = line.split("=", 1)
            cfg[section][k.strip()] = v.strip()
    else:
        cfg["app"][args.key] = args.value

    _save(cfg)
    print("ok")


def cmd_get(args):
    cfg = _load()
    section, key = ("app", args.key)
    if "." in args.key:
        section, key = args.key.split(".", 1)
    value = cfg.get(section, {}).get(key, "")
    print(value or "")


def cmd_test_llm(args):
    """Test LLM connection using the configured provider."""
    sys.path.insert(0, ROOT)
    from app.config import config
    from app.services import llm

    provider = args.provider
    cfg = _load()
    app_cfg = cfg.get("app", {})

    # Apply the settings from config so the test uses current config
    config.app["llm_provider"] = provider
    for k, v in app_cfg.items():
        config.app[k] = v

    ok, err, elapsed = llm.test_connection()
    if ok:
        print(f"ok {elapsed:.2f}s")
    else:
        print(f"error {err}")
        sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo config helper")
    parser.add_argument("--config", default=CONFIG_FILE, help="Path to config.toml")
    sub = parser.add_subparsers(dest="command", required=True)

    p_set = sub.add_parser("set")
    p_set.add_argument("key")
    p_set.add_argument("value")

    p_get = sub.add_parser("get")
    p_get.add_argument("key")

    p_test = sub.add_parser("test-llm")
    p_test.add_argument("--provider", required=True)

    args = parser.parse_args()

    global CONFIG_FILE
    CONFIG_FILE = args.config

    if args.command == "set":
        cmd_set(args)
    elif args.command == "get":
        cmd_get(args)
    elif args.command == "test-llm":
        cmd_test_llm(args)


if __name__ == "__main__":
    main()
