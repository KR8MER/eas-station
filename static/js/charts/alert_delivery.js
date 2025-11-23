(function (window) {
    'use strict';

    // Track chart instances for cleanup
    const chartInstances = {};

    function resolveSeries(entries) {
        const labels = [];
        const delivered = [];
        const missed = [];
        const delayed = [];
        const tooltipData = [];

        entries.forEach((entry) => {
            const total = entry.total || 0;
            const deliveredCount = entry.delivered || 0;
            const delayedCount = entry.delayed || 0;
            const missedCount = Math.max(total - deliveredCount, 0);
            labels.push(entry.label || 'Unknown');
            delivered.push(deliveredCount);
            missed.push(missedCount);
            delayed.push(delayedCount);
            tooltipData.push(entry);
        });

        return { labels, delivered, missed, delayed, tooltipData };
    }

    function renderChart(containerId, entries) {
        if (!window.Chart) {
            console.warn('Chart.js is not available; skipping chart render for', containerId);
            return;
        }

        const target = document.getElementById(containerId);
        if (!target) {
            return;
        }

        // Destroy existing chart if present
        if (chartInstances[containerId]) {
            chartInstances[containerId].destroy();
            delete chartInstances[containerId];
        }

        const series = resolveSeries(entries);
        if (series.labels.length === 0) {
            target.innerHTML = '<p class="text-muted mb-0">No data available for this chart.</p>';
            return;
        }

        // Clear container and create canvas
        target.innerHTML = '';
        const canvas = document.createElement('canvas');
        target.appendChild(canvas);

        // Create Chart.js stacked bar chart
        chartInstances[containerId] = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: series.labels,
                datasets: [
                    {
                        label: 'Delivered',
                        data: series.delivered,
                        backgroundColor: '#28a745',
                        borderWidth: 0
                    },
                    {
                        label: 'Missed',
                        data: series.missed,
                        backgroundColor: '#dc3545',
                        borderWidth: 0
                    }
                ]
            },
            options: {
                responsive: true,
                maintainAspectRatio: false,
                plugins: {
                    legend: {
                        display: true,
                        labels: {
                            color: 'var(--text-color, #212529)'
                        }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: 'rgba(255, 255, 255, 0.95)',
                        titleColor: '#212529',
                        bodyColor: '#212529',
                        borderColor: '#dee2e6',
                        borderWidth: 1,
                        callbacks: {
                            title: function(context) {
                                return context[0].label;
                            },
                            afterBody: function(context) {
                                const pointIndex = context[0].dataIndex;
                                const entry = series.tooltipData[pointIndex] || {};
                                const rate = entry.delivery_rate != null ? entry.delivery_rate.toFixed(1) + '%' : '—';
                                const latency = entry.average_latency_seconds != null ? entry.average_latency_seconds.toFixed(1) + ' s' : '—';
                                const delayed = entry.delayed || 0;

                                return [
                                    '',
                                    `Delivery Rate: ${rate}`,
                                    `Avg Latency: ${latency}`,
                                    `Delayed Alerts: ${delayed}`
                                ];
                            }
                        }
                    }
                },
                scales: {
                    x: {
                        stacked: true,
                        ticks: {
                            color: 'var(--text-color, #212529)'
                        },
                        grid: {
                            display: false
                        }
                    },
                    y: {
                        stacked: true,
                        beginAtZero: true,
                        title: {
                            display: true,
                            text: 'Alerts',
                            color: 'var(--text-color, #212529)'
                        },
                        ticks: {
                            color: 'var(--text-color, #212529)'
                        },
                        grid: {
                            color: 'rgba(0, 0, 0, 0.05)'
                        }
                    }
                }
            }
        });
    }

    function render(config) {
        const originators = Array.isArray(config.originators) ? config.originators : [];
        const stations = Array.isArray(config.stations) ? config.stations : [];

        renderChart('alert-originator-chart', originators);
        renderChart('alert-station-chart', stations);
    }

    window.AlertVerificationCharts = {
        render
    };
})(window);
