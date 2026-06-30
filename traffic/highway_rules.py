# traffic/highway_rules.py

class HighwayRules:
    """
    Definiert bevorzugte Fahrtrichtungen auf dem Grid.

    Patterns:
    - ring: Ringförmiges Einbahnstraßensystem
    - rows: Alternierende horizontale Reihen
    - lanes: Vertikale Bahnen
    - none: Keine Beschränkungen

    Wichtig:
    - Highway-Regeln sind nicht zwingend, sondern Kostenstrafen
    - Roboter können gegen die Richtung fahren, aber mit Penalty
    """

    def __init__(self, grid_width, grid_depth, pattern="ring"):
        """
        Args:
            grid_width: Breite des Grids
            grid_depth: Tiefe des Grids
            pattern: Highway-Pattern ("ring", "rows", "lanes", "none")
        """
        self.grid_width = grid_width
        self.grid_depth = grid_depth
        self.pattern = pattern.lower()

        # (x, y) → list[(dx, dy)]: Bevorzugte Richtungen pro Zelle
        self._preferred_directions = {}

        # Penalty für Fahrt gegen bevorzugte Richtung
        self.wrong_direction_penalty = 5

        self._build_directions()

    def _build_directions(self):
        """Baut Richtungsmatrix basierend auf Pattern."""
        if self.pattern == "ring":
            self._build_ring_pattern()
        elif self.pattern == "rows":
            self._build_row_pattern()
        elif self.pattern == "lanes":
            self._build_lane_pattern()
        elif self.pattern == "none":
            self._build_no_pattern()
        else:
            raise ValueError(f"Unknown highway pattern: {self.pattern}")

    def _build_ring_pattern(self):
        """
        Ringförmiges Highway-System.

        Idee:
        - Oberer Rand: nach rechts →
        - Rechter Rand: nach unten ↓
        - Unterer Rand: nach links ←
        - Linker Rand: nach oben ↑
        - Innere Zellen: mehrere Richtungen erlaubt

        Beispiel (5x5):
        → → → → ↓
        ↑ · · · ↓
        ↑ · · · ↓
        ↑ · · · ↓
        ↑ ← ← ← ←
        """
        for x in range(self.grid_width):
            for y in range(self.grid_depth):
                preferred = []

                # Oberer Rand (y = 0)
                if y == 0:
                    if x < self.grid_width - 1:
                        preferred.append((1, 0))  # Nach rechts
                    if x == self.grid_width - 1:
                        preferred.append((0, 1))  # Nach unten

                # Rechter Rand (x = grid_width - 1)
                elif x == self.grid_width - 1:
                    if y < self.grid_depth - 1:
                        preferred.append((0, 1))  # Nach unten
                    if y == self.grid_depth - 1:
                        preferred.append((-1, 0))  # Nach links

                # Unterer Rand (y = grid_depth - 1)
                elif y == self.grid_depth - 1:
                    if x > 0:
                        preferred.append((-1, 0))  # Nach links
                    if x == 0:
                        preferred.append((0, -1))  # Nach oben

                # Linker Rand (x = 0)
                elif x == 0:
                    if y > 0:
                        preferred.append((0, -1))  # Nach oben
                    if y == 0:
                        preferred.append((1, 0))  # Nach rechts

                # Innere Zellen: alle Richtungen erlaubt
                else:
                    preferred = [(0, 1), (0, -1), (1, 0), (-1, 0)]

                self._preferred_directions[(x, y)] = preferred

    def _build_row_pattern(self):
        """
        Alternierende horizontale Reihen.

        Idee:
        - Gerade Reihen (y=0,2,4,...): nach rechts →
        - Ungerade Reihen (y=1,3,5,...): nach links ←
        - Vertikale Bewegung überall erlaubt

        Beispiel (5x5):
        → → → → →
        ← ← ← ← ←
        → → → → →
        ← ← ← ← ←
        → → → → →
        """
        for x in range(self.grid_width):
            for y in range(self.grid_depth):
                preferred = []

                # Gerade Reihen: nach rechts
                if y % 2 == 0:
                    preferred.append((1, 0))
                # Ungerade Reihen: nach links
                else:
                    preferred.append((-1, 0))

                # Vertikale Bewegung überall erlaubt
                preferred.extend([(0, 1), (0, -1)])

                self._preferred_directions[(x, y)] = preferred

    def _build_lane_pattern(self):
        """
        Vertikale Bahnen mit festen Richtungen.

        Idee:
        - Gerade Spalten (x=0,2,4,...): nach unten ↓
        - Ungerade Spalten (x=1,3,5,...): nach oben ↑
        - Horizontale Bewegung überall erlaubt

        Beispiel (5x5):
        ↓ ↑ ↓ ↑ ↓
        ↓ ↑ ↓ ↑ ↓
        ↓ ↑ ↓ ↑ ↓
        ↓ ↑ ↓ ↑ ↓
        ↓ ↑ ↓ ↑ ↓
        """
        for x in range(self.grid_width):
            for y in range(self.grid_depth):
                preferred = []

                # Gerade Spalten: nach unten
                if x % 2 == 0:
                    preferred.append((0, 1))
                # Ungerade Spalten: nach oben
                else:
                    preferred.append((0, -1))

                # Horizontale Bewegung überall erlaubt
                preferred.extend([(1, 0), (-1, 0)])

                self._preferred_directions[(x, y)] = preferred

    def _build_no_pattern(self):
        """Keine Highway-Regeln - alle Richtungen überall erlaubt."""
        for x in range(self.grid_width):
            for y in range(self.grid_depth):
                self._preferred_directions[(x, y)] = [
                    (0, 1), (0, -1), (1, 0), (-1, 0)
                ]

    def get_preferred_directions(self, x, y):
        """
        Gibt bevorzugte Fahrtrichtungen für eine Zelle zurück.

        Args:
            x, y: Grid-Position

        Returns:
            list[(dx, dy)]: Liste bevorzugter Richtungen
        """
        return self._preferred_directions.get(
            (x, y),
            [(0, 1), (0, -1), (1, 0), (-1, 0)]  # Fallback: alle Richtungen
        )

    def get_direction_penalty(self, x, y, dx, dy):
        """
        Gibt Strafkosten für Bewegung in eine bestimmte Richtung zurück.

        Args:
            x, y: Aktuelle Position
            dx, dy: Bewegungsrichtung

        Returns:
            int: Strafkosten (0 wenn bevorzugte Richtung)
        """
        preferred = self.get_preferred_directions(x, y)

        if (dx, dy) in preferred:
            return 0

        return self.wrong_direction_penalty

    def is_direction_allowed(self, x, y, dx, dy):
        """
        Prüft ob Bewegung in eine Richtung erlaubt ist.

        Wichtig: Mit Highway-Regeln ist IMMER alles erlaubt,
        nur mit unterschiedlichen Kosten.

        Args:
            x, y: Aktuelle Position
            dx, dy: Bewegungsrichtung

        Returns:
            bool: Immer True (Regeln sind Kostenstrafen, keine Verbote)
        """
        return True

    def get_statistics(self):
        """Gibt Statistiken über Highway-System zurück."""
        total_cells = len(self._preferred_directions)

        # Zähle Zellen mit nur einer bevorzugten Richtung
        strict_cells = sum(
            1 for dirs in self._preferred_directions.values()
            if len(dirs) == 1
        )

        return {
            "pattern": self.pattern,
            "total_cells": total_cells,
            "strict_highway_cells": strict_cells,
            "penalty": self.wrong_direction_penalty,
        }

    def __repr__(self):
        return f"HighwayRules(pattern={self.pattern}, grid={self.grid_width}x{self.grid_depth})"