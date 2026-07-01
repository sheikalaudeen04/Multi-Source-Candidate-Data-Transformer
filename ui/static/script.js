document.addEventListener("DOMContentLoaded", function () {
  // Mode toggle: show/require the config file input only in "custom" mode.
  var modeDefault = document.getElementById("mode-default");
  var modeCustom = document.getElementById("mode-custom");
  var configField = document.getElementById("config-field");
  var configInput = document.getElementById("config-input");

  function syncConfigField() {
    var isCustom = modeCustom && modeCustom.checked;
    if (configField) configField.classList.toggle("is-collapsed", !isCustom);
    if (configInput) configInput.required = !!isCustom;
  }
  if (modeDefault) modeDefault.addEventListener("change", syncConfigField);
  if (modeCustom) modeCustom.addEventListener("change", syncConfigField);
  syncConfigField();

  // Pretty / Raw JSON view tabs.
  var tabButtons = document.querySelectorAll(".tab-btn");
  tabButtons.forEach(function (btn) {
    btn.addEventListener("click", function () {
      tabButtons.forEach(function (b) { b.classList.remove("active"); });
      btn.classList.add("active");
      document.querySelectorAll(".view-panel").forEach(function (panel) {
        panel.hidden = panel.id !== btn.dataset.target;
      });
    });
  });
});
