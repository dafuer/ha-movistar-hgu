"""Pure functions turning router responses into models.

Every ``cbGet*`` response looks like::

    <Response><cbGetX> ...rows or flat fields... <Result>0</Result></cbGetX></Response>

``Result`` 0 means success. Anything that is not that shape (for instance the
HTML 400 page the router serves when the session is gone) raises
``HguResponseError``; the client turns HTTP 400 into a session error before it
reaches here.
"""

from __future__ import annotations

import html
import re
from collections.abc import Iterable
from xml.etree.ElementTree import Element, ParseError

from defusedxml.ElementTree import fromstring

from .errors import HguResponseError
from .models import (
    VLAN_ROLES,
    AccessPoint,
    FiberInfo,
    Host,
    InterfaceCounters,
    IotInstall,
    PortMapping,
    Statistics,
    SyslogConfig,
    SystemInfo,
    VoiceLine,
    WanInterface,
    WanRole,
    WifiRadio,
)

_RESULT_OK = "0"
# XML 1.0 forbids most C0 control characters; the router emits some raw
# (e.g. the binary <OnuRegId> in cbGetGPONInfo), so they are dropped first.
_INVALID_XML_CHARS = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f]")


def _body(text: str) -> Element:
    """Return the ``<cbGetX>`` element after checking ``Result``."""
    try:
        root = fromstring(_INVALID_XML_CHARS.sub("", text).strip())
    except (ParseError, ValueError) as err:
        raise HguResponseError(f"Not an XML response: {text[:80]!r}") from err
    if root.tag != "Response" or len(root) == 0:
        raise HguResponseError(f"Unexpected root element {root.tag!r}")
    body = root[0]
    result = body.findtext("Result")
    if result != _RESULT_OK:
        raise HguResponseError(f"{body.tag} returned Result={result!r}")
    return body


def _fields(element: Element) -> dict[str, str]:
    return {child.tag: (child.text or "").strip() for child in element if len(child) == 0}


def _rows(body: Element, tag: str) -> Iterable[dict[str, str]]:
    return (_fields(row) for row in body.iter(tag))


def _int(value: str | None, default: int = 0) -> int:
    try:
        return int(float(value)) if value not in (None, "") else default
    except ValueError:
        return default


def _float(value: str | None) -> float | None:
    try:
        return float(value) if value not in (None, "") else None
    except ValueError:
        return None


def _ip(value: str | None) -> str | None:
    return value if value and value not in ("0.0.0.0", "::") else None


def parse_summary(text: str) -> SystemInfo:
    f = _fields(_body(text))
    load = tuple(_float(f.get(k)) or 0.0 for k in ("AvgLoad1", "AvgLoad5", "AvgLoad15"))
    return SystemInfo(
        model=f.get("ModelName") or f.get("DeviceModel", ""),
        manufacturer=f.get("DeviceManufacturer", ""),
        hardware_version=f.get("HWVersion", ""),
        firmware=f.get("SWVersion", ""),
        firmware_backup=f.get("SWVersionS", ""),
        uptime_s=_int(f.get("SysUptime")),
        cpu_pct=_int(f.get("CpuUsage")),
        memory_pct=_int(f.get("MemUsage")),
        load=(load[0], load[1], load[2]),
        total_ram_kb=_int(f.get("TotalRam")),
        free_ram_kb=_int(f.get("FreeRam")),
        onu_state=_int(f.get("OnuStatus")),
        serial_number=f.get("OnuSerialNumber", ""),
    )


def parse_gpon(text: str) -> FiberInfo:
    f = _fields(_body(text))
    return FiberInfo(
        rx_power_dbm=_float(f.get("OpticalRxPower")) or 0.0,
        tx_power_dbm=_float(f.get("OpticalTxPower")) or 0.0,
        temperature_c=_float(f.get("OpticalTemperature")) or 0.0,
        voltage_v=_float(f.get("OpticalVoltage")) or 0.0,
        bias_current_ma=_float(f.get("OpticalBiasCurrent")) or 0.0,
        onu_state=_int(f.get("OnuStatus") or f.get("OmciGponState")),
        pon_uptime_s=_int(f.get("OmciPonUpTime")),
        rx_power_low_dbm=_float(f.get("OmciRxPowerLowerThreshold")),
        rx_power_high_dbm=_float(f.get("OmciRxPowerUpperThreshold")),
    )


def parse_wan_interfaces(text: str) -> list[WanInterface]:
    wans = []
    for row in _rows(_body(text), "mll_wanconn_data"):
        vlan = _int(row.get("vlanid"), -1)
        wans.append(
            WanInterface(
                name=row.get("name", ""),
                vlan=vlan,
                role=VLAN_ROLES.get(vlan, WanRole.OTHER),
                connected=row.get("opr_status") == "1" and row.get("ipv4_opr_status") == "1",
                ipv4=_ip(row.get("dis_ipv4_addr")),
                gateway=_ip(row.get("dis_ipv4_gw")),
            )
        )
    return wans


def _counters(row: dict[str, str]) -> InterfaceCounters:
    return InterfaceCounters(
        name=row.get("name", ""),
        up=(row.get("opr_status") or row.get("opr_state")) == "1",
        rx_bytes=_int(row.get("rx_byte")),
        tx_bytes=_int(row.get("tx_byte")),
        rx_packets=_int(row.get("rx_pkt")),
        tx_packets=_int(row.get("tx_pkt")),
        rx_errors=_int(row.get("rx_pkt_err")),
        tx_errors=_int(row.get("tx_pkt_err")),
        rx_drops=_int(row.get("rx_pkt_discard")),
        tx_drops=_int(row.get("tx_pkt_discard")),
    )


def parse_statistics(text: str) -> Statistics:
    body = _body(text)
    return Statistics(
        ethernet=[_counters(r) for r in _rows(body, "dpm_cfg_eth")],
        ip_interfaces=[_counters(r) for r in _rows(body, "rtm_cfg_ip_intf")],
    )


def parse_hosts(text: str) -> list[Host]:
    hosts = []
    for row in _rows(_body(text), "rtm_cfg_host"):
        mac = row.get("mac_addr", "").upper().replace("-", ":")
        if not mac:
            continue
        hosts.append(
            Host(
                mac=mac,
                ip=_ip(row.get("ipv4_addr")),
                hostname=row.get("hostname") or None,
                active=row.get("is_active") == "1",
                # intf_type 1 = Ethernet, 2 = Wi-Fi (as shown by `show map_info`).
                wired=row.get("intf_type") == "1",
                lease_remaining_s=_int(row.get("dhcpv4_lease_remaining"), -1)
                if row.get("dhcpv4_lease_remaining")
                else None,
            )
        )
    return hosts


def parse_wifi_radio(text: str) -> WifiRadio:
    row = next(iter(_rows(_body(text), "dpm_cfg_wifi")), None)
    if row is None:
        raise HguResponseError("cbGetWifi without dpm_cfg_wifi")
    return WifiRadio(
        index=_int(row.get("dpm_cfg_wifi_id")),
        enabled=row.get("radio_adm_state") == "1",
        up=row.get("radio_opr_status") == "1",
        channel=_int(row.get("opr_channel")),
        auto_channel=row.get("auto_channel") == "1",
    )


def parse_access_point(text: str) -> AccessPoint:
    row = next(iter(_rows(_body(text), "dpm_cfg_wifi_acc_pt")), None)
    if row is None:
        raise HguResponseError("cbGetWifiAccPt without dpm_cfg_wifi_acc_pt")
    # Only whitelisted, non-secret fields are copied out of ``row``.
    return AccessPoint(
        index=_int(row.get("dpm_cfg_wifi_acc_pt_id")),
        radio=_int(row.get("dpm_cfg_wifi_id")),
        ssid=row.get("ssid", ""),
        enabled=row.get("adm_state") == "1",
        up=row.get("opr_status") == "1",
        hidden=row.get("ssid_hide") == "1",
        isolated=row.get("isolation") == "1",
    )


def parse_port_mappings(text: str) -> list[PortMapping]:
    return [
        PortMapping(
            description=row.get("desc", ""),
            enabled=row.get("adm_state") == "1",
            internal_ip=row.get("int_ip_addr", ""),
            external_port_min=_int(row.get("ext_l4_port_min_value")),
            external_port_max=_int(row.get("ext_l4_port_max_value")),
            protocol=_int(row.get("l4_protocol_value")),
        )
        for row in _rows(_body(text), "rtm_cfg_nat_port_mapping")
    ]


def parse_upnp(text: str) -> bool:
    row = next(iter(_rows(_body(text), "upnp_cfg")), {})
    return row.get("adm_state") == "1"


def parse_syslog(text: str) -> SyslogConfig:
    row = next(iter(_rows(_body(text), "syslog_module_info")), {})
    return SyslogConfig(
        enabled=row.get("syslog_enable") == "1",
        mode=_int(row.get("syslog_mode")),
        remote_server=row.get("remote_svr", ""),
        remote_port=_int(row.get("remote_port"), 514),
        remote_severity=_int(row.get("remote_severity"), 7),
        bind_interface=_int(row.get("bind_interface"), -1),
    )


def parse_voice_line(text: str) -> VoiceLine:
    row = next(iter(_rows(_body(text), "tr104_issue1_vp_line")), {})
    return VoiceLine(
        enabled=row.get("adm_state") == "1",
        status=row.get("clt_status", ""),
        call_status=row.get("call_status", ""),
    )


# --- ASP pages ---------------------------------------------------------------

_VAR = r"var\s+{name}\s*=\s*(?:htmlDecode\()?'([^']*)'"


def page_var(page: str, name: str) -> str | None:
    """Return a ``var name = '...'`` string from an ASP page, HTML-decoded."""
    m = re.search(_VAR.format(name=re.escape(name)), page)
    return html.unescape(m.group(1)) if m else None


def is_login_page(page: str) -> bool:
    return "te_acceso_router" in page and "sessionKey" not in page


def parse_iot_install(page: str) -> IotInstall:
    remaining = _int(page_var(page, "tef_assoc_time_left"))
    return IotInstall(
        active=page_var(page, "tef_assoc_state") == "1" and remaining > 0,
        remaining_s=remaining,
    )
