"""
Streaming phpBB MySQL dump -> SQLite extractor.
Only imports the columns we need from phpbb_forums, phpbb_topics,
phpbb_posts, phpbb_users. Skips everything else.

Usage:
  python import_dump.py <dump.sql> <output.db>
"""
from __future__ import annotations

import io
import os
import sqlite3
import sys
import time

# Column projections per table (1-indexed positions matching phpBB schema).
# Position lists are produced by inspecting the CREATE TABLE order in the dump.
WANTED = {
    "phpbb_forums": {
        "cols": [
            ("forum_id", 1, "int"),
            ("parent_id", 2, "int"),
            ("left_id", 3, "int"),
            ("right_id", 4, "int"),
            ("forum_name", 6, "str"),
            ("forum_desc", 7, "str"),
            ("forum_type", 21, "int"),
            ("forum_topics_approved", 44, "int"),
            ("forum_posts_approved", 41, "int"),
        ],
    },
    "phpbb_posts": {
        "cols": [
            ("post_id", 1, "int"),
            ("topic_id", 2, "int"),
            ("forum_id", 3, "int"),
            ("poster_id", 4, "int"),
            ("post_time", 7, "int"),
            ("post_username", 13, "str"),
            ("post_subject", 14, "str"),
            ("post_text", 15, "str"),
            ("bbcode_uid", 19, "str"),
            ("post_visibility", -1, "int"),
            ("enable_markdown", -1, "int"),
            ("enable_bbcode", -1, "int"),
        ],
    },
    "phpbb_users": {
        "cols": [
            ("user_id", 1, "int"),
            ("username", -1, "str"),
            ("user_colour", -1, "str"),
            ("user_posts", -1, "int"),
            ("user_regdate", -1, "int"),
            ("user_rank", -1, "int"),
            ("user_avatar", -1, "str"),
            ("user_avatar_type", -1, "str"),
            ("user_sig", -1, "str"),
            ("user_sig_bbcode_uid", -1, "str"),
            ("user_from", -1, "str"),
            ("user_website", -1, "str"),
        ],
    },
    "phpbb_topics": {
        "cols": [
            ("topic_id", 1, "int"),
            ("forum_id", 2, "int"),
            ("topic_title", 6, "str"),
            ("topic_poster", 7, "int"),
            ("topic_time", 8, "int"),
            ("topic_views", 10, "int"),
            ("topic_status", 11, "int"),
            ("topic_type", 12, "int"),
            ("topic_first_post_id", 13, "int"),
            ("topic_first_poster_name", 14, "str"),
            ("topic_first_poster_colour", 15, "str"),
            ("topic_last_post_id", 16, "int"),
            ("topic_last_poster_id", 17, "int"),
            ("topic_last_poster_name", 18, "str"),
            ("topic_last_post_time", 22, "int"),
            ("topic_moved_id", 24, "int"),
            ("topic_visibility", -1, "int"),
            ("icon_id", -1, "int"),
        ],
    },
}

# Column positions for tables resolved from CREATE TABLE block scan.
# We dynamically learn positions instead of hardcoding to handle phpBB version drift.


def parse_create_table(buf: str) -> list[str]:
    """Extract column names in declaration order from a CREATE TABLE block."""
    cols: list[str] = []
    in_block = False
    for line in buf.splitlines():
        s = line.strip()
        if not in_block:
            if s.startswith("CREATE TABLE"):
                in_block = True
            continue
        if s.startswith(")"):
            break
        if s.startswith("`"):
            end = s.find("`", 1)
            if end > 0:
                cols.append(s[1:end])
    return cols


def read_create_blocks(path: str) -> dict[str, list[str]]:
    """Scan dump for CREATE TABLE blocks of tables we care about. Returns table -> column list."""
    targets = set(WANTED.keys())
    found: dict[str, list[str]] = {}
    with open(path, "r", encoding="utf-8", errors="replace") as f:
        block: list[str] = []
        current: str | None = None
        for line in f:
            if current is None:
                if line.startswith("CREATE TABLE"):
                    # extract name
                    a = line.find("`")
                    b = line.find("`", a + 1)
                    name = line[a + 1 : b]
                    if name in targets:
                        current = name
                        block = [line]
                continue
            block.append(line)
            if line.startswith(")") and line.rstrip().endswith(";"):
                found[current] = parse_create_table("".join(block))
                current = None
                block = []
                if len(found) == len(targets):
                    break
    return found


# Streaming parser for INSERT INTO `table` VALUES (...),(...);
# Handles MySQL string escapes: \\ \' \" \n \r \t \0 \Z
class TupleStream:
    """Yield value tuples (as Python list[Any]) from a stream of INSERT VALUES bytes."""

    def __init__(self, src: io.TextIOBase):
        self.src = src
        self.buf = ""
        self.pos = 0
        self.eof = False

    def _refill(self, need: int = 4096) -> None:
        if self.eof:
            return
        if len(self.buf) - self.pos >= need:
            return
        chunk = self.src.read(65536)
        if not chunk:
            self.eof = True
            return
        if self.pos > 0:
            self.buf = self.buf[self.pos :] + chunk
            self.pos = 0
        else:
            self.buf += chunk

    def _peek(self) -> str:
        self._refill(1)
        if self.pos >= len(self.buf):
            return ""
        return self.buf[self.pos]

    def _advance(self, n: int = 1) -> None:
        self.pos += n

    def _read_value(self) -> object:
        self._refill(64)
        c = self._peek()
        if c == "'":
            return self._read_string()
        # number / NULL / unquoted token until comma or close paren
        start = self.pos
        while True:
            self._refill(64)
            if self.pos >= len(self.buf):
                break
            ch = self.buf[self.pos]
            if ch == "," or ch == ")":
                break
            self.pos += 1
        token = self.buf[start : self.pos].strip()
        if token == "NULL":
            return None
        try:
            if "." in token or "e" in token or "E" in token:
                return float(token)
            return int(token)
        except ValueError:
            return token

    def _read_string(self) -> str:
        # consume opening '
        assert self._peek() == "'"
        self._advance()
        out: list[str] = []
        while True:
            self._refill(64)
            if self.pos >= len(self.buf):
                raise ValueError("EOF inside string")
            ch = self.buf[self.pos]
            if ch == "\\":
                self._refill(2)
                self.pos += 1
                if self.pos >= len(self.buf):
                    raise ValueError("EOF after backslash")
                esc = self.buf[self.pos]
                self.pos += 1
                if esc == "n":
                    out.append("\n")
                elif esc == "r":
                    out.append("\r")
                elif esc == "t":
                    out.append("\t")
                elif esc == "0":
                    out.append("\x00")
                elif esc == "Z":
                    out.append("\x1a")
                elif esc == "b":
                    out.append("\b")
                else:
                    out.append(esc)
            elif ch == "'":
                self.pos += 1
                # check for doubled '' (alt escape)
                self._refill(1)
                if self.pos < len(self.buf) and self.buf[self.pos] == "'":
                    out.append("'")
                    self.pos += 1
                    continue
                return "".join(out)
            else:
                out.append(ch)
                self.pos += 1

    def read_tuple(self) -> list[object] | None:
        # Skip whitespace
        while True:
            self._refill(8)
            if self.pos >= len(self.buf):
                return None
            ch = self.buf[self.pos]
            if ch.isspace():
                self.pos += 1
                continue
            break
        c = self._peek()
        if c != "(":
            return None
        self._advance()
        vals: list[object] = []
        while True:
            self._refill(8)
            # value
            v = self._read_value()
            vals.append(v)
            self._refill(2)
            ch = self._peek()
            if ch == ",":
                self._advance()
                continue
            if ch == ")":
                self._advance()
                return vals
            raise ValueError(f"Unexpected char {ch!r} at pos {self.pos}")


def import_dump(dump_path: str, db_path: str) -> None:
    print(f"[1/3] Scanning CREATE TABLE blocks...")
    schemas = read_create_blocks(dump_path)
    for t, cols in schemas.items():
        print(f"   {t}: {len(cols)} cols")
        # resolve unknown positions in WANTED
        wanted_cols = WANTED[t]["cols"]
        resolved: list[tuple[str, int, str]] = []
        for cname, _pos, ctype in wanted_cols:
            if cname in cols:
                resolved.append((cname, cols.index(cname) + 1, ctype))
            else:
                # column missing in this dump version
                pass
        WANTED[t]["resolved"] = resolved
        WANTED[t]["all_cols"] = cols

    # SQLite setup
    if os.path.exists(db_path):
        os.remove(db_path)
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA journal_mode=OFF")
    conn.execute("PRAGMA synchronous=OFF")
    conn.execute("PRAGMA temp_store=MEMORY")
    cur = conn.cursor()
    for t, info in WANTED.items():
        col_defs = []
        for cname, _idx, ctype in info["resolved"]:
            sqlt = "INTEGER" if ctype == "int" else "TEXT"
            col_defs.append(f"{cname} {sqlt}")
        cur.execute(f"CREATE TABLE {t} ({', '.join(col_defs)})")
    conn.commit()

    print(f"[2/3] Streaming dump and inserting...")
    counts = {t: 0 for t in WANTED}
    t0 = time.time()
    with open(dump_path, "r", encoding="utf-8", errors="replace") as f:
        # Look for INSERT INTO `name` VALUES
        # Read line by line; INSERT lines may be huge.
        for raw_line in f:
            if not raw_line.startswith("INSERT INTO `"):
                continue
            # parse table name
            a = raw_line.find("`")
            b = raw_line.find("`", a + 1)
            tname = raw_line[a + 1 : b]
            if tname not in WANTED:
                continue
            # find ' VALUES ' marker
            vmark = raw_line.find(" VALUES ", b)
            if vmark < 0:
                continue
            # The remaining content (from vmark+8) plus possibly more lines may
            # contain the tuples. In practice mysqldump puts the entire INSERT on
            # one line ending with ';'. We slice and feed to TupleStream.
            payload = raw_line[vmark + 8 :]
            # If the line was buffered (it always is via 'for line'), we have it all.
            # But strip trailing ;\n
            payload = payload.rstrip()
            if payload.endswith(";"):
                payload = payload[:-1]
            stream = TupleStream(io.StringIO(payload))
            resolved = WANTED[tname]["resolved"]
            placeholders = ",".join("?" * len(resolved))
            colnames = ",".join(c[0] for c in resolved)
            insert_sql = f"INSERT INTO {tname} ({colnames}) VALUES ({placeholders})"
            batch: list[tuple] = []
            while True:
                tup = stream.read_tuple()
                if tup is None:
                    break
                row = []
                for _cname, idx, ctype in resolved:
                    if idx - 1 < len(tup):
                        v = tup[idx - 1]
                        if ctype == "int":
                            try:
                                v = int(v) if v is not None and v != "" else 0
                            except (ValueError, TypeError):
                                v = 0
                        else:
                            v = "" if v is None else str(v)
                        row.append(v)
                    else:
                        row.append(0 if ctype == "int" else "")
                batch.append(tuple(row))
                if len(batch) >= 5000:
                    cur.executemany(insert_sql, batch)
                    counts[tname] += len(batch)
                    batch = []
                # consume comma between tuples
                while True:
                    stream._refill(2)
                    if stream.pos >= len(stream.buf):
                        break
                    ch = stream.buf[stream.pos]
                    if ch == ",":
                        stream.pos += 1
                        break
                    if ch.isspace():
                        stream.pos += 1
                        continue
                    break
            if batch:
                cur.executemany(insert_sql, batch)
                counts[tname] += len(batch)
            conn.commit()
            elapsed = time.time() - t0
            print(f"   {tname}: {counts[tname]} rows  (t={elapsed:.1f}s)")

    print(f"[3/3] Creating indexes...")
    cur.execute("CREATE INDEX idx_topics_forum ON phpbb_topics(forum_id)")
    cur.execute("CREATE INDEX idx_posts_topic ON phpbb_posts(topic_id)")
    cur.execute("CREATE INDEX idx_posts_poster ON phpbb_posts(poster_id)")
    cur.execute("CREATE INDEX idx_users_id ON phpbb_users(user_id)")
    conn.commit()
    conn.close()
    print(f"Done. Counts: {counts}")


if __name__ == "__main__":
    if len(sys.argv) != 3:
        print(__doc__)
        sys.exit(1)
    import_dump(sys.argv[1], sys.argv[2])
