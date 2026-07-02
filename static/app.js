const fileInput = document.getElementById("fileInput");
const dropZone = document.getElementById("dropZone");
const imageList = document.getElementById("imageList");
const emptyMessage = document.getElementById("emptyMessage");
const imageCount = document.getElementById("imageCount");
const statusText = document.getElementById("status");
const allButton = document.getElementById("allButton");
const verticalScale = document.getElementById("verticalScale");
const gapMm = document.getElementById("gapMm");

let items = [];
let nextId = 1;

function setStatus(message, isError = false) {
  statusText.textContent = message;
  statusText.classList.toggle("error", isError);
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
      throw new Error(data.error || "PDF作成に失敗しました。");
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

allButton.addEventListener("click", () => {
  generate("/generate/all", "parts.zip");
});

renderList();
