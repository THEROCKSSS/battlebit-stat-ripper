/* Small, dependency-free interactions for the profile site. */
(function () {
  "use strict";

  function toast(message) {
    var region = document.getElementById("toast-region");
    if (!region) return;
    var node = document.createElement("div");
    node.className = "toast";
    node.textContent = message;
    region.appendChild(node);
    window.setTimeout(function () {
      node.style.opacity = "0";
      window.setTimeout(function () { node.remove(); }, 180);
    }, 2600);
  }

  // Dismiss flash messages.
  document.querySelectorAll(".flash-close").forEach(function (button) {
    button.addEventListener("click", function () {
      var flash = button.closest(".flash");
      if (flash) flash.remove();
    });
  });

  // Copy buttons: copy a target input's value and announce it.
  document.querySelectorAll("[data-copy-target]").forEach(function (button) {
    button.addEventListener("click", function () {
      var target = document.getElementById(button.getAttribute("data-copy-target"));
      if (!target) return;
      var value = target.value || target.textContent || "";
      function fallback() {
        target.select();
        document.execCommand("copy");
        toast("Copied to clipboard.");
      }
      if (navigator.clipboard && navigator.clipboard.writeText) {
        navigator.clipboard.writeText(value).then(function () {
          toast("Copied to clipboard.");
        }).catch(fallback);
      } else {
        fallback();
      }
    });
  });

  // Dropzone: show the picked file name and highlight on drag.
  document.querySelectorAll("[data-dropzone]").forEach(function (zone) {
    var input = zone.querySelector('input[type="file"]');
    var label = zone.querySelector("[data-file-name]");
    if (!input) return;
    function updateName() {
      if (label && input.files && input.files.length) {
        label.textContent = input.files[0].name;
      }
    }
    input.addEventListener("change", updateName);
    ["dragenter", "dragover"].forEach(function (eventName) {
      zone.addEventListener(eventName, function (event) {
        event.preventDefault();
        zone.classList.add("dragover");
      });
    });
    ["dragleave", "drop"].forEach(function (eventName) {
      zone.addEventListener(eventName, function () {
        zone.classList.remove("dragover");
      });
    });
  });

  // Portrait preview before upload.
  document.querySelectorAll("[data-image-input]").forEach(function (input) {
    input.addEventListener("change", function () {
      var file = input.files && input.files[0];
      var preview = document.querySelector("[data-avatar-preview]");
      if (!file || !preview || !file.type.startsWith("image/")) return;
      var image = document.createElement("img");
      image.alt = "Selected portrait preview";
      image.className = "avatar avatar-xl";
      image.src = URL.createObjectURL(file);
      preview.replaceChildren(image);
    });
  });

  // Character counters.
  document.querySelectorAll("[data-counter]").forEach(function (field) {
    var output = document.querySelector("[data-counter-output]");
    if (!output) return;
    function update() { output.textContent = String(field.value.length); }
    field.addEventListener("input", update);
    update();
  });

  // Confirm destructive forms with a clear message.
  document.querySelectorAll("form[data-confirm]").forEach(function (form) {
    form.addEventListener("submit", function (event) {
      if (!window.confirm(form.getAttribute("data-confirm"))) {
        event.preventDefault();
      }
    });
  });
})();
