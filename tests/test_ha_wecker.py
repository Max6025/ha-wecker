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


def relais_state(an1=False, muster1="aus", an3=False, muster3="aus", eingang=False, led_dunkel=None):
    d = _relais_state(an1, muster1, an3, muster3, eingang)
    if led_dunkel is not None:
        d["led_dunkel"] = led_dunkel
    return d


def _relais_state(an1, muster1, an3, muster3, eingang):
    return {
        "name": "Relaisbox", "version": "1.1.0", "mac": "1c:db:d4:5b:d2:d4",
        "ip": "192.168.1.60", "rssi": -61, "uptime_s": 120,
        "eingang": {"gpio": 7, "aktiv": eingang, "seit_s": 7, "zaehler": 3 if eingang else 2},
        "alarm": muster1 not in ("aus", "dauer") or muster3 not in ("aus", "dauer"),
        "muster": ["aus", "dauer", "blinken", "langsam", "schnell", "doppelblitz", "sos"],
        "relais": [
            {"nr": 1, "gpio": 4, "name": "Lampe", "defekt": False, "an": an1, "muster": muster1, "rest_s": -1},
            {"nr": 2, "gpio": 5, "defekt": True, "an": False, "muster": "aus", "rest_s": -1},
            {"nr": 3, "gpio": 6, "defekt": False, "an": an3, "muster": muster3, "rest_s": -1},
            {"nr": 4, "gpio": 16, "defekt": False, "an": False, "muster": "aus", "rest_s": -1},
        ],
    }


async def _setup_relais(hass: HomeAssistant, aioclient_mock, options=None, state=None) -> MockConfigEntry:
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=state or relais_state())
    entry = MockConfigEntry(
        domain=DOMAIN, title="Relaisbox", unique_id="1c:db:d4:5b:d2:d4",
        data={"typ": "relais", "name": "Relaisbox", "host": "192.168.1.60"},
        options=options or {},
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
    assert hass.states.get("switch.relaisbox_lampe").state == "off"
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
        "switch", "turn_on", {"entity_id": "switch.relaisbox_lampe"}, blocking=True
    )
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/relais/1" and url.query["an"] == "1"
    assert hass.states.get("switch.relaisbox_lampe").state == "on"

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
        {"entity_id": "switch.relaisbox_lampe", "muster": "doppelblitz", "dauer": 60},
        blocking=True,
    )
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/alarm"
    assert url.query["relais"] == "1" and url.query["muster"] == "doppelblitz" and url.query["dauer"] == "60"
    assert hass.states.get("binary_sensor.relaisbox_alarm").state == "on"
    assert hass.states.get("switch.relaisbox_lampe").attributes["icon"] == "mdi:alarm-light"

    # Ziel: das Geraet -> alle brauchbaren Relais (1,3,4)
    reg = er.async_get(hass)
    device_id = reg.async_get("switch.relaisbox_lampe").device_id
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
            DOMAIN, "alarm_starten", {"entity_id": "switch.relaisbox_lampe", "muster": "disco"}, blocking=True
        )

    # Box nicht erreichbar -> Fehler
    aioclient_mock.clear_requests()
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", status=500, text="kaputt")
    from homeassistant.exceptions import HomeAssistantError
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            DOMAIN, "alarm_starten", {"entity_id": "switch.relaisbox_lampe"}, blocking=True
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
    assert hass.states.get("switch.relaisbox_keller_lampe") is not None

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
    assert hass.states.get("switch.relaisbox_lampe").state == "off"


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
    assert hass.states.get("switch.relaisbox_lampe").state == "on"


# ---------------------------------------------------------------------------
# Weckerlampe: ein Relais folgt dem Wecker der App
# ---------------------------------------------------------------------------


def _posts(aioclient_mock):
    return [c for c in aioclient_mock.mock_calls if c[0].lower() == "post"]


def _befehle(aioclient_mock, ab=0):
    """POSTs ab Index `ab` als (Pfad, relais, muster, dauer)."""
    aus = []
    for c in _posts(aioclient_mock)[ab:]:
        url = c[1]
        aus.append((url.path, url.query.get("relais"), url.query.get("muster"), url.query.get("dauer")))
    return aus


def _licht(calls, ab=0):
    return [(c.service, c.data.get("brightness_pct"), c.data.get("transition")) for c in calls[ab:]]


IMMER = {"hauptlicht": "light.decke", "hauptlicht_von": "00:00:00", "hauptlicht_bis": "00:00:00"}


async def test_weckerlampe(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Der ganze Ablauf mit Relais 1 Lampe, 3 Rot, 4 Warnleuchte (2 ist defekt) und Hauptlicht."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

    licht = async_mock_service(hass, "light", "turn_on")
    licht_aus = async_mock_service(hass, "light", "turn_off")
    await _setup(hass)
    await _setup_relais(hass, aioclient_mock, options=IMMER)
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", json=relais_state(an1=True, muster1="doppelblitz"))
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm/stop", json=relais_state())

    # Schalter ist da und neu angelegt an, noch nichts geschaltet; Relais heissen wie gemeldet
    lampe = hass.states.get("switch.relaisbox_weckerlampe")
    assert lampe is not None and lampe.state == "on"
    assert lampe.attributes["phase"] == "aus" and lampe.attributes["relais"] == [1, 3, 4]
    assert lampe.attributes["hauptlicht"] == "light.decke"
    assert lampe.attributes["hauptlicht_fenster"] == "00:00-00:00"
    assert hass.states.get("switch.relaisbox_lampe").attributes["friendly_name"] == "Relaisbox Lampe"
    assert hass.states.get("switch.relaisbox_testmodus").state == "off"
    assert not _posts(aioclient_mock) and not licht

    client = await hass_client_no_auth()

    async def melden(**aenderung):
        p = copy.deepcopy(PAYLOAD)
        p.update(aenderung.pop("root", {}))
        p["alarms"][0].update(aenderung)
        p["state"] = p["alarms"][0]["next_trigger"] or ""
        resp = await client.post("/api/webhook/hawecker_test123", json=p)
        assert resp.status == 200
        await hass.async_block_till_done()

    # Weckruf in 150 s -> Timer auf eine Minute vorher, noch kein Befehl
    start = dt_util.utcnow()
    weckzeit = start + timedelta(seconds=150)
    await melden(next_trigger=weckzeit.isoformat())
    lampe = hass.states.get("switch.relaisbox_weckerlampe")
    assert lampe.attributes["naechster_wecker"] == weckzeit.isoformat()
    assert not _posts(aioclient_mock)

    # 95 s spaeter: Vorlauf - Rot dauer (Hoechstdauer 660 s), Hauptlicht 3 % und in der Minute auf 10 %
    async_fire_time_changed(hass, start + timedelta(seconds=95))
    await hass.async_block_till_done()
    assert _befehle(aioclient_mock) == [("/api/alarm", "3", "dauer", "660")]
    assert _licht(licht) == [("turn_on", 3, None)]
    async_fire_time_changed(hass, start + timedelta(seconds=98))
    await hass.async_block_till_done()
    assert _licht(licht) == [("turn_on", 3, None), ("turn_on", 10, 58)]
    zustand = hass.states.get("switch.relaisbox_weckerlampe").attributes
    assert zustand["phase"] == "vorlauf" and zustand["hauptlicht_dabei"] is True
    assert hass.states.get("switch.relaisbox_weckerlampe").attributes["icon"] == "mdi:lightbulb-on"

    # Klingelt -> Rot blinkt, Lampe Doppelblitz, Warnleuchte an, Hauptlicht 100 %
    n, nl = len(_posts(aioclient_mock)), len(licht)
    await melden(ringing=True, root={"ringing": True, "ringing_id": 1})
    assert _befehle(aioclient_mock, n) == [
        ("/api/alarm", "3", "blinken", "600"),
        ("/api/alarm", "1", "doppelblitz", "600"),
        ("/api/alarm", "4", "dauer", "600"),
    ]
    assert _licht(licht, nl) == [("turn_on", 100, 20)]
    assert hass.states.get("switch.relaisbox_weckerlampe").attributes["phase"] == "klingeln"

    # Schlummern -> alles aus, Hauptlicht 10 %
    n, nl = len(_posts(aioclient_mock)), len(licht)
    bis = (dt_util.utcnow() + timedelta(minutes=10)).isoformat()
    await melden(ringing=False, snoozed=True, snoozed_until=bis, root={"ringing": False, "ringing_id": None, "snoozed": True})
    assert _befehle(aioclient_mock, n) == [("/api/alarm/stop", "1,3,4", None, None)]
    assert _licht(licht, nl) == [("turn_on", 10, None)]
    assert hass.states.get("switch.relaisbox_weckerlampe").attributes["phase"] == "schlummer"

    # Klingelt wieder -> wie beim Klingeln
    n, nl = len(_posts(aioclient_mock)), len(licht)
    await melden(ringing=True, root={"ringing": True, "ringing_id": 1})
    assert [b[2] for b in _befehle(aioclient_mock, n)] == ["blinken", "doppelblitz", "dauer"]
    assert _licht(licht, nl) == [("turn_on", 100, 20)]

    # Beendet -> Nachlauf: Warnleuchte 5 s, Rot schnell 300 s, Lampe blinken 300 s, Hauptlicht 50 %
    n, nl = len(_posts(aioclient_mock)), len(licht)
    morgen = (weckzeit + timedelta(days=1)).isoformat()
    await melden(ringing=False, next_trigger=morgen, root={"ringing": False, "ringing_id": None, "snoozed": False})
    assert _befehle(aioclient_mock, n) == [
        ("/api/alarm", "4", "dauer", "5"),
        ("/api/alarm", "3", "schnell", "300"),
        ("/api/alarm", "1", "blinken", "300"),
    ]
    assert _licht(licht, nl) == [("turn_on", 50, None)]
    assert hass.states.get("switch.relaisbox_weckerlampe").attributes["phase"] == "nachlauf"

    # nach 10 min: Hauptlicht in 30 s aus; nach 10:30: Warnleuchte noch 10 s; nach 10:40: Ruhe
    n = len(_posts(aioclient_mock))
    t0 = dt_util.utcnow()
    async_fire_time_changed(hass, t0 + timedelta(seconds=601))
    await hass.async_block_till_done()
    assert _licht(licht_aus) == [("turn_off", None, 30)]
    assert len(_posts(aioclient_mock)) == n
    async_fire_time_changed(hass, t0 + timedelta(seconds=631))
    await hass.async_block_till_done()
    assert _befehle(aioclient_mock, n) == [("/api/alarm", "4", "dauer", "10")]
    assert hass.states.get("switch.relaisbox_weckerlampe").attributes["phase"] == "nachlauf"
    async_fire_time_changed(hass, t0 + timedelta(seconds=641))
    await hass.async_block_till_done()
    zustand = hass.states.get("switch.relaisbox_weckerlampe").attributes
    assert zustand["phase"] == "aus" and zustand["hauptlicht_dabei"] is False

    # Schalter aus waehrend eines Vorlaufs -> Stopp, Hauptlicht aus, kein Vorlauf mehr
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state())
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", json=relais_state(an3=True, muster3="dauer"))
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm/stop", json=relais_state())
    jetzt = dt_util.utcnow()
    await melden(next_trigger=(jetzt + timedelta(seconds=30)).isoformat())
    assert _letzter_aufruf(aioclient_mock).path == "/api/alarm"   # schon im Fenster
    nl = len(licht_aus)
    await hass.services.async_call(
        "switch", "turn_off", {"entity_id": "switch.relaisbox_weckerlampe"}, blocking=True
    )
    assert _befehle(aioclient_mock)[-1] == ("/api/alarm/stop", "1,3,4", None, None)
    assert _licht(licht_aus, nl) == [("turn_off", None, None)]
    lampe = hass.states.get("switch.relaisbox_weckerlampe")
    assert lampe.state == "off" and lampe.attributes["phase"] == "aus"
    n = len(_posts(aioclient_mock))
    await melden(ringing=True, root={"ringing": True, "ringing_id": 1})
    assert len(_posts(aioclient_mock)) == n   # aus heisst aus


async def test_weckerlampe_ohne_hauptlicht_ausserhalb_fenster(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Ausserhalb des Zeitfensters bleibt das Hauptlicht unangetastet, die Relais laufen."""
    from datetime import timedelta
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_mock_service

    licht = async_mock_service(hass, "light", "turn_on")
    jetzt = dt_util.now()
    fenster = {
        "hauptlicht": "light.decke",
        "hauptlicht_von": (jetzt + timedelta(hours=2)).strftime("%H:%M:%S"),
        "hauptlicht_bis": (jetzt + timedelta(hours=3)).strftime("%H:%M:%S"),
    }
    await _setup(hass)
    await _setup_relais(hass, aioclient_mock, options=fenster)
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", json=relais_state(an1=True, muster1="doppelblitz"))
    client = await hass_client_no_auth()
    p = copy.deepcopy(PAYLOAD)
    p.update({"ringing": True, "ringing_id": 1})
    p["alarms"][0]["ringing"] = True
    assert (await client.post("/api/webhook/hawecker_test123", json=p)).status == 200
    await hass.async_block_till_done()
    assert [b[2] for b in _befehle(aioclient_mock)] == ["blinken", "doppelblitz", "dauer"]
    assert not licht
    zustand = hass.states.get("switch.relaisbox_weckerlampe").attributes
    assert zustand["phase"] == "klingeln" and zustand["hauptlicht_dabei"] is False


async def test_weckerlampe_optionen(hass: HomeAssistant, aioclient_mock) -> None:
    """Optionsdialog: Adresse, Hauptlicht, Zeitfenster; leeres Hauptlicht heisst keins."""
    entry = await _setup_relais(hass, aioclient_mock)

    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == "form" and result["step_id"] == "relais"
    assert [str(k) for k in result["data_schema"].schema] == ["host", "hauptlicht", "hauptlicht_von", "hauptlicht_bis"]

    result = await hass.config_entries.options.async_configure(
        result["flow_id"],
        {"host": "192.168.1.60", "hauptlicht": "light.decke", "hauptlicht_von": "04:00:00", "hauptlicht_bis": "09:30:00"},
    )
    assert result["type"] == "create_entry"
    assert entry.options == {"host": "192.168.1.60", "hauptlicht": "light.decke",
                             "hauptlicht_von": "04:00:00", "hauptlicht_bis": "09:30:00"}
    await hass.async_block_till_done()
    zustand = hass.states.get("switch.relaisbox_weckerlampe").attributes
    assert zustand["hauptlicht"] == "light.decke" and zustand["hauptlicht_fenster"] == "04:00-09:30"

    result = await hass.config_entries.options.async_init(entry.entry_id)
    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {"host": "192.168.1.60", "hauptlicht_von": "03:00:00", "hauptlicht_bis": "10:00:00"}
    )
    assert result["type"] == "create_entry" and "hauptlicht" not in entry.options
    await hass.async_block_till_done()
    assert hass.states.get("switch.relaisbox_weckerlampe").attributes["hauptlicht"] is None


async def test_testmodus(hass: HomeAssistant, aioclient_mock) -> None:
    """Schalter Testmodus: Lichtbild ohne Ende auf den vorhandenen Relais, aus = Stopp."""
    await _setup_relais(hass, aioclient_mock)
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm", json=relais_state(an1=True, muster1="dreifachblitz"))
    aioclient_mock.post(f"{RELAIS_URL}/api/alarm/stop", json=relais_state())
    await hass.services.async_call("switch", "turn_on", {"entity_id": "switch.relaisbox_testmodus"}, blocking=True)
    assert _befehle(aioclient_mock) == [
        ("/api/alarm", "1", "dreifachblitz", "0"),
        ("/api/alarm", "3", "langsam", "0"),
        ("/api/alarm", "4", "intervall", "0"),
    ]
    assert hass.states.get("switch.relaisbox_testmodus").state == "on"
    n = len(_posts(aioclient_mock))
    await hass.services.async_call("switch", "turn_off", {"entity_id": "switch.relaisbox_testmodus"}, blocking=True)
    assert _befehle(aioclient_mock, n) == [("/api/alarm/stop", "1,3,4", None, None)]
    assert hass.states.get("switch.relaisbox_testmodus").state == "off"


async def test_led_nachtruhe(hass: HomeAssistant, aioclient_mock) -> None:
    """Zwischen 20 und 8 Uhr setzt die Integration /api/led?dunkel=1, tagsueber =0."""
    from datetime import datetime, timedelta
    from unittest.mock import patch
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    nacht = dt_util.now().replace(hour=22, minute=0, second=0)
    tag = dt_util.now().replace(hour=12, minute=0, second=0)
    aioclient_mock.post(f"{RELAIS_URL}/api/led", json=relais_state(led_dunkel=True))
    with patch("custom_components.ha_wecker.relais.dt_util.now", return_value=nacht):
        await _setup_relais(hass, aioclient_mock, state=relais_state(led_dunkel=False))
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/led" and url.query["dunkel"] == "1"

    # tagsueber meldet die Box noch dunkel -> wieder hell
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state(led_dunkel=True))
    aioclient_mock.post(f"{RELAIS_URL}/api/led", json=relais_state(led_dunkel=False))
    with patch("custom_components.ha_wecker.relais.dt_util.now", return_value=tag):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=11))
        await hass.async_block_till_done()
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/led" and url.query["dunkel"] == "0"

    # aeltere Firmware ohne led_dunkel: nichts senden
    aioclient_mock.clear_requests()
    aioclient_mock.get(f"{RELAIS_URL}/api/state", json=relais_state())
    with patch("custom_components.ha_wecker.relais.dt_util.now", return_value=nacht):
        async_fire_time_changed(hass, dt_util.utcnow() + timedelta(seconds=22))
        await hass.async_block_till_done()
    assert not _posts(aioclient_mock)


# --------------------------------------------------------------------------
# Signalsaeule (Arduino UNO R4 WiFi)

SAEULE_URL = "http://192.168.1.70"


def saeule_state(modus="auto", status="ruhe", warn=False, test=False, diagnose=None):
    stufen = {
        "ruhe":     [True,  False, False, False],
        "hinweis":  [True,  False, False, True],
        "achtung":  [False, True,  False, True],
        "stoerung": [False, False, True,  True],
        "alarm":    [False, False, True,  True],
    }[status]
    if modus != "auto":
        stufen = [False, False, False, False]
    namen = ["Gruen", "Orange", "Rot", "Hinweis"]
    relais = [
        {"nr": i + 1, "gpio": 3 + i, "name": namen[i], "rolle": "stufe", "defekt": False,
         "an": stufen[i], "live": stufen[i], "pegel": int(stufen[i]),
         "muster": "dauer" if stufen[i] else "aus", "rest_s": -1}
        for i in range(4)
    ]
    relais.append(
        {"nr": 5, "gpio": 2, "name": "Warnleuchte", "rolle": "warn", "defekt": False,
         "an": warn, "live": warn, "pegel": int(warn),
         "muster": "dauer" if warn else "aus", "rest_s": -1}
    )
    return {
        "name": "Signalsäule", "typ": "saeule", "version": "1.0.0",
        "mac": "34:85:18:aa:bb:cc", "ip": "192.168.1.70", "rssi": -58,
        "uptime_s": 300, "events_port": 8081, "ram_frei": 21000,
        "phase": "betrieb", "modus": modus, "status": status,
        "status_name": {"ruhe": "Ruhe", "hinweis": "Hinweis", "achtung": "Achtung",
                        "stoerung": "Störung", "alarm": "Alarm"}[status],
        "wechsel": False, "warn": warn, "test": test,
        "status_liste": [
            {"id": "ruhe", "name": "Ruhe"}, {"id": "hinweis", "name": "Hinweis"},
            {"id": "achtung", "name": "Achtung"}, {"id": "stoerung", "name": "Störung"},
            {"id": "alarm", "name": "Alarm"},
        ],
        "diagnose": diagnose or {"laeuft": False, "fertig": False, "ok": False,
                                 "vor_s": 0, "punkte": []},
        "relais": relais,
    }


async def _setup_saeule(hass: HomeAssistant, aioclient_mock, state=None) -> MockConfigEntry:
    aioclient_mock.get(f"{SAEULE_URL}/api/state", json=state or saeule_state())
    entry = MockConfigEntry(
        domain=DOMAIN, title="Signalsaeule", unique_id="34:85:18:aa:bb:cc",
        data={"typ": "saeule", "name": "Signalsaeule", "host": "192.168.1.70"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_saeule_entities(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_saeule(hass, aioclient_mock)

    assert hass.states.get("select.signalsaeule_betriebsart").state == "Auto"
    status = hass.states.get("select.signalsaeule_status")
    assert status.state == "Ruhe"
    assert status.attributes["options"] == ["Ruhe", "Hinweis", "Achtung", "Störung", "Alarm"]

    # In Ruhe brennt nur die gruene Stufe, die Warnleuchte ist aus
    assert hass.states.get("switch.signalsaeule_gruen").state == "on"
    assert hass.states.get("switch.signalsaeule_orange").state == "off"
    assert hass.states.get("switch.signalsaeule_warnleuchte").state == "off"
    assert hass.states.get("switch.signalsaeule_testmodus").state == "off"
    assert hass.states.get("button.signalsaeule_selbstdiagnose") is not None
    assert hass.states.get("button.signalsaeule_alles_aus") is not None
    assert hass.states.get("sensor.signalsaeule_anzeige").state == "Ruhe"
    assert hass.states.get("binary_sensor.signalsaeule_wechsel_laeuft").state == "off"
    # Die Relaisbox-Entitaeten duerfen nicht mitkommen
    assert hass.states.get("switch.signalsaeule_weckerlampe") is None


async def test_saeule_status_waehlen(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="stoerung"))

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.signalsaeule_status", "option": "Störung"},
        blocking=True,
    )
    assert "status=stoerung" in str(_letzter_aufruf(aioclient_mock))
    assert hass.states.get("select.signalsaeule_status").state == "Störung"
    assert hass.states.get("switch.signalsaeule_rot").state == "on"
    assert hass.states.get("switch.signalsaeule_gruen").state == "off"


async def test_saeule_manuell_und_warnleuchte(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_saeule(hass, aioclient_mock)

    aioclient_mock.post(f"{SAEULE_URL}/api/modus", json=saeule_state(modus="manuell"))
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.signalsaeule_betriebsart", "option": "Manuell"},
        blocking=True,
    )
    assert "modus=manuell" in str(_letzter_aufruf(aioclient_mock))
    assert hass.states.get("sensor.signalsaeule_anzeige").state == "Manuell"
    assert hass.states.get("switch.signalsaeule_gruen").state == "off"

    # Einzelne Leuchte in Manuell
    aioclient_mock.post(f"{SAEULE_URL}/api/relais/2", json=saeule_state(modus="manuell"))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_orange"}, blocking=True
    )
    assert "an=1" in str(_letzter_aufruf(aioclient_mock))

    # Die Warnleuchte laeuft ueber ihren eigenen Schalter
    aioclient_mock.post(f"{SAEULE_URL}/api/relais/5", json=saeule_state(modus="manuell", warn=True))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_warnleuchte"}, blocking=True
    )
    url = str(_letzter_aufruf(aioclient_mock))
    assert "/api/relais/5" in url and "an=1" in url
    assert hass.states.get("switch.signalsaeule_warnleuchte").state == "on"


async def test_saeule_diagnose_und_test(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_saeule(hass, aioclient_mock)
    assert hass.states.get("sensor.signalsaeule_selbstdiagnose").state == "nie gelaufen"
    assert hass.states.get("binary_sensor.signalsaeule_beanstandung").state == "unavailable"

    fertig = {
        "laeuft": False, "fertig": True, "ok": False, "vor_s": 3,
        "punkte": [
            {"name": "WLAN", "ok": 1, "text": "SAS00, -58 dBm"},
            {"name": "Geraet", "ok": 1, "text": "signalsaeule, Firmware 1.0.0"},
            {"name": "Rot", "ok": 0, "text": "Pin D5 liest 0"},
        ],
    }
    aioclient_mock.post(f"{SAEULE_URL}/api/diagnose", json=saeule_state(diagnose=fertig))
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.signalsaeule_selbstdiagnose"}, blocking=True
    )
    assert hass.states.get("sensor.signalsaeule_selbstdiagnose").state == "1 Beanstandung(en)"
    assert hass.states.get("binary_sensor.signalsaeule_beanstandung").state == "on"

    aioclient_mock.post(f"{SAEULE_URL}/api/test", json=saeule_state(test=True))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_testmodus"}, blocking=True
    )
    assert "an=1" in str(_letzter_aufruf(aioclient_mock))
    assert hass.states.get("switch.signalsaeule_testmodus").state == "on"
    assert hass.states.get("sensor.signalsaeule_anzeige").state == "Testmodus"


async def test_saeule_config_flow(hass: HomeAssistant, aioclient_mock) -> None:
    aioclient_mock.get(f"{SAEULE_URL}/api/state", json=saeule_state())
    ergebnis = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    ergebnis = await hass.config_entries.flow.async_configure(
        ergebnis["flow_id"], {"next_step_id": "saeule"}
    )
    assert ergebnis["step_id"] == "saeule"
    ergebnis = await hass.config_entries.flow.async_configure(
        ergebnis["flow_id"], {"name": "Signalsaeule", "host": "192.168.1.70"}
    )
    assert ergebnis["type"] == "create_entry"
    assert ergebnis["data"]["typ"] == "saeule"
    assert ergebnis["result"].unique_id == "34:85:18:aa:bb:cc"
