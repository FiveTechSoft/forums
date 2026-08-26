<?php
ob_implicit_flush(true);

$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo "DB connect error: " . $db->connect_error . "\n";
    exit(1);
}
$db->set_charset('utf8');

$cutoff = time() - (7 * 24 * 3600);

// A: newest NON-bot topic vis=1 in last 7d
$rA = $db->query("SELECT topic_id FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 1 AND topic_last_poster_id != 1581 ORDER BY topic_last_post_time DESC LIMIT 1");
$rowA = $rA->fetch_assoc();
$idA = $rowA ? (int)$rowA['topic_id'] : 0;

// B: newest bot topic vis=1
$rB = $db->query("SELECT topic_id FROM phpbb_topics WHERE topic_moved_id = 0 AND topic_last_post_time > $cutoff AND topic_visibility = 1 AND topic_last_poster_id = 1581 ORDER BY topic_last_post_time DESC LIMIT 1");
$rowB = $rB->fetch_assoc();
$idB = $rowB ? (int)$rowB['topic_id'] : 0;

echo "Comparing WORKING A=$idA vs BOT B=$idB\n\n";

$tA = $db->query("SELECT * FROM phpbb_topics WHERE topic_id = $idA")->fetch_assoc();
$tB = $db->query("SELECT * FROM phpbb_topics WHERE topic_id = $idB")->fetch_assoc();

echo "--- Column diffs ---\n";
$skip = array('topic_id','topic_title','topic_first_poster_name','topic_last_poster_name','topic_last_post_subject','topic_first_poster_colour','topic_last_poster_colour');
foreach ($tA as $col => $valA) {
    $valB = isset($tB[$col]) ? $tB[$col] : null;
    if ($valA !== $valB && !in_array($col, $skip)) {
        $a = strlen($valA) > 60 ? substr($valA,0,60)."..." : $valA;
        $b = strlen($valB) > 60 ? substr($valB,0,60)."..." : $valB;
        echo "$col:\n  A=[" . var_export($a, true) . "]\n  B=[" . var_export($b, true) . "]\n";
    }
}

echo "\n--- Forum info ---\n";
$fA = $db->query("SELECT forum_id, parent_id, forum_parents, forum_flags, forum_password, forum_type FROM phpbb_forums WHERE forum_id = " . $tA['forum_id'])->fetch_assoc();
$fB = $db->query("SELECT forum_id, parent_id, forum_parents, forum_flags, forum_password, forum_type FROM phpbb_forums WHERE forum_id = " . $tB['forum_id'])->fetch_assoc();
echo "A forum {$tA['forum_id']}: parent={$fA['parent_id']} flags={$fA['flags']} pw={$fA['forum_password']} type={$fA['forum_type']} parents_len=" . strlen($fA['forum_parents']) . "\n";
echo "B forum {$tB['forum_id']}: parent={$fB['parent_id']} flags={$fB['flags']} pw={$fB['forum_password']} type={$fB['forum_type']} parents_len=" . strlen($fB['forum_parents']) . "\n";

$db->close();
echo "\nDONE\n";
