# Reproducibility & Common Random Numbers Audit

**Phase 4 – Zufallsinfrastruktur für den späteren Strategievergleich**

**Datum:** 2026-08-21
**Baseline-Commit:** `21d8116` („Fix strategy policy correctness and
deterministic relocation", Branch `working_sim`)
**Vorgänger:** Phase 3B endete mit `READY_FOR_PHASE_4`

## Auftrag und Abgrenzung

Diese Phase korrigiert und validiert ausschließlich die RNG- und
Reproduzierbarkeitsinfrastruktur. Kein Performancevergleich, keine finale
Experimentparametrierung, keine Strategieoptimierung, keine Commits.

Über `baseline_reference`, `popularity_warmup_requests` und
`zipf_parameter` wird hier **nicht** entschieden.

## Umgebung

| | |
|---|---|
| Branch / Commit | `working_sim` @ `21d8116` |
| Python (Auditumgebung) | 3.10.12, pytest 9.1.1 |
| `git status` vor Phase 4 | `D tests/reservation_table.py` (gestagete Löschung aus Phase 2D), `?? .DS_Store` |
| Testsuite vorher | **336 passed** |
| Testsuite nachher | **363 passed** (336 + 27 neue) |

`tests/test_simulation_visual.py` bleibt nicht ausführbar (kein Flask) und
wird nicht mitgezählt.

---

# 1. RNG-Inventar (Zustand vor Phase 4)

| Zufallsgröße | Erzeugende Komponente | Damaliger RNG | Zeitpunkt | Art | Muss policyübergreifend identisch sein? |
|---|---|---|---|---|---|
| Initiale Bin-Verteilung | `config/init_strategy.py::init_random_distribution` | eigener `default_rng(random_seed)` | Konstruktion | exogen | **ja** |
| ABC-Klassen | `config/init_strategy.py::assign_abc_classes` | **kein Zufall** – Funktion von `bin_id` und Schwellen | Konstruktion | deterministisch | ja (trivial) |
| Roboter-Startpositionen | `SimulationEngine._create_robots` | `engine.rng` | Konstruktion | exogen | **ja** |
| Ankunftszeitpunkte (Poisson) | `RequestGenerator._generate_poisson` | **globaler** `np.random` | Konstruktion | exogen | **ja** |
| Angefragte Target-Bin (Zipf) | `config/bin_request_prob_strategy.py` | **globaler** `np.random` | Konstruktion | exogen | **ja** |
| `t_earliest`, Priorität | `RequestGenerator` | **globales** `random`-Modul | Konstruktion | exogen | **ja** |
| Zeitfenster-Rauschen | `RequestGenerator._generate_latest_time` | **globaler** `np.random` | Konstruktion | exogen | **ja** |
| Pickstation-Servicezeit | `ActionCostModel.pickstation_service_duration` | `engine.rng` | **Laufzeit** | exogen | **ja** |
| Blocker-Relocation (RR+RR) | `RelocationSelection.select_temporary_stack` | `engine.relocation_rng` (`default_rng([seed, 1])`, Phase 3B) | Laufzeit | endogen | nein |
| RANDOM-Placement | `PlacementSelector._select_random_stack` | `engine.rng` | Laufzeit | endogen | nein |
| ABC-Tie-Break | `PlacementSelector._select_abc_stack` | `engine.rng` | Laufzeit | endogen | nein |
| Popularity-Tie-Break / Warmup | `PlacementSelector._select_popularity_stack` | `engine.rng` | Laufzeit | endogen | nein |
| Deadlock-Opferwahl „random" | `traffic/deadlock_detector.py::_resolve_random` | **globales** `random`-Modul | Laufzeit | endogen (Plattform) | nein |

## 1.1 Zwei Befunde aus dem Inventar

**P4-01 — `engine.rng` versorgte drei fachlich unabhängige Größen.**
Roboter-Startpositionen (exogen), Servicezeiten (exogen) und sämtliche
Placement-Entscheidungen (endogen) zogen aus demselben Generator. Da die
Policies unterschiedlich oft aus dem Placement ziehen, verschob sich die
Servicezeit-Folge.

Gemessen vor Phase 4 (12×18, 1150 Bins, 5 Roboter, 800 ZE):

| Seed | Anzahl Serviceziehungen je Policy | Übereinstimmung mit A_RR+RR | erste Abweichung |
|---|---|---|---|
| 3 | A 51, B 66, C 50, D 42 | B 16/51, C 20/50, D 18/42 | Position 3 |
| 42 | A 50, B 59, C 42, D 45 | B 23/50, C 15/42, D 24/45 | Position 4–5 |

Ein Vergleich „bei gleichem Seed" verglich also Läufe mit unterschiedlichen
exogenen Bedingungen.

**P4-02 — Der Request-Strom hing am globalen Zufallszustand.**
`RequestGenerator.__init__` rief `np.random.seed()` und `random.seed()` –
prozessweiter Zustand, den sich der Generator unter anderem mit
`traffic/deadlock_detector.py::_resolve_random` teilt. Dass es bisher
funktionierte, lag allein daran, dass der gesamte Request-Strom im
Konstruktor erzeugt wird, bevor irgendein anderer Verbraucher zieht.

**Nicht als Befund gewertet:** `_resolve_random` ist zur Laufzeit
unerreichbar. `TrafficManager` konstruiert den `DeadlockResolver` fest mit
`strategy="lowest_priority"`; nichts setzt `"random"`. Bleibt als latenter
Punkt im Risk Register (R-15), wurde aber nicht umverdrahtet.

**Ebenfalls geprüft, kein Problem:** Initialverteilung, ABC-Klassen und
Request-Strom waren schon vor Phase 4 policyübergreifend identisch –
nachgemessen für die Seeds 3 und 42.

---

# 2. Exogen vs. endogen

| Strom | Inhalt | Art | Anforderung |
|---|---|---|---|
| `initialization` | Bin-Verteilung, Roboter-Startpositionen | exogen | policyübergreifend identisch |
| `requests` | Ankünfte, Target-Bins, Zeitfenster | exogen | policyübergreifend identisch |
| `service` | Pickstation-Bearbeitungszeit je Request | exogen | policyübergreifend identisch |
| `relocation` | zufällige Ablage von Blocking-Bins (RR+RR) | endogen | nur reproduzierbar |
| `placement` | RANDOM-Placement, ABC-/Popularity-Tie-Breaks, Popularity-Warmup | endogen | nur reproduzierbar |

Die ABC-Klassenzuweisung ist **kein** Zufall: `assign_abc_classes` leitet sie
allein aus `bin_id` und den Schwellen ab. Sie ist damit für jeden Seed und
jede Policy identisch – abgesichert durch
`test_abc_classes_are_deterministic_and_seed_independent`.

---

# 3. RNG-Architektur

## 3.1 Vorher

```
config.random_seed
  ├── np.random.default_rng(seed)          -> engine.rng
  │        ├── Roboter-Startpositionen      (exogen)
  │        ├── ActionCostModel Servicezeit  (exogen)   <- verschoben durch
  │        └── PlacementSelector            (endogen)  <- diese Ziehungen
  ├── np.random.default_rng(seed)          -> init_random_distribution
  │        (zweiter Generator mit demselben Seed, also identische Folge)
  ├── np.random.default_rng([seed, 1])     -> RelocationSelection  (Phase 3B)
  └── np.random.seed(seed) / random.seed(seed)  -> globaler Zustand
           └── RequestGenerator
```

## 3.2 Nachher

```
config.random_seed  ->  np.random.SeedSequence(master).spawn(5)
  ├── [0] initialization  -> _create_robots, init_random_distribution
  ├── [1] requests        -> RequestGenerator (numpy + eigener random.Random)
  ├── [2] service         -> ActionCostModel  (nur noch Servicezeiten)
  ├── [3] relocation      -> RelocationSelection
  └── [4] placement       -> PlacementSelector
```

Neu: `config/rng_streams.py` mit der Klasse `RngStreams`.

Wesentliche Eigenschaften:

* **Ein Master-Seed.** Kein Verbraucher baut sich mehr selbst einen
  Generator aus `config.random_seed`.
* **Kein globaler Zustand.** `RequestGenerator` hält eigene Generatoren; der
  Request-Strom ist unabhängig davon, was sonst im Prozess zieht.
* **Unbekannte Stromnamen werfen `KeyError`.** Ein Tippfehler soll nicht
  still einen unkoordinierten Strom erzeugen.
* **`STREAM_NAMES` ist append-only.** Die Reihenfolge bestimmt, welchen
  gespawnten Kindstrom ein Verbraucher bekommt. Einfügen oder Umsortieren
  würde alle bisherigen Läufe unreproduzierbar machen. Im Modul-Docstring
  ausdrücklich festgehalten.

Die Ad-hoc-Ableitung `default_rng([seed, 1])` aus Phase 3B ist in diese
Struktur aufgegangen und **entfernt**.

`engine.rng` existiert weiter, versorgt aber nur noch die Initialisierung.
Roboter-Startpositionen und Bin-Verteilung teilen sich diesen Strom in
fester Reihenfolge – beides exogen, beides einmalig bei der Konstruktion,
kein Policy-Einfluss möglich.

---

# 4. Servicezeit-Semantik

## 4.1 Warum Stream-Trennung allein nicht genügt

Ein eigener `service`-Strom macht die Servicezeiten nur dann
policyübergreifend identisch, wenn auch die **Ziehungsreihenfolge**
policyunabhängig ist. Das war sie nicht: Servicezeiten wurden in der
Reihenfolge gezogen, in der Roboter an den Pickstations eintreffen – und die
hängt vom Verhalten der Policy ab. Zwei Policies mit identischem Seed hätten
weiterhin für denselben Request unterschiedliche Zeiten bekommen, nur mit
anderen Zahlen.

## 4.2 Die Wahl der Identität

Gesucht war eine Entität, deren Menge **und** Identität in allen Policies
gleich ist.

| Kandidat | Geeignet? | Begründung |
|---|---|---|
| Servicejob | nein | Welche Requests gemeinsam bedient werden, hängt vom Timing und damit von der Policy ab. |
| Target-Bin | nein | Wie oft eine Bin physisch geholt wird, hängt vom Batching ab – gemessen 2,4–2,7 Requests je physischem Retrieval, und dieses Verhältnis unterscheidet sich zwischen den Policies. |
| Batch | nein | Existiert erst zur Laufzeit und ist per Definition policyabhängig. |
| **Request** | **ja** | Der komplette Request-Strom wird vor Simulationsbeginn erzeugt und ist bei gleichem Master-Seed über alle Policies identisch – nach Menge, `request_id`, Ankunftszeit und Target-Bin. |

**Gewählt: die `request_id`.**

## 4.3 Umsetzung

Die Bearbeitungszeit wird einmalig beim Erzeugen des Request-Stroms gezogen
(`SimulationEngine._assign_exogenous_service_times`), in Request-Reihenfolge,
aus dem `service`-Strom, und auf `Request.service_time` abgelegt. Zur
Laufzeit wird für Servicezeiten **gar nicht mehr gezogen**.

Die Verteilung bleibt an genau einer Stelle definiert
(`ActionCostModel.pickstation_service_duration`), damit
`pickstation_service_time_min/max` nicht doppelt interpretiert wird.

Damit ist die Realisierung von der Ereignisreihenfolge vollständig entkoppelt:
Es gibt keine Laufzeitziehung mehr, deren Position sich verschieben könnte.
Request 7 hat seinen Wert, bevor die Simulation den ersten Schritt macht.

## 4.4 Fallback

Requests ohne vorgezogene `service_time` (etwa handgebaute Objekte in Tests)
laufen weiter über den alten Laufzeitpfad. Im echten Lauf tritt das nie ein –
abgesichert durch `test_every_generated_request_carries_a_service_time`.

---

# 5. Batching

## 5.1 Fachliche Semantik

Gebatcht werden mehrere Requests auf **dieselbe** Bin. Die Bedienperson
entnimmt dann mehrere Artikel aus einer Bin; ein Request ist ein Griff.
`pickstation_service_time_min/max` beschreibt die Dauer eines Griffs.

Die Gesamtdauer eines Servicejobs ist deshalb die **Summe** der
Bearbeitungszeiten seiner Requests.

## 5.2 Änderung gegenüber vorher

| | vorher | nachher |
|---|---|---|
| Ziehungen je Job | 1 | 0 (vorab je Request) |
| Formel | `base × batch_count` | `sum(r.service_time for r in requests)` |
| Verteilung bei `batch_count = 3` | alle drei Griffe erzwungen gleich lang | drei unabhängige Griffdauern |

Die frühere Form erzwang für alle Requests eines Batches denselben Wert. Das
hatte keine physikalische Begründung, sondern lag daran, dass nur eine
Ziehung zur Verfügung stand.

## 5.3 Deterministisches Beispiel

Drei Requests auf dieselbe Bin mit den Bearbeitungszeiten 4, 6 und 5:

| Aufteilung | Servicejobs | Summe |
|---|---|---|
| alle drei gemeinsam | 15 | 15 |
| erst 1 allein, dann 2+3 | 4 und 11 | 15 |
| jeder einzeln | 4, 6, 5 | 15 |

In allen Fällen trägt jeder Request unverändert seinen eigenen Wert bei.
Unterschiedliche Batching-Zeitpunkte zwischen Policies verschieben deshalb
nichts – sie gruppieren nur anders. Auch die Reihenfolge innerhalb eines
Batches ist ohne Bedeutung.

Abgesichert durch `test_batched_service_duration_is_the_sum_of_the_request_times`.

---

# 6. Tests

Neu: `tests/test_reproducibility_crn.py` – **27 Tests**.

| Bereich | Tests |
|---|---|
| Stream-Struktur | Ströme sind unabhängig und seedabhängig; keine zwei Ströme liefern dieselbe Folge; unbekannter Name wirft; exogen/endogen ist vollständig und überschneidungsfrei; jeder Verbraucher hat seinen eigenen Generator |
| Gleiche Seeds | je Policy identische exogene Inputs (3 Wiederholungen) |
| Verschiedene Seeds | Initiallayout, Roboterpositionen, Request-Strom und Servicezeiten unterscheiden sich jeweils einzeln |
| ABC-Klassen | deterministisch und seedunabhängig – ausdrücklich als Nicht-Zufallsgröße dokumentiert |
| CRN-Kopplung | Initialzustand, Request-Strom und Servicezeiten policyübergreifend identisch; auch nach vollständigen Läufen |
| Entkopplung | 1000 zusätzliche Relocation-Ziehungen verschieben die Servicezeiten nicht; 1000 zusätzliche Placement-Ziehungen verschieben den Request-Strom nicht; 200 Tie-Break-Ziehungen lassen den exogenen Fingerabdruck unverändert |
| Gegenprobe | die Endzustände der vier Policies unterscheiden sich tatsächlich – sonst wäre der CRN-Nachweis wertlos |
| Reproduzierbarkeit | vollständiger Lauf je Policy, 3 Wiederholungen, identischer Endzustand inkl. `access_count`-Verteilung |
| Batching | Summenformel, Reihenfolgeunabhängigkeit, Fallback, alle erzeugten Requests haben eine Zeit |
| Globaler Zustand | Request-Strom bleibt gleich, obwohl `np.random.seed()` und `random.seed()` dazwischen manipuliert werden |

## 6.1 Angepasste bestehende Tests

Die Umstellung der Initialisierung auf einen abgeleiteten Strom ändert das
initiale Layout. 13 bestehende Tests brachen daran, weil sie fest verdrahtete
Stackpositionen (`(3,3)`, `(5,5)`, `(0,0)`) benutzten und stillschweigend
annahmen, dort liege eine Bin.

Diese Tests wurden **nicht abgeschwächt**. Sie stellen ihre Vorbedingung
jetzt explizit her, statt sich auf ein zufälliges Layout zu verlassen – über
`_find_non_empty_stack(...)`. Das Muster existierte bereits seit Phase 2B in
`tests/test_pickup_physical_invariants.py` und wurde auf
`test_evade_hardening.py`, `test_retry_semantics.py` und
`test_move_stall_recovery.py` übertragen. Geprüft wird unverändert dasselbe
Verhalten.

Betroffene Dateien: 4. Geänderte Assertions: keine.

---

# 7. Policyinterne Reproduzierbarkeit

Verglichen wurde jeweils der vollständige Endzustand: abgeschlossene
Requests, Stack-Belegung **und** die Verteilung aller `access_count`.

| Profil | Policy | 3 Wiederholungen | identisch |
|---|---|---|---|
| 12×18, 600 ZE, Seed 3 | A RR+RR | 65 / 65 / 65 | ja |
| | B LR+NR | 93 / 93 / 93 | ja |
| | C ABC+ABC | 64 / 64 / 64 | ja |
| | D POP+POP | 80 / 80 / 80 | ja |
| 20×30, 1000 ZE, Seed 3 | A RR+RR | 187 / 187 / 187 | ja |
| | B LR+NR | 161 / 161 / 161 | ja |
| | C ABC+ABC | 128 / 128 / 128 | ja |
| | D POP+POP | 118 / 118 / 118 | ja |

---

# 8. Policyübergreifende CRN-Prüfung

Der zentrale Erfolgstest. Bei gleichem Master-Seed werden alle vier Policies
gebaut und nur die **exogenen** Größen verglichen.

| Profil | Seed | Initiallayout | Roboterpositionen | Request-Strom | Servicezeiten | Requests |
|---|---|---|---|---|---|---|
| 12×18, 600 ZE | 3 | identisch | identisch | identisch | **identisch** | 350 |
| | 4 | identisch | identisch | identisch | **identisch** | 365 |
| | 42 | identisch | identisch | identisch | **identisch** | 389 |
| 20×30, 1200 ZE | 3 | identisch | identisch | identisch | **identisch** | 687 |
| | 4 | identisch | identisch | identisch | **identisch** | 718 |
| | 42 | identisch | identisch | identisch | **identisch** | 771 |

Zum Vergleich, dieselbe Messung vor Phase 4 (12×18, 800 ZE): Servicezeiten
stimmten je nach Policy nur in 15 bis 24 von rund 50 Werten überein.

## 8.1 Gegenprobe

Die Kopplung wäre wertlos, wenn sich die Policies gar nicht unterschiedlich
verhielten. 12×18, 600 ZE, Seed 3:

```text
abgeschlossene Requests je Policy:
    A_RR+RR 65   B_LR+NR 93   C_ABC+ABC 64   D_POP+POP 80
verschiedene Endzustände: 4 von 4
```

Die Policies treffen also unterschiedlich viele und andere Entscheidungen,
starten Servicejobs in anderer Reihenfolge und Anzahl – und bekommen
trotzdem dieselben exogenen Realisierungen. Genau das war das Ziel.

---

# 9. Systemvalidierung

Alle fünf Konfigurationen (vier Policies plus `baseline_reference`) über
12×18 mit 1150 Bins und 20×30 mit 4320 Bins, jeweils Seeds 3, 4 und 42 –
**30 Läufe**.

| Kriterium | A RR+RR | B LR+NR | C ABC | D POP | X baseline_reference |
|---|---|---|---|---|---|
| Läufe | 6 | 6 | 6 | 6 | 6 |
| Abbrüche | 0 | 0 | 0 | 0 | 0 |
| ungültige Pickups/Drops/Moves/Kollisionen | 0 | 0 | 0 | 0 | 0 |
| Bin verloren / dupliziert | 0 | 0 | 0 | 0 | 0 |
| Ownership-Verletzungen | 0 | 0 | 0 | 0 | 0 |
| Cross-Station-Verwechslung | 0 | 0 | 0 | 0 | 0 |
| Contract-Verletzungen | 0 | 0 | 0 | 0 | 0 |
| `move_stall_recoveries` | 1 | 1 | 18 | 0 | 0 |
| `move_recovery_unresolved` | **0** | **0** | **0** | **0** | **0** |

Kein Lauf hat eine Contract- oder Audit-Invariante verletzt.

---

# 10. Neue Befunde

| ID | Befund | Bereich | Severity | Status |
|---|---|---|---|---|
| **P4-01** | `engine.rng` versorgte Roboterpositionen, Servicezeiten und Placement gemeinsam; Servicezeiten verschoben sich dadurch policyabhängig | INTEGRATION | **BLOCKER** (für den Vergleich) | **FIXED** |
| **P4-02** | Request-Strom hing am globalen `np.random`-/`random`-Zustand | INTEGRATION | MAJOR | **FIXED** |
| **P4-03** | Servicezeiten wurden zur Laufzeit in policyabhängiger Reihenfolge gezogen; Stream-Trennung allein hätte das nicht behoben | INTEGRATION | **BLOCKER** (für CRN) | **FIXED** |
| **P4-04** | Batch-Servicezeit war `eine Ziehung × batch_count` und erzwang identische Griffdauern innerhalb eines Batches | STRATEGY (Modell) | MINOR | **FIXED**, Modelländerung dokumentiert |
| **P4-05** | `traffic/deadlock_detector.py::_resolve_random` zieht aus dem globalen `random`-Modul. Zur Laufzeit unerreichbar, weil `TrafficManager` fest `strategy="lowest_priority"` setzt | PLATFORM | MINOR (latent) | **OPEN**, bewusst nicht umverdrahtet |
| **P4-06** | Die Umstellung der Initialisierung ändert das initiale Layout gegenüber `21d8116`. Messwerte aus Phase 3B sind mit den heutigen nicht direkt vergleichbar | CONFIG | MINOR | dokumentiert |

---

# 11. Risk Register

R-1 bis R-14 aus Phase 3B bleiben bestehen. Keine Risiken wurden entfernt.

| # | Risiko | Status |
|---|---|---|
| R-1 | MOVE-Stall-Recovery: Schwelle 120 ZE, aus 4 Seeds abgeleitet | offen |
| R-2 | Begrenztes internes Stallfenster. Größtes Innenfenster in Phase 4: 113 ZE (C_ABC+ABC, `final`, Seed 42) | offen |
| R-3 | Recovery-Metriken je Policy mitführen | umgesetzt; `unresolved = 0` in allen 30 Läufen |
| R-4 | **RNG / Common Random Numbers** | **weitgehend geschlossen.** Exogene Größen sind policyübergreifend identisch, jede Policy ist für sich reproduzierbar, der globale Zufallszustand ist entfallen. Reststatus siehe R-16. |
| R-5 | Legacy `pickup_from_pickstation` | offen, unverändert |
| R-6 | AUDIT-008: unsauberer Bin-Status während Return | offen, weiterhin ohne nachgewiesene Wirkung |
| R-7 | Komplett volles Lager: Modellgrenze | offen |
| R-8 | `test_simulation_visual.py` nicht ausführbar (kein Flask) | offen |
| R-9 | `baseline_reference` unterscheidet sich von RR+RR in zwei Dimensionen | offen, fachliche Entscheidung |
| R-10 | Konzentration von ABC auf wenige Zielstacks (8–21 distinkte Ziele) | offen; NEAREST ist seit Phase 3B entspannt (18–28) |
| R-11 | Unterschiedliche Eligibility zwischen Initialisierung und Placement | offen |
| R-12 | `popularity_warmup_requests = 50` gegen eine batching-verlangsamte Größe kalibriert | offen. Phase 4 hat nur sichergestellt, dass die Warmup-Zufälligkeit aus dem `placement`-Strom kommt und keine exogene Größe verschiebt. Keine Neukalibrierung. |
| R-13 | LR+NR-Replanning bei dichten Originalregionen | offen, nicht optimiert |
| R-14 | Ownership-Freigabe hängt an der `active_queue`-Injektion | offen. Die RNG-Änderungen haben hier keinen Fehler ausgelöst (0 Ownership-Verletzungen in 30 Läufen). |
| R-15 | **neu:** `_resolve_random` zieht aus dem globalen `random`-Modul. Aktuell unerreichbar; würde `deadlock_resolution_strategy = "random"` je konfigurierbar, müsste der Resolver einen eigenen Strom bekommen | offen (latent) |
| R-16 | **neu:** Reststatus zu R-4. Roboter-Startpositionen und Bin-Verteilung teilen sich den `initialization`-Strom in fester Reihenfolge. Das ist für den Policyvergleich unkritisch (beide exogen, beide bei der Konstruktion), verhindert aber, dass man die Roboterzahl variiert, ohne die Bin-Verteilung zu verschieben. Für Sensitivitätsläufe über `num_robots` wäre ein eigener Strom nötig | offen |
| R-17 | **neu:** `STREAM_NAMES` ist append-only. Einfügen oder Umsortieren eines Stromnamens macht alle bisherigen Läufe unreproduzierbar. Im Modul dokumentiert, aber nicht technisch erzwungen | offen |

---

# 12. Readiness Gate

| Kriterium | Ergebnis |
|---|---|
| Jede Policy für sich deterministisch reproduzierbar | **ja** – 4 Policies × 3 Wiederholungen in zwei Profilen, Endzustand inkl. `access_count` identisch |
| Initialzustand policyübergreifend identisch | **ja** – Layout, Roboterpositionen, ABC-Klassen |
| Request-Strom policyübergreifend identisch | **ja** – 6 Seed/Profil-Kombinationen |
| Exogene Größen nicht von Strategy-RNG-Aufrufen beeinflusst | **ja** – 1000 zusätzliche Relocation-/Placement-Ziehungen lassen sie unverändert |
| Servicezeiten korrekt als Common Random Numbers gekoppelt | **ja** – identisch über alle vier Policies, bis 771 Requests je Lauf |
| Batching zerstört die Kopplung nicht | **ja** – Summenformel je Request, deterministisch belegt |
| Alle Tests grün | **ja** – 363 passed |
| Keine neuen Correctness-Verletzungen | **ja** – 30 Systemläufe ohne Befund |

## Urteil

```text
READY_FOR_EXPERIMENT_DESIGN
```

Begründung: Die exogenen Zufallsgrößen sind bei gleichem Master-Seed über
alle vier Policies identisch – Initialzustand, Request-Strom und
Servicezeit-Realisierungen. Das gilt, obwohl sich die Policies nachweislich
unterschiedlich verhalten (4 von 4 verschiedene Endzustände, 64 bis 93
abgeschlossene Requests bei identischem Seed). Jede Policy ist zugleich für
sich vollständig reproduzierbar.

Der entscheidende Schritt war nicht die Stream-Trennung, sondern die Bindung
der Servicezeit an die `request_id`: Sie ist die einzige Entität, deren Menge
und Identität in allen Policies gleich ist.

Offen bleiben R-1 bis R-17. Keines davon verhindert das Experimentdesign.
R-16 und R-17 sind unmittelbare Folgen der neuen Struktur und sollten
bekannt sein, bevor jemand Ströme ergänzt oder die Roboterzahl variiert.

## Empfohlener nächster Schritt

Experimentdesign. Drei fachliche Entscheidungen stehen dabei an, die diese
Phase bewusst offengelassen hat:

1. Ist `baseline_reference` Teil des Vergleichs? (R-9)
2. Wird `popularity_warmup_requests` an die batching-korrigierte Zugriffsrate
   angepasst? (R-12)
3. Macht `zipf_parameter = 1.5` bei 98,5 % Nachfrageanteil der A-Klasse die
   Unterschiede zwischen den Policies noch sichtbar? (P3-10)

Erst danach Seedzahl, Laufzeit und Einschwingphase festlegen. Für
Sensitivitätsläufe über `num_robots` wäre vorher R-16 zu klären.

Es wurden **keine Git-Commits oder Pushes** ausgeführt und **kein
Performancevergleich** begonnen.
