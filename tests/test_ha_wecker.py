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

    with patch("custom_components.ha_wecker.saeule.SaeuleCoordinator.async_start_events"):
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
                 warn_vom_alarm=False):
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
                        "stoerung": "Störung", "alarm": "Alarm",
                        "kreuz": "Kreuzwechsel", "blinker": "Blinker"}[status],
        "wechsel": False, "warn": warn, "warn_vom_alarm": warn_vom_alarm, "test": test,
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
