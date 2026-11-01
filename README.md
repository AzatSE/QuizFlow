# QuizFlow (Django)

QuizFlow — космическая площадка живых викторин: ведущий создаёт квиз и запускает игру, на экране показывается **QR-код и PIN**,
игроки сканируют QR с телефона, вводят ник и отвечают. Очки зависят от скорости ответа (500–1000).
Без WebSocket/Redis — клиенты опрашивают сервер раз в секунду, поэтому запускается одной командой.

## Быстрый старт

```bash
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
export DJANGO_DEBUG=1
# чтобы телефон открыл QR: укажите IP компьютера в локальной сети
export DJANGO_ALLOWED_HOSTS=localhost,192.168.1.50
python manage.py migrate
python manage.py runserver 0.0.0.0:8000
```

1. Откройте `http://<IP>:8000/`, зарегистрируйтесь («Создать квиз»), создайте квиз и добавьте вопросы.
   На странице квиза можно раскрыть «Вставить вопросы из текста», вставить блоки AI-формата и нажать «Разобрать и проверить». Импорт сначала показывает редактируемый предпросмотр и не сохраняет вопросы, пока вы не нажмёте «Подтвердить и создать вопросы».
2. «Запустить игру» → покажите экран хоста на проекторе (откройте его по IP, а не по localhost, иначе QR будет вести на localhost).
3. Игроки сканируют QR → ник → ждут старта. Ведущий жмёт «Начать», затем «Показать результаты» / «Дальше».

Вопрос закрывается сам, когда истекло время или ответили все.

Формат импорта: каждый блок начинается с `[вопрос]`, от 2 до 4 вариантов задаются строками `[ответ]`, а `[правильный ответ]` повторяет текст одного из этих вариантов и отмечает его как правильный. Между блоками можно оставлять пустые строки; максимум 50 вопросов за раз. Короткая вводная фраза перед первым вопросом игнорируется.

```text
[вопрос] Какая команда создает проект?
[ответ] python manage.py startproject
[ответ] django-admin startproject
[ответ] django-admin startapp
[правильный ответ] django-admin startproject
```

## Продакшен

```bash
cp .env.example .env   # заполните DJANGO_SECRET_KEY, ALLOWED_HOSTS, PUBLIC_BASE_URL
python manage.py migrate
python manage.py collectstatic --noinput
gunicorn config.wsgi --bind 127.0.0.1:8000 --workers 2
```
Ставьте за nginx/Caddy с HTTPS и `DJANGO_TRUST_PROXY=1` только если proxy удаляет клиентский `X-Forwarded-Proto` и выставляет свой. Для IP rate-limit приложение всё равно использует socket peer (`REMOTE_ADDR`), а не `X-Forwarded-For`: клиенты за одним proxy могут делить общий лимит. Периодически запускайте
`python manage.py cleanup_games` (cron) — удаляет игры старше суток.
Для нескольких воркеров/серверов замените кэш на Redis (иначе rate-limit считается отдельно в каждом процессе)
и SQLite на PostgreSQL.

Тесты: `python manage.py test`. Отчёт по безопасности: [SECURITY_AUDIT.md](SECURITY_AUDIT.md).

## Деплой на Railway

1. Залейте репозиторий на GitHub (`.env` и `db.sqlite3` уже в `.gitignore`).
2. Railway → **New Project → Deploy from GitHub repo** → выберите репозиторий.
3. В том же проекте: **+ New → Database → PostgreSQL**.
4. В сервисе приложения → **Variables**:
   - `DJANGO_SECRET_KEY` = длинная случайная строка (`python -c "import secrets;print(secrets.token_urlsafe(60))"`)
   - `DATABASE_URL` = `${{Postgres.DATABASE_URL}}` (ссылка на переменную сервиса Postgres)
   - (по желанию) `ALLOW_SIGNUP=0`, когда создадите нужные аккаунты
5. **Settings → Networking → Generate Domain**. Домен подхватывается автоматически
   (`RAILWAY_PUBLIC_DOMAIN` → `ALLOWED_HOSTS`, `CSRF_TRUSTED_ORIGINS`, адрес в QR-коде).
6. Старт описан в `Procfile`: миграции → collectstatic → gunicorn (1 воркер × 8 потоков).

Не включайте несколько реплик/воркеров без Redis-кэша: лимиты запросов хранятся в памяти процесса.
SQLite на Railway не используйте — файловая система контейнера временная.

## Деплой на Render

1. Залейте репозиторий на GitHub.
2. Render → **New → Blueprint** → выберите репозиторий. Render прочитает `render.yaml`
   и сам создаст веб-сервис и базу PostgreSQL, сгенерирует `DJANGO_SECRET_KEY` и подключит `DATABASE_URL`.
3. Дождитесь окончания сборки (`build.sh`: зависимости → collectstatic → миграции).
4. Откройте адрес `https://<имя>.onrender.com`. Домен подхватывается автоматически
   (`RENDER_EXTERNAL_HOSTNAME` → `ALLOWED_HOSTS`, CSRF, адрес в QR-коде).

Ручная настройка: Web Service → Build `bash build.sh`, Start
`gunicorn config.wsgi:application --workers 1 --threads 8`, переменные `DJANGO_SECRET_KEY` и `DATABASE_URL`
(Internal Database URL из созданной PostgreSQL).

Бесплатный веб-сервис Render «засыпает» без запросов и просыпается около минуты —
запустите сайт заранее, до начала игры. Условия бесплатной базы смотрите на странице тарифов Render.
