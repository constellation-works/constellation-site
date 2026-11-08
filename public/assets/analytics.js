// Progressive enhancement for the analytics pages. Without JavaScript every
// experiment and every metric group renders stacked, and the picker cards and
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
})();
