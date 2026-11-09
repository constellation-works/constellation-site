// Progressive enhancement for the analytics pages. Without JavaScript every
// experiment, metric group, role and reviewer board renders stacked, and the picker cards and
// group links are plain in-page anchors. Nothing here fetches data.
(function () {
  function sectionFor(nodes, hash) {
    if (!hash || hash.length < 2) return null;
    var target;
    try { target = document.getElementById(decodeURIComponent(hash.slice(1))); } catch (e) { return null; }
    if (!target) return null;
    for (var i = 0; i < nodes.length; i++) {
      if (nodes[i] === target || nodes[i].contains(target)) return { section: nodes[i], target: target };
    }
    return null;
  }

  // Experiments: the picker cards show one experiment at a time.
  var cards = Array.prototype.slice.call(document.querySelectorAll('.exp-card[data-exp]'));
  var experiments = Array.prototype.slice.call(document.querySelectorAll('[data-exp-section]'));
  if (cards.length > 1 && experiments.length > 1) {
    var showExperiment = function (id) {
      experiments.forEach(function (s) { s.hidden = s.id !== id; });
      cards.forEach(function (c) {
        if (c.getAttribute('data-exp') === id) c.setAttribute('aria-current', 'true');
        else c.removeAttribute('aria-current');
      });
    };
    var fromHash = function () {
      var hit = sectionFor(experiments, location.hash);
      if (hit) {
        showExperiment(hit.section.id);
        if (hit.target !== hit.section) hit.target.scrollIntoView();
      }
      return hit;
    };
    if (!fromHash()) showExperiment(experiments[0].id);
    cards.forEach(function (card) {
      card.addEventListener('click', function (event) {
        event.preventDefault();
        var id = card.getAttribute('data-exp');
        showExperiment(id);
        try { history.replaceState(null, '', '#' + id); } catch (e) {}
        var section = document.getElementById(id);
        if (section && section.getBoundingClientRect().top < 0) section.scrollIntoView();
      });
    });
    window.addEventListener('hashchange', fromHash);
    document.documentElement.classList.add('exp-picking');
  }

  // Experiments: "Clear signals only" keeps the primary row and rows with a clear cell.
  document.querySelectorAll('.sc-filter').forEach(function (button) {
    button.hidden = false;
    button.addEventListener('click', function () {
      var on = button.getAttribute('aria-pressed') !== 'true';
      button.setAttribute('aria-pressed', on ? 'true' : 'false');
      var scope = button.closest('section');
      if (scope) scope.classList.toggle('clear-only', on);
    });
  });

  // Metrics: the group links become tabs. "All" restores the stacked page.
  var nav = document.querySelector('.group-nav');
  var groups = Array.prototype.slice.call(document.querySelectorAll('[data-group]'));
  if (nav && groups.length > 1) {
    var tabs = Array.prototype.slice.call(nav.querySelectorAll('a[data-tab]'));
    var showGroup = function (name) {
      groups.forEach(function (g) { g.hidden = name !== 'all' && g.getAttribute('data-group') !== name; });
      tabs.forEach(function (t) {
        if (t.getAttribute('data-tab') === name) t.setAttribute('aria-current', 'true');
        else t.removeAttribute('aria-current');
      });
    };
    var groupFromHash = function () {
      var hit = sectionFor(groups, location.hash);
      if (hit) {
        var current = nav.querySelector('a[aria-current]');
        var showingAll = current && current.getAttribute('data-tab') === 'all';
        if (!showingAll || hit.section.hidden) showGroup(hit.section.getAttribute('data-group'));
        hit.target.scrollIntoView();
      }
      return hit;
    };
    nav.querySelectorAll('[hidden]').forEach(function (el) { el.hidden = false; });
    if (!groupFromHash()) showGroup(groups[0].getAttribute('data-group'));
    tabs.forEach(function (tab) {
      tab.addEventListener('click', function (event) {
        event.preventDefault();
        var name = tab.getAttribute('data-tab');
        showGroup(name);
        try { history.replaceState(null, '', name === 'all' ? location.pathname : '#' + name); } catch (e) {}
      });
    });
    window.addEventListener('hashchange', groupFromHash);
  }
  // Agents: the reviewer boards become a provisional/settled toggle. Without
  // JavaScript both boards render stacked, each with its own window.
  document.querySelectorAll('.board-toggle').forEach(function (toggle) {
    var buttons = Array.prototype.slice.call(toggle.querySelectorAll('button[data-board]'));
    var boards = buttons.map(function (b) { return document.getElementById(b.getAttribute('data-board')); });
    if (buttons.length < 2 || boards.some(function (b) { return !b; })) return;
    var show = function (id) {
      boards.forEach(function (b) { b.hidden = b.id !== id; });
      buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-board') === id ? 'true' : 'false'); });
    };
    var fromHash = function () {
      var hit = sectionFor(boards, location.hash);
      if (hit) { show(hit.section.id); return true; }
      return false;
    };
    if (!fromHash()) show(boards[0].id);
    buttons.forEach(function (b) {
      b.addEventListener('click', function () { show(b.getAttribute('data-board')); });
    });
    window.addEventListener('hashchange', fromHash);
    toggle.hidden = false;
  });

  // Reliability: sort failing jobs by count (the rendered order) or by rate.
  // Small samples sink when sorted by rate.
  document.querySelectorAll('.job-sort').forEach(function (toggle) {
    var section = toggle.closest('section');
    var table = section && section.querySelector('table.jobs');
    if (!table) return;
    var body = table.tBodies[0];
    var rows = Array.prototype.slice.call(body.rows);
    var num = function (row, key) { return parseFloat(row.getAttribute('data-' + key)); };
    var buttons = Array.prototype.slice.call(toggle.querySelectorAll('button[data-sort]'));
    var sortBy = function (mode) {
      var sorted = rows.slice().sort(function (a, b) {
        if (mode === 'rate') {
          return (num(a, 'low') - num(b, 'low')) || (num(b, 'rate') - num(a, 'rate')) || (num(a, 'order') - num(b, 'order'));
        }
        return num(a, 'order') - num(b, 'order');
      });
      sorted.forEach(function (row) { body.appendChild(row); });
      table.setAttribute('data-sort', mode);
      buttons.forEach(function (b) { b.setAttribute('aria-pressed', b.getAttribute('data-sort') === mode ? 'true' : 'false'); });
      section.querySelectorAll('[data-sort-note]').forEach(function (note) { note.hidden = note.getAttribute('data-sort-note') !== mode; });
    };
    buttons.forEach(function (b) {
      b.addEventListener('click', function () { sortBy(b.getAttribute('data-sort')); });
    });
    toggle.hidden = false;
  });
})();
