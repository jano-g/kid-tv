/* kid-tv web UI – no framework, no build step. */
(function () {
  "use strict";
  var S = (window.KIDTV && window.KIDTV.strings) || {};

  function fmtClock(sec) {
    if (sec == null || sec < 0) return "0:00";
    sec = Math.floor(sec);
    var h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
    return h ? h + ":" + String(m).padStart(2, "0") + ":" + String(s).padStart(2, "0") : m + ":" + String(s).padStart(2, "0");
  }

  // ---- confirm dialogs & rename prompts -----------------------------------
  document.querySelectorAll("form.js-confirm").forEach(function (f) {
    f.addEventListener("submit", function (e) { if (!confirm(f.dataset.confirm || "?")) e.preventDefault(); });
  });
  document.querySelectorAll("form.js-rename").forEach(function (f) {
    f.addEventListener("submit", function (e) {
      var input = f.querySelector("input[name=name]");
      var v = prompt(f.dataset.prompt || "", input.value);
      if (v === null || !v.trim()) { e.preventDefault(); return; }
      input.value = v.trim();
    });
  });

  // ---- remote control buttons ---------------------------------------------
  document.querySelectorAll("[data-action]").forEach(function (b) {
    if (b.classList.contains("js-learn")) return;
    b.addEventListener("click", function () {
      fetch("/api/control", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ action: b.dataset.action, kind: b.dataset.kind || "press" }) })
        .then(function () { refresh(); });
    });
  });

  // ---- live status ---------------------------------------------------------
  function set(el, name, value) { var n = el.querySelector("[data-f=" + name + "]"); if (n) n.textContent = value; }
  function refresh() {
    var boxes = document.querySelectorAll("[data-poll=status]");
    if (!boxes.length) return;
    fetch("/api/status").then(function (r) { return r.json(); }).then(function (st) {
      boxes.forEach(function (box) {
        var title = st.mode === "standby" ? S.standby : (st.episode ? st.episode.title : S.nothing);
        set(box, "title", title);
        var sub = "";
        if (st.channel) { sub = (window.KIDTV.lang === "en" ? "Channel " : "Kanál ") + st.channel.number + " · " + st.channel.name; if (st.episode) sub += " · " + st.episode.index + (window.KIDTV.lang === "en" ? " of " : " z ") + st.channel.episodes; }
        set(box, "sub", sub);
        set(box, "pos", fmtClock(st.position)); set(box, "dur", fmtClock(st.duration));
        var bar = box.querySelector("[data-f=bar]"); if (bar) bar.style.width = (st.duration ? 100 * (st.position || 0) / st.duration : 0) + "%";
        set(box, "watched", fmtClock(st.watched_seconds));
        set(box, "remaining", st.limit_enabled ? S.remaining.replace("{min}", Math.floor((st.remaining_seconds || 0) / 60)) : S.noLimit);
        set(box, "devices", (st.remote_devices || []).join(", ") || "–");
        set(box, "lastkey", st.last_key ? st.last_key.key : "–");
        var ls = document.getElementById("learn-status");
        if (ls) ls.textContent = st.learning ? S.learning + " (" + st.learning + ")" : "";
      });
    }).catch(function () {});
  }
  if (document.querySelector("[data-poll=status]")) { refresh(); setInterval(refresh, 2000); }

  // ---- remote learn ----------------------------------------------------------
  document.querySelectorAll(".js-learn").forEach(function (b) {
    b.addEventListener("click", function () {
      fetch("/remote/learn", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ action: b.dataset.action }) })
        .then(function () { var ls = document.getElementById("learn-status"); if (ls) ls.textContent = S.learning; setTimeout(function () { location.reload(); }, 6000); });
    });
  });

  // ---- uploads ---------------------------------------------------------------
  document.querySelectorAll(".drop").forEach(function (drop) {
    var input = drop.querySelector("input[type=file]");
    var queue = drop.querySelector(".drop__queue");
    var url = drop.dataset.upload;
    var accept = (drop.dataset.accept || "").split(",").map(function (s) { return s.trim().toLowerCase(); });
    drop.addEventListener("click", function (e) { if (e.target === input) return; input.click(); });
    ["dragenter", "dragover"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.add("is-over"); }); });
    ["dragleave", "drop"].forEach(function (ev) { drop.addEventListener(ev, function (e) { e.preventDefault(); drop.classList.remove("is-over"); }); });
    drop.addEventListener("drop", function (e) { handle(e.dataTransfer.files); });
    input.addEventListener("change", function () { handle(input.files); input.value = ""; });

    function handle(files) {
      var list = Array.prototype.slice.call(files);
      var chain = Promise.resolve();
      list.forEach(function (file) {
        var ext = file.name.split(".").pop().toLowerCase();
        var li = document.createElement("li");
        li.innerHTML = '<span class="name"></span><span class="bar"><i></i></span><span class="state"></span>';
        li.querySelector(".name").textContent = file.name;
        queue.appendChild(li);
        if (accept.length && accept.indexOf(ext) < 0) { li.querySelector(".state").textContent = S.failed + " (." + ext + ")"; li.querySelector(".state").className = "state fail"; return; }
        chain = chain.then(function () { return upload(file, li); });
      });
      chain.then(function () { setTimeout(function () { location.reload(); }, 800); });
    }

    function upload(file, li) {
      return new Promise(function (resolve) {
        var xhr = new XMLHttpRequest();
        var fd = new FormData();
        fd.append("file", file, file.name);
        var bar = li.querySelector(".bar i"), state = li.querySelector(".state");
        state.textContent = S.uploading.replace("{name}", "");
        xhr.upload.addEventListener("progress", function (e) { if (e.lengthComputable) bar.style.width = (100 * e.loaded / e.total) + "%"; });
        xhr.addEventListener("load", function () {
          var ok = xhr.status >= 200 && xhr.status < 300;
          state.textContent = ok ? S.done : S.failed; state.className = "state " + (ok ? "ok" : "fail"); bar.style.width = "100%";
          resolve();
        });
        xhr.addEventListener("error", function () { state.textContent = S.failed; state.className = "state fail"; resolve(); });
        xhr.open("POST", url);
        xhr.send(fd);
      });
    }
  });

  // ---- wifi scan -------------------------------------------------------------
  var wifiList = document.getElementById("wifi-list");
  if (wifiList) {
    function scan(rescan) {
      wifiList.innerHTML = '<li class="muted">…</li>';
      fetch("/api/wifi/scan?rescan=" + (rescan ? 1 : 0)).then(function (r) { return r.json(); }).then(function (nets) {
        wifiList.innerHTML = "";
        if (!nets.length) { wifiList.innerHTML = '<li class="muted">–</li>'; return; }
        nets.forEach(function (n) {
          var li = document.createElement("li");
          li.innerHTML = '<span class="ssid"></span>' + (n.secured ? '<span class="lock">🔒</span>' : "") + '<span class="sig"></span>';
          li.querySelector(".ssid").textContent = (n.in_use ? "• " : "") + n.ssid;
          li.querySelector(".sig").textContent = n.signal + " %";
          li.addEventListener("click", function () {
            document.getElementById("wifi-ssid").value = n.ssid;
            var p = document.getElementById("wifi-pass"); p.value = ""; if (n.secured) p.focus();
            document.getElementById("wifi-form").scrollIntoView({ behavior: "smooth", block: "center" });
          });
          wifiList.appendChild(li);
        });
      }).catch(function () { wifiList.innerHTML = '<li class="muted">–</li>'; });
    }
    scan(false);
    var btn = document.getElementById("wifi-scan"); if (btn) btn.addEventListener("click", function () { scan(true); });
  }
})();
