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

## Ergebnisse

`results/pilot_summary.json` enthält die verdichteten Kennzahlen je Lauf
(t_end, Retrievals, letzter Retrieval-Zeitpunkt, Stillstandsdauer, β-Mittel
und -Streuung, Deadlock-Detektionen, Fehler). Die vollständigen
Retrieval-Spuren und Distribution-Snapshots sind nicht eingecheckt — sie
lassen sich mit `pilot_batch.py` deterministisch neu erzeugen.
