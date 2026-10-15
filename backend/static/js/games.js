/* Шесть игр раздела «Игры» и режим «Трудные слова». Каждая — Alpine-компонент, который строит раунды из словаря
 * (/content.json) прямо на телефоне. Ответы копятся в this.answers и записываются в сохранение
 * одним действием, когда игра пройдена до конца (ZB.Save.commit в finish). Прерванная игра
 * прогресс не меняет. Сервер в игре не участвует, поэтому всё работает без сети.
 */
(function () {
  'use strict';

  var ZB = window.ZB;

  /* Общая часть всех игр: загрузка словаря, выбор темы, счёт, звёзды, экран итогов. */
  function base(slug, extra) {
    var game = {
      slug: slug,
      loading: true,
      content: null,
      topic: ZB.param('topic'),
      rounds: 8,
      round: 0,
      score: 0,
      maxScore: 8,
      done: false,
      empty: false, // играть не во что (в «Трудных словах» — мало трудных слов)
      answers: [], // [{w: id слова, ok}] — ответы этой игры, в сохранение попадут в finish()
      feedback: null, // 'ok' | 'bad' | null
      message: '',

      init: function () {
        var self = this;
        ZB.Content.load().then(function (c) {
          self.content = c;
          if (self.topic && !c.topicBySlug[self.topic]) self.topic = '';
          self.loading = false;
          self.start();
        });
      },

      setTopic: function (slug) {
        this.topic = slug;
        var url = slug ? '?topic=' + encodeURIComponent(slug) : window.location.pathname;
        window.history.replaceState(null, '', url);
        this.start();
      },

      start: function () {
        this.round = 0;
        this.score = 0;
        this.maxScore = this.rounds;
        this.done = false;
        this.answers = [];
        this.feedback = null;
        this.message = '';
        this.newRound();
      },

      /* Слова выбранной темы (или все), по желанию отфильтрованные. */
      pool: function (filter) {
        var c = this.content;
        var words = this.topic ? c.topicBySlug[this.topic].words : c.words;
        return filter ? words.filter(filter) : words.slice();
      },

      topicOf: function (word) { return this.content.topicBySlug[word.topic]; },

      /* Случайное слово, которого не было в последних раундах. */
      recent: [],
      pickFresh: function (pool) {
        var recent = this.recent;
        var fresh = pool.filter(function (w) { return recent.indexOf(w.id) < 0; });
        var list = fresh.length ? fresh : pool;
        var word = list[Math.floor(Math.random() * list.length)];
        this.recent = [word.id].concat(recent).slice(0, Math.min(4, Math.floor(pool.length / 2)));
        return word;
      },

      /* Слова-«отвлекалки»: другие слова, с текстом не таким, как у правильного. Синонимы
       * («чырткем» и «салам» — оба «привет») отсеиваются по обоим полям, иначе среди вариантов
       * оказалось бы второе верное слово. */
      distractors: function (target, n, field) {
        var self = this;
        var norm = function (s) { return String(s || '').trim().toLowerCase(); };
        var used = {};
        used[norm(target[field])] = true;
        var pick = function (list) {
          var out = [];
          ZB.shuffle(list).forEach(function (w) {
            var key = norm(w[field]);
            if (out.length >= n || used[key]) return;
            if (norm(w.ru) === norm(target.ru) || norm(w.udm) === norm(target.udm)) return;
            used[key] = true;
            out.push(w);
          });
          return out;
        };
        var same = pick(this.topicOf(target).words);
        if (same.length < n) {
          same = same.concat(pick(self.content.words).slice(0, n - same.length));
        }
        return same;
      },

      log: function (word, ok) { this.answers.push({ w: word.id, ok: ok }); },

      answer: function (word, ok) {
        this.log(word, ok);
        if (ok) this.score++;
        this.feedback = ok ? 'ok' : 'bad';
        ZB.Sound.play(ok ? 'ok' : 'bad');
      },

      next: function () {
        this.feedback = null;
        this.message = '';
        this.round++;
        if (this.round >= this.rounds) this.finish();
        else this.newRound();
      },

      /* После верного ответа идём дальше сами, после ошибки — ждём кнопку «Дальше». */
      autoNext: function () {
        var self = this;
        var round = this.round;
        setTimeout(function () { if (self.round === round && self.feedback === 'ok') self.next(); }, 900);
      },

      finish: function () {
        var slug = this.slug;
        var answers = this.answers;
        var stars = this.stars();
        this.done = true;
        ZB.Save.commit(function (s) { ZB.addGame(s, slug, answers, stars); });
        ZB.Sound.play('win');
      },

      stars: function () {
        var r = this.maxScore ? this.score / this.maxScore : 0;
        return r >= 0.9 ? 3 : r >= 0.6 ? 2 : 1;
      },

      progress: function () {
        return Math.round(100 * this.round / this.rounds);
      },

      pic: ZB.pic,
      hasPic: function (w) { return !!ZB.picKey(w); },
      speak: ZB.playAudio,
    };
    Object.keys(extra).forEach(function (k) { game[k] = extra[k]; });
    return game;
  }

  // ---------- «Выбери перевод» ----------

  /* Механика «Выбери перевод»; её же использует режим «Трудные слова». */
  function chooseRounds() {
    return {
      target: null,
      options: [],
      chosen: null,
      reverse: false, // false: удм → рус; true: картинка/рус → удм

      newRound: function () {
        var pool = this.pool();
        this.target = this.pickFresh(pool);
        this.reverse = this.round % 2 === 1;
        var field = this.reverse ? 'udm' : 'ru';
        this.options = ZB.shuffle([this.target].concat(this.distractors(this.target, 3, field)));
        this.chosen = null;
        ZB.playAudio(this.reverse ? null : this.target);
      },

      pick: function (opt) {
        if (this.feedback) return;
        this.chosen = opt.id;
        // Вариант с тем же текстом, что у правильного, тоже верный (на случай синонимов).
        var ok = opt.id === this.target.id || this.optionText(opt) === this.optionText(this.target);
        this.answer(this.target, ok);
        if (ok) this.autoNext();
        else this.message = this.target.udm + ' — ' + this.target.ru;
      },

      optionText: function (opt) { return this.reverse ? opt.udm : opt.ru; },
    };
  }

  function choose() {
    return base('choose', chooseRounds());
  }

  // ---------- «Трудные слова» ----------

  var HARD_MIN = 3; // меньше трудных слов — играть не во что: одно слово повторялось бы раз за разом
  var HARD_MAX = 10; // берём самые трудные, чтобы за игру каждое встретилось хотя бы раз-другой

  /* «Выбери перевод», но слова — те, в которых ребёнок ошибался (ZB.hardWords по сохранению
   * на телефоне). Страница одинакова для всех, список слов собирается здесь. */
  function hard() {
    var game = base('hard', chooseRounds());
    var extra = {
      hardList: [], // [{word, ok, bad, streak}] — слова этой игры
      hardLeft: 0, // сколько трудных слов всего (для сообщения, если их мало)
      cleared: 0, // сколько слов этой игры перестали быть трудными после неё

      start: function () {
        var all = ZB.hardWords(ZB.Save.get(), this.content);
        this.hardLeft = all.length;
        this.hardList = all.slice(0, HARD_MAX);
        this.empty = all.length < HARD_MIN;
        this.cleared = 0;
        // Каждое слово — примерно по два раза (в обе стороны), но не больше обычных 8 раундов.
        this.rounds = Math.min(8, this.hardList.length * 2);
        if (this.empty) {
          this.round = 0;
          this.done = false;
          this.feedback = null;
          return;
        }
        // Очередь слов: каждое встречается поровну, одно и то же слово не идёт два раза подряд.
        var words = this.hardList.map(function (h) { return h.word; });
        var queue = [];
        while (queue.length < this.rounds) {
          var next = ZB.shuffle(words);
          if (queue.length && next[0] === queue[queue.length - 1]) next.push(next.shift());
          queue = queue.concat(next);
        }
        this.queue = queue;
        chooseStart.call(this);
      },

      queue: [],
      pickFresh: function () { return this.queue[this.round]; },

      finish: function () {
        chooseFinish.call(this);
        var save = ZB.Save.get();
        var stillHard = {};
        ZB.hardWords(save, this.content).forEach(function (h) { stillHard[h.word.id] = true; });
        var answered = {};
        this.answers.forEach(function (a) { answered[a.w] = true; });
        this.cleared = this.hardList.filter(function (h) {
          return answered[h.word.id] && !stillHard[h.word.id];
        }).length;
      },
    };
    var chooseStart = game.start;
    var chooseFinish = game.finish;
    Object.keys(extra).forEach(function (k) { game[k] = extra[k]; });
    var init = game.init;
    game.init = function () {
      var self = this;
      init.call(this);
      // Сохранение могло прийти с сервера уже после открытия страницы.
      ZB.Save.onChange(function () { if (self.empty && self.content) self.start(); });
    };
    return game;
  }

  // ---------- «Найди лишнее» ----------

  function odd() {
    return base('odd', {
      words: [],
      oddWord: null,
      mainTopic: null,
      chosen: null,
      showPics: false,

      newRound: function () {
        var c = this.content;
        var topics = c.topics.filter(function (t) { return t.kind !== 'phrases' && t.words.length >= 3; });
        var main = topics[Math.floor(Math.random() * topics.length)];
        var others = topics.filter(function (t) { return t.family !== main.family; });
        var other = others[Math.floor(Math.random() * others.length)];
        this.mainTopic = main;
        this.oddWord = ZB.sample(other.words, 1)[0];
        this.words = ZB.shuffle(ZB.sample(main.words, 3).concat([this.oddWord]));
        this.chosen = null;
        this.showPics = false;
      },

      pick: function (w) {
        if (this.feedback) return;
        this.chosen = w.id;
        var ok = w.id === this.oddWord.id;
        this.answer(this.oddWord, ok);
        this.showPics = true;
        this.message = '«' + this.oddWord.udm + '» — ' + this.oddWord.ru + ', это из темы «' +
          this.topicOf(this.oddWord).title + '». Остальные слова — «' + this.mainTopic.title + '».';
      },
    });
  }

  // ---------- «Сортировка» ----------

  function sort() {
    return base('sort', {
      rounds: 3,
      set: null,
      groups: [],
      items: [],
      selected: null,
      shake: null,
      drag: null,

      start: function () {
        this.round = 0;
        this.score = 0;
        this.maxScore = 0;
        this.done = false;
        this.feedback = null;
        this.newRound();
      },

      newRound: function () {
        var c = this.content;
        var sets = c.sorting.filter(function (s) {
          return s.groups.every(function (g) {
            return g.topics.some(function (slug) { return c.topicBySlug[slug] && c.topicBySlug[slug].words.length; });
          });
        });
        this.set = sets[Math.floor(Math.random() * sets.length)];
        var perGroup = this.set.groups.length > 2 ? 2 : 3;
        var items = [];
        this.groups = this.set.groups.map(function (g, gi) {
          var words = [];
          g.topics.forEach(function (slug) { words = words.concat(c.topicBySlug[slug].words); });
          ZB.sample(words, perGroup).forEach(function (w) {
            items.push({ word: w, group: gi, placed: false, tried: false });
          });
          return { label: g.label, icon: g.icon || '', placed: [] };
        });
        this.items = ZB.shuffle(items);
        this.maxScore += items.length;
        this.selected = null;
      },

      remaining: function () { return this.items.filter(function (i) { return !i.placed; }); },

      drop: function (item, groupIndex) {
        if (!item || item.placed) return;
        var ok = item.group === groupIndex;
        if (!item.tried) {
          this.log(item.word, ok);
          if (ok) this.score++;
        }
        item.tried = true;
        this.selected = null;
        if (ok) {
          item.placed = true;
          this.groups[groupIndex].placed.push(item.word);
          ZB.Sound.play('ok');
          if (!this.remaining().length) {
            var self = this;
            setTimeout(function () { self.next(); }, 700);
          }
        } else {
          ZB.Sound.play('bad');
          this.shake = item.word.id;
          var me = this;
          setTimeout(function () { me.shake = null; }, 500);
        }
      },

      // Перетаскивание пальцем (pointer events) и запасной вариант — нажать слово, потом корзинку.
      dragStart: function (ev, item) {
        this.drag = { item: item, x0: ev.clientX, y0: ev.clientY, dx: 0, dy: 0, moved: false };
        try { ev.target.setPointerCapture(ev.pointerId); } catch (e) { /* старый WebView */ }
      },

      dragMove: function (ev) {
        if (!this.drag) return;
        this.drag.dx = ev.clientX - this.drag.x0;
        this.drag.dy = ev.clientY - this.drag.y0;
        if (Math.abs(this.drag.dx) + Math.abs(this.drag.dy) > 8) this.drag.moved = true;
      },

      dragEnd: function (ev) {
        var drag = this.drag;
        if (!drag) return;
        this.drag = null;
        if (!drag.moved) {
          this.selected = this.selected === drag.item ? null : drag.item;
          return;
        }
        var el = ev.target;
        var prev = el.style.visibility;
        el.style.visibility = 'hidden';
        var under = document.elementFromPoint(ev.clientX, ev.clientY);
        el.style.visibility = prev;
        var bucket = under && under.closest('[data-bucket]');
        if (bucket) this.drop(drag.item, Number(bucket.getAttribute('data-bucket')));
      },

      dragStyle: function (item) {
        if (!this.drag || this.drag.item !== item) return '';
        return 'transform: translate(' + this.drag.dx + 'px,' + this.drag.dy + 'px) scale(1.08); z-index: 30; position: relative;';
      },

      tapBucket: function (gi) { if (this.selected) this.drop(this.selected, gi); },

      progress: function () {
        var total = this.items.length || 1;
        var done = this.items.filter(function (i) { return i.placed; }).length;
        return Math.round(100 * (this.round + done / total) / this.rounds);
      },
    });
  }

  // ---------- «Найди пару» (Memory) ----------

  function memory() {
    return base('memory', {
      rounds: 1,
      cards: [],
      open: [],
      moves: 0,
      pairs: 0,
      busy: false,

      newRound: function () {
        // Пара — «удмуртское слово + картинка», а если картинки нет или она повторяется —
        // «удмуртское слово + перевод».
        var seenPic = {};
        var seenRu = {};
        var words = ZB.shuffle(this.pool()).filter(function (w) {
          if (seenRu[w.ru]) return false;
          seenRu[w.ru] = true;
          return true;
        });
        if (words.length < 3) words = ZB.shuffle(this.content.words);
        words = words.slice(0, 6);
        var cards = [];
        words.forEach(function (w) {
          var key = ZB.picKey(w);
          var usePic = key && !seenPic[key];
          if (usePic) seenPic[key] = true;
          cards.push({ uid: w.id + 'u', word: w, side: 'udm', flipped: false, matched: false });
          cards.push({ uid: w.id + 'p', word: w, side: usePic ? 'pic' : 'ru', flipped: false, matched: false });
        });
        this.cards = ZB.shuffle(cards);
        this.pairs = words.length;
        this.maxScore = words.length;
        this.moves = 0;
        this.open = [];
      },

      flip: function (card) {
        if (this.busy || card.flipped || card.matched) return;
        card.flipped = true;
        ZB.Sound.play('flip');
        this.open.push(card);
        if (this.open.length < 2) return;
        this.moves++;
        var a = this.open[0];
        var b = this.open[1];
        var self = this;
        this.open = [];
        if (a.word.id === b.word.id) {
          a.matched = b.matched = true;
          this.log(a.word, true);
          ZB.Sound.play('ok');
          this.score++;
          ZB.playAudio(a.word);
          if (this.cards.every(function (c) { return c.matched; })) {
            setTimeout(function () { self.finish(); }, 600);
          }
        } else {
          this.busy = true;
          setTimeout(function () {
            a.flipped = b.flipped = false;
            self.busy = false;
          }, 900);
        }
      },

      // Звёзды за количество ходов: идеально — по ходу на пару.
      stars: function () {
        if (this.moves <= this.pairs + 2) return 3;
        if (this.moves <= this.pairs * 2) return 2;
        return 1;
      },

      progress: function () { return Math.round(100 * this.score / (this.pairs || 1)); },
    });
  }

  // ---------- «Собери слово» ----------

  var SINGLE_WORD = /^[^\s\-.,!?…]{2,10}$/;

  function assemble() {
    return base('assemble', {
      target: null,
      letters: [],
      picked: [],

      newRound: function () {
        var self = this;
        var ok = function (w) { return self.topicOf(w).kind !== 'phrases' && SINGLE_WORD.test(w.udm); };
        var pool = this.pool(ok);
        if (!pool.length) pool = this.content.words.filter(ok);
        this.target = this.pickFresh(pool);
        var chars = Array.from(this.target.udm.toLowerCase());
        var mixed = ZB.shuffle(chars);
        for (var i = 0; i < 5 && mixed.join('') === chars.join('') && chars.length > 1; i++) mixed = ZB.shuffle(chars);
        this.letters = mixed.map(function (ch, idx) { return { ch: ch, idx: idx, used: false }; });
        this.picked = [];
      },

      take: function (tile) {
        if (this.feedback || tile.used) return;
        tile.used = true;
        this.picked.push(tile);
        ZB.Sound.play('flip');
        if (this.picked.length === this.letters.length) this.check();
      },

      giveBack: function (pos) {
        if (this.feedback) return;
        var tile = this.picked.splice(pos, 1)[0];
        if (tile) tile.used = false;
      },

      check: function () {
        var word = this.picked.map(function (t) { return t.ch; }).join('');
        var ok = word === this.target.udm.toLowerCase();
        this.answer(this.target, ok);
        if (ok) { ZB.playAudio(this.target); this.autoNext(); }
        else this.message = 'Правильно: ' + this.target.udm;
      },

      slots: function () {
        var out = [];
        for (var i = 0; i < this.letters.length; i++) out.push(this.picked[i] ? this.picked[i].ch : '');
        return out;
      },
    });
  }

  // ---------- «Правда или ложь» ----------

  function truefalse() {
    return base('truefalse', {
      target: null,
      shown: null,
      isTrue: true,

      newRound: function () {
        var pool = this.pool();
        this.target = this.pickFresh(pool);
        this.isTrue = Math.random() < 0.5;
        this.shown = this.target;
        if (!this.isTrue) {
          var key = ZB.picKey(this.target);
          var t = this.target;
          // Подменное слово должно явно не подходить: другая картинка и другой перевод.
          var others = this.distractors(t, 6, 'ru').filter(function (w) { return !key || ZB.picKey(w) !== key; });
          if (others.length) this.shown = others[0];
          else this.isTrue = true;
        }
      },

      say: function (yes) {
        if (this.feedback) return;
        var ok = yes === this.isTrue;
        this.answer(this.shown, ok);
        this.message = '«' + this.shown.udm + '» — это ' + this.shown.ru + '.';
        if (ok) this.autoNext();
      },
    });
  }

  document.addEventListener('alpine:init', function () {
    var Alpine = window.Alpine;
    Alpine.data('choose', choose);
    Alpine.data('hard', hard);
    Alpine.data('odd', odd);
    Alpine.data('sort', sort);
    Alpine.data('memory', memory);
    Alpine.data('assemble', assemble);
    Alpine.data('truefalse', truefalse);
  });
})();
