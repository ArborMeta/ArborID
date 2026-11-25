/* ==========================================================================
   SPECIES DETAIL VIEW
   Opens when a species card is clicked. Bundled data shows instantly; live
   sections load from the Atlas of Living Australia (map, photos, records,
   taxonomy), Wikipedia (description) and Wikimedia Commons (bark photos).
   ========================================================================== */
(function () {
  const BIE = 'https://bie-ws.ala.org.au/ws';
  const BIOCACHE = 'https://biocache-ws.ala.org.au/ws';
  const MONTHS = ['January', 'February', 'March', 'April', 'May', 'June', 'July',
    'August', 'September', 'October', 'November', 'December'];
  const STATE_CODES = {
    'New South Wales': 'NSW', 'Victoria': 'VIC', 'Queensland': 'QLD', 'Western Australia': 'WA',
    'South Australia': 'SA', 'Tasmania': 'TAS', 'Northern Territory': 'NT', 'Australian Capital Territory': 'ACT'
  };

  let map = null;
  let openToken = 0;   // ignores late responses after another species is opened
  const cache = {};    // url -> parsed JSON (per session)

  const esc = (v) => String(v ?? '').replace(/[&<>"']/g, c =>
    ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
  const stripHtml = (h) => { const d = document.createElement('div'); d.innerHTML = h || ''; return d.textContent.trim(); };
  const normalise = (s) => String(s || '').toLowerCase().replace(/[^a-z]+/g, ' ').trim();

  async function getJSON(url) {
    if (cache[url]) return cache[url];
    const res = await fetch(url);
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    return (cache[url] = await res.json());
  }

  function occQuery(sp) {
    return sp.guid ? `lsid:"${sp.guid}"` : `taxon_name:"${sp.sci}"`;
  }

  // Keep only records that look like wild plants in the native range:
  // in Australia, valid coordinates, not flagged cultivated/introduced, and
  // (when known) inside the states/islands where the species is native.
  const STATE_NAMES = Object.fromEntries(Object.entries(STATE_CODES).map(([n, c]) => [c, n]));
  function nativeFq(sp) {
    // Returned as two separate fq filters: ALA mis-parses them when combined into one.
    const base = 'country:"Australia" AND -degreeOfEstablishment:"cultivated" AND -establishmentMeans:"introduced"';
    let range;
    if (sp.rangeSource === 'native') {
      // States by name; islands by coordinates (their records rarely carry a state).
      const ISLAND_BOXES = {
        'Norfolk Island': 'latitude:[-29.3 TO -28.9] AND longitude:[167.8 TO 168.2]',
        'Lord Howe Island': 'latitude:[-31.9 TO -31.4] AND longitude:[158.9 TO 159.4]'
      };
      const clauses = [];
      const states = sp.states.map(c => STATE_NAMES[c]).filter(Boolean);
      // ALA flags island coordinates as invalid, so the validity check applies to mainland states only.
      if (states.length) clauses.push(`(spatiallyValid:true AND stateProvince:(${states.map(n => `"${n}"`).join(' OR ')}))`);
      (sp.nativeOther || []).forEach(o => clauses.push(ISLAND_BOXES[o] ? `(${ISLAND_BOXES[o]})` : `stateProvince:"${o}"`));
      range = clauses.length ? clauses.join(' OR ') : 'stateProvince:"__none__"';
    } else {
      range = 'spatiallyValid:true';
    }
    return [base, range];
  }

  /* ---------- modal shell ---------- */
  function ensureModal() {
    if (document.getElementById('detail-modal')) return;
    const el = document.createElement('div');
    el.id = 'detail-modal';
    el.className = 'fixed inset-0 z-40 hidden bg-black/70 backdrop-blur-sm flex items-stretch justify-center p-2 sm:p-6';
    el.innerHTML = `
      <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-6xl shadow-2xl flex flex-col overflow-hidden">
        <div class="flex items-start justify-between gap-4 px-5 py-4 border-b border-slate-200 dark:border-slate-800">
          <div id="detail-header" class="min-w-0"></div>
          <button onclick="closeSpeciesDetail()" class="shrink-0 text-slate-400 hover:text-slate-700 dark:hover:text-white text-xl p-1" title="Close (Esc)">
            <i class="fa-solid fa-xmark"></i>
          </button>
        </div>
        <div id="detail-body" class="flex-1 overflow-y-auto p-5"></div>
      </div>`;
    el.addEventListener('click', (e) => { if (e.target === el) closeSpeciesDetail(); });
    document.body.appendChild(el);
    document.addEventListener('keydown', (e) => {
      if (e.key !== 'Escape') return;
      const lb = document.getElementById('lightbox-modal');
      if (lb && !lb.classList.contains('hidden')) closeLightbox();
      else if (!el.classList.contains('hidden')) closeSpeciesDetail();
    });
  }

  const section = (id, icon, title, extra = '') => `
    <section class="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 p-4 ${extra}">
      <h3 class="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3 flex items-center gap-2">
        <i class="fa-solid ${icon} text-eucalyptus-500"></i>${title}
      </h3>
      <div id="${id}">${loading()}</div>
    </section>`;
  const loading = () => `<div class="text-xs text-slate-400 flex items-center gap-2"><i class="fa-solid fa-spinner fa-spin"></i> Loading…</div>`;
  const offline = (what) => `<div class="text-xs text-slate-400"><i class="fa-solid fa-wifi mr-1"></i>Couldn't load ${what}. Check your internet connection.</div>`;
  const empty = (msg) => `<div class="text-xs text-slate-400">${msg}</div>`;
  const setHTML = (id, html, token) => { if (token === openToken) { const n = document.getElementById(id); if (n) n.innerHTML = html; } };

  /* ---------- open / close ---------- */
  window.openSpeciesDetail = function (sci) {
    const sp = ALL_SPECIES.find(s => s.sci === sci);
    if (!sp) return;
    ensureModal();
    const token = ++openToken;
    const photo = getBundledPhoto(sp);
    const parts = sortedPhotos(sp);   // ALA photos sorted by plant part, or null
    const nr = (v) => v && v !== NOT_RECORDED;

    document.getElementById('detail-header').innerHTML = `
      <div class="text-xs font-mono text-slate-400">${esc(sp.family)} · ${esc(sp.genus)}</div>
      <h2 class="font-serif text-xl sm:text-2xl font-bold italic text-slate-900 dark:text-white leading-tight">
        ${esc(sp.sci)} <span id="detail-author" class="not-italic font-sans text-sm font-normal text-slate-400"></span>
      </h2>
      <div class="text-sm text-slate-600 dark:text-slate-300">${esc(sp.common)}</div>
      <div id="detail-badges" class="flex flex-wrap gap-1.5 mt-2"></div>`;

    const facts = [
      ['Bark', sp.bark], ['Foliage', sp.foliage], ['Habitat', sp.biome], ['Height', sp.height]
    ].filter(([, v]) => nr(v));

    document.getElementById('detail-body').innerHTML = `
      <div class="grid grid-cols-1 lg:grid-cols-3 gap-4">
        <div class="space-y-4">
          <div class="rounded-xl overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-900 aspect-[4/3] flex items-center justify-center text-emerald-400 relative">
            ${photo
              ? `<img src="${esc(photo.file)}" class="w-full h-full object-cover cursor-zoom-in" id="detail-main-photo" alt="${esc(sp.sci)}">`
              : renderBotanicalPlateSVG(sp)}
          </div>
          ${photo ? `<div class="text-[10px] text-slate-400 -mt-3">${esc(photo.attr)} · ${esc(photo.license)} · via ${esc(photo.via)}</div>` : ''}
          <section class="rounded-xl border border-slate-200 dark:border-slate-800 p-4 space-y-2 text-xs">
            ${facts.map(([k, v]) => `<div class="flex justify-between gap-3"><span class="text-slate-400">${k}</span><span class="text-right font-medium">${esc(v)}</span></div>`).join('')}
            <div class="flex justify-between gap-3"><span class="text-slate-400">${sp.rangeSource === 'native' ? 'Native to' : 'Recorded in'}</span>
              <span class="flex flex-wrap justify-end gap-1">${[...(sp.states || []), ...(sp.nativeOther || [])].map(s => `<span class="px-1.5 rounded font-mono font-bold bg-slate-100 dark:bg-slate-800">${esc(s)}</span>`).join('') || '—'}</span></div>
            ${sp.occ ? `<div class="flex justify-between gap-3"><span class="text-slate-400">ALA records (all)</span><span class="font-mono">${sp.occ.toLocaleString()}</span></div>` : ''}
            ${sp.curated || sp.custom ? `<p class="pt-2 border-t border-slate-200 dark:border-slate-800 text-slate-500 dark:text-slate-400 leading-relaxed">${esc(sp.notes)}</p>` : ''}
          </section>
          ${section('detail-names', 'fa-tags', 'Common names')}
        </div>
        <div class="lg:col-span-2 space-y-4">
          ${section('detail-wiki', 'fa-book-open', 'Description')}
          <section class="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 p-4">
            <h3 class="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3 flex items-center gap-2">
              <i class="fa-solid fa-map-location-dot text-eucalyptus-500"></i>Native records
              <span id="detail-map-count" class="ml-auto font-mono normal-case tracking-normal"></span>
            </h3>
            <div id="detail-map" class="h-80 rounded-lg overflow-hidden border border-slate-200 dark:border-slate-800 bg-slate-200 dark:bg-slate-800"></div>
            <p class="text-[10px] text-slate-400 mt-1">${sp.rangeSource === 'native'
              ? `Red dots are ALA records inside the species' native range (${esc([...sp.states, ...(sp.nativeOther || [])].join(', ') || 'none in the states')}, per Kew's World Checklist of Vascular Plants; ACT per the Australian Plant Census). Records from overseas, from non-native states, or flagged as cultivated or introduced are hidden. Planted trees within native states can't always be told apart.`
              : `Native range not available for this species, so only overseas records and records flagged as cultivated or introduced are hidden.`}</p>
            <div class="grid grid-cols-1 sm:grid-cols-2 gap-4 mt-4">
              <div><div class="text-[11px] font-semibold text-slate-500 mb-2">Records by state</div><div id="detail-states">${loading()}</div></div>
              <div><div class="text-[11px] font-semibold text-slate-500 mb-2">Records by month <span class="font-normal">(often reflects flowering)</span></div><div id="detail-months">${loading()}</div></div>
            </div>
          </section>
          ${parts ? renderPartSections(sp, parts) : `
            ${section('detail-bark', 'fa-tree', 'Bark photos <span class="normal-case font-normal tracking-normal">— Wikimedia Commons</span>')}
            ${section('detail-gallery', 'fa-images', 'Photos <span class="normal-case font-normal tracking-normal">— native-range records, Atlas of Living Australia</span>')}`}
          ${section('detail-taxonomy', 'fa-sitemap', 'Classification &amp; other names')}
        </div>
      </div>`;

    const main = document.getElementById('detail-main-photo');
    if (main) main.onclick = () => openLightbox(photo.large || photo.file, sp.sci, photo.via,
      `${photo.attr} · ${photo.license} · via ${photo.via}`, photo.file);

    document.getElementById('detail-modal').classList.remove('hidden');
    document.body.style.overflow = 'hidden';

    initMap(sp, token);
    loadSpeciesProfile(sp, token);
    loadWikipedia(sp, token);
    loadFacets(sp, token);
    loadBarkPhotos(sp, token);
    if (!parts) loadGallery(sp, token);
  };

  window.closeSpeciesDetail = function () {
    openToken++;
    if (map) { map.remove(); map = null; }
    const m = document.getElementById('detail-modal');
    if (m) m.classList.add('hidden');
    document.body.style.overflow = '';
  };

  /* ---------- map ---------- */
  function initMap(sp, token) {
    if (map) { map.remove(); map = null; }
    if (typeof L === 'undefined') { setHTML('detail-map', offline('the map library'), token); return; }
    const AUS = [[-44, 112], [-10, 154]];
    map = L.map('detail-map', { zoomSnap: 0.5, minZoom: 2, maxBounds: [[-85, -30], [85, 330]], maxBoundsViscosity: 1 }).fitBounds(AUS);
    L.tileLayer('https://server.arcgisonline.com/ArcGIS/rest/services/World_Topo_Map/MapServer/tile/{z}/{y}/{x}', {
      maxZoom: 18,
      attribution: 'Tiles &copy; Esri &mdash; Esri, HERE, Garmin, USGS, NGA and contributors'
    }).addTo(map);
    const [fqBase, fqRange] = nativeFq(sp);
    // 512px tiles: ALA draws each tile with a full native-range query, so 4x fewer,
    // larger tiles means much less work on ALA's side for the same map.
    const dots = L.tileLayer.wms(`${BIOCACHE}/mapping/wms/reflect?fq=${encodeURIComponent(fqBase)}`, {
      layers: 'ALA:occurrences', format: 'image/png', transparent: true, opacity: 0.9, tileSize: 512,
      q: occQuery(sp), fq: fqRange, ENV: 'color:dc2626;name:circle;size:3;opacity:0.85',
      attribution: 'Records: Atlas of Living Australia', maxZoom: 18
    });
    // "Loading records…" label while ALA is still drawing the dots.
    // (Listeners go on before addTo: Leaflet starts loading as soon as the layer is added.)
    const note = document.createElement('div');
    note.className = 'absolute top-2 right-2 z-[500] bg-slate-900/80 text-white text-[11px] px-2 py-1 rounded pointer-events-none';
    note.innerHTML = '<i class="fa-solid fa-spinner fa-spin mr-1"></i>Loading records…';
    map.getContainer().appendChild(note);
    dots.on('loading', () => { note.hidden = false; });
    dots.on('load', () => { note.hidden = true; });
    dots.addTo(map);
    // The panel lays out after this runs; resize and re-fit once it has its real size.
    [60, 300].forEach(ms => setTimeout(() => { if (map) { map.invalidateSize(); map.fitBounds(AUS); } }, ms));
  }

  /* ---------- ALA species profile: author, names, conservation, taxonomy ---------- */
  async function loadSpeciesProfile(sp, token) {
    try {
      const d = await getJSON(`${BIE}/species/${encodeURIComponent(sp.guid || sp.sci)}`);
      if (token !== openToken) return;
      const author = d.taxonConcept?.author;
      if (author) document.getElementById('detail-author').textContent = author;

      const badges = [];
      Object.entries(d.conservationStatuses || {}).forEach(([region, v]) => {
        const status = typeof v === 'string' ? v : (v.status || '');
        badges.push(`<span class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-red-100 text-red-700 dark:bg-red-950/60 dark:text-red-300 border border-red-300 dark:border-red-900">
          <i class="fa-solid fa-triangle-exclamation mr-1"></i>${esc(region)}: ${esc(status)}</span>`);
      });
      const alaUrl = `https://bie.ala.org.au/species/${encodeURIComponent(sp.guid || sp.sci)}`;
      badges.push(`<a href="${alaUrl}" target="_blank" rel="noopener" class="px-2 py-0.5 rounded-full text-[11px] font-semibold bg-amber-100 text-amber-800 dark:bg-amber-950/50 dark:text-amber-300 border border-amber-300 dark:border-amber-800 hover:underline">
        <i class="fa-solid fa-arrow-up-right-from-square mr-1"></i>Open on ALA</a>`);
      document.getElementById('detail-badges').innerHTML = badges.join('');

      const names = [...new Set((d.commonNames || []).map(c => c.nameString).filter(Boolean))];
      setHTML('detail-names', names.length
        ? `<div class="flex flex-wrap gap-1.5">${names.slice(0, 20).map(n => `<span class="px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700 text-xs">${esc(n)}</span>`).join('')}</div>`
        : empty('No common names recorded on ALA.'), token);

      const c = d.classification || {};
      const ranks = ['kingdom', 'phylum', 'class', 'order', 'family', 'genus'].filter(r => c[r]);
      const syn = [...new Set((d.synonyms || []).map(s => s.nameString).filter(Boolean))];
      setHTML('detail-taxonomy', `
        <div class="flex flex-wrap items-center gap-1 text-xs mb-3">
          ${ranks.map(r => `<span class="px-2 py-0.5 rounded bg-white dark:bg-slate-800 border border-slate-200 dark:border-slate-700"><span class="text-slate-400">${r}</span> ${esc(c[r])}</span>`).join('<i class="fa-solid fa-chevron-right text-[9px] text-slate-400"></i>')}
        </div>
        ${syn.length ? `<div class="text-[11px] text-slate-500 dark:text-slate-400"><span class="font-semibold">Synonyms (older or alternative names):</span> <i>${syn.slice(0, 25).map(esc).join(', ')}</i>${syn.length > 25 ? ` … +${syn.length - 25} more` : ''}</div>` : ''}`, token);
    } catch (e) {
      setHTML('detail-names', offline('names'), token);
      setHTML('detail-taxonomy', offline('the classification'), token);
    }
  }

  /* ---------- Wikipedia description ---------- */
  async function loadWikipedia(sp, token) {
    try {
      const d = await getJSON(`https://en.wikipedia.org/api/rest_v1/page/summary/${encodeURIComponent(sp.sci.replace(/ /g, '_'))}`);
      // Accept only an article about this species (redirects from synonyms are fine).
      const ok = d.type === 'standard' && d.extract &&
        (normalise(d.title) === normalise(sp.sci) || normalise(d.extract).includes(normalise(sp.sci)));
      setHTML('detail-wiki', ok ? `
        <p class="text-sm leading-relaxed text-slate-700 dark:text-slate-300">${esc(d.extract)}</p>
        <a href="${esc(d.content_urls?.desktop?.page)}" target="_blank" rel="noopener" class="inline-block mt-2 text-xs text-eucalyptus-600 dark:text-eucalyptus-400 hover:underline">
          Read the full Wikipedia article <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>
        <span class="text-[10px] text-slate-400 ml-2">Text: Wikipedia, CC BY-SA 4.0</span>`
        : empty('No Wikipedia article for this species yet.'), token);
    } catch (e) {
      setHTML('detail-wiki', e.message === 'HTTP 404' ? empty('No Wikipedia article for this species yet.') : offline('the description'), token);
    }
  }

  /* ---------- record counts by state and month ---------- */
  async function loadFacets(sp, token) {
    try {
      const q = new URLSearchParams({ q: occQuery(sp), facets: 'stateProvince,month', flimit: '-1', pageSize: '0' });
      nativeFq(sp).forEach(f => q.append('fq', f));
      const d = await getJSON(`${BIOCACHE}/occurrences/search?${q}`);
      if (token !== openToken) return;
      const count = document.getElementById('detail-map-count');
      if (count) count.textContent = `${(d.totalRecords || 0).toLocaleString()} native records`;
      const facet = (name) => (d.facetResults || []).find(f => f.fieldName === name)?.fieldResult || [];

      const states = facet('stateProvince').filter(x => STATE_CODES[x.label]).sort((a, b) => b.count - a.count);
      const smax = Math.max(1, ...states.map(x => x.count));
      setHTML('detail-states', states.length ? states.map(x => bar(STATE_CODES[x.label], x.count, smax)).join('')
        : empty('No state records.'), token);

      const byMonth = Object.fromEntries(facet('month').map(x => [x.label, x.count]));
      const vals = MONTHS.map((m, i) => byMonth[m] ?? byMonth[String(i + 1).padStart(2, '0')] ?? byMonth[String(i + 1)] ?? 0);
      const mmax = Math.max(1, ...vals);
      setHTML('detail-months', vals.some(v => v) ? `
        <div class="flex items-end gap-1 h-28">
          ${vals.map((v, i) => `<div class="flex-1 flex flex-col items-center justify-end h-full" title="${MONTHS[i]}: ${v.toLocaleString()} records">
            <div class="w-full rounded-t bg-wattle-500/80" style="height:${Math.max(2, (v / mmax) * 100)}%"></div>
            <div class="text-[9px] text-slate-400 mt-1">${MONTHS[i][0]}</div></div>`).join('')}
        </div>` : empty('No dated records.'), token);
    } catch (e) {
      setHTML('detail-states', offline('record counts'), token);
      setHTML('detail-months', '', token);
    }
  }

  function bar(label, value, max) {
    return `<div class="flex items-center gap-2 text-[11px] mb-1">
      <span class="w-9 font-mono font-bold text-slate-500">${esc(label)}</span>
      <div class="flex-1 bg-slate-200 dark:bg-slate-800 rounded h-2.5 overflow-hidden"><div class="h-full bg-eucalyptus-500" style="width:${(value / max) * 100}%"></div></div>
      <span class="w-14 text-right font-mono text-slate-400">${value.toLocaleString()}</span></div>`;
  }

  /* ---------- bark photos (Wikimedia Commons file titles mentioning bark) ---------- */
  async function loadBarkPhotos(sp, token) {
    try {
      const p = new URLSearchParams({
        action: 'query', generator: 'search', gsrsearch: `"${sp.sci}" bark`, gsrnamespace: '6', gsrlimit: '20',
        prop: 'imageinfo', iiprop: 'url|extmetadata', iiurlwidth: '500', format: 'json', origin: '*'
      });
      const d = await getJSON(`https://commons.wikimedia.org/w/api.php?${p}`);
      const want = normalise(sp.sci);
      const files = Object.values(d.query?.pages || {})
        .filter(pg => /\.(jpe?g|png|webp)$/i.test(pg.title))
        .filter(pg => { const t = normalise(pg.title); return /bark/.test(t) && t.includes(want); })
        .sort((a, b) => (a.index || 0) - (b.index || 0))
        .slice(0, 8);
      if (!files.length) {
        setHTML('detail-bark', empty(`No bark photos found on Wikimedia Commons for this species. <a class="underline" target="_blank" rel="noopener" href="https://commons.wikimedia.org/w/index.php?search=${encodeURIComponent(sp.sci)}">Search Commons</a>`), token);
        return;
      }
      setHTML('detail-bark', thumbGrid(files.map(pg => {
        const ii = pg.imageinfo[0], m = ii.extmetadata || {};
        const credit = `© ${stripHtml(m.Artist?.value) || 'Unknown'} · ${stripHtml(m.LicenseShortName?.value) || 'see Commons'} · via Wikimedia Commons`;
        const large = ii.thumburl.includes('/500px-') ? ii.thumburl.replace('/500px-', '/1600px-') : ii.thumburl;
        return { thumb: ii.thumburl, large, title: pg.title.replace(/^File:/, '').replace(/\.[a-z]+$/i, ''), credit };
      }), sp.sci), token);
    } catch (e) {
      setHTML('detail-bark', offline('bark photos'), token);
    }
  }

  /* ---------- ALA photos sorted by plant part (one section each) ---------- */
  const PART_SECTIONS = [
    ['f', 'Flowers', 'fa-fan'], ['s', 'Fruit & seeds', 'fa-seedling'], ['l', 'Leaves', 'fa-leaf'],
    ['b', 'Bark', 'fa-tree'], ['t', 'Tree', 'fa-mountain-sun']
  ];
  const SHOW_FIRST = 12;

  function sortedPhotos(sp) {
    const pc = window.PHOTO_CATS;
    const rows = pc && pc.species && pc.species[sp.sci];
    if (!rows || !rows.length) return null;
    return rows.map(([id, cats, c, l]) => ({
      cats,
      thumb: `https://images.ala.org.au/image/${id}/thumbnail`,
      large: `https://images.ala.org.au/image/${id}/large`,
      title: '',
      credit: `© ${pc.creators[c] || 'Unknown'} · ${pc.licenses[l] || ''} · via Atlas of Living Australia`
    }));
  }

  window.showAllPhotos = function (btn) {
    btn.closest('section').querySelectorAll('.extra-photo').forEach(el => { el.hidden = false; });
    btn.remove();
  };

  function renderPartSections(sp, photos) {
    const all = `https://bie.ala.org.au/species/${encodeURIComponent(sp.guid || sp.sci)}#gallery`;
    return PART_SECTIONS.map(([code, label, icon]) => {
      const items = photos.filter(p => p.cats.includes(code));
      const more = items.length > SHOW_FIRST
        ? `<button onclick="showAllPhotos(this)" class="mt-2 text-xs font-semibold text-eucalyptus-600 dark:text-eucalyptus-400 hover:underline">Show all ${items.length} photos</button>` : '';
      const wikimedia = code === 'b' ? `
          <div class="mt-4">
            <div class="text-[11px] font-semibold text-slate-500 mb-2">More bark photos — Wikimedia Commons</div>
            <div id="detail-bark">${loading()}</div>
          </div>` : '';
      return `
        <section class="rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 p-4">
          <h3 class="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-3 flex items-center gap-2">
            <i class="fa-solid ${icon} text-eucalyptus-500"></i>${label}
            <span class="ml-auto font-mono normal-case tracking-normal font-normal">${items.length} photo${items.length === 1 ? '' : 's'}</span>
          </h3>
          ${items.length ? thumbGrid(items, sp.sci, SHOW_FIRST) + more
            : empty(`No ${label.toLowerCase()} photos found among this species' ALA photos.`)}
          ${wikimedia}
        </section>`;
    }).join('') + `
      <p class="text-[10px] text-slate-400 -mt-2 px-1">Photos from native-range ALA records, sorted automatically by an image-recognition model, so a few may be in the wrong section; a photo showing two parts can appear in both.
        <a href="${all}" target="_blank" rel="noopener" class="text-eucalyptus-600 dark:text-eucalyptus-400 hover:underline whitespace-nowrap">See all photos on ALA <i class="fa-solid fa-arrow-up-right-from-square text-[9px]"></i></a></p>`;
  }

  // Live, unsorted gallery for species without sorted photos.
  async function loadGallery(sp, token) {
    try {
      const q = new URLSearchParams({ q: occQuery(sp), pageSize: '40', sort: 'eventDate', dir: 'desc' });
      q.append('fq', 'multimedia:Image');
      nativeFq(sp).forEach(f => q.append('fq', f));
      const d = await getJSON(`${BIOCACHE}/occurrences/search?${q}`);
      const open = (lic) => /CC|public|PD/i.test(lic || '');
      const items = (d.occurrences || []).filter(o => o.image && open(o.license)).slice(0, 24).map(o => {
        const who = (o.recordedBy || o.collectors || [])[0] || o.dataResourceName || 'Unknown';
        const when = o.eventDate ? new Date(o.eventDate).getFullYear() : '';
        const where = STATE_CODES[o.stateProvince] || o.stateProvince || '';
        return {
          thumb: o.smallImageUrl, large: o.largeImageUrl || o.imageUrl,
          title: [where, when].filter(Boolean).join(' · '),
          credit: `© ${who} · ${o.license} · ${o.dataResourceName || 'ALA'}`
        };
      });
      const all = `https://bie.ala.org.au/species/${encodeURIComponent(sp.guid || sp.sci)}#gallery`;
      setHTML('detail-gallery', items.length
        ? thumbGrid(items, sp.sci) + `<a href="${all}" target="_blank" rel="noopener" class="inline-block mt-3 text-xs text-eucalyptus-600 dark:text-eucalyptus-400 hover:underline">
            See all ${(d.totalRecords || items.length).toLocaleString()} records with photos on ALA <i class="fa-solid fa-arrow-up-right-from-square text-[10px]"></i></a>`
        : empty('No openly licensed photos on ALA for this species.'), token);
    } catch (e) {
      setHTML('detail-gallery', offline('the photo gallery'), token);
    }
  }

  // Thumbnails; clicking one opens the shared lightbox with its credit.
  function thumbGrid(items, sci, limit = Infinity) {
    const id = 'g' + Math.random().toString(36).slice(2);
    window[id] = items;
    return `<div class="grid grid-cols-3 sm:grid-cols-4 md:grid-cols-6 gap-2">
      ${items.map((it, i) => `
        <button ${i >= limit ? 'hidden' : ''} class="${i >= limit ? 'extra-photo ' : ''}group relative aspect-square rounded-lg overflow-hidden bg-slate-200 dark:bg-slate-800"
          onclick="openLightbox(window['${id}'][${i}].large, ${esc(JSON.stringify(sci))}, '', window['${id}'][${i}].credit, window['${id}'][${i}].thumb)"
          title="${esc(it.title)}">
          <img src="${esc(it.thumb)}" loading="lazy" onerror="this.closest('button').remove()" alt="${esc(it.title)}" class="w-full h-full object-cover group-hover:scale-105 transition">
          ${it.title ? `<span class="absolute bottom-0 inset-x-0 bg-black/55 text-white text-[9px] px-1 py-0.5 truncate">${esc(it.title)}</span>` : ''}
        </button>`).join('')}
    </div>`;
  }
})();
