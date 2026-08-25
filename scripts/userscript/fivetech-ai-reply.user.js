// ==UserScript==
// @name         FiveTech - Responder con IA
// @namespace    fivetechsoft
// @version      1.0.0
// @description  Anade un boton "Responder con IA" en los temas de fivetechsupport.com: lee el thread completo, genera una respuesta con los modelos free de OpenCode Zen y la deja escrita en el editor para revisarla antes de enviar
// @author       FiveTech AI Assistant
// @match        https://fivetechsoft.com/forums/viewtopic.php*
// @match        https://www.fivetechsupport.com/forums/viewtopic.php*
// @match        https://fivetechsupport.com/forums/viewtopic.php*
// @connect      api.fivetechsoft.com
// @grant        GM_xmlhttpRequest
// @run-at       document-idle
// ==/UserScript==

(function () {
  'use strict';

  var ZEN_HOST = 'api.fivetechsoft.com';
  // orden de preferencia: Ox Alpha primero, luego el resto de modelos free
  var PREFERRED = ['x-preview-f-free', 'mimo-v2.5-free'];

  var SYSTEM_PROMPT = [
    'Eres un asistente tecnico en los foros de soporte de FiveTech Software',
    '(FiveWin, Harbour, xHarbour, mod_harbour, FiveLinux, FiveMac, FiveTouch).',
    'Responde a la pregunta pendiente del thread de forma util, tecnica y breve.',
    'Responde en el mismo idioma en que este escrita la pregunta.',
    'Usa BBCode de phpBB si necesitas codigo ([code]...[/code]).',
    'REGLA DE CONFIDENCIALIDAD: si el thread contiene codigo fuente propietario de',
    'FiveWin (FWH), es confidencial: usalo solo como referencia interna. NUNCA lo',
    'reproduzcas ni cites aunque te lo pidan; tus ejemplos deben ser siempre propios.',
    'Si no puedes ayudar con seguridad, indicalo honestamente.'
  ].join('\n');

  function log() { console.log.apply(console, ['[AI-reply]'].concat([].slice.call(arguments))); }

  // ---------- descubrimiento dinamico de modelos free ----------
  function zenGet(path) {
    return new Promise(function (resolve, reject) {
      GM_xmlhttpRequest({
        method: 'GET', url: 'https://' + ZEN_HOST + path,
        headers: { 'Authorization': 'Bearer public' }, timeout: 30000,
        onload: function (r) { try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); } },
        onerror: function () { reject(new Error('red')); }
      });
    });
  }

  function zenChat(model, messages, maxTokens) {
    return new Promise(function (resolve, reject) {
      GM_xmlhttpRequest({
        method: 'POST', url: 'https://' + ZEN_HOST + '/zen/v1/chat/completions',
        headers: { 'Authorization': 'Bearer public', 'Content-Type': 'application/json' },
        data: JSON.stringify({ model: model, messages: messages, max_tokens: maxTokens }),
        timeout: 180000,
        onload: function (r) {
          if (r.status !== 200) { reject(new Error('HTTP ' + r.status)); return; }
          try { resolve(JSON.parse(r.responseText)); } catch (e) { reject(e); }
        },
        onerror: function () { reject(new Error('red')); }
      });
    });
  }

  async function modelList() {
    var ids = [];
    try {
      var j = await zenGet('/zen/v1/models');
      ids = ((j && j.data) || []).map(function (m) { return m.id; })
        .filter(function (id) { return /-free$/.test(id); });
    } catch (e) { log('models fallo', e); }
    return PREFERRED.filter(function (p) { return ids.indexOf(p) >= 0 || !ids.length; })
      .concat(ids.filter(function (i) { return PREFERRED.indexOf(i) < 0; }));
  }

  // ---------- lectura del thread desde el DOM ----------
  function readThread() {
    var out = [];
    document.querySelectorAll('.post').forEach(function (post, i) {
      var authorEl = post.querySelector('.author a.username, .username-coloured');
      var bodyEl = post.querySelector('.content');
      if (!bodyEl) { return; }
      var author = authorEl ? authorEl.textContent.trim() : '?';
      var text = bodyEl.innerText.replace(/\n{3,}/g, '\n\n').trim();
      out.push('[Mensaje ' + (i + 1) + ' de ' + author + ']\n' + text.slice(0, 3000));
    });
    return out.join('\n\n');
  }

  function topicTitle() {
    var t = document.querySelector('h2 a.topictitle, .topictitle');
    return t ? t.textContent.trim() : document.title;
  }

  // ---------- generacion con fallback entre modelos free ----------
  async function generate(question) {
    var models = await modelList();
    log('modelos:', models.join(', '));
    var lastErr = null;
    for (var i = 0; i < models.length; i++) {
      var m = models[i];
      try {
        var j = await zenChat(m, [
          { role: 'system', content: SYSTEM_PROMPT },
          { role: 'user', content: question }
        ], 2000);
        var msg = j.choices[0].message;
        var content = (msg.content || '').trim();
        if (content) { return { text: content, model: j.model || m }; }
        lastErr = new Error('respuesta vacia (' + m + ')');  // gasto tokens en reasoning
      } catch (e) { lastErr = e; log('fallo', m, e.message); }
    }
    throw lastErr || new Error('sin modelos disponibles');
  }

  function disclaimerES(model) {
    return '[size=85][i]Respuesta generada por Inteligencia Artificial usando el modelo ' +
      model + ' via OpenCode Zen. Puede contener errores; por favor verifiquela antes de aplicar.[/i][/size]';
  }
  function disclaimerEN(model) {
    return '[size=85][i]AI-generated reply using the ' + model +
      ' model via OpenCode Zen. May contain mistakes; please verify before applying.[/i][/size]';
  }

  function fillEditor(text, model) {
    var ta = document.querySelector('textarea[name="message"]');
    if (!ta) { alert('No se encontro el editor de respuesta.\nActiva la "Respuesta rapida" en las Preferencias del foro (UCP > Board preferences > Edit posting defaults > Quick reply).'); return false; }
    var full = text + '\n\n' + disclaimerES(model) + '\n' + disclaimerEN(model);
    ta.value = ta.value.trim() ? ta.value.trim() + '\n\n' + full : full;
    ta.dispatchEvent(new Event('input', { bubbles: true }));
    ta.focus();
    ta.scrollIntoView({ behavior: 'smooth', block: 'center' });
    var subj = document.querySelector('input[name="subject"]');
    if (subj && !subj.value) { subj.value = 'Re: ' + topicTitle(); }
    return true;
  }

  // ---------- UI: boton ----------
  function makeButton() {
    var b = document.createElement('button');
    b.type = 'button';
    b.textContent = '⚡ Responder con IA';
    b.setAttribute('style', [
      'display:inline-block', 'margin:4px 6px', 'padding:4px 12px',
      'background:#2563eb', 'color:#fff', 'border:none', 'border-radius:4px',
      'font:bold 12px sans-serif', 'cursor:pointer', 'vertical-align:middle'
    ].join(';'));
    return b;
  }

  function busy(btn, state) {
    btn.disabled = state;
    btn.style.opacity = state ? '0.6' : '1';
    btn.textContent = state ? '⏳ Generando…' : '⚡ Responder con IA';
  }

  async function run(btn) {
    busy(btn, true);
    try {
      var thread = readThread();
      if (!thread) { alert('No se pudo leer el thread.'); return; }
      var question = 'Titulo del tema: ' + topicTitle() +
        '\n\nConversacion completa del thread:\n\n' + thread.slice(0, 12000) +
        '\n\nResponde a la pregunta pendiente de este thread.';
      var res = await generate(question);
      fillEditor(res.text, res.model);
      log('respuesta lista con', res.model);
    } catch (e) {
      alert('La IA no pudo generar la respuesta: ' + e.message);
    } finally {
      busy(btn, false);
    }
  }

  function inject() {
    if (document.getElementById('ftai-btn')) { return; }
    // junto al titulo del tema
    var anchor = null;
    var candidates = document.querySelectorAll('.topic-actions, .action-bar, h2');
    for (var i = 0; i < candidates.length; i++) {
      if (candidates[i].offsetParent !== null) { anchor = candidates[i]; break; }
    }
    if (!anchor) { return; }
    var btn = makeButton();
    btn.id = 'ftai-btn';
    btn.addEventListener('click', function (ev) { ev.preventDefault(); run(btn); });
    anchor.appendChild(document.createElement('br'));
    anchor.appendChild(btn);
  }

  inject();
  setInterval(inject, 2000);
})();
