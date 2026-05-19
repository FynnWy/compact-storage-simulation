// static/js/views/base_view.js

class BaseView {
    constructor(containerId, svgId) {
        this.containerId = containerId;
        this.svgId = svgId;
        this.isActive = false;
    }

    /**
     * Initialisiert die View (einmalig beim Erstellen)
     */
    initialize() {
        throw new Error("initialize() must be implemented by subclass");
    }

    /**
     * Rendert den aktuellen State
     * @param {Object} state - Der aktuelle Simulationszustand
     */
    render(state) {
        throw new Error("render() must be implemented by subclass");
    }

    /**
     * Aktiviert diese View (macht sie sichtbar)
     */
    activate() {
        this.isActive = true;
        const container = document.getElementById(this.containerId);
        if (container) {
            container.style.display = "block";
        }
    }

    /**
     * Deaktiviert diese View (versteckt sie)
     */
    deactivate() {
        this.isActive = false;
        const container = document.getElementById(this.containerId);
        if (container) {
            container.style.display = "none";
        }
    }

    /**
     * Cleanup bei View-Wechsel
     */
    cleanup() {
        // Optional: D3-Selections aufräumen etc.
    }
}