# Closeout-Werkzeuge (Final Freeze, 2026-08-21)

Diese Skripte erzeugen die Belege, auf die sich der Abschnitt
**Final Freeze Closeout** in `FINAL_EXPERIMENT_FREEZE_2026-08-21.md` stützt.
Sie sind Diagnosewerkzeuge, keine Produktionslogik, und werden von der
Simulation nicht importiert.

Alle Skripte gehen davon aus, dass das Repository importierbar ist
(`sys.path`-Eintrag am Dateikopf; ggf. auf die eigene Umgebung anpassen).

## Piloten fahren

| Skript | Zweck |
|---|---|
| `pilot_run.py` | Konfiguration der finalen Policies und Hilfsfunktionen für den Export |
| `pilot_slice.py` | ein Pilotlauf in fortsetzbaren Rechenscheiben (Pickle-Checkpoint) |
| `pilot_batch.py` | fährt die N unfertigen Läufe mit dem geringsten Fortschritt eine Scheibe weiter |
| `pilot_status.py` | Fortschritts- und Stillstandsübersicht über alle Läufe |
| `verify_resume_identity.py` | belegt, dass Scheiben-Rechnen die Trajektorie nicht verändert |

```bash
python3 pilot_batch.py results/pilots 150 4     # wiederholt aufrufen
python3 pilot_status.py results/pilots 1000
```

`pilot_slice.py` akzeptiert als letztes Argument `old`. Dann wird mit dem
**alten** Initialzustand gerechnet (Port-Pufferzone initial belegt) — so
entstand die Gegenprobe, dass der Deadlock vorbestehend ist.

## Auswertung

| Skript | Zweck |
|---|---|
| `analyse_steady_state.py` | Stop-Regel offline auf der Retrieval-Spur; Konvergenz, Measurement Window, Reserve, räumliche Stabilität |
| `analyse_block_noise.py` | Streuung von β und die daraus folgende nötige Blockgröße |

## Correctness / Reproduzierbarkeit

| Skript | Zweck |
|---|---|
| `check_crn_final.py` | CRN über 10 Seeds × 5 Konfigurationen auf der finalen Geometrie |
| `check_correctness_final.py` | Audit-Harness (Invarianten nach jedem Schritt) auf der finalen Konfiguration |
| `check_deadlock_state.py` | prüft einen festgefahrenen Endzustand aus dem Pickle gegen alle Invarianten |
| `inspect_retry_cycle.py` | zeigt, welche Blocker die wartenden Roboter aufnehmen wollen und wo sie verschüttet liegen |
| `probe_abort.py` | einzelner Vergleichslauf alt/neu für einen Abbruch- oder Stillstandsbefund |

## Stall-Diagnose (Long-Run-Liveness-Phase, 2026-08-22)

| Skript | Zweck |
|---|---|
| `pilot_state.py` | Laden/Speichern eines Laufzustands **inklusive** `Event._next_event_id` — ohne den weicht eine prozessübergreifend fortgesetzte Trajektorie ab |
| `classify_stall.py` | wer wartet auf welche Bin, wer hat sie verschüttet, Wait-Kanten und Zyklen |
| `replay_stall_reasons.py` | setzt einen festgefahrenen Lauf einige Schritte fort und verdichtet die Blockade-Gründe aus dem Log |
| `inspect_pickstation_stall.py` | Roboterpositionen, getragene Bins, Portbelegung, doppelte Events |
| `trace_carry.py` | verfolgt, wie ein Roboter zu einer Bin kommt, die nicht zu seinem Task gehört |
| `trace_burial.py` | ordnet jeder verschütteten Blocker-Bin die Aktion zu, die die Bins darüber abgelegt hat |
| `diagnose_small_stall.py` | schnelle 7×7-Reproduktion eines Stillstands (unter zwei Minuten) |
| `reproduce_abort.py` | fährt eine Kombination bis zum Abbruch und zeigt den Zustand davor |

Der 7×7-Fall aus `diagnose_small_stall.py` ist der Arbeitsfall: vor der
Behebung blieb er bei t=1942 mit 47 Retrievals stehen, danach erreicht er
218 Retrievals bis t=6000 mit durchgehendem Fortschritt.

## Portstau und RQ4 (Klasse-C-Phase, 2026-08-22)

| Skript | Zweck |
|---|---|
| `inspect_port_congestion.py` | vollständige Zustandsaufnahme eines Portstaus: Positionen, Phasen, getragene Bins, Pfadreste, Portreservierung, Zonenbelegung je Station, Wait-Graph, Blockierketten und Zyklen |
| `analyse_abc_level_convergence.py` | räumliche RQ4-Konvergenz auf der (ABC-Klasse, Tiefe)-Verteilung: TVD zwischen Blöcken, wahlweise nach Retrievals oder nach Zeit, mit Persistenzprüfung |

```bash
python3 inspect_port_congestion.py final/ABC_ABC__seed42.pkl
python3 analyse_abc_level_convergence.py final 50 0.01 3 retrievals
```

## Finale Kalibration (2026-08-22)

| Skript | Zweck |
|---|---|
| `probe_port_toctou.py` | Randfallpruefung des PortExitGuard: zwei gleichzeitige Planer, letzte Ausfahrt als eigenes Ziel |
| `calib_batch.py` | Treiber fuer die symmetrische Matrix 5 Policies x Seeds 1/7/42 bis 30.000 ZE |
| `analyse_rq4_plateau.py` | finale RQ4-Regel: relatives Plateau-Kriterium auf der TVD-Folge |
| `analyse_measurement_window.py` | leitet `T_measure_start` und die Fensterlaenge aus den Kalibrationsspuren ab |

```bash
python3 probe_port_toctou.py
python3 calib_batch.py calib 150 4 30000      # wiederholt aufrufen
python3 analyse_rq4_plateau.py calib 50 2 0.10 2
python3 analyse_measurement_window.py calib 50 2 0.10 2
```

`results/rq4_calibration.json` enthaelt je Lauf Konvergenzstatus,
Konvergenzzeit, TVD-Folge, Plateauniveau und die Diagnosezaehler, dazu die
gewaehlte Regel und den festgelegten Zeithorizont.

## Lifecycle-Diagnose (2026-08-22)

| Skript | Zweck |
|---|---|
| `probe_foreign_target_return.py` | reproduziert deterministisch, wie ein Target-Return eines FREMDEN Requests auf dieselbe Bin die Buchhaltung des aktuellen Tasks ueberschreibt |

```bash
python3 probe_foreign_target_return.py
```

## ABC-/POPULARITY-Audit (2026-08-22)

| Skript | Zweck |
|---|---|
| `probe_reorder_direction.py` | zeigt die TATSAECHLICHE Stapelordnung nach dem Ordered Return fuer ABC, POPULARITY und LOFI — deckte die Richtungsumkehr auf |
| `probe_restore_target_mismatch.py` | protokolliert jede Umplanung des Rueckgabeziels einer Blocker-Bin und die zugehoerigen Drops |

```bash
python3 probe_reorder_direction.py
python3 probe_restore_target_mismatch.py "ABC+ABC" 42 2154
```

`results/abc_popularity_audit.json` enthaelt den Vorher/Nachher-Vergleich der
mittleren A-Klassen-Tiefe je Lauf sowie den Zustand der Laeufe nach dem Fix.

## Face Validity (2026-08-22)

| Skript | Zweck |
|---|---|
| `face_validity.py` | `trace` protokolliert einen vollstaendigen Retrieval-Zyklus je Policy menschenlesbar; `aggregate` prueft ueber einen Kurzlauf, ob A flacher liegt als C, heisse Bins flacher als kalte, Ordered Return nur dort stattfindet, wo er definiert ist, und ob Roboter verwaisen |
| `face_validity_multiblocker.py` | sucht einen Zyklus mit mehreren Blockern — erst dort wird die Reihenfolge des Ordered Return sichtbar |

```bash
python3 face_validity.py aggregate
python3 face_validity.py trace
python3 face_validity_multiblocker.py
```

## Finale Validierung und Kampagnen-Trockenlauf (2026-08-24)

| Skript | Zweck |
|---|---|
| `dry_check_matrix.py` | faehrt die eingefrorene Matrix 5 Policies x 10 Seeds ueber einen kurzen Horizont und prueft die STRUKTUR der Kampagne: laeuft jede Kombination, greift das gemeinsame Zeitfenster, ist die `runs.csv`-Zeile vollstaendig, stimmen `runs.csv` und `retrievals.csv` im Fensterbegriff ueberein, bleibt CRN intakt, verwaist ein Roboter |

```bash
# inkrementell: jeder Aufruf ersetzt die Zeilen der uebergebenen
# Policies/Seeds, das Urteil gilt ueber alle bisher gerechneten Zeilen
python3 dry_check_matrix.py 400 200 "ABC+ABC"
python3 dry_check_matrix.py 400 200 "RR+RR" "1,2,3,4,7"
```

`results/matrix_dry_check.json` haelt je Kombination Fenstermodus,
Fensterzahlen, Nachfrage-Fingerprint und fehlende Pflichtfelder fest.
`results/rq4_calibration_final.json` enthaelt die 15 neu gerechneten
Kalibrationslaeufe mit RQ4-Status, Plateauwerten, Fensterzahlen,
Klassentiefen und Diagnosezaehlern sowie die daraus abgeleiteten Horizonte.

Der Trockenlauf deckte zwei Exportbefunde auf (J-1: `in_measurement_window`
markiert das alte Steady-State-Fenster; J-2: vier Steady-State-Spalten
bleiben leer, weil `get_convergence_analysis()` die gelesenen Schluessel
nicht liefert). Beide sind in `FINAL_EXPERIMENT_FREEZE_2026-08-21.md`,
Abschnitt J.7 beschrieben und in Abschnitt K behoben; seither meldet der
Trockenlauf **MATRIX DRY-CHECK PASS** ueber alle 50 Kombinationen.

Seit dem Export-Closeout bezieht `dry_check_matrix.py` Policies, Seeds und
den Config-Builder aus `experiments/campaign_matrix.py` — derselben Quelle,
aus der auch der Kampagnentreiber `experiments/run_final_campaign.py` seine
Matrix nimmt. Die Pruefung kann damit nicht mehr etwas anderes pruefen, als
die Kampagne spaeter rechnet.

Ebenfalls seither ist `analyse_rq4_plateau.py` nur noch die Dateischale um
die eingefrorene Regel; die Regel selbst steht in `metrics/rq4_plateau.py`
und wird vom Kampagnenexport mitbenutzt. Eine Implementierung, zwei
Aufrufer.

## Ergebnisse

`results/pilot_summary.json` enthält die verdichteten Kennzahlen je Lauf
(t_end, Retrievals, letzter Retrieval-Zeitpunkt, Stillstandsdauer, β-Mittel
und -Streuung, Deadlock-Detektionen, Fehler). Die vollständigen
Retrieval-Spuren und Distribution-Snapshots sind nicht eingecheckt — sie
lassen sich mit `pilot_batch.py` deterministisch neu erzeugen.
