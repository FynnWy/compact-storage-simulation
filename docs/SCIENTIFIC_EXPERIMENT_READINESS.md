# Scientific Experiment Readiness

**Letzte Vorbereitungsphase vor der finalen Experimentkampagne**

**Datum:** 2026-08-21
**Baseline-Commit:** `a44393e` („Add policy-neutral RNG streams and
request-bound service times", Branch `working_sim`)
**Python:** 3.10.12 (Auditumgebung), pytest 9.1.1
**Testsuite:** vorher 363 passed → nachher **383 passed**

Dieses Dokument ist als Grundlage für die Methodik- und
Experimentdesign-Kapitel beider Masterarbeiten gedacht.

---

# 1. Forschungsziel und Scope

Die Simulation ist eine experimentelle Forschungsplattform für den Vergleich
von Betriebsstrategien eines AutoStore-ähnlichen RCS/R-Systems unter
identischen Bedingungen. Die Ergebnisse verteilen sich auf zwei Arbeiten:

| Arbeit | Policies |
|---|---|
| **A** | AutoStore-like Baseline, RR+RR, ABC+ABC |
| **B** | AutoStore-like Baseline, LR+NR, POPULARITY+POPULARITY |

Beide nutzen dieselbe Infrastruktur, dieselben Seeds, dieselben exogenen
Workloads, dieselben Metriken und dasselbe Setup.

## 1.1 Modellgrenze: eine Bin = ein Nachfrageobjekt

Im Modell ist eine Bin unmittelbar das nachgefragte Objekt. Es gibt **kein**
Konzept mehrerer austauschbarer Loads desselben Produkts, aus denen bei einem
Request ausgewählt werden könnte.

Lehmann & de Koster untersuchen zusätzlich genau diese Dimension
(*retrieval load selection*: `Random retrieval` vs. `Load with the fewest
reshuffles`) und lassen `a_j` Loads je Produkt der Klasse `j` zu. Diese
Dimension bilden wir **bewusst nicht** ab.

**Konsequenzen für die Interpretation:**

* Ergebnisse zur LFR-Strategie aus Lehmann sind auf unser Modell nicht
  übertragbar.
* Der „honeycombing"-Effekt (gleiche Produkte in einem Kanal, LIFO-Zugriff)
  existiert bei uns nicht.
* Unser Fall entspricht Lehmanns Sonderfall `a_j = 1` mit
  `Random retrieval` – dort ist die Auswahl trivial.

Das Datenmodell wurde dafür **nicht** erweitert.

## 1.2 Weitere bewusste Abstraktionen gegenüber realem AutoStore

| AutoStore (Meller 2023) | Unser Modell |
|---|---|
| Zwei Stufen: Bin wird „prepared", in ein Hole gelegt und wartet auf die Zuordnung zu einer Portqueue | Eine Stufe: Target-Bin geht direkt zur Pickstation |
| Mehrere Roboter können gemeinsam eine Bin ausgraben | Ein Roboter je Task |
| Proprietäre Controller-Algorithmen für Routing, Konfliktauflösung, Ladezustand | Eigene Traffic-/Scheduling-Logik, keine Ladezustände, keine Charger |
| ~25 % der Stacks halten die oberste Zelle frei („holes") | Kein reserviertes Hole-Kontingent; freie Top-Zellen ergeben sich aus dem Füllgrad (gemessen 56 % der Stacks mit freier Top-Zelle, mittlere Höhe 7,21 von 8) |
| Bins/Stunde, Sekunden | Abstrakte, normierte Zeiteinheiten (ZE) |
| Roboterorientierung (Nord-/Südträger), Overhang | Nicht modelliert |

---

# 2. Die vier Forschungsfragen von Meller (2023)

Wortlaut aus Abschnitt V des Papers, jeweils mit unserem Mapping.

## RQ1 — Restacking bins in created holes

> „the AutoStore controller returns unneeded bins from the preparation process
> in exactly the same order as they were taken out. In some situations, with
> some information available on future activity, this may not be optimal. In
> addition, there may be multiple stacks that are involved in the stacking
> process at any given time. So, it's not only an issue of in which order to
> return the bins, but also to which hole?"

**Mapping.** Zwei Freiheitsgrade unserer Konfiguration:

| Teilfrage | Steuergröße |
|---|---|
| In welcher Reihenfolge zurücklegen? | `reordering_strategy` (LOFI / ABC / POPULARITY) |
| Überhaupt zurücklegen? | `return_blocking_bins` (True / False) |
| In welches Hole? | `RelocationSelection` (zufällig bei RR+RR, kostenbasiert sonst) |

**Benötigte Daten:** `blocking_bins` je Retrieval, P(β = s), mittleres β,
primäre KPI je Policy.

**Einschränkung:** Die von Meller angesprochene Nutzung von Wissen über
zukünftige Aktivität bilden wir **nicht** ab — POPULARITY nutzt ausschließlich
beobachtete Vergangenheit (kein Look-ahead, testgesichert).

## RQ2 — Returning bins to the top of a stack after the picking process

> „Of the many holes at the top layer of the grid, which one is the correct
> location for the bin that just completed its picking process?"

**Mapping.** Direkt `placement_strategy`: RANDOM (AutoStore-Referenz),
NEAREST (strukturerhaltend), ABC (klassenbasiert), POPULARITY (dynamisch).

**Benötigte Daten:** primäre KPI, mittleres β, Level-Verteilung, räumliche
Verteilungs-Snapshots.

## RQ3 — The bin distribution realized in a dynamic system

> „if every SKU were allocated one bin in an AutoStore and the SKU activity
> followed an 80/20 distribution, then AutoStore advocates that 80% of the
> bins would be retrieved from the top-20% of the levels in the AutoStore.
> But given the dynamic nature of bin retrievals and returning to created
> holes, is this the case (even with a stable SKU ABC profile)?"

Dies ist die quantitativ prüfbarste Frage. Sie verlangt je Retrieval den
**Level vor dem Zugriff** — nachträglich nicht rekonstruierbar.

**Benötigte Daten:** die neue Retrieval-Tabelle (Abschnitt 5.3).

**Erster Messwert** (finales Setup, Seed 42, Baseline, Zipf 1.0):
77,4 % der Retrievals stammen aus den obersten 20 % der Ebenen des jeweiligen
Stacks. Mellers Behauptung lautet 80 %. Die Frage ist also mit unseren Daten
beantwortbar und die Größenordnung plausibel.

## RQ4 — Reaching a steady state bin distribution

> „AutoStore grids are typically loaded in an arbitrary fashion such that
> [...] fast-moving SKUs may be found at the bottom of the grid [...] How long
> will it take for the grid to arrive at a steady state bin distribution under
> typical operating conditions?"

**Benötigte Daten:** Konvergenzzeitpunkt in ZE **und** in physischen
Retrievals; Verlauf von β und der räumlichen Verteilung.

**Erster Messwert** (Baseline, Seed 42): β fällt von 1,36 im ersten Block auf
0,0 und bleibt dort; Konvergenz bei t = 1553 ZE nach 100 physischen
Retrievals. Der Effekt ist deutlich messbar.

---

# 3. Primäre KPI

## 3.1 Literaturanker

Lehmann & de Koster definieren die Durchsatzkapazität (Gleichung 1):

```
TP = 3600 · PS · K / (t_rack + t_wait + t_pick)          [retrieved loads per hour]
```

Einheit ausdrücklich **abgerufene Loads pro Stunde**, nicht Aufträge. Ein
Command Cycle ist genau ein Retrieval mitsamt seiner Reshuffles und der
anschließenden Einlagerung.

Meller misst durchgehend in **bins/hour** („the bins/hour throughput the
system must achieve") und Roboterproduktivität in **bins/robot/hour**
(29 bei 16 Ebenen, 36 bei 8 Ebenen).

## 3.2 Was `throughput` bisher zählte

`Metrics.throughput()` gab `len(self._arrival_to_full_completion)` zurück –
die Zahl **vollständig abgeschlossener Requests**, als absolute Zahl ohne
Zeitbezug.

## 3.3 Warum das nicht dieselbe Größe ist: Batching

Mehrere Requests auf dieselbe Bin werden zu einem physischen Retrieval
gebündelt. Gemessen im finalen Setup:

| Zipf θ | Requests je physischem Retrieval | größter beobachteter Batch |
|---|---|---|
| 1,5 | 2,14 | 22 |
| 1,0 | 1,14 | 6 |

Der Faktor hängt von der Nachfragekonzentration ab und ist damit
konfigurations- und policyabhängig. Eine request-basierte Größe misst also
teilweise die Nachfragestruktur statt der Systemleistung.

## 3.4 Entscheidung

> **Primäre KPI: `bin_throughput` = physische Target-Retrievals je Zeiteinheit**
> im Measurement Window.

Begründung:

1. entspricht der Einheit beider Paper (retrieved loads / bins pro Zeit),
2. misst physische Systemarbeit, nicht Nachfragestruktur,
3. ein Retrieval ist genau ein Command Cycle im Sinne von Lehmann,
4. Reshuffles, Fahrwege und Pickstation-Wartezeit erklären sie direkt.

`request_throughput` bleibt als **sekundäre operative KPI** erhalten. Es wird
**keine** zusammengesetzte Score-Metrik gebildet.

---

# 4. Finaler Metriksatz

Ein Wert ist nur dann im finalen Datensatz, wenn er die primäre KPI ist, sie
erklärt, eine RQ beantwortet oder einen Lauf validiert.

## 4.1 Primäre KPI

| Metrik | Definition | Einheit | Ebene | Erfassung | Zweck |
|---|---|---|---|---|---|
| `bin_throughput` | physische Target-Retrievals / Dauer des Measurement Window | Retrievals je ZE | System | aus `retrievals.csv` | primäre KPI |

## 4.2 Erklärende KPIs

| Metrik | Definition | Einheit | Ebene | RQ / Zweck |
|---|---|---|---|---|
| `mean_blocking_bins` | mittleres β je Retrieval | Bins | Retrieval | RQ1; Haupttreiber der Zykluszeit |
| `p_beta_zero` | Anteil Retrievals ohne Reshuffle | Anteil | Retrieval | RQ1; Verteilung P(β = s) aus Rohdaten |
| `mean_levels_from_top` | mittlere Ebenen über der Target-Bin | Ebenen | Retrieval | RQ3 |
| `share_retrievals_top20pct` | Anteil Retrievals aus den obersten 20 % der Ebenen | Anteil | Retrieval | **RQ3, Mellers 80/20-Behauptung** |
| `mean_dig_duration` | Zeit vom Beginn des Diggings bis zur Ankunft an der Pickstation | ZE | Retrieval | Zykluszeit-Proxy (Lehmanns `t_rack`) |
| `mean_batch_size` | Requests je physischem Retrieval | – | Retrieval | Abgrenzung Request- vs. Bin-Throughput |
| `pickstation_utilisation_mean` | mittlere Auslastung beider Stationen | Anteil | Pickstation | erklärt `t_wait`/`t_pick` |
| `request_throughput` | abgeschlossene Requests je ZE | Requests je ZE | System | sekundäre operative KPI |

## 4.3 Rohdaten

| Datei | Granularität | Zweck |
|---|---|---|
| `retrievals.csv` | ein physisches Retrieval | RQ1 (P(β = s)), RQ3 (Level-Verteilung), je ABC-Klasse aufschlüsselbar |
| `distribution.csv` | ein Snapshot je 100 ZE | RQ3 (räumliche Verteilung über Zeit), RQ4 |
| `runs.csv` | ein Lauf | KPIs, Steady State, Diagnose |
| `run_meta.json` | ein Lauf | vollständige Konfiguration, Reproduzierbarkeit |

## 4.4 Bewusst NICHT im finalen Satz

| Größe | Begründung |
|---|---|
| `deadline_miss_rate`, `average_tardiness`, `throughput_on_time` | Das System läuft im finalen Setup dauerhaft gesättigt (Abschnitt 6.4). Die Warteschlange wächst unbegrenzt, jede Terminmetrik misst dann nur noch die Überlast, nicht die Policy. |
| `average_arrival_to_full_completion` | Aus demselben Grund von der Backlog-Länge dominiert. |
| Vollständiger ROBOT_MOVE-Log | Rund 700 Bewegungsereignisse je Retrieval, ohne zusätzlichen Erklärungswert für die vier RQs. |
| `bin_distribution_entropy`, `abc_zone_adherence`, `popularity_depth_correlation` | Bleiben in `distribution.csv` erhalten, sind aber keine berichteten KPIs – sonst Metrics Sprawl. |
| Robot Travel als eigene KPI | In `mean_dig_duration` und `bin_throughput` bereits enthalten; eine separate Wegstrecke erklärt nichts zusätzlich. |

## 4.5 Diagnosegrößen (Laufvalidierung, keine Ergebnisse)

`move_stall_recoveries`, `move_recovery_unresolved`, `error`,
`steady_state_status`. Ein Lauf mit `unresolved > 0` oder `error != None`
gehört nicht in die Auswertung.

---

# 5. Was vorher schon korrekt war und was geändert wurde

## 5.1 Bereits korrekt (unverändert gelassen)

* **Digging-Depth-Erfassung.** Gegen die Grundwahrheit geprüft: gemeldeter
  Mittelwert 0,84 gegenüber tatsächlich 0,84 über 63 Retrievals; Anzahl der
  erfassten Retrievals stimmt exakt.
* **Verteilungs-Snapshots.** `DistributionMetrics` liefert Level-Verteilung
  nach ABC-Klasse, `hot_bins_top_ratio`, Stackhöhenverteilung und
  Popularitäts-Tiefen-Korrelation.
* **Pickstation-Zuordnung.** Minimale Manhattan-Distanz, danach
  `effective_load`, danach stabiler Index — siehe 5.5.
* **Kein Look-ahead.** Weder Strategien noch Scheduler lesen
  `future_request_queue` oder `request.service_time` (testgesichert).
* **Reproduzierbarkeit / CRN** aus Phase 4 unverändert.

## 5.2 Geändert: Retrieval-Tabelle (RQ3 war nicht beantwortbar)

**Problem.** Vorhanden war nur `request_digging_depths` – eine flache Liste
von Zahlen, ohne Level, Stackhöhe, Klasse oder Zeit. Der Level einer Bin vor
dem Zugriff ist nachträglich nicht rekonstruierbar; RQ3 war damit
unbeantwortbar.

**Fix.** `RobotTask` hält `retrieval_level`, `retrieval_stack_height` und
`retrieval_start_time`, gesetzt in `TopAccessStrategy`, sobald der Zielstack
erstmals bestimmt wird — der einzige Zeitpunkt, an dem der Stack garantiert
unberührt ist. `EventHandler._record_retrieval_row` schreibt daraus eine
Zeile, sobald die Bin an der Pickstation ankommt.

**Felder:** `t_pickstation`, `request_id`, `bin_id`, `abc_class`,
`access_count_before`, `level`, `stack_height`, `levels_from_top`,
`blocking_bins`, `blockers_returned`, `batch_size`, `t_retrieval_start`,
`dig_duration`, `pickstation`, `robot_id`.

**Zeitpunkt korrigiert.** Zuerst wurde die Zeile beim Drop geschrieben – dort
ist `batched_requests` noch leer und `batch_size` konstant 1. Sie entsteht
jetzt nach `_attach_batched_requests_to_task`.

## 5.3 Geändert: gemeinsame Definition zulässiger Lagerplätze

**Problem.** Bis Phase 3B durfte ausschließlich `RANDOM` in die
Port-Pufferzone platzieren; NEAREST/ABC/POPULARITY schlossen sie aus. Der zur
Laufzeit erreichbare Zustandsraum war policyabhängig — 598 gegenüber 592
Stacks. Räumliche Metriken wären auf unterschiedlichen Trägermengen gemessen
worden, und die betroffenen Zellen liegen genau dort, wo NEAREST/ABC/
POPULARITY bevorzugt platzieren würden.

**Fix.** `_select_random_stack` nutzt jetzt dieselbe Kandidatenmenge
(`_get_eligible_stacks`) wie alle anderen Strategien.

**Bewusst nicht geändert:** die Initialverteilung. Sie belegt weiterhin alle
Storage-Positionen einschließlich Pufferzone. Das ist keine Policy-Asymmetrie,
sondern ein für alle Policies **identischer** Startzustand; die Pufferzonen-Bins
laufen unter jeder Policy gleichermaßen aus. Auf sehr kleinen Testgrids würde
ein initialer Ausschluss zudem den Großteil des Grids verbrauchen.

## 5.4 Geändert: Roboterzahl und Binlayout entkoppelt

**Problem.** Roboter-Startpositionen und Bin-Verteilung zogen aus demselben
`initialization`-Strom. Ein Lauf mit 6 statt 8 Robotern verbrauchte zwei
Ziehungen weniger und erzeugte dadurch ein **anderes Lager**. Jede
Parameterstudie über `num_robots` — wie die in Abschnitt 6.3 — wäre
konfundiert gewesen.

**Fix.** Neuer Strom `robots`, hinten an `STREAM_NAMES` angehängt.
`SeedSequence.spawn(6)` liefert dieselben ersten fünf Kinder wie `spawn(5)`,
das Anhängen ist für die bestehenden Ströme also unschädlich. Das initiale
Binlayout hängt jetzt allein am Master-Seed.

## 5.5 Bewertet, aber nicht geändert: Pickstation-Tie-Break

Die Regel lautet `(Distanz, effective_load, stabiler Index)`. Der
lastabhängige Term greift nur bei **exaktem** Distanzgleichstand.

Im finalen Layout ist ein solcher Gleichstand **geometrisch unmöglich**:
Stationen liegen bei (0, 15) und (19, 15); Gleichstand verlangte
|x − 0| = |19 − x|, also x = 9,5. Empirisch bestätigt: 0 Gleichstände bei
54 Stationsauswahlen in einem 1000-ZE-Lauf.

**Entscheidung.** Die Regel reduziert sich im finalen Setup exakt auf
„minimale Manhattan-Distanz, bei Gleichstand stabiler Stationsindex" — also
genau die neutrale Semantik. Ein Codeeingriff würde nichts ändern und nur
Risiko erzeugen. Stattdessen sichert
`test_pickstation_choice_is_distance_only_in_the_final_layout` diese
Eigenschaft ab: Wird die Gridbreite oder Stationsanordnung je geändert,
schlägt der Test an und der lastabhängige Mechanismus muss neu bewertet
werden.

## 5.6 Präzisiert: Einheit des POPULARITY-Warmups

Der Warmup zählt `sum(bin.access_count)`, und `access_count` steigt genau
einmal je **physischem Retrieval** — nicht je Request. Bei Batching ist das
ein Unterschied. Das Feld heißt jetzt `popularity_warmup_retrievals`
(Altname bleibt als Alias).

## 5.7 Bestätigt: Ownership-Freigabe im Produktionspfad

`TopAccessStrategy` erhält die `ActiveQueue` in `SimulationEngine` immer
injiziert; testgesichert
(`test_ownership_release_is_wired_in_the_production_engine`).

---

# 6. AutoStore-like Baseline

## 6.1 Was Meller beschreibt

* Blocking Bins werden temporär auf beliebige Stacks gelegt und **immer** in
  denselben Stack zurückgebracht, „only one level deeper" — die relative
  Reihenfolge bleibt erhalten.
* Das Zurückbringen muss **sofort** erfolgen, weil es nur begrenzt Holes gibt.
* Die Target-Bin geht nach dem Picking „to any open hole in the grid
  (i.e., there is no attempt to return the bin to the stack it was retrieved
  from)". Daraus entsteht **Natural Slotting**.

Lehmann nennt dieselbe Kombination `CIRS-Random` und bezeichnet sie
ausdrücklich als „the current AutoStore strategy": Storage Assignment CIRS
(zufällige Platzierung, aber klassenabhängige Zugriffsfrequenz),
Reshuffle-Strategie **BBO** mit **LOFI**-Reihenfolge.

## 6.2 Unsere Implementierung

| Merkmal | Meller / Lehmann | Unsere `baseline_reference` | Bewertung |
|---|---|---|---|
| Blocker zurücklegen | ja, sofort | `return_blocking_bins = True` | PASS |
| Reihenfolge | gleiche relative Ordnung (LOFI) | `reordering_strategy = "LOFI"` = `reversed(blockers)` | PASS |
| Ziel des Blocker-Returns | Originalstack | `relocation["from_stack"]` = Originalstack | PASS |
| Temporäre Ablage | „top of a storage stack" | kostenbasiert (Manhattan + Nachbarbonus) auf zulässige Stacks | PASS mit Abweichung: AutoStore wählt nach eigenen Kriterien, wir fahrwegminimal |
| Target-Bin nach Picking | beliebiges offenes Hole, kein Bezug zum Ursprung | `placement_strategy = "RANDOM"` | PASS |
| Natural Slotting | erwartet | gemessen: 77,4 % der Retrievals aus den obersten 20 % der Ebenen; β fällt von 1,36 auf 0 | **PASS, empirisch bestätigt** |
| Klasseninformation | CIRS: implizit über Zugriffsfrequenz | Zipf-Nachfrage, ABC-Klassen statisch nach `bin_id` | PASS |
| Zwei Pickstations | Lehmann: 1; Meller: mehrere | 2 | Abweichung, bewusst |

**Urteil: PASS.** Unsere `baseline_reference` (LOFI + RANDOM +
`return_blocking_bins = True`) entspricht der von Meller beschriebenen und
von Lehmann als `CIRS-Random` formalisierten AutoStore-Strategie.

## 6.3 Wichtig: RR+RR ist NICHT die AutoStore-Baseline

RR+RR setzt `return_blocking_bins = False`. Meller schreibt ausdrücklich, dass
das Zurückbringen sofort erfolgen **muss**. RR+RR ist damit eine
kontrafaktische Policy — sie entspricht am ehesten Lehmanns
`Random reshuffle` („No, load stays in the new location").

Das ist als Vergleichsstrategie legitim, aber:

> Baseline und RR+RR unterscheiden sich in **zwei** Dimensionen gleichzeitig
> (Ordered Return **und** zufällige Blocker-Ablage). Eine Aussage der Form
> „Komponente X verursacht Y % Unterschied" ist zwischen diesen beiden nicht
> zulässig.

Zusätzliche Ablationsstrategien wurden **nicht** eingeführt.

## 6.4 Unterscheidungsdimensionen aller fünf Konfigurationen

| Konfiguration | reordering | placement | `return_blocking_bins` | Blocker-Ablage |
|---|---|---|---|---|
| `baseline_reference` | LOFI | RANDOM | True | kostenbasiert |
| RR+RR | LOFI* | RANDOM | **False** | **zufällig** |
| LR+NR | LOFI* | **NEAREST** | **False** | kostenbasiert |
| ABC+ABC | **ABC** | **ABC** | True | kostenbasiert |
| POPULARITY+POPULARITY | **POPULARITY** | **POPULARITY** | True | kostenbasiert |

\* wirkungslos, da ohne Ordered Return.

Sauber einkomponentig vergleichbar sind:
`baseline_reference` ↔ ABC+ABC und `baseline_reference` ↔ POPULARITY+POPULARITY
(je Reordering **und** Placement geändert, aber Ordered Return gleich), sowie
RR+RR ↔ LR+NR (nur Placement und Blocker-Ablage unterschiedlich).

---

# 7. Finales Setup

## 7.1 Empfehlung

| Parameter | Wert | Begründung |
|---|---|---|
| Grid | **20 × 30** | Footprint-Verhältnis 1,5 : 1; 598 Storage-Stacks. Nicht vergrößern — Laufzeit skaliert ungünstig. |
| Höhe H | **8** | Mellers eigenes Rechenbeispiel nutzt 8 Ebenen (36 bins/robot/hour); zugleich Lehmanns Baseline-`H`. Erzeugt relevante Digging-Effekte. |
| Bins | **4320** | ≈ 90 % der effektiven Kapazität (4784). |
| Pickstations | **2** | verbindlich gesetzt. |
| Roboter | **8** | siehe 7.2 |
| `request_utilization` | **0,6** | siehe 7.3 |
| Zipf θ | **1,0** *(Änderung von 1,5)* | siehe 7.4 |
| Seeds | **10 Seeds**, fest: 1, 2, 3, 4, 7, 11, 13, 42, 99, 123 | siehe 8.3 |
| Laufzeitgrenze | **6000 ZE** | siehe 8.2 |

## 7.2 Roboterzahl: 8

Kapazitätspilot (20 × 30, H = 8, Seed 42, util 0,6, θ = 1,0, 800 ZE):

| Roboter | bins/ZE | bins/Roboter/ZE |
|---|---|---|
| 4 | 0,0375 | 0,00937 |
| 6 | 0,0475 | 0,00792 |
| **8** | **0,0625** | **0,00781** |
| 10 | 0,0675 | 0,00675 |
| 12 | 0,0612 | 0,00510 |

Der Systemdurchsatz steigt bis 10 Roboter und fällt bei 12 wieder — die
klassische Stau-Kurve, die Meller beschreibt. 8 Roboter erreichen 93 % des
Maximums bei deutlich besserer Roboterproduktivität als 10. Zum Vergleich:
Lehmanns Baseline nutzt K = 5 Roboter je Pickstation, wir 4.

Dieser Pilot ist erst seit dem Fix aus 5.4 aussagekräftig — vorher hätte jede
Änderung der Roboterzahl auch das Binlayout verschoben.

## 7.3 Nachfrageintensität: 0,6 (gesättigt)

Sättigungspilot (800 ZE, 8 Roboter, θ = 1,0):

| `util` | angeboten/ZE | bins/ZE | offener Backlog am Ende |
|---|---|---|---|
| 0,05 | 0,07 | 0,0338 | 17 |
| 0,10 | 0,11 | 0,0437 | 42 |
| 0,20 | 0,22 | 0,0537 | 122 |
| 0,40 | 0,43 | 0,0600 | 289 |
| **0,60** | 0,66 | **0,0625** | 457 |
| 1,00 | 1,04 | 0,0550 | 738 |

Die Systemkapazität liegt bei ≈ 0,06 Retrievals/ZE. Schon `util = 0,1`
übersteigt sie. Das System arbeitet also **dauerhaft gesättigt** — was
Lehmanns Modellannahme entspricht („In a CQN, retrieval jobs are always
available"). Gemessen wird damit tatsächlich **Durchsatzkapazität**.

`util = 0,6` liegt am Durchsatzmaximum; bei 1,0 sinkt der Durchsatz durch
Stau wieder. **Kein Load-Sweep im finalen Experiment.**

Konsequenz: Terminmetriken sind bedeutungslos und wurden aus dem finalen
Metriksatz entfernt (4.4).

## 7.4 Zipf-Parameter: 1,0 statt 1,5

Meller argumentiert explizit mit einer 80/20-Nachfrage. Anteil der Nachfrage
auf die 20 % häufigsten Bins (N = 4320):

| θ | Top-20 % | Klasse A (20 %) | Klasse B (30 %) | Klasse C (50 %) |
|---|---|---|---|---|
| 0,8 | 67,0 % | – | – | – |
| 0,9 | 74,9 % | – | – | – |
| **1,0** | **82,0 %** | **82,0 %** | **10,2 %** | **7,7 %** |
| 1,2 | 92,4 % | – | – | – |
| **1,5 (bisher)** | **98,5 %** | **98,5 %** | **1,0 %** | **0,5 %** |

**θ = 1,0 trifft Mellers 80/20 nahezu exakt.** Bei θ = 1,5 entfallen 98,5 %
der Nachfrage auf die A-Klasse; B und C werden praktisch nie abgerufen, und
die B-/C-Zweige der ABC-Policy sind faktisch wirkungslos.

Nebeneffekt: θ = 1,0 reduziert das Batching von 2,14 auf 1,14 Requests je
Retrieval und erhöht die Zahl messbarer physischer Retrievals um rund 35 %.

## 7.5 Füllgrad und Holes

4320 Bins auf 598 Stacks × 8 = 4784 Slots ⇒ 90,3 %. Gemessen am Laufende:
mittlere Stackhöhe 7,21; **56 % der Stacks haben eine freie Top-Zelle**.

Mellers Referenz sind ~25 % reservierte Holes. Wir reservieren keine Holes;
freie Top-Zellen entstehen dynamisch. Der Wert liegt über Mellers Richtwert,
Relocations haben also ausreichend Platz. Als Modellabstraktion dokumentiert.

---

# 8. Steady-State- und Stop-Regel

## 8.1 Regel

1. Lauf startet aus dem definierten Initialzustand (zufällige Belegung).
2. Warm-up läuft.
3. Gemessen wird in **Blöcken von 50 physischen Retrievals**. Signal ist das
   mittlere β (Blocking Bins je Retrieval).
4. Konvergenz, sobald die relative Änderung zwischen aufeinanderfolgenden
   Blockmitteln **zweimal in Folge** ≤ 10 % bleibt.
5. Danach läuft ein Measurement Window von **200 weiteren physischen
   Retrievals**.
6. Wird bis 6000 ZE keine Konvergenz erreicht, gilt der Lauf als
   `not_converged` und wird in der Auswertung **getrennt** behandelt.

## 8.2 Begründung der Abweichung von Lehmann

Lehmann beendet den Warm-up bei < 0,1 % relativer Änderung von `t_rack`
zwischen zwei Blöcken von je 10.000 Command Cycles. Bei unseren ≈ 0,06
Retrievals/ZE entspräche ein Block rund 160.000 ZE — nicht rechenbar und
fachlich nicht übertragbar (anderes Modell: zwei Pickstations, echte
Verkehrsführung, Batching, abstrakte Zeit).

Übernommen wurde das **Prinzip**: Blöcke in Command Cycles statt in Zeit,
relative Änderung als Kriterium, festes Measurement Window danach.

Blöcke in **Retrievals** statt in ZE zu zählen ist wesentlich: Sonst hinge die
Warm-up-Länge davon ab, wie schnell eine Policy überhaupt arbeitet, und
langsamere Policies bekämen systematisch kürzere Warm-ups.

## 8.3 Wahl des Signals

β ist die Größe, die sich beim Übergang aus der zufälligen Anfangsbelegung
verändert (Natural Slotting) — also exakt RQ4 — und erklärt zugleich einen
Hauptteil der Zykluszeit (bei Lehmann geht β_all in `t_rack` ein). Ein
multivariates Kriterium wäre schwerer zu erklären; wer den räumlichen Zustand
zusätzlich prüfen will, findet ihn in `distribution.csv`.

**Robustheit.** Bei kleinen Blöcken ist das Blockmittel verrauscht, deshalb
`required_stable_pairs = 2`. β geht bei gutem Natural Slotting gegen 0; die
relative Änderung wird deshalb symmetrisch und nach unten begrenzt gebildet
(`|Δ| / max(Mittel beider Blöcke, 0,05)`). Zwei Blöcke mit β ≈ 0 gelten als
Steady State — fachlich richtig, denn ein Lager ohne Digging-Bedarf **ist**
im Steady State.

## 8.4 Praktischer Test

Baseline, Seed 42, 2500 ZE, Blockgröße 25, Schwelle 15 %:

```
Blockmittel β:      [1.36, 0.0, 0.0, 0.0]
relative Änderung:  [2.0,  0.0, 0.0]
Ergebnis:           converged, t = 1553 ZE, nach 100 Retrievals
```

Bei 1000 ZE meldet dieselbe Regel korrekt `not_converged` (β noch bei
1,35 → 0,35 → 0,0, Transient läuft noch).

Daraus die Laufzeitgrenze: Konvergenz ≈ 100 Retrievals ≈ 1550 ZE, plus 200
Retrievals Measurement Window ≈ 3200 ZE ⇒ ≈ 4800 ZE. Grenze **6000 ZE** mit
Reserve.

## 8.5 RQ4-Auswertung

`convergence_time` (in ZE) und `convergence_retrievals` (in Command Cycles)
stehen beide in `runs.csv`. Der Verlauf (`block_means`, `relative_changes`)
liegt in `run_meta.json`.

---

# 9. Datenformat und Datenmenge

## 9.1 Format

Vier Dateien je Kampagne, alle mit `run_id` als Schlüssel:

| Datei | Format | Inhalt |
|---|---|---|
| `runs.csv` | CSV, 36 Spalten | eine Zeile je Lauf |
| `retrievals.csv` | CSV, 19 Spalten | eine Zeile je physischem Retrieval, inkl. `in_measurement_window` |
| `distribution.csv` | CSV | eine Zeile je Verteilungs-Snapshot |
| `run_meta.json` | JSON | vollständige Konfiguration und Steady-State-Verlauf je Lauf |

Geschrieben wird **inkrementell** (`ExperimentWriter`), damit ein Abbruch die
bereits gerechneten Läufe nicht verliert. Kein Datenbanksystem, keine
Excel-Abhängigkeit, direkt mit `pandas.read_csv` auswertbar.

## 9.2 Größenabschätzung

Gemessen im Pilot: **87 Byte je Retrieval-Zeile**.

| | je Lauf | Kampagne (5 Konfigurationen × 10 Seeds = 50 Läufe) |
|---|---|---|
| `retrievals.csv` | ≈ 300 Retrievals ≈ 26 KB | ≈ 1,3 MB |
| `distribution.csv` | ≈ 60 Snapshots ≈ 4 KB | ≈ 200 KB |
| `runs.csv` | ≈ 0,6 KB | ≈ 30 KB |
| `run_meta.json` | ≈ 2,5 KB | ≈ 125 KB |
| **gesamt** | | **≈ 1,7 MB** |

Zum Vergleich: ein vollständiger ROBOT_MOVE-Log läge bei rund 700 Ereignissen
je Retrieval, also grob 1 GB — ohne zusätzlichen Erklärungswert.

## 9.3 Laufzeit

≈ 17–20 ZE/s im finalen Setup ⇒ ≈ 5 Minuten je 6000-ZE-Lauf, ≈ **4 Stunden**
für die gesamte Kampagne. Sequentiell beherrschbar.

---

# 10. Reproduzierbarkeit

Unverändert aus Phase 4, plus der Entkopplung aus 5.4:

| Strom | Verbraucher | Art |
|---|---|---|
| `initialization` | initiale Bin-Verteilung | exogen |
| `robots` | Roboter-Startpositionen | exogen |
| `requests` | Ankünfte, Target-Bins, Zeitfenster | exogen |
| `service` | Bearbeitungszeit je Request | exogen |
| `relocation` | zufällige Blocker-Ablage (RR+RR) | endogen |
| `placement` | RANDOM, Tie-Breaks, Warmup | endogen |

Garantien, alle testgesichert:

* gleicher Master-Seed ⇒ identisches Binlayout, identische Roboterpositionen,
  identischer Request-Strom und identische Servicezeit je Request über **alle**
  Policies,
* Servicezeit ist an die `request_id` gebunden und wird vor Simulationsbeginn
  gezogen — die policyabhängige Ereignisreihenfolge kann sie nicht verschieben,
* Batching zerstört die Kopplung nicht (Servicedauer = Summe der
  Request-Zeiten),
* zusätzliche Strategie-Ziehungen verschieben keinen exogenen Strom,
* die **Messinfrastruktur verbraucht keinen Zufall**
  (`test_metrics_do_not_consume_randomness`).

## 10.1 Statistik

Bewusst schlank gehalten:

* **10 unabhängige Replikationen** (Seeds) je Konfiguration,
* Mittelwert und Standardabweichung der primären KPI,
* **95-%-Konfidenzintervalle** über die Seeds (t-Verteilung, n = 10),
* **gepaarte Vergleiche** über Common Random Numbers: Für jeden Seed liegen
  alle Policies auf demselben exogenen Workload, Differenzen können also
  seedweise gebildet werden. Das reduziert die Varianz erheblich und ist der
  eigentliche Nutzen der CRN-Struktur.
* Für Verteilungsgrößen (P(β = s), Level-Verteilung) werden die Retrievals
  über alle Seeds einer Policy gepoolt.

Keine Dutzende Hypothesentests, keine Multiplizitätskorrekturen. Priorität:
Effektgröße, Unsicherheit, gepaarter Vergleich.

---

# 11. Bekannte Limitationen

| # | Limitation |
|---|---|
| L-1 | Ein Load je Produkt; keine retrieval load selection (1.1) |
| L-2 | Einstufige Bin-Vorbereitung statt Mellers „prepare → hole → port queue" |
| L-3 | Kein Hole-Kontingent; freie Top-Zellen entstehen dynamisch |
| L-4 | Keine Charger, keine Ladezustände, keine Roboterorientierung |
| L-5 | Abstrakte Zeiteinheiten; keine Kalibrierung auf Sekunden |
| L-6 | Dauerhafte Sättigung ⇒ Terminmetriken nicht interpretierbar |
| L-7 | Baseline und RR+RR unterscheiden sich in zwei Dimensionen (6.3) |
| L-8 | ABC-Placement ist ein Greedy-Score, kein Zonenmodell wie Lehmanns CBS-3 |
| L-9 | Initialverteilung nutzt die Port-Pufferzone, alle Placement-Policies nicht (5.3) |
| L-10 | MOVE-Stall-Recovery-Schwelle 120 ZE, aus vier Seeds abgeleitet |
| L-11 | `test_simulation_visual.py` nicht ausführbar (kein Flask) |
| L-12 | `STREAM_NAMES` ist append-only; Umsortieren macht frühere Läufe unreproduzierbar |
| L-13 | Warmup-Länge von 50 Retrievals nicht neu kalibriert (bei ≈ 300 Retrievals je Lauf rund 17 %) |

---

# 12. Readiness-Kriterien

| Kriterium | Ergebnis |
|---|---|
| Alle Tests grün | **ja** — 383 passed |
| Keine State-/Bin-/Task-/Traffic-Verletzungen | **ja** — Phase-3B-Re-Audit über 345 Läufe ohne Befund, seither keine Logikänderung an diesen Pfaden |
| Zwei Pickstations korrekt und nutzbar | **ja** — beide bedienen Tasks, Zuordnung im finalen Layout nachweislich distanzbasiert |
| AutoStore-like Baseline nachvollziehbar | **ja** — PASS gegen Meller und Lehmanns `CIRS-Random` |
| Jede finale Metrik definiert, erfasst, exportiert | **ja** — Abschnitt 4, Export getestet |
| Alle vier RQs mit dem geplanten Datensatz analysierbar | **ja** — RQ1/RQ3 über `retrievals.csv`, RQ2 über KPI-Vergleich, RQ4 über Steady-State-Felder |
| Primäre KPI eindeutig festgelegt | **ja** — `bin_throughput` |
| Batching-Semantik geklärt | **ja** — Abschnitt 3.3, `batch_size` je Retrieval |
| Steady-State- und Stop-Regel festgelegt und getestet | **ja** — Abschnitt 8 |
| Reproduzierbarkeit / CRN intakt | **ja** — Phase-4-Tests weiterhin grün, Messinfrastruktur zufallsfrei |
| Setup-Parameter wissenschaftlich begründet | **ja** — Abschnitt 7 |
| Datenmenge und Runtime beherrschbar | **ja** — ≈ 1,7 MB, ≈ 4 h |
| Keine policy-asymmetrische Infrastrukturverzerrung | **ja** — Eligibility vereinheitlicht, Layout von Roboterzahl entkoppelt, Tie-Break nachweislich unerreichbar |
| Keine Zusatzruns absehbar | **ja** — Rohdaten decken alle vier RQs ab |

## Urteil

```text
EXPERIMENT_READY
```

Die Simulation ist als wissenschaftliches Messinstrument geeignet. Die vier
offenen Forschungsfragen von Meller (2023) sind mit dem geplanten finalen
Datensatz im dokumentierten Scope analysierbar, die primäre KPI ist
literaturverankert, die Baseline entspricht der von Meller beschriebenen und
von Lehmann formalisierten AutoStore-Strategie, und alle bekannten
policy-asymmetrischen Verzerrungen sind beseitigt.

Offen bleiben die unter 11 dokumentierten Modellgrenzen. Keine davon
verhindert die Kampagne; L-1, L-2 und L-7 gehören in die
Limitations-Abschnitte beider Arbeiten.

## Vor dem Freeze zu entscheiden

Diese Phase empfiehlt, entscheidet aber nicht:

1. **Zipf 1,0 statt 1,5** (7.4) — inhaltlich die Kernänderung am Setup.
2. **`baseline_reference` im Vergleich behalten?** Sie ist die AutoStore-
   Referenz und für beide Arbeiten die gemeinsame Bezugsgröße — Empfehlung: ja.
3. **Seedanzahl 10** und Laufzeitgrenze 6000 ZE.
4. **Warmup-Länge** von 50 Retrievals (L-13).

`experiments/experiment_setup.md` wurde **noch nicht** auf θ = 1,0 umgestellt —
das geschieht erst nach dieser Entscheidung.

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Die finale Kampagne
wurde **nicht** gestartet.
