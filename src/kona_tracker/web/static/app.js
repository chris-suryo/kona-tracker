// Shared by every page. No framework, no build step: the pages are HTML
// rendered by the server, and this file only does what CSS cannot.
(function () {
  // Optional images (Kona's photo, when Fi has none) fall back to the
  // initial behind them. Formerly an inline onerror= handler; the page now
  // ships a Content-Security-Policy that forbids inline script, so the
  // listener lives here. `error` does not bubble, hence capture; images that
  // failed before this script ran are caught by the second pass.
  function dropIfBroken(img) {
    if (img.tagName === 'IMG' && img.hasAttribute('data-optional')) { img.remove(); }
  }
  document.addEventListener('error', function (e) { dropIfBroken(e.target); }, true);
  document.querySelectorAll('img[data-optional]').forEach(function (img) {
    if (img.complete && img.naturalWidth === 0) { img.remove(); }
  });
})();
