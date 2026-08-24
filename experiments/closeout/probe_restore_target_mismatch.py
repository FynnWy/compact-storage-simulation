"""
Diagnose fuer
`Cannot mark relocation restored for bin X: expected to_stack A, got B`.

Protokolliert fuer eine bestimmte Bin jede Aenderung ihres
Rueckgabeziels und jede geplante bzw. ausgefuehrte Rueckgabe-Aktion.
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, '/sessions/youthful-busy-noether/work')

from simulation.robot_task import RobotTask  # noqa: E402
from simulation.simulation_engine import SimulationEngine  # noqa: E402
from strategies.top_access_strategy import TopAccessStrategy  # noqa: E402
from pilot_run import build_config  # noqa: E402

policy = sys.argv[1]
seed = int(sys.argv[2])
beobachtet = int(sys.argv[3]) if len(sys.argv) > 3 else None

engine = SimulationEngine(build_config(policy, seed, 40000))
log = []

orig_update = RobotTask.update_return_stack_for_blocker
orig_restore = RobotTask.mark_last_relocation_restored
orig_next = TopAccessStrategy._next_restore_blockers_action


def update(self, bin_id, new_to_stack):
    if beobachtet is None or bin_id == beobachtet:
        alt = next((r for r in self.temp_storage if r["bin_id"] == bin_id), None)
        log.append((engine.state.t, "UPDATE_ZIEL", bin_id,
                    alt.get("from_stack") if alt else None, new_to_stack,
                    self.request_id))
    return orig_update(self, bin_id, new_to_stack)


def restore(self, bin_id, from_stack, to_stack):
    if beobachtet is None or bin_id == beobachtet:
        eintrag = next((r for r in self.temp_storage if r["bin_id"] == bin_id), None)
        log.append((engine.state.t, "RESTORE", bin_id,
                    eintrag.get("from_stack") if eintrag else None, to_stack,
                    self.request_id))
    return orig_restore(self, bin_id, from_stack, to_stack)


def naechste(self, state, task):
    aktion = orig_next(self, state, task)
    if (aktion and aktion.get("return_kind") == "blocker"
            and (beobachtet is None or aktion.get("bin_id") == beobachtet)):
        log.append((state.t, "PLAN", aktion.get("bin_id"),
                    None, aktion.get("to_stack"), task.request_id))
    return aktion


RobotTask.update_return_stack_for_blocker = update
RobotTask.mark_last_relocation_restored = restore
TopAccessStrategy._next_restore_blockers_action = naechste

fehler = None
with contextlib.redirect_stdout(io.StringIO()):
    try:
        while engine.step() is not None:
            pass
    except Exception as exc:
        fehler = f"{type(exc).__name__}: {exc}"

RobotTask.update_return_stack_for_blocker = orig_update
RobotTask.mark_last_relocation_restored = orig_restore
TopAccessStrategy._next_restore_blockers_action = orig_next

print(f"{policy}/{seed}  t_end={engine.state.t}  fehler={fehler}")
print(f"\nEreignisse fuer bin={beobachtet} (letzte 30):")
for t, art, bin_id, eintrag_ziel, aktion_ziel, req in log[-30:]:
    print(f"  t={t:6d} {art:12s} bin={bin_id} eintrag_from_stack={eintrag_ziel} "
          f"aktion_to_stack={aktion_ziel} request={req}")
