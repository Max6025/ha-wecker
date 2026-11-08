"""Durchlauf der HA-Wecker-Integration in einem echten Home-Assistant-Testkern."""
from __future__ import annotations

import copy

import pytest
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant
from homeassistant.helpers import entity_registry as er
from pytest_homeassistant_custom_component.common import MockConfigEntry
from pytest_homeassistant_custom_component.typing import ClientSessionGenerator

DOMAIN = "ha_wecker"

PAYLOAD = {
    "state": "2026-11-08T06:30:00+01:00",
    "next_alarm": {"id": 1, "name": "Arbeit", "time": "06:30", "enabled": True},
    "next_alarm_time": "06:30",
    "next_alarm_name": "Arbeit",
    "next_alarm_in": "12 Std 13 Min",
    "next_alarm_ts": 1762580000,
    "total_count": 2,
    "active_count": 1,
    "inactive_count": 1,
    "skipped_count": 0,
    "ringing": False,
    "ringing_id": None,
    "snoozed": False,
    "alarms": [
        {
            "id": 1, "name": "Arbeit", "label": "Arbeit", "time": "06:30",
            "hour": 6, "minute": 30, "enabled": True, "repeating": True,
            "days_mask": 31, "days_label": "Mo-Fr", "days": ["Mo", "Di", "Mi", "Do", "Fr"],
            "vibrate": True, "snooze_minutes": 10, "skip_next": False,
            "snoozed": False, "snoozed_until": None, "ringing": False,
            "next_trigger": "2026-11-08T06:30:00+01:00", "next_trigger_ts": 1762580000,
            "next_trigger_in": "12 Std 13 Min", "next_trigger_in_minutes": 733,
        },
        {
            "id": 2, "name": "", "label": "", "time": "08:00",
            "hour": 8, "minute": 0, "enabled": False, "repeating": True,
            "days_mask": 96, "days_label": "Sa+So", "days": ["Sa", "So"],
            "vibrate": True, "snooze_minutes": 10, "skip_next": False,
            "snoozed": False, "snoozed_until": None, "ringing": False,
            "next_trigger": None, "next_trigger_ts": None,
            "next_trigger_in": None, "next_trigger_in_minutes": None,
        },
    ],
    "active_alarms": [],
    "inactive_alarms": [],
    "summary": "AN   06:30  Mo-Fr  (Arbeit)\nAUS  08:00  Sa+So",
    "sleep": {"enabled": True, "active": False, "start": "22:30", "end": "06:30", "days_mask": 127,
              "next_start": "2026-11-07T22:30:00+01:00", "next_end": "2026-11-08T06:30:00+01:00",
              "remaining_minutes": None},
    "sleep_active": False,
    "prewarn_minutes": 5,
    "device_time": "2026-11-07T18:17:00+01:00",
    "timezone": "Europe/Berlin",
    "api_version": 2,
}


@pytest.fixture(autouse=True)
def kein_ereignisstrom():
    """Der Ereignisstrom haelt eine Verbindung offen - im Test abschalten."""
    from unittest.mock import patch

    with patch("custom_components.ha_wecker.relais.RelaisCoordinator.async_start_events"):
        yield


@pytest.fixture(autouse=True)
def auto_enable_custom_integrations(hass, enable_custom_integrations):
    # HA haengt beim Start sein Test-config_dir ein und importiert dessen
    # custom_components; hier gegen den Projektordner austauschen.
    import importlib
    import sys

    sys.modules.pop("custom_components", None)
    importlib.invalidate_caches()
    importlib.import_module("custom_components")
    from homeassistant import loader

    hass.data.pop(loader.DATA_CUSTOM_COMPONENTS, None)
    yield


async def _setup(hass: HomeAssistant) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA Wecker",
        data={"typ": "wecker", "name": "HA Wecker", CONF_WEBHOOK_ID: "hawecker_test123"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_webhook_fills_entities(
    hass: HomeAssistant, hass_client_no_auth: ClientSessionGenerator
) -> None:
    entry = await _setup(hass)

    # Vor dem ersten Push: Hauptsensoren nicht verfuegbar, Webhook-Sensor schon
    assert hass.states.get("sensor.ha_wecker_naechster_wecker").state == "unavailable"
    wh = hass.states.get("sensor.ha_wecker_webhook")
    assert wh.state == "hawecker_test123"
    assert "hawecker_test123" in wh.attributes["adresse_fuer_die_app"]
    # Der Wecker hat keine Knoepfe (nichts zum Abfragen)
    assert not [st for st in hass.states.async_all("button") if "wecker" in st.entity_id]

    client = await hass_client_no_auth()
    resp = await client.post("/api/webhook/hawecker_test123", json=PAYLOAD)
    assert resp.status == 200
    await hass.async_block_till_done()

    assert hass.states.get("sensor.ha_wecker_naechster_wecker").state == "2026-11-08T05:30:00+00:00"
    assert hass.states.get("sensor.ha_wecker_naechster_wecker_in").state == "12 Std 13 Min"
    aktiv = hass.states.get("sensor.ha_wecker_aktive_wecker")
    assert aktiv.state == "1"
    assert len(aktiv.attributes["alarms"]) == 2
    assert hass.states.get("binary_sensor.ha_wecker_klingelt").state == "off"
    schlaf = hass.states.get("binary_sensor.ha_wecker_schlafenszeit")
    assert schlaf.state == "off" and schlaf.attributes["von"] == "22:30"

    # Je Wecker eine Entitaet
    a1 = hass.states.get("binary_sensor.ha_wecker_06_30_arbeit")
    assert a1 is not None, [s.entity_id for s in hass.states.async_all("binary_sensor")]
    assert a1.state == "on"
    assert a1.attributes["tage"] == "Mo-Fr"
    assert a1.attributes["friendly_name"] == "HA Wecker 06:30 Arbeit"
    a2 = hass.states.get("binary_sensor.ha_wecker_08_00")
    assert a2.state == "off"
    assert a2.attributes["icon"] == "mdi:alarm-off"

    # Alle haengen am selben Geraet
    reg = er.async_get(hass)
    devices = {reg.async_get(s.entity_id).device_id for s in hass.states.async_all()
               if reg.async_get(s.entity_id) is not None}
    assert len(devices) == 1

    # Zweiter Push: Wecker 2 geloescht, Wecker 3 neu, Wecker 1 klingelt
    p2 = copy.deepcopy(PAYLOAD)
    p2["alarms"] = [p2["alarms"][0], dict(p2["alarms"][1], id=3, time="09:15", label="Sonntag")]
    p2["alarms"][0]["ringing"] = True
    p2["ringing"] = True
    p2["ringing_id"] = 1
    p2["sleep"] = dict(p2["sleep"], active=True, remaining_minutes=412)
    p2["sleep_active"] = True
    resp = await client.post("/api/webhook/hawecker_test123", json=p2)
    assert resp.status == 200
    await hass.async_block_till_done()

    assert hass.states.get("binary_sensor.ha_wecker_klingelt").state == "on"
    assert hass.states.get("binary_sensor.ha_wecker_klingelt").attributes["name"] == "Arbeit"
    schlaf = hass.states.get("binary_sensor.ha_wecker_schlafenszeit")
    assert schlaf.state == "on" and schlaf.attributes["rest_minuten"] == 412
    assert hass.states.get("binary_sensor.ha_wecker_08_00") is None
    assert reg.async_get_entity_id("binary_sensor", DOMAIN, f"{entry.entry_id}_alarm_2") is None
    a3 = hass.states.get("binary_sensor.ha_wecker_09_15_sonntag")
    assert a3 is not None and a3.state == "off"
    assert hass.states.get("binary_sensor.ha_wecker_06_30_arbeit").attributes["icon"] == "mdi:alarm-bell"

    # Ungueltiger Rumpf
    resp = await client.post("/api/webhook/hawecker_test123", data="kaputt")
    assert resp.status == 400

    # Neu laden: Stand kommt aus dem Store, Wecker-Entitaeten aus dem Register
    assert await hass.config_entries.async_reload(entry.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("sensor.ha_wecker_aktive_wecker").state == "1"
    assert hass.states.get("binary_sensor.ha_wecker_09_15_sonntag").state == "off"

    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()


async def test_wecker_options_zeigt_webhook(hass: HomeAssistant) -> None:
    entry = await _setup(hass)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form"
    assert "hawecker_test123" in result["description_placeholders"]["webhook_url"]
    result = await hass.config_entries.options.async_configure(result["flow_id"], {})
    assert result["type"] == "create_entry"


async def test_config_flow(hass: HomeAssistant) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "wecker"})
    assert result["type"] == "form" and result["step_id"] == "wecker"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Handy Max"})
    assert result["type"] == "create_entry", result
    assert result["title"] == "Handy Max"
    assert result["data"][CONF_WEBHOOK_ID]
    await hass.async_block_till_done()
    # Geraetename folgt dem Titel
    st = hass.states.get("sensor.handy_max_webhook")
    assert st is not None


# ---------------------------------------------------------------------------
# Relaisbox
# ---------------------------------------------------------------------------

RELAIS_URL = "http://192.168.1.60"


def relais_state(an1=False, muster1="aus", an3=False, muster3="aus", eingang=False):
    return {
        "name": "Relaisbox", "version": "1.1.0", "mac": "1c:db:d4:5b:d2:d4",
        "ip": "192.168.1.60", "rssi": -61, "uptime_s": 120,
        "eingang": {"gpio": 7, "aktiv": eingang, "seit_s": 7, "zaehler": 3 if eingang else 2},
        "alarm": muster1 not in ("aus", "dauer") or muster3 not in ("aus", "dauer"),
        "muster": ["aus", "dauer", "blinken", "langsam", "schnell", "doppelblitz", "sos"],
        "relais": [
            {"nr": 1, "gpio": 4, "defekt": False, "an": an1, "muster": muster1, "rest_s": -1},
            {"nr": 2, "gpio": 5, "defekt": True, "an": False, "muster": "aus", "rest_s": -1},
            {"nr": 3, "gpio": 6, "defekt": False, "an": an3, "muster": muster3, "rest_s": -1},
            {"nr": 4, "gpio": 16, "defekt": False, "an": False, "muster": "aus", "rest_s": -1},
        ],
    }


async def _setup_relais(hass: HomeAssistant, aioclient_mock) -> MockConfigEntry:
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state())
    entry = MockConfigEntry(
        domain=DOMAIN, title="Relaisbox", unique_id="1c:db:d4:5b:d2:d4",
        data={"typ": "relais", "name": "Relaisbox", "host": "192.168.1.60"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


def _letzter_aufruf(aioclient_mock, methode="post"):
    aufrufe = [c for c in aioclient_mock.mock_calls if c[0].lower() == methode]
    assert aufrufe, "kein Aufruf"
    return aufrufe[-1][1]  # URL mit Query


async def test_relaisbox_entities_und_schalter(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_relais(hass, aioclient_mock)

    # Nur brauchbare Relais bekommen einen Schalter, Relais 2 ist defekt
    assert hass.states.get("switch.relaisbox_relais_1").state == "off"
    assert hass.states.get("switch.relaisbox_relais_2") is None
    assert hass.states.get("switch.relaisbox_relais_3").state == "off"
    assert hass.states.get("switch.relaisbox_relais_4").state == "off"
    assert hass.states.get("binary_sensor.relaisbox_alarm").state == "off"
    assert hass.states.get("button.relaisbox_alarm_stoppen") is not None
    eingang = hass.states.get("binary_sensor.relaisbox_eingang")
    assert eingang.state == "off" and eingang.attributes["gpio"] == 7

    # Eingang geht an -> naechste Abfrage zeigt es
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state(eingang=True))
    async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
    await hass.async_block_till_done()
    eingang = hass.states.get("binary_sensor.relaisbox_eingang")
    assert eingang.state == "on" and eingang.attributes["zaehler"] == 3

    # Einschalten -> POST /api/relais/1?an=1, Antwort wird direkt uebernommen
    aioclient_mock.post(f"{RELAIS_URL}/api/relais/1", json=relais_state(an1=True, muster1="dauer"))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.relaisbox_relais_1"}, blocking=True
    )
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/relais/1" and url.query["an"] == "1"
    assert hass.states.get("switch.relaisbox_relais_1").state == "on"

    # Wecker-Aktionen sind angemeldet
    assert hass.services.has_service(DOMAIN, "alarm_starten")
    assert hass.services.has_service(DOMAIN, "alarm_stoppen")


async def test_relaisbox_alarm_aktionen(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup_relais(hass, aioclient_mock)
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", json=relais_state(an1=True, muster1="doppelblitz"))
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm/stop", json=relais_state())

    # Ziel: ein Schalter
    await hass.services.async_call(
        DOMAIN, "alarm_starten",
        {"entity_id": "switch.relaisbox_relais_1", "muster": "doppelblitz", "dauer": 60},
        blocking=True,
    )
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/alarm"
    assert url.query["relais"] == "1" and url.query["muster"] == "doppelblitz" and url.query["dauer"] == "60"
    assert hass.states.get("binary_sensor.relaisbox_alarm").state == "on"
    assert hass.states.get("switch.relaisbox_relais_1").attributes["icon"] == "mdi:alarm-light"

    # Ziel: das Geraet -> alle brauchbaren Relais (1,3,4)
    reg = er.async_get(hass)
    device_id = reg.async_get("switch.relaisbox_relais_1").device_id
    await hass.services.async_call(
        DOMAIN, "alarm_starten", {"device_id": device_id, "muster": "blinken"}, blocking=True
    )
    url = _letzter_aufruf(aioclient_mock)
    assert url.query["relais"] == "1,3,4" and url.query["muster"] == "blinken" and url.query["dauer"] == "0"

    # Ohne Ziel: alle Relaisboxen, "alle"
    await hass.services.async_call(DOMAIN, "alarm_stoppen", {}, blocking=True)
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/alarm/stop" and url.query["relais"] == "alle"
    assert hass.states.get("binary_sensor.relaisbox_alarm").state == "off"

    # Knopf "Alarm stoppen"
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.relaisbox_alarm_stoppen"}, blocking=True
    )
    assert _letzter_aufruf(aioclient_mock).path == "/api/alarm/stop"

    # Ungueltiges Muster wird abgelehnt
    import voluptuous as vol
    with pytest.raises(vol.Invalid):
        await hass.services.async_call(
            DOMAIN, "alarm_starten", {"entity_id": "switch.relaisbox_relais_1", "muster": "disco"}, blocking=True
        )

    # Box nicht erreichbar -> Fehler
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", status=500, text="kaputt")
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "alarm_starten", {"entity_id": "switch.relaisbox_relais_1"}, blocking=True
        )

    # Entladen entfernt die Aktionen, wenn kein Eintrag mehr da ist
    assert await hass.config_entries.async_unload(entry.entry_id)
    await hass.async_block_till_done()
    assert not hass.services.has_service(DOMAIN, "alarm_starten")


async def test_relaisbox_config_flow(hass: HomeAssistant, aioclient_mock) -> None:
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "relais"})
    assert result["type"] == "form" and result["step_id"] == "relais"

    # Nicht erreichbar
    aioclient_mock.get("http://relaisbox.local/api/state", status=404)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Relaisbox", "host": "relaisbox.local"}
    )
    assert result["errors"] == {"host": "nicht_erreichbar"}

    # Erreichbar -> Eintrag mit MAC als unique_id
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state())
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "Relaisbox Keller", "host": "192.168.1.60"}
    )
    assert result["type"] == "create_entry", result
    assert result["title"] == "Relaisbox Keller"
    assert result["result"].unique_id == "1c:db:d4:5b:d2:d4"
    await hass.async_block_till_done()
    assert hass.states.get("switch.relaisbox_keller_relais_1") is not None

    # Zweites Mal dieselbe Box -> abgebrochen
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "relais"})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {"name": "x", "host": "192.168.1.60"}
    )
    assert result["type"] == "abort" and result["reason"] == "already_configured"


async def test_relaisbox_zeroconf(hass: HomeAssistant, aioclient_mock) -> None:
    from ipaddress import ip_address
    from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state())
    info = ZeroconfServiceInfo(
        ip_address=ip_address("192.168.1.60"), ip_addresses=[ip_address("192.168.1.60")],
        hostname="relaisbox.local.", name="relaisbox._ha-wecker._tcp.local.", port=80,
        properties={"typ": "relaisbox", "version": "1.0.0"}, type="_ha-wecker._tcp.local.",
    )
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "zeroconf"}, data=info)
    assert result["type"] == "form" and result["step_id"] == "relais_bestaetigen", result
    assert result["description_placeholders"]["host"] == "192.168.1.60"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Relaisbox"})
    assert result["type"] == "create_entry"
    assert result["data"]["host"] == "192.168.1.60"


async def test_relaisbox_options(hass: HomeAssistant, aioclient_mock) -> None:
    entry = await _setup_relais(hass, aioclient_mock)
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form" and result["step_id"] == "relais"
    aioclient_mock.get("http://192.168.1.61/api/state", json=relais_state())
    result = await hass.config_entries.options.async_configure(result["flow_id"], {"host": "192.168.1.61"})
    assert result["type"] == "create_entry"
    assert entry.options["host"] == "192.168.1.61"
    await hass.async_block_till_done()
    assert hass.states.get("switch.relaisbox_relais_1").state == "off"


async def test_relaisbox_ereignisstrom(hass: HomeAssistant, aioclient_mock) -> None:
    """Zeilen des Ereignisstroms werden sofort uebernommen."""
    entry = await _setup_relais(hass, aioclient_mock)
    coord = hass.data[DOMAIN][entry.entry_id]
    assert coord.events_url == "http://192.168.1.60:8081/api/events"

    body = (
        "retry: 3000\n\n"
        ": ping\n\n"
        "data: " + __import__("json").dumps(relais_state(eingang=True, an1=True, muster1="dauer")) + "\n\n"
    ).encode()
    aioclient_mock.get("http://192.168.1.60:8081/api/events", content=body)
    import asyncio
    task = hass.async_create_task(coord._events_loop())
    for _ in range(50):
        await asyncio.sleep(0)
        if hass.states.get("binary_sensor.relaisbox_eingang").state == "on":
            break
    task.cancel()
    try:
        await task
    except asyncio.CancelledError:
        pass
    assert hass.states.get("binary_sensor.relaisbox_eingang").state == "on"
    assert hass.states.get("switch.relaisbox_relais_1").state == "on"
