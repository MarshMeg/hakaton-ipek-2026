# Клиент: `app.js`, `games.js`, шаблоны

Вся логика игрока — на клиенте, в `backend/static/js/`. Сервер отдаёт одинаковые для всех страницы
(Django Templates + Tailwind) и словарь `/content.json`; прогресс, статистику и игры считает JS.
Схема и формат сохранения — в [ARCHITECTURE.md](ARCHITECTURE.md).

- Alpine.js **3.14.8**, лежит в `backend/static/vendor/alpine.min.js` (без CDN — нужен офлайн).
- Код — обычный ES2017 без сборки и модулей (в `app.js`/`games.js` — `var` и `function`): WebView Android 8.
- Порядок в `base.html`: `app.js` → `games.js` → `alpine.min.js`, все с `defer`. Компоненты и store
  регистрируются в обработчике `alpine:init`, поэтому должны быть загружены раньше Alpine.
- Классы Tailwind из JS тоже попадают в `app.css`: Tailwind CLI сканирует `templates/` и `static/js/`.

## `app.js`

Один IIFE, наружу — объект `window.ZB`. Разделы файла:

| Раздел | Что делает |
|---|---|
| утилиты | `dayKey(ts)` (`YYYY-MM-DD` по местному времени), `shuffle`, `sample`, `param`, `escapeHtml`, `readJSON`/`writeJSON` с `try/catch` |
| мост во Flutter | `ZB.Bridge` — `ready` (Promise, ждёт `flutterInAppWebViewPlatformReady` не дольше 1,5 с), `available()`, `call(имя, …)`; без моста `call` возвращает `undefined` |
| сервер | `api(method, path, body, opts)` — `fetch` к `/api/` с Bearer-токеном; ошибка сети или тайм-аут → `err.network`, не 2xx → `err.status` и `err.data` |
| настройки | `ZB.Settings` — `values`, `set(key, value)` (через `Save.commit`), `apply(settings)` (из пришедшего сохранения, включает/выключает напоминание через мост), `geoEnabled()` |
| аккаунт | `ZB.Auth` — `{username, token, synced}` в `zb.auth.v1` |
| сохранение | `ZB.Save` — `data`, `get()`, `onChange(fn)`, `replace(save)`, `commit(mutator, opts)`, `push(opts)` |
| вход и синхронизация | `boot()`, `syncSave()`, `adopt()`, `restoreBackup()`, `signup`, `login`, `logout` |
| словарь | `ZB.Content.load()` — один Promise на страницу; `prepare` добавляет `wordById`, `topicBySlug`, `topic.words` |
| картинки | `pic(word)` — HTML «картинки»: файл → цветной круг → цифра → эмодзи; `picKey(word)`; `samePic(a, b)` |
| прогресс | `addGame`, `addViews`, `cardViews()`, `hardWords`, `isHard` |
| статистика | `computeStats(save, content)`, `wordOfDay(content)` |
| звук | `ZB.Sound.play('ok' \| 'bad' \| 'win' \| 'flip')` — синтез через Web Audio, без файлов; `playAudio(word)` — аудио слова |
| геолокация | `locate()` (сначала мост, потом `navigator.geolocation`), `distanceKm`, `IZHEVSK` |
| Alpine | `Alpine.store('app')` |

### Хранилище на телефоне

| Ключ | Где | Что |
|---|---|---|
| `zb.save.v2` | localStorage | сохранение (копия — `save.json` во Flutter через `backup`) |
| `zb.auth.v1` | localStorage | `{username, token, synced}`; после 401 токен стирается, имя остаётся |
| `zb.settings.v1` | localStorage | кэш блока `settings` из сохранения |
| `zb.geo.device` | localStorage | геолокация разрешена на этом устройстве |
| `zb.state.v1` | localStorage | журнал старой версии; при загрузке сворачивается в сохранение (`fromEvents`) и удаляется |
| `zb.booted` | sessionStorage | полный цикл запуска уже пройден в этом WebView |

### Сохранение

- `Save.commit(mutator)` — единственный способ изменить прогресс. Вызывается на конечных действиях:
  игра пройдена (`finish` в `games.js`), карточки темы записаны (`cardViews().flush`), профиль
  изменён, переключена настройка. Ставит `updated = max(Date.now(), updated + 1)` — значение строго
  растёт, даже если часы телефона отстали, — пишет в localStorage, делает `backup()` и `push()`.
- `push()` — `PUT /api/save`. Одновременно идёт один запрос; изменения за время отправки уходят
  следующим (`pushAgain`). 409 → если серверное новее, `replace(серверное)`, иначе повтор;
  401 → окно входа. Без сети сохранение остаётся на телефоне.
- `replace(save)` — заменить целиком (серверным, из копии во Flutter, при выходе — `null`),
  применить настройки, сделать копию и уведомить подписчиков.

### Запуск страницы (`boot`)

Сайт многостраничный, `boot()` выполняется на каждой странице:

1. Старый журнал `zb.state.v1`, если есть, переводится в сохранение.
2. Если `zb.booted` уже стоит, есть токен и сохранение — сразу `phase = 'ready'`.
3. Иначе `phase = 'loading'`: `restoreBackup()` (копия из Flutter, если она новее) → нет токена —
   `phase = 'auth'` → `syncSave()` (`GET /api/save` с тайм-аутом 5 с, `adopt`: новее серверное —
   заменить, иначе отправить своё) → `zb.booted` → `phase = 'ready'`.

`signup` переносит в новый аккаунт локальный прогресс без аккаунта (переход со старой версии), иначе
берёт пустое серверное сохранение. `login` выбрасывает локальное сохранение другого аккаунта и
вызывает `adopt(серверное)` без ожидания. `logout` сначала пробует `push()` и при неудаче спрашивает
подтверждение.

### `Alpine.store('app')`

| Поле | Значение |
|---|---|
| `phase` | `loading` (заставка в `base.html`) \| `auth` (окно `_auth.html`) \| `ready` |
| `profile` | `{name, avatar, ownName, ownAvatar}` — только в фазе `ready`; без имени показывается логин, без зверька — первый из `AVATARS` |
| `account` | `{username, synced}` или `null` |
| `settings` | `Settings.values`, где `geo` = `geoEnabled()` |
| `stats` | результат `computeStats` |
| `content`, `ready` | словарь и флаг «словарь загружен» |
| `refresh()` | пересчитывает всё выше; вызывается на `Save.onChange`, смене фазы и загрузке словаря |

### `computeStats(save, content)`

Считается заново из агрегатов сохранения при каждом `refresh()`:

| Поле | Как считается |
|---|---|
| `xp` | сумма `ok` по всем словам × 10 |
| `streak` | дни подряд, где `days[день].ok > 0`, начиная с сегодня, а если сегодня ещё нет верных ответов — со вчера. Просмотр карточек (`seen`) день не засчитывает |
| `activeDays` | число дней с `ok > 0` |
| `answers`, `correct`, `wrong`, `accuracy` | сумма `ok + bad`, `ok`, `bad`, `round(100·ok/(ok+bad))` |
| `learned`, `learnedWords` | слова с `ok ≥ 2`, `ok > bad` и не трудные; удалённые из словаря не считаются |
| `seen`, `totalWords` | слова с `seen > 0`; всего слов в словаре |
| `hard`, `hardCount`, `hardPlayable` | первые 5 из `hardWords`, их число, `hardCount ≥ HARD_MIN` (3) |
| `daily`, `maxDay` | 14 дней `{key, label, ok, bad, seen}` для графика `_daily_chart.html`; `maxDay` ≥ 1 |
| `topics` | по каждой теме: `total`, `learned`, `percent`, `seen` (карточка просмотрена или слово было в игре), `seenPercent` |
| `byGame`, `byWord` | блоки `games` и `words` сохранения как есть |

Трудное слово (`isHard`): `bad > 0` и `streak < HARD_CLEARED_AFTER` (3). `hardWords` сортирует по
`bad` по убыванию, затем по `streak` по возрастанию.

`wordOfDay(content)` — слово из тем не `phrases`, индекс — номер дня по местному времени × 2654435761
(`>>> 0`) по модулю размера пула: весь день одно и то же, у всех одинаковое.

`cardViews()` — компонент страницы темы: `see(id)` копит открытые карточки (одна карточка — один
раз за визит), `flush()` записывает их одним `commit` при `pagehide`, скрытии вкладки или по кнопке
«Готово» (`done(url)`).

## `games.js`

Шесть игр и режим «Трудные слова» — компоненты `Alpine.data(slug, …)`. Имя компонента совпадает со
slug в `play/games.py`, `game.html` пишет `x-data="{{ game.slug }}"` и подключает
`templates/play/games/<slug>.html`.

### Общая основа `base(slug, extra)`

Поля: `loading`, `content`, `topic` (из `?topic=`), `rounds` (8), `round`, `score`, `maxScore`,
`done`, `empty`, `answers` (`[{w, ok}]`), `feedback` (`'ok' | 'bad' | null`), `message`, `recent`.
Поля и методы `extra` перекрывают общие.

| Метод | Что делает |
|---|---|
| `init` | загружает словарь, сбрасывает неизвестную тему, вызывает `start` |
| `setTopic(slug)` | меняет `?topic=` через `history.replaceState` и перезапускает |
| `start` | сбрасывает счёт и ответы, вызывает `newRound` (его обязана определить каждая игра) |
| `pool(filter)` | слова выбранной темы или все |
| `pickFresh(pool)` | случайное слово, не из последних min(4, ½ пула) |
| `distractors(target, n, field)` | неверные варианты: сначала из той же темы, потом из всех; синонимы отсеиваются и по `ru`, и по `udm` |
| `log(word, ok)`, `answer(word, ok)` | записать ответ; `answer` ещё считает очко, ставит `feedback` и играет звук |
| `next`, `autoNext` | следующий раунд; после верного ответа — сам через 0,9 с |
| `finish` | `done = true`, один `ZB.Save.commit(addGame(...))`, звук победы |
| `stars` | доля верных ≥ 0,9 → 3, ≥ 0,6 → 2, иначе 1 |

Ответы копятся в `this.answers` и попадают в сохранение только в `finish()`: брошенная на середине
игра прогресс не меняет.

### Игры

| slug | Игра | Раунды | Особенности |
|---|---|---|---|
| `choose` | Выбери перевод | 8 | 4 варианта; чётные раунды удм → рус (и звук слова), нечётные — картинка/рус → удм. Вариант с тем же текстом, что у правильного, тоже верный |
| `odd` | Найди лишнее | 8 | 3 слова из темы (не `phrases`, ≥ 3 слов) + 1 из темы другого `family`; картинки скрыты до подсказки или ответа |
| `sort` | Сортировка | 3 | набор из `content.sorting`, где в каждой группе есть слова; наборы не повторяются, пока не сыграны все; 2 корзинки × 3 слова или 3+ × 2; в счёт идёт только первая попытка по слову; перетаскивание pointer-событиями (порог 8 px) или «нажми слово, потом корзинку»; `maxScore` = число слов за партию |
| `memory` | Найди пару | 1 | до 6 слов с разным `ru` (в теме меньше 3 — из всего словаря); пара — `udm` + картинка, а если картинки нет или такая уже есть (`picKey`) — `udm` + перевод; звёзды по ходам: ≤ пар + 2 → 3, ≤ 2 × пар → 2 |
| `assemble` | Собери слово | 8 | слова не из `phrases`, одно слово 2–10 букв (`SINGLE_WORD`); буквы в нижнем регистре, перемешиваются заново, если совпали с ответом; проверка, когда расставлены все |
| `truefalse` | Правда или ложь | 8 | в половине раундов показывается другое слово — с другим переводом и непохожей картинкой (`ZB.samePic`); подменить нечем — раунд «верно». Ответ записывается на показанное слово |
| `hard` | Трудные слова | min(8, 2 × слов) | механика `choose` по `ZB.hardWords` (до 10 слов); нужно ≥ `HARD_MIN` (3), иначе `empty` и объяснение; очередь слов без повторов подряд; после игры `cleared` — сколько слов вышли из трудных |

`hard` собирается так: `base('hard', chooseRounds())`, затем запоминаются `start`/`finish` от
`choose` и поверх кладутся свои, которые их вызывают. Если сохранение пришло с сервера уже после
открытия страницы, `Save.onChange` перезапускает пустой режим.

Общие хелперы для картинок и звука (`ZB.pic`, `ZB.picKey`, `ZB.samePic`, `ZB.playAudio`) живут в
`app.js`, игры берут их через `ZB`.

## Шаблоны

| Шаблон | Компонент / данные |
|---|---|
| `base.html` | `<body x-data>`, шапка (🔥 серия, ⭐ опыт, аватар), нижнее меню, заставка `loading`, `_auth.html`, русские тексты HTML5-валидации |
| `_auth.html` | `authWindow()` — шаги «привет» → «впервые?» → форма регистрации/входа; без сети — «Для первого входа нужен интернет» |
| `play/game.html` | обёртка игры: выбор темы (если `by_topic`), правила, прогресс, общая панель ответа, экран итогов |
| `play/profile.html` | `profilePage()` — правка имени и зверька, прогресс, трудные слова, аккаунт и выход, факты |
| `play/report.html` | `reportPage()` — отчёт; «Поделиться»: мост → `navigator.share` → буфер обмена |
| `play/settings.html` | `settingsPage()` — переключатели (`_toggle.html`), версия словаря и снимка (`Bridge.call('info')`) |
| `vocab/topic.html` | `ZB.cardViews()` + у каждой карточки свой `x-data="{ open }"` |
| `vocab/_pic.html` | серверная версия `ZB.pic` для карточек |

## Подводные камни Alpine 3

- **Все поля компонента объявляются в его данных.** Методы вызываются на объединённом прокси
  (`mergeProxies`): запись в поле, которого нет ни в одном объекте стека, уходит в самый внешний
  — пустой `x-data` на `<body>`. Тогда код, который читает поле у самого компонента, видит
  `undefined`. Так было с `usedSets` / `usedWords` в «Сортировке» (C1): во втором раунде падал
  `indexOf`. Поэтому в `sort()` они объявлены с пустыми значениями, а у `hard` объявлен `queue`.
- **`x-show` и `:style` на одном элементе.** `:style` со строкой перезаписывает атрибут `style` и
  стирает `display: none` от `x-show`. В `sort.html` плитка прячется классом `hidden`.
- **Вложенные `x-data`.** Внутренний компонент видит поля и методы внешнего: карточка в
  `topic.html` вызывает `see()` из `cardViews()`.
- **Данные из `$store` в `x-data` — через геттер** (`get t() { … }`, `get word() { … }`): так
  значение пересчитывается при `store.refresh()`.
- **`x-cloak`** прячет элементы, зависящие от профиля и фазы, до запуска Alpine, чтобы шапка не
  мелькала за окном входа.
