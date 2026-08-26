<?php
ob_implicit_flush(true);
ini_set('output_buffering', '0');

$phpbb_root_path = '/home4/fivetech/public_html/forums/';
include($phpbb_root_path . 'config.php');
include($phpbb_root_path . 'includes/constants.php');

$db = new mysqli($dbhost, $dbuser, $dbpasswd, $dbname);
$db->set_charset('utf8');

$sort_days = 7;
$last_post_time_sql = ' AND t.topic_last_post_time > ' . (time() - ($sort_days * 24 * 3600));
$visibility_sql = 't.topic_visibility IN (0)';

$sql = "SELECT t.topic_last_post_time, t.topic_id, t.topic_title, t.topic_visibility, t.topic_type
    FROM phpbb_topics t
    WHERE t.topic_moved_id = 0
        {$last_post_time_sql}
        AND ({$visibility_sql})
    ORDER BY t.topic_last_post_time DESC
    LIMIT 30";

echo "=== 1. ALL Active Topics (last 7 days, vis=0) ===\n";
$result = $db->query($sql);
echo "Total: " . $result->num_rows . "\n\n";
while ($row = $result->fetch_assoc()) {
    echo "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"\n";
}

echo "\n=== 2. Bot topics (last_poster_id=1581) ===\n";
$sql2 = "SELECT topic_id, topic_title, topic_visibility, topic_type, topic_last_poster_id,
         topic_posts_approved, topic_posts_unapproved, topic_last_post_time,
         topic_first_poster_name
    FROM phpbb_topics
    WHERE topic_last_poster_id = 1581
    ORDER BY topic_last_post_time DESC";
$result2 = $db->query($sql2);
while ($row = $result2->fetch_assoc()) {
    echo "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} approved={$row['topic_posts_approved']} unapproved={$row['topic_posts_unapproved']} starter=\"{$row['topic_first_poster_name']}\" time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"\n";
}

echo "\n=== 3. Posts in bot topics ===\n";
$sql3 = "SELECT p.topic_id, p.post_id, p.post_visibility, p.poster_id, p.post_time
    FROM phpbb_posts p
    WHERE p.poster_id = 1581
    ORDER BY p.post_time DESC
    LIMIT 30";
$result3 = $db->query($sql3);
while ($row = $result3->fetch_assoc()) {
    echo "topic={$row['topic_id']} post={$row['post_id']} vis={$row['post_visibility']} poster={$row['poster_id']} time=" . date('Y-m-d H:i', $row['post_time']) . "\n";
}

echo "\n=== 4. Bot user info ===\n";
$sql4 = "SELECT user_id, username, user_type, user_colour FROM phpbb_users WHERE user_id = 1581";
$result4 = $db->query($sql4);
$row4 = $result4->fetch_assoc();
echo "user_id={$row4['user_id']} username=\"{$row4['username']}\" type={$row4['user_type']} colour={$row4['user_colour']}\n";

echo "\n=== 5. Bot topics last_post_time vs now ===\n";
echo "Now: " . time() . " (" . date('Y-m-d H:i:s') . ")\n";
$sql5 = "SELECT topic_id, topic_last_post_time, " . time() . " - topic_last_post_time as diff_seconds FROM phpbb_topics WHERE topic_last_poster_id = 1581";
$result5 = $db->query($sql5);
while ($row = $result5->fetch_assoc()) {
    $days = round($row['diff_seconds'] / 86400, 2);
    echo "id={$row['topic_id']} diff_days={$days} last_post=" . date('Y-m-d H:i:s', $row['topic_last_post_time']) . "\n";
}

echo "\n=== 6. Topic type distribution for bot topics ===\n";
$sql6 = "SELECT topic_type, COUNT(*) as cnt FROM phpbb_topics WHERE topic_last_poster_id = 1581 GROUP BY topic_type";
$result6 = $db->query($sql6);
while ($row = $result6->fetch_assoc()) {
    echo "type={$row['topic_type']} count={$row['cnt']}\n";
}

echo "\n=== 7. phpbb_topics_posted for bot user ===\n";
$sql7 = "SELECT tp.topic_id, tp.user_id, tp.posted
    FROM phpbb_topics_posted tp
    WHERE tp.user_id = 1581
    ORDER BY tp.topic_id DESC
    LIMIT 20";
$result7 = $db->query($sql7);
if ($result7 && $result7->num_rows > 0) {
    while ($row = $result7->fetch_assoc()) {
        echo "topic={$row['topic_id']} user={$row['user_id']} posted={$row['posted']}\n";
    }
} else {
    echo "No rows in phpbb_topics_posted for user 1581\n";
}

$db->close();
echo "\n=== DONE ===\n";
