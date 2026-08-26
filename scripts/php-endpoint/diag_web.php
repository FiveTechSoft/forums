<?php
header('Content-Type: text/plain; charset=utf-8');

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

$result = $db->query($sql);
$out = "=== ALL Active Topics (last 7 days, vis=0) === Total: " . $result->num_rows . "\n";
while ($row = $result->fetch_assoc()) {
    $out .= "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"\n";
}

$out .= "\n=== Bot topics (last_poster_id=1581) ===\n";
$result2 = $db->query("SELECT topic_id, topic_title, topic_visibility, topic_type, topic_posts_approved, topic_posts_unapproved, topic_last_post_time, topic_first_poster_name FROM phpbb_topics WHERE topic_last_poster_id = 1581 ORDER BY topic_last_post_time DESC");
while ($row = $result2->fetch_assoc()) {
    $out .= "id={$row['topic_id']} vis={$row['topic_visibility']} type={$row['topic_type']} approved={$row['topic_posts_approved']} unapproved={$row['topic_posts_unapproved']} starter=\"{$row['topic_first_poster_name']}\" time=" . date('Y-m-d H:i', $row['topic_last_post_time']) . " \"{$row['topic_title']}\"\n";
}

$out .= "\n=== Posts by bot ===\n";
$result3 = $db->query("SELECT topic_id, post_id, post_visibility, poster_id, post_time FROM phpbb_posts WHERE poster_id = 1581 ORDER BY post_time DESC LIMIT 30");
while ($row = $result3->fetch_assoc()) {
    $out .= "topic={$row['topic_id']} post={$row['post_id']} vis={$row['post_visibility']} time=" . date('Y-m-d H:i', $row['post_time']) . "\n";
}

$out .= "\n=== Bot user ===\n";
$result4 = $db->query("SELECT user_id, username, user_type, user_colour FROM phpbb_users WHERE user_id = 1581");
$row4 = $result4->fetch_assoc();
$out .= "user_id={$row4['user_id']} name=\"{$row4['username']}\" type={$row4['user_type']} colour={$row4['user_colour']}\n";

$out .= "\n=== Now vs bot topics ===\n";
$out .= "Now: " . time() . " (" . date('Y-m-d H:i:s') . ")\n";
$result5 = $db->query("SELECT topic_id, topic_last_post_time, " . time() . " - topic_last_post_time as diff FROM phpbb_topics WHERE topic_last_poster_id = 1581");
while ($row = $result5->fetch_assoc()) {
    $out .= "id={$row['topic_id']} diff_days=" . round($row['diff']/86400,2) . " last=" . date('Y-m-d H:i:s', $row['topic_last_post_time']) . "\n";
}

$db->close();
$out .= "\n=== DONE ===\n";
echo $out;
