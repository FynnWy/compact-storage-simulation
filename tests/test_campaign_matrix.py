# tests/test_campaign_matrix.py
"""
Der eingefrorene Versuchsplan und der Weg, auf dem er gerechnet wird.

Bis 2026-08-24 gab es keinen ausfuehrbaren Pfad fuer das eingefrorene
Experiment: `run_experiments.py` fuhr 2.000 statt 30.000 ZE, ueber fuenf alte
Seeds statt der zehn festgelegten, ohne Messfenster und in den alten
Exporter. Die Matrixpruefung und der (nicht existierende) Treiber haetten
ausserdem zwei verschiedene Matrixdefinitionen benutzen koennen.

Diese Tests halten fest, was der Plan IST und dass nur eine Quelle ihn
definiert. Sie rechnen keine langen Laeufe; die Simulation ist an anderer
Stelle validiert.
"""

import json

import pytest

from experiments.campaign_matrix import (
    FINAL_POLICIES, FINAL_SEEDS, FINAL_SIMULATION_TIME, FINAL_T_FINAL,
    FINAL_T_MEASURE_START, build_run_config, check_final_config, check_matrix,
    final_matrix, run_id,
)


# ====================================================================== #
# Der Plan
# ====================================================================== #

def test_the_matrix_is_five_policies_times_ten_seeds():
    assert len(FINAL_POLICIES) == 5
    assert len(FINAL_SEEDS) == 10
    assert len(final_matrix()) == 50


def test_the_five_policies_are_exactly_the_frozen_ones():
    assert FINAL_POLICIES == {
        "baseline_reference":    ("LOFI",       "RANDOM",     True),
        "RR+RR":                 ("LOFI",       "RANDOM",     False),
        "LR+NR":                 ("LOFI",       "NEAREST",    False),
        "ABC+ABC":               ("ABC",        "ABC",        True),
        "POPULARITY+POPULARITY": ("POPULARITY", "POPULARITY", True),
    }


def test_the_ten_seeds_are_exactly_the_frozen_ones():
    assert FINAL_SEEDS == (1, 2, 3, 4, 7, 11, 13, 42, 99, 123)


def test_the_horizon_is_frozen():
    assert FINAL_T_MEASURE_START == 20_000
    assert FINAL_T_FINAL == 30_000
    assert FINAL_SIMULATION_TIME == 30_000


def test_run_ids_are_deterministic_and_unique():
    ids = [k[0] for k in final_matrix()]

    assert len(set(ids)) == 50
    assert run_id("ABC+ABC", 7) == "ABC+ABC__seed7"
    # Zweimal aufgerufen, zweimal dasselbe: kein UUID-artiger Schluessel.
    assert final_matrix() == final_matrix()


def test_check_matrix_catches_a_short_or_duplicated_matrix():
    voll = final_matrix()

    assert check_matrix(voll) == []
    assert check_matrix(voll[:49]) != []
    assert check_matrix(voll[:49] + [voll[0]]) != []


# ====================================================================== #
# Die Konfiguration
# ====================================================================== #

def test_default_config_is_the_frozen_campaign_config():
    for policy in FINAL_POLICIES:
        for seed in FINAL_SEEDS:
            config = build_run_config(policy, seed)
            assert check_final_config(config) == [], (
                f"{policy}/{seed} weicht vom eingefrorenen Szenario ab")
            assert config.random_seed == seed


def test_policy_strategies_are_wired_through():
    for policy, (reordering, placement, rbb) in FINAL_POLICIES.items():
        config = build_run_config(policy, 1)

        assert config.reordering_strategy == reordering
        assert config.placement_strategy == placement
        assert config.return_blocking_bins is rbb


def test_unknown_policy_fails_loudly():
    with pytest.raises(ValueError):
        build_run_config("ABC", 1)


def test_no_old_stop_rule_is_active():
    """
    Weder die alte Konvergenz-Stopregel noch ein Retrieval-Stop.

    Alle 50 Runs laufen bis zur selben festen Zeit; jedes vorzeitige,
    policyabhaengige Stoppen wuerde die Vergleichbarkeit der Tardiness
    zerstoeren.
    """
    config = build_run_config("ABC+ABC", 42)

    assert config.stop_on_convergence is False
    assert config.simulation_time == FINAL_SIMULATION_TIME


def test_window_can_be_switched_off_explicitly():
    """
    `None` heisst „kein Fenster", nicht „nimm den Default".

    Die Piloten rechnen bewusst ohne Fenster und legen es offline. Waere
    `None` mit dem Default verwechselt worden, haetten sie stillschweigend
    das Kampagnenfenster gesetzt bekommen.
    """
    ohne = build_run_config("ABC+ABC", 42, sim_time=1000,
                            t_measure_start=None, t_final=None)

    assert ohne.t_measure_start is None
    assert ohne.t_final is None
    assert ohne.simulation_time == 1000


def test_calibration_builder_delegates_to_the_same_source():
    """
    `pilot_run.build_config` und `build_run_config` duerfen nicht
    auseinanderlaufen — sonst waere die vorhandene Kalibration nicht mehr
    die Kalibration der Kampagnenkonfiguration.
    """
    import sys
    from pathlib import Path
    closeout = str(Path(__file__).resolve().parents[1]
                   / "experiments" / "closeout")
    if closeout not in sys.path:
        sys.path.insert(0, closeout)
    from pilot_run import build_config

    for policy in FINAL_POLICIES:
        pilot = vars(build_config(policy, 7, 30_000))
        kampagne = vars(build_run_config(policy, 7, sim_time=30_000,
                                         t_measure_start=None, t_final=None))
        assert pilot == kampagne, f"{policy}: Konfigurationen weichen ab"


# ====================================================================== #
# Der Treiber
# ====================================================================== #

def test_driver_plans_exactly_the_frozen_matrix():
    from experiments.run_final_campaign import plan

    eintraege = plan()
    kombinationen = [(e["run_id"], e["policy"], e["seed"]) for e in eintraege]

    assert len(eintraege) == 50
    assert check_matrix(kombinationen) == []
    for eintrag in eintraege:
        assert check_final_config(eintrag["config"]) == []


def test_driver_and_matrix_check_share_one_definition():
    """
    `dry_check_matrix.py` darf keine eigene Matrix haben.

    Genau diese Doppelung war der Grund, warum eine Matrixpruefung etwas
    anderes haette pruefen koennen, als die Kampagne rechnet.
    """
    import sys
    from pathlib import Path
    closeout = str(Path(__file__).resolve().parents[1]
                   / "experiments" / "closeout")
    if closeout not in sys.path:
        sys.path.insert(0, closeout)
    import dry_check_matrix

    assert tuple(dry_check_matrix.SEEDS) == FINAL_SEEDS
    assert dict(dry_check_matrix.POLICIES) == FINAL_POLICIES


def test_smoke_mode_never_uses_the_final_parameters():
    """
    Der Rauchtest muss technisch vom FINAL-Modus getrennt sein.

    Wuerde er versehentlich mit den finalen Horizonten laufen, waere sein
    Ergebnis nicht mehr von einem echten Kampagnenlauf zu unterscheiden.
    """
    from experiments.run_final_campaign import (
        SMOKE_SIM_TIME, SMOKE_T_MEASURE_START, plan,
    )

    smoke = plan(smoke=True)

    assert SMOKE_SIM_TIME != FINAL_SIMULATION_TIME
    assert SMOKE_T_MEASURE_START != FINAL_T_MEASURE_START
    for eintrag in smoke:
        config = eintrag["config"]
        assert config.simulation_time == SMOKE_SIM_TIME
        assert config.t_measure_start == SMOKE_T_MEASURE_START
        assert config.t_final == SMOKE_SIM_TIME


def test_dry_run_passes_and_writes_nothing(tmp_path, capsys):
    from experiments.run_final_campaign import main

    ziel = tmp_path / "final"
    code = main(["--dry-run", "--output-dir", str(ziel)])
    ausgabe = capsys.readouterr().out

    assert code == 0
    assert "CAMPAIGN DRY RUN PASS" in ausgabe
    assert not ziel.exists() or not any(ziel.iterdir())


def test_dry_run_rejects_a_diagnostic_output_directory(tmp_path, capsys):
    """
    Finale Kampagnendaten duerfen nicht neben Pilot-, Kalibrations- oder
    Debugmaterial landen.
    """
    from experiments.run_final_campaign import main

    code = main(["--dry-run",
                 "--output-dir", str(tmp_path / "closeout" / "results")])

    assert code == 1
    assert "Diagnosepfad" in capsys.readouterr().out


def test_a_non_empty_target_is_never_overwritten_silently(tmp_path, capsys):
    from experiments.run_final_campaign import main

    ziel = tmp_path / "final"
    ziel.mkdir()
    (ziel / "runs.csv").write_text("vorhandene Ergebnisse\n")

    code = main(["--output-dir", str(ziel), "--policy", "ABC+ABC",
                 "--seed", "1"])

    assert code == 2
    assert "nicht leer" in capsys.readouterr().out
    assert (ziel / "runs.csv").read_text() == "vorhandene Ergebnisse\n"


def test_smoke_refuses_to_write_into_a_final_output_directory(tmp_path,
                                                              capsys):
    from experiments.run_final_campaign import STATUS_DATEI, main

    ziel = tmp_path / "final"
    ziel.mkdir()
    (ziel / STATUS_DATEI).write_text(json.dumps({
        "ABC+ABC__seed1": {"state": "completed", "smoke": False}}))

    code = main(["--smoke", "--output-dir", str(ziel), "--resume"])

    assert code == 2
    assert "finale Laeufe" in capsys.readouterr().out


def test_resume_skips_completed_runs(tmp_path, capsys):
    from experiments.run_final_campaign import STATUS_DATEI, main

    ziel = tmp_path / "final"
    ziel.mkdir()
    status = {k: {"state": "completed", "smoke": True}
              for k, _, _ in final_matrix()}
    (ziel / STATUS_DATEI).write_text(json.dumps(status))

    code = main(["--smoke", "--output-dir", str(ziel), "--resume"])
    ausgabe = capsys.readouterr().out

    assert code == 0
    assert "alle Runs sind abgeschlossen" in ausgabe
    assert not (ziel / "runs.csv").exists(), "Es wurde doch gerechnet."
