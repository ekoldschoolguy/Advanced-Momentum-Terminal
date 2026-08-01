let screenerData = [];
let universes = {};
let currentSort = { column: 'cms', asc: false };
let allWatchlists = [];

const BROAD_INDICES = ["Nifty 500", "Nifty 200", "Nifty Midcap Select", "Nifty Microcap 250"];

async function fetchUniverses() {
    try {
        const response = await fetch('/api/universes');
        const res = await response.json();
        if (res.status === 'success') {
            universes = res.data;
            const select = document.getElementById('universe');
            for (const name in universes) {
                if (universes[name].length > 0) {
                    const option = document.createElement('option');
                    option.value = name;
                    option.textContent = name;
                    select.appendChild(option);
                }
            }
        }
    } catch (err) {
        console.error("Failed to load universes", err);
    }
}

function formatNumber(num, decimals = 2) {
    if (num === null || num === undefined || isNaN(num)) return '—';
    return Number(num).toFixed(decimals);
}

function formatPercent(num) {
    if (num === null || num === undefined || isNaN(num)) return '—';
    const prefix = num > 0 ? '+' : '';
    return prefix + Number(num).toFixed(2) + '%';
}

function getColorClass(num) {
    if (num === null || num === undefined || isNaN(num)) return '';
    return num > 0 ? 'positive' : (num < 0 ? 'negative' : '');
}

function getSector(symbol) {
    let matchedSectors = [];
    for (const name in universes) {
        if (!BROAD_INDICES.includes(name) && universes[name].includes(symbol)) {
            matchedSectors.push(name.replace(/Nifty /gi, "").replace(/NIFTY /gi, ""));
        }
    }
    return matchedSectors.length > 0 ? matchedSectors.join(", ") : "—";
}

function renderTable(data) {
    const tbody = document.getElementById('screener-body');
    tbody.innerHTML = '';

    const searchTerm = document.getElementById('table-search').value.toLowerCase();
    const universeFilter = document.getElementById('universe').value;
    const mtfFilter = document.getElementById('mtf-filter').value;
    let validSymbols = null;
    
    if (universeFilter !== 'All' && universes[universeFilter]) {
        validSymbols = new Set(universes[universeFilter]);
    }

    let rankIndex = 1;

    data.forEach(row => {
        if (searchTerm && !row.symbol.toLowerCase().includes(searchTerm) && !row.name.toLowerCase().includes(searchTerm)) {
            return;
        }
        
        if (validSymbols && !validSymbols.has(row.symbol)) {
            return;
        }

        if (mtfFilter === 'MTF' && !row.mtf_eligible) {
            return;
        }

        const tr = document.createElement('tr');
        tr.onclick = () => {
            // Open chart for this symbol in the RS engine UI
            window.open(`/rs_ui?symbol=${row.symbol}`, '_blank');
        };

        tr.innerHTML = `
            <td class="text-left">
                <div class="symbol-cell">
                    <span style="color: var(--text-muted); font-size: 12px; width: 24px; display: inline-block; text-align: right; padding-right: 8px;">${rankIndex}</span>
                    <div class="symbol-icon">${row.symbol.charAt(0)}</div>
                    <div class="symbol-info">
                        <span class="symbol-name">${row.symbol} <span class="cms-badge">CMS: ${formatNumber(row.cms, 1)}</span></span>
                        <span class="company-name">${row.name || row.instrument_key}</span>
                    </div>
                </div>
            </td>
            <td class="text-left" style="color: var(--text-primary); font-weight: 500; font-size: 12px;">${row.sector}</td>
            <td>${formatNumber(row.price)}</td>
            <td style="color: var(--text-primary); font-weight: 500;">${row.mcap_cr > 0 ? '₹' + formatNumber(row.mcap_cr) + ' Cr' : '—'}</td>
            <td style="color: var(--text-primary); font-weight: 500;">${row.mtf_eligible ? '₹' + Number(row.mtf_amt).toFixed(1) + ' Cr' : '—'}</td>
            <td style="color: var(--accent-blue); font-weight: 600;">${row.mtf_eligible && row.mtf_pct_mcap ? Number(row.mtf_pct_mcap).toFixed(2) + '%' : '—'}</td>
            <td style="color: #ffca28; font-weight: 600;">${formatNumber(row.cms, 1)}</td>
            <td class="${getColorClass(row.rs_1w)}">${formatPercent(row.rs_1w)}</td>
            <td class="${getColorClass(row.rs_1m)}">${formatPercent(row.rs_1m)}</td>
            <td class="${getColorClass(row.rs_3m)}">${formatPercent(row.rs_3m)}</td>
            <td class="${getColorClass(row.rs_6m)}">${formatPercent(row.rs_6m)}</td>
            <td class="${getColorClass(row.rs_ytd)}">${formatPercent(row.rs_ytd)}</td>
            <td class="${getColorClass(row.rs_1y)}">${formatPercent(row.rs_1y)}</td>
            <td style="text-align: center">
                <button class="btn-add-wl" onclick="event.stopPropagation(); showWatchlistMenu(event, '${row.symbol}', '${row.instrument_key}')">＋</button>
            </td>
        `;
        tbody.appendChild(tr);
        rankIndex++;
    });
}

function sortData(column) {
    if (currentSort.column === column) {
        currentSort.asc = !currentSort.asc;
    } else {
        currentSort.column = column;
        currentSort.asc = false; // default descending for metrics
    }

    // Update headers
    document.querySelectorAll('th').forEach(th => {
        th.classList.remove('sort-asc', 'sort-desc');
        if (th.dataset.sort === column) {
            th.classList.add(currentSort.asc ? 'sort-asc' : 'sort-desc');
        }
    });

    screenerData.sort((a, b) => {
        let valA = a[column];
        let valB = b[column];

        if (valA === null) valA = -999999;
        if (valB === null) valB = -999999;

        if (typeof valA === 'string') {
            return currentSort.asc ? valA.localeCompare(valB) : valB.localeCompare(valA);
        }

        return currentSort.asc ? valA - valB : valB - valA;
    });

    renderTable(screenerData);
}

async function fetchScreenerData() {
    const index = document.getElementById('index').value;
    const loader = document.getElementById('loader');
    
    loader.style.display = 'flex';
    document.getElementById('screener-body').innerHTML = '';

    try {
        const response = await fetch(`/api/rs/screener?index=${encodeURIComponent(index)}`);
        const res = await response.json();

        if (res.status === 'error') {
            throw new Error(res.message);
        }

        screenerData = res.data.map(row => {
            if (!row.sector || row.sector === '—') {
                row.sector = getSector(row.symbol);
            }
            return row;
        });
        // Initial sort by RS 3M Descending
        sortData('rs_3m');
        
    } catch (err) {
        alert(`Error fetching screener data: ${err.message}`);
    } finally {
        loader.style.display = 'none';
    }
}

// Event Listeners
document.getElementById('scan-btn').addEventListener('click', fetchScreenerData);

document.getElementById('table-search').addEventListener('input', () => {
    renderTable(screenerData);
});

document.getElementById('universe').addEventListener('change', () => {
    renderTable(screenerData);
});

document.querySelectorAll('th[data-sort]').forEach(th => {
    th.addEventListener('click', () => {
        sortData(th.dataset.sort);
    });
});

// Add URL parameter support for RS UI
const urlParams = new URLSearchParams(window.location.search);
if (urlParams.has('symbol') && document.getElementById('target')) {
    document.getElementById('target').value = urlParams.get('symbol');
}

// Watchlist Functions
async function loadWatchlists() {
    try {
        const response = await fetch('/api/watchlist');
        const res = await response.json();
        if (res.status === 'success') {
            allWatchlists = res.data;
        }
    } catch (err) {
        console.error("Failed to load watchlists", err);
    }
}

function showWatchlistMenu(event, symbol, instrumentKey) {
    const menu = document.getElementById('watchlist-ctx-menu');
    if (!menu) return;

    if (allWatchlists.length === 0) {
        alert("No watchlists found. Please create one in the Watchlist Manager page first!");
        return;
    }

    menu.innerHTML = '';
    
    // Add header
    const header = document.createElement('div');
    header.style.padding = '6px 12px 4px 12px';
    header.style.fontSize = '10px';
    header.style.color = 'var(--text-muted)';
    header.style.fontWeight = '700';
    header.style.textTransform = 'uppercase';
    header.textContent = `Add ${symbol} to:`;
    menu.appendChild(header);

    allWatchlists.forEach(w => {
        const item = document.createElement('div');
        item.className = 'watchlist-dropdown-item';
        item.textContent = w.name;
        item.onclick = async (e) => {
            e.stopPropagation();
            menu.style.display = 'none';
            await addToWatchlist(w.id, symbol, instrumentKey, w.name);
        };
        menu.appendChild(item);
    });

    // Position menu near the button
    menu.style.display = 'block';
    
    // Adjust positioning based on scroll coordinates
    const buttonRect = event.target.getBoundingClientRect();
    menu.style.top = `${buttonRect.bottom + window.scrollY + 4}px`;
    menu.style.left = `${buttonRect.left + window.scrollX - 120}px`;
}

async function addToWatchlist(watchlistId, symbol, instrumentKey, listName) {
    try {
        const response = await fetch(`/api/watchlist/${watchlistId}/items`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ symbol: symbol, instrument_key: instrumentKey })
        });
        const res = await response.json();
        if (res.status === 'success') {
            showToast(`Added ${symbol} to "${listName}"`);
        } else {
            showToast(res.message || "Failed to add stock", true);
        }
    } catch (err) {
        showToast("Error adding stock: " + err, true);
    }
}

function showToast(msg, isError = false) {
    const toast = document.getElementById('toast');
    if (!toast) return;
    toast.textContent = msg;
    toast.style.borderLeftColor = isError ? 'var(--accent-red)' : 'var(--accent-green)';
    toast.style.display = 'block';
    setTimeout(() => {
        toast.style.display = 'none';
    }, 3000);
}

// Close watchlist menu on clicking outside
document.addEventListener('click', (e) => {
    const menu = document.getElementById('watchlist-ctx-menu');
    if (menu && menu.style.display === 'block') {
        if (!menu.contains(e.target) && !e.target.classList.contains('btn-add-wl')) {
            menu.style.display = 'none';
        }
    }
});

async function fetchMtfSummary() {
    try {
        const response = await fetch('/api/rs/mtf/summary');
        const res = await response.json();
        if (res.status === 'success' && res.data && res.data.length > 0) {
            const sorted = res.data.sort((a, b) => new Date(a.date) - new Date(b.date));
            const latest = sorted[sorted.length - 1];
            
            document.getElementById('mtf-total-book').textContent = `₹${latest.outstanding_crores.toFixed(1)} Cr`;
            document.getElementById('mtf-fresh-exposure').textContent = `₹${latest.added_crores.toFixed(1)} Cr`;
            document.getElementById('mtf-liquidations').textContent = `₹${latest.liquidated_crores.toFixed(1)} Cr`;
        } else {
            document.getElementById('mtf-total-book').textContent = '—';
            document.getElementById('mtf-fresh-exposure').textContent = '—';
            document.getElementById('mtf-liquidations').textContent = '—';
        }
    } catch (err) {
        console.warn("Failed to fetch MTF summary stats:", err);
        document.getElementById('mtf-total-book').textContent = '—';
        document.getElementById('mtf-fresh-exposure').textContent = '—';
        document.getElementById('mtf-liquidations').textContent = '—';
    }
}

document.getElementById('mtf-filter').addEventListener('change', () => {
    renderTable(screenerData);
});

// Initial fetch
fetchUniverses().then(() => {
    loadWatchlists();
    fetchMtfSummary();
    setTimeout(fetchScreenerData, 500);
});
