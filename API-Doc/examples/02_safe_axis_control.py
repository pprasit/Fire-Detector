#!/usr/bin/env python3
"""Control one axis with a lease and always issue a fail-safe stop.

Run this only in a cleared test area with an operator at the mount.
The example is intentionally blocked until ALLOW_MOTION is changed to True.
"""

from __future__ import annotations

import json
import socket
import uuid

SOCKET_PATH = "/run/fire-detector/mount-agent.sock"
ALLOW_MOTION = False


class MountClient:
    def __init__(self, socket_path: str) -> None:
        self._socket = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._socket.connect(socket_path)
        self._stream = self._socket.makefile("rwb")

    def call(self, action: str, params: dict | None = None, lease_id: str = "") -> dict:
        message = {
            "version": "1.0",
            "type": "command",
            "message_id": str(uuid.uuid4()),
            "action": action,
            "params": params or {},
        }
        if lease_id:
            message["control_lease_id"] = lease_id
        self._stream.write(json.dumps(message, separators=(",", ":")).encode() + b"\n")
        self._stream.flush()
        response = json.loads(self._stream.readline())
        if not response.get("ok"):
            raise RuntimeError(response.get("error", response))
        return response

    def close(self) -> None:
        self._stream.close()
        self._socket.close()


def main() -> None:
    mount = MountClient(SOCKET_PATH)
    lease_id = ""
    try:
        status = mount.call("mount.get_status")
        print(json.dumps(status["result"], indent=2))

        if not ALLOW_MOTION:
            print("Motion is locked. Review the status and set ALLOW_MOTION=True to proceed.")
            return

        lease = mount.call("control.acquire", {"lease_ms": 5000})
        lease_id = lease["result"]["lease_id"]

        mount.call("axis.enable", {"axis": "altitude"}, lease_id)
        result = mount.call(
            "axis.goto",
            {
                "axis": "altitude",
                "position_deg": 10.0,
                "max_velocity_deg_per_sec": 2.0,
            },
            lease_id,
        )
        print(json.dumps(result, indent=2))
    finally:
        # Stop and disable are lease-exempt so they remain available after a fault.
        try:
            mount.call("axis.stop", {"axis": "altitude"})
            mount.call("axis.disable", {"axis": "altitude"})
            if lease_id:
                mount.call("control.release", {"lease_id": lease_id})
        finally:
            mount.close()


if __name__ == "__main__":
    main()
