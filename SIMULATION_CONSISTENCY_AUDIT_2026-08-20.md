# Simulation Consistency Audit

Phase 2 – Vollständiges Konsistenz- und Stress-Audit des gemeinsamen
Simulationskerns. **Reines Audit: es wurde kein Produktionscode geändert.**

Leitfrage: *Können wir den Simulationskern als konsistente und belastbare
Experimentplattform betrachten?*

---

## Baseline

| | |
|---|---|
| Branch | `working_sim` |
| **Commit** | **`7fa27fe6629971809ec8ffaea2943741a43207f4`** (kurz `7fa27fe`) |
| Commit-Message | „Harden robot recovery, enforce physical drops, and fix Seed-1 stalls" |
| Python | 3.10.12 |
| Referenzstrategie | `reordering_strategy = "LOFI"` (Config-Default) |
| Placement (2 Varianten geprüft) | `ORIGINAL` (Config-Default) und `RANDOM` (Experiment-Baseline laut `experiments/experiment_setup.md`) |
| Scheduler | `FIFO` (Default) |
| Strategievergleich | **nicht** Teil dieser Phase |

### Teststatus vor Änderungen

```text
collected : 230   (+ 1 Modul mit Collection-Error)
passed    : 230
failed    : 0
skipped   : 0
excluded  : 1 Modul – tests/test_simulation_visual.py
```

`tests/test_reservation_table.py` ist inzwischen korrekt benannt und läuft
regulär mit (17 Tests, alle grün).

`tests/test_simulation_visual.py` lässt sich **nicht** einsammeln:
`ModuleNotFoundError: No module named 'flask'`. Der Test wird ausdrücklich
**nicht** als bestanden gezählt. Kein Environment-Fix in dieser Phase.

### Neu angelegte Audit-Werkzeuge

| Datei | Zweck |
|---|---|
| `tests/audit_harness.py` | Wiederverwendbarer Invarianten-Harness. Umschließt Pickup/Drop/Move mit **reinen Beobachtern** (Original wird unverändert aufgerufen) und prüft den State nach Simulationsschritten. Kein `test_`-Präfix, da es Werkzeuge und keine Tests enthält. |

Alle Treiber-/Diagnoseskripte liegen außerhalb des Repositories im
Ausgabeordner der Session und verändern das Repo nicht.

---

## Audit-Invarianten

Geprüft pro Simulationsschritt (bei großen Läufen gesampelt):

**Bin-Invarianten** – jede Bin genau in einem Zustand: in genau einem Stack,
an genau einer Pickstation, oder in Transit bei genau einem Roboter.
Verboten: zwei Stacks, Stack+Transit, PS+Stack, nirgendwo, mehrere Träger,
Metadaten ≠ physische Lage.

**Robot-Carrying-Invarianten** – höchstens eine Bin je Roboter;
`carried_bin_id` verweist auf eine existierende, tatsächlich `in_transit`
befindliche Bin; keine getragene Bin zusätzlich im Stack; keine verwaisten
Transit-Bins; keine zwei Roboter auf derselben Zelle; `path_index` konsistent.

**Physische Aktionsinvarianten** – Zähler
`physically_invalid_pickups`, `physically_invalid_drops`,
`robot_position_collisions`, `invalid_moves`
(Schrittweite ≠ 1 oder außerhalb des Grids).

**Task-/Queue-Invarianten** – kein Task gleichzeitig wartend und zugewiesen;
kein Task bei mehreren Robotern; kein abgeschlossener Task erneut wartend;
`temp_storage` nur mit fachlich offenen Restores; Blocker-Ownership
konsistent; Batching ohne Duplikate.

**Pickstation-/Port-Invarianten** – Capacity, Slot-Buchhaltung, Queue ohne
Duplikate, kein Task gleichzeitig in Queue und Service, kein Bin an zwei
Stationen, `robot_on_port` deckt sich mit der physischen Position, kein Task
an zwei Stationen.

**Traffic-/Reservation-Invarianten** – Wait-Kanten eines erkannten Zyklus
müssen realen Blockaden entsprechen (Phantom-Zyklus-Erkennung); Port-
Reservierungen dürfen nicht dauerhaft von einem Halter gehalten werden, der
den Port weder besetzt noch anfährt.

**Fortschritt** – `max_no_progress_window` über die fachlichen Übergänge
(Target an PS, Service fertig, Target zurückgelagert, Request abgeschlossen);
zusätzlich längste Task-Wartezeit und Dauer dauerhaft blockierter Tasks.

---

## Testmatrix

Insgesamt **~190 auditierte Systemläufe**.

### 1 Pickstation (Stufe A)

Grid 7×7, max_height 6, 100 Bins, sim_time 500,
Robots {2,3,4} × util {0.5, 2.0} × Seeds {1,2,3,4,7,42,99} = **42 Läufe je Variante**.

| Variante | Läufe | Exceptions | Σ compl | 0-compl | max no-progress | invPickups | invDrops | Kollisionen | invMoves |
|---|---|---|---|---|---|---|---|---|---|
| A1 – LOFI/ORIGINAL | 42 | 0 | 2076 | 0 | 60 | **468** | 0 | 0 | **26** |
| A2 – LOFI/RANDOM | 42 | 0 | 2014 | 0 | 53 | **480** | 0 | 0 | **23** |

### 2 Pickstations (Stufe B)

Identische Matrix mit `num_pickstations = 2`.

| Variante | Läufe | Exceptions | Σ compl | max no-progress | invPickups | invMoves | PS_1 bedient |
|---|---|---|---|---|---|---|---|
| B1 – LOFI/ORIGINAL | 42 | 0 | 2097 | 64 | 506 | 3 | **0 in allen 42 Läufen** |
| B2 – LOFI/RANDOM | 42 | **1** | 1973 | 48 | 467 | 15 | **0 in allen 42 Läufen** |

### Größere Lager (Stufe C)

Geometrien vorab validiert (Stack-Anzahl, Kapazität, Füllgrad, Port-Lage,
Buffer-Zone, Roboter-Startpositionen):

| Konfiguration | Stacks | Kapazität | Bins | Füllgrad | Ports | Buffer-Zone |
|---|---|---|---|---|---|---|
| 7×7, h=6, 1 PS | 48 | 288 | 100 | 34,7 % | (0,3) | 4 Zellen |
| 12×18, h=6, 2 PS | 214 | 1284 | 1150 | **89,6 %** | (0,9), (11,9) | 8 Zellen |
| 20×30, h=8, 2 PS | 598 | 4784 | 4320 | **90,3 %** | (0,15), (19,15) | 8 Zellen |

Die 20×30-Werte decken sich exakt mit `experiments/experiment_setup.md`
(598 Stacks, 4784 effektive Kapazität, ~90 % Füllgrad). Roboter starten nie
auf einer Port-Zelle. **Alle drei Geometrien sind valide.**

Smoke (300 ZE) und Medium (1500 ZE) liefen ohne Exceptions; Bin-Bilanz in
allen Läufen vollständig.

| Medium 12×18, 5 Robots, 1500 ZE | 1 PS | 2 PS |
|---|---|---|
| Seed 1 | 198 | 167 |
| Seed 42 | 183 | 156 |
| Seed 99 | 224 | 203 |

### Long Runs (Stufe D)

| Lauf | Konfiguration | compl | max no-progress | Exceptions |
|---|---|---|---|---|
| LONG-1 niedrige Last | 12×18, 5 Rob, 2 PS, util 0.3, seed 42, 4000 ZE | 291 | 52 | 0 |
| LONG-2 typische Last | 12×18, 5 Rob, 2 PS, util 0.6, seed 42, 4000 ZE | 465 | 52 | 0 |
| LONG-3 hohe Last | 12×18, 5 Rob, 2 PS, util 2.0, seed 42, 4000 ZE | 195 | **2619** | 0 |
| LONG-4 schwächster Fall | 7×7, 2 Rob, 1 PS, util 2.0, seed 1, 4000 ZE | 333 | 53 | 0 |
| LONG-5 2 PS klein | 7×7, 4 Rob, 2 PS, util 2.0, seed 42, 4000 ZE | 569 | 19 | 0 |

### Finalnaher Lauf

20×30, h=8, 4320 Bins, 8 Robots, util 0.6, zipf 1.5, seed 42, 600 ZE:

| | 1 Pickstation | 2 Pickstations |
|---|---|---|
| `requests_completed` | **57** | **16** |
| `max_no_progress_window` | 53 | **191** |
| Replans | 59 | **1913** |
| Manhattan-Fallbacks | 0 | **136** |
| PS bedient | PS_0: 24 | PS_0: 7, **PS_1: 0** |
| Bin-Bilanz | vollständig | vollständig |
| Laufzeit | 23 s | 55 s |

Ein 3000-ZE-Lauf in dieser Größe war mit dem unveränderten Kern nicht
durchführbar (s. AUDIT-007).

---

## Gefundene Bugs

### AUDIT-001 — Pickup von der Pickstation ohne Positionsprüfung

**Schweregrad: BLOCKER** (physisch unmögliche Aktion)

*Szenario (minimal, deterministisch):* 6×6, h=4, 40 Bins, 2 Robots, 1 PS,
seed 42. Bin im Zustand nach `remove_target`-Drop
(`status=at_pickstation`, `in_transit=False`), Roboter auf (4,4),
Port auf (0,3). Pickup-Event `return/target` mit `from_stack=None`.

*Symptom:*

```text
vorher : status=at_pickstation in_transit=False carried=None   Roboter @(4,4)
nachher: status=at_pickstation in_transit=True  carried=24     Roboter @(4,4)
```

Der Roboter nimmt eine Bin über vier Zellen Entfernung von der Pickstation auf.

*Verletzte Invariante:* physische Aktionsinvariante (Pickup nur an der
tatsächlichen Pickup-Position).

*Root Cause (eingegrenzt):* In `EventHandler._handle_robot_pickup` steht die
Positionsprüfung ausschließlich im Zweig `if from_stack is not None:`.
Für Pickups von der Pickstation (`from_stack=None`) existiert **keine**
Positionsprüfung. `ConstraintManager._can_pickup_from_pickstation_with_reason`
prüft nur, ob die Bin an der Station liegt — die Roboterposition sieht es
nicht. Die spiegelbildliche Drop-Seite wurde in der Hardening-Phase
abgesichert, die Pickup-Seite für Ports nicht.

*Häufigkeit:* 467–506 Vorkommen je 42-Lauf-Matrix; in **jeder** getesteten
Größe und Konfiguration reproduzierbar.

---

### AUDIT-002 — Pathfinder plant Wege außerhalb des Grids

**Schweregrad: MAJOR** (verzerrt Wegzeiten und damit alle Durchsatzmetriken)

*Szenario:* 7×7, 3 Robots, 1 PS, util 0.5, seed 7, 500 ZE.

*Symptom:*

```text
t=429  robot 2 -> (-1, 3)
t=430  robot 2 -> (-1, 2)
t=431  robot 2 -> (-1, 1)
```

Geplanter Pfad: `[(-1,3), (-1,2), (-1,1), (0,1)]` — drei Zellen außerhalb
des 7×7-Grids.

*Root Cause (belegt):* `Pathfinder._is_valid_position` erlaubt explizit
`-5 <= x < 0` („Pickstations außerhalb links vom Grid"). Diese Annahme
stammt aus einer früheren Modellvariante; laut `Pickstation_Logik.md` und
der aktuellen Engine liegen Ports **im** Grid. Der Aufrufer ist
`_replan_path_around_obstacle`; die Reservierung dieser Zellen gelingt, weil
auch die `ReservationTable` Positionen bis ±5 außerhalb zulässt.

*Wirkung:* Roboter nehmen Abkürzungen durch nicht existierenden Raum.
Wegzeiten und damit Throughput/Tardiness werden verfälscht.

*Häufigkeit:* 3–26 Vorkommen je 42-Lauf-Matrix, in allen Größen.

---

### AUDIT-003 — Blocker-Bin wird Ziel eines anderen Tasks; `temp_storage` bleibt stehen

**Schweregrad: BLOCKER** (inkonsistenter Task-Zustand, permanenter Stillstand
eines Requests und dauerhafte Bindung eines Roboters)

*Szenario:* 7×7, 4 Robots, 1 PS, util 0.5, seed 42, LOFI/ORIGINAL, 500 ZE.

*Zeitlicher Ablauf (belegt):*

```text
t=1    Request 0 wird eingeplant, Ziel = Bin 82   (82 noch nicht reserviert)
t=15   Robot 1 lagert Bin 82 als BLOCKER von Task 1 aus: S_5_2 -> Buffer S_5_1
       task1.temp_storage = [{bin 82, from S_5_2, buffer S_5_1}]
t=22   register_blocker_ownership(82) für Task 1
t=29   Robot 0 nimmt Bin 82 als TARGET von Task 0 aus S_5_1
t=38   Bin 82 wird an der Pickstation abgegeben
t=65   Bin 82 wird von der Pickstation abgeholt
t=76   Bin 82 wird nach S_5_2 zurückgelagert (Originalstack)
...    task1.temp_storage enthält bis t=500 weiterhin {bin 82, buffer S_5_1}
```

*Symptom:* `TEMP_STORAGE_BIN_NOT_IN_BUFFER` – 455–1070 Meldungen je Matrix.
Task 1 bleibt bis Simulationsende in `restore_blockers`,
`has_blockers_to_restore()` ist dauerhaft True, `target_returned=False`.
Der zugeordnete Roboter bleibt gebunden.

*Root Cause (eingegrenzt):* Die Reservierungsprüfung wirkt nur in **einer**
Richtung. `get_all_reserved_bin_ids()` verhindert, dass ein *neuer* Task auf
eine bereits als Blocker geownte Bin startet. Es gibt aber keine Prüfung in
der Gegenrichtung: Eine Bin, die bereits **Target eines aktiven Tasks** ist,
darf trotzdem von einem anderen Task als Blocker ausgelagert werden. Wird sie
danach vom Target-Task regulär zurückgelagert, bleibt der Blocker-Eintrag im
`temp_storage` des anderen Tasks bestehen. Der vorhandene
Ownership-Transfer-Pfad (`Scheduler._try_schedule_opportunistic`) wird in
diesem Ablauf nicht durchlaufen (nachgewiesen: nur `register_blocker_ownership`,
kein `transfer`/`release`).

*Dauer:* bis zu 960 ZE dauerhaft blockierte Tasks (LONG-5); im 42er-Sweep
1–3 dauerhaft blockierte Tasks je Matrix.

---

### AUDIT-004 — Bin-Verlust durch Pickup bei bereits getragener Bin

**Schweregrad: BLOCKER** (Bin-Verlust)

*Szenario:* 7×7, 4 Robots, 1 PS, util 2.0, seed 42, LOFI/**RANDOM**, 500 ZE.

*Ablauf (belegt):*

```text
t=4    Robot 2 lagert Bin 30 aus S_5_5 aus
t=7    Bin 30 -> Buffer S_4_5
t=45..76  Robots 0, 1 und 2 planen ALLE die Aktion `return bin=30`
t=77   Robot 1 nimmt Bin 30 auf        -> carried_bin_id = 30
t=78   Robot 1 führt einen `return/target`-Pickup für Bin 99 aus
       -> carried_bin_id = 99, Bin 30 verliert ihren Träger
t=80   [STALE][DROP] robot=1 bin=30 (carried=99) -> Drop übersprungen
ab t=78 bis Simulationsende: Bin 30 ist in KEINEM Stack, an KEINER
        Pickstation und bei KEINEM Roboter (in_transit=True, stack=None)
```

*Bilanz am Ende:* 96 Bins in Stacks + 2 an der PS + 1 getragen = 99 von 100.

*Root Cause (eingegrenzt):* `_handle_robot_pickup` prüft nicht, ob der
Roboter bereits eine **andere** Bin trägt. In Kombination mit der fehlenden
Positionsprüfung aus AUDIT-001 (der zweite Pickup ist ein Pickstation-Pickup)
überschreibt der zweite Pickup die Trage-Verknüpfung; die erste Bin verwaist.

*Abgrenzung — ehrlich:* Auf `58c5ef2` (vor der Hardening-Phase) tritt in
derselben Konfiguration **kein** Bin-Verlust auf (0 Doppel-Pickups, Bilanz
100/100). Der in der Hardening-Phase eingeführte `[STALE][DROP]`-Guard
verhindert korrekt eine physisch unmögliche Ablage — wandelt das darunter
liegende Duplikationsproblem dabei aber von „falscher Drop" in
„dauerhaft verlorene Bin" um. Der Guard ist nicht die Ursache, aber er
verändert das Fehlerbild. Das gehört zur Bewertung dazu.

---

### AUDIT-005 — Zweite Pickstation wird nie genutzt

**Schweregrad: BLOCKER für das geplante Experimentdesign**

*Szenario:* Alle Konfigurationen mit `num_pickstations = 2`
(84 Matrixläufe + Smoke/Medium/Long/Final).

*Symptom:* `PS_1.total_tasks_processed == 0` in **jedem** Lauf
(eine einzige Ausnahme: 1 Task in LONG-5 über 4000 ZE).

*Root Cause (belegt, statisch + dynamisch):*

| Stelle | Verhalten |
|---|---|
| `EventHandler._get_drop_position_for_action("remove_target")` | liefert **hart** `state.pickstations[0].position` |
| `EventHandler._get_target_position_for_action("return", from_stack=None)` | liefert **hart** `state.pickstations[0].position` |
| `EventHandler._start_pickstation_service_and_release_robot` | reiht bei `get_nearest_pickstation(robot_position)` ein |

Da jede Anlieferung nach `pickstations[0]` geplant wird, steht der Roboter
beim Einreihen immer auf PS_0 — die „nächstgelegene" Station ist damit
zwangsläufig ebenfalls PS_0. PS_1 erhält nie Arbeit.
Zusätzlich beobachtet: 1 Fall von `pickup_at_wrong_station`
(t=113, Robot 3 holt an PS_1 ab, obwohl der Task PS_0 zugeordnet war) —
Cross-Station-Verwechslung ist also grundsätzlich möglich.

*Wirkung — messbar:* Die zweite Station bringt keinen Nutzen und **schadet**
messbar:

| | 1 PS | 2 PS |
|---|---|---|
| 12×18 Medium, Seeds 1/42/99 | 198 / 183 / 224 | 167 / 156 / 203 |
| 20×30 final, 600 ZE | **57** | **16** |
| 20×30 final, Replans | 59 | 1913 |

Erklärungsansatz (nicht abschließend untersucht): Die zweite Port-Zelle
erzeugt eine zusätzliche Buffer-Zone und wird vom `PortExitGuard` bei jeder
Pfadvalidierung berücksichtigt, ohne je Arbeit aufzunehmen. Ergebnis sind
massenhaft abgelehnte Pfade, Replans und Manhattan-Fallbacks.

**Konsequenz für das Experiment:** Ein Vergleich der drei Strategien mit
`num_pickstations = 2` würde de facto ein Ein-Stationen-System messen –
zusätzlich belastet durch die Nebenwirkungen der ungenutzten Station.

---

### AUDIT-006 — Nicht beendbarer Lauf (max retries)

**Schweregrad: BLOCKER** (Run bricht ab)

*Szenario (exakt):* 7×7, h=6, 100 Bins, **4 Robots, 2 Pickstations,
util 0.5, seed 3**, LOFI/**RANDOM**, sim_time 500.

*Symptom:*

```text
RuntimeError: Event exceeded max retries (20). action_type=return,
bin_id=29, time=479
```

Einziger Abbruch in 168 Matrixläufen. `max_retry_count` erreichte 20 –
die Eskalationsleiter greift in diesem Pfad nicht.

*Root Cause:* noch nicht eingegrenzt. Auffällig ist die Kombination
2 Pickstations + `RANDOM`-Placement; der Fehler trat in keiner
1-Pickstation-Konfiguration auf.

---

### AUDIT-007 — `_validate_bin_uniqueness` ist O(n²) und dominiert die Laufzeit

**Schweregrad: MAJOR** (verhindert die geplante Experimentgröße)

*Symptom:* Laufzeit pro Event:

| Konfiguration | ms/Event |
|---|---|
| 7×7, 100 Bins | 0,4 |
| 12×18, 1150 Bins | 24,8 |
| 20×30, 4320 Bins | **357** |

Hochrechnung 20×30: ~7,1 Events/ZE → **1000 ZE ≈ 42 min, 3000 ZE ≈ 126 min
pro Lauf**. Für 3 Strategien × mehrere Seeds nicht durchführbar.

*Root Cause (Profiler, eindeutig):* `SimulationEngine._validate_bin_uniqueness`
(Zeile ~410) verwendet `visible_bin_ids.count(bin_id)` in einer Comprehension
über alle Bins — O(n²). Im Profil: **8,19 s von 8,47 s Gesamtlaufzeit (97 %)**,
346 150 `list.count`-Aufrufe bei nur 300 Events. Die Prüfung läuft über
`_validate_runtime_state` nach **jedem** Event.

*Potenzial (gemessen, nur zur Quantifizierung):* Eine semantisch äquivalente
O(n)-Variante (Counter statt `count`) ergibt:

| | IST | O(n)-Variante | Faktor |
|---|---|---|---|
| 12×18 | 24,8 ms/Event | 1,5 ms/Event | 16,6× |
| 20×30 | 346 ms/Event | 6,0 ms/Event | **57,9×** |

3000 ZE bei 20×30 sinken damit rechnerisch von ~126 min auf ~2,2 min.
**Die eigentliche Simulationslogik ist schnell genug; nur diese
Debug-Validierung ist der Engpass.**

*Gegenprobe:* Ein Smoke-Lauf mit der Original-Validierung liefert exakt
dieselben Befunde (identische Verletzung bei t=86, PS_1=0). Die für die
großen Läufe verwendete Beschleunigung verdeckt nichts.

---

### AUDIT-008 — Bin behält `status = "at_pickstation"` während des Rücktransports

**Schweregrad: MINOR** (Modell-/Auswertungsklarheit)

Nach dem Abholen von der Pickstation gilt für die Bin gleichzeitig
`status == "at_pickstation"`, `in_transit == True` und
`carried_bin_id == bin_id`. Sie ist damit in naiven Auswertungen doppelt
zählbar (an der PS **und** getragen).

*Wirkung:* Keine Zustandskorruption, aber jede Bilanz über Bin-Status muss
eine Prioritätsregel anwenden. Betrifft potenziell auch
`Metrics`-Auswertungen, die auf `status` filtern.

---

### AUDIT-009 — Starvation bei hoher Last im größeren Lager

**Schweregrad: MAJOR** (verzerrt Ergebnisse, nicht nachweislich permanent)

*Szenario:* 12×18, 5 Robots, 2 PS, util 2.0, seed 42, 4000 ZE.

*Symptom:* `max_no_progress_window = 2619 ZE` — über 65 % der Laufzeit ohne
jeden fachlichen Fortschritt. Zum Vergleich: dieselbe Größe bei util 0.6
erreicht 52 ZE. Zusätzlich `stuck_max = 700 ZE` und
`longest_task_wait = 3993 ZE`.

Im 7×7-Referenzbereich lag das Maximum bei 60 ZE — dieses Verhalten wird
erst durch die größere Konfiguration sichtbar.

*Root Cause:* nicht eingegrenzt. Mitverursachend sind vermutlich AUDIT-003
(dauerhaft blockierte Tasks) und AUDIT-005 (2 PS unter Last).

---

## Ergebnisse nach Invariantengruppe

### Bin-/Robot-Invarianten

| Prüfung | Ergebnis |
|---|---|
| Bin in zwei Stacks | **0** Verstöße |
| Bin gleichzeitig Stack + Transit | **0** |
| Bin gleichzeitig PS + Stack | **0** |
| Bin von mehreren Robotern getragen | **0** |
| Bin-Metadaten ≠ physische Lage | **0** |
| Roboter trägt > 1 Bin | **0** (aber Überschreiben der Verknüpfung: AUDIT-004) |
| **Verwaiste Transit-Bin (Bin-Verlust)** | **422 Meldungen in 1 Lauf** → AUDIT-004 |
| Roboter-Positionskollisionen | **0** in allen ~190 Läufen |
| `path_index` außerhalb des Pfads | **0** |
| Bin-Bilanz am Laufende | in allen Läufen vollständig außer AUDIT-004 |

### Physische Aktionsinvarianten

| Zähler | Ergebnis | Erwartung |
|---|---|---|
| `physically_invalid_pickups` | **468 / 480 / 506 / 467** je Matrix | 0 → **verletzt** (AUDIT-001) |
| `physically_invalid_drops` | **0** in allen Läufen | 0 → erfüllt |
| `robot_position_collisions` | **0** in allen Läufen | 0 → erfüllt |
| `invalid_moves` | **26 / 23 / 3 / 15** je Matrix | 0 → **verletzt** (AUDIT-002) |

Die Drop-Seite ist seit der Hardening-Phase sauber — die Pickup-Seite für
Ports ist es nicht.

### Task-/Queue-Invarianten

| Prüfung | Ergebnis |
|---|---|
| Task gleichzeitig wartend und zugewiesen | **0** |
| Task bei mehreren Robotern | **0** |
| Duplikate in `waiting_tasks` | **0** |
| Abgeschlossener Task erneut wartend | **0** |
| Batching-Duplikate / Selbst-Batching | **0** |
| Blocker-Ownership ohne `temp_storage`-Eintrag | **0** |
| **`temp_storage` mit erledigtem Restore** | **455–1070 je Matrix** → AUDIT-003 |
| Dauerhaft blockierte Tasks | 1–3 je Matrix, bis 960 ZE |

### Event-/Retry-Invarianten

| Größe | 1 PS (A1) | 2 PS (B1) |
|---|---|---|
| stale MOVE-Events (Roboter ohne offenen Wegpunkt) | 6319 | 6425 |
| stale PICKUP-Events (`[STALE][PICKUP]`) | 6 | 0 |
| stale DROP-Events (`[STALE][DROP]`) | 8 | 0 |
| **stale Events, die trotzdem State ändern** | **0** | **0** |
| max `retry_count` | 19 | 14 |

Die in der Hardening-Phase eingeführten Guards funktionieren: Kein einziges
stale Event hat einen ungültigen Zustandsübergang ausgeführt. Die hohe Zahl
stale MOVE-Events ist konstruktionsbedingt (Events werden nicht storniert)
und ohne Wirkung.

Retry-Semantik: `max_retry_count` erreicht 14–20, die Requeue-Eskalation
greift (0–525 Requeues je Lauf). **Ausnahme:** In AUDIT-006 läuft der
Zähler bis 20 durch, ohne dass eine Eskalation greift.

### Traffic-/Reservation-Invarianten

| Prüfung | Ergebnis |
|---|---|
| Phantom-Wait-Kanten in erkannten Zyklen | **0** in allen Läufen |
| Dauerhaft verwaiste Port-Reservierung (> 50 Schritte) | **0** |
| Deadlock-Erkennungen | 0–65 je Lauf, Recovery greift |
| Manhattan-Fallbacks | 0–136 je Lauf (deutlich erhöht bei 2 PS) |

Die Wait-Graph-Bereinigung und die Port-Reservierungslogik aus der
Hardening-Phase halten dem Audit stand.

### Pickstation-/Port-Invarianten

| Prüfung | 1 PS | 2 PS |
|---|---|---|
| Capacity überschritten | 0 | 0 |
| Slot-Buchhaltung inkonsistent | 0 | 0 |
| Task gleichzeitig in Queue und Service | 0 | 0 |
| Bin an zwei Stationen bedient | 0 | 0 |
| Task an zwei Stationen | 0 | 0 |
| `robot_on_port` ≠ physische Position | 0 | 0 |
| Zwei Roboter auf derselben Port-Zelle | 0 | 0 |
| PS idle bei gefüllter Queue | 0 | 0 |
| **Zweite Station bekommt Arbeit** | – | **nein** → AUDIT-005 |

Die reine Zustandsbuchhaltung beider Stationen ist korrekt. Das Problem ist
nicht Korruption, sondern dass die zweite Station **nie adressiert** wird.

### Livelock-/Starvation-Ergebnisse

| Szenario | max_no_progress_window |
|---|---|
| 7×7, alle 168 Matrixläufe | ≤ 64 ZE |
| 12×18, util 0.3 / 0.6, 4000 ZE | 52 / 52 ZE |
| **12×18, util 2.0, 4000 ZE** | **2619 ZE** |
| 20×30, 1 PS, 600 ZE | 53 ZE |
| **20×30, 2 PS, 600 ZE** | **191 ZE** |

Kein reproduzierbarer *permanenter* Deadlock/Livelock in der Matrix.
Aber zwei Skalierungseffekte, die im 7×7-Referenzbereich unsichtbar bleiben.

### Metrics-Konsistenz

Geprüfte Plausibilitätsbeziehungen (7×7, drei Konfigurationen):

| Beziehung | Ergebnis |
|---|---|
| `requests_completed ≤ completed_requests` | erfüllt (53≤56, 72≤77, 35≤37) |
| `successful_requests ≤ completed_requests` | erfüllt |
| `len(target_bin_removals) == completed_requests` | erfüllt (exakt gleich) |
| `digging_depth`-Messungen == `remove_target`-Drops | erfüllt (40=40, 52=52, 30=30) |
| `ps_bins_processed ≥ ps_tasks_processed` | erfüllt |
| `requests_completed ≤ ps_bins_processed` | erfüllt (53≤56, 72≤74, 35≤37) |
| `summary()` liefert alle 14 Felder gefüllt | erfüllt |

**Wichtige Definitionsklärung:** `requests_completed` kann größer sein als
`pickstation.total_tasks_processed` (53 vs. 40). Das ist **kein** Fehler,
sondern Folge des Batchings: Ein Pickstation-Task bedient mehrere Requests
derselben Bin. Die passende Bezugsgröße ist `total_bins_processed`.

Keine Metrik-Inkonsistenz gefunden. Randbeobachtung ohne Bugcharakter:
`successful_requests` ist sehr niedrig (4/56, 8/77, 3/37) — nahezu alle
Requests überschreiten ihre Deadline. Das ist eine Parametrierungsfrage.

---

## Skalierungsbeobachtungen

1. **Laufzeit skaliert nicht mit der Modellgröße, sondern mit der
   Validierung** (AUDIT-007). Nach Behebung wären auch 20×30-Läufe in
   Minuten statt Stunden möglich.
2. **Fehlerklassen bleiben über alle Größen konstant.** AUDIT-001, -002
   und -003 treten von 7×7 bis 20×30 gleichermaßen auf; die Größe erzeugt
   keine neuen Korruptionsklassen.
3. **Neue Effekte erst ab mittlerer Größe:** Die extremen
   No-Progress-Fenster (AUDIT-009) und der 2-PS-Durchsatzeinbruch
   (AUDIT-005) sind im 7×7-Referenzbereich nicht erkennbar. Die bisherige
   Validierung auf 7×7 war dafür zu klein.
4. **Hoher Füllgrad senkt den Durchsatz stark:** 90 % Füllgrad bei 20×30
   ergibt 57 Completions in 600 ZE mit 8 Robotern. Das ist plausibel
   (tiefes Graben), sollte aber bei der Wahl der Simulationsdauer für die
   Experimente berücksichtigt werden.

---

## Experiment-Readiness

### Bewertung gegen die Kriterien

| Kriterium | Status |
|---|---|
| Vollständige Test-Suite grün | **erfüllt** (230 passed; `test_simulation_visual` nicht ausführbar und nicht gezählt) |
| Keine BLOCKER-Invariante verletzt | **NICHT erfüllt** – 4 BLOCKER |
| Keine Bin-Duplikation | erfüllt |
| Kein Bin-Verlust | **NICHT erfüllt** (AUDIT-004) |
| Keine physisch unmöglichen Pickups/Drops | **NICHT erfüllt** – Drops sauber, Pickups nicht (AUDIT-001) |
| Keine Task-Doppelvergabe | erfüllt |
| Keine verwaisten Port-Reservations | erfüllt |
| Kein reproduzierbarer permanenter Deadlock/Livelock | erfüllt für die Gesamtsimulation; **nicht** auf Task-Ebene (AUDIT-003) |
| 2 Pickstations funktionieren fachlich korrekt | **NICHT erfüllt** (AUDIT-005) |
| Größere Lagerkonfiguration läuft konsistent | erfüllt (Geometrie valide, Bilanz vollständig, keine Exceptions) |
| Mindestens ein finalnaher Long Run läuft durch | erfüllt (20×30, 600 ZE, 1 und 2 PS) |
| Metrics plausibel | erfüllt |
| Restrisiken dokumentiert | erfüllt |

### Urteil

```text
NOT_EXPERIMENT_READY
```

Begründung: Vier BLOCKER-Befunde betreffen die fachliche Aussagekraft
direkt.

- **AUDIT-005** ist für das geplante Design entscheidend: Mit
  `num_pickstations = 2` würde faktisch ein Ein-Stationen-System gemessen,
  zusätzlich verzerrt durch die Nebenwirkungen der ungenutzten Station
  (Durchsatz 57 → 16 im finalnahen Lauf).
- **AUDIT-001** erlaubt physisch unmögliche Aktionen und verkürzt Wegzeiten
  systematisch — genau die Größe, die zwischen den Strategien verglichen
  werden soll.
- **AUDIT-003** blockiert einzelne Requests dauerhaft und bindet Roboter.
  Das verzerrt Durchsatz und Tardiness richtungsabhängig von der Strategie
  (Relocation-intensive Strategien sind stärker betroffen — genau der
  Untersuchungsgegenstand).
- **AUDIT-004** verletzt die Massenerhaltung des Lagers.

Der Durchsatz ist ausdrücklich **kein** Gegenargument: Correctness geht vor
Throughput.

Positiv festzuhalten: Die in der Hardening-Phase eingeführten Absicherungen
halten dem Audit stand — keine Bin-Duplikation, keine Task-Doppelvergabe,
keine Positionskollisionen, keine ungültigen Drops, keine Phantom-Zyklen,
keine verwaisten Port-Reservierungen, und kein stale Event hat je einen
ungültigen Zustandsübergang ausgeführt.

---

## Empfohlene Reihenfolge vor Phase 3

| Priorität | Befund | Begründung |
|---|---|---|
| 1 | **AUDIT-005** | Entscheidet das Experimentdesign (1 vs. 2 Pickstations). Bis dahin sollte keine finale Parametrierung festgeschrieben werden. |
| 2 | **AUDIT-001** | Kleine, klar abgegrenzte Lücke; spiegelbildlich zur bereits vorhandenen Drop-Prüfung. |
| 3 | **AUDIT-004** | Hängt direkt an AUDIT-001 (fehlender „trägt bereits"-Guard). |
| 4 | **AUDIT-003** | Größerer Eingriff in die Reservierungs-/Ownership-Logik; braucht eine bewusste fachliche Entscheidung. |
| 5 | **AUDIT-007** | Keine Korrektheitsfrage, aber Voraussetzung für Läufe in Experimentgröße. Sehr kleiner Eingriff, sehr großer Effekt (58×). |
| 6 | **AUDIT-006** | Root Cause noch offen; nach 1–4 erneut prüfen, ob er weiterhin auftritt. |
| 7 | **AUDIT-002** | Verzerrt Wegzeiten; Behebung ist vermutlich das Streichen einer Altlast-Bedingung. |
| 8 | **AUDIT-009** | Nach 1–4 neu messen; ein Teil dürfte sich mit AUDIT-003 und -005 erledigen. |
| 9 | **AUDIT-008** | Kosmetisch/Auswertungsklarheit. |

Offene Frage an die Fachseite: Sollen zwei Pickstations tatsächlich Teil des
finalen Designs sein? Falls ja, ist AUDIT-005 zwingend zu beheben. Falls
nein, entfällt der wichtigste BLOCKER und der Weg zu `EXPERIMENT_READY` ist
deutlich kürzer.

---

## Reproduzierbarkeit

Alle Befunde sind mit festen Seeds reproduzierbar. Vollständige
Konfigurationen je Befund stehen in den jeweiligen Abschnitten. Allgemein
gilt für alle Läufe dieses Audits:

```text
reordering_strategy = "LOFI"
scheduler_strategy  = "FIFO"
enable_highway_system = False
enable_visualization  = False
bin_request_prob_strategy = "Uniform" (7x7) bzw. "zipf", zipf_parameter=1.5 (12x18, 20x30)
placement_strategy = "ORIGINAL" (A1/B1) bzw. "RANDOM" (A2/B2, Stufe C/D)
```

Es wurden **keine Git-Commits oder Pushes** ausgeführt und **kein
Produktionscode geändert**.

---
---

# Phase 2B – Experiment-Readiness Remediation

Behebung der experimentkritischen Correctness-Befunde aus Phase 2.

## Ausgangslage

| | |
|---|---|
| Branch | `working_sim` |
| **Ausgangscommit** | **`7fa27fe6629971809ec8ffaea2943741a43207f4`** (`7fa27fe`) |
| Python | 3.10.12 |
| Referenzstrategie | `reordering_strategy = "LOFI"`, `scheduler_strategy = "FIFO"` |
| Placement (beide Varianten geprüft) | `ORIGINAL` (Config-Default) und `RANDOM` (Experiment-Baseline) |
| Teststatus vorher | 230 collected / 230 passed / 1 Modul nicht einsammelbar |
| Teststatus nachher | **278 collected / 278 passed** / 1 Modul nicht einsammelbar |

`tests/test_simulation_visual.py` bleibt wegen fehlendem Flask nicht
einsammelbar und wird weiterhin **nicht** als bestanden gezählt.

**Fachliche Grundentscheidung (vorgegeben):** Zwei Pickstations sind fester
Bestandteil des Experimentdesigns. Die Multi-Pickstation-Semantik wurde daher
vollständig implementiert.

---

## AUDIT-005 — Echte Multi-Pickstation-Semantik

### Ausgangszustand

`PS_1.total_tasks_processed == 0` in allen 84 Läufen mit zwei Stationen.
Drei aktive Codepfade verwendeten hart `state.pickstations[0]`.

### Bestätigte Root Cause

Die Audit-Hypothese war korrekt und vollständig. Belegt durch statische Suche
und Laufzeitmessung:

| Stelle | Verhalten vorher |
|---|---|
| `_get_drop_position_for_action("remove_target")` | immer `pickstations[0].position` |
| `_get_target_position_for_action("return", from_stack=None)` | immer `pickstations[0].position` |
| `_start_pickstation_service_and_release_robot` | `get_nearest_pickstation(robot_position)` |

Da jede Anlieferung nach `pickstations[0]` geplant wurde, stand der Roboter
beim Einreihen immer auf PS_0 – die „nächstgelegene" Station war damit
zwangsläufig ebenfalls PS_0.

### Designentscheidung

**Auswahlzeitpunkt:** genau einmal, unmittelbar nach dem erfolgreichen
Target-Pickup aus dem Storage (`_handle_robot_pickup`, `action_type ==
"remove_target"`). Zu diesem Zeitpunkt steht der Roboter physisch am
Quellstapel und trägt die Bin – die Manhattan-Distanz ist damit fachlich
sinnvoll definiert.

**Manhattan-Regel:**

```text
distance(PS) = |robot.x - PS.x| + |robot.y - PS.y|
```

Die Station mit minimaler Distanz gewinnt. Auslastung darf eine eindeutig
nähere Station **nicht** verdrängen.

**`effective_load`:**

```text
effective_load(PS) = inbound + waiting_for_service + in_service
```

| Anteil | Quelle im Bestand |
|---|---|
| `in_service` | `pickstation.current_tasks` |
| `waiting_for_service` | `pickstation.queue` |
| `inbound` | Roboter, die einen Task dieser Station tragen, dessen Target die Station noch nicht erreicht hat |

**Beginn/Ende von `inbound`:** beginnt mit der Stationszuordnung beim
Target-Pickup; endet mit dem Target-Drop, weil `mark_waiting_at_pickstation()`
dann `target_at_pickstation = True` setzt und der Task in die Queue wandert.

**Vermeidung von Doppelzählung:** `inbound` filtert explizit auf
`target_at_pickstation is False`. Ein Task ist daher entweder inbound **oder**
in der Queue **oder** in Service – nie in mehreren Kategorien. Tasks mit
abgeschlossenem Service (`pickstation_completed`) belegen weder Queue noch
Kapazität und zählen nicht mehr. Es wurde **keine** Schattenbuchhaltung
eingeführt; alles wird aus vorhandenen Objekten abgeleitet.

**Tie-Break:** Bei vollständigem Gleichstand entscheidet der **Index in
`state.pickstations`** – stabil und deterministisch, keine Zufallsauswahl.
Bewusst nicht die Station-ID als String, weil `"PS_10" < "PS_2"`
lexikographisch falsch sortieren würde.

**Source of Truth:** `RobotTask.assigned_pickstation` (Station-ID).
Es gibt genau eine Stelle, an der geschrieben wird, und genau eine
Auflösungsfunktion `_resolve_assigned_pickstation(robot=…, task=…)`.

**Lifecycle:**

```text
Target erfolgreich aus Storage aufgenommen
   → _select_pickstation_for_target(robot)
   → task.assigned_pickstation = station.station_id        [entsteht]
   → Anfahrt, Drop, Service, Abholung lesen ausschließlich diesen Wert
   → Wert bleibt bis zum Abschluss des Tasks bestehen      [eingefroren]
   → wird beim nächsten remove_target-Pickup desselben Tasks neu gesetzt
```

Spätere Events finden die Zuordnung über `robot.current_task` bzw. den
übergebenen Task. `_get_drop_position_for_action` und
`_get_target_position_for_action` erhielten dafür optionale
`robot`/`task`-Parameter.

### Implementierung

| Datei | Funktion | Art |
|---|---|---|
| `simulation/event_handler.py` | `_effective_pickstation_load` | **neu** |
| | `_select_pickstation_for_target` | **neu** |
| | `_resolve_assigned_pickstation` | **neu** |
| | `_release_own_stale_port_reservations` | **neu** |
| | `_handle_robot_pickup` | Stationszuordnung beim Target-Pickup |
| | `_get_drop_position_for_action` | Kontextparameter, keine harte `[0]` |
| | `_get_target_position_for_action` | Kontextparameter, keine harte `[0]` |
| | `_start_pickstation_service_and_release_robot` | nutzt zugeordnete Station + Positionsprüfung |
| | `_handle_robot_move` | proaktive Freigabe eigener Port-Reservierungen |

### Zusätzlich gefunden und behoben

Im Re-Audit trat eine **verwaiste Port-Reservierung** auf (PS_0 51 Schritte
von einem Roboter gehalten, der PS_1 anfuhr). Der Halter gab die Reservierung
erst bei Kollision frei. Ergänzt: proaktive Freigabe nach jedem Move, wenn der
Roboter die Station weder besetzt noch im Restpfad anfährt.

### Tests

`tests/test_multi_pickstation.py` (13 Tests): näher an PS_0 / näher an PS_1 /
Distanz schlägt Last / Last-Tiebreak / inbound zählt / keine Doppelzählung /
Service beendet zählt nicht / vollständiger Gleichstand deterministisch /
Persistenz bei Lastwechsel / Return-Roboter fährt zur zugeordneten Station /
3 Systemläufe (MP-1, MP-6…MP-9, MP-11).

### Vorher/Nachher

Verteilung der Arbeit (7×7, 500 ZE, zwei Stationen):

| Konfiguration | vorher PS_0 / PS_1 | nachher PS_0 / PS_1 |
|---|---|---|
| 2 Rob, util 2.0, seed 42 | 33 / **0** | 20 / **15** |
| 4 Rob, util 2.0, seed 42 | 52 / **0** | 28 / **24** |
| 4 Rob, util 2.0, seed 99 | 58 / **0** | 32 / **17** |
| 3 Rob, util 0.5, seed 42 | – / **0** | 27 / **17** |

Entscheidungstypen (Summe über 8 Messläufe): Manhattan **269**,
Load-Tiebreak **23**, ID-Tiebreak **28**. Alle drei Kriterien sind real aktiv.

Durchsatz 1 PS vs. 2 PS (12×18, 5 Robots, 1500 ZE):

| Seed | 1 PS | 2 PS |
|---|---|---|
| 1 | 186 | **215** |
| 42 | 115 | **208** |

Vor Phase 2B war 2 PS durchgängig *schlechter* als 1 PS (z.B. 156 vs. 183) –
die Umkehr ist der direkte Beleg, dass die zweite Station jetzt arbeitet.

### Restrisiken

- Die Auswahl erfolgt rein distanzbasiert. Bei kleinen Grids mit vielen
  Robotern kann sich Arbeit an einer Station konzentrieren, weil Last eine
  nähere Station nicht verdrängen darf. Das ist die **vorgegebene** Regel und
  kein Defekt; eine ungleiche Auslastung ist ausdrücklich erlaubt.
- `ActionCostModel._pickstation_position()` verwendet für **Kostenschätzungen**
  weiterhin `pickstations[0]`. Das beeinflusst keine physische Routenwahl,
  kann aber Dauerabschätzungen bei zwei Stationen leicht verzerren.
  Dokumentierte technische Schuld.

---

## AUDIT-001 + AUDIT-004 — Physische Pickup-Invarianten

### Ausgangszustand

467–506 physisch unmögliche Pickups je 42-Lauf-Matrix; ein Bin-Verlust
(Bin 30, 422 Zeitschritte verwaist).

### Bestätigte Root Cause

Die Audit-Hypothese war korrekt:
Die Positionsprüfung in `_handle_robot_pickup` lag innerhalb des Zweigs
`if from_stack is not None:`. Pickups an der Pickstation (`from_stack=None`)
liefen völlig ungeprüft. Zusätzlich fehlte jede Prüfung, ob der Roboter bereits
eine andere Bin trägt.

### Fachliche Invarianten

```text
P-1  Robot steht physisch an der tatsächlichen Quelle der Bin
     (Stack-Position ODER die dem Task ZUGEORDNETE Pickstation).
P-2  Robot trägt vor dem Pickup keine andere Bin.
P-3  Duplikat-Pickup derselben, bereits getragenen Bin ist idempotent.
P-4  Ein Pickup-Event gehört zum aktuell gehaltenen Task des Roboters.
```

### Implementierung

- Positionsprüfung generalisiert: erwartete Position kommt jetzt aus
  `_get_target_position_for_action(action, robot=robot)` – derselben Quelle,
  die auch die Anfahrt plant. Damit gilt sie für Stack- **und**
  Pickstation-Pickups und respektiert die Stationszuordnung.
- Reihenfolge korrigiert: Der Positions-Guard steht **nach** `_can_pickup`.
  Sonst würden Staleness-Abkürzungen (z.B. „Target bereits zurückgelegt") nie
  erreicht, weil der Roboter erst zur Station fahren müsste. Gleiche
  Reihenfolge wie auf der Drop-Seite.
- Carrying-Guard mit Eskalation: Trägt der Roboter eine andere Bin, wird
  verzögert; ab `max_repeated_action_retries_before_requeue` wird das Event
  als fremd verworfen bzw. der eigene Task neu ausgewertet.
- Task-Zugehörigkeit (P-4): Ein Pickup-Event, dessen Request nicht zum
  aktuellen Task des Roboters gehört, wird verworfen.

### Hypothesen-Korrektur

Der Audit vermutete, `carried_bin_id` müsse im
`pickup_from_pickstation`-Executor-Pfad ergänzt werden. **Das wäre falsch
gewesen.** Die Analyse zeigt: Dieser Legacy-Pfad holt das Target *vor* dem
Restore der Blocker ab. Würde man dort `carried_bin_id` setzen, würden alle
folgenden Blocker-Pickups durch den (korrekten) Carrying-Guard blockiert und
der Task stallen. Der Pfad ist mit dem Ein-Bin-Modell strukturell
inkompatibel.

**Getroffener Designentscheid statt Umbau:** Der Legacy-Pfad wird abgesichert,
nicht angeglichen:
- Duplikat-Guard: Ist die Bin bereits `in_transit`, wird das Event verworfen.
  (Beobachtet: Der Pfad setzte das Transit-Flag einer Bin zurück, die die
  Zwei-Phasen-Pipeline gerade abholte.)
- Carrying-Guard: Trägt der Roboter bereits eine Bin, wird verworfen.
- Positionsprüfung: als regulärer „nicht ausführbar"-Grund, damit die
  vorhandene Eskalationsleiter greift statt eines eigenen Delay-Pfads.

Der Pfad feuert real (2× je 500 ZE in einer Konfiguration), pflegt aber
bewusst weiterhin kein `carried_bin_id`. **Offener Designentscheid:** Der
Legacy-Pfad sollte mittelfristig entfallen, weil die Zwei-Phasen-Pipeline das
Target ohnehin korrekt in der `RETURN_TARGET`-Phase von der Station holt. Das
ist ein Architekturschnitt und wurde hier bewusst NICHT durchgeführt.

### Selbst eingeführter und behobener Fehler

Der erste Entwurf des Duplikat-Guards kehrte **nach**
`_mark_bin_in_transit(True)` zurück und übersprang damit das Zurücksetzen –
Ergebnis war eine verwaiste Transit-Bin und ein wartender Roboter. Der Guard
wurde vor die Transit-Markierung verschoben.

### Tests

`tests/test_pickup_physical_invariants.py` (12 Tests): Positionsprüfung an der
Pickstation, Gegenprobe auf dem Port, falsche Station, Carrying-Guard
(Pickstation und Stack), Idempotenz, plus 6 Systemläufe.

### Vorher/Nachher

| Kennzahl (je 42-Lauf-Matrix) | vorher | nachher |
|---|---|---|
| `physically_invalid_pickups` (1 PS, ORIGINAL) | 468 | **0** |
| `physically_invalid_pickups` (1 PS, RANDOM) | 480 | **0** |
| `physically_invalid_pickups` (2 PS, ORIGINAL) | 506 | **0** |
| `physically_invalid_pickups` (2 PS, RANDOM) | 467 | **0** |
| verwaiste Transit-Bins / Bin-Verluste | 422 (1 Lauf) | **0** |
| Cross-Station-Pickups | 2–3 je Lauf | **0** |

---

## AUDIT-003 — Target-/Blocker-Ownership

### Ausgangszustand

455–1070 `TEMP_STORAGE_BIN_NOT_IN_BUFFER`-Meldungen je Matrix; 1–3 dauerhaft
blockierte Tasks, bis zu 960 ZE.

### Bestätigte Root Cause

Die Audit-Hypothese war korrekt und wurde präzisiert. Zeitliche Reihenfolge
(instrumentiert):

```text
t=1   Request 0 wird eingeplant, Ziel = Bin 82   (82 noch nicht reserviert)
t=15  Task 1 lagert Bin 82 als BLOCKER aus       (temp_storage-Eintrag)
t=22  register_blocker_ownership(82) für Task 1
t=29  Task 0 nimmt Bin 82 als TARGET auf
t=79  Bin 82 wird von Task 0 nach S_5_2 zurückgelagert
...   Task 1 führt Bin 82 bis t=500 als offenen Restore
```

Die Reservierungsprüfung wirkt nur in **einer** Richtung:
`get_all_reserved_bin_ids()` verhindert, dass ein neuer Task auf eine
blocker-geownte Bin startet. Es gibt keine Prüfung in der Gegenrichtung.
Der vorhandene Ownership-Transfer-Pfad (`_try_schedule_opportunistic`) wird in
diesem Ablauf nicht durchlaufen (nachgewiesen: nur `register`, kein
`transfer`/`release`).

### Fachlicher Contract

```text
C-1  Eine Blocker-Restore-Verpflichtung besteht nur so lange, wie die Bin
     wegen dieses Tasks im Buffer-Stack liegt.
C-2  Nimmt ein ANDERER Task die Bin regulär aus dem Buffer (weil sie sein
     Target ist), ist die Verpflichtung gegenstandslos und wird aufgelöst –
     Eintrag aus `temp_storage` UND globale Ownership.
C-3  Danach darf die Bin nicht erneut als offener Restore geführt werden.
C-4  Der Blocker-Task läuft anschließend normal weiter.
```

### Designentscheidung

Bewusst **nicht** gewählt: „Target-Bin darf niemals Blocker sein". Blocker
ergeben sich physisch aus dem Stapelinhalt; ein solches Verbot wäre nicht
erfüllbar, ohne Retrievals zu blockieren. Ebenfalls nicht gewählt: eine neue
globale Locking-Architektur.

Gewählt: **Ownership beim Übernehmen auflösen.** Das ist die kleinste
kohärente Lösung und nutzt die vorhandene `release_blocker_ownership`-Semantik.
Fachlich sauber, weil der übernehmende Task die Bin ohnehin wieder in einem
gültigen Stack ablegt.

### Implementierung

`simulation/event_handler.py`: neue Methode
`_release_foreign_blocker_obligation(robot, bin_id)`, aufgerufen nach jedem
erfolgreichen Pickup. Löst Eintrag und Ownership nur dann, wenn der Owner ein
**anderer** Task ist als der ausführende.

### Tests

`tests/test_blocker_target_ownership.py` (7 Tests): Übernahme löst
Verpflichtung, eigener Restore bleibt erhalten, 4 Systemläufe mit
Persistenzfenster, exaktes AUDIT-003-Szenario.

### Vorher/Nachher

| Kennzahl | vorher | nachher |
|---|---|---|
| `TEMP_STORAGE_BIN_NOT_IN_BUFFER` (je Matrix) | 455–1070 | **0** |
| dauerhaft blockierte Tasks | 1–3 je Matrix | **0** |
| max. Blockierdauer | 960 ZE | **0** |
| AUDIT-003-Szenario, Completions | 44 | **63** |

---

## AUDIT-002 — Pfade außerhalb des Grids

### Bestätigte Root Cause

Die Audit-Hypothese war korrekt. Drei Stellen enthielten Reste einer älteren
Modellgeneration mit Ports **neben** dem Grid:

| Stelle | vorher |
|---|---|
| `Pathfinder._is_valid_position` | zusätzlich `-5 <= x < 0` erlaubt |
| `ReservationTable._is_valid_position` | ±5 außerhalb erlaubt |
| `EventHandler._handle_robot_move` | `x < 0` galt als „PS-Bereich" |

`PortExitGuard` war bereits korrekt auf Grid-Grenzen beschränkt.

`Pickstation_Logik.md` ist verbindlich und eindeutig:

> „Die Port-Säule befindet sich vollständig innerhalb des Grids […]
>  Es existiert keine zusätzliche externe Übergabezone außerhalb des Grids."

### Implementierung

Alle drei Stellen auf reine Grid-Semantik zurückgeführt.

### Ausdrückliche Testkorrektur (keine Abschwächung)

Drei bestehende Tests kodierten das **alte** Modell und mussten daher
inhaltlich korrigiert werden:

| Test | vorher | nachher |
|---|---|---|
| `test_reservation_table.py::test_negative_x_allowed` | erwartete, dass `x=-1` reservierbar ist | umbenannt zu `test_negative_x_rejected`; zusätzlich `test_port_cell_inside_grid_is_reservable` |
| `test_pathfinder.py::test_path_to_pickstation` | Ziel `(-1, 2)` | Ziel `(0, 2)` – Port-Säule im Grid |
| `test_pathfinder.py::test_path_from_pickstation` | Start `(-1, 2)` | Start `(0, 2)` |

Zusätzlich neu: `test_path_outside_grid_is_impossible`.

Das ist **keine** Anpassung „damit es grün wird", sondern die Korrektur von
Tests, die eine überholte Fachregel festschrieben. Die geprüfte Fähigkeit
(Pfad zur/von der Port-Säule) bleibt vollständig abgedeckt.

### Tests

`tests/test_grid_bounds.py` (7 Tests): ReservationTable lehnt Außenpositionen
ab, Pathfinder-Bounds, Pfad bleibt im Grid, 4 Systemläufe.

### Vorher/Nachher

| Kennzahl (je 42-Lauf-Matrix) | vorher | nachher |
|---|---|---|
| `invalid_moves` (1 PS, ORIGINAL) | 26 | **0** |
| `invalid_moves` (1 PS, RANDOM) | 23 | **0** |
| `invalid_moves` (2 PS, ORIGINAL) | 3 | **0** |
| `invalid_moves` (2 PS, RANDOM) | 15 | **0** |

---

## AUDIT-007 — O(n²)-Laufzeitvalidierung

### Bestätigte Root Cause

Zwei quadratische Operationen in `_validate_bin_uniqueness`:
`bin_obj not in bins_in_stacks` (Listensuche je Bin) und
`visible_bin_ids.count(bin_id)` (Listenzählung je ID).

### Implementierung

Ersetzt durch Identitäts-Set bzw. `Counter`. **Semantik unverändert**, die
Prüfung läuft weiterhin nach jedem Event. Keine Abschaltung, keine
Ausdünnung der Prüffrequenz.

### Semantik-Regression

`tests/test_bin_uniqueness_validation.py` (7 Tests) – zuerst gegen die alte
Implementierung geschrieben und dort grün, danach unverändert gegen die neue:
gültiger Zustand akzeptiert, Bin in zwei Stacks erkannt, Stack + Pickstation
erkannt, fehlende Bin erkannt, Transit-Bin zählt als sichtbar, Transit + Stack
nicht doppelt gezählt, Validierung läuft weiterhin im Simulationspfad.

### Benchmark

| Konfiguration | vorher | nachher | Speedup |
|---|---|---|---|
| 7×7, 100 Bins | 0,4 ms/Event | **0,3 ms/Event** | 1,3× |
| 12×18, 1150 Bins | 24,8 ms/Event | **1,5 ms/Event** | **16,5×** |
| 20×30, 4320 Bins | 357 ms/Event | **6,2 ms/Event** | **57,6×** |

Gesamtlaufzeit der Testsuite: 56 s → **36 s**.
Ein 20×30-Lauf über 1500 ZE (15 114 Events) läuft jetzt in 92 s **inklusive**
vollständiger Audit-Instrumentierung; ohne Instrumentierung entsprechend
schneller. Vorher war er praktisch nicht durchführbar (~126 min für 3000 ZE).

---

## AUDIT-006 — Max-Retry-Abbruch

**Ergebnis: Folgefehler, ohne eigenen Fix verschwunden.**

Exakte Konfiguration erneut ausgeführt
(7×7, 4 Robots, 2 PS, util 0.5, Seed 3, LOFI/RANDOM, 500 ZE):

| | vorher | nachher |
|---|---|---|
| Ergebnis | `RuntimeError: Event exceeded max retries (20). action_type=return, bin_id=29` | **kein Abbruch** |
| Completions | 42 (bis Abbruch) | **52** |
| PS-Verteilung | PS_0 alles, PS_1 = 0 | PS_0 28 / PS_1 20 |

Ursächlich waren die Multi-Pickstation-Fehlleitung (AUDIT-005) und die
fehlenden Pickup-Guards (AUDIT-001/004).

### Korrektur der Severity-Tabelle

Der Phase-2-Gesamtbericht sprach von „4 BLOCKER", während AUDIT-006 im
Detailteil ebenfalls als BLOCKER geführt wurde. **Korrekt sind 5 BLOCKER**
(AUDIT-001, -003, -004, -005, -006). Die Zusammenfassung war falsch, nicht die
Einzelbewertung. Siehe Statustabelle am Ende dieses Abschnitts.

---

## AUDIT-009 — Starvation bei hoher Last

**Ergebnis: ohne eigene Scheduling-Änderung weitgehend aufgelöst.**

Konfiguration 12×18, 5 Robots, 2 PS, util 2.0, Seed 42, 4000 ZE:

| Kennzahl | vorher | nachher |
|---|---|---|
| `max_no_progress_window` | **2619 ZE** | **54 ZE** |
| `requests_completed` | 195 | **927** |
| dauerhaft blockierte Tasks | 1 (700 ZE) | **0** |
| PS-Verteilung | PS_0 50 / PS_1 **0** | PS_0 136 / PS_1 128 |
| Verletzungen | 3 Kategorien | **keine** |

Es wurde **keine** Scheduling-Optimierung vorgenommen. Die Verbesserung folgt
direkt aus der funktionierenden zweiten Station und der aufgelösten Ownership.

---

## AUDIT-008 — Bin behält `status = at_pickstation` beim Rücktransport

**Geprüft, unverändert, bleibt dokumentierte technische Schuld.**

| Frage | Antwort |
|---|---|
| Verursacht es falsche Metrics? | Nein. Die Metrik-Plausibilitätsprüfungen bleiben erfüllt; keine Metrik filtert auf `status == "at_pickstation"`. |
| Verursacht es falsche Audit-Bilanzen? | Nur bei naiver Zählung. Der Harness klassifiziert eindeutig (getragen > PS > Stack); die Bin-Bilanz stimmt in allen Läufen. |
| Leitet Produktionslogik daraus falsche Entscheidungen ab? | Nein. `_can_pickup` prüft für Pickstation-Returns `in_transit` und `stack is None`, nicht den Status. Die neue `effective_load` nutzt `target_at_pickstation` am Task, nicht den Bin-Status. |

Kein kosmetischer Umbau durchgeführt.

---

## Re-Audit

### Testsuite

```text
collected : 278   (+ 1 Modul mit Collection-Error)
passed    : 278
failed    : 0
skipped   : 0
excluded  : 1 Modul – tests/test_simulation_visual.py (flask fehlt)
```

Kein bestehender Test wurde abgeschwächt. Drei Tests wurden inhaltlich auf die
verbindliche Fachregel korrigiert (s. AUDIT-002), dokumentiert und mit
zusätzlichen Fällen ergänzt.

### Kleine vollständige Matrix

7×7, 100 Bins, sim_time 500, Robots {2,3,4} × util {0.5, 2.0} ×
Seeds {1,2,3,4,7,42,99}, je 42 Läufe pro Variante — **168 Läufe**.

| Kennzahl | A1 (1 PS, ORIGINAL) | A2 (1 PS, RANDOM) | B1 (2 PS, ORIGINAL) | B2 (2 PS, RANDOM) |
|---|---|---|---|---|
| Exceptions | 0 | 0 | 0 | 0 |
| Σ `requests_completed` | 1855 | 1748 | 2037 | 1837 |
| Konfigs mit 0 Completions | 0 | 0 | 0 | 0 |
| `max_no_progress_window` | 75 | 165 | 58 | 233 |
| `physically_invalid_pickups` | **0** | **0** | **0** | **0** |
| `physically_invalid_drops` | **0** | **0** | **0** | **0** |
| `invalid_moves` | **0** | **0** | **0** | **0** |
| `robot_position_collisions` | **0** | **0** | **0** | **0** |
| Bin-Verlust / -Duplikate / verwaiste Transit-Bins | **0** | **0** | **0** | **0** |
| Task-Invarianten-Verletzungen | **0** | **0** | **0** | **0** |
| Ownership-Verletzungen | **0** | **0** | **0** | **0** |
| stale Events mit State-Änderung | **0** | **0** | **0** | **0** |
| Phantom-Wait-Zyklen | **0** | **0** | **0** | **0** |
| verwaiste Port-Reservierungen | **0** | **0** | **0** | **0** |
| max `retry_count` | 15 | 14 | 14 | 15 |
| **Verletzungen gesamt** | **keine** | **keine** | **keine** | **keine** |

### Multi-Pickstation-Messung

Acht Messläufe (7×7, 2 Stationen, 500 ZE), je Station erfasst:

| Konfiguration | PS_0 assigned/tasks/bins/maxQueue/maxInbound/portOcc/util | PS_1 |
|---|---|---|
| 4 Rob, util 2.0, s42 | 29 / 28 / 37 / 1 / 2 / 191 / 39 % | 26 / 24 / 38 / 1 / 2 / 203 / 43 % |
| 4 Rob, util 2.0, s99 | 33 / 32 / 43 / 2 / 2 / 231 / 44 % | 18 / 17 / 21 / 1 / 2 / 107 / 23 % |
| 3 Rob, util 0.5, s42 | 27 / 27 / 28 / 1 / 2 / 205 / 29 % | 18 / 17 / 18 / 1 / 2 / 114 / 20 % |
| 4 Rob, util 0.5, s3, RANDOM | 29 / 28 / 33 / 1 / 3 / 203 / 33 % | 20 / 20 / 22 / 1 / 2 / 162 / 23 % |

Entscheidungen über alle Messläufe: Manhattan **269**, Load-Tiebreak **23**,
ID-Tiebreak **28**.

```text
cross_station_errors = 0
pickup_off_port      = 0
drop_off_port        = 0
not_nearest_errors   = 0
```

### Größere Lager

| Lauf | Ergebnis |
|---|---|
| Smoke 12×18, 1 PS, 300 ZE | 0 Verletzungen, Bilanz vollständig |
| Smoke 12×18, 2 PS, 300 ZE | 24 Completions, PS_0 4 / PS_1 6, 0 Verletzungen |
| Smoke 20×30, 1 PS, 300 ZE | 2 Completions, 0 Verletzungen |
| Smoke 20×30, 2 PS, 300 ZE | **19 Completions**, PS_0 3 / PS_1 9, 0 Verletzungen |
| Medium 12×18, 6 Läufe, 1500 ZE | 0 Verletzungen, Bilanz vollständig, 2 PS durchgängig besser |

### Long Runs

| Lauf | Konfiguration | compl | max_no_progress | Verletzungen |
|---|---|---|---|---|
| LONG-3 | 12×18, 5 Rob, 2 PS, util 2.0, seed 42, 4000 ZE | **927** | 54 | keine |
| LONG-4 | 7×7, 2 Rob, 1 PS, util 2.0, seed 1, 4000 ZE | 169 | 53 | keine |
| LONG-5 | 7×7, 4 Rob, 2 PS, util 2.0, seed 42, 4000 ZE | 520 | 26 | keine |

### Finalnaher Long Run

Konfiguration (Orientierung an `experiments/experiment_setup.md`,
**nicht final entschieden**):

```text
grid_width  = 20         num_robots   = 8
grid_depth  = 30         num_pickstations = 2
max_stack_height = 8     request_utilization = 0.6
bin_num     = 4320       bin_request_prob_strategy = "zipf", zipf_parameter = 1.5
random_seed = 42         simulation_time = 1500
reordering_strategy = "LOFI"   placement_strategy = "RANDOM"
```

| Kennzahl | 1 Pickstation | 2 Pickstations |
|---|---|---|
| Laufzeit (inkl. Audit-Instrumentierung) | 84,9 s | 92,5 s |
| verarbeitete Events | 13 780 | 15 114 |
| `requests_completed` | 180 | **224** |
| `max_no_progress_window` | 60 | **45** |
| invPickups / invDrops / Kollisionen / invMoves | 0 / 0 / 0 / 0 | 0 / 0 / 0 / 0 |
| PS bedient | PS_0 64 | PS_0 48 / **PS_1 36** |
| Bin-Bilanz (4320) | vollständig, 0 verloren | vollständig, 0 verloren |
| Verletzungen | **keine** | **keine** |

### Metrics-Konsistenz

Unverändert plausibel; keine neuen KPI-Definitionen eingeführt. Die in Phase 2
dokumentierte Definitionsklärung gilt weiter: `requests_completed` kann
`pickstation.total_tasks_processed` überschreiten, weil Batching mehrere
Requests je Pickstation-Task bedient; die passende Bezugsgröße ist
`total_bins_processed`.

---

## Status aller AUDIT-Befunde

| AUDIT-ID | Severity vorher | Severity nachher | Status | Beleg |
|---|---|---|---|---|
| AUDIT-001 | BLOCKER | – | **BEHOBEN** | `physically_invalid_pickups` 467–506 → **0** in 168 Läufen; `tests/test_pickup_physical_invariants.py` |
| AUDIT-002 | MAJOR | – | **BEHOBEN** | `invalid_moves` 3–26 → **0** in 168 Läufen; `tests/test_grid_bounds.py` |
| AUDIT-003 | BLOCKER | – | **BEHOBEN** | `TEMP_STORAGE_BIN_NOT_IN_BUFFER` 455–1070 → **0**; blockierte Tasks 1–3 → **0**; `tests/test_blocker_target_ownership.py` |
| AUDIT-004 | BLOCKER | – | **BEHOBEN** | verwaiste Transit-Bins 422 → **0**; Bin-Bilanz in allen Läufen vollständig |
| AUDIT-005 | BLOCKER | – | **BEHOBEN** | PS_1 0 Tasks → 15–36 Tasks je Lauf; 0 Cross-Station-Fehler; `tests/test_multi_pickstation.py` |
| AUDIT-006 | BLOCKER *(Zusammenfassung nannte fälschlich 4 statt 5)* | – | **BEHOBEN (Folgefehler)** | Seed 3 läuft durch, 52 Completions |
| AUDIT-007 | MAJOR | – | **BEHOBEN** | 20×30: 357 → 6,2 ms/Event (57,6×); Semantik-Tests |
| AUDIT-008 | MINOR | MINOR | **OFFEN (bewusst)** | geprüft: keine falschen Metrics, keine falschen Entscheidungen |
| AUDIT-009 | MAJOR | – | **BEHOBEN (Folgefehler)** | `max_no_progress_window` 2619 → 54 ZE; 195 → 927 Completions |

---

## Experiment-Readiness Gate

| Kriterium | Status |
|---|---|
| komplette Testsuite grün | **erfüllt** (278/278; `test_simulation_visual` nicht ausführbar und nicht gezählt) |
| echte Nutzung beider Pickstations | **erfüllt** |
| korrekte Manhattan-Auswahl | **erfüllt** (0 „not nearest"-Fehler) |
| korrekter Load-Tiebreak | **erfüllt** (23 Load-Tiebreaks real ausgelöst) |
| persistente Stationszuordnung | **erfüllt** (MP-5-Test + Systemläufe) |
| keine Cross-Station-Verwechslung | **erfüllt** (0) |
| keine physisch unmöglichen Pickups | **erfüllt** (0) |
| keine physisch unmöglichen Drops | **erfüllt** (0) |
| keine Bin-Verluste | **erfüllt** (0) |
| keine Bin-Duplikation | **erfüllt** (0) |
| keine verwaisten Transit-Bins | **erfüllt** (0) |
| keine Task-Doppelvergabe | **erfüllt** (0) |
| keine widersprüchliche Target-/Blocker-Ownership | **erfüllt** (0) |
| keine Pfade außerhalb des Grids | **erfüllt** (0) |
| keine verwaisten Port-Reservations | **erfüllt** (0) |
| keine Phantom-Wait-Zyklen | **erfüllt** (0) |
| kein reproduzierbarer Max-Retry-Abbruch | **erfüllt** (0 Exceptions in 168 + 15 Läufen) |
| kein reproduzierbarer permanenter Task-Stall | **erfüllt** (0 blockierte Tasks) |
| Metrics plausibel | **erfüllt** |
| finalnahe Größe praktisch ausführbar | **erfüllt** (57,6× schneller) |
| finalnaher längerer 2-Pickstation-Lauf erfolgreich | **erfüllt** (20×30, 1500 ZE, 0 Verletzungen) |

### Urteil

```text
EXPERIMENT_READY
```

Alle in Phase 2 gefundenen BLOCKER sind behoben und durch Regressionstests
sowie 183 auditierte Systemläufe belegt. Der verbleibende Befund AUDIT-008 ist
MINOR und nachweislich ohne Wirkung auf Metriken oder Entscheidungslogik.

---

## Verbleibende Risiken und technische Schulden

1. **Legacy-Pfad `pickup_from_pickstation`** ist mit dem Ein-Bin-Modell
   strukturell inkompatibel und pflegt bewusst kein `carried_bin_id`. Er ist
   abgesichert, aber redundant. **Empfohlener Designentscheid:** entfernen,
   sobald bestätigt ist, dass die Zwei-Phasen-Pipeline den Port-Pickup
   vollständig abdeckt.
2. **`ActionCostModel._pickstation_position()`** nutzt für Kostenschätzungen
   weiterhin `pickstations[0]`. Keine Auswirkung auf physische Routen, aber
   Dauerabschätzungen können bei zwei Stationen leicht verzerrt sein.
3. **AUDIT-008** (Bin-Status beim Rücktransport) bleibt offen.
4. **`max_no_progress_window` bei RANDOM-Placement** ist mit 165–233 ZE
   deutlich höher als bei ORIGINAL (58–75 ZE). Kein Correctness-Problem,
   aber vor dem Strategievergleich beobachtenswert – RANDOM ist die
   Baseline-Placement-Variante des geplanten Experiments.
5. **Periodischer Engine-Deadlock-Check** läuft weiterhin nur bei leerer
   EventQueue. Die lokale Detection reicht aus (0 Exceptions), unverändert.
6. **Kein Ausweg bei komplett vollem Lager** (Drop-Recovery ohne freien
   Stack). Unverändert bekannte Schuld.
7. **`test_simulation_visual.py`** weiterhin nicht ausführbar (Flask).

## Empfohlener nächster Schritt

Vor Phase 3: Kurze Vorabmessung der `max_no_progress_window`-Werte unter
`RANDOM`-Placement in Experimentgröße (20×30, 2 PS), um auszuschließen, dass
die Baseline-Strategie in der finalen Konfiguration systematisch benachteiligt
wird. Danach kann der Strategievergleich beginnen.

Es wurden **keine Git-Commits oder Pushes** ausgeführt.
