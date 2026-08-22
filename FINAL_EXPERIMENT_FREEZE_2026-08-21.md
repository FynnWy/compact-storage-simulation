# Final Experiment Freeze Audit

**Letzte Readiness-/Pilotphase vor der finalen Experimentkampagne**

**Datum:** 2026-08-21
**Baseline-Commit:** `a44393e` (Branch `working_sim`)
**Python:** 3.10.12, pytest 9.1.1
**Testsuite:** vorher 383 passed → nachher **400 passed**

---

# 1. Wissenschaftliches Ziel

Fünf Konfigurationen, gemeinsam gerechnet, aufgeteilt auf zwei Arbeiten:

| Arbeit | Policies |
|---|---|
| **A** | `baseline_reference`, RR+RR, ABC+ABC |
| **B** | `baseline_reference`, LR+NR, POPULARITY+POPULARITY |

Alle fünf nutzen dieselben Seeds, exogenen Workloads, Servicezeiten,
Deadlines, Metriken und dasselbe Setup.

Primäre KPI: `bin_throughput`. Deadline-/Tardiness-Kennzahlen sind sekundäre
Performance-KPIs. Keine zusammengesetzte Score-Metrik.

---

# 2. Der zentrale Befund dieser Phase

## 2.1 Cherry-Picking war real und massiv

Die Scheduling-Reihenfolge war:

```
1. waiting_tasks / Fortsetzungen
2. opportunistisch: Pending Request, dessen Target bereits obenauf liegt
3. FIFO / EDF
```

Stufe 2 ist ein **lageabhängiger Bypass**. Unter Backlog wurden bevorzugt
Requests bedient, deren Target ohnehin zugänglich war.

Gemessen (20×30, H = 8, 4320 Bins, 8 Roboter, Seed 42, 800 ZE, Zipf 1,0):

| Konfiguration | Zuweisungen opportunistisch | EDF | β | Retrievals aus obersten 20 % |
|---|---|---|---|---|
| `baseline_reference`, Bypass **an** | **39** | 8 | **0,73** | **84 %** |
| `baseline_reference`, Bypass **aus** | 0 | 32 | **2,70** | **33 %** |
| ABC+ABC, Bypass **an** | **37** | 9 | 0,95 | 81 % |
| ABC+ABC, Bypass **aus** | 0 | 30 | 2,65 | 31 % |

**83 % aller Zuweisungen liefen über den Bypass.** Er verzerrte genau die
Größen, die RQ1 und RQ3 messen sollen: β um den Faktor 3,7, der Anteil der
Retrievals aus den oberen Ebenen um mehr als das Doppelte.

## 2.2 Korrektur früherer Aussagen

Drei Aussagen aus `SCIENTIFIC_EXPERIMENT_READINESS.md` waren Artefakte des
Bypass und werden hiermit zurückgezogen:

| Frühere Aussage | Tatsächlich (ohne Bypass) |
|---|---|
| „77,4 % der Retrievals aus den obersten 20 % der Ebenen – Mellers 80/20 plausibel bestätigt" | **31–38 %.** Mellers 80/20-Behauptung wird in unserem Modell **nicht** reproduziert. |
| „β fällt von 1,36 auf 0, Natural Slotting sehr effektiv" | β bleibt bei **2,2–3,0**. Das Lager sortiert sich **nicht** dig-frei. |
| „Systemkapazität ≈ 0,0625 bins/ZE, Knick bei 10 Robotern" | Kapazität ≈ **0,031 bins/ZE**; der Durchsatz steigt bis mindestens 14 Roboter monoton. |

Ohne diesen Fix hätte die Kampagne Mellers Behauptung scheinbar bestätigt,
obwohl der Effekt aus der Request-Auswahl stammte.

## 2.3 Finale Scheduler-Semantik

```
1. Wartende aktive Tasks / Fortsetzungen / Rücklagerungen
2. Neue Pending Requests ausschließlich nach EDF
```

Der opportunistische Schritt entfällt im Hauptpfad. Die Methode bleibt als
dokumentierter Legacy-Code stehen; ein Verhaltenstest stellt sicher, dass sie
in keinem Lauf mehr aufgerufen wird.

**Zum zweiten Zweck des alten Zweigs** (opportunistischer Ownership-Transfer
einer ausgelagerten Blocker-Bin): entbehrlich. Blocker-owned Bins sind über
`get_all_reserved_bin_ids()` ohnehin von der Auswahl ausgeschlossen und werden
frei, sobald der Eigentümer sie zurücklegt oder seine Verpflichtung verwirft
(seit Phase 3B inklusive Ownership-Freigabe). Es entsteht Wartezeit, kein
Deadlock — in allen Piloten trat keine Starvation und kein Abbruch auf.

## 2.4 EDF-Tie-Break

```
Deadline → arrival_time → request_id
```

Vorher entschied allein `min(..., key=latest_time)`; bei Gleichstand gewann
die Iterationsreihenfolge. Bei konstantem Slack ist der Gleichstand der
Normalfall, nicht die Ausnahme. Kein Kriterium hängt von Lagerposition,
Digging-Tiefe, ABC-Klasse oder Popularität ab.

`scheduler_strategy` steht jetzt per Default auf `"EDF"` (vorher `"FIFO"`).

---

# 3. Deadline-Semantik

## 3.1 Audit des Ist-Zustands

| Aspekt | Befund |
|---|---|
| Erzeugung | `RequestGenerator._generate_latest_time`, vor Simulationsbeginn |
| Speicherung | **absolut** (`arrival + slack`) als `request.latest_time` |
| RNG-Quelle | `requests`-Strom (exogen) |
| Abhängigkeit von Bin/Position/Klasse | **keine** |
| Reproduzierbar über Policies | **ja** (testgesichert) |
| Vorher: Slack | 10 % urgent = 3 ZE, 75 % normal = 6, 15 % low = 12, plus Rauschen ∈ [−2, 2] ⇒ **1 bis 14 ZE** |
| Completion für die Deadline | Ankunft der Target-Bin **an der Pickstation** |
| Batching | jeder Request wird einzeln erfasst und gegen seine eigene Deadline bewertet |
| `successful_requests` | Requests, deren Bin die Pickstation **rechtzeitig** erreicht hat |
| Export | fehlte vollständig — jetzt ergänzt |

**Problem des alten Slacks:** 1–14 ZE, während allein Ausgraben und Transport
einer Bin rund 30 ZE dauern. Gemessene Miss-Rate 91–97 %. Die Kennzahl war
ohne Aussagekraft.

## 3.2 Finale Regel

```
deadline = arrival_time + D          mit konstantem D für alle Requests
```

Exogen, policyneutral, ohne Bezug zu Bin-ID, Lagerposition, ABC-Klasse oder
Popularität. Bei konstantem D entspricht EDF im Wesentlichen der
Ankunftsreihenfolge — die Deadline ist damit eine reine Messüberlagerung und
keine zusätzliche Priorisierungspolitik.

Testgesichert: **der Slackwert verändert den physischen Ablauf nicht.**
Läufe mit D = 60 und D = 240 liefern identische Retrieval-Sequenzen.

## 3.3 Kalibrierung von D

Baseline, Seed 42, 1200 ZE:

| D | Miss-Rate | mean | median | p95 |
|---|---|---|---|---|
| 60 | 68 % | 325 | 122 | 992 |
| 120 | 59 % | 286 | 62 | 932 |
| **240** | **44 %** | 224 | **0** | 812 |

Bei 3000 ZE und D = 240: Miss-Rate 54 %, median 327, p95 2241.

**Gewählt: D = 240 ZE.** Begründung: liegt rund eine Größenordnung über der
physischen Bearbeitungszeit eines einzelnen Retrievals, ergibt bei der
geplanten Lauflänge eine Miss-Rate im diskriminierenden Bereich um 50 % und
ist als „vier Zeiteinheiten je Ebene mal Gridhöhe mal Sicherheitsfaktor"
einfach zu erklären.

## 3.4 Interpretation unter Sättigung — wichtig

Gemessene Systemkapazität nach dem Scheduler-Fix: **≈ 0,031 Retrievals/ZE**.
Angebot bei `util = 0,6`: 0,66 Requests/ZE. Bereits bei `util = 0,05`
(0,07 Requests/ZE) wächst der Backlog.

| util | angeboten/ZE | bins/ZE | Backlog nach 800 ZE |
|---|---|---|---|
| 0,05 | 0,07 | 0,0300 | 21 |
| 0,10 | 0,11 | 0,0312 | 60 |
| 0,20 | 0,22 | 0,0325 | 132 |
| 0,60 | 0,66 | 0,0312 | 440 |

Es gilt also `arrival_rate > sustainable_completion_rate` bei **jeder**
getesteten Last. Die Warteschlange ist instabil.

**Konsequenz, ausdrücklich festgehalten:**

> Tardiness misst in diesem Szenario das **Alter des Backlogs**, nicht die
> Servicequalität eines stabilen Warteschlangensystems. Bei fester Deadline
> wächst sie systematisch mit der Lauflänge — gemessen: median 0 bei 1200 ZE,
> median 327 bei 3000 ZE, bei identischem D.

Zulässige Interpretation:

* **gepaarter Vergleich zwischen Policies** bei identischer Lauflänge,
  identischem Seed und identischem exogenem Workload — die Unterschiede sind
  dann policybedingt;
* als Indikator dafür, **wie schnell der Rückstand wächst**.

Unzulässig:

* absolute Aussagen über Service-Level oder Termintreue,
* Vergleiche zwischen Läufen unterschiedlicher Länge,
* das Verstecken der Instabilität hinter einem sehr großen D.

Ein stabiler Queue-Zustand wäre nur bei `util < 0,03` erreichbar. Dann wäre
der Durchsatz aber nachfragebegrenzt und die primäre KPI würde nicht mehr die
Kapazität messen. Beides gleichzeitig ist nicht erreichbar; wir priorisieren
die primäre KPI und dokumentieren die Einschränkung.

## 3.5 Batching und Deadlines

`_attach_batched_requests_to_task` ruft
`Metrics.record_target_bin_at_pickstation` für den primären **und** jeden
gebatchten Request einzeln auf.

| Frage | Antwort |
|---|---|
| Gleicher Completion-Zeitpunkt für alle Requests eines Batches? | **Ja** — die Bin kommt einmal an. |
| Jeder Request gegen seine eigene Deadline? | **Ja** — testgesichert mit unterschiedlichen Ankünften und Deadlines auf derselben Bin. |
| Batch als ein Request gezählt? | **Nein** — N Zeilen in `requests.csv`. |
| `bin_throughput` retrievalbasiert? | **Ja** — eine Zeile in `retrievals.csv`. |
| `request_throughput` requestbasiert? | **Ja**. |

---

# 4. Finale Parameter

| Parameter | Wert | Status |
|---|---|---|
| Grid | 20 × 30 | bestätigt |
| Höhe H | 8 | bestätigt |
| Bins | 4320 (≈ 90 %) | bestätigt |
| Pickstations | **genau 2** | verbindlich |
| Roboter | **8** | bestätigt, siehe 4.1 |
| Zipf θ | **1,0** | bestätigt, siehe 4.2 |
| `request_utilization` | **0,6** | bestätigt, siehe 4.3 |
| Scheduler | **EDF**, kein Bypass | neu |
| Deadline | `arrival + 240` | neu |
| Popularity-Warmup | 50 physische Retrievals | bestätigt |
| Seeds | 10: 1, 2, 3, 4, 7, 11, 13, 42, 99, 123 | bestätigt |
| `baseline_reference` | enthalten | bestätigt |

Im Code hinterlegt: `config/simulation_config.py` (`scheduler_strategy = "EDF"`,
`deadline_slack = 240`) und `run_experiments.py` (`zipf_parameter = 1.0`,
vorher 1.5). Damit stimmen Dokumentation und Default-Konfiguration überein.

## 4.1 Roboterzahl

Sweep nach dem Scheduler-Fix (800 ZE, Seed 42):

| Roboter | bins/ZE | bins/Roboter/ZE |
|---|---|---|
| 6 | 0,0250 | 0,00417 |
| **8** | **0,0312** | **0,00391** |
| 10 | 0,0375 | 0,00375 |
| 12 | 0,0437 | 0,00365 |
| 14 | 0,0488 | 0,00348 |

Der frühere „Knick bei 10, Einbruch bei 12" war ein Bypass-Artefakt. Ohne
Bypass steigt der Durchsatz im gesamten getesteten Bereich monoton, die
Roboterproduktivität sinkt nur mild (−17 % von 6 auf 14). Es gibt also kein
Optimum, vor dem man sitzen müsste.

**8 Roboter bleiben**: vorab festgelegt, im mild ausgelasteten Bereich
(94 % der Produktivität bei 6 Robotern), kein Traffic-Zusammenbruch, und mit
4 Robotern je Pickstation konservativer als Lehmanns Baseline (K = 5).

## 4.2 Zipf θ = 1,0

Bestätigt. Anteil der Nachfrage auf die 20 % häufigsten Bins bei N = 4320:

| θ | Top-20 % | A (20 %) | B (30 %) | C (50 %) |
|---|---|---|---|---|
| **1,0** | **82,0 %** | 82,0 % | 10,2 % | 7,7 % |
| 1,5 (alt) | 98,5 % | 98,5 % | 1,0 % | 0,5 % |

θ = 1,0 trifft Mellers 80/20-Szenario nahezu exakt. Kein neuer Befund spricht
dagegen.

## 4.3 Nachfrageintensität

`util = 0,6` bleibt: die Kapazität ist bei jeder getesteten Last erreicht,
der Durchsatz variiert zwischen 0,030 und 0,0325 bins/ZE, es gibt keinen
Traffic-Zusammenbruch und `move_recovery_unresolved = 0` in allen Piloten.
Ein Load-Sweep im finalen Experiment ist nicht vorgesehen.

---

# 5. Steady-State-Regel — **hier bleibt der Freeze offen**

## 5.1 Vorgesehene Regel

```
Blockgröße:           50 physische Retrievals
Signal:               mittleres β (Blocking Bins je Retrieval)
Konvergenz:           2 aufeinanderfolgende relative Änderungen ≤ 10 %
Measurement Window:   200 weitere physische Retrievals
Maximalgrenze:        6000 ZE
```

## 5.2 Was der Test ergab

Der Scheduler-Fix hat den Durchsatz etwa halbiert. Gemessene Retrieval-Raten
(Seed 42, EDF, ohne Bypass):

| Konfiguration | bins/ZE |
|---|---|
| LR+NR | 0,0530 |
| RR+RR | 0,0345 |
| POPULARITY+POPULARITY | 0,0330 |
| `baseline_reference` | 0,0308 |
| **ABC+ABC** | **0,0157** |

Für Konvergenz (3 Blöcke = 150 Retrievals) plus Measurement Window
(200 Retrievals) sind 350 Retrievals nötig. Beim langsamsten Kandidaten
ABC+ABC entspricht das **≈ 22.300 ZE** — die vorgesehene Grenze von 6000 ZE
ist um den Faktor 3,7 zu klein.

Kein Pilotlauf erreichte innerhalb des Zeitbudgets dieser Phase drei Blöcke;
alle meldeten korrekt `not_converged`:

| Konfiguration | Lauf | Retrievals | Blockmittel β |
|---|---|---|---|
| `baseline_reference` | 4000 ZE | 123 | [2,42; 2,28] → Änderung 6 % |
| LR+NR | 2000 ZE | 106 | [2,24; 2,68] |
| RR+RR | 2000 ZE | 69 | [2,18] |
| POP+POP | 2000 ZE | 66 | [2,38] |
| ABC+ABC | 3000 ZE | 47 | – |

Positiv: Die Regel verhält sich korrekt (kein falsches Konvergenzsignal), und
β liegt jetzt stabil bei 2,2–3,0 statt gegen 0 zu laufen — als
Konvergenzsignal ist es damit besser konditioniert als zuvor angenommen. Die
beim `baseline_reference` beobachtete Änderung von 6 % zwischen Block 1 und 2
liegt bereits unter der 10-%-Schwelle; es fehlte nur der dritte Block.

## 5.3 Empfehlung

```
Blockgröße:           50 physische Retrievals      (unverändert)
Schwelle:             10 %                          (unverändert)
Stabile Paare:        2                             (unverändert)
Measurement Window:   100 physische Retrievals      (statt 200)
Maximalgrenze:        20.000 ZE                     (statt 6000)
```

Begründung: 150 + 100 = 250 Retrievals ⇒ ABC+ABC benötigt ≈ 16.000 ZE, die
übrigen 4.700–8.100 ZE. Ein Window von 100 Retrievals je Lauf ergibt über
10 Seeds 1.000 gepoolte Retrievals je Policy — für P(β = s) und
Level-Histogramme ausreichend, und der Seed bleibt ohnehin die statistische
Replikationseinheit.

**Diese Empfehlung ist NICHT validiert.** Ein bestätigender Lauf über
≈ 16.000 ZE dauert rund 12 Minuten und war im Zeitbudget dieser Phase nicht
durchführbar.

## 5.4 β als Proxy für räumliche Stabilität

Ebenfalls **nicht validiert**. Der Nachweis setzt konvergierte Läufe voraus,
die aus demselben Grund nicht vorliegen. Die Daten dafür sind vorhanden
(`distribution.csv` mit `hot_bins_top_ratio`, Level-Verteilung, ABC-Tiefen);
die Prüfung ist auf konvergierten Läufen unmittelbar durchführbar.

---

# 6. Initiale Pufferzonen-Belegung

**Entscheidung: zustimmen — die Initialverteilung soll dieselben zulässigen
Storage-Positionen verwenden wie die Placement-Policies.**

Begründung wie vorgeschlagen: RQ4 soll die Reorganisation aus einem
zufälligen **gültigen** Lagerzustand messen, nicht zusätzlich das erzwungene
Ausströmen von Bins aus später verbotenen Zellen.

**Aber noch nicht umgesetzt.** Ein erster Versuch scheiterte an den kleinen
Testgrids: Auf einem 3×3-Grid (`small_config`) verbraucht die Pufferzone
(Manhattan ≤ 1 um den Port) den Großteil der Zellen, die Initialverteilung
findet keine Plätze mehr, und sieben bestehende Integrationstests brechen mit
`No relocation stack with free capacity available`.

Sauberer Weg: den Ausschluss nur anwenden, wenn nach Abzug der Pufferzone
noch hinreichend Kapazität bleibt — als explizite, dokumentierte
Vorbedingung des finalen Setups statt als stiller Fallback. Betroffen sind im
finalen Layout 6 von 598 Stacks (1 %), Kapazität 4784 → 4736, Füllgrad
90,3 % → 91,2 %.

Der Parameter `excluded_positions` ist in `init_random_distribution` bereits
vorhanden und dokumentiert; es fehlt die Verdrahtung in
`SimulationEngine._initialize_state` samt Anpassung der kleinen Test-Fixtures.

---

# 7. KPI-Definitionen

## 7.1 Primär

| KPI | Definition |
|---|---|
| `bin_throughput` | physische Target-Retrievals je Zeiteinheit im Measurement Window |

**Wann wird ein Retrieval gezählt?** Genau dann, wenn eine Target-Bin
physisch an einer Pickstation abgesetzt wird (`_handle_robot_drop`, Zweig
`remove_target`). Eine Zeile in `retrievals.csv`, unabhängig davon, wie viele
Requests dadurch bedient werden.

**Unterschied zu Lehmanns Command Cycle:** Lehmann fasst Retrieval,
zugehörige Reshuffles **und** die anschließende Einlagerung zu einem Zyklus
zusammen. Wir zählen beim Absetzen an der Pickstation, also **vor** der
Rücklagerung der Target-Bin und vor eventuellen Blocker-Restores. Die
Rücklagerung ist im System weiterhin enthalten und belastet die Roboter —
sie geht nur nicht in den Zählzeitpunkt ein. Die Größe ist damit
`retrieved loads per time` im Sinne von Lehmanns Gleichung (1), gemessen an
der Ankunft statt am Zyklusende.

## 7.2 Sekundär

`request_throughput`, `deadline_miss_rate`, `mean_tardiness`
(plus `median_tardiness`, `p95_tardiness`, `mean_flow_time` aus denselben
Rohdaten).

## 7.3 Erklärende KPIs (RQ1/RQ3)

`mean_blocking_bins`, `p_beta_zero`, `mean_levels_from_top`,
`share_retrievals_top20pct`, `mean_dig_duration`, `mean_batch_size`,
`pickstation_utilisation_mean`.

Für RQ1 ist `blockers_returned` je Retrieval-Zeile vorhanden; daraus lässt
sich `mean_blockers_returned` je Lauf ableiten. Da der Wert innerhalb einer
Konfiguration konstant ist (`return_blocking_bins`), wird er **nicht** als
eigene Run-KPI gespeichert.

**`full_cycle_duration` wurde geprüft und nicht ergänzt.** Der Zeitstempel
des endgültigen Target-Returns wäre ein zusätzliches Feld, dessen
Informationsgehalt bereits in `bin_throughput` (Systemdurchsatz inklusive
Rücklagerungsaufwand) und `dig_duration` (Retrieval-Anteil) steckt. Kein
Metrics Sprawl.

---

# 8. Statistik

Der **Seed ist die unabhängige Replikation**. Reihenfolge:

1. je Lauf (Policy × Seed) aggregieren — auch `deadline_miss_rate` und
   `mean_tardiness`,
2. über die 10 Seeds Mittelwert, Standardabweichung und 95-%-CI
   (t-Verteilung, n = 10),
3. gepaarte Policy-Differenzen je Seed über Common Random Numbers.

Einzelne Requests oder Retrievals sind **keine** unabhängigen Replikationen.
Gepoolte Roh­daten dienen ausschließlich deskriptiven Histogrammen
(P(β = s), Level-Verteilung).

---

# 9. Datenformat

Fünf Dateien je Kampagne, `run_id` als Schlüssel:

| Datei | Granularität |
|---|---|
| `runs.csv` (43 Spalten) | ein Lauf |
| `retrievals.csv` (19 Spalten) | ein physisches Retrieval |
| `requests.csv` (12 Spalten) | ein bedienter Request: `arrival_time`, `deadline`, `completion_time`, `flow_time`, `lateness`, `tardiness`, `on_time` |
| `distribution.csv` | ein Snapshot je 100 ZE |
| `run_meta.json` | Konfiguration und Steady-State-Verlauf je Lauf |

Gemessen: 87 Byte je Retrieval-Zeile. Bei ~250 Retrievals und ~350 Requests
je Lauf und 50 Läufen ergibt das **≈ 2,5 MB** gesamt.

**Laufzeit:** ≈ 20 ZE/s. Bei den empfohlenen Grenzen 4.700–16.000 ZE je Lauf
sind das 4–13 Minuten, für 50 Läufe **≈ 6 Stunden**.

---

# 10. Correctness und CRN

Testsuite: **400 passed** (`test_simulation_visual.py` weiterhin ohne Flask
nicht ausführbar).

In allen Piloten dieser Phase: 0 Abbrüche, 0 ungültige Aktionen,
`move_recovery_unresolved = 0`.

CRN inklusive Deadlines testgesichert:

* gleicher Seed ⇒ identische Deadlines über alle fünf Konfigurationen,
* der Deadline-Slack verändert weder den Request-Strom noch die
  Servicezeiten noch den physischen Ablauf,
* EDF- und Deadline-Code verbrauchen keinen Zufall,
* die Exportschicht verbraucht keinen Zufall.

---

# 11. Finale Run-Matrix

```
5 Konfigurationen × 10 Seeds = 50 Läufe

Konfigurationen: baseline_reference, RR+RR, LR+NR, ABC+ABC, POP+POP
Seeds:           1, 2, 3, 4, 7, 11, 13, 42, 99, 123

Grid 20×30, H=8, 4320 Bins, 2 Pickstations, 8 Roboter
Zipf 1,0, util 0,6, Scheduler EDF, Deadline = arrival + 240
Steady State: Block 50, Schwelle 10 %, 2 stabile Paare,
              Window 100 Retrievals, Grenze 20.000 ZE   [NICHT VALIDIERT]
```

---

# 12. Limitationen

L-1 bis L-13 aus `SCIENTIFIC_EXPERIMENT_READINESS.md` bleiben bestehen.
Neu bzw. geändert:

| # | Limitation |
|---|---|
| L-14 | Die Warteschlange ist bei jeder getesteten Last instabil. Tardiness misst Backlog-Alter, nicht Servicequalität (3.4). |
| L-15 | Der Deadline-Completion-Zeitpunkt ist die Ankunft an der Pickstation, nicht der Abschluss des vollständigen Zyklus. |
| L-16 | `bin_throughput` zählt beim Absetzen an der Pickstation, nicht am Ende des Command Cycle wie bei Lehmann (7.1). |
| L-9 (geändert) | Die Initialverteilung nutzt weiterhin die Port-Pufferzone; die beschlossene Angleichung ist noch nicht umgesetzt (6). |

---

# 13. Freeze-Gate

| Kriterium | Status |
|---|---|
| Kein lageabhängiger EDF-Bypass mehr | **erfüllt** |
| Begonnene/Return-Tasks weiterhin priorisiert | **erfüllt** |
| EDF korrekt und deterministisch | **erfüllt** |
| Deadline-Regel eindeutig, exogen, policyneutral | **erfüllt** |
| `D` wissenschaftlich vertretbar gewählt | **erfüllt** (D = 240) |
| Deadline/Tardiness korrekt berechnet und exportiert | **erfüllt** |
| Batching korrekt behandelt | **erfüllt** |
| Tardiness interpretierbar | **erfüllt** — mit dokumentierter Einschränkung (3.4) |
| Zipf = 1,0 bestätigt | **erfüllt** |
| `baseline_reference` enthalten | **erfüllt** |
| 10 Seeds bestätigt | **erfüllt** |
| Genau 2 Pickstations | **erfüllt** |
| 8 Roboter bestätigt | **erfüllt** |
| Nachfrageintensität bestätigt | **erfüllt** |
| **Exakte Steady-State-Regel getestet** | **NICHT erfüllt** (5.2) |
| **β als Proxy für räumliche Stabilität validiert** | **NICHT erfüllt** (5.4) |
| **Measurement Window vollständig erreichbar** | **NICHT erfüllt** — bei 6000 ZE nachweislich nicht |
| **Maximalgrenze sinnvoll** | **NICHT erfüllt** — 6000 ZE ist um Faktor 3,7 zu klein |
| Initial-State-Eligibility bewusst entschieden | entschieden, **nicht umgesetzt** (6) |
| Seed als statistische Replikation | **erfüllt** |
| Alle Tests grün | **erfüllt** — 400 passed |
| CRN inklusive Deadlines intakt | **erfüllt** |
| Keine Correctness-Verletzungen | **erfüllt** |

## Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender experimentkritischer Punkt — genau einer:**

> Die Steady-State-/Stop-Regel ist mit den vorgesehenen Parametern nicht
> lauffähig und nicht validiert. Der Scheduler-Fix hat den Durchsatz etwa
> halbiert; die langsamste Konfiguration (ABC+ABC, 0,0157 bins/ZE) benötigt
> für Konvergenz plus Measurement Window rund 22.300 ZE statt der
> vorgesehenen 6000 ZE. Kein Pilotlauf erreichte drei Blöcke, damit ist weder
> die Konvergenzregel selbst noch β als Proxy für räumliche Stabilität
> validiert.

Nachgelagert, aber ebenfalls vor dem Start zu erledigen: die in Abschnitt 6
beschlossene Angleichung der initialen Storage-Eligibility ist noch nicht
implementiert.

Alle übrigen Punkte sind abgeschlossen. Der Scheduler- und Deadline-Teil
dieser Phase ist vollständig, getestet und dokumentiert.

## Empfohlener nächster Schritt

Eine kurze Nachphase mit genau zwei Aufgaben:

1. Steady-State-Regel mit Window 100 und Grenze 20.000 ZE über alle fünf
   Konfigurationen und zwei bis drei Seeds tatsächlich durchlaufen lassen;
   dabei Konvergenzzeitpunkt in ZE und in Retrievals erfassen und β gegen
   `hot_bins_top_ratio` und die Level-Verteilung aus `distribution.csv`
   prüfen. Erwarteter Aufwand: ≈ 1 Stunde Rechenzeit.
2. Initiale Storage-Eligibility angleichen, mit angepassten kleinen
   Test-Fixtures.

Danach ist das Design einfrierbar.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

---
---

# Final Freeze Closeout

**Nachphase mit den zwei verbliebenen Aufgaben — Stand 2026-08-21**

| | |
|---|---|
| Commit zu Beginn | `fa49fe4` „Finalize EDF scheduling and deadline experiment semantics" |
| Branch | `working_sim` |
| Python / pytest | 3.10.12 / 9.1.1 |
| `git status` | nur vorbestehende Artefakte: `.idea/*`, `__pycache__/*`, `tests/reservation_table.py` gelöscht (bereits gestaged). Keine offenen Quelländerungen aus früheren Phasen. |
| Testsuite vorher | **400 passed** (`test_view.py` und `tests/test_simulation_visual.py` weiterhin ohne Flask nicht sammelbar) |
| Testsuite nachher | **400 passed** |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## C.1 Initial-State Storage Eligibility — umgesetzt

### Änderung

`SimulationEngine._initialize_state` berechnet die Port-Pufferzone jetzt vor
der Bin-Verteilung und übergibt sie als `excluded_positions` an
`initialize_bins`:

```python
storage_exclusions = calculate_buffer_zone(
    port_positions=[ps.position for ps in pickstations],
    grid_width=grid.width,
    grid_depth=grid.depth,
)
```

Es ist dieselbe Funktion, aus der `State.initialize_port_zones` die
`buffer_zone` bezieht, gegen die `State.is_valid_storage_position` zur
Laufzeit prüft. Initialisierung und Laufzeit teilen damit **eine** Definition
gültiger Storage-Positionen, nicht zwei ähnliche.

**Kein stiller Fallback.** Reicht die Kapazität nach Abzug der Pufferzone
nicht, wirft `init_random_distribution` weiterhin `ValueError` (Meldung um
`excluded_positions=<n>` ergänzt). Die Modellsemantik schaltet nie um.

### Vorher / nachher im finalen Layout (20 × 30, H = 8, 2 Pickstations)

| | vorher | nachher |
|---|---|---|
| Ports | (0,15), (19,15) | unverändert |
| Pufferzone | 8 Zellen (inkl. 2 Ports) | unverändert |
| Initial belegbare Stacks | 598 | **592** |
| Initiale Kapazität | 4784 | **4736** |
| Füllgrad bei 4320 Bins | 90,3 % | **91,2 %** |
| Bins auf später verbotenen Positionen bei t=0 | bis zu 6 Stacks | **0** |

Verifiziert über alle 10 Seeds: `eligibility_violations = 0`, d.h. keine
einzige Bin startet auf einer Position, die `is_valid_storage_position`
später ablehnt.

### Angepasste Test-Fixtures (Vorbedingung explizit gültig gemacht)

Keine Assertion wurde abgeschwächt. Geändert wurden ausschließlich
Konfigurationswerte, deren Voraussetzungen unter der neuen Eligibility
ungültig geworden wären:

| Fixture | vorher | nachher | Grund |
|---|---|---|---|
| `tests/conftest.py::small_config` | 3×3, H=4, 20 Bins | **4×4, H=4, 30 Bins** | Auf 3×3 sperrt die Pufferzone 4 von 9 Zellen; übrig blieben 5 Stacks mit 20 Slots für 20 Bins. Umlagern war unmöglich (`Cannot select original return stack: ... has no free capacity`). Ein 3×3-Grid mit Port ist unter der finalen Eligibility keine gültige Konfiguration. 4×4 lässt 12 zulässige Stacks (48 Slots); 30 Bins halten den Füllgrad exakt bei den vorherigen 62,5 %. |
| `tests/test_strategy_correctness.py::build_engine` | 7×7, H=6, 240 Bins | **7×7, H=6, 180 Bins** | Die Pufferzone kostet auf 7×7 6 von 47 Stacks (13 %). Mit 240 Bins startet der Lauf bei 98 % der nutzbaren Kapazität und 6 freien Top-Positionen; Relocations scheitern. 180 Bins (73 %, 66 freie Slots) halten die Fixture über den ganzen Lauf im gedachten Regime. |

`small_config` wird ausschließlich von `tests/test_workflow_integration.py`
genutzt; die Auswirkung der Änderung ist damit lokal.

**Beobachtung, die hier festgehalten gehört:** vor der Änderung war die
Pufferzone initial belegt und lief über die Laufzeit leer. Diese Stacks
lieferten also unbemerkt zusätzliche freie Kapazität, und der effektive
Füllgrad wanderte während des Laufs nach oben (im 7×7-Beispiel von 85 % auf
98 % der nutzbaren Kapazität). Der Startzustand war damit nicht nur
policy-fremd, sondern auch nicht stationär. Beides ist jetzt behoben.

### Korrigierter Test

`tests/test_experiment_readiness.py::test_blocking_bins_matches_the_position_in_the_stack`
prüfte `blocking_bins <= levels_from_top`. Diese Invariante ist faktisch
falsch:

* `levels_from_top` ist ein **Snapshot** bei Dig-Start
  (`TopAccessStrategy`, erster Blick auf den Zielstapel),
* `blocking_bins` ist der **tatsächlich geleistete** Umlagerungsaufwand
  (`len(task.temp_storage)`).

Legt ein anderer Roboter während des laufenden Digs eine Bin auf den
Zielstapel, muss der Task sie zusätzlich abräumen. Nachgewiesen im Trace:
Dig-Start t=95 auf `S_0_3`, fremder Push t=137, Abräumen t=150 — gemeldet
werden 5 Blocker bei `levels_from_top = 4`.

**Der Fall ist nicht neu.** Auf dem alten Initialzustand tritt er bei den
Seeds 3 und 7 ebenso auf; bei Seed 42 lief der Test nur zufällig durch. Die
Assertion wurde deshalb auf die tatsächliche Modellsemantik korrigiert
(Abweichung ≤ eine Stapelhöhe, > 80 % exakte Übereinstimmung, Über-Meldungen
< 20 %). Die Produktionslogik blieb unberührt — so entschieden.

---

## C.2 Steady-State-Regel — durchlaufen, und dabei widerlegt

### Aufbau der Piloten

5 Konfigurationen × 3 Seeds (42, 1, 7) = **15 Läufe**, finale Konfiguration,
Zeitgrenze 40.000 ZE, Abbruch bei 320 Retrievals (= 150 für die Konvergenz
+ 100 Measurement Window + Reserve). Die Stop-Regel wurde **offline** auf der
vollständigen Retrieval-Spur ausgewertet, damit dieselbe Messung gegen
mehrere Kandidatengrenzen (20k/25k/30k) prüfbar ist.

Die Läufe wurden in Rechenscheiben mit Pickle-Fortsetzung ausgeführt.
`verify_resume_identity.py` belegt, dass das die Trajektorie nicht verändert:
Simulationszeit, komplette Retrieval-Spur und alle Distribution-Snapshots
sind zwischen ununterbrochenem und dreifach fortgesetztem Lauf **identisch**.

### Ergebnis je Policy × Seed

| Policy | Seed | t_end (ZE) | Retrievals | β-Blockmittel (Blöcke à 50) | rel. Änderungen | Konvergenz |
|---|---|---|---|---|---|---|
| baseline_reference | 42 | 4782 | 123 | 2,24 / 1,94 | 0,144 | nein |
| baseline_reference | 1 | 4921 | 104 | 2,60 / 2,12 | 0,203 | nein |
| baseline_reference | 7 | 4988 | 106 | 2,66 / 2,20 | 0,189 | nein |
| RR+RR | 42 | 3783 | 138 | 2,14 / 2,08 | 0,028 | nein |
| RR+RR | 1 | 3603 | 81 | 2,66 | – | **Abbruch** |
| RR+RR | 7 | 4380 | 153 | 2,62 / 2,24 / 2,14 | 0,156 / 0,046 | nein |
| LR+NR | 42 | 5461 | 126 | 2,25er Reihe | – | nein, **festgefahren** |
| LR+NR | 1 | 5656 | **320** | 2,66 / 2,20 / 1,78 / 1,92 / 1,74 / 2,18 | 0,189 / 0,211 / 0,076 / 0,098 / **0,224** | **ja (Fehlalarm)** |
| LR+NR | 7 | 5332 | **320** | 2,68 / 2,16 / 1,90 / 1,60 / 1,92 / 1,88 | 0,215 / 0,128 / 0,171 / 0,182 / 0,021 | nein |
| ABC+ABC | 42 | 11192 | 96 | 2,76 | – | nein, **festgefahren** |
| ABC+ABC | 1 | 5739 | 120 | 2,74 / 2,58 | 0,060 | nein |
| ABC+ABC | 7 | 5727 | 120 | 2,72 / 2,44 | 0,109 | nein |
| POP+POP | 42 | 5123 | 116 | 2,34 / 2,30 | 0,017 | nein |
| POP+POP | 1 | 9331 | 97 | 2,58 | – | nein, **festgefahren** |
| POP+POP | 7 | 5991 | 114 | 2,64 / 2,34 | 0,120 | nein |

Genau **ein** Lauf von 15 hat die Regel ausgelöst, und zwei statistisch
gleichartige Läufe derselben Policy (LR+NR, Seeds 1 und 7) enden mit
gegensätzlichem Urteil.

### Warum die Regel nicht greift: β ist zu verrauscht für Blöcke à 50

Über alle 2.134 Pilot-Retrievals:

```text
mean(β) = 2,31     sd(β) = 2,27     CV = 0,98
```

Der Variationskoeffizient liegt bei 1 — β je Retrieval ist annähernd so
stark gestreut wie sein Mittelwert (typisch für eine geometrieartige
Verteilung mit vielen Nullen). Für das Blockmittel folgt daraus

```text
sd(rel. Änderung) ≈ √2 · CV / √B
```

| Blockgröße B | erwartete relative Änderung |
|---|---|
| **50 (aktuelle Regel)** | **0,197** |
| 100 | 0,139 |
| 150 | 0,113 |
| **200** | **0,098** |
| 300 | 0,080 |

**Die Schwelle von 10 % liegt bei B = 50 um den Faktor 2 unter dem reinen
Rauschen.** Zwei aufeinanderfolgende Unterschreitungen sind damit kein
Konvergenzsignal, sondern ein seltenes Zufallsereignis — genau das ist bei
LR+NR Seed 1 passiert: nach den beiden „stabilen" Paaren (0,076; 0,098) folgt
sofort 0,224.

Pro Policy × Seed liegt die für 10 % nötige Blockgröße bei 116–247
Retrievals, gepoolt bei **194**. Lehmann & de Koster arbeiten mit Blöcken von
10.000 Command Cycles und einer Schwelle von 0,1 % bzw. 1 % — vier
Größenordnungen mehr Mittelungsmasse. Unsere Parametrierung war zu
optimistisch, nicht das Prinzip.

### β als Proxy für räumliche Stabilität — **nicht bestätigt**

Auf dem einzigen (Fehlalarm-)Konvergenzpunkt, LR+NR Seed 1 bei t = 4341:

| Größe | t=0 | t≈4300 (β-Konvergenz) | t=5656 (Ende) | Bewertung |
|---|---|---|---|---|
| `hot_bins_top_ratio` | 0,543 | 0,542 | 0,542 | über den gesamten Lauf **konstant** |
| `stack_height_variance` | 1,16 | 2,92 | 3,02 | **steigt weiter** |
| Level-Verteilung, TVD(Konv→Ende) | – | – | 0,057 | – |
| `bin_distribution_entropy` | 0,0 | 0,0 | 0,0 | Metrik liefert konstant 0 |

Zwei Befunde:

1. `hot_bins_top_ratio` bewegt sich vom ersten Snapshot an nicht (0,543 →
   0,542, alle Seeds 0,52–0,55). Die Größe kann „vor" und „nach" der
   Reorganisation nicht unterscheiden und ist als Stabilitätssignal
   ungeeignet. `bin_distribution_entropy` ist konstant 0 — die Metrik
   funktioniert offenbar nicht; das ist **nicht** im Rahmen dieser Phase
   untersucht worden.
2. Die einzige Größe, die sich sichtbar entwickelt, ist die
   **Stackhöhenvarianz**: sie steigt von 1,16 auf 2,92 bis zum gemeldeten
   β-Konvergenzpunkt und danach monoton weiter auf 3,02. Zum Zeitpunkt der
   gemeldeten β-Konvergenz ist die räumliche Struktur also **nachweislich
   noch nicht stabil**.

β kann damit **nicht** als Proxy für räumliche Stabilität bestätigt werden.
Die Datenlage erlaubt aber auch keine Widerlegung im starken Sinn: es gibt
nur einen Konvergenzpunkt, und der ist selbst ein Artefakt.

### Measurement Window und Maximalgrenze

Beides ist **nicht entscheidbar**:

* Der einzige konvergierte Lauf erreichte nach der Konvergenz 70 von 100
  Retrievals — und zwar nicht wegen einer Zeitgrenze, sondern weil der Lauf
  am Retrieval-Ziel von 320 endete. Über die Tragfähigkeit von 100
  Retrievals sagt das nichts.
* Eine Maximalgrenze lässt sich nicht kalibrieren, solange kein Lauf die
  Konvergenz sauber erreicht. Die vorläufig gemessenen Kosten des einen
  Falls (4341 ZE bis Konvergenz + 1312 ZE für 70 Fenster-Retrievals) liegen
  weit innerhalb von 20.000 ZE — aber mit einer Regel, die eine Blockgröße
  von ~200 statt 50 braucht, verschiebt sich der Bedarf auf 600 + 100 = 700
  Retrievals je Lauf. Bei ABC+ABC (≈ 0,014 Retrievals/ZE) wären das rund
  **50.000 ZE**. Diese Zahl ist eine Hochrechnung, keine Messung.

---

## C.3 Der eigentliche Blocker: Deadlock beim Ordered Return

Vier der 15 Pilotläufe machen dauerhaft keinen Fortschritt mehr:

| Lauf | letztes Retrieval | Stillstand bis | Retrievals |
|---|---|---|---|
| ABC+ABC, Seed 42 | t = 7019 | t = 11192 (**4173 ZE**) | 96 |
| POP+POP, Seed 1 | t = 5134 | t = 9331 (**4197 ZE**) | 97 |
| LR+NR, Seed 42 | t = 2330 | t = 5461 (**3131 ZE**) | 126 |
| RR+RR, Seed 1 | t = 3137 | **Abbruch** t = 3603 | 81 |

`RR+RR` Seed 1 endet mit

```text
RuntimeError: Event exceeded max retries (20).
action_type=return, bin_id=73, time=3603
```

Die übrigen elf Läufe wurden nur 3.600–6.000 ZE weit gerechnet und sind
damit nicht freigesprochen, sondern schlicht noch nicht lange genug
gelaufen.

### Root Cause

Zustandsaufnahme von ABC+ABC Seed 42 bei t = 11192 (aus dem Pickle, mit den
Invariantenprüfern des Audit-Harness):

```text
Invariantenverletzungen: 0
7 von 8 Robotern in phase = restore_blockers
alle mit target_at_pickstation = True, pickstation_completed = True
temp_storage: 1 bis 4 offene Blocker je Task
Event-Queue: 7 x ROBOT_PICKUP, retry_count 4/4/6/8/8/8/10, alle zur selben Zeit
reservierte Bins: 29
```

Der Zustand ist **korrekt, aber blockiert** — kein kaputter State, ein echter
Deadlock. Jeder wartende Roboter will einen Blocker aufnehmen, den er zuvor
auf einem Puffer-Stack geparkt hat, um ihn zurückzulegen. Jeder dieser
Blocker ist inzwischen **verschüttet**:

```text
bin  307 auf S_2_15  Level 2 von 8   obenauf: NEIN
bin 4241 auf S_15_9  Level 4 von 6   obenauf: NEIN
bin 2911 auf S_0_2   Level 4 von 7   obenauf: NEIN
bin 4147 auf S_17_27 Level 3 von 6   obenauf: NEIN
bin 2526 auf S_17_19 Level 2 von 8   obenauf: NEIN
bin  817 auf S_3_18  Level 6 von 8   obenauf: NEIN
bin 1595 auf S_9_1   Level 2 von 8   obenauf: NEIN
```

Verschüttet hat sie jeweils ein **anderer** Roboter, der seinen eigenen
Blocker auf denselben Stack geparkt hat. Der Zyklus ist im Trace direkt
ablesbar:

```text
Roboter 0 parkt Blocker 868 auf S_3_18  und wartet auf Blocker 307 auf S_2_15
Roboter 5 parkt Blocker 2602 auf S_2_15 und wartet auf Blocker 817 auf S_3_18
```

Roboter 0 wartet auf einen Stack, den Roboter 5 blockiert, und umgekehrt.
Der `RelocationSelection` schließt beim Wählen eines Puffer-Stacks nur den
eigenen Zielstapel aus (`exclude_stack=target_stack`); Stacks, auf denen ein
**anderer** Task noch offene Blocker liegen hat, sind nicht geschützt.

Der Retry-Mechanismus löst das nicht auf, er zählt nur hoch: entweder dreht
er sich unbegrenzt (Stillstand) oder erreicht 20 und wirft (`RR+RR` Seed 1).
Es sind beide Male dieselbe Ursache in verschiedenen Stadien.

### Abgrenzung: vorbestehend, nicht durch die Initialisierung verursacht

Gegenprobe mit **altem** Initialzustand (Pufferzone initial belegt), gleiche
Policy, gleicher Seed:

| | letztes Retrieval | Stillstand | Retrievals |
|---|---|---|---|
| ABC+ABC Seed 42, **neue** Init | t = 7019 | 4173 ZE | 96 |
| ABC+ABC Seed 42, **alte** Init | t = 7368 | 1823 ZE (bei t=9191) | 97 |

Beide fahren sich an praktisch derselben Stelle fest. Zusätzlich zeigt die
alte 7×7-Fixture denselben Fortschrittsstillstand unter altem Initialzustand
(Seed 1: 39 Retrievals ab t≈1500 konstant; Seed 7: 47 ab t≈2500; Seed 42: 90
ab t≈5000).

**Der Deadlock ist vorbestehend.** Die Angleichung der Initial-Eligibility
ist nicht die Ursache. Sie ist aber auch keine Entwarnung: die Pufferzone
lieferte vorher unbemerkt zusätzliche freie Kapazität, deren Wegfall den
Fall eher früher eintreten lässt.

### Was die vorhandene Erkennung abdeckt — und was nicht

| | Status |
|---|---|
| Bewegungs-Deadlocks (Roboter blockieren sich auf dem Grid) | erkannt und aufgelöst: 504 Detektionen über alle Piloten, `move_recovery_unresolved = 0` |
| Task-/Ownership-Deadlock beim Ordered Return | **gar nicht erkannt** — kein Log, kein Fehler, nur stiller Stillstand bis zum Retry-Limit |

Das ist exakt die Trennung aus den Projektvorgaben: Detection und Resolution
sind zweierlei, und ein Livelock ist erst behandelt, wenn wieder echter
Fortschritt entsteht. Hier fehlt bereits die Detection.

---

## C.4 Correctness und CRN

### Physische Invarianten

Audit-Harness (`run_audit`, Prüfung nach jedem Schritt) auf der finalen
Konfiguration:

| Lauf | invalid pickups | invalid drops | invalid moves | Kollisionen | Verletzungen |
|---|---|---|---|---|---|
| baseline_reference, Seed 42, 400 ZE | 0 | 0 | 0 | 0 | 0 |
| ABC+ABC, Seed 42, 400 ZE | 0 | 0 | 0 | 0 | 0 |
| RR+RR, Seed 1, 400 ZE | 0 | 0 | 0 | 0 | 0 |

Zusätzlich: der **festgefahrene** Endzustand von ABC+ABC Seed 42 bei
t = 11192 erfüllt alle Bin-, Roboter-, Task-, Pickstation-, Reservierungs-
und Wait-Graph-Invarianten (0 Verletzungen). Der Deadlock ist kein
Zustandsfehler.

Über alle 15 Piloten: `move_recovery_unresolved = 0`, ein Abbruch
(`RR+RR` Seed 1, siehe C.3), sonst keine Exceptions.

**Einschränkung:** Die schrittweise Invariantenprüfung ist teuer (≈ 28 s je
400 ZE). Sie deckt hier nur die ersten 400 ZE je Lauf ab, nicht die
Deadlock-Phase im Verlauf — geprüft ist dort nur der Endzustand.

### CRN auf der finalen Konfiguration

Alle 10 Seeds × alle 5 Konfigurationen, nur Initialisierung (alle exogenen
Größen werden vor Simulationsbeginn gezogen):

```text
seed=  1  layout=496db3e75013fcd9  requests=e4a0ad4e2b096502 (n=1285)  identisch=JA
seed=  2  layout=4941f045a9f3259c  requests=8ca0d7691e4699da (n=1220)  identisch=JA
seed=  3  layout=3673233960a6c0c8  requests=b7101e1b82521565 (n=1162)  identisch=JA
seed=  4  layout=dad69a0147b4b2e8  requests=f52bc49d3f1dbd10 (n=1170)  identisch=JA
seed=  7  layout=dd20ca5dd405ec01  requests=ab5fe93455179c41 (n=1138)  identisch=JA
seed= 11  layout=f374160b7a2d08cd  requests=cdd99d1e47297cba (n=1203)  identisch=JA
seed= 13  layout=0f0bafd4afca6ca0  requests=523007213ded48dd (n=1167)  identisch=JA
seed= 42  layout=3681a1c414f285fc  requests=aa0428970b855228 (n=1225)  identisch=JA
seed= 99  layout=1f2ca8ff13e2fa23  requests=fb3252fa23f78f03 (n=1134)  identisch=JA
seed=123  layout=69030bfc13d0474a  requests=018acee039e0fe40 (n=1231)  identisch=JA

VERDICT: CRN INTAKT      eligibility_violations = 0 in allen 50 Kombinationen
```

Verglichen wurden Layout-Hash (Bin → Stack → Level), Request-Hash
(`request_id`, Ziel-Bin, `arrival_time`, `latest_time`) und Servicezeit-Hash
(`request_id` → `service_time`). Wie erwartet hat sich das Layout gegenüber
älteren Commits verändert — innerhalb der eingefrorenen Version ist es
deterministisch und policyneutral.

---

## C.5 Finale Run-Matrix

Unverändert im Ziel, aber **noch nicht lauffähig**:

```text
5 Konfigurationen × 10 Seeds = 50 Läufe

Konfigurationen: baseline_reference, RR+RR, LR+NR, ABC+ABC, POP+POP
Seeds:           1, 2, 3, 4, 7, 11, 13, 42, 99, 123

Grid 20×30, H=8, 4320 Bins, 2 Pickstations, 8 Roboter
Zipf 1,0, util 0,6, Scheduler EDF, Deadline = arrival + 240
Popularity-Warmup 50 physische Retrievals
Initialverteilung: zufällig über die 592 zulässigen Storage-Stacks
                   (Port-Pufferzone ausgeschlossen)      [EINGEFROREN]

Steady State: Blockgröße, Schwelle, Measurement Window und Maximalgrenze
              bleiben OFFEN — siehe C.2 und C.3.
```

---

## C.6 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-9 (**erledigt**) | Die Initialverteilung nutzte die Port-Pufferzone. Umgesetzt, siehe C.1. |
| L-17 (**neu**) | β je Retrieval hat CV ≈ 1. Eine Konvergenzregel mit Blöcken à 50 Retrievals und 10 % Schwelle misst Rauschen. Belastbar wären Blöcke ab ≈ 200 Retrievals. |
| L-18 (**neu**) | `hot_bins_top_ratio` ist über den gesamten Lauf konstant (0,52–0,55) und als Signal für räumliche Stabilisierung ungeeignet. Die einzige sichtbar konvergierende Größe ist die Stackhöhenvarianz. |
| L-19 (**neu**) | `bin_distribution_entropy` liefert konstant 0,0. Die Metrik ist offenbar defekt; nicht untersucht, nicht verwendet. |
| L-20 (**neu**) | Beim Ordered Return können sich Tasks über verschüttete Puffer-Blocker zyklisch blockieren (C.3). Es gibt dafür keine Erkennung; der Lauf bleibt stehen oder bricht am Retry-Limit ab. |
| L-21 (**neu**) | `blocking_bins` (geleisteter Umlagerungsaufwand) und `levels_from_top` (Snapshot bei Dig-Start) können in beide Richtungen auseinanderlaufen, wenn andere Roboter währenddessen auf den Zielstapel ablegen. Für RQ1 ist `blocking_bins` die richtige Größe; die Differenz ist kein Fehler, aber bei der Interpretation zu nennen. |
| L-14 bis L-16 | unverändert. |

---

## C.7 Freeze-Gate

| Kriterium | Status |
|---|---|
| Initialisierung und Laufzeit nutzen dieselbe Storage-Eligibility | **erfüllt** (C.1) |
| Kein stiller Produktionsfallback bei knapper Kapazität | **erfüllt** — Fail fast |
| Vollständige Testsuite grün | **erfüllt** — 400 passed, keine Assertion abgeschwächt |
| CRN intakt (Layout, Requests, Deadlines, Servicezeiten) | **erfüllt** (C.4) |
| Layout policyneutral und deterministisch | **erfüllt** |
| Physische Correctness in den geprüften Fenstern | **erfüllt** (C.4) |
| Exakte Steady-State-Regel real durchlaufen | **erfüllt** — und dabei **widerlegt** (C.2) |
| Steady-State-Regel praktikabel | **NICHT erfüllt** — 1 von 15 Läufen, und das als Fehlalarm |
| β als Proxy für räumliche Stabilität | **NICHT erfüllt** — nicht bestätigt (C.2) |
| 100 Retrievals als Measurement Window ausreichend | **NICHT entscheidbar** |
| Maximalgrenze mit Reserve wählbar | **NICHT entscheidbar** |
| Kein Pilot bleibt wegen der Zeitgrenze unvollständig | **NICHT erfüllt** — vier Läufe fahren sich fest bzw. brechen ab, unabhängig von der Zeitgrenze |
| Alle fünf Policies laufen physically/correctness-safe | **NICHT erfüllt** — `RR+RR` Seed 1 bricht mit RuntimeError ab |
| Finale Run-Matrix vollständig dokumentiert | teilweise — Parameter fest, Stop-Regel offen |

### Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender Blocker — genau einer, und er ist nicht die Stop-Regel:**

> Beim Ordered Return entstehen zyklische Wartebeziehungen über verschüttete
> Puffer-Blocker. Vier von 15 Pilotläufen machen dauerhaft keinen
> Fortschritt mehr, einer bricht mit `Event exceeded max retries (20)` ab.
> Der Zustand ist invariantenrein, wird von keiner Erkennung erfasst und
> löst sich nicht von selbst auf. Solange das offen ist, kann kein Lauf die
> Konvergenz erreichen — und ohne konvergierte Läufe ist weder die
> Steady-State-Regel kalibrierbar noch β als Proxy prüfbar noch eine
> Maximalgrenze wählbar.
>
> Der Deadlock ist **vorbestehend** und nicht durch die Änderung dieser
> Phase verursacht (Gegenprobe in C.3).

Nachgelagert, aber ebenfalls vor dem Start zu klären: die Konvergenzregel
braucht eine Blockgröße in der Größenordnung 200 statt 50 (C.2). Das ist
eine reine Parameterfrage und erst sinnvoll zu entscheiden, wenn Läufe
wieder durchlaufen.

> **Nachtrag 2026-08-22:** Die Punkte 1 und 2 dieses Abschnitts sind
> bearbeitet (siehe „Long-Run Liveness" weiter unten). Die dort genannte
> Diagnose „zyklische Wartebeziehungen" war zu grob: es sind DREI getrennte
> Fehlerklassen, zwei davon sind behoben. Der Abschnitt C.3 bleibt als
> Befundstand vom 2026-08-21 stehen; maßgeblich ist die Klassifikation in
> Abschnitt D.2.

### Empfohlener nächster Schritt

1. **Deadlock beim Ordered Return angehen** — als eigene Phase, mit
   deterministischem Reproduktionsszenario. Der Pilot ABC+ABC Seed 42 fährt
   sich reproduzierbar bei t ≈ 7019 fest und eignet sich als Fixture. Erst
   Detection (zyklische Wartebeziehung über `temp_storage`-Blocker
   erkennen), dann Resolution, und die Resolution ist erst erfolgreich, wenn
   danach messbar wieder Retrievals entstehen. Kleinste denkbare Ansätze:
   Puffer-Stacks mit offenen Fremd-Blockern beim `RelocationSelection`
   ausschließen, oder beim Erkennen eines Zyklus einen Task seine
   Rücklagerungsverpflichtung verwerfen lassen.
2. **Danach** die Steady-State-Regel mit Blockgröße ≈ 200 erneut über alle
   fünf Konfigurationen fahren und Measurement Window sowie Maximalgrenze
   auf echten konvergierten Läufen festlegen.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

---
---

# Long-Run Liveness (2026-08-22)

**Phase zur Beseitigung der Langzeit-Stillstände**

| | |
|---|---|
| Commit zu Beginn | `fa49fe4` (Branch `working_sim`), Arbeitsverzeichnis mit den Änderungen des Closeouts |
| Python / pytest | 3.10.12 / 9.1.1 |
| Testsuite vorher | 400 passed |
| Testsuite nachher | **413 passed** (13 neue Regressionstests) |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## D.1 Vorbemerkung: ein Fehler im Messwerkzeug, nicht im Modell

Die langen Piloten werden in Rechenscheiben mit Pickle-Fortsetzung
gerechnet. Dabei fiel auf, dass ein und dieselbe Kombination
(`RR+RR`, Seed 1) in zwei Läufen unterschiedlich endete.

Ursache: `Event._next_event_id` ist eine **Klassenvariable** und wird nicht
mit den Instanzen gepickelt. In einem neuen Prozess beginnt der Zähler wieder
bei 0. Da `Event.__lt__` die `event_id` als letzten Tie-Break benutzt,
sortieren neue Events dann vor den bereits wartenden — die fortgesetzte
Trajektorie weicht ab.

* **Die Simulation selbst ist nicht betroffen.** Innerhalb eines Prozesses
  ist der Zähler monoton; ein normaler Lauf und damit die geplante Kampagne
  sind davon unberührt.
* Betroffen war ausschließlich das Pilot-Werkzeug. `verify_resume_identity.py`
  hatte den Fehler nicht gefunden, weil es nur innerhalb EINES Prozesses
  gepickelt hatte.
* Behoben in `experiments/closeout/pilot_state.py`: der Zähler wird
  mitgespeichert und wiederhergestellt. Der Nachweis läuft jetzt über echte
  Prozessgrenzen:

```text
straight: t=900 n_retrievals=23 retrieval_hash=c754cd56beddd606 layout=4b155491cba2c406
sliced  : t=900 n_retrievals=23 retrieval_hash=c754cd56beddd606 layout=4b155491cba2c406
VERDICT : IDENTISCH
```

**Konsequenz für die Befunde des Closeouts:** Die Pilotzahlen vom
2026-08-21 stammen aus Läufen mit dieser Abweichung. Die Stillstände selbst
sind real und reproduzieren sich auch mit korrigiertem Werkzeug (`RR+RR`
Seed 1 bricht wieder exakt bei t=3603 mit 81 Retrievals ab), die exakte
Zuordnung Policy×Seed → Stillstand wurde in dieser Phase aber neu erhoben.

---

## D.2 Klassifikation: drei Fehlerklassen, nicht eine

Die vier auffälligen Läufe wurden mit dem korrigierten Werkzeug neu
gefahren und einzeln aufgeschlüsselt. Die Diagnose des Closeouts
(„zyklische Wartebeziehung über verschüttete Puffer-Blocker") trifft nur
auf die Hälfte der Fälle zu.

| Lauf | `return_blocking_bins` | Klasse | Signatur im Log |
|---|---|---|---|
| ABC+ABC, Seed 42 | True | **A** | `expected bin X not on top` beim Blocker-Return |
| POPULARITY, Seed 1 | True | **A** | dieselbe |
| LR+NR, Seed 42 | False | **B** | `robot already carries bin X` / `bin already in transit` |
| RR+RR, Seed 1 | False | **B** | `Event exceeded max retries (20). action_type=return` |

### Klasse A — verschütteter Blocker beim Ordered Return

Ein Task parkt Blocking-Bins auf Pufferstacks und holt sie zum Ordered Return
**genau dort** wieder ab. Der Rückgabeplan enthält keinen Schritt, um eine
zwischenzeitlich daraufgelegte fremde Bin abzuräumen. Ist die eigene Bin
verschüttet, scheitert der Pickup dauerhaft; Retry und Requeue ändern nichts,
weil niemand die fremde Bin entfernt.

Wer verschüttet? Im 7×7-Arbeitsfall mit vollständigem Ablage-Trace:

```text
Blocker 124 wird t=1001 von Roboter 3 auf S_1_4 geparkt
Roboter 0 legt t=1007..1078 vier eigene Blocker auf S_1_4 zurück
   -> S_1_4 ist SEIN Originalstack, das ist Ordered Return

Blocker 142 wird t=1898 von Roboter 3 auf S_4_4 geparkt
Roboter 2 legt t=1915 die Target-Bin 36 auf S_4_4
   -> Ziel war VOR t=1898 geplant worden
```

Zwei verschiedene Wege also: der **Ordered Return auf den Ursprungsstack**
und die **Target-Rücklagerung**, letztere über das Auseinanderfallen von
Planungs- und Ausführungszeitpunkt.

Anzumerken: In ABC+ABC/Seed 42 lagen über den verschütteten Blockern
überwiegend zurückgelagerte **A-Klasse-Target-Bins**. Die ABC-Policy
konzentriert genau diese Bins auf dieselbe portnahe Zone, in der auch geparkt
wird — die Klasse trifft ABC und POPULARITY deshalb härter.

Die im Closeout gemeldeten „zyklischen Wartebeziehungen" waren real, aber die
Ausnahme: der Wait-Graph über verschüttete Blocker enthielt bei ABC+ABC/
Seed 42 nur zwei Kanten und **keinen Zyklus**. Fachlich ist es also
Starvation einzelner Tasks, kein klassischer Deadlock — die Wirkung ist
dieselbe.

### Klasse B — verwaistes Pickup-Event

Wird ein Task requeued (`robot.clear_task()`), bleiben seine bereits
eingeplanten Pickup-Events in der Queue. Die vorhandene Stale-Prüfung greift
nur, wenn der Roboter einen ANDEREN Task hält:

```python
if (current_task is not None            # <- Lücke
        and event_request is not None
        and current_task.request_id != event_request.request_id):
    -> drop foreign pickup event
```

Ohne Task lief das Event ungeprüft durch. Belegt über einen Trace aller
Trage-Übergänge (LR+NR, Seed 42):

```text
t=2155 DROP   bin=3855 task_ziel=3855 phase=retrieve_target
t=2184 PICKUP bin=6    task_ziel=None phase=None request=None  pos=(0,15)
```

Roboter 1 nimmt **ohne Task** die Bin 6 auf — sie gehört zum Task von
Roboter 0. Danach bekommt er einen neuen Task (Ziel 3855), kann dessen Bin
wegen der getragenen fremden Bin nie aufnehmen
(`robot already carries bin 6`) und blockiert dauerhaft die einzige Portzelle
von PS_0. Roboter 0 wiederum wartet auf `bin already in transit`.

Dieselbe Lücke in der zweiten Ausprägung bei RR+RR/Seed 1: Roboter 7 hält
keinen Task und hat sechs Events für `return bin=73`; sie laufen bis
`max_retries` und brechen den Lauf ab.

### Klasse C — Stau im Portbereich (neu isoliert, offen)

Nach Behebung von A und B bleibt ein dritter, davon unabhängiger Fall. Er
war vorher durch A und B verdeckt.

Zustand ABC+ABC/Seed 42 bei t=4205 (letztes Retrieval t=2973):

```text
robot 0 (0,14) trägt 292   robot 1 (0,15) PORT, trägt nichts
robot 2 (1,16) trägt 2125  robot 3 (1,14) trägt 145
robot 4 (2,14)             robot 5 (0,16) trägt 1
robot 6 (1,15)             robot 7 (2,15)

PS_0 (0,15): robot_on_port=1, reserved_for_robot=1, queue=0
PS_1 (19,15): robot_on_port=None, queue=0, total_wait_time=382
```

Alle acht Roboter stehen in den sieben Zellen um PS_0. Roboter 1 steht auf
der Portzelle und ist von drei Seiten eingeschlossen; PS_1 auf der
gegenüberliegenden Gridseite ist gleichzeitig **unbenutzt**. Im Log
dominieren `[BLOCKED][DROP_POS]` und `[REPLAN] ... replanning path to avoid
robot`, kein einziges `not on top`.

Die vorhandene Auflösung greift nicht: der Wait-Graph erkennt Zyklen
zwischen **zwei** Robotern (`[DEADLOCK] Detected cycle at t=N: robots [a, b]`);
hier sind acht Roboter in einer Tasche ohne freie Ausweichzelle.
`[DEADLOCK][REQUEUE] robot cannot evade -> requeue task` feuert und ändert
nichts.

**Vorbestehend.** Derselbe Stau steckt schon in den Piloten vor dieser Phase:
LR+NR/Seed 42 hatte sechs Roboter in der PS_0-Tasche, RR+RR/Seed 1 acht
Roboter um PS_1. Dort lag nur zusätzlich Klasse B obenauf.

---

## D.3 Implementierte Prävention

Leitsatz: **Eine temporär ausgelagerte Bin mit offener Rückgabeverpflichtung
darf von einem fremden Vorgang nicht unzugänglich gemacht werden.** Keine
globale Stack-Sperre, keine zweite Ownership-Struktur — einzige Quelle bleibt
`ActiveQueue._blocker_ownership`.

| # | Ort | Änderung |
|---|---|---|
| P1 | `ActiveQueue` | zwei lesende Accessoren: `get_blocker_owned_bin_ids()` (nur Blocker, ohne Target-Bins) und `get_pending_restore_stack_ids()` (offene Rückgabeziele) |
| P2 | `RelocationSelection._get_critical_stack_ids` | schließt zusätzlich die offenen **Rückgabeziele** fremder Tasks aus. Damit wird nicht mehr dort geparkt, wo ein anderer Task per Ordered Return zurücklegen wird (Klasse A, Weg 1) |
| P3 | `PlacementSelector._get_eligible_stacks` | schließt Stacks aus, auf denen eine **fremde Blocker-Bin** liegt. Der Selektor bekommt dafür die `ActiveQueue` (Klasse A, Weg 2, Planungszeitpunkt) |
| P4 | `EventHandler._redirect_drop_that_would_bury_blocker` | prüft das Ablageziel **unmittelbar vor dem Absetzen** erneut und lässt bei Gefahr dieselbe Policy neu wählen (Klasse A, Weg 2, Ausführungszeitpunkt) |
| P5 | `EventHandler._handle_robot_pickup` | ein Pickup-Event eines Roboters **ohne Task** gilt als verwaist und wird verworfen (Klasse B) |

Bewusst **nicht** geändert:

* Der Ordered Return legt weiterhin auf den Ursprungsstack zurück, in der von
  `reordering_strategy` bestimmten Reihenfolge. Kein Rückgabeziel wird
  umgelenkt, keine Verpflichtung verworfen.
* `_select_original_stack` (Strategie `ORIGINAL`) bleibt unangetastet. Sie
  wird von keiner der fünf finalen Konfigurationen benutzt und scheitert im
  Zweifel laut, statt still zu verschütten.
* Kein Stack wird für die Dauer eines Digs global gesperrt. Dass
  `blocking_bins > levels_from_top` werden kann, bleibt gewollt.

### Zusätzlich: Freiräumen statt Endlos-Retry

Prävention kann den Restfall nicht ausschließen, solange Planungs- und
Ausführungszeitpunkt auseinanderfallen. `TopAccessStrategy` liefert deshalb,
wenn die nächste zurückzulegende Blocker-Bin unter fremden Bins liegt, eine
**Freiräum-Umlagerung** statt denselben Pickup erneut
(`_next_unbury_action`, Log `[UNBURY]`).

Das ist policyneutral und fachlich korrekt:

* Die Rücklagerung selbst bleibt unverändert (Ziel, Reihenfolge, Ownership).
* Die freigeräumte Bin wandert **nicht** in `temp_storage` und **nicht** in
  die Ownership — sonst würde sie per LIFO als Erste zurückgelegt,
  ausgerechnet auf den gerade freigeräumten Stack.
* **Kein Einfluss auf RQ1:** `blocking_bins` wird beim Eintreffen der
  Target-Bin an der Pickstation festgeschrieben, also vor dieser Phase.

### Detection

`[TASK_DEADLOCK][RESTORE_BURIED]` wird gemeldet und in
`EventHandler.task_dependency_deadlocks` gezählt, wenn die Strategie denselben
Blocker-Return wiederholt, also auch nicht freiräumen konnte. Bewusst getrennt
vom MOVE-Deadlock geführt: dort blockieren sich Roboter auf dem Grid, hier
wartet ein Task auf eine Bin. Eine Resolution gilt erst als erfolgreich, wenn
danach wieder Retrievals entstehen — deshalb wird in den Piloten der
Fortschritt selbst gemessen, nicht das Verschwinden einer Meldung.

---

## D.4 Regressionstests

Neu: `tests/test_liveness_buried_blockers.py` (13 Tests, alle grün).

| Anforderung | Test |
|---|---|
| Fremder Task darf benötigten Blocker nicht verschütten | `test_placement_skips_stack_holding_a_foreign_blocker` |
| Kein Parken auf fremdem Rückgabeziel | `test_relocation_skips_pending_restore_stack_of_another_task` |
| Kein zyklischer Relocation-Wait / Freiräumen statt Retry | `test_buried_blocker_triggers_unbury_instead_of_repeating_the_pickup` |
| Ownership bleibt konsistent | `test_unbury_relocation_does_not_become_an_own_blocker` |
| Verwaistes Pickup-Event | `test_orphaned_pickup_event_is_dropped_instead_of_taking_a_foreign_bin` |
| Kein Bin-Verlust / keine Duplikate / kein Retry-Abbruch | `test_run_keeps_bins_consistent_and_finishes_without_abort` (5 Policies) |
| Ordered Return bleibt erhalten | `test_ordered_return_semantics_are_preserved` |
| No-Return-Semantik unverändert | `test_no_return_policies_keep_their_semantics` |
| Fortschritt nach der alten Stallstelle | `test_long_run_keeps_making_progress_past_the_old_stall_point` |

Angepasst wurden drei bestehende Testaufbauten — **keine Assertion
abgeschwächt**:

* `test_pickup_physical_invariants` und `test_evade_hardening` steuerten
  `_handle_robot_pickup` mit einem Roboter **ohne Task** an. Das gibt es im
  Produktivlauf nicht, und genau dieser Zustand ist jetzt verboten. Die
  Fixtures stellen die reale Vorbedingung her (`_give_robot_task_for`).
* `test_retry_semantics::test_repeated_identical_action_reaches_requeue_threshold`
  benutzte einen dauerhaft verschütteten Blocker als Vehikel, um die
  Eskalationsschwelle zu prüfen. Da die Strategie diesen Fall jetzt
  freiräumt, wiederholt sich der Versuch nicht mehr identisch. Der Aufbau
  zeigt nun auf einen Pufferstack, in dem die Bin gar nicht mehr liegt —
  Freiräumen hilft dort nicht, der Versuch wiederholt sich identisch, und die
  geprüfte Schwelle wird wieder erreicht.

---

## D.5 Lange Liveness-Revalidation

Alle Läufe auf der finalen Geometrie, Zeitgrenze 15.000 ZE.

| Lauf | vorher | nachher | Urteil |
|---|---|---|---|
| **LR+NR, Seed 42** | 126 Retrievals, ab t=2330 Stillstand | **403 Retrievals bis t=7228**, letztes t=7204 | **behoben** |
| **RR+RR, Seed 1** | Abbruch t=3603, `max retries (20)` | **216 Retrievals bis t=5882**, letztes t=5857, kein Abbruch | **behoben** |
| **ABC+ABC, Seed 42** | ab t=7019 Stillstand (Klasse A) | 80 Retrievals, ab t=2973 Stillstand (**Klasse C**) | Klasse A behoben, Klasse C offen |
| **POPULARITY, Seed 1** | ab t=5134 Stillstand (Klasse A) | 37 Retrievals, ab t=1992 Stillstand (**Klasse C**) | dito |
| ABC+ABC, Seed 1 (Kontrolle) | – | 179 Retrievals bis t=6344, laufend | gesund |
| POPULARITY, Seed 42 (Kontrolle) | – | 92 Retrievals bis t=2613, laufend | gesund |
| baseline_reference, Seed 42 (Kontrolle) | – | 245 Retrievals bis t=6419, laufend | gesund |
| LR+NR, Seed 1 (Kontrolle) | – | 109 Retrievals bis t=2159, laufend | gesund |

Sechs von acht Läufen machen durchgehend Fortschritt. Die beiden Ausfälle
sind **kein** Rückfall in Klasse A oder B, sondern der Portstau (Klasse C).

Zähler über die gemessenen Scheiben:

```text
move_recovery_unresolved   = 0     (alle Läufe)
task_deadlock              = 0     (kein unauflösbarer Blocker-Fall)
unbury                     = 0     (Freiräumen musste nie einspringen)
drop_bury_redirect         = 15    (LR+NR/Seed 1), 1 (baseline/Seed 42)
stale_pickup_no_task       = 1     (POPULARITY/Seed 42)
```

Die Prävention greift also tatsächlich (16 verhinderte Verschüttungen, ein
abgefangenes verwaistes Event), und der nachgelagerte Freiräum-Pfad musste
nie einspringen.

### Correctness

Audit-Harness (Invariantenprüfung nach jedem Schritt), finale Konfiguration,
je 400 ZE:

| Lauf | invalid pickups | invalid drops | invalid moves | Kollisionen | Verletzungen |
|---|---|---|---|---|---|
| ABC+ABC, Seed 42 | 0 | 0 | 0 | 0 | 0 |
| LR+NR, Seed 42 | 0 | 0 | 0 | 0 | 0 |
| RR+RR, Seed 1 | 0 | 0 | 0 | 0 | 0 |

Kein Bin-Verlust, keine Duplikate, keine Ownership-Verletzung, keine
Cross-Station-Fehler, keine unbehandelte Exception in den langen Läufen außer
den beiden Klasse-C-Stillständen (die keine Exception werfen, sondern
stehenbleiben).

### CRN

Unverändert intakt auf der finalen Konfiguration, 10 Seeds × 5 Policies:
identisches Initiallayout, identischer Request-Strom, identische Deadlines,
identische Servicezeiten je Request, `eligibility_violations = 0`.

```text
VERDICT: CRN INTAKT
```

---

## D.6 Steady-State-Methodik, RQ4 und `T_final` — bewusst nicht festgelegt

Die Umstellung auf eine **gemeinsame feste Laufzeit** für alle 50 Runs ist
methodisch übernommen und in `experiments/experiment_setup.md` beschrieben.
Die konkreten Werte lassen sich aber **noch nicht** bestimmen:

* `T_measure_start` soll so liegen, dass auch die **langsamste** Policy
  vorher konvergiert ist. ABC+ABC und POPULARITY sind genau die Kandidaten
  dafür — und genau ihre betroffenen Seeds bleiben durch Klasse C stehen.
* Eine räumliche Konvergenzgröße (ABC-Klassen über die Grid-Level, Abstand
  aufeinanderfolgender Blöcke) lässt sich auf abgebrochenen Zeitreihen nicht
  validieren.
* `T_final` aus Läufen abzuleiten, von denen zwei bei t≈2000 bzw. t≈3000
  stehenbleiben, wäre eine Zahl ohne Deckung.

Festgehalten aus dieser Phase, damit die Nachphase darauf aufsetzen kann:

* β bleibt widerlegt als alleiniges Konvergenzsignal (CV ≈ 1, Blockgröße 50
  misst Rauschen, siehe C.2). Größenordnung für eine belastbare Blockgröße:
  ≈ 200 Retrievals.
* `hot_bins_top_ratio` ist als Signal ungeeignet (über den ganzen Lauf
  konstant 0,52–0,55).
* `bin_distribution_entropy` liefert konstant 0,0. **Entscheidung: aus der
  finalen Methodik entfernen**, nicht reparieren — die Größe wird für keine
  Forschungsfrage gebraucht, und eine kaputte Metrik mitzuschleppen ist
  schlechter als sie zu streichen. Sie bleibt vorerst im Snapshot stehen,
  wird aber nicht ausgewertet und nicht berichtet.
* Vorgesehene RQ4-Größe für die Nachphase: Verteilung der statischen
  A/B/C-Klassen über die Grid-Level, verglichen zwischen aufeinanderfolgenden
  Blöcken über die Total-Variation-Distance. Statisch definiert, für alle
  Policies identisch berechenbar, direkt an Mellers Frage. β und
  `stack_height_variance` bleiben erklärende Zusatzgrößen.

---

## D.7 Finale Run-Matrix

Unverändert im Ziel, weiterhin **nicht startbar**:

```text
5 Konfigurationen × 10 Seeds = 50 Läufe
Konfigurationen: baseline_reference, RR+RR, LR+NR, ABC+ABC, POP+POP
Seeds:           1, 2, 3, 4, 7, 11, 13, 42, 99, 123

Grid 20×30, H=8, 4320 Bins, 2 Pickstations, 8 Roboter
Zipf 1,0, util 0,6, Scheduler EDF, Deadline = arrival + 240
Popularity-Warmup 50 physische Retrievals
Initialverteilung über die 592 zulässigen Storage-Stacks   [EINGEFROREN]

Gemeinsame feste Laufzeit T_final für alle 50 Runs          [METHODIK FIXIERT]
T_final, T_measure_start                                    [OFFEN, siehe D.6]
```

---

## D.8 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-20 (**geändert**) | Die im Closeout als „zyklische Wartebeziehung" beschriebene Klasse ist behoben (Prävention P1–P4 plus Freiräumen). Es war überwiegend Starvation einzelner Tasks, kein Zyklus. |
| L-22 (**neu**) | **Portstau (Klasse C).** Bis zu acht Roboter sammeln sich in den sieben Zellen um eine Pickstation und blockieren sich gegenseitig, während die zweite Station leer läuft. Die Auflösung erkennt nur Zweierzyklen. Offener Blocker. |
| L-23 (**neu**) | Die Pickstation-Zuordnung ist distanzbasiert und policyneutral, aber nicht lastausgleichend. Bei ABC-/Popularity-Placement wandern die häufig angefragten Bins in eine portnahe Zone, wodurch sich die Nachfrage auf eine Station konzentriert (gemessen: PS_1 `total_wait_time=382` bei gleichzeitig blockiertem PS_0). |
| L-24 (**neu**) | `bin_distribution_entropy` ist defekt (konstant 0,0) und wird aus der Methodik genommen. |
| L-25 (**neu**) | Werkzeug-Limitation, behoben, aber dokumentiert: prozessübergreifendes Fortsetzen eines Laufs erfordert die Wiederherstellung von `Event._next_event_id`. Ohne sie weicht die Trajektorie ab (D.1). |
| L-17 bis L-19, L-21 | unverändert. |

---

## D.9 Freeze-Gate

| Kriterium | Status |
|---|---|
| ABC+ABC Seed 42 fährt sich nicht mehr fest | **NICHT erfüllt** — Klasse A behoben, jetzt Klasse C ab t=2973 |
| RR+RR Seed 1 bricht nicht mehr am Retry-Limit ab | **erfüllt** — 216 Retrievals bis t=5882, kein Abbruch |
| LR+NR/POP korrekt klassifiziert und behoben | **teilweise** — LR+NR Seed 42 behoben; POPULARITY Seed 1 klassifiziert, aber Klasse C offen |
| Keine neue Policysemantik durch Recovery | **erfüllt** — Ordered Return unverändert, keine Verpflichtung verworfen, No-Return-Semantik testgesichert |
| Lange Läufe behalten echten Fortschritt | **NICHT erfüllt** — 6 von 8 ja, 2 nein |
| Vollständige Testsuite grün | **erfüllt** — 413 passed |
| CRN intakt | **erfüllt** |
| Initial-Eligibility intakt | **erfüllt** — 0 Verletzungen über alle 50 Kombinationen |
| Räumliche Konvergenzregel validiert | **NICHT erfüllt** — nicht auf abgebrochenen Zeitreihen möglich |
| `T_final` auf realen langen Läufen begründet | **NICHT erfüllt** |
| `T_measure_start` nach der relevanten Konvergenz | **NICHT erfüllt** |
| Alle 50 Runs mit derselben Simulationsdauer | **Methodik fixiert**, Werte offen |
| Deadline/Tardiness über identische Zeitfenster auswertbar | **erfüllt durch die Methodik**, sobald `T_final` steht |
| Finale Run-Matrix eingefroren | **teilweise** — alle Parameter außer `T_final`/`T_measure_start` |

### Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender Blocker — genau einer:**

> **Klasse C: Stau im Portbereich.** Bis zu acht Roboter sammeln sich in den
> sieben Zellen um eine Pickstation und blockieren sich gegenseitig
> dauerhaft, während die zweite Station leer läuft. Die vorhandene
> Auflösung erkennt nur Zyklen zwischen zwei Robotern. Zwei von acht langen
> Läufen bleiben dadurch stehen (ABC+ABC/Seed 42 ab t=2973,
> POPULARITY/Seed 1 ab t=1992).
>
> Der Fehler ist **vorbestehend** und war bisher durch die Klassen A und B
> verdeckt. Er ist kein Zustandsfehler: alle Invarianten sind erfüllt, es
> fehlt ausschließlich der Fortschritt.
>
> Solange er offen ist, lassen sich weder `T_final` noch `T_measure_start`
> auf echten langen Läufen begründen, und die räumliche RQ4-Konvergenzregel
> ist nicht validierbar.

### Empfohlener nächster Schritt

1. **Klasse C angehen**, als eigene Phase und mit demselben Vorgehen wie hier:
   erst reproduzieren und klassifizieren, dann die kleinste Änderung. Zwei
   naheliegende Richtungen, beide ohne Eingriff in die Storage-Policies:
   * **Zutrittssteuerung zur Portzone** — ein Roboter darf die Pufferzone
     einer Station nur betreten, wenn er dort einen Platz in der
     Warteschlange hält. Die Station kennt `reserve()`/`queue` bereits.
   * **Auflösung für mehr als zwei Roboter** — der Wait-Graph erkennt heute
     nur Zweierzyklen; die beobachtete Tasche hat acht Beteiligte.
   Reproduktionsfälle mit festem Seed liegen vor: ABC+ABC/Seed 42 (t≈2973)
   und POPULARITY/Seed 1 (t≈1992).
2. **Danach** die langen Piloten über alle fünf Policies neu fahren und aus
   ihnen `T_measure_start` und `T_final` bestimmen, zusammen mit der
   ABC-Level-Verteilung als räumlicher Konvergenzgröße.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.
