"""Run read-only SQL against a user-supplied Postgres database and shape
results like Excel-extracted tables for the catalogue pipeline.

If `query` is omitted, user tables/views are auto-extracted (SELECT * with a
row cap). When the DB looks like a DHARA catalogue export
(`datasets` + `dataset_rows.row_data` JSONB), each logical dataset is expanded
into a real Excel-shaped table instead of returning the registry blobs.
A custom SELECT is still optional.
"""

from __future__ import annotations

import random
import re
import socket
import struct
from collections import OrderedDict
from datetime import date, datetime, time
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

import psycopg2
import psycopg2.extensions
from psycopg2 import sql as psql

# Soft guard — real protection is a read-only transaction + statement timeout.
_FORBIDDEN = re.compile(
    r"\b(INSERT|UPDATE|DELETE|DROP|ALTER|CREATE|TRUNCATE|GRANT|REVOKE|"
    r"COPY|CALL|EXECUTE|DO|VACUUM|REINDEX|CLUSTER|COMMENT|SECURITY|"
    r"SET\s+ROLE|SET\s+SESSION)\b",
    re.IGNORECASE,
)

DEFAULT_ROW_LIMIT = 50_000
DEFAULT_STATEMENT_TIMEOUT_MS = 30_000
DEFAULT_MAX_TABLES = 500
ABSOLUTE_MAX_TABLES = 2_000
_SYSTEM_SCHEMAS = ("pg_catalog", "information_schema", "pg_toast")

# Physical tables that store catalogue metadata / JSONB payloads — not the
# logical datasets the pipeline should review.
_CATALOGUE_REGISTRY_TABLES = frozenset(
    {"datasets", "dataset_rows", "metadata_groups", "kyds_entries"}
)

# Query-string keys some hosts (e.g. Neon) add that older libpq/psycopg2 reject.
_DSN_DROP_QUERY_KEYS = frozenset({"channel_binding"})

# Used when the host/container resolver cannot look up Neon / other public hosts
# (common with broken ISP DNS or Docker Desktop forwarding a bad resolv.conf).
_PUBLIC_DNS_SERVERS = ("8.8.8.8", "1.1.1.1", "8.8.4.4")
_LOCAL_OR_COMPOSE_HOSTS = frozenset(
    {"localhost", "127.0.0.1", "::1", "postgres", "host.docker.internal", "backend", "frontend"}
)


def _running_in_docker() -> bool:
    return Path("/.dockerenv").exists()


def _looks_like_ip(host: str) -> bool:
    try:
        socket.inet_pton(socket.AF_INET, host)
        return True
    except OSError:
        pass
    try:
        socket.inet_pton(socket.AF_INET6, host.strip("[]"))
        return True
    except OSError:
        return False


def _dns_query_a(hostname: str, nameserver: str, timeout: float = 3.0) -> list[str]:
    """Minimal UDP DNS A (+ follow one CNAME) lookup — no extra dependency."""
    name = hostname.strip(".").lower()
    if not name or len(name) > 253:
        return []

    def _encode_name(host: str) -> bytes:
        out = b""
        for label in host.split("."):
            raw = label.encode("idna")
            if not raw or len(raw) > 63:
                raise ValueError("invalid DNS label")
            out += bytes([len(raw)]) + raw
        return out + b"\x00"

    def _decode_name(buf: bytes, offset: int) -> tuple[str, int]:
        labels: list[str] = []
        jumped = False
        pos = offset
        end = offset
        for _ in range(64):
            if pos >= len(buf):
                raise ValueError("truncated name")
            length = buf[pos]
            if length == 0:
                pos += 1
                if not jumped:
                    end = pos
                break
            if length & 0xC0 == 0xC0:
                if pos + 1 >= len(buf):
                    raise ValueError("truncated pointer")
                pointer = ((length & 0x3F) << 8) | buf[pos + 1]
                if not jumped:
                    end = pos + 2
                pos = pointer
                jumped = True
                continue
            pos += 1
            labels.append(buf[pos : pos + length].decode("ascii", errors="replace"))
            pos += length
            if not jumped:
                end = pos
        return ".".join(labels), end

    try:
        qname = _encode_name(name)
    except ValueError:
        return []

    txid = random.randint(0, 65535)
    header = struct.pack(">HHHHHH", txid, 0x0100, 1, 0, 0, 0)
    question = qname + struct.pack(">HH", 1, 1)  # A IN
    packet = header + question

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (nameserver, 53))
        data, _ = sock.recvfrom(2048)
    except OSError:
        return []
    finally:
        sock.close()

    if len(data) < 12:
        return []
    r_txid, flags, qdcount, ancount, _, _ = struct.unpack(">HHHHHH", data[:12])
    if r_txid != txid or (flags & 0x000F) != 0 or ancount == 0:
        return []

    offset = 12
    for _ in range(qdcount):
        _, offset = _decode_name(data, offset)
        offset += 4

    addrs: list[str] = []
    cnames: list[str] = []
    for _ in range(ancount):
        _, offset = _decode_name(data, offset)
        if offset + 10 > len(data):
            break
        rtype, _, _, rdlength = struct.unpack(">HHIH", data[offset : offset + 10])
        offset += 10
        rdata = data[offset : offset + rdlength]
        offset += rdlength
        if rtype == 1 and rdlength == 4:  # A
            addrs.append(socket.inet_ntoa(rdata))
        elif rtype == 5:  # CNAME
            cname, _ = _decode_name(data, offset - rdlength)
            if cname:
                cnames.append(cname)

    if addrs:
        return addrs
    for cname in cnames:
        for ns in _PUBLIC_DNS_SERVERS:
            nested = _dns_query_a(cname, ns, timeout=timeout)
            if nested:
                return nested
    return []


def _resolve_host_ips(hostname: str) -> list[str]:
    """System resolver first; fall back to public DNS if that fails."""
    host = (hostname or "").strip().strip("[]")
    if not host:
        return []
    if _looks_like_ip(host):
        return [host]
    try:
        infos = socket.getaddrinfo(host, None, type=socket.SOCK_STREAM)
        ips: list[str] = []
        for info in infos:
            ip = info[4][0]
            if ip and ip not in ips:
                ips.append(ip)
        if ips:
            return ips
    except OSError:
        pass
    for ns in _PUBLIC_DNS_SERVERS:
        ips = _dns_query_a(host, ns)
        if ips:
            return ips
    return []


def _ensure_resolvable_dsn(dsn: str) -> str:
    """If system DNS cannot resolve the DB host, inject libpq hostaddr via public DNS.

    Keeps `host` for TLS SNI / cert verification; only adds the IP to connect to.
    """
    parsed = urlparse(dsn)
    host = parsed.hostname
    if not host:
        return dsn
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    if query.get("hostaddr") or host.lower() in _LOCAL_OR_COMPOSE_HOSTS or _looks_like_ip(host):
        return dsn

    try:
        socket.getaddrinfo(host, parsed.port or 5432, type=socket.SOCK_STREAM)
        return dsn
    except OSError:
        pass

    ips = _resolve_host_ips(host)
    if not ips:
        raise ValueError(
            f"Could not resolve database host {host!r}. "
            "Check the hostname, or your DNS (system resolver failed and public DNS fallback found nothing)."
        )
    # Prefer IPv4 — Docker Desktop / many NATs handle it more reliably than AAAA.
    ipv4 = [ip for ip in ips if ":" not in ip]
    query["hostaddr"] = (ipv4 or ips)[0]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(query),
            parsed.fragment,
        )
    )


def _sanitize_dsn(dsn: str) -> str:
    """Drop unsupported URI query params so libpq/psycopg2 can connect."""
    parsed = urlparse(dsn)
    if not parsed.query:
        return dsn
    kept = [
        (k, v)
        for k, v in parse_qsl(parsed.query, keep_blank_values=True)
        if k.lower() not in _DSN_DROP_QUERY_KEYS
    ]
    return urlunparse(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            parsed.params,
            urlencode(kept),
            parsed.fragment,
        )
    )


def _rewrite_localhost_for_docker(dsn: str) -> str:
    """Inside a container, localhost is the container itself — not the host
    machine or sibling Compose services.

    Prefer the Compose service hostname `postgres` when the DSN targets the
    local DHARA stack DB (same credentials/db as docker-compose). Otherwise
    rewrite to host.docker.internal (requires extra_hosts host-gateway).
    """
    if not _running_in_docker():
        return dsn
    parsed = urlparse(dsn)
    host = (parsed.hostname or "").lower()
    if host not in ("localhost", "127.0.0.1", "::1"):
        return dsn
    from urllib.parse import quote_plus

    userinfo = ""
    if parsed.username is not None:
        userinfo = quote_plus(parsed.username)
        if parsed.password is not None:
            userinfo += ":" + quote_plus(parsed.password)
        userinfo += "@"
    port = parsed.port or 5432
    db_name = (parsed.path or "").lstrip("/").split("/")[0]
    # Local Compose Postgres — talk to the sibling service, not the host.
    if (
        (parsed.username or "") == "dhara"
        and db_name == "dhara"
        and port == 5432
    ):
        target_host = "postgres"
    else:
        target_host = "host.docker.internal"
    netloc = f"{userinfo}{target_host}:{port}"
    return urlunparse((parsed.scheme, netloc, parsed.path, parsed.params, parsed.query, parsed.fragment))


def _json_safe(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, (datetime, date, time)):
        return value.isoformat()
    if isinstance(value, (bytes, memoryview)):
        return bytes(value).hex()
    if isinstance(value, (list, tuple)):
        return [_json_safe(v) for v in value]
    if isinstance(value, dict):
        return {str(k): _json_safe(v) for k, v in value.items()}
    return str(value)


def _normalize_dsn(
    database_url: Optional[str] = None,
    *,
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    sslmode: Optional[str] = None,
) -> str:
    raw = (database_url or "").strip()
    if raw:
        # Accept postgres:// as an alias for postgresql://
        if raw.startswith("postgres://"):
            raw = "postgresql://" + raw[len("postgres://") :]
        if not raw.startswith("postgresql://"):
            raise ValueError("Database URL must start with postgresql:// or postgres://")
        parsed = urlparse(raw)
        if not parsed.hostname:
            raise ValueError("Database URL is missing a host")
        if not (parsed.path or "").lstrip("/"):
            raise ValueError("Database URL is missing a database name")
        return _sanitize_dsn(_rewrite_localhost_for_docker(raw))

    if not host or not database or not user:
        raise ValueError(
            "Provide a postgresql:// URL, or host + database + user "
            "(password optional)."
        )
    from urllib.parse import quote_plus

    user_part = quote_plus(user)
    if password:
        user_part = f"{quote_plus(user)}:{quote_plus(password)}"
    resolved_host = host
    if _running_in_docker() and host.lower() in ("localhost", "127.0.0.1", "::1"):
        if user == "dhara" and database == "dhara" and int(port or 5432) == 5432:
            resolved_host = "postgres"
        else:
            resolved_host = "host.docker.internal"
    netloc = f"{user_part}@{resolved_host}:{int(port or 5432)}"
    query = f"sslmode={sslmode}" if sslmode else ""
    return _sanitize_dsn(urlunparse(("postgresql", netloc, f"/{database}", "", query, "")))


def _assert_select_only(query: str) -> str:
    q = (query or "").strip().rstrip(";")
    if not q:
        raise ValueError("SQL query is required")
    if ";" in q:
        raise ValueError("Only a single SQL statement is allowed (no semicolons)")
    if _FORBIDDEN.search(q):
        raise ValueError("Only read-only SELECT / WITH queries are allowed")
    head = q.lstrip().split(None, 1)[0].upper()
    if head not in ("SELECT", "WITH", "TABLE", "VALUES", "SHOW", "EXPLAIN"):
        raise ValueError("Query must start with SELECT (or WITH … SELECT)")
    if head == "EXPLAIN" and "ANALYZE" in q.upper():
        raise ValueError("EXPLAIN ANALYZE is not allowed")
    return q


def _slug(text: str, fallback: str = "QUERY") -> str:
    s = re.sub(r"[^A-Za-z0-9]+", "_", (text or "").strip().upper()).strip("_")
    return (s[:48] or fallback)


def _unique_column_names(raw_names: list) -> list[str]:
    seen: dict[str, int] = {}
    out: list[str] = []
    for i, name in enumerate(raw_names):
        base = str(name or "").strip() or f"column_{i + 1}"
        n = seen.get(base, 0)
        seen[base] = n + 1
        out.append(base if n == 0 else f"{base}_{n + 1}")
    return out


def _source_label(dsn: str) -> str:
    parsed = urlparse(dsn)
    host_disp = parsed.hostname or "db"
    db_disp = (parsed.path or "/").lstrip("/") or "db"
    return f"sql://{host_disp}/{db_disp}"


def _fetch_rows(cur, limit: int) -> tuple[list[str], list[dict]]:
    if cur.description is None:
        raise ValueError("Query returned no columns (not a SELECT result)")
    columns = _unique_column_names([d[0] for d in cur.description])
    rows: list[dict] = []
    while len(rows) < limit:
        raw = cur.fetchmany(500)
        if not raw:
            break
        for tup in raw:
            if len(rows) >= limit:
                break
            rows.append({col: _json_safe(val) for col, val in zip(columns, tup)})
    return columns, rows


def _shape_table(
    *,
    columns: list[str],
    rows: list[dict],
    title: str,
    table_id: str,
    sheet: str,
    source_file: str,
    notes: list[str],
    uid: str,
    table_code: Optional[str] = None,
) -> dict:
    code = (table_code or "").strip() or f"DDI_DEL_DES_SQL_{_slug(title)}_V1"
    return {
        "id": code,
        "table_id": table_id,
        "title": title,
        "sheet": sheet,
        "filename": "SQL database",
        "source_file": source_file,
        "columns": columns,
        "rows": rows,
        "row_count": len(rows),
        "raw_header_rows": [],
        "raw_col_num_rows": [],
        "raw_notes": notes,
        "original_excel_url": None,
        "_uid": uid,
        "id_validation": {"code": {"valid": True, "issues": []}, "llm": None},
        "id_title_mismatch": False,
        "source_type": "sql",
    }


def _list_user_relations(cur) -> list[tuple[str, str, str]]:
    """Return (schema, name, kind) for base tables and views in user schemas."""
    cur.execute(
        """
        SELECT table_schema, table_name, table_type
        FROM information_schema.tables
        WHERE table_type IN ('BASE TABLE', 'VIEW')
          AND table_schema NOT IN %s
          AND table_schema NOT LIKE 'pg_%%'
        ORDER BY table_schema, table_name
        """,
        (_SYSTEM_SCHEMAS,),
    )
    out: list[tuple[str, str, str]] = []
    for schema, name, kind in cur.fetchall():
        out.append((schema, name, "view" if kind == "VIEW" else "table"))
    return out


def _relation_exists(cur, schema: str, name: str) -> bool:
    cur.execute(
        """
        SELECT 1
        FROM information_schema.tables
        WHERE table_schema = %s
          AND table_name = %s
          AND table_type IN ('BASE TABLE', 'VIEW')
        LIMIT 1
        """,
        (schema, name),
    )
    return cur.fetchone() is not None


def _columns_exist(cur, schema: str, table: str, required: set[str]) -> bool:
    cur.execute(
        """
        SELECT column_name
        FROM information_schema.columns
        WHERE table_schema = %s AND table_name = %s
        """,
        (schema, table),
    )
    have = {r[0] for r in cur.fetchall()}
    return required.issubset(have)


def _detect_catalogue_layout(cur) -> Optional[str]:
    """Return schema name if this DB stores DHARA-style datasets + JSONB rows."""
    # Prefer public; otherwise first user schema that matches.
    candidates: list[str] = []
    cur.execute(
        """
        SELECT table_schema
        FROM information_schema.tables
        WHERE table_name IN ('datasets', 'dataset_rows')
          AND table_schema NOT IN %s
          AND table_schema NOT LIKE 'pg_%%'
        GROUP BY table_schema
        ORDER BY CASE WHEN table_schema = 'public' THEN 0 ELSE 1 END, table_schema
        """,
        (_SYSTEM_SCHEMAS,),
    )
    candidates = [r[0] for r in cur.fetchall()]
    for schema in candidates:
        if not (
            _relation_exists(cur, schema, "datasets")
            and _relation_exists(cur, schema, "dataset_rows")
        ):
            continue
        if not _columns_exist(
            cur, schema, "datasets", {"dataset_id", "table_id", "title"}
        ):
            continue
        if not _columns_exist(
            cur, schema, "dataset_rows", {"dataset_id", "row_data"}
        ):
            continue
        # Confirm row_data is object-shaped JSON (not just a text dump).
        cur.execute(
            psql.SQL(
                """
                SELECT 1
                FROM {}.dataset_rows
                WHERE jsonb_typeof(row_data) = 'object'
                LIMIT 1
                """
            ).format(psql.Identifier(schema))
        )
        if cur.fetchone():
            return schema
        # Empty catalogue still counts as catalogue layout.
        cur.execute(
            psql.SQL("SELECT 1 FROM {}.datasets LIMIT 1").format(psql.Identifier(schema))
        )
        if cur.fetchone():
            return schema
    return None


def _rows_from_jsonb_payloads(payloads: list[Any]) -> tuple[list[str], list[dict]]:
    """Flatten a list of JSON object rows into columns + dict rows."""
    col_order: "OrderedDict[str, None]" = OrderedDict()
    dict_rows: list[dict] = []
    for payload in payloads:
        if payload is None:
            continue
        if isinstance(payload, str):
            # Rare: json already stringified
            try:
                import json as _json

                payload = _json.loads(payload)
            except Exception:
                continue
        if not isinstance(payload, dict):
            continue
        safe = {str(k): _json_safe(v) for k, v in payload.items()}
        for k in safe:
            if k not in col_order:
                col_order[k] = None
        dict_rows.append(safe)
    columns = list(col_order.keys())
    # Ensure every row has every column key (Excel-shaped).
    normalized = [{col: row.get(col) for col in columns} for row in dict_rows]
    return columns, normalized


def _extract_catalogue_datasets(
    cur,
    schema: str,
    *,
    source_file: str,
    limit: int,
    max_tables: int,
) -> list[dict]:
    """Expand each datasets row into an Excel-shaped table via dataset_rows."""
    cur.execute(
        psql.SQL(
            """
            SELECT
              d.dataset_id,
              COALESCE(NULLIF(d.table_id, ''), d.dataset_id) AS table_id,
              COALESCE(NULLIF(d.title, ''), d.dataset_id) AS title,
              d.metadata_id,
              d.short_description,
              d.category,
              d.geography,
              d.frequency,
              d.time_period,
              d.data_source,
              d.units,
              d.source_excel,
              (
                SELECT COUNT(*)::int
                FROM {schema}.dataset_rows r
                WHERE r.dataset_id = d.dataset_id
              ) AS row_count
            FROM {schema}.datasets d
            ORDER BY d.dataset_id
            LIMIT %s
            """
        ).format(schema=psql.Identifier(schema)),
        (max_tables,),
    )
    meta_cols = [d[0] for d in cur.description]
    dataset_metas = [dict(zip(meta_cols, row)) for row in cur.fetchall()]
    if not dataset_metas:
        raise ValueError(
            f"Catalogue schema detected in '{schema}' but datasets is empty."
        )

    tables: list[dict] = []
    for i, meta in enumerate(dataset_metas):
        dataset_id = str(meta["dataset_id"] or "").strip()
        table_id = str(meta["table_id"] or dataset_id).strip() or dataset_id
        title = str(meta["title"] or table_id).strip() or table_id

        cur.execute(
            psql.SQL(
                """
                SELECT row_data
                FROM {}.dataset_rows
                WHERE dataset_id = %s
                ORDER BY row_index NULLS LAST, id
                LIMIT %s
                """
            ).format(psql.Identifier(schema)),
            (dataset_id, limit),
        )
        payloads = [r[0] for r in cur.fetchall()]
        columns, rows = _rows_from_jsonb_payloads(payloads)

        notes = [
            f"Expanded catalogue dataset {dataset_id} from {schema}.dataset_rows",
            f"Row limit applied: {limit}",
        ]
        for label, key in (
            ("Metadata group", "metadata_id"),
            ("Category", "category"),
            ("Geography", "geography"),
            ("Frequency", "frequency"),
            ("Time period", "time_period"),
            ("Data source", "data_source"),
            ("Units", "units"),
        ):
            val = meta.get(key)
            if val:
                notes.append(f"{label}: {val}")
        if meta.get("short_description"):
            notes.append(str(meta["short_description"]))
        if meta.get("source_excel"):
            notes.append(f"Source Excel: {meta['source_excel']}")
        total = meta.get("row_count")
        if isinstance(total, int) and total > len(rows):
            notes.append(f"Stored rows in DB: {total} (extracted {len(rows)})")

        tables.append(
            _shape_table(
                columns=columns,
                rows=rows,
                title=title,
                table_id=table_id,
                sheet="catalogue",
                source_file=source_file,
                notes=notes,
                uid=f"0__{i}",
                table_code=dataset_id,
            )
        )
    return tables


def _extract_relation(
    cur,
    schema: str,
    name: str,
    *,
    kind: str,
    source_file: str,
    limit: int,
    uid: str,
) -> dict:
    qualified = f"{schema}.{name}" if schema != "public" else name
    cur.execute(
        psql.SQL("SELECT * FROM {}.{} LIMIT %s").format(
            psql.Identifier(schema),
            psql.Identifier(name),
        ),
        (limit,),
    )
    columns, rows = _fetch_rows(cur, limit)
    return _shape_table(
        columns=columns,
        rows=rows,
        title=qualified,
        table_id=f"SQL:{_slug(qualified)}",
        sheet=kind,
        source_file=source_file,
        notes=[
            f"Auto-extracted {kind} {qualified} from {source_file}",
            f"Row limit applied: {limit}",
        ],
        uid=uid,
    )


def _extract_plain_relations(
    cur,
    relations: list[tuple[str, str, str]],
    *,
    source_file: str,
    limit: int,
    skip_names: Optional[set[str]] = None,
    uid_offset: int = 0,
) -> list[dict]:
    skip = skip_names or set()
    tables: list[dict] = []
    for i, (schema, name, kind) in enumerate(relations):
        if name.lower() in skip:
            continue
        try:
            tables.append(
                _extract_relation(
                    cur,
                    schema,
                    name,
                    kind=kind,
                    source_file=source_file,
                    limit=limit,
                    uid=f"0__{uid_offset + i}",
                )
            )
        except psycopg2.Error as e:
            tables.append(
                _shape_table(
                    columns=["_error"],
                    rows=[{"_error": str(e.pgerror or e).strip()}],
                    title=f"{schema}.{name}" if schema != "public" else name,
                    table_id=f"SQL:{_slug(name)}_ERROR",
                    sheet=kind,
                    source_file=source_file,
                    notes=[f"Failed to read {schema}.{name}: {e.pgerror or e}"],
                    uid=f"0__{uid_offset + i}",
                )
            )
    return tables


def extract_tables_from_sql(
    query: Optional[str] = None,
    *,
    database_url: Optional[str] = None,
    host: Optional[str] = None,
    port: Optional[int] = None,
    database: Optional[str] = None,
    user: Optional[str] = None,
    password: Optional[str] = None,
    sslmode: Optional[str] = None,
    title: Optional[str] = None,
    table_id: Optional[str] = None,
    row_limit: int = DEFAULT_ROW_LIMIT,
    statement_timeout_ms: int = DEFAULT_STATEMENT_TIMEOUT_MS,
    max_tables: int = DEFAULT_MAX_TABLES,
) -> list[dict]:
    """Connect and return one or more Excel-shaped tables.

    - With `query`: run that SELECT and return a single table.
    - Without `query`:
        1. If a DHARA catalogue layout is detected, expand each dataset from
           `dataset_rows.row_data` (skipping registry tables).
        2. Otherwise discover user tables/views and SELECT * from each
           (capped by `max_tables` and `row_limit` per relation).
    """
    dsn = _ensure_resolvable_dsn(
        _normalize_dsn(
            database_url,
            host=host,
            port=port,
            database=database,
            user=user,
            password=password,
            sslmode=sslmode,
        )
    )
    limit = max(1, min(int(row_limit or DEFAULT_ROW_LIMIT), DEFAULT_ROW_LIMIT))
    timeout_ms = max(1_000, min(int(statement_timeout_ms or DEFAULT_STATEMENT_TIMEOUT_MS), 120_000))
    table_cap = max(1, min(int(max_tables or DEFAULT_MAX_TABLES), ABSOLUTE_MAX_TABLES))
    source_file = _source_label(dsn)
    custom_sql = (query or "").strip()

    conn = None
    try:
        conn = psycopg2.connect(dsn, connect_timeout=15)
        conn.set_session(readonly=True, autocommit=True)
        with conn.cursor() as cur:
            cur.execute(f"SET statement_timeout = {timeout_ms}")

            if custom_sql:
                sql = _assert_select_only(custom_sql)
                cur.execute(sql)
                columns, rows = _fetch_rows(cur, limit)
                display_title = (title or "").strip() or "SQL query result"
                label = (table_id or "").strip() or f"SQL:{_slug(display_title)}"
                return [
                    _shape_table(
                        columns=columns,
                        rows=rows,
                        title=display_title,
                        table_id=label,
                        sheet="query",
                        source_file=source_file,
                        notes=[
                            f"Extracted via custom SQL from {source_file}",
                            f"Row limit applied: {limit}",
                        ],
                        uid="0__0",
                    )
                ]

            catalogue_schema = _detect_catalogue_layout(cur)
            if catalogue_schema:
                tables = _extract_catalogue_datasets(
                    cur,
                    catalogue_schema,
                    source_file=source_file,
                    limit=limit,
                    max_tables=table_cap,
                )
                # Also pull any non-registry tables/views in other schemas / extras.
                extras = [
                    rel
                    for rel in _list_user_relations(cur)
                    if rel[1].lower() not in _CATALOGUE_REGISTRY_TABLES
                ]
                if extras and len(tables) < table_cap:
                    remaining = table_cap - len(tables)
                    tables.extend(
                        _extract_plain_relations(
                            cur,
                            extras[:remaining],
                            source_file=source_file,
                            limit=limit,
                            uid_offset=len(tables),
                        )
                    )
                return tables

            relations = _list_user_relations(cur)
            if not relations:
                raise ValueError(
                    "No user tables or views found in this database "
                    "(system schemas are skipped). Provide a SQL query, or "
                    "check the connection points at the right database."
                )
            if len(relations) > table_cap:
                relations = relations[:table_cap]

            return _extract_plain_relations(
                cur,
                relations,
                source_file=source_file,
                limit=limit,
            )
    except psycopg2.Error as e:
        raise ValueError(f"Database error: {e.pgerror or e}") from e
    finally:
        if conn is not None:
            try:
                conn.close()
            except Exception:
                pass


# Back-compat for older callers
def extract_table_from_sql(query: str, **kwargs) -> dict:
    tables = extract_tables_from_sql(query=query, **kwargs)
    return tables[0]
