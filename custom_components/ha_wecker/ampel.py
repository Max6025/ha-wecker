"""Betriebsart "Ampel": die Signalsaeule zeichnet die Garagenampel nach.

Ein dritter Platz im Schalter "Betriebsart" neben Auto und Manuell. Steht er
auf Ampel, zeigt die Saeule, was der Garagen-ESP meldet (siehe garage.py):

    Auto steht richtig  (stopp)      -> rot
    Garage frei         (frei)       -> gruen
    Kein Strom am Tor   (kein_strom) -> gelb blinkt im Sekundentakt, wie an
                                        einer echten Kreuzung, und die
                                        Hinweisleuchte blinkt sehr schnell dazu
    Garage antwortet nicht           -> rot blinkt, im Takt der gelben
    Ampel aus           (aus)        -> nichts

Die beiden Stoerungen sind auseinanderzuhalten, weil sie Verschiedenes
heissen. Meldet der ESP "kein_strom", lebt er und sagt, dass der Lichtschranke
die 24 V fehlen - eine gestoerte Ampel also, und die blinkt gelb. Antwortet er
gar nicht, fehlen ihm selbst die 5 V: dann steht nicht einmal mehr fest, dass
die Garage ueberhaupt ueberwacht wird, und die Saeule blinkt rot. Ohne
Hinweisleuchte, im ruhigen Takt der gelben - nicht im schnellen.

Still bleibt das in jedem Fall: kein Ton, keine Blitz-Warnleuchte. Der
Tongeber kommt nur einmal beim Umschalten auf diese Betriebsart.

Diese Betriebsart gibt es nur in Home Assistant, nicht in der Saeule: sie
kennt die Garage nicht. Am Geraet steht sie dabei auf "manuell" und die Stufen
werden einzeln gestellt - ein stehendes Bild, keine Choreografie. Genau das
soll eine Ampel sein: ruhig und auf einen Blick zu lesen.

Drei Dinge beenden die Betriebsart:

- ein anderer Platz im Schalter (Auto oder Manuell),
- ein Status oder eine Leuchte von Hand (wer selbst stellt, will selbst
  stellen - dieselbe Regel gilt in der Firmware fuer Auto und Manuell),
- jeder Neustart: der Ampelmodus wird bewusst nicht gemerkt. Die Saeule geht
  abends vom Netz (siehe strom.py) und kommt morgens still wieder hoch; wuerde
  der Ampelmodus das ueberdauern, stuende sie um Viertel vor fuenf auf Rot,
  lange bevor der Wecker klingelt.

Der Weckruf hat Vorrang. Fasst der Weckablauf die Saeule an, ruht der
Ampelmodus bis zum Ende des Laufs und zieht danach das Ampelbild nach.
"""
from __future__ import annotations

import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    AMPEL_BLINK_MS,
    AMPEL_BLINK_SCHNELL_MS,
    DOMAIN,
    FARBE_GRUEN,
    FARBE_HINWEIS,
    FARBE_ORANGE,
    FARBE_ROT,
)
from .garage import AMPEL_AUS, AMPEL_FREI, AMPEL_KEIN_STROM, AMPEL_STOPP

_LOGGER = logging.getLogger(__name__)

# Welches Bild die Saeule bei welcher Ampel zeigt: Farbe und Blinkperiode in
# Millisekunden (0 heisst dauernd). Nach Farbe, nicht nach Relaisnummer - die
# Saeule meldet sie selbst (ab Firmware 1.3.0).
#
# Die Stoerung ist nachgebaut, wie eine Ampel es an der Kreuzung macht: gelb
# blinkt im Sekundentakt. Die Hinweisleuchte blinkt sehr schnell dazu, damit
# man eine Stoerung nicht mit "Achtung" verwechselt.
AMPEL_STOERUNG: dict[str, int] = {
    FARBE_ORANGE: AMPEL_BLINK_MS,
    FARBE_HINWEIS: AMPEL_BLINK_SCHNELL_MS,
}
# Der ESP antwortet nicht - ihm fehlen die 5 V. Rot, allein, im Takt der
# gelben. Nicht im schnellen Blinken, und ohne Hinweisleuchte.
AMPEL_KEIN_ESP: dict[str, int] = {FARBE_ROT: AMPEL_BLINK_MS}
AMPEL_BILD: dict[str, dict[str, int]] = {
    AMPEL_STOPP: {FARBE_ROT: 0},
    AMPEL_FREI: {FARBE_GRUEN: 0},
    AMPEL_KEIN_STROM: AMPEL_STOERUNG,
    AMPEL_AUS: {},
}


class Ampelmodus:
    """Haelt die Betriebsart "Ampel" fuer eine Signalsaeule."""

    def __init__(self, hass: HomeAssistant, coordinator: Any) -> None:
        self.hass = hass
        self.saeule = coordinator
        self.aktiv = False
        self.pausiert = False          # der Weckablauf hat die Saeule
        self.fehler: str | None = None
        self._bild: dict[int, int] | None = None   # was zuletzt gestellt wurde
        self._ab_garage: Any = None           # Abmelder des Garagen-Listeners
        self._gehoert: Any = None             # an welchem Coordinator er haengt

    # --- Die Garage ---------------------------------------------------

    def garage(self) -> Any | None:
        """Der Garagen-ESP aus einem anderen Eintrag derselben Integration."""
        from .garage import GarageCoordinator

        for obj in self.hass.data.get(DOMAIN, {}).values():
            if isinstance(obj, GarageCoordinator):
                return obj
        return None

    @property
    def ampel(self) -> str | None:
        """Der Ampelwert, oder None wenn die Garage nichts sagt."""
        g = self.garage()
        if g is None or not g.last_update_success or not g.data:
            return None
        return g.ampel

    # --- Ein und aus --------------------------------------------------

    async def async_an(self) -> None:
        """Betriebsart einschalten: Quittungston, dann das Ampelbild."""
        if self.garage() is None:
            raise UpdateFailed(
                "Die Betriebsart \"Ampel\" braucht den Garagen-ESP - "
                "er ist in Home Assistant nicht eingerichtet"
            )
        self.aktiv = True
        self.pausiert = False
        self._bild = None
        self._horchen()
        # Der Ton kommt vor dem Bild: das Umschalten soll man hoeren, auch
        # wenn die Ampel gerade "aus" sagt und gar nichts zu sehen ist.
        try:
            await self.saeule.async_piep()
        except Exception as err:  # noqa: BLE001 - ein stummer Piep ist kein Grund
            _LOGGER.debug("Quittungston ging nicht: %s", err)
        await self.async_nachziehen()

    @callback
    def verlassen(self) -> None:
        """Betriebsart beenden, ohne etwas zu schalten.

        Die Saeule bleibt stehen, wie sie gerade steht - wer von Hand einen
        Status oder eine Leuchte waehlt, hat damit schon gesagt, was er sehen
        will. Ein Bild darueberzuschreiben waere ein Stolperer.
        """
        self.aktiv = False
        self.pausiert = False
        self.fehler = None
        self._bild = None
        self._nicht_mehr_horchen()

    # --- Der Weckruf hat Vorrang --------------------------------------

    @callback
    def pausieren(self) -> None:
        """Der Weckablauf fasst die Saeule an - bis zu seinem Ende still sein."""
        if self.aktiv:
            self.pausiert = True

    async def async_weiter(self) -> None:
        """Der Weckablauf ist durch - das Ampelbild nachziehen."""
        if not self.aktiv or not self.pausiert:
            return
        self.pausiert = False
        self._bild = None           # der Ablauf hat die Saeule umgestellt
        await self.async_nachziehen()

    # --- Das Bild stellen ---------------------------------------------

    def _bild_fuer(self, ampel: str | None) -> tuple[dict[int, int], str]:
        """({Nummer: Blinkperiode in ms}; was das Bild bedeutet).

        Antwortet die Garage nicht, fehlen dem ESP die 5 V - ein anderer
        Fall als "kein Strom am Tor", und darum ein anderes Bild: rot blinkt
        im Takt der gelben, ohne Hinweisleuchte.
        """
        if ampel is None:
            farben, warum = AMPEL_KEIN_ESP, "Garage nicht zu erreichen"
        else:
            farben = AMPEL_BILD.get(ampel, {})
            warum = f"Ampel {ampel}"
        bild: dict[int, int] = {}
        for farbe, periode in farben.items():
            nr = self.saeule.nummer_farbe(farbe)
            if nr is None:
                raise UpdateFailed(
                    f"Die Saeule meldet keine Leuchte \"{farbe}\" - "
                    "braucht Firmware 1.3.0 oder neuer"
                )
            bild[nr] = periode
        return bild, warum

    async def async_nachziehen(self) -> None:
        """Das Ampelbild stellen, wenn es sich geaendert hat."""
        if not self.aktiv or self.pausiert:
            return
        try:
            an, warum = self._bild_fuer(self.ampel)
        except UpdateFailed as err:
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Ampel: %s", err)
            return
        if an == self._bild:
            return
        try:
            await self.saeule.async_stufen_stellen(an)
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Ampel: %s", err)
            return
        self._bild = an
        self.fehler = None
        _LOGGER.debug("Betriebsart Ampel: %s -> Leuchten %s", warum, an or "aus")

    # Die Saeule blinkt selbst (Firmware 1.6.0): Home Assistant kann nicht im
    # Sekundentakt schalten, und ein Ampeltakt aus dem Netz waere ein
    # Zufallstakt.

    # --- Auf die Garage hoeren ----------------------------------------

    @callback
    def _horchen(self) -> None:
        if self._ab_garage is not None:
            return
        g = self.garage()
        if g is None:
            return
        self._gehoert = g
        self._ab_garage = g.async_add_listener(self._garage_gemeldet)

    @callback
    def async_garage_neu(self) -> None:
        """Die Garage wurde (neu) eingerichtet - den Listener nachziehen.

        Wird der Garagen-Eintrag neu geladen, ist sein Coordinator ein neues
        Objekt: der alte Listener haengt an einem, das niemand mehr fragt, und
        die Saeule bliebe auf dem letzten Bild stehen. Darum ruft das
        Garagen-Setup diese Stelle (siehe __init__.py).
        """
        if not self.aktiv:
            return
        if self.garage() is self._gehoert and self._ab_garage is not None:
            return
        self._nicht_mehr_horchen()
        self._horchen()
        self._bild = None           # was dort steht, wissen wir nicht mehr
        self.hass.async_create_task(self.async_nachziehen())

    @callback
    def _nicht_mehr_horchen(self) -> None:
        ab, self._ab_garage = self._ab_garage, None
        self._gehoert = None
        if ab is not None:
            ab()

    @callback
    def _garage_gemeldet(self) -> None:
        if self.aktiv and not self.pausiert:
            self.hass.async_create_task(self.async_nachziehen())

    @callback
    def async_stop(self) -> None:
        self._nicht_mehr_horchen()

    # --- Anzeige ------------------------------------------------------

    def attribute(self) -> dict[str, Any]:
        return {
            "ampel": self.ampel,
            "ampel_pausiert": self.pausiert,
            "ampel_fehler": self.fehler,
            "garage": "verbunden" if self.garage() else "nicht eingerichtet",
        }
