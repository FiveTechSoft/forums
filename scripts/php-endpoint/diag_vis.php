<?php
ob_implicit_flush(true);

$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo "DB connect error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

$cutoff = time() - (7 * 24 * 3600);

echo "--- All topics last 7d, no filters ---\n";
$r = $db->query("SELECT t.topic_id, t.topic_visibility, t.topic_type, t.topic_moved_id, t.topic_last_poster_id, f.forum_id
    FROM phpbb_topics t LEFT JOIN phpbb_forums f ON f.forum_id = t.forum_id
    WHERE t.topic_last_post_time > $cutoff
    ORDER BY t.topic_last_post_time DESC LIMIT 30");
while ($row = $r->fetch_assoc()) {
    echo "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} moved={$row['topic_moved_id']} lastposter={$row['topic_last_poster_id']} forum={$row['forum_id']}\n";
}

echo "\n--- Visibility distribution (all topics) ---\n";
$r2 = $db->query("SELECT topic_visibility, COUNT(*) as c FROM phpbb_topics GROUP BY topic_visibility");
while ($row = $r2->fetch_assoc()) {
    echo "vis={$row['topic_visibility']} count={$row['c']}\n";
}

echo "\n--- Posts visibility distribution ---\n";
$r3 = $db->query("SELECT post_visibility, COUNT(*) as c FROM phpbb_posts GROUP BY post_visibility");
while ($row = $r3->fetch_assoc()) {
    echo "vis={$row['post_visibility']} count={$row['c']}\n";
}

$db->close();
echo "\nDONE\n";
