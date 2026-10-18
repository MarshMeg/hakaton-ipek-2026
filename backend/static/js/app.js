/* Ядро приложения на клиенте: вход, сохранение прогресса и его синхронизация, словарь,
 * статистика и мост во Flutter. Страницы и /content.json берутся из офлайн-снимка, поэтому
 * после первого входа всё работает без сети.
 *
 * Прогресс — одно «сохранение» на аккаунт (формат v2, см. play/api.py) в localStorage
 * (SAVE_KEY) с копией во Flutter (файл на телефоне), чтобы пережить очистку данных WebView.
 * При синхронизации более новое сохранение (по полю updated) заменяет старое целиком.
 * Настройки (звук, напоминание, геолокация) входят в сохранение (блок settings) и едут
 * вместе с прогрессом на другой телефон; SETTINGS_KEY — их локальный кэш. Аккаунт (AUTH_KEY)
 * лежит отдельно.
 *
 * Код намеренно без новейшего синтаксиса: приложение должно работать на Android 8.
 */
(function () {
  'use strict';

  var SAVE_KEY = 'zb.save.v2';
  var AUTH_KEY = 'zb.auth.v1';
  var SETTINGS_KEY = 'zb.settings.v1'; // кэш settings из сохранения
  var GEO_DEVICE_KEY = 'zb.geo.device'; // на этом устройстве геолокация уже разрешена
  var SETTINGS_DEFAULTS = { sound: true, notifications: false, geo: false };
  var OLD_STATE_KEY = 'zb.state.v1'; // журнал событий старых версий, переводится в сохранение
  var BOOTED_KEY = 'zb.booted'; // sessionStorage: синхронизация при запуске уже была
  var XP_PER_CORRECT = 10;
  var AVATARS = ['🦊', '🐻', '🐰', '🐿️', '🦔', '🐺', '🐱', '🐶', '🦉', '🐝'];
  var HARD_CLEARED_AFTER = 3; // столько верных ответов подряд — и слово больше не «трудное»
  var DAY_MS = 86400000;
  var SYNC_TIMEOUT_MS = 5000;
  var KEEPALIVE_LIMIT = 60000; // fetch keepalive не отправит тело больше 64 КБ
  var NO_NETWORK = 'Для первого входа нужен интернет';

  // ---------- утилиты ----------

  function pad(n) { return n < 10 ? '0' + n : String(n); }

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

  function param(name) {
    var m = new RegExp('[?&]' + name + '=([^&#]*)').exec(window.location.search);
    return m ? decodeURIComponent(m[1]) : '';
  }

  function readJSON(storage, key) {
    try {
      var raw = storage.getItem(key);
      return raw ? JSON.parse(raw) : null;
    } catch (e) { console.warn('read', key, e); return null; }
  }

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
     * ждём событие flutterInAppWebViewPlatformReady, но не дольше 1,5 с, чтобы старт не завис,
     * если мост так и не поднялся. Без моста все Bridge.call просто возвращают undefined. */
    ready: new Promise(function (resolve) {
      if (!inApp) return resolve(false);
      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) return resolve(true);
      window.addEventListener('flutterInAppWebViewPlatformReady', function () { resolve(true); });
      setTimeout(function () { resolve(false); }, 1500);
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

  /* У fetch нет своего тайм-аута: при плохой связи запрос может висеть минутами. Тайм-аут
   * считаем отсутствием сети (err.network) — дальше работаем с локальным сохранением. */
  function withTimeout(promise, ms) {
    if (!ms) return promise;
    return new Promise(function (resolve, reject) {
      var timer = setTimeout(function () {
        var err = new Error(NO_NETWORK);
        err.network = true;
        reject(err);
      }, ms);
      promise.then(
        function (v) { clearTimeout(timer); resolve(v); },
        function (e) { clearTimeout(timer); reject(e); }
      );
    });
  }

  /* Запрос к /api/. Ошибка сети — err.network, ответ не 2xx — err.status и err.data. */
  function api(method, path, body, opts) {
    opts = opts || {};
    var init = { method: method, headers: {} };
    if (opts.token) init.headers.Authorization = 'Bearer ' + opts.token;
    if (body !== undefined) {
      init.headers['Content-Type'] = 'application/json';
      init.body = JSON.stringify(body);
      if (opts.keepalive && init.body.length < KEEPALIVE_LIMIT) init.keepalive = true;
    }
    var request = fetch(path, init).catch(function () {
      var err = new Error(NO_NETWORK);
      err.network = true;
      throw err;
    }).then(function (r) {
      return r.json().catch(function () { return {}; }).then(function (data) {
        if (!r.ok) {
          var err = new Error(data.error || 'Ошибка сервера (' + r.status + ')');
          err.status = r.status;
          err.data = data;
          throw err;
        }
        return data;
      });
    });
    return withTimeout(request, opts.timeout);
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

  /* values — настройки из сохранения (кэш в SETTINGS_KEY, чтобы работали и до входа).
   * Геолокация показывается, только если включена в аккаунте И разрешена на этом устройстве
   * (geoEnabled): пришедшее с другого телефона geo=true не вызывает запрос разрешения молча. */
  var Settings = {
    values: cleanSettings(readJSON(window.localStorage, SETTINGS_KEY)),

    geoAllowed: function () { return !!readJSON(window.localStorage, GEO_DEVICE_KEY); },

    geoEnabled: function () { return this.values.geo && this.geoAllowed(); },

    /* Изменение игроком: в сохранение через Save.commit (растёт updated, уходит на сервер). */
    set: function (key, value) {
      if (key === 'geo' && value) writeJSON(window.localStorage, GEO_DEVICE_KEY, true);
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
      v: 2, updated: 0, profile: { name: name || '', avatar: avatar || '' },
      words: {}, days: {}, games: {}, settings: cleanSettings(Settings.values),
    };
  }

  function normalizeSave(s) {
    if (!s || typeof s !== 'object' || s.v !== 2) return null;
    var base = emptySave();
    base.updated = typeof s.updated === 'number' ? s.updated : 0;
    ['profile', 'words', 'days', 'games'].forEach(function (k) {
      if (s[k] && typeof s[k] === 'object') base[k] = s[k];
    });
    // В сохранениях до появления настроек блока нет — берём то, что было на этом устройстве.
    base.settings = cleanSettings(s.settings, Settings.values);
    return base;
  }

  function hasProgress(save) {
    return !!save && (Object.keys(save.words).length > 0 || Object.keys(save.days).length > 0);
  }

  /* Журнал событий старой версии (zb.state.v1) → сохранение v2 активного профиля.
   * Та же свёртка, что в миграции на сервере (accounts/migrations/0005_profile_save.py). */
  function fromEvents(state) {
    var p = state.profiles && state.profiles[state.active];
    if (!p) return null;
    var save = emptySave(p.name, p.avatar);
    save.updated = p.updated || 0;
    (state.events || []).forEach(function (e) {
      if (e.p !== state.active) return;
      save.updated = Math.max(save.updated, e.t);
      var w = save.words[e.w] = save.words[e.w] || { ok: 0, bad: 0, seen: 0, last: 0 };
      var key = dayKey(e.t);
      var d = save.days[key] = save.days[key] || { ok: 0, bad: 0, seen: 0 };
      w.last = Math.max(w.last, e.t);
      if (e.c === null || e.c === undefined) { w.seen++; d.seen++; return; }
      var g = save.games[e.g] = save.games[e.g] || { ok: 0, bad: 0, played: 0, best: 0 };
      var field = e.c ? 'ok' : 'bad';
      w[field]++; d[field]++; g[field]++;
    });
    return { save: save, account: p.account || null };
  }

  /* Переход со старого формата: прогресс сохраняется, токен — тоже, если он был. */
  function migrateOldState(state) {
    // Не через Settings.set: commit поднял бы updated текущего сохранения, и прогресс из
    // журнала ниже проиграл бы ему. Настройки попадут в сохранение через emptySave.
    if (state && state.settings && !readJSON(window.localStorage, SETTINGS_KEY)) {
      if (state.settings.geo) writeJSON(window.localStorage, GEO_DEVICE_KEY, true);
      Settings.apply(state.settings);
    }
    var old = fromEvents(state || {});
    if (!old) return;
    var current = Save.data;
    if (!current || old.save.updated > current.updated) Save.replace(old.save);
    if (!Auth.get() && old.account && old.account.token) {
      Auth.set({ username: old.account.username, token: old.account.token, synced: 0 });
    }
  }

  var listeners = [];

  function notify() { listeners.forEach(function (fn) { fn(); }); }

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
      var sent = this.data;
      pushing = api('PUT', '/api/save', { save: sent }, { token: token, keepalive: opts && opts.keepalive })
        .then(function () {
          Auth.patch({ synced: Date.now() });
          return true;
        }, function (err) {
          if (err.status === 409 && err.data && err.data.save) {
            // На сервере новее (другой телефон успел раньше) — принимаем серверное.
            if (err.data.save.updated > self.data.updated) self.replace(err.data.save);
            // Пока ждали ответ, локальное сохранение успело обогнать серверное — отправим ещё раз.
            else pushAgain = true;
            return false;
          }
          if (err.status === 401) expireAuth();
          return false;
        })
        .then(function (ok) {
          pushing = null;
          var again = pushAgain && self.data !== null;
          pushAgain = false;
          return again ? self.push() : ok;
        });
      return pushing;
    },
  };

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

  function adopt(server) {
    server = normalizeSave(server);
    var local = Save.data;
    if (server && (!local || server.updated > local.updated)) {
      Save.replace(server);
      return Promise.resolve();
    }
    return Save.push();
  }

  /* Копия во Flutter переживает очистку WebView: берём её, если она новее. В копии может
   * лежать и старый журнал событий (zb.state.v1) — тогда переводим его в сохранение. */
  function restoreBackup() {
    return Bridge.call('restore').then(function (raw) {
      if (!raw) return;
      var copy;
      try { copy = JSON.parse(raw); } catch (e) { return; }
      if (copy && copy.events && copy.profiles) { migrateOldState(copy); return; }
      var save = normalizeSave(copy && copy.save);
      if (save && (!Save.data || save.updated > Save.data.updated)) Save.replace(save);
      var auth = copy && copy.auth;
      if (auth && auth.token && !Auth.token()) Auth.set(auth);
    });
  }

  /* Запуск на каждой странице. Сайт многостраничный: любой переход — полная перезагрузка, и
   * boot() выполняется снова. Полный цикл (копия из Flutter → вход → синхронизация с сервером)
   * нужен один раз за запуск приложения, поэтому после него ставим флаг в sessionStorage
   * (живёт, пока открыт WebView) и на следующих страницах сразу переходим в 'ready'.
   * Фазы: loading — заставка, auth — окно входа (_auth.html), ready — можно играть. */
  function boot() {
    var old = readJSON(window.localStorage, OLD_STATE_KEY);
    if (old) {
      migrateOldState(old);
      writeJSON(window.localStorage, OLD_STATE_KEY, null);
    }
    var booted = readJSON(window.sessionStorage, BOOTED_KEY);
    if (booted && Auth.token() && Save.data) { setPhase('ready'); return; }
    setPhase('loading');
    restoreBackup().then(function () {
      if (!Auth.token()) { setPhase('auth'); return null; }
      return syncSave().then(function () {
        if (Boot.phase === 'auth') return;
        if (!Save.data) Save.replace(emptySave());
        writeJSON(window.sessionStorage, BOOTED_KEY, true);
        setPhase('ready');
      });
    }).catch(function (e) {
      console.error('boot', e);
      setPhase(Auth.token() ? 'ready' : 'auth');
    });
  }

  /* После входа: если на телефоне лежит сохранение другого аккаунта — выбрасываем его. */
  function forgetForeignSave(username) {
    var prev = Auth.get();
    if (prev && prev.username && prev.username !== username) Save.replace(null);
  }

  function finishLogin() {
    writeJSON(window.sessionStorage, BOOTED_KEY, true);
    setPhase('ready');
  }

  /* Регистрация. Если на телефоне уже есть прогресс без аккаунта (перешёл со старой версии),
   * он уходит в новый аккаунт, а имя и зверёк берутся из формы. */
  function signup(form) {
    var local = Save.data;
    var keepLocal = hasProgress(local) && !(Auth.get() && Auth.get().username);
    return api('POST', '/api/signup', {
      username: form.username, password: form.password,
      name: form.name, avatar: form.avatar, updated: Date.now(),
    }).then(function (data) {
      forgetForeignSave(data.username);
      Auth.set({ username: data.username, token: data.token, synced: 0 });
      if (keepLocal) {
        Save.commit(function (s) { s.profile = { name: form.name, avatar: form.avatar }; });
      } else {
        Save.replace(data.save);
      }
      finishLogin();
    });
  }

  function login(username, password) {
    return api('POST', '/api/login', { username: username, password: password })
      .then(function (data) {
        forgetForeignSave(data.username);
        Auth.set({ username: data.username, token: data.token, synced: 0 });
        // Не ждём: если серверное сохранение новее, adopt подменит его сразу (синхронно),
        // а если новее локальное — отправка на сервер пойдёт в фоне, играть можно уже сейчас.
        adopt(data.save);
        finishLogin();
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

  var Content = {
    load: function () {
      if (!contentPromise) {
        contentPromise = fetch('/content.json').then(function (r) { return r.json(); }).then(prepare);
      }
      return contentPromise;
    },
  };

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

  /* Ключ картинки: у двух слов с одинаковым ключом картинки не различить (👧 «апай» и «нылы»). */
  function picKey(word) {
    if (word.img) return 'i' + word.img;
    if (word.color) return 'c' + word.color;
    if (word.number != null) return 'n' + word.number;
    return word.emoji ? 'e' + word.emoji : '';
  }

  function playAudio(word) {
    if (!word || !word.audio || !Settings.values.sound) return;
    try { new Audio(word.audio).play(); } catch (e) { /* без звука */ }
  }

  // ---------- прогресс ----------

  /* Итоги сыгранной игры: answers — [{w: id слова, ok: true/false}], stars — 1…3. */
  function addGame(save, slug, answers, stars) {
    var now = Date.now();
    var key = dayKey(now);
    var day = save.days[key] = save.days[key] || { ok: 0, bad: 0, seen: 0 };
    var game = save.games[slug] = save.games[slug] || { ok: 0, bad: 0, played: 0, best: 0 };
    answers.forEach(function (a) {
      var w = save.words[a.w] = save.words[a.w] || { ok: 0, bad: 0, seen: 0, last: 0 };
      var field = a.ok ? 'ok' : 'bad';
      w[field]++; day[field]++; game[field]++;
      w.streak = a.ok ? (w.streak || 0) + 1 : 0;
      w.last = now;
    });
    game.played++;
    game.best = Math.max(game.best || 0, stars);
  }

  function isHard(w) {
    return w.bad > 0 && (w.streak || 0) < HARD_CLEARED_AFTER;
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
    var key = dayKey(now);
    var day = save.days[key] = save.days[key] || { ok: 0, bad: 0, seen: 0 };
    ids.forEach(function (id) {
      var w = save.words[id] = save.words[id] || { ok: 0, bad: 0, seen: 0, last: 0 };
      w.seen++;
      w.last = now;
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

  function computeStats(save, content) {
    save = save || emptySave();
    var byWord = save.words;
    var days = save.days;
    var ok = 0;
    var bad = 0;
    Object.keys(byWord).forEach(function (id) {
      ok += byWord[id].ok || 0;
      bad += byWord[id].bad || 0;
    });

    // Серия дней: считаем от сегодня (или от вчера, если сегодня ещё не занимались).
    var streak = 0;
    var t = Date.now();
    if (!days[dayKey(t)]) t -= DAY_MS;
    while (days[dayKey(t)]) { streak++; t -= DAY_MS; }

    // «Выучено»: хотя бы два верных ответа, верных больше, чем ошибок, и слово не «трудное»
    // (иначе оно попало бы и в «Выученные», и в «Чаще ошибаешься»).
    var learnedIds = Object.keys(byWord).filter(function (id) {
      var w = byWord[id];
      return w.ok >= 2 && w.ok > w.bad && !isHard(w);
    });
    var seenIds = Object.keys(byWord).filter(function (id) { return byWord[id].seen > 0; });
    // Слово могли удалить из словаря, а в сохранении оно осталось — такие не считаем.
    var known = function (id) { return !content || content.wordById[id]; };

    var allHard = hardWords(save, content);

    // График «Ответы за 14 дней» (_daily_chart.html); maxDay — высота самого высокого столбика,
    // минимум 1, чтобы не делить на ноль, когда ответов ещё нет.
    var daily = [];
    for (var i = 13; i >= 0; i--) {
      var ts = Date.now() - i * DAY_MS;
      var d = days[dayKey(ts)] || { ok: 0, bad: 0, seen: 0 };
      daily.push({ key: dayKey(ts), label: new Date(ts).getDate(), ok: d.ok, bad: d.bad, seen: d.seen });
    }
    var maxDay = Math.max.apply(null, daily.map(function (d) { return d.ok + d.bad; }).concat([1]));

    var topics = [];
    if (content) {
      topics = content.topics.map(function (topic) {
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
          percent: total ? Math.round(100 * learned.length / total) : 0,
          seen: seen.length,
          seenPercent: total ? Math.round(100 * seen.length / total) : 0,
        };
      });
    }

    return {
      xp: ok * XP_PER_CORRECT,
      streak: streak,
      answers: ok + bad,
      correct: ok,
      wrong: bad,
      accuracy: ok + bad ? Math.round(100 * ok / (ok + bad)) : 0,
      activeDays: Object.keys(days).length,
      learned: learnedIds.filter(known).length,
      learnedWords: content ? learnedIds.filter(known).map(function (id) { return content.wordById[id]; }) : [],
      seen: seenIds.filter(known).length,
      totalWords: content ? content.words.length : 0,
      hard: allHard.slice(0, 5),
      hardCount: allHard.length,
      daily: daily,
      maxDay: maxDay,
      byGame: save.games,
      topics: topics,
      byWord: byWord,
    };
  }

  /* Слово дня: одно и то же весь день, у всех детей одинаковое. */
  function wordOfDay(content) {
    var pool = content.words.filter(function (w) {
      var t = content.topicBySlug[w.topic];
      return t && t.kind !== 'phrases';
    });
    if (!pool.length) return null;
    // Номер дня по местному времени (смещение пояса вычитаем, чтобы слово менялось в полночь,
    // а не в 3:00 по Москве). Умножение на 2654435761 (хэш Кнута) перемешивает номера, чтобы
    // слова шли не подряд по словарю; >>> 0 оставляет результат неотрицательным 32-битным.
    var now = new Date();
    var day = Math.floor((now.getTime() - now.getTimezoneOffset() * 60000) / DAY_MS);
    return pool[((day * 2654435761) >>> 0) % pool.length];
  }

  // ---------- звуки ----------

  var audioCtx = null;

  /* Короткие звуки синтезируются Web Audio, без файлов: каждая нота — синусоида (у ошибки —
   * «треугольник») с быстрой атакой и затуханием за 0,25 с, ноты идут с шагом 0,12 с. */
  var Sound = {
    play: function (kind) {
      if (!Settings.values.sound) return;
      try {
        var AC = window.AudioContext || window.webkitAudioContext;
        audioCtx = audioCtx || new AC();
        var notes = { ok: [660, 880], bad: [220, 165], win: [523, 659, 784, 1046], flip: [440] }[kind] || [440];
        notes.forEach(function (freq, i) {
          var osc = audioCtx.createOscillator();
          var gain = audioCtx.createGain();
          osc.type = kind === 'bad' ? 'triangle' : 'sine';
          osc.frequency.value = freq;
          var t0 = audioCtx.currentTime + i * 0.12;
          gain.gain.setValueAtTime(0.0001, t0);
          gain.gain.exponentialRampToValueAtTime(0.25, t0 + 0.02);
          gain.gain.exponentialRampToValueAtTime(0.0001, t0 + 0.25);
          osc.connect(gain);
          gain.connect(audioCtx.destination);
          osc.start(t0);
          osc.stop(t0 + 0.3);
        });
      } catch (e) { /* звук не обязателен */ }
    },
  };

  // ---------- геолокация ----------

  var IZHEVSK = { lat: 56.8526, lon: 53.2045 };

  function distanceKm(a, b) {
    var rad = Math.PI / 180;
    var dLat = (b.lat - a.lat) * rad;
    var dLon = (b.lon - a.lon) * rad;
    var h = Math.sin(dLat / 2) * Math.sin(dLat / 2) +
      Math.cos(a.lat * rad) * Math.cos(b.lat * rad) * Math.sin(dLon / 2) * Math.sin(dLon / 2);
    return Math.round(6371 * 2 * Math.atan2(Math.sqrt(h), Math.sqrt(1 - h)));
  }

  function locate() {
    return Bridge.call('location').then(function (pos) {
      if (pos && pos.lat != null) return pos;
      if (!navigator.geolocation) return null;
      return new Promise(function (resolve) {
        navigator.geolocation.getCurrentPosition(
          function (p) { resolve({ lat: p.coords.latitude, lon: p.coords.longitude }); },
          function () { resolve(null); },
          { timeout: 10000, maximumAge: 3600000 }
        );
      });
    });
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
      settings: Object.assign({}, Settings.values, { geo: Settings.geoEnabled() }),
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
        // geo — то, что действует на этом устройстве (см. Settings.geoEnabled).
        this.settings = Object.assign({}, Settings.values, { geo: Settings.geoEnabled() });
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

  window.ZB = {
    Save: Save, Auth: Auth, Settings: Settings, Content: Content, Bridge: Bridge, Sound: Sound,
    computeStats: computeStats, wordOfDay: wordOfDay, fromEvents: fromEvents, emptySave: emptySave,
    addGame: addGame, addViews: addViews, cardViews: cardViews,
    hardWords: hardWords, HARD_CLEARED_AFTER: HARD_CLEARED_AFTER,
    pic: pic, picKey: picKey, playAudio: playAudio,
    signup: signup, login: login, logout: logout,
    locate: locate, distanceKm: distanceKm, IZHEVSK: IZHEVSK,
    shuffle: shuffle, sample: sample, param: param, dayKey: dayKey,
    AVATARS: AVATARS,
  };
})();
