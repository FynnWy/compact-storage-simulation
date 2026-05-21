# Zusammenfassung: Compact Storage Simulation

## Systemtyp
Discrete Event Simulation (DES) eines automatisierten Compact-Storage-Lagers mit vertikalem Stacking und roboterbasiertem Retrieval.

## Kern-Komponenten

**State:**
- StorageGrid: width × depth × max_stack_height
- Bins: ID, Stack-Position, Level, Status (not_locked/locked/at_pickstation)
- Roboter: Position, current_task, Status
- Event Queue + Future Request Queue
- Pickstations: Mehrere Stationen mit Kapazität
- ReservationTable + TrafficManager (Kollisions- & Deadlock-Vermeidung)

**Event-Driven Architecture:**
- EventTypes: ARRIVAL, REQUEST_COMPLETE, PICKSTATION_COMPLETE, Roboter-Actions
- Time advancement mit periodischem Cleanup (alle 10 ZE)
- Validation: Bin-Uniqueness, Stack-Capacities, Metadaten-Konsistenz

## Request-Generierung & Nachfrageverteilung

**Arrival Strategy:**
- **Poisson**: Exponential-verteilte Inter-Arrival-Times
- **Utilization**: Steuerung der Systemlast (z.B. 0.6 = 60% Auslastung)

**Bin Request Probability Strategy:**
- **Uniform**: Alle Bins gleichwahrscheinlich
- **Zipf**: ABC-Verteilung mit Parameter α (z.B. 1.1)
  - Hot Items: Top 20% der Bins werden überproportional häufig angefragt
  - Simuliert realistische Lagernachfrage (Pareto-Prinzip)

**Hot Bin Determination:**
- Bei Zipf: hot_fraction = 0.2 (obere 20% der Bin-IDs)
- Beeinflusst nur Request-Wahrscheinlichkeit, nicht initiale Platzierung

## Scheduling & Strategien

**Scheduler:**
- **FIFO**: First In First Out
- **EDF**: Earliest Deadline First (basierend auf latest_time)
- ActiveQueue: pending_tasks + waiting_tasks + completed_tasks

**Retrieval Strategy:**
- **TopAccessStrategy**: Nur oberste Bin direkt zugänglich
- **RelocationSelection**: Kostenbasierte Auswahl von Relocation-Zielen
  - Berücksichtigt ActiveQueue für intelligente Platzierung
  - Vermeidet weitere Blockierungen

## Kostenmodell (Realistische Aktionskosten)

- **move_cost_per_grid_step**: Manhattan-Distanz × Kostenfaktor
- **arm_move_cost_per_level**: Vertikale Armbewegung (abhängig von Zugriffstiefe)
- **grip_cost**: Greifen einer Bin
- **drop_cost**: Ablegen einer Bin
- **pickstation_service_time**: Min/Max Range (stochastisch)

## Verkehrsmanagement

**Highway-System (optional):**
- Patterns: ring, rows, lanes, none
- **wrong_direction_penalty**: Strafkosten für Bewegung gegen bevorzugte Richtung
- **Deadlock Detection**: Periodische Prüfung (alle 10 ZE)
  - Wait-For-Graph-Analyse
  - Victim-Selection mit Task-Requeue

**Reservation-System:**
- Zeit-basierte Reservierung von Grid-Zellen
- Cleanup vor vergangenen Zeitpunkten

## Initialisierung

**Init Strategy:**
- **random_distribution**: Bins zufällig verteilt über alle verfügbaren Stack-Positionen
- Respektiert max_stack_height
- Unabhängig von Hot-Item-Klassifikation

## Metriken

- **target_bin_removals**: Anzahl erfolgreich geholter Ziel-Bins
- **relocation_count**: Anzahl notwendiger Umlagerungen
- **time_series**: Event-basierte Zeitreihen
- Roboter-Auslastung, Wartezeiten, Durchsatz

## Pickstation-Konfiguration

- **num_pickstations**: Anzahl paralleler Ausgabestationen
- **capacity**: Bins pro Station
- **queue_strategy**: FCFS oder PRIORITY
- **Position**: Automatisch am Grid-Rand platziert (-1, y)





# Retrieval-, Relocation- und Return-Strategien

## 1. RETRIEVAL-STRATEGIE: Wie wird eine Kiste geholt?

**TopAccessStrategy - Nur oberste Bin zugänglich**

Die Simulation nutzt einen Top-Access-Ansatz: Es kann immer nur die oberste Bin eines Stacks direkt gegriffen werden.

**Entscheidungslogik beim Retrieval:**

Wenn eine Target-Bin angefordert wird, ermittelt die TopAccessStrategy die Zugriffstiefe. Alle Bins, die ÜBER der Target-Bin liegen, sind Blocker und müssen temporär weggelagert werden.

Die Strategie arbeitet sich von oben nach unten durch den Stack:
- Oberste Bin wird als erstes weggelagert
- Dann die nächste darunter
- Bis die Target-Bin erreicht ist

Jeder Blocker wird sofort beim Identifizieren einer RelocationSelection-Entscheidung unterzogen und in einem temporären Speicher im RobotTask vermerkt.

## 2. RELOCATION-STRATEGIE: Wohin werden Blocker-Kisten gelegt?

**Kostenbasierte Bewertung aller verfügbaren Stacks**

Für jeden Blocker wird ein temporärer Zielstack gewählt. Die RelocationSelection bewertet ALLE verfügbaren Stacks im Grid nach folgenden Kriterien:

**Hard Constraints (Ausschlusskriterien):**
- Stack muss freie Kapazität haben
- Stack darf nicht gesperrt sein
- Stack darf nicht der Quellstack sein

**Soft Constraints (Kostenbewertung):**

Die Entscheidung basiert auf einer Scoring-Funktion mit zwei Hauptkomponenten:

**Distanzkomponente:** Kürzere Wege werden bevorzugt. Die Manhattan-Distanz vom Quellstack zum Zielstack wird mit den konfigurierten Bewegungskosten multipliziert. Direkte Nachbar-Stacks erhalten einen Bonus.

**Critical-Stack-Penalty:** Stacks, die für andere laufende oder wartende Tasks wichtig sind, erhalten einen massiven Strafaufschlag von 1000 Punkten. Ein Stack gilt als kritisch, wenn er eine Bin enthält, die bereits für einen anderen Task reserviert ist - entweder als Target-Bin oder als Blocker mit Ownership.

**Auswahlprinzip:** Der Stack mit dem niedrigsten Score gewinnt.

**Strategische Effekte:**
- Verhindert Ping-Pong-Effekte: Blocker werden nicht auf Stacks gelegt, die bald wieder für andere Tasks benötigt werden
- Minimiert Gesamttransportzeit durch kurze Wege
- Dynamische Anpassung an aktuelle Workload-Situation durch Active-Queue-Integration

## 3. RETURN-STRATEGIE: Wohin werden Blocker zurückgelegt?

**Striktes Original-Stack-Prinzip**

Die Return-Strategie folgt einem deterministischen Ansatz: Jeder Blocker geht IMMER zurück auf seinen ursprünglichen Stack, von dem er gekommen ist.

**LIFO-Reihenfolge (Last In, First Out):**

Die Blocker werden in umgekehrter Reihenfolge ihrer Entfernung zurückgelegt. Der zuletzt entfernte Blocker wird als erstes zurückgebracht, der erste als letztes.

**Warum diese Strategie?**

Diese Entscheidung stellt sicher, dass die ursprüngliche Stack-Ordnung exakt wiederhergestellt wird. Wenn Blocker A und B von einem Stack genommen wurden (A lag über B), dann kommt erst B zurück, dann A darüber - die Ordnung bleibt erhalten.

**Keine Optimierung beim Return:**

Es findet KEINE erneute Platzwahl statt. Auch wenn während der Return-Phase bessere oder nähere Stacks verfügbar werden, werden Blocker konsequent zu ihrem Ursprungsstack zurückgebracht. Dies vereinfacht die Logik und garantiert Konsistenz.

**Alternative wäre nicht implementiert:** Eine intelligente Return-Strategie, die Blocker auf optimierte neue Positionen verteilt basierend auf Zugriffshäufigkeiten oder zukünftigen Requests, existiert bisher nicht.

## Zusammenfassung der Entscheidungshierarchie

**Retrieval:** Top-Down-Durchlauf, deterministisch - alle Blocker müssen weg

**Relocation:** Kostenbasierte Optimierung unter Berücksichtigung von Distanz und Workload-Konflikten

**Return:** Deterministisch, LIFO zurück zum Ursprungsstack ohne Re-Optimierung







## Vollständiger Task-Lifecycle

1. REQUEST_ARRIVAL
   ↓
2. SCHEDULER: Task → Robot (idle)
   ↓
3. RETRIEVING Phase:
   - Blocker identifizieren (alle Bins über Target)
   - Für jeden Blocker:
     * RelocationSelection wählt temp_stack
     * Blocker → temp_storage (LIFO)
     * Move + Pickup + Move + Drop Events
   - Target-Bin abholen
   - Move zu Pickstation
   ↓
4. PICKSTATION_SERVICE
   ↓
5. RETURNING Phase:
   - Für jeden Blocker in temp_storage (LIFO):
     * Move zu temp_stack
     * Pickup Blocker
     * Move zu original_stack
     * Drop Blocker
   ↓
6. COMPLETE
   - Robot → idle
   - Metrics update