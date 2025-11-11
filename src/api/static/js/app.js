const form = document.getElementById("forecast-form");
const resultsEl = document.getElementById("results");

if (!form || !resultsEl) {
  return;
}

const formatCurrency = (value) => {
  const currencyField = document.getElementById("currency");
  const code = currencyField ? currencyField.value.trim().toUpperCase() : "INR";
  const amount = Number(value);
  if (code === "INR") {
    return `₹${amount.toLocaleString("en-IN", { minimumFractionDigits: 4, maximumFractionDigits: 4 })}`;
  }
  return amount.toLocaleString(undefined, {
    style: "currency",
    currency: code,
  });
};

form.addEventListener("submit", async (event) => {
  event.preventDefault();

  const provider = document.getElementById("provider").value.trim();
  const service = document.getElementById("service").value.trim();
  const region = document.getElementById("region").value.trim();
  const currency = document.getElementById("currency").value.trim();
  const timeIdxStart = Number(document.getElementById("time_idx_start").value);
  const recentCosts = document
    .getElementById("recent_costs")
    .value.split(/[,\s]+/)
    .map((v) => v.trim())
    .filter(Boolean)
    .map((n) => Number(n));

  if (!recentCosts.length) {
    alert("Please provide at least one recent cost.");
    return;
  }

  resultsEl.innerHTML = '<p class="muted">Running forecast...</p>';

  try {
    const response = await fetch("/forecast", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        provider,
        service,
        region,
        currency,
        recent_costs: recentCosts,
        time_idx_start: timeIdxStart,
      }),
    });

    if (!response.ok) {
      const detail = await response.json();
      throw new Error(detail.detail || "Forecast failed");
    }

    const data = await response.json();
    renderResults(provider, service, data.forecast);
  } catch (error) {
    resultsEl.innerHTML = `<p class="muted">${error.message}</p>`;
  }
});

function renderResults(provider, service, forecast) {
  if (!forecast) {
    resultsEl.innerHTML = '<p class="muted">No forecast returned.</p>';
    return;
  }

  const quantiles = Object.keys(forecast).sort();
  const rows = quantiles
    .map((q) => {
      const series = forecast[q];
      return `<tr><td>${q}</td><td>${series.map((v) => formatCurrency(v)).join("<br>")}</td></tr>`;
    })
    .join("");

  const medianSeries = forecast["0.5"] || quantiles.length ? forecast[quantiles[Math.floor(quantiles.length / 2)]] : [];
  const horizonDays = medianSeries.length || 1;
  const weeklySum = medianSeries.reduce((acc, value) => acc + value, 0);
  const monthlyEstimate = (weeklySum / horizonDays) * 30;
  const yearlyEstimate = monthlyEstimate * 12;

  resultsEl.innerHTML = `
    <div class="summary">
      <p><strong>${provider.toUpperCase()}</strong> · ${service}</p>
      <div class="metrics">
        <div class="metric">
          <span>Weekly projection</span>
          <strong>${formatCurrency(weeklySum)}</strong>
        </div>
        <div class="metric">
          <span>Monthly projection</span>
          <strong>${formatCurrency(monthlyEstimate)}</strong>
        </div>
        <div class="metric">
          <span>Yearly projection</span>
          <strong>${formatCurrency(yearlyEstimate)}</strong>
        </div>
      </div>
    </div>
    <table>
      <thead>
        <tr>
          <th>Quantile</th>
          <th>Daily Forecasts</th>
        </tr>
      </thead>
      <tbody>${rows}</tbody>
    </table>
    <p class="muted">Monthly/yearly estimates scale the current horizon average across 30 days / 12 months.</p>
  `;
}
