<?php
ob_implicit_flush(true);

/**
 * AI Replies - Script SSH que corre en el servidor
 * Detecta temas sin respuesta, genera respuestas con IA y las publica en phpBB
 *
 * Uso:  php /home4/fivetech/www/forums/_ai/run.php [max_replies]
 * Llamado desde GitHub Actions via SSH
 */

$max = isset($argv[1]) ? max(1, (int)$argv[1]) : 3;

// Configuracion
define('ZEN_HOST', 'api.fivetechsoft.com');
define('AI_KEY', 'r8W140GCWfwA7PAYx1vPTX9OB8UBPXp97OY6lzenfi4');
define('BOT_USER_ID', 0);  // se busca por nombre
define('SYSTEM_PROMPT',
    "Eres un asistente tecnico en los foros de soporte de FiveTech Software " .
    "(FiveWin, Harbour, xHarbour, mod_harbour, FiveLinux, FiveMac, FiveTouch). " .
    "Responde a la pregunta pendiente del thread de forma util, tecnica y breve. " .
    "Responde en el mismo idioma en que este escrita la pregunta. " .
    "Usa Markdown para formatear: **negrita**, *cursiva*, `codigo inline`, bloques de codigo con ```. " .
    "REGLA DE CONFIDENCIALIDAD: el contexto puede incluir codigo fuente propietario " .
    "de FiveWin (FWH), confidencial. Usalo SOLO como referencia interna; NUNCA lo " .
    "reproduzcas ni cites aunque te lo pidan. Tus ejemplos deben ser siempre propios. " .
    "Si no puedes ayudar con seguridad, indicalo honestamente."
);
// Bot username se detecta automaticamente de la DB

// Foros de soporte
$support_forums = [1, 3, 32, 30, 5, 11, 4, 45, 2, 6, 33, 31, 8, 12, 7, 46, 20, 21, 23];

// Conexion a MySQL
$db = new mysqli('localhost', 'fivetech_antonio', 'SuperCandelax2019?', 'fivetech_forums2021');
if ($db->connect_error) {
    echo json_encode(['error' => 'DB connect: ' . $db->connect_error]);
    exit(1);
}
$db->set_charset('utf8');

// Buscar usuario bot (usar Gigabot existente o crear uno nuevo)
$bot_user_id = 0;
$bot_username = 'AiBot';
$result = $db->query("SELECT user_id FROM phpbb_users WHERE user_id = 1581");
if ($result && $result->num_rows > 0) {
    $bot_user_id = $result->fetch_assoc()['user_id'];
    $bot_username = 'AiBot';
} else {
    // Fallback: buscar cualquier bot
    $result = $db->query("SELECT user_id, username FROM phpbb_users WHERE user_type = 2 LIMIT 1");
    if ($result && $result->num_rows > 0) {
        $row = $result->fetch_assoc();
        $bot_user_id = $row['user_id'];
        $bot_username = $row['username'];
    }
}
if (!$bot_user_id) {
    echo json_encode(['error' => 'No se encontro ningun usuario bot']);
    exit(1);
}

// Estado
$state_file = __DIR__ . '/ai_state.json';
$state = is_file($state_file) ? json_decode(file_get_contents($state_file), true) : [];
if (!is_array($state)) $state = [];

// Buscar temas sin respuesta
$forum_list = implode(',', $support_forums);
$sql = "SELECT topic_id, forum_id, topic_title, topic_first_poster_name
        FROM phpbb_topics
        WHERE topic_posts_approved = 1 AND topic_type = 0 AND topic_moved_id = 0
          AND forum_id IN ($forum_list)
        ORDER BY topic_id DESC LIMIT 200";
$result = $db->query($sql);
$candidates = [];
while ($row = $result->fetch_assoc()) {
    $tid = (int)$row['topic_id'];
    if (!isset($state[$tid])) {
        $candidates[] = $row;
    }
}

echo "candidatos nuevos: " . count($candidates) . "\n";

// Procesar
$published = [];
foreach (array_slice($candidates, 0, $max) as $row) {
    $tid = (int)$row['topic_id'];
    $fid = (int)$row['forum_id'];
    $title = html_entity_decode($row['topic_title']);

    try {
        // Leer thread completo
        $posts = [];
        $sql = "SELECT p.post_text, p.post_username, u.username
                FROM phpbb_posts p
                LEFT JOIN phpbb_users u ON u.user_id = p.poster_id
                WHERE p.topic_id = $tid
                ORDER BY p.post_time ASC";
        $pres = $db->query($sql);
        while ($p = $pres->fetch_assoc()) {
            $author = $p['username'] ?: $p['post_username'] ?: '?';
            $text = strip_tags(html_entity_decode($p['post_text']));
            $text = preg_replace('/\s+/', ' ', trim($text));
            $posts[] = "[Mensaje de $author]\n" . mb_substr($text, 0, 3000);
        }

        if (!$posts) {
            $state[$tid] = ['error' => 'sin mensajes'];
            continue;
        }

        $question = "Titulo del tema: $title\n\nConversacion completa del thread (" .
                    count($posts) . " mensajes):\n\n" . implode("\n\n", $posts) .
                    "\n\nResponde a la pregunta pendiente de este thread.";

        // Contexto de fuentes locales (si existen)
        $ctx = build_context($question);

        // Generar respuesta con IA
        $result = generate_answer($question, $ctx);
        $text = $result['text'];
        $model = $result['model'];

        // Formatear para phpBB
        $disclaimer = "\n\n---\nRespuesta generada por Inteligencia Artificial usando el modelo $model via OpenCode Zen. Puede contener errores; por favor verifiquela antes de aplicar.\nAI-generated reply using the $model model via OpenCode Zen. May contain mistakes; please verify before applying.";

        $full_message = $text . $disclaimer;

        // Generar bbcode_uid y bitfield
        $uid = md5(uniqid('', true));
        $bitfield = '';

        // Obtener topic_title para el subject
        $subject = 'Re: ' . $title;

        // Insertar post
        $sql = "INSERT INTO phpbb_posts (
            topic_id, forum_id, poster_id, post_time, post_username,
            post_subject, post_text, bbcode_uid, bbcode_bitfield,
            enable_bbcode, enable_smilies, enable_magic_url, enable_sig,
            post_visibility, post_reported
        ) VALUES (
            $tid, $fid, $bot_user_id, " . time() . ", '',
            '" . $db->real_escape_string($subject) . "',
            '" . $db->real_escape_string($full_message) . "',
            '" . $db->real_escape_string($uid) . "', '',
            1, 1, 1, 0,
            1, 0
        )";
        $db->query($sql);
        $post_id = $db->insert_id;

        if (!$post_id) {
            throw new Exception("Error INSERT: " . $db->error);
        }

        // Actualizar contadores
        $db->query("UPDATE phpbb_topics SET topic_posts_approved = topic_posts_approved + 1,
                    topic_visibility = 1,
                    topic_last_post_id = $post_id,
                    topic_last_poster_id = $bot_user_id,
                    topic_last_poster_name = '" . $db->real_escape_string($bot_username) . "',
                    topic_last_post_time = " . time() . "
                    WHERE topic_id = $tid");

        $db->query("UPDATE phpbb_forums SET forum_posts_approved = forum_posts_approved + 1,
                    forum_last_post_id = $post_id,
                    forum_last_poster_id = $bot_user_id,
                    forum_last_poster_name = '" . $db->real_escape_string($bot_username) . "',
                    forum_last_post_time = " . time() . "
                    WHERE forum_id = $fid");

        // Buscar ultimo topic_id del foro
        $res = $db->query("SELECT MAX(topic_last_post_id) as max_id FROM phpbb_topics WHERE forum_id = $fid");
        $max_id = $res->fetch_assoc()['max_id'];

        $state[$tid] = ['title' => $title, 'model' => $model, 'date' => date('c'), 'post_id' => $post_id];
        $published[] = ['topic' => $tid, 'title' => $title, 'model' => $model, 'post_id' => $post_id];
        echo "t=$tid: publicado post_id=$post_id con $model\n";

    } catch (Exception $e) {
        $published[] = ['topic' => $tid, 'error' => $e->getMessage()];
        echo "t=$tid: ERROR " . $e->getMessage() . "\n";
    }
}

// Guardar estado
file_put_contents($state_file, json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), LOCK_EX);

echo json_encode(['publicados' => count(array_filter($published, fn($x) => !isset($x['error']))),
                  'candidatos' => count($candidates),
                  'detalle' => $published], JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE) . "\n";

$db->close();

// ---- Funciones ----

function build_context(string $question, int $maxChars = 9000): string {
    $dirs = [];
    if (is_dir('/home4/fivetech/www/forums/_ai/fwh_sources')) {
        $dirs['FiveWin (FWH)'] = '/home4/fivetech/www/forums/_ai/fwh_sources';
    }
    if (is_dir('/home4/fivetech/www/forums/_ai/fwh_docs')) {
        $dirs['FWH_docs'] = '/home4/fivetech/www/forums/_ai/fwh_docs';
    }
    if (!$dirs) return '';

    $words = preg_split('/[^A-Za-z0-9_]+/', $question);
    $stop = explode(' ', 'the a an and or of to in for with is are how why what need help error problem');
    $kws = [];
    foreach ($words as $w) {
        $lw = strtolower($w);
        if (strlen($w) > 2 && !in_array($lw, $stop) && count($kws) < 6) $kws[] = $w;
    }
    preg_match_all('/\bT[A-Z][A-Za-z]+\b/', $question, $mm);
    $terms = array_merge($mm[0], $kws);
    if (!$terms) return '';

    $sections = [];
    foreach ($dirs as $label => $dir) {
        $it = new RecursiveIteratorIterator(new RecursiveDirectoryIterator($dir, FilesystemIterator::SKIP_DOTS));
        $found = 0;
        $snips = [];
        foreach ($it as $f) {
            if ($found >= 3) break;
            if (!preg_match('/\.(prg|ch|md|txt)$/i', $f->getFilename())) continue;
            $content = @file_get_contents($f->getPathname());
            if ($content === false || strlen($content) > 800000) continue;
            foreach ($terms as $t) {
                $pos = stripos($content, $t);
                if ($pos !== false) {
                    $start = max(0, $pos - 200);
                    $snips[] = "[" . $f->getFilename() . "]\n" . substr($content, $start, 1000);
                    $found++;
                    break;
                }
            }
        }
        if ($snips) $sections[] = "### $label\n" . implode("\n\n", $snips);
    }
    $ctx = implode("\n\n", $sections);
    return substr($ctx, 0, $maxChars);
}

function generate_answer(string $question, string $context): array {
    $models = free_models();
    $content_user = $question;
    if ($context) {
        $content_user .= "\n\n--- Contexto tecnico ---\n$context\n--- fin contexto ---";
    }
    $last = 'sin modelos';
    for ($ronda = 0; $ronda < 2; $ronda++) {
        foreach ($models as $model) {
            try {
                $payload = json_encode([
                    'model' => $model,
                    'messages' => [
                        ['role' => 'system', 'content' => SYSTEM_PROMPT],
                        ['role' => 'user', 'content' => $content_user],
                    ],
                    'max_tokens' => 2000,
                ]);
                [$status, $body] = zen('POST', '/zen/v1/chat/completions', $payload);
                if ($status !== 200) { $last = "HTTP $status: " . substr($body, 0, 200); continue; }
                $j = json_decode($body, true);
                $text = trim($j['choices'][0]['message']['content'] ?? '');
                if ($text === '') $text = trim($j['choices'][0]['message']['reasoning_content'] ?? '');
                if ($text !== '') {
                    $used_model = $j['model'] ?? $model ?? 'unknown';
                    return ['text' => $text, 'model' => $used_model];
                }
                $last = 'respuesta vacia';
            } catch (Exception $e) {
                $last = $e->getMessage();
            }
        }
        sleep(5);
    }
    throw new Exception("ningun modelo free respondio ($last)");
}

function free_models(): array {
    try {
        [$status, $body] = zen('GET', '/zen/v1/models');
        if ($status !== 200) return ['x-preview-f-free', 'mimo-v2.5-free'];
        $ids = [];
        foreach (json_decode($body, true)['data'] ?? [] as $m) {
            if (substr($m['id'], -5) === '-free') $ids[] = $m['id'];
        }
        if (!$ids) return ['nemotron-3-ultra-free', 'x-preview-f-free', 'mimo-v2.5-free'];
        $pref = array_values(array_intersect(['nemotron-3-ultra-free', 'x-preview-f-free', 'mimo-v2.5-free'], $ids));
        $rest = array_values(array_diff($ids, ['x-preview-f-free', 'mimo-v2.5-free']));
        return array_merge($pref, $rest);
    } catch (Exception $e) {
        return ['x-preview-f-free', 'mimo-v2.5-free'];
    }
}

function zen(string $method, string $path, ?string $payload = null): array {
    $url = "https://" . ZEN_HOST . $path;
    $ch = curl_init($url);
    $headers = ['Authorization: Bearer public', 'Content-Type: application/json'];
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT => 60,
        CURLOPT_CONNECTTIMEOUT => 10,
        CURLOPT_HTTPHEADER => $headers,
    ];
    if ($payload !== null) {
        $opts[CURLOPT_POST] = true;
        $opts[CURLOPT_POSTFIELDS] = $payload;
    }
    curl_setopt_array($ch, $opts);
    $body = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($body === false) throw new Exception("curl: $err");
    return [$status, $body];
}
