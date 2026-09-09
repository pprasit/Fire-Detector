#!/usr/bin/env python3
"""Read Mount status and subscribe to telemetry over the local Unix socket."""

from __future__ import annotations

import json
import socket
import uuid

SOCKET_PATH = "/run/fire-detector/mount-agent.sock"


def command(action: str, params: dict | None = None) -> dict:
    return {
        "version": "1.0",
        "type": "command",
        "message_id": str(uuid.uuid4()),
        "action": action,
        "params": params or {},
    }


def send(stream, message: dict) -> None:
    stream.write(json.dumps(message, separators=(",", ":")).encode("utf-8") + b"\n")
    stream.flush()


def receive(stream) -> dict:
    line = stream.readline()
    if not line:
        raise ConnectionError("Mount Agent closed the connection.")
    return json.loads(line)


def main() -> None:
    with socket.socket(socket.AF_UNIX, socket.SOCK_STREAM) as client:
        client.connect(SOCKET_PATH)
        stream = client.makefile("rwb")

        send(stream, command("mount.get_status"))
        status = receive(stream)
        print("Status response:")
        print(json.dumps(status, indent=2))

        send(
            stream,
            command(
                "subscribe",
                {"topics": ["axis.telemetry", "sensor.status"], "interval_ms": 500},
            ),
        )
        print("Subscription response:")
        print(json.dumps(receive(stream), indent=2))

        print("Next 10 telemetry messages:")
        for _ in range(10):
            print(json.dumps(receive(stream), indent=2))

        send(stream, command("unsubscribe"))
        print(json.dumps(receive(stream), indent=2))


if __name__ == "__main__":
    main()
