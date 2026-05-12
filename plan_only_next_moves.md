# Umstellung auf Next-Step-Planning statt statischer Komplettplanung

## Ausgangsproblem

Aktuell erzeugt die Strategie beim Scheduling eines Requests einen vollständigen Plan im Voraus, z. B.:

Diese Events werden direkt komplett in die EventQueue gelegt.

Das funktioniert bei einem Roboter relativ gut, wird aber bei mehreren Robotern problematisch:

- Roboter A plant auf Basis des aktuellen States.
- Roboter B plant ebenfalls auf Basis eines ähnlichen States.
- Danach verändern beide Roboter parallel das Lager.
- Bereits erzeugte Aktionen können dadurch veralten.
- Eine Aktion kann später zwar formal noch ausführbar sein, aber nicht mehr optimal oder sogar nicht mehr nötig.
- Wenn eine Aktion nicht mehr ausführbar ist, wird sie aktuell nur verzögert (`retry`), aber nicht neu geplant.

Das führt zu hohen `retry_count`s und ineffizientem Verhalten.

## Ziel

Die Strategie soll nicht mehr den kompletten Request-Ablauf im Voraus planen.

Stattdessen soll immer nur die nächste aktuell sinnvolle Aktion geplant werden:
text Request wird Roboter zugewiesen → Strategie plant genau eine nächste Action anhand des aktuellen States → Action wird ausgeführt → danach wird anhand des neuen States die nächste Action geplant → ... → Request wird abgeschlossen

Dadurch basiert jede Entscheidung auf dem tatsächlich aktuellen Lagerzustand.

## Warum löst das das Problem?

Bei statischer Komplettplanung kann eine Aktion veralten:
text t=10: Plan wird erzeugt t=12: anderer Roboter verändert den Stack t=15: alte Action soll ausgeführt werden

Bei Next-Step-Planning wird nach jeder ausgeführten Aktion neu entschieden:
text t=10: nächste Action planen t=10: Action ausführen t=11: aktuellen State anschauen t=11: nächste Action planen

Damit werden veraltete Restpläne vermieden.

Das reduziert:

- unnötige Umlagerungen
- hohe Retry-Zahlen
- stale `return`-Actions
- Konflikte durch parallele Roboterbewegungen
- inkonsistente Aktionen auf Basis alter Stack-Zustände

Constraints bleiben trotzdem notwendig, werden aber eher zum Sicherheitsnetz.

---

# Vorgeschlagene Architektur

## 1. Task-Zustand einführen

Ein Roboter sollte nicht nur eine `request_id` speichern, sondern einen Task mit Fortschritt.

Neue Datei z. B.: text simulation/robot_task.py

Beispiel: python class RobotTask: def **init**(self, request): self.request = request self.phase = "retrieve_target" self.target_stack_id = None self.temp_storage = [] self.target_removed = False

Mögliche Phasen:
text retrieve_target # Zielkiste freilegen und entfernen restore_blockers # blockierende Kisten zurücklegen return_target # Zielkiste zurücklegen complete # Request abgeschlossen

`temp_storage` speichert die während des Zugriffs ausgelagerten Bins, z. B.:

Damit weiß die Strategie später, welche Bins zurückgelegt werden müssen.

---

## 2. Robot anpassen

Aktuell hält der Roboter vermutlich nur eine `current_task` oder `request_id`.

Ziel: python robot.assign_task(task) robot.current_task = task robot.status = "busy"

Für Debug-Ausgabe kann weiterhin die Request-ID angezeigt werden:
python def **repr**(self): task_id = self.current_task.request.request_id if self.current_task else None return f"Robot(id={self.robot_id}, status={self.status}, task={task_id})"


---

## 3. Strategie-Methode `next_action(state, task)` einführen

Statt: python plan = strategy.plan(state, request)

soll es geben: python action = strategy.next_action(state, task)

Diese Methode gibt genau eine nächste Aktion zurück.

Mögliche Rückgaben: python {"type": "relocate", ...} {"type": "remove_target", ...} {"type": "return", ...} {"type": "request_complete"}


oder `None`, falls aktuell keine Aktion erzeugt werden kann.

---

# TopAccessStrategy als Next-Step-Strategie

## Grundidee

Die Strategie schaut bei jedem Aufruf auf den aktuellen State.

### Phase `retrieve_target`

1. Ziel-Bin im Lager suchen.
2. Wenn Ziel-Bin nicht gefunden wird:
   - prüfen, ob sie an der Pickstation ist
   - dann Phase wechseln
3. Wenn Ziel-Bin im Stack liegt:
   - Wenn Ziel-Bin oben liegt:
     - `remove_target`
   - Sonst:
     - oberste blockierende Bin in Buffer-Stack umlagern
     - diese Umlagerung in `task.temp_storage` merken

### Phase `restore_blockers`

1. Wenn `temp_storage` nicht leer:
   - letzte ausgelagerte Bin zurücklegen
2. Wenn `temp_storage` leer:
   - Phase `return_target`

### Phase `return_target`

1. Ziel-Bin von Pickstation zurück in den ursprünglichen Zielstack legen.
2. Phase `complete`

### Phase `complete`

1. `request_complete` zurückgeben.

---

# Beispiel-Logik für `next_action`

Pseudo-Code:
python def next_action(self, state, task): request = task.request target_bin_id = request.target_box_id
if task.phase == "retrieve_target":
    target_stack, target_level = self._find_bin(state, target_bin_id)

    if target_stack is None:
        target_bin = state.get_bin_by_id(target_bin_id)

        if target_bin.get_status() == "at_pickstation":
            task.phase = "restore_blockers"
            return self.next_action(state, task)

        raise RuntimeError("Target bin not found")

    task.target_stack_id = target_stack.stack_id

    top_bin = target_stack.peek()

    if top_bin.bin_id == target_bin_id:
        task.phase = "restore_blockers"
        return {
            "type": "remove_target",
            "from_stack": target_stack.stack_id,
            "bin_id": target_bin_id,
        }

    buffer_stack = self._select_buffer_stack(state, exclude_stack=target_stack)

    task.temp_storage.append({
        "bin_id": top_bin.bin_id,
        "from_stack": target_stack.stack_id,
        "buffer_stack": buffer_stack.stack_id,
    })

    return {
        "type": "relocate",
        "from_stack": target_stack.stack_id,
        "to_stack": buffer_stack.stack_id,
        "bin_id": top_bin.bin_id,
    }

if task.phase == "restore_blockers":
    if task.temp_storage:
        move = task.temp_storage.pop()
        return {
            "type": "return",
            "from_stack": move["buffer_stack"],
            "to_stack": move["from_stack"],
            "bin_id": move["bin_id"],
        }

    task.phase = "return_target"
    return self.next_action(state, task)

if task.phase == "return_target":
    task.phase = "complete"
    return {
        "type": "return",
        "from_stack": None,
        "to_stack": task.target_stack_id,
        "bin_id": target_bin_id,
    }

if task.phase == "complete":
    return {
        "type": "request_complete",
        "request_id": request.request_id,
        "bin_id": target_bin_id,
    }

Wichtig: Das ist nur Pseudo-Code. Die finale Implementierung muss prüfen, ob `target_stack_id` als String oder Tuple verwendet wird.

---

# EventBuilder anpassen

Die Methode `build_event_from_action(...)` kann weiter genutzt werden.

Wichtig ist aber:

- Es wird nicht mehr `build_events_from_plan(...)` für einen kompletten Plan verwendet.
- Stattdessen wird immer nur ein Event aus genau einer Action erzeugt.

Beispiel:
python event = event_builder.build_event_from_action event_queue.push(event)

---

# Scheduler anpassen

Der Scheduler soll keinen kompletten Plan mehr erzeugen.

Aktuell ungefähr:
python plan = self.strategy.plan(state, request)
return { "request": request, "robot": robot, "plan": plan, "start_time": current_time, }

Neu:
python task = RobotTask(request) robot.assign_task(task) self.active_queue.mark_assigned(request, robot)
action = self.strategy.next_action(state, task)
return { "request": request, "robot": robot, "task": task, "action": action, "start_time": current_time, }


Oder alternativ:

- Scheduler weist nur den Task zu.
- EventHandler fragt danach die erste Action bei der Strategie ab.

---

# EventHandler anpassen

## Bei Scheduling

Wenn ein Request einem Roboter zugewiesen wird:
python action = strategy.next_action(state, robot.current_task) event = event_builder.build_event_from_action(action, request, robot, current_time) event_queue.push(event)


## Bei `ROBOT_ACTION`

Aktueller Ablauf:
text Constraint prüfen Action ausführen

Neuer Ablauf:

text Constraint prüfen Action ausführen nächste Action für denselben Task planen nächstes Event erzeugen
Pseudo-Code:
python def _handle_robot_action(self, event): action = self.event_builder.get_action_from_event(event)
can_execute = self.constraint_manager.can_execute(action, self.state)

if not can_execute:
    delayed_event = self.event_builder.delay_event(event, self.state.t)
    self.event_queue.push(delayed_event)
    return

self.executor.execute(event, self.state)

robot = event.payload["robot"]
task = robot.current_task

next_action = self.scheduler.strategy.next_action(self.state, task)

next_event = self.event_builder.build_event_from_action(
    action=next_action,
    request=task.request,
    robot=robot,
    time=self.state.t + self.event_builder.action_duration,
)

self.event_queue.push(next_event)


Wichtig:

- Nach einer `ROBOT_ACTION` wird nur die nächste Action desselben Tasks geplant.
- Es wird kein neuer Request gescheduled.
- Neue Requests werden weiterhin erst nach `REQUEST_COMPLETE`/Scheduling-Phase zugewiesen.

---

# `REQUEST_COMPLETE`

`request_complete` bleibt ein eigenes Event.

Wenn es verarbeitet wird: python active_queue.mark_completed(request) robot.clear_task()


Danach kann die `SimulationEngine` wie bisher freie Roboter neu schedulen.

---

# Umgang mit blockierten Actions

Es gibt zwei Optionen.

## Option A: Delay beibehalten

Einfachste Variante:


text Action blockiert → dieselbe Action später nochmal versuchen


Vorteil:

- wenig Umbau
- stabil

Nachteil:

- kann weiterhin zu Retries führen

## Option B: Bei Block neu planen

Passender zu Next-Step-Planning:

text Action blockiert → Action verwerfen → next_action erneut aus aktuellem State berechnen


Vorteil:

- weniger stale Actions
- weniger Retries
- dynamischer

Nachteil:

- etwas komplexer
- man muss aufpassen, dass `task.temp_storage` konsistent bleibt

Empfehlung:

1. Erst Option A implementieren.
2. Danach Option B ergänzen, wenn das Grundsystem stabil läuft.

---

# Weiterhin notwendige Constraints

Next-Step-Planning ersetzt Constraints nicht.

Weiterhin wichtig:

- Source-Stack existiert
- Target-Stack existiert
- Bin liegt oben
- Zielstack hat Kapazität
- Pickstation-Return nur, wenn Bin wirklich an Pickstation ist
- Keine parallele Bearbeitung derselben Ziel-Bin
- Keine Stack-Kapazitätsverletzung

Constraints bleiben das Sicherheitsnetz gegen ungültige Aktionen.

---

# Erwarteter Effekt

Die Umstellung sollte:

- hohe Retry-Zahlen reduzieren
- veraltete Komplettpläne vermeiden
- parallele Roboter robuster machen
- unnötige Umlagerungen reduzieren
- weniger Konflikte durch geänderte Stack-Zustände erzeugen
- die Simulation realistischer machen

---

# Wichtigste Modellentscheidung

Die Strategie muss wissen, was zu einem Request bereits passiert ist.

Daher ist der neue `RobotTask` bzw. `ActiveTask` zentral.

Ohne Task-Zustand kann `next_action(...)` nicht sauber entscheiden:

- welche Bins ausgelagert wurden
- wohin sie zurück müssen
- ob die Ziel-Bin schon an der Pickstation ist
- ob der Request abgeschlossen werden kann

---

# Empfohlene Umsetzungsschritte

1. `RobotTask` einführen.
2. `Robot.assign_task(...)` so anpassen, dass ein Task-Objekt gespeichert wird.
3. `TopAccessStrategy.next_action(state, task)` implementieren.
4. Scheduler so umbauen, dass er keinen Komplettplan mehr erzeugt.
5. EventHandler so umbauen, dass nach jeder erfolgreichen Action die nächste Action geplant wird.
6. `build_events_from_plan(...)` nicht mehr im neuen Flow verwenden.
7. Constraints beibehalten.
8. Debug-Ausgaben für blockierte Actions behalten.
9. Nach Stabilisierung optional Replanning bei blockierten Actions einführen.

---

# Fazit

Ja, Next-Step-Planning ist die richtige Richtung.

Es löst das Hauptproblem der aktuellen Architektur:


text statische Komplettpläne veralten durch parallele Roboterbewegungen


Die Simulation wird dadurch robuster, dynamischer und näher am tatsächlichen Ablauf eines diskreten Systems.
