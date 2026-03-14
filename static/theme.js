(function () {
  function setTheme(theme) {
    document.documentElement.setAttribute("data-theme", theme);
    try {
      localStorage.setItem("trade-proposer-theme", theme);
    } catch (_error) {
      // ignore storage failures
    }
    var label = document.getElementById("theme-toggle-label");
    if (label) {
      label.textContent = theme === "dark" ? "Dark" : "Light";
    }
  }

  function getCurrentTheme() {
    return document.documentElement.getAttribute("data-theme") || "dark";
  }

  document.addEventListener("DOMContentLoaded", function () {
    setTheme(getCurrentTheme());
    var button = document.getElementById("theme-toggle");
    if (!button) {
      return;
    }
    button.addEventListener("click", function () {
      setTheme(getCurrentTheme() === "dark" ? "light" : "dark");
    });
  });
})();
