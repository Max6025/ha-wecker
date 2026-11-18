"""Durchlauf der HA-Wecker-Integration in einem echten Home-Assistant-Testkern."""
from __future__ import annotations

import copy

import re

import pytest
from homeassistant.const import CONF_WEBHOOK_ID
from homeassistant.core import HomeAssistant, callback
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

    with patch("custom_components.ha_wecker.saeule.SaeuleCoordinator.async_start_events"), \
         patch("custom_components.ha_wecker.garage.GarageCoordinator.async_start_events"):
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


async def _setup(hass: HomeAssistant, options=None) -> MockConfigEntry:
    entry = MockConfigEntry(
        domain=DOMAIN,
        title="HA Wecker",
        data={"typ": "wecker", "name": "HA Wecker", CONF_WEBHOOK_ID: "hawecker_test123"},
        options=options or {},
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
    # Der Wecker hat den Probelauf-Knopf und den Schalter fuer den Weckablauf;
    # abzufragen gibt es bei ihm nichts, der Rest kommt ueber den Webhook.
    assert sorted(
        st.entity_id for st in hass.states.async_all("button") if "wecker" in st.entity_id
    ) == ["button.ha_wecker_ablauf_abbrechen", "button.ha_wecker_probelauf"]
    assert hass.states.get("switch.ha_wecker_weckablauf").state == "on"

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

# ---------------------------------------------------------------------------
# Signalsaeule (Arduino UNO R4 WiFi)
# ---------------------------------------------------------------------------




def _letzter_aufruf(aioclient_mock, methode="post"):
    aufrufe = [c for c in aioclient_mock.mock_calls if c[0].lower() == methode]
    assert aufrufe, "kein Aufruf"
    return aufrufe[-1][1]  # URL mit Query


SAEULE_URL = "http://192.168.1.70"


def saeule_state(modus="auto", status="ruhe", warn=False, test=False, diagnose=None,
                 warn_vom_alarm=False, ton=False, mit_farbe=True):
    stufen = {
        "ruhe":     [True,  False, False, False],
        "hinweis":  [True,  False, False, True],
        "achtung":  [False, True,  False, True],
        "stoerung": [False, False, True,  True],
        "alarm":    [False, False, True,  True],
        "kreuz":    [True,  True,  True,  True],
        "blinker":  [True,  True,  True,  True],
    }[status]
    if modus != "auto":
        stufen = [False, False, False, False]
    namen = ["Gruen", "Orange", "Rot", "Hinweis"]
    farben = ["gruen", "orange", "rot", "hinweis"]
    relais = [
        {"nr": i + 1, "gpio": 3 + i, "name": namen[i], "rolle": "stufe",
         "farbe": farben[i] if mit_farbe else None, "defekt": False,
         "an": stufen[i], "live": stufen[i], "pegel": int(stufen[i]),
         "muster": "dauer" if stufen[i] else "aus", "rest_s": -1}
        for i in range(4)
    ]
    relais.append(
        {"nr": 5, "gpio": 2, "name": "Warnleuchte", "rolle": "warn",
         "farbe": "warn" if mit_farbe else None, "defekt": False,
         "an": warn, "live": warn, "pegel": int(warn),
         "muster": "dauer" if warn else "aus", "rest_s": -1}
    )
    relais.append(
        {"nr": 6, "gpio": 7, "name": "Ton", "rolle": "ton",
         "farbe": "ton" if mit_farbe else None, "defekt": False,
         "an": ton, "live": ton, "pegel": int(ton),
         "muster": "dauer" if ton else "aus", "rest_s": -1}
    )
    return {
        "name": "Signalsäule", "typ": "saeule", "version": "1.3.0",
        "mac": "34:85:18:aa:bb:cc", "ip": "192.168.1.70", "rssi": -58,
        "uptime_s": 300, "events_port": 8081, "ram_frei": 21000,
        "phase": "betrieb", "modus": modus, "status": status,
        "status_name": {"ruhe": "Ruhe", "hinweis": "Hinweis", "achtung": "Achtung",
                        "stoerung": "Störung", "alarm": "Alarm",
                        "kreuz": "Kreuzwechsel", "blinker": "Blinker"}[status],
        "wechsel": False, "warn": warn, "warn_vom_alarm": warn_vom_alarm, "test": test,
        "ton": ton,
        "status_liste": [
            {"id": "ruhe", "name": "Ruhe"}, {"id": "hinweis", "name": "Hinweis"},
            {"id": "achtung", "name": "Achtung"}, {"id": "stoerung", "name": "Störung"},
            {"id": "alarm", "name": "Alarm"}, {"id": "kreuz", "name": "Kreuzwechsel"},
            {"id": "blinker", "name": "Blinker"},
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
    assert status.attributes["options"] == [
        "Ruhe", "Hinweis", "Achtung", "Störung", "Alarm", "Kreuzwechsel", "Blinker",
    ]

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
    warnleuchte = hass.states.get("switch.signalsaeule_warnleuchte")
    assert warnleuchte.state == "on"
    assert warnleuchte.attributes["vom_alarm"] is False


async def test_saeule_warnleuchte_im_alarm(hass: HomeAssistant, aioclient_mock) -> None:
    """Im Alarm schaltet die Saeule die Warnleuchte selbst ein."""
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(
        f"{SAEULE_URL}/api/status",
        json=saeule_state(status="alarm", warn=True, warn_vom_alarm=True),
    )
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.signalsaeule_status", "option": "Alarm"},
        blocking=True,
    )
    warnleuchte = hass.states.get("switch.signalsaeule_warnleuchte")
    assert warnleuchte.state == "on"
    assert warnleuchte.attributes["vom_alarm"] is True


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


async def test_saeule_neue_status(hass: HomeAssistant, aioclient_mock) -> None:
    """Kreuzwechsel und Blinker lassen alle vier Stufen als "an" gelten."""
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="kreuz"))
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.signalsaeule_status", "option": "Kreuzwechsel"},
        blocking=True,
    )
    assert "status=kreuz" in str(_letzter_aufruf(aioclient_mock))
    assert hass.states.get("select.signalsaeule_status").state == "Kreuzwechsel"
    for name in ("gruen", "orange", "rot", "hinweis"):
        assert hass.states.get(f"switch.signalsaeule_{name}").state == "on"
    # Die Warnleuchte bleibt dabei aussen vor
    assert hass.states.get("switch.signalsaeule_warnleuchte").state == "off"


# ---------------------------------------------------------------------------
# Weckablauf am Wecker: Hauptlicht und Saeule, geraeteuebergreifend
# ---------------------------------------------------------------------------


def _lichtrufe(calls):
    return [(c.service, c.data.get("brightness_pct"), c.data.get("transition")) for c in calls]


async def test_probelauf_faehrt_vorlauf_und_nachlauf(hass: HomeAssistant) -> None:
    """Der Probelauf spielt beide Haelften: ab dem Weckruf und ab dem Beenden."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

    an = async_mock_service(hass, "light", "turn_on")
    aus = async_mock_service(hass, "light", "turn_off")
    await _setup(hass, options={"hauptlicht": "light.decke"})

    schalter = hass.states.get("switch.ha_wecker_weckablauf")
    assert schalter is not None and schalter.state == "on"
    assert schalter.attributes["hauptlicht"] == "light.decke"
    assert schalter.attributes["saeule"] == "nicht eingerichtet"
    assert not an and not aus

    start = dt_util.utcnow()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()

    # Vorlauf: sofort auf 5 %, der Uebergang ueber die ganze Minute
    assert _lichtrufe(an) == [("turn_on", 5, 60)]
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["laeuft"] is True and zustand["probelauf"] is True
    assert zustand["block"] == "Immer"

    # Eine Minute spaeter klingelt es - am Licht aendert das nichts
    async_fire_time_changed(hass, start + timedelta(seconds=61))
    await hass.async_block_till_done()
    assert _lichtrufe(an) == [("turn_on", 5, 60)]

    # Nach weiteren 30 s gilt der Weckruf als beendet: Licht auf 70 %
    async_fire_time_changed(hass, start + timedelta(seconds=91))
    await hass.async_block_till_done()
    assert _lichtrufe(an)[-1] == ("turn_on", 70, 10)
    assert hass.states.get("switch.ha_wecker_weckablauf").attributes["beendet_um"]

    # Sieben Minuten nach dem Beenden geht das Licht aus
    async_fire_time_changed(hass, start + timedelta(seconds=91 + 421))
    await hass.async_block_till_done()
    assert len(aus) == 1

    eintraege = hass.states.get("switch.ha_wecker_weckablauf").attributes["protokoll"]
    assert [e["ergebnis"] for e in eintraege if e["was"].startswith("Hauptlicht")] == ["ok"] * 3


async def test_abbrechen_raeumt_auf(hass: HomeAssistant) -> None:
    """Der Abbruch stoppt die Timer und schaltet das Licht aus."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "light", "turn_on")
    aus = async_mock_service(hass, "light", "turn_off")
    await _setup(hass, options={"hauptlicht": "light.decke"})
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("switch.ha_wecker_weckablauf").attributes["laeuft"] is True

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_ablauf_abbrechen"}, blocking=True
    )
    await hass.async_block_till_done()
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["laeuft"] is False and zustand["probelauf"] is False
    assert len(aus) == 1


async def test_ablauf_ohne_hauptlicht_meldet_den_fehler(hass: HomeAssistant) -> None:
    """Ist keine Entitaet eingestellt, steht das im Protokoll - nicht nur im Log."""
    await _setup(hass)
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()
    eintraege = hass.states.get("switch.ha_wecker_weckablauf").attributes["protokoll"]
    fehler = [e for e in eintraege if e["ergebnis"] == "fehler"]
    assert fehler and fehler[0]["text"] == "keine Entitaet eingestellt"


async def test_weckzeit_wird_selbst_gerechnet() -> None:
    """Aus Stunde, Minute und Wochentagsmaske - nicht aus dem Zeitstempel der App."""
    from datetime import datetime, timezone

    from custom_components.ha_wecker.ablauf import _termin_rechnen

    jetzt = datetime(2026, 11, 16, 22, 0, tzinfo=timezone.utc)   # Montag, 23 Uhr lokal
    # Maske Bit 0 = Montag; Dienstag und Donnerstag
    alarm = {"hour": 5, "minute": 30, "days_mask": 0b0001010}
    termin = _termin_rechnen(alarm, jetzt)
    assert termin is not None
    from homeassistant.util import dt as dt_util

    lokal = dt_util.as_local(termin)
    assert (lokal.hour, lokal.minute) == (5, 30)
    assert lokal.weekday() == 1                                   # Dienstag

    # skip_next ueberspringt genau einen Termin
    alarm_uebersprungen = dict(alarm, skip_next=True)
    weiter = _termin_rechnen(alarm_uebersprungen, jetzt)
    assert dt_util.as_local(weiter).weekday() == 3                # Donnerstag


async def test_ablauf_json_wird_geprueft() -> None:
    """Unsinn in der Datei faellt auf den Standardablauf zurueck und wird gemeldet."""
    from custom_components.ha_wecker.ablauf import STANDARD_ABLAUF, ablauf_lesen

    daten, fehler = ablauf_lesen("{kein json")
    assert daten is STANDARD_ABLAUF and "nicht lesbar" in fehler
    daten, fehler = ablauf_lesen('{"bloecke": [{"schritte": [{"zeit": 0}]}]}')
    assert daten is STANDARD_ABLAUF and "tut nichts" in fehler
    daten, fehler = ablauf_lesen('{"bloecke": [{"schritte": [{"zeit": 5, "licht": {"aus": true}}]}]}')
    assert fehler is None and daten["bloecke"][0]["schritte"][0]["zeit"] == 5


async def test_ablauf_steuert_die_saeule(hass: HomeAssistant, aioclient_mock) -> None:
    """Der Ablauf am Wecker schaltet die Saeule - ein anderes Geraet, andere Eintrag."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    licht = async_mock_service(hass, "light", "turn_on")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="hinweis"))
    await _setup(hass, options={"hauptlicht": "light.decke"})

    schalter = hass.states.get("switch.ha_wecker_weckablauf")
    assert schalter.attributes["saeule"] == "verbunden"

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()

    # Der erste Schritt des Standardablaufs stellt die Saeule auf "hinweis"
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/status"
    assert url.query["status"] == "hinweis"
    assert licht, "das Hauptlicht wurde nicht geschaltet"

    eintraege = hass.states.get("switch.ha_wecker_weckablauf").attributes["protokoll"]
    saeulenschritte = [e for e in eintraege if e["was"] == "Signalsaeule"]
    assert saeulenschritte and saeulenschritte[0]["ergebnis"] == "ok"


async def test_beenden_des_weckrufs_startet_den_nachlauf(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Der echte Fall: die App meldet klingeln, dann beendet - und erst dann laeuft der Nachlauf."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    an = async_mock_service(hass, "light", "turn_on")
    await _setup_saeule(hass, aioclient_mock)
    for pfad in ("/api/status", "/api/relais/5"):
        aioclient_mock.post(f"{SAEULE_URL}{pfad}", json=saeule_state(status="alarm", warn=True))
    await _setup(hass, options={"hauptlicht": "light.decke"})

    client = await hass_client_no_auth()

    async def melden(**aenderung):
        p = copy.deepcopy(PAYLOAD)
        p.update(aenderung.pop("root", {}))
        p["alarms"][0].update(aenderung)
        resp = await client.post("/api/webhook/hawecker_test123", json=p)
        assert resp.status == 200
        await hass.async_block_till_done()

    # Es klingelt: die Saeule geht in den Alarm
    await melden(ringing=True, root={"ringing": True})
    assert _letzter_aufruf(aioclient_mock).query["status"] == "alarm"
    assert hass.states.get("switch.ha_wecker_weckablauf").attributes["beendet_um"] is None

    # Beendet: Kreuzwechsel und Licht auf 70 %
    vorher = len(an)
    await melden(ringing=False, root={"ringing": False})
    assert _letzter_aufruf(aioclient_mock).query["status"] == "kreuz"
    assert _lichtrufe(an[vorher:]) == [("turn_on", 70, 10)]
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["beendet_um"] is not None
    geplant = [e for e in zustand["protokoll"] if e["was"] == "Geplant"]
    assert "ab dem Beenden" in geplant[0]["text"]


async def test_nach_dem_ablauf_wieder_frei(hass: HomeAssistant) -> None:
    """Nach dem letzten Schritt ist der Ablauf wieder aufnahmebereit.

    Vorher blieb "laeuft" stehen und "probelauf" dazu - danach wurde kein
    Vorlauf mehr geplant und echte Weckrufe wurden stillschweigend ignoriert.
    """
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed, async_mock_service

    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    await _setup(hass, options={"hauptlicht": "light.decke"})

    start = dt_util.utcnow()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()
    async_fire_time_changed(hass, start + timedelta(seconds=91))
    await hass.async_block_till_done()
    assert hass.states.get("switch.ha_wecker_weckablauf").attributes["probelauf"] is True

    # Nach dem letzten Schritt (acht Minuten nach dem Beenden) ist Schluss
    async_fire_time_changed(hass, start + timedelta(seconds=91 + 482))
    await hass.async_block_till_done()
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["probelauf"] is False and zustand["laeuft"] is False
    assert zustand["beendet_um"] is None
    assert [e for e in zustand["protokoll"] if e["was"] == "Fertig"]


async def test_schlummern_dimmt_auf_fuenf_prozent(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Beim Schlummern: Saeule zurueck auf Ruhe, Licht auf 5 % - nicht dunkel.

    Max' Mo-Fr-Wecker schlummert zwei Minuten. Dazwischen soll es nicht
    stockdunkel werden, aber auch nicht hell bleiben.
    """
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import (
        async_fire_time_changed,
        async_mock_service,
    )

    an = async_mock_service(hass, "light", "turn_on")
    aus = async_mock_service(hass, "light", "turn_off")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="alarm", warn=True))
    await _setup(hass, options={"hauptlicht": "light.decke"})

    client = await hass_client_no_auth()

    async def melden(**aenderung):
        p = copy.deepcopy(PAYLOAD)
        p.update(aenderung.pop("root", {}))
        p["alarms"][0].update(aenderung)
        resp = await client.post("/api/webhook/hawecker_test123", json=p)
        assert resp.status == 200
        await hass.async_block_till_done()

    await melden(ringing=True, root={"ringing": True})
    assert _letzter_aufruf(aioclient_mock).query["status"] == "alarm"

    geschlummert = dt_util.utcnow()
    await melden(ringing=False, snoozed=True, root={"ringing": False, "snoozed": True})
    assert _letzter_aufruf(aioclient_mock).query["status"] == "ruhe"
    assert _lichtrufe(an)[-1] == ("turn_on", 5, 10), "Licht auf 5 %, nicht aus"
    assert not aus
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert [e for e in zustand["protokoll"] if e["was"] == "Schlummern"]
    assert [e for e in zustand["protokoll"] if "ab dem Schlummern" in e["text"]]

    # Kommt 19 Minuten lang nichts mehr, geht das Licht aus
    async_fire_time_changed(hass, geschlummert + timedelta(seconds=1145))
    await hass.async_block_till_done()
    assert len(aus) == 1


async def test_neues_klingeln_beendet_das_schlummern(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Klingelt es nach zwei Minuten wieder, gilt der Weckruf - nicht das Schlummern."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import (
        async_fire_time_changed,
        async_mock_service,
    )

    async_mock_service(hass, "light", "turn_on")
    aus = async_mock_service(hass, "light", "turn_off")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="alarm"))
    await _setup(hass, options={"hauptlicht": "light.decke"})

    client = await hass_client_no_auth()

    async def melden(**aenderung):
        p = copy.deepcopy(PAYLOAD)
        p.update(aenderung.pop("root", {}))
        p["alarms"][0].update(aenderung)
        resp = await client.post("/api/webhook/hawecker_test123", json=p)
        assert resp.status == 200
        await hass.async_block_till_done()

    await melden(ringing=True, root={"ringing": True})
    geschlummert = dt_util.utcnow()
    await melden(ringing=False, snoozed=True, root={"ringing": False, "snoozed": True})
    await melden(ringing=True, snoozed=False, root={"ringing": True, "snoozed": False})
    assert _letzter_aufruf(aioclient_mock).query["status"] == "alarm"

    # Der 19-Minuten-Timer des Schlummerns ist damit vom Tisch
    async_fire_time_changed(hass, geschlummert + timedelta(seconds=1145))
    await hass.async_block_till_done()
    assert not aus, "das neue Klingeln hat den Schlummer-Timer abgeraeumt"


# ---------------------------------------------------------------------------
# Stromplan: die Steckdose der Saeule folgt demselben Weckplan
# ---------------------------------------------------------------------------


def _schaltrufe(hass: HomeAssistant, dienst: str) -> list[str]:
    """Mitschnitt der Aufrufe von switch.<dienst> am Bus.

    async_mock_service hilft hier nicht: die Integration richtet selbst die
    Plattform "switch" ein, und deren echter Dienst ueberschreibt den Mock.
    """
    from homeassistant.const import EVENT_CALL_SERVICE
    from homeassistant.core import Event

    treffer: list[str] = []

    @callback
    def _mitschreiben(event: Event) -> None:
        if event.data.get("domain") != "switch" or event.data.get("service") != dienst:
            return
        ziel = (event.data.get("service_data") or {}).get("entity_id")
        treffer.append(ziel)

    hass.bus.async_listen(EVENT_CALL_SERVICE, _mitschreiben)
    return treffer


async def test_stromplan_json_wird_geprueft() -> None:
    """Unsinn faellt auf den Standardplan zurueck und wird gemeldet."""
    from custom_components.ha_wecker.strom import STANDARD_STROMPLAN, stromplan_lesen

    daten, fehler = stromplan_lesen("{kein json")
    assert daten is STANDARD_STROMPLAN and "nicht lesbar" in fehler
    daten, fehler = stromplan_lesen('{"vorlauf": 60}')
    assert daten is STANDARD_STROMPLAN and "aus" in fehler
    daten, fehler = stromplan_lesen('{"aus": [{"wochentage": ["mo"], "zeit": "halb neun"}]}')
    assert daten is STANDARD_STROMPLAN and "keine Uhrzeit" in fehler
    daten, fehler = stromplan_lesen('{"vorlauf": 120, "aus": [{"zeit": "20:15"}]}')
    assert fehler is None and daten["vorlauf"] == 120


async def test_ausschaltzeit_folgt_dem_wochentag() -> None:
    """Werktags um 21 Uhr, am Wochenende um 22 - aus dem Standardplan."""
    from datetime import datetime

    from homeassistant.util import dt as dt_util

    from custom_components.ha_wecker.strom import STANDARD_STROMPLAN, naechstes_aus

    def ortszeit(tag: int, stunde: int) -> datetime:
        return datetime(2026, 11, tag, stunde, tzinfo=dt_util.DEFAULT_TIME_ZONE)

    def aus(tag: int, stunde: int):
        treffer = naechstes_aus(STANDARD_STROMPLAN, ortszeit(tag, stunde))
        lokal = dt_util.as_local(treffer)
        return lokal.weekday(), lokal.hour

    assert aus(20, 7) == (4, 21)      # Freitag frueh -> heute um 21
    assert aus(20, 23) == (5, 22)     # Freitag nach 21 -> Samstag um 22
    assert aus(22, 23) == (0, 21)     # Sonntag nach 22 -> Montag um 21
    assert aus(21, 9) == (5, 22)      # Samstag frueh -> heute um 22


def _wochenend_payload() -> dict:
    """Max' Fall: ein Wecker um 9 Uhr an Samstag und Sonntag."""
    p = copy.deepcopy(PAYLOAD)
    p["alarms"] = [
        dict(
            p["alarms"][0],
            hour=9,
            minute=0,
            days_mask=0b1100000,
            days_label="Sa+So",
            next_trigger=None,
            enabled=True,
        )
    ]
    return p


async def _berlin(hass: HomeAssistant, freezer, wann: str) -> None:
    """Feste Zeitzone und fester Zeitpunkt - sonst haengt der Test am Kalender."""
    await hass.config.async_set_time_zone("Europe/Berlin")
    freezer.move_to(wann)


async def _vorspulen(hass: HomeAssistant, freezer, wann: str) -> None:
    """Uhr stellen und die faelligen Timer feuern."""
    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import async_fire_time_changed

    freezer.move_to(wann)
    async_fire_time_changed(hass, dt_util.utcnow())
    await hass.async_block_till_done()


async def test_strom_geht_vor_dem_weckruf_an(hass: HomeAssistant, freezer) -> None:
    """Fuenf Minuten vor dem Weckruf bekommt die Saeule Strom - Standardplan."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    # Samstag, 8 Uhr Berlin. Der Wecker steht auf 9, die Ausschaltzeit auf 22.
    await _berlin(hass, freezer, "2026-11-21 07:00:00")
    entry = await _setup(hass, options={"strom": "switch.dose"})
    an = _schaltrufe(hass, "turn_on")
    aus = _schaltrufe(hass, "turn_off")
    hass.data[DOMAIN][entry.entry_id].async_set_payload(_wochenend_payload())
    await hass.async_block_till_done()
    assert not an and not aus, "eine Stunde vorher darf nichts geschaltet werden"

    strom = hass.states.get("switch.ha_wecker_weckablauf").attributes["strom"]
    assert strom["entitaet"] == "switch.dose"
    assert strom["vorlauf_minuten"] == 5.0
    assert strom["naechstes_an"].startswith("2026-11-21T07:55")
    assert strom["naechstes_aus"].startswith("2026-11-21T21:00")

    await _vorspulen(hass, freezer, "2026-11-21 07:55:05")
    assert an == ["switch.dose"]
    assert not aus

    zeilen = [
        e
        for e in hass.states.get("switch.ha_wecker_weckablauf").attributes["protokoll"]
        if e["was"].startswith("Strom")
    ]
    assert zeilen and zeilen[0]["ergebnis"] == "ok"
    assert "vor dem Weckruf" in zeilen[0]["text"]


async def test_strom_geht_zur_ausschaltzeit_aus(hass: HomeAssistant, freezer) -> None:
    """Am Wochenende um 22 Uhr geht die Steckdose aus, danach gilt der Folgetag.

    Zugleich der Nachholfall: steht das Ausschalten vor dem naechsten
    Einschalten, laeuft eine An-Phase - beim Start wird eingeschaltet.
    """
    from pytest_homeassistant_custom_component.common import async_mock_service

    # Samstag, 11 Uhr Berlin: der Weckruf ist durch, aus kommt um 22 Uhr
    await _berlin(hass, freezer, "2026-11-21 10:00:00")
    entry = await _setup(hass, options={"strom": "switch.dose"})
    an = _schaltrufe(hass, "turn_on")
    aus = _schaltrufe(hass, "turn_off")
    hass.data[DOMAIN][entry.entry_id].async_set_payload(_wochenend_payload())
    await hass.async_block_till_done()

    assert an == ["switch.dose"]
    zeilen = [
        e["text"]
        for e in hass.states.get("switch.ha_wecker_weckablauf").attributes["protokoll"]
        if e["was"].startswith("Strom")
    ]
    assert "nachgeholt" in zeilen[0]

    await _vorspulen(hass, freezer, "2026-11-21 21:00:05")
    assert aus == ["switch.dose"]

    # Danach steht der Sonntag an: erst 8:55 an, dann 22 Uhr aus
    strom = hass.states.get("switch.ha_wecker_weckablauf").attributes["strom"]
    assert strom["naechstes_an"].startswith("2026-11-22T07:55")
    assert strom["naechstes_aus"].startswith("2026-11-22T21:00")


async def test_strom_wird_nicht_nachtraeglich_ausgeschaltet(
    hass: HomeAssistant, freezer
) -> None:
    """Eine verpasste Ausschaltzeit wird nicht nachgeholt - sonst stirbt die Saeule."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    # Samstag, 23 Uhr Berlin: 22 Uhr ist vorbei, Home Assistant war gerade aus
    await _berlin(hass, freezer, "2026-11-21 22:00:00")
    entry = await _setup(hass, options={"strom": "switch.dose"})
    aus = _schaltrufe(hass, "turn_off")
    hass.states.async_set("switch.dose", "on")
    hass.data[DOMAIN][entry.entry_id].async_set_payload(_wochenend_payload())
    await hass.async_block_till_done()
    assert not aus


async def test_probelauf_schaltet_den_strom_ein(hass: HomeAssistant) -> None:
    """Ohne Strom antwortet die Saeule nicht - der Probelauf sorgt dafuer."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "light", "turn_on")
    await _setup(hass, options={"strom": "switch.dose", "hauptlicht": "light.decke"})
    an = _schaltrufe(hass, "turn_on")

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()
    assert an == ["switch.dose"]


async def test_ohne_steckdose_schaltet_nichts(hass: HomeAssistant, freezer) -> None:
    """Ist keine Entitaet eingestellt, bleibt der Stromplan still."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    await _berlin(hass, freezer, "2026-11-21 07:50:00")
    entry = await _setup(hass)
    an = _schaltrufe(hass, "turn_on")
    hass.data[DOMAIN][entry.entry_id].async_set_payload(_wochenend_payload())
    await hass.async_block_till_done()
    assert not an
    strom = hass.states.get("switch.ha_wecker_weckablauf").attributes["strom"]
    assert strom["entitaet"] == "nicht eingestellt"


# ---------------------------------------------------------------------------
# Tongeber (Relais an D7, Nr. 6): eigener Schalter, Schritt im Weckablauf
# ---------------------------------------------------------------------------


async def test_saeule_tonschalter(hass: HomeAssistant, aioclient_mock) -> None:
    """Der Ton hat seinen eigenen Schalter und steht nicht bei den Stufen."""
    await _setup_saeule(hass, aioclient_mock)

    ton = hass.states.get("switch.signalsaeule_ton")
    assert ton is not None and ton.state == "off"
    assert ton.attributes["pin"] == 7
    # Die vier Stufen und die Warnleuchte sind eigene Entitaeten, der Ton
    # gehoert zu keiner Stufe
    assert hass.states.get("switch.signalsaeule_gruen") is not None
    assert hass.states.get("switch.signalsaeule_warnleuchte") is not None

    aioclient_mock.post(f"{SAEULE_URL}/api/relais/6", json=saeule_state(ton=True))
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_ton"}, blocking=True
    )
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/relais/6"
    assert url.query["an"] == "1"
    assert hass.states.get("switch.signalsaeule_ton").state == "on"


async def test_ton_nummer_kommt_aus_der_rolle(hass: HomeAssistant, aioclient_mock) -> None:
    """Die Nummer wird gesucht, nicht geraten - eine Saeule ohne Ton faellt auf."""
    from custom_components.ha_wecker.const import DOMAIN as D, ROLLE_TON, ROLLE_WARN

    entry = await _setup_saeule(hass, aioclient_mock)
    coordinator = hass.data[D][entry.entry_id]
    assert coordinator.nummer_fuer(ROLLE_TON) == 6
    assert coordinator.nummer_fuer(ROLLE_WARN) == 5

    # Aeltere Firmware ohne Tongeber: kein Ausgang, keine geratene Nummer
    ohne = saeule_state()
    ohne["relais"] = [r for r in ohne["relais"] if r["nr"] != 6]
    coordinator.async_set_updated_data(ohne)
    assert coordinator.nummer_fuer(ROLLE_TON) is None


TON_ABLAUF = """
{"version": 1, "bloecke": [{"name": "Mit Ton", "schritte": [
  {"zeit": 0, "saeule": {"status": "alarm", "ton": true}},
  {"zeit": 0, "ab": "ende", "saeule": {"status": "kreuz", "ton": false}}]}]}
"""


async def test_standardablauf_laesst_den_ton_in_ruhe(
    hass: HomeAssistant, aioclient_mock
) -> None:
    """Der Ton gehoert nicht in den Weckruf - er hat seinen eigenen Knopf."""
    from custom_components.ha_wecker.ablauf import STANDARD_ABLAUF

    schritte = [s for b in STANDARD_ABLAUF["bloecke"] for s in b["schritte"]]
    assert schritte, "der Standardablauf ist leer"
    assert not any("ton" in (s.get("saeule") or {}) for s in schritte)

    # Und auch beim Abbruch wird ein von Hand gedrueckter Ton nicht ausgemacht
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    await _setup_saeule(hass, aioclient_mock, state=saeule_state(ton=True))
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(ton=True))
    await _setup(hass, options={"hauptlicht": "light.decke"})
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_probelauf"}, blocking=True
    )
    await hass.async_block_till_done()
    await hass.services.async_call(
        "button", "press", {"entity_id": "button.ha_wecker_ablauf_abbrechen"}, blocking=True
    )
    await hass.async_block_till_done()
    assert not [
        u for _, u, *_ in aioclient_mock.mock_calls if u.path == "/api/relais/6"
    ], "der Ablauf darf den Tonschalter nicht anfassen"


async def test_ablauf_schaltet_den_ton(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Steht "ton" in der Ablaufdatei, piept es beim Klingeln und endet beim Beenden."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="alarm"))
    aioclient_mock.post(f"{SAEULE_URL}/api/relais/6", json=saeule_state(ton=True))
    await _setup(hass, options={"hauptlicht": "light.decke", "ablauf": TON_ABLAUF})

    client = await hass_client_no_auth()

    async def melden(**aenderung):
        p = copy.deepcopy(PAYLOAD)
        p.update(aenderung.pop("root", {}))
        p["alarms"][0].update(aenderung)
        resp = await client.post("/api/webhook/hawecker_test123", json=p)
        assert resp.status == 200
        await hass.async_block_till_done()

    def tonrufe():
        return [
            u for _, u, *_ in aioclient_mock.mock_calls if u.path == "/api/relais/6"
        ]

    await melden(ringing=True, root={"ringing": True})
    assert [u.query["an"] for u in tonrufe()] == ["1"], "beim Klingeln muss es piepen"

    await melden(ringing=False, root={"ringing": False})
    assert [u.query["an"] for u in tonrufe()] == ["1", "0"], "beim Beenden sofort still"

    protokoll = hass.states.get("switch.ha_wecker_weckablauf").attributes["protokoll"]
    tonzeilen = [e["text"] for e in protokoll if e["text"].startswith("Ton ")]
    assert tonzeilen == ["Ton aus", "Ton an"]      # neueste zuerst


async def test_sicherheitsnetz_macht_den_ton_aus(hass: HomeAssistant, aioclient_mock) -> None:
    """Kommt nie ein Beenden, darf es nicht zwei Stunden weiterpiepen."""
    from datetime import timedelta

    from homeassistant.util import dt as dt_util
    from pytest_homeassistant_custom_component.common import (
        async_fire_time_changed,
        async_mock_service,
    )

    from custom_components.ha_wecker.const import ABLAUF_MAX_S

    async_mock_service(hass, "light", "turn_on")
    aus = async_mock_service(hass, "light", "turn_off")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="alarm"))
    aioclient_mock.post(f"{SAEULE_URL}/api/relais/6", json=saeule_state(ton=True))
    entry = await _setup(
        hass, options={"hauptlicht": "light.decke", "ablauf": TON_ABLAUF}
    )
    data = hass.data[DOMAIN][entry.entry_id]

    start = dt_util.utcnow()
    p = copy.deepcopy(PAYLOAD)
    p["ringing"] = True
    p["alarms"][0]["ringing"] = True
    data.async_set_payload(p)
    await hass.async_block_till_done()
    assert hass.states.get("switch.ha_wecker_weckablauf").attributes["laeuft"] is True

    # Die App meldet sich nie wieder - nach ABLAUF_MAX_S greift das Netz
    async_fire_time_changed(hass, start + timedelta(seconds=ABLAUF_MAX_S + 5))
    await hass.async_block_till_done()

    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert [e for e in zustand["protokoll"] if e["was"] == "Sicherheitsnetz"]
    letzte = [u for _, u, *_ in aioclient_mock.mock_calls if u.path == "/api/relais/6"]
    assert letzte and letzte[-1].query["an"] == "0", "der Ton muss aus sein"
    assert any(
        u.query.get("status") == "ruhe"
        for _, u, *_ in aioclient_mock.mock_calls
        if u.path == "/api/status"
    ), "und die Saeule zurueck auf Ruhe"
    assert len(aus) == 1, "und das Licht aus"
    # "laeuft" steht danach wieder: _fertig plant gleich den naechsten Vorlauf.
    # Der alte Lauf ist aber zu Ende - der Nullpunkt zeigt auf den naechsten
    # Weckruf, nicht mehr auf den verpassten.
    assert zustand["beendet_um"] is None


async def test_vorlauf_zieht_bei_geaenderter_weckzeit_mit(
    hass: HomeAssistant, aioclient_mock, freezer
) -> None:
    """Wird der Wecker verstellt, waehrend der Vorlauf steht, gilt die neue Zeit.

    Max' Fall vom 16.11.: abends 05:00 auf 04:50 umgestellt. Der Vorlauf stand
    noch auf 04:59, und weil "laeuft" gesetzt war, plante der Ablauf nicht neu.
    Um 04:50 klingelte es, die alten Timer wurden abgeraeumt, und Hinweis und
    die 5 % Licht fielen ganz aus.
    """
    from pytest_homeassistant_custom_component.common import async_mock_service

    await _berlin(hass, freezer, "2026-11-16T21:00:00")
    an = async_mock_service(hass, "light", "turn_on")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="hinweis"))
    entry = await _setup(hass, options={"hauptlicht": "light.decke"})
    data = hass.data[DOMAIN][entry.entry_id]

    def mit_weckzeit(stunde, minute):
        p = copy.deepcopy(PAYLOAD)
        p["alarms"] = [
            dict(p["alarms"][0], hour=stunde, minute=minute, days_mask=31,
                 next_trigger=None, enabled=True)
        ]
        return p

    data.async_set_payload(mit_weckzeit(5, 0))
    await hass.async_block_till_done()
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["laeuft"] is True
    assert zustand["nullpunkt"].startswith("2026-11-17T04:00")   # 05:00 Berlin

    # Jetzt auf 04:50 umstellen - der Ablauf muss den Nullpunkt nachziehen
    data.async_set_payload(mit_weckzeit(4, 50))
    await hass.async_block_till_done()
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["nullpunkt"].startswith("2026-11-17T03:50")   # 04:50 Berlin

    # Eine Minute vor dem neuen Termin laeuft der Vorlauf wirklich
    await _vorspulen(hass, freezer, "2026-11-17T03:49:05")
    assert [(c.service, c.data.get("brightness_pct")) for c in an] == [("turn_on", 5)]
    assert _letzter_aufruf(aioclient_mock).query["status"] == "hinweis"


async def test_vorlauf_bleibt_waehrend_des_nachlaufs_stehen(
    hass: HomeAssistant, aioclient_mock, hass_client_no_auth: ClientSessionGenerator
) -> None:
    """Der Nachlauf darf nicht vom naechsten Wecker ueberschrieben werden."""
    from pytest_homeassistant_custom_component.common import async_mock_service

    async_mock_service(hass, "light", "turn_on")
    async_mock_service(hass, "light", "turn_off")
    await _setup_saeule(hass, aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="kreuz"))
    await _setup(hass, options={"hauptlicht": "light.decke"})

    client = await hass_client_no_auth()

    async def melden(**aenderung):
        p = copy.deepcopy(PAYLOAD)
        p.update(aenderung.pop("root", {}))
        p["alarms"][0].update(aenderung)
        resp = await client.post("/api/webhook/hawecker_test123", json=p)
        assert resp.status == 200
        await hass.async_block_till_done()

    await melden(ringing=True, root={"ringing": True})
    await melden(ringing=False, root={"ringing": False})
    beendet = hass.states.get("switch.ha_wecker_weckablauf").attributes["beendet_um"]
    assert beendet

    # Noch eine Meldung der App, waehrend der Nachlauf laeuft: er bleibt stehen
    await melden(ringing=False, root={"ringing": False})
    zustand = hass.states.get("switch.ha_wecker_weckablauf").attributes
    assert zustand["beendet_um"] == beendet
    assert len([e for e in zustand["protokoll"] if "ab dem Beenden" in e["text"]]) == 1


# ---------------------------------------------------------------------------
# Garage (ESP32 an der Lichtschranke)
# ---------------------------------------------------------------------------

GARAGE_URL = "http://192.168.1.110"


def garage_state(ampel="stopp", auto_drin=True, strom=True, tor="auf", auto=True,
                 verriegelt=False, zuendung=True, rueckwaerts=False, lampe=True):
    return {
        "typ": "garage", "name": "Garage", "version": "ls-1.8", "mac": "24:6f:28:aa:bb:cc",
        "ip": "192.168.1.110", "events_port": 8081,
        "ampel": ampel, "ampel_grund": "Lichtschranke durchtrennt, Tor auf",
        "auto_drin": auto_drin, "strom": strom, "lampe": lampe, "lampe_blinkt": False, "lampe_rest_s": 10,
        "tor": tor, "tor_entitaet": "cover.garagentor", "tor_gelesen_s": 2,
        "auto_zu_hoeren": auto, "auto_zuletzt_s": 1 if auto else None, "auto_pakete": 1234,
        "auto_verriegelt": verriegelt if auto else None, "auto_zuendung": zuendung if auto else None,
        "auto_rueckwaerts": rueckwaerts if auto else None, "auto_aufgesperrt": auto and not verriegelt,
        "funk_kanal": 1, "wlan_rssi": -61, "laufzeit_s": 4200, "ha_ok": True, "ha_angemeldet": True,
    }


async def _setup_garage(hass: HomeAssistant, aioclient_mock, state=None) -> MockConfigEntry:
    aioclient_mock.get(f"{GARAGE_URL}/api/state", json=state or garage_state())
    entry = MockConfigEntry(
        domain=DOMAIN, title="Garage", unique_id="24:6f:28:aa:bb:cc",
        data={"typ": "garage", "name": "Garage", "host": "192.168.1.110"},
    )
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry


async def test_garage_entities(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_garage(hass, aioclient_mock)

    ampel = hass.states.get("sensor.garage_ampel")
    assert ampel.state == "stopp"
    assert ampel.attributes["tor"] == "auf"
    assert hass.states.get("binary_sensor.garage_auto_in_der_garage").state == "on"
    assert hass.states.get("binary_sensor.garage_auto_esp_verbunden").state == "on"
    assert hass.states.get("binary_sensor.garage_auto_esp_verbunden").attributes["pakete"] == 1234
    # device_class lock: "on" heisst entriegelt - das Auto ist nicht verriegelt
    assert hass.states.get("binary_sensor.garage_auto_verriegelt").state == "on"
    assert hass.states.get("binary_sensor.garage_zundung_des_autos").state == "on"
    assert hass.states.get("binary_sensor.garage_ruckwartsgang").state == "off"
    assert hass.states.get("binary_sensor.garage_lichtschranke_strom").state == "on"
    assert hass.states.get("binary_sensor.garage_rote_lampe").state == "on"
    assert hass.states.get("binary_sensor.garage_tor_laut_esp").state == "on"
    assert hass.states.get("sensor.garage_pakete_vom_auto").state == "1234"
    assert hass.states.get("sensor.garage_auto_zuletzt_gehort").state != "unknown"
    assert hass.states.get("button.garage_lampe_testen") is not None
    assert hass.states.get("button.garage_neustart") is not None
    # Nichts von der Saeule oder vom Wecker haengt am Garagen-Geraet
    assert hass.states.get("switch.garage_weckerlampe") is None
    assert hass.states.get("select.garage_status") is None


async def test_garage_ohne_auto(hass: HomeAssistant, aioclient_mock) -> None:
    """Ohne Auto in Funkreichweite sind dessen Werte nicht verfuegbar, nicht etwa 'aus'."""
    await _setup_garage(hass, aioclient_mock, garage_state(ampel="aus", auto=False, tor="zu", lampe=False, auto_drin=False))
    assert hass.states.get("sensor.garage_ampel").state == "aus"
    assert hass.states.get("binary_sensor.garage_auto_esp_verbunden").state == "off"
    assert hass.states.get("binary_sensor.garage_auto_verriegelt").state == "unavailable"
    assert hass.states.get("binary_sensor.garage_zundung_des_autos").state == "unavailable"
    assert hass.states.get("sensor.garage_auto_zuletzt_gehort").state == "unknown"
    assert hass.states.get("binary_sensor.garage_tor_laut_esp").state == "off"


async def test_garage_lampe_testen(hass: HomeAssistant, aioclient_mock) -> None:
    await _setup_garage(hass, aioclient_mock)
    aioclient_mock.post(f"{GARAGE_URL}/api/lampe", json=garage_state(lampe=True))
    await hass.services.async_call("button", "press", {"entity_id": "button.garage_lampe_testen"}, blocking=True)
    await hass.async_block_till_done()
    url = _letzter_aufruf(aioclient_mock)
    assert url.path == "/api/lampe" and url.query["an"] == "1"


async def test_garage_config_flow_wie_der_esp(hass: HomeAssistant, aioclient_mock) -> None:
    """Genau die drei Schritte, die der ESP ueber die REST-Schnittstelle geht."""
    aioclient_mock.get(f"{GARAGE_URL}/api/state", json=garage_state())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == "menu"
    assert "garage" in result["menu_options"]
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "garage"})
    assert result["type"] == "form" and result["step_id"] == "garage"
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Garage", "host": "192.168.1.110"})
    assert result["type"] == "create_entry"
    assert result["data"] == {"typ": "garage", "name": "Garage", "host": "192.168.1.110"}
    await hass.async_block_till_done()
    # Zweiter Anlauf mit neuer IP: kein zweites Geraet, nur die Adresse wird nachgezogen
    aioclient_mock.get("http://192.168.1.111/api/state", json=garage_state())
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"next_step_id": "garage"})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {"name": "Garage", "host": "192.168.1.111"})
    assert result["type"] == "abort" and result["reason"] == "already_configured"
    eintraege = [e for e in hass.config_entries.async_entries(DOMAIN) if e.data.get("typ") == "garage"]
    assert len(eintraege) == 1 and eintraege[0].data["host"] == "192.168.1.111"


# --- Betriebsart "Ampel": die Saeule zeigt die Garagenampel ------------------


@pytest.fixture
def schnelle_phasen():
    """Gelb steht drei echte Sekunden - im Test im Zeitraffer.

    Die Schritte und ihre Reihenfolge bleiben, nur die Standzeiten fallen
    weg: sonst dauerte jeder Ampeltest mehr als zehn Sekunden.
    """
    from unittest.mock import patch

    from custom_components.ha_wecker import ampel as ampel_modul

    kurz = tuple((bild, 1) for bild, _ in ampel_modul.AMPEL_START)
    with patch.object(ampel_modul, "AMPEL_START", kurz), \
         patch.object(ampel_modul, "AMPEL_GELB_MS", 1), \
         patch.object(ampel_modul, "AMPEL_ROT_GELB_MS", 1):
        yield


STUFE_FARBE = {1: "gruen", 2: "orange", 3: "rot", 4: "hinweis"}


def _bilder(aioclient_mock, ab: int = 0) -> list[set[str]]:
    """Die Stufenbilder, die nacheinander gestellt wurden, nach Farbe.

    Die Integration setzt die vier Stufen der Reihe nach (die Saeule kann
    nicht mehr); dieser Helfer macht daraus wieder Bilder, damit die Tests
    nicht von der Reihenfolge einzelner Anfragen abhaengen.
    """
    bilder: list[set[str]] = []
    offen: set[str] = set()
    for pfad in _postpfade(aioclient_mock)[ab:]:
        m = re.match(r"/api/relais/(\d+)\?an=([01])", pfad)
        if not m:
            continue
        nr, an = int(m.group(1)), m.group(2) == "1"
        farbe = STUFE_FARBE.get(nr)
        if farbe is None:
            continue
        if an:
            offen.add(farbe)
        else:
            offen.discard(farbe)
        if nr == max(STUFE_FARBE):          # nach der letzten Stufe steht es
            bilder.append(set(offen))
    return bilder


def _postpfade(aioclient_mock) -> list[str]:
    """Pfad samt Query jedes POST an ein Geraet, in der Reihenfolge."""
    pfade = []
    for c in aioclient_mock.mock_calls:
        if c[0].lower() != "post":
            continue
        url = c[1]
        pfade.append(url.path + (f"?{url.query_string}" if url.query_string else ""))
    return pfade


def _saeule_posts(aioclient_mock, **kw) -> None:
    """Die Antworten, die die Saeule auf die Befehle der Ampel gibt.

    Der Piep antwortet noch mit dem Zustand von vorher - er stellt ja nichts
    um. Erst der Modusbefehl bringt die Saeule auf manuell.
    """
    antwort = saeule_state(modus="manuell", **kw)
    aioclient_mock.post(f"{SAEULE_URL}/api/piep", json=saeule_state(**kw))
    aioclient_mock.post(f"{SAEULE_URL}/api/modus", json=antwort)
    aioclient_mock.post(f"{SAEULE_URL}/api/stufen", json=antwort)
    for nr in range(1, 7):
        aioclient_mock.post(f"{SAEULE_URL}/api/relais/{nr}", json=antwort)


def _garage_melden(hass: HomeAssistant, entry, **kw) -> None:
    """Dem Garagen-Coordinator einen neuen Stand unterschieben."""
    hass.data[DOMAIN][entry.entry_id].async_set_updated_data(garage_state(**kw))


async def _betriebsart(hass: HomeAssistant, wahl: str) -> None:
    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.signalsaeule_betriebsart", "option": wahl},
        blocking=True,
    )
    await hass.async_block_till_done()


async def test_ampel_eroeffnung_fahrt_einmal_vor(
    hass: HomeAssistant, aioclient_mock, schnelle_phasen
) -> None:
    """Beim Einschalten: gelb blinkt, dann gruen, rot, gruen, dann das Bild."""
    await _setup_garage(hass, aioclient_mock)          # Auto steht drin
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    assert _bilder(aioclient_mock) == [
        {"orange"},                 # Inbetriebnahme
        {"rot"},
        {"rot", "orange"},          # rot -> rot+gelb -> gruen
        {"gruen"},
        {"orange"},                 # gruen -> gelb -> rot
        {"rot"},
        {"rot", "orange"},
        {"gruen"},
        {"orange"},                 # und von dort zum echten Bild,
        {"rot"},                    # auch ueber die Zwischenphase
    ]


async def test_ampel_fehlt_ohne_garage(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Ohne Garagen-ESP hat der Schalter nur Auto und Manuell."""
    await _setup_saeule(hass, aioclient_mock)
    st = hass.states.get("select.signalsaeule_betriebsart")
    assert st.attributes["options"] == ["Auto", "Manuell"]
    assert st.attributes["garage"] == "nicht eingerichtet"


async def test_ampel_umschalten_piept_und_zeigt_rot(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Auto steht drin: zwei kurze Toene, dann rot - und nur rot."""
    await _setup_garage(hass, aioclient_mock)          # ampel = stopp
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)

    st = hass.states.get("select.signalsaeule_betriebsart")
    assert "Ampel" in st.attributes["options"]

    await _betriebsart(hass, "Ampel")

    pfade = _postpfade(aioclient_mock)
    # Der Quittungston kommt vor dem Bild
    assert pfade[0] == "/api/piep"
    # Zuletzt steht Rot, und nur Rot
    assert _bilder(aioclient_mock)[-1] == {"rot"}
    # Die Warnleuchte und der Tongeber gehoeren zu keinem Bild
    assert not [p for p in pfade if p.startswith("/api/relais/5")]
    assert not [p for p in pfade if p.startswith("/api/relais/6")]

    st = hass.states.get("select.signalsaeule_betriebsart")
    assert st.state == "Ampel"
    assert st.attributes["lage"] == "besetzt"
    assert st.attributes["geraet"] == "manuell"
    assert st.attributes["ampel_fehler"] is None


async def test_ampel_folgt_der_garage(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Wird die Garage frei, wird die Saeule gruen - ohne Zutun."""
    garage = await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="frei", auto_drin=False, lampe=False)
    await hass.async_block_till_done()

    # Rot auf Gruen geht ueber Rot und Gelb zusammen - das ist das Deutsche daran
    assert _bilder(aioclient_mock, vorher) == [{"rot", "orange"}, {"gruen"}]
    assert hass.states.get("select.signalsaeule_betriebsart").attributes["lage"] == "frei"

    # Dasselbe noch einmal gemeldet schaltet nicht wieder - das Bild steht schon
    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="frei", auto_drin=False, lampe=False)
    await hass.async_block_till_done()
    assert _postpfade(aioclient_mock)[vorher:] == []


async def test_ampel_folgt_dem_platz_nicht_der_lampe(
    hass: HomeAssistant, aioclient_mock, schnelle_phasen
) -> None:
    """Die Lampe des ESP geht aus, wenn niemand einparkt - rot bleibt.

    Genau das ging am 17.11. schief: das Auto stand in der Garage, die
    Lichtschranke war durchtrennt, und der ESP meldete "ampel: aus" ("Tor zu
    und kein Auto zu hoeren"). Die Statusanzeige im Zimmer muss trotzdem rot
    zeigen - sie folgt dem Stellplatz, nicht der Lampe.
    """
    await _setup_garage(
        hass, aioclient_mock,
        garage_state(ampel="aus", auto_drin=True, strom=True, tor="zu",
                     auto=False, lampe=False),
    )
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    assert _postpfade(aioclient_mock)[0] == "/api/piep"
    assert _bilder(aioclient_mock)[-1] == {"rot"}
    st = hass.states.get("select.signalsaeule_betriebsart")
    assert st.attributes["lage"] == "besetzt"
    assert st.attributes["ampel"] == "aus"           # was der ESP seiner Lampe sagt


async def test_ampel_ohne_urteil_blinkt_gelb(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Weiss der ESP nichts ueber den Platz, ist das eine Stoerung."""
    daten = garage_state(ampel="aus", strom=True)
    daten["auto_drin"] = None
    await _setup_garage(hass, aioclient_mock, daten)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    # Lieber eine Stoerung zeigen als faelschlich gruen
    assert _bilder(aioclient_mock) == [{"orange", "hinweis"}]


async def test_ampel_gruen_auf_rot_ueber_gelb(
    hass: HomeAssistant, aioclient_mock, schnelle_phasen
) -> None:
    """Das Auto faehrt herein: gruen, gelb, rot - wie an der Kreuzung."""
    garage = await _setup_garage(
        hass, aioclient_mock, garage_state(ampel="frei", auto_drin=False),
    )
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="stopp", auto_drin=True)
    await hass.async_block_till_done()

    assert _bilder(aioclient_mock, vorher) == [{"orange"}, {"rot"}]


async def test_ampel_stoerung_ohne_ueberblenden(
    hass: HomeAssistant, aioclient_mock, schnelle_phasen
) -> None:
    """Zu einer Stoerung wird nicht ueberblendet - die muss sofort da sein."""
    garage = await _setup_garage(
        hass, aioclient_mock, garage_state(ampel="frei", auto_drin=False),
    )
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="kein_strom", strom=False, auto_drin=False)
    await hass.async_block_till_done()

    assert _bilder(aioclient_mock, vorher) == [{"orange", "hinweis"}]


async def test_ampel_stoerung_blinkt_gelb(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Kein Strom am Tor: gelb blinkt im Sekundentakt, Hinweis sehr schnell."""
    await _setup_garage(hass, aioclient_mock, garage_state(ampel="kein_strom", strom=False, auto_drin=False))
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    # Gelb und die Hinweisleuchte oben, ohne Eroeffnung: eine Stoerung sofort
    assert _bilder(aioclient_mock) == [{"orange", "hinweis"}]
    assert _postpfade(aioclient_mock)[0] == "/api/piep"


async def test_ampel_ueberlebt_ein_neuladen_der_garage(
    hass: HomeAssistant, aioclient_mock, schnelle_phasen
) -> None:
    """Nach einem Reload der Garage haengt der Listener am neuen Coordinator."""
    garage = await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    alt = hass.data[DOMAIN][garage.entry_id]
    await hass.config_entries.async_reload(garage.entry_id)
    await hass.async_block_till_done()
    neu_coordinator = hass.data[DOMAIN][garage.entry_id]
    assert neu_coordinator is not alt          # wirklich ein neues Objekt

    # Und die Saeule folgt dem neuen: ein Wort aus der Garage wirkt wieder
    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="frei", auto_drin=False)
    await hass.async_block_till_done()
    assert {"gruen"} in _bilder(aioclient_mock, vorher)
    assert hass.states.get("select.signalsaeule_betriebsart").state == "Ampel"


async def test_ampel_ohne_esp_blinkt_rot(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Antwortet der ESP nicht, fehlen ihm die 5 V: rot im Takt der gelben."""
    garage = await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    vorher = len(_postpfade(aioclient_mock))
    from homeassistant.helpers.update_coordinator import UpdateFailed

    coordinator = hass.data[DOMAIN][garage.entry_id]
    coordinator.async_set_update_error(UpdateFailed("weg"))
    await hass.async_block_till_done()

    # Rot und die Hinweisleuchte oben, ohne Ueberblenden
    assert _bilder(aioclient_mock, vorher) == [{"rot", "hinweis"}]
    assert hass.states.get("select.signalsaeule_betriebsart").attributes["lage"] == "kein_esp"


async def test_ampel_endet_bei_status_von_hand(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Einen Status zu waehlen heisst: ich stelle selbst."""
    garage = await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="alarm"))

    await hass.services.async_call(
        "select", "select_option",
        {"entity_id": "select.signalsaeule_status", "option": "Alarm"}, blocking=True,
    )
    await hass.async_block_till_done()
    assert hass.states.get("select.signalsaeule_betriebsart").state != "Ampel"

    # Und die Garage schaltet jetzt nichts mehr
    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="frei", auto_drin=False)
    await hass.async_block_till_done()
    assert _postpfade(aioclient_mock)[vorher:] == []


async def test_ampel_endet_bei_stufe_von_hand_nicht_beim_ton(
    hass: HomeAssistant, aioclient_mock, schnelle_phasen
) -> None:
    """Eine Stufe von Hand beendet die Ampel, Warnleuchte und Ton nicht."""
    await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    await _betriebsart(hass, "Ampel")

    # Tongeber: gehoert zu keinem Bild, die Ampel bleibt
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_ton"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("select.signalsaeule_betriebsart").state == "Ampel"

    # Warnleuchte: dasselbe
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_warnleuchte"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("select.signalsaeule_betriebsart").state == "Ampel"

    # Eine Stufe dagegen beendet sie
    await hass.services.async_call(
        "switch", "turn_on", {"entity_id": "switch.signalsaeule_orange"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("select.signalsaeule_betriebsart").state != "Ampel"


async def test_ampel_endet_bei_alles_aus(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Alles aus heisst alles aus - sonst waere der Knopf wirkungslos."""
    garage = await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    _saeule_posts(aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/alarm/stop", json=saeule_state(modus="manuell"))
    await _betriebsart(hass, "Ampel")

    await hass.services.async_call(
        "button", "press", {"entity_id": "button.signalsaeule_alles_aus"}, blocking=True
    )
    await hass.async_block_till_done()
    assert hass.states.get("select.signalsaeule_betriebsart").state != "Ampel"

    # Und die Garage schaltet die Saeule nicht wieder an
    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="frei", auto_drin=False)
    await hass.async_block_till_done()
    assert _postpfade(aioclient_mock)[vorher:] == []


async def test_ampel_ruht_waehrend_des_weckrufs(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Der Weckruf hat Vorrang und gibt die Ampel danach wieder frei."""
    garage = await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock)
    entry = await _setup(hass)
    _saeule_posts(aioclient_mock)
    aioclient_mock.post(f"{SAEULE_URL}/api/status", json=saeule_state(status="alarm"))
    await _betriebsart(hass, "Ampel")

    ablauf = hass.data[DOMAIN][entry.entry_id].ablauf
    saeule = ablauf.saeule()

    # Ein Schritt des Weckablaufs fasst die Saeule an
    await ablauf._saeule({"status": "alarm"})
    assert saeule.ampel.pausiert is True
    assert hass.states.get("select.signalsaeule_betriebsart").state == "Ampel"

    # Jetzt wird die Garage frei - das darf den Weckruf nicht stoeren
    vorher = len(_postpfade(aioclient_mock))
    _garage_melden(hass, garage, ampel="frei", auto_drin=False)
    await hass.async_block_till_done()
    assert _postpfade(aioclient_mock)[vorher:] == []

    # Am Ende des Laufs zieht die Ampel ihr Bild nach
    from homeassistant.util import dt as dt_util

    ablauf._fertig(dt_util.utcnow())
    await hass.async_block_till_done()
    assert saeule.ampel.pausiert is False
    assert {"gruen"} in _bilder(aioclient_mock, vorher)   # die Garage ist frei
    assert any(n["was"] == "Betriebsart Ampel" for n in ablauf.protokoll)


async def test_ampel_braucht_die_farben_der_firmware(hass: HomeAssistant, aioclient_mock, schnelle_phasen) -> None:
    """Eine alte Firmware ohne Farben: kein Bild, aber eine klare Auskunft."""
    await _setup_garage(hass, aioclient_mock)
    await _setup_saeule(hass, aioclient_mock, saeule_state(mit_farbe=False))
    _saeule_posts(aioclient_mock, mit_farbe=False)
    await _betriebsart(hass, "Ampel")

    st = hass.states.get("select.signalsaeule_betriebsart")
    assert st.state == "Ampel"
    assert "1.3.0" in st.attributes["ampel_fehler"]
    assert not [p for p in _postpfade(aioclient_mock) if p.startswith("/api/relais/")]
