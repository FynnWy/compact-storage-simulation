# config/bin_request_prob_strategy.py

import numpy as np


def uniform_bin_sampling(bin_num):
    """
    Gleichverteilung: Jede Kiste hat die gleiche Wahrscheinlichkeit angefragt zu werden.
    
    Args:
        bin_num: Anzahl der Kisten
    
    Returns:
        bin_id: Zufällig ausgewählte Kisten-ID
    """
    return np.random.randint(0, bin_num)


def zipf_bin_sampling(bin_num, zipf_parameter=1.2):
    """
    Zipf-Verteilung: Hot Items (wenige Kisten werden sehr häufig angefragt).
    Typisch für E-Commerce und Lagersysteme.
    
    Args:
        bin_num: Anzahl der Kisten
        zipf_parameter: Stärke der Konzentration (0.8-1.5 typisch)
                       Höher = stärkere Hot-Item-Konzentration
    
    Returns:
        bin_id: Nach Zipf-Verteilung ausgewählte Kisten-ID
    """
    ranks = np.arange(1, bin_num + 1)
    probabilities = 1.0 / np.power(ranks, zipf_parameter)
    probabilities /= probabilities.sum()  # Normalisieren
    
    return np.random.choice(bin_num, p=probabilities)


def abc_bin_sampling(bin_num):
    """
    ABC-Verteilung: Kisten werden in A/B/C-Klassen eingeteilt mit
    - 20% der Kisten in Klasse A tragen 80% der Requests
    - 30% der Kisten in Klasse B tragen 15% der Requests
    - 50% der Kisten in Klasse C tragen 5% der Requests

    Die Klassen sind nach Kisten-IDs sortiert:
        A: [0, a_end)
        B: [a_end, b_end)
        C: [b_end, bin_num)

    Innerhalb einer Klasse ist die Auswahl gleichverteilt.

    Args:
        bin_num: Anzahl der Kisten

    Returns:
        bin_id: Nach ABC-Verteilung ausgewählte Kisten-ID
    """
    if bin_num <= 0:
        raise ValueError("bin_num must be positive")

    # Kisten-Anteile pro Klasse
    a_count = int(bin_num * 0.2)
    b_count = int(bin_num * 0.3)
    # Rest geht in C, sodass sich genau bin_num ergibt
    c_count = bin_num - a_count - b_count

    # Korrektur für sehr kleine Lager: nur Klassen mit mindestens 1 Kiste verwenden
    class_ranges = []
    class_probs = []

    start = 0
    if a_count > 0:
        class_ranges.append((start, start + a_count))  # A
        class_probs.append(0.80)
        start += a_count

    if b_count > 0:
        class_ranges.append((start, start + b_count))  # B
        class_probs.append(0.15)
        start += b_count

    if c_count > 0:
        class_ranges.append((start, start + c_count))  # C
        class_probs.append(0.05)

    # Falls wegen Rundungen nur 1–2 Klassen übrig bleiben:
    class_probs = np.array(class_probs, dtype=float)
    class_probs /= class_probs.sum()  # Auf 1 normieren

    # Zuerst Klasse nach Request-Anteilen ziehen,
    # dann innerhalb der Klasse gleichverteilt eine Kiste wählen.
    class_index = np.random.choice(len(class_ranges), p=class_probs)
    start, end = class_ranges[class_index]
    return np.random.randint(start, end)
