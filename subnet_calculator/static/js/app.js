// ═══════════════════════════════════════
//  SubnetLab — Frontend Logic
// ═══════════════════════════════════════

const TAB_META = {
  basic:    { title: 'Basic Subnet Calculator',   hint: 'Enter a CIDR like 192.168.1.0/24' },
  split:    { title: 'Subnet Splitter',           hint: 'Split a network into equal subnets' },
  vlsm:     { title: 'VLSM Allocator',            hint: 'Allocate variable-length subnets from a pool' },
  batch:    { title: 'Batch Calculator',          hint: 'Calculate multiple CIDRs at once' },
  overlap:  { title: 'Overlap Detector',          hint: 'Check for conflicting subnet ranges' },
  supernet: { title: 'Supernetting / Aggregation',hint: 'Collapse multiple networks into summary routes' },
  lookup:   { title: 'IP Subnet Lookup',          hint: 'Check if an IP belongs to a subnet' },
};

// ─── Tab Switching ───────────────────────────────────────
document.querySelectorAll('.nav-item').forEach(btn => {
  btn.addEventListener('click', () => {
    const tab = btn.dataset.tab;
    document.querySelectorAll('.nav-item').forEach(b => b.classList.remove('active'));
    document.querySelectorAll('.tab-panel').forEach(p => p.classList.remove('active'));
    btn.classList.add('active');
    document.getElementById('tab-' + tab).classList.add('active');
    document.getElementById('tab-title').textContent = TAB_META[tab].title;
    document.getElementById('tab-hint').textContent  = TAB_META[tab].hint;
  });
});

// ─── API Helper ──────────────────────────────────────────
async function api(endpoint, body) {
  const res = await fetch('/api/' + endpoint, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  return res.json();
}

function showError(msg) {
  const t = document.getElementById('error-toast');
  t.textContent = '⚠ ' + msg;
  t.classList.remove('hidden');
  setTimeout(() => t.classList.add('hidden'), 4000);
}

// ─── Basic Subnet ────────────────────────────────────────
async function calcBasic() {
  const cidr = document.getElementById('basic-cidr').value.trim();
  if (!cidr) return showError('Please enter a CIDR.');
  const d = await api('subnet', { cidr });
  if (!d.success) return showError(d.error);

  const grid = document.getElementById('basic-grid');
  grid.innerHTML = '';

  const cards = [
    { label: 'Network Address',  value: d.network_address, cls: 'green' },
    { label: 'Broadcast Address',value: d.broadcast,        cls: '' },
    { label: 'Subnet Mask',      value: d.subnet_mask,      cls: '' },
    { label: 'Wildcard Mask',    value: d.wildcard_mask,    cls: '' },
    { label: 'First Usable Host',value: d.first_host,       cls: 'blue' },
    { label: 'Last Usable Host', value: d.last_host,        cls: 'blue' },
    { label: 'Usable Hosts',     value: d.usable_hosts.toLocaleString(), cls: 'green' },
    { label: 'Total Addresses',  value: d.total_hosts.toLocaleString(),  cls: '' },
    { label: 'CIDR Notation',    value: `/${d.prefix}`,     cls: 'green' },
    {
      label: 'IP Class',
      value: d.ip_class + (d.is_private
        ? ' <span class="badge badge-priv">PRIVATE</span>'
        : ' <span class="badge badge-pub">PUBLIC</span>'),
      cls: '',
      html: true
    },
  ];

  cards.forEach((c, i) => {
    const card = document.createElement('div');
    card.className = 'result-card' + (i === 0 ? ' accent' : '');
    card.innerHTML = `
      <div class="card-label">${c.label}</div>
      <div class="card-value ${c.cls}">${c.html ? c.value : escHtml(c.value)}</div>
    `;
    grid.appendChild(card);
  });

  document.getElementById('bin-ip').textContent   = d.binary_ip;
  document.getElementById('bin-mask').textContent = d.binary_mask;
  document.getElementById('bin-net').textContent  = d.binary_network;

  renderSteps(d);
  document.getElementById('basic-result').classList.remove('hidden');
}

function renderSteps(d) {
  const steps = [
    { text: `Input IP: <b>${d.input_ip}</b> with prefix length <b>/${d.prefix}</b>` },
    { text: `Subnet Mask in binary: <b>${d.binary_mask}</b>` },
    { text: `Network Address = IP AND Mask → <b>${d.network_address}</b>` },
    { text: `Broadcast = Network OR (NOT Mask) = <b>${d.broadcast}</b>` },
    { text: `First usable host = Network + 1 → <b>${d.first_host}</b>` },
    { text: `Last usable host = Broadcast − 1 → <b>${d.last_host}</b>` },
    { text: `Total addresses = 2^(32−${d.prefix}) = <b>${d.total_hosts.toLocaleString()}</b>, Usable = <b>${d.usable_hosts.toLocaleString()}</b>` },
  ];
  const container = document.getElementById('steps-content');
  container.innerHTML = steps.map((s, i) => `
    <div class="step">
      <div class="step-num">${i + 1}</div>
      <div class="step-text">${s.text}</div>
    </div>
  `).join('');
}

// ─── Split Subnet ────────────────────────────────────────
async function calcSplit() {
  const cidr = document.getElementById('split-cidr').value.trim();
  const n = parseInt(document.getElementById('split-n').value);
  if (!cidr || !n) return showError('Fill in all fields.');
  const d = await api('split', { cidr, n });
  if (!d.success) return showError(d.error);

  // Tree
  const tree = document.getElementById('split-tree');
  tree.innerHTML = `
    <div class="tree-label">Subnet Hierarchy</div>
    <div class="tree-row">
      <span class="tree-node parent">${escHtml(d.parent)} (parent)</span>
    </div>
    <div style="color:var(--text-muted); font-size:11px; padding: 4px 0 6px 14px; font-family:var(--mono);">
      ${d.subnets.map(() => '│').join('  ')}
    </div>
    <div class="tree-row">
      ${d.subnets.map(s => `<span class="tree-node">${escHtml(s.cidr)}</span>`).join('<span class="tree-connector">·</span>')}
    </div>
  `;

  const tbody = document.getElementById('split-tbody');
  tbody.innerHTML = d.subnets.map((s, i) => `
    <tr>
      <td>${i + 1}</td>
      <td class="cidr-cell">${escHtml(s.cidr)}</td>
      <td>${escHtml(s.network)}</td>
      <td>${escHtml(s.broadcast)}</td>
      <td>${escHtml(s.first_host)}</td>
      <td>${escHtml(s.last_host)}</td>
      <td class="num-cell">${s.usable_hosts.toLocaleString()}</td>
    </tr>
  `).join('');

  document.getElementById('split-result').classList.remove('hidden');
}

// ─── VLSM ────────────────────────────────────────────────
function addVlsmRow() {
  const container = document.getElementById('vlsm-rows');
  const row = document.createElement('div');
  row.className = 'vlsm-row';
  row.innerHTML = `
    <input type="text" placeholder="Subnet name" class="vlsm-name"/>
    <input type="number" placeholder="Hosts needed" class="vlsm-hosts" min="1"/>
    <button class="btn-remove" onclick="removeVlsmRow(this)">✕</button>
  `;
  container.appendChild(row);
}

function removeVlsmRow(btn) {
  const rows = document.querySelectorAll('.vlsm-row');
  if (rows.length <= 1) return;
  btn.closest('.vlsm-row').remove();
}

async function calcVLSM() {
  const pool = document.getElementById('vlsm-pool').value.trim();
  if (!pool) return showError('Enter a pool CIDR.');

  const rows = document.querySelectorAll('.vlsm-row');
  const requirements = [];
  for (const row of rows) {
    const name  = row.querySelector('.vlsm-name').value.trim();
    const hosts = parseInt(row.querySelector('.vlsm-hosts').value);
    if (name && hosts > 0) requirements.push({ name, hosts });
  }
  if (!requirements.length) return showError('Add at least one requirement.');

  const d = await api('vlsm', { network: pool, requirements });
  if (!d.success) return showError(d.error);

  const tbody = document.getElementById('vlsm-tbody');
  tbody.innerHTML = d.allocations.map(a => `
    <tr>
      <td><b>${escHtml(a.name)}</b></td>
      <td class="num-cell">${a.required_hosts}</td>
      <td class="cidr-cell">${escHtml(a.cidr)}</td>
      <td>${escHtml(a.network)}</td>
      <td>${escHtml(a.broadcast)}</td>
      <td>${escHtml(a.first_host)}</td>
      <td>${escHtml(a.last_host)}</td>
      <td class="num-cell">${a.usable_hosts.toLocaleString()}</td>
    </tr>
  `).join('');

  // Tree
  const tree = document.getElementById('vlsm-tree');
  tree.innerHTML = `
    <div class="tree-label">VLSM Allocation Map — Pool: ${escHtml(pool)}</div>
    <div class="tree-row">
      <span class="tree-node parent">${escHtml(pool)}</span>
    </div>
    <div class="tree-row" style="margin-top:8px;">
      ${d.allocations.map(a => `
        <span class="tree-node" title="${escHtml(a.name)}">
          ${escHtml(a.cidr)}<br>
          <span style="font-size:10px;color:var(--text-muted)">${escHtml(a.name)} (/${a.prefix})</span>
        </span>
      `).join('<span class="tree-connector" style="align-self:center">→</span>')}
    </div>
  `;

  document.getElementById('vlsm-result').classList.remove('hidden');
}

// ─── Batch ───────────────────────────────────────────────
let batchData = [];

async function calcBatch() {
  const raw = document.getElementById('batch-input').value;
  const cidrs = raw.split('\n').map(s => s.trim()).filter(Boolean);
  if (!cidrs.length) return showError('Enter at least one CIDR.');

  const d = await api('batch', { cidrs });
  if (!d.success) return showError(d.error);

  batchData = d.results;
  const tbody = document.getElementById('batch-tbody');
  tbody.innerHTML = d.results.map(r => {
    if (!r.success) return `<tr><td colspan="9" style="color:var(--danger)">${escHtml(r.error)}</td></tr>`;
    return `
      <tr>
        <td class="cidr-cell">${escHtml(r.cidr)}</td>
        <td>${escHtml(r.network_address)}</td>
        <td>${escHtml(r.broadcast)}</td>
        <td>${escHtml(r.subnet_mask)}</td>
        <td>${escHtml(r.first_host)}</td>
        <td>${escHtml(r.last_host)}</td>
        <td class="num-cell">${r.usable_hosts.toLocaleString()}</td>
        <td>${escHtml(r.ip_class)}</td>
        <td>${r.is_private
          ? '<span class="badge badge-priv">YES</span>'
          : '<span class="badge badge-pub">NO</span>'}</td>
      </tr>
    `;
  }).join('');

  document.getElementById('batch-result').classList.remove('hidden');
}

function exportBatchCSV() {
  if (!batchData.length) return showError('Run Batch Calculate first.');
  const headers = ['CIDR','Network','Broadcast','Mask','First Host','Last Host','Usable Hosts','Class','Private'];
  const rows = batchData.filter(r => r.success).map(r =>
    [r.cidr, r.network_address, r.broadcast, r.subnet_mask, r.first_host, r.last_host, r.usable_hosts, r.ip_class, r.is_private].join(',')
  );
  const csv = [headers.join(','), ...rows].join('\n');
  download('subnet_batch.csv', 'text/csv', csv);
}

// ─── Overlap ─────────────────────────────────────────────
async function calcOverlap() {
  const raw = document.getElementById('overlap-input').value;
  const cidrs = raw.split('\n').map(s => s.trim()).filter(Boolean);
  if (cidrs.length < 2) return showError('Enter at least 2 CIDRs.');

  const d = await api('overlap', { cidrs });
  if (!d.success) return showError(d.error);

  const statusEl = document.getElementById('overlap-status');
  const listEl   = document.getElementById('overlap-list');

  if (d.count === 0) {
    statusEl.innerHTML = `<div class="status-ok">✓ No overlaps detected — all ${cidrs.length} networks are non-overlapping.</div>`;
    listEl.innerHTML = '';
  } else {
    statusEl.innerHTML = `<div class="status-bad">⚠ ${d.count} overlap${d.count > 1 ? 's' : ''} detected!</div>`;
    listEl.innerHTML = d.overlaps.map(o => `
      <div class="overlap-item">
        <span class="cidr-a">${escHtml(o.a)}</span>
        <span style="color:var(--text-muted)">overlaps with</span>
        <span class="cidr-b">${escHtml(o.b)}</span>
      </div>
    `).join('');
  }
  document.getElementById('overlap-result').classList.remove('hidden');
}

// ─── Supernet ─────────────────────────────────────────────
async function calcSupernet() {
  const raw = document.getElementById('supernet-input').value;
  const cidrs = raw.split('\n').map(s => s.trim()).filter(Boolean);
  if (cidrs.length < 2) return showError('Enter at least 2 networks.');

  const d = await api('supernet', { cidrs });
  if (!d.success) return showError(d.error);

  const tbody = document.getElementById('supernet-tbody');
  tbody.innerHTML = d.supernets.map(s => `
    <tr>
      <td class="cidr-cell">${escHtml(s.cidr)}</td>
      <td>${escHtml(s.network)}</td>
      <td>${escHtml(s.mask)}</td>
      <td class="num-cell">${s.total_hosts.toLocaleString()}</td>
    </tr>
  `).join('');

  document.getElementById('supernet-result').classList.remove('hidden');
}

// ─── Lookup ──────────────────────────────────────────────
async function calcLookup() {
  const ip   = document.getElementById('lookup-ip').value.trim();
  const cidr = document.getElementById('lookup-cidr').value.trim();
  if (!ip || !cidr) return showError('Fill in both fields.');

  const d = await api('ip-in-subnet', { ip, cidr });
  if (!d.success) return showError(d.error);

  const el = document.getElementById('lookup-status');
  if (d.result) {
    el.innerHTML = `<div class="status-ok">✓ <b>${escHtml(ip)}</b> IS in subnet <b>${escHtml(cidr)}</b></div>`;
  } else {
    el.innerHTML = `<div class="status-bad">✗ <b>${escHtml(ip)}</b> is NOT in subnet <b>${escHtml(cidr)}</b></div>`;
  }
  document.getElementById('lookup-result').classList.remove('hidden');
}

// ─── Enter key shortcuts ─────────────────────────────────
document.getElementById('basic-cidr').addEventListener('keydown', e => { if (e.key === 'Enter') calcBasic(); });
document.getElementById('lookup-ip').addEventListener('keydown',  e => { if (e.key === 'Enter') calcLookup(); });
document.getElementById('lookup-cidr').addEventListener('keydown',e => { if (e.key === 'Enter') calcLookup(); });

// ─── Utilities ───────────────────────────────────────────
function escHtml(s) {
  return String(s)
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;');
}

function download(filename, type, content) {
  const blob = new Blob([content], { type });
  const a = document.createElement('a');
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
}
