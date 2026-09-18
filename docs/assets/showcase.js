(() => {
  "use strict";
  const frame = document.getElementById("demo-frame");
  const cards = [...document.querySelectorAll(".demo-card")];
  cards.forEach((card) => card.addEventListener("click", () => {
    if (card.classList.contains("active")) return;
    cards.forEach((item) => {
      const selected = item === card;
      item.classList.toggle("active", selected);
      item.setAttribute("aria-selected", String(selected));
      item.tabIndex = selected ? 0 : -1;
    });
    frame.title = `${card.dataset.title} interactive lesson`;
    frame.src = card.dataset.src;
  }));
})();
