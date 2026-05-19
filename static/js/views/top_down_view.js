// static/js/views/top_down_view.js

class TopDownView extends BaseView {
    constructor() {
        super("top-down-view-container", "top-down-svg");
    }

    initialize() {
        console.log("Top-Down View initialized");
    }

    render(state) {
        if (!this.isActive) return;

        const svg = d3.select("#" + this.svgId);
        const container = document.getElementById(this.containerId);

        if (!container || !state) return;

        const gridWidth = state.grid_width || 0;
        const gridDepth = state.grid_depth || 0;

        if (gridWidth <= 0 || gridDepth <= 0) {
            this._renderEmpty(svg);
            return;
        }

        const layout = this._calculateLayout(container, gridWidth, gridDepth);

        svg.attr("width", layout.totalWidth)
           .attr("height", layout.totalHeight);

        svg.selectAll("*").remove();

        this._renderGrid(svg, layout, state);
        this._renderStackHeights(svg, layout, state);
        this._renderRobots(svg, layout, state);
        this._renderPickstations(svg, layout, state);
    }

    _calculateLayout(container, gridWidth, gridDepth) {
        const containerWidth = container.clientWidth || 800;
        const containerHeight = container.clientHeight || 600;

        const padding = 60;
        const availableWidth = containerWidth - 2 * padding;
        const availableHeight = containerHeight - 2 * padding;

        const cellSize = Math.min(
            availableWidth / gridWidth,
            availableHeight / gridDepth,
            80  // Maximum cell size
        );

        return {
            cellSize: cellSize,
            padding: padding,
            totalWidth: containerWidth,
            totalHeight: containerHeight,
            gridWidth: gridWidth,
            gridDepth: gridDepth
        };
    }

    _renderGrid(svg, layout, state) {
        const { cellSize, padding, gridWidth, gridDepth } = layout;

        // Grid-Zellen zeichnen
        for (let x = 0; x < gridWidth; x++) {
            for (let y = 0; y < gridDepth; y++) {
                svg.append("rect")
                   .attr("x", padding + x * cellSize)
                   .attr("y", padding + y * cellSize)
                   .attr("width", cellSize)
                   .attr("height", cellSize)
                   .attr("fill", "#f0f0f0")
                   .attr("stroke", "#999")
                   .attr("stroke-width", 1);
            }
        }
    }

    _renderStackHeights(svg, layout, state) {
        const { cellSize, padding } = layout;
        const stacks = state.grid || [];

        stacks.forEach(stack => {
            const x = stack.x;
            const y = stack.y;
            const height = stack.bins ? stack.bins.length : 0;

            if (height === 0) return;

            // Höhe als Zahl anzeigen
            svg.append("text")
               .attr("x", padding + x * cellSize + cellSize / 2)
               .attr("y", padding + y * cellSize + cellSize / 2 + 5)
               .attr("text-anchor", "middle")
               .attr("dominant-baseline", "middle")
               .attr("font-size", Math.min(cellSize * 0.4, 24))
               .attr("font-weight", "bold")
               .attr("fill", "#333")
               .text(height);

            // Farbliche Kodierung der Höhe
            const maxHeight = state.max_height || 6;
            const intensity = Math.min(height / maxHeight, 1);
            const color = d3.interpolateBlues(intensity * 0.7 + 0.3);

            svg.selectAll(`rect`)
               .filter(function() {
                   const rectX = parseFloat(d3.select(this).attr("x"));
                   const rectY = parseFloat(d3.select(this).attr("y"));
                   return Math.abs(rectX - (padding + x * cellSize)) < 0.1 &&
                          Math.abs(rectY - (padding + y * cellSize)) < 0.1;
               })
               .attr("fill", color);
        });
    }

    _renderRobots(svg, layout, state) {
        const { cellSize, padding } = layout;
        const robots = state.robots || [];

        robots.forEach(robot => {
            if (!robot.pos || !Array.isArray(robot.pos) || robot.pos.length !== 2) return;

            const [x, y] = robot.pos;

            // Roboter-Status bestimmt Farbe
            const color = this._getRobotColor(robot);

            // Roboter als Kreis
            const radius = cellSize * 0.3;
            svg.append("circle")
               .attr("cx", padding + x * cellSize + cellSize / 2)
               .attr("cy", padding + y * cellSize + cellSize / 2)
               .attr("r", radius)
               .attr("fill", color)
               .attr("stroke", "#000")
               .attr("stroke-width", 2);

            // Roboter-ID
            svg.append("text")
               .attr("x", padding + x * cellSize + cellSize / 2)
               .attr("y", padding + y * cellSize + cellSize / 2)
               .attr("text-anchor", "middle")
               .attr("dominant-baseline", "middle")
               .attr("font-size", Math.min(cellSize * 0.25, 14))
               .attr("fill", "#fff")
               .attr("font-weight", "bold")
               .text(`R${robot.id ?? robot.robot_id ?? "?"}`);
        });
    }

    _getRobotColor(robot) {
        // Grün: idle
        // Rot: bearbeitet Auftrag (busy)
        // Orange: hat Target-Bin (später implementierbar)

        const status = robot.status || "idle";

        if (status === "busy") {
            return "#dc3545";  // Rot
        }

        return "#28a745";  // Grün
    }

    _renderPickstations(svg, layout, state) {
        const { cellSize, padding } = layout;
        const pickstationBins = state.pickstation || [];

        // Pickstation-Position ist bei (-1, y)
        // Wir zeichnen sie links vom Grid
        if (pickstationBins.length === 0) return;

        const psX = padding - cellSize * 0.6;
        const psY = padding + (state.grid_depth || 0) * cellSize / 2;

        // Pickstation als Rechteck
        svg.append("rect")
           .attr("x", psX - cellSize * 0.4)
           .attr("y", psY - cellSize * 0.4)
           .attr("width", cellSize * 0.8)
           .attr("height", cellSize * 0.8)
           .attr("fill", pickstationBins.length > 0 ? "#ffc107" : "#6c757d")
           .attr("stroke", "#000")
           .attr("stroke-width", 2)
           .attr("rx", 4);

        // Label
        svg.append("text")
           .attr("x", psX)
           .attr("y", psY)
           .attr("text-anchor", "middle")
           .attr("dominant-baseline", "middle")
           .attr("font-size", Math.min(cellSize * 0.2, 12))
           .attr("fill", "#fff")
           .attr("font-weight", "bold")
           .text("PS");

        // Anzahl Bins an Pickstation
        if (pickstationBins.length > 0) {
            svg.append("text")
               .attr("x", psX)
               .attr("y", psY + cellSize * 0.5)
               .attr("text-anchor", "middle")
               .attr("font-size", Math.min(cellSize * 0.15, 10))
               .attr("fill", "#333")
               .text(`(${pickstationBins.length})`);
        }
    }

    _renderEmpty(svg) {
        svg.selectAll("*").remove();
        svg.attr("width", 600).attr("height", 300);

        svg.append("text")
           .attr("x", 300)
           .attr("y", 150)
           .attr("text-anchor", "middle")
           .attr("fill", "#666")
           .attr("font-size", 16)
           .text("No grid data available");
    }
}