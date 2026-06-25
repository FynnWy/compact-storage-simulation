
## 1. Port-Reservierungsfehler, gelöst: JA
**RuntimeError:** Robot X cannot enter port PS_0: reserved for robot None

**Betroffene Tests:** viele Multi-Robot-, Scheduler-, Highway- und Workflow-Tests.

**Interpretation:** Der Port PS_0 wird als reserviert markiert, obwohl der reservierende Robot None ist. 
Das deutet auf inkonsistente Port-Reservierungslogik hin (z. B. Reservierung gesetzt, aber Besitzer nicht gespeichert,
oder nicht freigegeben).

**Wahrscheinliche Ursache**
1. Race-/State-Management-Problem im Port-Manager.
2. Freigabe einer Reservierung erfolgt nicht korrekt.
3. Prüfung "port reserved?" berücksichtigt Besitzer None nicht korrekt.

NACH FIX:
Die neuen Fehler sagen:
„In vielen Abläufen fährt ein Roboter in den Port, ohne vorher reserve() aufgerufen zu haben.“
Das ist ein Designproblem im Aufrufercode, nicht in der Pickstation:
Pathfinding / EventHandler / Robot-Move-Logik nutzt robot_enters offenbar direkt,
aber ohne vorher reserve(robot_id) aufzurufen.
Vor unserem Fix wurde das still toleriert.
Jetzt knallt es – was fachlich korrekt ist.

Was muss als Nächstes angepasst werden?
Nächster Schritt ist nicht, den Port wieder „weicher“ zu machen, sondern:
1. An der Stelle, wo ein Roboter in eine Port-Zelle eintritt (typisch:
EventHandler bei einem ROBOT_MOVE oder
spezielle Logik „Robot erreicht Pickstation“),
dort muss vor dem Eintritt:
   ps = state.find_pickstation_at(robot_position_next)
   if ps is not None:
       if not ps.reserve(robot.robot_id):
           # Port ist für anderen Robot reserviert → warten / neu planen / abbrechen
           ...
       else:
           ps.robot_enters(robot.robot_id)
2. Beim Verlassen des Ports (robot_leaves) und bei Abbruch von Tasks muss die Reservierung sauber freigegeben werden (release_reservation / robot_leaves).


## 2. Rückgabestapel-/Top-of-Stack-Invariante verletzt, gelöst: JA
**RuntimeError:** Cannot complete request 0: target bin 102 is not on top of return stack S_5_3; top is 135

**Betroffene Tests:** TestDifferentStrategies.

**Interpretation:** Beim Abschluss eines Requests wird erwartet, dass der Ziel-Bin oben auf dem Return-Stack liegt. 
Tatsächlich liegt ein anderer Bin oben.

**Wahrscheinliche Ursache**
1. Veralteter Test.
2. Relocation-/Return-Logik verletzt die Stack-Reihenfolge.
3. Bin wird in falscher Reihenfolge zurückgelegt.
4. Scheduler/Strategie erzeugt einen Ablauf, den die Stack-Invariante nicht abdeckt.

NACH FIX:
1. TopAccessStrategy: Keine weitere Action mehr planen, wenn PHASE_COMPLETE erreicht.
2. EventHandler: REQUEST_COMPLETE-Events erzeugen, wenn Target-Return erfolgreich.

## 3. Ungültige Auswahl des Original-Return-Stacks, gelöst: NEIN

WICHTIG: RÜCKLAGERUNG, ETC. Darf in den Bufferstacks passieren. NUR DÜRFEN DORT KEINE BLOCKIERENDEN BINS VON ANDEREN STACKS ZWISCHEN-
GELAGERT WERDEN

**RuntimeError:** Cannot select original return stack: stack S_0_1 is in a port buffer zone or at a port

**Betroffene Tests:** NoInfiniteLoop, BinConsistency, StackCapacity.

**Interpretation:** Die Logik versucht einen Stack auszuwählen, der laut System gerade gesperrt/ungeeignet ist (Port-Zone oder Port-Position).

**Wahrscheinliche Ursache**
1. Fehlerhafte Filterung verfügbarer Stacks.
2. State-Update nach Port-Nutzung fehlt oder kommt zu spät.
3. Geometrie-/Buffer-Zonen-Definition inkonsistent.


## 4. Fehlende Attribute im Test-Dummy, gelöst: NEIN
**AttributeError:** 'DummyState' object has no attribute 'port_positions'

**Betroffene Tests:** test_event_handler_smart_skip_*.

**Interpretation:** Test-Dummy ist nicht mehr kompatibel mit der Produktionsschnittstelle.

**Wahrscheinliche Ursache**
1. Neue Abhängigkeit auf state.port_positions eingeführt.
2. Tests nicht aktualisiert.


## 5. Kollisionsfehler, gelöst: NEIN
**Failed:** Collision at (-1, 0) between Robot 0 and Robot 1

**Betroffene Tests:** test_no_collision_two_robots.

**Interpretation:** Das Kollisionsvermeidungssystem lässt mindestens einen Konfliktpunkt zu.
Die Pickstations liegen nun INNERHALB des Grids, die Kollision mit -1 sollte eigentlich gar nicht möglich sein.
Vielleicht ein veralteter Test?

**Wahrscheinliche Ursache**
1. Veralteter Test?


## 6. Strategie-Selektor-Assertions, gelöst: NEIN
assert (5, 0) in {(0, 0), (2, 0)} bzw. assert (4, 0) == (0, 0)

**Betroffene Tests:** ABC- und Popularity-Selector.

**Interpretation:** Die Heuristik liefert andere Plätze als erwartet.

**Wahrscheinliche Ursache**
1. Scoring-/Gewichtungsänderung.
2. Sortierkriterium nicht deterministisch.
3. Test-Erwartungen veraltet.