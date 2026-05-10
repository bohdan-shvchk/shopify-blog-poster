# Аудити системи

Кожен запис — знімок стану і рекомендацій на конкретну дату. Нічого не замінювати, тільки додавати нові аудити в кінець.

---

## Аудит 2026-05-10 — після Phase 0/1

Стан: pipeline зелений, Claude Haiku 4.5 + Telegram + read_products scope активні. Перший детальний аудит.

Оцінка: 🟢 добре · 🟡 середньо · 🔴 слабко.

### Крок 1 — Завантаження історії · 🟡

**Що працює:** backfill embeddings для старих записів — добре зроблено.

**Слабкі місця:**
- В `published_slugs.json` зберігається `slug`, а не справжній заголовок статті. Дивитись історію незручно — треба декодувати назад зі slug.
- Немає захисту від дублів самого запису. Якщо workflow тригернути двічі за день (як ми сьогодні зробили) — два записи. Жоден з них не вибіркова основа для дедупу — embedding однаковий.
- Auto-commit `published_slugs.json` + `topic_pool.json` після кожного запуску → шум у git історії. Pool пересортовується щодня = щоденний коміт навіть якби не було публікації.

**Що покращити:**
- Зберігати `title`, `id` (Shopify Article ID), `url` поряд зі slug. Зараз id повертається з Shopify, але викидається.
- Додати поле `expired: true` для топіків старших за N днів замість видалення.

### Крок 2.1 — RSS discovery · 🟡

**Що працює:** Google News RSS — стабільне джерело без ключа.

**Слабкі місця:**
- **Єдине джерело**. Якщо Google News впаде або заблокує — pipeline на evergreen. agency-website використовує кілька RSS.
- **Heuristic scoring наївний:**
  - `+2.0 за "best"/"top"` — заохочує банальні listicles
  - `+0.5 за "?"` — clickbait-bonus
  - джерело не враховується (заголовок з reuters.com має ту ж вагу що з random-spam-blog.com)
- **Парсинг заголовка:** `title.split(" - ")[0]` ламається на заголовках типу `"How to do X - step by step - 2026 guide"` (обриває до першого тире, втрачаючи контекст).
- **Запити жорстко зашиті:** `best`, `how to`, `2026`, `guide`. Жодного запиту під «science / myths / comparison» — недоотримуємо різноманіття.

**Що покращити:**
- Додати білий список доменів (whitelist) — score×1.5 для reuters/bbc/healthline/тощо.
- Розширити запити: `<niche> myth`, `<niche> science`, `<niche> vs`, `<niche> tutorial`.
- Видалити score-bonus за `?` — це clickbait-фактор.

### Крок 2.2 — Topic pool · 🟡

**Що працює:** дедуп при додаванні + при виборі — два бар'єри. Embedding-подібність 0.75 розумне число для коротких заголовків.

**Слабкі місця:**
- **Немає expiry.** Топіки додані 60 днів тому з оцінкою 5.5 досі лежать першими. Світ змінився, тренд застарів.
- **Score не decay'ється.** Старий топік завжди буде вище свіжого з нижчим score, навіть якщо свіжий — actuality.
- **Немає category balance.** Pool може бути 90% «best X» і 0% myth-busting. Sort by score = monoculture контенту.
- **Threshold 0.75 hardcoded** — нормально для коротких рядків, але немає тюнінгу під різні мови / ніші.

**Що покращити:**
- Додати в `pick_best`: `effective_score = score - 0.05 × days_since_found`. Старі топіки самі собою сповзають.
- Видаляти з pool записи старші 60 днів (`expired_at`).
- Pool-balance: при `pick_best` чергувати категорії (rss → evergreen → ai_generated → rss…) — або вибирати найвищий score з кожної категорії по черзі.

### Крок 2.3 — Evergreen банк · 🟢

**Що працює:** 25 ручних тем у конфігу — якісних і різнопланових. Простий fallback.

**Слабке:** немає priority/score у самому банку — picks the first non-dup. Кращі теми в кінці списку можуть ніколи не виконатись, бо щоразу попередні беруться першими.

**Що покращити:** додати `evergreen_topics` як список об'єктів з `weight`, або просто перемішувати порядок при кожному запуску (`random.shuffle`).

### Крок 2.4 — AI генерація · 🟢

**Що працює:** 10 категорій-шаблонів, заборона на бренди, чіткий промпт. Як safety net відмінно.

**Слабке:** генеровані теми використовуються одноразово (бере першу не-дубль), не зберігаються в pool. Інші 19 ідей з batch'у викидаються.

**Що покращити:** додати всі 20 згенерованих тем у pool після фільтрації — наступного дня візьмемо звідти без виклику Claude.

### Великий пробіл — немає NEW/CONTINUATION/FORCED · 🔴

agency-website має це, у нас — ні. Кожна стаття пишеться як ізольована, без зв'язку з попередньою. Втрачаємо:
- внутрішнє лінкування статтей між собою (SEO силу site structure)
- серії «part 1 / part 2 / deep-dive»
- природну тематичну еволюцію блогу

**Що покращити:** перед генерацією питати Claude: "ось нова тема + останні 5 статей. Це NEW / CONTINUATION / FORCED?". Якщо CONTINUATION — додати в промпт slug попередньої статті як обов'язкове внутрішнє посилання.

### Крок 3 — Products · 🟡

**Що працює:** 24h кеш, пагінація, обробка GraphQL errors (свіжо додана), TTL логіка чиста.

**Слабкі місця:**
- **Немає ціни, картинок, варіантів.** Claude не знає що Lipstick A — $15, а Lipstick B — $300. Не може зробити «budget-friendly» рекомендацію.
- **Топ-30 без релевантності.** `format_for_prompt` бере перші 30 у тому порядку як Shopify повернув. Якщо стаття про hair removal, а перші 30 — це LED-маски, hair-removal продукт може не дійти до промпту.
- **Опис обрізаний до 300 символів** — Claude бачить мало контексту про сам продукт.
- **Тегів і product_type не використано в промпті** — поля fetched, але `format_for_prompt` їх не показує.

**Що покращити:** перед `format_for_prompt` фільтрувати каталог за релевантністю до теми (через embedding cosine між темою і `title + description + tags` кожного товару). Топ-15 за релевантністю → промпт.

### Крок 4.1 — Промпт генератора · 🟡

**Що працює:** жорсткий system prompt про hallucinations, чіткий шаблон секцій, JSON-only.

**Слабкі місця:**
- **Один шаблон на всі статті.** Кожна стаття: hook → "What you'll learn" → 3-5 H2 → FAQ → Sources. Через 10 статтей блог виглядає однотипно.
- **`published_topics` тільки 15 останніх.** Claude може ненавмисно повторити тему 16-у назад.
- **«Word count 900-1400» але gate 600.** Невідповідність — модель може видавати 600 слів, gate пропустить, у промпті 1400 ігнорується.
- **Немає one-shot example.** Висока якість потребує приклада в промпті — без нього модель видає середній mid-tier контент.
- **Author bio в промпті + інжектиться publisher'ом окремо** — теоретично може дублюватись у статті.

**Що покращити:**
- 6 шаблонів стилей з agency-website (How-To, Comparison, Buyer's Guide, Deep-Dive, Myth-Busting, Quick Tips). Перед генерацією Claude вибирає стиль під тему.
- Передавати ВСІ опубліковані теми (зараз їх <50 — токенів небагато), а не 15.
- Узгодити: gate ≥ 800 слів, промпт «strictly 900-1400».

### Крок 4.2 — Парсинг JSON · 🟡

**Що працює:** обробка markdown-fences, керуючих символів, fallback на rfind.

**Слабке:** JSON Claude'а валиться на одинарних / неекранованих лапках всередині HTML. Зараз ловиться JSONDecodeError → exit(0), але втрачаємо запит цілком.

**Що покращити:** додати у виклик Anthropic параметр `response_format` якщо доступний, або інструктувати у промпті: «escape all double-quotes inside HTML attributes as `&quot;`».

### Крок 4.3 — Quality gate · 🔴

**Що працює:** detection of hallucinated product handles — критична перевірка, добре зроблено.

**Слабкі місця:**
- **Тільки 4 перевірки.** Не детектить:
  - вигадану статистику («87% жінок повідомили…»)
  - вигадані експертні цитати («Dr. Smith from Harvard says…»)
  - вигадані зовнішні джерела (`<a href="https://nih.gov/study-12345">` що не існує)
  - meta_description > 160 символів (промпт просить max 160, але gate не валідує)
  - title > 60 символів (промпт max 60, gate валідує тільки 80)
  - heading hierarchy (H3 без батьківського H2)
  - кількість тегів (промпт просить 3, гейт ігнорує)
- **Word count 600** — нижче запрошених 900. Дозволяє mediocre короткі статті проходити.
- **Немає семантичної перевірки** «стаття про тему?». Claude може відписати статтю про щось дотичне.

**Що покращити:**
- Підняти `min_words=800`.
- Додати regex-перевірки: `\d+%`, `Dr\. \w+`, цитати в лапках > 20 слів — підняти WARN (не fail) у Telegram.
- Перевіряти зовнішні URL HEAD-запитом — якщо 404, fail.
- Жорсткіша валідація meta_description (≤ 160) і title (≤ 60).

### Крок 4.4 — Retry · 🟡

**Що працює:** 3 спроби.

**Слабке:**
- **Той самий промпт.** Якщо модель видала 500 слів — три рази видасть 500 слів. Retry без зміни умов = трата токенів.
- **Немає backoff** на API errors (rate limit, 529).

**Що покращити:** на retry змінювати промпт — додавати `"PREVIOUS ATTEMPT FAILED: <reason>. Fix specifically that"`. agency-website робить це і це різко піднімає success rate.

### Крок 5 — Images · 🟡

**Що працює:** primary/fallback запити, різні pages для cover і inline (не дублюються), per-h2 alt text.

**Слабкі місця:**
- **Pexels тільки.** Стокова якість. Конкуренти з Unsplash + Midjourney AI-images перевершують візуально.
- **Запит = повна назва теми.** Довгі заголовки типу `"Best Beauty Tech 2026: Microcurrent Wands to At-Home Lasers"` дають Pexels'у плутанину — повертає випадковий beauty-content.
- **Тільки 2 inline.** У статті 3-5 H2 — тобто половина без зображень.
- **Стиль інжекції inline** — inline стилі замість CSS-класу. Не змінити централізовано.
- **Немає Pexels attribution.** Не обов'язково, але best practice.

**Що покращити:**
- Перед запитом Pexels витягти 2-3 ключових слова з теми (можна Claude'ом дешево, або regex по nouns) — `"microcurrent face wand"` замість усього заголовка.
- Inline для всіх H2, не тільки 1-го і 2-го.

### Крок 6.1 — schema.org JSON-LD · 🟡

**Що працює:** базовий Article schema присутній.

**Слабке:** немає `mainEntityOfPage`, `wordCount`, `articleSection`, `keywords`, FAQ schema (якщо є FAQ — а в нас завжди є). Без FAQ schema Google не показує rich snippets.

**Що покращити:** додати FAQPage schema паралельно (extract Q&A з html_body по `<h3>` всередині FAQ-секції), додати `mainEntityOfPage`, `wordCount`.

### Крок 6.2 — Публікація · 🟢

**Що працює:** GraphQL мутація чиста, обробка userErrors, метаполе SEO description, image, tags, author. Все коректно.

**Слабке:**
- немає `seo.title` metafield — для og:title використовується звичайний `title`. Якщо хочемо різні — треба окремо.
- немає setting'у `published: true` явно — за замовчуванням Shopify публікує, але best practice бути explicit.

### Workflow YAML · 🟡

**Що працює:** Python cache, HF model cache, secrets injection, auto-commit.

**Слабкі місця:**
- **Node.js 20 actions deprecated** — ми вже бачили warning. До червня 2026 треба апнути `actions/checkout@v4`, `actions/setup-python@v5`, `actions/cache@v4` до версій з Node.js 24.
- **Немає `timeout-minutes`** — за замовчуванням 360 хв. Якщо щось зависне — годинник цокотить.
- **Один store hardcoded** (`--store my-store`). Якщо буде другий магазин — треба окремий job або matrix.
- **Auto-commit без перевірки** — комітить будь-яку зміну в `stores/`.

**Що покращити:**
- `timeout-minutes: 30` — більше ніж треба для запуску, менше ніж години простою.
- Matrix strategy для multi-store: `strategy.matrix.store: [my-store, store-2]`.

### Загальні дірки

**1. Telegram alerts добре зроблені, але один напрямок.** Немає способу швидко **вимкнути** posting (наприклад, на час перевалки магазину). Треба руками disable workflow.

**Що покращити:** додати read-only feature flag в `store_config.json` — `"enabled": true/false`. poster.py чекає, шле Telegram «store disabled, skipping».

**2. Немає тестів.** Жодного. Все тестується в продакшені на живому магазині.

**Що покращити:** хоча б `tests/test_quality.py` (валідатори чисті функції, легко тестувати), `tests/test_dedup.py`, `tests/test_topic_pool.py`. CI крок `pytest` перед deploy.

**3. Немає dry-run в CI.** `--dry-run` flag є в коді, але workflow його не використовує. Не можна перевірити PR без публікації.

**Що покращити:** додати окремий workflow `pr-check.yml` що запускає `python poster.py --store my-store --dry-run` на кожен PR.

**4. Немає observability.** Knowing «опубліковано X статтей за місяць» вимагає `git log` + grep.

**Що покращити:** окремий `stats.json` з місячним каунтером, або просто WeeklyDigest у Telegram у неділю.

**5. Single language**. `language: en` в конфігу, але по факту все hardcoded на англійську (промпт, evergreen-теми, scoring prefixes). Багатомовність декларована, не реалізована.

### Підсумок по пріоритетах (станом на 2026-05-10)

| Пункт | Оцінка | Імпакт фіксу |
|---|---|---|
| Quality gate (4.3) | 🔴 | висока — пропускає mediocre контент |
| NEW/CONTINUATION/FORCED | 🔴 | висока — внутрішня структура блогу |
| Topic pool expiry & balance (2.2) | 🟡 | середня — застарілий контент |
| Style templates (4.1) | 🟡 | висока — однотипність блогу |
| Retry diversification (4.4) | 🟡 | середня — економія токенів |
| Product relevance ranking (3) | 🟡 | висока — правильні товари у статті |
| Image keyword extraction (5) | 🟡 | низька — візуал |
| Save title + Article ID (1) | 🟡 | низька — UX логів |
| Node 20 → 24 actions | 🟡 | низька — до дедлайну є час |
| Pexels FAQ schema (6.1) | 🟡 | середня — SEO rich snippets |
