import sqlite3
import uuid
import calendar
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

from config import DB_PATH, JST


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = _conn()
    cur = conn.cursor()

    # 付款请求流水
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS requests (
            request_id TEXT PRIMARY KEY,
            guild_id   TEXT NOT NULL,
            user_id    TEXT NOT NULL,
            paypay_name TEXT NOT NULL,
            note       TEXT,
            status     TEXT NOT NULL, -- PENDING / APPROVED / REJECTED
            created_at TEXT NOT NULL,
            approved_by TEXT,
            approved_at TEXT,
            start_at   TEXT,
            end_at     TEXT
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_user_status ON requests(user_id, status)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_status_end ON requests(status, end_at)")

    # PayPay 链接版本表（只允许一个 active）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS paypay_links (
            link_id    TEXT PRIMARY KEY,
            url        TEXT NOT NULL,
            created_at TEXT NOT NULL,
            created_by TEXT,
            expires_at TEXT,
            is_active  INTEGER NOT NULL -- 0/1
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_paypay_active ON paypay_links(is_active)")

    # ===== Kvs_M 配置中心 =====
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS Kvs_M (
            key1  TEXT NOT NULL,
            key2  TEXT NOT NULL,
            key3  TEXT NOT NULL,
            value TEXT NOT NULL,
            note  TEXT,
            PRIMARY KEY (key1, key2, key3)
        )
        """
    )

    conn.commit()
    conn.close()

    ensure_default_kvs()


# ===== Kvs_M =====
def kv_upsert(key1: str, key2: str, key3: str, value: str, note: Optional[str] = None):
    """
    存在就更新，不存在就插入（SQLite upsert）
    """
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO Kvs_M(key1,key2,key3,value,note)
        VALUES(?,?,?,?,?)
        ON CONFLICT(key1,key2,key3)
        DO UPDATE SET value=excluded.value, note=excluded.note
        """,
        (key1, key2, key3, value, note),
    )
    conn.commit()
    conn.close()


def kv_get(key1: str, key2: str, key3: str) -> Optional[str]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT value FROM Kvs_M WHERE key1=? AND key2=? AND key3=?",
        (key1, key2, key3),
    )
    row = cur.fetchone()
    conn.close()
    return row["value"] if row else None


def kv_set_if_absent(key1: str, key2: str, key3: str, value: str, note: Optional[str] = None):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT OR IGNORE INTO Kvs_M(key1,key2,key3,value,note)
        VALUES(?,?,?,?,?)
        """,
        (key1, key2, key3, value, note),
    )
    conn.commit()
    conn.close()


def ensure_default_kvs():
    """
    只在不存在时写入默认值，避免覆盖你已有配置。
    key1: 大分类（auth/billing/security/discord/reminder 等）
    key2: 中类（channel/role/user/global 等）
    key3: 小类（具体参数名）
    """
    # Discord 资源
    kv_set_if_absent("discord", "channel", "review_id", "0", "审核单输出频道ID")
    kv_set_if_absent("discord", "channel", "remind_id", "0", "到期提醒输出频道ID")
    kv_set_if_absent("discord", "role", "paid_id", "0", "付费会员角色ID")

    # 权限
    kv_set_if_absent("auth", "role", "admin_role_ids", "", "机器人管理员角色ID，逗号分隔")

    # 付费显示
    kv_set_if_absent("billing", "global", "month_price_label", "XXX円", "月费显示用（不参与实际支付）")

    # 提醒策略
    kv_set_if_absent("reminder", "global", "expiry_days", "5", "提前几天提醒到期")
    kv_set_if_absent("reminder", "global", "scan_hours", "12", "扫描间隔（小时）")


def load_runtime_settings() -> Dict[str, Any]:
    """
    从 Kvs_M 读出运行时配置，返回 dict（bot.kcfg 使用）
    """
    def as_int(v: Optional[str], default: int) -> int:
        try:
            return int(v) if v is not None and str(v).strip() != "" else default
        except Exception:
            return default

    def as_csv_int_set(v: Optional[str]) -> set[int]:
        if not v:
            return set()
        out: set[int] = set()
        for part in str(v).split(","):
            part = part.strip()
            if part.isdigit():
                out.add(int(part))
        return out

    cfg = {
        "review_channel_id": as_int(kv_get("discord", "channel", "review_id"), 0),
        "remind_channel_id": as_int(kv_get("discord", "channel", "remind_id"), 0),
        "paid_role_id": as_int(kv_get("discord", "role", "paid_id"), 0),
        "admin_role_ids": as_csv_int_set(kv_get("auth", "role", "admin_role_ids")),
        "month_price_label": kv_get("billing", "global", "month_price_label") or "XXX円",
        "expiry_days": as_int(kv_get("reminder", "global", "expiry_days"), 5),
        "scan_hours": as_int(kv_get("reminder", "global", "scan_hours"), 12),
    }
    return cfg


# ===== 业务规则：一个月后的月末 23:59:59（JST） =====
def month_end_after_one_month(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=JST)

    year = dt.year
    month = dt.month + 1
    if month == 13:
        month = 1
        year += 1

    last_day = calendar.monthrange(year, month)[1]
    return datetime(year, month, last_day, 23, 59, 59, tzinfo=JST)


# ===== Requests =====
def has_pending_request(user_id: int) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT 1 FROM requests WHERE user_id=? AND status='PENDING' LIMIT 1", (str(user_id),))
    ok = cur.fetchone() is not None
    conn.close()
    return ok


def create_request(guild_id: int, user_id: int, paypay_name: str, note: Optional[str]) -> str:
    request_id = str(uuid.uuid4())
    now = datetime.now(JST).isoformat()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO requests(request_id, guild_id, user_id, paypay_name, note, status, created_at)
        VALUES (?, ?, ?, ?, ?, 'PENDING', ?)
        """,
        (request_id, str(guild_id), str(user_id), paypay_name, note, now),
    )
    conn.commit()
    conn.close()
    return request_id


def get_request(request_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM requests WHERE request_id=?", (request_id,))
    row = cur.fetchone()
    conn.close()
    return row


def approve_request(request_id: str, approved_by: int, start_at: datetime, end_at: datetime) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE requests
        SET status='APPROVED',
            approved_by=?,
            approved_at=?,
            start_at=?,
            end_at=?
        WHERE request_id=? AND status='PENDING'
        """,
        (
            str(approved_by),
            datetime.now(JST).isoformat(),
            start_at.isoformat(),
            end_at.isoformat(),
            request_id,
        ),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def reject_request(request_id: str, approved_by: int) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE requests
        SET status='REJECTED',
            approved_by=?,
            approved_at=?
        WHERE request_id=? AND status='PENDING'
        """,
        (str(approved_by), datetime.now(JST).isoformat(), request_id),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def list_expiring_soon(days: int = 5):
    now = datetime.now(JST)
    limit = now + timedelta(days=days)

    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT * FROM requests
        WHERE status='APPROVED'
          AND end_at IS NOT NULL
          AND datetime(end_at) >= datetime(?)
          AND datetime(end_at) <= datetime(?)
        """,
        (now.isoformat(), limit.isoformat()),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


# ===== PayPay links =====
def set_paypay_link(url: str, created_by: Optional[int], expires_at: Optional[str]) -> str:
    link_id = str(uuid.uuid4())
    now = datetime.now(JST).isoformat()

    conn = _conn()
    cur = conn.cursor()

    cur.execute("UPDATE paypay_links SET is_active=0 WHERE is_active=1")
    cur.execute(
        """
        INSERT INTO paypay_links(link_id, url, created_at, created_by, expires_at, is_active)
        VALUES (?, ?, ?, ?, ?, 1)
        """,
        (link_id, url, now, str(created_by) if created_by else None, expires_at),
    )

    conn.commit()
    conn.close()
    return link_id


def get_active_paypay_link() -> Tuple[Optional[str], Optional[str], Optional[str]]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT url, expires_at, created_at
        FROM paypay_links
        WHERE is_active=1
        ORDER BY created_at DESC
        LIMIT 1
        """
    )
    row = cur.fetchone()
    conn.close()

    if not row:
        return None, None, None
    return row["url"], row["expires_at"], row["created_at"]