# config/rng_streams.py
"""
Zentrale Zufallsströme der Simulation (Phase 4).

Hintergrund
-----------
Vor Phase 4 teilten sich mehrere fachlich unabhängige Größen denselben
Generator:

    engine.rng  ->  Roboter-Startpositionen   (exogen)
                ->  Pickstation-Servicezeiten (exogen)
                ->  RANDOM-Placement und Tie-Breaks (endogen, policyabhängig)

Weil die Policies unterschiedlich viele Placement-Entscheidungen treffen,
verschob sich dadurch die Servicezeit-Folge zwischen den Policies. Gemessen
(12x18, Seed 42, 800 ZE): von rund 50 Servicezeiten stimmten je nach Policy
nur 15 bis 24 mit der Referenz überein, erste Abweichung bereits an
Position 3 bis 5. Ein Vergleich unter „gleichem Seed" war damit kein
Vergleich unter gleichen Bedingungen.

Lösung
------
Ein Master-Seed, daraus über `SeedSequence.spawn()` unabhängige Ströme. Ein
Verbraucher zieht nie aus einem Strom, der einer fachlich anderen Größe
gehört.

    exogen   initialization   initiale Bin-Verteilung
    exogen   robots           Roboter-Startpositionen
    exogen   requests         Ankünfte, Target-Bins, Zeitfenster
    exogen   service          Pickstation-Servicezeit je Request
    endogen  relocation       zufällige Ablage von Blocking-Bins (RR+RR)
    endogen  placement        RANDOM-Placement, ABC-/Popularity-Tie-Breaks,
                              Popularity-Warmup

WICHTIG – Stromnamen sind append-only
-------------------------------------
Die Reihenfolge in `STREAM_NAMES` bestimmt, welcher gespawnte Kindstrom ein
Verbraucher bekommt. Wird ein Name eingefügt oder umsortiert, ändern sich
sämtliche Zufallsfolgen dahinter und alle bisherigen Läufe sind nicht mehr
reproduzierbar. Neue Ströme deshalb ausschließlich **hinten** anfügen.

`SeedSequence.spawn(n)` ist inkrementell: `spawn(6)` liefert dieselben ersten
fünf Kinder wie `spawn(5)`. Anhängen ist deshalb für die bestehenden Ströme
unschädlich.

Warum `robots` ein eigener Strom ist (Phase 5)
---------------------------------------------
Vorher zogen Roboter-Startpositionen und Bin-Verteilung nacheinander aus
`initialization`. Damit hing das Binlayout an der Roboterzahl: Ein Lauf mit
6 statt 8 Robotern verbrauchte zwei Ziehungen weniger und erzeugte ein
anderes Lager. Für Parameterstudien über `num_robots` wäre jeder Vergleich
dadurch konfundiert gewesen.

Jetzt gilt: Das initiale Binlayout hängt allein am Master-Seed – nicht an der
Roboterzahl.

Stream-Trennung allein genügt nicht
-----------------------------------
Ein eigener Strom macht eine Größe nur dann policyübergreifend identisch,
wenn auch die Ziehungsreihenfolge policyunabhängig ist. Für die
Servicezeiten ist das nicht der Fall – sie werden in der Reihenfolge
angefordert, in der Roboter an den Pickstations eintreffen, und die hängt
vom Verhalten der Policy ab.

Deshalb werden Servicezeiten nicht zur Laufzeit gezogen, sondern einmalig
beim Erzeugen des Request-Stroms – gebunden an die `request_id`. Siehe
`SimulationEngine._assign_exogenous_service_times`.
"""

import numpy as np


STREAM_NAMES = (
    "initialization",
    "requests",
    "service",
    "relocation",
    "placement",
    # Phase 5 (Experiment Readiness) angehaengt – siehe Hinweis unten.
    "robots",
)

EXOGENOUS_STREAMS = ("initialization", "requests", "service", "robots")
ENDOGENOUS_STREAMS = ("relocation", "placement")


class RngStreams:
    """
    Vergibt unabhängige `numpy.random.Generator` aus einem Master-Seed.

    Beispiel:
        streams = RngStreams(42)
        streams.get("service").integers(4, 7)
    """

    def __init__(self, master_seed):
        self.master_seed = master_seed
        self._root = np.random.SeedSequence(master_seed)
        children = self._root.spawn(len(STREAM_NAMES))
        self._streams = {
            name: np.random.default_rng(seq)
            for name, seq in zip(STREAM_NAMES, children)
        }

    def get(self, name):
        """
        Gibt den Generator eines Stroms zurück.

        Raises:
            KeyError: bei unbekanntem Stromnamen – ein Tippfehler soll nicht
                      still einen neuen, unkoordinierten Strom erzeugen.
        """
        if name not in self._streams:
            raise KeyError(
                f"Unbekannter RNG-Strom {name!r}. "
                f"Bekannt: {', '.join(STREAM_NAMES)}"
            )
        return self._streams[name]

    def is_exogenous(self, name):
        return name in EXOGENOUS_STREAMS

    def __repr__(self):
        return (
            f"RngStreams(master_seed={self.master_seed}, "
            f"streams={list(STREAM_NAMES)})"
        )
