# Simulationsszenario und Parametrisierung

Dieses Dokument beschreibt das Basisszenario, das für alle drei Strategien
(Baseline, ABC Policy, Popularity Policy) in den Experimenten verwendet wird.
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

Da jedoch zwei Grid-Zellen von Pickstations belegt sind, ist die
**effektive** Lagerkapazität

\[
C_{\text{effektiv}} = (20 \times 30 - 2) \times 8 = 4784 \text{ Bins}.
\]

Die Initialisierungslogik (`init_random_distribution`) verwendet ausschließlich
echte Storage-Positionen (d.h. keine Port-/Pickstation-Zellen) und berechnet
die verfügbare Kapazität genau auf Basis dieser effektiven Stack-Anzahl.

## Bin-Anzahl und physische Auslastung

Die Anzahl der Bins wird so gewählt, dass das Lager stark ausgelastet, aber
nicht vollständig gefüllt ist:

- Füllgrad: ca. 90 %
- Bin-Anzahl: `bin_num = 4320`

Bezogen auf die **effektive** Kapazität (ohne Pickstation-Zellen) ergibt sich:

\[
\text{Füllgrad} \approx \frac{4320}{4784} \approx 0{,}90.
\]

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
- Zipf-Parameter: `zipf_parameter = 1.5`

Damit entstehen „Hot Bins“, die wesentlich häufiger angefragt werden als der
Durchschnitt. Dies ist eine notwendige Voraussetzung, um die Effekte der
ABC- und Popularity-basierten Strategien auf Digging-Depth, Reshuffling-
Verhalten und räumliche Bin-Verteilung untersuchen zu können.

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
- und vor allem einen **fairen Vergleich** der drei Strategien
  (Baseline, ABC, Popularity) ermöglichen, da alle Strategien im exakt
  gleichen Kostenmodell laufen.

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

1. alle drei Strategien auf der **gleichen normierten Skala** bewertet werden,
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

Ob `baseline` Teil des finalen Vergleichs sein soll, ist eine offene
fachliche Frage.

Alle übrigen Parameter (Grid, Füllgrad, Roboterzahl, Pickstations,
Nachfrageprozess, Kostenparameter) werden aus der gemeinsamen
Basis-Konfiguration (`create_base_config()`) übernommen und sind somit für
alle Strategien und Seeds identisch. Dadurch sind die beobachteten
Unterschiede in Digging-Depth, Throughput, Reshuffling-Verhalten und
Bin-Verteilung direkt auf die untersuchten Strategien zurückzuführen.