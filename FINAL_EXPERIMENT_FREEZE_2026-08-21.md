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

---
---

# Class C Port Congestion Remediation (2026-08-22)

| | |
|---|---|
| Commit zu Beginn | `1c127be` „Fix long-run task liveness and pilot resume determinism" (Branch `working_sim`) |
| `git status` | sauber bis auf das bereits gestagete Delete `tests/reservation_table.py` |
| Python / pytest | 3.10.12 / 9.1.1 |
| Testsuite vorher | 413 passed |
| Testsuite nachher | **425 passed** (12 neue Tests) |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## E.1 Reproduktion auf sauberem Prozesszustand

Beide Hauptfixtures reproduzieren exakt, aus einem frischen Prozess und mit
dem korrigierten Pilotwerkzeug:

| Lauf | letztes Retrieval | Retrievals |
|---|---|---|
| ABC+ABC, Seed 42 | t = 2973 | 80 |
| POPULARITY, Seed 1 | t = 1992 | 37 |

## E.2 Root Cause

Zustandsaufnahme ABC+ABC/Seed 42 bei t = 3255:

```text
robot 0 (1,14) traegt=292  next=(1,15) blockiert_von=6  freie_nachbarn=1
robot 1 (0,15) traegt=None station=None  next=None  pfadrest=[]  freie_nachbarn=0
robot 3 (0,14) traegt=145  next=(0,15) blockiert_von=1  freie_nachbarn=1
robot 5 (0,16) traegt=1    next=(0,15) blockiert_von=1  freie_nachbarn=1
robot 6 (1,15) traegt=None next=(0,15) blockiert_von=1  freie_nachbarn=0

PS_0 (0,15): reserved_for=1 robot_on_port=1  Zone 4 von 4 Zellen belegt
PS_1 (19,15): reserved_for=None robot_on_port=None  Zone 0 von 4 belegt
```

POPULARITY/Seed 1 zeigt dasselbe Bild an PS_1: Roboter 3 auf der Portzelle,
**0 freie Nachbarn**, Zone voll, PS_0 leer.

Der Kern ist in beiden Fällen derselbe:

> **Der Roboter auf der Portzelle hat keine freie Ausfahrt mehr.** Er kann die
> Station nicht räumen, alle nachfolgenden Roboter warten auf genau diese
> Zelle, und der Lauf macht keinen Fortschritt mehr.

Ein Port am Grid-Rand hat genau drei Nachbarn. Werden alle drei belegt, ist
der Portroboter eingeschlossen. Der Wait-Graph erkennt Zweierzyklen; hier
sind vier bis acht Roboter beteiligt.

### Warum die vorhandene Schutzlogik nicht griff

`PortExitGuard` existiert und war in `TrafficManager.request_path`
verdrahtet — die Absicht war also bereits vorhanden. Zwei Lücken in der
Verdrahtung machten sie wirkungslos:

**Lücke 1 — blind für stehende Roboter.**
Die Prüfung liest ausschließlich die **Reservierungstabelle**
(`get_blocked_at`, `_robot_on_port_at`). Ein Roboter, der steht (leerer Pfad,
keine künftigen Reservierungen), steht dort nicht. In beiden Stillständen war
genau das der Fall (`pfadrest=[]`). `get_robot_on_port` lieferte **False**,
`would_block_last_exit` brach sofort ab, und die letzte Ausfahrt durfte
belegt werden. Zusätzlich zählte `count_free_exits` besetzte Zellen als frei.

**Lücke 2 — der Fallback umging jede Prüfung.**
Scheitert `request_path`, baut `ActionCostModel.build_path` einen naiven
Manhattan-Pfad ohne Reservierung und ohne Exit-Prüfung
(`[WARNING] TrafficManager failed for robot N, using simple path`). Dieser
Fallback greift genau dann, wenn es eng wird — und lief quer durch die
Portzone.

Beides sind **Verdrahtungsfehler an einem vorhandenen Mechanismus**, keine
fehlende Architektur.

## E.3 Gewählte Lösung: Zutritt zur letzten Ausfahrt sperren

`TrafficManager.get_port_exit_cells_to_keep_free(robot_id)` fragt den
**tatsächlichen** Zustand ab statt der Reservierungstabelle:

* welcher Roboter steht laut `Pickstation.robot_on_port` physisch auf einem
  Port,
* welche seiner Nachbarzellen sind aktuell von Robotern besetzt.

Bleibt genau eine Ausfahrt frei, wird diese Zelle für **alle anderen**
Roboter gesperrt — in der Pfadplanung (`request_path` erweitert
`blocked_cells`) **und** im Manhattan-Fallback (dort über die bereits
vorhandene `blocked_cells`-Prüfung, die den Pfad verwirft).

Eigenschaften:

| Anforderung | Umsetzung |
|---|---|
| Keine willkürliche Kapazitätszahl | Die Regel folgt aus der Geometrie: ein Port am Rand hat drei Nachbarn, ein besetzter Port braucht mindestens eine Ausfahrt. Es wird nichts auf „maximal N Roboter" gesetzt. |
| Keine zweite Reservierungsstruktur | Quelle ist `Pickstation.robot_on_port` und die Roboterpositionen im State. |
| Deterministisch | reine Zustandsabfrage, feste Reihenfolge |
| Kein Zufall | testgesichert (`test_rule_consumes_no_randomness`) |
| Policyneutral | keine Policy wird gesondert behandelt; die Regel kennt keine Storage-Strategie |
| Der Eingeschlossene bleibt handlungsfähig | für den Roboter auf dem Port selbst wird nichts gesperrt |
| Kein neues Ausschlussrisiko | das eigene Ziel eines planenden Roboters wird nie gesperrt |

**Bewusst NICHT geändert:** die Pickstation-Zuordnung. Es wird nichts
dynamisch auf die andere Station umgeleitet. Zu beheben war fehlende
Liveness, nicht ungleiche Auslastung.

Die MOVE-Deadlock-Erkennung wurde nicht erweitert. Sie war nicht die
Ursache, und mit der Prävention entsteht die Tasche gar nicht erst; eine
generische SCC-Erkennung wäre zusätzlicher Mechanismus ohne belegten Nutzen.

## E.4 Regressionstests

Neu: `tests/test_port_exit_admission.py` (12 Tests, alle grün) — Engstelle
wird nicht überfüllt, freier Port schränkt nichts ein, zwei freie Ausfahrten
schränken nichts ein, der Portroboter sperrt sich nicht selbst aus, das
eigene Ziel bleibt planbar, Reservierung ist eindeutig/idempotent/wird
freigegeben, keine stale Sperre nach dem Verlassen, beide Stationen bleiben
nutzbar, keine Umverteilung von Stationen, kein Zufallsverbrauch, und ein
synthetischer Stau mit mehr als zwei Robotern löst sich auf.

Keine bestehende Assertion wurde abgeschwächt; die Klasse-A/B-Regressionen
bleiben unverändert grün.

## E.5 Lange Liveness-Regression

Alle acht Läufe auf der finalen Geometrie, frisch gerechnet:

| Lauf | vorher | nachher | max. Stillstand |
|---|---|---|---|
| **ABC+ABC, Seed 42** | 80 Retrievals, ab t=2973 Stillstand | **180 Retrievals bis t=8888** | 131 ZE |
| **POPULARITY, Seed 1** | 37 Retrievals, ab t=1992 Stillstand | **186 Retrievals bis t=8457** | 13 ZE |
| LR+NR, Seed 42 | gesund | 463 Retrievals bis t=8198 | 44 ZE |
| RR+RR, Seed 1 | gesund | 254 Retrievals bis t=6753 | 7 ZE |
| baseline_reference, Seed 42 | – | 237 Retrievals bis t=6376 | 12 ZE |
| ABC+ABC, Seed 1 | – | 204 Retrievals bis t=6324 | 30 ZE |
| POPULARITY, Seed 42 | – | 201 Retrievals bis t=6266 | 38 ZE |
| LR+NR, Seed 1 | – | 292 Retrievals bis t=5137 | 16 ZE |

Die beiden Problemfälle laufen jetzt drei- bzw. vierfach über ihre alten
Stillstandspunkte hinaus und produzieren durchgehend Retrievals. Kein Lauf
zeigt einen dauerhaften No-Progress-Zustand.

Diagnosezähler über alle acht Läufe:

```text
move_recovery_unresolved   = 0
task_deadlock              = 0
unbury                     = 1     (POPULARITY/Seed 42)
drop_bury_redirect         = 194   (Klasse-A-Prävention greift weiterhin)
stale_pickup_no_task       = 13    (Klasse-B-Schutz greift weiterhin)
```

## E.6 Correctness und CRN

Audit-Harness (Invarianten nach jedem Schritt), finale Konfiguration, je
400 ZE — ABC+ABC/Seed 42, POPULARITY/Seed 1, baseline/Seed 42:

```text
invalid_pickups=0  invalid_drops=0  invalid_moves=0  collisions=0
violations=0
```

Kein Bin-Verlust, keine Duplikate, keine Ownership- oder
Cross-Station-Verletzung, keine unbehandelte Exception in den langen Läufen.

CRN unverändert intakt über 10 Seeds × 5 Policies (Layout, Requests,
Deadlines, Servicezeiten identisch, `eligibility_violations = 0`):

```text
VERDICT: CRN INTAKT
```

## E.7 Pickstation-Lastverteilung

Bei der geforderten Minimalprüfung kam ein Fehler zutage:

> `pickstation_utilisation_mean` war in **jedem** Lauf `None`. Der Export
> prüfte `hasattr(station, "utilization")`, die Methode heißt aber
> `get_utilization`. Die Liste blieb immer leer — eine still ausgefallene
> KPI. Behoben.

Bereits vorhanden und ausreichend: `retrievals.csv` enthält je physischem
Retrieval das Feld `pickstation`. Retrieval-Anteile je Station lassen sich
daraus ohne neue Metrik ableiten.

Ergänzt wurde nur das Minimum in `runs.csv`:

```text
pickstation_utilisation_ps0 / _ps1     Auslastung je Station
retrievals_ps0 / retrievals_ps1        physische Retrievals je Station
```

Ein Mittelwert kann eine Asymmetrie vollständig verdecken (100 %/0 % und
50 %/50 % ergeben beide 50 %) — beobachtet wurde genau das: während PS_0
blockiert war, lief PS_1 leer. Eine `station_load_imbalance` wird
**nicht** gespeichert; sie ist aus den beiden Zahlen ableitbar.

`total_wait_time` je Station wird bewusst **nicht** zusätzlich exportiert:
die Größe wird nur in einem Pfad hochgezählt und ihre Semantik ist nicht
eindeutig genug, um sie als KPI zu führen.

Interpretation bleibt Sekundäranalyse: eine policyinduzierte Asymmetrie darf
als Ergebnis bestehen bleiben. Seed bleibt die Replikationseinheit — Anteile
zuerst je Policy×Seed, dann zwischen Policies vergleichen. Keine
Kausalaussage allein aus einer Korrelation.

## E.8 RQ4: räumliche Konvergenz — Signal definiert, Parameter offen

### Signal (festgelegt)

Neu in den Distribution-Snapshots: `abc_level_<Klasse>_<Tiefe>` — die
gemeinsame Verteilung aller gelagerten Bins über **statische ABC-Klasse** und
**Tiefe unter der Stapeloberkante**, als Anteile, 24 Komponenten bei H = 8,
Summe 1. Flach als Skalare, damit sie durch den bestehenden CSV-Export kommt.

Vorbedingung geprüft: bilden die statischen ABC-Klassen die Zipf-Nachfrage
ab? Gemessen auf der finalen Konfiguration (Seed 42, 1784 Requests):

```text
A (20 % der Bins): 80,8 % der Requests
B (30 % der Bins): 10,7 %
C (50 % der Bins):  8,5 %
```

Das trifft Mellers 80/20-Szenario praktisch exakt. Die Klasse ist statisch
über die `bin_id` definiert, für alle Policies identisch berechenbar und
damit ein tragfähiger Träger für den Vergleich.

Abstandsmaß: **Total Variation Distance**, `TVD(p,q) = ½·Σ|pᵢ−qᵢ|`.

Blockbildung: **nach physischen Retrievals**, nicht nach Zeit. Begründung:
die räumliche Verteilung ändert sich durch Retrievals. LR+NR bewegt rund
55 Bins je 1000 ZE, ABC+ABC rund 22 — bei Zeitblöcken misst die schnelle
Policy zwangsläufig größere Abstände und würde systematisch als „nicht
konvergiert" markiert.

Persistenz ist Teil der Regel: K aufeinanderfolgende Blockpaare unter der
Schwelle **und** danach kein Zurückspringen über ein Vielfaches der
Schwelle. Genau das fehlte der alten β-Regel, die einmal kurz auslöste und
sofort zurücksprang.

### Parameter (noch NICHT festgelegt)

Gemessen über die acht langen Läufe, Blöcke à 50 Retrievals:

| Lauf | TVD-Folge |
|---|---|
| ABC+ABC / 42 | 0,0085 → 0,0052 |
| ABC+ABC / 1 | 0,0086 → 0,0089 → 0,0090 |
| POPULARITY / 1 | 0,0121 → 0,0075 |
| POPULARITY / 42 | 0,0121 → 0,0059 |
| baseline / 42 | 0,0116 → 0,0093 → 0,0114 |
| RR+RR / 1 | 0,0227 → 0,0191 → 0,0115 → 0,0080 |
| LR+NR / 1 | 0,0175 → 0,0115 → 0,0122 → 0,0114 |
| **LR+NR / 42** | 0,0194 → 0,0135 → 0,0160 → 0,0086 → 0,0118 → 0,0107 → 0,0102 → 0,0111 |

Das Signal verhält sich vernünftig: es fällt aus dem Transienten (0,019–0,023)
in einen Plateaubereich. Zwei Dinge verhindern aber eine seriöse
Parameterwahl:

1. **Das Plateau ist policyabhängig.** ABC+ABC und POPULARITY pendeln sich
   bei ≈ 0,005–0,009 ein, LR+NR bei ≈ 0,010–0,011. Das ist plausibel — ohne
   Ordered Return bleibt jede Umlagerung liegen, der eingeschwungene Zustand
   ist also von Natur aus unruhiger. Eine einzelne absolute Schwelle würde
   deshalb LR+NR und RR+RR systematisch benachteiligen.
2. **Der erreichte Horizont ist zu kurz.** Die längste Spur liefert acht
   Blockpaare, die meisten zwei bis vier. Auf zwei bis vier Punkten eine
   Schwelle und eine Persistenzlänge festzulegen wäre genau der Fehler, der
   die β-Regel unbrauchbar gemacht hat.

**Konsequenz:** Schwelle, Blockgröße und Persistenzlänge bleiben offen, und
damit auch `T_measure_start` und `T_final`. Es wird ausdrücklich **keine**
Zahl eingetragen, die auf zwei Blockpaaren beruht.

Nächster Schritt dafür: die acht Läufe auf 25.000–30.000 ZE verlängern
(rechenzeitgebunden, methodisch unproblematisch), dann Plateauhöhe je Policy
bestimmen und entscheiden zwischen
(a) einer gemeinsamen Schwelle oberhalb des höchsten Plateaus, oder
(b) einem relativen Kriterium „kein weiterer Rückgang" (Vergleich des
Mittels der letzten K Paare mit dem der vorangehenden K).
Variante (b) ist policyunabhängig und deshalb der bevorzugte Kandidat.

### Umgang mit `not_converged` (vorab festgelegt)

Erreicht ein finaler Lauf `T_measure_start` ohne Konvergenz, wird er
**nicht** gelöscht und der Seed **nicht** ausgetauscht. Er wird als
`not_converged_before_measurement` markiert, bleibt in allen
Performance-Auswertungen enthalten (das gemeinsame Zeitfenster gilt
unverändert) und wird in der RQ4-Auswertung getrennt ausgewiesen.

## E.9 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-22 (**erledigt**) | Portstau behoben (E.2/E.3). |
| L-23 (unverändert) | Die Pickstation-Zuordnung ist distanzbasiert und policyneutral, aber nicht lastausgleichend. Asymmetrische Stationslast bleibt ein mögliches Ergebnis der Policies und wird über `retrievals_ps0/ps1` und `pickstation_utilisation_ps0/ps1` sichtbar. |
| L-26 (**neu**) | `pickstation_utilisation_mean` war bis 2026-08-22 in jedem Lauf `None` (falscher Methodenname im Export). Ältere Auswertungen dieser Größe sind wertlos. |
| L-27 (**neu**) | Das TVD-Plateau der räumlichen Verteilung ist policyabhängig (ABC/POP ≈ 0,005–0,009; LR+NR ≈ 0,010–0,011). Eine gemeinsame absolute Konvergenzschwelle ist deshalb fragwürdig; ein relatives Kriterium ist vorzuziehen. |
| L-28 (**neu**) | Der in dieser Phase erreichte Pilothorizont (5.100–8.900 ZE, 180–463 Retrievals) reicht nicht aus, um Konvergenzparameter und Zeitfenster zu begründen. |
| L-14 bis L-21, L-24, L-25 | unverändert. |

## E.10 Finale Run-Matrix

```text
5 Konfigurationen × 10 Seeds = 50 Läufe
Konfigurationen: baseline_reference, RR+RR, LR+NR, ABC+ABC, POP+POP
Seeds:           1, 2, 3, 4, 7, 11, 13, 42, 99, 123

Grid 20×30, H=8, 4320 Bins, 2 Pickstations, 8 Roboter
Zipf 1,0, util 0,6, Scheduler EDF, Deadline = arrival + 240
Popularity-Warmup 50 physische Retrievals
Initialverteilung über die 592 zulässigen Storage-Stacks     [EINGEFROREN]
Gemeinsame feste Laufzeit T_final für alle 50 Runs           [METHODIK FIXIERT]
Auswertung nur im gemeinsamen Fenster [T_measure_start, T_final]

T_measure_start, T_final                                     [OFFEN, siehe E.8]
```

Es fehlen genau diese zwei Zeitwerte.

## E.11 Freeze-Gate

| Kriterium | Status |
|---|---|
| Klasse C reproduziert und fachlich erklärt | **erfüllt** (E.1/E.2) |
| ABC+ABC Seed 42 macht langfristig Fortschritt | **erfüllt** — 180 Retrievals bis t=8888 |
| POPULARITY Seed 1 macht langfristig Fortschritt | **erfüllt** — 186 Retrievals bis t=8457 |
| LR+NR Seed 42 und RR+RR Seed 1 bleiben gesund | **erfüllt** |
| Admission/Recovery verändert keine Storage-Policy | **erfüllt** — reine Verkehrsregel, keine Umverteilung von Stationen |
| Beide Pickstations bleiben nutzbar | **erfüllt** — testgesichert |
| Keine stale Portreservierungen | **erfüllt** — testgesichert |
| Volle Testsuite grün | **erfüllt** — 425 passed |
| CRN intakt | **erfüllt** |
| Keine physische Correctness-Verletzung | **erfüllt** |
| Lange Piloten auf allen fünf Policies | **erfüllt** — acht Läufe, alle mit Fortschritt |
| Räumliche A/B/C-Level-Konvergenz sinnvoll definiert | **erfüllt** — Signal, Abstandsmaß, Blockbildung und Persistenzprinzip stehen; Nachfragebezug empirisch geprüft (80,8 %) |
| … und empirisch getestet | **NICHT erfüllt** — Parameter nicht auf zwei bis acht Blockpaaren festlegbar |
| `T_measure_start` begründet | **NICHT erfüllt** |
| `T_final` begründet | **NICHT erfüllt** |
| Alle 50 Runs mit derselben Dauer | **Methodik fixiert**, Werte offen |
| Gemeinsame Performance-/Tardiness-Fenster definiert | **erfüllt durch die Methodik**, sobald die Werte stehen |

### Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender Punkt — genau einer, und er ist kein Fehler mehr:**

> `T_measure_start` und `T_final` sind noch nicht belastbar bestimmt. Die
> räumliche Konvergenzgröße ist definiert und ihr Nachfragebezug empirisch
> bestätigt, aber der in dieser Phase erreichbare Pilothorizont
> (5.100–8.900 ZE, 180–463 Retrievals je Lauf) liefert nur zwei bis acht
> Blockpaare. Das reicht nicht, um Schwelle und Persistenzlänge zu
> begründen — und ohne sie keine Zeitfenster.
>
> Es ist **kein Correctness- oder Liveness-Blocker mehr offen.** Alle drei
> Fehlerklassen sind behoben, alle acht langen Läufe machen durchgehend
> Fortschritt, die Testsuite ist grün und CRN ist intakt.

### Empfohlener nächster Schritt

Die acht Pilotläufe auf 25.000–30.000 ZE verlängern — reine Rechenzeit, ohne
weitere Codeänderung. Danach in einem Zug: Plateauhöhe je Policy bestimmen,
das relative Konvergenzkriterium gegen die absolute Schwelle prüfen,
`T_measure_start` mit begründeter Reserve und `T_final` mit ausreichendem
Fenster für die langsamste Policy festlegen, beides eintragen und einfrieren.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

---
---

# Final Calibration and Horizon Freeze (2026-08-22)

| | |
|---|---|
| Commit zu Beginn | `1c127be` (Branch `working_sim`) |
| Python / pytest | 3.10.12 / 9.1.1 |
| Testsuite vorher | 425 passed |
| Testsuite nachher | **432 passed** (7 neue Tests) |
| Kalibrationsrechenzeit | ≈ 442.000 ZE über 15 Läufe |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## F.1 PortExitGuard — Randfallprüfung: zweimal FAIL, behoben

Vor dem Start der Kalibration wurde der in Abschnitt E beschriebene Schutz
gegen den in der Aufgabenstellung genannten Planungs-/Ausführungs-Randfall
geprüft. **Beide Fragen ergaben zunächst FAIL.**

### Befund 1 — TOCTOU zwischen zwei Planern

```text
Port (0,3) besetzt, Ausfahrten [(1,3), (0,2), (0,4)]
(1,3) bereits belegt -> zwei Ausfahrten frei

robot 2 -> (0,2):  gesperrt=[]        Pfad=JA
robot 3 -> (0,4):  gesperrt=[(0,4)]   Pfad=JA
-> freie Ausfahrten danach: []        PORT EINGESCHLOSSEN
```

Bei zwei freien Ausfahrten sperrt die Regel korrekterweise nichts. Plant
daraufhin ein zweiter Roboter die verbleibende an, ist der Port nach
Ausführung beider Wege zu — jede Einzelprüfung war für sich richtig.

### Befund 2 — die Ausnahme für das eigene Ziel

Die erste Fassung nahm `target` aus der Sperrmenge heraus, damit ein Roboter
mit genau dieser Zielzelle planen kann. Damit durfte ein fremder Roboter die
letzte Ausfahrt belegen, sobald sie sein Ziel war — die Garantie war
wirkungslos.

### Behebung (zwei kleine Änderungen, keine neue Architektur)

1. **Bereits eingeplante Wege zählen wie Belegung.** `get_port_exit_cells_to_keep_free`
   berücksichtigt jetzt zusätzlich die verbleibenden Wegpunkte anderer
   Roboter **und** die `ReservationTable` — dort steht ein Weg schon, bevor
   der Aufrufer ihn dem Roboter zuweist.
2. **Die Zielausnahme entfällt.** Sie wird nicht gebraucht: Zellen der
   Port-Pufferzone sind keine gültigen Storage-Positionen, also nie Ziel
   eines Pickups oder einer Ablage; das Idle-Parking meidet die Zone
   ohnehin. Das einzige legitime Ziel in der Zone ist die Portzelle selbst,
   und die ist keine Ausfahrt. Für den Roboter **auf** dem Port wird
   weiterhin nichts gesperrt. Wird ein Weg deshalb abgelehnt, zählt
   `TrafficManager.port_admission_denials` und es erscheint
   `[PORT_ADMISSION]`.

Nachher:

```text
Szenario 1 (TOCTOU):                  PASS
Szenario 2 (letzte Ausfahrt als Ziel): PASS
```

Zwei neue Regressionstests halten das fest
(`test_last_exit_is_protected_even_when_it_is_the_own_target`,
`test_planned_paths_of_other_robots_count_as_claimed_exits`). Weil damit
Produktionscode geändert wurde, wurden **alle** Kalibrationsläufe anschließend
ab t = 0 neu gerechnet.

Danach: Testsuite grün, CRN intakt, Correctness sauber — ab diesem Punkt
wurde keine Simulationslogik mehr angefasst. Geändert wurde danach nur noch
der Export (Abschnitt F.5), der nicht in den Simulationsablauf eingreift.

---

## F.2 15 symmetrische Kalibrationsläufe

5 Policies × Seeds 1, 7, 42, Zielhorizont 30.000 ZE, alle ab t = 0 auf dem
neuen Codestand.

| Lauf | t_end | Retrievals | konvergiert | `t_conv` (ZE) | Plateauniveau |
|---|---|---|---|---|---|
| baseline_reference / 1 | 30000 | 1091 | ja | 7.600 | 0,0102 |
| baseline_reference / 7 | 30000 | 1281 | ja | 6.601 | 0,0124 |
| baseline_reference / 42 | 30000 | 911 | ja | 6.600 | 0,0108 |
| RR+RR / 1 | 30000 | 1027 | ja | 10.700 | 0,0089 |
| RR+RR / 7 | 30000 | 1221 | ja | 15.100 | 0,0077 |
| RR+RR / 42 | 30000 | 741 | ja | 13.600 | 0,0096 |
| LR+NR / 1 | 30000 | 842 | ja | 14.800 | 0,0081 |
| LR+NR / 7 | 30000 | 1778 | ja | 10.800 | 0,0070 |
| LR+NR / 42 | 30000 | 1301 | ja | 6.300 | 0,0102 |
| ABC+ABC / 1 | 30000 | 640 | ja | 16.302 | 0,0079 |
| ABC+ABC / 42 | 30000 | 470 | ja | 16.000 | 0,0114 |
| **ABC+ABC / 7** | **21869** | 405 | – | – | – |
| POPULARITY / 1 | 30000 | 796 | ja | 11.700 | 0,0078 |
| POPULARITY / 7 | 30000 | 740 | ja | **20.300** | 0,0074 |
| POPULARITY / 42 | 30000 | 568 | ja | 18.500 | 0,0062 |

**14 von 15 konvergieren.** Der fünfzehnte Lauf ist kein
Konvergenzproblem, sondern ein Abbruch — siehe F.6.

Diagnosezähler über alle 15 Läufe: `move_recovery_unresolved = 0`,
`task_deadlock = 0`. Die Prävention der Klassen A und B greift weiterhin
regelmäßig (`drop_bury_redirect`, `stale_pickup_no_task` > 0).

---

## F.3 Finale RQ4-Konvergenzregel

### Signal (unverändert)

`abc_level_<Klasse>_<Tiefe>` — gemeinsame Verteilung über die statische
ABC-Klasse und die Tiefe unter der Stapeloberkante, 24 Komponenten, Summe 1.
Nachfragebezug bestätigt: A = 20 % der Bins, **80,8 %** der Requests.
Abstandsmaß: Total Variation Distance. Blockbildung nach **physischen
Retrievals**.

### Kriterium: relativ (Variante B)

Die Kalibration bestätigt, warum eine absolute Schwelle ungeeignet ist. Die
Plateauniveaus liegen zwischen **0,0062 und 0,0124** — der höchste ist doppelt
so hoch wie der niedrigste, und die Reihenfolge ist policygeprägt
(baseline ≈ 0,011, POPULARITY ≈ 0,007). Eine gemeinsame absolute Schwelle
oberhalb von 0,0124 würde bei den ruhigeren Policies viel zu früh auslösen;
eine bei 0,008 würde `baseline_reference` nie konvergieren lassen.

Steady State heißt eben **nicht** `TVD → 0`: das Lager bleibt im
eingeschwungenen Zustand dynamisch, und wie stark, hängt an der Policy.

```text
Block             R = 50 physische Retrievals
d_i               TVD zwischen Block i-1 und Block i
Vergleichsfenster K = 2 aufeinanderfolgende d_i
Plateau ab i      mean(d[i-1..i]) >= (1 - delta) * mean(d[i-3..i-2])
                  mit delta = 0,10
Persistenz        P = 2 aufeinanderfolgende i erfuellen die Bedingung
```

In Worten: **die TVD fällt nicht mehr systematisch**, und das gilt zweimal
hintereinander. Vier Parameter, keine Grid-Search.

Begründung der Werte aus den Spuren:

* **R = 50** — dieselbe Blockgröße wie in der alten β-Regel, damit die Zahlen
  vergleichbar bleiben. Sie liefert bei der langsamsten Policy noch 8–11
  Distanzen über 30.000 ZE und bei der schnellsten 34.
* **K = 2** — kleinstes Fenster, das ein Mittel bildet statt einen Einzelwert
  zu vergleichen. Größere K kosten bei den langsamen Policies zu viele
  Distanzen.
* **delta = 0,10** — ein Rückgang unter 10 % zwischen benachbarten Fenstern
  ist bei einer Streuung, die zwischen 0,006 und 0,024 schwankt, kein Signal
  mehr.
* **P = 2** — Persistenz. Genau das fehlte der β-Regel, die einmal kurz
  auslöste und sofort zurücksprang. Zusätzlich wird geprüft, ob nach dem
  Plateau eine starke Re-Divergenz folgt; in keinem der 14 konvergierten
  Läufe war das der Fall.

Die Regel arbeitet **offline** auf der vollständigen Zeitreihe ab t = 0 und
beeinflusst den Lauf nicht.

---

## F.4 Zeithorizont

### `T_measure_start`

```text
langsamste beobachtete Konvergenz          20.300 ZE  (POPULARITY, Seed 7)
groesste Streuung innerhalb einer Policy    8.600 ZE  (POPULARITY: 11.700 ... 20.300)
Summe                                      28.900 ZE
aufgerundet                       ->       30.000 ZE
```

**`T_measure_start` = 30.000 ZE.**

Die Reserve ist nicht frei gewählt, sondern die größte innerhalb einer Policy
beobachtete Spanne zwischen Seeds: ein noch ungetesteter Seed darf noch
einmal so viel langsamer sein wie der größte gemessene Abstand. Das ist
nötig, weil die finale Kampagne zehn Seeds nutzt, von denen sieben nicht
kalibriert wurden. Aufgerundet auf einen glatten Wert.

### Measurement Window und `T_final`

Langsamste Retrievalrate **nach** der Konvergenz: **0,01451 Retrievals/ZE**
(RR+RR, Seed 42).

| Fensterlänge | Retrievals beim langsamsten Lauf |
|---|---|
| 5.000 ZE | 73 |
| 8.000 ZE | 116 |
| 10.000 ZE | 145 |
| **12.000 ZE** | **174** |
| 15.000 ZE | 218 |

**Fenster = 12.000 ZE, `T_final` = 42.000 ZE.**

12.000 ZE liegen im gewünschten Bereich von 150–200 Retrievals für den
langsamsten Lauf und kosten gegenüber 10.000 ZE nur 5 % mehr Rechenzeit.
15.000 ZE brächten keinen erkennbaren Zusatznutzen für Run-Level-KPIs.

Erwartete Retrievals im gemeinsamen Fenster (Post-Convergence-Rate × 12.000):

| Policy | Rate (retr/ZE) | erwartete Retrievals |
|---|---|---|
| baseline_reference | 0,028–0,044 | 340–530 |
| RR+RR | 0,015–0,042 | 174–498 |
| LR+NR | 0,023–0,059 | 270–702 |
| ABC+ABC | 0,016–0,017 | 187–209 |
| POPULARITY | 0,015–0,027 | 175–324 |

Auch die langsamste Kombination bleibt deutlich über 100.

---

## F.5 Pickstation-Auswertung: Fenstersemantik geklärt

Geprüft, wie gefordert:

| Größe | Bezug | Status |
|---|---|---|
| `pickstation` je Retrieval (`retrievals.csv`) | Einzelereignis | vorhanden, zeitlich filterbar |
| `retrievals_ps0` / `retrievals_ps1` | **Measurement Window** | korrekt |
| `pickstation_utilisation_ps0` / `_ps1` | **ganzer Lauf** | **nur diagnostisch** |
| `total_wait_time` je Station | uneindeutig | **nicht exportiert** |

`Pickstation.get_utilization` teilt die kumulierte Servicezeit durch die
Laufzeit. Eine fensterbezogene Auslastung gäbe es nur mit zusätzlicher
Telemetrie — das wäre neue Infrastruktur und ist ausdrücklich nicht gewollt.
Die Größe bleibt deshalb im Export, wird aber als Full-Run-Diagnose
gekennzeichnet. Für die Lastverteilung **im Messfenster** sind
`retrievals_ps0/ps1` zuständig; Anteile und eine etwaige Imbalance sind daraus
ableitbar.

### Notwendige Exportanpassung

Damit alle KPIs auf demselben Intervall beruhen, wertet `summarise_run` jetzt
`[t_measure_start, t_final]` aus, sobald die Config beides gesetzt hat:

* `bin_throughput` = Retrievals im Fenster / Fensterlänge,
* `requests_completed`, `request_throughput`, `deadline_miss_rate`,
  `mean_tardiness`, `mean_flow_time` über die **im Fenster abgeschlossenen**
  Requests,
* `retrievals_ps0/ps1` über die Retrievals im Fenster,
* neue Spalten `measurement_mode`, `t_measure_start`, `t_final` machen den
  Bezug in `runs.csv` explizit.

Ohne gesetztes Fenster bleibt das bisherige Verhalten erhalten (Tests,
Diagnoseläufe). Sieben Tests in `tests/test_measurement_window_export.py`
sichern das ab.

Ohne diese Anpassung wäre die Tardiness über den ganzen Lauf gemittelt
worden, während der Durchsatz nur das Fenster misst — der gepaarte
Policy-Vergleich wäre nicht sauber gewesen.

---

## F.6 Verbleibender Blocker: Abbruch bei langem Horizont

`ABC+ABC / Seed 7` bricht bei t = 21.869 ab:

```text
RuntimeError: Cannot complete request 394: target was not removed
```

Der Lauf war bis dahin gesund — das letzte Retrieval liegt bei t = 21.863,
sechs Zeiteinheiten vor dem Abbruch. Es ist **kein** Stillstand, sondern ein
inkonsistenter Taskzustand.

Zustand beim Abbruch:

```text
robot 7  pos=(17,13)  carry=None  phase=complete  request=394  target_bin=0
         target_removed=False  target_at_pickstation=False
         pickstation_completed=False  target_returned=True
```

Der Task ist in `PHASE_COMPLETE` und meldet die Target-Bin als
zurückgelegt, obwohl er sie nie ausgelagert hat. Request 394 ist bei
`arrival_time=696` eingegangen, also rund 21.000 ZE alt — der Task wurde über
den Lauf hinweg mehrfach requeued.

`RobotTask.mark_target_returned()` setzt `target_returned` und
`PHASE_COMPLETE` **ohne** zu prüfen, ob der Task die Bin überhaupt entnommen
hatte. Die Abschlussprüfung `can_complete_consistently` schlägt dann zu Recht
an. Der genaue Weg, auf dem der Task in diesen Zustand gerät, ist **nicht**
abschließend geklärt; naheliegend, aber unbelegt, ist ein Zusammenspiel aus
Requeue und der Bedienung derselben Bin durch einen anderen Vorgang.

Bewertung:

* Ein einzelner von 15 Kalibrationsläufen ist betroffen (6,7 %).
* Der Abbruch liegt bei t ≈ 21.900 und damit **vor** `T_measure_start`
  = 30.000. Ein solcher Lauf lieferte in der finalen Kampagne gar keine
  Messdaten.
* Er ist damit ein echter Blocker für die Kampagne, aber **kein** Rückfall in
  die Klassen A, B oder C: kein Stillstand, keine Invariantenverletzung, der
  Fortschritt lief bis zur letzten Zeiteinheit.

Er wurde **nicht** behoben. Eine Änderung an `mark_target_returned` oder am
Requeue-Pfad ohne belegte Ursache wäre genau der Schnellschuss, den die
Projektregeln ausschließen — zumal die Simulationslogik für die Kalibration
eingefroren war.

---

## F.7 Correctness und CRN

Audit-Harness (Invarianten nach jedem Schritt), finale Konfiguration, je
400 ZE — ABC+ABC/42, POPULARITY/1, LR+NR/7:

```text
invalid_pickups=0  invalid_drops=0  invalid_moves=0  collisions=0
violations=0
```

CRN unverändert intakt über 10 Seeds × 5 Policies. Testsuite **432 passed**.

---

## F.8 Finale 50-Run-Matrix

```text
5 Konfigurationen × 10 Seeds = 50 Läufe
Konfigurationen: baseline_reference, RR+RR, LR+NR, ABC+ABC, POP+POP
Seeds:           1, 2, 3, 4, 7, 11, 13, 42, 99, 123

Grid 20×30, H=8, 4320 Bins, 2 Pickstations, 8 Roboter
Zipf 1,0, util 0,6, Scheduler EDF, Deadline = arrival + 240
Popularity-Warmup 50 physische Retrievals
Initialverteilung über die 592 zulässigen Storage-Stacks

T_measure_start   = 30.000 ZE
Measurement Window= 12.000 ZE
T_final           = 42.000 ZE            alle 50 Runs laufen 0 ... 42.000

Auswertung ausschliesslich [30.000, 42.000] — identisch fuer alle Policies
und Seeds. RQ4 offline aus der vollstaendigen Zeitreihe ab t=0.
```

Umgang mit Läufen, die bis `T_measure_start` nicht konvergieren: Seed **nicht**
austauschen, Lauf **nicht** löschen, als `not_converged_before_measurement`
markieren, in allen Performance-Auswertungen belassen, in RQ4 getrennt
ausweisen.

---

## F.9 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-27 (**bestätigt**) | Das TVD-Plateau ist policyabhängig (0,0062–0,0124). Deshalb relatives statt absolutes Kriterium. |
| L-28 (**erledigt**) | Der Pilothorizont reicht jetzt (30.000 ZE, 405–1778 Retrievals je Lauf). |
| L-29 (**neu**) | `ABC+ABC / Seed 7` bricht bei t ≈ 21.869 mit `Cannot complete request 394: target was not removed` ab. Ursache nicht abschließend geklärt (F.6). |
| L-30 (**neu**) | `pickstation_utilisation_ps0/ps1` ist kumulativ über den ganzen Lauf und damit **nicht** fensterbezogen. Nur diagnostisch verwenden; Lastverteilung im Fenster über `retrievals_ps0/ps1`. |
| L-31 (**neu**) | `T_measure_start` beruht auf drei kalibrierten Seeds je Policy; sieben der zehn finalen Seeds sind ungetestet. Die Reserve deckt die größte beobachtete Streuung ab, garantiert aber keine Konvergenz für jeden Seed. |
| L-14 bis L-26 | unverändert. |

---

## F.10 Freeze-Gate

| Kriterium | Status |
|---|---|
| PortExitGuard behandelt den Planungs-/Ausführungs-Randfall | **erfüllt** — zwei Befunde behoben, Regressionstests |
| Vollständige Testsuite grün | **erfüllt** — 432 passed |
| CRN intakt | **erfüllt** |
| Keine bekannte Correctness-/Liveness-Verletzung | **NICHT erfüllt** — Abbruch in ABC+ABC/Seed 7 (F.6) |
| Alle fünf Policies machen über den langen Horizont Fortschritt | **erfüllt** — 14 Läufe bis 30.000 ZE, der 15. bis 21.869 ohne Stillstand |
| 15 symmetrische Pilotspuren | **erfüllt** |
| RQ4-Regel einfach, policyneutral, persistent | **erfüllt** |
| Konvergenzzeiten empirisch bestimmt | **erfüllt** — 14 von 15, 6.300–20.300 ZE |
| `T_measure_start` begründet | **erfüllt** — 30.000 ZE |
| `T_final` begründet | **erfüllt** — 42.000 ZE |
| Alle finalen Runs mit derselben Dauer und demselben Fenster | **erfüllt** — im Export durchgesetzt und testgesichert |
| Pickstation-Auswertung zeitlich korrekt definiert | **erfüllt** — Fenstergrößen korrekt, Utilisation als Diagnose gekennzeichnet |
| Dokumentation konsistent | **erfüllt** |

### Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender Punkt — genau einer:**

> `ABC+ABC / Seed 7` bricht bei t ≈ 21.869 mit `RuntimeError: Cannot complete
> request 394: target was not removed` ab. Der Task steht in
> `PHASE_COMPLETE` und meldet die Target-Bin als zurückgelegt, obwohl
> `target_removed` nie gesetzt wurde. Der Lauf war bis sechs Zeiteinheiten
> vor dem Abbruch produktiv.
>
> Der Abbruch liegt vor `T_measure_start` = 30.000 ZE; ein solcher Lauf
> lieferte in der finalen Kampagne keine Messdaten. Bei 15 Kalibrationsläufen
> ist ein Fall aufgetreten, also rund 7 % — bei 50 finalen Läufen wären drei
> bis vier Ausfälle zu erwarten.
>
> Alles andere ist fertig: Zeithorizont, Konvergenzregel, Fenstersemantik,
> Run-Matrix und Testabdeckung stehen. Es fehlt ausschließlich die Klärung
> dieses einen Abbruchpfads.

### Empfohlener nächster Schritt

Den Abbruch als eigene, kurze Phase behandeln — mit demselben Vorgehen wie
bei den Klassen A bis C: erst reproduzieren, dann klassifizieren, dann die
kleinste Änderung. Der Zustand liegt als Pickle vor, der Lauf ist
deterministisch reproduzierbar (`ABC+ABC`, Seed 7, Abbruch bei t = 21.869).
Zu klären ist, auf welchem Weg ein Task `mark_target_returned()` erreicht,
ohne je `mark_waiting_at_pickstation()` durchlaufen zu haben — die
Requeue-Pfade und die Batching-Zuordnung derselben Bin sind die
naheliegenden Kandidaten.

Danach genügt eine Wiederholung der 15 Kalibrationsläufe zur Bestätigung;
Regel und Zeithorizont müssen dafür nicht neu bestimmt werden, solange sich
die Konvergenzzeiten nicht wesentlich verschieben.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

---
---

# Final Lifecycle Remediation (2026-08-22)

| | |
|---|---|
| Commit | `1c127be` (Branch `working_sim`) |
| Python / pytest | 3.10.12 / 9.1.1 |
| Testsuite vorher | 432 passed |
| Testsuite nachher | **443 passed** (11 neue Tests) |
| Kalibration | 15 Läufe frisch ab t=0, ≈ 462.000 ZE |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## G.1 Root Cause des Abbruchs — bewiesen

Der Abbruch war **nicht** am Symptom zu erkennen. Der Zustand beim Fehler
zeigte einen Task in `PHASE_COMPLETE` mit `target_returned=True`, aber
`target_removed=False`, `target_at_pickstation=False`,
`pickstation_completed=False`.

Erste Vermutung (zwei Task-Objekte für denselben Request) ließ sich am
Pickle **widerlegen**: es existiert genau ein Task-Objekt für Request 394.
Bin 0 lag physisch korrekt auf `S_17_13` — dem im Task vermerkten
`actual_return_stack_id`. Die Rücklagerung hatte also stattgefunden, nur die
Buchhaltung saß am falschen Objekt.

### Der Mechanismus

`_handle_robot_drop` erkennt eine fremde Target-Rücklagerung an der **Bin**:

```python
foreign_target = (
    action_type == "return"
    and action.get("return_kind") == "target"
    and robot.current_task is not None
    and robot.current_task.target_bin_id != bin_id      # <- Bin, nicht Request
)
```

Zielen zwei Requests auf **dieselbe** Bin, stimmt `target_bin_id` überein,
obwohl die Aktion zu einem anderen Task gehört — der Guard greift nicht.
`_update_task_after_successful_return` ruft dann `mark_target_returned()` auf
dem falschen Task auf.

Das ist kein exotischer Randfall: Bin 0 ist A-Klasse, und in der
Batch-Warteliste standen zum Abbruchzeitpunkt **22 weitere Requests auf genau
diese Bin**. Der Pickup-Pfad prüft an derselben Stelle über die `request_id`
und war deshalb nie betroffen.

### Deterministischer Beweis

`experiments/closeout/probe_foreign_target_return.py` stellt genau die
Konstellation her: ein Roboter führt einen Target-Return für Bin B aus,
während ihm inzwischen ein Task eines **zweiten** Requests auf dieselbe Bin B
zugeteilt wurde.

```text
vor dem Drop:  task_b removed=False at_ps=False ps_done=False returned=False
nach dem Drop: task_b removed=False at_ps=False ps_done=False returned=True  phase=complete
  can_complete_consistently -> False, target was not removed
```

Damit ist der Entstehungsweg reproduziert — mit exakt dem Symptom des langen
Laufs.

### Antworten auf die Kernfragen

| Frage | Antwort |
|---|---|
| Wie erreicht der Task `mark_target_returned()` ohne `target_removed`? | Über einen Drop, der zu einem **anderen Request auf dieselbe Bin** gehört. Die Task-Phase spielt keine Rolle — die Buchhaltung hängt am Aktionstyp, nicht an der Phase. |
| Wurde die Bin durch einen anderen Vorgang bedient? | Ja. Der Retrieval und der Pickstation-Service liefen unter einem anderen Request. |
| Mehrere Tasks/Requests für dieselbe Bin? | Requests ja (22 in der Warteliste), Task-Objekte nein — genau ein Task je Zeitpunkt. |
| Verliert ein requeued Task den Bezug? | Nein. Der requeued Task ist nicht die Ursache. |
| Wird ein alter Task fälschlich fortgesetzt? | Nein — ein altes **Event** wird fälschlich dem neuen Task zugeschrieben. |
| Stale Return-/Completion-Event? | Ja, genau das: ein Drop-Event, dessen Task inzwischen gewechselt hat. |
| Ist Batching beteiligt? | Nur als Verstärker: Batching sammelt viele Requests auf dieselbe heiße Bin und macht die Kollision wahrscheinlich. |
| Ownership? | Nicht beteiligt; Blocker-Ownership war zum Zeitpunkt des Fehlers leer. |
| Ist `target_returned=True` falsch? | Ja — für DIESEN Task. Physisch war die Bin korrekt zurückgelegt. |

---

## G.2 Minimalfix

Drei kleine Änderungen, keine Policy-Semantik berührt:

| # | Ort | Änderung |
|---|---|---|
| 1 | `EventHandler._update_task_after_successful_return` | Die Buchhaltung eines Target-Returns wird nur ausgeführt, wenn der **Request** der Aktion zum aktuellen Task gehört. Sonst `[STALE][RETURN_TASK]` und überspringen. Dasselbe Kriterium, das der Pickup-Pfad schon benutzt. |
| 2 | `TopAccessStrategy._next_retrieve_target_action` | Findet ein Task seine Bin bereits an der Pickstation vor, wird `mark_target_at_pickstation()` aufgerufen statt nur `target_at_pickstation` zu setzen. Beide Flags gehören zusammen: eine Bin an der Pickstation ist nachweislich aus dem Lager entnommen. Vorher wäre auch dieser Zweig später an der Abschlussinvariante gescheitert. |
| 3 | `RobotTask.mark_target_returned` | Fail-Fast: `target_removed` muss gesetzt sein. Ein künftiger falscher Lebenszyklus fällt damit an der **ersten** ungültigen Transition auf, nicht erst rund 21.000 ZE später beim Abschluss. |

**Die physische Ablage bleibt unverändert.** Übersprungen wird ausschließlich
die Task-Buchhaltung — die Bin landet weiterhin im Zielstack und hängt nicht
im Transit. Der ursprüngliche Task findet sie über den vorhandenen Pfad
`[REPLAN][PICKUP_RETURN] ... already stored` wieder.

Nicht geändert: Ordered Return, No-Return-Semantik, Target Placement, EDF,
Deadline, Pickstation-Zuordnung, PortExitGuard, CRN, Servicezeiten,
RNG-Ströme.

---

## G.3 Regressionstests

Neu: `tests/test_task_lifecycle_consistency.py` (11 Tests).

| Anforderung | Test |
|---|---|
| `target_returned` nicht vor `target_removed` | `test_target_cannot_be_marked_returned_before_it_was_removed` |
| Regulärer Lebenszyklus bleibt möglich | `test_regular_lifecycle_still_completes` |
| Bin an der Pickstation ⇒ beide Flags | `test_bin_already_at_pickstation_sets_both_flags` |
| Fremder Return fasst den aktuellen Task nicht an | `test_foreign_target_return_does_not_touch_the_current_task` |
| Bin wird trotzdem physisch abgelegt | `test_foreign_target_return_still_stores_the_bin_physically` |
| Eigener Return wird weiterhin verbucht | `test_own_target_return_is_still_booked` |
| Kein Bin-Verlust, keine Duplikate, kein Abbruch (4 Policies) | `test_run_completes_requests_only_with_a_valid_lifecycle` |
| Mehrere Requests auf dieselbe Bin bleiben konsistent | `test_multiple_requests_for_the_same_bin_stay_consistent` |

Keine bestehende Assertion abgeschwächt. Die Regressionen der Klassen A, B
und C sowie die PortExitGuard-/TOCTOU-Tests bleiben unverändert grün.

---

## G.4 RQ4: `redivergence`-Semantik geklärt

Der gemeldete Widerspruch war real und hatte **zwei** Ursachen.

**Erstens: der Freeze-Bericht war stale.** `LR+NR / Seed 7` trug
`converged=true` **und** `redivergence=true`; die Aussage „bei keinem der 14
konvergierten Läufe starke Re-Divergenz" war schlicht falsch.

**Zweitens: der Analyzer erlaubte den Widerspruch.** `converged` hing allein
am gefundenen Plateau; die Re-Divergenz wurde berechnet, aber nie
ausgewertet. Behoben durch drei eindeutige Zustände:

```text
converged                  Plateau gefunden und gehalten
converged_then_rediverged  Plateau gefunden, danach steigt die TVD wieder
not_converged              kein Plateau gefunden
```

Nur `converged` zählt als konvergiert. Die beiden anderen werden getrennt
ausgewiesen.

**Dazu ein echter Implementierungsfehler der Regel.** Die Re-Divergenz
verglich **einzelne** Blockabstände gegen das Plateau-**Mittel** — dimensional
inkonsistent. Über die 15 Spuren erreichen auch klar stabile Läufe
Einzelwerte von 1,25 bis 1,42 mal dem Plateauniveau; die Schwelle 1,5 lag
also mitten im normalen Rauschband. Verglichen wird jetzt das gleitende
Mittel über K Distanzen gegen das Plateaumittel. **Der Faktor 1,5 blieb
unverändert** — korrigiert ist nur, *was* verglichen wird.

Ergebnis: 13 × `converged`, 1 × `converged_then_rediverged` (LR+NR / Seed 7,
mit 34 Distanzen die längste Spur — der Befund ist kein Rauschen), 1 ×
`not_converged` (ABC+ABC / Seed 7).

Für die finale Kampagne gilt dieselbe vorab festgelegte Regel wie für
`not_converged`: Seed nicht austauschen, Lauf nicht löschen, in allen
Performance-Auswertungen belassen, in RQ4 getrennt ausweisen.

---

## G.5 15 Kalibrationsläufe frisch auf dem finalen Code

Alle 15 ab t=0 neu gerechnet. **Keine Exception in keinem Lauf.**

| Lauf | t_end | Retrievals | Status | `t_conv` | Plateau |
|---|---|---|---|---|---|
| baseline_reference / 1 | 30000 | 1091 | converged | 7.600 | 0,0102 |
| baseline_reference / 7 | 30000 | 1281 | converged | 6.601 | 0,0124 |
| baseline_reference / 42 | 30000 | 911 | converged | 6.600 | 0,0108 |
| RR+RR / 1 | 30000 | 1027 | converged | 10.700 | 0,0089 |
| RR+RR / 7 | 30000 | 1221 | converged | 15.100 | 0,0077 |
| RR+RR / 42 | 30000 | 741 | converged | 13.600 | 0,0096 |
| LR+NR / 1 | 30000 | 842 | converged | 14.800 | 0,0081 |
| LR+NR / 7 | 30000 | 1778 | **converged_then_rediverged** | – | 0,0070 |
| LR+NR / 42 | 30000 | 1301 | converged | 6.300 | 0,0102 |
| ABC+ABC / 1 | 30000 | 640 | converged | 16.302 | 0,0079 |
| ABC+ABC / 42 | 30000 | 470 | converged | 16.000 | 0,0114 |
| **ABC+ABC / 7** | **42000** | 567 | **not_converged** | – | – |
| POPULARITY / 1 | 30000 | 796 | converged | 11.700 | 0,0078 |
| POPULARITY / 7 | 30000 | 740 | converged | 20.300 | 0,0074 |
| POPULARITY / 42 | 30000 | 568 | converged | 18.500 | 0,0062 |

Bemerkenswert: die 14 Läufe bis 30.000 ZE liefern **exakt dieselben
Retrievalzahlen** wie vor dem Fix. Der Fix greift also ausschließlich in den
pathologischen Pfad ein und verändert keine gesunde Trajektorie — die
RQ4-Kalibration und die Zeitwerte tragen unverändert.

`move_recovery_unresolved = 0` und `task_deadlock = 0` in allen 15 Läufen.

---

## G.6 ABC+ABC / Seed 7 bis 42.000 ZE — Abbruch weg, aber neuer Befund

Der Lauf erreicht **t = 42.000 ohne Exception**. Der Abbruch
`Cannot complete request 394: target was not removed` tritt nicht mehr auf;
der frühere Abbruchzeitpunkt t = 21.869 wird ohne Auffälligkeit passiert.

**Aber:** der Durchsatz zerfällt über den Horizont.

```text
Retrievals je 5.000 ZE:  151  97  102  46  79  53  19  14  6
groesste Luecke zwischen zwei Retrievals: 3.323 ZE
Retrievals im gemeinsamen Messfenster [30.000, 42.000]:  39
```

Zum Vergleich die anderen ABC-Läufe, die flach bleiben:

```text
ABC+ABC / 1 :  157 124 100 100  72  87
ABC+ABC / 42:  104  66  55  91  82  72
```

Der Lauf ist damit weder abgebrochen noch dauerhaft stehengeblieben — aber er
degeneriert. Zwei Folgen:

1. Er konvergiert bis 42.000 ZE nicht (10 Distanzen, kein Plateau).
2. Er liefert im gemeinsamen Messfenster nur **39** physische Retrievals
   statt der ausgelegten ~174.

Die Diagnosezähler weisen ihn als Ausreißer aus (auf Laufzeit normiert
allerdings unauffällig bei den Deadlock-Detektionen):

```text
                        retr  dl_det  stale  bury  maxLuecke
ABC+ABC / 7              567     588     38    80       3323
ABC+ABC / 42             470     194     17    88       1412
baseline_reference / 42  911     410     21    37        388
```

Auffällig ist die **Lückenlänge**, nicht die Zahl der Konflikte. Die Ursache
ist **nicht** geklärt. Sie wurde in dieser Phase bewusst nicht angefasst: der
Befund ist neu, die Simulationslogik war für die Kalibration eingefroren, und
eine Änderung ohne belegte Ursache wäre genau der Schnellschuss, den die
Projektregeln ausschließen.

---

## G.7 Zeithorizont bestätigt

Auf den 13 konvergierten Läufen unverändert:

```text
langsamste beobachtete Konvergenz          20.300 ZE  (POPULARITY, Seed 7)
groesste Streuung innerhalb einer Policy    8.600 ZE  (POPULARITY: 11.700 ... 20.300)
Summe                                      28.900 ZE
aufgerundet                       ->       T_measure_start = 30.000 ZE

langsamste Post-Convergence-Rate           0,01451 retr/ZE  (RR+RR, Seed 42)
Fenster 12.000 ZE                 ->       174 Retrievals
                                  ->       T_final = 42.000 ZE
```

Alle Konvergenzzeitpunkte liegen weiterhin deutlich vor 30.000 ZE; der
langsamste (20.300) behält 9.700 ZE Reserve. Es entsteht **keine** neue
langsamste Kombination unter den konvergierten Läufen.

Erwartete Retrievals im Fenster je Policy (Post-Convergence-Rate × 12.000):

| Policy | Rate (retr/ZE) | erwartete Retrievals |
|---|---|---|
| baseline_reference | 0,0283–0,0439 | 339–527 |
| RR+RR | 0,0145–0,0415 | 174–498 |
| LR+NR | 0,0225–0,0401 | 270–482 |
| ABC+ABC | 0,0156–0,0175 | 187–209 |
| POPULARITY | 0,0146–0,0270 | 175–324 |

**Ausnahme ABC+ABC / Seed 7: 39 gemessene Retrievals im Fenster.** Diese
Kombination unterläuft die Auslegung um den Faktor 4 und ist der Grund, warum
der Horizont zwar rechnerisch bestätigt, aber nicht abgesichert ist.

---

## G.8 Measurement- und Pickstation-Semantik (unverändert)

```text
Warm-up:      0 ... 30.000
Messfenster:  30.000 ... 42.000     fuer ALLE Policies und Seeds identisch
```

Im Fenster: `bin_throughput`, `request_throughput`, `deadline_miss_rate`,
`mean_tardiness`, `mean_flow_time`, `mean_blocking_bins`, `mean_dig_duration`,
`retrievals_ps0`, `retrievals_ps1`.

`pickstation_utilisation_ps0/ps1` bleibt **Full-Run-Diagnose**, weil
`get_utilization()` kumulativ arbeitet. Stationsasymmetrie im Messfenster
ausschließlich über `retrievals_ps0/ps1` bzw. die gefilterten Rohdaten.

---

## G.9 Correctness und CRN

Audit-Harness (Invarianten nach jedem Schritt), je 400 ZE — ABC+ABC/7,
POPULARITY/42, LR+NR/1:

```text
invalid_pickups=0  invalid_drops=0  invalid_moves=0  collisions=0
violations=0
```

Über alle 15 Kalibrationsläufe: kein Bin-Verlust, keine Duplikate, keine
Ownership- oder Cross-Station-Verletzung, **keine Exception**,
`move_recovery_unresolved = 0`, `task_deadlock = 0`.

CRN unverändert intakt über 10 Seeds × 5 Policies. Testsuite **443 passed**.

---

## G.10 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-29 (**erledigt**) | Der Abbruch `Cannot complete request 394: target was not removed` ist behoben (G.1/G.2). |
| L-32 (**neu**) | `ABC+ABC / Seed 7` verliert über den Horizont fortschreitend Durchsatz (151 → 6 Retrievals je 5.000 ZE, größte Lücke 3.323 ZE) und liefert im Messfenster nur 39 statt ~174 Retrievals. Ursache ungeklärt. |
| L-33 (**neu**) | `LR+NR / Seed 7` erreicht ein Plateau und divergiert danach wieder (`converged_then_rediverged`). Für RQ4 zählt der Lauf nicht als konvergiert. |
| L-34 (**neu**) | Die Re-Divergenz-Prüfung verglich bis 2026-08-22 Einzelwerte gegen ein Mittel. Ältere `redivergence`-Angaben sind nicht belastbar. |
| L-27, L-30, L-31 | unverändert. |

---

## G.11 Freeze-Gate

| Kriterium | Status |
|---|---|
| Root Cause des Request-394-Abbruchs nachgewiesen | **erfüllt** (G.1) |
| Fix behandelt Root Cause, nicht Symptom | **erfüllt** — Request-basierte Zuordnung statt Bin |
| ABC+ABC / Seed 7 läuft frisch bis 42.000 ZE | **erfüllt** — kein Abbruch |
| Messfenster [30.000, 42.000] vollständig erreicht | **NICHT erfüllt** — nur 39 statt ~174 Retrievals (G.6) |
| 15/15 Kalibrationsläufe ohne Exception | **erfüllt** |
| Keine bekannte Correctness-/Liveness-Verletzung | **NICHT erfüllt** — fortschreitender Durchsatzverlust in ABC+ABC/7 |
| A/B/C-Regressionsfälle bleiben behoben | **erfüllt** |
| PortExitGuard bleibt korrekt | **erfüllt** |
| Vollständige Testsuite grün | **erfüllt** — 443 passed |
| CRN intakt | **erfüllt** |
| RQ4 `converged/redivergence` intern konsistent | **erfüllt** (G.4) |
| RQ4-Regel nachvollziehbar und policyneutral | **erfüllt** |
| `T_measure_start` auf finalem Code begründet | **erfüllt** — 30.000 ZE, 9.700 ZE Reserve |
| `T_final` auf finalem Code begründet | **erfüllt für 13 Läufe**, widerlegt durch ABC+ABC/7 |
| Alle 50 Runs mit derselben Laufzeit und demselben Fenster | **erfüllt** |
| Export-/Tardiness-/Pickstation-Window-Semantik | **erfüllt** |

### Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender Blocker — genau einer:**

> **`ABC+ABC / Seed 7` verliert über den Horizont fortschreitend Durchsatz.**
> Von 151 Retrievals je 5.000 ZE zu Beginn bleiben am Ende 6; die größte
> Lücke zwischen zwei Retrievals beträgt 3.323 ZE. Im gemeinsamen
> Messfenster [30.000, 42.000] entstehen nur **39** physische Retrievals
> statt der ausgelegten ~174.
>
> Der Lauf bricht nicht ab und steht nicht dauerhaft still — die drei
> bekannten Fehlerklassen und der Lifecycle-Fehler sind behoben. Aber ein
> Run, der auf ein Zwanzigstel seines Anfangsdurchsatzes zerfällt, ist weder
> als Liveness unbedenklich noch als Messpunkt brauchbar.
>
> Die übrigen 14 Läufe sind unauffällig und liefern eine konsistente
> Kalibration; `T_measure_start = 30.000` und `T_final = 42.000` sind auf
> ihnen begründet.

### Empfohlener nächster Schritt

Den Durchsatzzerfall als eigene, eng begrenzte Phase behandeln — Vorgehen wie
bei den Klassen A bis C. Reproduktion ist deterministisch (`ABC+ABC`,
Seed 7); der Zerfall setzt ab etwa t = 20.000 ein und ist ab t = 30.000
deutlich. Erste Ansatzpunkte aus den Zählern: die Lückenlänge wächst, während
die Deadlock-Detektionen auf die Laufzeit normiert unauffällig bleiben — es
sieht eher nach einer sich aufbauenden Struktur im Lager aus als nach einem
Verkehrsproblem. Ein Zustandsabzug bei t = 25.000, 32.000 und 40.000
(Stapelhöhen, Verteilung der A-Klasse, offene Tasks, Backlog) sollte die
Frage schnell entscheiden.

Falls sich herausstellt, dass es sich um reguläres Sättigungsverhalten einer
einzelnen Seed-Kombination handelt und nicht um einen Defekt, ist die
Alternative, den Fall über die bereits vereinbarte Regel zu behandeln
(`not_converged_before_measurement`, Lauf behalten, getrennt ausweisen) —
dann aber ausdrücklich als Ergebnis dokumentiert und nicht als Ausnahme
weggeräumt.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

> **Nachtrag 2026-08-22 (Abschnitt H):** Die Frage nach der Klassifikation von
> ABC+ABC/Seed 7 ist damit **hinfällig geworden**. Der ABC-Audit hat einen
> Implementierungsfehler gefunden, der die Ordered-Return-Ordnung von ABC und
> POPULARITY **umkehrte**. Alle Zahlen dieses Abschnitts stammen aus Läufen
> mit invertierter Policy und taugen nicht zur Beurteilung des
> ABC-Verhaltens.

---
---

# ABC / POPULARITY Correctness Audit (2026-08-22)

| | |
|---|---|
| Commit | `1c127be` (Branch `working_sim`) |
| Python / pytest | 3.10.12 / 9.1.1 |
| Testsuite vorher | 443 passed |
| Testsuite nachher | **453 passed** (10 neue Tests) |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## H.1 Ergebnis des Audits in einem Satz

Der Audit hat **einen schweren Implementierungsfehler** gefunden: der Ordered
Return legte die Blocking-Bins in **umgekehrter** Reihenfolge zurück. ABC und
POPULARITY taten damit systematisch das **Gegenteil** ihrer Definition.

Alle anderen geprüften Punkte sind korrekt.

---

## H.2 Was korrekt ist

### ABC-Klassifikation

```text
A: 864 Bins = 20,0 %      Grenze bin 863 -> A, bin 864 -> B
B: 1296 Bins = 30,0 %     Grenze bin 2159 -> B, bin 2160 -> C
C: 2160 Bins = 50,0 %
heisseste Bin (id 0) -> A       kaelteste Bin (id 4319) -> C
```

Exakt, kein Off-by-One, Rankingrichtung stimmt. `set_abc_class` wird
ausschließlich in `config/init_strategy.py` aufgerufen — nichts überschreibt
die Klasse später. Die Klassifikation nutzt nur die `bin_id`, nie eine
Stapelposition. Nachfragebezug bestätigt: A trägt 80,8 % der Requests.

### ABC Target Placement

Unabhängig nachgerechnet auf einem kontrollierten State (41 Kandidaten):

```text
A  Soll: min(distance + depth)   -> gewaehlt score 2   = Optimum   OK
C  Soll: max(distance)           -> gewaehlt dist 6    = Optimum   OK
Kandidatenmenge: 0 volle Stacks, 0 Pufferzonen-Zellen                OK
```

Richtungen stimmen, kein Bonus/Penalty-Vorzeichenfehler.

### POPULARITY `access_count`

Genau **eine** Erhöhung je physischem Retrieval, an der Stelle, an der die
Target-Bin an der Pickstation ankommt (`_handle_robot_drop`, Zweig
`remove_target`). Kein Increment bei Arrival, Assignment, Batch-Mitglied oder
Return. Die zweite, historische Zählstelle ist dokumentiert deaktiviert.
Batching erhöht genau einmal.

### POPULARITY Warmup

```text
total_accesses = 49 -> Warmup aktiv
total_accesses = 50 -> Warmup beendet
total_accesses = 51 -> Warmup beendet
```

`>= 50`-Semantik, kein Off-by-One. Einheit sind kumulierte physische
Retrievals, nicht Requests. Der Warmup wählt aus **derselben**
Kandidatenmenge wie die aktive Phase.

### POPULARITY Target Placement

```text
p(hot) = 1,0  -> gewaehlter Score 0,1667 = Minimum   OK
p(cold) = 0,0 -> gewaehlter Score 0,6667 = Maximum   OK
```

`_get_popularity_score` nutzt ausschließlich den beobachteten
`access_count`; kein Zugriff auf künftige Requests oder
Zipf-Wahrscheinlichkeiten. `_calc_expected_digging_depth` ist die
dokumentierte Vereinfachung „aktuelle Stapelhöhe".

### Fallbacks

ABC und POPULARITY werfen `RuntimeError`, wenn keine zulässigen Kandidaten
existieren — kein stiller Fallback, keine Umgehung der Eligibility. Der
POPULARITY-Warmup nutzt dieselbe Kandidatenmenge wie die aktive Phase
(Befund P3-05 bereits früher behoben). Tie-Breaks ziehen aus dem
Placement-RNG-Strom; das ist endogene Policy-Zufälligkeit, dokumentiert und
seedstabil.

---

## H.3 Der gefundene Defekt: Ordered Return war invertiert

### Mechanismus

`ReorderingSelector.reorder_blockers` liefert die Rücklagerungsreihenfolge —
erstes Element wird zuerst zurückgelegt und landet **unten**. Die Rückgabe
konsumiert `temp_storage` aber vom **Ende** her (`peek_last_relocation()` →
`temp_storage[-1]`).

`reorder_blockers_for_return` sortierte **aufsteigend** nach dieser
Reihenfolge und drehte sie damit exakt um.

Gemessen (deterministische Reproduktion,
`experiments/closeout/probe_reorder_direction.py`):

| Strategie | Soll (unten→oben) | Ist (unten→oben) |
|---|---|---|
| ABC | C, B, A | **A, B, C** |
| POPULARITY | 0, 5, 20 Zugriffe | **20, 5, 0** |
| LOFI | Originalstapel | invertiert |

Beide untersuchten Policies legten die **häufig nachgefragten Bins
systematisch nach unten** — das Gegenteil ihrer Definition. Jeder Ordered
Return erhöhte damit die Grabtiefe für genau die Bins, die am häufigsten
gebraucht werden.

### Warum es niemand gemerkt hat

Die vorhandenen Tests prüfen `ReorderingSelector.reorder_blockers`
**isoliert** — dort war die Reihenfolge korrekt. Die Stapelordnung, die am
Ende tatsächlich entsteht, wurde nie geprüft.

### Unabhängiger Prüfstein

Ohne Reordering ist `temp_storage` in Auslagerungsreihenfolge
[oberste, …, unterste]; die unterste muss zuerst zurück und steht am Ende —
die Konsumreihenfolge stimmt also. **LOFI liefert genau diese Reihenfolge und
muss deshalb ein No-Op sein.** Mit absteigender Sortierung ist es das, mit
aufsteigender war es das nicht. Das entscheidet die Richtungsfrage ohne
Bezug auf ABC oder POPULARITY.

### Fix

Eine Zeile in `RobotTask.reorder_blockers_for_return`: `reverse=True`. Keine
Policy-Semantik geändert, keine Score-Funktion angefasst.

### Wirkung, gemessen

Mittlere Tiefe der A-Klasse (0 = ganz oben), gleiche Seeds, gleicher
Zeitpunkt t ≤ 18.000:

| Lauf | vorher | nachher |
|---|---|---|
| ABC+ABC / 1 | 3,217 | **2,758** |
| ABC+ABC / 7 | 3,371 | **2,961** |
| ABC+ABC / 42 | 3,277 | **2,852** |
| POPULARITY / 1 | 2,817 | 2,705 |
| POPULARITY / 7 | 2,913 | 2,845 |
| POPULARITY / 42 | 2,862 | 2,871 |
| baseline_reference / 1 | 2,693 | 2,695 |
| baseline_reference / 7 | 2,776 | 2,797 |
| baseline_reference / 42 | 2,777 | 2,610 |

Die A-Bins liegen bei ABC nach dem Fix in allen drei Seeds **messbar weiter
oben** — genau das, was die Policy definiert. Bei `baseline_reference` (LOFI)
ändert sich erwartungsgemäß praktisch nichts.

RR+RR und LR+NR sind **bit-identisch unberührt** (nachgewiesen durch
Spurvergleich): ohne Ordered Return wird der Reordering-Pfad nie erreicht.
Ihre Kalibrationsläufe bleiben gültig.

### Regressionstests

`tests/test_ordered_return_stack_order.py` (10 Tests) prüft die **tatsächlich
entstehende Stapelordnung** statt nur den Selektor: ABC-Ordnung, mehrere Bins
je Klasse, Determinismus, POPULARITY nach `access_count` statt ABC-Klasse,
Tie-Breaks, LOFI als No-Op, und zwei End-to-End-Läufe.

---

## H.4 Zweiter Defekt: veraltetes Ziel einer Blocker-Rücklagerung

Beim Nachrechnen der Kalibration trat auf:

```text
RuntimeError: Cannot mark relocation restored for bin 2154:
              expected to_stack S_1_9, got S_0_9
```

Ursache, aus dem Trace belegt: Das Rückgabeziel eines Blockers wird umgeplant,
wenn der Ursprungsstack nicht aufnahmefähig ist. Bin 2154 wurde zwischen
t = 1275 und t = 1796 **fünfmal** umgeplant; ein bei t = 1716 auf `S_0_9`
geplanter Drop lief bei t = 1797 durch, während der Eintrag längst auf
`S_1_9` zeigte.

Fix: Ein Blocker-Drop, dessen Ziel nicht mehr dem aktuellen Eintrag
entspricht, wird **vor der Ausführung** als veraltet verworfen und der Task
neu geplant (`[STALE][DROP_BLOCKER]`). Die Konsistenzprüfung bleibt
unangetastet — sie soll genau solche Abweichungen melden.

---

## H.5 Dritter Defekt — gefunden, NICHT behoben

Nach den beiden Fixes bleiben `ABC+ABC / Seed 7` und `/ Seed 42` stehen:

```text
ABC+ABC / 7 : letztes Retrieval t=14.176, danach 6.652 ZE ohne Fortschritt
ABC+ABC / 42: letztes Retrieval t=12.761, danach 5.756 ZE ohne Fortschritt
ABC+ABC / 1 : gesund (492 Retrievals bis t=19.108, Stillstand 30 ZE)
POPULARITY, baseline_reference: alle sechs gesund
```

Zustandsaufnahme von ABC+ABC/Seed 7 bei t = 20.828:

```text
Ports frei:   PS_0 robot_on_port=None,  PS_1 robot_on_port=None
Events in der Queue: 10 — fuer die Roboter 2, 3, 5, 6, 7
Roboter 0, 1, 4: haben einen Task, aber KEIN Event
robot 4 (17,17): Task req=374, phase=retrieve_target, Ziel Bin 11 auf (13,15)
                 pfadrest=[], next=None
robot 3, 6, 7:   wollen alle nach (17,17) und warten auf robot 4
```

**Drei Roboter halten einen Task, haben aber kein einziges Event in der
Queue** — sie sind aus der Ereignisschleife gefallen und blockieren als
stehende Hindernisse die übrigen.

Die Stelle ist eindeutig:

```python
# simulation/event_handler.py:4102 und :4193
action = scheduling_result["action"]
if action is None:
    return                      # <- Roboter behaelt den Task, ohne Event
```

`Scheduler.try_schedule` weist den Task zu (`robot.assign_task(task)`) und
ruft `strategy.next_action`. Liefert die Strategie `None` — etwa weil die
Target-Bin gerade `in_transit` ist, ein dokumentiert unkritischer Zustand mit
der Absicht „Task kurz warten lassen und später neu versuchen" — kehrt der
Handler zurück, **ohne etwas einzuplanen**. Ein späterer Versuch findet nie
statt.

Zum Vergleich behandelt `_schedule_next_action_for_task_new` denselben Fall
korrekt (Zeile 2640): Task zurück in `waiting_tasks`, Roboter freigeben. Dem
Zuweisungspfad fehlt genau das.

**Nicht behoben.** Der Befund ist neu, betrifft einen kritischen Pfad, und
eine Änderung ohne anschließende vollständige Neuvalidierung der Kalibration
wäre nicht verantwortbar. Der Fix selbst ist absehbar klein — dasselbe Muster
wie in Zeile 2640 —, braucht aber einen eigenen Validierungsdurchgang.

---

## H.6 Klassifikation von ABC+ABC / Seed 7

```text
REAL DEFECT
```

Die frühere Frage „legitime Policy-Degeneration oder Defekt?" lässt sich mit
den alten Daten **gar nicht** beantworten: sie stammen aus Läufen, in denen
ABC das Gegenteil seiner Definition tat. Der beobachtete Durchsatzzerfall ist
damit erklärbar — mit invertierter Ordnung wandern die A-Bins bei jedem
Ordered Return nach unten, die Grabtiefe für die häufigsten Bins wächst
monoton.

Nach dem Fix ist der Zerfall nicht mehr das Bild; stattdessen tritt der harte
Stillstand aus H.5 auf. Eine Aussage über das *legitime* Verhalten von ABC ist
erst möglich, wenn auch dieser Defekt behoben ist.

**Es wird ausdrücklich nicht behauptet**, ABC sei eine legitime Degeneration.
Die Datenlage trägt diese Aussage nicht.

---

## H.7 Correctness und CRN

Audit-Harness, je 400 ZE — ABC+ABC/7, POPULARITY/7, baseline_reference/7:

```text
invalid_pickups=0  invalid_drops=0  invalid_moves=0  collisions=0
violations=0
```

Kein Bin-Verlust, keine Duplikate, keine Ownership- oder
Cross-Station-Verletzung. `move_recovery_unresolved = 0`,
`task_deadlock = 0`. CRN unverändert intakt über 10 Seeds × 5 Policies.
Testsuite **453 passed**; die Regressionen der Klassen A/B/C, der
Lifecycle-Tests und des PortExitGuard bleiben grün.

---

## H.8 Auswirkungen auf Kalibration, RQ3/RQ4 und Zeitfenster

Die Kalibration aus Abschnitt G ist für `baseline_reference`, `ABC+ABC` und
`POPULARITY+POPULARITY` **ungültig geworden** — sie beschreibt eine
invertierte Policy. Gültig bleiben `RR+RR` und `LR+NR` (bit-identisch).

Damit sind auch `T_measure_start = 30.000` und `T_final = 42.000` derzeit nur
noch auf sechs statt dreizehn Läufen abgestützt. Beide Werte bleiben
**unverändert stehen** — sie werden erst nach Behebung von H.5 neu bewertet.
Eine Änderung jetzt wäre eine Anpassung an unvollständige Daten.

Die RQ4-Regel selbst (Signal, TVD, Blockbildung, Persistenz, drei
Statuswerte) ist von den Defekten unberührt; nur die damit erzeugten
Konvergenzzeiten für die drei Ordered-Return-Policies müssen neu erhoben
werden.

---

## H.9 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-32 (**hinfällig**) | Der Durchsatzzerfall von ABC+ABC/7 beruhte auf der invertierten Ordered-Return-Ordnung. |
| L-35 (**neu**) | **Alle ABC-/POPULARITY-/baseline-Ergebnisse vor dem 2026-08-22 sind mit invertierter Ordered-Return-Ordnung entstanden** und für inhaltliche Aussagen unbrauchbar. |
| L-36 (**neu**) | Ein Roboter kann einen Task zugewiesen bekommen, ohne dass ein Event eingeplant wird, wenn die erste Aktion `None` ist (`event_handler.py:4102/:4193`). Er bleibt dauerhaft stehen und blockiert Zellen. Offener Blocker. |
| L-37 (**neu**) | Das Rückgabeziel eines Blockers kann mehrfach umgeplant werden; in Flug befindliche Drops werden seit 2026-08-22 als veraltet verworfen. Die Häufigkeit der Umplanungen (fünfmal in 500 ZE im beobachteten Fall) ist nicht untersucht. |
| L-27, L-30, L-31, L-33, L-34 | unverändert. |

---

## H.10 Freeze-Gate

| Kriterium | Status |
|---|---|
| ABC-Klassifikation korrekt | **erfüllt** |
| ABC Placement korrekt | **erfüllt** |
| ABC Reordering korrekt | **erfüllt nach Fix** — vorher invertiert |
| POPULARITY `access_count` korrekt | **erfüllt** |
| POPULARITY Warmup korrekt | **erfüllt** |
| POPULARITY Reordering korrekt | **erfüllt nach Fix** — vorher invertiert |
| POPULARITY Placement korrekt | **erfüllt** |
| Fallbacks respektieren Eligibility | **erfüllt** |
| Vollständige Testsuite grün | **erfüllt** — 453 passed |
| CRN intakt | **erfüllt** |
| Keine bekannte Liveness-Verletzung | **NICHT erfüllt** — H.5 |
| ABC+ABC/7 klassifiziert | **erfüllt** — REAL DEFECT |
| Kalibration auf finalem Code gültig | **NICHT erfüllt** — für drei Policies neu zu erheben |
| `T_measure_start` / `T_final` begründet | **teilweise** — derzeit nur auf RR+RR und LR+NR abgestützt |

### Urteil

```text
FINAL_EXPERIMENT_NOT_FROZEN
```

**Verbleibender Blocker — genau einer:**

> **Ein Roboter kann einen Task halten, ohne dass jemals ein Event für ihn
> eingeplant wird** (`event_handler.py:4102` und `:4193`, wenn die erste
> Aktion `None` ist). Er bleibt dauerhaft stehen und blockiert als Hindernis
> die übrigen Roboter. Betroffen sind nach den beiden Fixes dieser Phase
> `ABC+ABC / Seed 7` (Stillstand ab t = 14.176) und `/ Seed 42` (ab
> t = 12.761); die sechs übrigen Ordered-Return-Läufe sind gesund.
>
> Die Stelle ist eindeutig lokalisiert und das Korrekturmuster liegt im
> selben Modul bereits vor (Zeile 2640: Task zurück in `waiting_tasks`,
> Roboter freigeben). Der Fix wurde bewusst nicht mehr in dieser Phase
> vorgenommen, weil er einen eigenen vollständigen Validierungsdurchgang
> braucht.

### Empfohlener nächster Schritt

1. Den Zuweisungspfad an beiden Stellen so behandeln wie Zeile 2640, mit
   Regressionstest („Roboter mit Task hat immer ein Event oder keinen Task").
2. Danach die neun Ordered-Return-Läufe (baseline, ABC, POPULARITY × Seeds
   1/7/42) erneut ab t = 0 rechnen; RR+RR und LR+NR können übernommen werden.
3. Erst dann Konvergenzzeiten, `T_measure_start` und `T_final` bestätigen
   oder neu begründen — und erst dann ist die Frage nach dem legitimen
   Langzeitverhalten von ABC überhaupt beantwortbar.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

---
---

# Bug 3 behoben + High-Level Face Validity (2026-08-22)

| | |
|---|---|
| Testsuite vorher | 453 passed |
| Testsuite nachher | **453 passed** |
| Commits / Pushes | keine |
| Finale Kampagne | nicht gestartet |

---

## I.1 Bug 3 behoben: verwaiste Tasks

`EventHandler.schedule_available_robots` kehrte zurück, sobald die erste
Aktion eines frisch zugewiesenen Tasks `None` war — der Roboter behielt den
Task, bekam nie ein Event und stand dauerhaft still.

Der Fix übernimmt das Muster, das `_schedule_next_action_for_task_new`
(Zeile 2640) für denselben Fall bereits verwendet: Task zurück in
`waiting_tasks`, Roboter freigeben, Meldung `[RELEASE][NO_ACTION]`. Der Task
bleibt fachlich erhalten und wird beim nächsten Scheduling regulär neu
vergeben.

---

## I.2 Face Validity — Einzelzyklen

Ein vollständiger Retrieval-Zyklus je Policy, gleicher Seed, gleicher
Startzustand (`experiments/closeout/face_validity.py trace`). Target-Bin 59
(Klasse B), Originalstack `S_4_6`, vorher unten→oben
`[70(B), 113(C), 28(A), 59(B), 1(A)]`:

| Policy | Blocker 1 (A-Klasse) | Target-Return | Stack nachher |
|---|---|---|---|
| baseline_reference | zurück auf `S_4_6` bei t=74 | `S_0_0` (random) | `[70, 113, 28, 1]` |
| RR+RR | **bleibt** auf `S_6_0` | `S_0_0` (random) | `[70, 113, 28]` |
| LR+NR | **bleibt** auf `S_3_6` | **`S_4_6`** (Originalstack, Distanz 0) | `[70, 113, 28, 59]` |
| ABC+ABC | zurück auf `S_4_6` bei t=74 | `S_0_0` | `[70, 113, 28, 1]` |
| POPULARITY | zurück auf `S_4_6` bei t=74 | `S_0_0` | `[70, 113, 28, 1]` |

Jede Zeile entspricht ihrer Definition:

* **RR+RR und LR+NR** legen den Blocker **nicht** zurück — er bleibt dort
  liegen, wo er beim Digging abgelegt wurde. Genau das bedeutet
  `return_blocking_bins=False`.
* **LR+NR** gibt die Target-Bin auf den **Originalstack** zurück. `NEAREST`
  misst die Distanz zum Originalstack; ist dieser zulässig, gewinnt er mit
  Distanz 0. Kein Bezug zur Pickstation.
* **baseline, ABC, POPULARITY** stellen den Blocker zurück — Ordered Return
  aktiv.

### Zyklus mit mehreren Blockern

Erst mit mehreren Blockern wird die Reihenfolge sichtbar
(`face_validity_multiblocker.py`):

```text
baseline_reference (LOFI)
  ausgelagert (oben zuerst):        [91, 137, 65]
  Rueckgabe (zuerst = unten):       [65, 137, 91]
  -> Originalordnung exakt wiederhergestellt

ABC+ABC (ABC)
  ausgelagert (oben zuerst):        [65, 137, 91]
  Rueckgabe (zuerst = unten):       [91(C), 137(C), 65(B)]
  -> unten C, C, darueber B          PLAUSIBEL

POPULARITY (POPULARITY)
  Rueckgabe (zuerst = unten):       [91(n=0), 137(n=0), 65(n=0)]
  -> alle Zaehler 0, stabile Reihenfolge erhalten
```

Der POPULARITY-Fall ist hier nicht diskriminierend (alle Zähler 0); die
Richtung ist über die Unit-Tests
(`test_popularity_ordered_return_puts_hot_bins_on_top`,
`test_popularity_uses_access_count_not_abc_class`) und die Aggregatprüfung
abgesichert.

---

## I.3 Face Validity — Aggregatprüfungen

Kurzer Lauf je Policy (7×7, 150 Bins, 3 Roboter, 2500 ZE, Zipf 1,0). Tiefe
ist **von oben** gemessen: 0 = ganz oben, kleiner = besser zugänglich.

| Policy | Retr. | Stillstand | Tiefe A | Tiefe C | Tiefe heiß | Tiefe kalt | Ordered Return | verwaiste Roboter |
|---|---|---|---|---|---|---|---|---|
| baseline_reference | 114 | 12 | 1,19 | 1,83 | 0,50 | 2,22 | **True** | 0 |
| RR+RR | 113 | 5 | 1,66 | 2,07 | 0,89 | 2,45 | **False** | 0 |
| LR+NR | 141 | 8 | 1,31 | 1,83 | 0,89 | 2,11 | **False** | 0 |
| **ABC+ABC** | 112 | 4 | **0,89** | 1,99 | 0,33 | 1,87 | **True** | 0 |
| POPULARITY | 98 | 3 | 1,21 | 2,01 | 0,50 | 2,24 | **True** | 0 |

Auswertung der geforderten Checks:

* `mean depth(A) < mean depth(C)` gilt in **allen fünf** Policies. Die
  **stärkste Trennung hat ABC+ABC** (0,89 vs 1,99, Abstand 1,10) — deutlich
  mehr als baseline (0,64), POPULARITY (0,80), LR+NR (0,52), RR+RR (0,41).
  ABC tut also nicht nur das Richtige, sondern erkennbar stärker als die
  Policies ohne ABC-Sortierung.
* Häufig zugegriffene Bins liegen in allen Policies flacher als nie
  angefragte. Unter Zipf korreliert „heiß" stark mit A-Klasse, der Check
  trennt ABC und POPULARITY deshalb nicht scharf — die Richtung stimmt
  überall.
* `blockers_returned` ist **genau** bei baseline, ABC und POPULARITY wahr und
  bei RR+RR und LR+NR falsch.
* **Null verwaiste Roboter** in allen fünf Policies — der Bug-3-Fix wirkt.
* Kein Abbruch, keine `Invalid task lifecycle`-Meldung, Stillstand ≤ 12 ZE.

---

## I.4 Gate

```text
High-Level Face Validity
baseline_reference: PASS
RR+RR:              PASS
LR+NR:              PASS
ABC+ABC:            PASS
POPULARITY+POP:     PASS
```

Auffälligkeiten:

* Keine Umkehr einer Strategieabsicht mehr feststellbar. Der zuvor gefundene
  invertierte Ordered Return ist behoben und durch den End-to-End-Test
  abgesichert.
* Keine verwaisten Tasks mehr.
* baseline, ABC und POPULARITY wählten im getracten Zyklus zufällig
  denselben Rückgabestack `S_0_0` — über drei unterschiedliche Mechanismen
  (RANDOM, ABC-B-Median, POPULARITY-neutral). Das ist Zufall dieser einen
  Situation, kein gemeinsamer Codepfad; die Score-Funktionen wurden in
  Abschnitt H.2 einzeln gegen unabhängig berechnete Optima geprüft.
* POPULARITY liegt im Kurzlauf bei der A/C-Trennung nur leicht über baseline.
  Erwartbar: der Warmup von 50 physischen Retrievals verbraucht bei 98
  Retrievals im Kurzlauf die halbe Laufzeit. Kein Widerspruch, aber im
  Kurzlauf nicht aussagekräftig.

Correctness auf der finalen Geometrie (400 ZE, ABC+ABC/7, RR+RR/42,
LR+NR/42): 0 invalid pickups/drops/moves, 0 Kollisionen, 0 Verletzungen.
CRN intakt über 10 Seeds × 5 Policies. Testsuite 453 passed.

**Damit ist das Gate für die Kalibration erfüllt.** Offen bleibt allein, dass
die Kalibration für baseline, ABC und POPULARITY nach den Fixes dieser Phase
neu zu rechnen ist (RR+RR und LR+NR sind bit-identisch unberührt).

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.

---

# Final Validation, Recalibration and Pre-Campaign Freeze Decision (2026-08-24)

Diese Phase beantwortet genau zwei Fragen:

1. Halten die Fixes der Abschnitte G, H und I über lange Horizonte?
2. Welche Zeitwerte gelten für die 50-Run-Kampagne — und ist die Kampagne
   technisch startbereit?

Antwort in einem Satz: **Die Simulation ist inhaltlich freigabereif, der
Export- und Kampagnenpfad ist es nicht.**

---

## J.1 Stage Gate A — Bug-3-Regression und Testsuite

`tests/test_task_release_without_action.py` (8 Tests) prüft die geforderte
Kette `NO_ACTION → RELEASE → RETRY → PROGRESS` und nicht nur „keine
Exception".

Entscheidend war der Aufbau. Es genügt **nicht**, an einer Bin nur
`mark_in_transit()` zu setzen: solange die Bin im Stack liegt, plant die
Strategie ganz normal weiter und der Fehlerpfad wird gar nicht betreten. Die
erste Fassung des Tests war deshalb in 4 von 8 Fällen grün, ohne irgendetwas
zu zeigen. `take_bin_into_transit()` hebt die Bin real aus dem Stack; erst
dann liefert `next_action` das `None`, um das es geht.

Belegt im Lauf:

```text
[RELEASE][NO_ACTION] t=0 robot=0 task=4711 ohne Aktion -> zurück in waiting_tasks
nach put_bin_back: Task erneut vergeben, events=6, stranded=[]
```

Geprüft wird zusätzlich: der Task überlebt genau einmal (kein Verlust, kein
Duplikat), es entsteht kein neuer Request, der Freigabepfad zieht **keine**
Zufallszahl (CRN bleibt unberührt) und es bleibt keine Blocker-Ownership
zurück.

**Testsuite: 464 passed, 0 failed** (41 Dateien, zwei Läufe wegen des
Zeitbudgets). `tests/test_simulation_visual.py` ist nicht ausführbar, weil
`flask` in der Sandbox fehlt — Umgebungsgrenze, keine Regression.

---

## J.2 Stage Gate B — die ABC-Stillstände sind Artefakte gewesen

Frisch ab t = 0 auf dem korrigierten Code, deutlich über die alten
Stillstandspunkte (14.176 bzw. 12.761) hinaus:

| Lauf | t_end | Retrievals | letztes Retrieval | größte Lücke |
|---|---|---|---|---|
| ABC+ABC / 7 | 21.929 | 702 | 21.928 | 229 ZE |
| ABC+ABC / 42 | 22.963 | 728 | 22.946 | 239 ZE |

Kein `move_recovery_unresolved`, kein `task_deadlock`, keine Exception,
4320 Bins vollständig und eindeutig. Der Durchsatz ist über die gesamte
Strecke flach.

Damit ist belegt: die zuvor berichtete „ABC7-Degeneration" war **kein**
Policy-Verhalten, sondern Folge des invertierten Ordered Return und der
verwaisten Tasks.

---

## J.3 Kalibration: 15 Läufe frisch ab t = 0

5 Policies × Seeds 1, 7, 42, alle auf **einem** eingefrorenen Codestand.
ABC+ABC/Seed 7 als Hauptregressionsfall bis 42.000 ZE.

| Policy | Seed | t_end | Retr. | letztes Retr. | Stillstand am Ende | größte Lücke |
|---|---|---|---|---|---|---|
| ABC+ABC | 1 | 30.000 | 956 | 29.928 | 72 | 358 |
| ABC+ABC | 42 | 30.000 | 954 | 29.892 | 108 | 239 |
| ABC+ABC | 7 | 42.000 | 1341 | 41.934 | 66 | 297 |
| LR+NR | 1 | 30.000 | 1723 | 29.977 | 23 | 153 |
| LR+NR | 42 | 30.000 | 1687 | 29.998 | 2 | 152 |
| LR+NR | 7 | 30.000 | 1778 | 29.997 | 3 | 94 |
| POPULARITY | 1 | 30.000 | 973 | 29.972 | 28 | 259 |
| POPULARITY | 42 | 30.000 | 984 | 29.954 | 46 | 279 |
| POPULARITY | 7 | 30.000 | 1076 | 29.955 | 45 | 187 |
| RR+RR | 1 | 30.000 | 1199 | 29.967 | 33 | 142 |
| RR+RR | 42 | 30.000 | 1143 | 29.983 | 17 | 211 |
| RR+RR | 7 | 30.000 | 1221 | 29.958 | 42 | 142 |
| baseline | 1 | 30.000 | 1275 | 29.930 | 70 | 123 |
| baseline | 42 | 30.000 | 1229 | 29.965 | 35 | 164 |
| baseline | 7 | 30.000 | 1328 | 29.999 | 1 | 170 |

Über alle 15 Läufe: `move_recovery_unresolved = 0`, `task_deadlock = 0`,
keine Exception. Die größte Retrievallücke im gesamten Datensatz beträgt
358 ZE — bei mittleren Abständen von 17–31 ZE ist das eine Verzögerung, kein
Stillstand.

### Ungeplanter Determinismus-Nachweis

Beim Versuch, den Horizont nachträglich von 30.000 auf 32.000 ZE anzuheben,
wurden vier Läufe (`baseline/1,42,7` und `RR+RR/1`) versehentlich von t = 0
neu gerechnet: `pilot_slice.py` löscht den Checkpoint, sobald ein Lauf fertig
ist, und `_pilot_finished` wird mitgepickelt. Beides ist inzwischen
korrigiert (der Merker blockiert nur noch, wenn der **angeforderte** Horizont
bereits erreicht ist).

Der Unfall war lehrreich: die vier neu gerechneten Läufe reproduzierten
Retrievalzahl, letzten Retrieval-Zeitpunkt, größte Lücke und Fensterzahl
**exakt**. Die logabgeleiteten Zähler verdoppelten sich dabei auf genau das
Zweifache (z. B. `deadlock_detected` 162 → 324, `stale_pickup_no_task`
4 → 8, `drop_bury_redirect` 41 → 82), weil die Zählerdatei über beide
Rechnungen akkumuliert. Ein exakter Faktor 2 über zwölf unabhängige Zähler
ist selbst ein Determinismusbeleg. Für diese vier Läufe gelten die
halbierten Zählerwerte.

---

## J.4 Neuer Zeithorizont

Die alten Werte 30.000 / 12.000 / 42.000 stammen aus Läufen, in denen
`baseline_reference`, `ABC+ABC` und `POPULARITY+POPULARITY` mit invertiertem
Ordered Return liefen. **Sie sind ungültig und wurden nicht übernommen.**

Dieselbe Herleitungsregel, neu angewandt:

```text
langsamste beobachtete Konvergenz          15.100 ZE  (RR+RR, Seed 7)
groesste Streuung innerhalb einer Policy    4.400 ZE  (RR+RR: 10.700 ... 15.100)
Summe                                      19.500 ZE
aufgerundet                       ->       20.000 ZE
```

Fensterlänge, **abgezählt** statt hochgerechnet:

| Fenster | Retrievals im langsamsten Lauf | Spanne über alle 15 |
|---|---|---|
| 8.000 ZE | 232 | 232 … 478 |
| **10.000 ZE** | **294** | **294 … 592** |

```text
T_measure_start   = 20.000 ZE
Measurement Window= 10.000 ZE
T_final           = 30.000 ZE
```

Das Fenster wird kürzer (12.000 → 10.000 ZE), die statistische Masse darin
**größer** (174 hochgerechnet → 294 gemessen): die Retrievalrate hat sich
nach den Fixes etwa verdoppelt. Der Gesamthorizont sinkt von 42.000 auf
30.000 ZE, rund 29 % weniger Rechenzeit je Lauf.

**Sensitivität.** `LR+NR/7` gilt als `converged_then_rediverged` und geht
nicht in die Streuung ein. Zählte man sein Plateau (10.800 ZE) mit, stiege
die LR+NR-Spanne auf 4.500 und die Summe auf 19.600 ZE — `T_measure_start`
bliebe 20.000. Der Wert hängt nicht an dieser Einordnung.

Zur Einordnung von `LR+NR/7` selbst: Plateauniveau 0,00701, das gleitende
Mittel danach erreicht 0,01083 gegen die Schwelle 0,01052 — eine
Überschreitung um 3 %. Ein Grenzfall im Rauschband. **Die Schwelle wurde
nicht angepasst.**

Alle 15 Läufe konvergieren räumlich; 14 als `converged`, einer als
Grenzfall. Kein `not_converged` mehr.

---

## J.5 Face Validity auf der finalen Geometrie

Mittlere Tiefe unter der Stapeloberkante am Laufende (0 = ganz oben):

| Policy | Seed | A | B | C | A<C | hot_top | Korr(Popularität, Tiefe) |
|---|---|---|---|---|---|---|---|
| ABC+ABC | 1 | 2,52 | 3,03 | 3,59 | ja | 0,650 | −0,109 |
| ABC+ABC | 42 | 2,53 | 3,04 | 3,60 | ja | 0,654 | −0,133 |
| ABC+ABC | 7 | 2,42 | 3,00 | 3,66 | ja | 0,672 | −0,120 |
| LR+NR | 1 | 3,11 | 3,35 | 3,38 | ja | 0,541 | −0,115 |
| LR+NR | 42 | 3,14 | 3,35 | 3,36 | ja | 0,547 | −0,075 |
| LR+NR | 7 | 3,03 | 3,35 | 3,42 | ja | 0,552 | −0,082 |
| POPULARITY | 1 | 2,58 | 3,31 | 3,42 | ja | 0,634 | −0,192 |
| POPULARITY | 42 | 2,58 | 3,25 | 3,46 | ja | 0,628 | −0,150 |
| POPULARITY | 7 | 2,59 | 3,29 | 3,41 | ja | 0,625 | −0,145 |
| RR+RR | 1 | 2,86 | 3,38 | 3,47 | ja | 0,589 | −0,086 |
| RR+RR | 42 | 2,99 | 3,34 | 3,45 | ja | 0,570 | −0,122 |
| RR+RR | 7 | 2,93 | 3,40 | 3,43 | ja | 0,586 | −0,105 |
| baseline | 1 | 2,41 | 3,26 | 3,51 | ja | 0,661 | −0,150 |
| baseline | 42 | 2,38 | 3,32 | 3,47 | ja | 0,669 | −0,164 |
| baseline | 7 | 2,47 | 3,29 | 3,44 | ja | 0,641 | −0,153 |

* A < B < C gilt in **allen 15** Läufen. Aus einem nahezu flachen
  Anfangszustand (3,14 / 3,17 / 3,23) entsteht überall die erwartete
  Schichtung.
* Die Korrelation zwischen Popularität und Tiefe ist überall negativ:
  häufig angefragte Bins liegen flacher.
* `LR+NR` zeigt die schwächste Schichtung (Spanne 0,3) — konsistent damit,
  dass es neben RR+RR ohne Ordered Return arbeitet und Blocker liegen lässt.

**Beobachtung, kein Defekt.** `ABC+ABC` erzeugt keine stärkere Klassentrennung
als `baseline_reference` (Spanne A→C: 1,06–1,23 gegen 0,97–1,10), obwohl
baseline mit LOFI/RANDOM arbeitet. Plausible Erklärung: baseline schafft im
selben Horizont deutlich mehr Retrievals (1275 gegen 956), und jedes
Retrieval legt die betroffene A-Bin ohnehin wieder nach oben. Die
Implementierung von ABC ist in Abschnitt H.2 einzeln gegen unabhängig
berechnete Optima geprüft worden und in `probe_reorder_direction.py` sowie
`face_validity_multiblocker.py` end-to-end belegt. Eine korrekt
implementierte Policy darf schwächer abschneiden — das ist ein Ergebnis, kein
Bug. Es wurde nichts daran verändert.

---

## J.6 Correctness, Liveness und CRN

Audit-Harness auf der **finalen** Konfiguration (20×30×8, 4320 Bins,
8 Roboter, 1.000 ZE, Seed 42), alle fünf Policies:

| Policy | Schritte | inv. Pickups | inv. Drops | inv. Moves | Kollisionen | Verletzungen | Deadlocks erkannt / behoben |
|---|---|---|---|---|---|---|---|
| ABC+ABC | 6.891 | 0 | 0 | 0 | 0 | 0 | 2 / 2 |
| POPULARITY | 7.033 | 0 | 0 | 0 | 0 | 0 | 3 / 3 |
| baseline | 7.179 | 0 | 0 | 0 | 0 | 0 | 8 / 8 |
| LR+NR | 9.158 | 0 | 0 | 0 | 0 | 0 | 10 / 10 |
| RR+RR | 10.993 | 0 | 0 | 0 | 0 | 0 | 1 / 1 |

Jede erkannte Blockade wurde aufgelöst; das längste Fenster ohne Fortschritt
lag bei 40–90 ZE.

CRN über 10 Seeds × 5 Konfigurationen: Layout-, Request- und Service-Hash je
Seed über alle Policies identisch, `eligibility_violations = 0`.
**VERDICT: CRN INTAKT.**

---

## J.7 Trockenlauf der 50er-Matrix — zwei blockierende Befunde

`experiments/closeout/dry_check_matrix.py` fährt alle 5 Policies × 10 Seeds
(1, 2, 3, 4, 7, 11, 13, 42, 99, 123) auf der finalen Geometrie über einen
kurzen Horizont und prüft die **Struktur** der Kampagne, nicht ihre
Ergebnisse.

Bestanden, jeweils 50 von 50:

| Prüfung | Ergebnis |
|---|---|
| Exceptions | 0 |
| verwaiste Roboter | 0 |
| unbekannte Exportfelder | 0 |
| Fenstermodus `time_window` | 50 |
| CRN: gleicher Seed → gleicher Nachfragestrom | 10 von 10 Seeds |
| 10 Seeds → 10 verschiedene Ströme | ja |

Nicht bestanden, ebenfalls jeweils 50 von 50:

**Befund J-1 — `retrievals.csv` und `runs.csv` meinen verschiedene Fenster.**

`summarise_run` filtert korrekt auf `[t_measure_start, t_final]` und zählt
3 … 13 Retrievals im Fenster. `retrieval_rows` markiert `in_measurement_window`
dagegen aus `steady["measurement_window"]` — dem **alten**
Steady-State-Fenster. Der Schlüssel existiert gar nicht mehr, die Spalte ist
in allen 50 Kombinationen durchgehend `False`.

Ursache: Der gemeinsame Zeitfenstermodus wurde in `summarise_run` ergänzt,
`retrieval_rows` blieb unverändert. Folge für die Kampagne: jede Analyse auf
Retrieval-Ebene (RQ2/RQ3: Grabtiefe, Blocking Bins, `levels_from_top`), die
auf `in_measurement_window` filtert, liefert eine **leere** Menge.

**Befund J-2 — vier Steady-State-Spalten sind strukturell tot.**

`Metrics.get_convergence_analysis()` liefert genau vier Schlüssel:
`is_converged`, `convergence_time`, `stability_metrics`, `snapshots`.
`summarise_run` liest daraus aber zusätzlich `status`,
`convergence_retrievals`, `measurement_complete` und `measurement_window` —
keiner davon existiert. `steady_state_status` ist deshalb in allen 50 Zeilen
leer, obwohl der Docstring `not_converged` verspricht und die eingefrorene
Regel aus F.8 verlangt, nicht konvergierte Läufe zu **markieren**.

Entschärfend: der RQ4-Status kommt in der eingefrorenen Methodik ohnehin
offline aus `analyse_rq4_plateau.py`. Die Spalten sind nicht falsch befüllt,
sondern gar nicht befüllt.

Beide Befunde betreffen **nur den Export**, nicht die Simulation. Sie wurden
gemäß Arbeitsauftrag **nicht ungefragt behoben.**

---

## J.8 Es gibt keinen Kampagnentreiber

`run_experiments.py` ist der einzige ausführbare Einstieg — und er entspricht
dem eingefrorenen Design in fünf Punkten nicht:

| Punkt | im Skript | eingefroren |
|---|---|---|
| Lauflänge | `simulation_time = 2000` | `T_final = 30.000` |
| Seeds | Default `[42, 123, 456, 789, 1011]` | `[1, 2, 3, 4, 7, 11, 13, 42, 99, 123]` |
| Matrixgröße | 5 × 5 = 25 Runs | 5 × 10 = 50 Runs |
| Messfenster | `t_measure_start` / `t_final` werden nie gesetzt | Pflicht |
| Export | `experiments/exporter.py` | `experiments/run_export.py` |

`experiments/run_export.py` enthält ausschließlich Funktionen und die Klasse
`ExperimentWriter` — **kein** `__main__`, kein Treiber. Aufgerufen wird es
derzeit nur aus Tests. Die gesamte eingefrorene Fenster- und KPI-Logik ist
damit vorhanden, aber nichts ruft sie für die Kampagne auf.

Weitere Beobachtungen aus derselben Prüfung:

* Policy-Namen weichen ab (`abc_policy` / `popularity_policy` gegen
  `ABC+ABC` / `POPULARITY+POPULARITY`).
* Ausgabetrennung ist gegeben, aber unvollständig definiert: Closeout-Belege
  liegen unter `experiments/closeout/results/`, ein Kampagnenziel existiert
  noch nicht.
* Alte Stop-Regeln sind sauber: `stop_on_convergence` ist per Default `False`
  und in `run_experiments.py` auskommentiert. Keine `TODO`/`FIXME`/
  `breakpoint()`-Reste im Produktionscode.
* Logvolumen: 150.000–200.000 Zeilen je 30.000-ZE-Lauf. Für 50 Runs muss
  `stdout` umgeleitet werden, sonst entstehen rund 8 Millionen Zeilen.
* Rechenzeitabschätzung aus den Kalibrationszeiten: 1.500–2.800 s je Lauf
  einkernig, also rund 30 CPU-Stunden für 50 Runs; bei vier parallelen
  Prozessen etwa 7–8 Stunden Wanduhr.
* `tests/reservation_table.py` ist im Index als gelöscht vorgemerkt (`D `).
  Vor einem Commit zu klären.

---

## J.9 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-29 (**erledigt**) | Der Abbruch in ABC+ABC/Seed 7 ist behoben; der Lauf erreicht 42.000 ZE mit durchgehendem Fortschritt. |
| L-31 (**bestätigt**) | `T_measure_start` beruht auf drei kalibrierten Seeds je Policy; sieben der zehn finalen Seeds sind ungetestet. Die Reserve deckt die größte beobachtete Streuung ab, garantiert aber keine Konvergenz für jeden Seed. |
| L-32 (**neu**) | `retrievals.csv → in_measurement_window` markiert das falsche Fenster (Befund J-1). Bis zur Behebung muss jede Retrieval-Analyse das Fenster selbst über `t_pickstation` bilden. |
| L-33 (**neu**) | `runs.csv → steady_state_status`, `convergence_retrievals` und `measurement_complete` bleiben leer (Befund J-2). RQ4 ist davon nicht betroffen, weil offline ausgewertet wird. |
| L-34 (**neu**) | Es existiert kein Kampagnentreiber für die eingefrorene 5 × 10-Matrix (Abschnitt J.8). |
| L-35 (**neu**) | `LR+NR / Seed 7` ist ein RQ4-Grenzfall (Schwelle um 3 % überschritten). Als `converged_then_rediverged` berichtet; die Schwelle wurde nicht angepasst. |
| L-27, L-28, L-30, L-14 bis L-26 | unverändert. |

---

## J.10 Freeze-Gate

| Kriterium | Status |
|---|---|
| Bug-3-Regression prüft `NO_ACTION → RELEASE → RETRY → PROGRESS` | **erfüllt** |
| Vollständige Testsuite grün | **erfüllt** — 464 passed, 0 failed |
| ABC+ABC/7 und /42 über die alten Stillstandspunkte hinaus | **erfüllt** — 21.929 / 22.963 ZE, flacher Durchsatz |
| 15 Kalibrationsläufe frisch ab t=0 auf einem Codestand | **erfüllt** |
| Alle fünf Policies machen über den langen Horizont Fortschritt | **erfüllt** — größte Lücke 358 ZE |
| Correctness-Zähler null | **erfüllt** — 0 über alle 15 Läufe und alle fünf Audit-Läufe |
| CRN intakt | **erfüllt** — 10 Seeds × 5 Konfigurationen |
| `T_measure_start` / `T_final` aus NEUEN Daten begründet | **erfüllt** — 20.000 / 30.000 ZE |
| Räumliche Konvergenz aller Läufe | **erfüllt** — 14 × `converged`, 1 Grenzfall |
| Face Validity auf der finalen Geometrie | **erfüllt** — A<B<C in 15 von 15 |
| Dokumentation konsistent | **erfüllt** — alte T-Werte als ungültig markiert |
| 5 × 10 Matrix läuft strukturell durch | **erfüllt** — 50 von 50 ohne Exception, CRN und Fenstermodus korrekt |
| Exportvertrag vollständig | **NICHT erfüllt** — Befunde J-1 und J-2 |
| Kampagnentreiber auf die eingefrorenen Parameter verdrahtet | **NICHT erfüllt** — Abschnitt J.8 |

### Urteil

```text
SIMULATION_VALIDATED           = JA
EXPERIMENT_HORIZON_FROZEN      = JA   (20.000 / 10.000 / 30.000 ZE)
FINAL_EXPERIMENT_FROZEN        = NEIN
```

Das Modell selbst ist freigabereif: Korrektheit, Liveness, CRN,
Reproduzierbarkeit, räumliche Konvergenz und Face Validity sind auf der
finalen Geometrie belegt, und der Zeithorizont steht auf einer sauberen,
neuen Datengrundlage.

Der Freeze scheitert nicht an der Simulation, sondern an der Strecke dahinter:
zwei Exportspalten meinen etwas anderes, als die Methodik verlangt, und es
gibt kein Skript, das die eingefrorene Matrix tatsächlich fährt. Würde die
Kampagne jetzt gestartet, liefe sie 2.000 statt 30.000 ZE, über fünf statt
zehn Seeds, ohne Messfenster und in den falschen Exporter.

**Empfohlener nächster Schritt** (klein, in dieser Reihenfolge):

1. `retrieval_rows` auf dieselbe Fensterdefinition umstellen wie
   `summarise_run` — eine Fensterquelle statt zwei. Regressionstest in
   `tests/test_measurement_window_export.py` ergänzen.
2. `steady_state_status` aus dem tatsächlich vorhandenen Feld `is_converged`
   bzw. aus der Offline-Regel befüllen, oder die drei toten Spalten aus
   `RUN_FIELDS` entfernen. Beides ist vertretbar; nicht vertretbar ist eine
   Spalte, die etwas verspricht und leer bleibt.
3. Einen Kampagnentreiber schreiben, der `pilot_run.build_config`,
   `T_measure_start = 20.000`, `T_final = 30.000`, die zehn Seeds und
   `ExperimentWriter` verbindet — und ihn mit `dry_check_matrix.py` gegen
   dieselbe Matrix prüfen.
4. Erst danach die Freigabe erneut stellen.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale
50-Run-Kampagne wurde **nicht** gestartet.

---

# Final Export & Campaign Pipeline Closeout (2026-08-24)

Der Simulationskern war zu Beginn dieser Phase validiert und der Zeithorizont
eingefroren. Offen waren drei Punkte, alle ausserhalb der Simulation:

```text
J-1  retrievals.csv markierte ein anderes Fenster als runs.csv
J-2  vier Steady-State-Spalten waren strukturell tot
J-3  es gab keinen ausfuehrbaren Kampagnentreiber
```

Alle drei sind geschlossen. In dieser Phase wurde **keine Zeile
Simulationslogik** angefasst.

---

## K.1 Ausgangszustand

```text
git rev-parse HEAD     1c127bec17ac7f8dcc56e37be46edc417a3f0c1a
git branch             working_sim
Python                 3.10.12
pytest                 9.1.1
Testsuite vorher       464 passed, 0 failed
```

### `tests/reservation_table.py` — geklärt, nicht angefasst

Die Datei ist im Index als gelöscht vorgemerkt. Herkunft: Ihr eigener
Dateikopf lautet `# tests/test_reservation_table.py` — sie ist eine
**fehlbenannte Kopie** von `tests/test_reservation_table.py`. Ohne
`test_`-Präfix hat pytest sie nie eingesammelt.

Inhaltlich ist sie die **überholte** Fassung: Sie enthält
`test_negative_x_allowed` und kodiert damit eine ältere Modellgeneration mit
Pickstations *links neben* dem Grid. Die gültige Fassung stellte das in Phase
2B (AUDIT-002) auf `test_negative_x_rejected` um, weil Roboter sonst real
durch nicht existierenden Raum fuhren. Die vorgemerkte Löschung entfernt also
einen toten, inhaltlich falschen Doppelgänger.

Wie gefordert nur dokumentiert. Nicht wiederhergestellt, nicht gelöscht.

---

## K.2 J-1 reproduziert

Vor dem Fix, finale Geometrie, Fenster `[200, 400]`:

```text
ABC+ABC   mode=time_window  runs.csv.measurement_retrievals=7  markiert=0  KONSISTENT=False
LR+NR     mode=time_window  runs.csv.measurement_retrievals=9  markiert=0  KONSISTENT=False
```

Über die volle 50er-Matrix: 50 von 50 inkonsistent.

---

## K.3 J-1 Root Cause

`summarise_run` filterte auf `[t_measure_start, t_final]`. `retrieval_rows`
markierte dagegen aus `steady["measurement_window"]` — dem **retrievalgezählten**
Fenster der verworfenen β-Stop-Regel aus `metrics/steady_state.py`.

Im Kampagnenpfad wurde `Metrics.get_convergence_analysis()` übergeben. Dieses
Objekt kennt den Schlüssel `measurement_window` überhaupt nicht, also war die
Menge leer und jede Zeile bekam `False`.

Der Fehler entstand, als der gemeinsame Zeitfenstermodus in `summarise_run`
ergänzt wurde, ohne `retrieval_rows` mitzuziehen. Zwei Fensterbegriffe in
einem Export, die auseinanderlaufen konnten, ohne dass es auffällt.

---

## K.4 Eine Fensterquelle

Neu in `experiments/run_export.py`:

```python
measurement_window(engine)        -> (modus, t_start, t_ende)
is_in_measurement_window(t, ...)  -> bool
retrievals_in_window(rows, ...)   -> list
```

Benutzt von `summarise_run` (Durchsatz, Service-KPIs, Retrievals je Station)
und von `retrieval_rows` (Markierung). `request_rows` braucht keine
Fensterlogik — `requests.csv` exportiert bewusst alle bedienten Requests als
Rohdaten; gefiltert wird in `summarise_run`. `requests.csv` bleibt damit
unverändert.

Die Grenzsemantik wurde **nicht** neu erfunden: beidseitig inklusive auf
`t_pickstation`, exakt wie `summarise_run` sie seit dem 2026-08-22 hatte.

Der dritte Modus `steady_state` ist entfallen. Er war die zweite,
unabhängige Fensterdefinition und damit genau die Fehlerquelle. Es gibt jetzt
zwei Modi: `time_window` (Kampagne) und `full_run` (Diagnose/Tests). Ein
stiller Rückfall auf die Legacy-Definition ist nicht mehr möglich, weil sie
im Export nicht mehr vorkommt.

---

## K.5 J-1 Regressionstests

In `tests/test_measurement_window_export.py` ergänzt (7 → 15 Tests):

| Test | prüft |
|---|---|
| `test_retrieval_flag_matches_the_run_level_window_count` | Zählergleichheit **je Run** |
| `test_every_marked_retrieval_lies_inside_the_window` | Markierung zeilenweise, nicht nur in der Summe |
| `test_no_silent_fallback_to_the_legacy_window` | die alte Regel liefert nachweislich ein anderes Fenster — und wird trotzdem nicht benutzt |
| `test_window_boundaries_are_inclusive_on_both_ends` | 199 / **200** / 500 / **800** / 801 |
| `test_boundary_count_matches_between_both_exports` | über alle fünf Grenzfälle zählen beide Seiten gleich |
| `test_without_a_window_the_whole_run_is_evaluated` | `full_run`, und `measurement_retrievals` = alle Retrievals |

Die Grenzfalltests laufen gegen einen minimalen Engine-Doppelgänger, damit
die Grenzen exakt getroffen werden statt zufällig.

---

## K.6 J-2 Analyse

`summarise_run` las vier Schlüssel, die es im Kampagnenpfad nicht gibt:

| Schlüssel | woher er stammt | im Kampagnenpfad |
|---|---|---|
| `status` | `metrics/steady_state.py::analyse_run` | fehlt |
| `convergence_retrievals` | dito | fehlt |
| `measurement_complete` | dito | fehlt |
| `measurement_window` | dito | fehlt |

`Metrics.get_convergence_analysis()` liefert genau vier andere Schlüssel:
`is_converged`, `convergence_time`, `stability_metrics`, `snapshots`.

Damit existierten **drei** verschiedene Konvergenzbegriffe im Projekt:

```text
A  metrics/steady_state.py      beta-Blockregel + retrievalgezaehltes Fenster   VERWORFEN
B  metrics/convergence_detector legacy ConvergenceDetector                      VERWORFEN
C  Offline-TVD auf abc_level_*  die EINGEFRORENE RQ4-Regel                      GUELTIG
```

---

## K.7 Entscheidung über die alten Steady-State-Felder

`is_converged` aus A oder B **nicht** als `steady_state_status = converged`
durchreichen: beide beruhen auf einem anderen Signal (β bzw. der
Legacy-Detektor) und einer anderen Regel. Eine Spalte mit dem Namen des
RQ4-Status, aber dem Inhalt einer verworfenen Regel, wäre schlimmer als eine
leere Spalte — sie wäre falsch, ohne es zu zeigen.

Deshalb entfernt aus `RUN_FIELDS`:

```text
steady_state_status
convergence_time
convergence_retrievals
measurement_complete
```

`metrics/steady_state.py` bleibt als Modul samt seinen Tests bestehen — es
ist methodische Vorgeschichte und in `experiment_setup.md` als solche
dokumentiert. Es speist nur den finalen Export nicht mehr.

---

## K.8 Finale RQ4-Exportsemantik

Neu in `RUN_FIELDS`:

| Feld | Bedeutung | immer gesetzt? |
|---|---|---|
| `rq4_status` | `converged` / `converged_then_rediverged` / `not_converged` | **ja** |
| `rq4_convergence_time_ZE` | Plateauzeitpunkt | nur bei `converged` |
| `rq4_convergence_retrievals` | physische Retrievals bis dahin | nur bei `converged` |
| `rq4_plateau_level` | mittlere TVD im Plateau | nur wenn ein Plateau gefunden wurde |
| `rq4_redivergence` | Plateau wieder verlassen? | **ja** |
| `rq4_blocks` | Zahl der ausgewerteten Blöcke | **ja** |

Die bedingten Felder sind **als bedingt dokumentiert** — im Schema, im
Docstring und in der Pflichtfeldliste der Matrixprüfung. Sie versprechen
nichts, was nicht berechnet wird.

`run_meta.json` enthält je Lauf die vollständige RQ4-Auswertung inklusive der
TVD-Folge und der vier Parameter, dazu die Fenstergrenzen. Jede
Statuszuweisung ist damit nachrechenbar, ohne den Lauf zu wiederholen.

---

## K.9 Offline-RQ4-Pipeline: Variante A, eine Implementierung

Gewählt wurde **Variante A**: Der Export wendet die eingefrorene Regel nach
Laufende auf die vollständige Zeitreihe ab t = 0 an und schreibt das Ergebnis
direkt in `runs.csv`. Kein manueller Nachbearbeitungsschritt, keine
vorläufige Datei.

Damit es dafür **keine zweite Implementierung** gibt, wurde die reine Regel
nach `metrics/rq4_plateau.py` gezogen:

```text
metrics/rq4_plateau.py                        die Regel (rein, kein RNG, kein Simulationszugriff)
  ├─ experiments/closeout/analyse_rq4_plateau.py   Kalibration  (Dateischale)
  └─ experiments/run_export.py                     Kampagne     (Engineschale)
```

`analyse_rq4_plateau.py` ist auf eine Dateischale geschrumpft; `plateau`,
`tvd` und `analyse_series` sind dort jetzt buchstäblich dieselben Objekte wie
im Modul — festgehalten durch
`test_only_one_implementation_of_the_rule_exists`.

**Nachweis, dass der Refactor nichts verändert hat:** Die 15
Kalibrationsläufe wurden neu ausgewertet und gegen
`results/rq4_calibration_final.json` verglichen.

```text
Abweichungen gegenueber der gespeicherten Kalibration: 0
```

Status, Konvergenzzeit, Plateauzeit, Plateauniveau, Re-Divergenz und das
gleitende Mittel danach stimmen in allen 15 Läufen exakt überein.
`analyse_measurement_window.py` liefert unverändert 15.100 / 4.400 / 19.500.

Zusätzlich geprüft, dass Datei- und Engineweg dasselbe rechnen: für einen
LR+NR/42-Lauf über 3.000 ZE sind Status, Zeiten und die komplette TVD-Folge
identisch — und die Folge `[0,01916, 0,01381]` stimmt mit den ersten beiden
Werten derselben Kombination aus der Kalibration überein.

Die Regel selbst ist unverändert: `R=50, K=2, delta=0,10, P=2,
Re-Divergenzfaktor 1,5`. Keine Grid-Search, keine neue Schwelle, keine
Neuberechnung der Horizonte — festgehalten in
`test_the_frozen_parameters_are_unchanged`.

---

## K.10 Kampagnentreiber

Neu: **`experiments/run_final_campaign.py`**. `run_experiments.py` bleibt
unangetastet, damit seine ursprüngliche Funktion als historischer
Vergleichslauf erkennbar bleibt.

```bash
python3 -m experiments.run_final_campaign --dry-run --output-dir results/final
python3 -m experiments.run_final_campaign --smoke   --output-dir /tmp/smoke
python3 -m experiments.run_final_campaign           --output-dir results/final
python3 -m experiments.run_final_campaign --output-dir results/final \
        --policy "ABC+ABC" --seed 7 --resume
```

### Eine Quelle für die Matrix

Neu: **`experiments/campaign_matrix.py`** — Policies, Seeds, Geometrie,
Horizonte und der Config-Builder stehen ausschliesslich dort.

```text
experiments/campaign_matrix.py
  ├─ experiments/run_final_campaign.py           die Kampagne
  ├─ experiments/closeout/dry_check_matrix.py    die Matrixpruefung
  └─ experiments/closeout/pilot_run.py           die Kalibration
```

`pilot_run.build_config` delegiert jetzt an `build_run_config`. Dass die
Konfiguration dadurch **feldweise unverändert** bleibt — und die vorhandene
Kalibration damit gültig — prüft
`test_calibration_builder_delegates_to_the_same_source` für alle fünf
Policies. Zusätzlich sind die CRN-Hashes byteidentisch zum Lauf vor dieser
Phase.

Ein Sentinel trennt „nicht übergeben" von einem ausdrücklichen `None`: Die
Piloten rechnen bewusst **ohne** Fenster. Ohne diese Unterscheidung hätten
sie stillschweigend das Kampagnenfenster gesetzt bekommen.

### Was der Treiber garantiert

| Anforderung | Umsetzung |
|---|---|
| 5 × 10 = 50 Runs | `final_matrix()`, geprüft durch `check_matrix` |
| deterministische Run-IDs | `ABC+ABC__seed7`, keine UUIDs |
| fester Horizont | 0 … 30.000, Fenster [20.000, 30.000], für alle gleich |
| keine alte Stop-Regel | `stop_on_convergence=False`, testgesichert |
| nur der finale Exporter | `run_export.ExperimentWriter`, nie `experiments/exporter.py` |
| dediziertes Ausgabeziel | `--output-dir`; Diagnosepfade (`closeout`, `pilot`, `calib`, `debug`) werden abgelehnt |
| kein stilles Überschreiben | nicht leeres Ziel ohne `--resume` → Exit 2 |
| Run-Level-Restart | `campaign_status.json` je Run: `completed` / `failed` / fehlt; `--resume` hängt an, ohne Kopfzeilen zu wiederholen |
| Fehlerbehandlung | Fehler in `runs.csv`, Statusdatei und Log; Run gilt als `failed`; **kein** Seed-Tausch, **kein** stilles Überspringen; Exit 1 |
| Logging | je Run `logs/<run_id>.log`; Konsole nur `START` / `DONE` / `ERROR` |
| keine Parallelisierung | bewusst sequentiell — `ExperimentWriter` schreibt gemeinsame CSVs; für Teilmengen gibt es `--policy` / `--seed` |

Kein neuer Fremdcode, keine neue Infrastruktur, kein Mid-Run-Pickle.

---

## K.11 Campaign Dry-Run

```text
Kombinationen : 50
Policies      : ABC+ABC, LR+NR, POPULARITY+POPULARITY, RR+RR, baseline_reference
Seeds         : 1, 2, 3, 4, 7, 11, 13, 42, 99, 123
eindeutige IDs: 50

alle 50 Konfigurationen entsprechen dem eingefrorenen Szenario
  Grid 20x30 H=8 bins=4320 robots=8 ps=2 cap=1
  Zipf=1.0 util=0.6 scheduler=EDF deadline_slack=240 pop_warmup=50
  Horizont 0 ... 30000, Fenster [20000, 30000]
  stop_on_convergence=False

Exporter      : experiments.run_export.ExperimentWriter
Ausgabeziel   : results/final          Ziel belegt: False

VERDICT: CAMPAIGN DRY RUN PASS
```

Der Dry-Run rechnet nichts und schreibt nichts. Er prüft jede der 50
Konfigurationen einzeln gegen `FINAL_SETUP` und rechnet die Policy-Zuordnung
unabhängig nach, statt sich auf Defaults zu verlassen.

Gegenproben, alle bestanden:

```text
Ziel in einem Diagnosepfad             -> CAMPAIGN DRY RUN FAIL, Exit 1
nicht leeres Ziel ohne --resume        -> Exit 2, Datei unveraendert
Smoke in ein finales Ergebnisverzeichnis -> Exit 2
--resume bei vollstaendiger Matrix     -> „nichts zu tun", nichts gerechnet
```

---

## K.12 End-to-End-Smoke-Test

Über den echten Kampagnenpfad, alle fünf Policies, ein Seed, kurzer Horizont
(600 ZE, Fenster [300, 600]) — technisch getrennte Konstanten, die nie die
finalen Parameter überschreiben können.

```text
[SMOKE] Horizont 600 ZE, Fenster [300, 600] — NICHT die finalen Parameter
[DONE ] baseline_reference__seed42     t_end=600 retr=18 rq4=not_converged
[DONE ] RR+RR__seed42                  t_end=600 retr=15 rq4=not_converged
[DONE ] LR+NR__seed42                  t_end=600 retr=30 rq4=not_converged
[DONE ] ABC+ABC__seed42                t_end=600 retr=18 rq4=not_converged
[DONE ] POPULARITY+POPULARITY__seed42  t_end=600 retr=18 rq4=not_converged
[OK] 5 Run(s) abgeschlossen                                          Exit 0
```

`not_converged` ist hier die **richtige** Antwort: bei 15–30 Retrievals kommt
kein einziger Block von R = 50 zustande. Die anderen beiden Zustände sind
über deterministische Zeitreihen getestet (K.14).

Geprüfte Kette: Runner → SimulationEngine → run_export → ExperimentWriter →
CSV/JSON.

---

## K.13 Ausgabedateien und Schema

| Datei | Zeilen (Smoke) | Kopf == Schema |
|---|---|---|
| `runs.csv` | 5 | `RUN_FIELDS` ✓ |
| `retrievals.csv` | 99 | `RETRIEVAL_FIELDS` ✓ |
| `requests.csv` | 187 | `REQUEST_FIELDS` ✓ |
| `distribution.csv` | 35 | ✓ |
| `run_meta.json` | 5 | Config, RNG-Streams, `rq4`, `measurement_window` |
| `logs/<run_id>.log` | 5 | je Run getrennt |

```text
run_id                          mode         Fenster     mw  flag  KONS  rq4
baseline_reference__seed42      time_window  [300,600]    7     7  True  not_converged
RR+RR__seed42                   time_window  [300,600]    7     7  True  not_converged
LR+NR__seed42                   time_window  [300,600]   17    17  True  not_converged
ABC+ABC__seed42                 time_window  [300,600]    8     8  True  not_converged
POPULARITY+POPULARITY__seed42   time_window  [300,600]    7     7  True  not_converged
```

Keine unbekannten Felder, keine doppelten Run-IDs, kein unerwartet leeres
Pflichtfeld.

Nach einer Fortsetzung (`--resume`, zwei Policies zuerst, dann die
restlichen drei): 5 Runs, 0 wiederholte Kopfzeilen in allen vier CSVs, 5
Metadaten-Einträge, Fensterkonsistenz für alle 5.

---

## K.14 RQ4-Postprocessing-Test

`tests/test_rq4_export_contract.py` (13 Tests). Die drei Zustände werden über
synthetisch konstruierte TVD-Folgen erzeugt — zwei Komponenten, um die Masse
`d` verschoben, ergibt exakt TVD `d`:

| Folge | erwartet | geprüft |
|---|---|---|
| durchgehend halbierend | `not_converged` | keine Konvergenzzeit |
| Abfall, dann flach bei 0,02 | `converged` | Plateauniveau 0,02, keine Re-Divergenz |
| Abfall, flach, dann Sprung auf 0,20 | `converged_then_rediverged` | `redivergence=True`, **keine** Konvergenzzeit |

Weiter geprüft: die vier toten Spalten existieren nicht mehr; `rq4_status`
ist nie leer; ein vom Treiber übergebenes Ergebnis wird unverändert
übernommen; `is_converged` der Legacy-Detektoren wird nicht als RQ4-Status
durchgereicht; die Regel existiert nur einmal; die vier Parameter sind
unverändert; das Postprocessing zieht keine Zufallszahl.

---

## K.15 `dry_check_matrix.py` nach dem Fix

Alle 5 Policies × 10 Seeds, frisch gerechnet:

```text
Kombinationen           : 50
Exceptions              : 0
Zeilen mit Luecken      : 0
unbekannte Felder       : 0
verwaiste Roboter       : 0
falscher Fenstermodus   : 0
Fenster inkonsistent    : 0
CRN-Bruch (Seed->Strom) : 0
Seed-Kollision          : False

VERDICT: MATRIX DRY-CHECK PASS
```

Die Pflichtfeldliste wurde **nicht** entleert, um grün zu werden:
`rq4_status` ist neu darin. Nur die ausdrücklich bedingten RQ4-Felder stehen
nicht drin, mit Begründung im Code.

Die Prüfung bezieht Policies, Seeds und den Config-Builder jetzt aus
`campaign_matrix` — sie kann gar nicht mehr etwas anderes prüfen, als die
Kampagne rechnet (`test_driver_and_matrix_check_share_one_definition`).

---

## K.16 CRN

```text
10 Seeds x 5 Konfigurationen
gleicher Seed -> identisches Layout, identische Requests, Ankunftszeiten,
                 Deadlines und Servicezeiten ueber alle Policies
eligibility_violations = 0

VERDICT: CRN INTAKT
```

Alle Hashes sind **byteidentisch** zum Lauf vor dieser Phase (z. B. Seed 1:
`layout=496db3e75013fcd9`, `requests=e4a0ad4e2b096502`). Export, Runner und
RQ4-Postprocessing verbrauchen keinen Simulations-RNG; zwei Tests halten das
explizit fest.

---

## K.17 Testsuite

```text
243 + 260 = 503 passed, 0 failed        (vorher 464)
```

Neu: 20 (`test_campaign_matrix.py`), 13 (`test_rq4_export_contract.py`),
8 zusätzliche Fenstertests. Keine bestehende Assertion abgeschwächt.

Angepasst wurden nur Aufrufstellen, deren Signatur sich geändert hat:
`summarise_run(..., steady)` → `summarise_run(..., rq4=None)`,
`retrieval_rows(..., steady)` → `retrieval_rows(...)`. Ein alter positioneller
Aufruf schlägt jetzt laut fehl statt still das Falsche zu tun.

`test_without_a_window_the_previous_behaviour_is_kept` wurde zu
`test_without_a_window_the_whole_run_is_evaluated`: die Zusicherung
`measurement_mode in ("steady_state", "full_run")` ist zu
`== "full_run"` **verschärft** worden, weil der dritte Modus nicht mehr
existiert.

`tests/test_simulation_visual.py` bleibt nicht ausführbar — `flask` fehlt in
der Sandbox. Umgebungsgrenze, keine Regression.

---

## K.18 Wurde Simulationscode verändert?

**Nein.** Geändert wurden ausschliesslich:

```text
metrics/rq4_plateau.py                       NEU  reines Postprocessing
experiments/campaign_matrix.py               NEU  Plan und Config-Builder
experiments/run_final_campaign.py            NEU  Kampagnentreiber
experiments/run_export.py                         Export
experiments/closeout/analyse_rq4_plateau.py       Diagnose
experiments/closeout/pilot_run.py                 Diagnose
experiments/closeout/dry_check_matrix.py          Diagnose
tests/*                                           Tests
```

Kein Scheduler, kein RobotTask, keine Strategie, kein Selector, kein
TrafficManager, kein PortExitGuard, kein RequestGenerator, keine RNG-Streams,
keine Policy-Scores, keine Deadline-Semantik.

Drei unabhängige Belege: die Zeitstempel im Arbeitsbaum, die byteidentischen
CRN-Hashes und die null Abweichungen der neu ausgewerteten Kalibration.

**Die 15×30k-Kalibration bleibt gültig und wurde nicht wiederholt.**

---

## K.19 Aktualisierte Limitationen

| # | Limitation |
|---|---|
| L-32 (**erledigt**) | `in_measurement_window` kommt aus derselben Quelle wie das Run-Level-Fenster; Zählergleichheit je Run testgesichert. |
| L-33 (**erledigt**) | Die toten Steady-State-Spalten sind entfernt und durch die Felder der eingefrorenen RQ4-Regel ersetzt. |
| L-34 (**erledigt**) | `experiments/run_final_campaign.py` existiert, Dry-Run und Smoke bestanden. |
| L-35 (**bleibt**) | `LR+NR / Seed 7` ist ein RQ4-Grenzfall: Plateau 10.800 ZE, Niveau 0,00701, gleitendes Mittel danach 0,01083 gegen Schwelle 0,01052 — Überschreitung um 3 %. Als `converged_then_rediverged` berichtet. **Die Schwelle wurde nicht angepasst.** |
| L-31 (**bleibt**) | `T_measure_start` beruht auf drei kalibrierten Seeds je Policy; sieben der zehn finalen Seeds sind ungetestet. |
| L-36 (**neu**) | Der Kampagnentreiber ist bewusst sequentiell. `ExperimentWriter` schreibt gemeinsame CSV-Dateien und ist nicht nebenläufigkeitssicher. Parallelität ist nur über getrennte `--output-dir` je Teilmenge zu erreichen, mit anschliessendem Zusammenführen. Geschätzte Laufzeit sequentiell: rund 30 CPU-Stunden. |
| L-37 (**neu**) | `metrics/steady_state.py` und `metrics/convergence_detector.py` bleiben im Code und in den Tests, speisen aber keinen finalen Export mehr. Sie sind methodische Vorgeschichte; wer sie liest, darf sie nicht für die RQ4-Regel halten. |
| L-30 (**bleibt**) | `pickstation_utilisation_ps0/ps1` ist kumulativ über den ganzen Lauf, nicht fensterbezogen. Nur diagnostisch. |
| L-27, L-28, L-14 bis L-26 | unverändert. |

---

## K.20 Freeze-Gate

### Simulation

| Kriterium | Status |
|---|---|
| `SIMULATION_VALIDATED` | **JA** (Abschnitt J) |
| in dieser Phase keine Simulationslogik verändert | **erfüllt** — drei unabhängige Belege |
| Kalibration weiterhin gültig | **erfüllt** — 0 Abweichungen, CRN byteidentisch |

### Horizont

| Kriterium | Status |
|---|---|
| `EXPERIMENT_HORIZON_FROZEN` | **JA** |
| `T_measure_start` = 20.000, `T_final` = 30.000 | **erfüllt**, unverändert |

### Export

| Kriterium | Status |
|---|---|
| `retrievals.csv` und `runs.csv` nutzen exakt dasselbe Fenster | **erfüllt** — eine Quelle |
| Fenster-Counter je Run exakt gleich | **erfüllt** — 50/50 im Dry-Check, testgesichert |
| keine toten Pflichtfelder | **erfüllt** |
| keine semantisch falschen RQ4-Felder | **erfüllt** |
| RQ4-Offlineworkflow eindeutig und reproduzierbar | **erfüllt** — eine Implementierung, Variante A |

### Runner

| Kriterium | Status |
|---|---|
| ausführbarer Kampagnentreiber | **erfüllt** |
| 5 × 10-Matrix, 50 eindeutige Runs | **erfüllt** |
| richtige Policies, Seeds, Horizont, Exporter | **erfüllt** |
| dediziertes Ausgabeziel | **erfüllt** — Diagnosepfade werden abgelehnt |
| keine alte Stop-Regel | **erfüllt** |

### Validation

| Kriterium | Status |
|---|---|
| `--dry-run` | **PASS** |
| End-to-End-Smoke | **PASS** |
| `dry_check_matrix` | **MATRIX DRY-CHECK PASS** (50/50) |
| volle Testsuite | **503 passed, 0 failed** |
| CRN | **INTAKT** |

### Reproducibility

| Kriterium | Status |
|---|---|
| kein RNG-Verbrauch durch Export/Runner/Postprocessing | **erfüllt** — zwei Tests |
| keine Duplikate | **erfüllt** — 50 eindeutige Run-IDs, Resume ohne Doppelzeilen |
| keine stillen Seed-Ersetzungen | **erfüllt** — Fehler beenden mit Exit 1 |
| keine stillen Output-Überschreibungen | **erfüllt** — Exit 2 |

### Urteil

```text
SIMULATION_VALIDATED        = JA
EXPERIMENT_HORIZON_FROZEN   = JA
EXPORT_PIPELINE_VALIDATED   = JA
CAMPAIGN_DRIVER_VALIDATED   = JA
FINAL_EXPERIMENT_FROZEN     = JA
```

Die Kampagne ist technisch und methodisch freigegeben.

Der Startbefehl lautet:

```bash
python3 -m experiments.run_final_campaign --output-dir results/final
```

Er wurde **nicht** ausgeführt. Die 50 finalen Runs sind nicht gestartet.

Es wurden **keine Git-Commits oder Pushes** ausgeführt.
