<?php
ob_implicit_flush(true);

$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo "DB connect error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

$lines = array();

$sort_days = 7;
$cutoff = time() - ($sort_days * 24 * 3600);

// 1) All topics vis=0 last 7 days
$result = $db->query("SELECT topic_id, topic_title, topic_visibility, topic_type, topic_last_post_time FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 0 ORDER BY topic_last_post_time DESC LIMIT 30");
$lines[] = "=== 1. Active Topics query (vis=0, 7d): " . $result->num_rows . " rows ===";
while ($row = $result->fetch_assoc()) {
    $lines[] = "id={$row['topic_id']} type={$row['topic_type']} time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"";
}

// 2) Bot topics
$result2 = $db->query("SELECT topic_id, topic_title, topic_visibility, topic_type, topic_posts_approved, topic_posts_unapproved, topic_last_post_time FROM phpbb_topics WHERE topic_last_poster_id = 1581 ORDER BY topic_last_post_time DESC");
$lines[] = "\n=== 2. Bot topics ===";
while ($row = $result2->fetch_assoc()) {
    $lines[] = "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} approved={$row['topic_posts_approved']} unapproved={$row['topic_posts_unapproved']} time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"";
}

// 3) Bot posts
$result3 = $db->query("SELECT topic_id, post_id, post_visibility, post_time FROM phpbb_posts WHERE poster_id = 1581 ORDER BY post_time DESC LIMIT 30");
$lines[] = "\n=== 3. Bot posts ===";
while ($row = $result3->fetch_assoc()) {
    $lines[] = "topic={$row['topic_id']} post={$row['post_id']} vis={$row['post_visibility']} time=" . date('Y-m-d H:i', $row['post_time']);
}

// 4) Bot user
$result4 = $db->query("SELECT user_id, username, user_type FROM phpbb_users WHERE user_id = 1581");
$row4 = $result4->fetch_assoc();
$lines[] = "\n=== 4. Bot user: id={$row4['user_id']} name=\"{$row4['username']}\" type={$row4['user_type']} ===";

// 5) Now
$lines[] = "\n=== 5. Now: " . time() . " (" . date('Y-m-d H:i:s') . ") ===";

// 6) Forums of bot topics
$result6 = $db->query("SELECT t.topic_id, t.forum_id, f.forum_flags FROM phpbb_topics t LEFT JOIN phpbb_forums f ON f.forum_id = t.forum_id WHERE t.topic_last_poster_id = 1581");
$lines[] = "\n=== 6. Bot topic forums (flag&16 = active topics enabled) ===";
while ($row = $result6->fetch_assoc()) {
    $flags = $row['forum_flags'] === null ? 'NULL' : $row['forum_flags'];
    $active = ($row['forum_flags'] & 16) ? 'YES' : 'NO';
    $lines[] = "topic={$row['topic_id']} forum={$row['forum_id']} flags={$flags} active_topics={$active}";
}

$output = implode("\n", $lines) . "\n=== DONE ===\n";

echo $output;

$written = @file_put_contents(__DIR__ . '/diag_out.txt', $output);
if ($written === false) {
    echo "\nWARNING: could not write diag_out.txt\n";
}

$db->close();
