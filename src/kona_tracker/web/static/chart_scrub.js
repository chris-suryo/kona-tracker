// Drag a finger across a chart and the reading follows it.
//
// **What this replaces.** Every bar is a link to `?selected=N`, so reading
// four hours meant four full page loads -- each one re-asking Fi, re-rendering
// and losing your scroll position. Fine as a fallback, useless as a way to
// look at a day.
//
// **Why the readings are cloned and not built here.** The text under a chart
// is not a number: it is "6h 12m of rest · sleep 5h 40m, naps 32m", with
// `<small>` on every unit, and the rules for it differ per chart. Rebuilding
// that in JavaScript would mean two implementations of the same formatting,
// and the drift would be invisible -- you see the server's version only
// without JavaScript, and this one only with it. So the server renders every
// bucket's reading into a hidden list and this file copies the nodes across.
// Nothing here assigns innerHTML.
//
// **It stays a progressive enhancement.** With this file absent or broken the
// links still work exactly as before; nothing below is load-bearing.
(function () {
  'use strict';

  // Horizontal is ours, vertical is the page's. `touch-action: pan-y` in the
  // stylesheet is the other half of this: without it a drag across the chart
  // would fight the page's own scroll, and with `none` instead you could not
  // scroll past the chart at all -- which on a phone, where the chart is
  // nearly the full width, would trap the page.
  function bars(chart) {
    return [].slice.call(chart.getElementsByTagName('a'));
  }

  function attach(chart) {
    var readings = document.getElementById(chart.dataset.readings);
    var section = chart.parentNode;
    var selection = section ? section.querySelector('.chart-selection') : null;
    if (!readings || !selection) { return; }
    var entries = [].slice.call(readings.children);
    var links = bars(chart);
    if (!entries.length || entries.length !== links.length) { return; }

    // Measured once per gesture. Layout cannot change mid-drag, and calling
    // getBoundingClientRect per pointermove is the classic way to make a
    // scrub janky on a phone.
    var boxes = null;
    var showing = -1;

    function measure() {
      boxes = links.map(function (link) { return link.getBoundingClientRect(); });
    }

    function show(index) {
      if (index === showing || index < 0 || index >= entries.length) { return; }
      showing = index;
      // Clone, then move the children across: a copy, so the hidden list is
      // still intact for the next bar, and node-by-node, so nothing is ever
      // parsed from a string.
      var copy = entries[index].cloneNode(true);
      while (selection.firstChild) { selection.removeChild(selection.firstChild); }
      // Detached from the copy before being attached here. `appendChild`
      // would reparent it anyway -- that is what the DOM does -- but relying
      // on that makes the loop's termination depend on a side effect two
      // lines away, and this loop has no other stopping condition.
      while (copy.firstChild) {
        var child = copy.firstChild;
        copy.removeChild(child);
        selection.appendChild(child);
      }
      links.forEach(function (link, i) {
        if (i === index) { link.setAttribute('aria-current', 'true'); }
        else { link.removeAttribute('aria-current'); }
      });
    }

    function at(clientX) {
      if (!boxes) { measure(); }
      for (var i = 0; i < boxes.length; i++) {
        if (clientX >= boxes[i].left && clientX < boxes[i].right) { return i; }
      }
      // Past either end, hold the end bar rather than losing the reading:
      // a thumb that overshoots by three pixels has not stopped asking.
      if (clientX < boxes[0].left) { return 0; }
      return boxes.length - 1;
    }

    var scrubbing = false;

    chart.addEventListener('pointerdown', function (e) {
      scrubbing = true;
      measure();
      show(at(e.clientX));
      // The chart keeps the pointer, so a thumb that slides off the top of
      // the bars while dragging sideways still belongs to this gesture.
      if (chart.setPointerCapture) {
        try { chart.setPointerCapture(e.pointerId); } catch (err) { /* not fatal */ }
      }
    });

    chart.addEventListener('pointermove', function (e) {
      if (!scrubbing) { return; }
      show(at(e.clientX));
      // Only once a bar has actually changed: calling this on the first
      // move would cancel a vertical scroll that was about to start.
      if (e.cancelable) { e.preventDefault(); }
    });

    function end() { scrubbing = false; boxes = null; }
    chart.addEventListener('pointerup', end);
    chart.addEventListener('pointercancel', end);

    // The links still exist and are still the fallback, but following one now
    // would be a page load that changes nothing on screen: the reading is
    // already showing. Keyboard focus is handled separately below, where
    // Enter *should* still navigate, because that is the accessible way to
    // land on a URL you can share.
    chart.addEventListener('click', function (e) {
      if (e.cancelable) { e.preventDefault(); }
    });

    // Tabbing through the bars moves the reading with the focus ring. Without
    // this, keyboard users get the highlight and no number.
    links.forEach(function (link, i) {
      link.addEventListener('focus', function () { show(i); });
    });
  }

  [].slice.call(document.querySelectorAll('.bar-chart[data-readings]')).forEach(attach);
})();
