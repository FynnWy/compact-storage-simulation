"""
Der Legacy-Runner darf nicht in den eingefrorenen Results-Bereich schreiben.

`run_experiments.py` ist historisch und schrieb frueher timestamped Ordner
direkt nach `results/` — also dorthin, wo seit dem Data Freeze der
eingefrorene Rohdatenbestand und die Freeze-/Audit-Dokumente liegen:

    results/final/          Rohdaten der finalen 50-Run-Kampagne
    results/final_raw/      byteidentische Archivkopie
    results/FINAL_DATA_*    Manifest, Freeze-Record, Validity Audit

Diese Tests halten den Default auf einem eigenen Unterordner fest. Sie
starten keine Simulation und schreiben nichts.
"""

from pathlib import Path

import run_experiments


def test_legacy_output_dir_ist_results_legacy():
    assert run_experiments.LEGACY_OUTPUT_DIR == Path("results") / "legacy"


def test_legacy_output_dir_zeigt_nicht_direkt_auf_results():
    """Der eigentliche Regressionsschutz: kein Rueckfall auf `results/`."""
    ziel = run_experiments.LEGACY_OUTPUT_DIR
    assert ziel != Path("results"), (
        "Legacy-Ausgaben duerfen nicht wieder direkt nach results/ gehen — "
        "dort liegt der eingefrorene Rohdatenbestand."
    )
    assert ziel.parent == Path("results")
    assert ziel.name == "legacy"


def test_legacy_output_dir_beruehrt_keinen_eingefrorenen_pfad():
    teile = run_experiments.LEGACY_OUTPUT_DIR.parts
    assert "final" not in teile
    assert "final_raw" not in teile


def test_main_exportiert_in_den_legacy_ordner(monkeypatch, tmp_path):
    """
    Verhaltenspruefung ohne Simulationslauf: `main()` muss den
    `ResultExporter` mit dem Legacy-Ordner bauen, nicht mit dem Default.
    """
    gesehen = {}

    class ExporterStub:
        def __init__(self, output_dir="results"):
            gesehen["output_dir"] = output_dir
            self.output_dir = output_dir

        def export_all(self, runner, experiment_name="experiment"):
            gesehen["experiment_name"] = experiment_name

    class RunnerStub:
        def __init__(self, config):
            pass

        def run_all(self, experiments):
            pass

        def compare_results(self):
            return {}

    monkeypatch.setattr(run_experiments, "ResultExporter", ExporterStub)
    monkeypatch.setattr(run_experiments, "ExperimentRunner", RunnerStub)
    # In ein tmp-Verzeichnis umlenken, damit der mkdir-Aufruf in `main()`
    # nichts im Repository anlegt.
    monkeypatch.setattr(run_experiments, "LEGACY_OUTPUT_DIR",
                        tmp_path / "results" / "legacy")

    run_experiments.main()

    assert gesehen["output_dir"] == str(tmp_path / "results" / "legacy")
    assert (tmp_path / "results" / "legacy").is_dir()
