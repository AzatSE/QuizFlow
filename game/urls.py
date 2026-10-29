from django.contrib.auth import views as auth_views
from django.urls import path, register_converter

from . import views


class PinConverter:
    regex = r"\d{6}"

    def to_python(self, v):
        return v

    def to_url(self, v):
        return v


register_converter(PinConverter, "pin")

urlpatterns = [
    path("", views.home, name="home"),
    path("signup/", views.signup, name="signup"),
    path("login/", views.RateLimitedLogin.as_view(), name="login"),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("dashboard/", views.dashboard, name="dashboard"),
    path("quiz/<int:pk>/", views.quiz_detail, name="quiz_detail"),
    path("quiz/<int:pk>/delete/", views.quiz_delete, name="quiz_delete"),
    path("quiz/<int:pk>/start/", views.quiz_start, name="quiz_start"),
    path("quiz/<int:pk>/question/<int:qpk>/delete/", views.question_delete, name="question_delete"),
    path("host/<pin:pin>/", views.host_game, name="host"),
    path("host/<pin:pin>/state/", views.host_state, name="host_state"),
    path("host/<pin:pin>/action/", views.host_action, name="host_action"),
    path("j/<pin:pin>/", views.join, name="join"),
    path("play/<pin:pin>/", views.play, name="play"),
    path("play/<pin:pin>/state/", views.play_state, name="play_state"),
    path("play/<pin:pin>/answer/", views.play_answer, name="play_answer"),
]
