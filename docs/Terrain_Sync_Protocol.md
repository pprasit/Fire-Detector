# Terrain synchronization contract

The station advertises its installed terrain in the initial TLS `hello`:

```json
{
  "payload": {
    "latitude": 18.853,
    "longitude": 98.958,
    "azimuth_north_offset_deg": 90.0,
    "terrain": {
      "available": true,
      "format": "geotiff",
      "sha256": "<64 lowercase hex characters>",
      "size_bytes": 174982
    }
  }
}
```

The receiver should use the installation GPS to find or build a DEM covering
the configured operating radius. If the advertised SHA-256 already matches,
the normal authenticated response needs no terrain field. Otherwise the
receiver returns this field in `auth_result.payload`:

```json
{
  "type": "auth_result",
  "payload": {
    "authenticated": true,
    "terrain": {
      "format": "geotiff",
      "sha256": "<64 lowercase hex characters>",
      "size_bytes": 1234567,
      "download_url": "https://<configured-receiver-host>:8443/api/v1/terrain/<signed-id>"
    }
  }
}
```

The URL must use HTTPS and the same hostname configured for the receiver. A
short-lived signed URL is recommended. The station limits the response to
128 MiB, verifies its exact size and SHA-256, checks the GeoTIFF georeference
and station coverage, then replaces the local DEM atomically. A failed check
leaves the previous DEM untouched and reconnects with exponential backoff.

The station renders a north-up local east/north grid at 30 m resolution. Rows
increase southward and columns increase eastward. Cell IDs use
`R####C####`. True-north azimuth is converted to the device frame by:

```text
device_azimuth = (true_azimuth + azimuth_north_offset_deg) mod 360
```
