# experiments/run_health.py
"""
Harte Correctness-/Liveness-Pruefung eines fertig gerechneten Laufs.

Ein Lauf kann technisch bis `T_final` durchlaufen und trotzdem ungueltig
sein: wenn unterwegs eine bereits eingefrorene harte Verletzung auftrat.
Solche Laeufe duerfen nicht stillschweigend als wissenschaftliche
Replikation in den finalen Daten landen.

Was hier GEPRUEFT wird
----------------------
Ausschliesslich die zwei eingefrorenen harten Signale:

    move_recovery_unresolved    eine Bewegungs-Recovery konnte den Konflikt
                                nicht aufloesen
    task_deadlock               ein Task-/Ownership-/Restore-Deadlock wurde
                                erkannt

Was hier NICHT geprueft wird
----------------------------
Alles, was ein legitimes Simulationsergebnis sein kann:

    niedriger Durchsatz, wenige Retrievals, grosse aber endliche
    Retrieval-Luecken, `not_converged`, `converged_then_rediverged`, hohe
    Deadline-Miss-Rate, viele NORMALE Deadlock-Detektionen, viele
    ERFOLGREICHE Move Recoveries, `unbury`, `drop_bury_redirect`,
    `stale_pickup_no_task`

Dies ist ein Correctness-Gate, kein Performancefilter. Eine korrekt
implementierte Policy darf schlecht abschneiden — das ist ein Ergebnis.

Befund 2026-08-24: die Zaehler zaehlten Strings, die es nicht gibt
------------------------------------------------------------------
Der Kampagnentreiber zaehlte bis hierher:

    recoveries  = log.count("[MOVE_RECOVERY]")
    unresolved  = log.count("MOVE_RECOVERY_UNRESOLVED")

Beide Zeichenketten werden von der Simulation **nie** ausgegeben. Empirisch
ueber alle fuenf Policies auf der finalen Geometrie geprueft: 0 Vorkommen,
und im gesamten Produktionscode existiert kein Erzeuger. Die Groesse
`move_recovery_unresolved` war damit strukturell immer 0 — sie konnte gar
nicht anschlagen.

Die tatsaechlichen Marker stehen in `simulation/event_handler.py`:

    [RECOVERY][MOVE_STALL] ...                        jeder Recovery-Versuch
    [RECOVERY][MOVE_STALL] ... keine Aufloesung ...   der Versuch scheiterte
    [TASK_DEADLOCK][RESTORE_BURIED] ...               Task-Deadlock

Hier wird deshalb der Marker gezaehlt, den die Simulation wirklich
schreibt. Das ist die Reparatur einer Messgroesse, KEIN neues oder
schaerferes Kriterium: in gesunden Laeufen aller fuenf Policies kommt der
Marker null Mal vor (gemessen), waehrend die legitimen `[DEADLOCK]`-
Detektionen dort 0 bis 9 Mal auftreten und bewusst nicht gewertet werden.

Warum nicht einfach auf die Ausnahme warten
-------------------------------------------
Bleibt ein Move-Stall dauerhaft unaufloesbar, laeuft die Retry-Leiter
irgendwann leer und der EventHandler wirft. Diesen Fall behandelt der
Treiber schon als `failed`. Das Gate hier greift frueher: es faengt den
Lauf, der die Verletzung hatte, sich aber wieder gefangen hat und deshalb
formal bis zum Ende lief.
"""

from typing import Dict, List

#: Marker der Simulation. Die Konstanten stehen hier, damit es genau eine
#: Stelle gibt, an der sie zu pflegen sind — und damit ein Test pruefen
#: kann, dass der Produktionscode sie noch schreibt. Genau diese Kopplung
#: fehlte, weshalb die alten Zaehler unbemerkt ins Leere liefen.
MARKER_MOVE_STALL_RECOVERY = "[RECOVERY][MOVE_STALL]"
MARKER_MOVE_STALL_UNRESOLVED = "keine Auflösung möglich"
MARKER_TASK_DEADLOCK = "[TASK_DEADLOCK]"

#: Die harten Signale. Wer hier etwas ergaenzt, aendert den Freeze.
HARTE_SIGNALE = ("move_recovery_unresolved", "task_deadlock")


def zaehle_health_signale(log: str) -> Dict[str, int]:
    """
    Zieht die Diagnosezahlen aus dem Lauflog.

    Returns:
        `move_stall_recoveries`   alle Recovery-VERSUCHE (nur Diagnose)
        `move_recovery_unresolved` davon die gescheiterten (HART)
        `task_deadlock`            erkannte Task-Deadlocks (HART)
    """
    versuche = log.count(MARKER_MOVE_STALL_RECOVERY)
    ungeloest = sum(
        1 for zeile in log.splitlines()
        if MARKER_MOVE_STALL_RECOVERY in zeile
        and MARKER_MOVE_STALL_UNRESOLVED in zeile
    )
    return {
        "move_stall_recoveries": versuche,
        "move_recovery_unresolved": ungeloest,
        "task_deadlock": log.count(MARKER_TASK_DEADLOCK),
    }


def evaluate_run_health(zaehler: Dict[str, int]) -> Dict[str, object]:
    """
    Entscheidet, ob ein Lauf als wissenschaftliche Replikation taugt.

    Args:
        zaehler: Ergebnis von `zaehle_health_signale`, oder ein Dict mit
            denselben Schluesseln.

    Returns:
        dict mit `healthy` (bool), `violations` (Liste lesbarer Befunde)
        und den geprueften Zahlen.

    Ein erfolgreich behandelter Recovery-Fall ist kein Fehler:
    `move_stall_recoveries` geht bewusst NICHT in die Bewertung ein.
    """
    verletzungen: List[str] = []
    for name in HARTE_SIGNALE:
        wert = int(zaehler.get(name, 0) or 0)
        if wert > 0:
            verletzungen.append(f"{name}={wert}")

    return {
        "healthy": not verletzungen,
        "violations": verletzungen,
        "move_stall_recoveries": int(
            zaehler.get("move_stall_recoveries", 0) or 0),
        "move_recovery_unresolved": int(
            zaehler.get("move_recovery_unresolved", 0) or 0),
        "task_deadlock": int(zaehler.get("task_deadlock", 0) or 0),
    }


def health_aus_log(log: str) -> Dict[str, object]:
    """Bequemlichkeitsschale: zaehlen und bewerten in einem Schritt."""
    return evaluate_run_health(zaehle_health_signale(log))
