"""
Beweis des Entstehungswegs fuer
`Cannot complete request 394: target was not removed`.

Hypothese
---------
Der Stale-Schutz im DROP-Pfad identifiziert eine Target-Ruecklagerung ueber
die BIN, nicht ueber den Request:

    foreign_target = (... and robot.current_task.target_bin_id != bin_id)

Zielen zwei Requests auf dieselbe Bin - bei einer A-Klasse-Bin der Normalfall,
fuer Bin 0 standen zuletzt 22 Requests in der Batch-Warteliste - dann stimmt
`target_bin_id` ueberein, obwohl die Aktion zu einem ANDEREN Task gehoert.
Der Guard greift nicht, und `_update_task_after_successful_return` schreibt
`mark_target_returned()` auf den falschen Task.

Der Pickup-Pfad prueft an derselben Stelle ueber die `request_id` und ist
deshalb nicht betroffen.

Aufbau
------
Ein Roboter fuehrt einen Target-Return fuer Bin B aus, waehrend ihm
zwischenzeitlich ein Task eines ZWEITEN Requests auf dieselbe Bin B zugeteilt
wurde. Genau das passiert im langen Lauf zwischen Planung und Ausfuehrung des
Drops.
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')

from config.simulation_config import SimulationConfig  # noqa: E402
from events.event_types import EventType  # noqa: E402
from requests_.request import Request  # noqa: E402
from simulation.robot_task import RobotTask  # noqa: E402
from simulation.simulation_engine import SimulationEngine  # noqa: E402


def build():
    c = SimulationConfig()
    c.grid_width, c.grid_depth, c.max_stack_height = 7, 7, 6
    c.bin_num, c.num_robots, c.num_pickstations = 100, 2, 2
    c.simulation_time, c.random_seed = 400, 42
    c.request_utilization, c.enable_visualization = 0.5, False
    c.reordering_strategy, c.placement_strategy = "ABC", "ABC"
    c.return_blocking_bins = True
    return SimulationEngine(c)


def task_for(request_id, bin_id):
    return RobotTask(Request(
        request_id=request_id, event_type=EventType.ARRIVAL, bin_id=bin_id,
        t_arrival=0, t_earliest=0, t_latest=1000,
    ))


def main():
    engine = build()
    handler = engine.event_handler
    st = engine.state
    robot = st.robots[0]

    # Bin B liegt an der Pickstation und wird gleich zurueckgelegt.
    quelle = next(s for s in st.grid.all_stacks() if s.height() > 0)
    bin_obj = quelle.pop()
    handler._sync_stack_bin_metadata(quelle)
    bin_obj.set_stack(None)
    bin_obj.set_level(None)
    bin_obj.set_status("at_pickstation")
    bin_obj.mark_in_transit()
    robot.set_carried_bin(bin_obj.bin_id)

    ziel = next(s for s in st.grid.all_stacks()
                if s.height() < engine.config.max_stack_height
                and st.is_valid_storage_position(
                    *[int(x) for x in s.stack_id.split("_")[1:]]))
    robot.set_position(tuple(int(x) for x in ziel.stack_id.split("_")[1:]))

    # Task A hat den Retrieval tatsaechlich geleistet.
    task_a = task_for(500, bin_obj.bin_id)
    task_a.target_stack_id = quelle.stack_id
    task_a.mark_waiting_at_pickstation()
    task_a.mark_pickstation_completed()
    task_a.phase = RobotTask.PHASE_RETURN_TARGET

    aktion = {
        "type": "return",
        "return_kind": "target",
        "from_stack": None,
        "to_stack": ziel.stack_id,
        "bin_id": bin_obj.bin_id,
    }
    drop_event = handler.event_builder.build_robot_drop_event(
        robot=robot, action=aktion, request=task_a.request, time=st.t
    )

    # Zwischenzeitlich bekommt der Roboter Task B - anderer Request, GLEICHE Bin.
    task_b = task_for(394, bin_obj.bin_id)
    robot.assign_task(task_b)

    print(f"vor dem Drop:  task_b removed={task_b.target_removed} "
          f"at_ps={task_b.target_at_pickstation} "
          f"ps_done={task_b.pickstation_completed} "
          f"returned={task_b.target_returned} phase={task_b.phase}")

    with contextlib.redirect_stdout(io.StringIO()) as log:
        handler._handle_robot_drop(drop_event)

    print(f"nach dem Drop: task_b removed={task_b.target_removed} "
          f"at_ps={task_b.target_at_pickstation} "
          f"ps_done={task_b.pickstation_completed} "
          f"returned={task_b.target_returned} phase={task_b.phase}")
    for zeile in log.getvalue().splitlines():
        if "STALE" in zeile or "TRACE" in zeile:
            print("   log:", zeile[:140])

    kaputt = task_b.target_returned and not task_b.target_removed
    print()
    if kaputt:
        print("REPRODUZIERT: fremder Target-Return hat Task B als 'returned' "
              "markiert, obwohl er nie etwas ausgelagert hat.")
        try:
            task_b.complete(st) if hasattr(task_b, "complete") else None
        except Exception as exc:
            print("  Folgefehler:", exc)
        ok, grund = task_b.can_complete_consistently(st)
        print(f"  can_complete_consistently -> {ok}, {grund}")
    else:
        print("NICHT reproduziert - der Guard hat gegriffen.")


if __name__ == "__main__":
    main()
