// static/js/visualizer.js

const colors = {
    normalBin: "#90caf9",
    targetBin: "#ef5350",
    movedBin: "#fb923c",
    previousPosition: "#cbd5e1",
    emptyStack: "#94a3b8",
    robot: "#37474f",
    pickstation: "#ffca28",
    lockedStack: "#fde68a",
    lockedStackStroke: "#f59e0b",
    background: "#f8fafc",
    textMuted: "#64748b"
};

let currentState = null;
let previousState = null;
let currentMovement = null;
let isPlaying = false;
let playInterval = null;

function normalizeStateResponse(data) {
    const state = data && data.state ? data.state : data;

    return {
        t: state?.t ?? 0,
        grid_width: state?.grid_width ?? 0,
        grid_depth: state?.grid_depth ?? 0,
        max_height: state?.max_height ?? 1,
        grid: Array.isArray(state?.grid) ? state.grid : [],
        robots: Array.isArray(state?.robots) ? state.robots : [],
        pickstation: Array.isArray(state?.pickstation) ? state.pickstation : [],
        event: state?.event ?? null,
        active_queue: state?.active_queue ?? {
            pending_count: 0,
            assigned_count: 0,
            pending: [],
            assigned: []
        },
        history_index: state?.history_index ?? 0,
        history_len: state?.history_len ?? 1,
        is_finished: state?.is_finished ?? false,
        status: data?.status ?? state?.status ?? null
    };
}

function getElement(id) {
    return document.getElementById(id);
}

function setNextButtonEnabled(enabled) {
    const nextButton = getElement("btn-next");

    if (!nextButton) {
        return;
    }

    nextButton.disabled = !enabled;

    if (enabled) {
        nextButton.classList.remove("opacity-50");
    } else {
        nextButton.classList.add("opacity-50");
    }
}

function setStatusBadge(text, className) {
    const badge = getElement("status-badge");

    if (!badge) {
        return;
    }

    badge.className = `px-3 py-1 rounded-full text-xs font-semibold ${className}`;
    badge.innerText = text;
}

function showError(message) {
    console.error(message);
    setStatusBadge("ERROR", "bg-red-500 text-white");

    const svg = d3.select("#viz-svg");
    svg.attr("width", 600).attr("height", 160);
    svg.selectAll("*").remove();

    svg.append("rect")
        .attr("x", 0)
        .attr("y", 0)
        .attr("width", 600)
        .attr("height", 160)
        .attr("fill", "#fff1f2")
        .attr("stroke", "#fb7185")
        .attr("stroke-width", 2);

    svg.append("text")
        .attr("x", 20)
        .attr("y", 70)
        .attr("fill", "#be123c")
        .attr("font-size", 14)
        .attr("font-weight", "bold")
        .text("Visualisierung konnte nicht aktualisiert werden.");

    svg.append("text")
        .attr("x", 20)
        .attr("y", 100)
        .attr("fill", "#881337")
        .attr("font-size", 12)
        .text(String(message));
}

async function requestJson(url, options = {}) {
    const response = await fetch(url, options);

    if (!response.ok) {
        throw new Error(`${url} returned HTTP ${response.status}`);
    }

    return response.json();
}

async function fetchState() {
    try {
        const data = await requestJson("/api/state");
        const nextState = normalizeStateResponse(data);

        previousState = null;
        currentState = nextState;
        currentMovement = null;

        setStatusBadge("CONNECTED", "bg-green-500 text-white");
        updateUI();
    } catch (error) {
        showError(error.message);
    }
}

async function nextStep() {
    try {
        const data = await requestJson("/api/next", { method: "POST" });
        const nextState = normalizeStateResponse(data);

        previousState = currentState;
        currentState = nextState;
        currentMovement = detectMovement(previousState, currentState);

        if (currentState.status === "finished" || currentState.is_finished) {
            setNextButtonEnabled(false);
        }

        updateUI();
    } catch (error) {
        stopPlaying();
        showError(error.message);
    }
}

async function prevStep() {
    try {
        const data = await requestJson("/api/previous", { method: "POST" });
        const nextState = normalizeStateResponse(data);

        previousState = null;
        currentState = nextState;
        currentMovement = null;

        setNextButtonEnabled(true);
        updateUI();
    } catch (error) {
        stopPlaying();
        showError(error.message);
    }
}

async function resetSim() {
    try {
        const data = await requestJson("/api/reset", { method: "POST" });
        const nextState = normalizeStateResponse(data);

        previousState = null;
        currentState = nextState;
        currentMovement = null;

        setNextButtonEnabled(true);
        updateUI();
    } catch (error) {
        stopPlaying();
        showError(error.message);
    }
}

function updateUI() {
    if (!currentState) {
        return;
    }

    updateTimeAndHistory();
    updateEventCard();
    updatePickstation();
    updateActiveQueue();
    updateRobots();
    renderGrid();
}

function updateTimeAndHistory() {
    const currentTime = getElement("current-time");
    const historyCounter = getElement("history-counter");

    if (currentTime) {
        currentTime.innerText = `t=${currentState.t}`;
    }

    if (historyCounter) {
        historyCounter.innerText = `${currentState.history_index}/${Math.max(0, currentState.history_len - 1)}`;
    }
}

function updateEventCard() {
    const eventType = getElement("event-type");
    const eventDetails = getElement("event-details");
    const eventCard = getElement("event-card");

    if (!eventType || !eventDetails || !eventCard) {
        return;
    }

    const eventInfo = currentState.event;

    if (!eventInfo) {
        eventType.innerText = "Initial State";
        eventDetails.innerText = "Bereit zum Start";
        eventCard.classList.remove("border-blue-300", "bg-blue-50");
        return;
    }

    eventType.innerText = eventInfo.type ?? "-";

    let details = `Time: ${eventInfo.time ?? "-"}`;

    if (eventInfo.robot_id !== null && eventInfo.robot_id !== undefined) {
        details += ` | Robot: R${eventInfo.robot_id}`;
    }

    if (eventInfo.action) {
        details += ` | Action: ${eventInfo.action}`;
    }

    if (eventInfo.target_bin !== null && eventInfo.target_bin !== undefined) {
        details += ` | Target Bin: ${eventInfo.target_bin}`;
    }

    eventDetails.innerText = details;
    eventCard.classList.add("border-blue-300", "bg-blue-50");
}

function updatePickstation() {
    const pickstationList = getElement("pickstation-list");

    if (!pickstationList) {
        return;
    }

    pickstationList.innerHTML = "";

    if (currentState.pickstation.length === 0) {
        pickstationList.innerHTML = '<span class="text-gray-400 italic text-sm">Leer</span>';
        return;
    }

    currentState.pickstation.forEach(bin => {
        const span = document.createElement("span");
        span.className = "px-2 py-1 bg-amber-100 text-amber-800 border border-amber-200 rounded font-bold text-xs";
        span.innerText = bin.id ?? "?";
        pickstationList.appendChild(span);
    });
}

function updateActiveQueue() {
    const card = getElement("active-queue-card");

    if (!card) {
        return;
    }

    const queue = currentState.active_queue ?? {
        pending_count: 0,
        pending: []
    };

    const pendingRequests = Array.isArray(queue.pending) ? queue.pending : [];

    if (pendingRequests.length === 0) {
        card.className = "bg-slate-50 border border-slate-200 rounded p-2 text-[10px] text-slate-500 leading-snug";
        card.innerHTML = "Keine pending Requests";
        return;
    }

    const requestBadges = pendingRequests.slice(0, 8).map(request => `
        <span class="inline-flex items-center px-1.5 py-0.5 rounded bg-blue-100 text-blue-700 font-bold border border-blue-200">
            Req ${request.request_id ?? "?"}
        </span>
    `).join("");

    const hiddenCount = pendingRequests.length - 8;
    const hiddenText = hiddenCount > 0
        ? `<span class="text-slate-400">+${hiddenCount} more</span>`
        : "";

    card.className = "bg-blue-50 border border-blue-200 rounded p-2 text-[10px] text-slate-700 leading-snug";
    card.innerHTML = `
        <div class="font-bold text-blue-700 mb-1">Pending: ${pendingRequests.length}</div>
        <div class="flex flex-wrap gap-1">
            ${requestBadges}
            ${hiddenText}
        </div>
    `;
}

function updateRobots() {
    const robotList = getElement("robot-list");

    if (!robotList) {
        return;
    }

    robotList.innerHTML = "";

    if (currentState.robots.length === 0) {
        robotList.innerHTML = '<span class="text-gray-400 italic text-sm">Keine Roboter</span>';
        return;
    }

    currentState.robots.forEach(robot => {
        const div = document.createElement("div");
        div.className = "p-1.5 border rounded text-[10px] flex flex-col gap-0.5";

        const status = robot.status ?? "unknown";
        const statusColor = status === "busy" ? "text-red-500" : "text-teal-600";
        const robotPosText = formatPosition(robot.pos);

        div.innerHTML = `
            <div class="flex justify-between font-bold">
                <span>R${robot.id ?? "?"}</span>
                <span class="${statusColor}">${status.toUpperCase()}</span>
            </div>
            <div class="text-gray-500 leading-tight">Pos: ${robotPosText}</div>
            <div class="text-gray-400 leading-tight">Task: ${robot.task ?? "-"}</div>
        `;

        robotList.appendChild(div);
    });
}

function formatPosition(position) {
    if (Array.isArray(position) && position.length === 2) {
        return `(${position[0]}, ${position[1]})`;
    }

    return "not placed";
}

function buildBinPositionMap(state) {
    const map = new Map();

    if (!state || !Array.isArray(state.grid)) {
        return map;
    }

    state.grid.forEach(stack => {
        if (!Array.isArray(stack.bins)) {
            return;
        }

        stack.bins.forEach((bin, level) => {
            map.set(String(bin.id), {
                binId: bin.id,
                x: stack.x,
                y: stack.y,
                level,
                location: "grid"
            });
        });
    });

    if (Array.isArray(state.pickstation)) {
        state.pickstation.forEach((bin, index) => {
            map.set(String(bin.id), {
                binId: bin.id,
                level: index,
                location: "pickstation"
            });
        });
    }

    return map;
}

function detectMovement(previous, current) {
    if (!previous || !current) {
        return null;
    }

    const previousPositions = buildBinPositionMap(previous);
    const currentPositions = buildBinPositionMap(current);

    for (const [binId, previousPosition] of previousPositions.entries()) {
        const currentPosition = currentPositions.get(binId);

        if (!currentPosition) {
            continue;
        }

        const moved =
            previousPosition.location !== currentPosition.location ||
            previousPosition.x !== currentPosition.x ||
            previousPosition.y !== currentPosition.y ||
            previousPosition.level !== currentPosition.level;

        if (!moved) {
            continue;
        }

        let type = "moved";

        if (previousPosition.location === "grid" && currentPosition.location === "grid") {
            type = "relocated";
        }

        if (previousPosition.location === "grid" && currentPosition.location === "pickstation") {
            type = "picked";
        }

        return {
            type,
            binId: Number.isNaN(Number(binId)) ? binId : Number(binId),
            from: previousPosition,
            to: currentPosition
        };
    }

    return null;
}

function renderGrid() {
    if (typeof d3 === "undefined") {
        throw new Error("D3 wurde nicht geladen. Prüfe die Script-Einbindung in index.html.");
    }

    const svg = d3.select("#viz-svg");
    const container = getElement("viz-container");

    if (!container) {
        return;
    }

    const gridWidth = Number(currentState.grid_width) || 0;
    const gridDepth = Number(currentState.grid_depth) || 0;
    const maxHeight = Math.max(1, Number(currentState.max_height) || 1);

    if (gridWidth <= 0 || gridDepth <= 0) {
        renderEmptyGridMessage(svg);
        return;
    }

    const layout = calculateGridLayout(container, gridWidth, gridDepth, maxHeight);

    svg.attr("width", layout.totalWidth).attr("height", layout.totalHeight);
    svg.selectAll("*").remove();

    const targetBinId = currentState.event ? currentState.event.target_bin : null;

    for (let y = 0; y < gridDepth; y++) {
        renderGridRow(svg, layout, y, gridWidth, maxHeight, targetBinId);
    }
}

function renderEmptyGridMessage(svg) {
    svg.attr("width", 400).attr("height", 120);
    svg.selectAll("*").remove();

    svg.append("rect")
        .attr("x", 0)
        .attr("y", 0)
        .attr("width", 400)
        .attr("height", 120)
        .attr("fill", colors.background)
        .attr("stroke", colors.emptyStack)
        .attr("stroke-width", 1.5);

    svg.append("text")
        .attr("x", 20)
        .attr("y", 60)
        .attr("fill", colors.textMuted)
        .attr("font-size", 14)
        .text("Kein Grid im aktuellen State vorhanden.");
}

function calculateGridLayout(container, gridWidth, gridDepth, maxHeight) {
    const availableWidth = Math.max(320, container.clientWidth - 16);
    const availableHeight = Math.max(240, container.clientHeight - 16);

    const baseBinW = 40;
    const baseBinH = 30;
    const baseStackGap = 10;
    const baseRowGap = 42;
    const baseRobotGap = 18;

    const idealRowWidth = gridWidth * (baseBinW + baseStackGap);
    const idealRowHeight = maxHeight * baseBinH + baseRowGap + baseRobotGap;

    const maxColumnsByWidth = Math.max(1, Math.floor(availableWidth / Math.max(1, idealRowWidth + 32)));
    const cols = Math.max(1, Math.min(gridDepth, maxColumnsByWidth));
    const rowsPerCol = Math.max(1, Math.ceil(gridDepth / cols));

    const unscaledWidth = cols * (idealRowWidth + 32);
    const unscaledHeight = rowsPerCol * idealRowHeight + 36;

    const widthScale = availableWidth / Math.max(1, unscaledWidth);
    const heightScale = availableHeight / Math.max(1, unscaledHeight);

    const scale = Math.max(0.55, Math.min(1.15, widthScale, heightScale));

    const binW = Math.max(24, Math.round(baseBinW * scale));
    const binH = Math.max(18, Math.round(baseBinH * scale));
    const stackGap = Math.max(5, Math.round(baseStackGap * scale));
    const rowGap = Math.max(24, Math.round(baseRowGap * scale));
    const robotGap = Math.max(12, Math.round(baseRobotGap * scale));

    const rowWidth = gridWidth * (binW + stackGap);
    const rowHeight = maxHeight * binH + rowGap + robotGap;

    const panelGap = Math.max(20, Math.round(32 * scale));

    return {
        binW,
        binH,
        stackGap,
        rowGap,
        robotGap,
        rowWidth,
        rowHeight,
        cols,
        rowsPerCol,
        panelGap,
        scale,
        totalWidth: cols * (rowWidth + panelGap) + 24,
        totalHeight: rowsPerCol * rowHeight + 36
    };
}

function renderGridRow(svg, layout, y, gridWidth, maxHeight, targetBinId) {
    const colIdx = Math.floor(y / layout.rowsPerCol);
    const rowIdx = y % layout.rowsPerCol;

    const offsetX = colIdx * (layout.rowWidth + layout.panelGap) + 34;
    const offsetY = rowIdx * layout.rowHeight + 28;

    const rowGroup = svg.append("g")
        .attr("transform", `translate(${offsetX}, ${offsetY})`);

    rowGroup.append("text")
        .attr("x", -6)
        .attr("y", (maxHeight * layout.binH) / 2)
        .attr("text-anchor", "end")
        .attr("dominant-baseline", "middle")
        .attr("class", "font-bold fill-gray-400")
        .attr("font-size", Math.max(8, Math.round(10 * layout.scale)))
        .text(`y=${y}`);

    for (let x = 0; x < gridWidth; x++) {
        renderStack(rowGroup, layout, x, y, maxHeight, targetBinId);
    }
}

function renderStack(rowGroup, layout, x, y, maxHeight, targetBinId) {
    const stackX = x * (layout.binW + layout.stackGap);
    const stack = findStack(x, y);
    const lockedBy = stack ? stack.locked_by : null;
    const isLocked = lockedBy !== null && lockedBy !== undefined;

    rowGroup.append("rect")
        .attr("x", stackX)
        .attr("y", 0)
        .attr("width", layout.binW)
        .attr("height", maxHeight * layout.binH)
        .attr("fill", isLocked ? colors.lockedStack : "#ffffff")
        .attr("stroke", isLocked ? colors.lockedStackStroke : colors.emptyStack)
        .attr("stroke-width", isLocked ? 2.5 : 1.5);

    renderPreviousPositionMarker(rowGroup, layout, stackX, x, y, maxHeight);

    if (isLocked) {
        rowGroup.append("text")
            .attr("x", stackX + layout.binW / 2)
            .attr("y", -Math.max(10, 12 * layout.scale))
            .attr("text-anchor", "middle")
            .attr("fill", colors.lockedStackStroke)
            .attr("font-size", Math.max(7, Math.round(8 * layout.scale)))
            .attr("font-weight", "800")
            .text(`R${lockedBy}`);
    }

    if (stack && Array.isArray(stack.bins)) {
        stack.bins.forEach((bin, level) => {
            renderBin(rowGroup, layout, stackX, maxHeight, bin, level, targetBinId);
        });
    }

    renderXLabelIfNeeded(rowGroup, layout, stackX, x, y, maxHeight);
    renderRobotsOnStack(rowGroup, layout, stackX, x, y);
}

function renderPreviousPositionMarker(rowGroup, layout, stackX, x, y, maxHeight) {
    if (
        !currentMovement ||
        !currentMovement.from ||
        currentMovement.from.location !== "grid" ||
        currentMovement.from.x !== x ||
        currentMovement.from.y !== y
    ) {
        return;
    }

    const previousLevel = currentMovement.from.level;
    const markerY = (maxHeight - 1 - previousLevel) * layout.binH;

    rowGroup.append("rect")
        .attr("x", stackX + 2)
        .attr("y", markerY + 2)
        .attr("width", layout.binW - 4)
        .attr("height", layout.binH - 4)
        .attr("rx", 4)
        .attr("fill", colors.previousPosition)
        .attr("stroke", "#64748b")
        .attr("stroke-width", 1.5)
        .attr("stroke-dasharray", "4 2")
        .attr("opacity", 0.85);

    if (layout.binH >= 18 && layout.binW >= 24) {
        rowGroup.append("text")
            .attr("x", stackX + layout.binW / 2)
            .attr("y", markerY + layout.binH / 2)
            .attr("text-anchor", "middle")
            .attr("dominant-baseline", "middle")
            .attr("fill", "#475569")
            .attr("font-size", Math.max(7, Math.round(8 * layout.scale)))
            .attr("font-weight", "800")
            .text("old");
    }
}

function findStack(x, y) {
    return currentState.grid.find(stack => stack.x === x && stack.y === y);
}

function renderBin(rowGroup, layout, stackX, maxHeight, bin, level, targetBinId) {
    const binY = (maxHeight - 1 - level) * layout.binH;
    const isTarget = bin.id === targetBinId;
    const isMoved = currentMovement && String(currentMovement.binId) === String(bin.id);

    const fillColor = isMoved
        ? colors.movedBin
        : isTarget
            ? colors.targetBin
            : colors.normalBin;

    const textColor = isTarget || isMoved ? "white" : "#263238";

    const binGroup = rowGroup.append("g")
        .attr("transform", `translate(${stackX + 2}, ${binY + 2})`);

    binGroup.append("rect")
        .attr("width", layout.binW - 4)
        .attr("height", layout.binH - 4)
        .attr("rx", 4)
        .attr("fill", fillColor)
        .attr("stroke", isMoved ? "#c2410c" : "none")
        .attr("stroke-width", isMoved ? 2 : 0)
        .attr("class", "bin-rect shadow-sm");

    if (layout.binH >= 18 && layout.binW >= 24) {
        binGroup.append("text")
            .attr("x", (layout.binW - 4) / 2)
            .attr("y", (layout.binH - 4) / 2)
            .attr("text-anchor", "middle")
            .attr("dominant-baseline", "middle")
            .attr("fill", textColor)
            .attr("font-size", Math.max(8, Math.round(10 * layout.scale)))
            .attr("font-weight", "700")
            .text(bin.id ?? "?");
    }
}

function renderXLabelIfNeeded(rowGroup, layout, stackX, x, y, maxHeight) {
    const isLastDepthRow = y === currentState.grid_depth - 1;
    const isLastRowInPanelColumn = (y + 1) % layout.rowsPerCol === 0;

    if (!isLastDepthRow && !isLastRowInPanelColumn) {
        return;
    }

    rowGroup.append("text")
        .attr("x", stackX + layout.binW / 2)
        .attr("y", maxHeight * layout.binH + Math.max(10, Math.round(14 * layout.scale)))
        .attr("text-anchor", "middle")
        .attr("fill", "#94a3b8")
        .attr("font-size", Math.max(7, Math.round(8 * layout.scale)))
        .text(`x=${x}`);
}

function renderRobotsOnStack(rowGroup, layout, stackX, x, y) {
    currentState.robots.forEach(robot => {
        if (!Array.isArray(robot.pos) || robot.pos.length !== 2) {
            return;
        }

        if (robot.pos[0] !== x || robot.pos[1] !== y) {
            return;
        }

        rowGroup.append("path")
            .attr("d", d3.symbol().type(d3.symbolTriangle).size(Math.max(60, 100 * layout.scale))())
            .attr("transform", `translate(${stackX + layout.binW / 2}, ${-Math.max(8, 10 * layout.scale)}) rotate(180)`)
            .attr("fill", colors.robot);

        rowGroup.append("text")
            .attr("x", stackX + layout.binW / 2)
            .attr("y", -Math.max(12, 16 * layout.scale))
            .attr("text-anchor", "middle")
            .attr("fill", "#334155")
            .attr("font-size", Math.max(7, Math.round(8 * layout.scale)))
            .attr("font-weight", "700")
            .text(`R${robot.id ?? "?"}`);
    });
}

async function togglePlay() {
    if (isPlaying) {
        stopPlaying();
        return;
    }

    startPlaying();
}

function startPlaying() {
    isPlaying = true;

    const icon = getElement("play-icon");
    const button = getElement("btn-play");

    if (icon) {
        icon.classList.replace("fa-play", "fa-pause");
    }

    if (button) {
        button.classList.replace("bg-teal-500", "bg-orange-500");
    }

    playInterval = setInterval(async () => {
        await nextStep();

        if (currentState && (currentState.status === "finished" || currentState.is_finished)) {
            stopPlaying();
        }
    }, 500);
}

function stopPlaying() {
    isPlaying = false;

    const icon = getElement("play-icon");
    const button = getElement("btn-play");

    if (icon) {
        icon.classList.replace("fa-pause", "fa-play");
    }

    if (button) {
        button.classList.replace("bg-orange-500", "bg-teal-500");
    }

    if (playInterval) {
        clearInterval(playInterval);
        playInterval = null;
    }
}

function initializeEventListeners() {
    const nextButton = getElement("btn-next");
    const previousButton = getElement("btn-prev");
    const resetButton = getElement("btn-reset");
    const playButton = getElement("btn-play");

    if (nextButton) {
        nextButton.addEventListener("click", () => {
            stopPlaying();
            nextStep();
        });
    }

    if (previousButton) {
        previousButton.addEventListener("click", () => {
            stopPlaying();
            prevStep();
        });
    }

    if (resetButton) {
        resetButton.addEventListener("click", () => {
            stopPlaying();
            resetSim();
        });
    }

    if (playButton) {
        playButton.addEventListener("click", togglePlay);
    }

    document.addEventListener("keydown", event => {
        if (event.key === "ArrowRight") {
            stopPlaying();
            nextStep();
        }

        if (event.key === "ArrowLeft") {
            stopPlaying();
            prevStep();
        }

        if (event.key === " ") {
            event.preventDefault();
            togglePlay();
        }
    });

    window.addEventListener("resize", () => {
        if (currentState) {
            renderGrid();
        }
    });
}

initializeEventListeners();
fetchState();