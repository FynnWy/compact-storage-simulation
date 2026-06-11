# 📦 Compact Storage Simulation

Eine diskrete Event-Simulation zur Modellierung und Analyse von kompakten Lagersystemen mit automatisierten Robotern und **Top-Access-Zugriff**.

---

## 🚀 Übersicht

Diese Simulation modelliert ein kompaktes Lager, in dem Kisten (Bins) in Stapeln (Stacks) gelagert und in einem Grid angeordnet sind. Roboter bearbeiten Anfragen, entnehmen Zielkisten von oben, bringen sie zu Pickstations und lagern sie anschließend wieder ein.

Der Fokus liegt vollständig auf einem realitätsnahen **Top-Access-System**:

- Bins können nur von oben aus einem Stack entnommen werden.
- Blockierende Bins müssen temporär ausgelagert werden.
- Entnommene blockierende Bins werden zurückgelegt.
- Die Target-Bin wird nach der Bearbeitung wieder oben auf den ursprünglichen Stack gelegt.
- Side-Access wird nicht mehr implementiert.

Das Projekt ist als **diskrete Event-Simulation (DES)** aufgebaut. Die Simulation läuft nicht kontinuierlich, sondern verarbeitet Ereignisse zu konkreten Zeitpunkten.

Die Strategie erzeugt zukünftig nicht mehr den vollständigen Plan im Voraus. Stattdessen wird nach jeder ausgeführten Aktion anhand des aktuellen Lagerzustands die nächste sinnvolle Aktion bestimmt.

### 🎯 Ziele der Simulation

- Analyse realistischer **Top-Access-Abläufe** in kompakten Lagersystemen.
- Bewertung von Scheduling-Regeln wie FIFO und EDF.
- Modellierung realistischer Roboteraktionen und Bewegungskosten.
- Untersuchung unterschiedlicher Nachfrageverteilungen wie Uniform, Zipf und ABC.
- Vergleich von Online- und Offline-Planung.
- Vorbereitung späterer Optimierungen für Relocation, Pickstation-Zuweisung und Multi-Robot-Koordination.

---

## 📑 Inhaltsverzeichnis

1. [Grundbegriffe](#-grundbegriffe)
2. [Simulation & Ablauf](#-simulation--ablauf)
3. [Komponenten](#-komponenten)
4. [Konfiguration](#-konfiguration)
5. [Projektstruktur](#-projektstruktur)
6. [Installation & Start](#-installation--start)
7. [Metriken](#-metriken)
8. [Roadmap](#-roadmap)

---

## 🧩 Grundbegriffe

| Begriff | Beschreibung |
| :--- | :--- |
| **Bin** | Eine Kiste im Lager. Wird nach der Bearbeitung wieder zurückgelegt. |
| **Stack** | Ein vertikaler Stapel aus mehreren Bins. Zugriff erfolgt ausschließlich von oben. |
| **Grid** | Das Lagerlayout, bestehend aus mehreren Stack-Positionen. |
| **Request** | Eine Anfrage nach einer bestimmten Zielkiste mit Ankunftszeit und Deadline. |
| **Robot** | Führt Aktionen aus, z. B. Fahren, Greifen, Umlagern, Entnehmen und Zurücklegen. |
| **Pickstation** | Externe Station, an der eine Target-Bin für eine definierte Bearbeitungszeit verweilt. |
| **Top-Access** | Zugriffskonzept, bei dem Bins nur von oben aus einem Stack entnommen werden können. |

---

## ⚙️ Simulation & Ablauf

### Event-Typen
| Typ | Bedeutung |
| :--- | :--- |
| `ARRIVAL` | Ein Request tritt in das System ein. |
| `ROBOT_ACTION` | Ein Roboter führt eine physische Bewegung aus. |
| `REQUEST_COMPLETE` | Ein Request ist vollständig abgeschlossen. |

### Der Prozess im Überblick

```mermaid graph TD A[Request kommt an] --> B[Request wird aktiv] B --> C[Scheduler weist freien Roboter zu] C --> D[RobotTask wird erzeugt] D --> E[Strategie plant genau nächste Aktion] E --> F[ROBOT_ACTION wird ausgeführt] F --> G{Request fertig?} G -->|Nein| E G -->|Ja| H[REQUEST_COMPLETE]

```

Die Strategie erzeugt zukünftig nicht mehr den vollständigen Plan im Voraus. Stattdessen wird nach jeder ausgeführten Aktion anhand des aktuellen Lagerzustands die nächste sinnvolle Aktion bestimmt.

---

## 🛠 Komponenten

### 🏗 SimulationEngine
Das Herzstück der Simulation. Initialisiert Grid, Bins, Roboter, Requests, Queues und steuert den gesamten Zeitverlauf.

### 🤖 Scheduler & Strategien

Der **Scheduler** entscheidet, welcher Request als nächstes einem freien Roboter zugewiesen wird:

- **FIFO**: Der älteste Request zuerst.
- **EDF**: Der Request mit der dringlichsten Deadline zuerst.

Die Lagerstrategie konzentriert sich auf:

- `TopAccessStrategy`: Zugriff von oben mit Umlagern blockierender Bins.

Side-Access wird nicht mehr weiterverfolgt.

### 🧠 Next-Step-Planning

Statt vollständige Aktionspläne vorab zu erzeugen, soll die Strategie pro Roboter-Task immer nur die nächste Aktion planen:

1. Ziel-Bin suchen.
2. Falls blockiert: oberste blockierende Bin temporär umlagern.
3. Falls erreichbar: Target-Bin entnehmen.
4. Target-Bin zur Pickstation bringen.
5. Blockierende Bins zurücklegen.
6. Target-Bin oben auf den ursprünglichen Stack zurücklegen.
7. Request abschließen.

Dadurch können mehrere Roboter robuster parallel arbeiten, weil Entscheidungen stets auf dem aktuellen Zustand basieren.

### 🚦 ConstraintManager

Prüft vor jeder Aktion, ob diese zulässig ist, z. B.:

- Existiert der Quellstack?
- Existiert der Zielstack?
- Liegt die zu bewegende Bin oben?
- Hat der Zielstack Kapazität?
- Befindet sich eine zurückzulegende Bin wirklich an der Pickstation?
- Wird dieselbe Bin nicht parallel durch mehrere Roboter bearbeitet?

Constraints bleiben auch mit Next-Step-Planning notwendig und dienen als Sicherheitsnetz.

---

## 📊 Metriken

Aktuell relevante Metriken:

- **Deadline Miss Rate**: Anteil der Requests, die zu spät abgeschlossen wurden.
- **Average Tardiness**: Durchschnittliche Verspätung.
- **Throughput**: Erfüllte Requests pro Zeiteinheit.

Zukünftig zusätzlich relevant:

- **Request Flow Time**: Zeit von Auftragseingang bis vollständiger Fertigstellung.
- **Pickstation Arrival Time**: Zeitpunkt, zu dem die Target-Bin an der Pickstation ankommt.
- **Pickstation Completion Time**: Zeitpunkt, zu dem die Bearbeitung an der Pickstation abgeschlossen ist.
- **Robot Busy Time / Idle Time**.
- **Relocation Count**.
- **Travel Time**.
- **Arm Movement Time**.

Für die Hauptbewertung ist perspektivisch **Auftragseingang bis vollständige Fertigstellung** am sinnvollsten, weil erst dann der Stack wieder konsistent hergestellt und der Auftrag wirklich abgeschlossen ist.

---

## 📂 Projektstruktur

```text
compact-storage-simulation
├── config/             # Konfiguration (SimulationConfig, Initalisierungs-Strategien)
├── events/             # Event-Definition und Typen
├── logging/            # Event-Logs
├── metrics/            # Datensammlung und Auswertung
├── requests_/          # Request-Generierung und Queues
├── simulation/         # Core-Logik (Engine, Handler, Scheduler)
├── state/              # Systemzustand (Grid, Stacks, Bins, Robots)
├── strategies/         # Lagerstrategien (TopAccess, SideAccess)
├── utils/              # Hilfsfunktionen & Visualisierung
├── main.py             # Haupteinstiegspunkt
└── requirements.txt    # Abhängigkeiten
```

---

## 💻 Installation & Start

### Voraussetzungen
- Python 3.8+
- pip

### Setup
1. Repository klonen:
   ```bash
   git clone https://github.com/ihr-repo/compact-storage-simulation.git
   cd compact-storage-simulation
   ```
2. Abhängigkeiten installieren:
   ```bash
   pip install -r requirements.txt
   ```

### Simulation ausführen
Starten Sie die Simulation über die `main.py`:
```bash
python main.py
```

---

## 🔧 Konfiguration

Die Parameter können in `config/simulation_config.py` angepasst werden:

```python
# Beispiel-Konfiguration
python self.grid_width = 5 
self.grid_depth = 5 
self.max_stack_height = 6 
self.num_robots = 4 
self.scheduler_strategy = "FIFO" 
self.request_arrival_strategy = "Poisson" 
self.bin_request_prob_strategy = "Uniform"
```

Zukünftig relevante Konfigurationen:
```python 
self.move_cost_per_grid_step = 1 
self.arm_move_cost_per_empty_level = 1 
self.pickstation_service_time_min = 4 
self.pickstation_service_time_max = 6 
self.bin_request_prob_strategy = "ABC"
```

---


> Dieses Projekt dient der wissenschaftlichen Untersuchung von Lagerlogistik-Algorithmen im Rahmen einer Masterarbeit an der Universität Hamburg (Institut für Operations Management).
