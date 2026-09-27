// Theme toggle for the Notes pages; the same behaviour as the inline script in
// index.html. Light is the default; dark applies only when chosen here. The button
// ships `hidden`, so without JavaScript the page stays light and shows no dead control.
(function () {
  var root = document.documentElement;
  function current() {
    var set = root.getAttribute('data-theme');
    return set === 'dark' ? 'dark' : 'light';
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
