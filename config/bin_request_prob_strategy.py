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
