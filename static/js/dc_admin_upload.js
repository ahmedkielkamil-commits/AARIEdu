(function () {
  var CHUNK_RETRIES = 3;

  // Proxy error pages (413, 502…) are HTML, not JSON; report the HTTP status instead.
  function readJson(res) {
    return res.text().then(function (text) {
      var data = null;
      try {
        data = text ? JSON.parse(text) : {};
      } catch (e) {
        throw new Error("Server returned HTTP " + res.status + " (" + (res.statusText || "error") + ").");
      }
      if (!res.ok) {
        throw new Error(data.error || "Server returned HTTP " + res.status + ".");
      }
      return data;
    });
  }

  function postJson(url, body, signal) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body || {}),
      signal: signal,
    }).then(readJson);
  }

  function sendChunk(url, blob, signal, attempt) {
    return fetch(url, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/octet-stream" },
      body: blob,
      signal: signal,
    })
      .then(readJson)
      .catch(function (err) {
        if (err.name === "AbortError" || attempt >= CHUNK_RETRIES) {
          throw err;
        }
        return new Promise(function (resolve) {
          setTimeout(resolve, 1500 * attempt);
        }).then(function () {
          return sendChunk(url, blob, signal, attempt + 1);
        });
      });
  }

  function formatMb(bytes) {
    return (bytes / (1024 * 1024)).toFixed(0) + " MB";
  }

  function chunkedUpload(panel, state, file, statusEl) {
    var startUrl = panel.dataset.uploadStartUrl;
    var baseUrl = startUrl.replace(/start$/, "");
    var signal = state.uploadAbort.signal;

    return postJson(startUrl, { filename: file.name, size: file.size }, signal).then(function (session) {
      state.uploadSession = baseUrl + session.upload_id;
      var chunkSize = session.chunk_size;

      function next(offset) {
        if (offset >= file.size) {
          return postJson(state.uploadSession + "/finish", {}, signal);
        }
        var end = Math.min(offset + chunkSize, file.size);
        statusEl.textContent =
          "Uploading… " + Math.floor((offset / file.size) * 100) + "% (" +
          formatMb(offset) + " of " + formatMb(file.size) + ")";
        return sendChunk(
          state.uploadSession + "/chunk?offset=" + offset,
          file.slice(offset, end),
          signal,
          1
        ).then(function () {
          return next(end);
        });
      }

      return next(0);
    });
  }

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
      .then(readJson)
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
    if (state.uploadSession) {
      fetch(state.uploadSession + "/abort", { method: "POST", credentials: "same-origin" });
      state.uploadSession = null;
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
    var state = { pollTimer: null, uploadAbort: null, uploadSession: null, uploading: false };

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

      state.uploadAbort = new AbortController();

      chunkedUpload(panel, state, file, statusEl)
        .then(function () {
          state.uploadAbort = null;
          state.uploadSession = null;
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
          if (state.uploadSession) {
            fetch(state.uploadSession + "/abort", { method: "POST", credentials: "same-origin" });
            state.uploadSession = null;
          }
          statusEl.textContent = "Upload failed: " + (err.message || "unknown error");
          finishBusy(panel, state);
        });
    });

    pollStatus(panel, state);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".video-upload-panel").forEach(initPanel);
  });
})();
