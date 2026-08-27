<?php
$lines = file('/home1/fivetec1/public_html/forums/config.php');
$dbname = $dbuser = $dbpass = '';
foreach ($lines as $l) {
    if (preg_match('/\$dbname\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbname = $m[1];
    if (preg_match('/\$dbuser\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbuser = $m[1];
    if (preg_match('/\$dbpasswd\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbpass = $m[1];
}
$db = new mysqli('localhost', $dbuser, $dbpass, $dbname);

echo "=== Bot topics_track (last 5) ===\n";
$r = $db->query("SELECT user_id, topic_id, forum_id, mark_time, FROM_UNIXTIME(mark_time) as read_at FROM phpbb_topics_track WHERE user_id = 6418 ORDER BY mark_time DESC LIMIT 5");
while ($row = $r->fetch_assoc()) {
    echo "topic={$row['topic_id']} forum={$row['forum_id']} mark_time={$row['mark_time']} read_at={$row['read_at']}\n";
}

echo "\n=== Bot forums_track (last 5) ===\n";
$r = $db->query("SELECT user_id, forum_id, mark_time, FROM_UNIXTIME(mark_time) as read_at FROM phpbb_forums_track WHERE user_id = 6418 ORDER BY mark_time DESC LIMIT 5");
while ($row = $r->fetch_assoc()) {
    echo "forum={$row['forum_id']} mark_time={$row['mark_time']} read_at={$row['read_at']}\n";
}

echo "\n=== Last bot post ===\n";
$r = $db->query("SELECT post_id, topic_id, post_time, FROM_UNIXTIME(post_time) as posted_at FROM phpbb_posts WHERE poster_id = 6418 ORDER BY post_id DESC LIMIT 1");
$row = $r->fetch_assoc();
echo "post_id={$row['post_id']} topic={$row['topic_id']} post_time={$row['post_time']} posted_at={$row['posted_at']}\n";

echo "\n=== Topic last_post_time vs track mark_time ===\n";
$r = $db->query("SELECT t.topic_id, t.topic_last_post_time, tt.mark_time,
    CASE WHEN t.topic_last_post_time <= tt.mark_time THEN 'READ' ELSE 'UNREAD' END as status
    FROM phpbb_topics t
    INNER JOIN phpbb_topics_track tt ON tt.topic_id = t.topic_id AND tt.user_id = 6418
    WHERE t.topic_id IN (SELECT topic_id FROM phpbb_posts WHERE poster_id = 6418 ORDER BY post_id DESC LIMIT 5)
    ORDER BY t.topic_id DESC");
while ($row = $r->fetch_assoc()) {
    echo "topic={$row['topic_id']} last_post={$row['topic_last_post_time']} mark={$row['mark_time']} status={$row['status']}\n";
}
