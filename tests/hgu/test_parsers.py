"""Parser tests against sanitized captures from a real RTF8316VW (2026-10-15)."""

from __future__ import annotations

import pytest

from custom_components.movistar_hgu.hgu import parsers
from custom_components.movistar_hgu.hgu.errors import HguResponseError
from custom_components.movistar_hgu.hgu.models import WanRole

from .conftest import fixture


def test_summary() -> None:
    info = parsers.parse_summary(fixture("cbGetSummary.xml"))
    assert info.model == "RTF8316VW"
    assert info.manufacturer == "ASKEY"
    assert info.hardware_version == "REV4"
    assert info.firmware == "GL_g1.18_R8316_V2.19"
    assert info.uptime_s == 706402
    assert info.cpu_pct == 5
    assert info.memory_pct == 44
    assert info.load == (7.14, 7.22, 7.26)
    assert info.onu_state == 5
    assert info.serial_number == "REDACTED"  # sanitized fixture
    assert "serial" not in repr(info)


def test_gpon() -> None:
    fiber = parsers.parse_gpon(fixture("cbGetGPONInfo.xml"))
    assert fiber.rx_power_dbm == pytest.approx(-18.327, abs=1e-3)
    assert fiber.tx_power_dbm == pytest.approx(2.878, abs=1e-3)
    assert fiber.temperature_c == pytest.approx(59.47, abs=1e-2)
    assert fiber.voltage_v == pytest.approx(3.2719)
    assert fiber.bias_current_ma == pytest.approx(9.572)
    assert fiber.onu_state == 5
    assert fiber.pon_uptime_s == 706310
    assert fiber.rx_power_low_dbm == -28.0
    assert fiber.rx_power_high_dbm == -8.0


def test_wan_interfaces() -> None:
    wans = parsers.parse_wan_interfaces(fixture("cbGetWanIPIntf.xml"))
    by_role = {w.role: w for w in wans}
    assert set(by_role) == {WanRole.INTERNET, WanRole.VOICE, WanRole.IPTV}
    assert by_role[WanRole.INTERNET].ipv4 == "203.0.113.7"
    assert by_role[WanRole.INTERNET].vlan == 6
    assert by_role[WanRole.VOICE].ipv4 == "10.22.195.244"
    assert by_role[WanRole.VOICE].name == "ip3"
    assert all(w.connected for w in wans)


def test_statistics() -> None:
    stats = parsers.parse_statistics(fixture("cbGetStatistic.xml"))
    eth = {c.name: c for c in stats.ethernet}
    assert eth["eth0.5"].up and eth["eth0.5"].tx_bytes == 82441262656
    assert eth["eth0.2"].up is False
    ip = {c.name: c for c in stats.ip_interfaces}
    assert ip["ip2"].rx_bytes == 3552396457
    assert ip["ip2"].rx_packets == 8506278
    assert ip["ip3"].tx_bytes == 968670


def test_hosts() -> None:
    hosts = parsers.parse_hosts(fixture("cbGetLanHostList.xml"))
    assert len(hosts) == 2
    archer = next(h for h in hosts if h.hostname == "Archer_C9")
    assert archer.ip == "192.168.1.34"
    assert archer.active and archer.wired
    assert archer.mac == archer.mac.upper()


def test_wifi_radio() -> None:
    radio24 = parsers.parse_wifi_radio(fixture("cbGetWifi.xml"))
    radio5 = parsers.parse_wifi_radio(fixture("cbGetWifi__dpm_cfg_wifi_0i-1.xml"))
    assert (radio24.index, radio24.enabled, radio24.channel) == (0, True, 1)
    assert (radio5.index, radio5.channel) == (1, 100)


def test_access_point_never_keeps_key() -> None:
    ap = parsers.parse_access_point(fixture("cbGetWifiAccPt__dpm_cfg_wifi_acc_pt_0i-2.xml"))
    assert ap.index == 2
    assert ap.ssid == "MOVISTAR-0000-INV-WIFI7"
    assert ap.enabled is False
    assert "REDACTED" not in repr(ap)
    assert not any("key" in f or "pass" in f for f in ap.__dataclass_fields__)


def test_port_mappings_include_dmz() -> None:
    mappings = parsers.parse_port_mappings(fixture("cbGetNatPortMapping.xml"))
    assert [(m.description, m.internal_ip, m.enabled) for m in mappings] == [
        ("DMZ", "192.168.1.34", True)
    ]


def test_small_configs() -> None:
    assert parsers.parse_upnp(fixture("cbGetUpnpCfg.xml")) is False
    syslog = parsers.parse_syslog(fixture("cbGetSyslog.xml"))
    assert (syslog.enabled, syslog.remote_server, syslog.remote_port) == (False, "", 514)
    voice = parsers.parse_voice_line(fixture("cbGetVoiceLine.xml"))
    assert voice.enabled is False and voice.status == "Disabled"
    assert "REDACTED" not in repr(voice)


def test_page_vars() -> None:
    page = fixture("te_wifi.asp")
    assert parsers.page_var(page, "sessionKey") == "0123456789"
    assert parsers.parse_iot_install(page).remaining_s == 0
    assert parsers.parse_iot_install(page).active is False


def test_error_result_raises() -> None:
    bad = "<Response><cbGetSummary><Result>1</Result></cbGetSummary></Response>"
    with pytest.raises(HguResponseError):
        parsers.parse_summary(bad)


def test_not_xml_raises() -> None:
    with pytest.raises(HguResponseError):
        parsers.parse_summary("<HTML><BODY>Access Error: 400</BODY></HTML>")


def test_binary_garbage_in_a_field_is_tolerated() -> None:
    """The real cbGetGPONInfo carries raw bytes in <OnuRegId> (control chars)."""
    raw = fixture("cbGetGPONInfo.xml").replace(
        "<OnuRegId>REDACTED</OnuRegId>", "<OnuRegId>\xf2\x01\x80\x08\x06\x95\x95</OnuRegId>"
    )
    assert "\x01" in raw
    assert parsers.parse_gpon(raw).onu_state == 5


def test_iot_state_lives_in_the_5ghz_block() -> None:
    """te_wifi.asp declares tef_assoc_* twice: 2.4 GHz first, 5 GHz (the real one) later."""
    page = (
        "var tef_assoc_state = '0';\nvar tef_assoc_time_left = '0';\n"
        "function getWifi5GStatus() {\n"
        "var tef_assoc_state = '1';\nvar tef_assoc_time_left = '58';\n}"
    )
    iot = parsers.parse_iot_install(page)
    assert iot.active is True
    assert iot.remaining_s == 58
