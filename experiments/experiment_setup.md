# Simulationsszenario und Parametrisierung

Dieses Dokument beschreibt das Basisszenario, das für alle **fünf**
Konfigurationen der finalen Kampagne gilt: `baseline_reference`, RR+RR,
LR+NR, ABC+ABC und POPULARITY+POPULARITY.
Ziel ist eine hohe Lagerauslastung bei gleichzeitig ausreichender Flexibilität
für Relocations sowie ein Layout, das strukturell den in der Literatur
diskutierten Systemen ähnelt, ohne die Simulation unnötig groß und langsam
zu machen.

## Lagergeometrie

- Grid-Breite: `grid_width = 20`
- Grid-Tiefe: `grid_depth = 30`
- Maximale Stapelhöhe: `max_stack_height = 8`
- Anzahl Pickstations im Grid: `num_pickstations = 2`

Wichtig:  
Die Pickstations liegen **im Grid** und belegen reguläre Grid-Zellen. Diese
Zellen werden in der Simulation **nicht** als Lager-Stacks behandelt und
stehen damit nicht für die Einlagerung von Bins zur Verfügung.

Damit ergibt sich eine **theoretische** maximale Lagerkapazität von

\[
C_{\text{theoretisch}} = 20 \times 30 \times 8 = 4800 \text{ Bins}.
\]

Davon entfallen zwei Zellen auf die Pickstations, was auf einen
**Zwischenwert** von \((20 \times 30 - 2) \times 8 = 4784\) Slots führt.

Dieser Zwischenwert ist NICHT der maßgebliche Nenner. Verbindlich ist die
Kapazität der **zulässigen** Storage-Positionen: Seit der Angleichung der
Initial-Eligibility ist zusätzlich die Port-Pufferzone gesperrt (Manhattan
≤ 1 um einen Port, im finalen Layout 8 Zellen, davon 2 Ports). Es bleiben

\[
C_{\text{zulässig}} = 592 \times 8 = 4736 \text{ Slots}.
\]

Die Initialisierungslogik (`init_random_distribution`) verteilt ausschließlich
über diese 592 Stacks und berechnet die verfügbare Kapazität genau darauf.

### Initialverteilung und Storage-Eligibility (verbindlich seit dem Freeze-Closeout)

Die Initialverteilung nutzt **exakt dieselben** zulässigen Storage-Positionen
wie die Placement-Policies zur Laufzeit. `SimulationEngine._initialize_state`
berechnet dazu die Port-Pufferzone mit `utils.port_buffer_zone.
calculate_buffer_zone` und übergibt sie als `excluded_positions` an
`initialize_bins` — dieselbe Funktion, aus der auch `State.buffer_zone` und
damit `State.is_valid_storage_position` gespeist wird.

Verboten sind also initial wie zur Laufzeit:

- die Port-/Pickstation-Zellen selbst,
- alle Zellen mit Manhattan-Distanz ≤ 1 zu einem Port.

Im finalen Layout betrifft das 8 Zellen, davon 2 Ports:

\[
C_{\text{zulässig}} = 592 \times 8 = 4736 \text{ Slots},\qquad
\text{Füllgrad} = \frac{4320}{4736} \approx 0{,}912.
\]

**Grund:** Mellers RQ4 fragt nach der Reorganisation aus einem zufälligen,
aber bereits *gültigen* Lagerzustand. Startete das Lager mit Bins in der
Pufferzone, würde zusätzlich deren erzwungenes Ausströmen aus Zellen
gemessen, die nach t=0 nie wieder belegt werden dürfen. Nebeneffekt der
alten Variante: die Pufferzonen-Stacks liefen im Laufe der Simulation leer
und lieferten unbemerkt zusätzliche freie Kapazität — der effektive Füllgrad
war damit nicht stationär.

**Kein Fallback.** Reicht die Kapazität nach Abzug der Pufferzone nicht,
wirft `init_random_distribution` einen `ValueError`. Die Modellsemantik
schaltet nie um; kleine Testkonfigurationen müssen ihre Voraussetzungen
explizit gültig wählen (Grid groß genug oder Binzahl klein genug).

## Bin-Anzahl und physische Auslastung

Die Anzahl der Bins wird so gewählt, dass das Lager stark ausgelastet, aber
nicht vollständig gefüllt ist:

- Bin-Anzahl: `bin_num = 4320`
- Füllgrad: **91,2 %**

Bezogen auf die zulässige Kapazität (ohne Pickstation-Zellen UND ohne
Port-Pufferzone) ergibt sich:

\[
\text{Füllgrad} = \frac{4320}{4736} \approx 0{,}912.
\]

Das ist der maßgebliche Wert. Der ältere Bezug auf 4784 Slots (nur
Pickstation-Zellen abgezogen) ergäbe 90,3 %, beschreibt aber einen
Zustandsraum, den die Simulation seit der Angleichung der Eligibility nicht
mehr verwendet.

Damit sind die meisten Stacks bis nahe an die maximale Höhe belegt, es
existieren jedoch noch ausreichend freie Top-Positionen, um Relocations von
Blocking-Bins durchführen zu können. Dieses Setting erzeugt ein realistisch
„dichtes“ Lager und macht Unterschiede in Reordering- und
Target-Bin-Placement-Strategien messbar.

## Pickstations und Roboter

Es werden zwei Pickstations eingesetzt:

- Anzahl Pickstations: `num_pickstations = 2`
- Kapazität pro Pickstation: `pickstation_capacity = 1`

Die Platzierung erfolgt direkt **im Grid** durch die Simulation-Engine:

- Die Pickstations liegen am Rand des Grids und sind sich gegenüberliegend
  angeordnet.
- Die konkrete Platzierung hängt von der längeren Seite des Grids ab:
  - Falls `grid_depth >= grid_width` (längere Seite in y-Richtung):
    - Linke Seite: `(0, depth // 2)`
    - Rechte Seite: `(width - 1, depth // 2)`
  - Andernfalls (längere Seite in x-Richtung):
    - Obere Seite: `(width // 2, 0)`
    - Untere Seite: `(width // 2, depth - 1)`

Diese Grid-Positionen werden vom `StorageGrid` als Port-/Pickstation-Zellen
gekennzeichnet und daher bei:

- der Berechnung der verfügbaren Stack-Positionen und
- der zufälligen Anfangsbelegung mit Bins

**nicht** als Lager-Stacks berücksichtigt. Effektiv stehen somit bei zwei
Pickstations genau zwei Stack-Positionen weniger für die Einlagerung zur
Verfügung.

Die Roboteranzahl wird relativ zur Systemgröße und den Pickstations gewählt:

- Gesamtzahl Roboter: `num_robots = 8`

Dies liefert hinreichend viele Roboter, um parallele Zugriffe, Interferenzen
und Traffic-Management-Effekte sichtbar zu machen, bleibt aber noch gut
simulierbar über mehrere Seeds und Strategien hinweg.

## Nachfragegenerierung

Die Nachfrage wird so parametrisiert, dass eine realistische, schiefe
Verteilung der Zugriffe entsteht, ohne dass das System permanent überlastet
wird:

- Ankunftsprozess: `request_arrival_strategy = "Poisson"`
- Zielauslastung: `request_utilization = 0.6`
- Bin-Nachfragewahrscheinlichkeit: Zipf-Verteilung
  (`bin_request_prob_strategy = "zipf"`)
- Zipf-Parameter: `zipf_parameter = 1.0`  (seit dem Freeze-Audit; vorher 1.5)

Damit entstehen „Hot Bins“, die wesentlich häufiger angefragt werden als der
Durchschnitt. Dies ist eine notwendige Voraussetzung, um die Effekte der
ABC- und Popularity-basierten Strategien auf Digging-Depth, Reshuffling-
Verhalten und räumliche Bin-Verteilung untersuchen zu können.

Der Wert 1,0 ist bewusst gewählt. Bei `bin_num = 4320` entfallen auf die
20 % meistgefragten Bins:

| `zipf_parameter` | Anteil der Nachfrage auf die Top-20 % |
|---|---|
| **1,0** | **82,0 %** |
| 1,5 | 98,5 % |

Damit trifft 1,0 das in der Literatur diskutierte 80/20-Szenario nahezu
exakt, während 1,5 die Nachfrage so stark auf wenige Bins konzentriert, dass
die C-Klasse praktisch nie angefragt wird (0,5 %) und ABC-/Popularity-Effekte
nicht mehr differenziert messbar sind.

Zur Einordnung der Nachfrageintensität: Die gemessene Systemkapazität liegt
bei rund 0,031 Retrievals je ZE, das Angebot bei `request_utilization = 0.6`
bei 0,66 Requests je ZE. Das System läuft damit im gesättigten Bereich; der
Durchsatz ist kapazitäts- und nicht nachfragebegrenzt. Das ist beabsichtigt,
weil die primäre Kennzahl die Systemkapazität misst — hat aber Folgen für die
Interpretation der Termintreue (siehe unten).

## Zeiteinheiten und Kostenparameter

Die Simulation arbeitet in **abstrakten, normierten Zeiteinheiten (ZE)**. Es
wird **keine direkte Abbildung** auf reale Sekunden vorgenommen. Insbesondere
wurden die im zugrunde liegenden Paper angegebenen physikalischen Parameter
(z.B. Roboter-Geschwindigkeiten in m/s, Beschleunigungen, Pick-Zeit des
Bedieners in Sekunden) **nicht 1:1 auf die Simulationszeiteinheiten
kalibriert**.

Stattdessen werden einfache, ganzzahlige Kostenparameter verwendet, die:

- alle Aktionen auf einer einheitlichen Skala bewerten,
- die Simulation numerisch stabil und gut interpretierbar halten,
- und vor allem einen **fairen Vergleich** aller fünf Konfigurationen
  ermöglichen, da sie im exakt gleichen Kostenmodell laufen.

Konkret kommen u.a. folgende Kostenparameter zum Einsatz:

- `move_cost_per_grid_step = 1`  
  → Horizontaler Bewegungsschritt auf dem Grid kostet 1 ZE.
- `arm_move_cost_per_level = 1`  
  → Vertikales Bewegen des Arms um eine Ebene kostet 1 ZE.
- `grip_cost = 1`, `drop_cost = 1`  
  → Greifen und Absetzen einer Bin werden jeweils mit 1 ZE bewertet.
- `pickstation_service_time_min = 4`,
  `pickstation_service_time_max = 6`  
  → Die Bearbeitung einer Bin an der Pickstation dauert zwischen 4 und 6 ZE.

Diese Parameter sind als **skalierte, normierte Zeiten** zu verstehen, nicht
als direkte Abbilder der in der Literatur genannten Sekundenwerte
(z.B. 20 s Pick-Zeit des Bedieners oder 2 s für Greifen/Absetzen). Entscheidend
für die vorliegende Arbeit ist, dass:

1. alle fünf Konfigurationen auf der **gleichen normierten Skala** bewertet
   werden,
2. die Kostenordnung plausibel ist (z.B. hat eine Pickstation-Bearbeitung
   eine höhere Dauer als ein einzelner Grid-Schritt),
3. und die Simulation damit ausreichend schnell bleibt, um mehrere Seeds und
   Layouts durchzuspielen.

Eine feinere physikalische Kalibrierung der Kostenparameter auf Basis realer
m/s- und Sekunden-Angaben aus der Literatur wäre prinzipiell möglich und
könnte in zukünftiger Arbeit ergänzt werden. Für die Beantwortung der
Forschungsfragen RQ1–RQ4 (Vergleich der Reordering- und Placement-Strategien
innerhalb eines konsistenten Modells) ist eine solche Kalibrierung jedoch
nicht erforderlich.

## Request-Auswahl und Termine (verbindlich seit dem Freeze-Audit)

### Auswahlreihenfolge

```text
1. bereits begonnene Tasks, Fortsetzungen und Rücklagerungen
2. neue Pending Requests ausschließlich nach EDF
```

`scheduler_strategy = "EDF"` (vorher `"FIFO"`).

Bis zum Freeze-Audit lag zwischen beiden Stufen ein **lageabhängiger
Bypass**: Lag das Target eines wartenden Requests zufällig obenauf, wurde
dieser Request bevorzugt bedient. Gemessen (Seed 42, 800 ZE,
`baseline`) liefen **39 von 47 Zuweisungen** über diesen Bypass, mit
drastischen Folgen für genau die Größen, die RQ1 und RQ3 messen sollen:

| | β (Blocking Bins je Retrieval) | Retrievals aus den obersten 20 % der Ebenen |
|---|---|---|
| mit Bypass | 0,73 | 84 % |
| ohne Bypass | 2,70 | 33 % |

Der Bypass ist deshalb aus dem Hauptpfad entfernt. Die Request-Auswahl darf
die untersuchten Storage-Policy-Effekte nicht überlagern; maximaler
Durchsatz ist ausdrücklich nicht das Ziel.

Der EDF-Tie-Break ist vollständig deterministisch:

```text
latest_time  →  arrival_time  →  request_id
```

Kein Kriterium hängt von Lagerposition, Digging-Tiefe, ABC-Klasse oder
Popularität ab.

### Deadline

```text
request.latest_time = arrival_time + deadline_slack        (absolut)
deadline_slack = 240
```

Der Slack ist für alle Requests konstant, exogen und policyneutral. Er wird
zusammen mit dem Request-Strom vor Simulationsbeginn festgelegt und ist bei
gleichem Seed über alle Policies identisch.

Bis zum Freeze-Audit wurde stattdessen eine Prioritätsklasse gezogen
(10 % urgent = 3 ZE, 75 % normal = 6 ZE, 15 % low = 12 ZE, plus Rauschen
∈ [−2, 2]). Der resultierende Slack von 1–14 ZE stand rund 30 ZE reiner
Bearbeitungszeit je Retrieval gegenüber; die Verspätungsquote lag bei
91–97 % und war damit ohne Aussagekraft.

Kalibrierung von `D` (Seed 42, 1200 ZE, `baseline`):

| `D` | Verspätungsquote | Median Tardiness |
|---|---|---|
| 60 | 68 % | 122 |
| 120 | 59 % | 62 |
| **240** | **44 %** | **0** |

Bei konstantem Slack entspricht EDF im Wesentlichen der
Ankunftsreihenfolge. Die Deadline ist damit eine reine Messüberlagerung und
keine zusätzliche Priorisierungspolitik — testgesichert dadurch, dass der
Slackwert die physische Retrieval-Sequenz nicht verändert.

### Termintreue: was die Kennzahl aussagt

```text
completion_time = Ankunft der Target-Bin an der Pickstation
lateness        = completion_time - latest_time
tardiness       = max(0, lateness)
```

Deadline- und Tardiness-Kennzahlen sind **sekundäre** Performance-KPIs; die
primäre Kennzahl bleibt der Durchsatz.

Weil das System gesättigt läuft (Angebot > Kapazität bei jeder getesteten
Last), misst die Tardiness hier das **Alter des Rückstands**, nicht die
Servicequalität eines stabilen Warteschlangensystems. Sie wächst
systematisch mit der Lauflänge — bei identischem `D = 240` liegt der Median
bei 1200 ZE noch bei 0 und bei 3000 ZE bereits bei 327.

Zulässig ist deshalb ausschließlich der **gepaarte Vergleich zwischen
Policies** bei identischem Seed und identischer Lauflänge. Absolute Aussagen
über Service-Level oder Termintreue sind es nicht, ebensowenig Vergleiche
zwischen unterschiedlich langen Läufen.

### Batching

Werden mehrere Requests durch ein physisches Retrieval bedient, teilen sie
den Completion-Zeitpunkt, werden aber **jeder gegen seine eigene Deadline**
bewertet. Ein Batch erzeugt N Zeilen in `requests.csv` und genau eine Zeile
in `retrievals.csv`.

## Lauflänge und Messfenster (Methodik verbindlich seit 2026-08-22)

Alle 50 finalen Runs laufen **bis zur selben festen Simulationszeit**
`T_final`. Es gibt kein policyabhängiges Stoppen mehr.

```text
Warm-up:      t = 0            bis  T_measure_start
Messfenster:  T_measure_start  bis  T_final          (für ALLE Runs identisch)
```

Gründe:

1. Vergleichbarkeit — alle Policies werden über dasselbe Zeitintervall
   bewertet.
2. Deutlich einfachere Experimentlogik als eine policyabhängige Stop-Regel.
3. **Tardiness ist nur bei identischer Lauflänge vergleichbar.** Das System
   läuft bewusst gesättigt; die Verspätung misst das Alter des Rückstands und
   wächst mit der Lauflänge. Unterschiedlich lange Policy-Runs wären nicht
   vergleichbar.
4. RQ4 geht dadurch nicht verloren, im Gegenteil: `convergence_time_ZE` und
   `convergence_retrieval_count` werden je Lauf **offline** aus der
   vollständigen Zeitreihe ab t=0 bestimmt und sind damit selbst eine
   Ergebnisgröße. Ein Lauf darf bei t=12.000 konvergieren und trotzdem bis
   `T_final` weiterlaufen.

Performance-KPIs werden ausschließlich im gemeinsamen Messfenster berechnet:
`bin_throughput`, `request_throughput`, `deadline_miss_rate`,
`mean_tardiness`, `mean_blocking_bins`, `mean_dig_duration`,
`pickstation_utilisation`. Die RQ3-Verteilungen werden bevorzugt ebenfalls
für das gemeinsame Fenster berichtet; RQ4 nutzt zusätzlich die komplette
Zeitreihe ab t=0.

`100` physische Retrievals bleiben eine grobe Mindestgröße für
Verteilungsaussagen, sind aber **keine** Stop-Regel mehr.

### Festgelegte Werte (2026-08-24, Neuherleitung)

```text
T_measure_start   = 20.000 ZE
Measurement Window= 10.000 ZE
T_final           = 30.000 ZE
```

Alle 50 finalen Runs laufen `0 ... 30.000` und werden ausschließlich im
Intervall `[20.000, 30.000]` ausgewertet.

> **Die früheren Werte 30.000 / 12.000 / 42.000 sind ungültig.** Sie stammen
> aus einer Kalibration, in der `baseline_reference`, `ABC+ABC` und
> `POPULARITY+POPULARITY` mit **invertiertem Ordered Return** liefen
> (Befund vom 2026-08-22, `simulation/robot_task.py`). Der Fehler senkte den
> Durchsatz und verzögerte die räumliche Konvergenz; jede daraus abgeleitete
> Zahl ist Artefakt und darf nicht übernommen werden. Die Werte unten
> stammen aus 15 vollständig neu ab t = 0 gerechneten Läufen auf dem
> korrigierten Code.

**Herleitung** (15 Kalibrationsläufe: 5 Policies × Seeds 1, 7, 42, je bis
30.000 ZE, ABC+ABC/Seed 7 bis 42.000 ZE):

| Größe | Wert |
|---|---|
| konvergiert | 14 von 15 |
| langsamste beobachtete Konvergenz | 15.100 ZE (RR+RR, Seed 7) |
| größte Streuung innerhalb einer Policy | 4.400 ZE (RR+RR: 10.700 … 15.100) |
| Summe 19.500, aufgerundet | **20.000 ZE** |
| langsamste Retrievalrate nach Konvergenz | 0,03126 retr/ZE (POPULARITY, Seed 1) |
| Fenster 10.000 ZE ⇒ langsamster Lauf | **294 physische Retrievals** (gemessen) |
| Fenster 10.000 ZE über alle 15 Läufe | 294 … 592 physische Retrievals |

Die Reserve ist nicht frei gewählt: sie entspricht der größten zwischen
Seeds derselben Policy beobachteten Spanne. Ein noch ungetesteter Seed darf
damit noch einmal so viel langsamer sein wie der größte gemessene Abstand —
nötig, weil sieben der zehn finalen Seeds nicht kalibriert wurden.

*Sensitivität.* `LR+NR / Seed 7` zählt als `converged_then_rediverged` und
geht deshalb nicht in die Streuung ein. Zählte man sein Plateau (10.800 ZE)
mit, stiege die LR+NR-Spanne auf 4.500 ZE und die Summe auf 19.600 ZE —
`T_measure_start = 20.000` bleibt also auch unter der ungünstigeren
Auslegung unverändert. Der Wert hängt nicht an dieser Einordnung.

Die Fensterlänge folgt aus der Retrievalzahl im Fenster beim langsamsten
Lauf. Anders als in der verworfenen Kalibration wird sie hier nicht aus der
Rate hochgerechnet, sondern **direkt an den 15 Spuren abgezählt**: 10.000 ZE
liefern selbst dem langsamsten Lauf 294 Retrievals, also fast das Doppelte
der angestrebten Untergrenze von 150. Die Fensterlänge sinkt gegenüber der
verworfenen Kalibration von 12.000 auf 10.000 ZE, die statistische Masse im
Fenster **steigt** trotzdem (vorher hochgerechnet 174 im ungünstigsten Fall,
jetzt gemessen 294) — Folge der nach der Fehlerbehebung rund verdoppelten
Retrievalrate. Der Gesamthorizont sinkt von 42.000 auf 30.000 ZE, also rund
29 % weniger Rechenzeit je Lauf.

Im Code: `SimulationConfig.t_measure_start` und `.t_final`. Sind beide
gesetzt, bezieht `experiments/run_export.summarise_run` **alle** KPIs auf
dieses Intervall — Durchsatz, Requests, Verspätung und die Retrievals je
Pickstation. `runs.csv` weist das über `measurement_mode`, `t_measure_start`
und `t_final` aus.

**Eine Fensterquelle (seit 2026-08-24).** `run_export.measurement_window()`
entscheidet als einzige Stelle über Modus und Grenzen; `summarise_run` und
`retrieval_rows` fragen sie beide. Damit gilt für jeden einzelnen Run

```text
sum(retrievals.csv.in_measurement_window)  ==  runs.csv.measurement_retrievals
```

Die Grenzen sind beidseitig **inklusive** auf `t_pickstation`. Es gibt genau
zwei Modi: `time_window` (Kampagne) und `full_run` (Diagnose, Tests). Der
frühere dritte Modus `steady_state` — ein Fenster aus einer festen Zahl
Retrievals nach der β-Konvergenz — ist entfallen; er war eine zweite,
unabhängige Fensterdefinition und lieferte im Kampagnenpfad durchgehend
`False`, während `runs.csv` korrekt zählte (Befund J-1).

### Pickstation-Kennzahlen: Fensterbezug

| Größe | Bezug |
|---|---|
| `retrievals_ps0` / `retrievals_ps1` | Measurement Window |
| `pickstation` je Retrieval in `retrievals.csv` | Einzelereignis, frei filterbar |
| `pickstation_utilisation_ps0` / `_ps1` | **ganzer Lauf — nur diagnostisch** |

`Pickstation.get_utilization` teilt die kumulierte Servicezeit durch die
Laufzeit und ist damit nicht fensterbezogen. Für Aussagen über die
Lastverteilung im Messfenster sind ausschließlich `retrievals_ps0/ps1` bzw.
die gefilterten Rohdaten zu verwenden.

## Räumliche Konvergenz für RQ4

**Signal (festgelegt seit 2026-08-22).** `abc_level_<Klasse>_<Tiefe>` in den
Distribution-Snapshots: die gemeinsame Verteilung aller gelagerten Bins über
die statische ABC-Klasse und die Tiefe unter der Stapeloberkante, als
Anteile (24 Komponenten bei H = 8, Summe 1).

Begründung: Die ABC-Klassen sind statisch über die `bin_id` definiert, für
alle Policies identisch berechenbar und bilden unter Zipf = 1,0 die
Nachfrage ab. Gemessen auf der finalen Konfiguration:

| Klasse | Anteil Bins | Anteil Requests |
|---|---|---|
| A | 20 % | **80,8 %** |
| B | 30 % | 10,7 % |
| C | 50 % | 8,5 % |

Damit trifft die Klassifikation Mellers 80/20-Szenario praktisch exakt. Die
Tiefe von oben ist die Größe, über die Meller in RQ3/RQ4 spricht — nicht das
absolute Level, weil Stapel unterschiedlich hoch sind.

**Abstandsmaß.** Total Variation Distance, `TVD(p,q) = ½·Σ|pᵢ−qᵢ|`.

**Blockbildung nach physischen Retrievals**, nicht nach Zeit: die räumliche
Verteilung ändert sich durch Retrievals. LR+NR bewegt rund 55 Bins je
1000 ZE, ABC+ABC rund 22; bei Zeitblöcken würde die schnellere Policy
systematisch größere Abstände zeigen und fälschlich als „nicht konvergiert"
gelten.

**Persistenz ist Teil der Regel.** Verlangt werden K aufeinanderfolgende
Blockpaare unterhalb der Schwelle UND danach kein Zurückspringen über ein
Vielfaches davon. Die frühere β-Regel löste einmal kurz aus und sprang
sofort zurück; das darf sich nicht wiederholen.

**Finales Kriterium (2026-08-22): relatives Plateau.** Die 15
Kalibrationsläufe bestätigen, dass das Plateau policyabhängig ist — die
Niveaus liegen zwischen 0,0062 (POPULARITY/42) und 0,0124
(baseline_reference/7). Eine gemeinsame absolute Schwelle würde entweder bei
den ruhigen Policies zu früh auslösen oder `baseline_reference` nie
konvergieren lassen. Steady State heißt eben nicht `TVD → 0`.

```text
Block             R = 50 physische Retrievals
d_i               TVD zwischen Block i-1 und Block i
Vergleichsfenster K = 2 aufeinanderfolgende d_i
Plateau ab i      mean(d[i-1..i]) >= (1 - delta) * mean(d[i-3..i-2]),  delta = 0,10
Persistenz        P = 2 aufeinanderfolgende i erfuellen die Bedingung
```

In Worten: die TVD fällt nicht mehr systematisch, und das gilt zweimal
hintereinander. Zusätzlich wird auf Re-Divergenz nach dem Plateau geprüft.

**Drei eindeutige Zustände** (seit 2026-08-22, vorher konnten `converged`
und `redivergence` widersprüchlich gleichzeitig gelten):

```text
converged                  Plateau gefunden und gehalten
converged_then_rediverged  Plateau gefunden, danach steigt die TVD wieder
not_converged              kein Plateau gefunden
```

Nur `converged` zählt als konvergiert. Die Re-Divergenz wird auf derselben
Mittelungsbasis geprüft wie das Plateau (gleitendes Mittel über K Distanzen
gegen das Plateaumittel, Faktor 1,5) — ein Vergleich einzelner Blockabstände
gegen ein Mittel markierte zuvor normales Rauschen als Drift.

Ergebnis der Kalibration auf dem finalen Code (15 Läufe ab t=0, Stand
2026-08-24, nach der Behebung des invertierten Ordered Return):
**14 × `converged`** mit Konvergenzzeiten 6.300–15.100 ZE,
**1 × `converged_then_rediverged`** (LR+NR/Seed 7: Plateau bei 10.800 ZE,
Niveau 0,00701; das gleitende Mittel danach erreicht 0,01083 gegen die
Schwelle 0,01052 — ein Grenzfall, der die Schwelle um 3 % überschreitet).
**Kein** Lauf ist `not_converged`; insbesondere ABC+ABC/Seed 7 konvergiert
jetzt bei 12.601 ZE und läuft ohne Abbruch bis 42.000 ZE.

Die Schwelle wurde dafür **nicht** angepasst. Ein Grenzfall bleibt ein
Grenzfall und wird als solcher berichtet.

**Nicht verwendet** werden `hot_bins_top_ratio` (über den ganzen Lauf
konstant) und `bin_distribution_entropy` (defekt, konstant 0,0). β bleibt als
Digging-Größe für RQ1 erhalten, `stack_height_variance` als
Plausibilitätscheck.

**Umgang mit `not_converged`.** Erreicht ein finaler Lauf `T_measure_start`
ohne Konvergenz, wird er nicht gelöscht und der Seed nicht ausgetauscht. Er
wird als `not_converged_before_measurement` markiert, bleibt in allen
Performance-Auswertungen enthalten und wird in der RQ4-Auswertung getrennt
ausgewiesen.

Nicht verwendet werden:

* `hot_bins_top_ratio` — über den gesamten Lauf konstant (0,52–0,55) und
  damit blind für die Reorganisation;
* `bin_distribution_entropy` — liefert konstant 0,0, ist also defekt und
  wird aus der Methodik genommen;
* β allein — zu verrauscht als Konvergenzkriterium (siehe unten). β bleibt
  als operative, digging-bezogene Zusatzgröße erhalten,
  `stack_height_variance` als Plausibilitätscheck.

## Steady-State-/Stop-Regel (VERWORFEN — methodische Vorgeschichte)

> **Diese Regel ist nicht Teil der finalen Methodik.** Sie steht hier, weil
> die Begründung, *warum* sie verworfen wurde, in die Arbeit gehört. Der
> Code dazu (`metrics/steady_state.py`, `metrics/convergence_detector.py`)
> existiert weiterhin samt eigener Tests, speist aber seit dem
> Export-Closeout (2026-08-24) **keinen** finalen Export mehr. Wer ihn liest,
> darf ihn nicht für die RQ4-Regel halten — die steht in
> `metrics/rq4_plateau.py` und ist oben unter „Räumliche Konvergenz für RQ4"
> beschrieben.

Die Regel ist auf der finalen Konfiguration real durchlaufen worden und
hat sich in der bisherigen Parametrierung **nicht bewährt**. Sie ist deshalb
hier bewusst *nicht* als verbindlich eingetragen.

Geprüfte Parametrierung:

```text
Blockgröße          = 50 physische Retrievals
Signal              = mittleres β (Blocking Bins je Retrieval)
Schwelle            = 10 % relative Änderung
stabile Paare       = 2
Measurement Window  = 100 physische Retrievals
```

Ergebnis über 15 Piloten (5 Policies × Seeds 42, 1, 7): **ein** Lauf löste
aus, und dieser eine war ein Fehlalarm — nach den beiden Unterschreitungen
(0,076; 0,098) folgte sofort 0,224. Ein statistisch gleichartiger Lauf
derselben Policy löste nie aus.

Ursache ist die Streuung des Signals, nicht das Prinzip:

```text
über 2134 Retrievals:   mean(β) = 2,31   sd(β) = 2,27   CV = 0,98
erwartete relative Änderung ≈ √2 · CV / √B
```

| Blockgröße B | erwartete relative Änderung |
|---|---|
| 50 | 0,197 |
| 100 | 0,139 |
| 200 | 0,098 |
| 300 | 0,080 |

Bei B = 50 liegt die 10-%-Schwelle um den Faktor 2 unter dem reinen Rauschen.
Belastbar wäre eine Blockgröße ab **rund 200 Retrievals** — dann werden je
Lauf etwa 600 Retrievals bis zur Konvergenz plus 100 für das Measurement
Window gebraucht. Zum Vergleich: Lehmann & de Koster (2026) mitteln über
Blöcke von 10.000 Command Cycles bei einer Schwelle von 0,1 % bzw. 1 % und
messen für ihre Systeme 20.000–120.000 Command Cycles bis zum Steady State.

Ebenfalls offen: β ist **nicht** als Proxy für räumliche Stabilität
bestätigt. `hot_bins_top_ratio` ist über den gesamten Lauf konstant
(0,52–0,55) und damit als Signal ungeeignet; die Stackhöhenvarianz stieg zum
gemeldeten β-Konvergenzpunkt noch monoton weiter.

Vorbedingung für die Festlegung: Die Läufe müssen die Konvergenz überhaupt
erreichen können. Derzeit fahren sich Läufe beim Ordered Return über
zyklisch verschüttete Puffer-Blocker fest (Details in
`FINAL_EXPERIMENT_FREEZE_2026-08-21.md`, Abschnitt C.3).

## Strategien und Experimentkonfiguration

Stand: Phase 3B, 2026-08-21.

Eine Policy wird über **drei** Felder der `ExperimentConfig` festgelegt, nicht
über zwei. Neben `reordering_strategy` und `placement_strategy` entscheidet
`return_blocking_bins` mit – dieser Schalter trennt die Policies fundamental.

### Die vier untersuchten Policies

| Policy | `reordering_strategy` | `placement_strategy` | `return_blocking_bins` |
|---|---|---|---|
| **RR+RR** – Random Relocation + Random Return | `LOFI` | `RANDOM` | `False` |
| **LR+NR** – Local Relocation + Nearest Return | `LOFI` | `NEAREST` | `False` |
| **ABC+ABC** – ABC-Reordering + ABC-Placement | `ABC` | `ABC` | `True` |
| **POPULARITY+POPULARITY** | `POPULARITY` | `POPULARITY` | `True` |

### `return_blocking_bins`

- `True` – **Ordered Return.** Alle für ein Retrieval ausgelagerten
  Blocking-Bins werden anschließend in ihren Originalstack zurückgelegt. Die
  Reihenfolge bestimmt `reordering_strategy`. Nur in diesem Fall hat das
  Reordering überhaupt eine Wirkung.
- `False` – **Kein Ordered Return.** Die Blocking-Bins bleiben liegen, wo sie
  während des Retrievals abgelegt wurden. `reordering_strategy` ist dann
  wirkungslos; der Eintrag `LOFI` bei RR+RR und LR+NR ist reine Formsache.

Zusätzlich schaltet die Kombination `placement_strategy = "RANDOM"` **und**
`return_blocking_bins = False` die **zufällige** Wahl des temporären
Ablageplatzes für Blocking-Bins frei (`RelocationSelection`). In allen
anderen Fällen wird der Ablageplatz kostenbasiert gewählt
(Manhattan-Distanz zum Quellstack plus Bonus für direkte Nachbarn).

### `NEAREST`

`NEAREST` bezeichnet den nächstgelegenen zulässigen Stack **relativ zum
Originalstack der Target-Bin**:

1. minimale Manhattan-Distanz zum Originalstack,
2. bei Gleichstand kleinere `y`-Koordinate,
3. danach kleinere `x`-Koordinate.

Ist der Originalstack selbst zulässig, gewinnt er mit Distanz 0. Die Policy
ist damit strukturerhaltend.

Zulässig ist ein Stack, wenn er nicht gesperrt ist, freie Kapazität hat und
nicht in der Port-Pufferzone liegt (Manhattan-Distanz ≤ 1 zu einem Port).

Bis Phase 3B maß `NEAREST` die Distanz zur nächsten **Pickstation**. Das war
eine andere Policy („so nah wie möglich an den Port"); Messungen aus Phase 3
sind mit den heutigen nicht vergleichbar.

## Reproduzierbarkeit (verbindlich seit Phase 4)

Ein Lauf ist vollständig durch `random_seed` zusammen mit der übrigen
Konfiguration bestimmt. Alle Zufallsgrößen stammen aus einem Master-Seed
(`config/rng_streams.py`).

**Exogen** – bei gleichem Seed für alle Policies identisch:

- initiale Bin-Verteilung und Roboter-Startpositionen
- Request-Strom: Ankunftszeiten, angefragte Bins, Zeitfenster
- Pickstation-Bearbeitungszeit **je Request**

**Endogen** – gehört zur jeweiligen Policy, nur reproduzierbar:

- zufällige Ablage von Blocking-Bins (RR+RR)
- RANDOM-Placement, ABC-/Popularity-Tie-Breaks, Popularity-Warmup

Eine Policy darf beliebig viele eigene Zufallsentscheidungen treffen, ohne
die exogenen Größen einer anderen zu verschieben. Damit sind die vier
Policies unter Common Random Numbers vergleichbar.

Die Bearbeitungszeit ist an die `request_id` gebunden und wird vor
Simulationsbeginn gezogen. Beim Batching mehrerer Requests auf dieselbe Bin
ist die Servicezeit des Jobs die **Summe** der Request-Zeiten – jeder Request
trägt unabhängig von der Gruppierung denselben Wert bei.

Achtung: Die Reihenfolge der Stromnamen in `config/rng_streams.py` ist
append-only. Wird sie geändert, sind frühere Läufe nicht mehr reproduzierbar.

### Zusätzliche Referenzkonfiguration `baseline`

`run_experiments.py` führt neben den vier Policies eine fünfte Konfiguration
namens `baseline` aus:

```text
reordering_strategy  = "LOFI"
placement_strategy   = "RANDOM"
return_blocking_bins = True
```

`baseline` ist **nicht** RR+RR. Beide nutzen `RANDOM`-Placement, aber
`baseline` legt Blocking-Bins geordnet zurück und benutzt deshalb weder die
zufällige Blocker-Relocation noch den Verzicht auf den Ordered Return. Die
beiden unterscheiden sich also in zwei Dimensionen gleichzeitig und dürfen
nicht als Variante voneinander gelesen werden.

`baseline` ist Teil des finalen Vergleichs. Sie dient als gemeinsame
Referenz für beide Arbeiten (A: `baseline`, RR+RR, ABC+ABC;
B: `baseline`, LR+NR, POPULARITY+POPULARITY) und macht die Ergebnisse
zwischen den Arbeiten anschlussfähig. Weil sie sich von RR+RR in zwei
Dimensionen gleichzeitig unterscheidet, darf sie nur als Referenzpunkt und
nicht als Variante von RR+RR interpretiert werden.

Alle übrigen Parameter (Grid, Füllgrad, Roboterzahl, Pickstations,
Nachfrageprozess, Kostenparameter) werden aus der gemeinsamen
Basis-Konfiguration (`create_base_config()`) übernommen und sind somit für
alle Strategien und Seeds identisch. Dadurch sind die beobachteten
Unterschiede in Digging-Depth, Throughput, Reshuffling-Verhalten und
Bin-Verteilung direkt auf die untersuchten Strategien zurückzuführen.
---

## Ausführung der finalen Kampagne (verbindlich seit 2026-08-24)

### Der eine ausführbare Pfad

```bash
# 1. Plan prüfen — rechnet nichts, schreibt nichts
python3 -m experiments.run_final_campaign --dry-run --output-dir results/final

# 2. optional: kurzer End-to-End-Test über denselben Pfad
python3 -m experiments.run_final_campaign --smoke --output-dir /tmp/smoke

# 3. die Kampagne
python3 -m experiments.run_final_campaign --output-dir results/final
```

`run_experiments.py` ist **nicht** der Kampagnentreiber. Es ist der
historische Vergleichslauf (2.000 ZE, fünf alte Seeds, kein Messfenster,
alter Exporter) und bleibt aus Nachvollziehbarkeitsgründen unverändert.

### Eine Quelle für den Versuchsplan

`experiments/campaign_matrix.py` definiert Policies, Seeds, Geometrie,
Horizonte und den Config-Builder. Alles andere leitet sich davon ab:

```text
experiments/campaign_matrix.py
  ├─ experiments/run_final_campaign.py           Kampagne
  ├─ experiments/closeout/dry_check_matrix.py    Matrixprüfung
  └─ experiments/closeout/pilot_run.py           Kalibration
```

Dass `pilot_run.build_config` feldweise dieselbe Konfiguration liefert wie
`build_run_config`, prüft `tests/test_campaign_matrix.py`. Die vorhandene
Kalibration ist damit die Kalibration genau dieser Kampagnenkonfiguration.

### Erzeugte Dateien

| Datei | Inhalt |
|---|---|
| `runs.csv` | eine Zeile je Lauf: Setup, KPIs im Messfenster, RQ4-Ergebnis |
| `retrievals.csv` | eine Zeile je physischem Retrieval, mit `in_measurement_window` |
| `requests.csv` | eine Zeile je bedientem Request (Rohdaten, ungefiltert) |
| `distribution.csv` | Verteilungs-Snapshots, Grundlage der RQ4-Zeitreihe |
| `run_meta.json` | vollständige Config, RNG-Ströme, komplette RQ4-Auswertung, Fenstergrenzen |
| `campaign_status.json` | je Lauf `completed` / `failed`, für `--resume` |
| `logs/<run_id>.log` | die Laufausgabe, je Lauf getrennt |

Run-IDs sind deterministisch (`ABC+ABC__seed7`) — keine UUIDs als
wissenschaftlicher Schlüssel.

### Betriebsregeln

- **Kein stilles Überschreiben.** Ein nicht leeres Ausgabeverzeichnis ohne
  `--resume` bricht mit Exit 2 ab.
- **Kein Diagnoseziel.** Pfade mit `closeout`, `pilot`, `calib` oder `debug`
  werden abgelehnt. Finale Daten liegen getrennt von Pilot- und Debugmaterial.
- **Kein Seed-Tausch.** Ein fehlgeschlagener Lauf wird als `failed` vermerkt,
  bleibt in der Matrix, und die Kampagne endet mit Exit 1.
- **Fortsetzen statt neu rechnen.** `--resume` überspringt abgeschlossene
  Läufe und hängt an die bestehenden CSVs an, ohne Kopfzeilen zu wiederholen.
- **Sequentiell.** `ExperimentWriter` schreibt gemeinsame CSV-Dateien und ist
  nicht nebenläufigkeitssicher. Wer parallelisieren will, fährt Teilmengen
  über `--policy` / `--seed` in **getrennte** `--output-dir` und führt die
  Dateien anschliessend zusammen. Reproduzierbarkeit geht vor Geschwindigkeit.
- **Rauchtest getrennt.** `--smoke` benutzt eigene Konstanten (600 ZE, Fenster
  [300, 600]) und weigert sich, in ein Verzeichnis mit finalen Läufen zu
  schreiben.

Rechenzeitabschätzung aus den Kalibrationsläufen: 1.500–2.800 s je Lauf
einkernig, also rund 30 CPU-Stunden für 50 Runs.

### RQ4 im Export

Die eingefrorene Offline-Regel (`metrics/rq4_plateau.py`) wird nach Laufende
auf die vollständige Zeitreihe ab t = 0 angewendet; das Ergebnis steht direkt
in `runs.csv`. Es gibt **keinen** manuellen Nachbearbeitungsschritt und keine
vorläufige Datei.

| Feld | immer gesetzt? |
|---|---|
| `rq4_status` (`converged` / `converged_then_rediverged` / `not_converged`) | **ja** |
| `rq4_redivergence`, `rq4_blocks` | **ja** |
| `rq4_convergence_time_ZE`, `rq4_convergence_retrievals` | nur bei `converged` |
| `rq4_plateau_level` | nur wenn ein Plateau gefunden wurde |

Dieselbe Funktion wertet auch die Kalibrationsspuren aus
(`experiments/closeout/analyse_rq4_plateau.py`) — eine Implementierung, zwei
Aufrufer.

**Umgang mit nicht konvergierten Läufen** (unverändert): Seed nicht
austauschen, Lauf nicht löschen, in allen Performance-Auswertungen belassen,
in der RQ4-Auswertung über `rq4_status` getrennt ausweisen.
