"use strict";

const pdfFileInput = document.getElementById("pdf-file");
const browseButton = document.getElementById("browse-button");
const analyzeButton = document.getElementById("analyze-button");
const redactButton = document.getElementById("redact-button");
const selectedFileLabel = document.getElementById("selected-file");
const entityList = document.getElementById("entity-list");
const resultsSummary = document.getElementById("results-summary");
const statusMessage = document.getElementById("status-message");
const licenseButton = document.getElementById("license-button");
const licenseDialog = document.getElementById("license-dialog");
const licenseClose = document.getElementById("license-close");
const eelBridge = typeof window.eel === "object" ? window.eel : null;

const state = {
  filePath: "",
  entities: [],
  busy: false,
  backendAvailable: eelBridge !== null,
  runtimeReady: false,
};

function setStatus(message, status = "idle") {
  statusMessage.textContent = message;
  statusMessage.dataset.state = status;
}

function setBusy(isBusy) {
  state.busy = isBusy;
  pdfFileInput.disabled = isBusy;
  browseButton.disabled = isBusy || !state.backendAvailable;
  analyzeButton.disabled = isBusy || !state.filePath || !state.runtimeReady;
  updateRedactButton();
}

function updateRedactButton() {
  const checkedCount = entityList.querySelectorAll("input[type='checkbox']:checked").length;
  redactButton.disabled = state.busy || !state.runtimeReady || checkedCount === 0;
}

function getLocalFilePath(file) {
  if (file && typeof file.path === "string" && file.path.trim()) {
    return file.path.trim();
  }

  const inputValue = pdfFileInput.value.trim();
  if (inputValue && !inputValue.toLowerCase().includes("fakepath")) {
    return inputValue;
  }

  return "";
}

function extractErrorMessage(error) {
  if (typeof error === "string") {
    return error;
  }
  if (error && typeof error.errorText === "string") {
    return error.errorText;
  }
  if (error && typeof error.message === "string") {
    return error.message;
  }
  return "An unexpected local processing error occurred.";
}

async function callBackend(functionName, ...argumentsList) {
  if (!eelBridge || typeof eelBridge[functionName] !== "function") {
    throw new Error(
      "The Python backend is unavailable. Close this page and run START_BACKEND.bat next to index.html.",
    );
  }
  return eelBridge[functionName](...argumentsList)();
}

function renderEntities(entities) {
  entityList.replaceChildren();

  if (!entities.length) {
    const emptyMessage = document.createElement("p");
    emptyMessage.className = "empty-state";
    emptyMessage.textContent = "No sensitive entities were detected.";
    entityList.appendChild(emptyMessage);
    resultsSummary.textContent = "No possible amounts, names, or cities were found.";
    updateRedactButton();
    return;
  }

  entities.forEach((entity, index) => {
    const label = document.createElement("label");
    label.className = "entity-item";

    const checkbox = document.createElement("input");
    checkbox.type = "checkbox";
    checkbox.value = entity.text;
    checkbox.checked = true;
    checkbox.id = `entity-${index}`;
    checkbox.addEventListener("change", updateRedactButton);

    const text = document.createElement("span");
    text.className = "entity-text";
    text.textContent = entity.text;

    const metadata = document.createElement("span");
    metadata.className = "entity-meta";
    const category = entity.category === "amount" ? "Amount" : "Potential name or city";
    const occurrences = Number.isInteger(entity.occurrences) ? entity.occurrences : 1;
    metadata.textContent = `${category} · ${occurrences} occurrence${occurrences === 1 ? "" : "s"}`;

    label.append(checkbox, text, metadata);
    entityList.appendChild(label);
  });

  resultsSummary.textContent = `${entities.length} unique sensitive entit${entities.length === 1 ? "y" : "ies"} detected.`;
  updateRedactButton();
}

function handleBrowserFileSelection() {
  const file = pdfFileInput.files && pdfFileInput.files[0];
  state.filePath = getLocalFilePath(file);
  state.entities = [];
  renderEntities([]);

  if (!file) {
    selectedFileLabel.textContent = "No file selected";
    setStatus("Ready. Processing remains on this computer.");
    analyzeButton.disabled = true;
    return;
  }

  selectedFileLabel.textContent = file.name;
  if (!file.name.toLowerCase().endsWith(".pdf")) {
    state.filePath = "";
    setStatus("Select a file with a .pdf extension.", "error");
  } else if (!state.filePath) {
    setStatus("The browser did not provide an absolute local file path.", "error");
  } else {
    setStatus("PDF selected. Ready to analyze.");
  }
  analyzeButton.disabled = !state.filePath || !state.runtimeReady;
}

async function choosePdf() {
  if (state.busy) {
    return;
  }

  if (!state.backendAvailable) {
    setStatus(
      "Close this page and run START_BACKEND.bat next to index.html.",
      "error",
    );
    return;
  }

  setBusy(true);
  setStatus("Opening the local PDF picker.", "busy");
  try {
    const selectedPath = await callBackend("select_pdf");
    if (!selectedPath) {
      setStatus("PDF selection canceled.");
      return;
    }

    state.filePath = selectedPath;
    state.entities = [];
    renderEntities([]);
    selectedFileLabel.textContent = selectedPath.split(/[\\/]/).pop() || selectedPath;
    setStatus("PDF selected. Ready to analyze.");
  } catch (error) {
    setStatus(extractErrorMessage(error), "error");
  } finally {
    setBusy(false);
  }
}

pdfFileInput.addEventListener("click", (event) => {
  if (state.backendAvailable) {
    event.preventDefault();
    void choosePdf();
  }
});

pdfFileInput.addEventListener("change", handleBrowserFileSelection);

browseButton.addEventListener("click", () => {
  void choosePdf();
});

analyzeButton.addEventListener("click", async () => {
  if (!state.filePath || state.busy) {
    return;
  }

  setBusy(true);
  setStatus("Analyzing the PDF locally. Scanned pages may take several minutes.", "busy");

  try {
    const result = await callBackend("analyze_pdf", state.filePath);
    if (!Array.isArray(result)) {
      throw new Error("The analysis service returned an invalid response.");
    }
    state.entities = result;
    renderEntities(state.entities);
    setStatus("Analysis complete. Review the selected entities before redaction.", "success");
  } catch (error) {
    state.entities = [];
    renderEntities([]);
    setStatus(extractErrorMessage(error), "error");
  } finally {
    setBusy(false);
  }
});

redactButton.addEventListener("click", async () => {
  if (!state.filePath || state.busy) {
    return;
  }

  const approvedEntities = Array.from(
    entityList.querySelectorAll("input[type='checkbox']:checked"),
    (checkbox) => checkbox.value,
  );

  if (!approvedEntities.length) {
    setStatus("Select at least one entity to redact.", "error");
    return;
  }

  setBusy(true);
  setStatus("Applying permanent redactions locally.", "busy");

  try {
    const result = await callBackend("redact_pdf", state.filePath, approvedEntities);
    if (!result || result.success !== true) {
      throw new Error(result && result.error ? result.error : "Redaction failed.");
    }
    setStatus(`Redaction complete. Saved to: ${result.output_path}`, "success");
  } catch (error) {
    setStatus(extractErrorMessage(error), "error");
  } finally {
    setBusy(false);
  }
});

licenseButton.addEventListener("click", () => {
  if (typeof licenseDialog.showModal === "function") {
    licenseDialog.showModal();
  } else {
    licenseDialog.setAttribute("open", "");
  }
});

licenseClose.addEventListener("click", () => {
  if (typeof licenseDialog.close === "function") {
    licenseDialog.close();
  } else {
    licenseDialog.removeAttribute("open");
  }
});

licenseDialog.addEventListener("click", (event) => {
  if (event.target === licenseDialog) {
    licenseClose.click();
  }
});

async function initializeApplication() {
  if (!state.backendAvailable) {
    setBusy(false);
    pdfFileInput.disabled = true;
    setStatus(
      "Python backend not detected. Close this page and run START_BACKEND.bat next to index.html.",
      "error",
    );
    return;
  }

  setBusy(true);
  setStatus("Checking local runtime dependencies.", "busy");
  try {
    const runtimeStatus = await callBackend("get_runtime_status");
    state.runtimeReady = runtimeStatus.python_ready === true;

    if (!state.runtimeReady) {
      const missingPackages = runtimeStatus.missing_python_packages.join(", ");
      setStatus(`Missing Python packages: ${missingPackages}. Run the dependency installation first.`, "error");
    } else if (runtimeStatus.ocr_ready !== true) {
      const missingTools = runtimeStatus.missing_ocr_tools.join(", ");
      setStatus(`Ready for native PDFs. Scanned PDFs require: ${missingTools}.`, "busy");
    } else {
      setStatus("Ready. Processing remains on this computer.", "success");
    }
  } catch (error) {
    state.runtimeReady = false;
    setStatus(extractErrorMessage(error), "error");
  } finally {
    setBusy(false);
  }
}

void initializeApplication();
