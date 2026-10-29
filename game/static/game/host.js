(function () {
  "use strict";
  const app = $("#app"); if (!app) return;
  const lobby = $("#p-lobby"), stage = $("#p-stage"), fin = $("#p-finished"), btn = $("#action");
  let state = null, deadline = 0;

  function render(s) {
    state = s;
    lobby.hidden = s.phase !== "lobby";
    stage.hidden = !(s.phase === "question" || s.phase === "results");
    fin.hidden = s.phase !== "finished";
    btn.hidden = s.phase === "finished";
    $("#pcount").textContent = s.players.length;
    $("#players").replaceChildren(...s.players.map((p) => {
      const x = document.createElement("span"); x.textContent = p.nickname; return x;
    }));
    if (s.phase === "lobby") { btn.textContent = "▶ Начать"; btn.disabled = s.players.length === 0; }
    if (s.phase === "finished") $("#final").replaceChildren(...leaderRows(s.players, 10));
    const q = s.question; if (!q) return;
    const res = s.phase === "results";
    $("#qnum").textContent = "Вопрос " + q.index + " / " + s.total;
    $("#qtext").textContent = q.text;
    $("#answered").textContent = "Ответили: " + q.answered + " / " + s.players.length;
    deadline = performance.now() + q.time_left * 1000;
    $$(".opt").forEach((el) => {
      const slot = Number(el.dataset.slot), o = q.options.find((x) => x.slot === slot);
      el.hidden = !o; if (!o) return;
      $(".t", el).textContent = o.text;
      const n = $(".n", el); n.hidden = !res; if (res) n.textContent = String(q.counts[slot] || 0);
      el.classList.toggle("right", res && slot === q.correct);
      el.classList.toggle("dim", res && slot !== q.correct);
    });
    $("#timer").hidden = res;
    $("#board").hidden = !res;
    if (res) {
      $("#board").replaceChildren(...leaderRows(s.players, 5));
      btn.textContent = q.index < s.total ? "Дальше ➜" : "Финал 🏆";
    } else if (s.phase === "question") btn.textContent = "Показать результаты";
  }

  setInterval(() => {
    if (state && state.phase === "question") $("#timer").textContent = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
  }, 200);

  btn.addEventListener("click", async () => {
    if (!state) return;
    btn.disabled = true;
    const r = await post(app.dataset.actionUrl, { from: state.phase });
    if (r.data && r.data.phase) render(r.data);
    btn.disabled = false;
  });
  poll(app.dataset.stateUrl, render, 1000);
})();
