import copy
import math
import matplotlib
import matplotlib.patches as patches

try:
    matplotlib.use("MacOSX")
except ImportError:
    try:
        matplotlib.use("TkAgg")
    except ImportError:
        matplotlib.use("Agg")

import matplotlib.pyplot as plt
from matplotlib.widgets import Button

from events.event_types import EventType


class StorageSideViewVisualizer:
    """
    Aufgeklappte 2D-Seitenansicht des Lagers.

    Darstellung:
    - Jede y-Reihe des Grids wird als eigene Seitenansicht gezeichnet.
    - Innerhalb einer Reihe liegen die x-Stacks nebeneinander.
    - Stack-Level werden vertikal dargestellt.
    - y-Reihen werden dynamisch über mehrere Spalten verteilt.
    - Rechts bleibt ein Info-Bereich für Pickstation und Roboterstatus.
    """

    def __init__(self, engine):
        self.engine = engine

        self.normal_bin_color = "#90caf9"  # Soft blue
        self.target_bin_color = "#ef5350"  # Soft red
        self.empty_stack_color = "#eceff1" # Light blue-grey
        self.target_stack_edge_color = "#c62828"
        self.robot_color = "#37474f"       # Dark blue-grey
        self.pickstation_color = "#ffca28" # Amber

        self.last_event = None
        self.history = []
        self.history_index = -1
        self.is_finished = False
        self.is_closed = False

        self._configure_dynamic_layout()

        # Use a more responsive layout setup
        self.fig, self.ax = plt.subplots(figsize=self.figure_size)
        self.fig.canvas.manager.set_window_title("Compact Storage Simulation")
        
        # Connect close event to handle clean shutdown
        self.fig.canvas.mpl_connect("close_event", self._on_close)

        plt.subplots_adjust(bottom=0.15, top=0.92, left=0.05, right=0.95)

        self.previous_button_ax = self.fig.add_axes([0.30, 0.04, 0.16, 0.06])
        self.previous_button = Button(self.previous_button_ax, "Previous")
        self.previous_button.on_clicked(self._on_previous_clicked)

        self.next_button_ax = self.fig.add_axes([0.50, 0.04, 0.22, 0.06])
        self.next_button = Button(self.next_button_ax, "Next visible event")
        self.next_button.on_clicked(self._on_next_clicked)

        self._store_snapshot(event=None)
        self.draw()

    def _configure_dynamic_layout(self):
        """
        Berechnet Layoutgrößen dynamisch.

        Wichtig:
        Die y-Reihen werden nicht mehr nur vertikal gestapelt,
        sondern auf mehrere horizontale Spalten verteilt.
        """
        grid = self.engine.state.grid
        max_stack_height = self.engine.config.max_stack_height
        robot_count = len(self.engine.state.robots)

        width = max(1, grid.width)
        depth = max(1, grid.depth)
        max_stack_height = max(1, max_stack_height)
        robot_count = max(1, robot_count)

        self.figure_size = self._calculate_figure_size(width, depth, max_stack_height)

        horizontal_capacity = self._estimate_horizontal_row_capacity(width)
        self.row_panel_columns = max(1, min(depth, horizontal_capacity))
        self.rows_per_panel_column = math.ceil(depth / self.row_panel_columns)

        width_scale = min(1.0, 10.0 / width)
        height_scale = min(1.0, 8.0 / max_stack_height)
        rows_scale = min(1.0, 5.0 / self.rows_per_panel_column)

        scale = max(0.35, min(width_scale, height_scale, rows_scale))

        self.bin_width = 0.85 * scale
        self.bin_height = 0.80 * scale
        self.stack_gap = 0.25 * scale
        self.row_gap = max(0.85 * scale, 0.45)
        self.panel_column_gap = max(1.35 * scale, 0.85)

        self.info_panel_gap = max(1.6 * scale, 0.9)
        self.info_panel_width = max(3.2, 3.8 * scale)

        self.robot_marker_size = max(25, 120 * scale)
        self.robot_vertical_gap = max(0.42 * scale, 0.22)

        self.bin_font_size = max(4, int(8 * scale))
        self.axis_font_size = max(5, int(9 * scale))
        self.row_label_font_size = max(6, int(11 * scale))
        self.title_font_size = max(8, int(12 * scale))
        self.info_font_size = max(6, int(10 * scale))

    def _calculate_figure_size(self, width, depth, max_stack_height):
        """
        Gibt der Figure genug Platz, begrenzt auf übliche Laptop-Maße.
        """
        # Basis-Berechnung
        ideal_width = width * 0.8 + min(depth, 4) * 2.5 + 5
        ideal_height = min(depth, 6) * max_stack_height * 0.35 + 4
        
        # Begrenzung auf Laptop-Dimensionen (Zoll bei ca. 100 DPI)
        # Wir wollen nicht, dass das Fenster größer als der Bildschirm wird
        estimated_width = min(max(10, ideal_width), 16)
        estimated_height = min(max(6, ideal_height), 9)
        
        return estimated_width, estimated_height

    def _estimate_horizontal_row_capacity(self, grid_width):
        """
        Schätzt, wie viele y-Reihen-Spalten horizontal sinnvoll nebeneinander passen.

        Rechts wird bewusst Platz für Roboter/Pickstation reserviert.
        """
        figure_width = self.figure_size[0]

        approximate_row_panel_width = max(2.5, grid_width * 0.62)
        reserved_info_width = 4.2
        usable_width = max(approximate_row_panel_width, figure_width - reserved_info_width)

        return max(1, int(usable_width // approximate_row_panel_width))

    def get_engine(self):
        """
        Gibt den aktuell angezeigten Engine-Zustand zurück.
        """
        return self.engine

    def show(self):
        """
        Öffnet die Visualisierung.
        """
        if matplotlib.get_backend().lower() == "agg":
            output_path = "storage_side_view.png"
            self.fig.savefig(output_path, dpi=150, bbox_inches="tight")
            print(
                f"Plot saved to {output_path} because no interactive "
                f"Matplotlib backend is available."
            )
        else:
            plt.show()

    def _on_close(self, event):
        """Handle window close event."""
        self.is_closed = True
        plt.close(self.fig)

    def draw(self, event=None):
        """
        Zeichnet den aktuellen Zustand vollständig neu.
        """
        if self.is_closed:
            return

        self.last_event = event

        self._configure_dynamic_layout()
        self.fig.set_size_inches(*self.figure_size, forward=True)

        self.ax.clear()

        target_bin_id = self._get_target_bin_id(event)
        target_stack_position = self._find_stack_position_of_bin(target_bin_id)

        self._draw_storage_rows(target_bin_id, target_stack_position)
        self._draw_info_panel()
        self._draw_robots_on_grid()
        self._draw_title(event, target_bin_id)
        self._configure_axes()

        self.fig.canvas.draw_idle()

    def _store_snapshot(self, event):
        """
        Speichert den aktuellen Zustand als History-Snapshot.
        Hinweis: Wir kopieren die gesamte Engine, um die Konsistenz der Handler zu bewahren.
        Um Speicherplatz zu sparen, begrenzen wir die History.
        """
        if self.history_index < len(self.history) - 1:
            self.history = self.history[:self.history_index + 1]

        self.history.append({
            "engine": copy.deepcopy(self.engine),
            "event": event,
        })
        self.history_index = len(self.history) - 1
        
        # History begrenzen, um Memory-Leaks/Crashes bei langen Simulationen zu vermeiden
        if len(self.history) > 100:
            self.history.pop(0)
            self.history_index -= 1

    def _restore_snapshot(self, index):
        """
        Stellt einen gespeicherten Zustand wieder her.
        """
        if index < 0 or index >= len(self.history):
            return
            
        snapshot = self.history[index]
        self.engine = copy.deepcopy(snapshot["engine"])
        self.last_event = snapshot["event"]
        self.history_index = index

        self._reset_next_button_if_needed()
        self.draw(self.last_event)

    def _on_next_clicked(self, click_event):
        """
        Button-Callback.
        """
        if self.history_index < len(self.history) - 1:
            self._restore_snapshot(self.history_index + 1)
            return

        if self.is_finished:
            print("Simulation already finished.")
            return

        next_visible_event = self._step_to_next_visible_event()

        if next_visible_event is None:
            self.is_finished = True
            self.next_button.label.set_text("Finished")
            self.next_button.ax.set_alpha(0.5)
            self.fig.canvas.draw_idle()
            print("Simulation finished.")
            return

        self._store_snapshot(next_visible_event)
        self.draw(next_visible_event)

    def _on_previous_clicked(self, click_event):
        """
        Springt einen sichtbaren Event-Schritt zurück.
        """
        if self.history_index <= 0:
            print("Already at initial state.")
            return

        self._restore_snapshot(self.history_index - 1)

    def _step_to_next_visible_event(self):
        """
        Führt Simulationsevents aus, bis ein sichtbares Event verarbeitet wurde.
        """
        while True:
            simulation_event = self.engine.step()

            if simulation_event is None:
                return None

            if simulation_event.event_type != EventType.ARRIVAL:
                return simulation_event

    def _reset_next_button_if_needed(self):
        """
        Aktiviert den Next-Button optisch wieder, wenn man nach 'Finished'
        zurückspringt.
        """
        if self.history_index < len(self.history) - 1:
            self.next_button.label.set_text("Next visible event")
            self.next_button.ax.set_alpha(1.0)

    def _draw_storage_rows(self, target_bin_id, target_stack_position):
        grid = self.engine.state.grid
        width = grid.width
        depth = grid.depth
        max_stack_height = self.engine.config.max_stack_height

        for y in range(depth):
            panel_column = y // self.rows_per_panel_column
            row_in_column = y % self.rows_per_panel_column

            panel_x = self._get_panel_column_x(panel_column)
            row_base_y = self._get_row_base_y(row_in_column)

            self.ax.text(
                panel_x - self._get_left_label_offset(),
                row_base_y + max_stack_height * self.bin_height / 2,
                f"y={y}",
                ha="right",
                va="center",
                fontsize=self.row_label_font_size,
                fontweight="bold",
            )

            for x in range(width):
                stack = grid.get_stack(x, y)
                stack_x = panel_x + self._get_stack_local_x(x)

                self._draw_empty_stack_frame(
                    x=stack_x,
                    y=row_base_y,
                    is_target_stack=target_stack_position == (x, y),
                )

                for level, bin_obj in enumerate(stack.bins):
                    bin_y = row_base_y + level * self.bin_height
                    is_target_bin = bin_obj.bin_id == target_bin_id

                    self._draw_bin(
                        x=stack_x,
                        y=bin_y,
                        bin_id=bin_obj.bin_id,
                        is_target_bin=is_target_bin,
                    )

                self.ax.text(
                    stack_x + self.bin_width / 2,
                    row_base_y - self._get_x_label_offset(),
                    f"x={x}",
                    ha="center",
                    va="top",
                    fontsize=self.axis_font_size,
                )

    def _draw_empty_stack_frame(self, x, y, is_target_stack):
        max_stack_height = self.engine.config.max_stack_height

        edge_color = (
            self.target_stack_edge_color
            if is_target_stack
            else self.empty_stack_color
        )
        line_width = max(0.8, 2.5 * self._get_visual_scale()) if is_target_stack else 0.6

        frame = patches.Rectangle(
            (x, y),
            self.bin_width,
            max_stack_height * self.bin_height,
            linewidth=line_width,
            edgecolor=edge_color,
            facecolor="none",
            linestyle="-",
            zorder=1,
        )

        self.ax.add_patch(frame)

    def _draw_bin(self, x, y, bin_id, is_target_bin):
        color = self.target_bin_color if is_target_bin else self.normal_bin_color
        text_color = "white" if is_target_bin else "#263238"
        fontweight = "bold" if is_target_bin else "normal"

        # Round corners for a more modern look
        padding_h = self.bin_width * 0.05
        padding_v = self.bin_height * 0.05
        
        rectangle = patches.FancyBboxPatch(
            (x + padding_h, y + padding_v),
            self.bin_width - 2 * padding_h,
            self.bin_height - 2 * padding_v,
            boxstyle=f"round,pad=0,rounding_size={min(0.1, self.bin_height*0.2)}",
            linewidth=max(0.5, 1.0 * self._get_visual_scale()),
            edgecolor="#455a64" if not is_target_bin else self.target_stack_edge_color,
            facecolor=color,
            zorder=2,
        )

        self.ax.add_patch(rectangle)

        if self.bin_font_size >= 4:
            self.ax.text(
                x + self.bin_width / 2,
                y + self.bin_height / 2,
                str(bin_id),
                ha="center",
                va="center",
                fontsize=self.bin_font_size,
                color=text_color,
                fontweight=fontweight,
                zorder=3,
            )

    def _draw_robots_on_grid(self):
        grid = self.engine.state.grid
        robots_by_position = {}

        for robot in self.engine.state.robots:
            position = robot.get_position()

            if isinstance(position, tuple) and len(position) == 2:
                robots_by_position.setdefault(position, []).append(robot)

        for position, robots in robots_by_position.items():
            x, y = position
            stack = grid.get_stack(x, y)

            if stack is None:
                continue

            panel_column = y // self.rows_per_panel_column
            row_in_column = y % self.rows_per_panel_column

            for index, robot in enumerate(robots):
                marker_x = (
                    self._get_panel_column_x(panel_column)
                    + self._get_stack_local_x(x)
                    + self.bin_width / 2
                    + (index - (len(robots) - 1) / 2) * self.bin_width * 0.35
                )
                marker_y = (
                    self._get_row_base_y(row_in_column)
                    + self.engine.config.max_stack_height * self.bin_height
                    + self.robot_vertical_gap
                )

                self.ax.scatter(
                    marker_x,
                    marker_y,
                    marker="v",
                    s=self.robot_marker_size,
                    c=self.robot_color,
                    zorder=4,
                )

                self.ax.text(
                    marker_x,
                    marker_y + self.robot_vertical_gap * 0.55,
                    f"R{robot.robot_id}",
                    ha="center",
                    va="bottom",
                    fontsize=self.axis_font_size,
                    fontweight="bold",
                    color=self.robot_color,
                    zorder=5,
                )

    def _draw_info_panel(self):
        """
        Zeichnet rechts Pickstation und Roboterstatus.
        """
        info_x = self._get_info_panel_x()
        top_y = self._get_top_content_y()

        self.ax.text(
            info_x,
            top_y,
            "Info",
            ha="left",
            va="bottom",
            fontsize=self.info_font_size + 1,
            fontweight="bold",
        )

        self._draw_pickstation(info_x, top_y - self.bin_height * 0.9)
        self._draw_robot_status(info_x, top_y - self.bin_height * 3.0)

    def _draw_pickstation(self, info_x, start_y):
        bins_at_pickstation = [
            bin_obj
            for bin_obj in self.engine.state.bins
            if bin_obj.get_status() == "at_pickstation"
        ]

        self.ax.text(
            info_x,
            start_y,
            "Pickstation",
            ha="left",
            va="bottom",
            fontsize=self.info_font_size,
            fontweight="bold",
        )

        if not bins_at_pickstation:
            self.ax.text(
                info_x,
                start_y - self.bin_height * 0.6,
                "empty",
                ha="left",
                va="top",
                fontsize=self.axis_font_size,
                color="gray",
            )
            return

        max_drawn_pickstation_bins = self._get_max_drawn_pickstation_bins()

        for index, bin_obj in enumerate(bins_at_pickstation[:max_drawn_pickstation_bins]):
            y = start_y - self.bin_height * 1.15 - index * self.bin_height

            padding_h = self.bin_width * 0.05
            padding_v = self.bin_height * 0.05

            rectangle = patches.FancyBboxPatch(
                (info_x + padding_h, y + padding_v),
                self.bin_width - 2 * padding_h,
                self.bin_height - 2 * padding_v,
                boxstyle=f"round,pad=0,rounding_size={min(0.1, self.bin_height*0.2)}",
                linewidth=max(0.35, 0.8 * self._get_visual_scale()),
                edgecolor="#455a64",
                facecolor=self.pickstation_color,
                zorder=2,
            )

            self.ax.add_patch(rectangle)

            self.ax.text(
                info_x + self.bin_width / 2,
                y + self.bin_height / 2,
                str(bin_obj.bin_id),
                ha="center",
                va="center",
                fontsize=self.bin_font_size,
                color="black",
                zorder=3,
            )

        hidden_count = len(bins_at_pickstation) - max_drawn_pickstation_bins

        if hidden_count > 0:
            hidden_y = start_y - self.bin_height * 1.15 - max_drawn_pickstation_bins * self.bin_height
            self.ax.text(
                info_x,
                hidden_y,
                f"+{hidden_count} more",
                ha="left",
                va="top",
                fontsize=self.axis_font_size,
                color="gray",
            )

    def _draw_robot_status(self, info_x, start_y):
        self.ax.text(
            info_x,
            start_y,
            "Robots",
            ha="left",
            va="bottom",
            fontsize=self.info_font_size,
            fontweight="bold",
        )

        for index, robot in enumerate(self.engine.state.robots):
            y = start_y - self.robot_vertical_gap * (index + 1.35)

            status = robot.get_status()
            position = robot.get_position()
            task = getattr(robot, "current_task", None)

            status_color = "#ef5350" if status == "busy" else "#26a69a"

            self.ax.scatter(
                info_x + self.bin_width * 0.25,
                y,
                marker="v",
                s=self.robot_marker_size,
                c=status_color,
                zorder=4,
            )

            text = f"R{robot.robot_id}: {status}"

            if task is not None:
                text += f" | task={task}"

            if position is not None:
                text += f" | pos={position}"

            self.ax.text(
                info_x + self.bin_width * 0.75,
                y,
                text,
                ha="left",
                va="center",
                fontsize=self.axis_font_size,
                color="black",
                zorder=5,
            )

    def _draw_title(self, event, target_bin_id):
        history_info = f"step={self.history_index}/{len(self.history) - 1}"

        if event is None:
            title = f"Storage Side View | t={self.engine.state.t} | {history_info}"
        else:
            event_type = event.event_type.value
            robot_id = self._get_robot_id(event)
            action_type = self._get_action_type(event)

            title = (
                f"Storage Side View | "
                f"t={self.engine.state.t} | "
                f"{history_info} | "
                f"event={event_type}"
            )

            if action_type is not None:
                title += f" | action={action_type}"

            if target_bin_id is not None:
                title += f" | target bin={target_bin_id}"

            if robot_id is not None:
                title += f" | robot=R{robot_id}"

        self.ax.set_title(title, fontsize=self.title_font_size, fontweight="bold")

    def _configure_axes(self):
        min_x = -self._get_left_label_offset() - 0.25
        max_x = self._get_info_panel_x() + self.info_panel_width

        bottom_y = -self._get_bottom_padding()
        top_y = self._get_top_content_y() + self._get_top_padding()

        self.ax.set_xlim(min_x, max_x)
        self.ax.set_ylim(bottom_y, top_y)

        self.ax.set_aspect("equal", adjustable="box")
        self.ax.axis("off")

    def _get_panel_column_x(self, panel_column):
        return panel_column * self._get_panel_column_width()

    def _get_panel_column_width(self):
        return (
            self.engine.state.grid.width * (self.bin_width + self.stack_gap)
            + self.panel_column_gap
        )

    def _get_stack_local_x(self, x):
        return x * (self.bin_width + self.stack_gap)

    def _get_row_base_y(self, row_in_column):
        return (self.rows_per_panel_column - 1 - row_in_column) * self._get_single_row_height()

    def _get_single_row_height(self):
        return (
            self.engine.config.max_stack_height * self.bin_height
            + self.row_gap
            + self.robot_vertical_gap * 1.6
        )

    def _get_info_panel_x(self):
        return (
            self.row_panel_columns * self._get_panel_column_width()
            + self.info_panel_gap
        )

    def _get_top_content_y(self):
        return (
            (self.rows_per_panel_column - 1) * self._get_single_row_height()
            + self.engine.config.max_stack_height * self.bin_height
        )

    def _get_bottom_padding(self):
        return max(0.75, self.bin_height * 1.3)

    def _get_top_padding(self):
        return max(1.0, self.robot_vertical_gap * 2.5)

    def _get_left_label_offset(self):
        return max(0.7, self.bin_width * 1.2)

    def _get_x_label_offset(self):
        return max(0.22, self.bin_height * 0.45)

    def _get_max_drawn_pickstation_bins(self):
        max_stack_height = self.engine.config.max_stack_height
        return max(3, min(12, max_stack_height * 2))

    def _get_visual_scale(self):
        return max(0.35, min(1.0, self.bin_width / 0.85))

    def _get_target_bin_id(self, event):
        if event is None:
            return None

        if event.event_type == EventType.ARRIVAL:
            request = event.payload
            return getattr(request, "target_box_id", None)

        if isinstance(event.payload, dict):
            request = event.payload.get("request")
            action = event.payload.get("action")

            if request is not None:
                return getattr(request, "target_box_id", None)

            if action is not None:
                return action.get("bin_id")

        return None

    def _get_robot_id(self, event):
        if event is None or not isinstance(event.payload, dict):
            return None

        robot = event.payload.get("robot")

        if robot is None:
            return None

        return robot.robot_id

    def _get_action_type(self, event):
        if event is None or not isinstance(event.payload, dict):
            return None

        action = event.payload.get("action")

        if action is None:
            return None

        return action.get("type")

    def _find_stack_position_of_bin(self, bin_id):
        if bin_id is None:
            return None

        for stack in self.engine.state.grid.all_stacks():
            for bin_obj in stack.bins:
                if bin_obj.bin_id == bin_id:
                    return self._parse_stack_position(stack)

        return None

    def _parse_stack_position(self, stack):
        stack_id = stack.stack_id

        if isinstance(stack_id, tuple):
            return stack_id

        if isinstance(stack_id, str) and stack_id.startswith("S_"):
            parts = stack_id.split("_")

            if len(parts) == 3:
                return int(parts[1]), int(parts[2])

        return stack_id


def show_storage_side_view(engine):
    """
    Convenience-Funktion für main.py.

    Beispiel:
        visualizer = show_storage_side_view(engine)
    """
    visualizer = StorageSideViewVisualizer(engine)
    visualizer.show()
    return visualizer