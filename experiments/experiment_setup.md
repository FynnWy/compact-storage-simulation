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

Damit ergibt sich eine maximale Lagerkapazität von

\[
C_{\max} = 20 \times 30 \times 8 = 4800 \text{ Bins}.
\]

Das Grid ist rechteckig, mit einer längeren Seite in y-Richtung. Dies erlaubt
eine platzierungsnahe Umsetzung der Empfehlung aus der Literatur, Pickstationen
in der Mitte einer Systemseite bzw. auf gegenüberliegenden Seiten zu platzieren.

## Bin-Anzahl und physische Auslastung

Die Anzahl der Bins wird so gewählt, dass das Lager stark ausgelastet, aber
nicht vollständig gefüllt ist:

- Füllgrad: ca. 90 %
- Bin-Anzahl: `bin_num = 4320 ≈ 0.9 · C_max`

Damit sind die meisten Stacks bis nahe an die maximale Höhe belegt, es
existieren jedoch noch ausreichend freie Top-Positionen, um Relocations von
Blocking-Bins durchführen zu können. Dieses Setting erzeugt ein realistisch
„dichtes“ Lager und macht Unterschiede in Reordering- und
Target-Bin-Placement-Strategien messbar.

## Pickstations und Roboter

Es werden zwei Pickstations eingesetzt:

- Anzahl Pickstations: `num_pickstations = 2`
- Kapazität pro Pickstation: `pickstation_capacity = 1`

Die Platzierung erfolgt in der Simulation-Engine wie folgt:

- Spezialfall `num_pickstations == 2`:
  - Zwei Pickstations werden auf gegenüberliegenden Seiten des Grids platziert,
    jeweils in der geometrischen Mitte:
    - Untere Seite: `(x_center, -1)`
    - Obere Seite: `(x_center, grid_depth)`
    mit `x_center = grid_width // 2`.

Damit werden zwei „Ports“ an gegenüberliegenden Seiten realisiert, wie es in
der Literatur zur Maximierung der Durchsatzkapazität beschrieben wird.

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

Die drei Strategien werden über die `ExperimentConfig` ausschließlich über
die Reordering- und Placement-Strategien unterschieden:

- Baseline:
  - `reordering_strategy = "LOFI"`
  - `placement_strategy = "RANDOM"`
- ABC Policy:
  - `reordering_strategy = "ABC"`
  - `placement_strategy = "ABC"`
- Popularity Policy:
  - `reordering_strategy = "POPULARITY"`
  - `placement_strategy = "POPULARITY"`

Alle übrigen Parameter (Grid, Füllgrad, Roboterzahl, Pickstations,
Nachfrageprozess, Kostenparameter) werden aus der gemeinsamen
Basis-Konfiguration (`create_base_config()`) übernommen und sind somit für
alle Strategien und Seeds identisch. Dadurch sind die beobachteten
Unterschiede in Digging-Depth, Throughput, Reshuffling-Verhalten und
Bin-Verteilung direkt auf die untersuchten Strategien zurückzuführen.