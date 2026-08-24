#!/usr/bin/env python3
"""Small read-only-by-default client for the local Mount Agent socket."""

from __future__ import annotations

import argparse
import json
import socket
import uuid


def main() -> int:
    parser = argparse.ArgumentParser(description="Send one JSON command to the local Mount Agent.")
    parser.add_argument("action", nargs="?", default="mount.get_status")
    parser.add_argument("--params", default="{}", help="JSON object containing command parameters")
    parser.add_argument("--lease-id", default="")
    parser.add_argument("--socket", default="/run/fire-detector/mount-agent.sock")
    args = parser.parse_args()
    params = json.loads(args.params)
    if not isinstance(params, dict):
        parser.error("--params must contain a JSON object")
    message = {
        "version": "1.0",
        "type": "command",
        "message_id": str(uuid.uuid4()),
        "action": args.action,
        "params": params,
    }
    if args.lease_id:
        message["control_lease_id"] = args.lease_id
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(args.socket)
        client.sendall(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        response = bytearray()
        while b"\n" not in response:
            chunk = client.recv(8192)
            if not chunk:
                raise ConnectionError("Mount Agent closed the connection.")
            response.extend(chunk)
    print(json.dumps(json.loads(response.partition(b"\n")[0]), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
