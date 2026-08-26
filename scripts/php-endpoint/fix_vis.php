<?php
ob_implicit_flush(true);

$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo "DB connect error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

// Fix posts by bot with wrong visibility
$db->query("UPDATE phpbb_posts SET post_visibility = 0 WHERE poster_id = 1581 AND post_visibility != 0");
echo "posts fixed: " . $db->affected_rows . "\n";

// Fix topics where bot made the last post
$db->query("UPDATE phpbb_topics SET topic_visibility = 0 WHERE topic_last_poster_id = 1581 AND topic_visibility != 0");
echo "topics fixed: " . $db->affected_rows . "\n";

// Verify
$result = $db->query("SELECT COUNT(*) as c FROM phpbb_topics WHERE topic_last_poster_id = 1581 AND topic_visibility != 0");
echo "bot topics still hidden: " . $result->fetch_assoc()['c'] . "\n";

$result2 = $db->query("SELECT COUNT(*) as c FROM phpbb_posts WHERE poster_id = 1581 AND post_visibility != 0");
echo "bot posts still hidden: " . $result2->fetch_assoc()['c'] . "\n";

$db->close();
echo "DONE\n";
