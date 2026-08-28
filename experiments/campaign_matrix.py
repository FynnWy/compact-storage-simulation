# experiments/campaign_matrix.py
"""
Die eingefrorene Experimentmatrix — EINE Quelle.

Policies, Seeds, Geometrie und Zeithorizonte der finalen Kampagne stehen
ausschliesslich hier. Der Kampagnentreiber
(`experiments/run_final_campaign.py`), die Matrixpruefung
(`experiments/closeout/dry_check_matrix.py`) und der Kalibrationstreiber
(`experiments/closeout/pilot_run.py`) beziehen sich alle auf diese Datei.

Warum das wichtig ist: waeren Policy-Menge, Seed-Liste oder Geometrie an
mehreren Stellen definiert, koennte die Matrixpruefung etwas anderes pruefen,
als die Kampagne spaeter rechnet — und niemand wuerde es merken. Genau diese
Klasse von Fehler hat den Freeze bereits einmal aufgehalten.

Dieses Modul rechnet nicht. Es erzeugt Konfigurationen und prueft sie.
Es fasst keine Simulationslogik an und verbraucht keine Zufallszahl.
"""

from typing import Dict, List, Optional, Tuple

from config.simulation_config import SimulationConfig

# ====================================================================== #
# Die fuenf finalen Konfigurationen
# ====================================================================== #
#
# (reordering_strategy, placement_strategy, return_blocking_bins)
#
# `baseline_reference` ist NICHT eine der vier untersuchten Policies, sondern
# die Referenz: LOFI/RANDOM, aber MIT Ordered Return. Sie unterscheidet sich
# von RR+RR in genau einer Dimension.
#
# Ohne Ordered Return (RR+RR, LR+NR) ist `reordering_strategy` wirkungslos;
# LOFI steht dort nur, weil ein Wert gesetzt sein muss.
FINAL_POLICIES: Dict[str, Tuple[str, str, bool]] = {
    "baseline_reference":    ("LOFI",       "RANDOM",     True),
    "RR+RR":                 ("LOFI",       "RANDOM",     False),
    "LR+NR":                 ("LOFI",       "NEAREST",    False),
    "ABC+ABC":               ("ABC",        "ABC",        True),
    "POPULARITY+POPULARITY": ("POPULARITY", "POPULARITY", True),
}

FINAL_SEEDS: Tuple[int, ...] = (1, 2, 3, 4, 7, 11, 13, 42, 99, 123)

# ====================================================================== #
# Eingefrorene Zeithorizonte (hergeleitet in experiments/experiment_setup.md)
# ====================================================================== #
FINAL_T_MEASURE_START = 20_000
FINAL_T_FINAL = 30_000
FINAL_SIMULATION_TIME = 30_000

# ====================================================================== #
# Eingefrorenes Szenario
# ====================================================================== #
#
# Diese Werte sind die Sollwerte des Pre-Campaign-Checks. Sie stehen als
# Datenstruktur da, damit der Treiber sie maschinell pruefen kann statt auf
# Defaults zu vertrauen.
FINAL_SETUP: Dict[str, object] = {
    "grid_width": 20,
    "grid_depth": 30,
    "max_stack_height": 8,
    "bin_num": 4320,
    "num_robots": 8,
    "num_pickstations": 2,
    "pickstation_capacity": 1,
    "request_arrival_strategy": "Poisson",
    "request_utilization": 0.6,
    "bin_request_prob_strategy": "zipf",
    "zipf_parameter": 1.0,
    "scheduler_strategy": "EDF",
    "deadline_slack": 240,
    "popularity_warmup_retrievals": 50,
    "distribution_snapshot_interval": 100,
    "enable_visualization": False,
    "stop_on_convergence": False,
    "simulation_time": FINAL_SIMULATION_TIME,
    "t_measure_start": FINAL_T_MEASURE_START,
    "t_final": FINAL_T_FINAL,
}


def run_id(policy: str, seed: int) -> str:
    """Deterministischer wissenschaftlicher Schluessel, z.B. `ABC+ABC__seed7`."""
    return f"{policy}__seed{seed}"


def final_matrix() -> List[Tuple[str, str, int]]:
    """Die 50 Kombinationen als `(run_id, policy, seed)`, feste Reihenfolge."""
    return [(run_id(p, s), p, s)
            for p in FINAL_POLICIES for s in FINAL_SEEDS]


#: Sentinel: „nicht uebergeben" ist etwas anderes als ein ausdrueckliches
#: `None`. Ohne ihn liesse sich das Fenster nicht gezielt abschalten, weil
#: `None` schon „nimm den Default" bedeutet — eine stille Falle fuer
#: Diagnoselaeufe, die bewusst ohne Fenster rechnen.
_DEFAULT = object()


def build_run_config(policy: str, seed: int,
                     sim_time: Optional[int] = None,
                     t_measure_start=_DEFAULT,
                     t_final=_DEFAULT) -> SimulationConfig:
    """
    Baut die Konfiguration einer Kombination.

    Ohne Argumente entsteht exakt die finale Kampagnenkonfiguration. Die drei
    optionalen Argumente existieren fuer Kalibration, Smoke-Test und
    Matrixpruefung — sie aendern NUR den Zeithorizont, niemals das Szenario.

    Args:
        sim_time: Lauflaenge. Default `FINAL_SIMULATION_TIME`.
        t_measure_start: Fensterbeginn. Nicht uebergeben -> finaler Wert.
            Ausdrueckliches `None` -> kein Fenster (`full_run`).
        t_final: Fensterende. Gleiche Semantik.
    """
    if policy not in FINAL_POLICIES:
        raise ValueError(
            f"Unbekannte Policy {policy!r}. Erlaubt: {sorted(FINAL_POLICIES)}")
    reordering, placement, rbb = FINAL_POLICIES[policy]

    c = SimulationConfig()
    c.grid_width = 20
    c.grid_depth = 30
    c.max_stack_height = 8
    c.bin_num = 4320
    c.num_robots = 8
    c.num_pickstations = 2
    c.pickstation_capacity = 1
    c.simulation_time = FINAL_SIMULATION_TIME if sim_time is None else sim_time
    c.random_seed = seed
    c.request_arrival_strategy = "Poisson"
    c.request_utilization = 0.6
    c.bin_request_prob_strategy = "zipf"
    c.zipf_parameter = 1.0
    c.enable_visualization = False
    c.distribution_snapshot_interval = 100
    c.reordering_strategy = reordering
    c.placement_strategy = placement
    c.return_blocking_bins = rbb
    c.t_measure_start = (FINAL_T_MEASURE_START
                         if t_measure_start is _DEFAULT else t_measure_start)
    c.t_final = FINAL_T_FINAL if t_final is _DEFAULT else t_final
    return c


def check_final_config(config: SimulationConfig) -> List[str]:
    """
    Prueft eine Konfiguration gegen das eingefrorene Szenario.

    Returns:
        Liste der Abweichungen als lesbare Zeilen. Leer heisst: passt.

    Bewusst gegen `FINAL_SETUP` und nicht gegen die Defaults von
    `SimulationConfig`: die Defaults sind das kleine Entwicklungsszenario
    (5x5, 100 Bins). Wer sich auf sie verlaesst, prueft nichts.
    """
    abweichungen = []
    for feld, soll in FINAL_SETUP.items():
        ist = getattr(config, feld, "<fehlt>")
        if ist != soll:
            abweichungen.append(f"{feld}: ist={ist!r} soll={soll!r}")
    return abweichungen


def check_matrix(kombinationen: List[Tuple[str, str, int]]) -> List[str]:
    """Prueft eine Matrix auf Vollstaendigkeit, Eindeutigkeit und Umfang."""
    fehler = []
    ids = [k[0] for k in kombinationen]
    erwartet = final_matrix()

    if len(kombinationen) != len(erwartet):
        fehler.append(f"{len(kombinationen)} Kombinationen statt "
                      f"{len(erwartet)}")
    if len(set(ids)) != len(ids):
        doppelt = sorted({i for i in ids if ids.count(i) > 1})
        fehler.append(f"doppelte run_id: {doppelt}")

    fehlend = {k[0] for k in erwartet} - set(ids)
    zuviel = set(ids) - {k[0] for k in erwartet}
    if fehlend:
        fehler.append(f"fehlende Kombinationen: {sorted(fehlend)}")
    if zuviel:
        fehler.append(f"unerwartete Kombinationen: {sorted(zuviel)}")

    policies = {k[1] for k in kombinationen}
    seeds = {k[2] for k in kombinationen}
    if policies != set(FINAL_POLICIES):
        fehler.append(f"Policy-Menge weicht ab: {sorted(policies)}")
    if seeds != set(FINAL_SEEDS):
        fehler.append(f"Seed-Menge weicht ab: {sorted(seeds)}")
    return fehler
