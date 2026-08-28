"""
Face Validity fuer einen Zyklus mit MEHREREN Blockern.

Der erste Zyklus eines Laufs hat oft nur einen Blocker — dort ist die
Reihenfolge des Ordered Return nicht sichtbar. Dieses Skript sucht den ersten
Zyklus mit mindestens N Blockern und protokolliert die Rueckgabereihenfolge
samt Klasse bzw. access_count, damit ein Mensch die Policy-Wirkung direkt
ablesen kann.
"""
import contextlib
import io
import sys

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')
sys.path.insert(0, str(__file__).rsplit("/", 1)[0])

from face_validity import build, POLICIES  # noqa: E402


def trace(policy, min_blockers=3, sim_time=3000):
    engine = build(policy, sim_time=sim_time)
    beobachtet = None
    protokoll = []

    with contextlib.redirect_stdout(io.StringIO()):
        while engine.step() is not None:
            for r in engine.state.robots:
                task = getattr(r, "current_task", None)
                if task is None:
                    continue
                if (beobachtet is None
                        and len(task.temp_storage or []) >= min_blockers
                        and task.phase == "restore_blockers"):
                    beobachtet = task
                    protokoll.append(
                        ("START", engine.state.t,
                         [e["bin_id"] for e in task.temp_storage]))
            if beobachtet is not None:
                offen = [e["bin_id"] for e in (beobachtet.temp_storage or [])]
                if protokoll[-1][2] != offen:
                    zurueck = [b for b in protokoll[-1][2] if b not in offen]
                    for b in zurueck:
                        protokoll.append(("RESTORE", engine.state.t, b))
                    protokoll.append(("STATE", engine.state.t, offen))
                if not offen:
                    break

    if beobachtet is None:
        print(f"{policy}: kein Zyklus mit >= {min_blockers} Blockern gefunden")
        return

    reihenfolge = [b for art, _, b in protokoll if art == "RESTORE"]
    infos = []
    for bin_id in reihenfolge:
        b = engine.state.get_bin_by_id(bin_id)
        infos.append(f"{bin_id}[{b.get_abc_class()},n={b.get_access_count()}]")

    reordering = POLICIES[policy][0]
    print(f"### {policy}  (reordering={reordering})")
    print(f"  ausgelagerte Blocker (Reihenfolge der Auslagerung, oben zuerst):")
    print(f"    {[f'{b}' for b in protokoll[0][2]]}")
    print(f"  Rueckgabereihenfolge (zuerst zurueck = landet UNTEN):")
    print(f"    {infos}")
    if reordering == "ABC":
        klassen = [i.split('[')[1].split(',')[0] for i in infos]
        ok = klassen == sorted(klassen, key=lambda k: {"C": 0, "B": 1, "A": 2}[k])
        print(f"  -> Klassenfolge unten->oben: {klassen}  "
              f"{'PLAUSIBEL (C unten, A oben)' if ok else 'WIDERSPRUCH'}")
    elif reordering == "POPULARITY":
        counts = [int(i.split('n=')[1].rstrip(']')) for i in infos]
        ok = counts == sorted(counts)
        print(f"  -> access_count unten->oben: {counts}  "
              f"{'PLAUSIBEL (kalt unten, heiss oben)' if ok else 'WIDERSPRUCH'}")
    else:
        ok = reihenfolge == list(reversed(protokoll[0][2]))
        print(f"  -> LOFI: Originalordnung wiederhergestellt? "
              f"{'JA' if ok else 'NEIN'}")
    print()


if __name__ == "__main__":
    policies = sys.argv[1:] or ["baseline_reference", "ABC+ABC",
                                "POPULARITY+POPULARITY"]
    for p in policies:
        trace(p)
