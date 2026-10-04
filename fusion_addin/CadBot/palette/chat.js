'use strict';
const $ = id => document.getElementById(id);
let images = [], busy = false, connected = false, signedIn = false, polling = false;
let modelCatalog = [], restoringCheckpoint = false, checkpointState = {available: [], reason: 'Checking checkpoint availability…'};
const restoreButtons = [];
const restoreReasons = [];
const messages = new Map(), tools = new Map();
function status(text) { $('status').textContent = text; }
function controls() {
  restoreReasons.forEach(({element, messageId}) => {
    const available = checkpointState.available.includes(messageId);
    element.hidden = available && !busy;
    element.textContent = busy ? 'Finish or stop the current response before restoring.' : available ? '' :
      'Design undo unavailable: ' + (checkpointState.reason || 'This message has no active checkpoint in this Fusion session.');
  });
  restoreButtons.forEach(button => { button.disabled = busy || !connected || (button.restoreMode !== 'conversation' && !checkpointState.available.includes(button.messageId)); button.title = button.disabled && !busy ? checkpointState.reason || 'This checkpoint is no longer available.' : ''; });
  $('send').disabled = restoringCheckpoint || !connected || (!signedIn && !busy);
  $('send').textContent = busy ? '■' : '↑';
  $('send').className = busy ? 'is-stopping' : '';
  $('send').setAttribute('aria-label', busy ? 'Stop response' : 'Send message');
  $('send').title = busy ? 'Stop response' : 'Send message';
  $('new').disabled = busy;
  $('reconnect').disabled = restoringCheckpoint;
  $('history').disabled = busy || !connected;
  $('login').hidden = signedIn;
  $('attach').disabled = busy;
  $('model').disabled = busy || !connected || !signedIn;
  $('effort').disabled = busy || !connected || !signedIn;
}
function resizeComposer() {
  const input = $('input');
  const lineHeight = parseFloat(window.getComputedStyle(input).lineHeight);
  input.style.height = 'auto';
  input.style.overflowY = 'hidden';
  const height = Math.min(input.scrollHeight, lineHeight * 5);
  input.style.height = Math.max(lineHeight, height) + 'px';
  input.style.overflowY = input.scrollHeight > height + 1 ? 'auto' : 'hidden';
}
function scroll() { $('conversation').scrollTop = $('conversation').scrollHeight; }
function hideWelcome() { if ($('welcome')) $('welcome').hidden = true; }
function message(role, text, id) {
  hideWelcome();
  if (id && messages.has(id)) { messages.get(id).textContent = text; return messages.get(id); }
  const section = document.createElement('section'); section.className = 'message ' + role;
  const label = document.createElement('div'); label.className = 'label'; label.textContent = role === 'user' ? 'You' : role === 'error' ? 'Connection / agent error' : 'CadBot';
  const body = document.createElement('div'); body.className = 'body'; body.textContent = text;
  section.append(label, body); $('conversation').append(section);
  if (id) messages.set(id, body); scroll(); return body;
}
async function rpc(action, data = {}) {
  if (!window.adsk || !window.adsk.fusionSendData) throw new Error('Open this chat from the CadBot add-in inside Fusion.');
  const raw = await window.adsk.fusionSendData(action, JSON.stringify(data));
  const result = typeof raw === 'string' ? JSON.parse(raw || '{}') : raw;
  if (result && result.error) throw new Error(result.error);
  return result || {};
}
function event(e) {
  if (e.kind === 'history') {
    $('history').replaceChildren();
    const blank = document.createElement('option'); blank.value = ''; blank.textContent = 'New conversation'; $('history').append(blank);
    (e.conversations || []).forEach(c => { const option = document.createElement('option'); option.value = c.id; option.textContent = c.title + ' · ' + c.updated.slice(0,10); $('history').append(option); });
    $('history').value = e.selected || '';
  }
  if (e.kind === 'restore_begin') {
    restoreButtons.length = 0; restoreReasons.length = 0;
    messages.clear(); tools.clear(); $('conversation').replaceChildren(); images = []; renderAttachments();
    $('input').value = ''; resizeComposer();
    if (modelCatalog.some(m => m.id === e.model)) { $('model').value = e.model; renderEfforts(); if (modelCatalog.find(m => m.id === e.model).efforts.includes(e.effort)) $('effort').value = e.effort; }
  }
  if (e.kind === 'replay') { event(e.event); }
  if (e.kind === 'user') {
    const body = message('user', e.text || 'Attached references', e.id);
    if (e.id && !body.checkpointAdded) {
      body.checkpointAdded = true;
      const menu = document.createElement('details'); menu.className = 'checkpoint-menu';
      const label = document.createElement('summary'); label.textContent = 'Restore before this message'; menu.append(label);
      [['design', 'Undo design to here'], ['conversation', 'Branch chat from here'], ['both', 'Undo design + branch chat']].forEach(([mode, text]) => {
        const button = document.createElement('button'); button.textContent = text; button.restoreMode = mode; button.messageId = e.id; restoreButtons.push(button);
        button.onclick = async () => {
          if (busy) return;
          busy = true; restoringCheckpoint = true; controls(); status('Restoring…');
          try { await rpc('restore', {id: e.id, mode}); }
          catch (err) { busy = false; restoringCheckpoint = false; controls(); message('error', err.message); }
        };
        menu.append(button);
      });
      const reason = document.createElement('div'); reason.className = 'checkpoint-reason'; menu.append(reason);
      restoreReasons.push({element: reason, messageId: e.id});
      body.parentElement.append(menu); controls();
    }
    (e.attachments || []).forEach(file => { const el = attachmentPreview(file); el.className += ' reference'; body.parentElement.append(el); });
  }
  if (e.kind === 'restore_end') { busy = false; controls(); $('restore-status').textContent = ''; status('Chat restored · Uses the active Fusion design'); }

  if (e.kind === 'models') {
    modelCatalog = e.models || [];
    let saved = $('model').value;
    try { saved = localStorage.getItem('cadbot.model') || saved; } catch (_) {}
    $('model').replaceChildren();
    (e.models || []).forEach(m => {
      const option = document.createElement('option');
      option.value = m.id; option.textContent = m.name + (m.default ? ' (default)' : '');
      option.title = m.description; $('model').append(option);
    });
    const selected = (e.models || []).find(m => m.id === saved) || (e.models || []).find(m => m.default) || (e.models || [])[0];
    $('model').value = selected ? selected.id : '';
    renderEfforts(); controls();
  }
  if (e.kind === 'ready') { connected = true; signedIn = e.signed_in; status(signedIn ? 'Ready · Active Fusion design' : 'Sign in to ChatGPT to start'); controls(); }
  if (e.kind === 'status') status(e.text);
  if (e.kind === 'delta') {
    let body = messages.get(e.id); if (!body) body = message('assistant', '', e.id);
    body.textContent += e.text; scroll();
  }
  if (e.kind === 'message' && e.text) { message('assistant', e.text, e.id); scroll(); }
  if (e.kind === 'tool') {
    hideWelcome(); let card = tools.get(e.id);
    if (!card) {
      card = document.createElement('details'); card.append(document.createElement('summary'), document.createElement('pre'));
      tools.set(e.id, card); $('conversation').append(card);
    }
    const item = e.item;
    let name = item.tool || item.name || item.command || item.type;
    if (item.tool === 'fusion') {
      let args = item.arguments;
      try { if (typeof args === 'string') args = JSON.parse(args); } catch (_) {}
      if (args && args.command) card.commandLabel = args.command.trim().split(/\s+--/)[0];
      name = card.commandLabel || 'fusion';
    }
    card.firstChild.textContent = (item.status === 'failed' || item.error ? '✕ ' : e.phase === 'completed' ? '✓ ' : '◌ ') + name + ' · ' + (item.status || e.phase);
    const details = {arguments: item.arguments, result: item.result, error: item.error, output: item.aggregatedOutput};
    card.lastChild.textContent = JSON.stringify(details, null, 2); scroll();
  }
  if (e.kind === 'error') { if ($('restore-status').textContent) { busy = false; controls(); $('restore-status').textContent = ''; } message('error', e.text); status('Needs attention'); }
  if (e.kind === 'complete') { if (e.error) message('error', e.error); status(e.status === 'interrupted' ? 'Stopped' : e.status === 'failed' ? 'Request failed' : 'Ready · Active Fusion design'); }
  if (e.kind === 'draft') { $('input').value = e.text; images = e.attachments || []; renderAttachments(); resizeComposer(); }
  if (e.kind === 'checkpoints') { checkpointState = e; controls(); if (e.reason) status('Design undo unavailable: ' + e.reason); }
  if (e.kind === 'idle') { restoringCheckpoint = false; busy = false; controls(); }
  if (e.kind === 'disconnected') { connected = false; busy = false; status('Disconnected'); controls(); }
  if (e.kind === 'reset') { restoreButtons.length = 0; restoreReasons.length = 0; images = []; renderAttachments(); $('input').value = ''; resizeComposer(); messages.clear(); tools.clear(); $('conversation').replaceChildren(); message('assistant', 'New chat started. Your Fusion design is unchanged.'); }
}
async function poll() {
  if (polling) return; polling = true;
  try { const result = await rpc('poll'); (result.events || []).forEach(event); if (result.checkpoints) { checkpointState = result.checkpoints; controls(); } }
  catch (err) { status(err.message); }
  finally { polling = false; setTimeout(poll, 250); }
}
async function connect(action = 'ready') {
  status('Connecting to Codex…'); connected = false; signedIn = false; controls();
  try { await rpc(action); } catch (err) { message('error', err.message); status('Connection failed'); }
}
function attachmentPreview(file) {
  const el = document.createElement(file.image ? 'img' : 'span');
  if (file.image) { el.src = file.url; el.alt = file.name; }
  else { el.textContent = '▤ ' + file.name; el.className = 'file-name'; }
  return el;
}
function renderAttachments() {
  $('attachments').replaceChildren();
  images.forEach((file, i) => {
    const chip = document.createElement('div'); chip.className = 'attachment';
    chip.title = file.name;
    const remove = document.createElement('button'); remove.textContent = '×'; remove.title = 'Remove ' + file.name;
    remove.onclick = () => { if (busy) return; images.splice(i, 1); renderAttachments(); };
    chip.append(attachmentPreview(file), remove); $('attachments').append(chip);
  });
}
async function addImages(files) {
  if (busy) return;
  for (const file of files) {
    if (images.length >= 4) { message('error', 'Attach up to 4 files per message.'); break; }
    if (file.size > 5*1024*1024) { message('error', file.name + ': maximum file size is 5 MB.'); continue; }
    try {
      const url = await new Promise((resolve, reject) => { const r = new FileReader(); r.onload = () => resolve(r.result); r.onerror = reject; r.readAsDataURL(file); });
      if (busy) return;
      images.push({name:file.name || 'Pasted image', url, image: ['image/png','image/jpeg','image/webp','image/gif'].includes(file.type)}); renderAttachments();
    } catch (_) { message('error', 'Could not read ' + file.name); }
  }
}
function renderEfforts() {
  const model = modelCatalog.find(m => m.id === $('model').value);
  const previous = $('effort').value;
  $('effort').replaceChildren();
  const efforts = model ? model.efforts || [] : [];
  efforts.forEach(value => { const el = document.createElement('option'); el.value = value; el.textContent = value.charAt(0).toUpperCase() + value.slice(1); $('effort').append(el); });
  $('effort').value = efforts.includes(previous) ? previous : (model && model.default_effort || '');
}
async function send() {
  if (busy || !connected || !signedIn) return;
  const text = $('input').value.trim(), attached = images.slice(); if (!text && !attached.length) return;
  busy = true; controls(); status('Working…');
  try {
    await rpc('send', {text, images: attached.filter(f => f.image), files: attached.filter(f => !f.image), model: $('model').value, effort: $('effort').value});
    $('input').value = ''; resizeComposer(); images = []; renderAttachments(); scroll();
  } catch (err) { busy = false; controls(); message('error', err.message); }
}
$('model').onchange = () => { renderEfforts(); try { localStorage.setItem('cadbot.model', $('model').value); } catch (_) {} };
$('history').onchange = async () => {
  if (!$('history').value) { await rpc('new'); return; }
  busy = true; controls(); $('restore-status').textContent = 'Opening…';
  try { await rpc('open', {id: $('history').value}); }
  catch (err) { busy = false; controls(); $('restore-status').textContent = ''; message('error', err.message); }
};
$('send').onclick = async () => {
  if (!busy) return send();
  try { status('Stopping…'); await rpc('cancel'); }
  catch (err) { message('error', err.message); }
};
$('input').oninput = resizeComposer;
window.addEventListener('resize', resizeComposer);
$('input').onkeydown = e => { if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); send(); } };
$('attach').onclick = () => $('files').click();
$('files').onchange = async e => { await addImages(e.target.files); e.target.value = ''; };
$('new').onclick = async () => { try { await rpc('new'); } catch (err) { message('error', err.message); } };
$('reconnect').onclick = () => { if (restoringCheckpoint) return; busy = false; connect('reconnect'); };
$('login').onclick = async () => { try { await rpc('login'); status('Opening ChatGPT sign-in…'); } catch (err) { message('error', err.message); } };
document.querySelectorAll('.suggestion').forEach(el => el.onclick = () => { $('input').value = el.textContent; resizeComposer(); $('input').focus(); });
document.addEventListener('paste', e => { const files = Array.from(e.clipboardData.items).filter(i => i.kind === 'file').map(i => i.getAsFile()); if (files.length) { e.preventDefault(); addImages(files); } });
document.addEventListener('dragover', e => { e.preventDefault(); document.body.classList.add('dragging'); });
document.addEventListener('dragleave', () => document.body.classList.remove('dragging'));
document.addEventListener('drop', e => { e.preventDefault(); document.body.classList.remove('dragging'); addImages(e.dataTransfer.files); });
// Fusion injects adsk after the document loads; wait briefly for that binding.
let attempts = 0;
(function boot() { if (window.adsk || attempts++ > 40) { connect(); poll(); } else setTimeout(boot, 100); })();
