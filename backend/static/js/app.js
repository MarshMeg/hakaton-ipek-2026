/* Ядро приложения на клиенте: вход, сохранение прогресса и его синхронизация, словарь,
 * статистика и мост во Flutter. Страницы и /content.json берутся из офлайн-снимка, поэтому
 * после первого входа всё работает без сети.
 *
 * Прогресс — одно «сохранение» на аккаунт (формат v2, см. play/api.py) в localStorage
 * (SAVE_KEY) с копией во Flutter (файл на телефоне), чтобы пережить очистку данных WebView.
 * При синхронизации более новое сохранение (по полю updated) заменяет старое целиком.
 * Настройки (звук, напоминание) входят в сохранение (блок settings) и едут
 * вместе с прогрессом на другой телефон; SETTINGS_KEY — их локальный кэш. Аккаунт (AUTH_KEY)
 * лежит отдельно.
 *
 * Код намеренно без новейшего синтаксиса: приложение должно работать на Android 8.
 */
(function () {
  'use strict';

  var SAVE_VERSION = 2;
  var SAVE_KEY = 'zb.save.v2';
  var AUTH_KEY = 'zb.auth.v1';
  var SETTINGS_KEY = 'zb.settings.v1'; // кэш settings из сохранения
  var SETTINGS_DEFAULTS = { sound: true, notifications: false };
  var OLD_STATE_KEY = 'zb.state.v1'; // журнал событий старых версий, переводится в сохранение
  var BOOTED_KEY = 'zb.booted'; // sessionStorage: синхронизация при запуске уже была
  var XP_PER_CORRECT = 10;
  var AVATARS = ['🦊', '🐻', '🐰', '🐿️', '🦔', '🐺', '🐱', '🐶', '🦉', '🐝'];
  var HARD_CLEARED_AFTER = 3; // столько верных ответов подряд — и слово больше не «трудное»
  // Игра «Трудные слова» и кнопка «Повторить» в профиле — только с таким числом трудных слов:
  // меньше — играть не во что, одно слово повторялось бы раз за разом.
  var HARD_MIN = 3;
  var HARD_SHOWN = 5; // столько трудных слов показывает профиль
  var LEARNED_MIN_OK = 2; // «выучено» — не меньше стольких верных ответов
  var CHART_DAYS = 14; // дней на графике «Ответы за 14 дней»
  var MINUTE_MS = 60000;
  var DAY_MS = 86400000;
  var BRIDGE_WAIT_MS = 1500;
  var SYNC_TIMEOUT_MS = 5000;
  var KEEPALIVE_LIMIT = 60000; // fetch keepalive не отправит тело больше 64 КБ
  var NO_NETWORK = 'Для первого входа нужен интернет';

  // ---------- утилиты ----------

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  // Ключ дня по местному времени телефона, например '2026-10-20'. Им размечен блок days.
  function dayKey(ts) {
    var d = new Date(ts);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function shuffle(list) {
    var a = list.slice();
    for (var i = a.length - 1; i > 0; i--) {
      var j = Math.floor(Math.random() * (i + 1));
      var t = a[i]; a[i] = a[j]; a[j] = t;
    }
    return a;
  }

  function sample(list, n) { return shuffle(list).slice(0, n); }

  function escapeHtml(s) {
    return String(s).replace(/[&<>"']/g, function (c) {
      return { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c];
    });
  }

  // Параметр из адресной строки, например param('topic') для /games/choose/?topic=numbers.
  function param(name) {
    var m = new RegExp('[?&]' + name + '=([^&#]*)').exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  // localStorage может быть недоступен или в нём лежит мусор — тогда просто null, без падения.
  function readJSON(storage, key) {
    try {
      var raw = storage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { console.warn('read', key, e); return null; }
  }

  // null удаляет ключ совсем.
  function writeJSON(storage, key, value) {
    try {
      if (value === null) storage.removeItem(key);
      else storage.setItem(key, JSON.stringify(value));
    } catch (e) { console.warn('write', key, e); }
  }

  // ---------- мост во Flutter ----------

  // flutter_inappwebview создаёт window.flutter_inappwebview до загрузки страницы, а приложение
  // дописывает «VotesApp» в User-Agent. В обычном браузере не ждём моста вовсе.
  var inApp = !!window.flutter_inappwebview || /VotesApp/.test(navigator.userAgent);

  var Bridge = {
    /* Promise<boolean>: доступен ли мост. В приложении callHandler появляется не сразу —
     * ждём событие flutterInAppWebViewPlatformReady, но не дольше BRIDGE_WAIT_MS, чтобы старт не завис,
     * если мост так и не поднялся. Без моста все Bridge.call просто возвращают undefined. */
    ready: new Promise(function (resolve) {
      if (!inApp) return resolve(false);
      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) return resolve(true);
      window.addEventListener('flutterInAppWebViewPlatformReady', function () { resolve(true); });
      setTimeout(function () { resolve(false); }, BRIDGE_WAIT_MS);
    }),
    available: function () {
      return !!(window.flutter_inappwebview && window.flutter_inappwebview.callHandler);
    },
    call: function (name) {
      var args = Array.prototype.slice.call(arguments, 1);
      return Bridge.ready.then(function () {
        if (!Bridge.available()) return undefined;
        var h = window.flutter_inappwebview;
        return h.callHandler.apply(h, [name].concat(args));
      }).catch(function (e) { console.warn('bridge', name, e); return undefined; });
    },
  };

  // ---------- сервер ----------

  // Ошибка «нет сети»: по флагу network вызывающий код понимает, что сервер просто недоступен.
  function networkError() {
    var err = new Error(NO_NETWORK);
    err.network = true;
    return err;
  }

  /* У fetch нет своего тайм-аута: при плохой связи запрос может висеть минутами. Тайм-аут
   * считаем отсутствием сети (err.network) — дальше работаем с локальным сохранением. */
  function withTimeout(promise, ms) {
    if (!ms) return promise;
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () { reject(networkError()); }, ms);
      promise.then(
        function (v) { clearTimeout(timer); resolve(v); },
        function (e) { clearTimeout(timer); reject(e); }
      );
    });
  }

  /* Запрос к /api/. Ошибка сети — err.network, ответ не 2xx — err.status и err.data. */
  function api(method, path, body, opts) {
    opts = opts || {};
    var request = fetch(path, requestInit(method, body, opts))
      .catch(function () { throw networkError(); })
      .then(readResponse);
    return withTimeout(request, opts.timeout);
  }

  // Параметры fetch: токен в заголовке, тело в JSON. keepalive — только для небольших тел.
  function requestInit(method, body, opts) {
    var init = { method: method, headers: {} };
    if (opts.token) init.headers.Authorization = 'Bearer ' + opts.token;
    if (body === undefined) return init;
    init.headers['Content-Type'] = 'application/json';
    init.body = JSON.stringify(body);
    if (opts.keepalive && init.body.length < KEEPALIVE_LIMIT) init.keepalive = true;
    return init;
  }

  // Ответ сервера → данные. Не 2xx — ошибка с текстом от сервера (или общим, если его нет).
  function readResponse(r) {
    return r.json().catch(function () { return {}; }).then(function (data) {
      if (r.ok) return data;
      var err = new Error(data.error || 'Ошибка сервера (' + r.status + ')');
      err.status = r.status;
      err.data = data;
      throw err;
    });
  }

  // ---------- настройки ----------

  /* Только известные булевы ключи; чего нет или что не булево — из fallback (по умолчанию —
   * SETTINGS_DEFAULTS). Так же чистит настройки сервер (clean_settings в play/api.py). */
  function cleanSettings(raw, fallback) {
    var out = {};
    raw = raw && typeof raw === 'object' ? raw : {};
    fallback = fallback || SETTINGS_DEFAULTS;
    for (var k in SETTINGS_DEFAULTS) {
      out[k] = typeof raw[k] === 'boolean' ? raw[k] : fallback[k];
    }
    return out;
  }

  /* values — настройки из сохранения (кэш в SETTINGS_KEY, чтобы работали и до входа). */
  var Settings = {
    values: cleanSettings(readJSON(window.localStorage, SETTINGS_KEY)),

    /* Изменение игроком: в сохранение через Save.commit (растёт updated, уходит на сервер). */
    set: function (key, value) {
      this.values[key] = value;
      writeJSON(window.localStorage, SETTINGS_KEY, this.values);
      var changed = Save.data && Save.data.settings[key] !== value;
      if (!changed || !Save.commit(function (s) { s.settings[key] = value; })) notify();
    },

    /* Настройки из сохранения, пришедшего с сервера или из копии во Flutter. Если напоминание
     * на этом устройстве было в другом состоянии — включаем или выключаем его через мост. */
    apply: function (settings) {
      var prev = this.values;
      this.values = cleanSettings(settings, prev);
      writeJSON(window.localStorage, SETTINGS_KEY, this.values);
      if (this.values.notifications !== prev.notifications) {
        Bridge.call('setNotifications', this.values.notifications);
      }
    },
  };

  // ---------- аккаунт ----------

  /* {username, token, synced}. После 401 токен стирается, а имя остаётся: так при входе
   * в другой аккаунт видно, что локальное сохранение чужое. */
  var Auth = {
    get: function () { return readJSON(window.localStorage, AUTH_KEY); },
    token: function () { var a = this.get(); return a && a.token; },
    set: function (auth) { writeJSON(window.localStorage, AUTH_KEY, auth); backup(); notify(); },
    patch: function (fields) {
      var a = this.get();
      if (!a) return;
      for (var k in fields) a[k] = fields[k];
      this.set(a);
    },
  };

  // ---------- сохранение ----------

  function emptySave(name, avatar) {
    return {
      v: SAVE_VERSION, updated: 0, profile: { name: name || '', avatar: avatar || '' },
      words: {}, days: {}, games: {}, settings: cleanSettings(Settings.values),
    };
  }

  /* Приводит сохранение (из localStorage, с сервера, из копии во Flutter) к полному виду v2.
   * Чужая версия или не объект — null. */
  function normalizeSave(s) {
    if (!s || typeof s !== 'object' || s.v !== SAVE_VERSION) return null;
    var base = emptySave();
    base.updated = typeof s.updated === 'number' ? s.updated : 0;
    ['profile', 'words', 'days', 'games'].forEach(function (k) {
      if (s[k] && typeof s[k] === 'object') base[k] = s[k];
    });
    // В сохранениях до появления настроек блока нет — берём то, что было на этом устройстве.
    base.settings = cleanSettings(s.settings, Settings.values);
    return base;
  }

  // save новее, чем than (или than нет вовсе) — тогда save заменяет than.
  function isNewer(save, than) {
    return !than || save.updated > than.updated;
  }

  /* Записи прогресса по слову, дню и игре. Создаются при первом обращении, поэтому в
   * сохранении есть только то, во что уже играли. */
  function wordEntry(save, id) {
    save.words[id] = save.words[id] || { ok: 0, bad: 0, seen: 0, last: 0 };
    return save.words[id];
  }

  function dayEntry(save, ts) {
    var key = dayKey(ts);
    save.days[key] = save.days[key] || { ok: 0, bad: 0, seen: 0 };
    return save.days[key];
  }

  function gameEntry(save, slug) {
    save.games[slug] = save.games[slug] || { ok: 0, bad: 0, played: 0, best: 0 };
    return save.games[slug];
  }

  // Есть ли что терять: хотя бы одно слово или день в сохранении.
  function hasProgress(save) {
    return !!save && (Object.keys(save.words).length > 0 || Object.keys(save.days).length > 0);
  }

  /* Журнал событий старой версии (zb.state.v1) → сохранение v2 активного профиля. */
  function fromEvents(state) {
    var profile = state.profiles && state.profiles[state.active];
    if (!profile) return null;
    var save = emptySave(profile.name, profile.avatar);
    save.updated = profile.updated || 0;
    (state.events || []).forEach(function (event) {
      if (event.p === state.active) addEvent(save, event);
    });
    return { save: save, account: profile.account || null };
  }

  /* Одно событие журнала: {w: слово, t: время, c: верно/неверно, g: игра}. Без c — это
   * просмотр карточки, а не ответ. */
  function addEvent(save, event) {
    save.updated = Math.max(save.updated, event.t);
    var word = wordEntry(save, event.w);
    var day = dayEntry(save, event.t);
    word.last = Math.max(word.last, event.t);
    if (event.c === null || event.c === undefined) {
      word.seen++;
      day.seen++;
      return;
    }
    var game = gameEntry(save, event.g);
    var field = event.c ? 'ok' : 'bad';
    word[field]++;
    day[field]++;
    game[field]++;
  }

  /* Переход со старого формата: прогресс сохраняется, токен — тоже, если он был. */
  function migrateOldState(state) {
    // Не через Settings.set: commit поднял бы updated текущего сохранения, и прогресс из
    // журнала ниже проиграл бы ему. Настройки попадут в сохранение через emptySave.
    if (state && state.settings && !readJSON(window.localStorage, SETTINGS_KEY)) {
      Settings.apply(state.settings);
    }
    var old = fromEvents(state || {});
    if (!old) return;
    if (isNewer(old.save, Save.data)) Save.replace(old.save);
    if (!Auth.get() && old.account && old.account.token) {
      Auth.set({ username: old.account.username, token: old.account.token, synced: 0 });
    }
  }

  // Подписчики на изменение сохранения или входа (Save.onChange). Главный — store.refresh().
  var listeners = [];

  function notify() { listeners.forEach(function (fn) { fn(); }); }

  // Копия {save, auth} во Flutter (bridge.dart → save.json). В браузере ничего не делает.
  function backup() {
    Bridge.call('backup', JSON.stringify({ save: Save.data, auth: Auth.get() }));
  }

  /* Одновременно идёт не больше одного PUT. pushing — Promise текущей отправки; если за время
   * отправки сохранение снова изменилось, ставим pushAgain, и по окончании уходит ещё один PUT
   * уже со свежими данными. Так отправки не обгоняют друг друга и не получают лишних 409. */
  var pushing = null;
  var pushAgain = false;

  var Save = {
    data: normalizeSave(readJSON(window.localStorage, SAVE_KEY)),

    get: function () { return this.data; },

    onChange: function (fn) { listeners.push(fn); },

    /* Заменить сохранение целиком (серверным, из копии во Flutter, при выходе — null). */
    replace: function (save) {
      this.data = save ? normalizeSave(save) : null;
      if (this.data) Settings.apply(this.data.settings);
      writeJSON(window.localStorage, SAVE_KEY, this.data);
      backup();
      notify();
    },

    /* Конечное действие (игра завершена, карточки просмотрены, изменён профиль): изменить
     * сохранение, записать его на телефоне и сразу отправить на сервер. */
    commit: function (mutator, opts) {
      if (!this.data) return null;
      mutator(this.data);
      // updated обязан строго расти: по нему сервер и другие устройства решают, чьё сохранение
      // новее. Если часы телефона отстают от прошлой записи (перевели время, сохранение пришло
      // с другого устройства), берём «прошлое + 1 мс», иначе изменение проиграло бы старому.
      this.data.updated = Math.max(Date.now(), this.data.updated + 1);
      writeJSON(window.localStorage, SAVE_KEY, this.data);
      backup();
      notify();
      return this.push(opts);
    },

    /* PUT /api/save. Возвращает Promise<boolean>: удалось ли отправить. Без сети сохранение
     * остаётся на телефоне и уйдёт при следующем запуске. */
    push: function (opts) {
      var self = this;
      if (pushing) { pushAgain = true; return pushing; }
      var token = Auth.token();
      if (!token || !this.data) return Promise.resolve(false);
      var keepalive = opts && opts.keepalive;
      pushing = api('PUT', '/api/save', { save: this.data }, { token: token, keepalive: keepalive })
        .then(function () {
          Auth.patch({ synced: Date.now() });
          return true;
        }, pushFailed)
        .then(function (ok) {
          pushing = null;
          var again = pushAgain && self.data !== null;
          pushAgain = false;
          return again ? self.push() : ok;
        });
      return pushing;
    },
  };

  /* Отправка не удалась. 409 — на сервере другое сохранение: если оно новее (другой телефон
   * успел раньше), принимаем его, а если пока ждали ответ, локальное успело обогнать
   * серверное, — отправим ещё раз. 401 — токен больше не действует. Всегда false. */
  function pushFailed(err) {
    if (err.status === 409 && err.data && err.data.save) {
      if (err.data.save.updated > Save.data.updated) Save.replace(err.data.save);
      else pushAgain = true;
    } else if (err.status === 401) {
      expireAuth();
    }
    return false;
  }

  // Кэш настроек и сохранение на телефоне должны совпадать (сохранение главнее).
  if (Save.data) Settings.apply(Save.data.settings);

  // ---------- вход и синхронизация ----------

  var Boot = { phase: 'loading', onPhase: null };

  function setPhase(phase) {
    Boot.phase = phase;
    if (Boot.onPhase) Boot.onPhase(phase);
  }

  function expireAuth() {
    var a = Auth.get();
    Auth.set(a ? { username: a.username, token: null, synced: a.synced || 0 } : null);
    setPhase('auth');
  }

  /* Шаг 3 цикла: сравнить локальное сохранение с серверным, победитель заменяет проигравшего. */
  function syncSave() {
    var token = Auth.token();
    if (!token) return Promise.resolve();
    return api('GET', '/api/save', undefined, { token: token, timeout: SYNC_TIMEOUT_MS })
      .then(function (data) { return adopt(data.save); })
      .catch(function (err) {
        if (err.status === 401) expireAuth();
        // Нет сети или тайм-аут — продолжаем с локальным сохранением.
      });
  }

  /* Серверное сохранение новее — берём его, иначе (локальное новее или такое же) отправляем
   * своё на сервер. */
  function adopt(server) {
    server = normalizeSave(server);
    if (server && isNewer(server, Save.data)) {
      Save.replace(server);
      return Promise.resolve();
    }
    return Save.push();
  }

  /* Копия во Flutter переживает очистку WebView: берём её, если она новее. В копии может
   * лежать и старый журнал событий (zb.state.v1) — тогда переводим его в сохранение. */
  function restoreBackup() {
    return Bridge.call('restore').then(function (raw) {
      var copy = parseBackup(raw);
      if (!copy) return;
      if (copy.events && copy.profiles) { migrateOldState(copy); return; }
      var save = normalizeSave(copy.save);
      if (save && isNewer(save, Save.data)) Save.replace(save);
      if (copy.auth && copy.auth.token && !Auth.token()) Auth.set(copy.auth);
    });
  }

  // Строка из Flutter → объект. Копии нет или в ней мусор — null.
  function parseBackup(raw) {
    if (!raw) return null;
    try { return JSON.parse(raw); } catch (e) { return null; }
  }

  /* Запуск на каждой странице. Сайт многостраничный: любой переход — полная перезагрузка, и
   * boot() выполняется снова. Полный цикл (копия из Flutter → вход → синхронизация с сервером)
   * нужен один раз за запуск приложения, поэтому после него ставим флаг в sessionStorage
   * (живёт, пока открыт WebView) и на следующих страницах сразу переходим в 'ready'.
   * Фазы: loading — заставка, auth — окно входа (_auth.html), ready — можно играть. */
  function boot() {
    migrateOldStorage();
    var booted = readJSON(window.sessionStorage, BOOTED_KEY);
    if (booted && Auth.token() && Save.data) { setPhase('ready'); return; }
    setPhase('loading');
    restoreBackup().then(function () {
      if (!Auth.token()) { setPhase('auth'); return null; }
      return syncSave().then(finishBoot);
    }).catch(function (e) {
      console.error('boot', e);
      setPhase(Auth.token() ? 'ready' : 'auth');
    });
  }

  // Журнал старой версии в localStorage переводим в сохранение и удаляем.
  function migrateOldStorage() {
    var old = readJSON(window.localStorage, OLD_STATE_KEY);
    if (!old) return;
    migrateOldState(old);
    writeJSON(window.localStorage, OLD_STATE_KEY, null);
  }

  // Синхронизация прошла (или сети нет). Если токен за это время не протух — можно играть.
  function finishBoot() {
    if (Boot.phase === 'auth') return;
    if (!Save.data) Save.replace(emptySave());
    enterGame();
  }

  // Флаг «запуск пройден» в sessionStorage и фаза ready: на следующих страницах цикл не нужен.
  function enterGame() {
    writeJSON(window.sessionStorage, BOOTED_KEY, true);
    setPhase('ready');
  }

  /* После входа или регистрации: запоминаем аккаунт. Если на телефоне лежит сохранение
   * другого аккаунта — выбрасываем его. */
  function rememberAccount(data) {
    var prev = Auth.get();
    if (prev && prev.username && prev.username !== data.username) Save.replace(null);
    Auth.set({ username: data.username, token: data.token, synced: 0 });
  }

  /* Регистрация. Если на телефоне уже есть прогресс без аккаунта (перешёл со старой версии),
   * он уходит в новый аккаунт, а имя и зверёк берутся из формы. */
  function signup(form) {
    var auth = Auth.get();
    var keepLocal = hasProgress(Save.data) && !(auth && auth.username);
    return api('POST', '/api/signup', {
      username: form.username, password: form.password,
      name: form.name, avatar: form.avatar, updated: Date.now(),
    }).then(function (data) {
      rememberAccount(data);
      if (keepLocal) {
        Save.commit(function (s) { s.profile = { name: form.name, avatar: form.avatar }; });
      } else {
        Save.replace(data.save);
      }
      enterGame();
    });
  }

  function login(username, password) {
    return api('POST', '/api/login', { username: username, password: password })
      .then(function (data) {
        rememberAccount(data);
        // Не ждём: если серверное сохранение новее, adopt подменит его сразу (синхронно),
        // а если новее локальное — отправка на сервер пойдёт в фоне, играть можно уже сейчас.
        adopt(data.save);
        enterGame();
      });
  }

  /* Выход: сначала пробуем отправить сохранение. Возвращает false, если игрок передумал. */
  function logout() {
    return Save.push().then(function (ok) {
      if (!ok && !window.confirm('Не получилось отправить прогресс на сервер. Если выйти сейчас, ' +
          'несохранённый прогресс пропадёт. Всё равно выйти?')) return false;
      Save.replace(null);
      Auth.set(null);
      writeJSON(window.sessionStorage, BOOTED_KEY, null);
      setPhase('auth');
      return true;
    });
  }

  // ---------- словарь ----------

  var contentPromise = null;

  // /content.json грузится один раз за страницу, все игры получают один и тот же Promise.
  var Content = {
    load: function () {
      if (!contentPromise) {
        contentPromise = fetch('/content.json').then(function (r) { return r.json(); }).then(prepare);
      }
      return contentPromise;
    },
  };

  // Добавляет к словарю индексы: wordById, topicBySlug и topic.words — чтобы игры не искали
  // слова перебором каждый раз.
  function prepare(c) {
    c.wordById = {};
    c.topicBySlug = {};
    c.topics.forEach(function (t) { t.words = []; c.topicBySlug[t.slug] = t; });
    c.words.forEach(function (w) {
      c.wordById[w.id] = w;
      var t = c.topicBySlug[w.topic];
      if (t) t.words.push(w);
    });
    return c;
  }

  /* «Картинка» слова: файл, цветной круг, цифра или эмодзи. Пустая строка — картинки нет. */
  function pic(word) {
    if (!word) return '';
    if (word.img) return '<img src="' + escapeHtml(word.img) + '" alt="" class="h-full w-full object-contain">';
    if (word.color) {
      return '<span class="block h-full w-full rounded-full border-4 border-line-soft" style="background:' +
        escapeHtml(word.color) + '"></span>';
    }
    var text = word.number != null ? word.number : word.emoji;
    if (text == null || text === '') return '';
    return '<span class="flex h-full w-full items-center justify-center font-extrabold leading-none">' +
      escapeHtml(text) + '</span>';
  }

  /* Все признаки картинки слова в том же порядке, в каком pic() выбирает, что показать:
   * файл, цвет, цифра, эмодзи. */
  function picKeys(word) {
    return [word.img && 'i' + word.img, word.color && 'c' + word.color,
      word.number != null && 'n' + word.number, word.emoji && 'e' + word.emoji].filter(Boolean);
  }

  /* Ключ картинки: у двух слов с одинаковым ключом картинки не различить (👧 «апай» и «нылы»). */
  function picKey(word) {
    return picKeys(word)[0] || '';
  }

  /* Похожи ли картинки двух слов. Сравниваются все признаки картинки, а не только показанный:
   * у «узы» (земляника) есть только 🍓, а у «боры» (клубника) фото и тот же 🍓 в словаре —
   * ребёнок их не различит, хотя picKey у них разный. */
  function samePic(a, b) {
    var keysB = picKeys(b);
    return picKeys(a).some(function (key) { return keysB.indexOf(key) >= 0; });
  }

  function playAudio(word) {
    if (!word || !word.audio || !Settings.values.sound) return;
    try { new Audio(word.audio).play(); } catch (e) { /* без звука */ }
  }

  // ---------- прогресс ----------

  /* Итоги сыгранной игры: answers — [{w: id слова, ok: true/false}], stars — 1…3. */
  function addGame(save, slug, answers, stars) {
    var now = Date.now();
    var day = dayEntry(save, now);
    var game = gameEntry(save, slug);
    answers.forEach(function (answer) {
      var word = wordEntry(save, answer.w);
      var field = answer.ok ? 'ok' : 'bad';
      word[field]++;
      day[field]++;
      game[field]++;
      word.streak = answer.ok ? (word.streak || 0) + 1 : 0;
      word.last = now;
    });
    game.played++;
    game.best = Math.max(game.best || 0, stars);
  }

  // Слово трудное, если в нём ошибались и серия верных ответов после этого ещё короткая.
  function isHard(w) {
    return w.bad > 0 && (w.streak || 0) < HARD_CLEARED_AFTER;
  }

  // «Выучено»: хотя бы два верных ответа, верных больше, чем ошибок, и слово не «трудное»
  // (иначе оно попало бы и в «Выученные», и в «Чаще ошибаешься»).
  function isLearned(w) {
    return w.ok >= LEARNED_MIN_OK && w.ok > w.bad && !isHard(w);
  }

  /* «Трудные» слова: в них ошибались, и после этого ещё не ответили верно HARD_CLEARED_AFTER
   * раз подряд (поле streak; в старых сохранениях его нет — считаем, что серия 0). Сначала
   * слова с большим числом ошибок. Возвращает [{word, ok, bad, streak}]. */
  function hardWords(save, content) {
    if (!save || !content) return [];
    var byWord = save.words;
    return Object.keys(byWord)
      .filter(function (id) {
        return isHard(byWord[id]) && content.wordById[id];
      })
      .sort(function (a, b) {
        return byWord[b].bad - byWord[a].bad || (byWord[a].streak || 0) - (byWord[b].streak || 0);
      })
      .map(function (id) {
        var w = byWord[id];
        return { word: content.wordById[id], ok: w.ok, bad: w.bad, streak: w.streak || 0 };
      });
  }

  /* Просмотренные карточки темы: ids — id слов. */
  function addViews(save, ids) {
    var now = Date.now();
    var day = dayEntry(save, now);
    ids.forEach(function (id) {
      var word = wordEntry(save, id);
      word.seen++;
      word.last = now;
      day.seen++;
    });
  }

  /* Карточки темы: просмотры копятся на странице и записываются одним сохранением при уходе
   * со страницы или по кнопке «Готово». Одна карточка за визит считается один раз. */
  function cardViews() {
    return {
      seenIds: {},
      pending: [],

      init: function () {
        var self = this;
        window.addEventListener('pagehide', function () { self.flush(true); });
        document.addEventListener('visibilitychange', function () {
          if (document.visibilityState === 'hidden') self.flush(true);
        });
      },

      see: function (id) {
        if (this.seenIds[id]) return;
        this.seenIds[id] = true;
        this.pending.push(id);
      },

      flush: function (keepalive) {
        if (!this.pending.length) return Promise.resolve(false);
        var ids = this.pending;
        this.pending = [];
        return Save.commit(function (s) { addViews(s, ids); }, { keepalive: keepalive }) || Promise.resolve(false);
      },

      done: function (url) {
        this.flush(true);
        window.location.href = url;
      },
    };
  }

  // ---------- статистика ----------

  /* Вся статистика для шаблонов ($store.app.stats) считается заново из сохранения: опыт,
   * серия дней, точность, выученные и трудные слова, график за 14 дней, прогресс по темам.
   * content может быть null (словарь ещё грузится) — тогда то, что зависит от слов, пустое. */
  function computeStats(save, content) {
    save = save || emptySave();
    var byWord = save.words;
    var days = save.days;
    var totals = answerTotals(byWord);
    var ok = totals.ok;
    var bad = totals.bad;

    var learnedIds = Object.keys(byWord).filter(function (id) { return isLearned(byWord[id]); });
    var seenIds = Object.keys(byWord).filter(function (id) { return byWord[id].seen > 0; });
    // Слово могли удалить из словаря, а в сохранении оно осталось — такие не считаем.
    var known = function (id) { return !content || content.wordById[id]; };
    var allHard = hardWords(save, content);
    var daily = dailyChart(days);

    return {
      xp: ok * XP_PER_CORRECT,
      streak: dayStreak(days),
      answers: ok + bad,
      correct: ok,
      wrong: bad,
      accuracy: percent(ok, ok + bad),
      activeDays: Object.keys(days).filter(function (key) { return isStudyDay(days[key]); }).length,
      learned: learnedIds.filter(known).length,
      learnedWords: content ? learnedIds.filter(known).map(function (id) { return content.wordById[id]; }) : [],
      seen: seenIds.filter(known).length,
      totalWords: content ? content.words.length : 0,
      hard: allHard.slice(0, HARD_SHOWN),
      hardCount: allHard.length,
      hardPlayable: allHard.length >= HARD_MIN,
      daily: daily,
      maxDay: chartMax(daily),
      byGame: save.games,
      topics: content ? topicProgress(content, byWord, learnedIds) : [],
      byWord: byWord,
    };
  }

  // Сколько всего верных и неверных ответов по всем словам.
  function answerTotals(byWord) {
    var totals = { ok: 0, bad: 0 };
    Object.keys(byWord).forEach(function (id) {
      totals.ok += byWord[id].ok || 0;
      totals.bad += byWord[id].bad || 0;
    });
    return totals;
  }

  // День занятий — день, когда получен опыт (хотя бы один верный ответ в игре). Просмотр
  // карточек в «Обучении» его не делает: иначе одна открытая карточка продлевала бы серию.
  function isStudyDay(day) {
    return !!day && day.ok > 0;
  }

  // Серия дней: считаем от сегодня (или от вчера, если сегодня ещё не занимались).
  function dayStreak(days) {
    var streak = 0;
    var t = Date.now();
    if (!isStudyDay(days[dayKey(t)])) t -= DAY_MS;
    while (isStudyDay(days[dayKey(t)])) {
      streak++;
      t -= DAY_MS;
    }
    return streak;
  }

  // Столбики графика «Ответы за 14 дней» (_daily_chart.html), от самого старого дня к сегодня.
  function dailyChart(days) {
    var now = Date.now();
    var chart = [];
    for (var i = CHART_DAYS - 1; i >= 0; i--) {
      var ts = now - i * DAY_MS;
      var key = dayKey(ts);
      var day = days[key] || { ok: 0, bad: 0, seen: 0 };
      chart.push({ key: key, label: new Date(ts).getDate(), ok: day.ok, bad: day.bad, seen: day.seen });
    }
    return chart;
  }

  // Высота самого высокого столбика; минимум 1, чтобы не делить на ноль, когда ответов ещё нет.
  function chartMax(chart) {
    return Math.max.apply(null, chart.map(function (d) { return d.ok + d.bad; }).concat([1]));
  }

  // Прогресс по каждой теме: сколько слов выучено и сколько уже встречалось (в процентах тоже).
  function topicProgress(content, byWord, learnedIds) {
    return content.topics.map(function (topic) {
      var learned = topic.words.filter(function (w) { return learnedIds.indexOf(String(w.id)) >= 0; });
      // Просмотренные карточки или слова, уже встречавшиеся в играх.
      var seen = topic.words.filter(function (w) {
        var s = byWord[w.id];
        return s && (s.seen || s.ok || s.bad);
      });
      var total = topic.words.length;
      return {
        slug: topic.slug, title: topic.title, icon: topic.icon, total: total,
        learned: learned.length,
        percent: percent(learned.length, total),
        seen: seen.length,
        seenPercent: percent(seen.length, total),
      };
    });
  }

  function percent(part, total) {
    return total ? Math.round(100 * part / total) : 0;
  }

  var KNUTH_HASH = 2654435761; // мультипликативный хэш Кнута

  /* Слово дня: одно и то же весь день, у всех детей одинаковое. */
  function wordOfDay(content) {
    var pool = content.words.filter(function (w) {
      var t = content.topicBySlug[w.topic];
      return t && t.kind !== 'phrases';
    });
    if (!pool.length) return null;
    // Номер дня по местному времени (смещение пояса вычитаем, чтобы слово менялось в полночь,
    // а не в 3:00 по Москве). Умножение на KNUTH_HASH перемешивает номера, чтобы слова шли
    // не подряд по словарю; >>> 0 оставляет результат неотрицательным 32-битным.
    var now = new Date();
    var day = Math.floor((now.getTime() - now.getTimezoneOffset() * MINUTE_MS) / DAY_MS);
    return pool[((day * KNUTH_HASH) >>> 0) % pool.length];
  }

  // ---------- звуки ----------

  var audioCtx = null;

  // Ноты каждого звука (частоты в Гц) и их тайминги в секундах.
  var NOTES = { ok: [660, 880], bad: [220, 165], win: [523, 659, 784, 1046], flip: [440] };
  var DEFAULT_NOTES = [440];
  var NOTE_STEP = 0.12; // шаг между нотами
  var NOTE_ATTACK = 0.02; // нарастание громкости
  var NOTE_FADE = 0.25; // к этому моменту нота затихает
  var NOTE_STOP = 0.3;
  var NOTE_VOLUME = 0.25;
  var SILENCE = 0.0001; // exponentialRamp не умеет идти от нуля, поэтому «тишина» — почти ноль

  /* Короткие звуки синтезируются Web Audio, без файлов: каждая нота — синусоида (у ошибки —
   * «треугольник») с быстрой атакой и затуханием за 0,25 с, ноты идут с шагом 0,12 с. */
  var Sound = {
    play: function (kind) {
      if (!Settings.values.sound) return;
      try {
        var AC = window.AudioContext || window.webkitAudioContext;
        audioCtx = audioCtx || new AC();
        var wave = kind === 'bad' ? 'triangle' : 'sine';
        (NOTES[kind] || DEFAULT_NOTES).forEach(function (freq, i) {
          playNote(freq, wave, audioCtx.currentTime + i * NOTE_STEP);
        });
      } catch (e) { /* звук не обязателен */ }
    },
  };

  // Одна нота: генератор нужной формы волны через регулятор громкости, начиная с момента start.
  function playNote(freq, wave, start) {
    var osc = audioCtx.createOscillator();
    var gain = audioCtx.createGain();
    osc.type = wave;
    osc.frequency.value = freq;
    gain.gain.setValueAtTime(SILENCE, start);
    gain.gain.exponentialRampToValueAtTime(NOTE_VOLUME, start + NOTE_ATTACK);
    gain.gain.exponentialRampToValueAtTime(SILENCE, start + NOTE_FADE);
    osc.connect(gain);
    gain.connect(audioCtx.destination);
    osc.start(start);
    osc.stop(start + NOTE_STOP);
  }

  // ---------- Alpine ----------

  /* Профиль для шаблонов: name и avatar — что показывать (без имени — логин аккаунта, без
   * зверька — первый из AVATARS), ownName и ownAvatar — что сохранено, для формы правки. */
  function shownProfile(p, account) {
    var name = (p.name || '').trim();
    return {
      name: name || (account ? account.username : ''),
      avatar: p.avatar || AVATARS[0],
      ownName: name,
      ownAvatar: p.avatar || '',
    };
  }

  document.addEventListener('alpine:init', function () {
    var Alpine = window.Alpine;
    Alpine.store('app', {
      // loading — заставка на время синхронизации, auth — окно входа, ready — игра.
      phase: 'loading',
      profile: null,
      account: null,
      settings: Object.assign({}, Settings.values),
      stats: computeStats(null, null),
      content: null,
      ready: false,

      /* Пересобирает всё, что показывают шаблоны, после любого изменения сохранения, входа
       * или словаря. profile пуст, пока не 'ready': так шапка не мелькает за окном входа. */
      refresh: function () {
        var save = Save.data;
        var auth = Auth.get();
        this.account = auth && auth.token ? { username: auth.username, synced: auth.synced || 0 } : null;
        this.profile = save && Boot.phase === 'ready' ? shownProfile(save.profile, this.account) : null;
        this.settings = Object.assign({}, Settings.values);
        this.stats = computeStats(save, this.content);
      },
    });

    var store = Alpine.store('app');
    Save.onChange(function () { store.refresh(); });
    Boot.onPhase = function (phase) { store.phase = phase; store.refresh(); };
    boot();
    store.phase = Boot.phase;
    store.refresh();
    Content.load().then(function (c) {
      store.content = c;
      store.ready = true;
      store.refresh();
    }).catch(function (e) { console.error('content', e); store.ready = true; });
  });

  // Всё, что нужно шаблонам и games.js, доступно через window.ZB.
  window.ZB = {
    Save: Save, Auth: Auth, Settings: Settings, Content: Content, Bridge: Bridge, Sound: Sound,
    computeStats: computeStats, wordOfDay: wordOfDay, fromEvents: fromEvents, emptySave: emptySave,
    addGame: addGame, addViews: addViews, cardViews: cardViews,
    hardWords: hardWords, HARD_CLEARED_AFTER: HARD_CLEARED_AFTER, HARD_MIN: HARD_MIN,
    pic: pic, picKey: picKey, samePic: samePic, playAudio: playAudio,
    signup: signup, login: login, logout: logout,
    shuffle: shuffle, sample: sample, param: param, dayKey: dayKey,
    AVATARS: AVATARS,
  };
})();
