class ConstraintManager:
    def can_execute(self, action, state):
        """
        Prüft, ob eine Aktion im aktuellen State ausgeführt werden darf.

        Beispiele für spätere Checks:
        - Ist der Zielstack frei?
        - Ist der Roboter verfügbar?
        - Ist der Zugriff auf den Stack blockiert?
        - Ist genug Platz im Buffer-Stack?
        """
        return True