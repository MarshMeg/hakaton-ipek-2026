/**
 * Брендбук в одном месте: чтобы перейти на фирменный стиль заказчика,
 * достаточно поменять цвета и шрифт здесь и пересобрать CSS (см. README).
 */
// Цвет из CSS-переменной вида "R G B" — так работают модификаторы прозрачности (bg-surface/95).
const v = (name) => `rgb(var(--c-${name}) / <alpha-value>)`;

module.exports = {
  // JS тоже сканируется: в static/js есть строки с классами (картинки слов).
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        // Цвета флага Удмуртии: чёрный, белый, красный.
        // Нейтральные и «мягкие» цвета зависят от темы: значения — CSS-переменные
        // в static/css/input.css (светлая тема и тёмная по prefers-color-scheme).
        brand: {
          ink: v("ink"),
          red: "#c8102e",
          redDark: "#9e0c24",
          redSoft: v("red-soft"), // выбранная плитка, подсказки
          paper: v("paper"),
          sun: "#f2b705",
          sunInk: v("sun-ink"), // «солнечный» текст (опыт, слово дня)
        },
        surface: { DEFAULT: v("surface"), hover: v("surface-hover"), sunk: v("surface-sunk") }, // карточки, плитки, поля
        line: { DEFAULT: v("line"), soft: v("line-soft"), strong: v("line-strong") }, // рамки, дорожки прогресса
        muted: { DEFAULT: v("muted"), soft: v("muted-soft"), strong: v("muted-strong") }, // второстепенный текст
        ok: { DEFAULT: "#3a9d23", faint: v("ok-faint"), soft: v("ok-soft"), light: v("ok-light") },
        almost: "#e39b00",
        bad: { DEFAULT: "#d7263d", soft: v("bad-soft") },
      },
      fontFamily: {
        sans: ['"Noto Sans"', "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
