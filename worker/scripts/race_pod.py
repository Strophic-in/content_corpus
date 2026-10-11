"""Operator CLI for Race pods — for poking the API by hand, not used by workers.

    python worker/scripts/race_pod.py whoami | gpus | templates | pods
    python worker/scripts/race_pod.py deploy <slice_id> <template_id> [--disk 50]
    python worker/scripts/race_pod.py status <pod_id> [--wait]
    python worker/scripts/race_pod.py pause|resume|terminate <pod_id>

Reads RACE_API_KEY from the environment or the repo-root .env. Prints raw JSON on
purpose: the response shapes are undocumented and this is how we learn them.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "worker"))

from dotenv import load_dotenv  # noqa: E402

from corpus.race import RaceClient, RaceError  # noqa: E402

READY_STATES = {"ready", "running"}


def main() -> int:
    load_dotenv(ROOT / ".env")
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)
    for name in ("whoami", "gpus", "templates", "pods"):
        sub.add_parser(name)
    d = sub.add_parser("deploy")
    d.add_argument("slice_id")
    d.add_argument("template_id")
    d.add_argument("--disk", type=int, default=50)
    d.add_argument("--name", default="corpus-test")
    s = sub.add_parser("status")
    s.add_argument("pod_id")
    s.add_argument("--wait", action="store_true", help="poll until ready (10 min max)")
    for name in ("pause", "resume", "terminate"):
        sub.add_parser(name).add_argument("pod_id")
    args = p.parse_args()

    key = os.environ.get("RACE_API_KEY", "").strip()
    if not key:
        print("RACE_API_KEY is not set (env or .env at repo root)", file=sys.stderr)
        return 2
    race = RaceClient(key, os.environ.get("RACE_BASE_URL") or
                      "https://api.raceengineering.ai")

    try:
        if args.cmd == "deploy":
            out = race.deploy(args.slice_id, args.template_id, disk_gb=args.disk,
                              name=args.name)
        elif args.cmd == "status" and args.wait:
            deadline = time.monotonic() + 600
            while True:
                out = race.status(args.pod_id)
                state = str(out.get("deploy_state") or out.get("status") or "")
                print(f"{time.strftime('%H:%M:%S')} {state} "
                      f"{out.get('progress_percent', '')}", file=sys.stderr)
                if state.lower() in READY_STATES or out.get("ssh_command") \
                        or out.get("error") or time.monotonic() > deadline:
                    break
                time.sleep(10)
        elif args.cmd in ("status", "pause", "resume", "terminate"):
            out = getattr(race, args.cmd)(args.pod_id)
        else:
            out = getattr(race, args.cmd)()
    except RaceError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    print(json.dumps(out, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
