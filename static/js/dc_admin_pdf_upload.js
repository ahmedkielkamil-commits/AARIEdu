(function () {
  function shortKey(pdfkey) {
    var parts = String(pdfkey).split("/");
    return parts[parts.length - 1] || pdfkey;
  }

  function render(panel, data) {
    var statusEl = panel.querySelector(".pdf-upload-status");
    var uploadBtn = panel.querySelector(".pdf-upload-btn");
    var removeBtn = panel.querySelector(".pdf-remove-btn");
    var fileInput = panel.querySelector(".pdf-file-input");
    var stored = data && data.status === "stored" && data.pdfkey;

    if (stored) {
      statusEl.textContent = "Document stored (" + shortKey(data.pdfkey) + ")";
    } else {
      statusEl.textContent = "No document uploaded";
    }

    removeBtn.hidden = !stored;
    removeBtn.disabled = false;
    uploadBtn.disabled = !fileInput.files[0];
    uploadBtn.textContent = stored ? "Replace PDF" : "Upload PDF";
  }

  function loadStatus(panel) {
    var url = panel.dataset.statusUrl;
    if (!url) return;

    fetch(url, { credentials: "same-origin" })
      .then(function (res) {
        return res.json();
      })
      .then(function (data) {
        render(panel, data);
      })
      .catch(function () {
        panel.querySelector(".pdf-upload-status").textContent =
          "Could not check document status.";
      });
  }

  function initPanel(panel) {
    var fileInput = panel.querySelector(".pdf-file-input");
    var uploadBtn = panel.querySelector(".pdf-upload-btn");
    var removeBtn = panel.querySelector(".pdf-remove-btn");
    var filenameEl = panel.querySelector(".pdf-upload-filename");
    var statusEl = panel.querySelector(".pdf-upload-status");
    var uploadUrl = panel.dataset.uploadUrl;

    if (!fileInput || !uploadBtn || !uploadUrl) return;

    fileInput.addEventListener("change", function () {
      var file = fileInput.files[0];
      uploadBtn.disabled = !file;
      filenameEl.textContent = file ? file.name : "";
    });

    uploadBtn.addEventListener("click", function () {
      var file = fileInput.files[0];
      if (!file) return;

      uploadBtn.disabled = true;
      removeBtn.disabled = true;
      statusEl.textContent = "Uploading…";

      var formData = new FormData();
      formData.append("pdf", file);

      fetch(uploadUrl, {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      })
        .then(function (res) {
          return res.json().then(function (data) {
            return { ok: res.ok, data: data };
          });
        })
        .then(function (result) {
          if (!result.ok) {
            throw new Error(result.data.error || "Upload failed");
          }
          fileInput.value = "";
          filenameEl.textContent = "";
          render(panel, result.data);
        })
        .catch(function (err) {
          statusEl.textContent = err.message || "Upload failed.";
          uploadBtn.disabled = false;
          removeBtn.disabled = false;
        });
    });

    removeBtn.addEventListener("click", function () {
      if (!window.confirm(panel.dataset.removePrompt || "Remove this lesson PDF?")) return;
      var removeUrl = panel.dataset.removeUrl;
      if (!removeUrl) return;

      removeBtn.disabled = true;
      statusEl.textContent = "Removing…";

      fetch(removeUrl, { method: "POST", credentials: "same-origin" })
        .then(function (res) {
          return res.json();
        })
        .then(function () {
          render(panel, { status: "idle" });
        })
        .catch(function () {
          statusEl.textContent = "Could not remove document.";
          removeBtn.disabled = false;
        });
    });

    loadStatus(panel);
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".pdf-upload-panel").forEach(initPanel);
  });
})();
