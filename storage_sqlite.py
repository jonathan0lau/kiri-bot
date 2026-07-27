import sqlite3
import uuid
import calendar
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

from config import DB_PATH, JST
from i18n import DEFAULT_LANG, normalize_lang


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _ensure_profile_user_t_schema(cur: sqlite3.Cursor):
    cur.execute("PRAGMA table_info(user_T)")
    rows = cur.fetchall()
    if not rows:
        cur.execute(
            """
            CREATE TABLE user_T (
                user_id        TEXT PRIMARY KEY,
                nickname       TEXT NOT NULL,
                birthday_mmdd  TEXT,
                twitter_handle TEXT,
                twitter_name   TEXT,
                note           TEXT,
                paid_start_at  TEXT,
                paid_end_at    TEXT,
                status         TEXT NOT NULL DEFAULT 'free',
                created_at     TEXT NOT NULL,
                updated_at     TEXT NOT NULL
            )
            """
        )
        return

    columns = {r[1]: r for r in rows}
    user_id_is_pk = "user_id" in columns and int(columns["user_id"][5]) == 1
    required = {"nickname", "birthday_mmdd", "twitter_handle", "twitter_name", "note", "created_at", "updated_at"}
    if user_id_is_pk and required.issubset(columns):
        for name, typ in [
            ("paid_start_at", "TEXT"),
            ("paid_end_at", "TEXT"),
            ("status", "TEXT NOT NULL DEFAULT 'free'"),
        ]:
            if name not in columns:
                cur.execute(f"ALTER TABLE user_T ADD COLUMN {name} {typ}")
        return

    legacy_name = f"user_T_legacy_{datetime.now(JST).strftime('%Y%m%d%H%M%S')}"
    cur.execute(f"ALTER TABLE user_T RENAME TO {legacy_name}")
    cur.execute(
        """
        CREATE TABLE user_T (
            user_id        TEXT PRIMARY KEY,
            nickname       TEXT NOT NULL,
            birthday_mmdd  TEXT,
            twitter_handle TEXT,
            twitter_name   TEXT,
            note           TEXT,
            paid_start_at  TEXT,
            paid_end_at    TEXT,
            status         TEXT NOT NULL DEFAULT 'free',
            created_at     TEXT NOT NULL,
            updated_at     TEXT NOT NULL
        )
        """
    )
    cur.execute(f"PRAGMA table_info({legacy_name})")
    legacy_cols = {r[1] for r in cur.fetchall()}

    def expr(*names: str, default: str = "NULL") -> str:
        for name in names:
            if name in legacy_cols:
                return name
        return default

    cur.execute(
        f"""
        INSERT OR IGNORE INTO user_T(
            user_id, nickname, birthday_mmdd, twitter_handle, twitter_name, note,
            paid_start_at, paid_end_at, status, created_at, updated_at
        )
        SELECT
            user_id,
            COALESCE(NULLIF({expr('nickname', 'display_name', default="''")}, ''), user_id),
            {expr('birthday_mmdd')},
            {expr('twitter_handle', 'twitter_id')},
            {expr('twitter_name')},
            {expr('note', 'profile_text')},
            {expr('paid_start_at')},
            {expr('paid_end_at')},
            COALESCE({expr('status', default="'free'")}, 'free'),
            COALESCE({expr('created_at', default='NULL')}, ?),
            COALESCE({expr('updated_at', default='NULL')}, ?)
        FROM {legacy_name}
        WHERE user_id IS NOT NULL
        """
        ,
        (datetime.now(JST).isoformat(), datetime.now(JST).isoformat()),
    )

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

    # 按月授权记录（同一用户同一月份只记录一次）
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS entitlement_T (
            user_id    TEXT NOT NULL,
            yyyymm     TEXT NOT NULL,
            request_id TEXT NOT NULL,
            granted_at TEXT NOT NULL,
            PRIMARY KEY (user_id, yyyymm)
        )
        """
    )

    # 新人资料表（user_T）
    _ensure_profile_user_t_schema(cur)

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
    kv_set_if_absent("discord", "global", "lang", DEFAULT_LANG, "Bot表示言語：ja/zh/zh-tw/en/ko")
    kv_set_if_absent("discord", "channel", "review_id", "0", "審査チャンネルID")
    kv_set_if_absent("discord", "channel", "remind_id", "0", "期限通知チャンネルID")
    kv_set_if_absent("discord", "channel", "welcome_id", "0", "ウェルカムチャンネルID")
    kv_set_if_absent("discord", "channel", "profile_id", "0", "プロフィールパネルチャンネルID")
    kv_set_if_absent("discord", "role", "paid_id", "0", "有料メンバーロールID")

    # 权限
    kv_set_if_absent("auth", "role", "admin_role_ids", "", "Bot管理者ロールID（カンマ区切り）")

    # 付费显示
    kv_set_if_absent("billing", "global", "month_price_label", "XXX円", "月額表示用（実決済には使用しない）")

    # 提醒策略
    kv_set_if_absent("reminder", "global", "expiry_days", "5", "期限切れ何日前に通知するか")
    kv_set_if_absent("reminder", "global", "scan_hours", "12", "通知スキャン間隔（時間）")
    kv_set_if_absent("reminder", "global", "sync_enabled", "1", "毎日03:00 JSTの月別ロール同期を有効化：1/0")


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

    def as_bool(v: Optional[str], default: bool) -> bool:
        if v is None or str(v).strip() == "":
            return default
        return str(v).strip().lower() in {"1", "true", "yes", "on", "enabled"}

    cfg = {
        "review_channel_id": as_int(kv_get("discord", "channel", "review_id"), 0),
        "lang": normalize_lang(kv_get("discord", "global", "lang")),
        "remind_channel_id": as_int(kv_get("discord", "channel", "remind_id"), 0),
        "welcome_channel_id": as_int(kv_get("discord", "channel", "welcome_id"), 0),
        "profile_channel_id": as_int(kv_get("discord", "channel", "profile_id"), 0),
        "paid_role_id": as_int(kv_get("discord", "role", "paid_id"), 0),
        "admin_role_ids": as_csv_int_set(kv_get("auth", "role", "admin_role_ids")),
        "month_price_label": kv_get("billing", "global", "month_price_label") or "XXX円",
        "expiry_days": as_int(kv_get("reminder", "global", "expiry_days"), 5),
        "scan_hours": as_int(kv_get("reminder", "global", "scan_hours"), 12),
        "sync_enabled": as_bool(kv_get("reminder", "global", "sync_enabled"), True),
    }
    return cfg


def upsert_user_profile(
    user_id: int,
    nickname: str,
    birthday_mmdd: Optional[str],
    twitter_handle: Optional[str],
    twitter_name: Optional[str],
    note: Optional[str],
) -> None:
    now = datetime.now(JST).isoformat()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO user_T(
            user_id, nickname, birthday_mmdd, twitter_handle, twitter_name, note, created_at, updated_at
        )
        VALUES(?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(user_id)
        DO UPDATE SET
            nickname=excluded.nickname,
            birthday_mmdd=excluded.birthday_mmdd,
            twitter_handle=excluded.twitter_handle,
            twitter_name=excluded.twitter_name,
            note=excluded.note,
            updated_at=excluded.updated_at
        """,
        (
            str(user_id),
            nickname,
            birthday_mmdd,
            twitter_handle,
            twitter_name,
            note,
            now,
            now,
        ),
    )
    conn.commit()
    conn.close()


def get_user_profile(user_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM user_T WHERE user_id=?", (str(user_id),))
    row = cur.fetchone()
    conn.close()
    return row


def set_user_paid_status(
    guild_id: int,
    user_id: int,
    status: str,
    paid_start_at: Optional[datetime],
    paid_end_at: Optional[datetime],
) -> None:
    now = datetime.now(JST).isoformat()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE user_T
        SET status=?,
            paid_start_at=?,
            paid_end_at=?,
            updated_at=?
        WHERE user_id=?
        """,
        (
            status,
            paid_start_at.isoformat() if paid_start_at else None,
            paid_end_at.isoformat() if paid_end_at else None,
            now,
            str(user_id),
        ),
    )
    if cur.rowcount == 0:
        cur.execute(
            """
            INSERT INTO user_T(user_id, nickname, status, paid_start_at, paid_end_at, created_at, updated_at)
            VALUES(?,?,?,?,?,?,?)
            """,
            (
                str(user_id),
                "",
                status,
                paid_start_at.isoformat() if paid_start_at else None,
                paid_end_at.isoformat() if paid_end_at else None,
                now,
                now,
            ),
        )
    conn.commit()
    conn.close()


def months_covered(start_at: datetime, end_at: datetime) -> List[str]:
    """返回起止时间在 JST 下覆盖的所有自然月（包含起止月）。"""
    if start_at.tzinfo is None:
        start_at = start_at.replace(tzinfo=JST)
    else:
        start_at = start_at.astimezone(JST)
    if end_at.tzinfo is None:
        end_at = end_at.replace(tzinfo=JST)
    else:
        end_at = end_at.astimezone(JST)

    if end_at < start_at:
        raise ValueError("end_at は start_at より前にできません")

    y, m = start_at.year, start_at.month
    ey, em = end_at.year, end_at.month
    out: List[str] = []
    while (y < ey) or (y == ey and m <= em):
        out.append(f"{y}{m:02d}")
        m += 1
        if m == 13:
            m = 1
            y += 1
    return out


def upsert_month_entitlements(user_id: int, yyyymms: List[str], request_id: str) -> int:
    """以单个事务写入按月授权，返回新插入的行数。"""
    granted_at = datetime.now(JST).isoformat()
    conn = _conn()
    try:
        cur = conn.cursor()
        before = conn.total_changes
        cur.executemany(
            """
            INSERT OR IGNORE INTO entitlement_T(user_id, yyyymm, request_id, granted_at)
            VALUES (?, ?, ?, ?)
            """,
            [(str(user_id), yyyymm, request_id, granted_at) for yyyymm in yyyymms],
        )
        conn.commit()
        return conn.total_changes - before
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def grant_month_entitlement(user_id: int, yyyymm: str, request_id: str) -> bool:
    """兼容单月调用；新流程优先使用 upsert_month_entitlements。"""
    return upsert_month_entitlements(user_id, [yyyymm], request_id) == 1


def list_entitlements():
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT user_id, yyyymm, request_id, granted_at
        FROM entitlement_T
        ORDER BY user_id, yyyymm
        """
    )
    rows = cur.fetchall()
    conn.close()
    return rows


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
