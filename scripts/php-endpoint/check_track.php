<?php
$lines = file('/home1/fivetec1/public_html/forums/config.php');
$dbname = $dbuser = $dbpass = '';
foreach ($lines as $l) {
    if (preg_match('/\$dbname\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbname = $m[1];
    if (preg_match('/\$dbuser\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbuser = $m[1];
    if (preg_match('/\$dbpasswd\s*=\s*\x27([^\x27]*)\x27/', $l, $m)) $dbpass = $m[1];
}
$db = new mysqli('localhost', $dbuser, $dbpass, $dbname);

echo "=== Last 5 bot posts ===\n";
$r = $db->query("SELECT post_id, topic_id, post_time, FROM_UNIXTIME(post_time) as posted_at FROM phpbb_posts WHERE poster_id = 6418 ORDER BY post_id DESC LIMIT 5");
$topics = [];
while ($row = $r->fetch_assoc()) {
    echo "post_id={$row['post_id']} topic={$row['topic_id']} posted_at={$row['posted_at']}\n";
    $topics[] = $row['topic_id'];
}

echo "\n=== Tracking for those topics ===\n";
foreach ($topics as $tid) {
    $r = $db->query("SELECT mark_time, FROM_UNIXTIME(mark_time) as read_at FROM phpbb_topics_track WHERE user_id = 6418 AND topic_id = $tid");
    if ($r->num_rows > 0) {
        $row = $r->fetch_assoc();
        $r2 = $db->query("SELECT topic_last_post_time FROM phpbb_topics WHERE topic_id = $tid");
        $trow = $r2->fetch_assoc();
        $lpt = $trow['topic_last_post_time'];
        $mt = $row['mark_time'];
        $status = ($lpt <= $mt) ? 'READ' : 'UNREAD';
        echo "topic=$tid mark={$row['read_at']} last_post_time=$lpt status=$status\n";
    } else {
        echo "topic=$tid NO TRACKING RECORD\n";
    }
}

echo "\n=== forums_track for bot ===\n";
$r = $db->query("SELECT forum_id, mark_time, FROM_UNIXTIME(mark_time) as read_at FROM phpbb_forums_track WHERE user_id = 6418 ORDER BY mark_time DESC LIMIT 5");
while ($row = $r->fetch_assoc()) {
    echo "forum={$row['forum_id']} read_at={$row['read_at']}\n";
}
