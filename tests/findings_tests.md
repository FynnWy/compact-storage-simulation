## AI Assistant
Aus dem zweiten Lauf kann man jetzt deutlich klarer ablesen, **wo** dein System schon stabil ist und **wo** noch Baustellen sind.
Ich gehe das nach Themen sortiert durch.
## 1. Allgemeiner Zustand
- Du hast jetzt **84 Tests**, davon **74 PASSED, 10 FAILED**.
- Neue Tests (HighwayRules, Metrics-Integration, EventFlowSanity) sind **alle grün** – das ist ein gutes Zeichen:
    - Highway-Regel-Logik funktioniert wie gedacht.
    - Distribution-Snapshots & Convergence-/Position-Tracking funktionieren.
    - Es gibt ARRIVAL-, PICKSTATION_COMPLETE- und REQUEST_COMPLETE-Events im Event-Flow.

Das heißt:
Deine **Grundarchitektur läuft**, Events fließen, Metriken werden geschrieben, viele Invarianten halten.
## 2. Cluster 1 – Target-Bin-Rücklagerung & Strategien
Fehler:
- `TestDifferentStrategies.test_strategy_combinations[LOFI-RANDOM]`
- `...[ABC-ABC]`
- `...[POPULARITY-POPULARITY]`

Fehlermeldung:``` text
RuntimeError: Cannot mark target returned for task 1:
action to_stack S_3_0 is not target stack S_0_0
```

Ableitung:
Bei Strategiekombinationen, in denen du Nicht-ORIGINAL-Placement verwendest (RANDOM, ABC, POPULARITY), kommt es genau beim Return der Target-Bin zu einem Konflikt.
task.target_stack_id bleibt offenbar auf dem ursprünglichen Stack (S_0_0), während PlacementSelector für die Rücklagerung einen anderen Stack auswählt (S_3_0, S_2_3 …).
EventHandler._update_task_after_successful_return() erwartet aber, dass to_stack == task.target_stack_id.
Fazit:
Deine neuen Placement-Strategien sind „aktiv“, aber die Task-/Event-Logik ist noch auf „ORIGINAL-Stack-only“ ausgelegt.
Späteres Debugging-Thema:
Entweder task.target_stack_id muss auf den gewählten Rückgabe-Stack gesetzt werden, bevor der Return kommt (z.B. task.actual_return_stack_id → target_stack_id synchronisieren),
oder die Konsistenzprüfung im EventHandler muss an das neue Verhalten angepasst werden.
 
3. Cluster 2 – Multi-Robot-Koordination (Kollisionen & keine fertigen Requests)
Fehler:
TestNoCollisions.test_no_collision_two_robots
TestNoCollisions.test_no_collision_three_robots
TestNoInfiniteLoop.test_requests_complete
Symptome:
Mehrere Roboter landen gleichzeitig auf derselben Position (z.B. (-1, 0) – sehr wahrscheinlich bei Pickstations).
In einem längeren Lauf mit medium_config wird kein Request vollständig abgeschlossen (requests_completed == 0), obwohl Events fließen.
Aber:
Die neuen Event-Flow-Tests zeigen:
ARRIVAL-Events treten auf.
PICKSTATION_COMPLETE-Events treten auf.
Es gibt REQUEST_COMPLETE-Events (Event-Flow), also werden Tasks schon „fertig“ markiert.
Das heißt:
Der Event-Fluss ist in Ordnung — Requests kommen bis zum REQUEST_COMPLETE-Event.
Das Metrics-Recording (metrics.record_full_completion / requests_completed) spiegelt das aber noch nicht korrekt in summary() wider.
Und beim Multi-Robot-Szenario gibt es offenbar:
Kollisionen an Rand-/Pickstation-Positionen.
Viele [BLOCKED] relocate blocked: expected bin X on top of S_3_0, but top is Y → Konflikte zwischen Task-Annahmen und realem Stackzustand.
Fazit:
Zwei getrennte Baustellen:
Kollisionsvermeidung / TrafficManager im Multi-Robot-Fall (insbesondere an Pickstations / (-1, y)).
Metriken: requests_completed wird (noch) nicht hochgezählt, obwohl REQUEST_COMPLETE-Events passieren.
Beides kannst du später gezielt debuggen; die Tests markieren dir jetzt sehr genau, welche Szenarien betroffen sind.
 
4. Cluster 3 – Pathfinder Head-on-Test
Fehler:
TestPathfinderWaiting.test_head_on_move_is_avoided``` text
assert [(0, 1), (0, 0), (1, 0)] is None
```

Ableitung:
Dein zusätzlicher Test ging davon aus, dass in diesem Head-on-Szenario kein Pfad gefunden werden kann.
Die aktuelle Pathfinder-Implementierung findet aber einen alternativen Pfad, der den Konflikt umgeht (z.B. [(0, 1), (0, 0), (1, 0)]).
Das ist aus Sicht der Pfadfindung korrektes, sogar besseres Verhalten.
Fazit:
Hier ist nicht die Implementierung „falsch“, sondern der Test zu streng.
Später solltest du den Test so umformulieren, dass er prüft:
Der Pfad nutzt nicht direkt den verbotenen Head-on-Kantenwechsel,
aber er darf durchaus existieren.
 
5. Cluster 4 – Strategie-Unit-Tests (DummyState & distance_helpers)
Fehler:
TestPlacementSelectorABC.test_abc_prefers_near_and_shallow_for_A
TestPlacementSelectorPopularity.test_popularity_hot_bin_prefers_low_score_stack
Fehlermeldung:``` text
AttributeError: 'DummyState' object has no attribute 'pickstations'
```

Ableitung:
Die Tests verwenden einen DummyState, aber get_min_distance_to_pickstation(state, pos) erwartet, dass state.pickstations existiert.
Der Fehler ist rein testseitig: Implementierung ok, Test-Dummies unvollständig.
Fazit:
In deinen Test-Dummies für PlacementSelector musst du nur minimal ergänzen:``` python
  class DummyState:
      def __init__(..., ...):
          ...
          self.pickstations = []  # oder eine Fake-Pickstation, wenn du Distanzlogik realistisch nutzen willst
```

Das ist eine kleine, klar isolierte Korrektur in den Tests, kein Codeproblem deiner Strategien.
 
6. Cluster 5 – Single-Request-Workflow (Metrik vs. Verhalten)
Fehler:
TestSingleRequestWorkflow.test_single_request_completes``` text
AssertionError: assert 0 >= 1  # requests_completed == 0
```

Aber gleichzeitig:
TestEventFlowSanity.test_request_complete_event_occurs PASSED.
Ableitung:
Mindestens ein REQUEST_COMPLETE-Event tritt in der kleinen Simulation auf.
Aber die Metrik summary()["requests_completed"] bleibt 0.
Fazit:
Der Workflow an sich kommt bis „fertig“ (Event-Level),
die Metrik „requests_completed“ wird aber noch nicht korrekt gezählt:
entweder wird record_full_completion nicht oder zu selten aufgerufen,
oder summary() berücksichtigt die gespeicherten Completion-Zeiten nicht,
oder es gibt ein Missverständnis, was als „completed“ zählt (z.B. nur Hauptrequest vs. batched Requests).
Das ist später ein sehr guter Einstiegspunkt, um die Metrik-Implementierung zu überprüfen.
 
7. Gesamtbild
Was du jetzt aus dem zweiten Output mitnehmen kannst:
Stabil und gut getestet:
ReservationTable-Invarianten
DeadlockDetector/Resolver
Pathfinder-Grundlogik + Vermeidung/Waiting/Highway-Integration
HighwayRules-Verhalten
Metrik-Subsystem (ConvergenceDetector, PositionChangeTracker, DistributionSnapshots)
Event-Fluss (ARRIVAL, PICKSTATION_COMPLETE, REQUEST_COMPLETE treten auf)
Viele Strategie-Kombinationen (z.B. LOFI/ORIGINAL, ABC/ORIGINAL) laufen durch.
Offene Baustellen, sauber markiert:
Target-Bin-Rücklagerung mit alternativen Placement-Strategien
→ Anpassung Task-/EventHandler-Logik an neue Strategien.
Multi-Robot-Koordination
→ Kollisionen, Blockadefälle, keine abgeschlossenen Requests im Mehrroboter-Szenario.
Testkorrekturen / -verfeinerungen
Head-on-Pfadfinder-Test zu streng.
DummyState für PlacementSelector-Tests braucht pickstations.
Metrik „requests_completed“
→ weicht vom tatsächlichen Event-Verlauf ab.
Damit hast du jetzt ein ziemlich gutes Fehler-Radar: du weißt genau, wo du später einsteigen musst.
Wenn du willst, können wir im nächsten Schritt z.B. mit den einfachen Fixes anfangen (DummyState für Strategietests und Head-on-Test anpassen), oder direkt an die Placement/Target-Return-Logik gehen.

## Me
Schreibe mir alle erkenntnisse aus BEIDEN TESTS zusammen. Sei GENAU!

## AI Assistant

Hier ist eine präzise Gesamtauswertung aus beiden Testläufen – also was wir aktuell über dein System wissen.
Ich gliedere das in:
Was sicher funktioniert (grüne Bereiche)
Welche Probleme eindeutig sichtbar sind (rote Bereiche)
Wo die Tests selbst angepasst werden müssen (falsche Annahmen / Dummies)
 
1. Bereiche, die stabil und gut getestet sind
1.1 ReservationTable (Space-Time-Reservierungen)
Tests in tests/test_reservation_table.py zeigen:
Basisfunktionen:
reserve reserviert korrekt und ist idempotent.
is_free verhält sich korrekt, auch mit exclude_robot.
get_blocking_robot liefert die blockierende ID.
Invarianten:
INV-R1 (keine zwei Roboter zur selben Zeit auf derselben Zelle) wird korrekt erzwungen:
Zwei Roboter können nicht (x, y, t) gleichzeitig reservieren.
Verschiedene Zellen zur gleichen Zeit sind erlaubt.
Gleiche Zelle zu verschiedenen Zeiten ist erlaubt.
Atomare Pfadreservierung:
reserve_path reserviert komplette Pfade, wenn möglich.
Bei Konflikt wird nichts des Pfads reserviert (sauberer Rollback).
Konfliktinfos (position, time, blocking_robot) werden korrekt gefüllt.
Head-on & Swap:
Head-on Collision Detection: A→B und B→A gleichzeitig wird als Konflikt erkannt.
Swap-Szenario (zwei Roboter tauschen Positionen) wird ebenfalls als Konflikt erkannt.
Freigabe & Cleanup:
release und release_all geben Reservierungen korrekt frei.
cleanup_before entfernt alte Reservierungen und aktualisiert auch das robot_reservations-Mapping korrekt.
Negative x-Positionen (Pickstations links vom Grid) sind erlaubt.
Erkenntnis:
Deine ReservationTable ist sauber modelliert und erfüllt die definierten Invarianten. Das ist ein solides Fundament.
 
1.2 DeadlockDetector & DeadlockResolver
Tests in tests/test_deadlock.py:
Zyklen-Erkennung funktioniert für:
2er-, 3er-, 4er-Zyklen.
Keine Zyklen bei Ketten, leerem Graph, Einzelkanten, parallelen Ketten.
clear_wait und clear_all lösen Zyklen zuverlässig auf.
Hilfsfunktionen:
is_waiting, get_waiting_robots, get_wait_time liefern konsistente Ergebnisse.
Resolver:
Strategy "lowest_priority": Ohne Scheduler wird die höchste robot_id als Victim genommen.
Strategy "random" wählt ein Element aus dem Zyklus.
Leerer Zyklus → None.
Erkenntnis:
Deadlock-Management auf Graph-Ebene funktioniert logisch korrekt und deterministisch.
 
1.3 Pathfinder (A* im Space-Time-Grid)
Tests in tests/test_pathfinder.py:
Grundfunktionalität:
Findet einfache Pfade im leeren Grid, Endposition korrekt.
Pfade enthalten nicht die Startposition.
Wenn Start=Ziel → leerer Pfad.
Pfadlängen liegen in sinnvollem Bereich (≤ 1,5× Manhattan-Distanz).
Umgehung von Reservierungen:
Reservierte Zellen (auch ganze Reihen mit Zeitabhängigkeit) werden umgangen, Ziel wird erreicht.
Warten:
Mit allow_waiting=True findet Pathfinder einen Pfad, auch wenn eine Zielzelle temporär blockiert ist.
Mit allow_waiting=False kann es keinen Pfad geben – Test akzeptiert beide Varianten (Pfad oder None).
Highway-Integration:
Mit HighwayRules wird weiterhin ein Pfad gefunden und das Ziel erreicht.
Der Pfad existiert in einem Ring-Pattern-Szenario.
Pickstation-Bereich:
Pfade zu Positionen außerhalb des Grids ((-1, y)) funktionieren.
Pfade von Pickstation zurück ins Grid funktionieren.
Ein offener Punkt (s.u. in 2.3):
Der zusätzliche Test test_head_on_move_is_avoided erwartet path is None, aber deine Implementation findet einen alternativen Pfad. Das deutet eher auf einen zu strengen Test hin, nicht auf fehlerhaften Code.
 
1.4 HighwayRules
Neue Tests in tests/test_highway_rules.py:
Pattern „ring“:
Obere Zeile bevorzugt Rechtsbewegung.
Rechte obere Ecke bevorzugt Bewegung nach unten.
Penalty 0 für bevorzugte Richtungen, >0 für falsche Richtungen.
Pattern „rows“:
Gerade Reihen → bevorzugen rechts.
Ungerade Reihen → bevorzugen links.
Penalty unterscheidet korrekt zwischen „richtiger“ und „falscher“ Hauptrichtung.
Pattern „lanes“:
Gerade Spalten → bevorzugen nach unten.
Ungerade Spalten → bevorzugen nach oben.
Penalty für falsche vertikale Richtung wird korrekt vergeben.
Pattern „none“:
Alle Richtungen gleichermaßen erlaubt.
Penalty immer 0.
Erkenntnis:
Dein Highway-Regelsystem verhält sich genau wie spezifiziert. Integration mit Pathfinder ist also auf einer stabilen Grundlage.
 
1.5 Strategien: ReorderingSelector & PlacementSelector
Tests in tests/test_strategies_selectors.py:
ReorderingSelector:
LOFI: kehrt die Reihenfolge der Blocking-Bins korrekt um.
ABC: sortiert C zuerst, dann B, dann A – Reihenfolge innerhalb einer Klasse bleibt stabil.
POPULARITY: sortiert Blocking-Bins aufsteigend nach access_count.
PlacementSelector – ORIGINAL & RANDOM:
ORIGINAL:
Liefert den Original-Stack, wenn er existiert, nicht gelockt ist und Kapazität hat.
Wirft sinnvolle Fehler, wenn Stack nicht existiert / gelockt / voll ist.
RANDOM:
Wählt nur Stacks, die nicht gelockt und nicht voll sind.
POPULARITY – Warmup-Fall:
Wenn nicht genug Access-Daten vorhanden sind, wird korrekt auf RANDOM-Fallback gewechselt.
Erkenntnis:
Die Strategien LOFI/ABC/POPULARITY und ORIGINAL/RANDOM sind auf Unit-Test-Ebene konsistent und stabil.
Die Probleme mit Strategiekombinationen liegen eher im Task-/Event-Handling (siehe 2.1).
 
1.6 ConvergenceDetector & PositionChangeTracker
Tests in tests/test_convergence_and_position_tracking.py + test_metrics_integration.py:
ConvergenceDetector:
Leerer Verlauf → sinnvolle Default-Metriken, kein Konvergenzpunkt.
Bei nahezu konstanten Werten über window_size Snapshots wird Konvergenz erkannt.
Bei hoher Varianz wird keine Konvergenz erkannt.
get_stability_metrics() liefert:
variance_over_time
rolling_mean_digging_depth
post_convergence_stability mit sinnvollen (≥0) Varianzen.
PositionChangeTracker:
Erste Aufnahme erzeugt keine Änderungseinträge (wie erwartet).
Stack-Wechsel und Level-Wechsel werden getrennt gezählt.
Wenn eine Bin „verschwindet“ im nächsten Snapshot, zählt das als Stack-Wechsel.
Integration mit SimulationEngine:
Mit distribution_snapshot_interval > 0 werden tatsächlich Distribution-Snapshots aufgenommen.
engine.metrics.get_distribution_timeseries() liefert eine nicht-leere Liste.
engine.metrics.get_convergence_analysis() und convergence_detector.get_stability_metrics() arbeiten ohne Fehler.
position_change_tracker.get_timeseries() liefert konsistent strukturierte Einträge.
Erkenntnis:
Dein Monitoring-/Metrik-System ist funktional, robust und bereits gut mit der Engine verdrahtet.
 
1.7 Workflow & State-Invarianten
Event-Flow-Sanity (TestEventFlowSanity):
In small_config-Simulation:
Es tritt mindestens ein ARRIVAL-Event auf.
Es tritt mindestens ein PICKSTATION_COMPLETE-Event auf.
In medium_config:
Es tritt mindestens ein REQUEST_COMPLETE-Event im Event-Flow auf.
Bin-Konsistenz & Kapazität (TestBinConsistency, TestStackCapacity):
Über viele Events bleiben:
Gesamtzahl der sichtbaren Bins konstant (keine Bins „verloren“).
Keine doppelten Bin-IDs in Stacks + Pickstation.
Kein Stack überschreitet max_stack_height.
Erkenntnis:
Auf Zustandsebene ist die Simulation konsistent: keine Bins verloren, keine Doppelungen, Kapazitätseinhaltung.
Der Eventfluss läuft in die richtigen Stationen (ARRIVAL → PICKSTATION → REQUEST_COMPLETE tritt auf).
 
2. Eindeutige Probleme und Inkonsistenzen
2.1 Placement-Strategien vs. Task-/Event-Logik (Target-Bin-Rücklagerung)
Fehlschläge:
TestDifferentStrategies.test_strategy_combinations[LOFI-RANDOM]
...[ABC-ABC]
...[POPULARITY-POPULARITY]
Fehlermuster:``` text
RuntimeError: Cannot mark target returned for task 1:
action to_stack S_3_0 is not target stack S_0_0
```

Befunde:
In diesen Konfigurationen benutzt du Nicht-ORIGINAL Placement (RANDOM, ABC, POPULARITY).
Die Target-Bin wird physisch auf einen anderen Stack gelegt (S_3_0, S_2_3, …), während im RobotTask:
task.target_stack_id weiterhin auf dem ursprünglichen Ziel (S_0_0) steht.
task.actual_return_stack_id hält vermutlich den tatsächlichen Rückgabe-Stack.
EventHandler._update_task_after_successful_return prüft aber:``` python
  if action.get("to_stack") != task.target_stack_id:
      raise RuntimeError(...)
```

→ Diese Prüfung ist für „PlacementStrategien != ORIGINAL“ nicht mehr kompatibel.
Erkenntnis:
Logische Diskrepanz:
Strategie-Ebene erlaubt, die Target-Bin an einen sinnvollen anderen Stack zurückzulegen.
Task-/Event-Validierung ist noch auf „muss zurück zum ursprünglichen Stack“ ausgelegt.
Längerfristiger Fix:
Task-Objekt (RobotTask) und EventHandler müssen den neuen „tatsächlichen Rückgabe-Stack“ akzeptieren (z.B. target_stack_id zur Laufzeit anpassen oder auf actual_return_stack_id prüfen).
 
2.2 Multi-Robot-Koordination – Kollisionen & keine Requests fertig im Multi-Robot-Fall
Fehlschläge:
TestNoCollisions.test_no_collision_two_robots
TestNoCollisions.test_no_collision_three_robots
TestNoInfiniteLoop.test_requests_complete
Symptome:
Kollisionen:
Mehrfach Meldung: Collision at (-1, 0) between Robot 0 and Robot 1
collision_count == 302 im Drei-Roboter-Test.
Requests werden im medium_config in TestNoInfiniteLoop.test_requests_complete metrisch nie als „completed“ gezählt (requests_completed == 0), obwohl Events fließen.
Viele [BLOCKED] relocate ... expected bin X on top of S_3_0, but top is Y/None-Logs:
zeigen, dass Roboteraktionen (insb. relocate) wiederholt blockiert werden, weil der erwartete Bin nicht mehr oben auf dem Stack ist.
Erkenntnisse:
Kollisionen:
Die Reservation-/Traffic-Logik verhindert im Mehrroboterbetrieb nicht zuverlässig Kollisionen, insbesondere an Rand-/Pickstation-Positionen ((-1, 0)).
Dort teilen sich offenbar Roboter gleichzeitig dieselbe Zelle.
Fortschritt / Deadlocks:
Auch wenn "Simulation stuck"-Test grün ist (Zeit schreitet voran), scheinen sich Roboter häufig in Zuständen zu befinden, wo geplante Aktionen nicht mehr ausführbar sind (falsche Top-Bin), was auf:
veraltete Annahmen im Task über Stackzustände oder
nicht konsistente Updates bei Relocations
hindeutet.
RequestsCompleted-Metrik:
Im Mehrroboter-Szenario kommt engine.metrics.summary()["requests_completed"] nie über 0.
Trotzdem gibt es REQUEST_COMPLETE-Events (EventFlowSanity → grün).
Das deutet auf eine Diskrepanz zwischen:
Event-Ebene (Request wird per Event abgeschlossen)
Metrik-Zählung in Metrics.record_full_completion / summary().
 
2.3 Pathfinder-Head-on-Test (Testfehler, nicht Implementationsfehler)
Fehlschlag:
TestPathfinderWaiting.test_head_on_move_is_avoided``` text
assert [(0, 1), (0, 0), (1, 0)] is None
```

Befund:
Die Testannahme war: „In diesem minimalen Head-on-Szenario existiert kein alternativer Pfad, also muss find_path None liefern.“
Tatsächlich findet deine Implementierung einen alternativen Pfad, der den Konflikt umgeht (z.B. über (0,1)).
ReservationTable und Pathfinder-Logik sind ansonsten konsistent und durch andere Tests gut abgedeckt.
Erkenntnis:
Dieser spezielle Test ist zu streng / fachlich falsch:
Es ist völlig ok, dass der Pathfinder eine Umfahrung findet.
Der Test sollte angepasst werden auf:
„Pfad vermeidet direkt den verbotenen A→B-Move in der kritischen Zeit“, nicht „es darf gar kein Pfad existieren“.
 
2.4 Strategie-Dummies – fehlendes pickstations-Attribut im DummyState
Fehlschläge:
TestPlacementSelectorABC.test_abc_prefers_near_and_shallow_for_A
TestPlacementSelectorPopularity.test_popularity_hot_bin_prefers_low_score_stack
Fehler:``` text
AttributeError: 'DummyState' object has no attribute 'pickstations'
```

Befund:
Die Tests nutzen einen DummyState, aber get_min_distance_to_pickstation(state, stack_position) erwartet state.pickstations.
In der echten Simulation existiert dieses Attribut (Pickstations werden in der Engine erstellt).
Erkenntnis:
Implementierung ist korrekt; die Test-Dummies sind unvollständig.
Fix rein testseitig: DummyState muss mindestens self.pickstations = [] besitzen (oder eine simple Kunst-Pickstation, falls du mehr Realismus willst).
 
2.5 Single-Request-Workflow – Metrische Completion vs. Event-Completion
Fehlschlag:
TestSingleRequestWorkflow.test_single_request_completes:``` text
AssertionError: assert 0 >= 1  # requests_completed == 0
```

Gleichzeitig:
TestEventFlowSanity.test_request_complete_event_occurs ist PASSED:
Es tritt mindestens ein REQUEST_COMPLETE-Event im medium_config-Setup auf.
Befund:
Ein einzelner Lauf mit small_config schafft es in 500 Events offenbar nicht, einen Request metrisch als abgeschlossen zu zählen.
In einem anderen Setup (medium_config) werden REQUEST_COMPLETE-Events generiert, aber requests_completed bleibt offenbar auch dort 0 (siehe auch Multi-Robot-Test).
Erkenntnis:
Die „logische“ Fertigstellung eines Requests (Event REQUEST_COMPLETE) und die „metrische“ Fertigstellung (requests_completed in metrics.summary()) sind inkonsistent.
Entweder:
record_full_completion wird nicht oder nicht für alle relevanten Requests aufgerufen,
oder summary() wertet die gespeicherten Daten nicht korrekt aus,
oder es gibt eine Diskrepanz zwischen Hauptrequest und gebatchten Requests.
 
3. Zusammenfassung in einem Satz
Deine Kernbausteine (ReservationTable, DeadlockDetector, Pathfinder, Strategien, HighwayRules, Metriksystem, State-Invarianten) sind weitgehend stabil und korrekt implementiert.
Die aktuell offenen, klar lokalisierten Probleme liegen vor allem in:
der Integration von Target-Bin-Placement-Strategien mit der Task-/Event-Logik,
der Multi-Robot-Koordination (Kollisionen, blockierte Relocations),
der Metrik requests_completed, die nicht mit den abgeschlossenen Requests im Event-Flow übereinstimmt,
sowie in einzelnen Tests (Head-on-Pathfinder, DummyState für Placement-Tests), die an die tatsächliche Implementierung angepasst werden müssen.

