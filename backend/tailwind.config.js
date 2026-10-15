/**
 * Брендбук в одном месте: чтобы перейти на фирменный стиль заказчика,
 * достаточно поменять цвета и шрифт здесь и пересобрать CSS (см. README).
 */
module.exports = {
  // JS тоже сканируется: в static/js есть строки с классами (картинки слов).
  content: ["./templates/**/*.html", "./static/js/**/*.js"],
  theme: {
    extend: {
      colors: {
        // Цвета флага Удмуртии: чёрный, белый, красный.
        brand: {
          ink: "#1b1b1b",
          red: "#c8102e",
          redDark: "#9e0c24",
          paper: "#fbf7f0",
          sun: "#f2b705",
        },
        ok: "#3a9d23",
        almost: "#e39b00",
        bad: "#d7263d",
      },
      fontFamily: {
        sans: ['"Noto Sans"', "system-ui", "sans-serif"],
      },
    },
  },
  plugins: [],
};
