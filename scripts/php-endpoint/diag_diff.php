<?php
ob_implicit_flush(true);

$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo "DB connect error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

$cutoff = time() - (7 * 24 * 3600);

// A: newest non-bot topic in last 7d, vis=0 (appears in Active Topics)
$rA = $db->query("SELECT topic_id FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 0 AND topic_last_poster_id != 1581 ORDER BY topic_last_post_time DESC LIMIT 1");
$rowA = $rA->fetch_assoc();
$idA = $rowA ? (int)$rowA['topic_id'] : 0;

// B: newest bot topic, vis=0
$rB = $db->query("SELECT topic_id FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 0 AND topic_last_poster_id = 1581 ORDER BY topic_last_post_time DESC LIMIT 1");
$rowB = $rB->fetch_assoc();
$idB = $rowB ? (int)$rowB['topic_id'] : 0;

echo "Comparing WORKING topic A=$idA vs BOT topic B=$idB\n\n";

$tA = $db->query("SELECT * FROM phpbb_topics WHERE topic_id = $idA")->fetch_assoc();
$tB = $db->query("SELECT * FROM phpbb_topics WHERE topic_id = $idB")->fetch_assoc();

echo "--- Column diffs (topics table) ---\n";
foreach ($tA as $col => $valA) {
    $valB = isset($tB[$col]) ? $tB[$col] : null;
    if ($valA !== $valB && !in_array($col, array('topic_id','topic_title','topic_first_poster_name','topic_last_poster_name','topic_last_post_subject','topic_first_poster_colour','topic_last_poster_colour'))) {
        echo "$col: A=[" . var_export($valA, true) . "] B=[" . var_export($valB, true) . "]\n";
    }
}

echo "\n--- last_post_id integrity ---\n";
foreach (array($idA, $idB) as $id) {
    $t = $db->query("SELECT topic_last_post_id, topic_posts_approved, topic_posts_unapproved, topic_posts_softdeleted FROM phpbb_topics WHERE topic_id = $id")->fetch_assoc();
    $lpid = (int)$t['topic_last_post_id'];
    $pr = $db->query("SELECT post_id, post_visibility, poster_id FROM phpbb_posts WHERE post_id = $lpid");
    if ($pr && $pr->num_rows > 0) {
        $p = $pr->fetch_assoc();
        echo "topic=$id lpid=$lpid EXISTS vis={$p['post_visibility']} poster={$p['poster_id']} approved={$t['topic_posts_approved']}\n";
    } else {
        echo "topic=$id lpid=$lpid MISSING!\n";
    }
}

echo "\n--- max post_id in topic vs topic_last_post_id ---\n";
foreach (array($idA, $idB) as $id) {
    $t = $db->query("SELECT topic_last_post_id FROM phpbb_topics WHERE topic_id = $id")->fetch_assoc();
    $mx = $db->query("SELECT MAX(post_id) as m FROM phpbb_posts WHERE topic_id = $id AND post_visibility = 0")->fetch_assoc();
    echo "topic=$id last_post_id={$t['topic_last_post_id']} max_visible_post={$mx['m']}\n";
}

$db->close();
echo "\nDONE\n";
