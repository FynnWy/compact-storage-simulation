# Final Data Validity Audit

Datum: 2026-08-26
Gegenstand: `results/final/` (finale 50-Run-Kampagne)
Modus: **ausschliesslich lesend** — keine Rohdatei wurde geaendert, kein Run
neu gerechnet, keine Simulations-, Policy- oder Seed-Aenderung.

---

## 1. Scope

Diese Pruefung beantwortet genau drei Fragen:

1. Ist der finale Datenbestand strukturell und intern konsistent?
2. Sehen die in den finalen Logs beobachtbaren physischen Ablaeufe
   (Bewegungen, Tasks, Pickups, Drops, Pickstation, Retrievals) wie
   konsistente Lagerprozesse aus?
3. Sind die vier eingefrorenen Forschungsfragen mit diesen Daten
   **technisch** beantwortbar?

Ausdruecklich **nicht** Gegenstand: welche Policy besser ist, ob Unterschiede
signifikant sind, ob Ergebnisse ueberraschend sind, Rankings, Hypothesen.
Ebenfalls nicht Gegenstand: ein erneutes allgemeines Code-Audit der
Simulation.

Verwendete Quellen:

| Quelle | Rolle |
|---|---|
| `results/final/runs.csv` (50 Zeilen, 52 Spalten) | Run-Ebene |
| `results/final/retrievals.csv` (60 998 Zeilen) | physische Retrievals |
| `results/final/requests.csv` (117 775 Zeilen) | bediente Requests |
| `results/final/distribution.csv` (15 036 Zeilen) | RQ3/RQ4-Snapshots |
| `results/final/run_meta.json` (50 Eintraege) | Config, RNG-Streams, RQ4 |
| `results/final/campaign_status.json` (50 Eintraege) | Laufstatus |
| `results/final/logs/*.log` (50 Dateien, 8 718 321 Zeilen, 631 MB) | Lauflogs |
| `docs/FINAL_EXPERIMENT_FREEZE_2026-08-21.md` | eingefrorene Methodik |
| `docs/SCIENTIFIC_EXPERIMENT_READINESS.md` §2 | Wortlaut RQ1–RQ4 |
| `experiments/run_export.py`, `run_final_campaign.py`, `metrics/rq4_plateau.py` | Exportsemantik (gezielt gelesen) |

Alle Auswertungsskripte dieses Audits liefen ausserhalb des Rohdatenbestands
(`/tmp`). Die einzige neue persistente Datei ist dieses Dokument.

---

## 2. Dataset completeness

### 2.1 Matrix

| Kriterium | Soll | Ist | Ergebnis |
|---|---|---|---|
| Policies | 5 | 5 | OK |
| Seeds | 10 | 10 | OK |
| Runs | 50 | 50 | OK |
| eindeutige `run_id` | 50 | 50 | OK |
| jede Policy × Seed genau einmal | ja | ja | OK |
| unbekannte Policy/Seed | 0 | 0 | OK |
| doppelte `run_id` | 0 | 0 | OK |
| fehlende Runs | 0 | 0 | OK |
| Logdateien | 50 | 50 | OK |

Policies: `baseline_reference`, `RR+RR`, `LR+NR`, `ABC+ABC`,
`POPULARITY+POPULARITY`. Seeds: 1, 2, 3, 4, 7, 11, 13, 42, 99, 123. Das
entspricht exakt der eingefrorenen Matrix (Freeze §11 / C.5).

### 2.2 Pflichtfelder je Run

| Feld | Soll | Ist |
|---|---|---|
| `state` | `completed` | 50/50 |
| `error` | leer | 50/50 leer |
| `measurement_mode` | `time_window` | 50/50 |
| `t_measure_start` | 20000 | 50/50 |
| `t_final` | 30000 | 50/50 |
| `rq4_status` | vorhanden | 50/50 |
| `move_recovery_unresolved` | 0 | 50/50 |
| `task_deadlock` | 0 | 50/50 |
| `smoke` | false | 50/50 |
| `versuche` | 1 | 50/50 (kein Run musste wiederholt werden) |

`rq4_status`-Verteilung: 48 × `converged`, 2 × `converged_then_rediverged`
(`RR+RR/seed11`, `LR+NR/seed7`). Kein `not_converged`, kein unbekannter
Status. Alle drei erlaubten Werte sind zulaessig; die beiden redivergierten
Laeufe sind gueltige wissenschaftliche Ergebnisse und werden **nicht**
ausgeschlossen.

### 2.3 Unabhaengige Bestaetigung des Integritaetschecks

Der eingefrorene Check des Runners (`pruefe_integritaet` aus
`experiments/run_final_campaign.py`) wurde rein lesend gegen
`results/final/` ausgefuehrt (auf einer Arbeitskopie des Repos, ohne
Schreibzugriff auf die Rohdaten):

```text
matrix size: 50
BEFUNDE:     0
FINAL CAMPAIGN INTEGRITY CHECK: PASS
```

Zusaetzlich wurden alle Teilpruefungen dieses Checks unabhaengig
nachimplementiert und liefern dasselbe Ergebnis.

### 2.4 Abweichung: `t_end = 30003` in einem Lauf

`baseline_reference/seed99` hat `t_end = 30003`, alle anderen 49 Laeufe
`t_end = 30000`.

Ursache (aus `simulation/simulation_engine.py` belegt): die Hauptschleife
bricht bei `state.t >= config.simulation_time` ab. Springt die Uhr auf die
Zeit des naechsten Events, kann sie dabei ueber 30000 hinauslaufen, bevor die
Abbruchbedingung greift. Der Runner-Integritaetscheck prueft `t_final` und
`t_measure_start`, **nicht** `t_end` — die Abweichung ist deshalb keine
Verletzung der eingefrorenen Regel.

Wirkung auf die Daten, geprueft:

| Groesse | Befund |
|---|---|
| Retrievals mit `t_pickstation > 30000` | 0 (Maximum 29 989) |
| Request-Completions `> 30000` | 0 |
| Distribution-Snapshots `> 30000` | 1 (der letzte, bei t = 30003) |
| Messfenster [20000, 30000] | unberuehrt |
| KPI-Auswirkung | keine |

**Bewertung: technisch erklaert, wissenschaftlich folgenlos.** Kein
Ausschlussgrund.

---

## 3. Cross-file consistency

### 3.1 Referentielle Integritaet

| Pruefung | Ergebnis |
|---|---|
| unbekannte `run_id` in `retrievals.csv` / `requests.csv` / `distribution.csv` | 0 |
| Runs ohne Zeilen in einer der Detaildateien | 0 |
| `run_meta.json` deckt sich mit `runs.csv` | ja (50/50) |
| `campaign_status.json` vs. `runs.csv` (`physical_retrievals`, `rq4_status`, `move_stall_recoveries`) | 50/50 identisch |
| Doppelte auf Run-Ebene | 0 |

### 3.2 Messfenster

| Pruefung | Ergebnis |
|---|---|
| `sum(retrievals.in_measurement_window) == runs.measurement_retrievals` | 50/50 exakt |
| `in_measurement_window == (20000 <= t_pickstation <= 30000)` | 60 998/60 998 Zeilen korrekt |
| `measurement_retrievals <= physical_retrievals` | 50/50 |
| `len(retrievals-Zeilen) == physical_retrievals` | 50/50 exakt |

### 3.3 Rekonstruktion aller Run-KPIs aus den Detaildaten

Saemtliche Kennzahlen in `runs.csv` wurden aus `retrievals.csv` und
`requests.csv` nach der im Export (`summarise_run`) definierten Vorschrift
neu berechnet und Zeile fuer Zeile verglichen:

`bin_throughput`, `requests_completed`, `request_throughput`,
`mean_blocking_bins`, `p_beta_zero`, `mean_levels_from_top`,
`share_retrievals_top20pct`, `mean_dig_duration`, `mean_batch_size`,
`requests_evaluated`, `deadline_miss_rate`, `mean_tardiness`,
`median_tardiness`, `p95_tardiness`, `mean_flow_time`.

**Ergebnis: 0 Abweichungen ueber alle 50 Laeufe und alle 15 Kennzahlen.**
`runs.csv` ist damit vollstaendig aus den Rohzeilen reproduzierbar.

### 3.4 Pickstation-Zaehler

`retrievals_ps0 + retrievals_ps1` entspricht in **allen 50 Laeufen** exakt
`measurement_retrievals` (nicht `physical_retrievals`). Das deckt sich mit
dem Exportcode: die Stationszaehler werden ueber `basis` = Fenster-Retrievals
gebildet. Auch die Aufteilung je Station stimmt zeilenweise mit
`retrievals.csv` ueberein. Die im Auftrag genannte harte Gleichheit gilt also
gegen die Fenstergroesse — genau so, wie der Export sie definiert.

### 3.5 Batching-Konsistenz

Fuer jeden Lauf, im Fenster **und** ueber die gesamte Laufzeit:

```text
sum(retrievals.batch_size) == Anzahl Zeilen in requests.csv
```

**50/50 exakt** (Fenster: 20 556 Retrievals -> 41 934 Request-Completions;
gesamt: 60 998 -> 117 775). Ein physisches Retrieval erzeugt genau eine
Zeile in `retrievals.csv` und N Zeilen in `requests.csv`. Es gibt **keine**
doppelte physische Erfassung desselben Ereignisses.

### 3.6 Verknuepfung Retrieval <-> Request

Fuer alle 60 998 Retrieval-Zeilen wurde geprueft, ob die referenzierte
`request_id` im selben Lauf existiert, ob die `bin_id` uebereinstimmt und ob
`completion_time` der Request-Zeile gleich `t_pickstation` ist.

**0 Abweichungen.**

### 3.7 Formelkonsistenz der Request-Zeilen

Ueber alle 117 775 Zeilen:

| Pruefung | Ergebnis |
|---|---|
| `deadline == arrival_time + 240` | 0 Verstoesse |
| `lateness == completion_time - deadline` | 0 Verstoesse |
| `tardiness == max(0, lateness)` | 0 Verstoesse |
| `on_time == (tardiness <= 0)` | 0 Verstoesse |
| `completion_time >= arrival_time` | 0 Verstoesse |
| negative Zeit-/Zaehlwerte | 0 |

### 3.8 Common Random Numbers

Fuer jeden Seed wurde der Request-Strom (`bin_id`, `arrival_time`,
`deadline` je `request_id`) zwischen `baseline_reference` und jeder anderen
Policy verglichen.

```text
verglichene gemeinsame request_ids : 52 536
Abweichungen                       : 1
```

Die eine Abweichung ist der unter 3.9 beschriebene Befund. CRN ist damit
intakt; die gepaarte, seedweise Policy-Differenz ist tragfaehig.
`run_meta.json` weist fuer alle 50 Laeufe dieselben sechs benannten
RNG-Streams aus (`initialization`, `requests`, `service`, `relocation`,
`placement`, `robots`).

### 3.9 BEFUND F-1 — doppelte `request_id` in `POPULARITY+POPULARITY/seed1`

**Der einzige echte Datenbefund dieses Audits.**

```text
Lauf   : POPULARITY+POPULARITY__seed1
Datei  : results/final/requests.csv
request_id 459 kommt zweimal vor:
  459 | bin 3 | arrival 664 | deadline 904 | completion 12623
  459 | bin 0 | arrival 664 | deadline 904 | completion 12644
request_id 466 fehlt vollstaendig.
```

Beobachtbarer Kontext im Log (`POPULARITY+POPULARITY__seed1.log`):

```text
t=12629  [TRACE][PS_ASSIGN] robot=1 bin=0 task=466 -> PS_0
t=12644  [BLOCKED][PICKUP]  robot=1 action=return bin=3 reason=robot already carries bin 0
t=12644  [TRACE][DROP_TARGET] robot=1 bin=0 to=pickstation
t=12645  [STALE][PICKUP_TASK] robot=1 action=return bin=3 belongs to request 459,
                              robot holds task 462 -> drop foreign pickup event
```

Bin 0 gehoert laut `PS_ASSIGN` zu Task 466, wird aber in beiden CSVs unter
`request_id = 459` gefuehrt. Der Completion-Record uebernimmt `bin_id` aus
der Aktion und `request_id` aus dem uebergebenen Request-Objekt
(`Metrics.record_target_bin_at_pickstation`); in genau diesem Fall laufen
beide auseinander. Der zeitliche Zusammenfall mit dem verworfenen
Fremd-Pickup-Event fuer Bin 3 ist die plausibelste Erklaerung — **bewiesen
ist sie nicht**, dafuer waere ein instrumentierter Neulauf noetig, der hier
ausdruecklich ausgeschlossen ist.

Belegbare Wirkung:

| Aspekt | Befund |
|---|---|
| Zahl physischer Retrievals | unveraendert (zwei getrennte Retrievals, zwei Zeilen) |
| Zahl bedienter Requests | unveraendert (`sum(batch_size)` = Zeilenzahl, 3.5) |
| Zuordnung Retrieval <-> Bin <-> Zeit | korrekt (3.6) |
| Messfenster-KPIs | **keine** — beide Zeilen liegen bei t ≈ 12 6xx, also ausserhalb [20000, 30000] |
| CRN | 1 von 52 536 verglichenen Zuordnungen |
| Haeufigkeit | 1 von 117 775 Request-Zeilen, 1 von 50 Laeufen |

**Einordnung:** ein Label-Defekt, kein Zaehl- oder Mengendefekt. Keine der
eingefrorenen Kennzahlen ist betroffen. Die Zeile wurde **nicht** geloescht
und **nicht** korrigiert.

**Konsequenz fuer die Auswertung:** `request_id` darf innerhalb eines Laufs
nicht als eindeutiger Schluessel behandelt werden. Auswertungen auf
`requests.csv` sollten zeilenweise aggregieren (`groupby(run_id)` +
Zeilenzahl), nicht ueber `nunique(request_id)`.

---

## 4. Log health

Ueber alle 50 Logs (8 718 321 Zeilen):

| Marker | Dateien | Gesamt | Bewertung |
|---|---|---|---|
| `Traceback` | 0 | 0 | sauber |
| `Exception` | 0 | 0 | sauber |
| `ERROR` / `[ERROR` | 0 | 0 | sauber |
| `health_failed` | 0 | 0 | sauber |
| `[TASK_DEADLOCK]` | 0 | 0 | sauber |
| `MOVE_RECOVERY_UNRESOLVED` (alter toter Marker) | 0 | 0 | nicht aktiv benutzt |
| „keine Aufloesung moeglich" | 0 | 0 | sauber |

Klassifikation der regulaeren Diagnosemarker (keine Fehler, sondern
dokumentierte Betriebszustaende):

| Marker | Runs | Gesamt | Bewertung |
|---|---|---|---|
| `[DEADLOCK] Detected cycle` | 50 | 9 449 | normal |
| `[DEADLOCK] Resolved` | 50 | 9 449 | **normal — Detection == Resolution in jedem einzelnen Lauf** |
| `[DEADLOCK] evades` | 50 | 9 949 | normal |
| `[DEADLOCK][REQUEUE]` | – | 622 | normal |
| `[RECOVERY][MOVE_STALL]` | 45 | 817 | normal (siehe 7.2) |
| `[RECOVERY][PORT]` | 50 | 519 | normal |
| `[UNBURY]` | 20 | 109 | normal |
| `[REPLAN]*` | 50 | 394 275 | normal |
| `[STALE]*` | 47 | 1 016 | normal |
| `[OWNERSHIP][RELEASE]` / `[RELEASE][NO_ACTION]` | 50 | 2 048 | normal |
| `[REQUEUE][PICKUP_STUCK]` | – | 97 | normal (Retry-Limit 15, danach Requeue) |
| `[BLOCKED]*` / `[WARNING] blocked … retrying` | 50 | ~630 000 | normal (begrenzte Retry-Leiter) |
| `DROP_BURY` | 50 | 7 045 | normal |

Die Summe der Log-Marker `[RECOVERY][MOVE_STALL]` (817) stimmt exakt mit
`sum(runs.csv.move_stall_recoveries) = 817` und mit
`campaign_status.json` ueberein — die exportierten Health-Zaehler sind aus
dem Log verifiziert und nicht tautologisch (relevant fuer L-41/L-42).

**LOG_HEALTH_VALID = JA.**

---

## 5. Robot/task trajectory plausibility

### 5.1 Was die finalen Logs hergeben — und was nicht

Die finalen Logs enthalten **jeden einzelnen Grid-Schritt** jedes Roboters
(`[DEBUG][MOVE] t=… robot=… current_pos=(x,y) next_waypoint=(a,b)`,
6 271 936 Zeilen ueber alle 50 Laeufe). Eine Zell-fuer-Zell-Rekonstruktion
der Bewegung ist damit **moeglich** und wurde durchgefuehrt.

Nicht aus dem Log nachweisbar und deshalb hier **nicht** behauptet:

* die interne Reservierungs-/Zeitfenster-Logik des `TrafficManager`
  (nur ihre Wirkung ist sichtbar, nicht ihr Zustand),
* Kollisionsfreiheit als formale Invariante — belegt sind die
  Blockade-/Ausweichmeldungen und die Positionsfolgen, nicht eine
  vollstaendige Belegungsmatrix je Zeitschritt,
* die vollstaendige Task-Zustandsmaschine (nur die Uebergaenge, die ein
  Trace-Ereignis erzeugen),
* der Grund einzelner Scheduling-Entscheidungen.

### 5.2 Automatisierter Scan ueber alle 50 Runs

Aus jedem Log wurde eine Zustandsmaschine rekonstruiert (Roboterposition,
getragene Bin je Roboter, Aufenthaltsort jeder Bin) und gegen jedes Ereignis
gepruft.

| Pruefung | geprueft | Verstoesse |
|---|---|---|
| Move-Schritt ist 4-adjazent (Manhattan-Distanz 1) | 6 271 936 | **0** |
| Positionsfolge lueckenlos (keine Teleports; `current_pos` = vorherige Position oder vorheriges Wegziel) | 6 271 936 | **0** |
| Pickup, waehrend der Roboter bereits eine Bin traegt | 307 477 Pickups | **0** |
| Pickup einer Bin, die ein anderer Roboter traegt | 307 477 | **0** |
| Pickup-Quelle stimmt mit dem verfolgten Bin-Ort ueberein | 307 477 | **0** |
| Drop einer Bin, die der Roboter nicht traegt (`DROP_TARGET`/`RETURN`/`RELOCATE`) | 307 212 Drops | **0** |
| Pickup von der Pickstation, ohne dass die Bin dort liegt | alle `PICKUP_PS` | **0** |
| Zeitstempel nicht monoton | 50 Laeufe | **0** |
| Simulationsende erreicht | 50 Laeufe | 50/50 (`tmax` = 29 999) |
| `[TRACE][DROP_TARGET]`-Ereignisse vs. Zeilen in `retrievals.csv` | 60 998 vs. 60 998 | **exakt gleich** |

Keine Bin verschwindet, keine Bin wird doppelt gefuehrt, kein Roboter
befindet sich in einem widerspruechlichen Tragezustand.

**Nicht beweisbar und deshalb offen gelassen:** „verwaiste Tasks" und
„widerspruechlicher Taskzustand" lassen sich aus dem Log nur ueber die
vorhandenen expliziten Marker (`[STALE]*`, `[RELEASE][NO_ACTION]`,
`[REQUEUE]*`) beobachten. Diese Marker existieren, sind gezaehlt (Abschnitt
4 ) und beschreiben jeweils eine **aufgeloeste** Situation — ein
verbleibender verwaister Task waere daraus nicht sichtbar.

### 5.3 Lebenszyklus-Schliessung

| Groesse | Wert |
|---|---|
| `DROP_TARGET` (Ankunft Target-Bin an der Pickstation) | 60 998 |
| davon anschliessend von der Pickstation abgeholt und eingelagert | 60 824 (**99,71 %**) |
| offen bei t = 30000 | 174 (0–14 je Lauf) |

Die 174 offenen Faelle sind Bins, die zum Zeitpunkt des Horizontendes noch
an der Pickstation lagen — reine Abschneidung am Horizont, kein Verlust.

Blocker-Relocations: 122 675 insgesamt. Der Anteil, der anschliessend
zurueckgelagert wird, folgt exakt der Konfiguration
`return_blocking_bins`:

| Policy | `return_blocking_bins` | Relocations mit `DROP_RETURN` |
|---|---|---|
| `baseline_reference` | True | ~98 % |
| `ABC+ABC` | True | ~97 % |
| `POPULARITY+POPULARITY` | True | ~98 % |
| `RR+RR` | False | ~7 % |
| `LR+NR` | False | ~6 % |

Bei den beiden `False`-Policies bleibt eine relozierte Blocker-Bin
planmaessig an ihrem neuen Platz — kein Defekt, sondern die Policy. Passend
dazu ist `blockers_returned` in `retrievals.csv` je Policy konstant
(`True` fuer baseline/ABC/POPULARITY, `False` fuer RR+RR/LR+NR).

### 5.4 Qualitative Stichprobe (Seed 42, alle fuenf Policies)

Deterministisch gewaehlt, nicht nach Ergebnisqualitaet.

**`baseline_reference/seed42` — Request 826, Bin 5, Robot 1** (vollstaendiger
Zyklus, im Messfenster):

```text
t=19997  DROP_RETURN  robot=1 bin=3121 -> S_10_19      (Vorgaenger-Task frei)
t=19998…20022  Zell-fuer-Zell-Anfahrt (10,19) -> (16,0), jeder Schritt adjazent
t=20023  PICKUP       robot=1 bin=16  from=S_16_0      (Blocker)
t=20051  DROP_RELOCATE robot=1 bin=16 -> S_14_0        (temporaere Auslagerung)
t=20054  PS_ASSIGN    robot=1 bin=5 task=826 -> PS_1
t=20054  PICKUP       robot=1 bin=5   from=S_16_0      (Target)
t=20055…20083  Transport (16,0) -> (19,15) = Port PS_1
t=20084  DROP_TARGET  robot=1 bin=5 to=pickstation     -> Retrieval erfasst
t=20133  PICKUP       robot=3 bin=16  from=S_14_0      (Blocker-Restore)
t=20159  DROP_RETURN  robot=3 bin=16 -> S_16_0         (Ursprungsstapel!)
t=20179  PICKUP       robot=3 bin=5   from=None        (von der Pickstation)
t=20206  DROP_RETURN  robot=3 bin=5  -> S_7_14         (Ruecklagerung)
```

Gegenprobe `retrievals.csv`: `t_pickstation=20084`, `request_id=826`,
`bin_id=5`, `level=6`, `stack_height=8`, `levels_from_top=1`,
`blocking_bins=1`, `batch_size=2`, `t_retrieval_start=19997`,
`dig_duration=87`, `pickstation=PS_1`, `robot_id=1`. Alle Felder stimmen mit
dem Log ueberein, `dig_duration = 20084 − 19997 = 87`. Der Blocker geht
exakt in seinen Ursprungsstapel zurueck (Ordered Return).

**`ABC+ABC/seed42` — Request 677, Bin 1198, Robot 2** (Tiefgrabung mit fuenf
Blockern):

```text
t=19826  DROP_RETURN   robot=2 bin=215  -> S_18_23   (Task-Start)
t=19870/19901  PICKUP 146  S_1_9  -> DROP_RELOCATE S_1_6
t=19905/19932  PICKUP  29  S_1_9  -> DROP_RELOCATE S_2_7
t=19936/19962  PICKUP 2110 S_1_9  -> DROP_RELOCATE S_3_7
t=19967/19993  PICKUP 973  S_1_9  -> DROP_RELOCATE S_5_9
t=19998/20023  PICKUP 2327 S_1_9  -> DROP_RELOCATE S_1_4
t=20029  PS_ASSIGN robot=2 bin=1198 task=677 -> PS_0
t=20029  PICKUP    robot=2 bin=1198 from=S_1_9
t=20042  DROP_TARGET robot=2 bin=1198 to=pickstation
```

Genau fuenf Blocker, alle aus demselben Stapel `S_1_9`, jeder einzeln
ausgelagert; `blocking_bins=5`, `dig_duration = 20042 − 19826 = 216` — beides
deckungsgleich mit `retrievals.csv`.

**`LR+NR/seed42` — Request 1191, Bin 3, Robot 1:** ein Blocker (2898) wird
reloziert und policykonform **nicht** zurueckgelagert; Target ab `S_4_16`,
`DROP_TARGET` t=20006, `dig_duration = 45`. Bin 3 wird t=20024 von Robot 4
von der Pickstation geholt und t=20035 nach `S_4_16` zurueckgelagert —
Zyklus geschlossen.

**`RR+RR/seed42` — Request 804, Bin 0, Robot 3:** ein Blocker (2365) nach
`S_6_14` reloziert (Random Return, nicht Ursprungsstapel — policykonform);
`DROP_TARGET` t=20013, `dig_duration = 92`.

**`POPULARITY+POPULARITY/seed42` — Request 687, Bin 26, Robot 6:** enthaelt
eine Blocker-Eigentumsuebergabe:

```text
t=20045  [OWNERSHIP][RELEASE] robot=6 bin=133 taken by task 687;
                              blocker obligation of task 646 resolved
t=20045  PICKUP        robot=6 bin=133 from=S_3_5
t=20071  DROP_RELOCATE robot=6 bin=133 -> S_2_6
t=20074  PS_ASSIGN/PICKUP robot=6 bin=26 task=687 -> PS_0
t=20095  DROP_TARGET   robot=6 bin=26 to=pickstation
```

Die Bin wechselt sauber von der Blocker-Verpflichtung des Tasks 646 zu Task
687; es entsteht keine doppelte Buchfuehrung und keine verwaiste
Verpflichtung.

**Bewertung:** in allen fuenf Stichproben sind Request-Auswahl,
Task-Entstehung, Anfahrt, Blockerabbau, temporaere Relocation, Pickup,
Transport, Ankunft an der Pickstation, Rueckholung und Ruecklagerung
durchgaengig nachvollziehbar und widerspruchsfrei. Kein Bin verschwindet,
keiner wird doppelt gefuehrt, der Roboter wird jeweils anschliessend
freigegeben und macht weiter.

---

## 6. Retrieval and pickstation plausibility

| Pruefung | Ergebnis |
|---|---|
| Target-Completion erfolgt bei Ankunft an der Pickstation | bestaetigt — `DROP_TARGET`-Ereignis und `t_pickstation` sind dieselbe Groesse (60 998 == 60 998) |
| Retrieval-Zeitpunkte monoton je Lauf | 50/50 monoton |
| doppelte physische Erfassung desselben Ereignisses | 0 (keine `(bin_id, t_pickstation)`-Dublette in einem Lauf) |
| Batching: N Request-Completions, 1 physisches Retrieval | 50/50 exakt (`sum(batch_size)` == Request-Zeilen, 3.5) |
| Pickstation-Zuordnung plausibel | ja — `PS_ASSIGN` nennt die Station, der Drop erfolgt physisch am zugehoerigen Port: PS_0 = (0, 15), PS_1 = (19, 15) |
| Kapazitaet verletzt | nicht beobachtbar verletzt (siehe unten) |
| `t_pickstation >= t_retrieval_start` | 60 998/60 998 |
| `levels_from_top == stack_height − 1 − level` | 60 998/60 998 |
| `0 <= level < stack_height <= 8` | 60 998/60 998 |

**Pickstation-Kapazitaet.** `pickstation_capacity = 1` bezeichnet laut
`state/pickstation.py` die Zahl **gleichzeitig bedienter** Tasks, nicht die
Zahl der Bins, die an der Station liegen duerfen; die Warteschlange
(`PickStation.queue`) ist unbeschraenkt. `start_service` wirft bei
erschoepften Slots eine `RuntimeError` — in keinem der 50 Logs erscheint ein
Traceback, die Kapazitaet wurde also nie ueberschritten. Beobachtbar ist
lediglich, dass sich bereits bediente Bins bis zur Rueckholung an der Station
stapeln (Maximum 44 gleichzeitig in `ABC+ABC/seed11`). Das ist ein
Rueckstau, keine Kapazitaetsverletzung — eine harte Obergrenze existiert im
Modell nicht.

**`blocking_bins` vs. `levels_from_top`.** In 57 698 von 60 998 Zeilen
(94,6 %) identisch; 2 252 Zeilen `blocking_bins > levels_from_top`, 1 048
Zeilen `<`, Abweichungen konzentriert bei ±1. Das ist exakt die bereits
dokumentierte Limitation **L-21**: `levels_from_top` ist ein Snapshot bei
Dig-Start, `blocking_bins` der tatsaechlich geleistete Umlagerungsaufwand;
andere Roboter koennen waehrend des Grabens auf den Zielstapel ablegen. Kein
Fehler; fuer RQ1 ist `blocking_bins` die richtige Groesse.

---

## 7. Progress / liveness

### 7.1 Fortschrittsverteilung

Fuer jeden Lauf wurden die Retrievals in sechs Bloecke à 5000 ZE eingeteilt.

| Kriterium | Ergebnis |
|---|---|
| Laeufe, die t = 30000 erreichen | 50/50 |
| Laeufe mit einem leeren 5000-ZE-Block | **0** |
| erstes Retrieval | t = 26 … 194 |
| letztes Retrieval | t = 29 892 … 29 999 (alle Laeufe) |
| groesste Retrieval-Luecke ueber alle 50 Laeufe | **571 ZE** (`ABC+ABC/seed99`, um t ≈ 16 556) |

Es wurde **kein** neuer Grenzwert und **kein** Failure-Threshold eingefuehrt.
Die groesste beobachtete Luecke entspricht 1,9 % des Horizonts; die naechsten
Faelle liegen bei 489, 487 und 403 ZE. Alle betreffen `ABC+ABC` und liegen
im Bereich der uebrigen Streuung. Kein Lauf haengt ueber laengere Zeit ohne
physischen Fortschritt fest.

### 7.2 Livelock-Recovery: fuehrt sie zu echtem Fortschritt?

817 `[RECOVERY][MOVE_STALL]`-Ereignisse in 45 der 50 Laeufe.

| Kriterium | Ergebnis |
|---|---|
| Zeit vom Recovery-Ereignis bis zum naechsten physischen Retrieval — Maximum ueber alle 817 Faelle | **435 ZE** |
| Recovery-Ereignisse ohne folgendes Retrieval | 2 |
| erkannte Deadlocks ohne Resolution | **0** (9 449 == 9 449, in jedem Lauf einzeln geprueft) |

Die zwei Faelle ohne folgendes Retrieval sind vollstaendig erklaert: sie
treten bei t = 29 994 (`ABC+ABC/seed11`) bzw. t = 29 955
(`POPULARITY+POPULARITY/seed4`) auf, also nach dem letzten Retrieval und
unmittelbar vor dem Horizontende. Abschneidung, kein ungeloester Livelock.

**Nachvollzogener Einzelfall** (`ABC+ABC/seed42`, t = 15882) — Detection,
Recovery, Aufloesung, Fortschritt:

```text
t=15852…15881  Robot 6 steht auf (1,15), will auf den Port (0,15);
               Retry-Leiter 1/5 -> REPLAN -> 1/5 -> … ueber 120 ZE
               (Signatur eines Livelocks: Zustandswechsel ohne Fortschritt)
t=15882  [RECOVERY][MOVE_STALL] robot=6 @(1,15) grund=stall standzeit=120
                                blocker=7
t=15882  [DEADLOCK] Robot 6 evades to break deadlock with robot 7
t=15883  Robot 6 weicht aus: next_waypoint (0,15) -> (1,14)   <- Zustand geaendert
t=15885  Robot 7 verlaesst den Port (0,15) -> (1,15) -> (2,15) …  <- Konflikt geloest
t=15885  PICKUP robot=5 bin=4 from=None   (Pickstation wird geleert)
t=15890  Robot 6 kehrt zurueck (1,14) -> (1,15) -> (0,15)
t=15892  [TRACE][DROP_TARGET] robot=6 bin=1697 to=pickstation   <- echter Fortschritt
```

Zwischen Recovery und physischem Retrieval liegen 10 ZE. Der Konflikt wird
aufgeloest, nicht nur umgeschichtet — das erfuellt das im Projekt geforderte
Kriterium (Detection -> Recovery -> Konflikt aufgeloest -> echter
Fortschritt).

---

## 8. Metric-level plausibility

Keine Interpretation, nur Groessenordnungen. Bereiche ueber alle 50 Laeufe:

| Kennzahl | Min | Max | endlich |
|---|---|---|---|
| `bin_throughput` | 0,0248 | 0,0611 | 50/50 |
| `physical_retrievals` | 871 | 1 778 | 50/50 |
| `measurement_retrievals` | 248 | 611 | 50/50 |
| `requests_completed` (Fenster) | 604 | 1 420 | 50/50 |
| `mean_blocking_bins` | 1,23 | 2,61 | 50/50 |
| `p_beta_zero` | 0,327 | 0,614 | 50/50 |
| `mean_levels_from_top` | 1,23 | 2,27 | 50/50 |
| `share_retrievals_top20pct` | 0,418 | 0,679 | 50/50 |
| `mean_dig_duration` | 78,1 | 164,3 | 50/50 |
| `mean_batch_size` | 1,49 | 5,02 | 50/50 |
| `deadline_miss_rate` | 0,596 | 0,928 | 50/50 |
| `mean_tardiness` | 6 191 | 15 264 | 50/50 |
| `p95_tardiness` | 24 837 | 27 196 | 50/50 |
| `mean_flow_time` | 6 421 | 15 434 | 50/50 |
| `pickstation_utilisation_ps0/ps1` | 0,103 | 0,452 | 50/50 |
| `rq4_plateau_level` | 0,00666 | 0,01095 | 50/50 |

| Pruefung | Ergebnis |
|---|---|
| `NaN` / `Inf` in einer wissenschaftlichen Kennzahl | **0** |
| Anteile ausserhalb [0, 1] wo semantisch gefordert | **0** |
| negative Zeit- oder Zaehlwerte | **0** |
| `physical_retrievals > 0` und `measurement_retrievals > 0` | 50/50 |
| `bin_throughput` endlich und > 0 | 50/50 |
| durchgehend leere Spalten | nur `error` (planmaessig leer) |
| bedingt leere Spalten | `rq4_convergence_time_ZE`, `rq4_convergence_retrievals` in genau den 2 redivergierten Laeufen — regelkonform (`analyse_engine` setzt sie bei `converged_then_rediverged` auf `None`) |

Die hohen Tardiness-Werte sind **kein** Datenbefund, sondern die direkte
Folge der dokumentierten Limitation **L-14** (die Warteschlange ist bei
dieser Last bewusst instabil; Tardiness misst Backlog-Alter, nicht
Servicequalitaet).

**Historischer Plausibilitaetsanker** (Kalibration: ca. 294–592 physische
Retrievals im Fenster [20000, 30000]) — ausdruecklich **kein** Acceptance
Threshold:

| Lauf | `measurement_retrievals` | Bewertung |
|---|---|---|
| `ABC+ABC/seed99` | 248 | leicht unterhalb — geprueft |
| `ABC+ABC/seed11` | 283 | leicht unterhalb — geprueft |
| `LR+NR/seed13` | 611 | leicht oberhalb — geprueft |
| uebrige 47 Laeufe | 294 … 592 | im Ankerbereich |

Alle drei geflaggten Laeufe wurden im Log geprueft: kein Traceback, kein
Deadlock, `move_recovery_unresolved = 0`, Retrievals gleichmaessig ueber alle
sechs 5000-ZE-Bloecke verteilt, letztes Retrieval bei t = 29 956 / 29 898 /
29 989. `ABC+ABC/seed99` hat mit 41 Stall-Recoveries und der groessten
Einzelluecke (571 ZE) den unruhigsten Verlauf — technisch erklaerbar, kein
Defekt. **Kein Lauf wird ausgeschlossen, kein Wert korrigiert, kein Seed
ersetzt.**

---

## 9. RQ1–RQ4 data availability

Wortlaut und Operationalisierung uebernommen aus
`docs/SCIENTIFIC_EXPERIMENT_READINESS.md` §2 (Mapping der vier Fragen von Meller
2023) und den eingefrorenen KPI-/Statistikdefinitionen im
`docs/FINAL_EXPERIMENT_FREEZE_2026-08-21.md` §7 / §8 / F.3.

Statistische Replikationseinheit fuer alle vier RQs (Freeze §8): **der
Seed**. n = 10 je Policy, gepaart ueber Common Random Numbers. Einzelne
Requests oder Retrievals sind **keine** unabhaengigen Replikationen.

### RQ1 — Restacking bins in created holes

> „…it's not only an issue of in which order to return the bins, but also to
> which hole?"

| | |
|---|---|
| **Benoetigte Variablen** | `blocking_bins` je Retrieval, P(β = s), mittleres β, primaere KPI je Konfiguration; `blockers_returned` |
| **Quelle im finalen Export** | `retrievals.csv` (`blocking_bins`, `blockers_returned`, `in_measurement_window`); `runs.csv` (`mean_blocking_bins`, `p_beta_zero`, `bin_throughput`) |
| **Replikationseinheit** | Seed (gepaart, CRN) |
| **Replikationen** | 10 je Konfiguration, 5 Konfigurationen |
| **Technisch vorhanden** | ja — 60 998 Retrieval-Zeilen, davon 20 556 im Fenster; `mean_blocking_bins` und `p_beta_zero` in 50/50 Laeufen endlich; Histogramm P(β = s) aus den Rohzeilen bildbar |
| **Wesentliche Einschraenkung** | L-21: `blocking_bins` und `levels_from_top` laufen in 5,4 % der Zeilen auseinander — fuer RQ1 ist `blocking_bins` die richtige Groesse, die Differenz ist zu berichten. Der Faktor „ueberhaupt zurueckgeben?" ist nur im Kontrast `baseline_reference` ↔ `RR+RR` isoliert (gleiches Reordering, gleiches Placement, nur `return_blocking_bins` verschieden); in `ABC+ABC` und `POPULARITY+POPULARITY` variieren Reordering und Placement gemeinsam, dort ist nur der kombinierte Konfigurationseffekt aussagbar. Look-ahead auf zukuenftige Aktivitaet ist bewusst nicht modelliert. |
| **Urteil** | **BEANTWORTBAR MIT EINSCHRÄNKUNG** |

### RQ2 — Returning bins to the top of a stack after picking

> „Of the many holes at the top layer of the grid, which one is the correct
> location for the bin that just completed its picking process?"

| | |
|---|---|
| **Benoetigte Variablen** | primaere KPI, mittleres β, Level-Verteilung, raeumliche Verteilungs-Snapshots |
| **Quelle im finalen Export** | `runs.csv` (`bin_throughput`, `mean_blocking_bins`, `mean_levels_from_top`, `share_retrievals_top20pct`); `retrievals.csv` (`level`, `stack_height`, `levels_from_top`); `distribution.csv` (`abc_level_*`, `stack_height_variance`, `average_digging_depth`) |
| **Replikationseinheit** | Seed (gepaart, CRN) |
| **Replikationen** | 10 je Konfiguration |
| **Technisch vorhanden** | ja — `placement_strategy` je Lauf gesetzt (RANDOM / NEAREST / ABC / POPULARITY), 15 036 Distribution-Snapshots (300–301 je Lauf), `abc_level_*` summiert in jeder Zeile exakt auf 1 |
| **Wesentliche Einschraenkung** | Placement ist nur im Kontrast `RR+RR` ↔ `LR+NR` (RANDOM vs. NEAREST, beide `return_blocking_bins=False`) isoliert; ABC- und POPULARITY-Placement treten nur gemeinsam mit dem gleichnamigen Reordering auf. `bin_distribution_entropy` ist konstant 0,0 in allen 15 036 Zeilen (L-19/L-24, defekt, aus der Methodik genommen); `hot_bins_top_ratio` ist als Stabilitaetssignal ungeeignet (L-18). Beide sind fuer RQ2 nicht vorgesehen. |
| **Urteil** | **BEANTWORTBAR MIT EINSCHRÄNKUNG** |

### RQ3 — The bin distribution realized in a dynamic system

> „…AutoStore advocates that 80% of the bins would be retrieved from the
> top-20% of the levels … but given the dynamic nature … is this the case?"

| | |
|---|---|
| **Benoetigte Variablen** | Level **vor dem Zugriff** je Retrieval; Anteil aus den obersten 20 % der Ebenen |
| **Quelle im finalen Export** | `retrievals.csv` (`level`, `stack_height`, `levels_from_top`, `abc_class`, `access_count_before`); `runs.csv` (`share_retrievals_top20pct`, `mean_levels_from_top`) |
| **Replikationseinheit** | Seed (gepaart, CRN); gepoolte Rohzeilen nur deskriptiv (Freeze §8) |
| **Replikationen** | 10 je Konfiguration; 20 556 Retrieval-Zeilen im Fenster |
| **Technisch vorhanden** | ja — `level`/`stack_height` sind je Retrieval erfasst und nachtraeglich nicht rekonstruierbar; die Identitaet `levels_from_top = stack_height − 1 − level` haelt in 60 998/60 998 Zeilen; `share_retrievals_top20pct` in 50/50 Laeufen endlich und in [0, 1] |
| **Wesentliche Einschraenkung** | `share_retrievals_top20pct` benutzt die eingefrorene Definition `levels_from_top < max(1, round(0,2 · stack_height))`; bei H = 8 heisst das faktisch „oberste 1–2 Ebenen". Diese Definition ist beim Berichten zu nennen, damit der Vergleich mit Mellers 80-%-Behauptung nachvollziehbar bleibt. |
| **Urteil** | **BEANTWORTBAR** |

### RQ4 — Reaching a steady state bin distribution

> „How long will it take for the grid to arrive at a steady state bin
> distribution under typical operating conditions?"

| | |
|---|---|
| **Benoetigte Variablen** | Konvergenzzeitpunkt in ZE **und** in physischen Retrievals; Verlauf der raeumlichen Verteilung |
| **Quelle im finalen Export** | `runs.csv` (`rq4_status`, `rq4_convergence_time_ZE`, `rq4_convergence_retrievals`, `rq4_plateau_level`, `rq4_redivergence`, `rq4_blocks`); `run_meta.json` (vollstaendige RQ4-Auswertung inkl. der TVD-Distanzfolge); `distribution.csv` (`abc_level_*`-Zeitreihe ab t = 0) |
| **Replikationseinheit** | Seed; RQ4 ist **unabhaengig** vom Performance-Messfenster und wird offline auf der vollstaendigen Zeitreihe ab t = 0 gerechnet |
| **Replikationen** | 10 je Konfiguration |
| **Technisch vorhanden** | ja — 50/50 Laeufe mit gueltigem Status; 48 mit Konvergenzzeit und -retrievals, 2 (`RR+RR/seed11`, `LR+NR/seed7`) regelkonform ohne, weil `converged_then_rediverged`; `rq4_blocks` 17–35 je Lauf, `rq4_plateau_level` 0,00666–0,01095 (innerhalb des kalibrierten Bereichs 0,0062–0,0124, L-27); `run_meta.json` enthaelt je Lauf Regelname und alle vier Parameter (R = 50, K = 2, δ = 0,10, P = 2) plus die Distanzfolge — die Auswertung ist reproduzierbar |
| **Wesentliche Einschraenkung** | L-31: `T_measure_start` ist auf drei Seeds je Policy kalibriert, sieben der zehn finalen Seeds waren ungetestet. **Beobachtung aus den finalen Daten:** alle 48 konvergierten Laeufe konvergieren zwischen t = 6 000 und t = 16 100, also durchgehend vor t = 20 000 — die Reserve hat in dieser Kampagne gehalten. L-35: `LR+NR/seed7` ist ein Grenzfall (Schwelle um ca. 3 % ueberschritten), die Schwelle wurde bewusst nicht angepasst. `converged_then_rediverged` ist ein gueltiges Ergebnis und fuehrt **nicht** zum Ausschluss. |
| **Urteil** | **BEANTWORTBAR** |

---

## 10. Known limitations

Uebernommen aus dem Freeze-Dokument; hier nur daraufhin geprueft, ob sie die
**Beantwortbarkeit** beruehren. Keine neue Post-hoc-Methodik.

| # | Limitation | Wirkung auf die Beantwortbarkeit |
|---|---|---|
| L-14 | Die Warteschlange ist bei jeder getesteten Last instabil; Tardiness misst Backlog-Alter, nicht Servicequalitaet. | Bestaetigt durch die Daten (`deadline_miss_rate` 0,60–0,93; `mean_tardiness` 6 191–15 264 ZE). Deadline-/Tardiness-Groessen sind ausschliesslich als **gepaarter Policyvergleich** zu berichten, nicht als absolutes Service-Level. |
| L-15 | Deadline-Completion = Ankunft an der Pickstation, nicht Zyklusende. | Beim Berichten zu nennen. |
| L-16 | `bin_throughput` zaehlt beim Absetzen an der Pickstation, nicht am Ende des Command Cycle (Lehmann). | Beim Literaturvergleich zu nennen. |
| L-18 / L-19 / L-24 | `hot_bins_top_ratio` ungeeignet; `bin_distribution_entropy` defekt (konstant 0,0 — in den finalen Daten bestaetigt: alle 15 036 Zeilen). | Beide sind in der eingefrorenen Methodik nicht mehr vorgesehen. Kein Einfluss. |
| L-21 | `blocking_bins` vs. `levels_from_top` koennen auseinanderlaufen. | In den finalen Daten quantifiziert: 94,6 % identisch, Abweichungen ±1 dominant. Fuer RQ1 `blocking_bins` verwenden, Differenz erwaehnen. |
| L-23 / L-30 | Pickstation-Zuordnung distanzbasiert, nicht lastausgleichend; `pickstation_utilisation_ps0/ps1` ist kumulativ ueber den ganzen Lauf, **nicht** fensterbezogen. | Fuer Lastverteilung im Fenster `retrievals_ps0/ps1` verwenden, nicht die Utilisation-Spalten. |
| L-27 | TVD-Plateau ist policyabhaengig; deshalb relatives Kriterium. | Von der eingefrorenen Regel bereits beruecksichtigt. |
| L-31 / L-35 | `T_measure_start` auf 3 Seeds je Policy kalibriert; `LR+NR/seed7` ist RQ4-Grenzfall. | Siehe RQ4 oben; in den finalen Daten hat die Reserve gehalten. |
| L-40 | Der Integritaetscheck prueft Struktur und die harten Signale, **nicht** inhaltliche Plausibilitaet oder Performance. | Genau die Luecke, die dieses Dokument schliesst. |
| L-41 / L-42 | Health-Signale werden aus dem Lauflog gelesen, nicht aus einem Kern-Zaehler. | In dieser Kampagne unabhaengig verifiziert: Log-Marker (817) == `runs.csv` == `campaign_status.json`. Nicht tautologisch. |
| **F-1 (neu, dieses Audit)** | Doppelte `request_id` 459 in `POPULARITY+POPULARITY/seed1`, `request_id` 466 fehlt (3.9). | Label-Defekt, kein Zaehldefekt. Keine Fenster-KPI betroffen. `request_id` nicht als eindeutigen Schluessel verwenden. |
| **F-2 (neu, dieses Audit)** | `t_end = 30003` in `baseline_reference/seed99` (2.4). | Folgenlos; keine Messgroesse betroffen. |
| **B-1 (Beobachtung, dieses Audit)** | Die Matrix ist als **fuenf benannte Konfigurationen** eingefroren, nicht als vollstaendiges Faktordesign: Reordering und Placement variieren in `ABC+ABC` und `POPULARITY+POPULARITY` gemeinsam. | Faktorseparierte Aussagen sind nur ueber `baseline_reference` ↔ `RR+RR` (Return) und `RR+RR` ↔ `LR+NR` (Placement) moeglich. Fuer die uebrigen Vergleiche gilt der kombinierte Konfigurationseffekt. Das ist eine Eigenschaft des eingefrorenen Versuchsplans, keine Dateneigenschaft; ob sie in der Arbeit bereits so gefasst ist, wurde hier nicht geprueft. |

---

## 11. Final assessment

```text
CAMPAIGN_COMPLETE              = JA
DATASET_STRUCTURALLY_VALID     = JA
LOG_HEALTH_VALID               = JA
ROBOT_TASK_FLOWS_PLAUSIBLE     = JA
METRIC_VALUES_PLAUSIBLE        = JA
RQ1_DATA_SUFFICIENT            = MIT_EINSCHRÄNKUNG
RQ2_DATA_SUFFICIENT            = MIT_EINSCHRÄNKUNG
RQ3_DATA_SUFFICIENT            = JA
RQ4_DATA_SUFFICIENT            = JA
FINAL_DATA_VALIDATED           = JA
READY_FOR_SCIENTIFIC_ANALYSIS  = JA
```

* **Warum valide:** 50/50 Laeufe, Integritaetscheck unabhaengig PASS, kein
  Traceback/Error/Deadlock/unresolved Recovery in 8,7 Mio. Logzeilen, und
  jede der 15 Run-Kennzahlen laesst sich in allen 50 Laeufen **exakt** aus
  den Rohzeilen rekonstruieren. Die physischen Ablaeufe sind belegt, nicht
  nur behauptet: 6 271 936 Bewegungsschritte sind ausnahmslos 4-adjazent und
  lueckenlos, 307 477 Pickups und 307 212 Drops verletzen kein einziges Mal
  den Tragezustand, und die 60 998 `DROP_TARGET`-Ereignisse im Log
  entsprechen exakt den 60 998 Zeilen in `retrievals.csv`.
* **Livelock-Frage beantwortet:** 9 449 erkannte Deadlocks stehen 9 449
  Aufloesungen gegenueber — in jedem Lauf einzeln. Nach jeder der 817
  Stall-Recoveries folgte spaetestens nach 435 ZE ein physisches Retrieval;
  die zwei Ausnahmen liegen nach dem letzten Retrieval kurz vor dem Horizont.
  Kein Lauf hat einen leeren 5000-ZE-Block; die groesste Retrieval-Luecke
  betraegt 571 ZE.
* **Echte verbleibende Limitation:** L-14 — die Warteschlange ist bewusst
  instabil, `deadline_miss_rate` (0,60–0,93) und `mean_tardiness`
  (6 191–15 264 ZE) sind nur als gepaarter Policyvergleich interpretierbar,
  nicht als Service-Level. Dazu B-1: nur zwei der Policy-Kontraste isolieren
  einen einzelnen Faktor.
* **Konkret zu beachtender Lauf:** `POPULARITY+POPULARITY/seed1` — Befund
  F-1 (doppelte `request_id` 459, fehlende 466). Der Lauf bleibt gueltig;
  die Auswertung darf `request_id` innerhalb eines Laufs nicht als
  eindeutigen Schluessel behandeln. Nachrangig: `baseline_reference/seed99`
  (`t_end = 30003`, folgenlos) und `ABC+ABC/seed99` (unruhigster Verlauf,
  248 Fenster-Retrievals, technisch sauber).
* **Nichts wurde veraendert:** keine CSV-Zeile, kein Log, kein Run, kein
  Seed, kein Wert. Dieser Audit endet hier; eine weitere allgemeine
  Auditphase ist nicht erforderlich.
