const verticalScale = document.getElementById("verticalScale");
const gapMm = document.getElementById("gapMm");
const memoryPart = document.getElementById("memoryPart");
const memoryStart = document.getElementById("memoryStart");
const memoryClear = document.getElementById("memoryClear");
const memoryFileInput = document.getElementById("memoryFileInput");
const memoryFinish = document.getElementById("memoryFinish");
const memoryStatus = document.getElementById("memoryStatus");
const memoryDownloads = document.getElementById("memoryDownloads");
const registeredPages = document.getElementById("registeredPages");

let memorySessionId = null;
let memoryState = null;
let lastReadyPageCount = 0;

function setMemoryStatus(message, isError = false) {
  memoryStatus.textContent = message;
  memoryStatus.classList.toggle("error", isError);
}

function selectedPartLabel() {
  const part = memoryState ? memoryState.part : memoryPart.value;
  return `パート${part}`;
}

function updateRegisteredPages() {
  const count = memoryState ? Number(memoryState.uploaded_pages || 0) : 0;
  registeredPages.textContent = `スコア${count}ページを登録しました。`;
}

function updateMemoryControls() {
  const active = Boolean(memorySessionId);
  memoryFileInput.disabled = !active;
  memoryFinish.disabled = !active || !memoryState || Number(memoryState.current_count || 0) === 0;
  memoryStart.disabled = active;
  memoryPart.disabled = active;
  verticalScale.disabled = active;
  gapMm.disabled = active;
}

function renderProgress(defaultMessage = "") {
  if (!memoryState) {
    setMemoryStatus(defaultMessage || "作成を開始すると、ここに進行状況が表示されます。");
    return;
  }

  const part = selectedPartLabel();
  const totalSystems = Number(memoryState.extracted_systems || 0);
  const readyPages = memoryState.ready_pages || [];
  const latestReady = readyPages[readyPages.length - 1];

  if (readyPages.length > lastReadyPageCount && latestReady) {
    setMemoryStatus(
      `${part}の${latestReady.page}ページ目が作成できるようになりました。まだ入りきらなかった段があるので次ページの先頭に入れます。`
    );
    lastReadyPageCount = readyPages.length;
    return;
  }

  if (defaultMessage) {
    setMemoryStatus(defaultMessage);
    return;
  }

  setMemoryStatus(`${part}の${totalSystems}段目まで抽出しました。`);
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
  setMemoryStatus("作成を開始しています。");

  try {
    const response = await fetch("/memory/start", {
      method: "POST",
      body: formData,
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "作成を開始できませんでした。");

    memorySessionId = data.session_id;
    memoryState = data.state;
    lastReadyPageCount = 0;
    updateRegisteredPages();
    renderMemoryDownloads();
    renderProgress(`${selectedPartLabel()}の0段目まで抽出しました。`);
  } catch (error) {
    setMemoryStatus(error.message, true);
  } finally {
    updateMemoryControls();
  }
}

async function addMemoryImages(files) {
  if (!memorySessionId) {
    setMemoryStatus("先に作成を開始してください。", true);
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
    updateRegisteredPages();
    renderMemoryDownloads();
    renderProgress();
  } catch (error) {
    setMemoryStatus(error.message, true);
  } finally {
    updateMemoryControls();
  }
}

async function finishMemoryPage() {
  if (!memorySessionId) return;

  setMemoryStatus("余った段をPDFにしています。");
  try {
    const response = await fetch(`/memory/${memorySessionId}/finish`, {
      method: "POST",
    });
    const data = await response.json();
    if (!response.ok) throw new Error(data.error || "余った段をPDFにできませんでした。");

    const previousReadyCount = memoryState ? memoryState.ready_pages.length : 0;
    memoryState = data.state;
    lastReadyPageCount = previousReadyCount;
    updateRegisteredPages();
    renderMemoryDownloads();

    const latestReady = memoryState.ready_pages[memoryState.ready_pages.length - 1];
    if (latestReady && memoryState.ready_pages.length > previousReadyCount) {
      setMemoryStatus(`パート${memoryState.part}の${latestReady.page}ページ目が作成できるようになりました。`);
      lastReadyPageCount = memoryState.ready_pages.length;
    } else {
      renderProgress("余った段はありません。");
    }
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
  lastReadyPageCount = 0;
  memoryDownloads.innerHTML = "";
  updateRegisteredPages();
  setMemoryStatus("作成を開始すると、ここに進行状況が表示されます。");
  updateMemoryControls();
}

memoryStart.addEventListener("click", startMemoryMode);
memoryClear.addEventListener("click", clearMemoryMode);
memoryFinish.addEventListener("click", finishMemoryPage);
memoryFileInput.addEventListener("change", () => {
  addMemoryImages(memoryFileInput.files);
  memoryFileInput.value = "";
});

updateRegisteredPages();
updateMemoryControls();
