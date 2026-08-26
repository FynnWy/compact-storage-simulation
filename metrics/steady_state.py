# metrics/steady_state.py
"""
Steady-State-Erkennung und Stop-Regel für die finale Experimentkampagne.

Wissenschaftlicher Hintergrund
------------------------------
Meller (2023) fragt als vierte offene Forschungsfrage:

    "AutoStore grids are typically loaded in an arbitrary fashion such that,
    before the grid is put into operation, fast-moving SKUs may be found at
    the bottom of the grid and slow-moving SKUs may be found at the top.
    How long will it take for the grid to arrive at a steady state bin
    distribution under typical operating conditions?"

Lehmann & de Koster (2026) beenden ihre Warm-up-Phase, wenn sich die mittlere
Zykluszeit `t_rack` zweier aufeinanderfolgender Blöcke von je 10.000 Command
Cycles um weniger als 0,1 % unterscheidet.

Warum wir ihre Zahlen NICHT übernehmen
--------------------------------------
Ihr Modell ist ein geschlossenes Warteschlangennetz mit einer Pickstation,
ohne Roboterstaus und mit exponentiellen Servicezeiten. Unser System ist eine
ereignisdiskrete Simulation mit zwei Pickstations, echter Verkehrsführung,
Batching und abstrakten Zeiteinheiten. 10.000 Command Cycles entsprächen bei
gemessenen ~0,06 Retrievals je ZE rund 160.000 ZE pro Block – praktisch nicht
rechenbar und fachlich nicht übertragbar.

Übernommen wird das PRINZIP, nicht die Parametrierung:

    * gemessen wird in Blöcken **physischer Retrievals** (Command Cycles),
      nicht in Simulationszeit – sonst hinge die Warm-up-Länge davon ab, wie
      schnell eine Policy überhaupt arbeitet,
    * Konvergenz heißt: die relative Änderung des Signals zwischen
      aufeinanderfolgenden Blöcken bleibt klein,
    * nach der Konvergenz folgt ein FEST definiertes Measurement Window.

Wahl des Signals
----------------
Konvergiert wird auf der **mittleren Anzahl Blocking Bins je Retrieval**
(β, "digging depth").

Begründung:
    * β ist genau die Größe, die sich verändert, während sich das Lager aus
      der zufälligen Anfangsbelegung heraus sortiert (Natural Slotting) –
      also exakt der Gegenstand von RQ4,
    * β erklärt zugleich einen Hauptteil der Zykluszeit und damit der
      primären KPI (vgl. Lehmann, wo β_all in t_rack eingeht),
    * β ist eine einfache, in einer Masterarbeit erklärbare Zahl.

Ein multivariates Kriterium wäre möglich, aber schwerer zu begründen und zu
erklären. Wer den räumlichen Zustand zusätzlich prüfen will, findet die
Verteilungs-Snapshots in `DistributionMetrics`.

Robustheit bei kleinen Blöcken
------------------------------
Bei Blockgrößen in der Größenordnung von 50 Retrievals ist das Blockmittel
verrauscht. Ein einzelner Unterschreiter der Schwelle wäre daher kein
belastbares Konvergenzsignal. Verlangt werden deshalb `required_stable_pairs`
aufeinanderfolgende Blockpaare unterhalb der Schwelle.
"""

from typing import List, Optional


class SteadyStateDetector:
    """
    Blockbasierte Konvergenzerkennung auf physischen Retrievals.

    Anwendung:
        detector = SteadyStateDetector(block_size=50, threshold=0.10)
        for row in retrievals:              # in zeitlicher Reihenfolge
            detector.observe(row["blocking_bins"], row["t_pickstation"])
        detector.is_converged()
    """

    def __init__(self, block_size: int = 50, threshold: float = 0.10,
                 required_stable_pairs: int = 2,
                 reference_floor: float = 0.05):
        """
        Args:
            block_size: Anzahl physischer Retrievals je Block.
            threshold: maximale relative Änderung des Blockmittels, die noch
                als "stabil" gilt.
            required_stable_pairs: wie viele aufeinanderfolgende Blockpaare
                die Schwelle unterschreiten müssen.
            reference_floor: untere Schranke der Bezugsgröße, damit die
                relative Änderung nahe β = 0 nicht explodiert.
        """
        if block_size < 1:
            raise ValueError("block_size muss mindestens 1 sein")
        if threshold <= 0:
            raise ValueError("threshold muss positiv sein")
        if required_stable_pairs < 1:
            raise ValueError("required_stable_pairs muss mindestens 1 sein")

        self.block_size = block_size
        self.threshold = threshold
        self.required_stable_pairs = required_stable_pairs
        self.reference_floor = reference_floor

        self._current: List[float] = []
        self.block_means: List[float] = []
        self.block_end_times: List[int] = []
        self.relative_changes: List[float] = []

        self._stable_streak = 0
        self._converged_block: Optional[int] = None
        self._converged_time: Optional[int] = None
        self._converged_retrievals: Optional[int] = None

        self.total_observed = 0

    # ------------------------------------------------------------------ #

    def observe(self, value: float, time: int) -> None:
        """
        Nimmt ein weiteres Retrieval auf.

        Args:
            value: Signalwert dieses Retrievals (Anzahl Blocking Bins).
            time: Simulationszeit des Retrievals.
        """
        self.total_observed += 1
        self._current.append(float(value))

        if len(self._current) < self.block_size:
            return

        mittel = sum(self._current) / len(self._current)
        self.block_means.append(mittel)
        self.block_end_times.append(time)
        self._current = []

        if len(self.block_means) < 2:
            return

        vorher = self.block_means[-2]
        # Symmetrische, nach unten begrenzte relative Änderung.
        #
        # β geht in einem gut sortierten Lager gegen 0 (Natural Slotting).
        # Eine naive Division durch den Vorgängerwert würde dort explodieren
        # und Konvergenz nie erkennen; eine Division durch 0 wäre undefiniert.
        # Bezugsgröße ist deshalb der Mittelwert beider Blöcke, nach unten
        # durch `reference_floor` begrenzt.
        #
        # Wirkung: Zwei Blöcke mit β ≈ 0 gelten als stabil – fachlich richtig,
        # denn ein Lager ohne Digging-Bedarf IST im Steady State.
        bezug = max((mittel + vorher) / 2.0, self.reference_floor)
        aenderung = abs(mittel - vorher) / bezug
        self.relative_changes.append(aenderung)

        if aenderung <= self.threshold:
            self._stable_streak += 1
        else:
            self._stable_streak = 0

        if (self._converged_block is None
                and self._stable_streak >= self.required_stable_pairs):
            self._converged_block = len(self.block_means)
            self._converged_time = time
            self._converged_retrievals = self._converged_block * self.block_size

    # ------------------------------------------------------------------ #

    def is_converged(self) -> bool:
        return self._converged_block is not None

    def convergence_time(self) -> Optional[int]:
        """Simulationszeit (ZE), zu der der Steady State erreicht war."""
        return self._converged_time

    def convergence_retrievals(self) -> Optional[int]:
        """Anzahl physischer Retrievals bis zum Steady State."""
        return self._converged_retrievals

    def summary(self) -> dict:
        return {
            "converged": self.is_converged(),
            "convergence_time": self._converged_time,
            "convergence_retrievals": self._converged_retrievals,
            "block_size": self.block_size,
            "threshold": self.threshold,
            "required_stable_pairs": self.required_stable_pairs,
            "reference_floor": self.reference_floor,
            "blocks_completed": len(self.block_means),
            "total_retrievals_observed": self.total_observed,
            "block_means": list(self.block_means),
            "block_end_times": list(self.block_end_times),
            "relative_changes": list(self.relative_changes),
        }


def analyse_run(retrievals: List[dict], block_size: int = 50,
                threshold: float = 0.10, required_stable_pairs: int = 2,
                measurement_retrievals: int = 200,
                reference_floor: float = 0.05) -> dict:
    """
    Wertet die Retrieval-Tabelle eines Laufs nach der Stop-Regel aus.

    Stop-Regel der finalen Kampagne:
        1. Lauf startet aus dem definierten Initialzustand.
        2. Warm-up läuft, bis das Konvergenzkriterium greift.
        3. Ab dann werden `measurement_retrievals` weitere physische
           Retrievals als Measurement Window gewertet.
        4. Wird bis zum Ende des Laufs keine Konvergenz erreicht, gilt der Lauf
           als `not_converged` und wird in der Auswertung getrennt behandelt –
           nicht stillschweigend wie ein konvergierter Lauf.

    Returns:
        dict mit Konvergenzstatus, Fenstergrenzen und der Teilmenge der
        Retrievals im Measurement Window.
    """
    detector = SteadyStateDetector(block_size, threshold,
                                   required_stable_pairs, reference_floor)
    for row in retrievals:
        detector.observe(row.get("blocking_bins", 0), row.get("t_pickstation", 0))

    result = detector.summary()
    result["measurement_retrievals_target"] = measurement_retrievals

    if not detector.is_converged():
        result["status"] = "not_converged"
        result["measurement_window"] = []
        result["measurement_complete"] = False
        return result

    start_index = detector.convergence_retrievals()
    fenster = retrievals[start_index:start_index + measurement_retrievals]
    result["status"] = "converged"
    result["measurement_window"] = fenster
    result["measurement_complete"] = len(fenster) >= measurement_retrievals
    result["measurement_start_time"] = (
        fenster[0].get("t_pickstation") if fenster else None
    )
    result["measurement_end_time"] = (
        fenster[-1].get("t_pickstation") if fenster else None
    )
    return result
