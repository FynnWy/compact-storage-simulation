class Bin:
    def __init__(self, bin_id, stack_id, level, status):
        self.bin_id = bin_id
        self.stack_id = stack_id  # (x, y)
        self.stack_level = level  # Höhe im Stack
        self.status = status
        self.in_transit = False  # True, solange die Bin physisch bewegt wird
        # Neue Attribute für Strategien
        self.abc_class = None  # "A", "B", "C" oder None
        self.access_count = 0  # Anzahl bisheriger Zugriffe

    def get_status(self):
        return self.status

    def set_status(self, status):
        self.status = status

    def set_level(self, level):
        self.stack_level = level

    def get_level(self):
        return self.stack_level

    def set_stack(self, stack_id):
        self.stack_id = stack_id

    def get_stack(self):
        return self.stack_id

    def mark_in_transit(self):
        self.in_transit = True

    def mark_transit_done(self):
        self.in_transit = False

    # --- Neue API für ABC-Klasse und Popularity ---

    def increment_access_count(self):
        """Erhöht den Zugriffszähler für diese Bin um 1."""
        self.access_count += 1

    def get_access_count(self):
        """Gibt die bisherige Zugriffszahl zurück."""
        return self.access_count

    def set_abc_class(self, cls):
        """
        Setzt die ABC-Klasse der Bin.
        Erwartete Werte: "A", "B", "C" oder None.
        """
        if cls not in ("A", "B", "C", None):
            raise ValueError(f"Invalid ABC class: {cls}")
        self.abc_class = cls

    def get_abc_class(self):
        """Gibt die ABC-Klasse der Bin zurück."""
        return self.abc_class

    def __repr__(self):
        return (
            f"Bin(id={self.bin_id}, stack={self.stack_id}, "
            f"level={self.stack_level}, status={self.status}, "
            f"in_transit={self.in_transit}, "
            f"abc_class={self.abc_class}, access_count={self.access_count})"
        )