<?php
$lines = file('/home1/fivetec1/public_html/forums/config.php');
$dbname = $dbuser = $dbpass = '';
foreach ($lines as $l) {
    if (preg_match('/\$dbname\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbname = $m[1];
    if (preg_match('/\$dbuser\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbuser = $m[1];
    if (preg_match('/\$dbpasswd\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbpass = $m[1];
}
$db = new mysqli('localhost', $dbuser, $dbpass, $dbname);
$r = $db->query("SELECT post_id, post_subject, post_text FROM phpbb_posts WHERE poster_id = 6418 ORDER BY post_time DESC LIMIT 1");
$row = $r->fetch_assoc();
echo "post_id: " . $row['post_id'] . "\n";
echo "subject: " . $row['post_subject'] . "\n";
echo "text: " . substr($row['post_text'], 0, 500) . "\n";
