// static/js/main.js

// Globale ViewManager-Instanz
let viewManager;

// Beim Laden initialisieren
document.addEventListener('DOMContentLoaded', function() {
    console.log("main.js: DOM loaded, initializing ViewManager...");

    // ViewManager erstellen
    viewManager = new ViewManager();

    // Views registrieren
    viewManager.registerView('side', new SideView());
    viewManager.registerView('topdown', new TopDownView());

    // Standardmäßig Side-View aktivieren
    viewManager.switchTo('side');

    console.log("ViewManager initialized with side and topdown views");
});

// Globale Switch-Funktion für Buttons
function switchView(viewName) {
    console.log("switchView called with:", viewName);

    if (!viewManager) {
        console.error("ViewManager not initialized yet");
        return;
    }

    viewManager.switchTo(viewName);

    // Aktuellen State neu rendern
    if (typeof currentState !== 'undefined' && currentState) {
        console.log("Rendering current state in new view");
        viewManager.render(currentState);
    } else {
        console.warn("No currentState available for rendering");
    }
}