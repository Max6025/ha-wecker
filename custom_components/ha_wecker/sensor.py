"""Sensoren der HA-Wecker-Integration."""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorStateClass,
)
from homeassistant.config_entries import ConfigEntry
from homeassistant.const import EntityCategory
from homeassistant.core import HomeAssistant
from homeassistant.helpers.entity_platform import AddEntitiesCallback
from homeassistant.util import dt as dt_util

from homeassistant.const import SIGNAL_STRENGTH_DECIBELS_MILLIWATT

from . import WeckerData
from .const import DOMAIN
from .entity import GarageEntity, SaeuleEntity, WeckerEntity
from .garage import AMPEL_ALLE, GarageCoordinator
from .saeule import SaeuleCoordinator


async def async_setup_entry(
    hass: HomeAssistant, entry: ConfigEntry, async_add_entities: AddEntitiesCallback
) -> None:
    obj = hass.data[DOMAIN][entry.entry_id]
    if isinstance(obj, SaeuleCoordinator):
        async_add_entities(
            [
                SaeuleStatusSensor(obj),
                SaeuleDiagnoseSensor(obj),
                RssiSensor(obj),
                UptimeSensor(obj),
            ]
        )
        return
    if isinstance(obj, GarageCoordinator):
        async_add_entities(
            [
                GarageAmpelSensor(obj),
                GarageAutoZuletztSensor(obj),
                GaragePaketeSensor(obj),
                GarageZahl(obj, "funk_kanal", "Funkkanal", "mdi:radio-tower", None, None),
                GarageZahl(obj, "wlan_rssi", "WLAN-Signal", None, SensorDeviceClass.SIGNAL_STRENGTH, SIGNAL_STRENGTH_DECIBELS_MILLIWATT),
                GarageZahl(obj, "laufzeit_s", "Laufzeit", None, SensorDeviceClass.DURATION, "s"),
            ]
        )
        return
    data: WeckerData = obj
    async_add_entities(
        [
            NextAlarmSensor(data),
            NextAlarmInSensor(data),
            ActiveCountSensor(data),
            LastSeenSensor(data),
            WebhookSensor(data),
        ]
    )


class NextAlarmSensor(WeckerEntity, SensorEntity):
    """Zeitpunkt des naechsten Weckrufs."""

    _attr_translation_key = "next_alarm"
    _attr_name = "Naechster Wecker"
    _attr_icon = "mdi:alarm"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "next_alarm")

    @property
    def native_value(self) -> datetime | None:
        raw = self.payload.get("state")
        if not raw:
            return None
        return dt_util.parse_datetime(str(raw))

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.payload
        return {
            "name": p.get("next_alarm_name"),
            "uhrzeit": p.get("next_alarm_time"),
            "in": p.get("next_alarm_in"),
            "wecker": p.get("next_alarm"),
            "geraetezeit": p.get("device_time"),
            "zeitzone": p.get("timezone"),
        }


class NextAlarmInSensor(WeckerEntity, SensorEntity):
    """Restzeit als lesbarer Text."""

    _attr_name = "Naechster Wecker in"
    _attr_icon = "mdi:timer-sand"

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "next_alarm_in")

    @property
    def native_value(self) -> str:
        return self.payload.get("next_alarm_in") or "keiner"


class ActiveCountSensor(WeckerEntity, SensorEntity):
    """Anzahl eingeschalteter Wecker, mit allen Weckern als Attribut."""

    _attr_name = "Aktive Wecker"
    _attr_icon = "mdi:alarm-multiple"
    _attr_native_unit_of_measurement = "Wecker"
    _attr_state_class = SensorStateClass.MEASUREMENT

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "active_count")

    @property
    def native_value(self) -> int | None:
        value = self.payload.get("active_count")
        return int(value) if isinstance(value, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        p = self.payload
        return {
            "alarms": p.get("alarms", []),
            "active_alarms": p.get("active_alarms", []),
            "inactive_alarms": p.get("inactive_alarms", []),
            "total_count": p.get("total_count"),
            "inactive_count": p.get("inactive_count"),
            "skipped_count": p.get("skipped_count"),
            "summary": p.get("summary"),
        }


class LastSeenSensor(WeckerEntity, SensorEntity):
    """Wann sich das Handy zuletzt gemeldet hat."""

    _attr_name = "Letzte Meldung"
    _attr_icon = "mdi:cellphone-check"
    _attr_device_class = SensorDeviceClass.TIMESTAMP
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "last_seen")

    @property
    def native_value(self) -> datetime | None:
        return self._data.last_seen


class WebhookSensor(WeckerEntity, SensorEntity):
    """Zeigt die Adresse, die in der App eingetragen werden muss."""

    _attr_name = "Webhook"
    _attr_icon = "mdi:webhook"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, data: WeckerData) -> None:
        super().__init__(data, "webhook")

    @property
    def available(self) -> bool:
        return True

    @property
    def native_value(self) -> str:
        return self._data.webhook_id

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "adresse_fuer_die_app": self._data.webhook_url,
        }


class RssiSensor(SaeuleEntity, SensorEntity):
    """WLAN-Empfang der Signalsaeule."""

    _attr_name = "WLAN-Signal"
    _attr_device_class = SensorDeviceClass.SIGNAL_STRENGTH
    _attr_native_unit_of_measurement = SIGNAL_STRENGTH_DECIBELS_MILLIWATT
    _attr_state_class = SensorStateClass.MEASUREMENT
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "rssi")

    @property
    def native_value(self) -> int | None:
        v = self.daten.get("rssi")
        return int(v) if isinstance(v, (int, float)) else None


class UptimeSensor(SaeuleEntity, SensorEntity):
    """Laufzeit der Saeule seit dem letzten Start."""

    _attr_name = "Laufzeit"
    _attr_device_class = SensorDeviceClass.DURATION
    _attr_native_unit_of_measurement = "s"
    _attr_entity_category = EntityCategory.DIAGNOSTIC
    _attr_entity_registry_enabled_default = False

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "uptime")

    @property
    def native_value(self) -> int | None:
        v = self.daten.get("uptime_s")
        return int(v) if isinstance(v, (int, float)) else None

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        return {
            "ip": self.daten.get("ip"),
            "version": self.daten.get("version"),
            "ereignisstrom": "verbunden" if self.coordinator.events_verbunden else "getrennt (Abfrage alle 10 s)",
        }


# --- Signalsaeule -----------------------------------------------------------


class SaeuleStatusSensor(SaeuleEntity, SensorEntity):
    """Was die Saeule gerade zeigt - in Klartext, fuer Ansichten und Ansagen."""

    _attr_name = "Anzeige"
    _attr_icon = "mdi:traffic-light-outline"

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "anzeige")

    @property
    def native_value(self) -> str | None:
        if not self.coordinator.auto:
            return "Manuell"
        if (self.coordinator.data or {}).get("test"):
            return "Testmodus"
        return self.coordinator.status_name(self.coordinator.status)

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        daten = self.coordinator.data or {}
        leuchtet = [
            str(r.get("name"))
            for r in self.coordinator.leuchten()
            if r.get("an")
        ]
        return {
            "betriebsart": self.coordinator.modus,
            "status": self.coordinator.status,
            "wechsel_laeuft": bool(daten.get("wechsel")),
            "warnleuchte": bool(daten.get("warn")),
            "leuchtet": leuchtet,
        }


class SaeuleDiagnoseSensor(SaeuleEntity, SensorEntity):
    """Ergebnis der letzten Selbstdiagnose; die Punkte stehen in den Attributen."""

    _attr_name = "Selbstdiagnose"
    _attr_icon = "mdi:clipboard-pulse-outline"
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: SaeuleCoordinator) -> None:
        super().__init__(coordinator, "diagnose_ergebnis")

    @property
    def native_value(self) -> str:
        d = self.coordinator.diagnose
        if d.get("laeuft"):
            return "läuft"
        if not d.get("fertig"):
            return "nie gelaufen"
        punkte = d.get("punkte") or []
        fehler = [p for p in punkte if isinstance(p, dict) and p.get("ok") == 0]
        return "in Ordnung" if not fehler else f"{len(fehler)} Beanstandung(en)"

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.coordinator.diagnose
        return {
            "laeuft": bool(d.get("laeuft")),
            "vor_s": d.get("vor_s"),
            "punkte": [
                {
                    "name": p.get("name"),
                    "bewertung": {1: "ok", 0: "Fehler", -1: "Hinweis"}.get(p.get("ok")),
                    "text": p.get("text"),
                }
                for p in (d.get("punkte") or [])
                if isinstance(p, dict)
            ],
        }


# ---------------------------------------------------------------------------
# Garage (ESP32 an der Lichtschranke)
# ---------------------------------------------------------------------------


class GarageAmpelSensor(GarageEntity, SensorEntity):
    """Die Ampel, wie sie der Tacho im Auto zeichnet: Stopp, Frei, kein Strom oder aus.

    Stopp = Lichtschranke durchtrennt, das Auto steht weit genug drin. Frei =
    Schranke frei. Kein Strom = die 24 V der Schranke fehlen, kein Urteil. Aus =
    Tor zu und kein Auto zu hoeren, die Schranke interessiert gerade niemanden.
    """

    _attr_name = "Ampel"
    _attr_icon = "mdi:traffic-light"
    _attr_device_class = SensorDeviceClass.ENUM
    _attr_options = AMPEL_ALLE
    _attr_translation_key = "ampel"

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "ampel")

    @property
    def native_value(self) -> str:
        return self.coordinator.ampel

    @property
    def extra_state_attributes(self) -> dict[str, Any]:
        d = self.daten
        return {
            "grund": d.get("ampel_grund"),
            "auto_drin": d.get("auto_drin"),
            "tor": d.get("tor"),
            "auto_zu_hoeren": d.get("auto_zu_hoeren"),
            "strom": d.get("strom"),
        }


class GarageAutoZuletztSensor(GarageEntity, SensorEntity):
    """Wann der Auto-ESP zuletzt zu hoeren war."""

    _attr_name = "Auto zuletzt gehört"
    _attr_icon = "mdi:car-clock"
    _attr_device_class = SensorDeviceClass.TIMESTAMP

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "auto_zuletzt")

    @property
    def native_value(self) -> datetime | None:
        vor = self.daten.get("auto_zuletzt_s")
        if vor is None or isinstance(vor, bool) or not isinstance(vor, (int, float)):
            return None
        return dt_util.utcnow() - timedelta(seconds=float(vor))


class GaragePaketeSensor(GarageEntity, SensorEntity):
    """Funkpakete vom Auto seit dem Start des ESP."""

    _attr_name = "Pakete vom Auto"
    _attr_icon = "mdi:package-variant"
    _attr_state_class = SensorStateClass.TOTAL_INCREASING
    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarageCoordinator) -> None:
        super().__init__(coordinator, "auto_pakete")

    @property
    def native_value(self) -> int | None:
        w = self.daten.get("auto_pakete")
        return int(w) if isinstance(w, (int, float)) and not isinstance(w, bool) else None


class GarageZahl(GarageEntity, SensorEntity):
    """Eine Zahl aus /api/state, nur zur Diagnose."""

    _attr_entity_category = EntityCategory.DIAGNOSTIC

    def __init__(self, coordinator: GarageCoordinator, key: str, name: str, icon: str | None,
                 klasse: SensorDeviceClass | None, einheit: str | None) -> None:
        super().__init__(coordinator, key)
        self._attr_name = name
        self._attr_icon = icon
        self._attr_device_class = klasse
        self._attr_native_unit_of_measurement = einheit
        if klasse == SensorDeviceClass.DURATION:
            self._attr_state_class = SensorStateClass.TOTAL_INCREASING

    @property
    def native_value(self) -> int | float | None:
        w = self.daten.get(self._key)
        return w if isinstance(w, (int, float)) and not isinstance(w, bool) else None
