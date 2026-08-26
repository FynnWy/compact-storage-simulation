"""
Auswertung der Pilot-Spuren gegen die Steady-State-/Stop-Regel.

Die Regel wird OFFLINE auf der vollstaendigen Retrieval-Spur angewandt,
dadurch laesst sich dieselbe Messung gegen mehrere Kandidaten-Obergrenzen
pruefen, ohne neu zu rechnen.

Erfasst je Lauf:
    convergence yes/no, convergence_time (ZE), convergence_retrievals,
    beta-Blockmittel, ZE fuer das anschliessende Measurement Window,
    Reserve bis zu den Kandidatengrenzen.

Zusaetzlich: beta-Konvergenzpunkt gegen die raeumliche Stabilitaet
(`hot_bins_top_ratio`, Level-/Stackhoehen-Verteilung) aus den
Distribution-Snapshots.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
from metrics.steady_state import SteadyStateDetector  # noqa: E402

BLOCK = 50
THRESHOLD = 0.10
PAIRS = 2
WINDOW = 100
CANDIDATES = (20000, 25000, 30000)


def analyse(rows, window=WINDOW):
    det = SteadyStateDetector(BLOCK, THRESHOLD, PAIRS)
    for r in rows:
        det.observe(r["blocking_bins"], r["t"])
    s = det.summary()
    out = {
        "converged": s["converged"],
        "convergence_time": s["convergence_time"],
        "convergence_retrievals": s["convergence_retrievals"],
        "block_means": [round(m, 3) for m in s["block_means"]],
        "relative_changes": [round(c, 3) for c in s["relative_changes"]],
        "blocks": s["blocks_completed"],
        "n": len(rows),
    }
    if s["converged"]:
        start = s["convergence_retrievals"]
        win = rows[start:start + window]
        out["window_retrievals"] = len(win)
        out["window_complete"] = len(win) >= window
        if win:
            out["window_start_t"] = win[0]["t"]
            out["window_end_t"] = win[-1]["t"]
            out["window_ze"] = win[-1]["t"] - win[0]["t"]
            out["total_ze_needed"] = win[-1]["t"]
            out["window_mean_beta"] = round(
                sum(r["blocking_bins"] for r in win) / len(win), 3)
    return out


def spatial(snapshots, t_conv, t_end):
    """Raeumliche Stabilitaet um den beta-Konvergenzpunkt."""
    def at(t):
        best = None
        for s in snapshots:
            if s.get("time") is not None and s["time"] <= t:
                best = s
        return best

    def levels(s):
        """Relative Haeufigkeit der Stackhoehen (0..H) als Verteilung."""
        d = (s or {}).get("stack_height_distribution") or {}
        heights = d.get("heights") if isinstance(d, dict) else None
        if heights is None:
            return {}
        counts = {}
        for h in heights:
            counts[str(h)] = counts.get(str(h), 0) + 1
        total = len(heights) or 1
        return {k: v / total for k, v in counts.items()}

    def tvd(a, b):
        keys = set(a) | set(b)
        return round(0.5 * sum(abs(a.get(k, 0) - b.get(k, 0)) for k in keys), 4)

    s_conv, s_end = at(t_conv), at(t_end)
    if not s_conv or not s_end:
        return None
    mid = at((t_conv + t_end) / 2)
    return {
        "t_conv": s_conv.get("time"),
        "t_end": s_end.get("time"),
        "hot_ratio_conv": round(s_conv.get("hot_bins_top_ratio") or 0, 4),
        "hot_ratio_mid": round((mid or {}).get("hot_bins_top_ratio") or 0, 4),
        "hot_ratio_end": round(s_end.get("hot_bins_top_ratio") or 0, 4),
        "hot_ratio_rel_change": (
            round(abs((s_end.get("hot_bins_top_ratio") or 0)
                      - (s_conv.get("hot_bins_top_ratio") or 0))
                  / max(s_conv.get("hot_bins_top_ratio") or 1e-9, 1e-9), 4)),
        "levels_tvd_conv_to_end": tvd(levels(s_conv), levels(s_end)),
        "height_var_conv": round(s_conv.get("stack_height_variance") or 0, 4),
        "height_var_end": round(s_end.get("stack_height_variance") or 0, 4),
        "entropy_conv": round(s_conv.get("bin_distribution_entropy") or 0, 4),
        "entropy_end": round(s_end.get("bin_distribution_entropy") or 0, 4),
    }


def main():
    out_dir = Path(sys.argv[1])
    for f in sorted(out_dir.glob("*.json")):
        if f.name.endswith(".logcount.json"):
            continue
        d = json.loads(f.read_text())
        rows = [r for r in d["retrievals"] if r["t"] is not None]
        res = analyse(rows)
        ts = [r["t"] for r in rows]
        stall = d["t_end"] - (ts[-1] if ts else 0)
        print(f"\n=== {d['policy']}  seed={d['seed']} ===")
        print(f"  t_end={d['t_end']}  retrievals={len(rows)}  "
              f"stall_since_last_retrieval={stall} ZE  "
              f"finished={d['finished']} ({d.get('stop_reason')})"
              + (f"  ERROR={d['error']}" if d.get("error") else ""))
        print(f"  beta Blockmittel: {res['block_means']}")
        print(f"  rel. Aenderungen: {res['relative_changes']}")
        if res["converged"]:
            print(f"  KONVERGIERT nach {res['convergence_retrievals']} Retrievals "
                  f"= {res['convergence_time']} ZE")
            if "total_ze_needed" in res:
                print(f"  Measurement Window {res['window_retrievals']}/{WINDOW} "
                      f"Retrievals, {res['window_ze']} ZE, "
                      f"beta_window={res['window_mean_beta']}, "
                      f"Gesamt bis Fensterende: {res['total_ze_needed']} ZE")
                for cand in CANDIDATES:
                    print(f"     Reserve bis {cand} ZE: "
                          f"{cand - res['total_ze_needed']} ZE "
                          f"({'OK' if res['total_ze_needed'] <= cand else 'REICHT NICHT'})")
            else:
                print(f"  Measurement Window: 0/{WINDOW} Retrievals erreicht")
            sp = spatial(d.get("distribution") or [], res["convergence_time"], d["t_end"])
            if sp:
                print(f"  raeumlich: hot_bins_top_ratio {sp['hot_ratio_conv']} "
                      f"-> {sp['hot_ratio_mid']} -> {sp['hot_ratio_end']} "
                      f"(rel. Aenderung {sp['hot_ratio_rel_change']})")
                print(f"             Level-Verteilung TVD(konv->Ende) = "
                      f"{sp['levels_tvd_conv_to_end']}, "
                      f"Hoehenvarianz {sp['height_var_conv']} -> {sp['height_var_end']}, "
                      f"Entropie {sp['entropy_conv']} -> {sp['entropy_end']}")
        else:
            print(f"  NICHT konvergiert ({res['blocks']} Bloecke gerechnet)")


if __name__ == "__main__":
    main()
