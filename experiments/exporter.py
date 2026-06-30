import csv
import json
from datetime import datetime
from pathlib import Path
from typing import Any, List, Dict

from experiments.runner import ExperimentRunner


class ResultExporter:
    """Exportiert Experiment-Ergebnisse in verschiedene Formate."""

    def __init__(self, output_dir: str = "results"):
        self.output_dir = Path(output_dir)
        self.output_dir.mkdir(exist_ok=True)

    # ------------------------------------------------------------------ #
    # Öffentliche API
    # ------------------------------------------------------------------ #

    def export_all(self, runner: ExperimentRunner, experiment_name: str = "experiment"):
        """Exportiert alle Ergebnisse in alle Formate."""
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        base_path = self.output_dir / f"{experiment_name}_{timestamp}"
        base_path.mkdir(exist_ok=True)

        self.export_summary_json(runner.results, base_path / "summary.json")
        self.export_comparison_csv(
            runner.compare_results(),
            base_path / "comparison.csv",
        )
        self.export_timeseries(runner.results, base_path / "timeseries")
        self.export_config(runner.base_config, base_path / "base_config.json")

    def export_summary_json(self, results: List[dict], path: Path):
        """Exportiert vollständige Ergebnisse als JSON."""
        serializable = self._make_serializable(results)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

    def export_comparison_csv(self, comparison: Dict[str, dict], path: Path):
        """Exportiert Vergleichstabelle als CSV."""
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)

            # Header
            metrics = [
                "average_digging_depth_mean",
                "average_digging_depth_std",
                "throughput_mean",
                "throughput_std",
                "convergence_time_mean",
            ]
            writer.writerow(["strategy"] + metrics)

            # Rows
            for strategy, data in comparison.items():
                avg_dig = data.get("average_digging_depth", {})
                thr = data.get("throughput", {})
                conv = data.get("convergence_time", {})

                row = [
                    strategy,
                    avg_dig.get("mean"),
                    avg_dig.get("std"),
                    thr.get("mean"),
                    thr.get("std"),
                    conv.get("mean"),
                ]
                writer.writerow(row)

    def export_timeseries(self, results: List[dict], dir_path: Path):
        """Exportiert Zeitreihen-Daten für jeden Run."""
        dir_path.mkdir(exist_ok=True)

        for result in results:
            strategy_name = result["experiment"]["name"]
            for run in result["individual_runs"]:
                seed = run["seed"]
                snapshots = run.get("distribution_snapshots", [])

                filename = f"{strategy_name}_seed{seed}_distribution_timeseries.csv"
                self._export_timeseries_csv(snapshots, dir_path / filename)

                # Optional: Konvergenz-Variance-Over-Time exportieren
                conv = run.get("convergence_analysis", {})
                stability = conv.get("stability_metrics", {})
                variance_over_time = stability.get("variance_over_time", [])
                if variance_over_time:
                    var_filename = (
                        f"{strategy_name}_seed{seed}_convergence_variance.csv"
                    )
                    self._export_timeseries_csv(
                        variance_over_time,
                        dir_path / var_filename,
                    )

    def export_config(self, base_config: Any, path: Path):
        """Exportiert Basis-SimulationConfig als JSON."""
        # SimulationConfig ist ein einfacher Container mit Attributen
        raw = getattr(base_config, "__dict__", {})
        serializable = self._make_serializable(raw)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(serializable, f, indent=2, ensure_ascii=False)

    # ------------------------------------------------------------------ #
    # Interne Helfer
    # ------------------------------------------------------------------ #

    def _export_timeseries_csv(self, snapshots: List[dict], path: Path):
        """Exportiert Zeitreihe eines Runs als CSV."""
        if not snapshots:
            return

        # Alle Keys vereinheitlichen (Union aller Keys)
        fieldnames = sorted(
            {key for snap in snapshots for key in snap.keys()}
        )

        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            for snap in snapshots:
                writer.writerow(snap)

    def _make_serializable(self, obj: Any) -> Any:
        """
        Konvertiert verschachtelte Strukturen (Listen/Dictionaries)
        in JSON-serialisierbare Objekte und behandelt typische
        Typen aus Numpy/Pathlib.
        """
        # Primitive Typen
        if isinstance(obj, (str, int, float, bool)) or obj is None:
            return obj

        # Path → str
        if isinstance(obj, Path):
            return str(obj)

        # Numpy-Skalare → Python-Scalar
        try:
            import numpy as np  # lokale Import-Sicherheit

            if isinstance(obj, np.generic):
                return obj.item()
        except Exception:
            pass

        # Listen/Tuples
        if isinstance(obj, (list, tuple)):
            return [self._make_serializable(o) for o in obj]

        # Dictionaries
        if isinstance(obj, dict):
            return {
                str(k): self._make_serializable(v)
                for k, v in obj.items()
            }

        # Fallback: __dict__ wenn vorhanden
        if hasattr(obj, "__dict__"):
            return self._make_serializable(obj.__dict__)

        # Letzter Fallback: String-Repräsentation
        return str(obj)