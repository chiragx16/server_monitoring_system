const REFRESH_INTERVAL = 5000;
const charts = {};
let downCount = 0;

// Configuration for time ranges in hours
const TIME_RANGES = {
    '5m': 5 / 60,   // 5 minutes in hours
    '10m': 10 / 60, // 10 minutes in hours
    '1h': 1,
    '3h': 3,
    '5h': 5,
    '24h': 24
};
// Map to store the currently selected time range for each server
const selectedTimeRanges = {};

/**
 * Sanitizes the server key (IP address) to be a valid CSS class name by replacing dots with underscores.
 * @param {string} key - The original server key (e.g., '10.1.1.25').
 * @returns {string} - The sanitized key (e.g., '10_1_1_25').
 */
function sanitizeKey(key) {
    return key.replace(/\./g, '_');
}

/**
 * Filters the server history based on the specified time duration (in hours, potentially fractional).
 * @param {Array<{time: string, status: string}>} history - The full history array.
 * @param {number} durationInHours - The duration of past time to filter for (e.g., 1 for 1 hour, 5/60 for 5 minutes).
 * @returns {Array<{time: Date, status: string}>} - The filtered history data with time converted to Date objects.
 */
function filterHistory(history, durationInHours) {
    if (!history || history.length === 0) return [];

    const cutoff = new Date();
    // Calculate milliseconds to subtract: durationInHours * 60 minutes/hour * 60 seconds/minute * 1000 ms/second
    const msToSubtract = durationInHours * 3600 * 1000;
    cutoff.setTime(cutoff.getTime() - msToSubtract);

    return history
        .map(h => ({
            ...h,
            // Convert the time string back to a Date object for comparison (assuming time is ISO string)
            time: new Date(h.time)
        }))
        .filter(h => h.time >= cutoff);
}


async function fetchStatus() {
    const response = await fetch('/api/status');
    return response.json();
}

function statusBadge(status) {
    if (status === 'up') {
        return 'bg-green-500 text-white status-up';
    }
    if (status === 'down') {
        return 'bg-red-500 text-white status-down';
    }
    return 'bg-gray-400 text-white';
}

function statusIcon(status) {
    if (status === 'up') {
        return 'fa-check-circle';
    }
    if (status === 'down') {
        return 'fa-exclamation-circle';
    }
    return 'fa-question-circle';
}

function statusColor(status) {
    if (status === 'up') {
        return 'text-green-600';
    }
    if (status === 'down') {
        return 'text-red-600';
    }
    return 'text-gray-600';
}

function createTimeRangeButtons(serverKey) {
    const safeKey = sanitizeKey(serverKey);
    // Use the value (duration in hours) for comparison in the template
    const currentDuration = selectedTimeRanges[serverKey] || 1;

    return `
        <div class="flex space-x-2 text-xs mb-4 p-1 bg-gray-100 rounded-lg">
            ${Object.entries(TIME_RANGES).map(([label, duration]) => `
                <button
                    data-duration="${duration}"
                    data-server-key="${serverKey}"
                    class="time-range-btn-${safeKey} px-2 py-1 rounded-md font-medium transition-colors duration-200
                        ${duration === currentDuration ? 'bg-indigo-600 text-white shadow-md' : 'text-gray-600 hover:bg-white'}
                    "
                >
                    ${label}
                </button>
            `).join('')}
        </div>
    `;
}

function createServerCard(serverKey, server) {
    // Set default time range if not set (default to 1 hour)
    if (!selectedTimeRanges[serverKey]) {
        selectedTimeRanges[serverKey] = 1;
    }

    const container = document.createElement('div');
    container.id = `server-${serverKey}`;
    container.className = `
        glass-effect rounded-xl shadow-lg p-5 server-card animate-slide-in
        hover:shadow-xl transition-all duration-300
    `;

    container.innerHTML = `
        <div class="flex justify-between items-center mb-4">
            <h2 class="text-xl font-bold text-gray-800 flex items-center">
                <i class="fas fa-server mr-2 text-indigo-600"></i>
                ${server.name}
            </h2>
            <div class="status-indicator relative">
                <span class="px-3 py-1 rounded-full text-sm font-semibold ${statusBadge(server.status)} flex items-center">
                    <i class="fas ${statusIcon(server.status)} mr-1"></i>
                    ${server.status.toUpperCase()}
                </span>
            </div>
        </div>

        <div class="space-y-3 mb-4">
            <div class="flex items-center text-sm">
                <i class="fas fa-network-wired mr-2 text-gray-500 w-5"></i>
                <span class="text-gray-600">Host:</span>
                <span class="font-mono ml-1 text-gray-800">${server.host}</span>
            </div>
            
            <div class="flex items-center text-sm">
                <i class="fas fa-clock mr-2 text-gray-500 w-5"></i>
                <span class="text-gray-600">Last check:</span>
                <span class="ml-1 last-check text-gray-800">${server.last_check}</span>
            </div>
            
            <div class="flex items-center text-sm">
                <i class="fas fa-chart-line mr-2 text-gray-500 w-5"></i>
                <span class="text-gray-600">Uptime:</span>
                <div class="ml-1 flex items-center">
                    <div class="w-24 bg-gray-200 rounded-full h-2 mr-2">
                        <div class="uptime-bar bg-${server.status === 'up' ? 'green' : 'red'}-500 h-2 rounded-full"></div>
                    </div>
                    <span class="uptime font-semibold ${statusColor(server.status)}">
                        ${server.uptime_percentage.toFixed(2)}%
                    </span>
                </div>
            </div>
        </div>

        <!-- Time Range Buttons -->
        ${createTimeRangeButtons(serverKey)}
        
        <div class="chart-container">
            <canvas id="chart-${serverKey}"></canvas>
        </div>
        
        <div class="mt-4 flex justify-end">
            <!-- Updated button to link to the new log details page -->
            <a href="/logs/${serverKey}" target="_blank" class="text-indigo-600 hover:text-indigo-800 text-sm font-medium flex items-center">
                <i class="fas fa-info-circle mr-1"></i>
                View Details (48h Logs)
            </a>
        </div>
    `;

    document.getElementById('servers').appendChild(container);

    // Attach event listeners for time range buttons
    const safeKey = sanitizeKey(serverKey);
    container.querySelectorAll(`.time-range-btn-${safeKey}`).forEach(button => {
        button.addEventListener('click', (e) => {
            // Use currentTarget to ensure we get the button element
            const btn = e.currentTarget;
            // Parse as float since we now use fractional hours
            const duration = parseFloat(btn.dataset.duration);
            const key = btn.dataset.serverKey;

            // Re-fetch the full data object to get the complete history
            fetchStatus().then(allData => {
                const currentServerData = allData[key];
                if (currentServerData) {
                    changeTimeRange(key, duration, currentServerData.history);
                }
            }).catch(error => console.error("Error fetching status for time change:", error));
        });
    });

    // Initial chart creation with filtered data
    const initialDuration = selectedTimeRanges[serverKey];
    const initialHistory = filterHistory(server.history, initialDuration);
    createChart(serverKey, initialHistory);
}

function updateServerCard(serverKey, server) {
    const card = document.getElementById(`server-${serverKey}`);
    if (!card) {
        createServerCard(serverKey, server);
        return;
    }

    // Add animation class
    card.classList.add('animate-pulse-once');
    setTimeout(() => {
        card.classList.remove('animate-pulse-once');
    }, 1000);

    // Update status badge
    const badge = card.querySelector('.status-indicator span');
    badge.className = `px-3 py-1 rounded-full text-sm font-semibold ${statusBadge(server.status)} flex items-center`;
    badge.innerHTML = `
    <i class="fas ${statusIcon(server.status)} mr-1"></i>
    <span>${server.status.toUpperCase()}</span>
`;


    // Update other elements
    card.querySelector('.last-check').textContent = server.last_check;
    card.querySelector('.uptime').textContent = server.uptime_percentage.toFixed(2) + '%';
    card.querySelector('.uptime').className = `uptime font-semibold ${statusColor(server.status)}`;

    // Update progress bar
    const progressBar = card.querySelector('.uptime-bar');
    progressBar.className = `uptime-bar h-2 rounded-full bg-${server.status === 'up' ? 'green' : 'red'}-500`;

    // Update chart with data filtered by current selection
    const currentDuration = selectedTimeRanges[serverKey] || 1;
    const filteredHistory = filterHistory(server.history, currentDuration);
    updateChart(serverKey, filteredHistory);
}


/**
 * Handles the selection of a new time range for the chart.
 * @param {string} serverKey - The key of the server.
 * @param {number} duration - The new time range duration in hours (potentially fractional).
 * @param {Array<object>} fullHistory - The complete, unfiltered history (needed for re-filtering).
 */
function changeTimeRange(serverKey, duration, fullHistory) {
    selectedTimeRanges[serverKey] = duration;

    // 1. Update button styling
    const card = document.getElementById(`server-${serverKey}`);
    const safeKey = sanitizeKey(serverKey);
    card.querySelectorAll(`.time-range-btn-${safeKey}`).forEach(btn => {
        // Parse as float since we now use fractional hours
        const btnDuration = parseFloat(btn.dataset.duration);

        // Clean up classes for all buttons
        btn.classList.remove('bg-indigo-600', 'text-white', 'shadow-md');
        btn.classList.add('text-gray-600', 'hover:bg-white');

        // Apply selected classes to the current button
        if (btnDuration === duration) {
            btn.classList.remove('text-gray-600', 'hover:bg-white');
            btn.classList.add('bg-indigo-600', 'text-white', 'shadow-md');
        }
    });

    // 2. Filter data and update chart
    const filteredHistory = filterHistory(fullHistory, duration);
    updateChart(serverKey, filteredHistory);
}

/**
 * Gets a human-readable label for the selected time range.
 * @param {string} serverKey - The key of the server.
 * @returns {string} - The label (e.g., '1h', '5m').
 */
function getDurationLabel(serverKey) {
    const duration = selectedTimeRanges[serverKey] || 1;
    const entry = Object.entries(TIME_RANGES).find(([label, value]) => value === duration);
    return entry ? entry[0] : `${(duration * 60).toFixed(0)}m`; // Fallback to minutes if fractional
}


function createChart(serverKey, history) {
    const ctx = document.getElementById(`chart-${serverKey}`).getContext('2d');

    // Function to format the labels for the X axis
    const getLabels = (h) => {
        // If history is short (e.g., less than 10 points), use index for simplicity
        if (h.length < 10) return h.map((_, i) => i + 1);
        // Otherwise, use a simplified time format (e.g., HH:MM)
        return h.map(item => item.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    };

    charts[serverKey] = new Chart(ctx, {
        type: 'line',
        data: {
            labels: getLabels(history),
            datasets: [{
                label: `Uptime History (Past ${getDurationLabel(serverKey)})`,
                data: history.map(h => h.status === 'up' ? 1 : 0),
                borderColor: '#6366f1',
                backgroundColor: 'rgba(99, 102, 241, 0.1)',
                borderWidth: 2,
                tension: 0.3,
                pointRadius: 3,
                pointBackgroundColor: history.map(h => h.status === 'up' ? '#10b981' : '#ef4444'),
                pointBorderColor: '#fff',
                pointBorderWidth: 1,
            }]
        },
        options: {
            responsive: true,
            maintainAspectRatio: false,
            animation: {
                duration: 500 // Smooth transition on update
            },
            scales: {
                y: {
                    min: -0.1,   // little below 0
                    max: 1.1,    // little above 1
                    ticks: {
                        callback: v => v >= 1 ? 'UP' : 'DOWN',
                        stepSize: 1
                    },
                    grid: {
                        display: true,
                        color: 'rgba(0, 0, 0, 0.05)'
                    }
                },
                x: {
                    type: 'category',
                    ticks: {
                        autoSkip: true,
                        maxTicksLimit: 6,
                        font: { size: 10 }
                    },
                    grid: {
                        display: false
                    }
                }
            },
            plugins: {
                legend: { display: false },
                tooltip: {
                    callbacks: {
                        title: function (context) {
                            // Show the time label, or index if time not available
                            return context[0].label || `Point ${context[0].dataIndex + 1}`;
                        },
                        label: function (context) {
                            return context.parsed.y === 1 ? 'Status: UP' : 'Status: DOWN';
                        }
                    }
                }
            }
        }
    });
}

function updateChart(serverKey, history) {
    const chart = charts[serverKey];
    if (!chart) return;

    // Function to format the labels for the X axis
    const getLabels = (h) => {
        // If history is short (e.g., less than 10 points), use index for simplicity
        if (h.length < 10) return h.map((_, i) => i + 1);
        // Otherwise, use a simplified time format (e.g., HH:MM)
        return h.map(item => item.time.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' }));
    };

    chart.data.labels = getLabels(history);
    chart.data.datasets[0].data = history.map(h => h.status === 'up' ? 1 : 0);
    chart.data.datasets[0].pointBackgroundColor = history.map(h => h.status === 'up' ? '#10b981' : '#ef4444');
    chart.data.datasets[0].label = `Uptime History (Past ${getDurationLabel(serverKey)})`;
    chart.update();
}

function updateStats(data) {
    const servers = Object.values(data);
    const totalServers = servers.length;
    const onlineServers = servers.filter(s => s.status === 'up').length;
    const offlineServers = servers.filter(s => s.status === 'down').length;
    const avgUptime = servers.reduce((sum, s) => sum + s.uptime_percentage, 0) / totalServers;

    document.getElementById('totalServers').textContent = totalServers;
    document.getElementById('onlineServers').textContent = onlineServers;
    document.getElementById('offlineServers').textContent = offlineServers;
    document.getElementById('avgUptime').textContent = avgUptime.toFixed(2) + '%';

    // Update notification badge
    const notificationBadge = document.getElementById('notificationBadge');
    if (offlineServers > 0) {
        notificationBadge.textContent = offlineServers;
        notificationBadge.classList.remove('hidden');
    } else {
        notificationBadge.classList.add('hidden');
    }

    // Track down servers count for animation
    if (offlineServers > downCount) {
        document.getElementById('notificationBtn').classList.add('animate-pulse-once');
        setTimeout(() => {
            document.getElementById('notificationBtn').classList.remove('animate-pulse-once');
        }, 1000);
    }
    downCount = offlineServers;
}

function updateTime() {
    const now = new Date();
    document.getElementById('currentTime').textContent = now.toLocaleTimeString();
}

function updateLastRefresh() {
    const now = new Date();
    document.getElementById('lastRefresh').textContent = `Last refresh: ${now.toLocaleTimeString()}`;
}

async function refreshDashboard() {
    const data = await fetchStatus();
    Object.entries(data).forEach(([key, server]) => {
        updateServerCard(key, server);
    });
    updateStats(data);
    updateLastRefresh();
}

// Initialize
document.addEventListener('DOMContentLoaded', () => {
    // Set up manual refresh button
    document.getElementById('refreshBtn').addEventListener('click', () => {
        refreshDashboard();
        document.getElementById('refreshBtn').querySelector('i').classList.add('fa-spin');
        setTimeout(() => {
            document.getElementById('refreshBtn').querySelector('i').classList.remove('fa-spin');
        }, 1000);
    });

    // Update time every second
    updateTime();
    setInterval(updateTime, 1000);

    // Initial load
    refreshDashboard();

    // Set up auto-refresh
    setInterval(refreshDashboard, REFRESH_INTERVAL);
});