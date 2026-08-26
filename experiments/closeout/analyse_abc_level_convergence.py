"""
Raeumliche RQ4-Konvergenz auf der (ABC-Klasse, Tiefe)-Verteilung.

Signal
------
`abc_level_<Klasse>_<Tiefe>` aus den Distribution-Snapshots: der Anteil aller
gelagerten Bins je Kombination aus statischer ABC-Klasse und Tiefe unter der
Stapeloberkante. 24 Komponenten bei H=8, Summe 1.

Warum diese Groesse: Meller fragt, wie lange es dauert, bis sich eine
willkuerlich befuellte Anlage auf eine stabile Bin-Verteilung einschwingt,
und ob Schnelldreher tatsaechlich oben liegen. Die ABC-Klasse ist statisch
ueber die `bin_id` definiert, fuer alle Policies identisch berechenbar und
bildet unter Zipf=1.0 die Nachfrage ab (gemessen: 80,8 % der Requests auf die
A-Klasse). Die Tiefe von oben ist die Groesse, ueber die Meller spricht.

Regel
-----
    Block          = W aufeinanderfolgende Snapshots, Mittelwert je Komponente
    Abstand        = Total Variation Distance zwischen aufeinanderfolgenden
                     Bloecken:  TVD(p,q) = 0.5 * sum_i |p_i - q_i|
    Konvergenz     = K aufeinanderfolgende Blockpaare mit TVD <= theta
    Persistenz     = danach kein sofortiges Zurueckspringen ueber
                     `redivergence_factor * theta`

Der Persistenzteil ist Absicht: die alte beta-Regel loeste einmal kurz aus
und sprang sofort zurueck. Ein einzelner Unterschreiter ist kein Steady
State.
"""
import json
import statistics as st
import sys
from pathlib import Path


def komponenten(snapshot):
    return {k: v for k, v in snapshot.items() if k.startswith("abc_level_")}


def blockmittel(snapshots, start, w):
    teile = snapshots[start:start + w]
    if len(teile) < w:
        return None
    keys = sorted(komponenten(teile[0]))
    return {k: st.mean(s.get(k, 0.0) for s in teile) for k in keys}


def tvd(p, q):
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0.0) - q.get(k, 0.0)) for k in keys)


def blockfolge(snapshots, w):
    """Liste (block_index, end_time, mittelwert) — Bloecke fester ZEIT."""
    blocks = []
    i = 0
    while i + w <= len(snapshots):
        mittel = blockmittel(snapshots, i, w)
        blocks.append((len(blocks), snapshots[i + w - 1]["time"], mittel))
        i += w
    return blocks


def blockfolge_retrievals(snapshots, retrievals, r_pro_block):
    """
    Bloecke fester RETRIEVAL-Zahl statt fester Zeit.

    Warum: Die raeumliche Verteilung aendert sich durch Retrievals, nicht
    durch Zeit. Bei Zeitbloecken misst eine schnelle Policy zwangslaeufig
    groessere Abstaende als eine langsame — LR+NR bewegt rund 55 Bins je
    1000 ZE, ABC+ABC rund 22. Ein gemeinsamer Zeitschwellenwert wuerde die
    schnelle Policy systematisch als „nicht konvergiert" markieren, obwohl
    sie nur mehr Arbeit je Zeiteinheit leistet.

    Bloecke gleicher Retrieval-Zahl vergleichen dagegen gleich viel
    Umlagerungsarbeit und sind damit policyunabhaengig lesbar.
    """
    zeiten = sorted(r["t"] for r in retrievals if r.get("t") is not None)

    def bis(t):
        lo, hi = 0, len(zeiten)
        while lo < hi:
            mid = (lo + hi) // 2
            if zeiten[mid] <= t:
                lo = mid + 1
            else:
                hi = mid
        return lo

    blocks = []
    start = 0
    naechste_grenze = r_pro_block
    for idx, snap in enumerate(snapshots):
        if bis(snap["time"]) >= naechste_grenze:
            teile = snapshots[start:idx + 1]
            if teile:
                keys = sorted(komponenten(teile[0]))
                mittel = {k: st.mean(s.get(k, 0.0) for s in teile) for k in keys}
                blocks.append((len(blocks), snap["time"], mittel))
            start = idx + 1
            naechste_grenze += r_pro_block
    return blocks


def analyse(snapshots, retrievals, w, theta, k, redivergence_factor=2.0,
            modus="retrievals"):
    if modus == "retrievals":
        blocks = blockfolge_retrievals(snapshots, retrievals, w)
    else:
        blocks = blockfolge(snapshots, w)
    abstaende = []
    for i in range(1, len(blocks)):
        abstaende.append((blocks[i][1], tvd(blocks[i - 1][2], blocks[i][2])))

    treffer = 0
    konvergenz_zeit = None
    konvergenz_index = None
    for idx, (zeit, d) in enumerate(abstaende):
        if d <= theta:
            treffer += 1
            if treffer >= k and konvergenz_zeit is None:
                konvergenz_zeit = zeit
                konvergenz_index = idx
        else:
            treffer = 0

    persistent = None
    if konvergenz_index is not None:
        spaeter = [d for _, d in abstaende[konvergenz_index + 1:]]
        persistent = all(d <= redivergence_factor * theta for d in spaeter)

    ergebnis = {
        "window_snapshots": w,
        "theta": theta,
        "required_pairs": k,
        "block_count": len(blocks),
        "distances": [(z, round(d, 5)) for z, d in abstaende],
        "converged": konvergenz_zeit is not None and bool(persistent),
        "convergence_time": konvergenz_zeit if persistent else None,
        "persistent": persistent,
    }
    if ergebnis["converged"]:
        ergebnis["convergence_retrievals"] = sum(
            1 for r in retrievals if r.get("t") is not None
            and r["t"] <= konvergenz_zeit
        )
    return ergebnis


def rauschboden(abstaende, anteil=0.5):
    """Median der TVD in der SPAETEN Haelfte der Zeitreihe."""
    if not abstaende:
        return None
    spaet = [d for _, d in abstaende[int(len(abstaende) * anteil):]]
    return st.median(spaet) if spaet else None


def main():
    ordner = Path(sys.argv[1])
    w = int(sys.argv[2]) if len(sys.argv) > 2 else 50
    theta = float(sys.argv[3]) if len(sys.argv) > 3 else 0.01
    k = int(sys.argv[4]) if len(sys.argv) > 4 else 3
    modus = sys.argv[5] if len(sys.argv) > 5 else "retrievals"

    einheit = "Retrievals" if modus == "retrievals" else f"Snapshots ({w*100} ZE)"
    print(f"Block = {w} {einheit}, theta = {theta}, "
          f"K = {k} stabile Paare\n")
    for f in sorted(ordner.glob("*.json")):
        if f.name.endswith(".logcount.json"):
            continue
        d = json.loads(f.read_text())
        snaps = [s for s in d.get("distribution", [])
                 if any(kk.startswith("abc_level_") for kk in s)]
        if len(snaps) < 4:
            print(f"{d['policy']:24s} seed={d['seed']:<3d} zu kurz "
                  f"({len(snaps)} Snapshots)")
            continue
        res = analyse(snaps, d["retrievals"], w, theta, k, modus=modus)
        boden = rauschboden(res["distances"])
        print(f"{d['policy']:24s} seed={d['seed']:<3d} "
              f"t_end={d['t_end']:<6d} Bloecke={res['block_count']:<3d} "
              f"Rauschboden={boden:.5f} "
              f"konvergiert={res['converged']} "
              f"t_conv={res['convergence_time']} "
              f"retr_conv={res.get('convergence_retrievals')}")
        print(f"    TVD-Folge: {[d2 for _, d2 in res['distances']]}")


if __name__ == "__main__":
    main()
