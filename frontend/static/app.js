// ─── State ───────────────────────────────────────────────────────────────────────────────
let packageTypes = [];
let activeList = null;

// ─── Init ────────────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await loadPackageTypes();
  await loadActiveList();
  setupDropZone();
});

async function loadPackageTypes() {
  const res = await fetch("/api/package-types");
  packageTypes = await res.json();
  renderOrderForm();
}

async function loadActiveList() {
  const res = await fetch("/api/price-list/active");
  activeList = await res.json();
  renderActiveListInfo();
}

function renderActiveListInfo() {
  const box = document.getElementById("active-list-info");
  if (!activeList || !activeList.active) {
    box.className = "info-box warning";
    box.innerHTML = "⚠️ Geen actieve prijslijst. Upload hieronder de prijslijst van vandaag.";
  } else {
    const date = new Date(activeList.upload_date).toLocaleDateString("nl-NL", {
      day: "numeric", month: "long", year: "numeric",
    });
    const cat = activeList.products.filter(p => p.price_per_piece).length;
    box.className = "info-box";
    box.innerHTML = `✅ Actieve prijslijst: <strong>${activeList.filename}</strong> &nbsp;|&nbsp; Geüpload: ${date} &nbsp;|&nbsp; ${cat} producten met kg-prijs`;
  }
}

function renderOrderForm() {
  const container = document.getElementById("package-order-list");
  if (!packageTypes.length) {
    container.innerHTML = '<p class="hint">Geen pakketsoorten geconfigureerd. Ga naar <a href="/admin">Beheer</a> om pakketsoorten toe te voegen.</p>';
    return;
  }
  container.innerHTML = packageTypes.map(pkg => `
    <div class="order-row">
      <label>
        <strong>${pkg.name}</strong>
        <small style="display:block;color:#888;font-weight:400">${pkg.total_pieces} kg per pakket</small>
      </label>
      <input type="number" id="qty-${pkg.id}" value="0" min="0" placeholder="Aantal" />
      <span style="color:#888;font-size:.85rem">pakketten</span>
    </div>
  `).join("");
}

// ─── Upload ─────────────────────────────────────────────────────────────────────────────
function setupDropZone() {
  const zone = document.getElementById("drop-zone");
  const input = document.getElementById("file-input");

  zone.addEventListener("dragover", e => { e.preventDefault(); zone.classList.add("drag-over"); });
  zone.addEventListener("dragleave", () => zone.classList.remove("drag-over"));
  zone.addEventListener("drop", e => {
    e.preventDefault();
    zone.classList.remove("drag-over");
    const file = e.dataTransfer.files[0];
    if (file) uploadFile(file);
  });
  input.addEventListener("change", () => { if (input.files[0]) uploadFile(input.files[0]); });
}

async function uploadFile(file) {
  const progress = document.getElementById("upload-progress");
  const result = document.getElementById("upload-result");
  const dropLabel = document.querySelector(".drop-label");

  dropLabel.classList.add("hidden");
  progress.classList.remove("hidden");
  result.innerHTML = "";

  const formData = new FormData();
  formData.append("file", file);

  try {
    const res = await fetch("/api/upload-price-list", { method: "POST", body: formData });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Upload mislukt");
    result.innerHTML = `<div class="info-box">✅ Prijslijst verwerkt: <strong>${data.products_parsed}</strong> producten gevonden.</div>`;
    await loadActiveList();
    await loadPackageTypes();
  } catch (e) {
    result.innerHTML = `<div class="info-box error">❌ Fout: ${e.message}</div>`;
  } finally {
    progress.classList.add("hidden");
    dropLabel.classList.remove("hidden");
  }
}

// ─── Calculate ────────────────────────────────────────────────────────────────────────────
async function calculate() {
  if (!activeList || !activeList.active) {
    alert("Upload eerst een prijslijst van vandaag.");
    return;
  }

  const order = packageTypes
    .map(pkg => ({ package_type_id: pkg.id, quantity: parseInt(document.getElementById(`qty-${pkg.id}`).value) || 0 }))
    .filter(o => o.quantity > 0);

  if (!order.length) {
    alert("Voer bij minimaal één pakketsoort een aantal in.");
    return;
  }

  const btn = document.getElementById("btn-calculate");
  btn.disabled = true;
  btn.textContent = "Berekenen…";

  try {
    const res = await fetch("/api/calculate", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(order),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.detail || "Berekening mislukt");
    renderResults(data);
    document.getElementById("section-results").classList.remove("hidden");
    document.getElementById("section-results").scrollIntoView({ behavior: "smooth" });
  } catch (e) {
    alert(`Fout: ${e.message}`);
  } finally {
    btn.disabled = false;
    btn.textContent = "Bereken goedkoopste inkoop";
  }
}

function renderResults(results) {
  const container = document.getElementById("results-container");
  container.innerHTML = results.map(r => {
    const warningsHtml = r.warnings?.length
      ? r.warnings.map(w => `<div class="warning-box">⚠️ ${w}</div>`).join("")
      : "";

    const rows = r.allocations.map(a => {
      const product = a.product;
      const plan = a.plan;
      const ppkg = a.price_per_kg != null ? `€ ${a.price_per_kg.toFixed(4)}/kg` : "onbekend";

      let inkoop = "";
      if (!product) {
        inkoop = `<span style="color:#c00">Geen product gevonden</span>`;
      } else if (!plan) {
        inkoop = product.description;
      } else {
        const unitLabel = plan.kg_per_unit === 1 ? "kg" : `${plan.kg_per_unit} kg`;
        const unitWord = plan.units === 1 ? "eenheid" : "eenheden";
        inkoop = `${product.description}<br><small>${plan.units} × ${unitLabel} = ${plan.actual_kg} kg`;
        if (plan.supplement) {
          const s = plan.supplement;
          inkoop += ` + ${s.kg} kg van <em>${s.product.description}</em> (€ ${s.cost.toFixed(2)})`;
        }
        inkoop += `</small>`;
      }

      const costPerPkg = plan ? (plan.total_cost / r.num_packages) : 0;

      return `
        <tr>
          <td class="best">${a.category_name}</td>
          <td>${inkoop}</td>
          <td>${a.pct}%</td>
          <td>${a.kg_per_package} kg</td>
          <td>${plan ? plan.actual_kg : a.kg_needed ?? "?"} kg</td>
          <td>${ppkg}</td>
          <td>€ ${costPerPkg.toFixed(2)}</td>
          <td>€ ${a.total_cost.toFixed(2)}</td>
        </tr>
      `;
    }).join("");

    return `
      <div class="result-block">
        <div class="result-header">
          <span>${r.package_name}</span>
          <span>${r.num_packages}× pakket</span>
        </div>
        ${warningsHtml}
        <table class="result-table">
          <thead>
            <tr>
              <th>Categorie</th>
              <th>Inkoop</th>
              <th>%</th>
              <th>Kg/pakket</th>
              <th>Totaal kg</th>
              <th>Prijs/kg</th>
              <th>Kosten/pakket</th>
              <th>Totaal</th>
            </tr>
          </thead>
          <tbody>${rows}</tbody>
        </table>
        <div class="result-total">
          <span>Per pakket: € ${r.total_cost_per_package.toFixed(2)}</span>
          <span>Totaal ${r.num_packages} pakketten: <strong>€ ${r.grand_total.toFixed(2)}</strong></span>
        </div>
      </div>
    `;
  }).join("");
}
