<?php
// Diagnostic endpoint for Active Topics investigation
header('Content-Type: text/plain; charset=utf-8');

$phpbb_root_path = '/home4/fivetech/public_html/forums/';
include($phpbb_root_path . 'config.php');
include($phpbb_root_path . 'includes/constants.php');

$db = new mysqli($dbhost, $dbuser, $dbpasswd, $dbname);
$db->set_charset('utf8');

$sort_days = 7;
$last_post_time_sql = ' AND t.topic_last_post_time > ' . (time() - ($sort_days * 24 * 3600));
$visibility_sql = 't.topic_visibility IN (0)';

// 1) Active topics query (what Active Topics page should show)
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

// 2) Bot topics specifically
echo "\n=== 2. Bot topics (last_poster_id=1581) ===\n";
$sql2 = "SELECT topic_id, topic_title, topic_visibility, topic_type, topic_last_poster_id, 
         topic_posts_approved, topic_posts_unapproved, topic_last_post_time,
         topic_first_poster_name
    FROM phpbb_topics 
    WHERE topic_last_poster_id = 1581
    ORDER BY topic_last_post_time DESC";
$result2 = $db->query($sql2);
while ($row = $result2->fetch_assoc()) {
    echo "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} approved_posts={$row['topic_posts_approved']} unapproved={$row['topic_posts_unapproved']} starter=\"{$row['topic_first_poster_name']}\" time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"\n";
}

// 3) Check posts for bot topics
echo "\n=== 3. Posts in bot topics ===\n";
$sql3 = "SELECT p.topic_id, p.post_id, p.post_visibility, p.poster_id, p.post_time
    FROM phpbb_posts p
    WHERE p.poster_id = 1581 OR p.topic_id IN (SELECT topic_id FROM phpbb_topics WHERE topic_last_poster_id = 1581)
    ORDER BY p.post_time DESC";
$result3 = $db->query($sql3);
while ($row = $result3->fetch_assoc()) {
    echo "topic={$row['topic_id']} post={$row['post_id']} vis={$row['post_visibility']} poster={$row['poster_id']} time=" . date('Y-m-d H:i', $row['post_time']) . "\n";
}

// 4) Check forums flags
echo "\n=== 4. Forums with ACTIVE_TOPICS flag ===\n";
$sql4 = "SELECT forum_id, forum_name, forum_flags, forum_flags & 16 as has_active_flag FROM phpbb_forums WHERE forum_flags & 16 ORDER BY forum_id";
$result4 = $db->query($sql4);
while ($row = $result4->fetch_assoc()) {
    echo "id={$row['forum_id']} flag={$row['forum_flags']} active_flag={$row['has_active_flag']} \"{$row['forum_name']}\"\n";
}

// 5) Check topic_type distribution for bot topics
echo "\n=== 5. Topic type distribution for bot topics ===\n";
$sql5 = "SELECT topic_type, COUNT(*) as cnt FROM phpbb_topics WHERE topic_last_poster_id = 1581 GROUP BY topic_type";
$result5 = $db->query($sql5);
while ($row = $result5->fetch_assoc()) {
    echo "type={$row['topic_type']} count={$row['cnt']}\n";
}

// 6) Check topic_last_post_time values
echo "\n=== 6. Bot topics last_post_time (epoch) vs now ===\n";
echo "Now: " . time() . " (" . date('Y-m-d H:i:s') . ")\n";
$sql6 = "SELECT topic_id, topic_last_post_time, " . time() . " - topic_last_post_time as diff_seconds FROM phpbb_topics WHERE topic_last_poster_id = 1581";
$result6 = $db->query($sql6);
while ($row = $result6->fetch_assoc()) {
    $days = round($row['diff_seconds'] / 86400, 2);
    echo "id={$row['topic_id']} diff_days={$days} \"";
    echo date('Y-m-d H:i:s', $row['topic_last_post_time']);
    echo "\"\n";
}

// 7) Simulate phpBB's get_global_visibility_sql for topic mode
echo "\n=== 7. phpBB visibility SQL for 'topic' mode (logged-in normal user) ===\n";
echo "Expected SQL: t.topic_visibility IN (0)\n";
$sql7 = "SELECT t.topic_id, t.topic_title, t.topic_visibility
    FROM phpbb_topics t
    WHERE t.topic_moved_id = 0
        {$last_post_time_sql}
        AND t.topic_visibility IN (0)
    ORDER BY t.topic_last_post_time DESC
    LIMIT 30";
$result7 = $db->query($sql7);
echo "Results with simple vis filter: " . $result7->num_rows . "\n\n";
while ($row = $result7->fetch_assoc()) {
    echo "id={$row['topic_id']} vis={$row['topic_visibility']} \"{$row['topic_title']}\"\n";
}

// 8) Check user type for bot
echo "\n=== 8. Bot user info ===\n";
$sql8 = "SELECT user_id, username, user_type, user_colour FROM phpbb_users WHERE user_id = 1581";
$result8 = $db->query($sql8);
$row8 = $result8->fetch_assoc();
echo "user_id={$row8['user_id']} username=\"{$row8['username']}\" type={$row8['user_type']} colour={$row8['user_colour']}\n";

// 9) Check if phpbb_topics_track or phpbb_topics_posted affects this
echo "\n=== 9. Check phpbb_topics_posted for bot topics ===\n";
$sql9 = "SELECT tp.topic_id, tp.user_id, tp.posted
    FROM phpbb_topics_posted tp
    WHERE tp.user_id = 1581
    ORDER BY tp.topic_id DESC
    LIMIT 20";
$result9 = $db->query($sql9);
if ($result9) {
    while ($row = $result9->fetch_assoc()) {
        echo "topic={$row['topic_id']} user={$row['user_id']} posted={$row['posted']}\n";
    }
} else {
    echo "phpbb_topics_posted not found or empty\n";
}

$db->close();
