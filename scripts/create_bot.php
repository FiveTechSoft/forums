<?php
/**
 * Create AiBot user for phpBB
 * Run from forums root: php _ai/create_bot.php
 */

define('PHPBB_INSTALLED', true);

$forum_path = dirname(__DIR__); // parent of _ai/
$config_file = $forum_path . '/config.php';

echo "Config path: $config_file\n";
echo "File exists: " . (file_exists($config_file) ? 'YES' : 'NO') . "\n";
echo "File readable: " . (is_readable($config_file) ? 'YES' : 'NO') . "\n";
echo "File size: " . filesize($config_file) . "\n";

if (!file_exists($config_file)) {
    echo "ERROR: config.php not found at $config_file\n";
    echo "Dir contents: " . implode(', ', array_slice(scandir($forum_path), 0, 10)) . "\n";
    exit(1);
}

// Parse DB credentials from config.php
$content = file_get_contents($config_file);
preg_match('/\$dbname\s*=\s*\'([^\']*)\'/', $content, $m);
$dbname = $m[1] ?? '';
preg_match('/\$dbuser\s*=\s*\'([^\']*)\'/', $content, $m);
$dbuser = $m[1] ?? '';
preg_match('/\$dbpasswd\s*=\s*\'([^\']*)\'/', $content, $m);
$dbpass = $m[1] ?? '';

if (!$dbname || !$dbuser) {
    echo "ERROR: Could not parse DB credentials\n";
    echo "Content sample: " . substr($content, 0, 500) . "\n";
    echo "Regex matches: dbname=" . ($m[1] ?? 'NONE') . "\n";
    exit(1);
}

echo "DB: $dbname, user: $dbuser\n";

// Connect
$db = new mysqli('localhost', $dbuser, $dbpass, $dbname);
if ($db->connect_error) {
    echo "DB error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

// Check if AiBot exists
$result = $db->query("SELECT user_id FROM phpbb_users WHERE username = 'AiBot [Bot]'");
if ($result && $result->num_rows > 0) {
    $row = $result->fetch_assoc();
    echo "AiBot already exists with ID: " . $row['user_id'] . "\n";
    $db->close();
    exit(0);
}

// Create the bot user
// Clone AdsBot (1572) structure but with AiBot name
$result = $db->query("SELECT * FROM phpbb_users WHERE user_id = 1572");
if (!$result || $result->num_rows === 0) {
    echo "ERROR: Could not find AdsBot user_id=1572\n";
    exit(1);
}

$adsbot = $result->fetch_assoc();

// Build INSERT with all columns except user_id (auto_increment)
$cols = [];
$values = [];
foreach ($adsbot as $key => $value) {
    if ($key === 'user_id') continue;
    
    if ($key === 'username') {
        $cols[] = $key;
        $values[] = "'AiBot [Bot]'";
    } elseif ($key === 'username_clean') {
        $cols[] = $key;
        $values[] = "'aibot [bot]'";
    } elseif ($key === 'user_regdate' || $key === 'user_lastmark') {
        $cols[] = $key;
        $values[] = time();
    } elseif ($key === 'user_session_time') {
        $cols[] = $key;
        $values[] = 0;
    } elseif ($key === 'user_ip') {
        $cols[] = $key;
        $values[] = "''";
    } elseif ($key === 'user_password') {
        $cols[] = $key;
        $values[] = "''";
    } elseif ($key === 'user_email') {
        $cols[] = $key;
        $values[] = "''";
    } else {
        $cols[] = $key;
        if (is_null($value)) {
            $values[] = 'NULL';
        } elseif (is_int($value)) {
            $values[] = $value;
        } else {
            $values[] = "'" . $db->real_escape_string($value) . "'";
        }
    }
}

$sql = "INSERT INTO phpbb_users (" . implode(', ', $cols) . ") VALUES (" . implode(', ', $values) . ")";
$result = $db->query($sql);

if (!$result) {
    echo "INSERT ERROR: " . $db->error . "\n";
    exit(1);
}

$new_id = $db->insert_id;
echo "Created AiBot with ID: $new_id\n";

// Add to Registered Users group (group_id=2 for regular users, or keep AdsBot's group=6 for BOTS)
$adsbot_group = (int)$adsbot['group_id'];
$db->query("INSERT INTO phpbb_users_groups (user_id, group_id, group_leader) VALUES ($new_id, $adsbot_group, 0) ON DUPLICATE KEY UPDATE group_leader=0");
echo "Added to group $adsbot_group\n";

// Verify
$result = $db->query("SELECT user_id, username, user_type, group_id FROM phpbb_users WHERE user_id = $new_id");
if ($result && $result->num_rows > 0) {
    $row = $result->fetch_assoc();
    echo "VERIFY: user_id=" . $row['user_id'] . " username=" . $row['username'] . " type=" . $row['user_type'] . " group=" . $row['group_id'] . "\n";
}

$db->close();
