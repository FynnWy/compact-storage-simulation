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
