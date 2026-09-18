"""Flyway 10 schema history compatibility; original SQL resources remain byte-identical.

Checksum reference: flyway-10.10.0 ChecksumCalculator.calculateChecksumForResource.
Line separators and the initial BOM are excluded; all other whitespace is retained.
"""
import re
import time
import zlib
from pathlib import Path
from sqlalchemy import text
from .database import mysql_engine
from bemodel.config import settings

MIGRATIONS = Path(__file__).resolve().parents[1] / "db/migration"


def checksum(source: str) -> int:
    value = zlib.crc32(re.sub(r"\r\n|\r|\n", "", source.lstrip("\ufeff")).encode("utf-8"))
    return value if value < 0x80000000 else value - 0x100000000


def split_sql(source):
    """Split MySQL SQL, respecting comments, escaped quotes and quoted identifiers."""
    output, buffer, quote, i = [], [], None, 0
    while i < len(source):
        ch = source[i]
        if quote:
            buffer.append(ch)
            if ch == "\\" and i + 1 < len(source):
                i += 1
                buffer.append(source[i])
            elif ch == quote:
                if i + 1 < len(source) and source[i + 1] == quote:
                    i += 1
                    buffer.append(source[i])
                else:
                    quote = None
        elif ch in "'\"`":
            quote = ch
            buffer.append(ch)
        elif source[i:i+2] == "/*":
            end = source.find("*/", i+2)
            if end < 0:
                raise ValueError("Unterminated SQL comment")
            if source[i:i+3] == "/*!":
                buffer.append(source[i:end+2])
            else:
                buffer.append(" ")
            i = end + 1
        elif ch == "#" or (source[i:i+2] == "--" and (i+2 == len(source) or source[i+2].isspace())):
            end = source.find("\n", i)
            i = len(source) if end < 0 else end
            buffer.append("\n")
        elif ch == ";":
            if "".join(buffer).strip():
                output.append("".join(buffer).strip())
            buffer = []
        else:
            buffer.append(ch)
        i += 1
    if quote:
        raise ValueError("Unterminated SQL string")
    if "".join(buffer).strip():
        output.append("".join(buffer).strip())
    return output


HISTORY = """CREATE TABLE IF NOT EXISTS flyway_schema_history (
installed_rank INT NOT NULL PRIMARY KEY, version VARCHAR(50), description VARCHAR(200) NOT NULL,
type VARCHAR(20) NOT NULL, script VARCHAR(1000) NOT NULL, checksum INT,
installed_by VARCHAR(100) NOT NULL, installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
execution_time INT NOT NULL, success BOOL NOT NULL, INDEX flyway_schema_history_s_idx(success)
) ENGINE=InnoDB"""


def run_migrations(engine, config=settings):
    admin = mysql_engine()
    try:
        with admin.begin() as conn:
            name = config.mysql_database.replace("`", "``")
            conn.exec_driver_sql(f"CREATE DATABASE IF NOT EXISTS `{name}` CHARACTER SET utf8mb4")
    finally:
        admin.dispose()
    count = 0
    with engine.connect() as conn:
        lock = "bemodel-flyway-" + config.mysql_database
        if conn.execute(text("SELECT GET_LOCK(:name, 60)"), {"name": lock}).scalar() != 1:
            raise RuntimeError("Unable to acquire migration lock")
        try:
            conn.exec_driver_sql(HISTORY)
            conn.commit()
            rows = list(conn.execute(text("SELECT * FROM flyway_schema_history ORDER BY installed_rank")).mappings())
            if any(not r["success"] for r in rows):
                raise RuntimeError("Failed Flyway migration exists; repair database before restarting")
            applied = {r["version"]: r for r in rows if r["type"] == "SQL"}
            rank = max((r["installed_rank"] for r in rows), default=0)
            for path in sorted(MIGRATIONS.glob("V*__*.sql"), key=lambda p: int(p.name.split("__")[0][1:])):
                version, description = path.stem[1:].split("__", 1)
                source = path.read_text(encoding="utf-8-sig")
                digest = checksum(source)
                if version in applied:
                    if applied[version]["checksum"] != digest:
                        raise RuntimeError(f"Flyway checksum mismatch: {path.name}")
                    continue
                for key, value in {"demo_db_username": config.mysql_username, "demo_db_password": config.mysql_password}.items():
                    source = source.replace("${" + key + "}", value.replace("\\", "\\\\").replace("'", "''"))
                started, success = time.monotonic(), False
                rank += 1
                try:
                    for statement in split_sql(source):
                        conn.exec_driver_sql(statement)
                    success = True
                finally:
                    conn.execute(text("""INSERT INTO flyway_schema_history
                        (installed_rank,version,description,type,script,checksum,installed_by,execution_time,success)
                        VALUES (:rank,:version,:description,'SQL',:script,:checksum,:installed_by,:elapsed,:success)"""),
                        dict(rank=rank, version=version, description=description.replace("_", " "), script=path.name,
                             checksum=digest, installed_by=config.mysql_username, elapsed=int((time.monotonic()-started)*1000), success=success))
                    conn.commit()
                count += 1
        finally:
            conn.execute(text("SELECT RELEASE_LOCK(:name)"), {"name": lock})
            conn.commit()
    return count
