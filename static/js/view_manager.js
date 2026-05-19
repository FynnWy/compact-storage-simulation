// static/js/view_manager.js

class ViewManager {
    constructor() {
        this.views = new Map();
        this.activeView = null;
    }

    registerView(name, viewInstance) {
        console.log(`ViewManager: registering view '${name}'`);
        this.views.set(name, viewInstance);
        viewInstance.initialize();
        viewInstance.deactivate();
    }

    switchTo(viewName) {
        console.log(`ViewManager: switching to view '${viewName}'`);

        const view = this.views.get(viewName);

        if (!view) {
            console.error(`View '${viewName}' not found`);
            return;
        }

        // Alte View deaktivieren
        if (this.activeView) {
            console.log(`ViewManager: deactivating old view`);
            this.activeView.cleanup();
            this.activeView.deactivate();
        }

        // Neue View aktivieren
        this.activeView = view;
        this.activeView.activate();

        console.log(`ViewManager: view '${viewName}' is now active`);

        // Button-States aktualisieren
        this._updateButtonStates(viewName);
    }

    render(state) {
        if (this.activeView) {
            console.log("ViewManager: rendering active view");
            this.activeView.render(state);
        } else {
            console.warn("ViewManager: no active view to render");
        }
    }

    _updateButtonStates(activeViewName) {
        document.querySelectorAll('.view-switch-btn').forEach(btn => {
            if (btn.dataset.view === activeViewName) {
                btn.classList.add('active');
            } else {
                btn.classList.remove('active');
            }
        });
    }
}