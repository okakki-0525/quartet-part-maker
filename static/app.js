const verticalScale = document.getElementById("verticalScale");
const gapMm = document.getElementById("gapMm");
const memoryPart = document.getElementById("memoryPart");
const memoryStart = document.getElementById("memoryStart");
const memoryClear = document.getElementById("memoryClear");
const memoryFileInput = document.getElementById("memoryFileInput");
const memoryNext = document.getElementById("memoryNext");
const memoryFinish = document.getElementById("memoryFinish");
const memoryStatus = document.getElementById("memoryStatus");
const memoryDownloads = document.getElementById("memoryDownloads");
const registeredPages = document.getElementById("registeredPages");
const memoryDropZone = document.querySelector(".memory-upload");
const dropMain = document.getElementById("dropMain");
const dropSub = document.getElementById("dropSub");

let memorySessionId = null;
let memoryState = null;
let lastReadyPageCount = 0;
let waitingForNextPage = false;

function setMemoryStatus(message, isError = false) {
  memoryStatus.textContent = message;
  memoryStatus.classList.toggle("error", isError);
}

function setDropText(main, sub, isError = false) {
  dropMain.textContent = main;
  dropSub.textContent = sub;
  memoryDropZone.classList.toggle("drop-error", isError);
}

function resetDropText() {
  setDropText("次の画像を追加", "クリックまたはドラッグ＆ドロップで1ページずつ登録");
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
  memoryFileInput.disabled = waitingForNextPage;
  memoryNext.hidden = !waitingForNextPage;
  memoryNext.disabled = !waitingForNextPage;
  memoryFinish.disabled =
    !active || waitingForNextPage || !memoryState || Number(memoryState.current_count || 0) === 0;
  memoryStart.disabled = active;
  memoryPart.disabled = active;
  verticalScale.disabled = active;
  gapMm.disabled = active;
}

function renderProgress(defaultMessage = "") {
  if (!memoryState) {
    setMemoryStatus(defaultMessage || "画像を登録すると、自動で作成を開始します。");
    return;
  }

  const part = selectedPartLabel();
  const totalSystems = Number(memoryState.extracted_systems || 0);
  const readyPages = memoryState.ready_pages || [];
  const latestReady = readyPages[readyPages.length - 1];

  if (readyPages.length > lastReadyPageCount && latestReady) {
    waitingForNextPage = true;
    setMemoryStatus(
      `${part}の${latestReady.page}ページ目が作成できるようになりました。まだ入りきらなかった段があるので次ページの先頭に入れます。`
    );
    setDropText("ページが完成しました", "「次のページを作成する」を押すと次の画像を登録できます");
    lastReadyPageCount = readyPages.length;
    updateMemoryControls();
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
  if (memorySessionId) return true;

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
    waitingForNextPage = false;
    updateRegisteredPages();
    renderMemoryDownloads();
    renderProgress(`${selectedPartLabel()}の0段目まで抽出しました。`);
    resetDropText();
    return true;
  } catch (error) {
    setMemoryStatus(error.message, true);
    return false;
  } finally {
    updateMemoryControls();
  }
}

async function addMemoryImages(files) {
  const selected = Array.from(files).filter((file) => file.type.startsWith("image/"));
  if (selected.length === 0) return;

  if (selected.length > 1) {
    setDropText("画像は1枚ずつ登録してください", "2枚以上は登録されませんでした", true);
    return;
  }

  if (waitingForNextPage) {
    setDropText("次のページを作成してください", "先に「次のページを作成する」を押してください", true);
    return;
  }

  const started = await startMemoryMode();
  if (!started || !memorySessionId) return;

  const formData = new FormData();
  formData.append("images", selected[0], selected[0].name);
  memoryFileInput.disabled = true;
  memoryFinish.disabled = true;
  setDropText("画像を処理しています", selected[0].name);
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
    resetDropText();
    renderProgress();
  } catch (error) {
    setMemoryStatus(error.message, true);
    setDropText("画像の処理に失敗しました", "別の画像で試してください", true);
  } finally {
    updateMemoryControls();
  }
}

function continueNextPage() {
  waitingForNextPage = false;
  resetDropText();
  renderProgress(`${selectedPartLabel()}の${Number(memoryState.extracted_systems || 0)}段目まで抽出しました。`);
  updateMemoryControls();
}

async function finishMemoryPage() {
  if (!memorySessionId || waitingForNextPage) return;

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
    waitingForNextPage = false;
    updateRegisteredPages();
    renderMemoryDownloads();
    resetDropText();

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
  waitingForNextPage = false;
  memoryDownloads.innerHTML = "";
  updateRegisteredPages();
  resetDropText();
  setMemoryStatus("画像を登録すると、自動で作成を開始します。");
  updateMemoryControls();
}

memoryStart.addEventListener("click", startMemoryMode);
memoryClear.addEventListener("click", clearMemoryMode);
memoryNext.addEventListener("click", continueNextPage);
memoryFinish.addEventListener("click", finishMemoryPage);
memoryFileInput.addEventListener("change", () => {
  addMemoryImages(memoryFileInput.files);
  memoryFileInput.value = "";
});

memoryDropZone.addEventListener("dragover", (event) => {
  event.preventDefault();
  if (!waitingForNextPage) {
    memoryDropZone.classList.add("dragover");
  }
});

memoryDropZone.addEventListener("dragleave", () => {
  memoryDropZone.classList.remove("dragover");
});

memoryDropZone.addEventListener("drop", (event) => {
  event.preventDefault();
  memoryDropZone.classList.remove("dragover");
  addMemoryImages(event.dataTransfer.files);
});

resetDropText();
updateRegisteredPages();
updateMemoryControls();
