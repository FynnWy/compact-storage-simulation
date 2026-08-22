"""
Beleg, dass das Scheiben-Verfahren die Trajektorie nicht veraendert -
auch ueber PROZESSGRENZEN hinweg.

Die erste Fassung dieses Skripts hat nur innerhalb eines Prozesses gepickelt
und war deshalb blind fuer den eigentlichen Fehler: `Event._next_event_id`
ist eine Klassenvariable und wird nicht mitgepickelt. In einem neuen Prozess
beginnt der Zaehler wieder bei 0, neue Events sortieren dann vor den bereits
wartenden (`Event.__lt__` nutzt die `event_id` als Tie-Break) und der Lauf
weicht ab. `pilot_state.save_engine/load_engine` sichert den Zaehler mit.

Aufruf:
    verify_resume_identity.py straight <out.json>
    verify_resume_identity.py slice   <state.pkl> <bis_t> <out.json>
    verify_resume_identity.py compare <a.json> <b.json>
"""
import contextlib
import hashlib
import io
import json
import sys
from pathlib import Path

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, str(Path(__file__).resolve().parent))

from simulation.simulation_engine import SimulationEngine  # noqa: E402
from pilot_run import build_config  # noqa: E402
from pilot_state import save_engine, load_engine  # noqa: E402

POLICY, SEED, LIMIT = "ABC+ABC", 42, 900


def fingerprint(engine):
    rows = [
        f"{r.get('t_pickstation')}:{r.get('bin_id')}:{r.get('level')}:"
        f"{r.get('stack_height')}:{r.get('blocking_bins')}"
        for r in engine.metrics.retrievals
    ]
    heights = [f"{s.stack_id}:{s.height()}" for s in engine.state.grid.all_stacks()]
    return {
        "t": engine.state.t,
        "n_retrievals": len(rows),
        "retrieval_hash": hashlib.sha256("|".join(rows).encode()).hexdigest()[:16],
        "layout_hash": hashlib.sha256("|".join(heights).encode()).hexdigest()[:16],
    }


def run_to(engine, bis_t):
    with contextlib.redirect_stdout(io.StringIO()):
        while engine.state.t < bis_t:
            if engine.step() is None:
                return False
    return True


def main():
    mode = sys.argv[1]
    if mode == "straight":
        e = SimulationEngine(build_config(POLICY, SEED, LIMIT))
        with contextlib.redirect_stdout(io.StringIO()):
            while e.step() is not None:
                pass
        Path(sys.argv[2]).write_text(json.dumps(fingerprint(e)))
        print("straight", fingerprint(e))
    elif mode == "slice":
        state_file, bis_t, out = Path(sys.argv[2]), int(sys.argv[3]), Path(sys.argv[4])
        if state_file.exists():
            e = load_engine(state_file)
        else:
            e = SimulationEngine(build_config(POLICY, SEED, LIMIT))
        if bis_t <= 0:
            with contextlib.redirect_stdout(io.StringIO()):
                while e.step() is not None:
                    pass
        else:
            run_to(e, bis_t)
        save_engine(state_file, e)
        out.write_text(json.dumps(fingerprint(e)))
        print("slice bis", bis_t, fingerprint(e))
    elif mode == "compare":
        a = json.loads(Path(sys.argv[2]).read_text())
        b = json.loads(Path(sys.argv[3]).read_text())
        print("straight:", a)
        print("sliced  :", b)
        print("VERDICT :", "IDENTISCH" if a == b else "ABWEICHUNG")
    else:
        raise SystemExit("unbekannter Modus")


if __name__ == "__main__":
    main()
