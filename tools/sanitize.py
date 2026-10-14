"""Turn raw router captures (captures/) into committable test fixtures.

Every value that could identify the house or open it is replaced:
credentials, Wi-Fi keys, serial numbers, phone number, public IP and MAC
addresses (MACs are remapped consistently so relations between files hold).
ASP pages are reduced to the handful of ``var`` lines the parsers read.

Run: python3 -I tools/sanitize.py
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SRC = ROOT / "captures"
DST = ROOT / "tests" / "fixtures"

SECRET_TAG = re.compile(
    r"pass|pwd|psk|key|secret|auth_username|OnuRegId|SerialNumber|"
    r"directory_number|register_uri|wps_device_pin",
    re.I,
)
MAC = re.compile(r"\b([0-9A-Fa-f]{2}[:-]){5}[0-9A-Fa-f]{2}\b")
PUBLIC_IP = re.compile(r"\b81\.\d{1,3}\.\d{1,3}\.\d{1,3}\b")

# Page variables the integration reads; everything else in a page is dropped.
PAGE_VARS = {
    "te_wifi.asp": ["sessionKey", "tef_assoc_state", "tef_assoc_time_left", "wifiActive",
                    "wifi5GActive", "unitNum"],
    "te_wifi_guest.asp": ["sessionKey", "ssid_id", "acc_pt_id", "wifiSSIDName", "wifiActive",
                          "wifiAuthMode", "wifiPassword", "wpaPskKey", "unitNum", "uniqueSSID"],
}

_mac_map: dict[str, str] = {}


def fake_mac(match: re.Match[str]) -> str:
    original = match.group(0).upper().replace("-", ":")
    if original not in _mac_map:
        _mac_map[original] = "02:00:00:00:00:%02X" % (len(_mac_map) + 1)
    fake = _mac_map[original]
    sep = "-" if "-" in match.group(0) else ":"
    out = fake.replace(":", sep)
    return out if match.group(0).isupper() or not match.group(0).islower() else out.lower()


def scrub_text(text: str) -> str:
    text = MAC.sub(fake_mac, text)
    # Some hostnames embed the MAC without separators (e.g. the TV decoder).
    for original, fake in _mac_map.items():
        text = re.sub(original.replace(":", ""), fake.replace(":", ""), text, flags=re.I)
    return PUBLIC_IP.sub("203.0.113.7", text)


def sanitize_xml(text: str) -> str:
    def repl(m: re.Match[str]) -> str:
        tag, value = m.group(1), m.group(2)
        if SECRET_TAG.search(tag) and value.strip():
            return f"<{tag}>REDACTED</{tag}>"
        return m.group(0)

    text = re.sub(r"<(\w+)>([^<]*)</\1>", repl, text)
    return scrub_text(text)


def sanitize_page(name: str, text: str) -> str:
    lines = []
    for var in PAGE_VARS[name]:
        m = re.search(rf"var\s+{var}\s*=\s*([^;\n]*);", text)
        if m is None:
            continue
        value = m.group(1)
        if SECRET_TAG.search(var):
            value = "'REDACTED'" if var != "sessionKey" else "'0123456789'"
        lines.append(f"var {var} = {value};")
    return scrub_text("<script>\n" + "\n".join(lines) + "\n</script>\n")


def main() -> int:
    DST.mkdir(parents=True, exist_ok=True)
    for path in sorted(SRC.glob("cbGet*.xml")):
        (DST / path.name).write_text(sanitize_xml(path.read_text(encoding="latin-1")))
    for name in PAGE_VARS:
        src = SRC / name
        if src.exists():
            (DST / name).write_text(sanitize_page(name, src.read_text(encoding="latin-1")))
    # Self-check: nothing that looks like a secret may survive.
    leaks = []
    for f in DST.iterdir():
        body = f.read_text()
        if PUBLIC_IP.search(body) or re.search(r"ASKY[0-9A-F]{8}", body):
            leaks.append(f.name)
    if leaks:
        print("LEAK in", leaks)
        return 1
    print(f"{len(list(DST.iterdir()))} fixtures written, {len(_mac_map)} MACs remapped")
    return 0


if __name__ == "__main__":
    sys.exit(main())
