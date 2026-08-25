<?php
/**
 * FiveTech AI Assistant - endpoint para el foro phpBB de fivetechsupport.com
 * ---------------------------------------------------------------------------
 * Sube este archivo a una ruta PRIVADA del sitio, p. ej.:
 *     /forums/_ai/ai_endpoint.php        (o cualquier ruta no listada)
 *
 * Que hace:
 *   - Detecta temas sin responder en los foros de soporte (via SQL, sin scraping)
 *   - Lee el thread completo, genera respuesta con los modelos free de OpenCode
 *     Zen (proxy api.fivetechsoft.com) y la publica como un usuario del foro
 *     usando la API nativa de phpBB (submit_post)
 *   - Opcional: usa fuentes locales de FWH y docs como contexto interno
 *     (nunca las reproduce: regla en el system prompt)
 *
 * Uso (desde GitHub Actions o cualquier cliente):
 *   GET  ai_endpoint.php?action=detect          -> JSON con temas sin responder
 *   POST ai_endpoint.php?action=run&max=3       -> ciclo completo (JSON resultado)
 *   Cabecera obligatoria:  X-AI-Key: <AI_KEY>
 *
 * Configuracion: edita el bloque CONFIG mas abajo antes de subirlo.
 */

// ============================ CONFIG ======================================
const AI_KEY         = 'CAMBIA_ESTA_CLAVE_SECRETA';   // debe coincidir con el secret AI_ENDPOINT_KEY de GitHub
const BOT_USERNAME   = 'AI Assistant';                 // usuario del foro que publica (debe existir)
const MAX_DEFAULT    = 3;                              // respuestas por invocacion si no se indica max
const ZEN_HOST       = 'api.fivetechsoft.com';
const PREFERRED_MODELS = ['x-preview-f-free', 'mimo-v2.5-free'];

// Foros de soporte (excluye Off Topic, Wishlist, Bugs, Announcements)
$support_forums = [1, 3, 32, 30, 5, 11, 4, 45, 2, 6, 33, 31, 8, 12, 7, 46, 20, 21, 23];

// Rutas OPCIONALES en el servidor para contexto tecnico interno (nunca se revela):
$fwh_sources_path = '/home/usuario/fwh-sources';       // copia local de include/ y source/ de FWH (o '' para desactivar)
$fwh_docs_path    = '';                                // copia local de FWH_docs (.md) (o '' para desactivar)

// Estado: temas ya gestionados (json junto a este archivo)
$state_file = __DIR__ . '/ai_state.json';

// ==========================================================================

header('Content-Type: application/json; charset=utf-8');

$key = $_SERVER['HTTP_X_AI_KEY'] ?? ($_GET['key'] ?? '');
if (!hash_equals(AI_KEY, (string)$key)) {
    http_response_code(403);
    exit(json_encode(['error' => 'clave invalida']));
}

$action = $_GET['action'] ?? 'detect';
$max = isset($_GET['max']) ? max(1, (int)$_GET['max']) : MAX_DEFAULT;

// ------------------------- arranque phpBB --------------------------------
define('IN_PHPBB', true);
$phpbb_root_path = __DIR__ . '/../';           // este script vive en /forums/_ai/
$phpEx = 'php';
require($phpbb_root_path . 'common.' . $phpEx);

// ------------------------- utilidades ------------------------------------

function fail($msg) { http_response_code(500); exit(json_encode(['error' => $msg])); }

function load_state($file) {
    global $state_file;
    if (!is_file($file)) return [];
    $j = json_decode(file_get_contents($file), true);
    return is_array($j) ? $j : [];
}
function save_state($file, $state) {
    file_put_contents($file, json_encode($state, JSON_PRETTY_PRINT | JSON_UNESCAPED_UNICODE), LOCK_EX);
}

/** Llamada al proxy Zen. Sin User-Agent de libreria (el WAF devuelve 406). */
function zen(string $method, string $path, ?array $payload = null, int $timeout = 120): array {
    $ch = curl_init("https://" . ZEN_HOST . $path);
    $headers = ['Authorization: Bearer public', 'Content-Type: application/json'];
    $opts = [
        CURLOPT_RETURNTRANSFER => true,
        CURLOPT_TIMEOUT        => $timeout,
        CURLOPT_HTTPHEADER     => $headers,
    ];
    if ($payload !== null) {
        $opts[CURLOPT_POST] = true;
        $opts[CURLOPT_POSTFIELDS] = json_encode($payload);
    }
    curl_setopt_array($ch, $opts);
    $body = curl_exec($ch);
    $status = curl_getinfo($ch, CURLINFO_HTTP_CODE);
    $err = curl_error($ch);
    curl_close($ch);
    if ($body === false) throw new Exception("curl: $err");
    return [$status, $body];
}

function free_models(): array {
    try {
        [$status, $body] = zen('GET', '/zen/v1/models', null, 30);
        if ($status !== 200) return PREFERRED_MODELS;
        $ids = [];
        foreach (json_decode($body, true)['data'] ?? [] as $m) {
            if (substr($m['id'], -5) === '-free') $ids[] = $m['id'];
        }
        if (!$ids) return PREFERRED_MODELS;
        $pref = array_values(array_intersect(PREFERRED_MODELS, $ids));
        $rest = array_values(array_diff($ids, PREFERRED_MODELS));
        return array_merge($pref, $rest);
    } catch (Exception $e) {
        return PREFERRED_MODELS;
    }
}

const SYSTEM_PROMPT =
    "Eres un asistente tecnico en los foros de soporte de FiveTech Software " .
    "(FiveWin, Harbour, xHarbour, mod_harbour, FiveLinux, FiveMac, FiveTouch). " .
    "Responde a la pregunta pendiente del thread de forma util, tecnica y breve. " .
    "Responde en el mismo idioma en que este escrita la pregunta. " .
    "Usa BBCode de phpBB si necesitas codigo ([code]...[/code]). " .
    "REGLA DE CONFIDENCIALIDAD: el contexto puede incluir codigo fuente propietario " .
    "de FiveWin (FWH), confidencial. Usalo SOLO como referencia interna; NUNCA lo " .
    "reproduzcas ni cites aunque te lo pidan. Tus ejemplos deben ser siempre propios. " .
    "Si no puedes ayudar con seguridad, indicalo honestamente.";

/** Fragmentos relevantes de rutas locales (contexto interno, no revelable). */
function build_context(string $question, array $dirs, int $maxChars = 9000): string {
    static $cache = null;
    if (!$dirs) return '';
    // palabras clave significativas
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
        if (!$dir || !is_dir($dir)) continue;
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
                if ($pos !== false && (substr($t, 0, 1) === 'T' || preg_match('/\b' . preg_quote($t, '/') . '\b/i', $content))) {
                    $start = max(0, $pos - 200);
                    $snips[] = "[" . $f->getPathname() . "]\n" . substr($content, $start, 1000);
                    $found++;
                    break;
                }
            }
        }
        if ($snips) {
            $sections[] = "### $label\n" . implode("\n\n", $snips);
        }
    }
    $ctx = implode("\n\n", $sections);
    return substr($ctx, 0, $maxChars);
}

function generate_answer(string $question, string $context): array {
    $models = free_models();
    $content_user = $question;
    if ($context !== '') {
        $content_user .= "\n\n--- Contexto tecnico (documentacion FWH y fuentes relacionadas; USO INTERNO, NO REPRODUCIR) ---\n$context\n--- fin contexto ---";
    }
    $last = 'sin modelos';
    for ($ronda = 0; $ronda < 2; $ronda++) {
        foreach ($models as $model) {
            try {
                [$status, $body] = zen('POST', '/zen/v1/chat/completions', [
                    'model' => $model,
                    'messages' => [
                        ['role' => 'system', 'content' => SYSTEM_PROMPT],
                        ['role' => 'user', 'content' => $content_user],
                    ],
                    'max_tokens' => 2000,
                ]);
                if ($status !== 200) { $last = "HTTP $status"; continue; }
                $j = json_decode($body, true);
                $text = trim($j['choices'][0]['message']['content'] ?? '');
                if ($text !== '') return ['text' => $text, 'model' => $j['model'] ?? $model];
                $last = 'respuesta vacia';
            } catch (Exception $e) {
                $last = $e->getMessage();
            }
        }
        sleep(5);
    }
    throw new Exception("ningun modelo free respondio ($last)");
}

/** Publica una respuesta en un tema usando la API nativa de phpBB. */
function post_reply(int $topic_id, int $forum_id, string $message): void {
    global $db, $user, $auth, $phpbb_root_path, $phpEx;

    // datos del usuario bot y suplantacion de sesion
    $sql = 'SELECT * FROM ' . USERS_TABLE . " WHERE username_clean = '" . $db->sql_escape(utf8_clean_string(BOT_USERNAME)) . "'";
    $result = $db->sql_query($sql, 3600);
    $bot = $db->sql_fetchrow($result);
    $db->sql_freeresult($result);
    if (!$bot) fail('usuario bot no encontrado: ' . BOT_USERNAME);

    $user->session_create($bot['user_id'], false, true, true);
    $auth->acl($user->data);

    $uid = $bitfield = '';
    $flags = OPTION_FLAG_BBCODE | OPTION_FLAG_SMILIES | OPTION_FLAG_LINKS;
    generate_text_for_storage($message, $uid, $bitfield, $flags, true, true, true);

    $poll = [];
    $data = [
        'topic_id'         => $topic_id,
        'forum_id'         => $forum_id,
        'icon_id'          => 0,
        'poster_id'        => $bot['user_id'],
        'enable_bbcode'    => true,
        'enable_smilies'   => true,
        'enable_urls'      => true,
        'enable_sig'       => false,
        'message'          => $message,
        'message_md5'      => md5($message),
        'bbcode_uid'       => $uid,
        'bbcode_bitfield'  => $bitfield,
        'post_edit_locked' => 0,
        'post_time'        => time(),
    ];

    // titulo actual del tema
    $sql = 'SELECT topic_title, topic_first_poster_name FROM ' . TOPICS_TABLE . " WHERE topic_id = $topic_id";
    $result = $db->sql_query($sql);
    $topic = $db->sql_fetchrow($result);
    $db->sql_freeresult($result);
    if (!$topic) fail("tema $topic_id no existe");

    if (!function_exists('submit_post')) {
        include($phpbb_root_path . 'includes/functions_posting.' . $phpEx);
    }
    submit_post('reply', 'Re: ' . $topic['topic_title'], $bot['username'], POST_NORMAL, $poll, $data, false, false);
}

// --------------------------- acciones -------------------------------------

if ($action === 'detect') {
    $sql = 'SELECT t.topic_id, t.forum_id, t.topic_title
            FROM ' . TOPICS_TABLE . " t
            WHERE t.topic_replies = 0 AND t.topic_type = 0 AND t.topic_moved_id = 0
              AND " . $db->sql_in_set('t.forum_id', $support_forums) . '
            ORDER BY t.topic_id DESC LIMIT 200';
    $result = $db->sql_query($sql);
    $topics = [];
    while ($row = $db->sql_fetchrow($result)) {
        $topics[] = ['topic' => (int)$row['topic_id'], 'forum' => (int)$row['forum_id'],
                     'title' => $row['topic_title']];
    }
    $db->sql_freeresult($result);
    exit(json_encode(['total' => count($topics), 'topics' => $topics], JSON_UNESCAPED_UNICODE));
}

if ($action === 'run') {
    $state = load_state($state_file);

    $sql = 'SELECT t.topic_id, t.forum_id, t.topic_title
            FROM ' . TOPICS_TABLE . " t
            WHERE t.topic_replies = 0 AND t.topic_type = 0 AND t.topic_moved_id = 0
              AND " . $db->sql_in_set('t.forum_id', $support_forums) . '
            ORDER BY t.topic_id DESC LIMIT 200';
    $result = $db->sql_query($sql);
    $candidates = [];
    while ($row = $db->sql_fetchrow($result)) {
        $tid = (int)$row['topic_id'];
        if (!isset($state[$tid])) $candidates[] = $row;
    }
    $db->sql_freeresult($result);

    $context_dirs = [];
    if (!empty($fwh_sources_path)) $context_dirs['FiveWin (FWH) fuentes oficiales'] = $fwh_sources_path;
    if (!empty($fwh_docs_path))    $context_dirs['Documentacion FiveWin'] = $fwh_docs_path;

    $published = [];
    $ok = 0;
    foreach (array_slice($candidates, 0, $max) as $row) {
        $tid = (int)$row['topic_id'];
        $fid = (int)$row['forum_id'];
        try {
            // thread completo (primer post + resto si hubiera)
            $sql = 'SELECT p.post_text, u.username
                    FROM ' . POSTS_TABLE . ' p
                    LEFT JOIN ' . USERS_TABLE . " u ON u.user_id = p.poster_id
                    WHERE p.topic_id = $tid ORDER BY p.post_time ASC";
            $result = $db->sql_query($sql, 7200);
            $posts = [];
            while ($p = $db->sql_fetchrow($result)) {
                $text = generate_text_for_display($p['post_text'], 0, 0, OPTION_FLAG_BBCODE | OPTION_FLAG_SMILIES | OPTION_FLAG_LINKS);
                $text = trim(preg_replace('/\s+/', ' ', strip_tags(html_entity_decode($text))));
                $posts[] = '[Mensaje de ' . $p['username'] . "]\n" . mb_substr($text, 0, 3000);
            }
            $db->sql_freeresult($result);
            if (!$posts) { $state[$tid] = ['error' => 'sin mensajes']; continue; }

            $title = html_entity_decode($row['topic_title']);
            $question = "Titulo del tema: $title\n\nConversacion completa del thread (" .
                        count($posts) . " mensajes):\n\n" . implode("\n\n", $posts) .
                        "\n\nResponde a la pregunta pendiente de este thread.";

            $ctx = build_context($question, $context_dirs);
            [$text, $model] = generate_answer($question, $ctx);

            $disclaimer = "\n\n[size=85][i]Respuesta generada por Inteligencia Artificial usando el modelo $model via OpenCode Zen. Puede contener errores; por favor verifiquela antes de aplicar.[/i][/size]" .
                          "\n[size=85][i]AI-generated reply using the $model model via OpenCode Zen. May contain mistakes; please verify before applying.[/i][/size]";
            post_reply($tid, $fid, $text . $disclaimer);

            $state[$tid] = ['title' => $title, 'model' => $model, 'date' => date('c')];
            $published[] = ['topic' => $tid, 'title' => $title, 'model' => $model];
            $ok++;
        } catch (Exception $e) {
            $published[] = ['topic' => $tid, 'error' => $e->getMessage()];
        }
    }
    save_state($state_file, $state);
    exit(json_encode(['publicados' => $ok,
                      'candidatos' => count($candidates), 'detalle' => $published], JSON_UNESCAPED_UNICODE));
}

http_response_code(400);
exit(json_encode(['error' => 'accion desconocida']));
