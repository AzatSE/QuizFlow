(function () {
  "use strict";
  const app = $("#app"); if (!app) return;
  const P = { wait: $("#p-wait"), answer: $("#p-answer"), result: $("#p-result"), fin: $("#p-finished") };
  let deadline = 0, phase = "", locked = false, lastQ = 0;
  const show = (k) => Object.keys(P).forEach((n) => { P[n].hidden = n !== k; });

  function render(s) {
    phase = s.phase;
    $("#me").textContent = s.nickname; $("#score").textContent = "Очки: " + s.score;
    const q = s.question;
    if (s.phase === "lobby") { show("wait"); $("#wait-msg").textContent = "Вы в игре! Ждём начала…"; }
    else if (s.phase === "finished") { show("fin"); $("#fin-rank").textContent = s.rank + " место из " + s.players; }
    else if (q && s.phase === "question") {
      if (q.index !== lastQ) { lastQ = q.index; locked = false; }
      if (q.answered || locked) { show("wait"); $("#wait-msg").textContent = "Ответ принят! Ждём остальных…"; return; }
      show("answer");
      $("#qtext").textContent = q.text;
      deadline = performance.now() + q.time_left * 1000;
      $$(".abtn").forEach((b) => {
        const o = q.options.find((x) => x.slot === Number(b.dataset.slot));
        b.hidden = !o; b.textContent = o ? o.text : "";
      });
    } else if (q && s.phase === "results") {
      show("result");
      $("#res-title").textContent = q.answered ? (q.my_correct ? "✅ Верно!" : "❌ Неверно") : "⏰ Время вышло";
      $("#res-points").textContent = "+" + q.my_points;
      $("#res-rank").textContent = "Вы на " + s.rank + " месте";
    }
  }

  setInterval(() => {
    if (phase === "question") $("#timer").textContent = Math.max(0, Math.ceil((deadline - performance.now()) / 1000));
  }, 200);

  $$(".abtn").forEach((b) => b.addEventListener("click", async () => {
    if (locked) return;
    locked = true; show("wait"); $("#wait-msg").textContent = "Отправляем ответ…";
    const r = await post(app.dataset.answerUrl, { slot: Number(b.dataset.slot) });
    if (!r.ok && r.status !== 409) locked = false;
  }));
  poll(app.dataset.stateUrl, render, 1000);
})();
