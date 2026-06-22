# 🤖 Серверный бот ежедневного дайджеста

`ai_digest.py` каждое утро: собирает новости (RSS + Telegram через t.me/s/) → делает сводку через LLM (простой язык, наши разделы) → кладёт выпуск в `00_Дайджесты/<дата>.md` → коммитит в репозиторий → шлёт в ваш Telegram-бот.

Все секреты — только в `_bot/.env` на сервере (он в `.gitignore`, в репозиторий не попадает).

## Установка (один раз)

**1. Клонировать репозиторий на сервере**
```
git clone https://github.com/ivanqwerty35725-collab/ai-knowledge.git
cd ai-knowledge
```

**2. Доступ git на запись (чтобы сервер коммитил выпуски)** — рекомендуется SSH deploy key:
```
ssh-keygen -t ed25519 -f ~/.ssh/ai_knowledge -N ""
cat ~/.ssh/ai_knowledge.pub   # добавить в GitHub: репозиторий → Settings → Deploy keys → Add key → ✔ Allow write access
git remote set-url origin git@github.com:ivanqwerty35725-collab/ai-knowledge.git
git config user.name "AI Digest Bot"
git config user.email "bot@local"
```
*(SSH-ключ не передаётся в чат — он живёт на сервере. Альтернатива — fine-grained PAT, но ключ чище.)*

**3. Python и зависимости**
```
python3 -m venv .venv && . .venv/bin/activate
pip install -r _bot/requirements.txt
```

**4. Секреты**
```
cp _bot/.env.example _bot/.env
nano _bot/.env   # вписать: LLM_API_KEY, (LLM_MODEL/BASE_URL), TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, REPO_DIR
```
- **LLM**: ключ OpenAI (или другого провайдера + его `LLM_BASE_URL`/`LLM_MODEL`).
- **Telegram**: токен и `chat_id` — те же, что у мониторинга (тот же бот).
- **REPO_DIR**: абсолютный путь к этому клону (напр. `/home/user/ai-knowledge`).

## Тестовый запуск
```
cd /home/user/ai-knowledge
set -a; . _bot/.env; set +a
.venv/bin/python3 _bot/ai_digest.py
```
Ожидаемо: соберёт материалы → пришлёт выпуск в Telegram → сделает коммит/пуш. Ошибки видны в выводе.

## Расписание (cron)
`crontab -e` и добавить строку (пример: 08:00 МСК = 05:00 UTC, если сервер в UTC):
```
0 5 * * * cd /home/user/ai-knowledge && set -a && . _bot/.env && set +a && /home/user/ai-knowledge/.venv/bin/python3 _bot/ai_digest.py >> /home/user/ai-knowledge/_bot/digest.log 2>&1
```
Подставьте свои пути и нужное время.

## Заметки
- Списки источников правятся в начале `ai_digest.py` (`RSS_FEEDS`, `TG_CHANNELS`).
- Модель/провайдер меняются через `LLM_MODEL` и `LLM_BASE_URL` в `.env`.
- Когда сервер заработает — облачную рутину на claude.ai можно отключить, чтобы не дублировать.
