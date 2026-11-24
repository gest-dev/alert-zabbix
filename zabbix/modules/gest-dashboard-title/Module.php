<?php
namespace Modules\GestDashboardTitle;

use Zabbix\Core\CModule;

class Module extends CModule {
    public function getAssets(): array {
        return ($_GET['action'] ?? '') === 'dashboard.view'
            ? parent::getAssets()
            : ['css' => [], 'js' => []];
    }
}
