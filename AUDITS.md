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

---

## Аудит 2026-05-10 #2 — після фіксу 🔴 і першого 🟡

Стан: pipeline зелений. Закрито обидва 🔴 з попереднього аудиту (quality gate hardening, NEW/CONTINUATION/FORCED). Закрито перший пріоритетний 🟡 (style templates) і пов'язаний з ним (retry diversification — тепер різний стиль на кожній спробі).

Оцінки переглянуто з нуля під поточний стан коду.

### Крок 1 — Завантаження історії · 🟡 (без змін)

Все ще зберігаємо `slug` замість заголовка, без `id` і `url`. Backfill embeddings працює.

**Слабкі місця (актуальні):**
- `published_slugs.json` — slug, topic, date, source, embedding. Немає `title` (читабельний заголовок), `article_id` (Shopify ID повертається з мутації, але викидається), `url` (не зберігається — щоб клікнути в логах треба рукою клеїти).
- Нема дедупу самого запису. Два запуски за день = два записи однієї статті.
- Auto-commit `stores/` без перевірки на що саме — git історія шумна.

**Що покращити:**
- В `poster.py` після `publish_article` зберігати в pub_records ще `title`, `article_id`, `url` (publisher повертає `id` і `handle`, url склеюється з `public_domain`).
- Додати soft idempotency: якщо `date == today` і `topic` уже є в records — skip + Telegram «duplicate run today».

### Крок 2.1 — RSS discovery · 🟡 (без змін)

**Актуальні слабкості:**
- Єдине джерело — Google News.
- Heuristic scoring: +2.0 за «best/top/how to» — заохочує банальні listicles. +0.5 за «?» — clickbait. Джерело новини не враховується.
- Парсинг заголовка: `title.split(" - ")[0]` обриває контекст.
- 4 жорстко зашитих query patterns (`best/how to/2026/guide`).

**Що покращити:**
- Whitelist доменів: парсити частину `title` після останнього « - » як source, мати dict `{reuters.com: 1.5, healthline.com: 1.4, ...}`, множити score.
- Розширити queries: додати `<niche> myth`, `<niche> science`, `<niche> tutorial`, `<niche> review`.
- Прибрати +0.5 за `?`.

**Зауваження:** з появою стилей у генератора різноманіття query'їв стало важливішим — інакше picker буде завжди впадати в `buyers_guide` (бо «best X» виграє score).

### Крок 2.2 — Topic pool · 🟡 (без змін)

**Актуальні слабкості:**
- Немає expiry. Топіки старші 60 днів все ще конкурують за score.
- Немає score decay по часу. Старий топік завжди вище свіжого з нижчим score.
- Немає category balance — pool може стати моно-культурою «best X».
- threshold 0.75 hardcoded.

**Що покращити:**
- В `pick_best`: `effective_score = score - 0.05 * days_since_found`.
- В `add_candidates` (або окремий cleanup): викидати записи з `found_date` старше 60 днів.
- Опційно: `pick_best` повертає не топ-1 а топ-N, потім poster.py обирає враховуючи розподіл стилей у останніх N статтях (щоб не йти в моно-культуру).

### Крок 2.3 — Evergreen банк · 🟢 (без змін)

Працює. Slabost: перші у списку — завжди першими. `random.shuffle(unused)` — однорядкова правка.

### Крок 2.4 — AI генерація fallback · 🟢 (без змін)

Працює. Slabost: 19 з 20 згенерованих ідей викидаються. Не критично, поки fallback rare.

### Крок 3 — Products · 🟡 (без змін, але важливість виросла)

**Актуальні слабкості:**
- Немає ціни, картинок, варіантів — Claude не може робити budget recommendations.
- `format_for_prompt` бере перші 30 без relevance ranking — нерелевантні товари в промпті, релевантні можуть не дійти.
- Опис обрізаний до 300 символів, далі ще до 120 у форматі рядка.
- Tags і product_type fetched, але не показуються Claude'у.

**Чому виросла важливість:** новий стиль `buyers_guide` явно просить «one product per category». Якщо в промпті 30 нерелевантних товарів — у статті будуть нерелевантні рекомендації, або Claude омітить секцію.

**Що покращити:**
- Embed `topic` + embed `f"{title} {description} {' '.join(tags)} {product_type}"` для кожного товару → cosine similarity → топ-15 за релевантністю → у промпт.
- Розширити GraphQL query: додати `priceRangeV2`, `featuredImage { url }`, `variants(first:1) { edges { node { price } } }`.
- Показати в промпті ціновий tier (low/mid/high) і product_type, щоб стилі типу buyers_guide могли категоризувати.

### Крок 3.5 — Topic relationship classifier · 🟢 (нове, після фіксу)

Працює. Claude Haiku 4.5, max_tokens=300, парс падає → fallback NEW. Інтегровано як `[3.5/6]`. Результат прокидається в generator як `relationship_block`.

**Дрібні слабкості:**
- Якщо classifier повертає `CONTINUATION` з validним `related_index`, але `related_topic` — це stem зі словом «best», а нова стаття теж buyers_guide про той же товар — може вийти overlap а не справжня continuation. Класифікатор не дивиться на стиль.
- Recent topics беруться з `pub_topics` — це тільки `topic`, без `style`. Тобто classifier не бачить, який формат був у попередньої статті, тільки заголовок.
- Жодного логування decision rate (% NEW vs CONTINUATION vs FORCED) — щоб зрозуміти чи рекомендації моделі sane, треба дивитись в Telegram-стрічку рукою.

**Що покращити (низький пріоритет):**
- Додати в pub_records ще `style_used` і передавати classifier'у разом з topic, щоб «articles N ago: 'X' (deep_dive)».
- Лог-файл `stats.json`: `{"continuation": 3, "new": 22, "forced": 1}` за весь час.

### Крок 4.1 — Промпт генератора · 🟢 (після фіксу)

Працює. 6 стилей, picker за ключовими словами, ranked_styles для retry. published_topics window — всі (раніше 30, до того 15). Length aligned (gate 800, prompt 900-1400).

**Дрібні слабкості:**
- Picker детермінований на ключових словах. Заголовки що не матчать жодний паттерн — завжди `deep_dive`. Не катастрофа, але всі «The Truth About X» / «Why You Need Y» падуть в deep_dive хоча краще б myth_busting / how_to.
- Стилі мають `intent` блок, але немає прикладу (one-shot). Як тільки Claude розширить контекст вікна задешево — буде легка перемога додати по одному прикладу гарного hook на стиль.
- Ніде не валідується що згенерована стаття реально відповідає вибраному стилю (e.g., quick_tips з 3-ма tips замість 8-12 — пройде, бо word count і структуру H2 quality.py не перевіряє по стилю).
- Author bio в промпті + інжектиться publisher'ом. Теоретичний дубль не виявлено (Claude дотримується), але подвоєне нагадування.

**Що покращити:**
- Розширити `_RULES` патернами: `truth about|why you|secret of` → варіативно.
- Додати в `quality.py` мінімальну кількість H2 під стиль (e.g., `quick_tips` ≥ 6 H2, `myth_busting` ≥ 4 H2). Зараз структуру не перевіряє ніщо.

### Крок 4.2 — Парсинг JSON · 🟡 (без змін)

Все ще ручний parsing з регексами для markdown-fences і керуючих символів. Ловиться JSONDecodeError на верхньому рівні → exit(0). Ризик: усе ще можлива JSON-помилка через неекрановані `"` в HTML.

**Що покращити:**
- В Anthropic SDK немає `response_format=json_object` для Haiku — але можна додавати в промпт «escape `"` inside HTML attributes as `&quot;` or use `'`».
- Або: parse не як JSON, а просити Claude віддати кожне поле з sentinel-маркерами (`<<<TITLE>>>...<<<META>>>...`) — складно, але невразливо до лапок.

### Крок 4.3 — Quality gate · 🟢 (після фіксу)

Працює. Hard gates: hallucinated handles, word count ≥800, title ≤60, meta ≤160, broken external URLs (HEAD-fallback-GET). Soft warnings: `\d+%`, «Dr. X», довгі цитати.

**Залишилися слабкості:**
- Перевірка URL послідовна, не паралельна. 3 URL × 5s timeout = до 15s на статтю.
- HEAD-fallback-GET stream'иться але `resp.close()` не викликається — на коротких статтях це не проблема, але best practice.
- Soft warnings ловлять лише кілька паттернів. Не ловиться: вигадані назви компаній («Acme Labs»), вигадані clinical-trial ID (`NCT-12345`).
- Не валідується heading hierarchy (H3 без H2-батька).
- Не валідується мінімум H2 під стиль.
- Не валідується кількість тегів (промпт каже 3, gate ігнорує).
- Не валідується мова (config каже `en`, але якщо Claude напише пів-рядка українською — пройде).

**Що покращити:**
- HEAD-перевірка: `concurrent.futures.ThreadPoolExecutor(max_workers=4)`.
- Додати `validate_heading_hierarchy(html)` — простий regex.
- Додати soft warning «\b[A-Z][a-z]+ (Labs|Institute|Foundation|University)\b» для quasi-organizations.

### Крок 4.4 — Retry diversification · 🟢 (після фіксу)

Працює. На кожній спробі — наступний стиль зі `ranked_styles(topic)`. На спробі 1 — primary, спроба 2 — alternative1, спроба 3 — alternative2.

**Слабкі місця:**
- Cause-aware retry відсутній. Якщо fail причина — `too short: 650 words`, наступна спроба не отримує підказки «це треба виправити». Просто новий стиль.
- На retry не передається список причин невдачі попередньої спроби в промпт. agency-website робить це і це підіймає success rate з ~60% до ~85% за їхнім досвідом.
- Якщо retry succeed, ми не логуємо що retry був потрібен. Просто публікація. Без logging — не зрозуміти процент retry.

**Що покращити:**
- В `generate_with_quality_gate` тримати `last_failure_reasons` і передавати в `generate_article(... previous_failure=last_failure_reasons)`. Generator інжектить «PREVIOUS ATTEMPT FAILED: <reasons>. Fix these issues.».
- В Telegram сповіщення «Published (after N retries)» — щоб помітити деградацію якості над часом.

### Крок 5 — Images · 🟡 (без змін)

**Актуальні слабкості:**
- Pexels тільки. Стокова якість.
- Запит = повна назва теми. Довгі заголовки — Pexels плутає.
- Тільки 2 inline image, для статей з 5-6 H2 половина без візуалу. Особливо помітно з новими стилями `quick_tips` (8-12 H2) і `myth_busting` (4-6 H2).
- Inline стилі замість CSS-класу.
- Немає Pexels attribution (best practice, не обов'язково).

**Чому стало гостріше:** стиль `quick_tips` має 8-12 H2 — один inline image на 12 секцій виглядає голо. Стиль `comparison` має side-by-side секції, а зображень немає в обох — асиметрія.

**Що покращити:**
- Витягувати ключові слова з теми (regex по nouns, або 1 запит до Claude дешево). `"microcurrent face wand"` замість `"Best Beauty Tech 2026: Microcurrent Wands to At-Home Lasers"`.
- Скейлити count за кількістю H2 (e.g., max(3, len(h2)//2)).
- Винести inline-стилі в `<style>` блок один раз на статтю.

### Крок 6.1 — schema.org JSON-LD · 🟡 (без змін)

**Актуальні слабкості:**
- Базовий Article schema. Немає `mainEntityOfPage`, `wordCount`, `articleSection`, `keywords`.
- **Немає FAQ schema**, хоча FAQ є в КОЖНІЙ статті. Без FAQPage schema Google не показує FAQ rich snippets.
- Немає `Product` schema коли стаття-buyers_guide рекомендує реальні товари — втрачаємо product rich snippets.

**Чому важливо:** з 6 стилями `buyers_guide` і `comparison` особливо виграють від product/comparison schema. Це конкретний SERP-impact, що видно в Search Console за тиждень.

**Що покращити:**
- Парсити `<h3>` всередині FAQ-секції, генерувати FAQPage schema.
- В buyers_guide-статтях парсити `<a href=".../products/...">` лінки, для кожного — Product schema (тільки name + url, без ціни щоб не брехати).

### Крок 6.2 — Публікація · 🟢 (без змін)

Чисто, обробка userErrors, metafield SEO description. Slabost: немає `published: true` явно (Shopify default — true), немає окремого `seo.title` metafield.

### Workflow YAML · 🟡 (без змін)

**Актуальні слабкості:**
- Node 20 actions — deprecated до червня 2026. Треба апнути всі actions до v5/v4 версій з Node 24.
- Немає `timeout-minutes`. Дефолт 360 хв = години простою якщо щось зависне.
- Single store hardcoded. Multi-store потребує matrix strategy.
- Auto-commit без фільтра — комітить будь-яку зміну в `stores/`.

**Що покращити:**
- `timeout-minutes: 30`.
- `actions/checkout@v4`, `actions/setup-python@v5`, `actions/cache@v4` — зараз вони уже на v4/v5, треба перевірити що це Node 24 версії (на 2026-05 — так, але періодично треба апати).
- Дрібно: `git add stores/*/published_slugs.json stores/*/topic_pool.json stores/*/products_cache.json` явно, не `git add stores/`.

### Загальні дірки (без змін)

1. **Telegram-only output, no kill switch.** Немає `enabled: true/false` в config. Якщо треба швидко вимкнути posting — Settings → Actions disable workflow.
2. **Нуль тестів.** Live-test only. `validate_article`, `pick_style`, `topic_pool.add_candidates` — чисті функції, легко покрити pytest'ом.
3. **`--dry-run` flag є в коді, але не використовується в CI.** На PR не запускається dry-run check.
4. **Немає observability.** «Скільки статтей опубліковано?» = git log + grep.
5. **Single language.** Hardcoded EN scoring prefixes, evergreen-теми, style picker rules.

### Підсумок по пріоритетах (станом на 2026-05-10 #2)

| Пункт | Оцінка | Імпакт фіксу |
|---|---|---|
| Product relevance ranking (3) | 🟡 | висока — правильні товари у статті, особливо для buyers_guide |
| FAQ schema (6.1) | 🟡 | висока — конкретний SERP win, FAQ є в кожній статті |
| Topic pool expiry & decay (2.2) | 🟡 | середня — запобігає stale-topic дрейфу |
| Cause-aware retry (4.4) | 🟡 | середня — економить токени, підіймає success rate |
| Image keyword extraction + scaling (5) | 🟡 | середня — quick_tips/myth_busting виглядають голо |
| Save title + article_id + url (1) | 🟡 | низька — UX логів і дебагу |
| RSS query/source diversity (2.1) | 🟡 | середня — підгодовує picker різними стилями |
| Heading hierarchy + style structure check (4.3) | 🟡 | низька — додатковий guard |
| Node action versions + timeout-minutes | 🟡 | низька — до дедлайну є час |
| Tests for pure-function modules | 🟡 | середня — фундамент під майбутні зміни |

### Що змінилось за день (2026-05-10 → 2026-05-10 #2)

- 🔴 → 🟢: Quality gate (додані stats/expert/quote warnings, URL HEAD check, title/meta length).
- 🔴 → 🟢: NEW/CONTINUATION/FORCED classifier (`modules/conflict.py`).
- 🟡 → 🟢: Style templates (`modules/style.py`, 6 шаблонів + picker).
- 🟡 → 🟢: Retry diversification (різний стиль на спробі 1, 2, 3).
- 🟡 (новий за фактом покращення сусіднього): published_topics в промпті — раніше 15, тепер всі.
