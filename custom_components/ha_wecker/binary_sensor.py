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
from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers.dispatcher import async_dispatcher_connect
from homeassistant.helpers.entity_platform import AddEntitiesCallback

from . import WeckerData
from .const import DOMAIN, SIGNAL_UPDATE
from .entity import RelaisEntity, WeckerEntity
from .relais import RelaisCoordinator

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
    if isinstance(obj, RelaisCoordinator):
        entities: list[BinarySensorEntity] = [RelaisAlarmBinarySensor(obj)]
        if isinstance((obj.data or {}).get("eingang"), dict):
            entities.append(RelaisEingangBinarySensor(obj))
        async_add_entities(entities)
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


class RelaisAlarmBinarySensor(RelaisEntity, BinarySensorEntity):
    """Laeuft auf der Relaisbox gerade ein Alarmmuster?"""

    _attr_name = "Alarm"
    _attr_icon = "mdi:alarm-light"

    def __init__(self, coordinator: RelaisCoordinator) -> None:
        super().__init__(coordinator, "alarm")

    @property
    def is_on(self) -> bool | None:
        v = self.daten.get("alarm")
        return bool(v) if v is not None else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        aktiv = [
            {"nr": r.get("nr"), "muster": r.get("muster"), "rest_s": r.get("rest_s")}
            for r in self.daten.get("relais", []) or []
            if isinstance(r, dict) and r.get("muster") not in (None, "aus", "dauer")
        ]
        return {"relais": aktiv, "muster_verfuegbar": self.daten.get("muster")}


class RelaisEingangBinarySensor(RelaisEntity, BinarySensorEntity):
    """Digitaler Eingang der Relaisbox: an = Signal liegt an."""

    _attr_name = "Eingang"

    def __init__(self, coordinator: RelaisCoordinator) -> None:
        super().__init__(coordinator, "eingang")

    @property
    def _eingang(self) -> dict[str, Any]:
        e = self.daten.get("eingang")
        return e if isinstance(e, dict) else {}

    @property
    def available(self) -> bool:
        return super().available and bool(self._eingang)

    @property
    def is_on(self) -> bool | None:
        v = self._eingang.get("aktiv")
        return bool(v) if v is not None else None

    @property
    def icon(self) -> str:
        return "mdi:electric-switch-closed" if self.is_on else "mdi:electric-switch"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        e = self._eingang
        return {"gpio": e.get("gpio"), "seit_s": e.get("seit_s"), "zaehler": e.get("zaehler")}
