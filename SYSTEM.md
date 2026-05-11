# Shopify Blog Poster — як працює система (2026-05-10)

Знімок стану ПІСЛЯ закриття всіх пунктів audit #3 (semantic dedup, product grounding, topic pool, E-E-A-T, slugify DRY, single source of truth для style.min_h2, broaden FAQ regex, Product schema, blog_handle cache, parallel HEAD-checks, API backoff, separate embeddings file). Pipeline зелений, 44 unittest-и проходять локально.

---

## 1. Загальний огляд

- **Тригер:** GitHub Actions, cron `0 7 * * *` (07:00 UTC щодня) + `workflow_dispatch` для ручного запуску.
- **Команда:** `python poster.py --store my-store`.
- **Стейт магазину:** `stores/my-store/` — конфіг, історія, пул тем, кеш товарів, кеш embeddings.
- **Зовнішні API:** Anthropic (Claude Haiku 4.5), Shopify Admin GraphQL 2024-10, Pexels, Google News RSS, Bing News RSS, Telegram.

---

## 2. Запуск і ініціалізація (`poster.py:main`)

1. Парс аргументів: `--store` (обов'язково), `--dry-run` (опціонально).
2. Перевірка існування `stores/<store>/`. Якщо нема — `exit(1)`.
3. **Kill switch:** якщо `config["enabled"] is False` → `exit(0)` (магазин тимчасово вимкнений, GitHub run зелений, нічого не публікується).
4. Завантаження `store_config.json`.

---

## 3. Phase [1/6] — Завантаження історії

- Читає `stores/my-store/published_slugs.json`. Структура запису:
  ```json
  {"slug": "...", "title": "...", "topic": "...", "date": "YYYY-MM-DD",
   "source": "rss|evergreen|ai_generated", "article_id": "gid://...",
   "url": "https://...", "handle": "...", "embedding": [384 floats]}
  ```
- **Backfill embeddings:** для старих записів (де є `topic` але нема `embedding`) обчислює embedding через `dedup.embed()` (sentence-transformers `all-MiniLM-L6-v2`, 384-dim) і зберігає назад.
- Готує два списки: `pub_embeddings` (для cosine-перевірок) та `pub_topics` (для текстових промптів LLM).

---

## 4. Phase [2/6] — Вибір теми (`select_topic`, до 3 fallback-ітерацій)

### 4.1. RSS discovery (`topic_finder.discover_candidates`)

- Формує до 9 пошукових запитів: 5 keywords + niche-шаблони (`best <niche>`, `how to <niche>`, `<niche> 2026`, `<niche> guide`).
- **Два джерела паралельно** для кожного запиту:
  - Google News: `news.google.com/rss/search?q=...`
  - Bing News: `www.bing.com/news/search?q=...&format=RSS`
- Звідти витягує заголовки + лінки → визначає домен джерела через `_domain_from_link` (нормалізує `www.` префікс).
- **Скоринг** (`_score`):
  - база 1.0
  - +0.5 за кожен дубль у різних запитах (max +2.5) — означає що тема популярна
  - +2.0 якщо починається з `how to`, `what is`, `best`, `top`, `why`, `vs`, `is`, `are`
  - +1.0 якщо 5-9 слів
  - +0.5 якщо є `?`
  - +0.5 якщо згадано `2026/2027`
  - **× domain_weight** (1.5 для reuters/wsj/mayoclinic/etc., 1.0 для unknown)
- Повертає топ-25.

### 4.2. Topic Pool (`topic_pool.add_candidates` + `pick_best`)

- Файл: `stores/my-store/topic_pool.json` (макс 100 записів).
- Кожен новий кандидат:
  - Обчислюється embedding.
  - **Відкидається** якщо cosine ≥ 0.75 до будь-якого запису в pool **або** будь-якого опублікованого.
  - Інакше додається з полями `topic`, `score`, `found_date`, `source`, `embedding`.
- **Decay:** при `pick_best` ефективний score = `score - 0.05 × days_since(found_date)`. Старі теми поступово втрачають актуальність.
- **Pick:** найвищий ефективний score, який не дублює published. Якщо знайшов → це тема.

### 4.3. Evergreen банк

- Якщо pool порожній / усі дублі — береться `config["evergreen_topics"]` (25 ручних тем).
- Перша неопублікована (cosine < 0.75) → тема.

### 4.4. AI-replenish

- Якщо й evergreen вичерпано — Claude Haiku генерує 20 нових ідей.
- Промпт: niche + audience + останні 30 опублікованих + 10 категорій-шаблонів + правила (60-80 chars, без клікбейту, без вигаданих брендів).
- Перша не-дубль → тема.

Якщо всі 4 джерела впали → Telegram «No safe topic found», `exit(0)`.

---

## 5. Same-day idempotency (cosine ≥ 0.85)

Між phase 2 і 3 — захист від випадкового подвійного запуску в межах одного дня:

- Бере embeddings всіх записів з `date == today`.
- Якщо знайдена тема має cosine ≥ 0.85 до будь-чого опублікованого сьогодні → Telegram + `exit(0)`.

Це **не** перетинається з 0.75-перевіркою на дубль — той фільтр запобігає схожому контенту з різних запусків, цей запобігає двом постам за день.

---

## 6. Phase [3/6] — Каталог товарів (`products.get_products`)

- Кеш: `stores/my-store/products_cache.json`, TTL 24 години (фіксовано в `_CACHE_TTL_SECONDS`).
- Окремий файл: `stores/my-store/products_embeddings.json` (key = handle, value = 384-dim вектор). Розділення зроблено щоб:
  - кеш-файл лишався читабельним (без сотень тисяч флоатів),
  - embeddings можна було переобчислювати без re-fetch каталогу.
- Якщо кеш свіжий і embeddings є — миттєво. Якщо нема — Shopify GraphQL (`products(first: 50, query: "status:active")`, до 20 сторінок = 1000 max).
- Збирає поля: `title`, `handle`, `description` (truncated 300), `productType`, `tags`.
- **Migration шар:** `_migrate_inline_embeddings` витягує embeddings з legacy-формату (де вони були в кеші), переносить у окремий файл, переписує кеш без них.
- **`_attach_embeddings`:** для нових продуктів обчислює embedding від `title + product_type + tags + description`.
- При помилці запиту (відсутній scope, мережа) → WARN + Telegram, `catalog = []`, стаття пишеться без посилань.

---

## 7. Phase [3.5/6] — Класифікація відносин (`conflict.classify`)

- Викликає Claude Haiku з топ-5 останніх опублікованих тем + новою темою.
- LLM повертає JSON `{"relationship": "NEW|CONTINUATION|FORCED", "related_index": int|null, "rationale": "..."}`.
- **NEW:** standalone, без додаткових інструкцій.
- **CONTINUATION:** генератор отримає блок «In our recent article on X…» — природне internal-linking.
- **FORCED:** генератор отримає блок «While we've previously covered X… take a clearly different angle».
- Парс захищений regex від керуючих символів і markdown-обгорток.
- При будь-якій помилці класифікатора → fallback `{"relationship": "NEW", ...}`.
- Backoff: спільний `_create_with_backoff` з generator.

---

## 8. Phase [4/6] — Генерація з quality gate (`generate_with_quality_gate`)

### 8.1. Підготовка контексту

- **Ranked catalog:** `products.rank_by_relevance(catalog, topic, top_n=15)` — cosine між embedding теми і embedding продукту, продукти без embedding на дно списку.
- **Catalog text:** `format_for_prompt` → `- Title [Type] | URL | description (120 chars)`.
- **Style rotation:** `style.ranked_styles(topic)` — primary за topic + всі інші у стабільному порядку. На retry attempt N → style_order[N % 6].

### 8.2. Прокачування промпту (`generator.generate_article`)

- System prompt — жорсткі правила: ніяких вигаданих брендів/SKU/статистики/цитат, посилання тільки на каталог, 2-3 надійних зовнішніх джерела, чистий JSON.
- User prompt — niche + topic + audience + tone + language + author + катaлог + останні 15 тем + style block + relationship block + previous failure block.
- **Style block** (з `style.render(style_key)`) — 6 форматів:
  - `how_to` (4 H2 min) — Hook + What you'll need + numbered steps + Common mistakes + FAQ + Sources.
  - `comparison` (4 H2 min) — Hook + At a glance + один H2 на опцію + Which to pick + FAQ + Sources.
  - `buyers_guide` (4 H2 min) — Hook + What to look for + Our picks (тільки з каталогу) + Red flags + FAQ + Sources.
  - `deep_dive` (5 H2 min) — Hook + Basics + 3-5 progressive H2 + Practical takeaways + FAQ + Sources.
  - `myth_busting` (4 H2 min) — Hook + How myths spread + 4-6 myth H2 + What works + FAQ + Sources.
  - `quick_tips` (6 H2 min) — Hook + 8-12 tip H2 + Putting it together + FAQ + Sources.
- **Previous failure block:** якщо попередній attempt провалив hard-gate → bullet-list причин (тільки fixable). LLM знає що саме виправити.
- **Relationship block:** інструкція природно посилатися на попередню статтю (для CONTINUATION/FORCED).
- Параметри виклику: `model="claude-haiku-4-5-20251001"`, `max_tokens=8192`.

### 8.3. API backoff (`_create_with_backoff`)

- 4 attempts, sleep `2 ** attempt` між ними (0 + 2 + 4 + 8 = 14s).
- Retryable: `RateLimitError`, `APIConnectionError`, `InternalServerError`. На останній спробі — re-raise.

### 8.4. Парсинг відповіді

- `_parse_json_response` — strip markdown fences, знайти `{...}`, видалити control chars, `json.loads`.

### 8.5. Quality gate (`quality.validate_article`)

**Hard gates** (cause regeneration):
1. **Hallucinated products:** усі `<a href="**/products/<handle>">` з тіла — handle має існувати в catalog.
2. **Length:** ≥ 800 слів (після strip тегів). У git log є коміт що знижував до 350, але поточний код = 800.
3. **Title:** existed, ≤ 60 chars.
4. **Meta description:** existed, ≤ 160 chars.
5. **Structure:** style-specific min H2 count (`style.min_h2(style_key)` — единое джерело правди в `STYLES["...]["min_h2"]`).
6. **Heading hierarchy:** жодного `<h3>` до першого `<h2>`.
7. **Broken external URLs:** усі зовнішні `<a href>` перевіряються — HEAD з fallback на streamed GET (Cloudflare любить блокувати HEAD), 4 паралельних потоки через `ThreadPoolExecutor(max_workers=4)`.

**Soft warnings** (логуються + Telegram, **не** провалюють):
- Numeric stats (`87% of...`).
- `Dr. X`-style experts.
- Long direct quotes (`"…80+ chars…"`).
- Quasi-organizations (`Acme Labs`, `Smith Institute`) — whitelist відомих (Mayo Clinic, Harvard, FDA, etc.).

### 8.6. Cause-aware retry

- `_MAX_GENERATION_RETRIES = 2` → всього 3 спроби.
- Перед кожним retry: `quality.filter_fixable(reasons)` відкидає те що Claude не може виправити (broken external URLs — модель не знає які URL існують).
- Якщо і третя спроба провалила → Telegram + `exit(0)`.

---

## 9. Phase [5/6] — Зображення (`image_fetcher`)

- **Keyword extraction:** `topic_to_keywords(topic)` — drops stopwords, year-числа, punctuation. `"The best retinol serum 2026 guide" → "retinol serum"`.
- **Кількість картинок:** `desired_count = max(3, min(6, 1 + (h2_count - 1) // 2))` — масштабується від кількості H2 у тілі статті.
- **Pexels:**
  - Cover: пошук за keywords, page 1.
  - Inline: пошук за keywords, page 2 (інша сторінка щоб не було дублів cover).
  - Якщо порожньо — fallback за `image_query` з конфігу (`woman skincare beauty`).
- **Розподіл inline:** рівномірно після H2 секцій (`distribute_evenly`), з alt-text = текст відповідного `<h2>` (truncated 120 chars), стилі `width:100%; border-radius:8px; margin:16px 0;`.

---

## 10. Dry-run

`--dry-run` → не публікуємо, друкуємо JSON, виходимо. Embeddings/pool/published не змінюються.

---

## 11. Phase [6/6] — Публікація в Shopify (`publisher.publish_article`)

### 11.1. Blog handle resolve

- `config.get("blog_handle")` → якщо є, використовуємо. Інакше — GraphQL `query BlogHandle($id) { blog(id) { handle } }`.
- При успіху записуємо в `config["blog_handle"]`. **Caller (poster.py)** після `publish_article` порівнює `config != config_before` і викликає `save_config(...)` — тоді у наступному запуску це вже cached.
- В пам'яті — `_blog_handle_cache` (per-process), щоб не робити query двічі за один запуск.

### 11.2. JSON-LD блоки

- **Article schema:** headline, description, datePublished/Modified, author, publisher, wordCount, keywords, image, mainEntityOfPage URL.
- **FAQPage schema:** будується з FAQ-секції тіла. Regex `_FAQ_SECTION_PATTERN` ловить `FAQ`, `FAQs`, `Frequently Asked Questions`, `Questions & Answers`, `Common Questions` (case-insensitive). Кожне `<h3>Q</h3><p>A</p>` → entry.
- **Product schemas:** для кожного унікального `/products/<handle>` що згадується в тілі — окремий schema-блок з `name` (з catalog title, не з anchor), `url` (canonical). Price свідомо опускаємо щоб не вигадувати. Якщо catalog порожній → schemas порожні.

### 11.3. HTML decoration

- На початок: усі JSON-LD `<script type="application/ld+json">` блоки.
- В кінець: `<div class="author-bio">` з ім'ям (ПОСИЛАННЯ якщо `author_url` є) і біо.

### 11.4. GraphQL мутація

- `articleCreate(article: ArticleCreateInput!)` на `https://<domain>/admin/api/2024-10/graphql.json`.
- Variables: `blogId`, `title`, `body` (decorated HTML), `tags`, `author.name`, `image.url` (cover), `metafields[]` з `seo.description`.
- Очікує `userErrors == []`. Якщо є — `RuntimeError`.
- Повертає dict з `id`, `title`, `handle`, `publishedAt`, `blog.handle`, синтезованим `url`.

---

## 12. Запис в історію

```python
pub_records.append({
    "slug": slugify(article["title"]),
    "title": article["title"],
    "topic": topic,
    "date": today,
    "source": pick["source"],
    "article_id": result["id"],
    "url": result.get("url"),
    "handle": result["handle"],
    "embedding": pick["embedding"],
})
```

- `slugify` — спільний з publisher через `modules/slug.py` (one source of truth, ідентичні правила нормалізації).
- `topic_pool.remove(store_path, topic)` — викидаємо тему з pool щоб не була кандидатом завтра.
- Telegram «Published: <title>\n<url>».

---

## 13. Auto-commit (workflow YAML)

Якщо в `stores/` щось змінилось (а воно завжди міняється — щонайменше `published_slugs.json` і `topic_pool.json`):
- `git config user.name "blog-bot"` + email.
- `git add stores/`.
- `git commit -m "log: published blog post YYYY-MM-DD"`.
- `git push`.

---

## 14. Telegram alerts catalog

| Подія | Текст |
|---|---|
| Тема не знайдена | `No safe topic found. Skipping today.` |
| Same-day duplicate | `Already published a near-duplicate today (similarity 0.XX). ...` |
| Products fetch failed | `WARN: product fetch failed: <error>` |
| Soft warnings знайдені | `Quality warnings for '<topic>':\n- ...` |
| Generation failed (3 attempts) | `Generation failed for topic: <topic>\n<ErrorType>: <message>` |
| Published after retries | `Published after N retry(ies) for '<topic>'` |
| Final success | `Published: <title>\n<url>` |

---

## 15. Тести (`tests/test_pure.py` + `.github/workflows/tests.yml`)

- 44 unittest-и, тільки stdlib (без pytest).
- Покриття: StylePicker, QualityValidators (включно з integration test що quality читає `style.min_h2`), ImageHelpers, TopicFinderHelpers, TopicPoolDecay, PublisherHelpers (FAQ regex варіанти, product schema, slugify edge cases), StyleStructureSourceOfTruth.
- CI: `python -m unittest discover -s tests -v` на push/PR в main.
- Тести **не** торкають мережу/диск/sentence-transformers — тільки чисті функції.

---

## 16. Store config schema (`stores/my-store/store_config.json`)

```json
{
  "enabled": true,
  "name": "Store Name",
  "niche": "skincare",
  "shopify_domain": "fheegt-kv.myshopify.com",
  "public_domain": "https://example.com",
  "blog_id": "gid://shopify/Blog/...",
  "blog_handle": "news",  // cached after first run
  "audience": "...",
  "tone": "...",
  "language": "en",
  "author_name": "...",
  "author_bio": "...",
  "author_url": "...",
  "image_query": "woman skincare beauty",
  "keywords": ["...", "...", "...", "...", "..."],
  "evergreen_topics": ["...", "..."]
}
```

---

## 17. GitHub Actions secrets

| Secret | Призначення |
|---|---|
| `ANTHROPIC_API_KEY` | Claude Haiku (генерація + класифікація + replenish) |
| `SHOPIFY_TOKEN` | Admin API (scopes: `read_content`, `write_content`, `read_products`) |
| `PEXELS_KEY` | Зображення |
| `TELEGRAM_BOT_TOKEN` | Сповіщення |
| `TELEGRAM_CHAT_ID` | Куди слати |

---

## 18. Data flow (ASCII) + defense matrix

```
cron 07:00 UTC
   │
   ▼
poster.py main
   │
   ├─[kill switch]─ enabled=false ──► exit(0)
   │
   ├─[1/6] load history ─► backfill embeddings ─► save
   │
   ├─[2/6] select_topic
   │   │
   │   ├─ topic_finder ─► Google News + Bing News (×9 queries)
   │   │       │
   │   │       └─► score (prefix +2.0, len-band +1.0, ?, year, dup, domain×)
   │   │
   │   ├─ topic_pool ─► dedup vs pool+published (cosine 0.75) ─► add ─► pick_best (with decay)
   │   ├─ evergreen.get_unused (cosine 0.75 vs published)
   │   └─ evergreen.replenish (Claude Haiku, 20 ideas)
   │
   ├─[idempotency] cosine 0.85 vs today's published ──► exit(0) if dup
   │
   ├─[3/6] products.get_products
   │   ├─ cache (TTL 24h) + embeddings (separate file, migrate legacy)
   │   └─ Shopify GraphQL (status:active, 50/page, ≤20 pages)
   │
   ├─[3.5/6] conflict.classify ─► Claude Haiku ─► NEW|CONTINUATION|FORCED
   │
   ├─[4/6] generate_with_quality_gate (3 attempts, style rotation)
   │   ├─ rank_by_relevance (cosine topic↔product)
   │   ├─ generator.generate_article
   │   │     └─ _create_with_backoff (4 retries on 429/5xx/conn)
   │   └─ quality.validate_article
   │         ├─ hard: products / length / title / meta / structure / hierarchy
   │         ├─ HEAD-check (parallel ×4) + GET fallback for Cloudflare
   │         └─ soft: stats / experts / quasi-orgs / long quotes
   │
   ├─[5/6] image_fetcher (Pexels) ─► cover + inline distributed across H2s
   │
   ├─[dry-run?] ─► print JSON, exit
   │
   ├─[6/6] publisher.publish_article
   │   ├─ blog_handle (cached config / GraphQL query / process cache)
   │   ├─ JSON-LD: Article + FAQPage + Product schemas
   │   ├─ author bio
   │   └─ articleCreate mutation (+ image + seo.description metafield)
   │
   ├─[journal] append to published_slugs.json
   ├─[pool] remove published topic
   ├─[telegram] Published: <title>
   │
   ▼
workflow yaml: git commit -m "log: published blog post YYYY-MM-DD" + push
```

### Defense matrix

| Загроза | Захист |
|---|---|
| Випадковий подвійний запуск | cosine 0.85 vs today's published ─► exit(0) |
| Той самий контент в інші дні | cosine 0.75 vs all published (pool dedup + evergreen filter) |
| Pool тримає stale теми | decay 0.05/day ефективного score |
| Hallucinated brand/SKU | system prompt + product handle whitelist (hard gate) |
| Hallucinated stats/experts | soft warnings ─► Telegram |
| Stale facts ("dr. acme labs") | quasi-org regex з whitelist реальних orgs |
| Broken sources URL | parallel HEAD ─► GET fallback ─► hard gate (filtered out of retry feedback) |
| LLM ігнорує quality reasons | filter_fixable + previous_failure_block у промпті |
| Один format на retry | style rotation (6 formats × 3 attempts) |
| API rate limit / 5xx | _create_with_backoff (4 retries, 0/2/4/8s) |
| Shopify products scope зник | WARN + Telegram, fallback to empty catalog |
| FAQ schema не будується | broad regex (5 phrases) ловить будь-який варіант секції |
| Slug розбіжність між poster і publisher | modules/slug.py — one source of truth |
| min_h2 розбіжність style ↔ quality | style.STYLES[k]["min_h2"] — one source of truth |
| Embeddings блоат у products_cache | окремий файл products_embeddings.json |
| GitHub run червоний на нормальному skip | exit(0) для всіх planned skip-ів, exit(1) тільки для unrecoverable |
| Магазин тимчасово паузити | enabled: false у store_config.json |
