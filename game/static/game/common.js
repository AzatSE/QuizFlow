(function () {
  "use strict";
  window.$ = (s, r) => (r || document).querySelector(s);
  window.$$ = (s, r) => Array.from((r || document).querySelectorAll(s));
  const token = () => document.querySelector('meta[name="csrf-token"]').content;
  window.post = async function (url, body) {
    const r = await fetch(url, {
      method: "POST", credentials: "same-origin",
      headers: { "Content-Type": "application/json", "X-CSRFToken": token() },
      body: JSON.stringify(body || {}),
    });
    let data = null;
    try { data = await r.json(); } catch (e) { /* пустой ответ */ }
    return { ok: r.ok, status: r.status, data: data };
  };
  window.poll = function (url, cb, ms) {
    (async function loop() {
      try {
        const r = await fetch(url, { credentials: "same-origin", cache: "no-store" });
        if (r.ok) cb(await r.json());
      } catch (e) { /* сеть моргнула — пробуем снова */ }
      setTimeout(loop, ms || 1000);
    })();
  };
  // ВАЖНО: пользовательский текст вставляем только через textContent (защита от XSS)
  window.leaderRows = (players, limit) => players.slice(0, limit).map((p) => {
    const li = document.createElement("li");
    const a = document.createElement("span"); a.textContent = p.nickname;
    const b = document.createElement("b"); b.textContent = String(p.score);
    li.append(a, b);
    return li;
  });
})();
