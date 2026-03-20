"""
ONVIF Camera Discovery — finds cameras on the local network using
the WS-Discovery protocol (via onvif-zeep or a lightweight UDP probe).

Strategy (graceful degradation)
────────────────────────────────
1. Try onvif-zeep (WSDiscovery) for full ONVIF support.
2. If onvif-zeep is not installed, fall back to a raw WS-Discovery
   UDP multicast probe (no external dependency).
3. For each discovered device, attempt to retrieve a media profile
   and build an RTSP URL.

The result is a list of CameraConfig dicts suitable for CameraManager.
"""

import asyncio
import logging
import re
import socket
import struct
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)

# ── WS-Discovery constants ────────────────────────────────────────────────────

WSD_MULTICAST_ADDR = "239.255.255.250"
WSD_PORT           = 3702
WSD_TIMEOUT        = 3.0     # seconds to collect replies

WSD_PROBE = """<?xml version="1.0" encoding="UTF-8"?>
<e:Envelope xmlns:e="http://www.w3.org/2003/05/soap-envelope"
            xmlns:w="http://schemas.xmlsoap.org/ws/2004/08/addressing"
            xmlns:d="http://schemas.xmlsoap.org/ws/2005/04/discovery"
            xmlns:dn="http://www.onvif.org/ver10/network/wsdl">
  <e:Header>
    <w:MessageID>uuid:{msg_id}</w:MessageID>
    <w:To>urn:schemas-xmlsoap-org:ws:2005:04:discovery</w:To>
    <w:Action>http://schemas.xmlsoap.org/ws/2005/04/discovery/Probe</w:Action>
  </e:Header>
  <e:Body>
    <d:Probe>
      <d:Types>dn:NetworkVideoTransmitter</d:Types>
    </d:Probe>
  </e:Body>
</e:Envelope>"""


# ── Raw UDP WS-Discovery probe ────────────────────────────────────────────────

def _udp_wsdiscovery_probe(timeout: float = WSD_TIMEOUT) -> List[Dict]:
    """
    Send a WS-Discovery multicast probe and collect responses.
    Returns a list of dicts: {xaddrs: [...], types: str, name: str}
    """
    msg_id = str(uuid.uuid4())
    probe  = WSD_PROBE.format(msg_id=msg_id).encode("utf-8")
    results = []

    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM, socket.IPPROTO_UDP)
        sock.setsockopt(socket.IPPROTO_IP, socket.IP_MULTICAST_TTL, 2)
        sock.settimeout(timeout)
        sock.sendto(probe, (WSD_MULTICAST_ADDR, WSD_PORT))

        end_time = asyncio.get_event_loop().time() if False else \
                   __import__("time").time() + timeout

        while __import__("time").time() < end_time:
            try:
                data, addr = sock.recvfrom(65535)
                text = data.decode("utf-8", errors="ignore")
                xaddrs = re.findall(r'<[^>]*XAddrs[^>]*>(.*?)</[^>]*XAddrs>', text, re.DOTALL)
                types  = re.findall(r'<[^>]*Types[^>]*>(.*?)</[^>]*Types>',  text, re.DOTALL)
                name   = re.findall(r'<[^>]*FriendlyName[^>]*>(.*?)</[^>]*FriendlyName>', text)
                if xaddrs:
                    results.append({
                        "ip":      addr[0],
                        "xaddrs": [x.strip() for x in xaddrs[0].split()],
                        "types":  types[0].strip() if types else "",
                        "name":   name[0].strip()  if name  else addr[0],
                    })
            except socket.timeout:
                break
            except Exception:
                continue

        sock.close()

    except Exception as exc:
        logger.debug(f"ONVIF UDP probe error: {exc}")

    return results


# ── onvif-zeep based discovery (richer, requires package) ────────────────────

def _zeep_discover(username: str = "", password: str = "") -> List[Dict]:
    """
    Use onvif-zeep WSDiscovery + ONVIF device services.
    Returns list of CameraConfig-compatible dicts.
    """
    try:
        from wsdiscovery.discovery import ThreadedWSDiscovery as WSDiscovery
    except ImportError:
        logger.debug("wsdiscovery not available — skipping zeep discovery")
        return []

    discovered = []
    try:
        wsd = WSDiscovery()
        wsd.start()
        services = wsd.searchServices(timeout=WSD_TIMEOUT)
        wsd.stop()
    except Exception as exc:
        logger.warning(f"WSDiscovery error: {exc}")
        return []

    for svc in services:
        xaddrs = [str(a) for a in (svc.getXAddrs() or [])]
        if not xaddrs:
            continue

        device_url = xaddrs[0]
        ip = re.search(r"://([^:/]+)", device_url)
        ip = ip.group(1) if ip else device_url

        rtsp_url = _get_rtsp_url_zeep(device_url, username, password)
        if rtsp_url:
            discovered.append({
                "ip":       ip,
                "xaddrs":  xaddrs,
                "name":    ip,
                "rtsp":    rtsp_url,
            })

    return discovered


def _get_rtsp_url_zeep(device_url: str,
                        username: str, password: str) -> Optional[str]:
    """Connect to an ONVIF device and retrieve the first RTSP stream URL."""
    try:
        from onvif import ONVIFCamera  # type: ignore
        import re as _re
        ip   = _re.search(r"://([^:/]+)",   device_url).group(1)
        port = _re.search(r":(\d+)/",       device_url)
        port = int(port.group(1)) if port else 80

        cam = ONVIFCamera(ip, port, username or "admin", password or "",
                          no_cache=True)
        media = cam.create_media_service()
        token = media.GetProfiles()[0].token
        uri   = media.GetStreamUri({
            "StreamSetup": {
                "Stream": "RTP-Unicast",
                "Transport": {"Protocol": "RTSP"},
            },
            "ProfileToken": token,
        }).Uri
        # Inject credentials
        if username and "@" not in uri:
            uri = uri.replace("rtsp://", f"rtsp://{username}:{password}@")
        return uri

    except Exception as exc:
        logger.debug(f"ONVIF GetStreamUri failed ({device_url}): {exc}")
        return None


# ── Public API ────────────────────────────────────────────────────────────────

class ONVIFDiscovery:
    """
    Discover ONVIF cameras on the local network.

    Usage:
        discovery = ONVIFDiscovery(username="admin", password="pass")
        cameras   = await discovery.discover()
        # cameras → List[dict] ready for CameraManager.add_camera()
    """

    def __init__(self, username: str = "", password: str = ""):
        self.username = username
        self.password = password

    async def discover(self) -> List[Dict]:
        """
        Run discovery in a thread pool (blocking network I/O).
        Returns a list of camera info dicts.
        """
        loop = asyncio.get_event_loop()
        results = await loop.run_in_executor(None, self._discover_sync)
        logger.info(f"ONVIF discovery: found {len(results)} camera(s)")
        return results

    def _discover_sync(self) -> List[Dict]:
        # Try rich zeep path first
        cameras = _zeep_discover(self.username, self.password)
        if cameras:
            return [self._to_config(c) for c in cameras]

        # Fall back to raw UDP probe
        raw = _udp_wsdiscovery_probe()
        result = []
        for r in raw:
            # For each discovered device try to get RTSP via zeep
            if r.get("xaddrs"):
                rtsp = _get_rtsp_url_zeep(
                    r["xaddrs"][0], self.username, self.password
                )
                if rtsp:
                    r["rtsp"] = rtsp
                    result.append(self._to_config(r))
                else:
                    # Build a guessed RTSP URL as last resort
                    ip = r["ip"]
                    guessed = f"rtsp://{self.username}:{self.password}@{ip}:554/stream1" \
                              if self.username else f"rtsp://{ip}:554/stream1"
                    r["rtsp"] = guessed
                    r["rtsp_guessed"] = True
                    result.append(self._to_config(r))

        return result

    @staticmethod
    def _to_config(info: Dict) -> Dict:
        """Convert discovery result to CameraManager add_camera() kwargs."""
        cam_id = f"onvif_{info['ip'].replace('.', '_')}"
        return {
            "camera_id": cam_id,
            "cam_type":  "ONVIF",
            "source":    info.get("rtsp", info["xaddrs"][0] if info.get("xaddrs") else ""),
            "extra": {
                "ip":            info["ip"],
                "name":          info.get("name", ""),
                "xaddrs":        info.get("xaddrs", []),
                "rtsp_guessed":  info.get("rtsp_guessed", False),
                "discovered_at": datetime.now(tz=timezone.utc).isoformat(),
            }
        }
