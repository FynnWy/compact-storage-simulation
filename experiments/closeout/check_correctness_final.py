"""
Physische Correctness-Checks auf der finalen Konfiguration.

Nutzt den bestehenden Audit-Harness (`tests/audit_harness.run_audit`), der die
Simulation Schritt fuer Schritt mit Invariantenpruefungen faehrt:
ungueltige Pickups/Drops/Moves, Kollisionen, Bin-Verlust, Duplikate,
Ownership-Verletzungen, Cross-Station-Fehler, Reservierungen, Wait-Graph.
"""
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')

from tests.audit_harness import run_audit  # noqa: E402
from pilot_run import build_config  # noqa: E402

policy = sys.argv[1]
seed = int(sys.argv[2])
sim_time = int(sys.argv[3])

config = build_config(policy, seed, sim_time)
result = run_audit(config, label=f"{policy}/seed{seed}/{sim_time}ZE")

print(f"=== {policy} seed={seed} bis {sim_time} ZE ===")
print(f"  t_end={result.t_end} steps={result.steps} wall={result.wall_seconds}s "
      f"error={result.error}")
print(f"  invalid_pickups={result.physically_invalid_pickups} "
      f"invalid_drops={result.physically_invalid_drops} "
      f"invalid_moves={result.invalid_moves} "
      f"collisions={result.robot_position_collisions}")
print(f"  violations={len(result.violations)} kinds={dict(result.violation_kinds)}")
print(f"  deadlock_detections={result.deadlock_detections} "
      f"recoveries={result.deadlock_recoveries} evades={result.evades}")
print(f"  max_no_progress_window={result.max_no_progress_window} "
      f"progress_events={result.progress_events}")
print(f"  retrievals={len(getattr(result, 'summary', {}) and [])} "
      f"summary_keys={sorted(result.summary.keys())[:6]}")
for v in result.violations[:10]:
    print("   VIOLATION", v)
