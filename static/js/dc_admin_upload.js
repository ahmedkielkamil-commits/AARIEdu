(function () {
  function statusLabel(data) {
    if (data.status === "processing") {
      if (data.phase === "queued") {
        return "Waiting in queue…";
      }
      return "Transcoding…";
    }
    switch (data.status) {
      case "ready":
        return "Ready for streaming";
      case "failed":
        return "Transcode failed";
      case "cancelled":
        return "Transcode cancelled";
      case "idle":
        return "No upload in progress";
      default:
        return data.status || "";
    }
  }

  function setBusy(panel, busy) {
    var uploadBtn = panel.querySelector(".video-upload-btn");
    var cancelBtn = panel.querySelector(".video-cancel-btn");
    var fileInput = panel.querySelector(".video-file-input");
    var label = panel.querySelector(".video-upload-label");

    if (uploadBtn) {
      uploadBtn.hidden = busy;
    }
    if (cancelBtn) {
      cancelBtn.hidden = !busy;
      cancelBtn.disabled = false;
    }
    if (label) {
      label.style.pointerEvents = busy ? "none" : "";
      label.style.opacity = busy ? "0.6" : "";
    }
    if (!busy && uploadBtn && fileInput) {
      uploadBtn.disabled = !fileInput.files[0];
    }
  }

  function clearPoll(state) {
    if (state.pollTimer) {
      clearTimeout(state.pollTimer);
      state.pollTimer = null;
    }
  }

  function finishBusy(panel, state) {
    clearPoll(state);
    state.uploadAbort = null;
    state.uploading = false;
    setBusy(panel, false);
  }

  function pollStatus(panel, state) {
    var statusEl = panel.querySelector(".video-upload-status");
    var url = panel.dataset.statusUrl;
    if (!url || !statusEl) return;

    fetch(url, { credentials: "same-origin" })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        var text = statusLabel(data);
        if (data.hint) {
          text += " — " + data.hint;
        } else if (data.error) {
          text += " — " + data.error;
        }
        if (data.object_key && data.status === "ready") {
          text += " (" + data.object_key + ")";
          var item = panel.closest(".video-admin-item");
          if (item) {
            var keyInput = item.querySelector('input[name="miniokey"]');
            if (keyInput) {
              keyInput.value = data.object_key;
            }
          }
        }
        statusEl.textContent = text;

        if (data.status === "processing") {
          setBusy(panel, true);
          state.pollTimer = setTimeout(function () {
            pollStatus(panel, state);
          }, 2000);
        } else if (
          data.status === "ready" ||
          data.status === "failed" ||
          data.status === "cancelled"
        ) {
          finishBusy(panel, state);
        }
      })
      .catch(function () {
        statusEl.textContent = "Could not check status.";
        finishBusy(panel, state);
      });
  }

  function cancelTranscode(panel, state) {
    var statusEl = panel.querySelector(".video-upload-status");
    var cancelBtn = panel.querySelector(".video-cancel-btn");
    var cancelUrl = panel.dataset.cancelUrl;

    clearPoll(state);

    if (state.uploadAbort) {
      state.uploadAbort.abort();
      state.uploadAbort = null;
    }

    if (cancelBtn) {
      cancelBtn.disabled = true;
    }
    statusEl.textContent = "Cancelling…";

    if (!cancelUrl) {
      statusEl.textContent = "Transcode cancelled.";
      finishBusy(panel, state);
      return;
    }

    fetch(cancelUrl, {
      method: "POST",
      credentials: "same-origin",
    })
      .then(function (res) {
        return res.json();
      })
      .then(function () {
        statusEl.textContent = "Transcode cancelled.";
        finishBusy(panel, state);
      })
      .catch(function () {
        statusEl.textContent = "Could not cancel transcode.";
        finishBusy(panel, state);
      });
  }

  function initPanel(panel) {
    var fileInput = panel.querySelector(".video-file-input");
    var uploadBtn = panel.querySelector(".video-upload-btn");
    var cancelBtn = panel.querySelector(".video-cancel-btn");
    var filenameEl = panel.querySelector(".video-upload-filename");
    var statusEl = panel.querySelector(".video-upload-status");
    var uploadUrl = panel.dataset.uploadUrl;
    var state = { pollTimer: null, uploadAbort: null, uploading: false };

    if (!fileInput || !uploadBtn || !uploadUrl) return;

    fileInput.addEventListener("change", function () {
      if (state.uploading) return;
      var file = fileInput.files[0];
      uploadBtn.disabled = !file;
      filenameEl.textContent = file ? file.name : "";
    });

    cancelBtn.addEventListener("click", function () {
      cancelTranscode(panel, state);
    });

    uploadBtn.addEventListener("click", function () {
      var file = fileInput.files[0];
      if (!file) return;

      state.uploading = true;
      setBusy(panel, true);
      statusEl.textContent = "Uploading…";

      var formData = new FormData();
      formData.append("video", file);
      state.uploadAbort = new AbortController();

      fetch(uploadUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
        signal: state.uploadAbort.signal,
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          state.uploadAbort = null;
          if (!result.ok) {
            throw new Error(result.data.error || "Upload failed");
          }
          statusEl.textContent = "Processing…";
          fileInput.value = "";
          filenameEl.textContent = "";
          pollStatus(panel, state);
        })
        .catch(function (err) {
          state.uploadAbort = null;
          if (err.name === "AbortError") {
            return;
          }
          statusEl.textContent = err.message || "Upload failed.";
          finishBusy(panel, state);
        });
    });

    pollStatus(panel, state);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".video-upload-panel").forEach(initPanel);
  });
})();
