"""
Finale RQ4-Konvergenzregel auf den Kalibrationsspuren.

Die REGEL selbst steht in `metrics/rq4_plateau.py` und wird von dort
importiert — dieselbe Funktion, die auch der Export der finalen Kampagne
benutzt. Dieses Skript ist nur noch die Dateischale drumherum: Pilot-/
Kalibrations-JSON laden, Zeiten herausziehen, Ergebnis lesbar ausgeben.

Vorher lag die Regel hier und wurde vom Export nicht mitbenutzt. Zwei
Implementierungen derselben Regel sind ein Reproduzierbarkeitsrisiko; die
Zusammenfuehrung war Teil des Export-Closeouts (2026-08-24).

Aufruf:
    analyse_rq4_plateau.py <ordner> [R] [K] [delta] [P]
"""
import json
import sys
from pathlib import Path

REPO = str(Path(__file__).resolve().parents[2])
if REPO not in sys.path:
    sys.path.insert(0, REPO)

from metrics.rq4_plateau import (  # noqa: E402
    RQ4_BLOCK_RETRIEVALS, RQ4_DELTA, RQ4_K, RQ4_P, RQ4_REDIVERGENCE_FACTOR,
    abc_level_components, analyse_series, distance_series,
    has_abc_level_signal, plateau, total_variation_distance,
)

# Rueckwaertskompatible Namen fuer die uebrigen Closeout-Skripte.
komponenten = abc_level_components
tvd = total_variation_distance


def distanzfolge(snapshots, retrievals, r_pro_block):
    """Zeiten aus den Pilot-Retrievalzeilen (`"t"`) ziehen, dann die Regel."""
    return distance_series(snapshots,
                           [r.get("t") for r in retrievals],
                           r_pro_block)


def analysiere(datei, r=RQ4_BLOCK_RETRIEVALS, k=RQ4_K, delta=RQ4_DELTA,
               p=RQ4_P, redivergence_factor=RQ4_REDIVERGENCE_FACTOR):
    """
    Wertet eine Pilot-/Kalibrationsdatei aus.

    Der Status kommt unveraendert aus `metrics.rq4_plateau.analyse_series`;
    ergaenzt werden nur die Kennfelder des Laufs (Policy, Seed, t_end).
    """
    d = json.loads(Path(datei).read_text())
    snaps = [s for s in d.get("distribution", []) if has_abc_level_signal(s)]
    zeiten = [row.get("t") for row in d["retrievals"]]

    ergebnis = analyse_series(snaps, zeiten, r=r, k=k, delta=delta, p=p,
                              redivergence_factor=redivergence_factor)
    ergebnis.update(policy=d["policy"], seed=d["seed"], t_end=d["t_end"],
                    retrievals=len(d["retrievals"]))
    return ergebnis


def main():
    ordner = Path(sys.argv[1])
    r = int(sys.argv[2]) if len(sys.argv) > 2 else RQ4_BLOCK_RETRIEVALS
    k = int(sys.argv[3]) if len(sys.argv) > 3 else RQ4_K
    delta = float(sys.argv[4]) if len(sys.argv) > 4 else RQ4_DELTA
    p = int(sys.argv[5]) if len(sys.argv) > 5 else RQ4_P

    print(f"Block R={r} Retrievals | Vergleichsfenster K={k} | "
          f"delta={delta} | Persistenz P={p}\n")
    for f in sorted(ordner.glob("*.json")):
        if f.name.endswith(".logcount.json"):
            continue
        e = analysiere(f, r, k, delta, p)
        print(f"{e['policy']:24s} seed={e['seed']:<3d} t_end={e['t_end']:<6d} "
              f"retr={e['retrievals']:<4d} n_d={len(e['distances']):<3d} "
              f"status={e['status']:<25s} t_conv={e['convergence_time']} "
              f"niveau={e['plateau_level']} "
              f"max_danach={e.get('max_after_plateau')}")
        print(f"    TVD: {e['distances']}")


if __name__ == "__main__":
    main()
