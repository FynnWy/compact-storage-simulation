"""
CRN-Nachweis auf der FINALEN Konfiguration (20x30, H=8, 4320 Bins,
2 Pickstations, 8 Roboter, Zipf 1.0, util 0.6, EDF, Deadline arrival+240).

Geprueft wird, dass bei gleichem Seed ueber alle fuenf Konfigurationen
identisch sind:
    * das initiale Layout (und dass es die Storage-Eligibility erfuellt),
    * der Request-Strom (Ankunftszeit, Bin, Deadline),
    * die exogenen Pickstation-Servicezeiten je Request.

Es wird nur initialisiert, nicht simuliert - alle exogenen Groessen werden
vor Simulationsbeginn gezogen.
"""
import hashlib
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')

from simulation.simulation_engine import SimulationEngine  # noqa: E402
from pilot_run import build_config, POLICIES  # noqa: E402

SEEDS = [1, 2, 3, 4, 7, 11, 13, 42, 99, 123]


def layout_hash(engine):
    parts = []
    for b in sorted(engine.state.bins, key=lambda b: b.bin_id):
        parts.append(f"{b.bin_id}:{b.stack_id}:{b.get_level()}")
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16]


def _requests(engine):
    return [r for _, r in engine.state.future_request_queue.queue]


def requests_hash(engine):
    parts = [f"{r.request_id}:{r.target_box_id}:{r.arrival_time}:{r.latest_time}"
             for r in sorted(_requests(engine), key=lambda r: r.request_id)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], len(parts)


def service_hash(engine):
    parts = [f"{r.request_id}:{r.service_time}"
             for r in sorted(_requests(engine), key=lambda r: r.request_id)]
    return hashlib.sha256("|".join(parts).encode()).hexdigest()[:16], len(parts)


def eligibility_violations(engine):
    st = engine.state
    return sum(1 for b in st.bins
               if b.stack_id is not None
               and not st.is_valid_storage_position(*b.stack_id))


ok = True
for seed in SEEDS:
    rows = []
    for policy in POLICIES:
        e = SimulationEngine(build_config(policy, seed, 2000))
        rh, rn = requests_hash(e)
        sh, sn = service_hash(e)
        rows.append((policy, layout_hash(e), rh, rn, sh, sn,
                     eligibility_violations(e)))
    base = rows[0]
    gleich = all(r[1:6] == base[1:6] for r in rows)
    verletzungen = sum(r[6] for r in rows)
    ok = ok and gleich and verletzungen == 0
    print(f"seed={seed:>3d}  layout={base[1]}  requests={base[2]} (n={base[3]})  "
          f"service={base[4]} (n={base[5]})  "
          f"identisch={'JA' if gleich else 'NEIN'}  "
          f"eligibility_violations={verletzungen}")

print("\nVERDICT:", "CRN INTAKT" if ok else "CRN VERLETZT")
