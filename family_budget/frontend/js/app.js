// Family Budget Tracker - Frontend Application

let chartInstance = null;
let comparisonChartInstance = null;
let categoryTrendChartInstance = null;
let dayOfWeekChartInstance = null;
let categories = [];
let currentExpenses = [];
let selectedMonth = null; // Single global month for all tabs

// ============ API Helpers ============

async function apiGet(endpoint) {
  const res = await fetch(endpoint);
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function apiPost(endpoint, data) {
  const res = await fetch(endpoint, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function apiPut(endpoint, data) {
  const res = await fetch(endpoint, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function apiPatch(endpoint, data) {
  const res = await fetch(endpoint, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(data)
  });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

async function apiDelete(endpoint) {
  const res = await fetch(endpoint, { method: "DELETE" });
  if (!res.ok) throw new Error(`API error: ${res.status}`);
  return res.json();
}

// ============ Tab Navigation ============

function switchTab(tabName) {
  // Hide all tab contents
  document.querySelectorAll('.tab-content').forEach(tab => {
    tab.classList.remove('active');
  });
  // Remove active from all buttons
  document.querySelectorAll('.tab-btn').forEach(btn => {
    btn.classList.remove('active');
  });
  // Show selected tab
  document.getElementById(`tab-${tabName}`).classList.add('active');
  document.querySelector(`.tab-btn[data-tab="${tabName}"]`).classList.add('active');

  // Load tab-specific data
  if (tabName === 'expenses') {
    initExpensesTab();
  } else if (tabName === 'reports') {
    loadReportsTab();
  } else if (tabName === 'settings') {
    loadSettingsTab();
  }
}

// ============ Global Month Selector ============

function initGlobalMonthSelector() {
  const select = document.getElementById("global-month-select");
  if (select.options.length === 0) {
    const now = new Date();
    for (let i = 0; i < 12; i++) {
      const d = new Date(now.getFullYear(), now.getMonth() - i, 1);
      const option = document.createElement("option");
      option.value = `${d.getFullYear()}-${d.getMonth() + 1}`;
      option.textContent = d.toLocaleDateString('he-IL', { year: 'numeric', month: 'long' });
      select.appendChild(option);
    }
  }
  if (!selectedMonth) {
    selectedMonth = select.value;
  }
  select.value = selectedMonth;
}

function changeGlobalMonth(delta) {
  const select = document.getElementById("global-month-select");
  const newIndex = select.selectedIndex + delta;
  if (newIndex >= 0 && newIndex < select.options.length) {
    select.selectedIndex = newIndex;
    loadByGlobalMonth();
  }
}

async function loadByGlobalMonth() {
  const select = document.getElementById("global-month-select");
  selectedMonth = select.value;
  // Reload all data based on the new global month
  await Promise.all([
    fetchDashboard(),
    loadExpensesByMonth(),
    loadReportsData()
  ]);
}

// ============ Dashboard Tab ============

async function fetchDashboard() {
  try {
    // Build URL with selected month
    let url = "/api/analytics/monthly";
    if (selectedMonth) {
      const [year, month] = selectedMonth.split('-').map(Number);
      url += `?year=${year}&month=${month}`;
    }
    const data = await apiGet(url);
    document.getElementById("stat-income").textContent = `₪${data.totals.income.toLocaleString()}`;
    document.getElementById("stat-spent").textContent = `₪${data.totals.spent.toLocaleString()}`;
    document.getElementById("stat-invested").textContent = `₪${data.totals.invested.toLocaleString()}`;
    document.getElementById("stat-savings-rate").textContent = `${data.totals.savings_rate_pct}%`;
    renderInsights(data.alerts, data.insights);
    renderCategoryProgress(data.category_breakdown);
    renderChart(data.category_breakdown);
    await fetchRecentExpenses();
  } catch (error) {
    console.error("Dashboard fetch error:", error);
  }
}

function renderInsights(alerts, insights) {
  const insightsList = document.getElementById("insights-list");
  const insightsCard = document.getElementById("insights-card");
  insightsList.innerHTML = "";
  const allMessages = [...alerts, ...insights];
  if (allMessages.length > 0) {
    insightsCard.classList.remove("hidden");
    allMessages.forEach((msg) => {
      const li = document.createElement("li");
      const isAlert = alerts.includes(msg);
      li.innerHTML = `<span class="${isAlert ? 'text-amber-400' : 'text-slate-300'}">${isAlert ? '⚠️ ' : '💡 '}${msg}</span>`;
      insightsList.appendChild(li);
    });
  } else {
    insightsCard.classList.add("hidden");
  }
}

function renderCategoryProgress(breakdown) {
  const container = document.getElementById("category-progress-list");
  container.innerHTML = "";
  breakdown.forEach((cat) => {
    const isOver = cat.budget > 0 && cat.spent > cat.budget;
    const barWidth = Math.min(cat.percent_used, 100);
    const item = document.createElement("div");
    item.innerHTML = `
      <div class="flex justify-between mb-1 text-slate-300">
        <span class="font-medium">${cat.name}</span>
        <span>₪${cat.spent.toLocaleString()} / ₪${cat.budget.toLocaleString()} (${cat.percent_used}%)</span>
      </div>
      <div class="w-full bg-slate-700 h-2 rounded-full overflow-hidden">
        <div class="${isOver ? 'bg-rose-500' : 'bg-emerald-500'} h-full transition-all duration-300" style="width: ${barWidth}%"></div>
      </div>
    `;
    container.appendChild(item);
  });
}

function renderChart(breakdown) {
  const ctx = document.getElementById("categoryChart").getContext("2d");
  const filtered = breakdown.filter(c => c.spent > 0);
  const chartLabels = filtered.map((c) => c.name);
  const chartValues = filtered.map((c) => c.spent);
  const colors = ["#10b981", "#38bdf8", "#f59e0b", "#ec4899", "#8b5cf6", "#f43f5e", "#64748b", "#06b6d4"];
  if (chartInstance) chartInstance.destroy();
  chartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: chartLabels,
      datasets: [{ data: chartValues, backgroundColor: colors.slice(0, chartValues.length), borderWidth: 0 }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: { callbacks: { label: (context) => `₪${context.parsed.toLocaleString()}` } }
      }
    }
  });
}

async function fetchRecentExpenses() {
  try {
    const expenses = await apiGet("/api/analytics/recent?limit=10");
    const container = document.getElementById("recent-expenses");
    container.innerHTML = "";
    if (expenses.length === 0) {
      container.innerHTML = '<div class="text-slate-500 text-center py-2">אין הוצאות עדיין</div>';
      return;
    }
    expenses.forEach((exp) => {
      const date = new Date(exp.created_at).toLocaleDateString("he-IL");
      const sourceLabel = exp.source === 'file' ? 'קובץ' : 'ידני';
      const item = document.createElement("div");
      item.className = "flex justify-between items-center py-2 border-b border-slate-700/50 group";
      item.innerHTML = `
        <div class="flex-1 flex items-center gap-2">
          <span class="text-slate-200">${exp.description}</span>
          <span class="text-slate-500">•</span>
          <select class="category-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1" data-expense-id="${exp.id}">
            ${categories.map(cat => `<option value="${cat.id}" ${cat.name === exp.category ? 'selected' : ''}>${cat.name}</option>`).join('')}
          </select>
        </div>
        <div class="flex items-center gap-3">
          <span class="text-rose-400 font-medium">₪${exp.amount.toLocaleString()}</span>
          <span class="text-slate-500 text-xs">${date}</span>
          <span class="text-xs px-1.5 py-0.5 rounded ${exp.source === 'file' ? 'bg-sky-900/50 text-sky-400' : 'bg-slate-700 text-slate-400'}">${sourceLabel}</span>
          <button class="delete-btn text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100" data-expense-id="${exp.id}">✕</button>
        </div>
      `;
      container.appendChild(item);
    });
    container.querySelectorAll('.category-select').forEach(select => select.addEventListener('change', handleCategoryChange));
    container.querySelectorAll('.delete-btn').forEach(btn => btn.addEventListener('click', handleDeleteExpense));
  } catch (error) {
    console.error("Recent expenses fetch error:", error);
  }
}

async function handleCategoryChange(e) {
  const select = e.target;
  const expenseId = select.dataset.expenseId;
  const newCategoryId = parseInt(select.value);
  select.disabled = true;
  try {
    await apiPatch(`/api/expenses/${expenseId}`, { category_id: newCategoryId });
    await fetchDashboard();
  } catch (error) {
    console.error("Failed to update category:", error);
    alert("שגיאה בעדכון קטגוריה");
  } finally {
    select.disabled = false;
  }
}

async function handleDeleteExpense(e) {
  const btn = e.target;
  const expenseId = btn.dataset.expenseId;
  if (!confirm("למחוק את ההוצאה?")) return;
  try {
    await apiDelete(`/api/expenses/${expenseId}`);
    await fetchDashboard();
  } catch (error) {
    console.error("Failed to delete expense:", error);
    alert("שגיאה במחיקת הוצאה");
  }
}

// ============ Categories ============

async function loadCategories() {
  try {
    categories = await apiGet("/api/categories");
    populateCategorySelects();
  } catch (error) {
    console.error("Categories fetch error:", error);
  }
}

function populateCategorySelects() {
  const selects = ['exp-category', 'rec-category', 'expense-category-filter'];
  selects.forEach(id => {
    const select = document.getElementById(id);
    if (select) {
      const firstOption = id === 'expense-category-filter' ? '<option value="">הכל</option>' : '';
      select.innerHTML = firstOption + categories.map(cat => `<option value="${cat.id}">${cat.name}</option>`).join('');
    }
  });
}

// ============ Form Handlers ============

function setupFormHandlers() {
  document.getElementById("income-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");
    try {
      await apiPost("/api/incomes", {
        amount: parseFloat(document.getElementById("inc-amount").value),
        income_type: document.getElementById("inc-type").value,
        notes: document.getElementById("inc-notes").value || null,
        member_id: 1,
        received_date: new Date().toISOString().split("T")[0]
      });
      form.reset();
      await fetchDashboard();
    } catch (error) {
      alert("שגיאה בהוספת הכנסה");
    } finally {
      form.classList.remove("loading");
    }
  });

  document.getElementById("investment-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");
    try {
      await apiPost("/api/investments", {
        amount: parseFloat(document.getElementById("inv-amount").value),
        target_name: document.getElementById("inv-target").value,
        transaction_date: new Date().toISOString().split("T")[0]
      });
      form.reset();
      await fetchDashboard();
    } catch (error) {
      alert("שגיאה בהוספת הפקדה");
    } finally {
      form.classList.remove("loading");
    }
  });

  document.getElementById("expense-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");
    try {
      await apiPost("/api/expenses", {
        amount: parseFloat(document.getElementById("exp-amount").value),
        description: document.getElementById("exp-desc").value,
        category_id: parseInt(document.getElementById("exp-category").value),
        payer: "Dashboard",
        is_fixed: false
      });
      form.reset();
      await fetchDashboard();
    } catch (error) {
      alert("שגיאה בהוספת הוצאה");
    } finally {
      form.classList.remove("loading");
    }
  });
}

async function refreshDashboard() {
  await fetchDashboard();
  await fetchRecurringExpenses();
}

// ============ Recurring Expenses ============

function toggleRecurringForm() {
  document.getElementById("recurring-form").classList.toggle("hidden");
}

async function fetchRecurringExpenses() {
  try {
    const recurring = await apiGet("/api/recurring");
    const container = document.getElementById("recurring-list");
    container.innerHTML = "";
    if (recurring.length === 0) {
      container.innerHTML = '<div class="text-slate-500 text-center py-2">אין הוצאות קבועות</div>';
      return;
    }
    const totalMonthly = recurring.filter(r => r.is_active && r.frequency === "monthly").reduce((sum, r) => sum + r.amount, 0);
    const summary = document.createElement("div");
    summary.className = "mb-3 p-2 bg-slate-900/50 rounded text-amber-400 font-medium";
    summary.innerHTML = `סה"כ הוצאות קבועות חודשיות: ₪${totalMonthly.toLocaleString()}`;
    container.appendChild(summary);
    recurring.forEach((rec) => {
      const item = document.createElement("div");
      item.className = `flex justify-between items-center py-2 border-b border-slate-700/50 group ${!rec.is_active ? 'opacity-50' : ''}`;
      item.innerHTML = `
        <div class="flex-1 flex items-center gap-2">
          <span class="text-slate-200 font-medium">${rec.name}</span>
          <span class="text-slate-500">•</span>
          <span class="text-slate-400">${rec.category}</span>
          <span class="text-xs px-2 py-0.5 rounded ${rec.frequency === 'monthly' ? 'bg-amber-900/50 text-amber-400' : 'bg-slate-700 text-slate-400'}">${rec.frequency === 'monthly' ? 'חודשי' : 'חד פעמי'}</span>
        </div>
        <div class="flex items-center gap-3">
          <span class="text-amber-400 font-medium">₪${rec.amount.toLocaleString()}</span>
          <span class="text-slate-500 text-xs">יום ${rec.day_of_month}</span>
          <button class="toggle-recurring-btn text-slate-500 hover:text-amber-400 opacity-0 group-hover:opacity-100" data-recurring-id="${rec.id}" data-is-active="${rec.is_active}">${rec.is_active ? '⏸' : '▶'}</button>
          <button class="delete-recurring-btn text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100" data-recurring-id="${rec.id}">✕</button>
        </div>
      `;
      container.appendChild(item);
    });
    container.querySelectorAll('.toggle-recurring-btn').forEach(btn => btn.addEventListener('click', handleToggleRecurring));
    container.querySelectorAll('.delete-recurring-btn').forEach(btn => btn.addEventListener('click', handleDeleteRecurring));
  } catch (error) {
    console.error("Recurring expenses fetch error:", error);
  }
}

async function handleToggleRecurring(e) {
  const btn = e.target;
  try {
    await apiPatch(`/api/recurring/${btn.dataset.recurringId}`, { is_active: btn.dataset.isActive !== 'true' });
    await refreshDashboard();
  } catch (error) {
    alert("שגיאה בעדכון הוצאה קבועה");
  }
}

async function handleDeleteRecurring(e) {
  if (!confirm("למחוק את ההוצאה הקבועה?")) return;
  try {
    await apiDelete(`/api/recurring/${e.target.dataset.recurringId}`);
    await refreshDashboard();
  } catch (error) {
    alert("שגיאה במחיקת הוצאה קבועה");
  }
}

function setupRecurringForm() {
  document.getElementById("recurring-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");
    try {
      await apiPost("/api/recurring", {
        name: document.getElementById("rec-name").value,
        amount: parseFloat(document.getElementById("rec-amount").value),
        category_id: parseInt(document.getElementById("rec-category").value),
        frequency: document.getElementById("rec-frequency").value,
        day_of_month: parseInt(document.getElementById("rec-day").value) || 1,
        notes: document.getElementById("rec-notes").value || null
      });
      form.reset();
      form.classList.add("hidden");
      await refreshDashboard();
    } catch (error) {
      alert("שגיאה בהוספת הוצאה קבועה");
    } finally {
      form.classList.remove("loading");
    }
  });
}

// ============ Expenses Tab ============

function initExpensesTab() {
  // Just load expenses using the global month
  loadExpensesByMonth();
}

async function loadExpensesByMonth() {
  if (!selectedMonth) return;
  const [year, month] = selectedMonth.split('-').map(Number);
  try {
    currentExpenses = await apiGet(`/api/expenses/by-month?year=${year}&month=${month}`);
    const total = currentExpenses.reduce((sum, e) => sum + e.amount, 0);
    document.getElementById("expense-month-total").textContent = `₪${total.toLocaleString()}`;
    filterExpenses();
  } catch (error) {
    console.error("Failed to load expenses:", error);
  }
}

async function clearMonthExpenses() {
  const select = document.getElementById("global-month-select");
  const monthLabel = select.options[select.selectedIndex].text;
  const [year, month] = selectedMonth.split('-').map(Number);

  if (!confirm(`האם אתה בטוח שברצונך למחוק את כל ההוצאות של ${monthLabel}?\n\nפעולה זו בלתי הפיכה!`)) {
    return;
  }

  try {
    const result = await apiDelete(`/api/expenses/bulk/by-month?year=${year}&month=${month}`);
    alert(`נמחקו ${result.count} הוצאות`);
    await loadExpensesByMonth();
    await refreshDashboard();
  } catch (error) {
    console.error("Failed to clear month expenses:", error);
    alert("שגיאה במחיקת הוצאות");
  }
}

function filterExpenses() {
  const categoryFilter = document.getElementById("expense-category-filter").value;
  const searchText = document.getElementById("expense-search").value.toLowerCase();
  let filtered = currentExpenses;
  if (categoryFilter) {
    filtered = filtered.filter(e => e.category_id === parseInt(categoryFilter));
  }
  if (searchText) {
    filtered = filtered.filter(e => e.description.toLowerCase().includes(searchText));
  }
  renderExpensesTable(filtered);
}

function renderExpensesTable(expenses) {
  const tbody = document.getElementById("expenses-table-body");
  tbody.innerHTML = "";
  if (expenses.length === 0) {
    tbody.innerHTML = '<tr><td colspan="6" class="text-center p-4 text-slate-500">לא נמצאו הוצאות</td></tr>';
    return;
  }
  expenses.forEach(exp => {
    // Use transaction_date if available, otherwise created_at
    const dateStr = exp.transaction_date || exp.created_at;
    const date = new Date(dateStr).toLocaleDateString("he-IL");
    const sourceLabel = exp.source === 'file' ? 'קובץ' : 'ידני';
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-800/50";
    tr.innerHTML = `
      <td class="p-3 text-slate-300">${date}</td>
      <td class="p-3">
        <input type="text" value="${exp.description}" class="expense-desc-input bg-transparent border-b border-transparent hover:border-slate-600 focus:border-emerald-500 focus:outline-none w-full" data-expense-id="${exp.id}" />
      </td>
      <td class="p-3">
        <select class="expense-cat-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1" data-expense-id="${exp.id}">
          ${categories.map(cat => `<option value="${cat.id}" ${cat.id === exp.category_id ? 'selected' : ''}>${cat.name}</option>`).join('')}
        </select>
      </td>
      <td class="p-3">
        <input type="number" value="${exp.amount}" step="0.01" class="expense-amount-input bg-transparent border-b border-transparent hover:border-slate-600 focus:border-emerald-500 focus:outline-none w-20 text-rose-400 font-medium" data-expense-id="${exp.id}" />
      </td>
      <td class="p-3 text-center">
        <span class="text-xs px-1.5 py-0.5 rounded ${exp.source === 'file' ? 'bg-sky-900/50 text-sky-400' : 'bg-slate-700 text-slate-400'}">${sourceLabel}</span>
      </td>
      <td class="p-3 text-center">
        <button class="expense-delete-btn text-slate-500 hover:text-rose-400" data-expense-id="${exp.id}">🗑️</button>
      </td>
    `;
    tbody.appendChild(tr);
  });
  // Add event listeners
  tbody.querySelectorAll('.expense-desc-input').forEach(input => {
    input.addEventListener('blur', handleExpenseUpdate);
  });
  tbody.querySelectorAll('.expense-amount-input').forEach(input => {
    input.addEventListener('blur', handleExpenseUpdate);
  });
  tbody.querySelectorAll('.expense-cat-select').forEach(select => {
    select.addEventListener('change', handleExpenseUpdate);
  });
  tbody.querySelectorAll('.expense-delete-btn').forEach(btn => {
    btn.addEventListener('click', handleExpenseDelete);
  });
  document.getElementById("expenses-pagination").textContent = `מציג ${expenses.length} הוצאות`;
}

async function handleExpenseUpdate(e) {
  const el = e.target;
  const expenseId = el.dataset.expenseId;
  const updates = {};
  if (el.classList.contains('expense-desc-input')) {
    updates.description = el.value;
  } else if (el.classList.contains('expense-amount-input')) {
    updates.amount = parseFloat(el.value);
  } else if (el.classList.contains('expense-cat-select')) {
    updates.category_id = parseInt(el.value);
  }
  try {
    await apiPatch(`/api/expenses/${expenseId}`, updates);
    el.classList.add('border-emerald-500');
    setTimeout(() => el.classList.remove('border-emerald-500'), 500);
    // Update local data
    const exp = currentExpenses.find(e => e.id === parseInt(expenseId));
    if (exp) Object.assign(exp, updates);
    const total = currentExpenses.reduce((sum, e) => sum + e.amount, 0);
    document.getElementById("expense-month-total").textContent = `₪${total.toLocaleString()}`;
  } catch (error) {
    alert("שגיאה בעדכון הוצאה");
  }
}

async function handleExpenseDelete(e) {
  const expenseId = e.target.dataset.expenseId;
  if (!confirm("למחוק את ההוצאה?")) return;
  try {
    await apiDelete(`/api/expenses/${expenseId}`);
    await loadExpensesByMonth();
  } catch (error) {
    alert("שגיאה במחיקת הוצאה");
  }
}

// ============ Reports Tab ============

async function loadReportsTab() {
  await loadReportsData();
}

async function loadReportsData() {
  try {
    // Load both comparison data and advanced analytics
    const [comparisonData] = await Promise.all([
      apiGet("/api/analytics/comparison?months=6"),
      loadAdvancedAnalytics()
    ]);
    renderComparisonChart(comparisonData);
    renderCategoryTrendChart(comparisonData);
    renderComparisonTable(comparisonData);
  } catch (error) {
    console.error("Failed to load reports:", error);
  }
}

async function loadAdvancedAnalytics() {
  if (!selectedMonth) return;
  const [year, month] = selectedMonth.split('-').map(Number);

  try {
    const data = await apiGet(`/api/analytics/advanced?year=${year}&month=${month}`);
    renderAdvancedAnalytics(data);
  } catch (error) {
    console.error("Failed to load advanced analytics:", error);
  }
}

function renderAdvancedAnalytics(data) {
  // Update stats cards
  document.getElementById("stat-transactions").textContent = data.total_transactions.toLocaleString();
  document.getElementById("stat-daily-avg").textContent = `₪${data.daily_average.toLocaleString()}`;
  document.getElementById("stat-unique-merchants").textContent = data.top_merchants.length;
  document.getElementById("stat-duplicates").textContent = data.potential_duplicates.length;

  // Render insights
  const insightsCard = document.getElementById("advanced-insights-card");
  const insightsList = document.getElementById("advanced-insights-list");
  insightsList.innerHTML = "";
  if (data.insights && data.insights.length > 0) {
    insightsCard.classList.remove("hidden");
    data.insights.forEach(insight => {
      const li = document.createElement("li");
      li.innerHTML = `<span class="text-slate-300">• ${insight}</span>`;
      insightsList.appendChild(li);
    });
  } else {
    insightsCard.classList.add("hidden");
  }

  // Render potential duplicates
  renderDuplicates(data.potential_duplicates);

  // Render top merchants
  renderTopMerchants(data.top_merchants, data.total_spent);

  // Render charts
  renderDayOfWeekChart(data.spending_by_day_of_week);
}

function renderDuplicates(duplicates) {
  const section = document.getElementById("duplicates-section");
  const list = document.getElementById("duplicates-list");
  list.innerHTML = "";

  if (duplicates.length === 0) {
    section.classList.add("hidden");
    return;
  }

  section.classList.remove("hidden");

  duplicates.forEach(dup => {
    const item = document.createElement("div");
    item.className = "bg-slate-900/50 p-3 rounded-lg border border-rose-900/30";
    item.innerHTML = `
      <div class="flex justify-between items-start gap-4">
        <div class="flex-1">
          <div class="text-slate-200 font-medium">${dup.expense1.description}</div>
          <div class="text-xs text-slate-400">${dup.expense1.date} • ${dup.expense1.category}</div>
        </div>
        <div class="text-rose-400 font-bold">₪${dup.expense1.amount.toLocaleString()}</div>
      </div>
      <div class="my-2 text-center text-xs text-slate-500">↕️ ${dup.days_apart} ימים הפרש</div>
      <div class="flex justify-between items-start gap-4">
        <div class="flex-1">
          <div class="text-slate-200 font-medium">${dup.expense2.description}</div>
          <div class="text-xs text-slate-400">${dup.expense2.date} • ${dup.expense2.category}</div>
        </div>
        <div class="text-rose-400 font-bold">₪${dup.expense2.amount.toLocaleString()}</div>
      </div>
    `;
    list.appendChild(item);
  });
}

function renderTopMerchants(merchants, totalSpent) {
  const list = document.getElementById("top-merchants-list");
  list.innerHTML = "";

  if (merchants.length === 0) {
    list.innerHTML = '<div class="text-slate-500 text-center py-4">אין נתונים להצגה</div>';
    return;
  }

  const maxTotal = merchants[0].total;

  merchants.forEach((merchant, index) => {
    const percentage = totalSpent > 0 ? (merchant.total / totalSpent * 100).toFixed(1) : 0;
    const barWidth = (merchant.total / maxTotal * 100);
    const item = document.createElement("div");
    item.className = "relative";
    item.innerHTML = `
      <div class="flex justify-between items-center mb-1">
        <div class="flex items-center gap-2">
          <span class="text-xs text-slate-500 w-5">${index + 1}.</span>
          <span class="text-sm text-slate-200">${merchant.name}</span>
          <span class="text-xs text-slate-500">(${merchant.count} עסקאות)</span>
        </div>
        <div class="flex items-center gap-2">
          <span class="text-sm font-medium text-emerald-400">₪${merchant.total.toLocaleString()}</span>
          <span class="text-xs text-slate-500">${percentage}%</span>
        </div>
      </div>
      <div class="w-full bg-slate-700 h-1.5 rounded-full overflow-hidden">
        <div class="bg-emerald-500 h-full transition-all duration-300" style="width: ${barWidth}%"></div>
      </div>
    `;
    list.appendChild(item);
  });
}

function renderDayOfWeekChart(dayData) {
  const ctx = document.getElementById("dayOfWeekChart").getContext("2d");
  if (dayOfWeekChartInstance) dayOfWeekChartInstance.destroy();

  // Sort by day number for correct order (Sunday first in Israel)
  const sortedData = [...dayData].sort((a, b) => {
    // Reorder: Sunday (6) first, then Monday (0) through Saturday (5)
    const orderA = a.day_num === 6 ? 0 : a.day_num + 1;
    const orderB = b.day_num === 6 ? 0 : b.day_num + 1;
    return orderA - orderB;
  });

  dayOfWeekChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: sortedData.map(d => d.day),
      datasets: [{
        label: 'סה"כ הוצאות',
        data: sortedData.map(d => d.total),
        backgroundColor: '#38bdf8',
        borderRadius: 4
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: (ctx) => `₪${ctx.parsed.y.toLocaleString()} (${sortedData[ctx.dataIndex].count} עסקאות)`
          }
        }
      },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { display: false } },
        y: { ticks: { color: '#94a3b8', callback: (v) => `₪${v.toLocaleString()}` }, grid: { color: '#334155' } }
      }
    }
  });
}

function renderComparisonChart(data) {
  const ctx = document.getElementById("comparisonChart").getContext("2d");
  if (comparisonChartInstance) comparisonChartInstance.destroy();
  comparisonChartInstance = new Chart(ctx, {
    type: "bar",
    data: {
      labels: data.map(d => d.period_label),
      datasets: [
        {
          label: 'הוצאות',
          data: data.map(d => d.total_spent),
          backgroundColor: '#f43f5e',
          borderRadius: 4
        },
        {
          label: 'הכנסות',
          data: data.map(d => d.total_income),
          backgroundColor: '#10b981',
          borderRadius: 4
        }
      ]
    },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8' } },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ₪${ctx.parsed.y.toLocaleString()}` } }
      },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
        y: { ticks: { color: '#94a3b8', callback: (v) => `₪${v.toLocaleString()}` }, grid: { color: '#334155' } }
      }
    }
  });
}

function renderCategoryTrendChart(data) {
  const ctx = document.getElementById("categoryTrendChart").getContext("2d");
  if (categoryTrendChartInstance) categoryTrendChartInstance.destroy();
  const categoryNames = categories.map(c => c.name);
  const colors = ["#10b981", "#38bdf8", "#f59e0b", "#ec4899", "#8b5cf6", "#f43f5e", "#64748b", "#06b6d4"];
  const datasets = categoryNames.map((catName, idx) => ({
    label: catName,
    data: data.map(d => d.categories[catName] || 0),
    borderColor: colors[idx % colors.length],
    backgroundColor: colors[idx % colors.length] + '20',
    fill: false,
    tension: 0.3
  }));
  categoryTrendChartInstance = new Chart(ctx, {
    type: "line",
    data: { labels: data.map(d => d.period_label), datasets },
    options: {
      responsive: true,
      maintainAspectRatio: false,
      plugins: {
        legend: { labels: { color: '#94a3b8', font: { size: 10 } }, position: 'bottom' },
        tooltip: { callbacks: { label: (ctx) => `${ctx.dataset.label}: ₪${ctx.parsed.y.toLocaleString()}` } }
      },
      scales: {
        x: { ticks: { color: '#94a3b8' }, grid: { color: '#334155' } },
        y: { ticks: { color: '#94a3b8', callback: (v) => `₪${v.toLocaleString()}` }, grid: { color: '#334155' } }
      }
    }
  });
}

function renderComparisonTable(data) {
  const header = document.getElementById("comparison-table-header");
  const tbody = document.getElementById("comparison-table-body");
  // Build header
  header.innerHTML = '<th class="text-right p-3 text-slate-400 sticky right-0 bg-slate-800">קטגוריה</th>';
  data.forEach(d => {
    header.innerHTML += `<th class="text-right p-3 text-slate-400">${d.period_label}</th>`;
  });
  // Build body
  tbody.innerHTML = "";
  const categoryNames = categories.map(c => c.name);
  categoryNames.forEach(catName => {
    const tr = document.createElement("tr");
    tr.className = "hover:bg-slate-800/50";
    tr.innerHTML = `<td class="p-3 font-medium text-slate-300 sticky right-0 bg-slate-800/90">${catName}</td>`;
    data.forEach(d => {
      const val = d.categories[catName] || 0;
      tr.innerHTML += `<td class="p-3 text-slate-300">₪${val.toLocaleString()}</td>`;
    });
    tbody.appendChild(tr);
  });
  // Add totals row
  const totalRow = document.createElement("tr");
  totalRow.className = "bg-slate-700/50 font-bold";
  totalRow.innerHTML = '<td class="p-3 text-emerald-400 sticky right-0 bg-slate-700/90">סה"כ</td>';
  data.forEach(d => {
    totalRow.innerHTML += `<td class="p-3 text-emerald-400">₪${d.total_spent.toLocaleString()}</td>`;
  });
  tbody.appendChild(totalRow);
}

// ============ Settings Tab ============

async function loadSettingsTab() {
  await loadCategories();
  renderCategoriesList();
  await loadKeywords();
}

function renderCategoriesList() {
  const container = document.getElementById("categories-list");
  container.innerHTML = "";
  categories.forEach(cat => {
    const item = document.createElement("div");
    item.className = "flex justify-between items-center p-4 hover:bg-slate-800/50 group";
    item.innerHTML = `
      <div class="flex-1 grid grid-cols-1 md:grid-cols-4 gap-3 items-center">
        <input type="text" value="${cat.name}" class="cat-name-input bg-transparent border-b border-transparent hover:border-slate-600 focus:border-emerald-500 focus:outline-none text-slate-200" data-cat-id="${cat.id}" />
        <select class="cat-type-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1" data-cat-id="${cat.id}">
          <option value="variable" ${cat.type === 'variable' ? 'selected' : ''}>הוצאה משתנה</option>
          <option value="fixed" ${cat.type === 'fixed' ? 'selected' : ''}>הוצאה קבועה</option>
        </select>
        <div class="flex items-center gap-1">
          <span class="text-slate-500 text-xs">תקציב:</span>
          <input type="number" value="${cat.monthly_budget}" step="0.01" class="cat-budget-input bg-transparent border-b border-transparent hover:border-slate-600 focus:border-emerald-500 focus:outline-none w-24 text-amber-400" data-cat-id="${cat.id}" />
          <span class="text-slate-500 text-xs">₪</span>
        </div>
        <button class="save-cat-btn bg-emerald-600 hover:bg-emerald-500 px-3 py-1 rounded text-xs text-white opacity-0 group-hover:opacity-100 transition" data-cat-id="${cat.id}">שמור</button>
      </div>
      <button class="delete-cat-btn text-slate-500 hover:text-rose-400 mr-4 opacity-0 group-hover:opacity-100 transition" data-cat-id="${cat.id}">🗑️</button>
    `;
    container.appendChild(item);
  });
  container.querySelectorAll('.save-cat-btn').forEach(btn => btn.addEventListener('click', handleSaveCategory));
  container.querySelectorAll('.delete-cat-btn').forEach(btn => btn.addEventListener('click', handleDeleteCategory));

  // Calculate and display total budget
  const totalBudget = categories.reduce((sum, cat) => sum + (cat.monthly_budget || 0), 0);
  const totalEl = document.getElementById("total-budget-sum");
  if (totalEl) {
    totalEl.textContent = `₪${totalBudget.toLocaleString()}`;
  }
}

async function handleSaveCategory(e) {
  const catId = e.target.dataset.catId;
  const row = e.target.closest('.group');
  const name = row.querySelector('.cat-name-input').value;
  const type = row.querySelector('.cat-type-select').value;
  const budget = parseFloat(row.querySelector('.cat-budget-input').value) || 0;
  try {
    await apiPut(`/api/categories/${catId}`, { name, type, monthly_budget: budget });
    await loadCategories();
    alert("קטגוריה עודכנה בהצלחה");
  } catch (error) {
    alert("שגיאה בעדכון קטגוריה");
  }
}

async function handleDeleteCategory(e) {
  const catId = e.target.dataset.catId;
  if (!confirm("למחוק את הקטגוריה? (רק אם אין הוצאות משויכות)")) return;
  try {
    const result = await apiDelete(`/api/categories/${catId}`);
    if (result.error) {
      alert(result.error);
    } else {
      await loadCategories();
      renderCategoriesList();
    }
  } catch (error) {
    alert("שגיאה במחיקת קטגוריה");
  }
}

function setupCategoryForm() {
  document.getElementById("category-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");
    try {
      await apiPost("/api/categories", {
        name: document.getElementById("cat-name").value,
        type: document.getElementById("cat-type").value,
        monthly_budget: parseFloat(document.getElementById("cat-budget").value) || 0
      });
      form.reset();
      await loadCategories();
      renderCategoriesList();
    } catch (error) {
      alert("שגיאה בהוספת קטגוריה");
    } finally {
      form.classList.remove("loading");
    }
  });
}

// ============ Keywords Management (Learning System) ============

async function loadKeywords() {
  try {
    const keywords = await apiGet("/api/keywords");
    renderKeywordsList(keywords);
    document.getElementById("keywords-count").textContent = `${keywords.length} מילות מפתח`;
    // Populate category select for new keyword form
    const select = document.getElementById("new-keyword-category");
    if (select) {
      select.innerHTML = categories.map(cat => `<option value="${cat.id}">${cat.name}</option>`).join('');
    }
  } catch (error) {
    console.error("Failed to load keywords:", error);
  }
}

function renderKeywordsList(keywords) {
  const container = document.getElementById("keywords-list");
  container.innerHTML = "";

  if (keywords.length === 0) {
    container.innerHTML = '<div class="p-4 text-center text-slate-500 text-xs">אין מילות מפתח נלמדות עדיין. שנה קטגוריה של הוצאה והמערכת תלמד!</div>';
    return;
  }

  // Group keywords by category for better display
  const groupedByCategory = {};
  keywords.forEach(kw => {
    if (!groupedByCategory[kw.category]) {
      groupedByCategory[kw.category] = [];
    }
    groupedByCategory[kw.category].push(kw);
  });

  for (const [categoryName, categoryKeywords] of Object.entries(groupedByCategory)) {
    const groupDiv = document.createElement("div");
    groupDiv.className = "p-3 hover:bg-slate-800/30";
    groupDiv.innerHTML = `
      <div class="text-xs font-semibold text-emerald-400 mb-2">${categoryName}</div>
      <div class="flex flex-wrap gap-2">
        ${categoryKeywords.map(kw => `
          <span class="inline-flex items-center gap-1 bg-slate-700/50 text-slate-300 text-xs px-2 py-1 rounded group">
            ${kw.keyword}
            <button onclick="deleteKeyword(${kw.id})" class="text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition">✕</button>
          </span>
        `).join('')}
      </div>
    `;
    container.appendChild(groupDiv);
  }
}

async function deleteKeyword(keywordId) {
  try {
    await apiDelete(`/api/keywords/${keywordId}`);
    await loadKeywords();
  } catch (error) {
    alert("שגיאה במחיקת מילת מפתח");
  }
}

async function clearAllKeywords() {
  if (!confirm("האם אתה בטוח שברצונך למחוק את כל מילות המפתח הנלמדות?\n\nהמערכת תצטרך ללמוד מחדש משינויי קטגוריות.")) {
    return;
  }
  try {
    const result = await apiDelete("/api/keywords/bulk/all");
    alert(`נמחקו ${result.count} מילות מפתח`);
    await loadKeywords();
  } catch (error) {
    alert("שגיאה באיפוס הלמידה");
  }
}

function setupKeywordForm() {
  const form = document.getElementById("keyword-form");
  if (!form) return;

  form.addEventListener("submit", async (e) => {
    e.preventDefault();
    const keyword = document.getElementById("new-keyword").value.trim();
    const categoryId = parseInt(document.getElementById("new-keyword-category").value);

    if (!keyword) return;

    try {
      await apiPost("/api/keywords", {
        keyword: keyword,
        category_id: categoryId
      });
      document.getElementById("new-keyword").value = "";
      await loadKeywords();
    } catch (error) {
      alert("שגיאה בהוספת מילת מפתח");
    }
  });
}

// ============ Initialize ============

document.addEventListener("DOMContentLoaded", async () => {
  await loadCategories();
  initGlobalMonthSelector();
  await fetchDashboard();
  await fetchRecurringExpenses();
  setupFormHandlers();
  setupRecurringForm();
  setupCategoryForm();
  setupKeywordForm();
  setInterval(refreshDashboard, 30000);
});
