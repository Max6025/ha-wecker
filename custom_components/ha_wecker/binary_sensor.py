"""Binaersensoren der HA-Wecker-Integration.

- "Klingelt": laeuft gerade ein Weckruf
- je Wecker ein eigener Binaersensor (an/aus), der beim ersten Auftauchen
  einer Wecker-ID im Payload angelegt und beim Verschwinden wieder aus dem
  Entitaetsregister entfernt wird.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WeckerData
from .const import DOMAIN, SIGNAL_UPDATE
from .entity import GarageEntity, SaeuleEntity, WeckerEntity
from .garage import GarageCoordinator
from .saeule import SaeuleCoordinator

_LOGGER = logging.getLogger(__name__)


def _alarm_ids(payload: dict[str, Any] | None) -> dict[int, dict[str, Any]]:
    """Alle Wecker aus dem Payload, nach ID."""
    result: dict[int, dict[str, Any]] = {}
    for alarm in (payload or {}).get("alarms", []) or []:
        if not isinstance(alarm, dict):
            continue
        raw_id = alarm.get("id")
        if isinstance(raw_id, bool) or not isinstance(raw_id, (int, float)):
            continue
        result[int(raw_id)] = alarm
    return result


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if isinstance(obj, SaeuleCoordinator):
        async_add_entities([SaeuleWechselBinarySensor(obj), SaeuleDiagnoseOkBinarySensor(obj)])
        return
    if isinstance(obj, GarageCoordinator):
        async_add_entities(
            [
                GarageJaNein(obj, "auto_drin", "Auto in der Garage", BinarySensorDeviceClass.OCCUPANCY, "mdi:garage-variant"),
                GarageTor(obj),
                GarageAutoVerbunden(obj),
                GarageAutoWert(obj, "auto_verriegelt", "Auto verriegelt", BinarySensorDeviceClass.LOCK, "mdi:car-key", umkehren=True),
                GarageAutoWert(obj, "auto_zuendung", "Zündung des Autos", BinarySensorDeviceClass.POWER, "mdi:key-variant"),
                GarageAutoWert(obj, "auto_rueckwaerts", "Rückwärtsgang", None, "mdi:car-back"),
                GarageJaNein(obj, "strom", "Lichtschranke Strom", BinarySensorDeviceClass.POWER, "mdi:flash"),
                GarageLampe(obj),
                GarageEreignisstrom(obj),
            ]
        )
        return
    data: WeckerData = obj
    async_add_entities([RingingBinarySensor(data), SleepBinarySensor(data)])

    known: dict[int, AlarmBinarySensor] = {}

    @callback
    def _sync_alarms() -> None:
        """Neue Wecker anlegen, verschwundene entfernen."""
        current = _alarm_ids(data.payload)

        new_entities = [
            AlarmBinarySensor(data, alarm_id)
            for alarm_id in current
            if alarm_id not in known
        ]
        for ent in new_entities:
            known[ent.alarm_id] = ent
        if new_entities:
            async_add_entities(new_entities)

        # Nur entfernen, wenn ueberhaupt ein Payload da ist - ohne Payload
        # (noch nie gemeldet) sollen die wiederhergestellten Entitaeten bleiben.
        if data.payload is None:
            return
        gone = [alarm_id for alarm_id in known if alarm_id not in current]
        for alarm_id in gone:
            ent = known.pop(alarm_id)
            hass.async_create_task(ent.async_remove_completely())

    # Beim Start: Registereintraege aus frueheren Laeufen beruecksichtigen.
    # Ist ein Payload da, werden verwaiste Eintraege (Wecker in der App
    # geloescht, waehrend HA aus war) direkt aus dem Register entfernt;
    # ohne Payload bleiben sie als "nicht verfuegbar" stehen.
    registry = er.async_get(hass)
    prefix = f"{entry.entry_id}_alarm_"
    current_ids = _alarm_ids(data.payload)
    for reg_entry in er.async_entries_for_config_entry(registry, entry.entry_id):
        if reg_entry.domain != "binary_sensor" or not reg_entry.unique_id.startswith(prefix):
            continue
        try:
            alarm_id = int(reg_entry.unique_id[len(prefix) :])
        except ValueError:
            continue
        if data.payload is not None and alarm_id not in current_ids:
            registry.async_remove(reg_entry.entity_id)
            continue
        if alarm_id not in known:
            known[alarm_id] = AlarmBinarySensor(data, alarm_id)
    if known:
        async_add_entities(list(known.values()))

    _sync_alarms()
    entry.async_on_unload(
        async_dispatcher_connect(
            hass, SIGNAL_UPDATE.format(entry.entry_id), _sync_alarms
        )
    )


class RingingBinarySensor(WeckerEntity, BinarySensorEntity):
    """Laeuft gerade ein Weckruf?"""

    _attr_name = "Klingelt"
    _attr_icon = "mdi:alarm-bell"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "ringing")

    @property
    def is_on(self) -> bool | None:
        value = self.payload.get("ringing")
        return bool(value) if value is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.payload
        alarms = _alarm_ids(p)
        ringing = alarms.get(p.get("ringing_id")) if p.get("ringing_id") is not None else None
        return {
            "ringing_id": p.get("ringing_id"),
            "name": (ringing or {}).get("label") or (ringing or {}).get("name"),
            "snoozed": p.get("snoozed"),
        }


class SleepBinarySensor(WeckerEntity, BinarySensorEntity):
    """Schlafenszeit der App: an, solange das eingestellte Fenster laeuft."""

    _attr_name = "Schlafenszeit"
    _attr_icon = "mdi:sleep"

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "sleep")

    @property
    def _sleep(self) -> dict[str, Any]:
        s = self.payload.get("sleep")
        return s if isinstance(s, dict) else {}

    @property
    def available(self) -> bool:
        # Aeltere App-Versionen (api_version 1) kennen keine Schlafenszeit
        return super().available and bool(self._sleep)

    @property
    def is_on(self) -> bool | None:
        v = self._sleep.get("active")
        return bool(v) if v is not None else None

    @property
    def icon(self) -> str:
        return "mdi:sleep" if self.is_on else "mdi:sleep-off"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        s = self._sleep
        return {
            "eingeschaltet": s.get("enabled"),
            "von": s.get("start"),
            "bis": s.get("end"),
            "naechster_beginn": s.get("next_start"),
            "naechstes_ende": s.get("next_end"),
            "rest_minuten": s.get("remaining_minutes"),
        }


class AlarmBinarySensor(WeckerEntity, BinarySensorEntity):
    """Ein einzelner Wecker: an = eingeschaltet."""

    _attr_icon = "mdi:alarm"

    def __init__(self, data: WeckerData, alarm_id: int) -> None:
        super().__init__(data, f"alarm_{alarm_id}")
        self.alarm_id = alarm_id

    @property
    def _alarm(self) -> dict[str, Any] | None:
        return _alarm_ids(self.payload).get(self.alarm_id)

    @property
    def name(self) -> str:
        alarm = self._alarm or {}
        label = (alarm.get("label") or alarm.get("name") or "").strip()
        time = alarm.get("time") or ""
        # has_entity_name: HA stellt den Geraetenamen voran -> "HA Wecker 06:30 Arbeit".
        # Die entity_id wird nur beim ersten Anlegen aus dem Namen gebildet und
        # bleibt danach stabil, auch wenn die Uhrzeit geaendert wird.
        if label and time:
            return f"{time} {label}"
        if time:
            return time
        return f"Wecker {self.alarm_id}"

    @property
    def available(self) -> bool:
        return self._alarm is not None

    @property
    def is_on(self) -> bool | None:
        alarm = self._alarm
        if alarm is None:
            return None
        return bool(alarm.get("enabled"))

    @property
    def icon(self) -> str:
        alarm = self._alarm or {}
        if alarm.get("ringing"):
            return "mdi:alarm-bell"
        if alarm.get("snoozed"):
            return "mdi:alarm-snooze"
        if not alarm.get("enabled"):
            return "mdi:alarm-off"
        if alarm.get("skip_next"):
            return "mdi:alarm-note-off"
        return "mdi:alarm"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        alarm = self._alarm or {}
        return {
            "id": self.alarm_id,
            "name": alarm.get("label") or alarm.get("name"),
            "uhrzeit": alarm.get("time"),
            "stunde": alarm.get("hour"),
            "minute": alarm.get("minute"),
            "tage": alarm.get("days_label"),
            "tage_liste": alarm.get("days"),
            "tage_maske": alarm.get("days_mask"),
            "wiederkehrend": alarm.get("repeating"),
            "naechster_termin": alarm.get("next_trigger"),
            "naechster_termin_in": alarm.get("next_trigger_in"),
            "naechster_termin_in_minuten": alarm.get("next_trigger_in_minutes"),
            "heute_uebersprungen": alarm.get("skip_next"),
            "geschlummert": alarm.get("snoozed"),
            "geschlummert_bis": alarm.get("snoozed_until"),
            "klingelt": alarm.get("ringing"),
            "vibration": alarm.get("vibrate"),
            "schlummer_minuten": alarm.get("snooze_minutes"),
        }

    async def async_remove_completely(self) -> None:
        """Entitaet samt Registereintrag loeschen (Wecker wurde in der App geloescht)."""
        registry = er.async_get(self.hass)
        entity_id = registry.async_get_entity_id(
            "binary_sensor", DOMAIN, self._attr_unique_id or ""
        )
        if entity_id:
            # Entfernt den Registereintrag und damit auch die Entitaet selbst.
            registry.async_remove(entity_id)
        else:
            await self.async_remove(force_remove=True)
        _LOGGER.debug("Wecker %s entfernt (%s)", self.alarm_id, entity_id or "ohne Register")


class SaeuleWechselBinarySensor(SaeuleEntity, BinarySensorEntity):
    """An, solange die Saeule einen Statuswechsel ansagt."""

    _attr_name = "Wechsel laeuft"
    _attr_icon = "mdi:transfer-up"
    _attr_device_class = BinarySensorDeviceClass.RUNNING

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "wechsel")

    @property
    def is_on(self) -> bool:
        return bool((self.coordinator.data or {}).get("wechsel"))


class SaeuleDiagnoseOkBinarySensor(SaeuleEntity, BinarySensorEntity):
    """Problem, wenn die letzte Selbstdiagnose etwas beanstandet hat."""

    _attr_name = "Beanstandung"
    _attr_device_class = BinarySensorDeviceClass.PROBLEM
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "diagnose_problem")

    @property
    def available(self) -> bool:
        return super().available and bool(self.coordinator.diagnose.get("fertig"))

    @property
    def is_on(self) -> bool:
        punkte = self.coordinator.diagnose.get("punkte") or []
        return any(isinstance(p, dict) and p.get("ok") == 0 for p in punkte)


# ---------------------------------------------------------------------------
# Garage (ESP32 an der Lichtschranke)
# ---------------------------------------------------------------------------


class GarageJaNein(GarageEntity, BinarySensorEntity):
    """Ein dreiwertiger Wert des ESP: an, aus oder (noch) unbekannt."""

    def __init__(self, coordinator: GarageCoordinator, key: str, name: str,
                 klasse: BinarySensorDeviceClass | None, icon: str) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_device_class = klasse
        self._attr_icon = icon

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.ja(self._key) is not None

    @property
    def is_on(self) -> bool | None:
        return self.coordinator.ja(self._key)


class GarageTor(GarageEntity, BinarySensorEntity):
    """Das Garagentor, wie der ESP es von Home Assistant gelesen hat (an = offen).

    Klingt doppelt - das Tor hat ja schon seine cover-Entitaet -, zeigt aber,
    was der ESP glaubt: danach richtet sich die Lampe.
    """

    _attr_name = "Tor laut ESP"
    _attr_device_class = BinarySensorDeviceClass.GARAGE_DOOR
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "tor")

    @property
    def available(self) -> bool:
        return super().available and self.daten.get("tor") in ("auf", "zu")

    @property
    def is_on(self) -> bool | None:
        tor = self.daten.get("tor")
        return None if tor not in ("auf", "zu") else tor == "auf"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"entitaet": self.daten.get("tor_entitaet"), "gelesen_vor_s": self.daten.get("tor_gelesen_s")}


class GarageAutoVerbunden(GarageEntity, BinarySensorEntity):
    """Der ESP im Auto ist per Funk zu hoeren - das Auto steht also wach vor oder in der Garage."""

    _attr_name = "Auto-ESP verbunden"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_icon = "mdi:car-connected"

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "auto_zu_hoeren")

    @property
    def is_on(self) -> bool:
        return self.coordinator.auto_zu_hoeren

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.daten
        return {
            "zuletzt_vor_s": d.get("auto_zuletzt_s"),
            "pakete": d.get("auto_pakete"),
            "aufgesperrt": d.get("auto_aufgesperrt"),
            "funkkanal": d.get("funk_kanal"),
        }


class GarageAutoWert(GarageEntity, BinarySensorEntity):
    """Ein Wert, den der Auto-ESP funkt - nur solange er zu hoeren ist."""

    def __init__(self, coordinator: GarageCoordinator, key: str, name: str,
                 klasse: BinarySensorDeviceClass | None, icon: str, umkehren: bool = False) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_device_class = klasse
        self._attr_icon = icon
        self._umkehren = umkehren   # device_class lock: an heisst "entriegelt"

    @property
    def available(self) -> bool:
        return super().available and self.coordinator.auto_zu_hoeren and self.coordinator.ja(self._key) is not None

    @property
    def is_on(self) -> bool | None:
        w = self.coordinator.ja(self._key)
        if w is None:
            return None
        return (not w) if self._umkehren else w


class GarageLampe(GarageEntity, BinarySensorEntity):
    """Die rote Lampe (logisch an, auch wenn sie am Ende des Nachlaufs blinkt)."""

    _attr_name = "Rote Lampe"
    _attr_device_class = BinarySensorDeviceClass.LIGHT
    _attr_icon = "mdi:alarm-light"

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "lampe")

    @property
    def is_on(self) -> bool:
        return bool(self.daten.get("lampe"))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {"blinkt": bool(self.daten.get("lampe_blinkt")), "nachlauf_rest_s": self.daten.get("lampe_rest_s")}


class GarageEreignisstrom(GarageEntity, BinarySensorEntity):
    """Steht die Dauerverbindung, ueber die der ESP jede Aenderung sofort schickt?"""

    _attr_name = "Ereignisstrom"
    _attr_device_class = BinarySensorDeviceClass.CONNECTIVITY
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "ereignisstrom")

    @property
    def is_on(self) -> bool:
        return self.coordinator.events_verbunden
