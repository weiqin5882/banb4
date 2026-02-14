const form = document.getElementById('reconcile-form');
const tbody = document.querySelector('#result-table tbody');
const summary = document.getElementById('summary');
const message = document.getElementById('message');
const pageInfo = document.getElementById('page-info');

let allRows = [];
let currentPage = 1;
const pageSize = 20;
let sortKey = '序号';
let sortAsc = true;

function formatMoney(n) {
  return Number(n).toLocaleString('zh-CN', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

function renderSummary(data) {
  summary.innerHTML = `
    <p>总销售额：${formatMoney(data['总销售额'])}</p>
    <p>总成本：${formatMoney(data['总成本'])}</p>
    <p>总利润：${formatMoney(data['总利润'])}</p>
    <p>订单总数：${data['订单总数']}</p>
  `;
}

function sortedRows() {
  const rows = [...allRows];
  rows.sort((a, b) => {
    const x = a[sortKey], y = b[sortKey];
    if (typeof x === 'number' && typeof y === 'number') return sortAsc ? x - y : y - x;
    return sortAsc ? String(x).localeCompare(String(y), 'zh-CN') : String(y).localeCompare(String(x), 'zh-CN');
  });
  return rows;
}

function renderTable() {
  const rows = sortedRows();
  const totalPages = Math.max(1, Math.ceil(rows.length / pageSize));
  currentPage = Math.min(currentPage, totalPages);
  const start = (currentPage - 1) * pageSize;
  const pageRows = rows.slice(start, start + pageSize);

  tbody.innerHTML = '';
  pageRows.forEach(row => {
    const tr = document.createElement('tr');
    if (String(row['状态标记']).includes('亏损订单')) tr.classList.add('loss');
    tr.innerHTML = `
      <td>${row['序号']}</td>
      <td>${row['订单号']}</td>
      <td>${row['商品名称']}</td>
      <td>${formatMoney(row['销售金额'])}</td>
      <td>${formatMoney(row['成本'])}</td>
      <td>${formatMoney(row['单笔利润'])}</td>
      <td>${row['状态标记']}</td>
    `;
    tbody.appendChild(tr);
  });
  pageInfo.textContent = `第 ${currentPage} / ${totalPages} 页`;
}

form.addEventListener('submit', async (e) => {
  e.preventDefault();
  message.textContent = '';
  const fd = new FormData(form);

  const resp = await fetch('/api/reconcile', { method: 'POST', body: fd });
  const data = await resp.json();
  if (!resp.ok) {
    message.textContent = data.error || '请求失败';
    return;
  }

  allRows = data.rows;
  currentPage = 1;
  renderSummary(data.summary);
  renderTable();
});

document.querySelectorAll('#result-table th').forEach(th => {
  th.addEventListener('click', () => {
    const key = th.dataset.key;
    if (sortKey === key) {
      sortAsc = !sortAsc;
    } else {
      sortKey = key;
      sortAsc = true;
    }
    renderTable();
  });
});

document.getElementById('prev').addEventListener('click', () => {
  if (currentPage > 1) {
    currentPage--;
    renderTable();
  }
});

document.getElementById('next').addEventListener('click', () => {
  const totalPages = Math.max(1, Math.ceil(allRows.length / pageSize));
  if (currentPage < totalPages) {
    currentPage++;
    renderTable();
  }
});
