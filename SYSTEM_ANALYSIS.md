# System Analysis — Shopify Blog Poster

## Як працює зараз

### Тригер

`cron: "0 7 * * *"` — щодня о 7:00 UTC. Без timeout в GH Actions (дефолтний = 6 годин).

---

### Крок 1 — Завантаження історії

Читає `stores/my-store/published_slugs.json`. Для старих записів без embedding — рахує їх через sentence-transformers (backfill). Зберігає назад.

Що зберігається зараз у кожному записі: `slug`, `topic`, `date`, `source`, `embedding`.

**Що НЕ зберігається:** реальний заголовок статті (не topic, а title який згенерував LLM), стиль, чи була публікація примусова.

---

### Крок 2 — Вибір теми (до 3 fallback-спроб)

**a) RSS discovery** → Google News за 8+ запитами (keywords + niche шаблони типу "best {niche}", "how to {niche} 2026"). З кожного запиту — до 8 заголовків. Скоринг: базовий 1.0 + бонус за префікс (how to/best/top = +2.0) + довжина 5-9 слів (+1.0) + знак питання (+0.5) + рік (+0.5) + джерело-дублікат (+0.5 за кожне, max +2.5).

Топ-25 кандидатів → додаються в `topic_pool.json` якщо НЕ є дублікатом (cosine ≥ 0.75 відносно pool і published).

**b) Pick з пулу** → вибирається найвищий за score, який не є дублікатом published. Пул максимум 100 записів.

**c) Evergreen fallback** → якщо пул порожній або всі дублікати — бере перший невикористаний топік з `store_config.json` (25 штук).

**d) AI-generated evergreen** → якщо evergreen вичерпаний — запитує Llama-4-Scout згенерувати 20 нових ідей по 10 категоріях. Фільтрує знову через cosine.

---

### Крок 3 — Продукти

Shopify GraphQL запит на всі active продукти. Кеш 24h в `products_cache.json`. Формує текст для промпту: handle, title, URL.

**Поточна проблема:** якщо відповідь не має `data.products` — падає з `NoneType` (незакомічений фікс в `modules/products.py`).

---

### Крок 4 — Генерація з quality gate (до 3 спроб)

Викликає Groq. Модель: **Llama-4-Scout-17B** (primary). Llama-3.3-70B — fallback **тільки при API-помилці**, не при поганій якості.

Промпт: niche + topic + audience + tone + catalog + published topics (останні 15). Просить 900–1400 слів, семантичний HTML, JSON-відповідь.

**Quality gate після кожної спроби:**
1. Жодного `/products/handle` в HTML що не є в каталозі
2. ≥ 350 слів (зараз незакомічена зміна; в продакшені ще 600)
3. title присутній і ≤ 80 символів
4. meta_description присутній

Якщо провал після 3 спроб → `raise RuntimeError` → `sys.exit(1)`.

**Прихований баг:** 70B ніколи не використовується для quality retry — тільки при API-помилці. Три спроби підряд з тим самим Scout 17B дають той самий результат.

---

### Крок 5 — Зображення

Pexels page 1 → 1 cover (за topic). Pexels page 2 → 2 inline (за topic). Якщо Pexels пустий → Unsplash.

**Поточна проблема:** `UNSPLASH_KEY` в GH Actions порожній. Unsplash фактично не працює.

Inline-зображення вставляються після 1-ї і 2-ї `<h2>` тегів. Alt = заголовок секції.

---

### Крок 6 — Публікація в Shopify

GraphQL mutation `articleCreate`. До HTML додає:
- `<script type="application/ld+json">` з schema.org Article
- `<div class="author-bio">` внизу

SEO meta description → metafield `seo.description`. Якщо є cover image → `image.url` в mutation.

---

### Після публікації

Запис у `published_slugs.json`. Видалення теми з `topic_pool.json`. Git commit + push (тільки папка `stores/`).

---

### Що відбувається при будь-якій помилці

`sys.exit(1)` → GitHub Actions червоний → нічого більше. Жодного сповіщення.

---

## Поточні баги

| Баг | Де | Статус |
|---|---|---|
| `NoneType` при product fetch | `modules/products.py` | Фікс написаний, не закомічений |
| Word count gate = 600 в продакшені | `modules/quality.py` | Фікс написаний (→350), не закомічений |
| 70B ніколи не використовується для quality retry | `modules/generator.py` | Не виправлено |
| `UNSPLASH_KEY` порожній в GH Secrets | `.github/workflows/daily-blog.yml` | Не виправлено |
| exit(1) при всіх помилках | `poster.py` | Не виправлено |

---

## Що можна змінити / додати

| # | Що | Що зараз | Що стане |
|---|---|---|---|
| 1 | **Telegram** | Нічого | Сповіщення при помилці (крок + текст), при success (заголовок статті) |
| 2 | **exit(0) при skip** | exit(1) → GitHub червоний | exit(0) + Telegram → GitHub зелений, ти знаєш що день пропущено |
| 3 | **Retry з 70B** | 3x Scout підряд → завжди та сама відповідь | При quality fail → retry з Llama-3.3-70B |
| 4 | **або Claude Haiku** | Groq безкоштовно, але 400 слів замість 900 | ~$1/міс, надійно дотримується довжини і формату |
| 5 | **Progressive retry** | 3 спроби без паузи | 5с → 15с → 30с, потім hourly retries при API-недоступності |
| 6 | **GH Actions timeout** | Не виставлено | `timeout-minutes: 360` для hourly retries |
| 7 | **Зберігати title в лог** | Тільки topic (RSS заголовок) | + реальний title що згенерував LLM, + style |
| 8 | **Варіативність стилю** | Завжди один формат | 6 форматів: how-to, comparison, ingredient deep-dive, myth-busting, buyer guide, quick tips |
| 9 | **Expiry для пулу** | Теми в пулі назавжди | Видаляти топіки старші 30 днів |
| 10 | **UNSPLASH_KEY** | Порожній в GH Actions | Додати секрет або прибрати Unsplash як марний fallback |

---

## Варіативність стилю — TODO (детально розібрати)

Зараз всі статті одного формату: hook + 3-5 H2 + FAQ + Sources.
Потрібно ввести 6 форматів адаптованих під e-commerce, не повторювати підряд.
Формати (орієнтовно): how-to, comparison (X vs Y), myth-busting, buyer guide, ingredient deep-dive, quick tips.
Логіка вибору стилю — через LLM на основі теми + останні 5 стилів щоб не повторювати.

---

## Groq vs Claude Haiku

| | Groq (Llama-4-Scout 17B) | Claude Haiku 4.5 |
|---|---|---|
| Ціна | Безкоштовно | ~$1/міс при щоденних запусках |
| Дотримання довжини | Ненадійно (400 замість 900+) | Надійно |
| JSON без обгортки | Часто додає \`\`\`json | Рідко |
| Instruction-following | Середній рівень | Значно кращий |
| Швидкість | Дуже швидко | Трохи повільніше |
| Стабільність | Залежить від free tier limits | Стабільно |

Зниження порогу до 350 слів — workaround, не рішення. Для SEO потрібно 700+ слів.

---

# Об'єднаний план (Shopify + Agency архітектура)

Третя ітерація аналізу: об'єднати найкраще з обох систем у єдину архітектуру.

## Фундаментальна різниця в задачах

| | Agency | Shopify |
|---|---|---|
| Тип контенту | Новини (timed) | Evergreen SEO (timeless) |
| Час життя статті | 1-7 днів | Місяці-роки |
| Мета | Trafiк з соцмереж + RSS | Органічний пошук |
| Метрика успіху | Свіжість + покриття | Ranking + relevance |
| "Done" критерій | Є новини за вчора | Є нероз'яснена тема в ніші |

Деякі патерни agency застосовні дослівно, деякі — концептуально, деякі — недоречні.

## Ядро від кожної системи

### Береться від Agency без змін
1. Telegram-парадигма — спостереженість як перший клас
2. Progressive retry — 5с → 15с → 30с → 1г → 1г → 1г
3. LLM як шар прийняття рішень — не просто генерація
4. Структурований лог — date, title, slug, style, forced, summary
5. Style-rotation — не повторювати останні N стилів
6. Schema як контракт — формальна валідація перед записом

### Береться від Shopify без змін
1. Шар фолбеків для тем — RSS → pool → evergreen → AI
2. Product grounding + handle validation — критично для e-commerce
3. Image enrichment — Pexels (Unsplash прибрати)
4. Multi-store config — масштабованість на майбутнє

### Адаптується концептуально
1. **NEW/CONTINUATION/FORCED** — з новин у evergreen-семантику:
   - NEW = свіжа тема
   - CONTINUATION = поглиблення/продовження теми ("Beginner LED routine" → "Advanced LED routine") з посиланням на попередню статтю
   - FORCED = всі теми конфліктують, публікуємо найменш схожу + флаг

2. **Стилі** — заміна під e-commerce:
   - News Roundup → **Comparison** (X vs Y)
   - Deep Dive → **Ingredient/Tech Deep-Dive**
   - Rumor Report → ❌ (нема еквіваленту)
   - Quick Hits → **Quick Tips**
   - Trend Analysis → **Buyer's Guide**
   - Breaking Down → **How-To** (step-by-step)
   - **+ Myth-Busting** (e-commerce specific)

### Не береться
- Time-window filter за вчорашнім днем (нерелевантно для evergreen)
- Article aggregation з 6 RSS-джерел (наша задача — теми, не події)

## Архітектурні шари об'єднаної системи

```
Layer 1: TOPIC DISCOVERY (Shopify-style fallback chain)
   RSS → pool → evergreen bank → AI-replenish

Layer 2: TOPIC DECISIONING (Agency-style LLM)
   Claude Haiku check vs last 30 logged → NEW | CONTINUATION | FORCED | SKIP

Layer 3: STYLE SELECTION (Agency-style)
   Claude Haiku picks style avoiding last 5 used

Layer 4: GENERATION (Claude Haiku)
   Style-specific prompt + product catalog + (optional) prev_article_link for CONTINUATION

Layer 5: VALIDATION (extended Shopify quality gate)
   Product handles + word count + schema fields + frontmatter contract

Layer 6: PUBLICATION (Shopify GraphQL — без змін)
   Article + schema.org + author bio + cover image

Layer 7: LOGGING (Agency-style rich entries)
   {date, title, slug, style, source, verdict, forced, prev_slug}

Layer 8: OBSERVABILITY (Agency-style Telegram)
   Per-attempt retry alerts + skip + forced + success
```

## Ключові рішення (потребують підтвердження)

### Embedding-dedup vs LLM-dedup
**Рекомендація:** замінити повністю на LLM. Embedding має відомі проблеми (LED masks vs red light therapy), Claude Haiku коштує копійки. Видалити sentence-transformers повністю — мінус 500MB кешу і складність.

### forced-fallback — публікувати завжди?
**Рекомендація:** forced тільки якщо LLM знаходить тему з відстанню вище порогу. Інакше ризик duplicate content penalty від Google. Якщо LLM каже "всі теми занадто схожі" — це чесний сигнал що сьогодні нема чого публікувати.

### CONTINUATION-linking — як саме
При verdict=CONTINUATION промпт містить `prev_slug` і `prev_title` + інструкцію природно посилатися на попередню статтю. Зберігати `prev_slug_referenced` в log для аналітики мережі зв'язків.

### Style-список — фінальний (6 стилів)
1. **How-To** — крок-за-кроком, інструктивний
2. **Comparison** — X vs Y (продукти, техніки, інгредієнти)
3. **Buyer's Guide** — фреймворк прийняття рішень
4. **Deep-Dive** — одна технологія/інгредієнт детально
5. **Myth-Busting** — спростування поширених помилок
6. **Quick Tips** — короткий actionable список

### Лог-схема — фінальна
```python
{
  "date": "2026-05-10",
  "slug": "how-led-therapy-works",
  "title": "...",                  # реальний LLM-title
  "topic": "...",                  # вихідна тема
  "source": "rss"|"evergreen"|"ai_generated",
  "style": "Deep-Dive",
  "verdict": "NEW"|"CONTINUATION"|"FORCED",
  "forced": false,
  "prev_slug": null|"some-slug",
  "embedding": [...]                # опціонально
}
```
Migration: скрипт що бере існуючий `published_slugs.json` і додає поля з дефолтами.

### Топік-пул
Залишити, додати expiry (>30 днів). Pool корисний коли RSS дає 25 кандидатів — не треба викидати 24 невикористаних.

### Image strategy
Видалити Unsplash з коду повністю. Тільки Pexels. Якщо Pexels відмовить — публікувати без cover (graceful degradation вже є).

### Cost (Claude Haiku, 3-4 виклики/день)
- Conflict check: ~$0.005
- Style select: ~$0.001
- Generate article: ~$0.015
- Evergreen replenish: ~$0.008
- **Per day:** ~$0.025 / **Per month:** ~$0.75

## Пріоритизована послідовність

### Phase 0 — already done ✅
- Telegram базовий + exit(0) — код в poster.py і workflow, **НЕ запушений**
- Telegram secrets в GitHub repo — додані

### Phase 1 — Foundation
1. Перехід на Claude Haiku — `generator.py` + `evergreen.py` + `requirements.txt` + GH secrets
2. Видалити Groq залежності — імпорти, secrets, dead code
3. Видалити Unsplash dead code — тільки Pexels
4. Migration script для `published_slugs.json` у новий формат

### Phase 2 — Decisioning
5. Прибрати embedding-cosine dedup, видалити sentence-transformers
6. LLM-based conflict detection з verdict NEW/CONTINUATION/FORCED
7. CONTINUATION → prev_slug в промпті для природного internal-linking
8. forced-fallback логіка з порогом якості

### Phase 3 — Generation quality
9. 6 e-commerce style templates з prompt-guides на кожен
10. LLM-style-selection на основі теми + last 5 styles
11. Lower word count gate (Claude слідує інструкціям, можна цілитись 900-1200 надійно)

### Phase 4 — Robustness & observability
12. Progressive retry 5с/15с/30с/1г/1г/1г
13. Telegram per-attempt з countdown до наступної спроби
14. GH Actions `timeout-minutes: 360`

### Phase 5 — Hygiene
15. Topic pool expiry (>30 днів)
16. Save title in log (частина Phase 1 migration)

## Поточний стан виконання

| Phase | Item | Status |
|---|---|---|
| 0 | Telegram базовий | Код є, не запушено |
| 0 | exit(0) при skip | Код є, не запушено |
| 0 | TG secrets в GH | ✅ |
| 1 | Claude Haiku | Не починалось |
| 1 | Видалити Groq | Не починалось |
| 1 | Видалити Unsplash | Не починалось |
| 1 | Migration script | Не починалось |
| 2 | Embedding → LLM | Не починалось |
| 2 | Conflict detection | Не починалось |
| 2 | CONTINUATION linking | Не починалось |
| 2 | forced-fallback | Не починалось |
| 3 | 6 styles | Не починалось |
| 3 | Style selection | Не починалось |
| 3 | Word count target | Не починалось |
| 4 | Progressive retry | Не починалось |
| 4 | TG per-attempt | Не починалось |
| 4 | GH timeout 360 | Не починалось |
| 5 | Pool expiry | Не починалось |
| 5 | Save title | Buffered у Phase 1 |
