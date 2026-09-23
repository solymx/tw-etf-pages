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

  /* ---- 近20天持股趨勢 (Chart.js) ---- */
  function sharesToLots(v) {
    if (v == null) return null;
    return Math.round((Number(v) / 1000) * 1000) / 1000;
  }

  function formatLotsLabel(v) {
    if (v == null || Number.isNaN(v)) return '—';
    var abs = Math.abs(v);
    if (Math.abs(abs - Math.round(abs)) < 1e-9) {
      return (v > 0 && String(v).indexOf('+') !== 0 ? '' : '') + Math.round(v).toLocaleString('zh-TW') + ' 張';
    }
    return v.toLocaleString('zh-TW', { maximumFractionDigits: 3 }) + ' 張';
  }

  var PALETTE = [
    '#e84967', '#2563eb', '#0d9488', '#d97706', '#7c3aed',
    '#db2777', '#0891b2', '#65a30d', '#ea580c', '#4f46e5'
  ];

  function initTrend() {
    var dataEl = qs('#trend-data');
    var canvas = qs('#trend-chart');
    var select = qs('#trend-stock-select');
    if (!dataEl || !canvas || !select) return;
    if (typeof Chart === 'undefined') {
      console.warn('Chart.js 未載入，跳過趨勢圖');
      return;
    }

    var trend;
    try {
      trend = JSON.parse(dataEl.textContent);
    } catch (err) {
      console.error('trend JSON parse failed', err);
      return;
    }

    var byCode = {};
    (trend.stocks || []).forEach(function (s) {
      byCode[s.stock_code] = s;
    });

    // Populate select: intermittent first, then by activity
    var ordered = (trend.stocks || []).slice().sort(function (a, b) {
      if (b.intermittent_buy_score !== a.intermittent_buy_score) {
        return b.intermittent_buy_score - a.intermittent_buy_score;
      }
      if (b.buy_days !== a.buy_days) return b.buy_days - a.buy_days;
      return (b.activity || 0) - (a.activity || 0);
    });

    ordered.forEach(function (s) {
      var opt = document.createElement('option');
      opt.value = s.stock_code;
      var tag = s.intermittent_label ? ' · ' + s.intermittent_label : '';
      opt.textContent = s.stock_code + ' ' + s.stock_name + tag;
      select.appendChild(opt);
    });

    var chart = new Chart(canvas.getContext('2d'), {
      type: 'line',
      data: { labels: trend.dates || [], datasets: [] },
      options: {
        responsive: true,
        maintainAspectRatio: true,
        interaction: { mode: 'index', intersect: false },
        plugins: {
          legend: { position: 'bottom' },
          tooltip: {
            callbacks: {
              label: function (ctx) {
                var v = ctx.parsed.y;
                return ctx.dataset.label + '：' + formatLotsLabel(v);
              }
            }
          }
        },
        scales: {
          x: {
            title: { display: true, text: '資料日' },
            ticks: { maxRotation: 45, minRotation: 0 }
          },
          y: {
            title: { display: true, text: '持股（張）' },
            ticks: {
              callback: function (v) {
                return Number(v).toLocaleString('zh-TW');
              }
            }
          }
        }
      }
    });

    function selectedCodes() {
      return Array.from(select.selectedOptions).map(function (o) { return o.value; });
    }

    function setSelected(codes) {
      var set = {};
      (codes || []).forEach(function (c) { set[c] = true; });
      Array.from(select.options).forEach(function (o) {
        o.selected = !!set[o.value];
      });
      refreshChart();
    }

    function refreshChart() {
      var codes = selectedCodes();
      var countEl = qs('[data-trend-selected-count]');
      if (countEl) countEl.textContent = String(codes.length);

      chart.data.datasets = codes.map(function (code, i) {
        var s = byCode[code];
        var label = s ? (s.stock_code + ' ' + s.stock_name) : code;
        var color = PALETTE[i % PALETTE.length];
        return {
          label: label,
          data: (s ? s.shares : []).map(sharesToLots),
          borderColor: color,
          backgroundColor: color,
          tension: 0.25,
          spanGaps: true,
          pointRadius: 3,
          pointHoverRadius: 5,
          borderWidth: 2
        };
      });
      chart.update();

      qsa('.trend-pick-row').forEach(function (row) {
        var c = row.getAttribute('data-pick-code');
        row.classList.toggle('is-selected', codes.indexOf(c) !== -1);
      });
    }

    select.addEventListener('change', refreshChart);

    qsa('[data-trend-preset]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        var preset = btn.getAttribute('data-trend-preset');
        if (preset === 'clear') {
          setSelected([]);
          return;
        }
        if (preset === 'default') {
          setSelected(trend.default_codes || []);
          return;
        }
        if (preset === 'intermittent') {
          var codes = (trend.top_intermittent || []).map(function (t) {
            return t.stock_code;
          }).slice(0, 5);
          if (!codes.length) codes = trend.default_codes || [];
          setSelected(codes);
        }
      });
    });

    qsa('.trend-pick-row').forEach(function (row) {
      function toggle() {
        var code = row.getAttribute('data-pick-code');
        var cur = selectedCodes();
        var idx = cur.indexOf(code);
        if (idx === -1) cur.push(code);
        else cur.splice(idx, 1);
        setSelected(cur);
      }
      row.addEventListener('click', toggle);
      row.addEventListener('keydown', function (ev) {
        if (ev.key === 'Enter' || ev.key === ' ') {
          ev.preventDefault();
          toggle();
        }
      });
    });

    setSelected(trend.default_codes || []);
  }

  function whenChartReady(fn, tries) {
    tries = tries == null ? 40 : tries;
    if (typeof Chart !== 'undefined') {
      fn();
      return;
    }
    if (tries <= 0) {
      console.warn('Chart.js 未載入，跳過趨勢圖');
      return;
    }
    setTimeout(function () { whenChartReady(fn, tries - 1); }, 50);
  }

  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', function () {
      whenChartReady(initTrend);
    });
  } else {
    whenChartReady(initTrend);
  }
})();
