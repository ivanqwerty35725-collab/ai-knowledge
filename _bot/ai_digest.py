#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Ежедневный ИИ-дайджест (серверная версия).

Что делает:
  1) собирает свежие материалы из RSS-лент и публичных Telegram-каналов (t.me/s/);
  2) просит LLM сделать сводку простым русским языком по нашим разделам;
  3) сохраняет выпуск в 00_Дайджесты/<ДАТА>.md и коммитит в git-репозиторий;
  4) отправляет выпуск в ваш Telegram-бот.

Все секреты берутся из переменных окружения (см. .env.example). Запуск — по cron.
"""

import os
import re
import sys
import html
import datetime
import subprocess
import urllib.request

import requests
import feedparser

# ----------------------- Конфиг из переменных окружения -----------------------
LLM_API_KEY  = os.environ["LLM_API_KEY"]
LLM_BASE_URL = os.environ.get("LLM_BASE_URL", "https://api.openai.com/v1")
LLM_MODEL    = os.environ.get("LLM_MODEL", "gpt-5-mini")
TG_TOKEN     = os.environ["TELEGRAM_BOT_TOKEN"]
TG_CHAT      = os.environ["TELEGRAM_CHAT_ID"]
# Корень репозитория базы знаний (по умолчанию — на два уровня выше этого файла,
# если скрипт лежит в <repo>/_bot/ai_digest.py)
REPO_DIR   = os.environ.get("REPO_DIR", os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DIGEST_DIR = os.path.join(REPO_DIR, "00_Дайджесты")

RSS_FEEDS = [
    "https://openai.com/news/rss.xml",
    "https://deepmind.google/blog/rss.xml",
    "https://www.oneusefulthing.org/feed",
    "https://importai.substack.com/feed",
    "https://simonwillison.net/atom/everything/",
    "https://www.latent.space/feed",
    "https://rss.arxiv.org/rss/cs.AI",
    "https://rss.arxiv.org/rss/cs.CL",
    "https://rss.arxiv.org/rss/cs.LG",
    "https://techcrunch.com/category/artificial-intelligence/feed/",
    "https://www.technologyreview.com/feed/",
    "https://feeds.arstechnica.com/arstechnica/index",
    "https://news.ycombinator.com/rss",
    "https://www.reddit.com/r/LocalLLaMA/.rss",
    "https://www.reddit.com/r/artificial/.rss",
    "https://habr.com/ru/rss/hubs/machine_learning/articles/?fl=ru",
    "https://habr.com/ru/rss/hubs/analysis_design/articles/?fl=ru",
    "https://www.interconnects.ai/feed",
    "https://erictopol.substack.com/feed",
    "https://recodechinaai.substack.com/feed",
    "https://www.semianalysis.com/feed",
    "https://www.transformernews.ai/feed",
    "https://thezvi.substack.com/feed",
]

TG_CHANNELS = [
    "seeallochnaya", "denissexy", "ai_newz", "data_secrets", "gonzo_ML",
    "ai_machinelearning_big_data", "cgevent", "llm_under_hood", "addmeto",
    "abstractDL", "rybolos_channel", "boris_again", "evilfreelancer",
    "sys_sa", "sa_chulan",
]

UA = {"User-Agent": "Mozilla/5.0 (compatible; ai-digest-bot/1.0)"}
NOW = datetime.datetime.now(datetime.timezone.utc)
RECENT = datetime.timedelta(hours=48)


def log(msg):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {msg}", flush=True)


# ----------------------------- Сбор материалов -------------------------------
def fetch_rss():
    items = []
    for url in RSS_FEEDS:
        try:
            d = feedparser.parse(url, request_headers=UA)
            for e in d.entries[:8]:
                # фильтр по свежести, если дата известна
                t = e.get("published_parsed") or e.get("updated_parsed")
                if t:
                    pub = datetime.datetime(*t[:6], tzinfo=datetime.timezone.utc)
                    if NOW - pub > RECENT:
                        continue
                title = (e.get("title") or "").strip()
                link = (e.get("link") or "").strip()
                summary = re.sub("<[^>]+>", " ", e.get("summary", ""))
                summary = re.sub(r"\s+", " ", summary).strip()[:400]
                if title and link:
                    items.append({"src": d.feed.get("title", url), "title": title,
                                  "link": link, "summary": summary})
        except Exception as ex:
            log(f"RSS skip {url}: {ex}")
    return items


def fetch_telegram():
    items = []
    for ch in TG_CHANNELS:
        try:
            r = requests.get(f"https://t.me/s/{ch}", headers=UA, timeout=20)
            if r.status_code != 200:
                continue
            blocks = re.findall(
                r'<div class="tgme_widget_message_text[^"]*"[^>]*>(.*?)</div>',
                r.text, flags=re.S)
            for b in blocks[-5:]:  # последние ~5 постов
                text = re.sub("<br\\s*/?>", " ", b)
                text = re.sub("<[^>]+>", " ", text)
                text = html.unescape(re.sub(r"\s+", " ", text)).strip()
                if len(text) > 40:
                    items.append({"src": f"@{ch}", "title": text[:120],
                                  "link": f"https://t.me/{ch}", "summary": text[:600]})
        except Exception as ex:
            log(f"TG skip {ch}: {ex}")
    return items


def recent_digest_titles():
    """Заголовки последних выпусков — чтобы LLM не повторялся."""
    out = []
    try:
        files = sorted([f for f in os.listdir(DIGEST_DIR) if f.endswith(".md")], reverse=True)
        for f in files[:5]:
            with open(os.path.join(DIGEST_DIR, f), encoding="utf-8") as fh:
                for line in fh:
                    if line.startswith("### "):
                        out.append(line.strip("# \n"))
    except Exception as ex:
        log(f"recent digests: {ex}")
    return out[:60]


# ------------------------------- Вызов LLM -----------------------------------
SYSTEM = """Ты — редактор ежедневного дайджеста об ИИ для системного аналитика. \
Пиши простым русским языком, без жаргона (термин — короткой расшифровкой в скобках), нейтрально, без хайпа. \
Каждый пункт — 2–3 содержательных предложения по сути, не только заголовок."""

PROMPT_TMPL = """Сегодня {date}. Составь выпуск дайджеста на основе материалов ниже.

УЖЕ ВЫХОДИЛО (НЕ повторять эти темы):
{seen}

СВЕЖИЕ МАТЕРИАЛЫ (источник | заголовок | суть | ссылка):
{material}

ЗАДАЧА: отбери 5–7 самых важных и НОВЫХ материалов, распредели по разделам ниже. \
Бери только разделы, где реально есть материал (пустые пропускай):
🔬 Технологии, наука и открытия
🧩 ИИ для системного анализа
🎓 Учёба и обучение
🛠️ Навыки и приёмы (скиллы)
🧑‍💻 Как люди используют ИИ (реальный опыт/адаптация, не «вендор выкатил функцию»)
🧰 Инструменты и программы

ФОРМАТ — строго Markdown, верни ТОЛЬКО его (без пояснений):
---
тип: дайджест
дата: {date}
---

# 📰 Дайджест за {date}
⏱️ Чтение ~N минут · счётчики по присутствующим разделам

## <эмодзи и название раздела>
### 1. Заголовок 🟢
**Простыми словами:** 2–3 предложения по сути.
**Зачем вам:** практическая польза.
🔗 [Подробнее](РАБОЧАЯ_ССЫЛКА) · ⏱️ N мин

(остальные разделы и пункты по той же схеме)

## 💡 Что попробовать сегодня
Одна короткая рекомендация.

ПРАВИЛА: ссылки только из материалов выше (не выдумывай). Если материал из Telegram — добавь «via @канал». \
Обозначения сложности: 🟢 поймёт любой · 🟡 базовые понятия · 🔴 хардкор."""


def call_llm(material, seen, date):
    prompt = PROMPT_TMPL.format(
        date=date,
        seen="\n".join(f"- {t}" for t in seen) or "(нет)",
        material="\n".join(f"- {i['src']} | {i['title']} | {i['summary']} | {i['link']}"
                           for i in material)[:60000],
    )
    resp = requests.post(
        f"{LLM_BASE_URL}/chat/completions",
        headers={"Authorization": f"Bearer {LLM_API_KEY}", "Content-Type": "application/json"},
        json={"model": LLM_MODEL,
              "messages": [{"role": "system", "content": SYSTEM},
                           {"role": "user", "content": prompt}],
              "temperature": 0.4},
        timeout=180,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


# ----------------------------- Сохранение / git ------------------------------
def save_and_commit(text, date):
    os.makedirs(DIGEST_DIR, exist_ok=True)
    path = os.path.join(DIGEST_DIR, f"{date}.md")
    with open(path, "w", encoding="utf-8") as f:
        f.write(text + "\n")
    rel = os.path.relpath(path, REPO_DIR)
    try:
        subprocess.run(["git", "-C", REPO_DIR, "pull", "--rebase", "--autostash"], check=False)
        subprocess.run(["git", "-C", REPO_DIR, "add", rel], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "commit", "-m", f"Дайджест за {date}"], check=True)
        subprocess.run(["git", "-C", REPO_DIR, "push"], check=True)
        log("git push OK")
    except Exception as ex:
        log(f"git error (файл сохранён локально): {ex}")
    return path


# ------------------------------- Telegram ------------------------------------
def md_to_plain(text):
    text = re.sub(r"\[([^\]]+)\]\((https?://[^)]+)\)", r"\1 (\2)", text)  # ссылки
    text = re.sub(r"^#{1,6}\s*", "", text, flags=re.M)                    # заголовки
    text = text.replace("**", "").replace("`", "")
    return text


def send_telegram(text):
    text = md_to_plain(text)
    chunks, cur = [], ""
    for line in text.split("\n"):
        if len(cur) + len(line) + 1 > 3800:
            chunks.append(cur); cur = ""
        cur += line + "\n"
    if cur.strip():
        chunks.append(cur)
    for ch in chunks:
        r = requests.post(
            f"https://api.telegram.org/bot{TG_TOKEN}/sendMessage",
            data={"chat_id": TG_CHAT, "text": ch, "disable_web_page_preview": "true"},
            timeout=30,
        )
        if r.status_code != 200:
            log(f"Telegram error {r.status_code}: {r.text[:200]}")


# --------------------------------- main --------------------------------------
def main():
    date = NOW.strftime("%Y-%m-%d")
    log("Сбор RSS...")
    material = fetch_rss()
    log(f"RSS: {len(material)} материалов. Сбор Telegram...")
    material += fetch_telegram()
    log(f"Всего материалов: {len(material)}")
    if not material:
        log("Нет материалов — выход.")
        return
    seen = recent_digest_titles()
    log("Запрос к LLM...")
    digest = call_llm(material, seen, date)
    if not digest.strip().startswith("---"):
        digest = f"---\nтип: дайджест\nдата: {date}\n---\n\n" + digest
    log("Сохранение и коммит...")
    save_and_commit(digest, date)
    log("Отправка в Telegram...")
    send_telegram(digest)
    log("Готово.")


if __name__ == "__main__":
    main()
