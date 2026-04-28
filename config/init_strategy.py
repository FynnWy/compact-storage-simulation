# config/init_strategy.py

import math
import numpy as np


def _all_stack_positions(grid):
    positions = []
    for x in range(grid.width):
        for y in range(grid.depth):
            positions.append((x, y))
    return positions


def _stack_sort_key(position):
    """
    Deterministische Reihenfolge für 'bessere Zugänglichkeit':
    Hier einfach von oben links nach unten rechts.
    Falls ihr später echte Zugänglichkeitsmetriken habt, kann das hier ersetzt werden.
    """
    x, y = position
    return (x, y)


def _build_balanced_stack_order(grid):
    """
    Liefert Stack-Positionen in einer balancierten, gut verteilten Reihenfolge.
    """
    positions = _all_stack_positions(grid)
    return sorted(positions, key=_stack_sort_key)


def init_uniform_distribution(grid, bins, random_seed=None):
    """
    Verteilt alle Bins zufällig und möglichst gleichmäßig über das Grid.
    """
    rng = np.random.default_rng(random_seed)
    positions = _all_stack_positions(grid)
    rng.shuffle(positions)

    stack_count = len(positions)
    if stack_count == 0:
        return

    for idx, bin_obj in enumerate(bins):
        stack_pos = positions[idx % stack_count]
        stack = grid.get_stack(*stack_pos)

        bin_obj.set_stack(stack_pos)
        bin_obj.set_level(stack.height())
        stack.push(bin_obj)


# def init_hot_items_top(grid, bins, hot_bin_ids=None, random_seed=None):
#     """
#     Platziert Hot Items bevorzugt in zugänglicheren Positionen.
#     Hot Items werden zuerst auf die bevorzugten Stack-Positionen gelegt.
#     """
#     if not hot_bin_ids:
#         return init_uniform_distribution(grid, bins, random_seed=random_seed)

#     rng = np.random.default_rng(random_seed)
#     hot_id_set = set(hot_bin_ids)

#     hot_bins = [b for b in bins if b.bin_id in hot_id_set]
#     cold_bins = [b for b in bins if b.bin_id not in hot_id_set]

#     positions = _build_balanced_stack_order(grid)
#     if not positions:
#         return

#     rng.shuffle(positions)

#     hot_positions = positions[:len(hot_bins)]
#     cold_positions = positions[len(hot_bins):]
#     # cold_positions = positions # Alle Positionen können auch für Cold Items genutzt werden

#     if not cold_positions:
#         cold_positions = positions

#     for bin_obj, stack_pos in zip(hot_bins, hot_positions):
#         stack = grid.get_stack(*stack_pos)
#         bin_obj.set_stack(stack_pos)
#         bin_obj.set_level(stack.height())
#         stack.push(bin_obj)

#     for idx, bin_obj in enumerate(cold_bins):
#         stack_pos = cold_positions[idx % len(cold_positions)]
#         stack = grid.get_stack(*stack_pos)
#         bin_obj.set_stack(stack_pos)
#         bin_obj.set_level(stack.height())
#         stack.push(bin_obj)

def init_hot_items_top(grid, bins, hot_bin_ids=None, random_seed=None):
    if not hot_bin_ids:
        return init_uniform_distribution(grid, bins, random_seed=random_seed)

    rng = np.random.default_rng(random_seed)
    hot_id_set = set(hot_bin_ids)

    hot_bins = [b for b in bins if b.bin_id in hot_id_set]
    cold_bins = [b for b in bins if b.bin_id not in hot_id_set]
    
    # Get all available stack coordinates
    positions = _all_stack_positions(grid) 
    
    # 1. Place COLD bins first (The Foundation)
    # To keep heights balanced, we iterate through positions repeatedly
    rng.shuffle(positions)
    for i, bin_obj in enumerate(cold_bins):
        stack_pos = positions[i % len(positions)]
        stack = grid.get_stack(*stack_pos)
        
        bin_obj.set_stack(stack_pos)
        bin_obj.set_level(stack.height())
        stack.push(bin_obj)

    # 2. Place HOT bins (The Top Layer)
    # Shuffle again so they aren't always on the same "first" stacks
    rng.shuffle(positions)
    positions.sort(key=lambda pos: grid.get_stack(*pos).height())
    
    for i, bin_obj in enumerate(hot_bins):
        # Using modulo ensures that if you have 10 stacks and 5 hot items,
        # each hot item gets its OWN stack.
        # If you have 15 hot items, the first 5 stacks will have 2, others 1.
        stack_pos = positions[i % len(positions)]
        stack = grid.get_stack(*stack_pos)
        
        bin_obj.set_stack(stack_pos)
        bin_obj.set_level(stack.height())
        stack.push(bin_obj)


def initialize_bins(grid, bins, init_strategy="uniform", hot_bin_ids=None, random_seed=None):
    """
    Zentrale Einstiegsmethode für die Initialverteilung.
    """
    if init_strategy == "uniform":
        init_uniform_distribution(grid, bins, random_seed=random_seed)
    elif init_strategy == "hot_items_top":
        init_hot_items_top(
            grid=grid,
            bins=bins,
            hot_bin_ids=hot_bin_ids,
            random_seed=random_seed,
        )
    else:
        raise ValueError(f"Unknown init_strategy: {init_strategy}")