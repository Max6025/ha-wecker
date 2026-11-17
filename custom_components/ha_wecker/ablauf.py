"""Weckablauf: Hauptlicht und Signalsaeule folgen dem Wecker der App.

Der Ablauf haengt am Wecker-Eintrag, nicht an einem Leuchtmittel. Er holt sich
die Weckzeiten aus dem, was die App gemeldet hat, und steuert damit Geraete,
die in ganz anderen Eintraegen derselben Integration stecken - die Saeule etwa.
Vorher hing er an der Relaisbox: ohne die lief gar nichts, und wo ein Schritt
scheiterte, sah man es nur im Protokoll.

Was wann passiert, steht in Zeitbloecken (JSON, in den Optionen des Weckers):

    {"version": 1, "bloecke": [{
       "name": "Werktags frueh",
       "wochentage": ["mo","di","mi","do","fr"],
       "von": "04:00", "bis": "10:00",
       "schritte": [
         {"zeit": -60, "saeule": {"status": "hinweis"}},
         {"zeit": -60, "licht":  {"prozent": 3, "dauer": 60}},
         {"zeit":   0, "saeule": {"status": "alarm"}},
         {"zeit":   0, "licht":  {"prozent": 90, "dauer": 20}},
         {"zeit": 540, "licht":  {"prozent": 5, "dauer": 30}},
         {"zeit": 840, "licht":  {"aus": true}},
         {"zeit": 840, "saeule": {"status": "ruhe"}}]}]}

"zeit" zaehlt in Sekunden, "ab" sagt wovon: "weckruf" (Vorgabe) rechnet ab dem
Klingeln, negativ heisst vorher; "ende" rechnet ab dem Moment, in dem der
Weckruf beendet wird; "schlummern" ab dem Moment, in dem du ihn vertagst.
Nachlauf und Schlummern haengen also an dir, nicht an der Uhr.

Es gewinnt der erste Block, dessen Wochentag und Zeitfenster zur Weckzeit
passen. Jeder Schritt landet mit Zeit und Ergebnis im Protokoll am Schalter.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, time, timedelta
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import CALLBACK_TYPE, HomeAssistant, callback
from homeassistant.helpers.dispatcher import async_dispatcher_connect, async_dispatcher_send
from homeassistant.helpers.event import async_track_point_in_utc_time
from homeassistant.util import dt as dt_util

from .const import (
    ABLAUF_MAX_S,
    CONF_ABLAUF,
    CONF_HAUPTLICHT,
    DOMAIN,
    PROTOKOLL_MAX,
    ROLLE_TON,
    ROLLE_WARN,
    SIGNAL_ABLAUF,
    SIGNAL_WECKER_ALLE,
    STATUS_STANDARD,
)

_LOGGER = logging.getLogger(__name__)

TAGE = ["mo", "di", "mi", "do", "fr", "sa", "so"]

# Ohne eigene Datei gilt das hier - genau der Ablauf, den Max beschrieben hat.
STANDARD_ABLAUF: dict[str, Any] = {
    "version": 1,
    "bloecke": [
        {
            "name": "Immer",
            "wochentage": TAGE,
            "von": "00:00",
            "bis": "00:00",
            "schritte": [
                # Vorlauf: in der letzten Minute vor dem Weckruf hoch auf 5 %
                {"zeit": -60, "saeule": {"status": "hinweis"}},
                {"zeit": -60, "licht": {"prozent": 5, "dauer": 60}},
                # Es klingelt: Saeule in den Alarm, sie nimmt die Warnleuchte
                # mit. Der Tongeber bleibt bewusst draussen - er hat seinen
                # eigenen Schalter und haengt nicht am Weckruf.
                {"zeit": 0, "saeule": {"status": "alarm"}},
                # Weckruf beendet: Warnleuchte faellt mit dem Alarm weg, die
                # Saeule geht in den Kreuzwechsel, das Licht auf 70 %
                {"zeit": 0, "ab": "ende", "saeule": {"status": "kreuz"}},
                {"zeit": 0, "ab": "ende", "licht": {"prozent": 70, "dauer": 10}},
                # Nach sieben Minuten Licht aus, dafuer noch einmal Alarm
                {"zeit": 420, "ab": "ende", "licht": {"aus": True, "dauer": 30}},
                {"zeit": 420, "ab": "ende", "saeule": {"status": "alarm"}},
                # Eine Minute spaeter zurueck auf Gruen und stehen bleiben
                {"zeit": 480, "ab": "ende", "saeule": {"status": "ruhe"}},
                # Geschlummert: Saeule zurueck in den Ruhestand, Licht auf
                # 5 %. Es soll nicht stockdunkel werden, aber auch nicht hell
                # bleiben. Kommt danach 19 Minuten lang nichts mehr - kein
                # neues Klingeln, kein Beenden -, geht es aus.
                {"zeit": 0, "ab": "schlummern", "saeule": {"status": "ruhe"}},
                {"zeit": 0, "ab": "schlummern", "licht": {"prozent": 5, "dauer": 10}},
                {"zeit": 1140, "ab": "schlummern", "licht": {"aus": True, "dauer": 30}},
            ],
        }
    ],
}

AB_WECKRUF = "weckruf"
AB_ENDE = "ende"
AB_SCHLUMMER = "schlummern"
BEZUEGE = (AB_WECKRUF, AB_ENDE, AB_SCHLUMMER)
# Diese beiden haengen an einem Moment, den du bestimmst, nicht an der Uhr -
# darum werden sie erst in diesem Moment geplant und enden mit ihrem letzten
# Schritt, waehrend der Weckruf-Teil auf das Beenden wartet.
AB_SPAETER = (AB_ENDE, AB_SCHLUMMER)


def bezug(schritt: dict[str, Any]) -> str:
    wert = str(schritt.get("ab") or AB_WECKRUF).lower()
    return wert if wert in BEZUEGE else AB_WECKRUF


def zeit_lesen(wert: Any, vorgabe: time) -> time:
    """'HH:MM' oder 'HH:MM:SS'; Unsinn faellt auf die Vorgabe zurueck."""
    if isinstance(wert, time):
        return wert
    t = dt_util.parse_time(str(wert)) if wert else None
    return t if t is not None else vorgabe


def im_fenster(jetzt: time, von: time, bis: time) -> bool:
    """von == bis heisst: immer. Ueber Mitternacht geht."""
    if von == bis:
        return True
    if von < bis:
        return von <= jetzt < bis
    return jetzt >= von or jetzt < bis


def ablauf_lesen(roh: Any) -> tuple[dict[str, Any], str | None]:
    """JSON pruefen. Gibt (Ablauf, Fehlertext) - bei Fehler den Standardablauf."""
    if not roh:
        return STANDARD_ABLAUF, None
    daten = roh
    if isinstance(roh, str):
        try:
            daten = json.loads(roh)
        except ValueError as err:
            return STANDARD_ABLAUF, f"JSON nicht lesbar: {err}"
    if not isinstance(daten, dict) or not isinstance(daten.get("bloecke"), list):
        return STANDARD_ABLAUF, "Es fehlt die Liste \"bloecke\""
    for i, block in enumerate(daten["bloecke"], 1):
        if not isinstance(block, dict):
            return STANDARD_ABLAUF, f"Block {i} ist kein Objekt"
        if not isinstance(block.get("schritte"), list):
            return STANDARD_ABLAUF, f"Block {i} hat keine Liste \"schritte\""
        for j, schritt in enumerate(block["schritte"], 1):
            if not isinstance(schritt, dict):
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j} ist kein Objekt"
            if "zeit" not in schritt:
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j} hat keine \"zeit\""
            try:
                int(schritt["zeit"])
            except (TypeError, ValueError):
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j}: \"zeit\" ist keine Zahl"
            if not any(k in schritt for k in ("licht", "saeule")):
                return STANDARD_ABLAUF, f"Block {i}, Schritt {j} tut nichts"
            if "ab" in schritt and str(schritt["ab"]).lower() not in BEZUEGE:
                return STANDARD_ABLAUF, (
                    f"Block {i}, Schritt {j}: \"ab\" kennt nur "
                    + ", ".join(f'"{b}"' for b in BEZUEGE)
                )
    return daten, None


def block_waehlen(ablauf: dict[str, Any], weckzeit: datetime) -> dict[str, Any] | None:
    """Erster Block, dessen Wochentag und Fenster zur (lokalen) Weckzeit passen."""
    lokal = dt_util.as_local(weckzeit)
    tag = TAGE[lokal.weekday()]
    for block in ablauf.get("bloecke", []):
        tage = block.get("wochentage") or TAGE
        if tag not in [str(t).lower()[:2] for t in tage]:
            continue
        von = zeit_lesen(block.get("von"), time(0, 0))
        bis = zeit_lesen(block.get("bis"), time(0, 0))
        if im_fenster(lokal.time(), von, bis):
            return block
    return None


def naechste_weckzeit(hass: HomeAssistant) -> tuple[bool, bool, datetime | None]:
    """(klingelt, schlummert, naechster Weckruf) aus allen Wecker-Eintraegen.

    Die Weckzeit wird aus Stunde, Minute und Wochentagsmaske selbst gerechnet.
    "next_trigger" aus der App ist nur die Rueckfallebene: die App meldet sich
    nur bei Aenderungen, der Zeitstempel kann also von gestern sein.
    """
    from . import WeckerData  # Kreisimport vermeiden

    klingelt = schlummert = False
    naechster: datetime | None = None
    jetzt = dt_util.utcnow()
    for obj in hass.data.get(DOMAIN, {}).values():
        if not isinstance(obj, WeckerData) or not obj.payload:
            continue
        p = obj.payload
        klingelt = klingelt or bool(p.get("ringing"))
        schlummert = schlummert or bool(p.get("snoozed"))
        for a in (p.get("alarms") or []):
            if not isinstance(a, dict) or not a.get("enabled") or a.get("snoozed"):
                continue
            kandidat = _termin_rechnen(a, jetzt) or _termin_lesen(a.get("next_trigger"))
            if kandidat and kandidat > jetzt and (naechster is None or kandidat < naechster):
                naechster = kandidat
        if not p.get("alarms") and p.get("state"):
            kandidat = _termin_lesen(p.get("state"))
            if kandidat and kandidat > jetzt and (naechster is None or kandidat < naechster):
                naechster = kandidat
    return klingelt, schlummert, naechster


def _termin_lesen(wert: Any) -> datetime | None:
    if not wert:
        return None
    dt = dt_util.parse_datetime(str(wert))
    return dt_util.as_utc(dt) if dt else None


def _termin_rechnen(alarm: dict[str, Any], jetzt: datetime) -> datetime | None:
    """Naechster Termin aus Stunde, Minute und Wochentagsmaske der App.

    days_mask ist ein Bitfeld, Bit 0 ist Montag. Null heisst: einmalig, dann
    gilt der naechste Tag, an dem die Uhrzeit noch kommt. "skip_next"
    ueberspringt genau einen Termin.
    """
    try:
        stunde = int(alarm["hour"])
        minute = int(alarm["minute"])
    except (KeyError, TypeError, ValueError):
        return None
    try:
        maske = int(alarm.get("days_mask") or 0)
    except (TypeError, ValueError):
        maske = 0
    lokal = dt_util.as_local(jetzt)
    uebersprungen = bool(alarm.get("skip_next"))
    for tage_weiter in range(0, 9):
        kandidat = (lokal + timedelta(days=tage_weiter)).replace(
            hour=stunde, minute=minute, second=0, microsecond=0
        )
        if kandidat <= lokal:
            continue
        if maske and not (maske >> kandidat.weekday()) & 1:
            continue
        if uebersprungen:
            uebersprungen = False
            continue
        return dt_util.as_utc(kandidat)
    return None


class Weckablauf:
    """Faehrt die Schritte des passenden Blocks rund um den Weckruf."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry) -> None:
        self.hass = hass
        self.entry = entry
        self.aktiv = True                       # Schalter "Weckablauf"
        self.laeuft = False
        self.probelauf = False
        self.block: str | None = None           # Name des gewaehlten Blocks
        self.naechster_wecker: datetime | None = None
        self.nullpunkt: datetime | None = None  # Weckruf, auf den sich "zeit" bezieht
        self.beendet_um: datetime | None = None # wann der Weckruf beendet wurde
        self.strom: Any = None                  # Stromplan der Saeule, siehe strom.py
        self.protokoll: list[dict[str, Any]] = []
        self._klingelt_alt = False
        # Hat ein Schritt den Tongeber angestellt? Nur dann macht der Ablauf
        # ihn beim Schlummern oder im Sicherheitsnetz wieder aus. Steht er
        # ab Werk nicht im Ablauf, soll ein von Hand gedrueckter Knopf auch
        # nicht von einem Weckruf abgeschaltet werden.
        self._ton_von_uns = False
        self._letzte_art = AB_WECKRUF            # welcher Teil zuletzt lief
        self._timer: list[CALLBACK_TYPE] = []
        self._probe_timer: CALLBACK_TYPE | None = None
        self._unsub_signal: CALLBACK_TYPE | None = None

    # --- Einstellungen ------------------------------------------------

    @property
    def hauptlicht(self) -> str | None:
        wert = self.entry.options.get(CONF_HAUPTLICHT)
        return str(wert) if wert else None

    @property
    def ablauf(self) -> tuple[dict[str, Any], str | None]:
        return ablauf_lesen(self.entry.options.get(CONF_ABLAUF))

    def saeule(self) -> Any | None:
        """Die Signalsaeule aus einem anderen Eintrag derselben Integration."""
        from .saeule import SaeuleCoordinator

        for obj in self.hass.data.get(DOMAIN, {}).values():
            if isinstance(obj, SaeuleCoordinator):
                return obj
        return None

    def attribute(self) -> dict[str, Any]:
        _, fehler = self.ablauf
        saeule = self.saeule()
        return {
            "laeuft": self.laeuft,
            "probelauf": self.probelauf,
            "block": self.block,
            "hauptlicht": self.hauptlicht or "nicht eingestellt",
            "saeule": "verbunden" if saeule else "nicht eingerichtet",
            "naechster_wecker": self.naechster_wecker.isoformat() if self.naechster_wecker else None,
            "nullpunkt": self.nullpunkt.isoformat() if self.nullpunkt else None,
            "beendet_um": self.beendet_um.isoformat() if self.beendet_um else None,
            "ablauf_fehler": fehler,
            "strom": self.strom.attribute() if self.strom else None,
            "protokoll": list(reversed(self.protokoll)),
        }

    # --- Lebenszyklus -------------------------------------------------

    @callback
    def async_start(self) -> None:
        self._unsub_signal = async_dispatcher_connect(
            self.hass, SIGNAL_WECKER_ALLE, self._wecker_geaendert
        )
        self._wecker_geaendert()

    @callback
    def async_stop(self) -> None:
        if self._unsub_signal:
            self._unsub_signal()
            self._unsub_signal = None
        self._timer_weg()

    async def async_setzen(self, an: bool) -> None:
        self.aktiv = an
        if an:
            self._wecker_geaendert()
            return
        self._timer_weg()
        self.laeuft = self.probelauf = False
        self.melden()

    # --- Reaktion auf den Wecker --------------------------------------

    @callback
    def _wecker_geaendert(self) -> None:
        klingelt, schlummert, naechster = naechste_weckzeit(self.hass)
        self.naechster_wecker = naechster
        flanke_an = klingelt and not self._klingelt_alt
        flanke_aus = not klingelt and self._klingelt_alt
        self._klingelt_alt = klingelt

        if not self.aktiv or self.probelauf:
            self.melden()
            return

        if flanke_an:
            # Es klingelt wirklich: ab hier zaehlt die Zeit, alles ab 0 kommt neu
            self._starten(dt_util.utcnow(), AB_WECKRUF, nur_ab_null=True)
        elif flanke_aus and schlummert:
            # Geschlummert: die Schritte des Weckrufs sind durch, der Nachlauf
            # gilt noch nicht. Ohne eigene Schritte bliebe die Saeule im Alarm
            # stehen und das Licht hell, bis es wieder klingelt. Was dann
            # passiert, steht als "ab": "schlummern" in der Ablaufdatei.
            self.notiz("Schlummern", "Weckruf vertagt", "ok")
            self._starten(dt_util.utcnow(), AB_SCHLUMMER)
        elif flanke_aus:
            # Weckruf beendet: der Nachlauf haengt an diesem Moment
            self.beendet_um = dt_util.utcnow()
            self._starten(self.beendet_um, AB_ENDE)
        elif not self.laeuft and naechster is not None:
            self._starten(naechster, AB_WECKRUF)
        elif (
            self.laeuft
            and not klingelt
            and self.beendet_um is None
            and naechster is not None
            and naechster != self.nullpunkt
        ):
            # Die Weckzeit hat sich verschoben, waehrend der Vorlauf schon
            # stand. Am 16.11. stellte Max abends 05:00 auf 04:50 um: der
            # Stromplan zog mit (die Dose ging um 04:45 an), der Ablauf nicht -
            # er sah nur "laeuft" und liess die alten Timer auf 04:59 stehen.
            # Um 04:50 klingelte es, die wurden weggeraeumt, und Hinweis und
            # die 5 % Licht fielen ganz aus.
            self._starten(naechster, AB_WECKRUF)
        self.melden()

    def _starten(self, nullpunkt: datetime, art: str, nur_ab_null: bool = False) -> None:
        """Die Schritte des Blocks mit diesem Bezugspunkt auf Zeitpunkte legen.

        `art` trennt die Schritte der Liste: die am Weckruf haengen, die erst
        nach dem Beenden gelten und die beim Schlummern. Ein neuer Lauf raeumt
        die Timer des alten ab, damit nichts aus dem Vorlauf hereinredet.
        """
        ablauf, fehler = self.ablauf
        if fehler:
            self.notiz("Ablaufdatei", fehler, "fehler")
        bezugszeit = self.nullpunkt if art in AB_SPAETER and self.nullpunkt else nullpunkt
        block = block_waehlen(ablauf, bezugszeit)
        if block is None:
            self._timer_weg()
            self.laeuft = False
            self.block = None
            self.notiz("Kein Block", "Weckzeit passt in keinen Zeitblock", "uebersprungen")
            return
        self._timer_weg()
        self.block = str(block.get("name") or "ohne Namen")
        if art == AB_WECKRUF:
            self.nullpunkt = nullpunkt
            self.beendet_um = None
        self.laeuft = True
        self._letzte_art = art
        jetzt = dt_util.utcnow()
        geplant = 0
        letzter: datetime | None = None
        for schritt in block.get("schritte", []):
            if bezug(schritt) != art:
                continue
            versatz = int(schritt["zeit"])
            if nur_ab_null and versatz < 0:
                continue
            faellig = nullpunkt + timedelta(seconds=versatz)
            if faellig <= jetzt - timedelta(seconds=5):
                continue                      # laengst vorbei, nicht nachholen
            if faellig <= jetzt:
                self.hass.async_create_task(self._ausfuehren(schritt))
                geplant += 1
                continue
            self._timer.append(
                async_track_point_in_utc_time(self.hass, self._faellig(schritt), faellig)
            )
            geplant += 1
            if letzter is None or faellig > letzter:
                letzter = faellig
        # Wann ist der Lauf vorbei? Nach dem Nachlauf steht das fest: mit dem
        # letzten Schritt. Beim Weckruf-Teil wartet er auf das Beenden - kommt
        # das nie (App stumm, Handy aus), greift das Sicherheitsnetz, sonst
        # bliebe "laeuft" fuer immer stehen und kein Vorlauf mehr geplant.
        ende = (letzter + timedelta(seconds=1)) if art in AB_SPAETER and letzter else None
        if art == AB_WECKRUF:
            ende = nullpunkt + timedelta(seconds=ABLAUF_MAX_S)
        if ende is not None:
            self._timer.append(
                async_track_point_in_utc_time(self.hass, self._fertig, ende)
            )
        woher = {
            AB_WECKRUF: "ab dem Weckruf",
            AB_ENDE: "ab dem Beenden",
            AB_SCHLUMMER: "ab dem Schlummern",
        }[art]
        self.notiz(
            "Geplant",
            f"Block \"{self.block}\", {geplant} Schritte {woher} "
            f"{dt_util.as_local(nullpunkt):%H:%M:%S}",
            "ok",
        )

    @callback
    def _fertig(self, _jetzt: datetime) -> None:
        """Lauf zu Ende: wieder frei fuer den naechsten Weckruf.

        Die Timer werden hier bewusst nicht abgeraeumt: werden mehrere
        Zeitpunkte auf einmal faellig, ist die Reihenfolge nicht garantiert,
        und ein Wegraeumen wuerde den letzten Schritt verschlucken.

        Lief aber der Weckruf-Teil ins Sicherheitsnetz, ohne dass je ein
        Beenden kam (App stumm, Handy aus), dann stehen Saeule und Tongeber
        noch im Alarm. Zwei Stunden Piepen in einem leeren Zimmer will
        niemand - das wird hier zurueckgestellt.
        """
        war_probe = self.probelauf
        war_schlummer = self._letzte_art == AB_SCHLUMMER
        ohne_ende = (
            self.laeuft and not war_probe and not war_schlummer and self.beendet_um is None
        )
        self.laeuft = self.probelauf = False
        self.beendet_um = None
        if ohne_ende:
            self.notiz(
                "Sicherheitsnetz",
                "kein Beenden gemeldet - Saeule, Ton und Licht zurueck",
                "uebersprungen",
            )
            self.hass.async_create_task(self._aufraeumen())
        self.notiz("Fertig", "Probelauf beendet" if war_probe else "Ablauf beendet", "ok")
        self._ampel_weiter()
        # Gleich den naechsten Vorlauf planen, sonst wartet er auf die naechste
        # Meldung der App - und die kommt vielleicht erst beim Klingeln.
        self._wecker_geaendert()

    @callback
    def _ampel_weiter(self) -> None:
        """Die Betriebsart "Ampel" wieder laufen lassen, falls sie ruhte."""
        coordinator = self.saeule()
        ampel = getattr(coordinator, "ampel", None) if coordinator else None
        if ampel is not None and ampel.aktiv and ampel.pausiert:
            self.notiz("Betriebsart Ampel", "laeuft wieder", "ok")
            self.hass.async_create_task(ampel.async_weiter())

    def _faellig(self, schritt: dict[str, Any]):
        @callback
        def _ausloesen(_jetzt: datetime) -> None:
            self.hass.async_create_task(self._ausfuehren(schritt))
        return _ausloesen

    # --- Probelauf ----------------------------------------------------

    async def async_probelauf(self, vorlauf_s: int = 60, klingelt_s: int = 30) -> None:
        """Ablauf sofort durchspielen, ohne auf einen echten Weckruf zu warten.

        Nach `vorlauf_s` "klingelt" es, nach weiteren `klingelt_s` wird der
        Weckruf "beendet" - sonst liefe der Nachlauf nie an, der ja genau an
        diesem Moment haengt.
        """
        self._timer_weg()
        self.protokoll = []
        self.probelauf = True
        self.beendet_um = None
        if self.strom is not None:
            await self.strom.async_sichern()
        weckruf = dt_util.utcnow() + timedelta(seconds=vorlauf_s)
        self.notiz(
            "Probelauf",
            f"Klingeln in {vorlauf_s} s, Beenden {klingelt_s} s spaeter",
            "ok",
        )
        self._starten(weckruf, AB_WECKRUF)
        self._probe_timer = async_track_point_in_utc_time(
            self.hass, self._probe_beenden, weckruf + timedelta(seconds=klingelt_s)
        )
        self.melden()

    @callback
    def _probe_beenden(self, _jetzt: datetime) -> None:
        self._probe_timer = None
        if not self.probelauf:
            return
        self.beendet_um = dt_util.utcnow()
        self.notiz("Probelauf", "Weckruf beendet", "ok")
        self._starten(self.beendet_um, AB_ENDE)
        self.melden()

    async def _aufraeumen(self) -> None:
        """Saeule auf Ruhe, Licht aus - und den Ton nur, wenn er von uns kam."""
        wunsch: dict[str, Any] = {"status": STATUS_STANDARD}
        if self._ton_von_uns:
            wunsch["ton"] = False
        await self._saeule(wunsch)
        await self._licht({"aus": True})
        self.melden()

    async def async_abbrechen(self) -> None:
        """Laufenden Ablauf stoppen und aufraeumen: Licht aus, Saeule auf Ruhe."""
        self._timer_weg()
        war = self.laeuft or self.probelauf
        self.laeuft = self.probelauf = False
        self.beendet_um = None
        self.notiz("Abbruch", "Ablauf gestoppt" if war else "nichts lief", "ok")
        if war:
            await self._aufraeumen()
        self._ampel_weiter()
        self.melden()

    # --- Schritte ausfuehren ------------------------------------------

    async def _ausfuehren(self, schritt: dict[str, Any]) -> None:
        if "licht" in schritt:
            await self._licht(schritt["licht"])
        if "saeule" in schritt:
            await self._saeule(schritt["saeule"])
        self.melden()

    async def _licht(self, wunsch: dict[str, Any]) -> None:
        ziel = self.hauptlicht
        if not ziel:
            self.notiz("Hauptlicht", "keine Entitaet eingestellt", "fehler")
            return
        aus = bool(wunsch.get("aus"))
        daten: dict[str, Any] = {"entity_id": ziel}
        if not aus and wunsch.get("prozent") is not None:
            daten["brightness_pct"] = int(wunsch["prozent"])
        if wunsch.get("dauer"):
            daten["transition"] = int(wunsch["dauer"])
        dienst = "turn_off" if aus else "turn_on"
        beschreibung = "aus" if aus else f"{daten.get('brightness_pct', '?')} %"
        if wunsch.get("dauer"):
            beschreibung += f" in {int(wunsch['dauer'])} s"
        try:
            await self.hass.services.async_call("light", dienst, daten, blocking=True)
            self.notiz(f"Hauptlicht {ziel}", beschreibung, "ok")
        except Exception as err:  # noqa: BLE001
            # Viele Leuchten koennen kein "transition". Dann ohne, statt
            # den Schritt stillschweigend fallen zu lassen.
            if "transition" in daten:
                daten.pop("transition")
                try:
                    await self.hass.services.async_call("light", dienst, daten, blocking=True)
                    self.notiz(f"Hauptlicht {ziel}", beschreibung + " (ohne Uebergang)", "ok")
                    return
                except Exception as err2:  # noqa: BLE001
                    err = err2
            self.notiz(f"Hauptlicht {ziel}", f"{beschreibung}: {err}", "fehler")
            _LOGGER.warning("Weckablauf: Hauptlicht %s %s: %s", ziel, dienst, err)

    async def _saeule(self, wunsch: dict[str, Any]) -> None:
        coordinator = self.saeule()
        if coordinator is None:
            self.notiz("Signalsaeule", "nicht eingerichtet", "uebersprungen")
            return
        # Der Weckruf hat Vorrang: steht die Saeule auf der Garagenampel, ruht
        # die Betriebsart jetzt und zieht ihr Bild erst am Ende des Laufs
        # wieder nach (siehe ampel.py).
        ampel = getattr(coordinator, "ampel", None)
        if ampel is not None and ampel.aktiv and not ampel.pausiert:
            ampel.pausieren()
            self.notiz("Betriebsart Ampel", "ruht bis zum Ende des Laufs", "ok")
        try:
            if "status" in wunsch:
                await coordinator.async_status(str(wunsch["status"]))
                self.notiz("Signalsaeule", f"Status {wunsch['status']}", "ok")
            if "warn" in wunsch:
                await coordinator.async_rolle_schalten(ROLLE_WARN, bool(wunsch["warn"]))
                self.notiz("Signalsaeule", f"Warnleuchte {'an' if wunsch['warn'] else 'aus'}", "ok")
            if "ton" in wunsch:
                an = bool(wunsch["ton"])
                await coordinator.async_rolle_schalten(ROLLE_TON, an)
                self._ton_von_uns = an
                self.notiz("Signalsaeule", f"Ton {'an' if an else 'aus'}", "ok")
        except Exception as err:  # noqa: BLE001
            self.notiz("Signalsaeule", str(err), "fehler")
            _LOGGER.warning("Weckablauf: Saeule %s: %s", wunsch, err)

    # --- Kleinkram ----------------------------------------------------

    def notiz_extern(self, was: str, text: str, ergebnis: str) -> None:
        """Notiz von aussen - der Stromplan schreibt ins selbe Protokoll.

        Anders als bei den eigenen Schritten muss der Schalter danach gleich
        aufgefrischt werden, sonst steht die neue Zeile erst beim naechsten
        Anlass im Protokoll.
        """
        self.notiz(was, text, ergebnis)
        self.melden()

    def notiz(self, was: str, text: str, ergebnis: str) -> None:
        self.protokoll.append(
            {
                "zeit": dt_util.as_local(dt_util.utcnow()).strftime("%d.%m. %H:%M:%S"),
                "was": was,
                "text": text,
                "ergebnis": ergebnis,
            }
        )
        del self.protokoll[:-PROTOKOLL_MAX]

    def _timer_weg(self) -> None:
        for t in self._timer:
            t()
        self._timer = []
        if self._probe_timer:
            self._probe_timer()
            self._probe_timer = None

    def melden(self) -> None:
        async_dispatcher_send(self.hass, SIGNAL_ABLAUF.format(self.entry.entry_id))
