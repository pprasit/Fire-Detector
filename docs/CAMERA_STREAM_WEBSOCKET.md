# Camera stream ingest and central frame pool

The physical-camera service is the only live-image ingest owner. It publishes
each thermal and visible frame once to the Station through either the producer
WebSocket or the HTTP compatibility API. The Station replaces the retained
latest frame in its central `CameraFramePool`; it never builds a playback FIFO.

All application consumers read from that pool:

- Camera View uses `/api/camera-mjpeg/<source>/<camera>`.
- Pointing Model uses `/api/camera-frame/latest/<source>/<camera>?preview=pointing`.
- Metadata panels use `/api/camera-stream/metadata-stream/<source>/<camera>`.
- The outbound MediaMTX publisher reads the loopback MJPEG pool endpoint.

Dashboard modules must not open `/dev/video*`, RTSP, or any camera vendor API.
Multiple Station endpoints are views of the same retained frame, not additional
connections to the camera source. `GET /api/camera-stream` exposes the pool
contract, freshness, retained-frame count, and centrally controlled profiles.

The producer WebSocket endpoint remains available at
`/ws/camera-stream?role=producer`. Read-only protocol clients may also use the
viewer role, although the bundled dashboards use the pool endpoints above.

Each frame is a JSON text message. `metadata` is intentionally extensible while
the camera contract is being finalized.

```json
{
  "type": "frame",
  "camera": "thermal",
  "image": {
    "mime_type": "image/jpeg",
    "data": "BASE64_ENCODED_IMAGE"
  },
  "metadata": {
    "captured_at": "2026-08-05T15:07:21.020Z",
    "resolution": "640x512",
    "zoom_x": 1.41
  }
}
```

`camera` must be `thermal` or `visible`. An image may alternatively be supplied
as `image.data_url`. The relay currently accepts JSON messages up to 16 MiB.
The producer should reconnect after a disconnect; viewers receive connection
status messages and the latest frame for each camera after connecting.

## Recommended binary WebSocket producer (60 FPS)

Do not represent image bytes as a JSON array of integers and do not Base64-encode
high-rate frames. Connect once to:

```text
ws://192.168.1.105:8000/ws/camera-stream?role=producer&source=live
```

Send one binary WebSocket message per frame with this wire layout:

```text
uint32_be header_length
header_length bytes of UTF-8 JSON
remaining bytes: encoded JPEG or PNG payload
```

Example header (the image bytes are not inside JSON):

```json
{
  "camera": "thermal",
  "mime_type": "image/jpeg",
  "sha256": "64-lowercase-hex-characters",
  "metadata": {
    "producer_sequence": 1234,
    "captured_at": "2026-08-11T10:30:00.000Z",
    "width": 640,
    "height": 512
  }
}
```

`sha256` is optional but recommended when application-level integrity evidence
is required. WebSocket over TCP already provides ordered, reliable delivery;
the sequence lets the receiver/operator detect producer-side frame gaps. The
complete client is `API-Doc/examples/04_publish_camera_binary_ws.py`.

Disable WebSocket per-message compression (`compression=None` in the Python
client). JPEG and PNG are already compressed, so attempting to compress every
frame again wastes CPU and can cut the achievable frame rate substantially.

```bash
.venv/bin/python API-Doc/examples/04_publish_camera_binary_ws.py \
  --camera thermal --frame thermal-frame.jpg --fps 60
```

Use encoded images. A 1280x720 RGB raw frame is about 2.64 MiB, or roughly
158 MiB/s at 60 FPS before protocol overhead. If radiometric Thermal values are
required, define a separate raw-16-bit scientific-data channel rather than
mixing sensor values with the display-image stream.

`GET /api/camera-stream` reports whether a producer is connected, the last-frame
timestamp, and the available stream names.

## HTTP compatibility API

The camera module can publish raw encoded frames without connecting either
camera to the main system. Send each JPEG or PNG as the request body:

```text
POST /api/camera-stream/frame/thermal?source=live
Content-Type: image/jpeg
X-Camera-Metadata: {"captured_at":"2026-08-11T09:30:00.000Z","width":640,"height":512}

<raw JPEG bytes>
```

Use `/visible` for the visible camera. The endpoint returns HTTP 202 and the
assigned relay sequence. It accepts frames up to 16 MiB. The relay retains only
the newest frame per camera and wakes viewers as soon as it arrives; this avoids
queue growth when a producer publishes at approximately 60 FPS. Reuse HTTP
connections (keep-alive) at high frame rates. The existing producer WebSocket
remains supported when a persistent JSON protocol is preferred.

Dashboard clients consume the server-originated MJPEG endpoints
`/api/camera-mjpeg/live/thermal` and `/api/camera-mjpeg/live/visible`; these now
read exclusively from the external-module relay and never open `/dev/video0` or
an RTSP camera directly.

### Complete curl examples

```bash
# Thermal
curl -X POST "http://192.168.1.105:8000/api/camera-stream/frame/thermal?source=live" \
  -H "Content-Type: image/jpeg" \
  -H 'X-Camera-Metadata: {"captured_at":"2026-08-11T10:30:00.000Z","width":640,"height":512,"producer_sequence":1}' \
  --data-binary @thermal-frame.jpg

# Visible
curl -X POST "http://192.168.1.105:8000/api/camera-stream/frame/visible?source=live" \
  -H "Content-Type: image/jpeg" \
  -H 'X-Camera-Metadata: {"captured_at":"2026-08-11T10:30:00.000Z","width":1280,"height":720,"producer_sequence":1}' \
  --data-binary @visible-frame.jpg
```

Successful response:

```json
{"camera":"thermal","ok":true,"sequence":1234,"source":"live"}
```

Errors use JSON with an `error` string and an appropriate HTTP status: `400`
for invalid metadata/source, `413` for an empty or oversized frame, `415` for
an unsupported content type, and `404` for an unknown camera.

### 60 FPS Python example

The complete runnable client is
`API-Doc/examples/03_publish_camera_frames.py`:

```bash
.venv/bin/python API-Doc/examples/03_publish_camera_frames.py \
  --host 192.168.1.105 --port 8000 \
  --camera thermal --frame thermal-frame.jpg --fps 60
```

Run a second process with `--camera visible` for the visible feed. Real camera
modules should replace the sample-file read with their encoder output while
preserving the endpoint, content type, metadata, pacing, and error handling.
The endpoint expects an already encoded JPEG/PNG, not a raw thermal sensor array.
