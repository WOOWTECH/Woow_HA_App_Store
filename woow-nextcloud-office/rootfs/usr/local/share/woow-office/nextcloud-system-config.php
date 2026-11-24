<?php
// Writes the per-boot system values of init-nextcloud-config into config.php in one pass
// (pipeline unattended-pipeline/229). Each `occ` call boots Nextcloud (about 1.3 s on an N2840),
// and s6 cannot stop the add-on cleanly while this oneshot runs.
//
// The result is the same as the former sequence of `occ config:system:set` calls followed by the
// trusted_proxies/overwritehost edit:
// - occ reads config.php merged with the other *.config.php files (Config::readData) and, if any
//   value changed, writes that merged array back (Config::writeData); if nothing changed it
//   writes nothing;
// - a value is changed only when it is not set or not identical (Config::set);
// - `name 0` style keys replace one entry and keep the rest (SetConfig::mergeArrayValue);
// - values are strings unless the call had --type integer;
// - the trusted_proxies/overwritehost edit then reads config.php alone and always writes it.
//
// Usage: PUBLIC_HOST=… PUBLIC_URL=… DEFAULT_PHONE_REGION=… DB_PASS=… php nextcloud-system-config.php <config.php>

function read_config(string $file): array {
    $CONFIG = null;
    include $file;
    return is_array($CONFIG) ? $CONFIG : [];
}

function env_value(string $name): string {
    $value = getenv($name);
    if ($value === false) {
        fwrite(STDERR, "nextcloud-system-config: $name is not set\n");
        exit(1);
    }
    return $value;
}

$file = $argv[1] ?? '';
if ($file === '' || !is_file($file)) {
    fwrite(STDERR, "nextcloud-system-config: config.php not found: $file\n");
    exit(1);
}
$host = env_value('PUBLIC_HOST');

$own = read_config($file);
$merged = $own;
$extra = glob(dirname($file) . '/*.config.php');
if (is_array($extra)) {
    natsort($extra);
    foreach ($extra as $f) {
        $merged = array_replace_recursive($merged, read_config($f));
    }
}

// In the order of the former occ calls: [key, sub-key or null, value].
$values = [
    ['trusted_domains', 0, $host],
    ['trusted_domains', 1, 'localhost'],
    ['trusted_domains', 2, '127.0.0.1'],
    ['trusted_domains', 3, 'homeassistant'],
    ['overwrite.cli.url', null, env_value('PUBLIC_URL')],
    ['overwriteprotocol', null, 'https'],
    ['default_phone_region', null, env_value('DEFAULT_PHONE_REGION')],
    ['dbpassword', null, env_value('DB_PASS')],
    ['memcache.local', null, '\OC\Memcache\APCu'],
    ['memcache.locking', null, '\OC\Memcache\Redis'],
    ['redis', 'host', '/run/redis/redis.sock'],
    ['redis', 'port', 0],
    ['maintenance_window_start', null, 1],
];
$changed = false;
foreach ($values as [$key, $sub, $value]) {
    if ($sub !== null) {
        $array = $merged[$key] ?? '';
        if (!is_array($array)) {
            $array = [];
        }
        $array[$sub] = $value;
        $value = $array;
    }
    if (!isset($merged[$key]) || $merged[$key] !== $value) {
        $merged[$key] = $value;
        $changed = true;
    }
}

$config = $changed ? $merged : $own;
// Allow framing by HA/public hosts.
$proxies = $config['trusted_proxies'] ?? [];
if (!is_array($proxies)) {
    $proxies = [$proxies];
}
$config['trusted_proxies'] = array_values(array_unique(array_merge($proxies, ['127.0.0.1', '172.30.32.2'])));
$config['overwritehost'] = $host;

$out = "<?php\n\$CONFIG = " . var_export($config, true) . ";\n";
if (file_get_contents($file) !== $out && file_put_contents($file, $out, LOCK_EX) === false) {
    fwrite(STDERR, "nextcloud-system-config: could not write $file\n");
    exit(1);
}
