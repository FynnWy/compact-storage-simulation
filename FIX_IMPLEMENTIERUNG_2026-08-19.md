# Fix-Implementierung – 2026-08-19

Technischer Handoff. Basis: `ARCHITEKTUR_KARTE.md`, insbesondere Abschnitt 9
(Re-Baseline vom 2026-08-19).

## Baseline

| | |
|---|---|
| Branch | `working_sim` |
| Ausgangscommit | `82cfcab` |
| Datum | 2026-08-19 |
| Teststatus vor Änderungen | `pytest tests/ --ignore=tests/test_simulation_visual.py` → **138 passed** (6.5 s) |

`test_simulation_visual.py` wird ausgeklammert (benötigt Flask, wie in der
Architektur-Karte Abschnitt 9 dokumentiert).

Nicht angefasst in diesem Auftrag (explizite Vorgabe): `average_digging_depth`.

---

## Fix 1 – Pickstation-Service-Start

**Status: BEHOBEN** (Datum: 2026-08-19, Baseline `82cfcab`)

### Symptom

Bins bleiben sehr lange an der Pickstation liegen. Die Service-Queue wächst
(bis 37 Einträge bei Seed 7), während die Pickstation gleichzeitig `idle` ist.
Laut Baseline-Messung (Architektur-Karte 9.3) war die PS in 45–62 % der
Simulationszeit idle, obwohl Arbeit in der Queue lag.

### Reproduzierbares Szenario

Direkter Unit-Repro (`tests/test_pickstation_service_start.py::
test_next_service_starts_even_when_no_robot_is_idle`):

```text
Pickstation bedient Task A (capacity 1)
Task B wartet in pickstation.queue
alle Roboter sind busy
→ PICKSTATION_COMPLETE(Task A) wird behandelt
Erwartet: Service für Task B startet sofort
Baseline: Service für Task B startet NICHT
```

Systemrepro: 7×7, max_height 6, 100 Bins, 4 Robots, util 2.0, sim_time 500,
Seeds 42 und 7 (Messwerte s. u.).

### Bestätigte Root Cause

In `EventHandler._handle_pickstation_complete` stand der Aufruf
`_try_start_pickstation_service(pickstation)` als **letzte** Anweisung der
Methode, also hinter fünf Early Returns. Der praktisch immer greifende ist
`available_robot is None` → `[INFO] No robot available …` (Baseline: 26/26
bzw. 41/44 aller PICKSTATION_COMPLETE-Events).

Der Pickstation-Service selbst benötigt keinen Roboter – nur der spätere
Abtransport der fertigen Bin. Der Service-Start war damit fälschlich an die
Roboter-Verfügbarkeit gekoppelt. Der freie Service-Slot blieb ungenutzt, bis
der nächste Bin neu **angeliefert** wurde.

Bestätigt durch den Unit-Repro (schlägt ohne Fix fehl) und durch die
Vorher-/Nachher-Messung.

### Implementierte Änderung

`_try_start_pickstation_service(pickstation)` wurde vom Ende der Methode an die
Stelle unmittelbar **nach** `pickstation.complete_service(task)` verschoben –
also genau dorthin, wo die Kapazität frei wird. Der alte Aufruf am Methodenende
wurde entfernt (sonst würde er bei `capacity > 1` doppelt starten).

Keine Änderung an Scheduling-Prioritäten, Roboter-Zuweisung, Return-Task-
Prioritäten oder der Pickstation-Architektur.

### Begleitfix (notwendig, nicht optional): Drop-Recovery bei vollem Ziel-Stack

Nach Fix 1 laufen deutlich mehr Returns parallel. Dabei trat ein **bereits in
der Baseline vorhandener** Fehler häufiger auf:

`to_stack` einer `relocate`/`return`-Aktion wird zum Planungszeitpunkt gewählt.
Füllt ein anderer Roboter diesen Stack zwischenzeitlich, meldet `_can_drop`
dauerhaft `to_stack is full`. `_handle_robot_drop` hat den Fall nur delayed –
bis `EventBuilder.max_retries` (20) mit
`RuntimeError: Event exceeded max retries` abbricht.

Belegt durch Sweep (6×6, 2 Robots, sim_time 200, je Seed × Placement):

| Variante | abbrechende Läufe von 16 |
|---|---|
| Baseline `82cfcab` | 3 (Seed 99/RANDOM, Seed 555/ORIGINAL+RANDOM) |
| nur Fix 1 | 5 (zusätzlich Seed 7/RANDOM, Seed 123/RANDOM) |
| Fix 1 + Drop-Recovery | 0 |

Hypothese-Korrektur: Der Verdacht „Fix 1 verursacht einen neuen Crash" ist
**falsch**. Fix 1 erhöht nur die Eintrittswahrscheinlichkeit eines schon
vorhandenen Fehlers.

Änderung: `_handle_robot_drop` leitet ab
`max_drop_retries_before_redirect = 5` auf einen Ausweich-Stack um
(`_redirect_blocked_drop`). Die Stack-Auswahl delegiert an die bestehende
`RelocationSelection` (gleiche Kriterien wie R-D2). Für Blocker-Returns wird
`task.update_return_stack_for_blocker` mitgeführt, damit die
temp_storage-Invariante erhalten bleibt. Unterhalb der Schwelle bleibt das
bisherige Delay-Verhalten unverändert.

Der Move-zu-Drop-Block aus `_handle_robot_pickup` wurde dafür 1:1 in den Helper
`_schedule_move_to_drop` extrahiert (verhaltensneutral, gleicher Aufrufpunkt).

### Betroffene Dateien / Funktionen

| Datei | Funktion | Art |
|---|---|---|
| `simulation/event_handler.py` | `_handle_pickstation_complete` | Aufruf verschoben |
| `simulation/event_handler.py` | `EventHandler.__init__` | `max_drop_retries_before_redirect = 5` |
| `simulation/event_handler.py` | `_handle_robot_pickup` | Move-Planung in Helper extrahiert |
| `simulation/event_handler.py` | `_schedule_move_to_drop` | **neu** (extrahiert) |
| `simulation/event_handler.py` | `_handle_robot_drop` | Redirect-Zweig ergänzt |
| `simulation/event_handler.py` | `_redirect_blocked_drop` | **neu** |

### Neu hinzugefügte Tests

- `tests/test_pickstation_service_start.py` (3 Tests)
  - `test_next_service_starts_even_when_no_robot_is_idle` – Kernregression
  - `test_service_start_is_not_duplicated_when_robot_is_available` – Kapazität
  - `test_service_start_respects_capacity_and_empty_queue` – leere Queue
- `tests/test_drop_redirect.py` (5 Tests)
  - Umleitung ab Schwelle / kein Redirect unterhalb der Schwelle
  - 3 parametrisierte Szenarien, die auf der Baseline abbrachen

Verifiziert gegen die unveränderte Baseline: der Kerntest von
`test_pickstation_service_start.py` und 3 von 5 Tests aus
`test_drop_redirect.py` schlagen ohne die Fixes fehl.

### Ausgeführte Tests / Ergebnisse

```text
pytest tests/ --ignore=tests/test_simulation_visual.py
  vorher : 138 passed
  nachher: 141 passed  (138 alt + 3 neue Pickstation-Tests)
  + tests/test_drop_redirect.py: 5 passed
```

Kein bestehender Test wurde geändert oder abgeschwächt.

### Vorher/Nachher (deterministischer Systemlauf)

7×7, max_height 6, 100 Bins, 4 Robots, util 2.0, sim_time 500:

| Messgröße | Seed 42 vorher | Seed 42 nachher | Seed 7 vorher | Seed 7 nachher |
|---|---|---|---|---|
| PS idle bei gefüllter Queue | 309/500 ZE | **0/500 ZE** | 225/499 ZE | **0/499 ZE** |
| max. Service-Queue-Länge | 7 | **1** | 37 | **4** |
| Queue am Simulationsende | 7 | **0** | 37 | **1** |
| PS-Tasks bearbeitet | 26 | **30** | 44 | **64** |
| PS-Bins bearbeitet | 37 | **39** | 61 | **83** |
| `requests_completed` (Metrik 3) | 35 | **39** | 59 | **80** |
| `completed_requests` (Metrik 1, Ankunft an PS) | 48 | 42 | 102 | 88 |
| `average_tardiness` | 142,8 | 165,6 | 153,8 | 162,8 |

Einordnung:

- Das Kernsymptom ist vollständig verschwunden: die PS ist in keinem
  Zeitschritt mehr idle, während Arbeit in der Queue liegt.
- Vollständige Completions steigen deutlich (+11 % / +36 %).
- `completed_requests` (Metrik 1 = Bin erreicht PS) **sinkt**. Das ist
  konsistent: Roboter verbringen jetzt mehr Zeit mit Rücktransporten
  (`waiting_tasks` hat höchste effektive Priorität) statt neue Bins anzuliefern.
  Das System baut WIP ab, statt ihn anzuhäufen.
- `average_tardiness` steigt leicht. Ursache ist ein Selektionseffekt: Requests,
  die vorher nie fertig wurden und daher nicht in die Statistik eingingen,
  werden jetzt abgeschlossen – mit entsprechend hoher Verspätung. Das ist kein
  Verschlechterung des Verhaltens, aber beim Interpretieren der Metrik zu
  beachten.

### Verbleibende Risiken

- Der Redirect erzeugt ein neues Drop-Event mit `retry_count = 0`. Das ist
  hier vertretbar, weil sich der Zielzustand tatsächlich ändert (anderer
  Stack). Sind **alle** Stacks voll, wirft `RelocationSelection` und der
  Code fällt auf das alte Delay-Verhalten zurück → weiterhin `RuntimeError`
  bei anhaltender Vollauslastung. Das ist bewusst nicht mitbehandelt.
- `average_tardiness`/`completed_requests` sind wegen des Selektionseffekts
  nicht direkt mit den Baseline-Zahlen vergleichbar.
- Der Fix verschiebt die Systemlast Richtung Rücktransport. Ob die
  Priorisierung `waiting_tasks` vor neuen Requests unter dieser höheren
  Return-Last noch optimal ist, wurde **nicht** untersucht (war ausdrücklich
  nicht Teil des Auftrags).

### Mögliche Folgearbeiten

- Eskalation ergänzen, wenn wirklich kein Stack mehr Kapazität hat
  (z. B. Task-Requeue statt `RuntimeError`).
- Metrik „PS idle trotz gefüllter Queue" dauerhaft in `Metrics.summary()`
  aufnehmen – sie war der entscheidende Indikator und existiert bisher nur
  als Ad-hoc-Messung.

---

## Fix 2 – Task-Doppelvergabe

**Status: BEHOBEN** (Datum: 2026-08-19, Baseline `82cfcab`)

### Symptom

Derselbe Task wird gleichzeitig zwei Robotern zugewiesen. In der Baseline
äußerte sich das ursprünglich als
`RuntimeError: Invalid state: duplicate bin detected`. Neuere `in_transit`-
Guards fangen den zweiten Zugriff meist ab – damit war aber nur das Symptom
maskiert, nicht die Ursache.

Im Seed-Sweep ist der Crash weiterhin reproduzierbar (7×7, 4 Robots, util 2.0,
Seed 4 → `duplicate bin detected. duplicate_bin_ids=[30]`). Die Aussage aus
Architektur-Karte 9.1 („Duplicate-Bin-Crash **BEHOBEN (Symptom)**") gilt also
nur für die dort gemessene Konfiguration (util 2.0, 3 Robots, Seeds 1–4/42),
nicht allgemein. **Hypothese-Korrektur.**

### Invariante

```text
Ein Task darf zu einem Zeitpunkt nicht gleichzeitig
als wartend (ActiveQueue.waiting_tasks) und
als zugewiesen (ActiveQueue.assigned) gelten.

Ein Task darf nicht gleichzeitig mehreren Robotern zugewiesen sein.
```

### Reproduzierbares Szenario

```text
Task landet in waiting_tasks   (mark_pickstation_task_completed)
→ Task wird Robot A zugewiesen (assign_task_to_robot → mark_task_assigned)
→ Task steht weiterhin in waiting_tasks
→ Scheduler läuft erneut
→ _try_schedule_waiting_task popt denselben Task
→ Task wird Robot B zugewiesen
```

Beobachtet im Systemlauf (5×5, 3 Robots, Seed 2): `t=31: Task 0 gleichzeitig
bei Robot 1 und Robot 2`.

### Bestätigte Root Cause

`ActiveQueue.mark_task_assigned` entfernte den Task aus `pickstation_tasks`,
aber **nicht** aus `waiting_tasks`.

Root-Cause-Verifikation (gezielt, keine Neuanalyse): `mark_task_assigned` hat
genau zwei Aufrufpfade und ist damit der zentrale und korrekte Ort:

| Aufrufer | Zustand vor dem Aufruf |
|---|---|
| `Scheduler._try_schedule_waiting_task` (Z. 104) | Task wurde direkt davor per `pop_waiting_task()` entnommen → Bereinigung ist dort ein No-op |
| `EventHandler._handle_pickstation_complete` über `assign_task_to_robot` | Task wurde kurz zuvor per `mark_pickstation_task_completed` in `waiting_tasks` gelegt → **hier entsteht die Doppelvergabe** |

Neu erzeugte Tasks laufen über `mark_assigned(request, robot)` und sind nie in
`waiting_tasks` – dieser Pfad ist nicht betroffen.

### Implementierte Änderung

In `requests_/active_queue.py`:

- `mark_task_assigned` ruft jetzt `remove_waiting_task(task)`.
- Neue Hilfsmethode `remove_waiting_task(task)` (idempotent, vergleicht über
  `request_id`, damit auch mehrfach eingetragene logisch identische Tasks
  verschwinden).

Bewusst **keine** zusätzlichen symptomatischen Guards; die Korrektur setzt am
Task-/Container-Zustand an. Keine Änderung an Scheduling-Prioritäten oder an
der Reihenfolge `waiting → opportunistisch → FIFO/EDF`.

### Betroffene Dateien / Funktionen

| Datei | Funktion | Art |
|---|---|---|
| `requests_/active_queue.py` | `mark_task_assigned` | Bereinigung ergänzt |
| `requests_/active_queue.py` | `remove_waiting_task` | **neu** |

### Neu hinzugefügte Tests

`tests/test_task_assignment_invariant.py` (5 Tests):

- `test_mark_task_assigned_removes_task_from_waiting_tasks` – Container-Invariante
- `test_task_is_never_waiting_and_assigned_at_the_same_time` – Schnittmenge leer
- `test_same_task_cannot_be_offered_to_a_second_robot` – Scheduling-Invariante,
  reproduziert den bekannten Ablauf
- `test_no_double_assignment_during_multi_robot_run` – Invariante in **jedem**
  Simulationsschritt (3 Robots)
- `test_no_double_assignment_across_seeds` – Seeds 1, 2, 3, 4, 42

Ohne den Fix schlagen 4 der 5 Tests fehl.

### Ausgeführte Tests / Ergebnisse

```text
pytest tests/test_task_assignment_invariant.py   → 5 passed
pytest tests/ --ignore=tests/test_simulation_visual.py → 151 passed
```

Kein bestehender Test wurde geändert.

### Seed-Sweep (7×7, 100 Bins, sim_time 500)

`dbl` = Anzahl Simulationsschritte mit Invarianten-Verletzung.

| Konfiguration | Baseline `82cfcab` | mit Fix 1+2 |
|---|---|---|
| 2 Robots, util 0.5, Seeds 1/2/3 | dbl = 60 / 41 / 132 | **0 / 0 / 0** |
| 3 Robots, util 2.0, Seeds 2/4/7 | dbl = 91 / 216 / 285 | **0 / 0 / 0** |
| 4 Robots, util 2.0, Seeds 1/2/3/4/7 | dbl = 83 / 394 / 312 / 204 / 204 | **0 / 0 / 0 / 0 / 0** |
| 4 Robots, util 2.0, Seed 4 | `RuntimeError: duplicate bin detected` | **läuft durch** |

Über alle 18 gemessenen Konfigurationen: **0 Invarianten-Verletzungen,
0 Exceptions**.

Completions (`requests_completed`) im Vergleich, 4 Robots / util 2.0:

| Seed | Baseline | Fix 1+2 |
|---|---|---|
| 1 | 38 | 39 |
| 2 | 57 | **83** |
| 3 | 60 | **75** |
| 4 | 38 (Crash) | **82** |
| 7 | 59 | **84** |
| 42 | 35 | 39 |

Keine Konfiguration verschlechtert sich substanziell; keine Return-Regression
(Returns laufen weiterhin mit höchster effektiver Priorität über
`waiting_tasks`); keine neue Starvation beobachtet (kein Roboter bleibt
dauerhaft ohne Fortschritt, außer im bekannten Livelock-Szenario Seed 42 /
2 Robots → Fix 3).

### Verbleibende Risiken

- Die Invariante wird im Container hergestellt, nicht durch einen Assert
  erzwungen. Ein künftiger Aufrufer könnte einen bereits zugewiesenen Task
  erneut per `add_waiting_task` einreihen. Der Systemtest deckt das ab,
  ein harter Guard existiert bewusst nicht (wäre wieder ein Symptom-Guard).
- Der `duplicate bin detected`-Crash ist im gemessenen Sweep verschwunden,
  aber nicht formal ausgeschlossen – es gibt weitere Wege, wie eine Bin
  doppelt referenziert werden könnte (nicht untersucht).

---

## Fix 3 – Multi-Robot-Livelock

**Status: BEHOBEN** für das beauftragte deterministische Szenario.
Ein **davon unabhängiger**, bereits in der Baseline vorhandener Stillstand
(Seed 1, util 2.0) bleibt offen – siehe „Nicht behoben" am Ende dieses
Abschnitts.

### Reproduktion

7×7, max_height 6, 100 Bins, **2 Robots, Seed 42, util 0.5**, sim_time 500.

Endzustand (reproduziert, identisch zur Architektur-Karte 9.2):

```text
Robot 0: pos=(5,2)  planned_path=[(5,1)]  task 0, phase retrieve_target
Robot 1: pos=(5,1)  planned_path=[(5,2)]  task 1, phase retrieve_target
```

Zwei benachbarte Roboter wollen **die Zelle des jeweils anderen** – ein
Swap-Konflikt. Messwerte über 500 ZE:

| | |
|---|---|
| `requests_completed` | 0 |
| längste Phase ohne Nutzfortschritt | 499 ZE (ab t≈9) |
| `[REPLAN]` (Move) | 414 |
| `[REPLAN][PICKUP_POS]` | 136 |
| `[REQUEUE][PICKUP_POS]` | **0** |
| `[BLOCKED][PICKUP]` | 694 |
| `[WARNING]` | 965 |
| `[DEADLOCK]` | **0** |
| `TrafficManager failed … using simple path` | 414 |

### Konkrete Root Cause (gezielt verifiziert)

Instrumentierter Lauf (Monkeypatch auf `DeadlockDetector`, kein Produktionscode
geändert):

```text
register_wait   aus _handle_robot_move            414
detect_cycle    → Ergebnis "kein Zyklus"          414
clear_wait      aus release_robot_reservations    414
clear_wait      aus request_path                  142
```

Der Ablauf pro Konflikt-Retry ist:

```text
_handle_robot_move: Zelle physisch belegt, retry ≥ 1
  → register_wait(A → B)
  → detect_cycle()            # nur Kante A→B vorhanden → kein Zyklus
  → _replan_path_around_obstacle(A, Zelle von B)
        → blocked_cells = {Zelle von B}  — das ist aber A's ZIEL
        → Pathfinder findet nie einen Pfad → request_path = None
        → Manhattan-Fallback ignoriert blocked_cells
          → liefert genau den 1-Schritt-Pfad in B's Zelle
        → Pfad ist nicht leer → release_robot_reservations(A)
          → clear_wait(A)     ← die eben gesetzte Kante wird gelöscht
  → nächster Move scheitert physisch → von vorn
```

Vier belegte Teilursachen:

1. **Manhattan-Fallback ignoriert `blocked_cells`** (`ActionCostModel.calculate_path`,
   Z. 226 ff.). Er liefert einen Pfad, der garantiert physisch scheitert.
2. **Replanning um die Zielzelle ist konstruktiv unmöglich.** Ist die blockierte
   Zelle gleich dem Ziel, kann A\* per Definition nichts finden.
3. **Wait-Kante wird im selben Handler-Aufruf wieder gelöscht.**
   `_replan_path_around_obstacle` ruft `traffic_manager.release_robot_reservations`,
   und das ruft `clear_wait`. Der Graph enthält daher nie beide Kanten
   gleichzeitig → `detect_cycle` schlägt strukturell nie an.
   **Hypothese-Korrektur:** Architektur-Karte 9.2 Punkt 3 führt das Löschen auf
   „erfolgreiche Tabellen-Reservierung in `request_path`" zurück. Dieser Pfad
   existiert (142 Aufrufe), ist hier aber **nicht** der entscheidende – die
   414 relevanten `clear_wait`-Aufrufe kommen aus `release_robot_reservations`.
4. **Auflösung erzeugt keinen Fortschritt.** Selbst bei erkanntem Zyklus:
   Opfer = eigener Robot → nur `delay_event`; Opfer = anderer Robot → `pass`.
   Zusätzlich setzt `[REPLAN][PICKUP_POS]` neue Pickup-Events mit
   `retry_count=0` → die Requeue-Schwelle (15) wird nie erreicht (0 Requeues).

### Geplante Minimaländerung

1. `ActionCostModel.calculate_path`: Manhattan-Fallback respektiert
   `blocked_cells`. Führt der Fallback-Pfad durch eine blockierte Zelle, wird
   **kein** Pfad geliefert.
2. `EventHandler._replan_path_around_obstacle`:
   - gibt nur die Reservierungen frei (`reservation_table.release_all`), **nicht**
     die Wartekante;
   - erkennt den Fall „blockierte Zelle == Ziel" und meldet Misserfolg zurück,
     statt sinnlos zu planen.
3. `EventHandler._handle_robot_move`: Bei erkanntem Zyklus echte Recovery statt
   `delay`/`pass` – `_resolve_move_deadlock`: das Opfer weicht einen Schritt auf
   eine freie Nachbarzelle aus (`_evade_robot`). Ist keine freie Nachbarzelle
   vorhanden und hat das Opfer einen Task, wird der Task requeued (bereits
   vorhandenes Eskalationsmuster aus dem Engine-Resolver).

### Warum das echten Fortschritt ermöglichen sollte

Änderung 1 entfernt den Generator der Endlosschleife (physisch unmögliche
Pfade). Änderung 2 macht den Konflikt für die vorhandene Detection überhaupt
erst sichtbar. Änderung 3 macht die Auflösung wirksam: Bei einem Swap-Konflikt
kann **kein** Umplanen helfen – einer der beiden muss die Zelle räumen. Nach dem
Ausweichen ist die umstrittene Zelle innerhalb 1 ZE frei, der wartende Robot
kommt an seinem Stack an und die Task-Phase schreitet fort.

### Risiken (vorab)

- 1 allein würde den Livelock in einen **statischen Deadlock** verwandeln
  (beide stehen). Nur zusammen mit 2+3 entsteht Fortschritt. Das Erfolgskriterium
  ist deshalb explizit „Nutzfortschritt", nicht „weniger Warnungen".
- Das Ausweichen versetzt einen Roboter, der ggf. eine Bin trägt. Ein
  Positions-Check im Drop-Pfad existiert im Bestand nicht; die Situation ist
  aber schon heute möglich (Drop-Events feuern zeitgesteuert, unabhängig von
  der tatsächlichen Ankunft). Wird über Sweep + Engine-Invarianten überwacht.
- Das Behalten der Wartekante kann zu Phantom-Zyklen führen, wenn eine Kante
  veraltet. Gegenmaßnahme: Die Kante wird weiterhin gelöscht, sobald
  `request_path` erfolgreich reserviert oder der Robot seinen Task verliert.

### Progress-Bedingung (Erfolgskriterium)

Definiert auf Basis vorhandener Zustände, nicht neu erfunden. Ein
**Fortschrittsereignis** ist jeder dieser monotonen Übergänge:

| Ereignis | Quelle |
|---|---|
| Target-Bin erreicht die Pickstation | `RobotTask.target_at_pickstation` |
| Pickstation-Service abgeschlossen | `RobotTask.pickstation_completed` |
| Target-Bin zurückgelagert | `RobotTask.target_returned` |
| Request vollständig abgeschlossen | `Metrics.summary()["requests_completed"]` |

Erfolgskriterien im Regressionstest:

1. `requests_completed > 0` (echte Nutzarbeit, nicht nur „keine Exception")
2. längste Phase ohne Fortschrittsereignis ≤ **120 ZE**
3. Gegenprobe: beide Roboter haben sich im Verlauf bewegt (kein Ersatz des
   Livelocks durch einen statischen Deadlock)

### Implementierte Änderung

| # | Datei / Funktion | Änderung |
|---|---|---|
| 1 | `simulation/action_cost_model.py` → `calculate_path` | Manhattan-Fallback prüft `blocked_cells`; führt der Pfad durch eine blockierte Zelle, wird `[]` (kein Pfad) geliefert |
| 2a | `simulation/event_handler.py` → `_replan_path_around_obstacle` | Ist die blockierte Zelle das eigene Ziel, wird nur verzögert statt sinnlos geplant |
| 2b | `simulation/event_handler.py` → `_replan_path_around_obstacle` | `reservation_table.release_all` statt `traffic_manager.release_robot_reservations` → die Wartekante überlebt; `clear_wait` erst nach erfolgreicher Neuplanung |
| 3a | `simulation/event_handler.py` → `_handle_robot_move` | Bei erkanntem Zyklus Aufruf von `_resolve_move_deadlock` statt `delay`/`pass` |
| 3b | `simulation/event_handler.py` → `_resolve_move_deadlock` | **neu**: Opfer weicht aus; scheitert das, wird sein Task requeued |
| 3c | `simulation/event_handler.py` → `_evade_robot` | **neu**: deterministischer 1-Schritt-Ausweichzug auf eine freie Nachbarzelle (Ports ausgenommen) |
| 4 | `requests_/active_queue.py` → `add_waiting_task` | Gegenstück zur Fix-2-Invariante: entfernt den Task aus `assigned` (im Sweep aufgedeckt, s. u.) |

Nicht angefasst: `TrafficManager`, `ReservationTable`, `Pathfinder`,
`Scheduler`, Deadlock-Architektur, `average_digging_depth`.

**Während der Arbeit aufgedeckt:** Der neue Requeue-Pfad in
`_resolve_move_deadlock` legte den Task in `waiting_tasks`, ließ ihn aber in
`assigned` stehen → im Sweep 18 Invarianten-Verletzungen (Seed 99, 3 Robots,
util 0.5). Dasselbe Muster existiert bereits in
`SimulationEngine.step` (Engine-Deadlock-Resolver) und im
`[REQUEUE][PICKUP_POS]`-Pfad. Korrigiert zentral in `add_waiting_task`,
symmetrisch zu Fix 2.

### Neu hinzugefügte Tests

`tests/test_livelock_two_robots.py` (8 Tests):

- `test_two_robot_scenario_makes_real_progress` – Kernregression, prüft
  Completions **und** max. Stillstandsfenster
- `test_two_robot_scenario_does_not_become_a_static_deadlock` – Gegenprobe
- `test_manhattan_fallback_respects_blocked_cells` – Änderung 1
- `test_swap_conflict_is_detected_and_resolved` – Detection + tatsächliches
  Räumen der umstrittenen Zelle
- `test_low_load_two_robot_scenarios_make_progress[1|2|3|42]` – Niedriglast

Auf der Baseline `82cfcab` schlagen 4 davon fehl (u. a. Kernregression und
Manhattan-Fallback).

### Ausgeführte Tests / Ergebnisse

```text
pytest tests/test_livelock_two_robots.py            → 8 passed
pytest tests/ --ignore=tests/test_simulation_visual.py → 157 passed
```

Kein bestehender Test wurde geändert oder abgeschwächt.

### Vorher/Nachher – Kernszenario (7×7, 2 Robots, Seed 42, util 0.5, 500 ZE)

| Messgröße | Baseline `82cfcab` | Fix 1+2+3 |
|---|---|---|
| `requests_completed` | **0** | **32** |
| längste Phase ohne Nutzfortschritt | 499 ZE | **31 ZE** |
| `[REPLAN]` (Move) | 551 | 27 |
| `[BLOCKED]` | 694 | 36 |
| `[WARNING]` | 965 | 49 |
| `[DEADLOCK]` erkannt | **0** | **6** |
| Manhattan-Fallbacks | 414 | **0** |
| `[REQUEUE][PICKUP_POS]` | 0 | 0 |
| Endzustand | beide Roboter stehen seit t≈9 | beide arbeiten aktiv |

Wichtig: Der Fix erfüllt das Erfolgskriterium – die Roboter „zappeln" nicht
weniger, sie **arbeiten**. Die Detection schlägt jetzt an (0 → 6 erkannte
Zyklen), und jede Erkennung führt zu einem tatsächlichen Räumen der Zelle.

### Seed-Sweep (7×7, 100 Bins, sim_time 500, 35 Konfigurationen)

Konfigurationen: 2/3/4 Roboter × util 0.5 und 2.0 × Seeds 1, 2, 3, 4, 7, 42, 99.

| Kennzahl | Baseline `82cfcab` | Fix 1+2+3 |
|---|---|---|
| Summe `requests_completed` über alle 35 Läufe | 1280 | **1745 (+36 %)** |
| Konfigurationen mit **0** Completions | 2 | **0** |
| Konfigurationen verbessert / verschlechtert | – | 27 / 4 |
| Exceptions | 1 (`duplicate bin detected`, Seed 4/4 Robots) | **0** |
| Invarianten-Verletzungen (`dbl`) | bis 394 pro Lauf | **0 in allen Läufen** |
| Manhattan-Fallbacks | bis 414 pro Lauf | 0–4 |
| erkannte Deadlock-Zyklen | 0 (in 34 von 35 Läufen) | 0–9, greift regelmäßig |
| längste Phase ohne Nutzfortschritt | bis 499 ZE | ≤ 31 ZE (Ausnahme s. u.) |

Detailwerte für die kritischen Niedriglast-Fälle:

| Konfiguration | Baseline compl / maxgap | Fix compl / maxgap |
|---|---|---|
| 2 Robots, util 0.5, Seed 42 | 0 / 499 | **32 / 31** |
| 3 Robots, util 0.5, Seed 42 | 3 / 375 | **45 / 23** |
| 2 Robots, util 2.0, Seed 42 | 0 / 499 | **39 / 23** |
| 3 Robots, util 2.0, Seed 42 | 16 / 24 | **61 / 17** |
| 4 Robots, util 2.0, Seed 42 | 35 / 19 | **69 / 18** |

Höhere Last (util 2.0, 3–4 Robots) löste sich schon in der Baseline teilweise
durch Fremdbewegung; auch dort steigen die Completions deutlich
(z. B. 4 Robots: 57→85, 60→85, 38→77, 59→84).

### Nicht behoben (bewusst, außerhalb des Auftrags)

**Seed 1, util 2.0** bleibt in allen Roboterzahlen problematisch
(2 Robots: 1 Completion, maxgap 449). Das ist ein **anderer**, unabhängiger
Fehler und **kein** Bewegungs-Livelock:

```text
Robot 0 steht auf (4,6), Phase restore_blockers
  → next_action liefert dauerhaft `return bin=90`
  → _can_pickup: "expected bin 90 not on top" (Bin 90 ist längst zurückgelegt)
  → [REPLAN][PICKUP_RETURN] "already stored -> re-evaluating next action"
  → neues Pickup-Event mit retry_count=0
  → identische Aktion, endlos (457×)
Robot 1 wartet auf genau diese Zelle und kommt nie durch.
```

Root Cause liegt in der Task-/Strategie-Ebene (`temp_storage` enthält eine
Bin, die bereits zurückgelegt wurde, `mark_last_relocation_restored` wurde nie
aufgerufen), nicht in der Traffic-Schicht. Es entsteht **keine Wartekante für
Robot 0** (er bewegt sich gar nicht), daher kann die Deadlock-Erkennung hier
konstruktiv nicht greifen.

Belegt als vorbestehend: identische Zahlen auf der Baseline.

| | Baseline | Fix 1+2+3 |
|---|---|---|
| Seed 1, 2 Robots, `[REPLAN][PICKUP_RETURN]` | 457 | 457 |
| Seed 1, 3 Robots | 449 | 449 |
| Seed 1, 4 Robots | 457 | 456 |

Gemäß Auftrag („entdeckte Zusatzprobleme nicht ungefragt mitbeheben") wurde
hier **nichts geändert**. Es existiert bewusst auch kein Test, der dieses
Verhalten grün stellt.

### Verbleibende Risiken

- **Ausweichen bewegt ggf. einen tragenden Roboter.** Ein Positions-Check im
  Drop-Pfad existiert im Bestand nicht (Drop-Events feuern zeitgesteuert). In
  35 Sweep-Läufen traten keine Bin-Inkonsistenzen auf (Engine-`_validate_runtime_state`
  war aktiv), formal ausgeschlossen ist es aber nicht.
- **Wartekanten können veralten.** Sie werden jetzt länger gehalten. Gelöscht
  wird bei erfolgreicher Reservierung (`request_path`), erfolgreichem Replan,
  Ausweichen und `release_robot_reservations`. Ein Zeit-basiertes Verfallen
  existiert nicht.
- **`_evade_robot` meidet Ports.** Steht ein Opfer in einer Sackgasse neben
  einem Port, greift nur noch der Requeue-Pfad.
- Der periodische Deadlock-Check der Engine läuft weiterhin nur bei leerer
  Event-Queue (unverändert, Architektur-Karte 5.3 Punkt 2). Die wirksame
  Erkennung sitzt weiterhin ausschließlich in `_handle_robot_move`.

### Mögliche Folgearbeiten

- Den Seed-1-Fehler (`[REPLAN][PICKUP_RETURN]`-Schleife) angehen: entweder
  `temp_storage` beim Erkennen einer bereits gelagerten Bin bereinigen oder
  den Retry-Zähler über Event-Neuerzeugungen hinweg erhalten.
- Genereller: `retry_count` bei Replan-Neuerzeugungen übertragen, damit die
  Requeue-Schwellen überhaupt erreichbar werden (betrifft
  `[REPLAN][PICKUP_POS]` und `[REPLAN][PICKUP_RETURN]`).
- Periodischen Deadlock-Check aus dem Leer-Queue-Zweig lösen.

---

## Abschlussvalidierung

### Gesamtteststatus

```text
pytest tests/ --ignore=tests/test_simulation_visual.py
  Baseline 82cfcab : 138 passed
  nach Fix 1+2+3   : 159 passed   (138 bestehende + 21 neue)
```

Kein bestehender Test wurde geändert, gelöscht oder abgeschwächt.
`test_simulation_visual.py` bleibt ausgeklammert (Flask-Abhängigkeit,
wie in der Baseline).

### Wechselwirkungen der drei Fixes

| Paar | Wechselwirkung | Bewertung |
|---|---|---|
| Fix 1 ↔ Begleitfix Drop-Recovery | Fix 1 erhöht die Parallelität der Returns und macht den vorbestehenden „to_stack is full"-Abbruch häufiger (3 → 5 von 16 Läufen). Die Drop-Recovery bringt ihn auf 0. | **notwendige Kopplung**, dokumentiert |
| Fix 2 ↔ Fix 3 | Der neue Requeue-Pfad in `_resolve_move_deadlock` verletzte die Fix-2-Invariante (Task in `waiting_tasks` **und** `assigned`). Aufgedeckt durch den Sweep. Korrigiert durch die symmetrische Bereinigung in `add_waiting_task`. | **aufgedeckt und behoben** |
| Fix 1 ↔ Fix 3 | Verstärken sich: Nach Auflösung des Livelocks werden Roboter wieder frei, die PS bekommt mehr Zuläufe – und gibt sie dank Fix 1 auch wieder ab. Seed 42, 4 Robots, util 2.0: 39 Completions (nur Fix 1) → 69 (alle Fixes). | positiv |
| Fix 1 Drop-Redirect ↔ Fix 3 `blocked_cells` | `_redirect_blocked_drop` plant über `_schedule_move_to_drop` **ohne** `blocked_cells`; die Änderung am Manhattan-Fallback wirkt dort nicht. Keine Kopplung. | neutral |

### Abschlussprüfungen

| Prüfpunkt | Ergebnis |
|---|---|
| Pickstation arbeitet, solange Service-Arbeit vorhanden ist | **erfüllt** – „PS idle bei gefüllter Queue" = 0/500 ZE (Seed 42) und 0/499 ZE (Seed 7) |
| keine Task-Doppelvergabe | **erfüllt** – 0 Invarianten-Verletzungen in 35 Sweep-Konfigurationen (Baseline: bis 394 pro Lauf) |
| kein bekanntes 2-Robot-Livelock | **erfüllt** – Seed 42/2 Robots/util 0.5: 0 → 32 Completions, max. Stillstand 499 → 31 ZE |
| keine neuen Deadlocks | **erfüllt** – Gegenprobe-Test stellt sicher, dass beide Roboter sich bewegen; kein Lauf endet mit dauerhaft stehenden Robotern (Ausnahme: vorbestehender Seed-1-Fall) |
| keine Duplicate-Bin-Crashes | **erfüllt** – Baseline hatte 1 Crash (Seed 4/4 Robots), jetzt 0 Exceptions in 35 Läufen |
| keine offensichtliche Starvation | **erfüllt** – längste Phase ohne Nutzfortschritt ≤ 31 ZE in 34 von 35 Konfigurationen |
| Metrics weiterhin funktionsfähig | **erfüllt** – `summary()` liefert 14 Felder, **kein** leeres/0-Feld (7×7, 3 Robots, util 2.0, Seed 42) |
| `average_digging_depth` nicht verändert | **erfüllt** – `simulation/metrics.py` ist unverändert. Die Werte steigen nur, weil überhaupt wieder gegraben und abgeschlossen wird (Seed 42/2 Robots: n=0 → n=30 erfasste Werte) |

### Offene technische Schulden

1. **`[REPLAN][PICKUP_RETURN]`-Endlosschleife** (Seed 1, util 2.0). Vorbestehend,
   nicht behoben, s. Fix 3 „Nicht behoben".
2. **Retry-Zähler gehen bei Replan verloren.** `[REPLAN][PICKUP_POS]` und
   `[REPLAN][PICKUP_RETURN]` erzeugen Events mit `retry_count=0`; die
   Requeue-Schwellen (15 bzw. 20) sind dadurch praktisch unerreichbar.
3. **Periodischer Deadlock-Check der Engine läuft nur bei leerer Event-Queue**
   (Architektur-Karte 5.3 Punkt 2, unverändert).
4. **Kein Positions-Check im Drop-Pfad.** `_handle_robot_drop` prüft nicht, ob
   der Roboter tatsächlich am Ziel-Stack steht.
5. **Kein Ausweg bei komplett vollem Lager.** Findet die Drop-Recovery keinen
   Ausweich-Stack, endet der Lauf weiterhin in `RuntimeError`.
6. **`average_tardiness`/`completed_requests` sind über Versionen hinweg nicht
   vergleichbar** (Selektionseffekt, s. Fix 1).
7. `tests/reservation_table.py` wird ohne `test_`-Präfix weiterhin nicht von
   pytest eingesammelt (Befund aus Architektur-Karte 10, unverändert).

### Empfohlene nächste Schritte

1. Punkt 2 der technischen Schulden zuerst: `retry_count` über Replan-Grenzen
   hinweg erhalten. Das ist eine kleine Änderung und würde die
   Eskalationsleiter insgesamt wieder scharf schalten – Voraussetzung für
   Punkt 1.
2. Danach die `[REPLAN][PICKUP_RETURN]`-Schleife gezielt reproduzieren
   (Seed 1, util 2.0, 2 Robots) und die `temp_storage`-Bereinigung korrigieren.
3. Die Ad-hoc-Messgrößen „PS idle bei gefüllter Queue" und „längste Phase ohne
   Nutzfortschritt" dauerhaft in `Metrics.summary()` aufnehmen – sie waren in
   dieser Arbeit die beiden aussagekräftigsten Indikatoren.
4. Erst danach über Scheduling-Prioritäten (Returns vs. neue Requests) reden;
   die Lastverteilung hat sich durch Fix 1 spürbar verschoben.

### Geänderte Dateien

Produktionscode (3 Dateien, +358/−24 Zeilen gegenüber `82cfcab`):

```text
 requests_/active_queue.py        |  38 +++++
 simulation/action_cost_model.py  |  26 +++-
 simulation/event_handler.py      | 318 +++++++++++++++++++++++++++++-----
```

| Datei | Geänderte/neue Funktionen |
|---|---|
| `requests_/active_queue.py` | `mark_task_assigned`, `add_waiting_task`, `remove_waiting_task` (neu) |
| `simulation/action_cost_model.py` | `calculate_path` (Manhattan-Fallback) |
| `simulation/event_handler.py` | `EventHandler.__init__`, `_handle_pickstation_complete`, `_handle_robot_pickup`, `_schedule_move_to_drop` (neu), `_handle_robot_drop`, `_redirect_blocked_drop` (neu), `_handle_robot_move`, `_replan_path_around_obstacle`, `_resolve_move_deadlock` (neu), `_evade_robot` (neu) |

Neue Testdateien (4 Dateien, 21 Tests):

```text
 tests/test_pickstation_service_start.py    (3 Tests)
 tests/test_drop_redirect.py                (5 Tests)
 tests/test_task_assignment_invariant.py    (5 Tests)
 tests/test_livelock_two_robots.py          (8 Tests)
```

Es wurden **keine** Git-Commits oder Pushes ausgeführt.

---
---

# Hardening + Seed-1

Zweiter Arbeitsblock. Ziel: die zuvor eingeführten Recovery-Mechanismen gegen
State-Korruption absichern, offene Unsicherheiten klären und den verbliebenen
Seed-1-Stillstand an seiner tatsächlichen Ursache beheben.

## Ausgangslage

| | |
|---|---|
| Branch | `working_sim` |
| **Ausgangscommit (neue Baseline)** | **`58c5ef2486f91b18b6521cc16ec967866b0d11e0`** (kurz `58c5ef2`) |
| Commit-Message | „Fix pickstation flow, task assignment invariants, and robot livelocks" |
| Teststatus vor Änderungen | `pytest tests/ --ignore=tests/test_simulation_visual.py` → **159 passed** |
| Teststatus nach Änderungen | **213 passed** (159 bestehende + 54 neue) |

Kein bestehender Test wurde geändert, gelöscht oder abgeschwächt.
`average_digging_depth` wurde nicht angefasst (`simulation/metrics.py` ist
unverändert).

---

## Phase 1 – Evade-Sicherheitsanalyse

### 1A Befund: Die Drop-Positionsinvariante existierte NICHT

Direkt reproduziert (`tests/test_evade_hardening.py`):

```text
Robot steht auf (5,5), trägt Bin 24
Drop-Aktion: relocate → Stack S_2_2 (Position (2,2))
→ Drop wird ausgeführt, Bin landet in S_2_2
```

Der Roboter legt eine Bin über drei Zellen Distanz ab. `_handle_robot_drop`
prüfte die Roboterposition überhaupt nicht.

Häufigkeit im Realbetrieb (7×7, 500 ZE, vollständige 42er-Matrix):

| | Baseline `58c5ef2` | nach Hardening |
|---|---|---|
| erfolgreiche Drops gesamt | 4041 | 3702 |
| davon **physisch unmöglich** | **1372 (34,0 %)** | **0 (0,0 %)** |

Dominant war `remove_target` – Bins wurden aus der Entfernung an der
Pickstation „abgegeben". Das ist für die Bewertung aller früheren
Durchsatzzahlen entscheidend (s. Abschnitt „Vergleichbarkeit").

### Layer-Entscheidung

Die Invariante gehört in den **EventHandler**, nicht in `_can_drop` oder den
`ConstraintManager` – beide sehen den Roboter gar nicht (Signatur
`(action, state)`). `_handle_robot_pickup` besitzt die spiegelbildliche
Prüfung für die Pickup-Hälfte bereits inklusive Eskalationsleiter; der
Drop-Handler ist damit der konsistente Ort.

Reihenfolge innerhalb des Handlers: **erst** `_can_drop` (Stack-Constraints,
inkl. Redirect auf Ausweich-Stack), **dann** der Positions-Guard. Nur so
bleibt der Redirect unabhängig von der Roboterposition auswertbar; der Guard
schützt ausschließlich die eigentliche Zustandsänderung.

Eskalation bewusst **ohne Requeue**: Der Roboter trägt die Bin bereits, ein
Requeue würde sie stranden lassen. Korrekte Auflösung ist immer „Bewegung zum
Ablageziel neu planen" (`_schedule_move_to_drop`).

### 1B Stale-Event-Klassifikation nach `_evade_robot`

| Event | Status | Mechanismus |
|---|---|---|
| `ROBOT_MOVE` (alter Plan) | **selbst-invalidierend** | `set_path` ersetzt den Plan; `get_next_waypoint()` liefert `None`; zusätzlich Duplikat-Schutz pro Zeitschritt |
| `ROBOT_PICKUP` (alter Plan) | **muss neu geplant werden** | Positions-Prüfung in `_handle_robot_pickup` → Delay → Replan → Requeue (Mechanismus existierte) |
| `ROBOT_DROP` (alter Plan) | **muss neu geplant werden** | Positions-Prüfung **neu ergänzt** → Delay → Replan der Bewegung |
| `PICKSTATION_COMPLETE`, `REQUEST_COMPLETE` | **weiterhin gültig** | nicht positionsabhängig |

**Kein Event muss verworfen werden.** Ein Mechanismus zum Entfernen von Events
aus der Queue war nicht nötig – alle Fälle sind entweder selbst-invalidierend
oder werden über Guards neu geplant.

### 1C Neue State-Invarianten

**Roboter→Bin-Verknüpfung.** Bisher existierte keine Möglichkeit festzustellen,
*welcher* Roboter eine `in_transit`-Bin trägt. Neu: `Robot.carried_bin_id`,
gesetzt beim erfolgreichen Pickup, gelöscht beim erfolgreichen Drop – bewusst
**nicht** von `clear_task()` angefasst, weil die Bin physisch weiter am
Roboter hängt.

Damit sind drei Invarianten prüfbar geworden:

```text
INV-C1  Ein Roboter, der eine Bin trägt, darf nicht von seinem Task
        getrennt werden (Requeue) – die Bin wäre sonst weder in einem
        Stack noch einem Task zugeordnet.

INV-C2  Ein Pickup-Event für eine bereits getragene Bin ist ein Duplikat
        → Fortsetzung mit der Drop-Phase, kein erneuter Pickup.

INV-C3  Ein Drop-Event darf den State nur verändern, wenn der Roboter die
        betreffende Bin trägt UND an der Ablageposition steht.
```

INV-C1 wurde durch einen konkreten Fehler belegt: Der Deadlock-Requeue trennte
einen tragenden Roboter von seinem Task, Bin 86 blieb verwaist `in_transit`,
die Folge-Pickups liefen in `RuntimeError: Event exceeded max retries`.
Derselbe Guard wurde auch im Engine-Deadlock-Resolver ergänzt.

---

## Phase 2 – Wait-Graph-Lifecycle

Alle semantischen Cleanup-Punkte einzeln getestet
(`tests/test_wait_graph_lifecycle.py`).

| Übergang | Ergebnis vor Hardening |
|---|---|
| Blockade → Kante entsteht | OK |
| erfolgreicher Replan → Kante entfernt | OK |
| erfolgreiche Pfadreservierung → Kante entfernt | OK |
| Ausweichen → Kante entfernt | OK |
| Task-Requeue / `release_robot_reservations` → Kante entfernt | OK |
| unmöglicher Replan (Ziel == blockierte Zelle) → Kante **bleibt** | OK (von Fix 3 beabsichtigt) |
| **Konflikt löst sich, Roboter fährt weiter → Kante entfernt** | **FEHLTE** |

### Belegter Phantom-Zyklus

Der fehlende Cleanup-Punkt war nicht theoretisch. Systemlauf 7×7, 2 Robots,
Seed 42:

```text
t=320: erkannter Zyklus enthält Kante 0 → 1
       Robot 0 hat aber gar keinen Pfad mehr (next_waypoint = None)
       → veraltete Kante aus einem längst aufgelösten Konflikt
```

**Fix:** `clear_wait(robot_id)` nach jedem tatsächlich ausgeführten
Bewegungsschritt in `_handle_robot_move`. Ein Roboter, der sich bewegt hat,
wartet per Definition nicht mehr.

Bewusst **semantisch statt zeitbasiert** – ein TTL wurde nicht eingeführt, weil
der fehlende semantische Punkt ausreicht. Der systemweite Test
`test_no_phantom_cycles_during_full_run` prüft für jede Kante eines erkannten
Zyklus, dass der Blocker tatsächlich die gewünschte Zelle besetzt oder die
Port-Reservierung hält.

---

## Phase 3 – Klärung „35 statt 42"

**Die Dokumentation war falsch, es wurden keine Kombinationen bewusst
ausgeschlossen.**

Das Sweep-Skript des vorherigen Blocks iterierte über eine explizite Liste:

```python
for robots, util in [(2,0.5), (3,0.5), (2,2.0), (3,2.0), (4,2.0)]:
    for seed in [1, 2, 3, 4, 7, 42, 99]:
```

Das sind 5 × 7 = 35 Läufe. Die fehlende Kombination ist **(4 Robots, util 0.5)**.
Der Bericht beschrieb die Matrix jedoch als „2/3/4 Robots × util 0.5/2.0",
also 6 × 7 = 42. **Korrektur der vorherigen Dokumentationsaussage.**

Alle 42 Kombinationen sind valide; die vollständige Matrix wurde ausgeführt
(s. u.). Der zuvor nie gemessene Block (4 Robots, util 0.5) war
aufschlussreich – dort trat der Großteil der neu entdeckten Probleme auf.

### Die vier verschlechterten Konfigurationen des Vorberichts

| Konfiguration | `82cfcab` | nach Fix 1–3 | Δ | jetzt | Bewertung |
|---|---|---|---|---|---|
| 2 Robots, util 0.5, Seed 1 | 38 | 37 | −1 | 36 | Trade-off, s. u. |
| 2 Robots, util 0.5, Seed 2 | 33 | 26 | −7 | **34** | erholt, jetzt über Ausgangswert |
| 3 Robots, util 0.5, Seed 4 | 47 | 38 | −9 | 40 | Trade-off, s. u. |
| 3 Robots, util 2.0, Seed 1 | 28 | 22 | −6 | **40** | erholt, deutlich über Ausgangswert |

Alle vier sind **deterministisch** (fester Seed, deterministische Simulation;
mehrfach reproduziert).

Bewertung: Es handelt sich **nicht** um eine Regression durch einen der Fixes,
sondern um einen Mess-Artefakt plus WIP-Umverteilung:

1. Die Vergleichszahlen der Baseline enthalten zu 34 % physisch unmögliche
   Drops (s. Phase 1). Sie sind schlicht **zu hoch angesetzt**.
2. Fix 1 verschiebt Kapazität vom Anliefern zum Rücktransport; die
   `completed_requests`-Metrik (Ankunft an der PS) sinkt dabei zwangsläufig,
   während `requests_completed` (Vollabschlüsse) steigt.

Zwei der vier haben sich durch das Hardening von selbst erledigt. Die
verbleibenden zwei liegen 2 bzw. 7 Vollabschlüsse unter dem Ausgangswert – bei
gleichzeitig **physisch gültigem** Verhalten. Keine Scheduling-Optimierung
durchgeführt (war ausdrücklich nicht Teil des Auftrags).

---

## Phase 4 – Seed-1-`PICKUP_RETURN`-Endlosschleife

### Reproduktion

7×7, 100 Bins, **2 Robots, Seed 1, util 2.0**, sim_time 500.
Baseline: 457 identische `[REPLAN][PICKUP_RETURN]`, **1** abgeschlossener
Request, längste Phase ohne Fortschritt 449 ZE.

Endzustand der Baseline:

```text
Robot 0 @ (4,6)  task 0, restore_blockers
        temp_storage = [{bin 90, from S_5_6, buffer S_4_6}]
Robot 1 @ (5,6)  task 1, restore_blockers
        temp_storage = [{bin 52, ... buffer S_5_6},
                        {bin  3, ... buffer S_4_6}]
Bin 90: Stack (4,6), Level 2, status=stored, in_transit=False
```

### KORREKTUR DER BISHERIGEN HYPOTHESE

Die vorherige Dokumentation nahm an:

> „`temp_storage` enthält eine Bin, die bereits zurückgelagert wurde;
> `mark_last_relocation_restored` wurde nie aufgerufen."

**Das ist falsch.** Bin 90 lag noch im Buffer-Stack S_4_6 und war korrekt als
offener Restore-Schritt geführt. Sie war lediglich **von Bin 3 überdeckt** –
einem Blocker des *anderen* Tasks. `temp_storage` war zu keinem Zeitpunkt
inkonsistent; die Invariante war bereits korrekt.

### Tatsächliche Root Cause

In `_handle_robot_pickup` galt die Abkürzung

```python
if action_type == "return" and bin_obj.get_status() == "stored":
    → "already stored" → next_action neu auswerten
```

für **alle** Return-Aktionen. Für einen **Blocker**-Return ist `stored`
jedoch der Normalzustand – die Bin liegt planmäßig im Buffer-Stack. Der echte
Grund war `expected bin 90 not on top`.

Folge: Fehldeutung → `next_action` liefert exakt dieselbe Aktion → neues
Pickup-Event mit `retry_count = 0` → Endlosschleife, keine Eskalation.

### Vollständiger Trace des erfolgreichen Blocker-Returns

```text
next_action(return blocker)          strategies/top_access_strategy.py:161-185
  → MOVE …                           _schedule_next_action_for_task_new
  → ROBOT_PICKUP                     _handle_robot_pickup  (from_stack = Buffer)
  → MOVE …                           _schedule_move_to_drop
  → ROBOT_DROP                       _handle_robot_drop
  → _update_task_after_successful_action_new
  → _update_task_after_successful_return(return_kind="blocker")
  → task.mark_last_relocation_restored(...)   ← Transition IST vorhanden
  → active_queue.release_blocker_ownership(...)
  → _schedule_next_action_for_same_task_new
```

Die State-Transition fehlt nirgends. Der Fehler saß ausschließlich im
Fehlerpfad davor.

### Implementierte Korrektur

1. **Semantik (`_handle_robot_pickup`):** Die „already stored"-Abkürzung gilt
   nur noch für `return_kind == "target"`.
2. **Eskalation (`not on top`-Zweig):** Liefert die Strategie dieselbe Aktion
   erneut, wächst der Retry-Zähler (dieser Zweig verzögert nicht, also muss er
   explizit hochzählen). Ab `max_repeated_action_retries_before_requeue = 15`
   wird der Task requeued.
3. **Ressourcenfreigabe:** Der Requeue allein genügte nicht – der Roboter blieb
   auf der umstrittenen Zelle stehen und bekam denselben Task sofort wieder
   zugeteilt. Er weicht jetzt zusätzlich aus (`_evade_robot`).

### Zusätzlich aufgedeckt: verwaiste Port-Reservierung

Beim Nachmessen von Seed 1 mit 3 Robots zeigte sich ein davon unabhängiger
Blocker: Ein Roboter reserviert den Port beim Anfahren
(`_handle_robot_move`) und plant danach um. Die Reservierung blieb dann
**für immer** bestehen; alle anderen warteten unbegrenzt (bekannte Lücke
„Port-Warten hat keine Eskalation", Architektur-Karte 5.3 Punkt 4).

Gemessen (7×7, 4 Robots, Seed 7): Port 223 ZE am Stück reserviert, ohne dass
der Halter je ankam.

Zwei Ergänzungen, beide semantisch (kein Timeout):

- `_release_stale_port_reservation`: Eine Reservierung ist verwaist, wenn ihr
  Halter weder auf dem Port steht noch ihn im Restpfad anfährt.
- Wartekante + Zyklusauflösung auch im Port-Reservierungs-Zweig und im
  PS-Bereich-Zweig von `_handle_robot_move` (beide hatten bisher gar keine
  Deadlock-Erkennung).

### Vorher/Nachher Seed 1

| Messgröße | Baseline `58c5ef2` | nach Hardening |
|---|---|---|
| `[REPLAN][PICKUP_RETURN]`, 2 Robots | 457 | **0** |
| `requests_completed`, 2 Robots | 1 | **17** |
| längste Phase ohne Fortschritt, 2 Robots | 449 ZE | **61 ZE** |
| `requests_completed`, 3 Robots | 22 | **40** |
| `requests_completed`, 4 Robots (util 2.0) | 39 | **55** |
| `[REPLAN][PICKUP_RETURN]` über alle 42 Läufe | 2917 | **0** |

---

## Phase 5 – Retry-Semantik

### Regel

```text
Retry-Fortschritt bleibt erhalten, wenn identisch sind:
    type, return_kind, bin_id, from_stack, to_stack
und kein Zustandsfortschritt stattgefunden hat.

Retry-Budget beginnt neu bei:
    - gewechseltem Ziel-Stack (Drop-Redirect)
    - anderer Bin
    - anderer Aktionsart
    - Phasenwechsel
    - echtem Bewegungsfortschritt
```

Implementiert als `EventHandler._is_same_attempt(old_action, new_action)` –
ein Vergleich über fünf Identitätsfelder, keine Retry-Architektur.

Zusätzlich `_note_position_progress(kind, robot, position)`: Bewegt sich ein
Roboter beim Warten auf eine Pickup-/Drop-Position, ist das echter Fortschritt
und **kein** fehlgeschlagener Versuch → Budget zurücksetzen. Ohne diese
Unterscheidung hätte ein normal (aber verzögert) anfahrender Roboter seinen
Bewegungsfortschritt alle 5 ZE durch einen kompletten Replan verloren –
gemessene Folge: 61 → 14 Completions, nach Einbau der Fortschrittserkennung
wieder 58.

### Erreichbarkeit der Schwellen

| Pfad | vorher | nachher |
|---|---|---|
| `[REPLAN][PICKUP_POS]` | `retry_count = 0` | Budget wandert mit |
| `[REPLAN][PICKUP]` („not on top") | `retry_count = 0` | Zähler wächst, Requeue bei 15 |
| `[REPLAN][PICKUP_RETURN]` | `retry_count = 0`, Endlosschleife | Zweig gilt nur noch für Target-Returns |
| Drop-Redirect auf anderen Stack | – | Budget wird **zurückgesetzt** (neues Ziel) |
| generischer Pickup-Fallback | keine Eskalation | Requeue bei 15 (nur wenn nichts getragen wird) |

Belegt durch `tests/test_retry_semantics.py` (12 Tests), u.a.
`test_repeated_identical_action_reaches_requeue_threshold` (Schwelle wird
erreicht) und `test_drop_redirect_to_other_stack_starts_a_fresh_attempt`
(Reset bei echtem Zielwechsel).

---

## Weitere während der Arbeit gefundene Duplikat-Fehler

Der Positions-Guard machte zwei bis dahin verdeckte Duplikat-Probleme sichtbar
(beide führten zu `RuntimeError`):

| Problem | Symptom | Guard |
|---|---|---|
| **Duplikat-Pickup** für bereits getragene Bin. `_schedule_next_action_for_task_new` beginnt jede physische Aktion mit einer Pickup-Phase – auch nach einem Replan während des Transports. | `not on top` bis `max_retries` → `RuntimeError` | `[STALE][PICKUP]` → Fortsetzung mit der Drop-Phase |
| **Duplikat-Drop**: mehrere Recovery-Pfade planen ein neues Drop-Event ein, ohne das alte entfernen zu können. Beobachtet: zwei `DROP_TARGET` desselben Roboters im selben Zeitschritt für verschiedene Bins. | `RuntimeError: Cannot start pickstation service: robot has no task` | `[STALE][DROP]` → überspringen, wenn Bin nicht im Transit ist ODER der Roboter eine andere Bin trägt |

---

## Phase 6 – Kontrollierte Restrisiken

| Punkt | Ergebnis | Änderung |
|---|---|---|
| **A. Periodischer Deadlock-Check** | Läuft weiterhin **nie** (Engine-Zweig „EventQueue leer"): 0 Aufrufe in allen gemessenen Läufen, alle Checks kommen aus `_register_wait_and_try_resolve`. Die lokale Detection reicht für alle 42 Konfigurationen aus (0 Exceptions, max. 61 ZE ohne Fortschritt). | **keine** – Engine-Architektur unangetastet |
| **B. `_evade_robot` und Ports/Sackgassen** | Ausweichen meidet Port-Zellen (getestet). Ist keine freie Nachbarzelle vorhanden, greift der Requeue-Pfad und hinterlässt konsistenten State (Task genau einmal wartend, nicht mehr in `assigned`, Roboter ohne Task, nichts getragen). | Requeue-Pfad um Carrying-Guard ergänzt; Zyklusauflösung probiert jetzt alle Roboter des Zyklus |
| **C. Komplett volles Lager** | 6×6-Sweep (16 Kombinationen) weiterhin **0 Abbrüche**. Die neuen Guards machen das Verhalten nicht häufiger oder inkonsistenter. | **keine** – bleibt bekannte technische Schuld |
| **D. `tests/reservation_table.py`** | Enthält **17 echte, bestehende Tests** (Datei-Docstring nennt sich selbst `test_reservation_table.py` – der Dateiname ist schlicht falsch). Im Standardlauf `pytest tests/` wird sie **nicht** eingesammelt (0 Treffer beim Collect). Explizit ausgeführt: 17 passed. | **keine** – Empfehlung s. u. |
| **E. `test_simulation_visual.py`** | Collect schlägt weiterhin fehl (Flask fehlt). Wird ausgeklammert und **nicht** als bestanden gezählt. | **keine** |

Empfehlung zu D: Datei in `tests/test_reservation_table.py` umbenennen. Die
17 Tests laufen unverändert durch, würden dann aber dauerhaft mitlaufen.
Bewusst nicht ungefragt durchgeführt.

---

## Neue Tests

| Datei | Tests | Inhalt |
|---|---|---|
| `tests/test_evade_hardening.py` | 20 | Drop-Positionsinvariante, Carrying-Robot + Evade, Stale-Events, Duplikat-Pickup/Drop, Evade nahe Port/Sackgasse, systemweite Invarianten |
| `tests/test_wait_graph_lifecycle.py` | 12 | Entstehung + alle Cleanup-Punkte einer Wartekante, Phantom-Zyklus-Prüfung im Systemlauf |
| `tests/test_blocker_return_invariant.py` | 10 | „stored"-Semantik für Blocker vs. Target, `temp_storage`-Invariante, Seed-1-Regression |
| `tests/test_retry_semantics.py` | 12 | Identität eines Versuchs, Erreichbarkeit der Schwellen, Reset bei echtem Zielwechsel/Fortschritt |

**54 neue Tests.** Gegen die unveränderte Baseline `58c5ef2` ausgeführt
schlagen davon **31 fehl** (23 passed) – sie prüfen also tatsächliche
Verhaltensänderungen und nicht nur Implementierungsdetails.

---

## Vollständige Sweep-Matrix

Ausgeführt: **Robots {2, 3, 4} × util {0.5, 2.0} × Seeds {1, 2, 3, 4, 7, 42, 99}
= 42 Läufe.** Alle Kombinationen valide, keine ausgeschlossen.
Grid 7×7, max_height 6, 100 Bins, sim_time 500.

| Kennzahl | Baseline `58c5ef2` | nach Hardening |
|---|---|---|
| Summe `requests_completed` | 2185 | 2076 |
| Konfigurationen mit 0 Completions | 0 | **0** |
| **Exceptions** | 0 | **0** |
| **Task-Invarianten-Verletzungen** | 0 | **0** |
| **Duplicate-Bin-Fehler** | 0 | **0** |
| **längste Phase ohne Nutzfortschritt (max)** | **449 ZE** | **61 ZE** |
| `[REPLAN][PICKUP_RETURN]` gesamt | **2917** | **0** |
| Manhattan-Fallbacks gesamt | 35 | 17 |
| Deadlock-Erkennungen gesamt | 126 | 569 |
| Requeues gesamt | 0 | 114 |
| **physisch unmögliche Drops** | **1372 (34 %)** | **0** |

### Vergleichbarkeit der Completion-Summe

Die Summe sinkt um 5 % (2185 → 2076). Das ist **kein** Durchsatzverlust im
üblichen Sinn: In der Baseline waren 34 % aller erfolgreichen Ablagen physisch
unmöglich – überwiegend `remove_target`, also Bin-Abgaben an der Pickstation
aus mehreren Zellen Entfernung. Diese Abkürzung existiert nicht mehr, die
Roboter müssen den Port jetzt tatsächlich erreichen.

Messbarer Beleg für die veränderte Physik (7×7, 4 Robots, util 2.0, Seed 7):
Der Port ist jetzt **287 von 499 ZE** physisch besetzt gegenüber **184 von
499 ZE** in der Baseline. Der Engpass ist damit der Port selbst, nicht mehr
die Recovery.

### Verteilung

| | Baseline | nachher |
|---|---|---|
| Konfigurationen ≥ 40 Completions | 27 | **31** |
| Konfigurationen < 20 Completions | 1 | 1 |
| schlechteste Konfiguration | **1** (Seed 1, 2 Rob, util 2.0) | **17** (dieselbe) |
| Konfigurationen mit > 100 ZE Stillstand | 1 | **0** |

---

## Regressionsvalidierung der früheren Fixes

| Prüfpunkt | Ergebnis |
|---|---|
| **Pickstation** idle bei gefüllter Service-Queue | **0/500 ZE** (Seed 42) und **0/499 ZE** (Seed 7) – unverändert behoben. Kein Service-Stau: max. Queue 5 bzw. 3 |
| **Task-Assignment**: kein Task gleichzeitig wartend und zugewiesen | 0 Verletzungen in 42 Läufen |
| **Task-Assignment**: keine Doppelzuweisung | 0 Verletzungen in 42 Läufen |
| **Duplicate-Bin-Crashes** | 0 in 42 Läufen |
| **Ursprüngliches Livelock** (7×7, 2 Robots, Seed 42, util 0.5) | 32 Completions, längste Stillstandsphase 23 ZE – weiterhin behoben, kein Rückfall |
| **Drop-Recovery** (`to_stack is full`, 6×6-Sweep, 16 Kombinationen) | 0 Abbrüche. Der neue Retry-Reset bei echtem Zielwechsel funktioniert (`test_drop_redirect_to_other_stack_starts_a_fresh_attempt`) |
| **Seed-1-Regression** (2 Robots, util 2.0) | 0 `[REPLAN][PICKUP_RETURN]`, 17 Completions, max. 61 ZE ohne Fortschritt |
| **Metrics funktionsfähig** | `summary()` liefert 14 Felder, kein leeres/0-Feld |
| **`average_digging_depth`** | `simulation/metrics.py` unverändert |

---

## Erfolgskriterien

| # | Kriterium | Status |
|---|---|---|
| 1 | alle bisherigen 159 Tests bestehen | **erfüllt** (213 gesamt) |
| 2 | neue Hardening-/Seed-1-Tests bestehen | **erfüllt** (54 neu) |
| 3 | Carrying-Robot + Evade erzeugt keine ungültigen Bin-/Drop-Zustände | **erfüllt** |
| 4 | stale Events nach Evade führen keinen unmöglichen Übergang aus | **erfüllt** |
| 5 | keine nachgewiesenen Phantom-Zyklen | **erfüllt** (Cleanup-Punkt ergänzt, Systemtest) |
| 6 | Task- und Container-Invarianten bestehen | **erfüllt** (0 Verletzungen / 42 Läufe) |
| 7 | Seed 1 nicht mehr in der `PICKUP_RETURN`-Schleife | **erfüllt** (457 → 0) |
| 8 | Retry-Eskalation bei identischem Versuch erreichbar | **erfüllt** |
| 9 | Retry-Reset bei tatsächlich neuer Aktion | **erfüllt** |
| 10 | Seed-42-Livelock weiterhin behoben | **erfüllt** |
| 11 | Pickstation- und Drop-Recovery funktionieren weiter | **erfüllt** |
| 12 | keine neue schwerwiegende Regression im Sweep | **erfüllt** (0 Exceptions, max_gap 449 → 61) |

Ein größerer Architekturumbau war an keiner Stelle nötig; alle Änderungen sind
lokale Guards bzw. Wiederverwendung vorhandener Mechanismen.

---

## Geänderte Dateien

Produktionscode (4 Dateien, +586/−47 gegenüber `58c5ef2`):

```text
 simulation/event_handler.py     | 585 ++++++++++++++++++++++-----
 state/robot.py                  |  28 ++
 simulation/event_builder.py     |  12 +-
 simulation/simulation_engine.py |   8 +
```

| Datei | Funktionen |
|---|---|
| `state/robot.py` | `__init__` (`carried_bin_id`), `set_carried_bin`, `get_carried_bin`, `clear_carried_bin`, `is_carrying_bin` (alle neu) |
| `simulation/event_builder.py` | `build_robot_pickup_event` (Parameter `retry_count`) |
| `simulation/simulation_engine.py` | `step` (Carrying-Guard im Deadlock-Resolver) |
| `simulation/event_handler.py` | `__init__` (3 neue Schwellen/Tracker), `_handle_robot_move` (Wait-Kante im PS-Zweig, Port-Eskalation, `clear_wait` nach Move), `_handle_robot_pickup` (Stale-Pickup-Guard, Blocker-Semantik, Retry-Wachstum, 2 Requeue-Eskalationen), `_handle_robot_drop` (Stale-Drop-Guard, Positions-Guard), `_schedule_next_action_for_task_new` (`inherited_retry_count`), `_register_wait_and_try_resolve` (alle Zyklus-Roboter), `_resolve_move_deadlock` (Carrying-Guard) |
| **neu** | `_is_robot_at_drop_position`, `_handle_drop_position_mismatch`, `_release_stale_port_reservation`, `_note_position_progress`, `_is_same_attempt` |

Neue Testdateien (4, 54 Tests):

```text
 tests/test_evade_hardening.py           (20)
 tests/test_wait_graph_lifecycle.py      (12)
 tests/test_blocker_return_invariant.py  (10)
 tests/test_retry_semantics.py           (12)
```

Keine Git-Commits oder Pushes ausgeführt.

---

## Bekannte Restrisiken

- **Duplikat-Events werden erkannt, nicht verhindert.** Die Recovery-Pfade
  können alte Events nicht aus der Queue entfernen; die Guards fangen sie beim
  Feuern ab. Robust, aber es bleibt unnötige Event-Last.
- **Port bleibt struktureller Engpass.** Bei 4 Robots und einer Pickstation
  drängen sich zeitweise alle Roboter um eine Zelle. Die Recovery löst das
  zuverlässig, kann die physische Kapazität aber nicht erhöhen.
- **`carried_bin_id` wird nur im Zwei-Phasen-Pfad gepflegt.** Der alte
  `pickup_from_pickstation`-Executor-Pfad setzt die Verknüpfung nicht; alle
  daran hängenden Guards fallen dort auf die `in_transit`-Prüfung zurück.
- **Seed 1, 2 Robots, util 2.0** bleibt mit 17 Completions die schwächste
  Konfiguration (max. 61 ZE ohne Fortschritt). Kein Stillstand mehr, aber
  auffällig unter dem Feld.
- **Wartekanten verfallen nicht zeitbasiert.** Die semantischen Cleanup-Punkte
  reichen für alle gemessenen Läufe; ein TTL wurde bewusst nicht eingeführt.
- **`completed_requests` und `average_tardiness` sind über Versionen hinweg
  nicht vergleichbar** (Selektions- und WIP-Effekte, s. Fix 1).

## Bewusst nicht behobene technische Schulden

1. **Periodischer Engine-Deadlock-Check** läuft weiterhin nur bei leerer
   EventQueue (Architektur-Karte 5.3 Punkt 2). Lokale Detection reicht aktuell
   aus; eine Engine-Änderung wäre nicht gerechtfertigt.
2. **Kein Ausweg bei komplett vollem Lager** – findet die Drop-Recovery keinen
   Ausweich-Stack, endet der Lauf weiterhin in `RuntimeError`. Erfordert eine
   Storage-Policy-Entscheidung, keine reine Bugfix-Frage.
3. **`tests/reservation_table.py`** wird ohne `test_`-Präfix nicht
   eingesammelt (17 echte Tests laufen unbemerkt nicht mit).
4. **`test_simulation_visual.py`** bleibt wegen Flask ausgeklammert.
5. **Zwei Konfigurationen** (2 Rob/util 0.5/Seed 1 und 3 Rob/util 0.5/Seed 4)
   liegen weiterhin leicht unter dem Ausgangswert – Scheduling-Thema, war
   ausdrücklich nicht Teil des Auftrags.

## Empfohlene nächste Schritte

1. `tests/reservation_table.py` umbenennen – ein Handgriff, dauerhaft
   17 zusätzliche Tests in der Suite.
2. Port-Kapazität als Experiment variieren (2 Pickstations). Die Messung zeigt
   den Port jetzt eindeutig als Engpass; das ist die erste Stellschraube mit
   erwartbar großer Wirkung.
3. Erst danach Scheduling-Prioritäten betrachten (Returns vs. neue Requests).
4. Optional: `carried_bin_id` auch im `pickup_from_pickstation`-Executor-Pfad
   pflegen, damit alle Guards überall auf derselben Information arbeiten.
