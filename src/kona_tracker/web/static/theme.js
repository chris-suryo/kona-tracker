// Light, dark, or whatever the phone says. Applied before the page paints.
//
// This file is loaded in <head> WITHOUT `defer`, and that is deliberate: a
// deferred script runs after the document is parsed, so the page would paint
// in the phone's theme and then snap to the chosen one. A flash of the wrong
// colours on every single navigation is worse than having no choice at all.
//
// It cannot be inline, which is the usual way to do this, because the page
// carries a Content-Security-Policy of `script-src 'self'` and inline script
// is exactly what that forbids. So: a separate file, tiny, blocking, first.
//
// Keep it that way. Adding `defer` here reintroduces the flash silently.
(function () {
  'use strict';
  var KEY = 'kona-theme';

  function read() {
    // Private browsing and blocked site data both make this throw rather
    // than return null, and a theme preference is never worth a broken page.
    try {
      var saved = window.localStorage.getItem(KEY);
      return saved === 'light' || saved === 'dark' ? saved : '';
    } catch (e) {
      return '';
    }
  }

  function apply(choice) {
    // No attribute means "follow the phone", which is what the CSS media
    // query already does. Removing it is how you get back to that.
    if (choice) {
      document.documentElement.setAttribute('data-theme', choice);
    } else {
      document.documentElement.removeAttribute('data-theme');
    }
  }

  apply(read());

  // The rest is for the control on the Settings page, which does not exist
  // yet when this runs. Exposed rather than wired here for that reason.
  window.KonaTheme = {
    get: read,
    set: function (choice) {
      try {
        if (choice) { window.localStorage.setItem(KEY, choice); }
        else { window.localStorage.removeItem(KEY); }
      } catch (e) {
        // Saving failed, so the choice lasts until this page is closed.
        // Applying it anyway is better than appearing to ignore the tap.
      }
      apply(choice);
    }
  };
})();
