# Movistar HGU (Askey RTF8316VW) for Home Assistant

Local integration for the Movistar «Router WiFi 7» (Askey **RTF8316VW**, HGU).
It reads what the router's web interface knows about itself, and optionally its
SSH console, and exposes a few safe controls. It needs no cloud and no extra
hardware: only the router's admin password.

> Unofficial. Not affiliated with Movistar/Telefónica or Askey. Tested on
> hardware REV4, firmware `GL_g1.18_R8316_V2.19`.

## What you get

| Area | Entities |
|---|---|
| Connection | Internet / voice / TV connected; public, voice and TV IPs |
| Traffic | Downloaded and uploaded totals per VLAN (energy-style `total_increasing`, survive HA and router restarts, 32-bit counter wraps handled) and current rates in Mbit/s |
| Fiber | Optical RX/TX power, module temperature, voltage, laser bias, ONT state (O1–O7), fiber up since |
| System | Last boot, CPU, memory, load averages |
| Clients | Connected / wired / Wi-Fi counts; optional device trackers per MAC (disabled by default) |
| Wi-Fi & config | 2.4/5 GHz radios and channels, guest network, port mappings and DMZ, UPnP, remote syslog, router voice line |
| SSH (optional) | SoC and radio temperatures, TR-069 remote management status |

Controls (configuration category, not exposed to voice assistants):

- **Reboot router**
- **Start / cancel IoT install** — opens the router's 10-minute IoT pairing window
- **Guest Wi-Fi** switch — re-sends the current guest configuration, so the key is preserved

### Event: `movistar_hgu_wan_ip_changed`

Fired when a WAN interface (internet, voice or TV) shows a different IPv4 than
the last one seen. The last IP is remembered across router reboots and Home
Assistant restarts, so a router that comes back from a reboot with a new IP is
reported even though the entities went `unavailable` in between. Data:
`entry_id`, `role` (`internet` / `voice` / `iptv`), `previous`, `current`.

Typical use: an Asterisk/SIP setup that pins the voice VLAN IP
(`external_media_address`) loses audio when that IP changes.

```yaml
triggers:
  - trigger: event
    event_type: movistar_hgu_wan_ip_changed
    event_data:
      role: voice
```

## Installation

### HACS (custom repository)

1. HACS → ⋮ → *Custom repositories* → add `https://github.com/dafuer/ha-movistar-hgu`, type *Integration*.
2. Install **Movistar HGU**, restart Home Assistant.

### Manual

Copy `custom_components/movistar_hgu` into your `config/custom_components/` and restart.

## Configuration

*Settings → Devices & services → Add integration → Movistar HGU*, then enter the
router address (usually `192.168.1.1`) and the admin password (the one printed on
the router label unless you changed it).

Options: enable **SSH** to add temperatures and TR-069 status. The router's SSH
host key is pinned on the first connection.

Polling: 30 s for WAN and traffic, 5 min for system/fiber/clients, 1 h for
configuration data. Requests are serialized and reuse one web session.

## Safety

- The web client only reads `cbGet*` endpoints; the few writes are explicit
  methods behind the buttons and the switch.
- Wi-Fi keys, PPPoE/SIP credentials and serial numbers are never stored in
  entities, logs or diagnostics (diagnostics are redacted).
- SSH commands are an allow-list; console commands that print passwords are
  refused.
- Avoid repeated wrong passwords: the router has a brute-force lockout.

## Development

```sh
uv venv --python 3.13 && uv pip install pytest-homeassistant-custom-component asyncssh defusedxml ruff
.venv/bin/pytest && .venv/bin/ruff check .
```

`tools/capture.py` dumps raw router responses to `captures/` (git-ignored);
`tools/sanitize.py` turns them into the test fixtures, scrubbing credentials,
serials, MACs, public IP, phone number and SSID suffix.

## License

MIT
