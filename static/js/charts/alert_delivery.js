(function (window) {
    'use strict';

    function resolveSeries(entries) {
        const categories = [];
        const delivered = [];
        const missed = [];
        const delayed = [];
        const tooltips = [];

        entries.forEach((entry) => {
            const total = entry.total || 0;
            const deliveredCount = entry.delivered || 0;
            const delayedCount = entry.delayed || 0;
            const missedCount = Math.max(total - deliveredCount, 0);
            categories.push(entry.label || 'Unknown');
            delivered.push(deliveredCount);
            missed.push(missedCount);
            delayed.push(delayedCount);
            tooltips.push(entry);
        });

        return { categories, delivered, missed, delayed, tooltips };
    }

    function renderChart(containerId, entries) {
        if (!window.Highcharts) {
            console.warn('Highcharts is not available; skipping chart render for', containerId);
            return;
        }

        const target = document.getElementById(containerId);
        if (!target) {
            return;
        }

        const series = resolveSeries(entries);
        if (series.categories.length === 0) {
            target.innerHTML = '<p class="text-muted mb-0">No data available for this chart.</p>';
            return;
        }

        Highcharts.chart(containerId, {
            chart: {
                type: 'column',
                backgroundColor: 'transparent'
            },
            title: { text: null },
            xAxis: {
                categories: series.categories,
                crosshair: true,
                labels: { style: { color: 'var(--text-color)' } }
            },
            yAxis: {
                min: 0,
                title: { text: 'Alerts', style: { color: 'var(--text-color)' } },
                labels: { style: { color: 'var(--text-color)' } }
            },
            legend: {
                itemStyle: { color: 'var(--text-color)' }
            },
            tooltip: {
                shared: true,
                useHTML: true,
                formatter: function () {
                    const pointIndex = this.points && this.points.length ? this.points[0].point.index : 0;
                    const entry = series.tooltips[pointIndex] || {};
                    const rate = entry.delivery_rate != null ? entry.delivery_rate.toFixed(1) + '%' : '—';
                    const latency = entry.average_latency_seconds != null ? entry.average_latency_seconds.toFixed(1) + ' s' : '—';
                    return `
                        <div class="small">
                            <strong>${entry.label || 'Unknown'}</strong><br>
                            Delivery Rate: ${rate}<br>
                            Avg Latency: ${latency}<br>
                            Delayed Alerts: ${entry.delayed || 0}
                        </div>
                    `;
                }
            },
            plotOptions: {
                column: {
                    stacking: 'normal',
                    borderWidth: 0
                }
            },
            series: [
                {
                    name: 'Delivered',
                    data: series.delivered,
                    color: '#28a745'
                },
                {
                    name: 'Missed',
                    data: series.missed,
                    color: '#dc3545'
                }
            ]
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
