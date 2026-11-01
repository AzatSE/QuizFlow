import json
from datetime import timedelta

from django.contrib.auth.models import User
from django.test import Client, TestCase, override_settings
from django.urls import reverse
from django.utils import timezone

from .models import Game, Question, Quiz
from .text_import import MAX_IMPORT_CHARS, parse_question_text


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

    def test_homepage_shows_redesigned_branding(self):
        response = self.pc.get(reverse("home"))
        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'class="hero-logo"')
        self.assertContains(response, "Выбирай ответ.")
        self.assertContains(response, "Набирай баллы.")
        self.assertContains(response, "Побеждай!")

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

    @override_settings(TRUST_PROXY=True)
    def test_rate_limit_ip_ignores_untrusted_forwarded_header(self):
        from django.test import RequestFactory
        from .utils import client_ip

        request = RequestFactory().get("/", HTTP_X_FORWARDED_FOR="203.0.113.9")
        request.META["REMOTE_ADDR"] = "192.0.2.10"
        self.assertEqual(client_ip(request), "192.0.2.10")

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


class QuestionTextImportTests(TestCase):
    source = """[вопрос] Какая команда создает проект?
[ответ] python manage.py startproject
[ответ] python manage.py startapp
[правильный ответ] django-admin startproject

[вопрос] Для чего нужен URLconf?
[ответ] Для настройки моделей
[правильный ответ] Для маршрутизации запросов
"""

    def setUp(self):
        self.user = User.objects.create_user("importer", password="pw-pw-pw-123456")
        self.quiz = Quiz.objects.create(owner=self.user, title="Django")
        self.client = Client()
        self.client.login(username="importer", password="pw-pw-pw-123456")
        self.url = reverse("quiz_import", args=[self.quiz.pk])

    def test_parser_maps_correct_answer_to_its_option_slot(self):
        questions, errors = parse_question_text(self.source)
        self.assertEqual(errors, [])
        self.assertEqual(len(questions), 2)
        self.assertEqual(questions[0]["correct"], 3)
        self.assertEqual(questions[0]["option_3"], "django-admin startproject")
        self.assertEqual(questions[1]["correct"], 2)
        self.assertEqual(questions[1]["option_3"], "")

    def test_parser_rejects_ambiguous_or_invalid_blocks_and_oversized_text(self):
        invalid = """[вопрос] Сколько?
[ответ] Один
[ответ] Один
[правильный ответ] Один
[правильный ответ] Два"""
        questions, errors = parse_question_text(invalid)
        self.assertEqual(questions, [])
        self.assertTrue(errors)
        questions, errors = parse_question_text("x" * (MAX_IMPORT_CHARS + 1))
        self.assertEqual(questions, [])
        self.assertIn("слишком большой", errors[0])

    def test_preview_populates_editable_forms_without_creating_questions(self):
        response = self.client.post(self.url, {"action": "preview", "raw_text": self.source})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["import_preview"])
        self.assertContains(response, "Подтвердить и создать вопросы")
        self.assertContains(response, "django-admin startproject")
        self.assertEqual(self.quiz.questions.count(), 0)

    @override_settings(MAX_QUESTIONS_PER_QUIZ=1)
    def test_preview_warns_when_questions_need_to_be_skipped_for_quiz_limit(self):
        response = self.client.post(self.url, {"action": "preview", "raw_text": self.source})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["import_preview"])
        self.assertIn("свободно мест: 1", response.context["import_error"])
        self.assertEqual(self.quiz.questions.count(), 0)

    def test_confirm_creates_only_non_deleted_questions(self):
        data = {
            "action": "create", "import-TOTAL_FORMS": "2", "import-INITIAL_FORMS": "2",
            "import-MIN_NUM_FORMS": "0", "import-MAX_NUM_FORMS": "50",
            "import-0-text": "Какая команда создает проект?",
            "import-0-option_1": "python manage.py startproject",
            "import-0-option_2": "python manage.py startapp",
            "import-0-option_3": "django-admin startproject",
            "import-0-option_4": "", "import-0-correct": "3", "import-0-time_limit": "20",
            "import-1-text": "Не включать",
            "import-1-option_1": "Один", "import-1-option_2": "Два",
            "import-1-option_3": "", "import-1-option_4": "",
            "import-1-correct": "1", "import-1-time_limit": "20", "import-1-DELETE": "on",
        }
        response = self.client.post(self.url, data)
        self.assertRedirects(response, reverse("quiz_detail", args=[self.quiz.pk]))
        self.assertEqual(self.quiz.questions.count(), 1)
        question = self.quiz.questions.get()
        self.assertEqual(question.correct, 3)
        self.assertEqual(question.option_3, "django-admin startproject")

    def test_invalid_preview_and_unauthorized_import_do_not_write(self):
        response = self.client.post(self.url, {"action": "preview", "raw_text": "без метки"})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.context["import_errors"])
        self.assertIsNone(response.context["import_formset"])
        self.assertEqual(self.quiz.questions.count(), 0)

        other = User.objects.create_user("other-importer", password="pw-pw-pw-123456")
        other_client = Client()
        other_client.login(username="other-importer", password="pw-pw-pw-123456")
        self.assertEqual(other_client.post(self.url, {"action": "preview", "raw_text": self.source}).status_code, 404)
        self.assertEqual(self.quiz.questions.count(), 0)

    def test_import_preview_escapes_user_text_and_requires_csrf(self):
        payload = """[вопрос] <img src=x onerror=alert(1)>?
[ответ] Один
[правильный ответ] Два"""
        response = self.client.post(self.url, {"action": "preview", "raw_text": payload})
        self.assertEqual(response.status_code, 200)
        self.assertNotContains(response, "<img src=x onerror=alert(1)>")
        self.assertEqual(self.quiz.questions.count(), 0)

        csrf_client = Client(enforce_csrf_checks=True)
        csrf_client.force_login(self.user)
        self.assertEqual(csrf_client.post(self.url, {"action": "preview", "raw_text": self.source}).status_code, 403)
