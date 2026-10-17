#!/usr/bin/env python3
"""Read-only device inventory and station readiness check; never moves motors."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import socket
import sys
import uuid
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]


def usb_inventory(base=Path('/sys/bus/usb/devices')):
    devices = []
    for entry in sorted(base.glob('*')):
        def read(name):
            try:
                return (entry / name).read_text().strip()
            except OSError:
                return ''
        vendor, product = read('idVendor'), read('idProduct')
        if vendor and product:
            device = {'vendor': vendor, 'product': product,
                      'name': read('product'), 'serial': read('serial'),
                      'odrive': vendor == '1209' and product.startswith('0d3')}
            if device['odrive'] and device['serial']:
                try:
                    device['serial_decimal'] = str(int(device['serial'], 16))
                except ValueError:
                    pass
            devices.append(device)
    return devices


def discover_cameras(timeout=3.0):
    """ONVIF WS-Discovery probe on the local multicast network."""
    message = f'''<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
      xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
      xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
      xmlns:n="http://www.onvif.org/ver10/network/wsdl">
      <e:Header><w:MessageID>uuid:{uuid.uuid4()}</w:MessageID>
      <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
      <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action></e:Header>
      <e:Body><d:Probe><d:Types>n:NetworkVideoTransmitter</d:Types></d:Probe></e:Body>
      </e:Envelope>'''
    found = set()
    from time import monotonic
    with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.sendto(message.encode(), ('239.255.255.250', 3702))
        deadline = monotonic() + timeout
        while (remaining := deadline - monotonic()) > 0:
            sock.settimeout(remaining)
            try:
                packet, _ = sock.recvfrom(65535)
            except socket.timeout:
                break
            try:
                for node in ET.fromstring(packet).iter():
                    if node.tag.endswith('}XAddrs') and node.text:
                        # Only report device service addresses, never RTSP credentials.
                        from urllib.parse import urlsplit
                        for address in node.text.split():
                            url = urlsplit(address)
                            if url.hostname:
                                found.add(url.hostname)
            except (ET.ParseError, ValueError):
                continue
    return sorted(found)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--discover-cameras', action='store_true')
    parser.add_argument('--probe-odrive', action='store_true', help='Read ODrive serials and power; no calibration or motion')
    args = parser.parse_args()
    result = {'usb': usb_inventory(), 'serial_ports': sorted(str(p) for p in Path('/dev/serial/by-id').glob('*')),
              'video_devices': sorted(str(p) for p in Path('/dev').glob('video*'))}
    issues = []
    settings_path = ROOT / 'AppSetting.JSON'
    if settings_path.exists():
        settings = json.loads(settings_path.read_text())
        drives = settings.get('drive_serials', {})
        result['simulation_mode'] = settings.get('simulation_mode', {}).get('enabled', False)
        if not all(drives.get(k) for k in ('azimuth_serial', 'altitude_serial')):
            issues.append('Assign discovered ODrive serials to Azimuth and Altitude in Settings before hardware use.')
        if result['simulation_mode']:
            issues.append('Simulation is enabled; hardware acceptance is still required.')
    else:
        issues.append('Run bootstrap_iriv.sh to create local station settings.')
    if args.discover_cameras:
        result['onvif_camera_hosts'] = discover_cameras()
    if args.probe_odrive:
        # The dashboard owns the USB handles while running. Reuse its telemetry
        # instead of contending with the hardware I/O owner.
        from urllib.request import urlopen
        try:
            with urlopen('http://127.0.0.1:8000/api/status', timeout=2) as response:
                status = json.load(response)
            if status.get('simulation_mode') or status.get('run_mode') == 'simulation':
                issues.append('Dashboard is in simulation; USB inventory shows physical serials but live drive telemetry is unavailable.')
                result['odrives'] = []
            else:
                result['odrives'] = [
                    {'serial_decimal': str(axis['drive_serial']), 'axis': axis.get('label'),
                     'bus_voltage': axis.get('drive_vbus_voltage')}
                    for axis in status.get('axes', []) if axis.get('available') and axis.get('drive_serial')]
                if len(result['odrives']) < 2 or not status.get('has_bus_power'):
                    issues.append('Two powered ODrives are required for hardware operation.')
            result['odrive_probe_source'] = 'dashboard'
        except (OSError, ValueError):
            sys.path.insert(0, str(ROOT / 'src'))
            from fire_detector.odrive_connection import connect_many, read_status
            from contextlib import redirect_stdout
            try:
                with redirect_stdout(sys.stderr):
                    statuses = [read_status(d) for d in connect_many(count=2, timeout=5)]
                result['odrives'] = [{'serial_decimal': str(s.serial_number), 'bus_power': s.has_bus_power} for s in statuses]
                result['odrive_probe_source'] = 'usb'
                if len(statuses) < 2 or not all(s.has_bus_power for s in statuses):
                    issues.append('Two powered ODrives are required for hardware operation.')
            except Exception:
                issues.append('ODrive probe failed; check whether another service owns USB, then permissions, wiring and power.')
    camera_path = ROOT / 'camera_runtime/system_settings.json'
    if camera_path.exists():
        cameras = json.loads(camera_path.read_text()).get('cameras', {})
        for name in ('thermal', 'visible'):
            camera = cameras.get(name, {})
            if not camera.get('ip') or not camera.get('rtsp_url'):
                issues.append(f'Configure {name} camera IP and RTSP URL in local camera settings.')
    else:
        issues.append('Create camera_runtime/system_settings.json from its example.')
    result['issues'] = issues
    result['ready_for_acceptance'] = not issues
    print(json.dumps(result, indent=2))
    return 1 if issues else 0


if __name__ == '__main__':
    raise SystemExit(main())
