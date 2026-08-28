"""
Prueft den festgefahrenen Endzustand eines Pilotlaufs gegen alle
Audit-Invarianten und beschreibt die Warte-Struktur.

Frage: ist der Stillstand ein Correctness-Fehler (kaputter Zustand) oder ein
gueltiger, aber blockierter Zustand (echter Deadlock)?
"""
import sys
from collections import Counter

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')
sys.setrecursionlimit(200000)

from pilot_state import load_engine  # noqa: E402

from tests.audit_harness import (AuditResult, check_bin_invariants,  # noqa: E402
                                 check_robot_invariants, check_task_invariants,
                                 check_pickstation_invariants,
                                 check_reservation_invariants, check_wait_graph)

e = load_engine(sys.argv[1])

res = AuditResult("deadlock_state", {})
for check in (check_bin_invariants, check_robot_invariants, check_task_invariants,
              check_pickstation_invariants, check_reservation_invariants,
              check_wait_graph):
    try:
        check(e, res)
    except Exception as exc:
        res.add(e.state.t, "CHECK_FAILED", f"{check.__name__}: {exc}")

print(f"t={e.state.t}  retrievals={len(e.metrics.retrievals)}  "
      f"letztes Retrieval t={e.metrics.retrievals[-1]['t_pickstation']}")
print(f"Invariantenverletzungen: {len(res.violations)}  {dict(res.violation_kinds)}")
for v in res.violations[:12]:
    print("   ", v)

st = e.state
print("\nRoboter / Tasks:")
phasen = Counter()
for r in st.robots:
    t = getattr(r, "current_task", None)
    phasen[getattr(t, "phase", None)] += 1
    blocker = getattr(t, "temp_storage", None)
    restore = getattr(t, "relocations", None) or getattr(t, "blocker_relocations", None)
    print(f"  robot {r.robot_id}: phase={getattr(t, 'phase', None)} "
          f"target_bin={getattr(t, 'target_bin_id', None)} "
          f"target_stack={getattr(t, 'target_stack_id', None)} "
          f"target_at_pickstation={getattr(t, 'target_at_pickstation', None)} "
          f"pickstation_completed={getattr(t, 'pickstation_completed', None)} "
          f"temp_storage={len(blocker) if blocker is not None else None} "
          f"restore_offen={len(restore) if restore is not None else None}")
print(" Phasen:", dict(phasen))

print("\nEvent-Queue:")
eq = st.event_queue
for attr in ("queue", "_queue", "events", "_events", "heap", "_heap"):
    v = getattr(eq, attr, None)
    if v is not None:
        try:
            print(f"  {attr}: len={len(v)}  naechste={list(v)[:5]}")
        except Exception as exc:
            print(f"  {attr}: {exc}")
        break

print("\nOwnership / reservierte Bins:")
aq = getattr(e, "active_queue", None)
for name in dir(aq):
    if name.startswith("get_all") or name in ("reserved_bins", "owned_bins"):
        try:
            val = getattr(aq, name)
            val = val() if callable(val) else val
            print(f"  {name}: {len(val) if hasattr(val, '__len__') else val}")
        except Exception:
            pass
