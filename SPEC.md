# Shopify Blog Poster — Специфікація

Автоматична система що щодня генерує і публікує SEO-оптимізовані статті в блог будь-якого Shopify магазину. Безкоштовно. Без ручного втручання.

---

## Загальні правила

- Завжди аналізуй проблему перед тим як писати код. Розумій чому це потрібно і які будуть наслідки. Якщо не впевнений — не роби.
- Говори простою мовою, без технічного жаргону. Відповідай коротко і по суті. Не тисни після кожного речення питаннями типу "робимо?".
- Коли даєш інструкцію — завжди описуй кожен крок детально: яке посилання відкрити, на яку кнопку натиснути, який пункт меню знайти. Скорочені інструкції типу "створи", "зайди", "налаштуй" — не підходять.
- Ніколи не писати "будь-який текст" або "будь-яка назва" — завжди давати конкретне значення яке треба вставити.
- Коли пояснюєш що було зроблено або що існує — завжди пояснюй простими словами що це таке і яку проблему вирішує. Не просто список назв файлів чи функцій, а зрозуміле пояснення для людини без технічного досвіду.
- Російська мова категорично заборонена — ніколи, навіть якщо попросять.
- Загальні правила зберігати у `/Users/bohdan/My Projects/general MD/`. Правила цього проєкту — у папці проєкту.

---

## Архітектура

```
Google News RSS + Google Trends (pytrends)
              ↓
     Фільтрація та ранжування тем
              ↓
     Перевірка дублів (вже опубліковані)
              ↓
     Groq Llama 4 — генерація статті
              ↓
     Unsplash API — featured image
              ↓
     Markdown → HTML конвертація
              ↓
     Shopify GraphQL API — публікація
              ↓
     GitHub Actions — щоденний cron
```

---

## Блок 1 — Пошук і фільтрація тем

### Джерела (в порядку пріоритету)

**1. Google News RSS** — головне джерело, безкоштовно, без API ключа
- URL формат: `https://news.google.com/rss/search?q={query}&hl=en-US&gl=US&ceid=US:en`
- Запит будується динамічно на основі ніші магазину з `store_config.json`
- Приклад для fashion магазину: `sustainable fashion 2026`, `clothing trends`
- Приклад для tech магазину: `gadgets 2026`, `smart home trends`
- Дає свіжі новини за останні 24-48 годин — завжди актуально

**2. pytrends — Google Trends** — для перевірки популярності
- Бере топ 5 кандидатів з Google News
- Перевіряє їх trending score за останні 7 днів
- Відкидає теми з низьким інтересом
- Безкоштовно, без API ключа (неофіційний інтерфейс)
- Ризик: може бути заблокований Google → fallback на RSS без перевірки

**3. Fallback — статичні теми з конфігу**
- Якщо обидва джерела недоступні — бере з `evergreen_topics` в конфізі
- Вічнозелені теми що завжди в пошуку (how-to, buyer's guide тощо)

### Фільтрація
- Мінімум 2 джерела згадують тему → вища пріоритетність
- Виключити теми що вже є в `published_slugs.json`
- Виключити теми що не релевантні до ніші (перевірка через Groq — один короткий запит)
- Перевага темам з питальними заголовками ("How to", "What is", "Best") — вони краще ранкуються

---

## Блок 2 — Конфігурація магазину

Система підтримує **будь-який магазин** через конфіг файл. Один конфіг = один магазин.

### `stores/my-store/store_config.json`
```json
{
  "name": "My Shopify Store",
  "shopify_domain": "my-store.myshopify.com",
  "blog_id": "gid://shopify/Blog/123456789",
  "niche": "sustainable fashion",
  "audience": "eco-conscious women aged 25-40",
  "keywords": ["sustainable fashion", "ethical clothing", "eco friendly outfits"],
  "author": "Jane Doe",
  "language": "en",
  "tone": "friendly and informative",
  "internal_links": [
    {"anchor": "our collection", "url": "https://my-store.myshopify.com/collections/all"},
    {"anchor": "summer dresses", "url": "https://my-store.myshopify.com/collections/dresses"}
  ],
  "evergreen_topics": [
    "how to build a sustainable wardrobe",
    "best eco-friendly fabrics guide",
    "capsule wardrobe for beginners"
  ],
  "unsplash_query": "sustainable fashion clothing"
}
```

### Секрети (GitHub Secrets або `.env` локально)
```
SHOPIFY_ACCESS_TOKEN_MY_STORE=shpat_xxx
GROQ_API_KEY=gsk_xxx
UNSPLASH_ACCESS_KEY=xxx
```

---

## Блок 3 — Генерація статті

### Модель
- **Groq Llama 4 Maverick** (або Llama 3.3 70B як fallback)
- Безкоштовно, швидко (~3-5 сек на статтю)

### Промпт стратегія
Промпт отримує з конфігу:
- нішу магазину
- цільову аудиторію
- тон
- список внутрішніх посилань для вставки
- список вже опублікованих тем (щоб не повторюватись)

Промпт вимагає від AI:
- 1000-1500 слів
- структуру: hook → проблема → рішення → H2/H3 секції → CTA → FAQ
- органічно вставити 1-2 внутрішніх посилання на продукти
- не вигадувати статистику
- повернути чистий HTML (не Markdown — Shopify приймає HTML)

### Формат відповіді
```json
{
  "title": "...",
  "meta_description": "...",
  "tags": ["tag1", "tag2"],
  "html_body": "<h2>...</h2><p>...</p>..."
}
```

AI повертає JSON — легко парсити, без проблем з frontmatter.

---

## Блок 4 — Зображення

**Unsplash API** — безкоштовно (50 запитів/годину на free tier)
- Запит: `unsplash_query` з конфігу магазину
- Бере перше фото з ліцензією для комерційного використання
- Передає URL напряму в Shopify (не завантажує локально)

Fallback: якщо Unsplash недоступний — публікує без зображення.

---

## Блок 5 — Публікація в Shopify

**GraphQL Admin API** — безкоштовно, без лімітів на статті

```python
mutation articleCreate($article: ArticleCreateInput!) {
  articleCreate(article: $article) {
    article {
      id
      title
      handle
      publishedAt
    }
  }
}
```

Поля що передаються:
- `blogId` — з конфігу
- `title` — з AI
- `body` — HTML з AI
- `tags` — з AI
- `image.url` — з Unsplash
- `metafields` — meta description для SEO
- `published: true` — публікується одразу

### Отримання blog_id
```python
# Один раз запускається вручну щоб знайти ID блогу
query { blogs(first: 10) { nodes { id title } } }
```

---

## Блок 6 — Запис опублікованих тем

Після кожної публікації скрипт дописує в `stores/my-store/published_slugs.json`:
```json
[
  {"slug": "how-to-build-sustainable-wardrobe", "date": "2026-05-04"},
  {"slug": "best-eco-fabrics-guide", "date": "2026-05-05"}
]
```

Цей файл комітується в репо після кожного запуску — GitHub Actions це робить автоматично.

---

## Блок 7 — GitHub Actions

### Один магазин
```yaml
name: Daily Blog Post
on:
  schedule:
    - cron: "0 7 * * *"
  workflow_dispatch:
jobs:
  post:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with: { python-version: "3.12" }
      - run: pip install groq requests pytrends markdown
      - run: python poster.py --store my-store
        env:
          GROQ_API_KEY: ${{ secrets.GROQ_API_KEY }}
          SHOPIFY_TOKEN: ${{ secrets.SHOPIFY_ACCESS_TOKEN_MY_STORE }}
          UNSPLASH_KEY: ${{ secrets.UNSPLASH_ACCESS_KEY }}
      - run: |
          git config user.name "blog-bot"
          git config user.email "bot@agency.com"
          git add stores/
          git diff --cached --quiet || git commit -m "log: published blog post $(date +%Y-%m-%d)"
          git push
```

### Кілька магазинів
Один workflow — matrix strategy:
```yaml
strategy:
  matrix:
    store: [my-store, client-store-1, client-store-2]
```

---

## Структура файлів

```
shopify-blog-poster/
├── poster.py                  # головний скрипт
├── modules/
│   ├── topic_finder.py        # Google News RSS + pytrends
│   ├── generator.py           # Groq генерація
│   ├── publisher.py           # Shopify GraphQL API
│   └── image_fetcher.py       # Unsplash API
├── stores/
│   └── my-store/
│       ├── store_config.json
│       └── published_slugs.json
├── .github/
│   └── workflows/
│       └── daily-blog.yml
├── requirements.txt
└── SPEC.md
```

---

## Що потрібно для запуску (один раз)

1. Shopify: Settings → Apps → Develop apps → Create app → scope `write_content` → Install → скопіювати токен
2. Groq: console.groq.com → API Keys → Create (безкоштовно)
3. Unsplash: unsplash.com/developers → New Application → скопіювати Access Key (безкоштовно)
4. GitHub: додати всі токени в Secrets репозиторію
5. Знайти blog_id через GraphQL playground (один запит)
6. Заповнити `store_config.json`

---

## Відомі ризики та обмеження

| Ризик | Ймовірність | Рішення |
|---|---|---|
| pytrends заблокований Google | Середня | Fallback на RSS без перевірки трендів |
| Groq rate limit (free tier) | Низька | 30 req/min — для 1 статті/день достатньо |
| AI генерує повторну тему | Середня | Перевірка published_slugs.json |
| Unsplash 50 req/hour limit | Низька | 1 запит/день — ніколи не досягнемо |
| Shopify API змінює структуру | Низька | Моніторити changelog Shopify |
| AI контент без E-E-A-T | Висока | Додати авторський контекст в промпт |

---

## Наступні кроки

- [ ] Реалізувати `topic_finder.py`
- [ ] Реалізувати `generator.py`
- [ ] Реалізувати `publisher.py`
- [ ] Реалізувати `image_fetcher.py`
- [ ] Написати `poster.py` (головний скрипт)
- [ ] Налаштувати GitHub Actions
- [ ] Тестовий запуск на одному магазині
