"""
Ableitung von `T_measure_start` und `T_final` aus den Kalibrationsspuren.

Vorgehen
--------
1. Konvergenzzeitpunkt je Lauf (relatives Plateau-Kriterium).
2. `T_measure_start` = langsamste beobachtete Konvergenz + Reserve.
   Die Reserve wird NICHT frei gewaehlt, sondern aus der beobachteten
   Streuung zwischen Seeds derselben Policy abgeleitet: ein bisher
   ungetesteter Seed darf noch einmal so viel langsamer sein wie der
   groesste beobachtete Abstand innerhalb einer Policy.
3. Fensterlaenge aus der LANGSAMSTEN Retrievalrate NACH der Konvergenz,
   so dass auch der langsamste Lauf genuegend physische Retrievals im
   gemeinsamen Fenster hat.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from analyse_rq4_plateau import analysiere  # noqa: E402


def main():
    ordner = Path(sys.argv[1])
    r = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    k = int(sys.argv[3]) if len(sys.argv) > 3 else 2
    delta = float(sys.argv[4]) if len(sys.argv) > 4 else 0.10
    p = int(sys.argv[5]) if len(sys.argv) > 5 else 2

    ergebnisse = []
    for f in sorted(ordner.glob("*.json")):
        if f.name.endswith(".logcount.json"):
            continue
        e = analysiere(f, r, k, delta, p)
        d = json.loads(f.read_text())
        zeiten = [x["t"] for x in d["retrievals"] if x.get("t") is not None]
        e["_zeiten"] = zeiten
        ergebnisse.append(e)

    konvergiert = [e for e in ergebnisse if e["converged"]]
    print(f"Konvergiert: {len(konvergiert)}/{len(ergebnisse)}\n")

    # 1) Konvergenzzeiten je Policy
    je_policy = {}
    for e in konvergiert:
        je_policy.setdefault(e["policy"], []).append(e["convergence_time"])
    print("Konvergenzzeiten je Policy:")
    max_spread = 0
    for policy, zeiten in sorted(je_policy.items()):
        spread = max(zeiten) - min(zeiten)
        max_spread = max(max_spread, spread)
        print(f"  {policy:24s} {sorted(zeiten)}  min={min(zeiten)} "
              f"max={max(zeiten)} spread={spread}")

    langsamste = max(e["convergence_time"] for e in konvergiert)
    print(f"\nlangsamste beobachtete Konvergenz : {langsamste} ZE")
    print(f"groesste Streuung innerhalb Policy : {max_spread} ZE")
    roh = langsamste + max_spread
    print(f"langsamste + Streuung              : {roh} ZE")

    # 2) Post-Convergence-Rate je Lauf
    print("\nRetrievalrate NACH der Konvergenz (bis Laufende):")
    raten = []
    for e in sorted(konvergiert, key=lambda x: (x["policy"], x["seed"])):
        tc = e["convergence_time"]
        nach = [t for t in e["_zeiten"] if t > tc]
        dauer = e["t_end"] - tc
        rate = len(nach) / dauer if dauer > 0 else 0
        raten.append((rate, e["policy"], e["seed"]))
        print(f"  {e['policy']:24s} seed={e['seed']:<3d} t_conv={tc:<6d} "
              f"n={len(nach):<5d} ueber {dauer:<6d} ZE -> {rate:.5f} retr/ZE")

    langsamste_rate, lp, ls = min(raten)
    print(f"\nlangsamste Post-Convergence-Rate: {langsamste_rate:.5f} retr/ZE "
          f"({lp}, seed {ls})")

    # 3) Kandidaten fuer Fensterlaenge
    print("\nFensterlaenge -> Retrievals beim langsamsten Lauf:")
    for fenster in (5000, 8000, 10000, 12000, 15000):
        print(f"  {fenster:6d} ZE -> {langsamste_rate * fenster:6.0f} Retrievals")


if __name__ == "__main__":
    main()
