// ─── State ───────────────────────────────────────────────────────────────────────────────
let categories = [];
let packageTypes = [];
let allProducts = [];

// ─── Init ────────────────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", async () => {
  await Promise.all([loadCategories(), loadPackageTypes(), loadProducts(), loadHistory()]);
});

// ─── Tabs ────────────────────────────────────────────────────────────────────────────────
function showTab(tabId) {
  document.querySelectorAll(".tab-content").forEach(el => el.classList.add("hidden"));
  document.querySelectorAll(".tab-btn").forEach(el => el.classList.remove("active"));
  document.getElementById(tabId).classList.remove("hidden");
  event.target.classList.add("active");
}

// ─── Categories ─────────────────────────────────────────────────────────────────────────────
async function loadCategories() {
  const res = await fetch("/api/categories");
  categories = await res.json();
  renderCategories();
  populateCatFilter();
}

function renderCategories() {
  const container = document.getElementById("categories-list");
  if (!categories.length) {
    container.innerHTML = '<p class="hint">Geen categorieën.</p>';
    return;
  }
  container.innerHTML = categories.map(c => `
    <div class="cat-item">
      <div class="cat-item-info">
        <strong>${c.name}</strong>
        <div class="cat-keywords">Zoekwoorden: ${c.keywords.join(", ") || "—"}</div>
      </div>
      <button class="btn-secondary" onclick="editCategory(${c.id})">Bewerken</button>
      <button class="btn-danger" onclick="deleteCategory(${c.id})">Verwijder</button>
    </div>
  `).join("");
}

function showCategoryForm(cat) {
  document.getElementById("category-form").classList.remove("hidden");
  if (cat) {
    document.getElementById("cat-form-title").textContent = "Categorie bewerken";
    document.getElementById("cat-id").value = cat.id;
    document.getElementById("cat-name").value = cat.name;
    document.getElementById("cat-keywords").value = cat.keywords.join(", ");
  } else {
    document.getElementById("cat-form-title").textContent = "Nieuwe categorie";
    document.getElementById("cat-id").value = "";
    document.getElementById("cat-name").value = "";
    document.getElementById("cat-keywords").value = "";
  }
}

function editCategory(id) {
  const cat = categories.find(c => c.id === id);
  if (cat) showCategoryForm(cat);
}

function cancelCategoryForm() {
  document.getElementById("category-form").classList.add("hidden");
}

async function saveCategory() {
  const id = document.getElementById("cat-id").value;
  const name = document.getElementById("cat-name").value.trim();
  const keywords = document.getElementById("cat-keywords").value
    .split(",").map(s => s.trim()).filter(Boolean);

  if (!name) { alert("Vul een naam in."); return; }

  const url = id ? `/api/categories/${id}` : "/api/categories";
  const method = id ? "PUT" : "POST";
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, keywords }),
  });
  if (!res.ok) { alert("Opslaan mislukt."); return; }
  cancelCategoryForm();
  await loadCategories();
}

async function deleteCategory(id) {
  if (!confirm("Weet je zeker dat je deze categorie wilt verwijderen?")) return;
  await fetch(`/api/categories/${id}`, { method: "DELETE" });
  await loadCategories();
}

// ─── Package types ────────────────────────────────────────────────────────────────────────────
async function loadPackageTypes() {
  const res = await fetch("/api/package-types");
  packageTypes = await res.json();
  renderPackages();
}

function renderPackages() {
  const container = document.getElementById("packages-list");
  if (!packageTypes.length) {
    container.innerHTML = '<p class="hint">Geen pakketsoorten.</p>';
    return;
  }
  container.innerHTML = packageTypes.map(pkg => {
    const reqBadges = (pkg.requirements || []).map(r => {
      const rest = r.max_pct >= 100 ? "rest" : `${r.min_pct}–${r.max_pct}%`;
      return `<span class="req-badge">${r.category_name}: ${rest}</span>`;
    }).join("");
    return `
      <div class="pkg-item">
        <div class="pkg-item-info">
          <strong>${pkg.name}</strong>
          <small style="color:#888;display:block;margin:2px 0">${pkg.total_pieces} kg per pakket</small>
          <div class="pkg-reqs">${reqBadges}</div>
        </div>
        <div class="pkg-item-actions">
          <button class="btn-secondary" onclick="editPackage(${pkg.id})">Bewerken</button>
          <button class="btn-danger" onclick="deletePackage(${pkg.id})">Verwijder</button>
        </div>
      </div>
    `;
  }).join("");
}

function showPackageForm(pkg) {
  document.getElementById("package-form").classList.remove("hidden");
  const reqs = document.getElementById("pkg-requirements");
  if (pkg) {
    document.getElementById("pkg-form-title").textContent = "Pakket bewerken";
    document.getElementById("pkg-id").value = pkg.id;
    document.getElementById("pkg-name").value = pkg.name;
    document.getElementById("pkg-total").value = pkg.total_pieces;
    reqs.innerHTML = "";
    (pkg.requirements || []).forEach(r => addRequirement(r));
  } else {
    document.getElementById("pkg-form-title").textContent = "Nieuw pakket";
    document.getElementById("pkg-id").value = "";
    document.getElementById("pkg-name").value = "";
    document.getElementById("pkg-total").value = 25;
    reqs.innerHTML = "";
  }
}

function editPackage(id) {
  const pkg = packageTypes.find(p => p.id === id);
  if (pkg) showPackageForm(pkg);
}

function cancelPackageForm() {
  document.getElementById("package-form").classList.add("hidden");
}

function addRequirement(existing) {
  const container = document.getElementById("pkg-requirements");
  const catOptions = categories.map(c =>
    `<option value="${c.id}" ${existing && existing.category_id === c.id ? "selected" : ""}>${c.name}</option>`
  ).join("");

  const div = document.createElement("div");
  div.className = "req-row";
  div.innerHTML = `
    <div>
      <label>Categorie</label>
      <select class="req-cat">${catOptions}</select>
    </div>
    <div>
      <label>Min %</label>
      <input type="number" class="req-min" value="${existing ? existing.min_pct : 0}" min="0" max="100" />
    </div>
    <div>
      <label>Max %</label>
      <input type="number" class="req-max" value="${existing ? existing.max_pct : 100}" min="0" max="100" />
    </div>
    <div>
      <label>Is "rest"</label>
      <input type="checkbox" class="req-rest" ${existing && existing.max_pct >= 100 && existing.min_pct === 0 ? "checked" : ""} title="Vul aan tot 100%" />
    </div>
    <button class="btn-danger" onclick="this.parentElement.remove()">x</button>
  `;
  container.appendChild(div);
}

async function savePackage() {
  const id = document.getElementById("pkg-id").value;
  const name = document.getElementById("pkg-name").value.trim();
  const totalKg = parseFloat(document.getElementById("pkg-total").value) || 25;

  if (!name) { alert("Vul een naam in."); return; }

  const reqRows = document.querySelectorAll("#pkg-requirements .req-row");
  const requirements = Array.from(reqRows).map(row => ({
    category_id: parseInt(row.querySelector(".req-cat").value),
    min_pct: row.querySelector(".req-rest").checked ? 0 : parseInt(row.querySelector(".req-min").value),
    max_pct: row.querySelector(".req-rest").checked ? 100 : parseInt(row.querySelector(".req-max").value),
  }));

  const url = id ? `/api/package-types/${id}` : "/api/package-types";
  const method = id ? "PUT" : "POST";
  const res = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, total_pieces: totalKg, requirements }),
  });
  if (!res.ok) { alert("Opslaan mislukt."); return; }
  cancelPackageForm();
  await loadPackageTypes();
}

async function deletePackage(id) {
  if (!confirm("Weet je zeker dat je dit pakketsoort wilt verwijderen?")) return;
  await fetch(`/api/package-types/${id}`, { method: "DELETE" });
  await loadPackageTypes();
}

// ─── Products ─────────────────────────────────────────────────────────────────────────────
async function loadProducts() {
  const res = await fetch("/api/price-list/active");
  const data = await res.json();
  allProducts = data.products || [];
  renderProducts();
}

function populateCatFilter() {
  const sel = document.getElementById("product-cat-filter");
  if (!sel) return;
  const existing = Array.from(sel.options).map(o => o.value);
  categories.forEach(c => {
    if (!existing.includes(String(c.id))) {
      const opt = document.createElement("option");
      opt.value = c.id;
      opt.textContent = c.name;
      sel.appendChild(opt);
    }
  });
}

function renderProducts() {
  const container = document.getElementById("products-table-container");
  const filterCat = document.getElementById("product-cat-filter")?.value;
  const filterText = document.getElementById("product-search")?.value.toLowerCase() || "";

  let products = allProducts;
  if (filterCat) products = products.filter(p => String(p.category_id) === filterCat);
  if (filterText) products = products.filter(p => p.description.toLowerCase().includes(filterText));

  if (!products.length) {
    container.innerHTML = '<p class="hint">Geen producten gevonden.</p>';
    return;
  }

  container.innerHTML = `
    <table class="product-table">
      <thead>
        <tr>
          <th>Omschrijving</th>
          <th>Inhoud</th>
          <th>Prijs</th>
          <th>Eenheid</th>
          <th>Categorie</th>
          <th>Prijs/kg</th>
          <th>Grammen/stuk</th>
          <th>Actie</th>
        </tr>
      </thead>
      <tbody>
        ${products.map(p => {
          const catName = categories.find(c => c.id === p.category_id)?.name || "—";
          const ppkg = p.price_per_piece != null ? `€ ${p.price_per_piece.toFixed(4)}` : "—";
          return `
            <tr id="prod-row-${p.id}">
              <td>${p.description}</td>
              <td>${p.content || "—"}</td>
              <td>€ ${p.price?.toFixed(2) ?? "—"}</td>
              <td>${p.price_unit || "—"}</td>
              <td>
                <select onchange="updateProductCat(${p.id}, this.value)">
                  <option value="">Geen</option>
                  ${categories.map(c => `<option value="${c.id}" ${c.id === p.category_id ? "selected" : ""}>${c.name}</option>`).join("")}
                </select>
              </td>
              <td>${ppkg}</td>
              <td>
                <input type="number" style="width:70px" placeholder="gram" value="" 
                  onchange="updateProductGrams(${p.id}, this.value)" />
              </td>
              <td><button class="btn-secondary" onclick="saveProductRow(${p.id})">Opslaan</button></td>
            </tr>
          `;
        }).join("")}
      </tbody>
    </table>
  `;
}

async function updateProductCat(id, catId) {}
async function updateProductGrams(id, grams) {}

async function saveProductRow(id) {
  const row = document.getElementById(`prod-row-${id}`);
  const catId = parseInt(row.querySelector("select").value) || null;
  const grams = parseFloat(row.querySelector('input[type=number]').value) || null;
  const res = await fetch(`/api/products/${id}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ category_id: catId, grams_per_piece: grams }),
  });
  if (res.ok) {
    const data = await res.json();
    await loadProducts();
  } else {
    alert("Opslaan mislukt.");
  }
}

// ─── History ─────────────────────────────────────────────────────────────────────────────
async function loadHistory() {
  const res = await fetch("/api/price-lists");
  const lists = await res.json();
  const container = document.getElementById("history-list");
  if (!lists.length) {
    container.innerHTML = '<p class="hint">Nog geen prijslijsten geüpload.</p>';
    return;
  }
  container.innerHTML = lists.map(u => `
    <div class="history-item ${u.active ? "active" : ""}">
      <div>
        <strong>${u.filename}</strong>
        <small style="display:block;color:#888">${new Date(u.upload_date).toLocaleString("nl-NL")}</small>
      </div>
      <div style="display:flex;gap:8px;align-items:center">
        ${u.active ? '<span class="badge-active">Actief</span>' : `<button class="btn-secondary" onclick="activateList(${u.id})">Activeren</button>`}
      </div>
    </div>
  `).join("");
}

async function activateList(id) {
  await fetch(`/api/price-lists/${id}/activate`, { method: "POST" });
  await loadHistory();
  await loadProducts();
}
