/* Student photo on the Add/Edit student page: upload a picture or take one with the
   PC's camera. The picture is cropped to a centred square and shrunk in the browser,
   then sent with the form as a JPEG. */
(function () {
  "use strict";
  const SIZE = 480;                       // saved photo is 480 x 480 px
  const $ = id => document.getElementById(id);
  const frame = $("photo-frame"), preview = $("photo-preview"), empty = $("photo-empty");
  const data = $("photo-data"), remove = $("photo-remove"), fileInput = $("photo-file");
  const dlg = $("camera"), video = $("cam-video"), shot = $("cam-shot"), msg = $("cam-msg");
  const snapBtn = $("cam-snap"), useBtn = $("cam-use"), retakeBtn = $("cam-retake"), select = $("cam-select");
  let stream = null;

  function squareJpeg(source, w, h) {
    const side = Math.min(w, h);
    const c = document.createElement("canvas");
    c.width = c.height = SIZE;
    const g = c.getContext("2d");
    g.imageSmoothingQuality = "high";
    g.drawImage(source, (w - side) / 2, (h - side) / 2, side, side, 0, 0, SIZE, SIZE);
    return c.toDataURL("image/jpeg", 0.86);
  }

  function setPhoto(url) {
    data.value = url || "";
    remove.value = url ? "0" : "1";
    preview.hidden = !url;
    empty.hidden = !!url;
    if (url) preview.src = url; else preview.removeAttribute("src");
    $("photo-clear").hidden = !url;
    frame.dataset.has = url ? "1" : "0";
    if (url) { frame.classList.remove("just-set"); void frame.offsetWidth; frame.classList.add("just-set"); }
  }

  /* ---------- upload ---------- */
  $("photo-upload").addEventListener("click", () => fileInput.click());
  fileInput.addEventListener("change", () => {
    const file = fileInput.files[0];
    fileInput.value = "";
    if (!file) return;
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => { setPhoto(squareJpeg(img, img.naturalWidth, img.naturalHeight)); URL.revokeObjectURL(url); };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      ui.toast({type: "error", title: "That file isn't a picture this browser can open", sub: "Use a JPG or PNG photo."});
    };
    img.src = url;
  });

  $("photo-clear").addEventListener("click", () => setPhoto(""));

  /* ---------- camera ---------- */
  function showMsg(text) { msg.textContent = text; msg.hidden = !text; }

  function stop() {
    if (stream) stream.getTracks().forEach(t => t.stop());
    stream = null;
  }

  async function start(deviceId) {
    stop();
    showMsg("Starting camera…");
    if (!navigator.mediaDevices?.getUserMedia) {
      showMsg("This browser can't use the camera here. Open the dashboard at http://127.0.0.1:5000 in Chrome or Edge.");
      snapBtn.disabled = true;
      return;
    }
    try {
      stream = await navigator.mediaDevices.getUserMedia({
        video: deviceId ? {deviceId: {exact: deviceId}} : {facingMode: "user", width: {ideal: 1280}, height: {ideal: 720}},
        audio: false,
      });
      video.srcObject = stream;
      await video.play();
      showMsg("");
      snapBtn.disabled = false;
      // List cameras (names appear only after permission is given)
      const cams = (await navigator.mediaDevices.enumerateDevices()).filter(d => d.kind === "videoinput");
      const current = stream.getVideoTracks()[0]?.getSettings().deviceId;
      select.innerHTML = cams.map((c, i) => `<option value="${c.deviceId}" ${c.deviceId === current ? "selected" : ""}>${ui.esc(c.label || "Camera " + (i + 1))}</option>`).join("");
      select.hidden = cams.length < 2;
    } catch (e) {
      snapBtn.disabled = true;
      showMsg(e.name === "NotAllowedError"
        ? "Camera access was blocked. Click the camera icon in the browser's address bar, choose Allow, then try again."
        : e.name === "NotFoundError" || e.name === "OverconstrainedError"
          ? "No camera was found. Plug in a webcam, or use Upload instead."
          : e.name === "NotReadableError"
            ? "The camera is being used by another app (e.g. Zoom or the Camera app). Close it and try again."
            : "The camera couldn't start: " + e.message);
    }
  }

  function live(on) {               // switch between live preview and the captured still
    video.hidden = !on; shot.hidden = on;
    snapBtn.hidden = !on; useBtn.hidden = on; retakeBtn.hidden = on;
  }

  $("photo-camera").addEventListener("click", () => { live(true); dlg.showModal(); start(); });
  select.addEventListener("change", () => start(select.value));
  snapBtn.addEventListener("click", () => {
    const w = video.videoWidth, h = video.videoHeight;
    if (!w) return;
    shot.width = w; shot.height = h;
    shot.getContext("2d").drawImage(video, 0, 0, w, h);
    live(false);
  });
  retakeBtn.addEventListener("click", () => live(true));
  useBtn.addEventListener("click", () => {
    setPhoto(squareJpeg(shot, shot.width, shot.height));
    dlg.close();
  });
  $("cam-cancel").addEventListener("click", () => dlg.close());
  dlg.addEventListener("close", stop);       // always turn the camera light off
})();
