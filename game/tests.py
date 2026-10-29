import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Game, Question, Quiz


def mk_game(owner):
    quiz = Quiz.objects.create(owner=owner, title="T")
    Question.objects.create(quiz=quiz, order=1, text="2+2?", option_1="3", option_2="4", correct=2, time_limit=20)
    Question.objects.create(quiz=quiz, order=2, text="1+1?", option_1="2", option_2="5", correct=1, time_limit=20)
    return Game.objects.create(quiz=quiz, host=owner)


class FlowTests(TestCase):
    def setUp(self):
        self.host = User.objects.create_user("host", password="pw-pw-pw-123456")
        self.other = User.objects.create_user("other", password="pw-pw-pw-123456")
        self.game = mk_game(self.host)
        self.hc = Client(); self.hc.login(username="host", password="pw-pw-pw-123456")
        self.pc = Client()

    def act(self, frm):
        return self.hc.post(reverse("host_action", args=[self.game.pin]), json.dumps({"from": frm}), content_type="application/json")

    def answer(self, c, slot):
        return c.post(reverse("play_answer", args=[self.game.pin]), json.dumps({"slot": slot}), content_type="application/json")

    def state(self, c):
        return c.get(reverse("play_state", args=[self.game.pin])).json()

    def test_full_flow_and_no_answer_leak(self):
        self.pc.post(reverse("join", args=[self.game.pin]), {"nickname": "Ann"})
        self.assertEqual(self.state(self.pc)["phase"], "lobby")
        self.act("lobby")
        st = self.state(self.pc)
        self.assertEqual(st["phase"], "question")
        self.assertNotIn("correct", st["question"])  # не утекает до результатов
        self.assertEqual(self.answer(self.pc, 2).status_code, 200)
        self.assertEqual(self.answer(self.pc, 1).status_code, 409)  # повторный ответ
        st = self.state(self.pc)  # единственный игрок ответил -> авто-результаты
        self.assertEqual(st["phase"], "results")
        self.assertTrue(st["question"]["my_correct"])
        self.assertGreaterEqual(st["score"], 500)
        self.act("results"); self.act("question"); self.act("results")
        self.assertEqual(self.state(self.pc)["phase"], "finished")

    def test_late_answer_rejected(self):
        self.pc.post(reverse("join", args=[self.game.pin]), {"nickname": "Bob"})
        self.pc2 = Client(); self.pc2.post(reverse("join", args=[self.game.pin]), {"nickname": "Cat"})
        self.act("lobby")
        Game.objects.filter(pk=self.game.pk).update(question_started=timezone.now() - timedelta(seconds=60))
        self.assertEqual(self.answer(self.pc, 2).status_code, 409)

    def test_bad_input(self):
        self.pc.post(reverse("join", args=[self.game.pin]), {"nickname": "Dan"})
        self.act("lobby")
        for body in ["garbage", "[]", '{"slot": "x"}', '{"slot": 99}', '{"slot": 1e999}']:
            r = self.pc.post(reverse("play_answer", args=[self.game.pin]), body, content_type="application/json")
            self.assertIn(r.status_code, (400, 409), body)

    def test_nickname_rules(self):
        url = reverse("join", args=[self.game.pin])
        self.pc.post(url, {"nickname": "<script>alert(1)</script>"})
        self.assertEqual(self.game.players.count(), 0)
        self.pc.post(url, {"nickname": "Ann"})
        c2 = Client(); c2.post(url, {"nickname": "ann"})  # без учёта регистра
        self.assertEqual(self.game.players.count(), 1)

    def test_cannot_join_after_start(self):
        self.pc.post(reverse("join", args=[self.game.pin]), {"nickname": "Ann"})
        self.act("lobby")
        c = Client(); c.post(reverse("join", args=[self.game.pin]), {"nickname": "Late"})
        self.assertEqual(self.game.players.count(), 1)

    def test_host_isolation(self):
        c = Client(); c.login(username="other", password="pw-pw-pw-123456")
        for name in ("host", "host_state"):
            self.assertEqual(c.get(reverse(name, args=[self.game.pin])).status_code, 404)
        self.assertEqual(c.post(reverse("host_action", args=[self.game.pin]), "{}", content_type="application/json").status_code, 404)
        self.assertEqual(c.get(reverse("quiz_detail", args=[self.game.quiz.pk])).status_code, 404)
        self.assertEqual(c.post(reverse("quiz_delete", args=[self.game.quiz.pk])).status_code, 404)
        self.assertEqual(Client().get(reverse("host", args=[self.game.pin])).status_code, 302)

    def test_player_cannot_use_other_session(self):
        self.assertEqual(self.state(Client())["error"], "not joined")
        self.assertEqual(self.answer(Client(), 1).status_code, 403)

    def test_csrf_enforced(self):
        c = Client(enforce_csrf_checks=True); c.login(username="host", password="pw-pw-pw-123456")
        self.assertEqual(c.post(reverse("quiz_delete", args=[self.game.quiz.pk])).status_code, 403)
        self.assertEqual(c.post(reverse("host_action", args=[self.game.pin]), "{}", content_type="application/json").status_code, 403)

    def test_headers_and_qr(self):
        r = self.hc.get(reverse("host", args=[self.game.pin]))
        self.assertIn("script-src 'self'", r["Content-Security-Policy"])
        self.assertNotIn("unsafe-inline", r["Content-Security-Policy"])
        self.assertContains(r, "data:image/svg+xml;base64,")
        self.assertEqual(r["X-Frame-Options"], "DENY")

    def test_xss_escaped_in_templates(self):
        Quiz.objects.create(owner=self.host, title="<b>x</b>")
        r = self.hc.get(reverse("dashboard"))
        self.assertNotContains(r, "<b>x</b>")

    def test_login_throttle(self):
        from django.core.cache import cache
        cache.clear()
        codes = [Client().post(reverse("login"), {"username": "host", "password": "bad"}).status_code for _ in range(17)]
        self.assertEqual(codes[-1], 429)
        cache.clear()
