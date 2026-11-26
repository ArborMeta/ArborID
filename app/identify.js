/* ArborID: Identify a plant from one or more photos.
 * The page sends the photos to the desktop app (main.py -> atlas_identify.py), which reads the GPS
 * position from the photos, scores every atlas species with the built-in image model, favours
 * species with native records near that position, and returns a ranked list with percentages.
 * Only available in the desktop app (needs window.pywebview).
 */
(function () {
  const STATES = [['', 'Unknown / anywhere'], ['NSW', 'New South Wales'], ['VIC', 'Victoria'], ['QLD', 'Queensland'],
    ['SA', 'South Australia'], ['WA', 'Western Australia'], ['TAS', 'Tasmania'], ['NT', 'Northern Territory'],
    ['ACT', 'Australian Capital Territory']];
  let photos = [];   // {name, dataUrl, lat, lon, taken}
  let busy = false;

  const $ = (id) => document.getElementById(id);
  const escH = (s) => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

  function ensureModal() {
    if ($('identify-modal')) return;
    const el = document.createElement('div');
    el.id = 'identify-modal';
    el.className = 'fixed inset-0 z-[35] hidden bg-black/70 backdrop-blur-sm flex items-stretch justify-center p-2 sm:p-6';
    el.innerHTML = `
      <div class="bg-white dark:bg-slate-900 border border-slate-200 dark:border-slate-800 rounded-2xl w-full max-w-4xl shadow-2xl flex flex-col overflow-hidden">
        <div class="flex items-start justify-between gap-4 px-5 py-4 border-b border-slate-200 dark:border-slate-800">
          <div>
            <h2 class="font-serif text-xl font-bold text-slate-900 dark:text-white flex items-center gap-2">
              <i class="fa-solid fa-camera text-eucalyptus-500"></i> Identify a plant</h2>
            <div class="text-xs text-slate-500 dark:text-slate-400 mt-0.5">Add one or more photos of the same plant. Bark, leaves, flowers, fruit and the whole tree all help.</div>
          </div>
          <button onclick="closeIdentify()" class="shrink-0 text-slate-400 hover:text-slate-700 dark:hover:text-white text-xl p-1" title="Close (Esc)">
            <i class="fa-solid fa-xmark"></i></button>
        </div>
        <div class="flex-1 overflow-y-auto p-5 space-y-4">
          <label id="id-drop" class="block rounded-xl border-2 border-dashed border-slate-300 dark:border-slate-700 hover:border-eucalyptus-500 p-5 text-center cursor-pointer transition">
            <input id="id-file" type="file" accept="image/jpeg,image/png,image/webp,image/heic" multiple class="hidden">
            <i class="fa-solid fa-images text-2xl text-eucalyptus-500"></i>
            <div class="text-sm font-semibold text-slate-700 dark:text-slate-200 mt-1">Choose photos or drop them here</div>
            <div class="text-xs text-slate-400">Use the original photo files, so their GPS location is included</div>
          </label>
          <div id="id-thumbs" class="flex flex-wrap gap-2"></div>
          <div id="id-location" class="hidden rounded-xl border border-slate-200 dark:border-slate-800 bg-slate-50 dark:bg-slate-950/40 p-3 text-xs"></div>
          <div class="flex justify-end">
            <button id="id-run" onclick="runIdentify()" disabled class="px-4 py-2 rounded-xl bg-eucalyptus-600 hover:bg-eucalyptus-700 disabled:opacity-40 disabled:cursor-not-allowed font-semibold text-white text-sm transition flex items-center gap-2">
              <i class="fa-solid fa-magnifying-glass"></i> Identify</button>
          </div>
          <div id="id-results"></div>
        </div>
      </div>`;
    el.addEventListener('click', (e) => { if (e.target === el) closeIdentify(); });
    document.body.appendChild(el);
    $('id-file').addEventListener('change', (e) => { addFiles(e.target.files); e.target.value = ''; });
    const drop = $('id-drop');
    drop.addEventListener('dragover', (e) => { e.preventDefault(); drop.classList.add('border-eucalyptus-500'); });
    drop.addEventListener('dragleave', () => drop.classList.remove('border-eucalyptus-500'));
    drop.addEventListener('drop', (e) => { e.preventDefault(); drop.classList.remove('border-eucalyptus-500'); addFiles(e.dataTransfer.files); });
    document.addEventListener('keydown', (e) => {
      if (e.key === 'Escape' && !el.classList.contains('hidden')) {
        const detail = $('detail-modal');
        if (!detail || detail.classList.contains('hidden')) closeIdentify();
      }
    });
  }

  window.openIdentify = function () {
    ensureModal();
    $('identify-modal').classList.remove('hidden');
    document.body.style.overflow = 'hidden';
  };
  window.closeIdentify = function () {
    $('identify-modal').classList.add('hidden');
    document.body.style.overflow = '';
  };

  function readFile(f) {
    return new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsDataURL(f); });
  }

  async function addFiles(list) {
    const files = [...list].filter(f => f.type.startsWith('image/') || /\.(jpe?g|png|webp|heic)$/i.test(f.name));
    for (const f of files.slice(0, 8 - photos.length)) {
      const dataUrl = await readFile(f);
      const p = { name: f.name, dataUrl, lat: null, lon: null, taken: null, thumb: null };
      photos.push(p);
      try {
        const info = await window.pywebview.api.photo_info(dataUrl);
        Object.assign(p, info);
      } catch (e) { p.error = 'Could not read this photo'; }
      renderThumbs();
    }
    $('id-results').innerHTML = '';
  }

  window.removeIdentifyPhoto = function (i) { photos.splice(i, 1); renderThumbs(); $('id-results').innerHTML = ''; };

  function gpsPhoto() { return photos.find(p => p.lat != null && p.lon != null); }

  function renderThumbs() {
    $('id-thumbs').innerHTML = photos.map((p, i) => `
      <div class="relative w-24 h-24 rounded-lg overflow-hidden border border-slate-200 dark:border-slate-700 bg-slate-100 dark:bg-slate-800">
        <img src="${p.thumb || p.dataUrl}" class="w-full h-full object-cover" alt="">
        <button onclick="removeIdentifyPhoto(${i})" class="absolute top-1 right-1 w-5 h-5 rounded-full bg-black/60 text-white text-[10px]" title="Remove"><i class="fa-solid fa-xmark"></i></button>
        <span class="absolute bottom-1 left-1 text-[10px] px-1 rounded ${p.lat != null ? 'bg-eucalyptus-600' : 'bg-slate-600'} text-white">
          <i class="fa-solid ${p.lat != null ? 'fa-location-dot' : 'fa-location-crosshairs'}"></i> ${p.lat != null ? 'GPS' : 'no GPS'}</span>
      </div>`).join('');
    $('id-run').disabled = !photos.length || busy;
    const loc = $('id-location');
    if (!photos.length) { loc.classList.add('hidden'); return; }
    loc.classList.remove('hidden');
    const g = gpsPhoto();
    if (g) {
      loc.innerHTML = `<i class="fa-solid fa-location-dot text-eucalyptus-500 mr-1"></i>
        <b>Location from photo:</b> ${g.lat.toFixed(4)}, ${g.lon.toFixed(4)}${g.taken ? ` · taken ${escH(g.taken)}` : ''}.
        Species with native records near here are favoured.`;
    } else {
      const prev = $('id-state') ? $('id-state').value : '';
      loc.innerHTML = `<i class="fa-solid fa-location-crosshairs text-amber-500 mr-1"></i>
        <b>No GPS location in these photos.</b> Choose where it was found to narrow it down:
        <select id="id-state" class="ml-1 px-2 py-1 rounded-lg bg-white dark:bg-slate-800 border border-slate-300 dark:border-slate-700">
          ${STATES.map(([c, n]) => `<option value="${c}" ${c === prev ? 'selected' : ''}>${n}</option>`).join('')}
        </select>`;
    }
  }

  window.runIdentify = async function () {
    if (!photos.length || busy) return;
    busy = true;
    $('id-run').disabled = true;
    $('id-results').innerHTML = `<div class="text-sm text-slate-500 flex items-center gap-2"><i class="fa-solid fa-spinner fa-spin"></i>
      Looking at ${photos.length} photo${photos.length > 1 ? 's' : ''}… (the first time takes a few seconds longer)</div>`;
    try {
      const g = gpsPhoto();
      const res = await window.pywebview.api.identify(photos.map(p => p.dataUrl),
        g ? g.lat : null, g ? g.lon : null, g ? null : ($('id-state') ? $('id-state').value || null : null));
      if (res.error) throw new Error(res.error);
      renderResults(res, g);
    } catch (e) {
      $('id-results').innerHTML = `<div class="text-sm text-red-600"><i class="fa-solid fa-triangle-exclamation mr-1"></i>${escH(e.message || e)}</div>`;
    }
    busy = false;
    $('id-run').disabled = !photos.length;
  };

  function renderResults(res, g) {
    const top = res.results;
    const max = Math.max(...top.map(r => r.pct), 1);
    const rows = top.map((r, i) => {
      const sp = ALL_SPECIES.find(s => s.sci === r.sci);
      const ph = sp ? getBundledPhoto(sp) : null;
      const near = r.nearby == null ? '' : r.nearby > 0
        ? `<span class="text-eucalyptus-600 dark:text-eucalyptus-400"><i class="fa-solid fa-location-dot"></i> ${r.nearby.toLocaleString()} native record${r.nearby === 1 ? '' : 's'} within ${res.near_km} km</span>`
        : `<span class="text-amber-600"><i class="fa-solid fa-circle-exclamation"></i> no native records within ${res.near_km} km</span>`;
      return `
        <button onclick="openSpeciesDetail('${escH(r.sci).replace(/'/g, "\\'")}')" class="w-full text-left flex items-center gap-3 p-2 rounded-xl hover:bg-slate-100 dark:hover:bg-slate-800 transition">
          <div class="w-6 text-right text-xs font-mono text-slate-400">${i + 1}</div>
          <div class="w-14 h-14 shrink-0 rounded-lg overflow-hidden bg-slate-100 dark:bg-slate-800 flex items-center justify-center">
            ${ph ? `<img src="${escH(ph.file)}" class="w-full h-full object-cover" alt="">` : '<i class="fa-solid fa-tree text-slate-400"></i>'}</div>
          <div class="flex-1 min-w-0">
            <div class="font-serif italic font-semibold text-slate-900 dark:text-white truncate">${escH(r.sci)}</div>
            <div class="text-xs text-slate-500 dark:text-slate-400 truncate">${escH(r.common || '')}${r.common ? ' · ' : ''}${escH(r.family)}</div>
            <div class="text-[11px] mt-0.5">${near}</div>
          </div>
          <div class="w-40 shrink-0">
            <div class="text-right text-sm font-bold ${i === 0 ? 'text-eucalyptus-600 dark:text-eucalyptus-400' : 'text-slate-700 dark:text-slate-200'}">${r.pct < 0.1 ? '<0.1' : r.pct}%</div>
            <div class="h-1.5 rounded-full bg-slate-200 dark:bg-slate-800 overflow-hidden"><div class="h-full bg-eucalyptus-500" style="width:${(r.pct / max) * 100}%"></div></div>
          </div>
        </button>`;
    }).join('');
    const genera = res.genera.map(x => `<span class="px-2 py-0.5 rounded-full bg-slate-100 dark:bg-slate-800 text-slate-700 dark:text-slate-200"><i>${escH(x.genus)}</i> ${x.pct}%</span>`).join(' ');
    $('id-results').innerHTML = `
      <div class="rounded-xl border border-slate-200 dark:border-slate-800 p-3">
        <div class="text-xs font-bold uppercase tracking-wider text-slate-500 dark:text-slate-400 mb-2">Most likely species</div>
        ${rows}
        <div class="text-xs mt-3 flex flex-wrap items-center gap-1.5"><span class="text-slate-500">By genus:</span> ${genera}</div>
        <div class="text-[11px] text-slate-400 mt-3 leading-relaxed">
          Percentages are the model's estimate that it's each of the atlas's ${ALL_SPECIES.length.toLocaleString()} species; on test photos they were roughly right on average.
          ${g ? '' : 'Without a GPS location the result relies much more on the photos alone. '}
          ${res.month ? `Species recorded in ${['January', 'February', 'March', 'April', 'May', 'June', 'July', 'August', 'September', 'October', 'November', 'December'][res.month - 1]} (when the photo was taken) are favoured slightly. ` : ''}
          Exact species is hard from photos for eucalypts and wattles: check buds, fruit and leaves on the species page before relying on it.
          A plant not in the atlas (e.g. a garden or weed species) will still be matched to its nearest atlas species.</div>
      </div>`;
  }

  // show the header button only inside the desktop app
  function enable() {
    const b = $('identify-btn');
    if (b && window.pywebview && window.pywebview.api && window.pywebview.api.identify) b.classList.remove('hidden');
  }
  window.addEventListener('pywebviewready', enable);
  document.addEventListener('DOMContentLoaded', enable);
})();
