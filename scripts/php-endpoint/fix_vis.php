<?php
ob_implicit_flush(true);

$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo "DB connect error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

// phpBB 3.1+: ITEM_APPROVED = 1. Restore bot content to approved visibility.
$db->query("UPDATE phpbb_posts SET post_visibility = 1 WHERE poster_id = 1581 AND post_visibility != 1");
echo "posts fixed: " . $db->affected_rows . "\n";

$db->query("UPDATE phpbb_topics SET topic_visibility = 1 WHERE topic_last_poster_id = 1581 AND topic_visibility != 1");
echo "topics fixed: " . $db->affected_rows . "\n";

$result = $db->query("SELECT COUNT(*) as c FROM phpbb_topics WHERE topic_last_poster_id = 1581 AND topic_visibility != 1");
echo "bot topics not approved: " . $result->fetch_assoc()['c'] . "\n";

$result2 = $db->query("SELECT COUNT(*) as c FROM phpbb_posts WHERE poster_id = 1581 AND post_visibility != 1");
echo "bot posts not approved: " . $result2->fetch_assoc()['c'] . "\n";

// Verify active topics query now returns bot topics
$cutoff = time() - (7 * 24 * 3600);
$r = $db->query("SELECT COUNT(*) as c FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 1");
echo "active topics (vis=1, 7d): " . $r->fetch_assoc()['c'] . "\n";

$r2 = $db->query("SELECT topic_id FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 1 ORDER BY topic_last_post_time DESC LIMIT 10");
while ($row = $r2->fetch_assoc()) {
    echo "id={$row['topic_id']}\n";
}

$db->close();
echo "DONE\n";
