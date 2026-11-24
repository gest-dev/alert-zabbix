(() => {
    'use strict';
    if (new URLSearchParams(location.search).get('action') !== 'dashboard.view') return;

    let attempts = 0;
    function start() {
        const dashboard = window.ZABBIX?.Dashboard;
        const grid = document.querySelector('.dashboard-grid');
        if (!dashboard || !grid) {
            if (++attempts < 100) setTimeout(start, 50);
            return;
        }
        // Escopo do painel operacional; não altera outros dashboards.
        if (String(dashboard.getData().dashboardid) !== '1') return;
        if (document.getElementById('gest-dashboard-title')) return;

        const title = document.createElement('div');
        title.id = 'gest-dashboard-title';
        title.setAttribute('role', 'heading');
        title.setAttribute('aria-level', '2');
        title.setAttribute('aria-live', 'polite');
        grid.before(title);

        function update() {
            const page = dashboard.getSelectedDashboardPage();
            const name = page?.getName() || dashboard.getData().name;
            if (title.textContent !== name) {
                title.textContent = name;
                title.title = name;
            }
        }
        update();
        let pending = false;
        new MutationObserver(() => {
            if (pending) return;
            pending = true;
            requestAnimationFrame(() => { pending = false; update(); });
        }).observe(grid.parentElement, {childList: true, subtree: true, characterData: true});
    }
    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', start, {once: true});
    } else {
        start();
    }
})();
