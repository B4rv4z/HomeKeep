// Family Budget Tracker - Frontend Application

let chartInstance = null;
let categories = [];

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

// ============ Dashboard Data ============

async function fetchDashboard() {
  try {
    const data = await apiGet("/api/analytics/monthly");

    // Update period
    document.getElementById("current-period").textContent = data.period;

    // Update stats
    document.getElementById("stat-income").textContent = `₪${data.totals.income.toLocaleString()}`;
    document.getElementById("stat-spent").textContent = `₪${data.totals.spent.toLocaleString()}`;
    document.getElementById("stat-invested").textContent = `₪${data.totals.invested.toLocaleString()}`;
    document.getElementById("stat-savings-rate").textContent = `${data.totals.savings_rate_pct}%`;

    // Render Insights & Alerts
    renderInsights(data.alerts, data.insights);

    // Render Category Progress Bars
    renderCategoryProgress(data.category_breakdown);

    // Render Doughnut Chart
    renderChart(data.category_breakdown);

    // Fetch and render recent expenses
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
      // Add warning icon for alerts
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

  // Filter out categories with zero spending for cleaner chart
  const filtered = breakdown.filter(c => c.spent > 0);
  const chartLabels = filtered.map((c) => c.name);
  const chartValues = filtered.map((c) => c.spent);

  const colors = [
    "#10b981", "#38bdf8", "#f59e0b", "#ec4899",
    "#8b5cf6", "#f43f5e", "#64748b", "#06b6d4"
  ];

  if (chartInstance) chartInstance.destroy();

  chartInstance = new Chart(ctx, {
    type: "doughnut",
    data: {
      labels: chartLabels,
      datasets: [{
        data: chartValues,
        backgroundColor: colors.slice(0, chartValues.length),
        borderWidth: 0
      }]
    },
    options: {
      responsive: true,
      maintainAspectRatio: true,
      plugins: {
        legend: { display: false },
        tooltip: {
          callbacks: {
            label: function(context) {
              return `₪${context.parsed.toLocaleString()}`;
            }
          }
        }
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
      const item = document.createElement("div");
      item.className = "flex justify-between items-center py-2 border-b border-slate-700/50 group";
      item.innerHTML = `
        <div class="flex-1 flex items-center gap-2">
          <span class="text-slate-200">${exp.description}</span>
          <span class="text-slate-500">•</span>
          <select
            class="category-select bg-slate-800 border border-slate-600 text-slate-300 text-xs rounded px-2 py-1 cursor-pointer hover:border-emerald-500 focus:border-emerald-500 focus:outline-none"
            data-expense-id="${exp.id}"
            data-original-category="${exp.category}"
          >
            ${categories.map(cat => `
              <option value="${cat.id}" ${cat.name === exp.category ? 'selected' : ''}>${cat.name}</option>
            `).join('')}
          </select>
        </div>
        <div class="flex items-center gap-3">
          <span class="text-rose-400 font-medium">₪${exp.amount.toLocaleString()}</span>
          <span class="text-slate-500 text-xs">${date}</span>
          <button
            class="delete-btn text-slate-500 hover:text-rose-400 opacity-0 group-hover:opacity-100 transition-opacity"
            data-expense-id="${exp.id}"
            title="מחק הוצאה"
          >
            ✕
          </button>
        </div>
      `;
      container.appendChild(item);
    });

    // Add event listeners for category changes
    container.querySelectorAll('.category-select').forEach(select => {
      select.addEventListener('change', handleCategoryChange);
    });

    // Add event listeners for delete buttons
    container.querySelectorAll('.delete-btn').forEach(btn => {
      btn.addEventListener('click', handleDeleteExpense);
    });

  } catch (error) {
    console.error("Recent expenses fetch error:", error);
  }
}

async function handleCategoryChange(e) {
  const select = e.target;
  const expenseId = select.dataset.expenseId;
  const newCategoryId = parseInt(select.value);
  const originalCategory = select.dataset.originalCategory;

  select.disabled = true;
  select.classList.add('opacity-50');

  try {
    await apiPatch(`/api/expenses/${expenseId}`, { category_id: newCategoryId });

    // Update the original category data attribute
    const newCategory = categories.find(c => c.id === newCategoryId);
    select.dataset.originalCategory = newCategory ? newCategory.name : originalCategory;

    // Show success feedback
    select.classList.add('border-emerald-500');
    setTimeout(() => select.classList.remove('border-emerald-500'), 1000);

    // Refresh dashboard to update charts/totals
    await fetchDashboard();
  } catch (error) {
    console.error("Failed to update category:", error);
    // Revert selection on error
    const originalCat = categories.find(c => c.name === originalCategory);
    if (originalCat) select.value = originalCat.id;
    alert("שגיאה בעדכון קטגוריה");
  } finally {
    select.disabled = false;
    select.classList.remove('opacity-50');
  }
}

async function handleDeleteExpense(e) {
  const btn = e.target;
  const expenseId = btn.dataset.expenseId;

  if (!confirm("למחוק את ההוצאה?")) return;

  btn.disabled = true;
  btn.textContent = "...";

  try {
    await apiDelete(`/api/expenses/${expenseId}`);
    await fetchDashboard();
  } catch (error) {
    console.error("Failed to delete expense:", error);
    alert("שגיאה במחיקת הוצאה");
    btn.disabled = false;
    btn.textContent = "✕";
  }
}

// ============ Categories ============

async function loadCategories() {
  try {
    categories = await apiGet("/api/categories");
    const select = document.getElementById("exp-category");
    select.innerHTML = "";

    categories.forEach((cat) => {
      const option = document.createElement("option");
      option.value = cat.id;
      option.textContent = cat.name;
      select.appendChild(option);
    });
  } catch (error) {
    console.error("Categories fetch error:", error);
  }
}

// ============ Form Handlers ============

function setupFormHandlers() {
  // Income form
  document.getElementById("income-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");

    try {
      const payload = {
        amount: parseFloat(document.getElementById("inc-amount").value),
        income_type: document.getElementById("inc-type").value,
        notes: document.getElementById("inc-notes").value || null,
        member_id: 1,
        received_date: new Date().toISOString().split("T")[0]
      };

      await apiPost("/api/incomes", payload);
      form.reset();
      await fetchDashboard();
    } catch (error) {
      console.error("Income submit error:", error);
      alert("שגיאה בהוספת הכנסה");
    } finally {
      form.classList.remove("loading");
    }
  });

  // Investment form
  document.getElementById("investment-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");

    try {
      const payload = {
        amount: parseFloat(document.getElementById("inv-amount").value),
        target_name: document.getElementById("inv-target").value,
        transaction_date: new Date().toISOString().split("T")[0]
      };

      await apiPost("/api/investments", payload);
      form.reset();
      await fetchDashboard();
    } catch (error) {
      console.error("Investment submit error:", error);
      alert("שגיאה בהוספת הפקדה");
    } finally {
      form.classList.remove("loading");
    }
  });

  // Expense form
  document.getElementById("expense-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    const form = e.target;
    form.classList.add("loading");

    try {
      const payload = {
        amount: parseFloat(document.getElementById("exp-amount").value),
        description: document.getElementById("exp-desc").value,
        category_id: parseInt(document.getElementById("exp-category").value),
        payer: "Dashboard",
        is_fixed: false
      };

      await apiPost("/api/expenses", payload);
      form.reset();
      await fetchDashboard();
    } catch (error) {
      console.error("Expense submit error:", error);
      alert("שגיאה בהוספת הוצאה");
    } finally {
      form.classList.remove("loading");
    }
  });
}

// ============ Refresh ============

async function refreshDashboard() {
  await fetchDashboard();
}

// ============ Initialize ============

document.addEventListener("DOMContentLoaded", async () => {
  await loadCategories();
  await fetchDashboard();
  setupFormHandlers();

  // Auto-refresh every 30 seconds
  setInterval(fetchDashboard, 30000);
});
