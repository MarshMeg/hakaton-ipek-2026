/* Ядро приложения на клиенте: локальный прогресс, словарь, статистика, синхронизация
 * и мост во Flutter. Всё работает без сети: страницы и /content.json берутся из офлайн-снимка.
 *
 * Прогресс хранится в localStorage (ключ STATE_KEY) и дублируется во Flutter (файл на телефоне),
 * чтобы пережить очистку данных WebView. Журнал событий только дописывается, поэтому любые две
 * копии состояния можно безопасно объединить (merge) — ничего не теряется.
 *
 * Код намеренно без новейшего синтаксиса: приложение должно работать на Android 8.
 */
(function () {
  'use strict';

  var STATE_KEY = 'zb.state.v1';
  var XP_PER_CORRECT = 10;
  var SYNC_BATCH = 2000;
  var DAY_MS = 86400000;

  // ---------- утилиты ----------

  function pad(n) { return n < 10 ? '0' + n : String(n); }

  function dayKey(ts) {
    var d = new Date(ts);
    return d.getFullYear() + '-' + pad(d.getMonth() + 1) + '-' + pad(d.getDate());
  }

  function uuid() {
    if (window.crypto && window.crypto.randomUUID) {
      try { return window.crypto.randomUUID(); } catch (e) { /* не https — ниже */ }
    }
    var b = window.crypto.getRandomValues(new Uint8Array(16));
    b[6] = (b[6] & 15) | 64;
    b[8] = (b[8] & 63) | 128;
    var h = '';
    for (var i = 0; i < 16; i++) h += (b[i] < 16 ? '0' : '') + b[i].toString(16);
    return h.slice(0, 8) + '-' + h.slice(8, 12) + '-' + h.slice(12, 16) + '-' + h.slice(16, 20) + '-' + h.slice(20);
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

  // ---------- мост во Flutter ----------

  var Bridge = {
    ready: new Promise(function (resolve) {
      if (window.flutter_inappwebview && window.flutter_inappwebview.callHandler) return resolve(true);
      window.addEventListener('flutterInAppWebViewPlatformReady', function () { resolve(true); });
      // В обычном браузере событие не придёт.
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

  // ---------- состояние ----------

  function emptyState() {
    return {
      v: 1, rev: 0, active: null, profiles: {}, events: [],
      settings: { sound: true, notifications: false, geo: false },
    };
  }

  function readLocal() {
    try {
      var raw = window.localStorage.getItem(STATE_KEY);
      if (raw) return normalize(JSON.parse(raw));
    } catch (e) { console.warn('state read', e); }
    return emptyState();
  }

  function normalize(s) {
    var base = emptyState();
    if (!s || typeof s !== 'object') return base;
    base.rev = s.rev || 0;
    base.active = s.active || null;
    base.profiles = s.profiles || {};
    base.events = Array.isArray(s.events) ? s.events : [];
    for (var k in s.settings || {}) base.settings[k] = s.settings[k];
    return base;
  }

  /* Объединение двух копий состояния: профили — по времени правки, события — по id. */
  function merge(a, b) {
    var out = normalize(JSON.parse(JSON.stringify(a)));
    b = normalize(b);
    Object.keys(b.profiles).forEach(function (id) {
      var mine = out.profiles[id];
      var theirs = b.profiles[id];
      if (!mine || (theirs.updated || 0) > (mine.updated || 0)) {
        if (mine && mine.account && !theirs.account) theirs.account = mine.account;
        out.profiles[id] = theirs;
      }
    });
    var index = {};
    out.events.forEach(function (e) { index[e.id] = e; });
    b.events.forEach(function (e) {
      if (!index[e.id]) { out.events.push(e); index[e.id] = e; }
      else if (e.s) index[e.id].s = 1;
    });
    out.events.sort(function (x, y) { return x.t - y.t; });
    if (!out.active || !out.profiles[out.active]) out.active = b.active;
    if (!a.rev) out.settings = b.settings;
    out.rev = Math.max(a.rev || 0, b.rev || 0);
    return out;
  }

  var listeners = [];
  var backupTimer = null;

  var Store = {
    state: readLocal(),

    onChange: function (fn) { listeners.push(fn); },

    save: function () {
      this.state.rev++;
      try {
        window.localStorage.setItem(STATE_KEY, JSON.stringify(this.state));
      } catch (e) { console.warn('state write', e); }
      // Резервная копия во Flutter — не чаще раза в полсекунды.
      clearTimeout(backupTimer);
      var self = this;
      backupTimer = setTimeout(function () { Bridge.call('backup', JSON.stringify(self.state)); }, 500);
      listeners.forEach(function (fn) { fn(); });
    },

    /* При запуске подтягиваем копию из Flutter: она могла пережить очистку WebView. */
    restore: function () {
      var self = this;
      return Bridge.call('restore').then(function (raw) {
        if (!raw) return false;
        var backup;
        try { backup = JSON.parse(raw); } catch (e) { return false; }
        var before = self.state.events.length + ':' + Object.keys(self.state.profiles).length;
        self.state = merge(self.state, backup);
        var after = self.state.events.length + ':' + Object.keys(self.state.profiles).length;
        if (before !== after) { self.save(); return true; }
        return false;
      });
    },

    // --- профили ---

    profile: function () { return this.state.profiles[this.state.active] || null; },

    profiles: function () {
      var p = this.state.profiles;
      return Object.keys(p).map(function (id) { return p[id]; })
        .sort(function (a, b) { return a.created - b.created; });
    },

    createProfile: function (name, avatar, account) {
      var now = Date.now();
      var p = { id: uuid(), name: name, avatar: avatar, created: now, updated: now, account: account || null };
      this.state.profiles[p.id] = p;
      this.state.active = p.id;
      this.save();
      return p;
    },

    updateProfile: function (id, patch) {
      var p = this.state.profiles[id];
      if (!p) return;
      for (var k in patch) p[k] = patch[k];
      if (!('account' in patch)) p.updated = Date.now();
      this.save();
    },

    setActive: function (id) {
      if (this.state.profiles[id]) { this.state.active = id; this.save(); }
    },

    // --- журнал ---

    /* correct: true/false — ответ в игре, null — просмотр карточки. */
    record: function (wordId, game, correct) {
      if (!this.state.active) return;
      this.state.events.push({
        id: uuid(), p: this.state.active, w: wordId, g: game,
        c: correct === null ? null : (correct ? 1 : 0), t: Date.now(),
      });
      this.save();
    },

    events: function (profileId) {
      var pid = profileId || this.state.active;
      return this.state.events.filter(function (e) { return e.p === pid; });
    },

    setSetting: function (key, value) {
      this.state.settings[key] = value;
      this.save();
    },
  };

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
      return '<span class="block h-full w-full rounded-full border-4 border-gray-200" style="background:' +
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
    if (!word || !word.audio || !Store.state.settings.sound) return;
    try { new Audio(word.audio).play(); } catch (e) { /* без звука */ }
  }

  // ---------- статистика ----------

  function computeStats(events, content) {
    var byWord = {};
    var days = {};
    var byGame = {};
    var ok = 0;
    var bad = 0;
    events.forEach(function (e) {
      var key = dayKey(e.t);
      days[key] = days[key] || { ok: 0, bad: 0, seen: 0 };
      var w = byWord[e.w] = byWord[e.w] || { ok: 0, bad: 0, seen: 0 };
      if (e.c === null || e.c === undefined) { w.seen++; days[key].seen++; return; }
      byGame[e.g] = byGame[e.g] || { ok: 0, bad: 0 };
      if (e.c) { ok++; w.ok++; days[key].ok++; byGame[e.g].ok++; }
      else { bad++; w.bad++; days[key].bad++; byGame[e.g].bad++; }
    });

    // Серия дней: считаем от сегодня (или от вчера, если сегодня ещё не занимались).
    var streak = 0;
    var t = Date.now();
    if (!days[dayKey(t)]) t -= DAY_MS;
    while (days[dayKey(t)]) { streak++; t -= DAY_MS; }

    var learnedIds = Object.keys(byWord).filter(function (id) {
      var w = byWord[id];
      return w.ok >= 2 && w.ok > w.bad;
    });
    var seenIds = Object.keys(byWord).filter(function (id) { return byWord[id].seen > 0; });
    var known = function (id) { return !content || content.wordById[id]; };

    var hard = Object.keys(byWord)
      .filter(function (id) { return byWord[id].bad > 0 && known(id); })
      .sort(function (a, b) { return byWord[b].bad - byWord[a].bad; })
      .slice(0, 5)
      .map(function (id) {
        return { word: content ? content.wordById[id] : null, ok: byWord[id].ok, bad: byWord[id].bad };
      });

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
        return {
          slug: topic.slug, title: topic.title, icon: topic.icon, total: topic.words.length,
          learned: learned.length,
          percent: topic.words.length ? Math.round(100 * learned.length / topic.words.length) : 0,
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
      hard: hard,
      daily: daily,
      maxDay: maxDay,
      byGame: byGame,
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
    var now = new Date();
    var day = Math.floor((now.getTime() - now.getTimezoneOffset() * 60000) / DAY_MS);
    return pool[((day * 2654435761) >>> 0) % pool.length];
  }

  // ---------- облачный аккаунт ----------

  function api(path, body, token) {
    var headers = { 'Content-Type': 'application/json' };
    if (token) headers.Authorization = 'Bearer ' + token;
    return fetch(path, { method: 'POST', headers: headers, body: JSON.stringify(body) })
      .catch(function () { throw new Error('Нет связи с сервером. Попробуй, когда появится интернет.'); })
      .then(function (r) {
        return r.json().catch(function () { return {}; }).then(function (data) {
          if (!r.ok) {
            var err = new Error(data.error || 'Ошибка сервера (' + r.status + ')');
            err.status = r.status;
            throw err;
          }
          return data;
        });
      });
  }

  var syncing = {};

  function sync(profileId) {
    var pid = profileId || Store.state.active;
    var p = Store.state.profiles[pid];
    if (!p || !p.account || !p.account.token) return Promise.resolve(false);
    if (syncing[pid]) return syncing[pid];

    function round() {
      var pending = Store.state.events.filter(function (e) { return e.p === pid && !e.s; });
      var batch = pending.slice(0, SYNC_BATCH);
      var payload = {
        profile: { name: p.name, avatar: p.avatar, updated: p.updated },
        events: batch.map(function (e) { return { id: e.id, w: e.w, g: e.g, c: e.c, t: e.t }; }),
      };
      return api('/api/sync', payload, p.account.token).then(function (data) {
        var sent = {};
        batch.forEach(function (e) { sent[e.id] = true; });
        var have = {};
        Store.state.events.forEach(function (e) {
          if (sent[e.id]) e.s = 1;
          have[e.id] = true;
        });
        (data.events || []).forEach(function (e) {
          if (!have[e.id]) Store.state.events.push({ id: e.id, p: pid, w: e.w, g: e.g, c: e.c, t: e.t, s: 1 });
        });
        Store.state.events.sort(function (x, y) { return x.t - y.t; });
        if (data.profile && data.profile.updated > (p.updated || 0)) {
          p.name = data.profile.name || p.name;
          p.avatar = data.profile.avatar || p.avatar;
          p.updated = data.profile.updated;
        }
        p.account.synced = Date.now();
        Store.save();
        return pending.length > batch.length ? round() : true;
      });
    }

    syncing[pid] = round().then(function (result) {
      delete syncing[pid];
      return result;
    }, function (err) {
      delete syncing[pid];
      if (err.status === 401) Store.updateProfile(pid, { account: null });
      throw err;
    });
    return syncing[pid];
  }

  /* Регистрация привязывает облачный аккаунт к текущему профилю. */
  function signup(username, password) {
    var p = Store.profile();
    if (!p) return Promise.reject(new Error('Сначала создай профиль'));
    return api('/api/signup', {
      username: username, password: password, name: p.name, avatar: p.avatar, updated: p.updated,
    }).then(function (data) {
      Store.updateProfile(p.id, { account: { username: data.username, token: data.token } });
      return sync(p.id);
    });
  }

  /* Вход: если аккаунт уже есть на телефоне — переключаемся на него; если текущий профиль
   * пустой и без аккаунта — привязываем к нему; иначе заводим новый локальный профиль. */
  function login(username, password) {
    return api('/api/login', { username: username, password: password }).then(function (data) {
      var account = { username: data.username, token: data.token };
      var existing = Store.profiles().filter(function (p) {
        return p.account && p.account.username === data.username;
      })[0];
      var current = Store.profile();
      var target;
      if (existing) {
        Store.updateProfile(existing.id, { account: account });
        Store.setActive(existing.id);
        target = existing;
      } else if (current && !current.account && Store.events(current.id).length === 0) {
        // Пустой профиль (например, «Гость» с первого экрана) получает имя и аватар из облака.
        Store.updateProfile(current.id, {
          account: account,
          name: data.profile.name || current.name,
          avatar: data.profile.avatar || current.avatar,
          updated: data.profile.updated || 0,
        });
        target = current;
      } else {
        target = Store.createProfile(data.profile.name || data.username, data.profile.avatar || '🦊', account);
        target.updated = data.profile.updated || 0;
      }
      return sync(target.id);
    });
  }

  function logout(profileId) {
    Store.updateProfile(profileId || Store.state.active, { account: null });
  }

  /* Тихая синхронизация при открытии страницы, если есть что отправить или давно не было. */
  function autoSync() {
    var p = Store.profile();
    if (!p || !p.account || navigator.onLine === false) return;
    var pending = Store.state.events.some(function (e) { return e.p === p.id && !e.s; });
    var stale = !p.account.synced || Date.now() - p.account.synced > 10 * 60000;
    if (pending || stale) sync(p.id).catch(function () { /* попробуем в следующий раз */ });
  }

  // ---------- звуки ----------

  var audioCtx = null;

  var Sound = {
    play: function (kind) {
      if (!Store.state.settings.sound) return;
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

  document.addEventListener('alpine:init', function () {
    var Alpine = window.Alpine;
    Alpine.store('app', {
      profile: null,
      profiles: [],
      settings: Store.state.settings,
      stats: computeStats([], null),
      content: null,
      ready: false,

      refresh: function () {
        this.profile = Store.profile() ? Object.assign({}, Store.profile()) : null;
        this.profiles = Store.profiles().map(function (p) { return Object.assign({}, p); });
        this.settings = Object.assign({}, Store.state.settings);
        this.stats = computeStats(Store.events(), this.content);
      },

      createProfile: function (name, avatar) {
        name = (name || '').trim();
        if (!name) return;
        Store.createProfile(name.slice(0, 60), avatar || '🦊');
      },
    });

    var store = Alpine.store('app');
    store.refresh();
    Store.onChange(function () { store.refresh(); });
    Content.load().then(function (c) {
      store.content = c;
      store.ready = true;
      store.refresh();
    }).catch(function (e) { console.error('content', e); store.ready = true; });
    Store.restore().then(function () { autoSync(); });
  });

  window.ZB = {
    Store: Store, Content: Content, Bridge: Bridge, Sound: Sound,
    computeStats: computeStats, wordOfDay: wordOfDay, merge: merge,
    pic: pic, picKey: picKey, playAudio: playAudio,
    sync: sync, signup: signup, login: login, logout: logout,
    locate: locate, distanceKm: distanceKm, IZHEVSK: IZHEVSK,
    shuffle: shuffle, sample: sample, param: param, dayKey: dayKey, uuid: uuid,
    AVATARS: ['🦊', '🐻', '🐰', '🐿️', '🦔', '🐺', '🐱', '🐶', '🦉', '🐝'],
  };
})();
