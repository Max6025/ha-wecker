"""Betriebsart "Ampel": die Signalsaeule als deutsche Verkehrsampel.

Ein dritter Platz im Schalter "Betriebsart" neben Auto und Manuell. Steht er
auf Ampel, zeigt die Saeule, wie der Stellplatz in der Garage steht (siehe
garage.py):

    Auto steht in der Garage   -> rot
    Garage frei                -> gruen
    Kein Strom an der Lichtschranke
                               -> gelb blinkt im Sekundentakt, wie an einer
                                  echten Kreuzung, und die Hinweisleuchte
                                  blinkt sehr schnell dazu
    ESP antwortet nicht        -> rot blinkt, im Takt der gelben

**Nicht** an der Ampel des ESP (`ampel` in /api/state): die gehoert zur Lampe
in der Garage und ist zum Einparken gedacht. Sie geht aus, sobald das Tor zu
ist und das Auto nicht mehr per Funk zu hoeren ist - dann steht der 206 immer
noch drin, aber es muss ihn in der Garage niemand mehr anleuchten. Eine
Statusanzeige im Zimmer will das Gegenteil: sie soll gerade dann sagen, dass
der Platz belegt ist. Darum urteilt diese Betriebsart selbst, aus `auto_drin`
und `strom`.

Die beiden Stoerungen sind auseinanderzuhalten, weil sie Verschiedenes
heissen. Fehlt der Lichtschranke der Strom, lebt der ESP und sagt, dass ihm
die 24 V fehlen - eine gestoerte Ampel also, und die blinkt gelb. Antwortet er
gar nicht, fehlen ihm selbst die 5 V: dann steht nicht einmal mehr fest, dass
die Garage ueberhaupt ueberwacht wird, und die Saeule blinkt rot. Ohne
Hinweisleuchte, im ruhigen Takt der gelben - nicht im schnellen. Weiss der ESP
nichts ueber den Platz, blinkt es ebenfalls gelb: lieber eine Stoerung zeigen
als faelschlich gruen. Ein Bild fuer "nichts leuchtet" gibt es nicht - eine
Statusanzeige, die dunkel ist, sagt nichts.

**Geschaltet wird wie an einer deutschen Ampel** (Wechsellichtzeichen nach
StVO, Zeiten nach RiLSA fuer 50 km/h):

    gruen -> GELB (3 s) -> rot
    rot   -> ROT UND GELB zusammen (1 s) -> gruen

Rot und Gelb zugleich ist das, was eine deutsche Ampel von den meisten
anderen unterscheidet, und ohne diese Zwischenphasen springt die Saeule
unvermittelt um. Zu einer Stoerung und aus einer Stoerung heraus wird nicht
ueberblendet: die soll sofort zu sehen sein.

Beim Einschalten fahert die Saeule einmal vor, wie eine Ampel bei der
Inbetriebnahme: gelb blinkt eine Sekunde, dann einmal die volle Folge durch -
gruen, gelb, rot, rot+gelb, gruen - und danach steht, was wirklich gilt (auch
dorthin ueber die richtige Zwischenphase). Ist gerade eine Stoerung, entfaellt
das: dann soll man sie sofort sehen und nicht erst nach zehn Sekunden Theater.

Still bleibt das in jedem Fall: kein Ton, keine Blitz-Warnleuchte. Der
Tongeber kommt nur einmal beim Umschalten auf diese Betriebsart.

Diese Betriebsart gibt es nur in Home Assistant, nicht in der Saeule: sie
kennt die Garage nicht. Am Geraet steht sie dabei auf "manuell", und das Bild
wird in einem Zug gesetzt (`/api/stufen`) - nicht ueber den Status, denn
dessen Choreografie waere hier ein Stolperer. Das Blinken macht die Saeule
selbst, denn ein Takt aus dem Netz waere ein Zufallstakt.

Vier Dinge beenden die Betriebsart:

- ein anderer Platz im Schalter (Auto oder Manuell),
- ein Status oder eine Stufe von Hand (wer selbst stellt, will selbst stellen
  - dieselbe Regel gilt in der Firmware fuer Auto und Manuell). Warnleuchte
  und Tongeber nicht, die gehoeren zu keinem Bild,
- der Knopf "Alles aus",
- jeder Neustart: der Ampelmodus wird bewusst nicht gemerkt. Die Saeule geht
  abends vom Netz (siehe strom.py) und kommt morgens still wieder hoch; wuerde
  der Ampelmodus das ueberdauern, stuende sie um Viertel vor fuenf auf Rot,
  lange bevor der Wecker klingelt.

Der Weckruf hat Vorrang. Fasst der Weckablauf die Saeule an, ruht der
Ampelmodus bis zum Ende des Laufs und zieht danach das Ampelbild nach.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Any

from homeassistant.core import HomeAssistant, callback
from homeassistant.helpers.update_coordinator import UpdateFailed

from .const import (
    AMPEL_BLINK_MS,
    AMPEL_BLINK_SCHNELL_MS,
    AMPEL_GELB_MS,
    AMPEL_ROT_GELB_MS,
    AMPEL_STEHT_MS,
    AMPEL_START_BLINK_MS,
    DOMAIN,
    FARBE_GRUEN,
    FARBE_HINWEIS,
    FARBE_ORANGE,
    FARBE_ROT,
)

_LOGGER = logging.getLogger(__name__)

# Die Lage am Stellplatz - das, was die Saeule zeigen soll. Nicht zu
# verwechseln mit der Ampel des ESP, die zur Lampe in der Garage gehoert.
LAGE_BESETZT = "besetzt"
LAGE_FREI = "frei"
LAGE_KEIN_STROM = "kein_strom"
LAGE_KEIN_ESP = "kein_esp"
# Bei diesen Lagen wird weder ueberblendet noch vorgefahren
LAGE_STOERUNG = (LAGE_KEIN_STROM, LAGE_KEIN_ESP)

# Die Bilder einer Ampel: Farbe -> Blinkperiode in ms, 0 heisst dauernd. Nach
# Farbe, nicht nach Relaisnummer - die Saeule meldet sie selbst (ab 1.3.0).
BILD_ROT: dict[str, int] = {FARBE_ROT: 0}
BILD_GELB: dict[str, int] = {FARBE_ORANGE: 0}
BILD_ROT_GELB: dict[str, int] = {FARBE_ROT: 0, FARBE_ORANGE: 0}
BILD_GRUEN: dict[str, int] = {FARBE_GRUEN: 0}

AMPEL_BILD: dict[str, dict[str, int]] = {
    LAGE_BESETZT: BILD_ROT,
    LAGE_FREI: BILD_GRUEN,
    # Eine gestoerte Ampel blinkt gelb, wie an der Kreuzung. Die
    # Hinweisleuchte blinkt sehr schnell dazu, damit man es nicht mit dem
    # Status "Achtung" verwechselt.
    LAGE_KEIN_STROM: {
        FARBE_ORANGE: AMPEL_BLINK_MS,
        FARBE_HINWEIS: AMPEL_BLINK_SCHNELL_MS,
    },
    # Der ESP antwortet nicht - ihm fehlen die 5 V. Rot, allein, im Takt der
    # gelben. Nicht im schnellen Blinken, und ohne Hinweisleuchte.
    LAGE_KEIN_ESP: {FARBE_ROT: AMPEL_BLINK_MS},
}

LAGE_TEXT: dict[str, str] = {
    LAGE_BESETZT: "Auto steht in der Garage",
    LAGE_FREI: "Garage frei",
    LAGE_KEIN_STROM: "kein Strom an der Lichtschranke",
    LAGE_KEIN_ESP: "Garage nicht zu erreichen",
}

# Ein Schritt ist (Bild, wie lange es steht in ms).
Schritt = tuple[dict[str, int], int]

# Die Eroeffnung: gelb blinkt, dann einmal die volle Folge durch. Was danach
# wirklich gilt, haengt der Ampelmodus mit der richtigen Zwischenphase an.
AMPEL_START: tuple[Schritt, ...] = (
    ({FARBE_ORANGE: AMPEL_START_BLINK_MS}, 1000),   # Inbetriebnahme
    (BILD_GRUEN, AMPEL_STEHT_MS),
    (BILD_GELB, AMPEL_GELB_MS),
    (BILD_ROT, AMPEL_STEHT_MS),
    (BILD_ROT_GELB, AMPEL_ROT_GELB_MS),
    (BILD_GRUEN, AMPEL_STEHT_MS),
)


def uebergang(von: dict[str, int] | None, nach: dict[str, int]) -> tuple[Schritt, ...]:
    """Die Zwischenphasen zwischen zwei Ampelbildern, deutsch.

    Gruen auf Rot geht ueber Gelb, Rot auf Gruen ueber Rot und Gelb zusammen.
    Alles andere - der erste Lauf, ein Blinkbild, zurueck aus einer Stoerung -
    kommt ohne Ueberblendung: da gibt es keine Phase, die dazu passt, und eine
    Stoerung soll ohnehin sofort zu sehen sein.
    """
    if von == BILD_GRUEN and nach == BILD_ROT:
        return ((BILD_GELB, AMPEL_GELB_MS),)
    if von == BILD_ROT and nach == BILD_GRUEN:
        return ((BILD_ROT_GELB, AMPEL_ROT_GELB_MS),)
    return ()


class Ampelmodus:
    """Haelt die Betriebsart "Ampel" fuer eine Signalsaeule."""

    def __init__(self, hass: HomeAssistant, coordinator: Any) -> None:
        self.hass = hass
        self.saeule = coordinator
        self.aktiv = False
        self.pausiert = False          # der Weckablauf hat die Saeule
        self.fehler: str | None = None
        self._bild: dict[str, int] | None = None   # was zuletzt gestellt wurde
        self._folge: asyncio.Task | None = None    # laufende Phasenfolge
        self._ab_garage: Any = None           # Abmelder des Garagen-Listeners
        self._gehoert: Any = None             # an welchem Coordinator er haengt

    @callback
    def melden(self) -> None:
        """Die Entitaeten der Saeule auffrischen.

        Die Betriebsart steht am Schalter mit allem, was hier passiert - Lage,
        Fehler, laufende Folge. Weil das auch ausserhalb eines Dienstrufs
        passiert (Wort aus der Garage, Ende einer Folge), muss es von hier
        gemeldet werden, sonst bleibt der Schalter auf dem alten Stand.
        """
        self.saeule.async_update_listeners()

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
        """Der Ampelwert des ESP - nur zur Anzeige, nicht fuer das Bild."""
        g = self.garage()
        if g is None or not g.last_update_success or not g.data:
            return None
        return g.ampel

    @property
    def lage(self) -> str:
        """Wie der Stellplatz steht - das, was die Saeule zeigen soll.

        Aus `auto_drin` und `strom`, nicht aus der Ampel des ESP: die gehoert
        zur Lampe in der Garage und geht aus, sobald niemand mehr einparkt.
        Weiss der ESP nichts ueber den Platz, ist das eine Stoerung und keine
        freie Garage - lieber gelb blinken als faelschlich gruen.
        """
        g = self.garage()
        if g is None or not g.last_update_success or not g.data:
            return LAGE_KEIN_ESP
        if not g.ja("strom"):
            return LAGE_KEIN_STROM
        drin = g.ja("auto_drin")
        if drin is None:
            return LAGE_KEIN_STROM
        return LAGE_BESETZT if drin else LAGE_FREI

    # --- Ein und aus --------------------------------------------------

    async def async_an(self) -> None:
        """Betriebsart einschalten: Quittungston, dann vorfahren."""
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
        # wenn gerade nichts Neues zu sehen ist.
        try:
            await self.saeule.async_piep()
        except Exception as err:  # noqa: BLE001 - ein stummer Piep ist kein Grund
            _LOGGER.debug("Quittungston ging nicht: %s", err)
        if self.lage in LAGE_STOERUNG:
            # Eine Stoerung soll sofort zu sehen sein, nicht erst nach zehn
            # Sekunden Theater.
            await self.async_nachziehen()
            return
        self._folge_starten(AMPEL_START)

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
        self._folge_abbrechen()
        self._nicht_mehr_horchen()

    # --- Der Weckruf hat Vorrang --------------------------------------

    @callback
    def pausieren(self) -> None:
        """Der Weckablauf fasst die Saeule an - bis zu seinem Ende still sein."""
        if self.aktiv:
            self.pausiert = True
            self._folge_abbrechen()

    async def async_weiter(self) -> None:
        """Der Weckablauf ist durch - das Ampelbild nachziehen."""
        if not self.aktiv or not self.pausiert:
            return
        self.pausiert = False
        self._bild = None           # der Ablauf hat die Saeule umgestellt
        await self.async_nachziehen()

    # --- Phasenfolgen -------------------------------------------------

    @property
    def schaltet(self) -> bool:
        """Laeuft gerade eine Folge (Eroeffnung oder Zwischenphase)?"""
        return self._folge is not None and not self._folge.done()

    @callback
    def _folge_starten(self, schritte: tuple[Schritt, ...]) -> None:
        """Eine Folge nebenher abfahren und danach das echte Bild stellen.

        Nebenher, weil ein Dienstruf in Home Assistant nicht sekundenlang
        haengen darf. Solange sie laeuft, schreibt der Ampelmodus kein Bild -
        sonst funkte ein Wort aus der Garage mitten hinein.
        """
        self._folge_abbrechen()
        self._folge = self.hass.async_create_task(self._folge_fahren(schritte))

    async def _folge_fahren(self, schritte: tuple[Schritt, ...]) -> None:
        try:
            for bild, dauer_ms in schritte:
                if not self.aktiv or self.pausiert:
                    return
                if self.lage in LAGE_STOERUNG:
                    break           # eine Stoerung dazwischen bricht ab
                await self.saeule.async_stufen_stellen(bild)
                self._bild = bild
                await asyncio.sleep(dauer_ms / 1000)
        except asyncio.CancelledError:
            raise
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Ampel, Phasenfolge: %s", err)
        finally:
            self._folge = None
            if self.aktiv and not self.pausiert:
                await self.async_nachziehen()
            self.melden()

    @callback
    def _folge_abbrechen(self) -> None:
        task, self._folge = self._folge, None
        if task is not None and not task.done():
            task.cancel()

    # --- Das Bild stellen ---------------------------------------------

    def _bild_fuer(self, lage: str) -> tuple[dict[str, int], str]:
        """({Farbe: Blinkperiode in ms}; was das Bild bedeutet)."""
        bild = AMPEL_BILD.get(lage, {})
        for farbe in bild:
            if self.saeule.nummer_farbe(farbe) is None:
                raise UpdateFailed(
                    f"Die Saeule meldet keine Leuchte \"{farbe}\" - "
                    "braucht Firmware 1.3.0 oder neuer"
                )
        return dict(bild), LAGE_TEXT.get(lage, lage)

    async def async_nachziehen(self) -> None:
        """Das Ampelbild stellen, wenn es sich geaendert hat.

        Liegt zwischen dem alten und dem neuen Bild eine Zwischenphase (Gelb
        oder Rot+Gelb), wird die zuerst gefahren - und zwar in einer Folge
        nebenher, die am Ende hier wieder hereinkommt.
        """
        if not self.aktiv or self.pausiert or self.schaltet:
            return
        try:
            ziel, warum = self._bild_fuer(self.lage)
        except UpdateFailed as err:
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Ampel: %s", err)
            self.melden()
            return
        if ziel == self._bild:
            return

        zwischen = uebergang(self._bild, ziel)
        if zwischen:
            _LOGGER.debug("Betriebsart Ampel: %s, ueber die Zwischenphase", warum)
            self._folge_starten(zwischen + ((ziel, 0),))
            return

        try:
            await self.saeule.async_stufen_stellen(ziel)
        except Exception as err:  # noqa: BLE001
            self.fehler = str(err)
            _LOGGER.warning("Betriebsart Ampel: %s", err)
            self.melden()
            return
        self._bild = ziel
        self.fehler = None
        self.melden()
        _LOGGER.debug("Betriebsart Ampel: %s -> %s", warum, ziel or "aus")

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
        if self.aktiv and not self.pausiert and not self.schaltet:
            self.hass.async_create_task(self.async_nachziehen())

    @callback
    def async_stop(self) -> None:
        self._folge_abbrechen()
        self._nicht_mehr_horchen()

    # --- Anzeige ------------------------------------------------------

    def attribute(self) -> dict[str, Any]:
        return {
            "lage": self.lage,                 # was die Saeule zeigt
            "lage_text": LAGE_TEXT.get(self.lage, self.lage),
            "ampel": self.ampel,               # was der ESP seiner Lampe sagt
            "ampel_pausiert": self.pausiert,
            "ampel_schaltet": self.schaltet,
            "ampel_fehler": self.fehler,
            "garage": "verbunden" if self.garage() else "nicht eingerichtet",
        }
