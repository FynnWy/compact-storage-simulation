# metrics/rq4_plateau.py
"""
Die eingefrorene RQ4-Konvergenzregel — EINE Implementierung.

Diese Datei enthaelt die reine Analysefunktion. Sie rechnet ausschliesslich
auf bereits erzeugten Daten (Distribution-Snapshots und Retrieval-Zeiten),
greift NICHT auf die Simulation zu und verbraucht KEINE Zufallszahl.

Warum hier und nicht in `experiments/closeout/`
-----------------------------------------------
Die Regel wird an zwei Stellen gebraucht:

* `experiments/closeout/analyse_rq4_plateau.py` — offline auf den
  Kalibrationsspuren,
* `experiments/run_export.py` — beim Export der finalen Kampagne.

Zwei Implementierungen derselben Regel waeren ein Reproduzierbarkeitsrisiko:
sie koennten auseinanderlaufen, ohne dass es jemand merkt. Deshalb liegt die
Regel an einem neutralen Ort, und beide Aufrufer importieren sie.

Signal
------
`abc_level_<Klasse>_<Tiefe>`: der Anteil aller gelagerten Bins je Kombination
aus statischer ABC-Klasse und Tiefe unter der Stapeloberkante. 24 Komponenten
bei H = 8, Summe 1.

Die ABC-Klasse ist statisch ueber die `bin_id` definiert, fuer alle Policies
identisch berechenbar und bildet unter Zipf = 1,0 die Nachfrage ab. Die Tiefe
von oben ist genau die Groesse, ueber die Mellers vierte Forschungsfrage
spricht.

Regel
-----
    Block             = R aufeinanderfolgende physische Retrievals
    d_i               = TVD zwischen Block i-1 und Block i
    Vergleichsfenster = je K aufeinanderfolgende d_i
    Plateau ab i      : mean(d[i-K+1..i]) >= (1 - delta) * mean(d[i-2K+1..i-K])
    Persistenz        : die Bedingung haelt P-mal hintereinander
    Re-Divergenz      : ein spaeteres gleitendes Mittel ueber K Distanzen
                        steigt ueber `redivergence_factor` mal das Plateauniveau

Warum relativ und nicht absolut: Steady State heisst nicht `TVD -> 0`. Ein
Lager bleibt auch eingeschwungen dynamisch, und wie gross dieses
Grundrauschen ist, haengt an der Policy — ohne Ordered Return bleibt jede
Umlagerung liegen, das Plateau liegt hoeher. Eine gemeinsame absolute
Schwelle wuerde ganze Policyfamilien systematisch als „nicht konvergiert"
markieren.

Warum Retrieval-Bloecke und nicht Zeitbloecke: Die raeumliche Verteilung
aendert sich durch Retrievals, nicht durch Zeit. Bei Zeitbloecken misst eine
schnelle Policy zwangslaeufig groessere Abstaende als eine langsame.

Die vier Parameter stammen aus den Kalibrationsspuren. Sie sind eingefroren;
es gibt keine Grid-Search und keine nachtraegliche Anpassung.
"""

import statistics as st
from typing import Dict, List, Optional, Sequence, Tuple

# ------------------------------------------------------------------ #
# Eingefrorene Parameter (Stand 2026-08-22, unveraendert)
# ------------------------------------------------------------------ #
RQ4_BLOCK_RETRIEVALS = 50
RQ4_K = 2
RQ4_DELTA = 0.10
RQ4_P = 2
RQ4_REDIVERGENCE_FACTOR = 1.5

#: Die drei einzigen zulaessigen Zustaende.
RQ4_STATUSES = ("converged", "converged_then_rediverged", "not_converged")


def abc_level_components(snapshot: dict) -> Dict[str, float]:
    """Die `abc_level_*`-Komponenten eines Snapshots."""
    return {k: v for k, v in snapshot.items() if k.startswith("abc_level_")}


def has_abc_level_signal(snapshot: dict) -> bool:
    return any(k.startswith("abc_level_") for k in snapshot)


def total_variation_distance(p: Dict[str, float], q: Dict[str, float]) -> float:
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def retrieval_blocks(snapshots: Sequence[dict],
                     retrieval_times: Sequence[float],
                     r_per_block: int) -> List[Tuple[int, float, dict]]:
    """
    Bloecke fester RETRIEVAL-Zahl.

    Jeder Block mittelt alle Snapshots, die zwischen zwei Retrieval-Grenzen
    liegen. Rueckgabe: Liste `(block_index, end_time, komponentenmittel)`.
    """
    zeiten = sorted(t for t in retrieval_times if t is not None)

    def bis(t):
        lo, hi = 0, len(zeiten)
        while lo < hi:
            mid = (lo + hi) // 2
            if zeiten[mid] <= t:
                lo = mid + 1
            else:
                hi = mid
        return lo

    blocks: List[Tuple[int, float, dict]] = []
    start = 0
    naechste_grenze = r_per_block
    for idx, snap in enumerate(snapshots):
        if bis(snap["time"]) >= naechste_grenze:
            teile = snapshots[start:idx + 1]
            if teile:
                keys = sorted(abc_level_components(teile[0]))
                mittel = {k: st.mean(s.get(k, 0.0) for s in teile)
                          for k in keys}
                blocks.append((len(blocks), snap["time"], mittel))
            start = idx + 1
            naechste_grenze += r_per_block
    return blocks


def distance_series(snapshots: Sequence[dict],
                    retrieval_times: Sequence[float],
                    r_per_block: int = RQ4_BLOCK_RETRIEVALS
                    ) -> List[Tuple[float, float]]:
    """Folge `(end_time, TVD zum Vorblock)`."""
    blocks = retrieval_blocks(snapshots, retrieval_times, r_per_block)
    return [(blocks[i][1], total_variation_distance(blocks[i - 1][2],
                                                    blocks[i][2]))
            for i in range(1, len(blocks))]


def plateau(series: Sequence[Tuple[float, float]], k: int, delta: float,
            p: int) -> Tuple[Optional[int], Optional[float], Optional[float]]:
    """
    Erster Index, ab dem das Plateau-Kriterium P-fach hintereinander haelt.

    Returns:
        `(index, zeit, niveau)` oder `(None, None, None)`.
    """
    werte = [d for _, d in series]
    treffer = 0
    for i in range(2 * k - 1, len(werte)):
        jung = st.mean(werte[i - k + 1:i + 1])
        alt = st.mean(werte[i - 2 * k + 1:i - k + 1])
        if jung >= (1 - delta) * alt:
            treffer += 1
            if treffer >= p:
                start = i - p + 1
                niveau = st.mean(werte[start - k + 1:i + 1])
                return start, series[start][0], niveau
        else:
            treffer = 0
    return None, None, None


def analyse_series(snapshots: Sequence[dict],
                   retrieval_times: Sequence[float],
                   r: int = RQ4_BLOCK_RETRIEVALS,
                   k: int = RQ4_K,
                   delta: float = RQ4_DELTA,
                   p: int = RQ4_P,
                   redivergence_factor: float = RQ4_REDIVERGENCE_FACTOR
                   ) -> dict:
    """
    Wertet einen Lauf aus und liefert EINEN eindeutigen Status.

        not_converged             kein Plateau gefunden
        converged_then_rediverged Plateau gefunden, danach steigt die TVD
                                  wieder ueber `redivergence_factor` mal das
                                  Plateauniveau
        converged                 Plateau gefunden und gehalten

    Frueher konnte `converged=True` gleichzeitig mit einer Re-Divergenz
    gelten — fachlich widerspruechlich: ein Lager, dessen Verteilung wieder
    deutlich zu wandern beginnt, war zu diesem Zeitpunkt nicht im Steady
    State. `converged` bedeutet ausschliesslich den dritten Fall.

    Die Re-Divergenz wird auf DERSELBEN Mittelungsbasis geprueft wie das
    Plateau: gleitendes Mittel ueber K Distanzen gegen das Plateaumittel. Ein
    Vergleich einzelner Blockabstaende gegen ein Mittel ist dimensional
    inkonsistent — auch klar stabile Laeufe erreichen Einzelwerte von 1,25 bis
    1,42 mal dem Plateauniveau, die Schwelle 1,5 laege mitten im Rauschband.

    Args:
        snapshots: Distribution-Snapshots mit `time` und `abc_level_*`.
        retrieval_times: Zeitpunkte der physischen Retrievals.

    Returns:
        dict mit `status`, `converged`, `convergence_time`,
        `convergence_retrievals`, `plateau_time`, `plateau_level`,
        `redivergence`, `distances` und den verwendeten Parametern.
    """
    brauchbar = [s for s in snapshots if has_abc_level_signal(s)]
    zeiten = sorted(t for t in retrieval_times if t is not None)
    folge = distance_series(brauchbar, zeiten, r)
    idx, zeit, niveau = plateau(folge, k, delta, p)

    ergebnis = {
        "rule": "abc_level_tvd_relative_plateau",
        "block_retrievals": r,
        "k": k,
        "delta": delta,
        "persistence": p,
        "redivergence_factor": redivergence_factor,
        "blocks": len(folge) + 1 if folge else 0,
        "distances": [round(x, 5) for _, x in folge],
        "plateau_time": zeit,
        "plateau_level": round(niveau, 5) if niveau is not None else None,
        "max_after_plateau": None,
        "max_window_mean_after_plateau": None,
        "convergence_retrievals": None,
    }

    if idx is None:
        ergebnis.update(status="not_converged", converged=False,
                        convergence_time=None, redivergence=False)
        return ergebnis

    spaet = [x for _, x in folge[idx + 1:]]
    fenster_mittel = [st.mean(spaet[i:i + k])
                      for i in range(len(spaet) - k + 1)]
    rediv = bool(fenster_mittel
                 and max(fenster_mittel) > redivergence_factor * niveau)
    ergebnis["redivergence"] = rediv
    ergebnis["max_after_plateau"] = round(max(spaet), 5) if spaet else None
    ergebnis["max_window_mean_after_plateau"] = (
        round(max(fenster_mittel), 5) if fenster_mittel else None)

    if rediv:
        ergebnis.update(status="converged_then_rediverged", converged=False,
                        convergence_time=None)
        return ergebnis

    ergebnis.update(status="converged", converged=True, convergence_time=zeit)
    ergebnis["convergence_retrievals"] = sum(1 for t in zeiten if t <= zeit)
    return ergebnis


def analyse_engine(engine, r: int = RQ4_BLOCK_RETRIEVALS, **kwargs) -> dict:
    """
    Bequemlichkeitsschale fuer einen abgeschlossenen Lauf.

    Liest die Snapshots und Retrieval-Zeitpunkte aus dem Engine-Objekt und
    wendet dieselbe reine Regel an. Nur Lesezugriff, kein RNG.
    """
    snapshots = engine.metrics.get_distribution_timeseries() or []
    zeiten = [row.get("t_pickstation")
              for row in engine.metrics.retrievals]
    return analyse_series(snapshots, zeiten, r=r, **kwargs)
