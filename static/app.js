const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const imageList = document.getElementById("imageList");
const emptyMessage = document.getElementById("emptyMessage");
const imageCount = document.getElementById("imageCount");
const statusText = document.getElementById("status");
const verticalScale = document.getElementById("verticalScale");
const gapMm = document.getElementById("gapMm");
const memoryPart = document.getElementById("memoryPart");
const memoryStart = document.getElementById("memoryStart");
const memoryClear = document.getElementById("memoryClear");
const memoryFileInput = document.getElementById("memoryFileInput");
const memoryFinish = document.getElementById("memoryFinish");
const memoryStatus = document.getElementById("memoryStatus");
const memoryDownloads = document.getElementById("memoryDownloads");

let items = [];
let nextId = 1;
let memorySessionId = null;
let memoryState = null;

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("error", isError);
}

function setMemoryStatus(message, isError = false) {
  memoryStatus.textContent = message;
  memoryStatus.classList.toggle("error", isError);
}

function addFiles(files) {
  Array.from(files)
    .filter((file) => file.type.startsWith("image/"))
    .forEach((file) => {
      items.push({
        id: nextId++,
        file,
        url: URL.createObjectURL(file),
      });
    });
  renderList();
}

function renderList() {
  imageList.innerHTML = "";
  items.forEach((item, index) => {
    const li = document.createElement("li");
    li.className = "image-item";

    const number = document.createElement("div");
    number.className = "number";
    number.textContent = index + 1;

    const thumbnail = document.createElement("img");
    thumbnail.src = item.url;
    thumbnail.alt = item.file.name;

    const info = document.createElement("div");
    info.className = "file-info";
    const name = document.createElement("strong");
    name.textContent = item.file.name;
    const size = document.createElement("span");
    size.textContent = `${Math.round(item.file.size / 1024)} KB`;
    info.append(name, size);

    const controls = document.createElement("div");
    controls.className = "item-controls";
    controls.append(
      controlButton("↑", () => moveItem(index, -1), index === 0),
      controlButton("↓", () => moveItem(index, 1), index === items.length - 1),
      controlButton("削除", () => removeItem(index), false, "danger")
    );

    li.append(number, thumbnail, info, controls);
    imageList.appendChild(li);
  });

  imageCount.textContent = `${items.length}枚`;
  emptyMessage.hidden = items.length > 0;
}

function controlButton(label, onClick, disabled = false, className = "") {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = label;
  button.disabled = disabled;
  if (className) button.classList.add(className);
  button.addEventListener("click", onClick);
  return button;
}

function moveItem(index, direction) {
  const target = index + direction;
  if (target < 0 || target >= items.length) return;
  [items[index], items[target]] = [items[target], items[index]];
  renderList();
}

function removeItem(index) {
  URL.revokeObjectURL(items[index].url);
  items.splice(index, 1);
  renderList();
}

function makeFormData() {
  const formData = new FormData();
  items.forEach((item) => {
    formData.append("images", item.file, item.file.name);
  });
  formData.append("vertical_scale", verticalScale.value);
  formData.append("gap_mm", gapMm.value);
  return formData;
}

function setButtonsDisabled(disabled) {
  document.querySelectorAll("button").forEach((button) => {
    button.disabled = disabled;
  });
  renderList();
  updateMemoryControls();
}

async function generate(url, filename) {
  if (items.length === 0) {
    setStatus("画像を追加してください。", true);
    return;
  }

  setButtonsDisabled(true);
  setStatus("PDFを作成しています。少し待ってください。");
  try {
    const response = await fetch(url, {
      method: "POST",
      body: makeFormData(),
    });
    if (!response.ok) {
      const data = await response.json().catch(() => ({}));
      throw new Error(data.error || "PDFファイルの作成に失敗しました。");
    }
    const blob = await response.blob();
    downloadBlob(blob, filename);
    setStatus("作成が完了しました。");
  } catch (error) {
    setStatus(error.message, true);
  } finally {
    setButtonsDisabled(false);
  }
}

function downloadBlob(blob, filename) {
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  URL.revokeObjectURL(url);
}

function updateMemoryControls() {
  const active = Boolean(memorySessionId);
  memoryFileInput.disabled = !active;
  memoryFinish.disabled = !active || !memoryState || memoryState.current_count === 0;
  memoryStart.disabled = active;
  memoryPart.disabled = active;
  verticalScale.disabled = active;
  gapMm.disabled = active;
}

function renderMemoryDownloads() {
  memoryDownloads.innerHTML = "";
  if (!memorySessionId || !memoryState) return;
  memoryState.ready_pages.forEach((page) => {
    const link = document.createElement("a");
    link.href = `/memory/${memorySessionId}/download/${page.page}`;
    link.textContent = `パート${memoryState.part} ${page.page}ページ目をダウンロード`;
    link.className = "download-link";
    memoryDownloads.appendChild(link);
  });
}

async function startMemoryMode() {
  const formData = new FormData();
  formData.append("part", memoryPart.value);
  formData.append("vertical_scale", verticalScale.value);
  formData.append("gap_mm", gapMm.value);
  setMemoryStatus("省メモリモードを開始しています。");
  try {
    const response = await fetch("/memory/start", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "省メモリモードを開始できませんでした。");
    memorySessionId = data.session_id;
    memoryState = data.state;
    setMemoryStatus(data.message);
    renderMemoryDownloads();
    updateMemoryControls();
  } catch (error) {
    setMemoryStatus(error.message, true);
  }
}

async function addMemoryImages(files) {
  if (!memorySessionId) {
    setMemoryStatus("先に省メモリモードを開始してください。", true);
    return;
  }
  const selected = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (selected.length === 0) return;

  const formData = new FormData();
  selected.forEach((file) => formData.append("images", file, file.name));
  memoryFileInput.disabled = true;
  memoryFinish.disabled = true;
  setMemoryStatus("画像を処理しています。");
  try {
    const response = await fetch(`/memory/${memorySessionId}/add`, {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "画像の処理に失敗しました。");
    memoryState = data.state;
    setMemoryStatus(data.message);
    renderMemoryDownloads();
  } catch (error) {
    setMemoryStatus(error.message, true);
  } finally {
    updateMemoryControls();
  }
}

async function finishMemoryPage() {
  if (!memorySessionId) return;
  setMemoryStatus("最後のページを作成しています。");
  try {
    const response = await fetch(`/memory/${memorySessionId}/finish`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "最後のページを作成できませんでした。");
    memoryState = data.state;
    setMemoryStatus(data.message);
    renderMemoryDownloads();
  } catch (error) {
    setMemoryStatus(error.message, true);
  } finally {
    updateMemoryControls();
  }
}

async function clearMemoryMode() {
  if (memorySessionId) {
    await fetch(`/memory/${memorySessionId}/clear`, { method: "POST" }).catch(() => {});
  }
  memorySessionId = null;
  memoryState = null;
  memoryDownloads.innerHTML = "";
  setMemoryStatus("省メモリモードの作業をリセットしました。");
  updateMemoryControls();
}

fileInput.addEventListener("change", () => {
  addFiles(fileInput.files);
  fileInput.value = "";
});

dropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  dropZone.classList.add("dragover");
});

dropZone.addEventListener("dragleave", () => {
  dropZone.classList.remove("dragover");
});

dropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  dropZone.classList.remove("dragover");
  addFiles(event.dataTransfer.files);
});

document.querySelectorAll("[data-part]").forEach((button) => {
  button.addEventListener("click", () => {
    const part = button.dataset.part;
    generate(`/generate/${part}`, `part${part}.pdf`);
  });
});

memoryStart.addEventListener("click", startMemoryMode);
memoryClear.addEventListener("click", clearMemoryMode);
memoryFinish.addEventListener("click", finishMemoryPage);
memoryFileInput.addEventListener("change", () => {
  addMemoryImages(memoryFileInput.files);
  memoryFileInput.value = "";
});

renderList();
updateMemoryControls();
