# Strategy Correctness Audit

**Phase 3 – fachliche Korrektheit der vorgesehenen Relocation-/Return-Policies**

**Datum:** 2026-08-21
**Baseline-Commit:** `bfe2a99` („Harden MOVE stall recovery to prevent
multi-robot port congestion", Branch `working_sim`)
**Vorgänger:** Phase 2D endete mit `READY_FOR_STRATEGY_AUDIT`

## Auftrag und Abgrenzung

Dies ist ein **Audit**, kein Strategievergleich. Es wurde keine
Performance-Rangfolge gebildet, keine Strategie optimiert, keine
Common-Random-Numbers-Änderung vorgenommen und **kein Produktionscode
geändert**. Gefundene Fehler wurden reproduziert, in der Ursache eingegrenzt,
klassifiziert und dokumentiert – nicht behoben.

## Umgebung

| | |
|---|---|
| Branch / Commit | `working_sim` @ `bfe2a99` |
| Python (Auditumgebung) | 3.10.12, pytest 9.1.1 |
| Python (Projekt-venv) | 3.9 (`.venv`, laut `__pycache__`-Artefakten) |
| `git status` vor dem Audit | `D tests/reservation_table.py` (gestagete Löschung aus Phase 2D), `?? .DS_Store` |
| Testsuite vor dem Audit | **291 passed** (ohne `tests/test_simulation_visual.py`) |
| Testsuite nach dem Audit | **320 passed, 6 xfailed** |

`tests/test_simulation_visual.py` ist weiterhin **nicht ausführbar**
(`ModuleNotFoundError: No module named 'flask'`) und wird nicht als bestanden
gezählt.

---

# 1. Tatsächliche Strategy-Architektur

## 1.1 Verdrahtung

```
SimulationEngine._build_*  (simulation_engine.py:154-180)
├── RelocationSelection(cost_model=…, active_queue=…)      ← KEIN rng-Argument
├── PlacementSelector(config=…, rng=self.rng)
├── ReorderingSelector(config=…)
└── TopAccessStrategy(relocation_selector, placement_selector,
                      reordering_selector, …)
        └── wird an Scheduler übergeben  →  engine.scheduler.strategy
```

Die Policy-Auswahl erfolgt ausschließlich über drei Config-Felder:
`reordering_strategy`, `placement_strategy`, `return_blocking_bins`.

## 1.2 Mapping-Tabelle

| Policy | Relocation der Blocker | `return_blocking_bins` | Blocker-Reordering | Target-Placement | Aktive Klassen / Funktionen |
|---|---|---|---|---|---|
| **A RR+RR** | zufällig aus zulässigen Kandidaten | `False` | entfällt (`clear_all_relocations`) | zufälliger Stack mit Kapazität | `RelocationSelection.select_temporary_stack` (RR-Zweig, Zeile 152), `PlacementSelector._select_random_stack` |
| **B LR+NR** | kostenbasiert (Manhattan + Nachbarbonus) | `False` | entfällt | **nächster Stack zur PICKSTATION** | `RelocationSelection.select_temporary_stack` (Default-Zweig), `PlacementSelector._select_nearest_stack` |
| **C ABC+ABC** | kostenbasiert | `True` | `C → B → A` | Greedy-Score je Klasse | `ReorderingSelector._reorder_abc`, `PlacementSelector._select_abc_stack` |
| **D POP+POP** | kostenbasiert | `True` | `access_count` aufsteigend | Score aus Distanz + Tiefe, Hot/Cold/Neutral | `ReorderingSelector._reorder_popularity`, `PlacementSelector._select_popularity_stack` |
| *X baseline* | kostenbasiert | `True` | LOFI (umgekehrte Auslagerungsreihenfolge) | zufälliger Stack | `_reorder_lofi`, `_select_random_stack` |

## 1.3 Fallbacks, Tie-Breaks, RNG-Aufrufe

| Ort | Verhalten |
|---|---|
| `RelocationSelection` RR-Zweig | Aktiv **nur** bei `placement_strategy == "RANDOM"` **und** `return_blocking_bins is False`. Ziehung über `self.rng` (siehe Befund P3-03). |
| `RelocationSelection` Default-Zweig | `sort` nach geschätzten Kosten, erster Treffer. Tie-Break implizit über Iterationsreihenfolge des Grids – deterministisch. |
| `_select_random_stack` | `self.rng.integers(len(candidates))`, **ohne** Pufferzonen-Filter (bewusst dokumentiert). |
| `_select_nearest_stack` | Sortierschlüssel `(distanz_zur_pickstation, y, x)`. Kein RNG. |
| `_select_abc_stack` | Greedy-Argmin/Argmax; bei Gleichstand `self.rng.integers(len(best))`. |
| `_select_popularity_stack` | Warmup-Fallback auf `_select_random_stack`; sonst Greedy; bei Gleichstand RNG. |
| `_reorder_*` | `sorted()` – stabil, kein RNG. |
| `zipf_bin_sampling` | globaler NumPy-RNG, in `RequestGenerator.__init__` via `np.random.seed(config.random_seed)` gesetzt. Deterministisch. |

## 1.4 Abweichungen zwischen Dokumentation und Code

| # | Dokumentation | Code | Bewertung |
|---|---|---|---|
| 1 | `experiments/experiment_setup.md` beschreibt **drei** Strategien (Baseline, ABC, Popularity) | `run_experiments.py` definiert **fünf** Experimente – zusätzlich `RR+RR` und `LR+NR` | Doku unvollständig, siehe P3-08 |
| 2 | `ExperimentConfig.placement_strategy` Docstring: `"ORIGINAL", "RANDOM", "ABC", "POPULARITY"` | `NEAREST` wird in `run_experiments.py` verwendet und in `PlacementSelector` unterstützt | Doku unvollständig |
| 3 | Auftragsvorgabe NR: „minimale Manhattan-Distanz **zum Originalstack**" | `_select_nearest_stack` misst zur **Pickstation** und nimmt `original_stack_id` nicht entgegen | **Befund P3-04** |
| 4 | `experiment_setup.md` erwähnt `return_blocking_bins` nicht | Der Schalter unterscheidet A/B von C/D fundamental | Doku unvollständig |
| 5 | Trello nennt für ABC-Placement u.a. Zonen/Terzile | Implementiert ist ein **Greedy-Score** über alle zulässigen Stacks, keine Zonen | Keine Abweichung im Sinne eines Fehlers – aber die tatsächliche Variante muss beim Auswerten benannt werden |
| 6 | `RelocationSelection`-Docstring: Kostenmodell wird genutzt, „falls kompatibel" | `ActionCostModel` besitzt kein `estimate_relocate_cost` | **Befund P3-07** |

---

# 2. Tatsächliche Semantik der vier Policies

## 2.1 A – RR+RR (Random Relocation + Random Return)

**Erzeugung der Random Relocation.** Nicht durch die Placement-Strategie,
sondern durch einen expliziten Sonderzweig in
`RelocationSelection.select_temporary_stack`:

```python
if placement_strategy == "RANDOM" and return_blocking_bins is False:
    index = int(self.rng.integers(len(candidate_stacks)))
    return candidate_stacks[index]
```

Beide Bedingungen müssen erfüllt sein. Die Baseline-Konfiguration
(`LOFI/RANDOM` mit `return_blocking_bins=True`) trifft diesen Zweig **nicht**
und benutzt die kostenbasierte Relocation – Baseline und RR+RR unterscheiden
sich also in zwei Dimensionen gleichzeitig.

Kandidaten sind gefiltert auf: nicht Quellstack, nicht gesperrt, freie
Kapazität, keine Pufferzone, kein „kritischer" Stack. **Verifiziert:** alle
gezogenen Ziele erfüllen sämtliche Kriterien (Test
`test_random_relocation_uses_only_admissible_candidates`).

**Random Return.** `_select_random_stack` über alle nicht gesperrten Stacks
mit Kapazität. Bewusst **ohne** Pufferzonen-Filter – im Code als Absicht
dokumentiert.

**Blocker bleiben liegen.** `_next_restore_blockers_action` ruft bei
`return_blocking_bins=False` sofort `task.clear_all_relocations()`.
**Verifiziert:** 0 Blocker-Rücklagerungen in 67 Läufen.

## 2.2 B – LR+NR (Local Relocation + Nearest Return)

**Local Relocation** ist eine Kostenfunktion aus Manhattan-Distanz vom
Quellstack plus einem Bonus von `-1` für direkte Nachbarn. Das injizierte
`ActionCostModel` wird faktisch nie verwendet (P3-07), Stapeltiefe und
Armkosten gehen also **nicht** ein.

**Nearest Return** misst die Distanz zur nächstgelegenen **Pickstation**, nicht
zum Originalstack (P3-04). Wirkung in den Läufen:

| Profil | Ziel-Rücklagerungen | distinkte Zielstacks |
|---|---|---|
| `final` (20×30), Seed 3 | 646 | **9** |
| `final` (20×30), Seed 42 | 590 | **8** |
| über alle 67 Läufe | – | min 1 / median 6 / max 13 |

Zum Vergleich erreicht X_baseline (RANDOM) 18–53 distinkte Ziele, A_RR+RR bis
326. NR konzentriert praktisch die gesamte Rücklagerung auf die wenigen Zellen
am Rand der Pufferzone um die beiden Ports.

## 2.3 C – ABC+ABC

**Reordering** ist korrekt: `class_priority = {"C": 0, "B": 1, "A": 2}`,
`sorted()` ist stabil. `[A, C, B] → [C, B, A]`; die erste Bin wird zuerst
zurückgelegt und liegt damit unten. **A landet oben, C unten.** Verifiziert.

**Klassensemantik.** `assign_abc_classes` vergibt A an niedrige `bin_id`;
`zipf_bin_sampling` zieht niedrige Indizes mit höherer Wahrscheinlichkeit.
Beide Annahmen passen zusammen. Gemessen am tatsächlichen Nachfragestrom
(20×30, 4320 Bins, Zipf 1.5, Seed 42, 2000 ZE, 1172 Requests):

| Klasse | Bin-Anteil | Nachfrageanteil |
|---|---|---|
| A | 20,0 % | **98,5 %** |
| B | 30,0 % | 1,1 % |
| C | 50,0 % | 0,4 % |

Richtung korrekt und monoton. Die Konzentration ist allerdings extrem – siehe
Befund P3-10.

`abc_class` ist **statisch**: einmalig in `initialize_bins` gesetzt, danach
nirgends verändert. Verifiziert.

**Placement-Variante.** Implementiert ist **kein** Zonen-/Terzilmodell, sondern
ein Greedy-Score über alle zulässigen Stacks:

| Klasse | Zielfunktion |
|---|---|
| A | minimiert `distanz + stackhöhe` |
| B | minimiert `abs(distanz − median_distanz)` |
| C | maximiert `distanz` |

Gleichstand wird per RNG aufgelöst. Distanz immer zur **nächsten** Pickstation
(`get_min_distance_to_pickstation`), bei zwei Ports korrekt verifiziert.

Folge dieser Variante: A-Bins laufen alle auf denselben aktuell besten Stack,
bis dieser voll ist. Distinkte Zielstacks je Lauf: min 8 / median 20 / max 28.
Das ist eine Eigenschaft der gewählten Variante, kein Fehler – es muss beim
Auswerten aber als „Greedy" und nicht als „Zonen" beschrieben werden.

## 2.4 D – POPULARITY+POPULARITY

**Diese Policy ist derzeit wirkungslos.** Ursache ist Befund P3-01.

`increment_access_count()` wird an genau einer Stelle aufgerufen
(`event_handler.py:2796`) – innerhalb von `_handle_robot_action`. Diese Methode
wird zur Laufzeit nur noch für den Legacy-Pfad `pickup_from_pickstation`
erreicht. Gemessen (12×18, 5 Roboter, Seed 42, 800 ZE):

```text
DROP:relocate                        16
DROP:remove_target                  135
DROP:return                          70
PICKUP:relocate                      16
PICKUP:remove_target                 59
PICKUP:return                       435
ROBOT_ACTION:pickup_from_pickstation 21     <- einziger Aufrufgrund
requests_completed: 109
Summe access_count über alle Bins:    0
```

Damit gilt in **jedem** Lauf `access_count == 0` für alle Bins. Konsequenzen:

1. `_reorder_popularity` sortiert nach einem konstanten Schlüssel. `sorted()`
   ist stabil, also bleibt die Auslagerungsreihenfolge erhalten. Das ist weder
   Popularity-Reordering noch LOFI (LOFI kehrt die Reihenfolge um) – die
   oberste Bin landet unten.
2. `_select_popularity_stack` sieht dauerhaft `max_count == 0` und fällt
   **immer** auf `_select_random_stack` zurück. Gemessen: 113 von 113 Aufrufen
   im finalnahen Lauf, 74 von 74 im mittleren Lauf.

D_POP+POP ist faktisch „keine Umsortierung + RANDOM-Placement".

Die Hot/Cold-Logik selbst ist plausibel implementiert (Score aus normierter
Distanz und normierter erwarteter Grabtiefe, Schwellen 0.7/0.3, Gewichte je
0.5, `expected_digging_depth = aktuelle Stackhöhe`) und wurde isoliert gegen
künstlich gesetzte `access_count`-Werte geprüft – dort verhält sie sich
korrekt (heiße Bin näher an der Pickstation als kalte).

**Kein Look-ahead.** Keine der vier Strategiedateien referenziert
`future_request_queue`. Als Test hinterlegt
(`test_strategies_never_read_the_future_request_queue`).

---

# 3. Gemeinsamer Correctness-Contract

## 3.1 Prüfumfang

Für jede geplante `relocate`- und `return`-Aktion wurde geprüft: Stack
existiert, liegt im Grid, ist nicht gesperrt, hat freie Kapazität, ist keine
Portzelle, liegt nicht in der Port-Pufferzone (dort, wo die Policy das
zusichert), und ist nie der Quellstack.

Am Laufende zusätzlich: Bin-Eindeutigkeit, Bin-Erhaltung, keine getragene Bin
zugleich im Stack, keine Stacks über Kapazität, keine Bins auf Portzellen,
offene `temp_storage`-Einträge, verwaiste Blocker-Ownership.

Parallel liefen die Invarianten aus `tests/audit_harness.py`
(physikalisch gültige Pickups/Drops/Moves, Positionskollisionen,
Task-Doppelvergabe, Pickstation-Invarianten, Blocker-Ownership).

**Zwei Fehlalarme des Harness wurden vor der Bewertung korrigiert:**

* Blocker-Rücklagerungen gehen per Definition auf den **Originalstack**
  zurück. Der darf in der Pufferzone liegen, weil die Initialverteilung nur
  `grid.is_storage_position` prüft. Ursprünglich als Verstoß gezählt – ist
  keiner.
* `State` trägt kein Attribut `max_stack_height`; die Selektoren lesen es über
  `state.config`. Die erste Fassung der Kapazitätsprüfung lief dadurch ins
  Leere und wurde korrigiert. Nach der Korrektur trat **keine** Verletzung auf.

## 3.2 Ergebnis

| Kriterium | A RR+RR | B LR+NR | C ABC | D POP | X baseline |
|---|---|---|---|---|---|
| Läufe | 67 | 67 | 67 | 67 | 66 |
| Abbrüche | **5** | **5** | 0 | 0 | 0 |
| ungültige Pickups/Drops/Moves/Kollisionen | 0 | 0 | 0 | 0 | 0 |
| Ziel über Kapazität | 0 | 0 | 0 | 0 | 0 |
| Ziel = Portzelle | 0 | 0 | 0 | 0 | 0 |
| Ziel außerhalb Grid | 0 | 0 | 0 | 0 | 0 |
| Relocation auf Quellstack | 0 | 0 | 0 | 0 | 0 |
| Bin verloren / dupliziert | 0 | 0 | 0 | 0 | 0 |
| Blocker-Return trotz `rbb=False` | 0 | 0 | – | – | – |
| Blocker mehrfach restored | 0 | 0 | 0 | 0 | 0 |
| `BLOCKER_OWNERSHIP_ORPHAN` | **60** | **29** | 0 | 0 | 0 |
| Placement in Pufferzone (unzulässig) | – | 0 | 0 | **596** | – |
| `move_stall_recoveries` | 25 | 33 | 9 | 5 | 4 |
| `move_recovery_unresolved` | 0 | **1** | 0 | 0 | 0 |
| Cross-Station-Verwechslung | 0 | 0 | 0 | 0 | 0 |

Gefahrene Szenarien: 7×7 (100 und 240 Bins, 2/3/4 Roboter, `util` 0.5 und
2.0), 12×18 mit 1150 Bins, 20×30 mit 4320 Bins und 8 Robotern; Seeds
1, 2, 3, 4, 7, 42, 99; jeweils 2 Pickstations. Seeds 3 und 4 sind wegen der
Stallhistorie aus Phase 2C/2D durchgängig enthalten.

## 3.3 `return_blocking_bins = False` im Detail

Die Restore-Verpflichtung wird korrekt verworfen: `task.temp_storage` ist
danach leer, `blockers_reordered` wird gesetzt, es folgen keine
Blocker-Rücklagerungen.

**Aber:** die globale Sperre in `ActiveQueue._blocker_ownership` bleibt
bestehen (Befund P3-02). Gemessen im Profil `mittel`:

| Policy | verwaiste Ownerships je Lauf | max. gleichzeitig | Lebensdauer Median / Max |
|---|---|---|---|
| A RR+RR, Seed 42 | 17 | 5 | 29 / 57 ZE |
| A RR+RR, Seed 3 | 25 | 9 | 35 / 53 ZE |
| B LR+NR, Seed 42 | 15 | 6 | 22 / 62 ZE |
| B LR+NR, Seed 3 | 32 | 10 | 47 / 113 ZE |
| X baseline (`rbb=True`) | **0** | 0 | – |

Die Sperre endet erst mit `ActiveQueue.mark_completed()` des besitzenden
Requests. In diesem Fenster sind die betroffenen Bins global reserviert und
ihre Stacks als Relocation-Ziel ausgeschlossen.

## 3.4 `return_blocking_bins = True` im Detail

Alle offenen Blocker werden genau einmal je Task zurückgelegt – über alle 134
Läufe von C und D kein einziger Doppel-Restore. Die am Laufende noch offenen
`temp_storage`-Einträge (42 bzw. 37 über alle Läufe) gehören zu Tasks, die zum
Abbruchzeitpunkt der Simulation noch in Arbeit waren, und sind kein Leck.

---

# 4. Befunde

## P3-01 — `access_count` wird nie erhöht; POPULARITY ist wirkungslos

* **Verantwortungsbereich:** INTEGRATION (Wirkung auf STRATEGY)
* **Severity:** **BLOCKER**
* **Betroffen:** Policy D (POPULARITY+POPULARITY), außerdem alle
  popularitätsbasierten Auswertungen

`increment_access_count()` steht ausschließlich im Legacy-Zweig
`_handle_robot_action` (`event_handler.py:2781-2796`). Der aktive
Zwei-Phasen-Pfad behandelt `remove_target` in `_handle_robot_drop`
(`event_handler.py:1731-1748`) und zählt dort zwar Digging-Depth und
Pickstation-Ankunft mit, aber **nicht** den Zugriff.

Es fehlt genau eine Zeile im Live-Pfad. Nachweis: 109 abgeschlossene Requests,
`sum(access_count) == 0`.

Folgewirkungen: Reordering ohne Effekt, Placement dauerhaft im RANDOM-Fallback
(113/113 Aufrufe), und die Metrik „Korrelation `access_count` ↔ Grabtiefe" in
`metrics/distribution_metrics.py` ist ebenfalls degeneriert.

**Tests:** `test_access_count_increases_on_real_retrievals`,
`test_popularity_placement_leaves_warmup_in_a_realistic_run` (beide `xfail`).

## P3-02 — Verworfene Restore-Pflicht gibt die globale Blocker-Ownership nicht frei

* **Verantwortungsbereich:** INTEGRATION
* **Severity:** **BLOCKER**
* **Betroffen:** Policies A und B (alle Konfigurationen mit `return_blocking_bins=False`)

`RobotTask.clear_all_relocations()` leert `self.temp_storage`, ruft aber nicht
`ActiveQueue.release_blocker_ownership(bin_id)`. Die Bin bleibt global
reserviert, obwohl kein Task sie mehr zurücklegen wird. Das verletzt die
projekteigene Invariante `BLOCKER_OWNERSHIP_ORPHAN` aus
`tests/audit_harness.py` – 89 Verletzungen über 134 Läufe von A und B, null
bei C, D und der Baseline.

**Folgewirkung mit Abbruch.** `Scheduler._try_schedule_opportunistic` fragt
`get_blocker_owner()` und ruft dann `RobotTask.release_blocker_ownership()`.
Diese Methode wirft, wenn die Bin nicht mehr in `temp_storage` steht:

```text
RuntimeError: Cannot release ownership of bin 125 from task 0:
              bin not found in temp_storage
```

Der umgebende Code ist als „✅ DEFENSIV" kommentiert und prüft
`if released is not None` – die Methode gibt jedoch nie `None` zurück, sondern
wirft. Die Absicherung greift daher nicht.

**10 von 134 Läufen** der Policies A und B brachen so ab, verteilt über
`dicht_r3`, `dicht_r4`, `dicht_r3_util2`, `klein_r3_util2` und
`klein_r4_util2`.

**Tests:** `test_discarding_restores_also_releases_global_blocker_ownership`
(`xfail`), `test_orphaned_ownership_makes_the_transfer_path_raise`
(deterministische Reproduktion, grün).

## P3-03 — `RelocationSelection` benutzt einen ungeseedeten RNG

* **Verantwortungsbereich:** INTEGRATION
* **Severity:** **BLOCKER** (für Phase 4 zwingend)
* **Betroffen:** Policy A (einzige Policy, die den Zufallszweig erreicht)

In `simulation_engine.py:154` wird `RelocationSelection(...)` **ohne**
`rng=self.rng` konstruiert. Der Konstruktor fällt auf
`np.random.default_rng()` ohne Seed zurück. `PlacementSelector` erhält den
Engine-RNG korrekt.

Nachweis – drei Läufe, identischer Seed 42:

| Policy | `requests_completed` | Endlayout identisch |
|---|---|---|
| A RR+RR | 21 / 23 / 23 | **nein** |
| B LR+NR | 22 / 22 / 22 | ja |
| C ABC+ABC | 24 / 24 / 24 | ja |
| D POP+POP | 24 / 24 / 24 | ja |
| X baseline | 25 / 25 / 25 | ja |

Die Streuung ist nicht kosmetisch. Zwei Läufe von A_RR+RR im Profil `final`,
Seed 3, lieferten `requests_completed` 155 bzw. 67 und ein terminales
No-Progress-Fenster von 5 bzw. 331 ZE.

Damit ist Policy A weder reproduzierbar noch für Common Random Numbers
geeignet, und jede Einzelmessung an ihr ist eine Stichprobe unbekannter
Varianz.

**Tests:** `test_relocation_selection_uses_the_seeded_engine_rng`,
`test_rr_rr_is_reproducible_for_a_fixed_seed` (beide `xfail`).

## P3-04 — NEAREST misst zur Pickstation statt zum Originalstack

* **Verantwortungsbereich:** STRATEGY
* **Severity:** **MAJOR**
* **Betroffen:** Policy B (LR+NR)

`_select_nearest_stack(self, state)` nimmt `original_stack_id` gar nicht
entgegen und sortiert nach
`(get_min_distance_to_pickstation(pos), y, x)`.

Die fachliche Vorgabe für NR lautet „minimale Manhattan-Distanz zum
Originalstack, Tie-Break y dann x; der Originalstack gewinnt mit Distanz 0".
Implementiert ist eine andere Policy: „so nah wie möglich an den Port".

Wirkung: 1 bis 13 distinkte Zielstacks je Lauf; im finalnahen Setup 8–9 Ziele
für ~600 Rücklagerungen. Die Rücklagerung ist damit kein
strukturerhaltendes Verfahren mehr, sondern eine Konzentration am Port.

Der Tie-Break (y, x) und der Determinismus sind korrekt implementiert.

**Tests:** `test_nearest_prefers_the_original_stack_when_admissible`
(`xfail`), `test_nearest_placement_minimises_distance_to_the_pickstation`
(hält den Ist-Zustand fest, grün).

## P3-05 — POPULARITY-Warmup platziert in die Port-Pufferzone

* **Verantwortungsbereich:** STRATEGY
* **Severity:** MINOR (derzeit durch P3-01 auf 100 % der Fälle verstärkt)
* **Betroffen:** Policy D

`_select_popularity_stack` filtert über `_get_eligible_stacks`, das die
Pufferzone ausschließt. Der Warmup-/Cold-Start-Zweig ruft dagegen
`_select_random_stack`, das den Filter bewusst **nicht** anwendet. Die Policy
platziert im Warmup also in Zellen, die sie sonst als unzulässig behandelt.

596 Fälle über 67 Läufe. Solange P3-01 besteht, ist der gesamte Lauf Warmup –
der Effekt ist damit nicht auf die Anlaufphase begrenzt.

## P3-06 — `critical_stack_penalty` ist unerreichbar

* **Verantwortungsbereich:** STRATEGY (toter Code)
* **Severity:** MINOR

In `select_temporary_stack` werden kritische Stacks bereits per `continue`
übersprungen (Zeile 127). Die anschließende Bewertung
`critical_term = self.critical_stack_penalty if is_critical else 0`
(Zeile 136-137) kann daher nie zutreffen; `critical_stack_penalty=1000` ist
wirkungslos. Kein Fehlverhalten, aber irreführend.

## P3-07 — Das Kostenmodell wird in der Local Relocation nie verwendet

* **Verantwortungsbereich:** INTEGRATION
* **Severity:** MINOR

`_estimate_relocation_cost` prüft
`hasattr(self.cost_model, "estimate_relocate_cost")`. `ActionCostModel`
besitzt diese Methode nicht. Die Bewertung fällt daher immer auf
Manhattan-Distanz plus Nachbarbonus zurück. Stapeltiefe und Armkosten fließen
nicht ein, obwohl das injizierte Kostenmodell sie kennt.

Relevant für die Interpretation: „Local Relocation" heißt hier
„fahrwegminimal", nicht „kostenminimal".

## P3-08 — Experiment-Dokumentation deckt nur drei der fünf Konfigurationen ab

* **Verantwortungsbereich:** CONFIG
* **Severity:** MINOR

`experiments/experiment_setup.md` beschreibt Baseline, ABC und Popularity.
`run_experiments.py` führt zusätzlich `RR+RR` und `LR+NR` aus. Der Schalter
`return_blocking_bins` – der A/B von C/D fundamental trennt – wird im
Setup-Dokument nirgends erwähnt, ebenso wenig `NEAREST`.

Zusätzlich enthält die Liste weiterhin `baseline` (`LOFI/RANDOM`,
`return_blocking_bins=True`), das keiner der vier vorgesehenen Policies
entspricht. Vor dem Vergleich ist zu klären, ob es als fünfte Vergleichsgröße
gewollt ist.

Die Seeds sind über alle fünf Experimente identisch
(`[42, 123, 456, 789, 1011]`, Default von `ExperimentConfig`); die explizite
Wiederholung in `run_experiments.py` ist redundant, aber unschädlich.

## P3-09 — Debug-Ausgaben in heißen Pfaden

* **Verantwortungsbereich:** INTEGRATION
* **Severity:** MINOR

* `relocation_selection.py:160` – `print("[DEBUG] selecting relocation for source", …)` bei jeder kostenbasierten Auswahl
* `relocation_selection.py:270-271` – `print("[DEBUG] reserved_bin_ids:", …)` bei jedem Aufruf, gibt die vollständige Menge aus
* `event_handler.py:2806` – `if bin_id == 102:` mit hartkodierter Bin-ID

Kein Korrektheitsproblem, aber Laufzeit- und Log-Rauschen und ein
offensichtlicher Instrumentierungsrest.

## P3-10 — Zipf 1.5 macht die ABC-Klassen B und C nahezu bedeutungslos

* **Verantwortungsbereich:** CONFIG
* **Severity:** MINOR (Beobachtung zum Experimentdesign)

Bei `zipf_parameter = 1.5` und 4320 Bins entfallen 98,5 % aller Requests auf
die A-Klasse, 1,1 % auf B und 0,4 % auf C. Die B- und C-Zweige des
ABC-Placements werden dadurch fast nie retrieval-wirksam, und
`abc_zone_adherence` wird von A dominiert.

Die Klassensemantik ist korrekt – die Frage ist, ob die Parametrierung die
Unterschiede zwischen den Policies noch sichtbar macht. Das ist eine
fachliche Entscheidung, kein Codefehler.

## Übersicht

| ID | Bereich | Severity | Betroffene Policies |
|---|---|---|---|
| P3-01 | INTEGRATION → STRATEGY | **BLOCKER** | D |
| P3-02 | INTEGRATION | **BLOCKER** | A, B |
| P3-03 | INTEGRATION | **BLOCKER** | A |
| P3-04 | STRATEGY | **MAJOR** | B |
| P3-05 | STRATEGY | MINOR | D |
| P3-06 | STRATEGY (toter Code) | MINOR | A, B, C, D |
| P3-07 | INTEGRATION | MINOR | B, C, D, X |
| P3-08 | CONFIG | MINOR | alle |
| P3-09 | INTEGRATION | MINOR | alle |
| P3-10 | CONFIG | MINOR | C |

Alle drei BLOCKER sind **nicht** strategiespezifische Denkfehler, sondern
Verdrahtungsfehler an der Grenze zwischen Strategie und Plattform. Sie sind
nur deshalb bisher unentdeckt geblieben, weil die Phasen 1 bis 2D
ausschließlich `return_blocking_bins=True` und keine
popularitätsabhängigen Größen geprüft haben.

---

# 5. Mikrotests

Neu: `tests/test_strategy_correctness.py` – 35 Tests, davon 29 grün und
6 als `xfail(strict=True)` mit Verweis auf den jeweiligen Befund. Ein
gemeinsamer parametrisierter Harness deckt den Contract aller Policies ab;
policy-spezifische Tests ergänzen ihn.

| Bereich | Tests |
|---|---|
| Gemeinsamer Contract (parametrisiert über A–D) | zulässige Relocation-Ziele, keine Blocker-Restores bei `rbb=False`, höchstens ein Restore je Task und Bin, Bin-Erhaltung |
| A RR+RR | Random Relocation nur aus gültigen Kandidaten, Random Return nur aus gültigen Kandidaten, RNG-Bindung (`xfail`), Reproduzierbarkeit (`xfail`) |
| B LR+NR | Determinismus und Zulässigkeit, Ist-Semantik „nächste Pickstation" festgehalten, Vorgabe „Originalstack gewinnt" (`xfail`) |
| C ABC | `[A,C,B] → [C,B,A]`, Stabilität innerhalb einer Klasse, Klassensemantik am realen Nachfragestrom, Schwellenaufteilung 20/30/50, Score- statt Zonenvariante, Distanz zur näheren von zwei Pickstations |
| D POPULARITY | `[5,1,10] → [1,5,10]`, Stabilität bei gleichen Counts, kein Look-ahead, Cold-Start-Fallback, Reaktion auf geänderte `access_count`, `access_count` steigt bei echten Retrievals (`xfail`), Warmup wird verlassen (`xfail`) |
| Ownership | `temp_storage` wird geleert, globale Ownership wird freigegeben (`xfail`), deterministische Reproduktion des `RuntimeError` |

Die `xfail`-Markierungen sind `strict=True`. Sobald ein Befund behoben wird,
schlägt der zugehörige Test als XPASS an und erzwingt die Entschärfung der
Markierung – die Remediation kann damit nicht stillschweigend unvollständig
bleiben.

**Testsuite gesamt: 320 passed, 6 xfailed.** Kein bestehender Test wurde
verändert.

---

# 6. Risk Register

Fortgeschrieben aus Phase 2D. Alte Risiken bleiben bestehen.

| # | Risiko | Status | Herkunft |
|---|---|---|---|
| R-1 | MOVE-Stall-Recovery: konservative Schwelle 120 ZE, aus 4 Seeds abgeleitet, nicht universell validiert | offen | Phase 2D |
| R-2 | Restliches internes Stallfenster (Seed 3: ~162 ZE), begrenzt, kein permanenter Stall | offen; in Phase 3 max. Innenfenster 167 ZE (A_RR+RR, `final`, Seed 3) | Phase 2D |
| R-3 | `move_stall_recoveries` / `move_recovery_unresolved` je Policy mitführen | **umgesetzt** – siehe 3.2. Ein einziges `unresolved=1` bei B_LR+NR, `mittel`, Seed 42 | Phase 2D |
| R-4 | RNG / Common Random Numbers: laufzeitabhängige Ziehungen divergieren zwischen Policies | offen, **verschärft** durch P3-03 (Policy A gar nicht reproduzierbar) | Phase 2C |
| R-5 | Legacy `pickup_from_pickstation` | offen, **neu bewertet**: der Legacy-Zweig ist nicht nur tote Last, er enthält mit `increment_access_count()` produktive Logik, die im Live-Pfad fehlt (P3-01) | Phase 2B |
| R-6 | AUDIT-008: unsauberer Bin-Status während Return | offen, weiterhin ohne nachgewiesene Wirkung | Phase 2 |
| R-7 | Komplett volles Lager: bekannte Modellgrenze ohne allgemeinen Recovery-Ausweg | offen | Phase 2 |
| R-8 | `test_simulation_visual.py` nicht ausführbar (kein Flask) | offen, weiterhin nicht als bestanden gezählt | Phase 1 |
| R-9 | **neu:** Zwei der fünf ausgeführten Experimentkonfigurationen (`baseline`, `RR+RR`) unterscheiden sich in zwei Dimensionen gleichzeitig (Placement **und** `return_blocking_bins`) | offen | Phase 3, P3-08 |
| R-10 | **neu:** ABC- und NEAREST-Placement konzentrieren die Rücklagerung auf sehr wenige Stacks (8–28 bzw. 1–13 distinkte Ziele). Für die Interpretation räumlicher Metriken relevant | offen | Phase 3 |
| R-11 | **neu:** Initialverteilung nutzt `grid.is_storage_position`, Placement-Policies mit Pufferzonen-Filter nutzen `state.is_valid_storage_position`. Bins können daher in der Pufferzone starten, aber unter NEAREST/ABC/POPULARITY nie dorthin zurückkehren – ein systematischer Drift, der Policies unterschiedlich trifft | offen | Phase 3 |

---

# 7. Readiness Gate

| Kriterium | Ergebnis |
|---|---|
| Alle Policies eindeutig verstanden und korrekt verdrahtet | **nein** – P3-01, P3-03, P3-04 |
| Jede Policy erfüllt ihren eigenen fachlichen Contract | **nein** – D ist wirkungslos (P3-01), B implementiert eine andere Policy (P3-04) |
| Keine Bin-/Ownership-/Capacity-/Physical-Invariante verletzt | **nein** – `BLOCKER_OWNERSHIP_ORPHAN` bei A und B (P3-02) |
| Keine ungültigen Relocation-/Return-Ziele | teilweise – Kapazität, Grid, Ports, Quellstack durchgehend sauber; Pufferzone bei D verletzt (P3-05) |
| `return_blocking_bins` korrekt behandelt | teilweise – Restore-Verhalten korrekt, Ownership-Freigabe fehlt |
| Multi-Pickstation-Semantik respektiert | **ja** – 0 Cross-Station-Verwechslungen, Distanz stets zur näheren Station |
| Kein strategiespezifischer permanenter Stall | **ja** – kein Endfenster wächst 1:1; größtes Endfenster 331 ZE bei 1200 ZE Laufzeit (A_RR+RR, nicht reproduzierbar) |
| `move_recovery_unresolved = 0` | **nein** – 1 Fall (B_LR+NR, `mittel`, Seed 42) |
| Systemläufe ohne Correctness-Fehler | **nein** – 10 Abbrüche, alle auf P3-02 zurückgeführt |

## Urteil

```text
NOT_READY_FOR_PHASE_4
```

Begründung: Drei BLOCKER. Policy D misst nichts, was sie zu messen vorgibt
(P3-01). Policies A und B verletzen eine projekteigene Zustandsinvariante und
brechen dadurch in 10 von 134 Läufen ab (P3-02). Policy A ist bei festem Seed
nicht reproduzierbar (P3-03), was Phase 4 – die genau diese Reproduzierbarkeit
herstellen soll – auf einer nicht tragfähigen Grundlage beginnen ließe.

Zusätzlich implementiert Policy B eine andere Rücklagerungsregel als
vorgesehen (P3-04, MAJOR). Das ist keine Fehlfunktion, aber ein
Bedeutungsunterschied, der vor jedem Vergleich entschieden sein muss.

Positiv: die **physikalische** Korrektheit ist über alle Policies hinweg
intakt – null ungültige Pickups, Drops, Moves, Kollisionen, Kapazitäts- oder
Portverletzungen, kein Bin-Verlust, keine Duplikation, keine
Cross-Station-Verwechslung, keine Task-Doppelvergabe. Policy C (ABC+ABC) und
die Baseline sind in allen 133 Läufen vollständig sauber.

---

# 8. Remediation-Empfehlung (nicht ausgeführt)

Vorgeschlagene Reihenfolge, jeweils kleinstmöglicher Eingriff:

1. **P3-02 zuerst.** Ein Aufruf: `clear_all_relocations()` muss die globalen
   Ownerships der verworfenen Einträge freigeben. Beseitigt zugleich die 10
   Abbrüche. Danach sollte separat entschieden werden, ob
   `RobotTask.release_blocker_ownership` bei unbekannter Bin wirklich werfen
   soll oder – wie der umgebende Code bereits annimmt – `None` liefern.
2. **P3-01.** Die fehlende Zeile in den Live-Drop-Pfad
   (`_handle_robot_drop`, Zweig `remove_target`) neben die dort bereits
   vorhandene Digging-Depth-Erfassung. Anschließend muss die
   POPULARITY-Policy neu charakterisiert werden, weil sie danach erstmals
   überhaupt läuft; die bisherigen D-Messungen sind wertlos.
3. **P3-03.** `rng=self.rng` bei der Konstruktion von `RelocationSelection`
   ergänzen. Gehört fachlich schon zu Phase 4, ist aber Voraussetzung dafür,
   Punkt 1 und 2 überhaupt reproduzierbar nachmessen zu können.
4. **P3-04** ist eine **fachliche Entscheidung**, kein Bugfix: Soll NR
   „zurück in die Nähe des Ursprungs" oder „so nah wie möglich an den Port"
   bedeuten? Erst danach implementieren. Beides ist eine legitime Policy –
   nur nicht beides gleichzeitig unter demselben Namen.
5. P3-05 bis P3-10 gebündelt danach; P3-08 und P3-10 sind Entscheidungen der
   Fachseite, keine Codeänderungen.

Nach der Remediation ist dieser Audit zu wiederholen: die sechs
`xfail`-Tests müssen dann XPASS zeigen und die Markierungen entfernt werden.

Es wurden **keine Git-Commits oder Pushes** ausgeführt und **kein
Produktionscode geändert**. Phase 4 wurde nicht begonnen.

---

# Phase 3B – Remediation & Re-Audit

**Datum:** 2026-08-21
**Baseline-Commit:** `bfe2a99` (unverändert; Phase-3-Artefakte waren noch nicht committet)
**Auftrag:** Ausschließlich die experimentkritischen Befunde aus Phase 3
minimal beheben und denselben Correctness-Audit erneut ausführen. Keine
Strategieoptimierung, kein Performancevergleich, keine
Common-Random-Numbers-Architektur, keine Commits.

## Ausgangs- und Endzustand

| | vor Phase 3B | nach Phase 3B |
|---|---|---|
| Testsuite (ohne `test_simulation_visual.py`) | 320 passed, 6 xfailed | **336 passed, 0 xfailed, 0 xpassed** |
| Systemläufe im Re-Audit | 330 | **345** |
| Abbrüche | 10 | **0** |
| `BLOCKER_OWNERSHIP_ORPHAN` | 89 | **0** |
| Contract-Verletzungen | 596 | **0** |
| `move_recovery_unresolved` | 1 | **0** |
| physikalisch ungültige Aktionen | 0 | 0 |

`tests/test_simulation_visual.py` bleibt nicht ausführbar (kein Flask) und
wird weiterhin nicht mitgezählt.

---

## P3-02 — Blocker-Ownership bei `return_blocking_bins=False`

**Status: FIXED**

### Root Cause

`RobotTask.clear_all_relocations()` leerte ausschließlich `temp_storage`. Die
globale Sperre in `ActiveQueue._blocker_ownership` blieb bestehen, obwohl kein
Task die Bin mehr zurücklegen würde. Folgen:

* die Bin blieb über `get_all_reserved_bin_ids()` global reserviert,
* ihr Stack war über `RelocationSelection._get_critical_stack_ids` als
  Relocation-Ziel gesperrt,
* und `Scheduler._try_schedule_opportunistic` lief in
  `RuntimeError: Cannot release ownership of bin N from task M`.

Die dortige Absicherung `if released is not None` war wirkungslos:
`RobotTask.release_blocker_ownership` gibt nie `None` zurück – sie liefert den
Eintrag oder wirft.

### Fix

Zwei Stellen, beide innerhalb der bestehenden Ownership-Architektur; keine
zweite Buchhaltung.

1. `clear_all_relocations(active_queue=None)` gibt für jeden verworfenen
   Eintrag die globale Ownership frei – aber nur, wenn der Task selbst noch
   Eigentümer ist. Wurde die Bin zwischenzeitlich übertragen, bleibt die
   fremde Ownership unangetastet. Die Methode liefert die verworfenen
   Einträge zurück.
2. `Scheduler._try_schedule_opportunistic` benutzt jetzt dasselbe Muster wie
   `EventHandler._release_foreign_blocker_ownership`: erst prüfen, ob die
   Verpflichtung überhaupt noch offen ist (`still_open`), dann die globale
   Sperre in jedem Fall lösen.

Die Queue erreicht die Entscheidungsstelle über eine optionale Injektion in
`TopAccessStrategy(active_queue=…)` – analog zur bereits vorhandenen
Injektion in `RelocationSelection`.

### Geänderte Dateien

| Datei | Funktion |
|---|---|
| `simulation/robot_task.py` | `clear_all_relocations` |
| `strategies/top_access_strategy.py` | `__init__`, `_next_restore_blockers_action` |
| `simulation/simulation_engine.py` | Konstruktion von `TopAccessStrategy` |
| `simulation/scheduler.py` | `_try_schedule_opportunistic` |

### Regressionstests

`test_discarding_restores_also_releases_global_blocker_ownership`
(prüft jetzt den echten Strategiepfad statt der Task-Methode),
`test_clear_all_relocations_releases_only_its_own_ownership`,
`test_ownership_transfer_survives_an_already_released_obligation`.

### Vorher / Nachher

Profil `mittel` (12×18, 1150 Bins, 5 Roboter, util 0.6, 800 ZE):

| | verwaiste Ownerships | max. gleichzeitig | Lebensdauer Median/Max | RuntimeError |
|---|---|---|---|---|
| RR+RR Seed 42 vorher | 17 | 5 | 29 / 57 ZE | – |
| RR+RR Seed 42 nachher | 0 | **0** | **0** | 0 |
| LR+NR Seed 3 vorher | 32 | 10 | 47 / 113 ZE | – |
| LR+NR Seed 3 nachher | 0 | **0** | **0** | 0 |

Systemweit: 89 `BLOCKER_OWNERSHIP_ORPHAN` → **0**; 10 Abbrüche → **0**.

### Rest-Risiko

Die Freigabe hängt daran, dass `TopAccessStrategy` die Queue injiziert
bekommt. Wird die Strategie anderswo ohne `active_queue` konstruiert (in
Tests zulässig und weiterhin möglich), fällt die Freigabe still aus. Die
Absicherung im Scheduler fängt die Folgewirkung dann trotzdem ab, sodass kein
Abbruch mehr entstehen kann.

---

## P3-01 — `access_count` im aktiven Zwei-Phasen-Pfad

**Status: FIXED**

### Root Cause

`increment_access_count()` stand ausschließlich in
`EventHandler._handle_robot_action` – einem Zweig, der zur Laufzeit nur noch
für `pickup_from_pickstation` erreicht wird. Der aktive Zwei-Phasen-Pfad
(`_handle_robot_drop`) zählte den Zugriff nicht mit. Gemessen: 109
abgeschlossene Requests, Summe aller `access_count` = 0.

### Fix

Die Zählung wurde in `_handle_robot_drop`, Zweig `remove_target`, verschoben –
direkt neben die dort bereits vorhandene Digging-Depth-Erfassung. Fachlicher
Zeitpunkt: die Target-Bin ist physisch an der Pickstation angekommen.

**Bewusst verschoben statt dupliziert.** Zwei Zählstellen würden bei einer
späteren Reaktivierung des Legacy-Zweigs jeden Retrieval doppelt zählen.

Die Stelle liegt hinter dem Positions- und Stale-Guard, ein Doppelaufruf je
Retrieval ist damit ausgeschlossen. Blocker-Bewegungen (`relocate`) und
Rücklagerungen (`return`) erhöhen den Zähler nicht.

**Batching-Semantik geprüft.** Werden mehrere Requests für dieselbe Bin
gebündelt, gibt es genau einen physischen Retrieval und genau eine Erhöhung.
`access_count` misst damit **Zugriffshäufigkeit, nicht Requestanzahl**. Das
entspricht der ursprünglichen Absicht („Jeder erfolgreiche Retrieval zählt")
und der Verwendung als Grabtiefen-Proxy. Gemessenes Verhältnis:

| Profil | Completions | Increments | Requests je Retrieval |
|---|---|---|---|
| mittel, 800 ZE | 109 | 46 | 2,37 |
| final, 1200 ZE | 187 | 70 | 2,67 |

`Increments` und `sum(access_count)` stimmen exakt überein – keine
Doppelzählung.

### Geänderte Dateien

`simulation/event_handler.py` – `_handle_robot_drop` (Zählung ergänzt),
`_handle_robot_action` (Zählung entfernt, mit Begründung im Code).

### Regressionstests

`test_access_count_increases_on_real_retrievals`,
`test_access_count_ignores_blocker_movements`,
`test_popularity_placement_leaves_warmup_in_a_realistic_run`,
`test_popularity_placement_actually_runs_its_own_logic`.

### Vorher / Nachher — Neucharakterisierung von POPULARITY

| Profil | vorher | nachher |
|---|---|---|
| dicht_r3, 500 ZE | access 0, Placement 42/42 Warmup | access 16, max 6 |
| dicht_r4, 1200 ZE | access 0 | access **62**, max **16**, 13 Bins mit Zugriff, Placement 62 → 47 Warmup / **15 echt** (hot 3, neutral 9, cold 3) |
| mittel, 800 ZE | access 0, 74/74 Warmup | access 45, max 7, 18 Bins mit Zugriff, weiterhin 58/58 Warmup |
| final, 1200 ZE | access 0, 113/113 Warmup | access **70**, max **9**, 27 Bins mit Zugriff, Placement 144 → 90 Warmup / **54 echt** (hot 5, neutral 41, cold 8) |

`access_count` divergiert also tatsächlich, das Reordering hat einen echten
Schlüssel, und Placement erreicht Hot-, Neutral- und Cold-Zweig im realen
Lauf.

**Die Phase-3-Zahlen für POPULARITY sind wertlos** und wurden nicht
weiterverwendet.

### Rest-Risiko

`popularity_warmup_requests = 50` ist gegen eine Größe kalibriert, die durch
Batching rund 2,4–2,7× langsamer wächst als die Requestzahl. In kurzen oder
kleinen Läufen (`mittel` bei 800 ZE: 45 < 50) wird der Warmup nicht verlassen
und POPULARITY verhält sich wie zufällige Platzierung. In der finalnahen
Konfiguration ist das kein Problem. Neu im Risk Register als **R-12**.

---

## P3-03 — Reproduzierbarkeit von RR+RR

**Status: FIXED**

### Root Cause

`RelocationSelection` wurde in `SimulationEngine` ohne `rng=` konstruiert und
erzeugte sich intern ein ungeseedetes `np.random.default_rng()`. Nur RR+RR
erreicht den Zufallszweig, daher war ausschließlich diese Policy betroffen.

### Fix

`SimulationEngine` hält jetzt einen zweiten, aus dem Simulationsseed
abgeleiteten Strom:

```python
self.rng            = np.random.default_rng(self.config.random_seed)
self.relocation_rng = np.random.default_rng([self.config.random_seed, 1])
```

und übergibt ihn als `rng=` an `RelocationSelection`.

**Bewusst nicht `self.rng` mitbenutzt.** Dieser Strom versorgt bereits
`ActionCostModel` (Servicezeiten) und `PlacementSelector`. Eine dritte Partei
darin würde die in Phase 2C dokumentierte Kopplung verschärfen, die Phase 4
gerade auflösen soll. `self.rng` bleibt unverändert, damit sich das Verhalten
aller anderen Policies nicht verschiebt.

Das ist **keine** Common-Random-Numbers-Architektur, sondern nur
Reproduzierbarkeit.

**Verwendeter RNG nach dem Fix:** `RelocationSelection.rng is
engine.relocation_rng`, abgeleitet über eine `SeedSequence` aus
`[config.random_seed, 1]`.

### Geänderte Dateien

`simulation/simulation_engine.py` – `__init__`, Konstruktion von
`RelocationSelection`.

### Regressionstests

`test_relocation_selection_uses_a_seed_derived_rng`,
`test_relocation_rng_is_deterministic_and_seed_dependent`,
`test_rr_rr_is_reproducible_for_a_fixed_seed`.

### Vorher / Nachher

Drei Läufe je Konfiguration, identischer Seed:

| Profil / Seed | vorher (`requests_completed`) | nachher |
|---|---|---|
| 7×7 dicht, s42 | 21 / 23 / 23 – Layouts verschieden | 58 / 58 / 58 – **identisch** |
| dicht_r3, s3 | – | 56 / 56 / 56 – identisch |
| mittel, s3 | – | 125 / 125 / 125 – identisch |
| mittel, s42 | – | 127 / 127 / 127 – identisch |

Verglichen wurde nicht nur die Completion-Zahl, sondern der vollständige
Endzustand: Stack-Belegung **und** Verteilung aller `access_count`.

Verschiedene Seeds liefern weiterhin verschiedene Ergebnisse – der Strom ist
seedabhängig, nicht konstant.

### Rest-Risiko

Die Ableitung `[seed, 1]` ist eine Ad-hoc-Wahl. Für Phase 4 ist eine
einheitliche Strom-Vergabe über `SeedSequence.spawn()` für alle
Zufallsverbraucher vorzusehen; dann sollte auch diese Stelle darauf
umgestellt werden. Bleibt als **R-4** offen.

---

## P3-04 — NEAREST relativ zum Originalstack

**Status: FIXED**

### Root Cause

`_select_nearest_stack(self, state)` nahm `original_stack_id` nicht entgegen
und sortierte nach der Distanz zur nächsten **Pickstation**. Das ist eine
andere Policy als die fachlich vorgesehene.

### Fix

Verbindlicher Contract, umgesetzt in `_select_nearest_stack`:

1. minimale Manhattan-Distanz zum Originalstack,
2. bei Gleichstand kleinere `y`-Koordinate,
3. danach kleinere `x`-Koordinate.

Ist der Originalstack selbst zulässig, gewinnt er mit Distanz 0. Die
Zulässigkeitsprüfung (`_get_eligible_stacks`) bleibt unverändert: nicht
gesperrt, freie Kapazität, nicht in der Port-Pufferzone.

**Fallback.** Lässt sich der Originalstack nicht auflösen, greift das frühere,
ebenfalls deterministische Kriterium „Distanz zur nächsten Pickstation", mit
Logzeile `[NEAREST][FALLBACK]`. Keine neue Optimierungsstrategie. Der Fall ist
im regulären Ablauf nicht erreichbar – `_next_return_target_action` bricht
bereits ab, wenn `task.target_stack_id` fehlt.

Neu ergänzt: `_resolve_stack_position(state, stack_id)` als gemeinsamer
Auflöser für Tuple- und `S_x_y`-Form.

### Geänderte Dateien

`strategies/target_bin_placement_selector.py` – `select_return_stack`,
`_select_nearest_stack`, neu `_resolve_stack_position`.
Dokumentation: `experiments/experiment_setup.md`,
`experiments/experiment_config.py`, `run_experiments.py`.

### Regressionstests

`test_nearest_minimises_manhattan_distance_to_the_original_stack`,
`test_nearest_prefers_the_original_stack_when_admissible`,
`test_nearest_falls_back_deterministically_without_an_original_stack`,
`test_nearest_spreads_returns_instead_of_clustering_at_the_port`.

**Modellkorrektur an bestehenden Tests.** `tests/test_strategies_selectors.py`
enthielt eine Testklasse, die die alte Pickstation-Semantik festhielt
(inklusive Kommentar „wird für NEAREST nicht verwendet"). Sie wurde auf den
heute verbindlichen Contract umgestellt und um Tie-Break- und
Originalstack-Fälle erweitert – dokumentiert im Klassen-Docstring, analog zur
Modellkorrektur AUDIT-002 aus Phase 2B. Der Test wurde **nicht** abgeschwächt,
sondern auf die geänderte Fachregel gehoben.

### Vorher / Nachher

Direkter Nachweis (12×18, 40 geprüfte Originalstacks):

| | vorher | nachher |
|---|---|---|
| Ziel ist Optimum bzgl. Originalstack | 1/40 (zufällig) | **40/40** |
| Ziel ist Optimum bzgl. Pickstation | 40/40 | 1/40 |
| distinkte Ziele über alle Originalstacks | 1 | **201** |

Systemweit (distinkte Placement-Ziele je Lauf, min/median/max):

| Policy | vorher | nachher |
|---|---|---|
| B LR+NR | 1 / 6 / 13 | **14 / 22 / 30** |

Im finalnahen Lauf stieg die Zahl distinkter Ziele von 8–9 auf 15–27.

### Rest-Risiko

Bei Seed 3 im finalnahen Profil steigt die Zahl **geplanter**
Target-Rücklagerungen deutlich (646 → 1877 Planungsaufrufe bei 104
Completions). Die Ursache ist erwartbar: liegt der Originalstack in einer
dichten Region, sind auch seine Nachbarn voll, und die Aktion wird häufiger
neu geplant. Es entstand dabei keine Invariantenverletzung, kein Abbruch und
kein permanenter Stillstand (Endfenster 21 ZE). Neu im Risk Register als
**R-13**.

---

## P3-05 — Warmup-Eligibility der POPULARITY-Policy

**Status: FIXED**

### Root Cause

`_select_popularity_stack` filtert über `_get_eligible_stacks` (ohne
Pufferzone), der Warmup-Zweig rief dagegen `_select_random_stack`, das den
Pufferzonen-Filter bewusst nicht anwendet. Die Policy platzierte im Warmup in
Zellen, die sie in ihrer aktiven Phase als unzulässig behandelt – 596 Fälle.

### Fix

Der Warmup zieht jetzt zufällig aus **derselben** Kandidatenmenge wie die
aktive Phase (`candidates` aus `_get_eligible_stacks`).

Die eigenständige RANDOM-Semantik von RR+RR wurde **nicht** angetastet:
`_select_random_stack` darf Pufferzonen-Stacks weiterhin nutzen. Das ist durch
`test_random_placement_keeps_its_own_semantics` explizit abgesichert.

### Geänderte Dateien

`strategies/target_bin_placement_selector.py` – `_select_popularity_stack`.

### Regressionstests

`test_popularity_warmup_uses_the_same_eligibility_as_the_active_phase`,
`test_random_placement_keeps_its_own_semantics`,
`test_popularity_placement_falls_back_to_random_during_cold_start`.

### Vorher / Nachher

`target_return_ziel_in_pufferzone` über alle Läufe: **596 → 0**.

### Rest-Risiko

Keines erkennbar. Die Unterscheidung zwischen „RANDOM als eigenständige
Policy" und „Zufall als Warmup-Fallback" ist jetzt explizit und getestet.

---

## P3-06 bis P3-10

| ID | Entscheidung | Status |
|---|---|---|
| **P3-06** `critical_stack_penalty` unerreichbar | Nur dokumentiert. Der Aufschlag hat keine Correctness-Wirkung; ein Entfernen würde die Signatur ändern. Kommentar im Code ergänzt. | OPEN (dokumentiert) |
| **P3-07** Kostenmodell in der Local Relocation ungenutzt | Nur dokumentiert. Im Docstring steht jetzt ausdrücklich: „Local Relocation" heißt **fahrwegminimal** (Manhattan zum Quellstack, Bonus 1 für direkte Nachbarn), **nicht** kostenminimal. Stapeltiefe und Armwege gehen nicht ein. Keine Kostenanbindung gebaut. | OPEN (dokumentiert) |
| **P3-08** Experiment-Dokumentation | Behoben. `experiment_setup.md` beschreibt jetzt alle vier Policies mit ihren drei Schaltern, die Bedeutung von `return_blocking_bins` und `NEAREST`. Die zusätzliche Referenzkonfiguration wurde in `baseline_reference` umbenannt und ausdrücklich von RR+RR abgegrenzt. Auch `ExperimentConfig` und der Modul-Docstring von `run_experiments.py` sind aktualisiert. | FIXED |
| **P3-09** Debug-Reste | Behoben. Entfernt: `[DEBUG] selecting relocation for source`, `[DEBUG] reserved_bin_ids`/`critical_stack_ids` (bei jedem Aufruf), sowie zwei hartkodierte Traces auf Bin 102 in `event_handler.py`. Keine funktionale Änderung. | FIXED |
| **P3-10** Zipf 1.5 / ABC-Dominanz | Unverändert. Experimentdesign-Frage, bleibt im Risk Register. | OPEN (bewusst) |

---

## Re-Audit

Gefahren wurde derselbe Harness wie in Phase 3: 7×7 (100 und 240 Bins, 2/3/4
Roboter, `util` 0.5 und 2.0), 12×18 mit 1150 Bins, 20×30 mit 4320 Bins und
8 Robotern; Seeds 1, 2, 3, 4, 7, 42, 99 in den kleinen Profilen, 3/4/42
finalnah; durchgängig 2 Pickstations. **345 Läufe.**

| Kriterium | A RR+RR | B LR+NR | C ABC | D POP | X baseline |
|---|---|---|---|---|---|
| Läufe | 69 | 69 | 69 | 69 | 69 |
| Abbrüche | **0** | **0** | 0 | 0 | 0 |
| ungültige Pickups/Drops/Moves/Kollisionen | 0 | 0 | 0 | 0 | 0 |
| Bin verloren / dupliziert | 0 | 0 | 0 | 0 | 0 |
| Ziel über Kapazität / Portzelle / außerhalb Grid | 0 | 0 | 0 | 0 | 0 |
| `BLOCKER_OWNERSHIP_ORPHAN` | **0** | **0** | 0 | 0 | 0 |
| Contract-Verletzungen | **0** | **0** | 0 | **0** | 0 |
| Blocker mehrfach restored | 0 | 0 | 0 | 0 | 0 |
| Blocker-Return trotz `rbb=False` | 0 | 0 | – | – | – |
| Cross-Station-Verwechslung | 0 | 0 | 0 | 0 | 0 |
| `move_stall_recoveries` | 10 | 23 | 13 | 4 | 13 |
| `move_recovery_unresolved` | **0** | **0** | **0** | **0** | **0** |
| distinkte Placement-Ziele (min/med/max) | 16/33/237 | 14/22/30 | 8/20/28 | 10/29/194 | 18/30/244 |

Der Abschnitt „Verletzungen je Profil" ist leer – kein einziger Lauf hat eine
Contract- oder Audit-Invariante verletzt.

### Zusätzliche Einzelnachweise

**RR+RR reproduzierbar.** Je drei Wiederholungen mit identischem Seed,
verglichen wurde der vollständige Endzustand (Stacks + `access_count`):
`dicht_r3` s3 → 56/56/56, s42 → 58/58/58; `mittel` s3 → 125/125/125,
s42 → 127/127/127. Alle identisch.

**POPULARITY dynamisch aktiv.** `dicht_r4` (1200 ZE): `access_count` 0 → 62,
Maximum 16, 13 Bins mit Zugriff, 15 von 62 Placement-Aufrufen laufen mit
eigener Logik, Hot/Neutral/Cold alle erreicht. Finalnah (1200 ZE): 54 von 144
Aufrufen mit eigener Logik.

**LR+NR misst zum Originalstack.** 40/40 geprüfte Fälle liefern das Optimum
bezüglich des Originalstacks, nur 1/40 zufällig auch bezüglich der
Pickstation; 201 distinkte Ziele statt zuvor 1.

---

## Risk Register (fortgeschrieben)

| # | Risiko | Status |
|---|---|---|
| R-1 | MOVE-Stall-Recovery: Schwelle 120 ZE, aus 4 Seeds abgeleitet, nicht universell validiert | offen |
| R-2 | Begrenztes internes Stallfenster (kein permanenter Stall). Größtes Innenfenster im Re-Audit: 162 ZE (X_baseline, `final`, Seed 3) | offen |
| R-3 | `move_stall_recoveries` / `move_recovery_unresolved` je Policy mitführen | umgesetzt; `unresolved = 0` in allen 345 Läufen |
| R-4 | RNG / Common Random Numbers: laufzeitabhängige Ziehungen divergieren zwischen Policies. Durch P3-03 ist jede Policy jetzt für sich reproduzierbar; die policy-übergreifende Kopplung von `engine.rng` bleibt offen | offen → **Phase 4** |
| R-5 | Legacy `pickup_from_pickstation` | offen. Die produktive Logik daraus (`increment_access_count`) ist mit P3-01 in den Live-Pfad überführt; der Zweig selbst bleibt unangetastet |
| R-6 | AUDIT-008: unsauberer Bin-Status während Return | offen, weiterhin ohne nachgewiesene Wirkung |
| R-7 | Komplett volles Lager: Modellgrenze ohne allgemeinen Recovery-Ausweg | offen |
| R-8 | `test_simulation_visual.py` nicht ausführbar (kein Flask) | offen |
| R-9 | `baseline` unterscheidet sich von RR+RR in zwei Dimensionen gleichzeitig | entschärft: umbenannt in `baseline_reference` und dokumentiert abgegrenzt. Ob es Teil des Vergleichs sein soll, bleibt fachlich offen |
| R-10 | Konzentration von ABC/NEAREST auf wenige Zielstacks | für NEAREST behoben (1/6/13 → 14/22/30). Für ABC unverändert (8/20/28) – Eigenschaft der Greedy-Variante, keine Fehlfunktion |
| R-11 | Unterschiedliche Eligibility zwischen Initialisierung (`grid.is_storage_position`) und Placement (`state.is_valid_storage_position`): Bins können in der Pufferzone starten, unter NEAREST/ABC/POPULARITY aber nie dorthin zurückkehren | offen |
| R-12 | **neu:** `popularity_warmup_requests = 50` ist gegen `access_count` kalibriert, das durch Batching 2,4–2,7× langsamer wächst als die Requestzahl. In kurzen/kleinen Läufen wird der Warmup nicht verlassen und POPULARITY verhält sich wie zufällige Platzierung | offen |
| R-13 | **neu:** LR+NR erzeugt bei dichten Originalregionen deutlich mehr Replanungen der Target-Rücklagerung (finalnah Seed 3: 1877 Planungsaufrufe bei 104 Completions). Keine Invariantenverletzung, kein Stall – aber beim Interpretieren von Laufzeitmetriken zu beachten | offen |
| R-14 | **neu:** Die Ownership-Freigabe aus P3-02 hängt an der Injektion `TopAccessStrategy(active_queue=…)`. Ohne sie fällt sie still aus; die Scheduler-Absicherung verhindert dann zwar den Abbruch, nicht aber die Reservierung | offen |

Keine Risiken wurden entfernt.

---

## Readiness Gate

| Kriterium | Ergebnis |
|---|---|
| Alle BLOCKER behoben (P3-01, P3-02, P3-03) | **ja** |
| P3-04 gemäß verbindlicher LR+NR-Semantik behoben | **ja** – 40/40 Nachweis |
| Keine Ownership-Leaks | **ja** – 89 → 0 |
| Keine Abbrüche | **ja** – 10 → 0 |
| RR+RR bei festem Seed reproduzierbar | **ja** – 4 Konfigurationen × 3 Wiederholungen identisch |
| POPULARITY tatsächlich dynamisch aktiv | **ja** – finalnah 54/144 Aufrufe mit eigener Logik, Hot/Neutral/Cold erreicht |
| LR+NR misst NEAREST zum Originalstack | **ja** |
| ABC weiterhin sauber | **ja** – 69/69 Läufe ohne Befund, unverändert zu Phase 3 |
| Alle vier Policies erfüllen ihre Correctness-Contracts | **ja** |
| `move_recovery_unresolved = 0` | **ja** – 345/345 Läufe |
| Vollständige Testsuite grün | **ja** – 336 passed |
| Keine verbleibenden `xfail` für P3-01 bis P3-04 | **ja** – 0 xfailed, 0 xpassed |

## Urteil

```text
READY_FOR_PHASE_4
```

Begründung: Alle drei BLOCKER aus Phase 3 sind behoben und durch
Regressionstests abgesichert, die vorher rot waren. Der Re-Audit über 345
Läufe – dieselben Profile, Seeds und Invarianten wie in Phase 3 – ist
vollständig frei von Abbrüchen, Ownership-Verletzungen, Contract-Verletzungen
und physikalisch ungültigen Aktionen. Alle vier Policies tun jetzt fachlich
das, was ihr Name behauptet.

Das Urteil stützt sich ausdrücklich **nicht** auf Durchsatzzahlen. Diese haben
sich durch die Fixes verändert (bei POPULARITY und LR+NR erheblich), sind aber
kein Bewertungskriterium dieser Phase.

Offen bleiben R-1 bis R-14; keines davon verhindert die Arbeit an Phase 4.
R-4 ist genau ihr Gegenstand. R-12 und R-13 sollten vor dem eigentlichen
Strategievergleich noch geklärt werden, weil sie die Interpretation der
Ergebnisse berühren.

## Empfohlener nächster Schritt

Phase 4: Common Random Numbers. Konkret: alle Zufallsverbraucher
(`ActionCostModel`, `PlacementSelector`, `RelocationSelection`,
Request-Generierung) auf getrennte, über `SeedSequence.spawn()` vergebene
Ströme umstellen, sodass exogene Größen – insbesondere die
Pickstation-Servicezeiten – zwischen den Policies identisch bleiben. Die in
P3-03 eingeführte Ad-hoc-Ableitung `[seed, 1]` ist dabei mit abzulösen.

Vorher zu klären (fachlich, ohne Code): ob `baseline_reference` Teil des
Vergleichs ist (R-9), ob `popularity_warmup_requests` an die
Batching-korrigierte Zugriffsrate angepasst wird (R-12) und ob
`zipf_parameter = 1.5` bei 98,5 % Nachfrageanteil der A-Klasse die
gewünschten Unterschiede noch sichtbar macht (P3-10).

Es wurden **keine Git-Commits oder Pushes** ausgeführt. Phase 4 wurde nicht
begonnen.
