(function () {
  // The TTS provider caps how much text one request can synthesize, so the backend
  // hands back pre-split chunks. Each chunk is fetched as its own MP3 and the
  // clips are played back to back.
  function createState(viewer) {
    return {
      videoid: viewer.dataset.videoid,
      extractUrl: viewer.dataset.extractUrl,
      speakUrl: viewer.dataset.speakUrl,
      chunks: [],
      index: 0,
      audioUrls: {},
      inflight: {},
      started: false,
      stopping: false,
    };
  }

  function setStatus(viewer, message) {
    viewer.querySelector(".doc-status").textContent = message;
  }

  // Letter-size pages stay legible up to about this factor before text gets
  // uncomfortably large on wide monitors.
  var FULLSCREEN_MAX_SCALE = 1.75;

  // PDF pages carry absolute point dimensions, so scale each one down to the
  // width of the content column instead of forcing horizontal scrolling.
  // In full screen, pages may also scale up to fill the wider view.
  function fitPages(body) {
    var style = window.getComputedStyle(body);
    var available =
      body.clientWidth -
      parseFloat(style.paddingLeft || 0) -
      parseFloat(style.paddingRight || 0);
    if (!(available > 0)) return;
    var viewer = body.closest(".doc-viewer");
    var maxScale = viewer && viewer.classList.contains("is-fullscreen") ? FULLSCREEN_MAX_SCALE : 1;

    body.querySelectorAll(".pdf-page").forEach(function (page) {
      var canvas = page.querySelector(".pdf-page-canvas");
      if (!canvas) return;

      canvas.style.transform = "";
      page.style.width = "";
      page.style.height = "";

      var width = canvas.offsetWidth;
      var height = canvas.offsetHeight;
      if (!width || !height) return;

      var scale = Math.min(maxScale, available / width);
      if (scale !== 1) {
        canvas.style.transform = "scale(" + scale + ")";
      }
      page.style.width = Math.ceil(width * scale) + "px";
      page.style.height = Math.ceil(height * scale) + "px";
    });
  }

  function watchResize(body) {
    var timer = null;
    window.addEventListener("resize", function () {
      window.clearTimeout(timer);
      timer = window.setTimeout(function () {
        fitPages(body);
      }, 150);
    });
  }

  function nativeFullscreenElement() {
    return document.fullscreenElement || document.webkitFullscreenElement || null;
  }

  // Uses the browser Fullscreen API where available; iPhone Safari lacks it for
  // non-video elements, so there the viewer expands to cover the page instead.
  function setupFullscreen(viewer, body) {
    var btn = viewer.querySelector(".doc-fullscreen-btn");
    if (!btn) return;
    var canNative = !!(viewer.requestFullscreen || viewer.webkitRequestFullscreen);

    function applyState(active) {
      // Keep the reader at the same spot in the document across the resize.
      var ratio = body.scrollHeight > 0 ? body.scrollTop / body.scrollHeight : 0;
      viewer.classList.toggle("is-fullscreen", active);
      document.documentElement.classList.toggle("doc-fullscreen-lock", active && !canNative);
      btn.textContent = active ? "Exit full screen" : "Full screen";
      btn.setAttribute("aria-pressed", active ? "true" : "false");
      fitPages(body);
      body.scrollTop = ratio * body.scrollHeight;
    }

    function enter() {
      if (canNative) {
        var request = viewer.requestFullscreen || viewer.webkitRequestFullscreen;
        var result = request.call(viewer);
        if (result && result.catch) {
          result.catch(function () {
            canNative = false;
            applyState(true);
          });
        }
        return;
      }
      applyState(true);
    }

    function exit() {
      if (nativeFullscreenElement() === viewer) {
        (document.exitFullscreen || document.webkitExitFullscreen).call(document);
        return;
      }
      applyState(false);
    }

    btn.addEventListener("click", function () {
      if (viewer.classList.contains("is-fullscreen")) exit();
      else enter();
    });

    ["fullscreenchange", "webkitfullscreenchange"].forEach(function (evt) {
      document.addEventListener(evt, function () {
        var active = nativeFullscreenElement() === viewer;
        if (active !== viewer.classList.contains("is-fullscreen")) applyState(active);
      });
    });

    document.addEventListener("keydown", function (e) {
      if (e.key === "Escape" && viewer.classList.contains("is-fullscreen") && !nativeFullscreenElement()) {
        applyState(false);
      }
    });
  }

  function progressLabel(state) {
    if (state.chunks.length <= 1) return "Reading aloud…";
    return "Reading part " + (state.index + 1) + " of " + state.chunks.length;
  }

  function releaseAudio(state) {
    Object.keys(state.audioUrls).forEach(function (key) {
      URL.revokeObjectURL(state.audioUrls[key]);
    });
    state.audioUrls = {};
    state.inflight = {};
  }

  // Synthesize one chunk, memoized so replays and prefetch never re-request.
  function fetchChunk(state, index) {
    if (index < 0 || index >= state.chunks.length) {
      return Promise.reject(new Error("No such chunk"));
    }
    if (state.audioUrls[index]) {
      return Promise.resolve(state.audioUrls[index]);
    }
    if (state.inflight[index]) {
      return state.inflight[index];
    }

    var request = fetch(state.speakUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: state.chunks[index] }),
    })
      .then(function (res) {
        if (!res.ok) {
          return res
            .json()
            .catch(function () {
              return {};
            })
            .then(function (data) {
              throw new Error(data.error || "Speech synthesis failed");
            });
        }
        return res.blob();
      })
      .then(function (blob) {
        var url = URL.createObjectURL(blob);
        state.audioUrls[index] = url;
        delete state.inflight[index];
        return url;
      })
      .catch(function (err) {
        delete state.inflight[index];
        throw err;
      });

    state.inflight[index] = request;
    return request;
  }

  function prefetchNext(state, index) {
    if (index + 1 < state.chunks.length) {
      fetchChunk(state, index + 1).catch(function () {
        /* surfaced when that chunk is reached */
      });
    }
  }

  function playIndex(viewer, state, audio, index) {
    state.index = index;
    setStatus(viewer, state.chunks.length > 1 ? "Preparing " + progressLabel(state).toLowerCase() + "…" : "Preparing audio…");

    return fetchChunk(state, index)
      .then(function (url) {
        if (state.stopping) return;
        audio.hidden = false;
        audio.src = url;
        prefetchNext(state, index);
        return audio.play();
      })
      .then(function () {
        if (state.stopping) return;
        setStatus(viewer, progressLabel(state));
      })
      .catch(function (err) {
        if (state.stopping || (err && err.name === "AbortError")) return;
        setStatus(viewer, err.message || "Could not play audio.");
        resetControls(viewer, state);
      });
  }

  function resetControls(viewer, state) {
    var playBtn = viewer.querySelector(".doc-play-btn");
    var stopBtn = viewer.querySelector(".doc-stop-btn");
    state.started = false;
    state.index = 0;
    playBtn.hidden = false;
    playBtn.disabled = state.chunks.length === 0;
    playBtn.textContent = "Read aloud";
    stopBtn.hidden = true;
  }

  function stopPlayback(viewer, state, audio) {
    state.stopping = true;
    audio.pause();
    audio.removeAttribute("src");
    audio.load();
    audio.hidden = true;
    state.stopping = false;
    resetControls(viewer, state);
    setStatus(
      viewer,
      state.chunks.length
        ? "Ready to read " + state.chunks.length + " part" + (state.chunks.length === 1 ? "" : "s") + "."
        : "No readable text in this document."
    );
  }

  function initViewer(viewer) {
    var state = createState(viewer);
    var body = viewer.querySelector(".doc-body");
    var audio = viewer.querySelector(".doc-audio");
    var playBtn = viewer.querySelector(".doc-play-btn");
    var stopBtn = viewer.querySelector(".doc-stop-btn");

    if (!state.extractUrl || !state.videoid) return;

    setupFullscreen(viewer, body);

    fetch(state.extractUrl, {
      method: "POST",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ videoid: Number(state.videoid) }),
    })
      .then(function (res) {
        return res.json().then(function (data) {
          return { ok: res.ok, data: data };
        });
      })
      .then(function (result) {
        if (!result.ok) {
          throw new Error(result.data.error || "Could not load document");
        }
        body.innerHTML = result.data.html || "";
        body.setAttribute("aria-busy", "false");
        fitPages(body);
        watchResize(body);
        state.chunks = result.data.chunks || [];

        if (!state.chunks.length) {
          setStatus(viewer, "No readable text in this document.");
          return;
        }
        playBtn.disabled = false;
        setStatus(
          viewer,
          "Ready to read " + state.chunks.length + " part" + (state.chunks.length === 1 ? "" : "s") + "."
        );
      })
      .catch(function (err) {
        body.setAttribute("aria-busy", "false");
        body.innerHTML = "";
        setStatus(viewer, err.message || "Could not load document.");
      });

    playBtn.addEventListener("click", function () {
      if (!state.chunks.length) return;

      // Resume a paused document rather than re-synthesizing it.
      if (state.started && audio.paused) {
        audio.play();
        playBtn.textContent = "Pause";
        setStatus(viewer, progressLabel(state));
        return;
      }
      if (state.started && !audio.paused) {
        audio.pause();
        playBtn.textContent = "Resume";
        setStatus(viewer, "Paused · " + progressLabel(state).toLowerCase());
        return;
      }

      state.started = true;
      playBtn.textContent = "Pause";
      stopBtn.hidden = false;
      playIndex(viewer, state, audio, 0);
    });

    stopBtn.addEventListener("click", function () {
      stopPlayback(viewer, state, audio);
    });
    audio.addEventListener("ended", function () {
      if (!state.started) return;
      if (state.index + 1 < state.chunks.length) {
        playIndex(viewer, state, audio, state.index + 1);
        return;
      }
      resetControls(viewer, state);
      setStatus(viewer, "Finished reading.");
    });

    audio.addEventListener("pause", function () {
      if (state.started && !audio.ended && !state.stopping) {
        playBtn.textContent = "Resume";
      }
    });

    audio.addEventListener("play", function () {
      if (state.started) {
        playBtn.textContent = "Pause";
      }
    });

    window.addEventListener("pagehide", function () {
      releaseAudio(state);
    });
  }

  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll(".doc-viewer").forEach(initViewer);
  });
})();
