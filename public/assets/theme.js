// Theme toggle for the Notes pages; the same behaviour as the inline script in
// index.html. The button ships `hidden`, so without JavaScript the page keeps
// prefers-color-scheme and shows no dead control.
(function () {
  var root = document.documentElement;
  var mq = window.matchMedia('(prefers-color-scheme: dark)');
  function current() {
    var set = root.getAttribute('data-theme');
    return set === 'dark' || set === 'light' ? set : (mq.matches ? 'dark' : 'light');
  }
  function label(b) {
    b.setAttribute('aria-label', 'Switch to ' + (current() === 'dark' ? 'light' : 'dark') + ' theme');
  }
  document.querySelectorAll('.theme').forEach(function (b) {
    b.hidden = false;
    label(b);
    b.addEventListener('click', function () {
      var next = current() === 'dark' ? 'light' : 'dark';
      root.setAttribute('data-theme', next);
      try { localStorage.setItem('theme', next); } catch (e) {}
      label(b);
    });
  });
})();
