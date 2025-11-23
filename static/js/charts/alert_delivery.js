(function (window) {
    'use strict';

    // Track chart instances for cleanup
    const chartInstances = {};

    /**
     * Get theme-aware colors for charts
     * Reads CSS custom properties to adapt to current theme
     */
    function getThemeColors() {
        const root = document.documentElement;
        const style = getComputedStyle(root);
        const isDarkMode = root.getAttribute('data-theme-mode') === 'dark';

        const getColor = (varName, lightFallback, darkFallback) => {
            const value = style.getPropertyValue(varName).trim();
            return value || (isDarkMode ? darkFallback : lightFallback);
        };

        return {
            text: getColor('--text-color', '#212529', '#ffffff'),
            textSecondary: getColor('--text-secondary', '#5a6c8f', '#d5deed'),
            textMuted: getColor('--text-muted', '#8892a6', '#a8b4cc'),
            border: getColor('--border-color', '#dee2e6', '#38465a'),
            gridLines: isDarkMode ? 'rgba(255, 255, 255, 0.05)' : 'rgba(0, 0, 0, 0.05)',
            delivered: isDarkMode ? '#34d399' : '#28a745',
            missed: isDarkMode ? '#f87171' : '#dc3545',
            tooltipBg: getColor('--surface-color', '#ffffff', '#243046'),
            tooltipBorder: getColor('--border-color', '#dee2e6', '#38465a')
        };
    }

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

        // Get theme colors
        const colors = getThemeColors();

        // Create Chart.js stacked bar chart
        chartInstances[containerId] = new Chart(canvas, {
            type: 'bar',
            data: {
                labels: series.labels,
                datasets: [
                    {
                        label: 'Delivered',
                        data: series.delivered,
                        backgroundColor: colors.delivered,
                        borderWidth: 0
                    },
                    {
                        label: 'Missed',
                        data: series.missed,
                        backgroundColor: colors.missed,
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
                            color: colors.text
                        }
                    },
                    tooltip: {
                        mode: 'index',
                        intersect: false,
                        backgroundColor: colors.tooltipBg,
                        titleColor: colors.text,
                        bodyColor: colors.text,
                        borderColor: colors.tooltipBorder,
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
                            color: colors.text
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
                            color: colors.text
                        },
                        ticks: {
                            color: colors.text
                        },
                        grid: {
                            color: colors.gridLines
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

    // Listen for theme changes and re-render all charts
    window.addEventListener('theme-changed', () => {
        console.log('🎨 Alert delivery charts: Theme changed, re-rendering...');

        // Get the last rendered config from a stored reference
        if (window.__lastAlertVerificationConfig) {
            render(window.__lastAlertVerificationConfig);
        }
    });

    // Store the config for theme change re-renders
    const originalRender = render;
    window.AlertVerificationCharts.render = function(config) {
        window.__lastAlertVerificationConfig = config;
        originalRender(config);
    };
})(window);
