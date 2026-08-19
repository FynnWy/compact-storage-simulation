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
