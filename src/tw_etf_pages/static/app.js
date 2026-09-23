(function () {
  function qs(sel, root) { return (root || document).querySelector(sel); }
  function qsa(sel, root) { return Array.from((root || document).querySelectorAll(sel)); }

  var tocToggle = qs('[data-toc-toggle]');
  var toc = qs('#toc');
  if (tocToggle && toc) {
    tocToggle.addEventListener('click', function () {
      toc.classList.toggle('open');
    });
  }

  qsa('[data-filter-group]').forEach(function (group) {
    var targetId = group.getAttribute('data-filter-group');
    var table = qs('[data-etf-table="' + targetId + '"]');
    if (!table) return;
    group.addEventListener('click', function (ev) {
      var btn = ev.target.closest('[data-filter]');
      if (!btn) return;
      qsa('[data-filter]', group).forEach(function (b) {
        b.classList.toggle('active', b === btn);
      });
      var mode = btn.getAttribute('data-filter');
      qsa('tr.unchanged', table).forEach(function (row) {
        row.classList.toggle('hidden', mode === 'changed');
      });
    });
  });

  var links = qsa('#toc a[href^="#"]');
  var sections = links
    .map(function (a) { return qs(a.getAttribute('href')); })
    .filter(Boolean);

  function setActive() {
    var y = window.scrollY + 100;
    var current = sections[0];
    sections.forEach(function (sec) {
      if (sec.offsetTop <= y) current = sec;
    });
    links.forEach(function (a) {
      a.classList.toggle('active', current && a.getAttribute('href') === '#' + current.id);
    });
  }

  if (sections.length) {
    window.addEventListener('scroll', setActive, { passive: true });
    setActive();
  }
})();
