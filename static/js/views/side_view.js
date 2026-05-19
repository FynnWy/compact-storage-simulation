// static/js/views/side_view.js

class SideView extends BaseView {
    constructor() {
        super("side-view-container", "viz-svg");
    }

    initialize() {
        console.log("Side View initialized");
    }

    render(state) {
        if (!this.isActive) {
            console.log("Side View: not active, skipping render");
            return;
        }

        console.log("Side View: rendering with state", state);

        // Nutze die bestehende renderGrid() Funktion
        if (typeof renderGrid === 'function') {
            console.log("Side View: calling renderGrid()");
            try {
                renderGrid();
                console.log("Side View: renderGrid() completed successfully");
            } catch (error) {
                console.error("Side View: renderGrid() failed:", error);
            }
        } else {
            console.error("Side View: renderGrid function not found");
        }
    }
}