(() => {
  "use strict";

  const $ = (s) => document.getElementById(s);
  const AUTO_MS = 650;
  const LETTERS = "ABCDEFGH";

  // ---------- Lưu trữ (an toàn khi trình duyệt chặn localStorage) ----------
  const store = {
    get(k, d) { try { const v = localStorage.getItem("lsq:" + k); return v == null ? d : JSON.parse(v); } catch { return d; } },
    set(k, v) { try { localStorage.setItem("lsq:" + k, JSON.stringify(v)); } catch { /* bỏ qua */ } },
    del(k) { try { localStorage.removeItem("lsq:" + k); } catch { /* bỏ qua */ } },
  };

  let lessons = [];        // [{id,title,subtitle,questions:[...]}]
  const Q = {};            // id -> câu hỏi (kèm lessonTitle)
  const settings = Object.assign({ shuffleQ: true, shuffleA: true, auto: true, limit: 0 }, store.get("settings", {}));
  let selected = new Set(store.get("selected", []));
  let stats = store.get("stats", {});   // id -> [số lần đúng, số lần sai, lần cuối đúng? 1/0]
  let S = null;            // phiên đang làm
  let state = "idle";      // ask | answered
  let autoTimer = 0;

  // ---------- Tiện ích ----------
  function shuffle(a) {
    for (let i = a.length - 1; i > 0; i--) {
      const j = (Math.random() * (i + 1)) | 0;
      [a[i], a[j]] = [a[j], a[i]];
    }
    return a;
  }
  // Không xáo đáp án nếu có phương án tham chiếu tới phương án khác ("Cả A và B", "Tất cả đều đúng"...)
  const NO_SHUFFLE = /(tất cả|cả\s+(ba|bốn|hai|3|4|2)\b|các\s+(ý|đáp án|phương án)\s+trên|đều\s+(đúng|sai)|\b[A-D]\s*(và|,|&)\s*[A-D]\b|cả\s+[A-D]\b|không\s+có\s+(ý|đáp án|phương án))/i;
  const canShuffle = (q) => !q.o.some((t) => NO_SHUFFLE.test(t));
  const usable = (q) => q.a !== null && q.a !== undefined && q.o.length >= 2;
  const isWeak = (id) => { const s = stats[id]; return !!s && (s[2] === 0 || s[1] > s[0]); };
  const isKnown = (id) => { const s = stats[id]; return !!s && s[2] === 1; };
  const fmtTime = (ms) => { const s = Math.round(ms / 1000); return Math.floor(s / 60) + ":" + String(s % 60).padStart(2, "0"); };
  const el = (tag, cls, text) => { const e = document.createElement(tag); if (cls) e.className = cls; if (text != null) e.textContent = text; return e; };
  const checkSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>';
  const xSvg = '<svg viewBox="0 0 24 24" width="16" height="16" fill="none" stroke="currentColor" stroke-width="3.2" stroke-linecap="round"><path d="M18 6 6 18M6 6l12 12"/></svg>';
  const playSvg = '<svg viewBox="0 0 24 24" width="18" height="18" fill="currentColor"><path d="M8 5.5v13a1 1 0 0 0 1.5.86l10.5-6.5a1 1 0 0 0 0-1.72L9.5 4.64A1 1 0 0 0 8 5.5Z"/></svg>';

  // ---------- Điều hướng (nút Back trên điện thoại) ----------
  function show(view) {
    for (const v of ["home", "quiz", "result"]) $(v).hidden = v !== view;
    window.scrollTo(0, 0);
  }
  window.addEventListener("popstate", () => {
    if (!$("quiz").hidden || !$("result").hidden) { clearTimeout(autoTimer); goHome(false); }
  });

  // ---------- Tải dữ liệu ----------
  fetch("questions.json", { cache: "no-cache" })
    .then((r) => r.json())
    .then(init)
    .catch(() => { $("heroSub").textContent = "Không tải được câu hỏi. Kiểm tra kết nối mạng rồi thử lại."; });

  function init(data) {
    lessons = (data.lessons || []).map((l) => ({ ...l, questions: l.questions.filter(usable) }));
    for (const l of lessons) for (const q of l.questions) Q[q.id] = Object.assign(q, { lesson: l.id, lessonTitle: l.title });
    selected = new Set([...selected].filter((id) => lessons.some((l) => l.id === id)));
    if (!selected.size) lessons.forEach((l) => selected.add(l.id));
    $("demoNote").hidden = !data.demo;
    const total = Object.keys(Q).length;
    $("heroSub").textContent = `${lessons.length} bài · ${total} câu hỏi`;
    $("allCount").textContent = `${total} câu · ${lessons.length} bài`;
    bindSettings();
    renderHome();
    if ("serviceWorker" in navigator && location.protocol === "https:") navigator.serviceWorker.register("sw.js").catch(() => {});
  }

  // ---------- Trang chủ ----------
  function renderHome() {
    const list = $("lessonList");
    list.textContent = "";
    for (const l of lessons) {
      const n = l.questions.length;
      const known = l.questions.filter((q) => isKnown(q.id)).length;
      const card = el("div", "lesson");
      card.setAttribute("role", "checkbox");
      card.setAttribute("tabindex", "0");
      card.setAttribute("aria-checked", selected.has(l.id));
      const check = el("span", "check"); check.innerHTML = checkSvg;
      const info = el("span", "info");
      info.append(el("span", "ttl", l.title));
      if (l.subtitle) info.append(el("span", "desc", l.subtitle));
      const meta = el("span", "meta");
      const bar = el("span", "bar"); const fill = el("i"); fill.style.width = (n ? (known / n) * 100 : 0) + "%"; bar.append(fill);
      meta.append(el("span", null, `${n} câu`), bar, el("span", null, `${known}/${n}`));
      info.append(meta);
      const go = el("button", "go"); go.innerHTML = playSvg; go.setAttribute("aria-label", "Ôn riêng " + l.title);
      go.addEventListener("click", (e) => { e.stopPropagation(); startSession([l.id], l.title); });
      card.append(check, info, go);
      const toggle = () => {
        selected.has(l.id) ? selected.delete(l.id) : selected.add(l.id);
        store.set("selected", [...selected]);
        renderHome();
      };
      card.addEventListener("click", toggle);
      card.addEventListener("keydown", (e) => { if (e.key === " " || e.key === "Enter") { e.preventDefault(); toggle(); } });
      list.append(card);
    }

    const all = Object.keys(Q);
    const known = all.filter(isKnown).length;
    $("overall").hidden = !all.length;
    $("overallText").textContent = `${known}/${all.length} câu`;
    $("overallBar").style.width = (all.length ? (known / all.length) * 100 : 0) + "%";

    const weak = all.filter(isWeak).length;
    $("startWeak").disabled = !weak;
    $("weakCount").textContent = weak ? `${weak} câu cần ôn lại` : "Chưa có câu sai";

    $("toggleAll").textContent = selected.size === lessons.length ? "Bỏ chọn" : "Chọn tất cả";
    const count = lessons.filter((l) => selected.has(l.id)).reduce((s, l) => s + l.questions.length, 0);
    const take = settings.limit ? Math.min(settings.limit, count) : count;
    $("startBtn").disabled = !count;
    $("startBtn").textContent = !count ? "Chọn ít nhất 1 bài"
      : `Bắt đầu · ${take} câu` + (selected.size > 1 ? ` (${selected.size} bài)` : "");

    const saved = store.get("session", null);
    const ok = saved && saved.ids && saved.ids.every((id) => Q[id]) && saved.idx < saved.ids.length;
    $("resumeCard").hidden = !ok;
    if (ok) {
      $("resumeTitle").textContent = saved.title;
      $("resumeMeta").textContent = `Câu ${saved.idx + 1}/${saved.ids.length} · đúng ${saved.res.filter((r) => r.ok).length}`;
    }
  }

  function bindSettings() {
    const sw = { optShuffleQ: "shuffleQ", optShuffleA: "shuffleA", optAuto: "auto" };
    for (const [id, key] of Object.entries(sw)) {
      $(id).checked = settings[key];
      $(id).addEventListener("change", () => { settings[key] = $(id).checked; store.set("settings", settings); });
    }
    const seg = $("optLimit");
    const paint = () => seg.querySelectorAll("button").forEach((b) => b.setAttribute("aria-checked", +b.dataset.v === settings.limit));
    seg.querySelectorAll("button").forEach((b) => {
      b.setAttribute("role", "radio");
      b.addEventListener("click", () => { settings.limit = +b.dataset.v; store.set("settings", settings); paint(); renderHome(); });
    });
    paint();
  }

  $("toggleAll").addEventListener("click", () => {
    if (selected.size === lessons.length) selected.clear(); else lessons.forEach((l) => selected.add(l.id));
    store.set("selected", [...selected]);
    renderHome();
  });
  $("startBtn").addEventListener("click", () => {
    const ids = lessons.filter((l) => selected.has(l.id)).map((l) => l.id);
    const title = ids.length === 1 ? lessons.find((l) => l.id === ids[0]).title
      : ids.length === lessons.length ? "Ôn tập tổng hợp" : ids.map((id) => lessons.find((l) => l.id === id).title).join(" + ");
    startSession(ids, title);
  });
  $("startAll").addEventListener("click", () => startSession(lessons.map((l) => l.id), "Ôn tập tổng hợp"));
  $("startWeak").addEventListener("click", () => startWithIds(Object.keys(Q).filter(isWeak), "Câu hay sai"));
  $("resumeGo").addEventListener("click", () => {
    S = store.get("session", null);
    if (!S) return;
    history.pushState({ v: "quiz" }, "");
    show("quiz");
    renderQuestion();
  });
  $("resumeDrop").addEventListener("click", () => { store.del("session"); renderHome(); });
  $("resetStats").addEventListener("click", () => {
    if (!confirm("Xoá toàn bộ tiến độ (câu đã thuộc, câu hay sai)?")) return;
    stats = {}; store.del("stats"); store.del("session"); renderHome();
  });

  // ---------- Phiên ôn tập ----------
  function startSession(lessonIds, title) {
    const ids = [];
    for (const l of lessons) if (lessonIds.includes(l.id)) for (const q of l.questions) ids.push(q.id);
    startWithIds(ids, title);
  }

  function startWithIds(ids, title, opts = {}) {
    if (!ids.length) return;
    let list = ids.slice();
    if (settings.shuffleQ || opts.forceShuffle) shuffle(list);
    if (settings.limit && !opts.noLimit) {
      // ưu tiên câu chưa thuộc khi giới hạn số câu
      if (settings.shuffleQ) list.sort((a, b) => isKnown(a) - isKnown(b));
      list = list.slice(0, settings.limit);
      if (settings.shuffleQ) shuffle(list);
    }
    const orders = {};
    for (const id of list) {
      const q = Q[id];
      const perm = q.o.map((_, i) => i);
      orders[id] = settings.shuffleA && canShuffle(q) ? shuffle(perm) : perm;
    }
    S = { title, ids: list, orders, idx: 0, res: [], t0: Date.now(), elapsed: 0, src: ids };
    store.set("session", S);
    if (!$("result").hidden) history.replaceState({ v: "quiz" }, "");
    else if ($("quiz").hidden) history.pushState({ v: "quiz" }, "");
    show("quiz");
    renderQuestion();
  }

  const optBox = $("options");
  const feedback = $("feedback");

  function renderQuestion() {
    clearTimeout(autoTimer);
    state = "ask";
    S.t0 = Date.now();
    const id = S.ids[S.idx];
    const q = Q[id];
    const perm = S.orders[id];
    const okN = S.res.filter((r) => r.ok).length;
    $("okCount").textContent = okN;
    $("badCount").textContent = S.res.length - okN;
    $("counter").textContent = `${S.idx + 1}/${S.ids.length}`;
    $("progBar").style.width = (S.idx / S.ids.length) * 100 + "%";
    $("qLesson").textContent = q.lessonTitle;
    $("qLesson").hidden = lessons.length < 2;
    $("qText").textContent = q.q;

    optBox.textContent = "";
    perm.forEach((orig, i) => {
      const b = el("button", "opt");
      b.dataset.i = i;
      b.append(el("span", "k", LETTERS[i]), el("span", "t", q.o[orig]), el("span", "s"));
      optBox.append(b);
    });
    const card = $("qcard");
    card.classList.remove("fade"); optBox.classList.remove("fade");
    void card.offsetWidth;
    card.classList.add("fade"); optBox.classList.add("fade");
    feedback.className = "feedback";
  }

  optBox.addEventListener("click", (e) => {
    const b = e.target.closest(".opt");
    if (b) answer(+b.dataset.i);
  });

  function answer(i) {
    if (state !== "ask") return;
    const id = S.ids[S.idx];
    const q = Q[id];
    const perm = S.orders[id];
    if (i >= perm.length) return;
    state = "answered";
    const chosen = perm[i];
    const ok = chosen === q.a;
    S.res.push({ id, c: chosen, ok });
    S.elapsed += Date.now() - S.t0;
    const s = stats[id] || [0, 0, 0];
    s[ok ? 0 : 1]++; s[2] = ok ? 1 : 0;
    stats[id] = s;
    store.set("stats", stats);
    store.set("session", { ...S, idx: S.idx + 1 });

    const btns = optBox.children;
    for (let k = 0; k < btns.length; k++) {
      const b = btns[k];
      b.disabled = true;
      if (perm[k] === q.a) {
        b.classList.add("correct");
        b.querySelector(".k").innerHTML = checkSvg;
        if (!ok) b.querySelector(".s").textContent = "Đáp án đúng";
      } else if (k === i) {
        b.classList.add("wrong");
        b.querySelector(".k").innerHTML = xSvg;
        b.querySelector(".s").textContent = "Bạn chọn";
      } else {
        b.classList.add("dim");
      }
    }
    const okN = S.res.filter((r) => r.ok).length;
    $("okCount").textContent = okN;
    $("badCount").textContent = S.res.length - okN;
    $("progBar").style.width = ((S.idx + 1) / S.ids.length) * 100 + "%";

    $("fbIcon").innerHTML = ok ? checkSvg : xSvg;
    $("fbText").textContent = ok ? pick(PRAISE) : pick(ENCOURAGE);
    feedback.className = "feedback show " + (ok ? "ok" : "bad");
    if (ok && settings.auto) {
      feedback.style.setProperty("--auto-ms", AUTO_MS + "ms");
      feedback.classList.add("auto");
      autoTimer = setTimeout(next, AUTO_MS);
    } else {
      if (!ok && navigator.vibrate) navigator.vibrate(60);
      $("nextBtn").focus({ preventScroll: true });
    }
  }

  const PRAISE = ["Chính xác!", "Tuyệt vời!", "Đúng rồi!", "Giỏi lắm!", "Chuẩn luôn!"];
  const ENCOURAGE = ["Chưa đúng – xem lại đáp án nhé", "Sai rồi, ghi nhớ đáp án đúng nhé", "Chưa chính xác, cố lên!"];
  const pick = (a) => a[(Math.random() * a.length) | 0];

  function next() {
    clearTimeout(autoTimer);
    if (state !== "answered") return;
    S.idx++;
    if (S.idx >= S.ids.length) return finish();
    renderQuestion();
  }
  $("nextBtn").addEventListener("click", next);
  $("quitBtn").addEventListener("click", () => history.back());

  document.addEventListener("keydown", (e) => {
    if ($("quiz").hidden || e.ctrlKey || e.metaKey || e.altKey) return;
    const k = e.key.toUpperCase();
    if (state === "ask") {
      let i = "1234567".indexOf(k);
      if (i < 0) i = LETTERS.indexOf(k);
      if (i >= 0 && k.length === 1) { e.preventDefault(); answer(i); }
    } else if (state === "answered" && (k === "ENTER" || k === " " || k === "ARROWRIGHT")) {
      e.preventDefault(); next();
    }
  });

  // ---------- Kết quả ----------
  function finish() {
    state = "idle";
    store.del("session");
    const total = S.res.length;
    const okN = S.res.filter((r) => r.ok).length;
    const wrong = S.res.filter((r) => !r.ok);
    const pct = total ? Math.round((okN / total) * 100) : 0;
    history.replaceState({ v: "result" }, "");
    show("result");

    $("pct").textContent = pct + "%";
    const fg = $("ringFg");
    fg.style.stroke = pct >= 80 ? "var(--ok)" : pct >= 50 ? "#f5a524" : "var(--bad)";
    fg.style.strokeDashoffset = 326.7;
    requestAnimationFrame(() => requestAnimationFrame(() => { fg.style.strokeDashoffset = 326.7 * (1 - pct / 100); }));
    $("resTitle").textContent = pct === 100 ? "Hoàn hảo! 🎉" : pct >= 80 ? "Rất tốt!" : pct >= 50 ? "Khá ổn, cố thêm chút nữa!" : "Cần ôn thêm nhé!";
    $("resSub").textContent = `${S.title} · đúng ${okN}/${total} câu`;
    $("resOk").textContent = okN;
    $("resBad").textContent = wrong.length;
    $("resTime").textContent = fmtTime(S.elapsed);

    $("retryWrong").hidden = !wrong.length;
    $("retryWrong").textContent = `Ôn lại ${wrong.length} câu sai`;
    $("wrongNum").textContent = wrong.length ? `${wrong.length} câu` : "";

    const list = $("wrongList");
    list.textContent = "";
    if (!wrong.length) {
      list.append(el("div", "perfect card", "Bạn không trả lời sai câu nào. Xuất sắc! 🌟"));
    }
    for (const r of wrong) {
      const q = Q[r.id];
      const c = el("div", "wcard");
      c.append(el("span", "wn", q.lessonTitle + (q.n ? ` · Câu ${q.n}` : "")), el("p", "wq", q.q));
      const y = el("div", "ans yours"); y.append(el("span", "lb", "Bạn chọn"), el("span", "tx", q.o[r.c]));
      const a = el("div", "ans right"); a.append(el("span", "lb", "Đáp án"), el("span", "tx", q.o[q.a]));
      c.append(y, a);
      list.append(c);
    }
    const last = S;
    $("retryWrong").onclick = () => startWithIds(wrong.map((r) => r.id), "Ôn lại câu sai", { noLimit: true, forceShuffle: true });
    $("retryAll").onclick = () => startWithIds(last.src, last.title);
  }

  function goHome(viaHistory = true) {
    clearTimeout(autoTimer);
    state = "idle";
    if (viaHistory && history.state && history.state.v) { history.back(); return; }
    show("home");
    renderHome();
  }
  $("goHome").addEventListener("click", () => goHome());
})();
