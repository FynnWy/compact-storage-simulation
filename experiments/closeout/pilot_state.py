"""
Laden/Speichern eines Pilot-Zustands.

Warum eigenes Modul: `Event._next_event_id` ist eine KLASSENvariable. Sie
wird nicht mit den Instanzen gepickelt. Wird ein Lauf in einem neuen Prozess
fortgesetzt, beginnt der Zaehler wieder bei 0; neue Events sortieren dann vor
den bereits wartenden, weil `Event.__lt__` die `event_id` als Tie-Break
benutzt. Die fortgesetzte Trajektorie weicht dadurch ab.

Innerhalb EINES Prozesses faellt das nicht auf - deshalb war der Fehler in
der ersten Fassung des Harness unsichtbar.
"""
import pickle
import sys
from pathlib import Path

sys.path.insert(0, '/sessions/youthful-busy-noether/mnt/compact-storage-simulation')

from events.event import Event  # noqa: E402


def save_engine(path, engine):
    tmp = Path(str(path) + ".tmp")
    with open(tmp, "wb") as fh:
        pickle.dump({"engine": engine, "next_event_id": Event._next_event_id},
                    fh, pickle.HIGHEST_PROTOCOL)
    tmp.replace(path)


def load_engine(path):
    """Laedt einen Zustand und stellt den Event-Zaehler wieder her."""
    with open(path, "rb") as fh:
        blob = pickle.load(fh)
    if isinstance(blob, dict) and "engine" in blob:
        Event._next_event_id = blob["next_event_id"]
        return blob["engine"]
    # Altes Format ohne Zaehler: Zaehler defensiv hinter die groesste
    # vergebene ID setzen, damit wenigstens keine IDs kollidieren.
    engine = blob
    groesste = 0
    for item in list(engine.state.event_queue.queue):
        ev = item[-1] if isinstance(item, tuple) else item
        groesste = max(groesste, getattr(ev, "event_id", 0))
    Event._next_event_id = groesste + 1
    return engine
