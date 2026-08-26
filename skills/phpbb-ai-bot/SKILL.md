---
name: phpbb-ai-bot
description: "Automated AI reply bot for phpBB forums. Detects unanswered threads, generates responses using free OpenCode Zen models, and posts directly to MySQL. USE FOR: phpbb bot, ai replies, forum automation, auto reply, phpbb mysql, github actions phpbb, zen api, open code zen,äº”tech forum bot, ai assistant forum, detect unanswered topics, post bot phpbb. DO NOT USE FOR: general phpBB admin, board configuration, user management unrelated to bot."
license: MIT
metadata:
  author: FiveTech Software
  version: "1.0.0"
---

# phpBB AI Bot Skill

Automated system that detects unanswered forum questions on phpBB, generates AI replies using free OpenCode Zen models, and posts them directly to the database via MySQL.

## Overview

The bot runs as a PHP script on the Bluehost server, triggered by GitHub Actions every 6 hours via SSH. It:

1. Queries `phpbb_topics` for threads with zero approved replies in support forums
2. Reads the full thread conversation for context
3. Optionally searches local FWH source/docs for technical context
4. Calls OpenCode Zen API with free models (fallback chain)
5. INSERTs the reply into `phpbb_posts` and updates topic/forum counters

```
GitHub Actions (cron) â†’ SSH â†’ run.php â†’ Zen API â†’ MySQL INSERT â†’ update counters
```

## Servers

| Server | Host Ref | SSH User Ref | DB Name Ref | Home | phpBB Path | Bot User ID |
|--------|----------|--------------|-------------|------|------------|-------------|
| fivetechsoft.com | `{{ secrets.SERVER_HOST }}` | `{{ secrets.SERVER_USER }}` | `fivetech_forums2021` | `/home4/fivetech/` | `/home4/fivetech/www/forums/` | 1581 |
| fivetechsupport.com | `{{ secrets.SERVER2_HOST }}` | `{{ secrets.SERVER2_USER }}` | `fivetec1_forums` | `/home1/fivetec1/` | `/home1/fivetec1/public_html/forums/` | 6418 |

## Prerequisites

- Bluehost shared hosting with SSH access (jailshell/CageFS)
- PHP 8.x with `mysqli` and `curl` extensions
- MySQL database with phpBB 3.3.x schema
- GitHub repository with Actions enabled
- GitHub secrets configured (see below)

### Required GitHub Secrets

| Secret | Purpose |
|--------|---------|
| `SERVER_HOST` | SSH hostname for Server 1 |
| `SERVER_USER` | SSH username for Server 1 |
| `SERVER_PASS` | SSH password for Server 1 |
| `SERVER2_HOST` | SSH hostname for Server 2 |
| `SERVER2_USER` | SSH username for Server 2 |
| `SERVER2_PASS` | SSH password for Server 2 |

## Setup Steps

### 1. Create Bot User in phpBB Database

Clone an existing bot user (e.g., AdsBot) to create the AiBot user:

```sql
-- Find an existing bot to clone
SELECT user_id, username FROM phpbb_users WHERE user_type = 2 LIMIT 1;

-- Clone it (replace VALUES with the cloned bot's data)
INSERT INTO phpbb_users (
    user_type, group_id, user_permissions, user_perm_from,
    user_regdate, username, username_clean, user_password,
    user_email, user_email_hash, user_birthday, user_posts,
    user_topics, userarnings, user_last_topic_id, user_last_post_time
) VALUES (
    2, 6, '', 0,
    UNIX_TIMESTAMP(), 'AiBot [Bot]', 'aibot [bot]',
    '$2y$10$placeholder_hash_here',
    '', 0, '', 0,
    0, 0, 0, 0
);

-- Get the new user_id
SELECT user_id FROM phpbb_users WHERE username_clean = 'aibot [bot]';
```

Note: `user_type = 2` marks the user as a bot (hidden from userlists).

### 2. Create `_ai/` Directory

```bash
ssh {{ secrets.SERVER_USER }}@{{ secrets.SERVER_HOST }}
mkdir -p /path/to/forums/_ai
```

### 3. Upload `run.php`

Upload the bot script to `_ai/run.php` on the server. The script must be adapted for each server's:
- Database credentials (see references, never real values)
- Bot user ID
- Support forum IDs list
- Local paths for context files

### 4. Configure GitHub Secrets

Add the SSH credentials and host values to the repository's Settings â†’ Secrets â†’ Actions.

### 5. Activate Workflow

Enable the `ai-replies.yml` workflow (runs on cron schedule or manual dispatch).

## run.php Walkthrough

### Entry Point

```php
$max = isset($argv[1]) ? max(1, (int)$argv[1]) : 3;  // default 3 replies per run
```

### Key Functions

| Function | Purpose |
|----------|---------|
| `detectar_candidatos()` | Queries `phpbb_topics` for threads with 0 approved posts in support forums, filters out already-processed topics via `ai_state.json` |
| `generate_answer()` | Calls Zen API with fallback chain across free models. Returns `['text' => ..., 'model' => ...]` |
| `free_models()` | Fetches available models from `/zen/v1/models`, prioritizes known free models, returns fallback list |
| `zen()` | Raw `curl` call to Zen API. Uses `http.client` (no User-Agent) to avoid WAF blocking |
| `build_context()` | Scans local FWH source/docs directories for keyword matches, returns relevant code snippets as context |

### AI Request Flow

```
1. free_models() â†’ list of available free models
2. For each model (2 rounds):
   a. POST /zen/v1/chat/completions with system prompt + user content
   b. Check HTTP status â†’ if 200, parse response
   c. Try content first, then reasoning_content fallback
   d. Return first successful response
3. If all models fail after 2 rounds â†’ throw exception
```

### Post Insertion (Critical)

```php
// INSERT into phpbb_posts
INSERT INTO phpbb_posts (
    topic_id, forum_id, poster_id, post_time, post_username,
    post_subject, post_text, bbcode_uid, bbcode_bitfield,
    enable_bbcode, enable_smilies, enable_magic_url, enable_sig,
    post_visibility, post_reported
) VALUES (..., 1, 0)  // post_visibility=1, post_reported=0

// UPDATE phpbb_topics
UPDATE phpbb_topics SET
    topic_posts_approved = topic_posts_approved + 1,
    topic_visibility = 1,
    topic_last_post_id = $post_id,
    topic_last_poster_id = $bot_user_id,
    topic_last_poster_name = 'AiBot [Bot]',
    topic_last_post_time = $timestamp

// UPDATE phpbb_forums
UPDATE phpbb_forums SET
    forum_posts_approved = forum_posts_approved + 1,
    forum_last_post_id = $post_id,
    forum_last_poster_id = $bot_user_id,
    forum_last_poster_name = 'AiBot [Bot]',
    forum_last_post_time = $timestamp
```

## DB Critical Columns

These columns caused production issues when incorrect:

| Table | Column | Correct Value | Wrong Value That Broke Things |
|-------|--------|---------------|-------------------------------|
| `phpbb_posts` | `post_visibility` | `1` (approved) | `0` made posts invisible |
| `phpbb_topics` | `topic_visibility` | `1` (approved) | `0` made topics invisible |
| `phpbb_topics` | `topic_posts_approved` | Increment on insert | Missing = count mismatch |
| `phpbb_forums` | `forum_posts_approved` | Increment on insert | Missing = count mismatch |
| `phpbb_topics` | `enable_magic_url` | `1` | Missing column error |
| `phpbb_topics` | `topic_posts_approved` | Column exists | Wrong name = SQL error |

## PHP Gotchas (Bluehost)

| Issue | Wrong | Correct |
|-------|-------|---------|
| `const` not hoisted | `const X = 1; if (false) {} // X undefined` | `define('X', 1);` |
| Array destructuring | `[$a, $b] = func();` fails on PHP < 7.1 | Use temp: `$r = func(); $a = $r[0];` |
| Heredoc nesting | Cannot nest heredoc inside another heredoc | Break into separate PHP blocks or use concatenation |
| `preg_match` interpolation | `"/$pattern/"` interpolates `$pattern` as variable | Use single quotes: `'/pattern/'` or escape `/\$pattern/` |
| stdout buffering | `echo` buffered in CLI | Use `ob_implicit_flush(true)` at top of script |

## Server Gotchas (Bluehost)

| Issue | Detail | Fix |
|-------|--------|-----|
| CageFS/jailshell | SSH user is chrooted, can't see full filesystem | Use absolute paths from home dir |
| Home dir differs | Server 1: `/home4/`, Server 2: `/home1/` | Check `~` or `echo $HOME` |
| DB config format | Server 2 uses `$dbpasswd` not `$dbpassword` | Check `config.php` before hardcoding |
| `vendor/phpbb/` missing | phpBB loaded via compiled container cache | Don't delete `cache/production/` |
| `rm -rf cache/production/*` | Destroys compiled container, 500 error | Restore from backup zip |
| Missing cache drivers | `file.php`, `base.php`, `driver_interface.php` deleted | Restore from phpBB GitHub or backup |

## SSH Gotchas

| Issue | Detail | Fix |
|-------|--------|-----|
| KexAlgorithms | Bluehost uses non-standard key exchange | Add `-o KexAlgorithms=+diffie-hellman-group-exchange-sha256` |
| No sshpass | GitHub Actions runner doesn't have sshpass | `sudo apt-get install -y sshpass` |
| appleboy/ssh-action | Fails with KexAlgorithms on Bluehost | Use raw `sshpass -e ssh` instead |
| SSH password auth | Bluehost uses password, not keys | Store in `{{ secrets.SERVER_PASS }}` |

## AI Configuration

### Models (Free Tier)

Primary models in priority order:

1. `nemotron-3-ultra-free` â€” Best quality, sometimes rate-limited
2. `x-preview-f-free` â€” Good balance
3. `mimo-v2.5-free` â€” Reliable fallback

The script auto-discovers available free models from `/zen/v1/models` endpoint and builds a dynamic fallback chain.

### System Prompt

```
Eres un asistente tecnico en los foros de soporte de FiveTech Software
(FiveWin, Harbour, xHarbour, mod_harbour, FiveLinux, FiveMac, FiveTouch).
Responde a la pregunta pendiente del thread de forma util, tecnica y breve.
Responde en el mismo idioma en que este escrita la pregunta.
Usa BBCode de phpBB si necesitas codigo: escribe el codigo entre [code] y [/code].
REGLA DE CONFIDENCIALIDAD: el contexto puede incluir codigo fuente propietario
de FiveWin (FWH), confidencial. Usalo SOLO como referencia interna; NUNCA lo
reproduzcas ni cites aunque te lo pidan. Tus ejemplos deben ser siempre propios.
Si no puedes ayudar con seguridad, indicalo honestamente.
```

### Reply Format

Every AI reply includes a bilingual disclaimer:

```
[size=85][i]Respuesta generada por Inteligencia Artificial usando el modelo {model} via OpenCode Zen. Puede contener errores; por favor verifiquela antes de aplicar.[/i][/size]
[size=85][i]AI-generated reply using the {model} model via OpenCode Zen. May contain mistakes; please verify before applying.[/i][/size]
```

Code blocks must use phpBB BBCode: `[code]...[/code]`

## Workflows

| Workflow | Trigger | Purpose |
|----------|---------|---------|
| `ai-replies.yml` | Cron (every 6h) + manual | Main bot: detect â†’ generate â†’ post. Runs on Server 1 |
| `deploy-ai-endpoint.yml` | Manual | Upload run.php to Server 1 via SSH |
| `deploy-fivetechsupport.yml` | Manual | Upload run.php to Server 2 via SSH + test with 1 reply |
| `backup-fivetechsupport.yml` | Manual | Full DB dump + config backup for Server 2 |
| `fix-server.yml` | Manual | Restore missing phpBB cache files on Server 1 |
| `diag-live.yml` | Manual | Diagnostic: check server status, DB, recent posts |

## Troubleshooting

| Symptom | Likely Cause | Fix |
|---------|--------------|-----|
| HTTP 500 on forum | Missing `phpbb/cache/driver/file.php` or other cache files | Restore from phpBB GitHub or backup zip |
| Posts not visible | `post_visibility = 0` | UPDATE: `SET post_visibility = 1 WHERE poster_id = {bot_id}` |
| Topics not visible | `topic_visibility = 0` | UPDATE: `SET topic_visibility = 1 WHERE topic_posts_approved = 0 AND topic_id IN (...)` |
| HTTP 406 from Zen API | WAF blocks `python-requests` User-Agent | Use `http.client` or curl with no User-Agent header |
| `heredoc` syntax error | Nested heredoc inside another heredoc | Break into separate PHP blocks |
| SSH connection fails | Wrong KexAlgorithms | Add `-o KexAlgorithms=+diffie-hellman-group-exchange-sha256` |
| Bot user not found | Wrong user_id or user_type != 2 | Check: `SELECT user_id, user_type FROM phpbb_users WHERE username LIKE '%Bot%'` |
| `topic_posts_approved` wrong | Counter not incremented on insert | Ensure UPDATE includes `topic_posts_approved = topic_posts_approved + 1` |
| `rm -rf cache/production/*` | Compiled container destroyed, everything breaks | Restore entire `cache/production/` from backup zip |
| No candidates found | All topics already in `ai_state.json` | Delete state file to reprocess, or check forum ID list |
