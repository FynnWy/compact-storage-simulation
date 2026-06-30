# tests/test_workflow_integration.py
"""
Integrationstests für komplette Workflows.

Testet:
- Einzelner Request-Zyklus (Arrival → Retrieval → Pickstation → Return → Complete)
- Bin-Konsistenz (keine Bins verloren)
- Task-Phasen-Übergänge
"""
import pytest
from simulation.simulation_engine import SimulationEngine
from events.event_types import EventType


class TestSingleRequestWorkflow:
    """Kompletter Workflow für einen einzelnen Request."""

    def test_single_request_completes(self, small_config):
        """Ein einzelner Request muss vollständig abgeschlossen werden."""
        engine = SimulationEngine(small_config)

        events_processed = 0
        max_events = 500

        while events_processed < max_events:
            event = engine.step()
            if event is None:
                break
            events_processed += 1

        # Mindestens ein Request sollte abgeschlossen sein
        summary = engine.metrics.summary()
        assert summary.get("requests_completed", 0) >= 1

    def test_events_in_correct_order(self, small_config):
        """Events müssen in zeitlich korrekter Reihenfolge auftreten."""
        engine = SimulationEngine(small_config)

        last_time = -1

        for _ in range(300):
            event = engine.step()
            if event is None:
                break

            # Zeit darf nicht rückwärts laufen
            current_time = engine.state.t
            assert current_time >= last_time, f"Time went backwards: {last_time} -> {current_time}"
            last_time = current_time


class TestBinConsistency:
    """Bin-Konsistenz über die gesamte Simulation."""

    def test_no_bins_lost(self, medium_config):
        """Keine Bins dürfen verloren gehen."""
        engine = SimulationEngine(medium_config)

        initial_bin_count = len(engine.state.bins)

        for _ in range(500):
            event = engine.step()
            if event is None:
                break

            # Nach jedem Event: Prüfe Bin-Konsistenz
            bins_in_stacks = sum(
                stack.height() for stack in engine.state.grid.all_stacks()
            )
            bins_at_pickstation = sum(
                1 for b in engine.state.bins if b.get_status() == "at_pickstation"
            )

            total_visible = bins_in_stacks + bins_at_pickstation

            assert total_visible == initial_bin_count, (
                f"Bins lost! Expected {initial_bin_count}, found {total_visible} "
                f"(stacks: {bins_in_stacks}, pickstation: {bins_at_pickstation})"
            )

    def test_no_duplicate_bins(self, medium_config):
        """Keine Bin darf doppelt existieren."""
        engine = SimulationEngine(medium_config)

        for _ in range(500):
            event = engine.step()
            if event is None:
                break

            # Sammle alle sichtbaren Bin-IDs
            bin_ids = []

            for stack in engine.state.grid.all_stacks():
                for bin_obj in stack.bins:
                    bin_ids.append(bin_obj.bin_id)

            for bin_obj in engine.state.bins:
                if bin_obj.get_status() == "at_pickstation":
                    bin_ids.append(bin_obj.bin_id)

            # Keine Duplikate
            duplicates = [bid for bid in set(bin_ids) if bin_ids.count(bid) > 1]
            assert not duplicates, f"Duplicate bins found: {duplicates}"


class TestBlockerHandling:
    """Blocker-Bin Handling."""

    def test_blockers_tracked_correctly(self, small_config):
        """Blocker-Bins müssen korrekt in temp_storage erfasst werden."""
        engine = SimulationEngine(small_config)

        for _ in range(300):
            event = engine.step()
            if event is None:
                break

            # Nach jedem ROBOT_ACTION prüfen
            if hasattr(event, 'event_type') and event.event_type == EventType.ROBOT_ACTION:
                for robot in engine.state.robots:
                    task = robot.current_task
                    if task is not None:
                        # temp_storage sollte nur gültige Einträge haben
                        for reloc in task.temp_storage:
                            assert "bin_id" in reloc
                            assert "from_stack" in reloc
                            assert "buffer_stack" in reloc


class TestStackCapacity:
    """Stack-Kapazitätsgrenzen."""

    def test_no_stack_overflow(self, medium_config):
        """Kein Stack darf max_stack_height überschreiten."""
        engine = SimulationEngine(medium_config)

        max_height = medium_config.max_stack_height

        for _ in range(500):
            event = engine.step()
            if event is None:
                break

            for stack in engine.state.grid.all_stacks():
                assert stack.height() <= max_height, (
                    f"Stack {stack.stack_id} overflow: "
                    f"{stack.height()} > {max_height}"
                )

class TestEventFlowSanity:
    """
    Einfache sanity-checks für Event-Fluss:

    - Mindestens ein ARRIVAL-Event sollte auftreten.
    - Mindestens ein PICKSTATION_COMPLETE-Event sollte auftreten
      (d.h. mindestens ein Task erreicht eine Pickstation).
    - REQUEST_COMPLETE-Events können, müssen aber aktuell noch
      nicht zahlreich sein – wir prüfen nur, ob überhaupt einer auftritt.
    """

    def test_at_least_one_arrival_occurs(self, small_config):
        engine = SimulationEngine(small_config)

        seen_arrival = False

        for _ in range(500):
            event = engine.step()
            if event is None:
                break
            if event.event_type == EventType.ARRIVAL:
                seen_arrival = True
                break

        assert seen_arrival is True, "No ARRIVAL event observed in simulation"

    def test_pickstation_complete_occurs(self, small_config):
        """
        Mindestens ein PICKSTATION_COMPLETE-Event sollte in einer
        nicht-trivialen Simulation auftreten, sonst kommen Requests
        nie an der Pickstation an.
        """
        engine = SimulationEngine(small_config)

        seen_ps_complete = False

        for _ in range(1000):
            event = engine.step()
            if event is None:
                break
            if event.event_type == EventType.PICKSTATION_COMPLETE:
                seen_ps_complete = True
                break

        assert seen_ps_complete is True, (
            "No PICKSTATION_COMPLETE event observed; "
            "requests may never reach a pickstation"
        )

    def test_request_complete_event_occurs(self, medium_config):
        """
        Prüft, ob zumindest ein REQUEST_COMPLETE-Event erzeugt wird.
        Die metrische Zählung (requests_completed) kann separat betrachtet
        werden; hier geht es nur um den Event-Fluss.
        """
        engine = SimulationEngine(medium_config)

        seen_request_complete = False

        while True:
            event = engine.step()
            if event is None:
                break
            if event.event_type == EventType.REQUEST_COMPLETE:
                seen_request_complete = True
                break

        assert seen_request_complete is True, (
            "No REQUEST_COMPLETE event observed; "
            "tasks may never be fully finalized in the event flow"
        )