# config/init_strategy.py

import math
import numpy as np


def _all_stack_positions(grid, excluded_positions=None):
    """
    Alle Positionen, auf denen initial gelagert werden darf.

    FINAL FREEZE CLOSEOUT (2026-08-21):
    Die Initialverteilung nutzt GENAU DIESELBEN zulässigen Storage-Positionen
    wie die Placement-Policies zur Laufzeit. `SimulationEngine._initialize_state`
    übergibt dafür die Port-Pufferzone aus `utils.port_buffer_zone.
    calculate_buffer_zone` – dieselbe Funktion, aus der auch
    `State.is_valid_storage_position` ihre Menge bezieht.

    Grund: Mellers RQ4 fragt nach der Reorganisation aus einem zufälligen,
    aber bereits GÜLTIGEN Lagerzustand. Startete das Lager mit Bins in der
    Pufferzone, würde zusätzlich das erzwungene Ausströmen aus Zellen gemessen,
    die nach t=0 nie wieder belegt werden dürfen.

    Kein stiller Fallback: Reicht die Kapazität nach Abzug der Pufferzone
    nicht, wirft `init_random_distribution` einen Fehler. Kleine Testfixtures
    müssen ihre Voraussetzungen explizit gültig konfigurieren (Grid groß
    genug oder Binzahl klein genug), statt die Modellsemantik umzuschalten.
    """
    excluded = set(excluded_positions or ())
    positions = []

    for x in range(grid.width):
        for y in range(grid.depth):
            # Wenn das Grid Port-Positionen kennt, nur echte Storage-Positionen verwenden. Pickstations nicht betrachten.
            if hasattr(grid, "is_storage_position"):
                if not grid.is_storage_position(x, y):
                    continue
            if (x, y) in excluded:
                continue
            positions.append((x, y))

    return positions


def init_random_distribution(grid, bins, random_seed=None, max_stack_height=None,
                             rng=None, excluded_positions=None):
    """
    Verteilt alle Bins zufällig über das Grid.

    Wichtig:
    - Diese Initialisierung kennt keine Hot Items.
    - Hot Items werden ausschließlich über die Request-Wahrscheinlichkeit simuliert.
    - max_stack_height wird respektiert.

    PHASE 4:
    `rng` hat Vorrang vor `random_seed`. Die Engine übergibt hier den
    Initialisierungs-Strom aus `RngStreams`, damit alle Zufallsgrößen aus
    einem Master-Seed stammen. `random_seed` bleibt für direkte Aufrufe
    erhalten.
    """
    rng = rng if rng is not None else np.random.default_rng(random_seed)
    positions = _all_stack_positions(grid, excluded_positions)

    if not positions:
        return

    if max_stack_height is None:
        max_stack_height = math.ceil(len(bins) / len(positions))

    total_capacity = len(positions) * max_stack_height

    if len(bins) > total_capacity:
        # Fail fast statt stillem Umschalten der Modellsemantik: Wenn die
        # zulässigen Storage-Positionen (ohne Port-Pufferzone) nicht reichen,
        # ist die KONFIGURATION unzulässig – die Eligibility wird nicht
        # aufgeweicht.
        raise ValueError(
            f"Not enough storage capacity: bin_count={len(bins)}, "
            f"capacity={total_capacity}, "
            f"stacks={len(positions)}, "
            f"max_stack_height={max_stack_height}, "
            f"excluded_positions={len(set(excluded_positions or ()))}"
        )

    shuffled_bins = list(bins)
    rng.shuffle(shuffled_bins)

    available_slots = []

    for stack_pos in positions:
        for _ in range(max_stack_height):
            available_slots.append(stack_pos)

    rng.shuffle(available_slots)

    for bin_obj in shuffled_bins:
        stack_pos = available_slots.pop()
        stack = grid.get_stack(*stack_pos)

        bin_obj.set_stack(stack_pos)
        bin_obj.set_level(stack.height())
        bin_obj.set_status("stored")
        stack.push(bin_obj)


def assign_abc_classes(bins, abc_threshold_a, abc_threshold_b):
    """
    Weist allen Bins eine ABC-Klasse basierend auf ihrer bin_id zu.

    Annahmen:
    - Niedrige bin_ids haben höhere Request-Wahrscheinlichkeit (Zipf-artig).
    - Grenzen:
        bin_id < bin_num * abc_threshold_a -> "A"
        bin_id < bin_num * abc_threshold_b -> "B"
        sonst -> "C"
    """
    if not bins:
        return

    bin_num = len(bins)

    # Defensive Bounds
    abc_threshold_a = max(0.0, min(1.0, abc_threshold_a))
    abc_threshold_b = max(0.0, min(1.0, abc_threshold_b))

    if abc_threshold_b < abc_threshold_a:
        raise ValueError(
            f"Invalid ABC thresholds: abc_threshold_b ({abc_threshold_b}) "
            f"must be >= abc_threshold_a ({abc_threshold_a})"
        )

    a_limit = int(bin_num * abc_threshold_a)
    b_limit = int(bin_num * abc_threshold_b)

    for bin_obj in bins:
        bin_id = bin_obj.bin_id

        if bin_id < a_limit:
            bin_obj.set_abc_class("A")
        elif bin_id < b_limit:
            bin_obj.set_abc_class("B")
        else:
            bin_obj.set_abc_class("C")


def initialize_bins(
    grid,
    bins,
    init_strategy="random_distribution",
    hot_bin_ids=None,
    random_seed=None,
    max_stack_height=None,
    abc_threshold_a=0.2,
    abc_threshold_b=0.5,
    rng=None,
    excluded_positions=None,
):
    """
    Zentrale Einstiegsmethode für die Initialverteilung.

    hot_bin_ids bleibt absichtlich als Parameter erhalten, wird aber bei
    random_distribution nicht verwendet.

    Grund:
    Hot Items sollen requestseitig simuliert werden, nicht durch eine besondere
    initiale Lagerposition.

    Zusätzlich:
    - Weist allen Bins eine ABC-Klasse zu (Zipf-basiert über bin_id).
    """
    if init_strategy == "random_distribution":
        init_random_distribution(
            grid=grid,
            bins=bins,
            random_seed=random_seed,
            max_stack_height=max_stack_height,
            rng=rng,
            excluded_positions=excluded_positions,
        )

        # Nach der Platzierung: ABC-Klassen vergeben
        assign_abc_classes(
            bins=bins,
            abc_threshold_a=abc_threshold_a,
            abc_threshold_b=abc_threshold_b,
        )
        return

    raise ValueError(f"Unknown init_strategy: {init_strategy}")