AutoStore-Simulation – Port- und Rücklagerungsmodell (Verbindliche Implementierung)

Ziel

Dieses Dokument definiert das vollständige Verhalten von Pickstations (Ports), Robotern und der Rücklagerung von Bins.

Die Implementierung soll nicht das reale AutoStore-System im Detail nachbilden, sondern eine vereinfachte, konsistente, deterministische und deadlock-resistente Simulation erzeugen.

Alle Regeln in diesem Dokument sind verbindlich.

⸻

Position der Port-Säule (Pickstation) im Grid:

Die Port-Säule befindet sich vollständig innerhalb des Grids und belegt dort eine reguläre Grid-Zelle. Sie liegt an derselben Position, an der sich die Pickstation logisch befindet, wird jedoch nicht außerhalb des Grids modelliert. 
Für die Simulation bedeutet dies, dass die Port-Säule eine normale Grid-Koordinate besitzt und von Robotern wie jedes andere Grid-Feld angefahren werden kann. Da sich die Pickstationen am Rand des Grids befinden, liegt die Port-Säule ebenfalls auf einer Randposition innerhalb des Grids. 
Die Port-Säule stellt somit die direkte Schnittstelle zwischen Grid und Pickstation dar. Es existiert keine zusätzliche externe Übergabezone außerhalb des Grids. Alle Anfahr-, Übergabe- und Abholvorgänge finden ausschließlich auf dieser im Grid liegenden Portposition statt. 
Die Position der Pickstation bleibt gegenüber dem bisherigen Modell unverändert; lediglich die technische Umsetzung erfolgt als spezielle, nicht lagerfähige Grid-Säule innerhalb des Grids. Dadurch können Roboter die Portposition direkt anfahren, ohne das Grid jemals zu verlassen.

⸻

Port-Säule (Pickstation)

Jeder Port besitzt eine dedizierte Port-Säule.

Diese Säule gehört nicht zum normalen Lagerbereich.

Verbotene Aktionen in der Port-Säule

Folgende Aktionen sind innerhalb der Port-Säule grundsätzlich verboten:

* Einlagerung
* Rücklagerung
* Umlagerung
* Zwischenlagerung
* Digging
* Nutzung als Hole
* Nutzung als temporärer Lagerplatz

Die Port-Säule dient ausschließlich der Übergabe zwischen Roboter und Pickstation. Die Portsäule ist die Pickstation mit der Logik.

Normale Lagerbins dürfen sich dort niemals befinden.

HIERFÜR MUSS WAHRSCHEINLICH DIE INITALISIERUNG DES GRIDS ANGEPASST WERDEN

⸻

Port-Pufferzone

Zusätzlich zur Port-Säule existiert eine Port-Pufferzone.

Definition:

* Distanz 0 = Portposition
* Distanz 1 = alle direkt benachbarten Grid-Felder

Die Port-Pufferzone umfasst somit alle Felder mit Distanz ≤ 1 zum Port.

⸻

Rücklagerung von Bins

Das konkrete Slotting-Verfahren (ABC, Nachfrageklassen, Strategien usw.) wird separat definiert.

Unabhängig von der verwendeten Strategie gelten folgende Regeln:

Verbotene Rücklagerungspositionen

Ein Bin darf niemals zurückgelagert werden auf:

* Distanz 0 zum Port
* Distanz 1 zum Port

Die Port-Säule und die gesamte Port-Pufferzone sind für Rücklagerungen ausgeschlossen.

Begründung:

* Vermeidung lokaler Verkehrs-Hotspots
* Sicherstellung der Port-Erreichbarkeit
* Reduktion von Staus
* Verbesserung der Deadlock-Resistenz

Jede Rücklagerungsstrategie muss diese Einschränkung zwingend berücksichtigen.

⸻

Bin-Abgabe am Port

Ablauf

2. Roboter fährt zur Portposition.
3. Nach Erreichen der Portposition wartet der Roboter exakt 1 Zeiteinheit.
4. Nach Ablauf dieser Zeiteinheit gilt der Bin als abgegeben.
5. Der Bin wird aus dem Besitz des Roboters entfernt.
6. Der Auftrag wird abgeschlossen.
7. Der Roboter verlässt die Portposition sofort.

Erst danach kann ein neuer Auftrag ausgeführt werden.

⸻

Bin-Abholung am Port

Ablauf

2. Ein Roboter erhält den Rücklagerungsauftrag.
3. Der Roboter fährt zur Portposition.
4. Nach Erreichen der Portposition wartet der Roboter exakt 1 Zeiteinheit.
5. Nach Ablauf dieser Zeiteinheit befindet sich der Bin auf dem Roboter.
6. Der Roboter verlässt die Portposition sofort.
7. Anschließend erfolgt die Rücklagerung.

⸻

Übergabezeit

Für jede Übergabe gilt:

* Abgabe = exakt 1 Zeiteinheit
* Abholung = exakt 1 Zeiteinheit

Es werden keine weiteren Portprozesse simuliert.

⸻

Portkapazität

Jeder Port darf sich niemals mehr als ein Roboter gleichzeitig auf der Portposition befinden.

Es dürfen aber unendlich viele Bins am Port abgegeben werden.

⸻

Wann gilt ein Port als frei?

Ein Port gilt NICHT als frei sobald die Übergabe abgeschlossen wurde.

Ein Port gilt ERST dann als frei wenn:

* Übergabe abgeschlossen
    UND
* Roboter hat die Portposition verlassen

Vorher darf kein weiterer Roboter einfahren.

⸻

Reservierungslogik

Jeder Port besitzt:

reservedForRobot = null

Sobald ein Roboter den Zuschlag für den Port erhält:

reservedForRobot = robotId

Nur dieser Roboter darf den Port anfahren.

Alle anderen Roboter müssen warten.

⸻

Freigabe

Nach dem Verlassen der Portposition:

reservedForRobot = null

Erst danach wird ein neuer Roboter ausgewählt.

⸻

Priorisierung beim Portzugang

Ziel:

Der Port soll möglichst keine Leerlaufzeiten haben.

Reines Earliest Deadline First (EDF) wird deshalb nicht verwendet.

Die Auswahl erfolgt zweistufig.

⸻

Stufe 1 – Portnahe Kandidaten

Zunächst werden ausschließlich Roboter betrachtet, die sich bereits im unmittelbaren Portbereich befinden oder den Port praktisch erreicht haben.

Beispiele:

* direkt benachbart zum Port
* unmittelbar vor dem Port wartend
* nur noch wenige Schritte entfernt

Diese Roboter besitzen Vorrang gegenüber weit entfernten Robotern.

Begründung:

Ein freier Port soll niemals auf einen weit entfernten Roboter warten müssen.

⸻

Stufe 2 – Earliest Deadline First

Existieren mehrere portnahe Kandidaten:

Dann gewinnt der Auftrag mit der frühesten Deadline.

⸻

Wichtige EDF-Ausnahme

Ein weit entfernter Roboter mit früherer Deadline darf keinen bereits portnahen Roboter verdrängen.

Beispiel:

Robot A:

* 1 Feld vom Port entfernt
* Deadline 120

Robot B:

* 40 Felder vom Port entfernt
* Deadline 100

Gewinner:

Robot A

Grund:

Portauslastung besitzt Vorrang vor globalem EDF.

⸻

Verhalten bei belegtem Port

Wenn ein Port belegt oder reserviert ist:

* darf kein weiterer Roboter einfahren
* darf kein weiterer Roboter den Port reservieren

Der wartende Roboter bleibt auf seiner aktuellen Position.

⸻

Idle-Roboter

Idle-Roboter dürfen sich nicht dauerhaft im Portbereich aufhalten.

Insbesondere dürfen sie:

* nicht auf der Portposition stehen
* nicht absichtlich in der Port-Pufferzone parken
* keine Warteschlangen bilden

Nach Abschluss eines Auftrags müssen Idle-Roboter den Portbereich verlassen.

⸻

Aktive Roboter

Diese Einschränkung gilt nicht für aktive Roboter.

Ein Roboter mit aktivem Portauftrag darf in Portnähe warten.

⸻

Freies Ausfahrfeld

Während ein Roboter den Port benutzt, muss mindestens ein benachbartes Feld als Ausfahrmöglichkeit frei bleiben.

Der Roboter auf dem Port muss die Portposition jederzeit verlassen können.

Andere Roboter dürfen dieses Ausfahrfeld nicht blockieren.

⸻

Deadlock-Prävention

Folgende Situationen dürfen niemals entstehen:

* Port vollständig von Robotern eingeschlossen
* Roboter auf Port kann nicht ausfahren
* Zwei Roboter fahren gleichzeitig auf denselben Port
* Zwei Roboter besitzen gleichzeitig dieselbe Portreservierung

Falls dennoch ein Deadlock erkannt wird, darf zusätzlich der bestehende Deadlock Resolver verwendet werden.

⸻

Verbindliche Kernregeln

* Port-Säulen enthalten niemals Lagerbins.
* Port-Säulen dürfen niemals für Digging verwendet werden.
* Port-Säulen dürfen niemals als Hole verwendet werden.
* Distanz 0 zum Port ist für Rücklagerung verboten.
* Distanz 1 zum Port ist für Rücklagerung verboten.
* Übergabezeit beträgt exakt 1 Zeiteinheit.
* Portkapazität beträgt genau 1 Roboter.
* Port wird erst nach Verlassen der Portposition freigegeben.
* Jeder Port besitzt eine exklusive Reservierung.
* Nur der reservierte Roboter darf einfahren.
* Portnahe Roboter besitzen Vorrang.
* Innerhalb portnaher Kandidaten gilt Earliest Deadline First.
* Ein entfernter EDF-Kandidat darf keinen portnahen Kandidaten verdrängen.
* Idle-Roboter dürfen nicht im Portbereich parken.
* Aktive Roboter dürfen in Portnähe warten.
* Mindestens ein Ausfahrfeld muss jederzeit frei bleiben.
* Ports dürfen niemals vollständig eingeschlossen werden.