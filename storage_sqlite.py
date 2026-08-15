import sqlite3
import uuid
import calendar
import re
import json
from datetime import datetime, timedelta
from typing import Optional, Tuple, Dict, Any, List

from config import DB_PATH, JST
from i18n import DEFAULT_LANG, normalize_lang


def _conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


PRODUCT_ID_RE = re.compile(r"^[A-Z0-9_-]{3,50}$")
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def utc_now_iso() -> str:
    return datetime.utcnow().replace(microsecond=0).isoformat() + "Z"


def _table_columns(cur: sqlite3.Cursor, table: str) -> set[str]:
    cur.execute(f"PRAGMA table_info({table})")
    return {row[1] for row in cur.fetchall()}


def _add_column_if_missing(cur: sqlite3.Cursor, table: str, name: str, definition: str) -> None:
    if name not in _table_columns(cur, table):
        cur.execute(f"ALTER TABLE {table} ADD COLUMN {name} {definition}")


def validate_email(email: str) -> str:
    normalized = (email or "").strip()
    if len(normalized) > 254 or not EMAIL_RE.match(normalized):
        raise ValueError("invalid email")
    return normalized


def normalize_product_id(product_id: str) -> str:
    normalized = (product_id or "").strip().upper()
    if not PRODUCT_ID_RE.match(normalized):
        raise ValueError("product_id must be 3-50 chars: A-Z, 0-9, _ or -")
    return normalized


def validate_https_url(value: str) -> str:
    text = (value or "").strip()
    if not text.startswith("https://"):
        raise ValueError("url must start with https://")
    return text


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
    for name, definition in [
        ("purchase_type", "TEXT NOT NULL DEFAULT 'MEMBERSHIP'"),
        ("product_id", "TEXT"),
        ("email", "TEXT"),
        ("payment_note", "TEXT"),
        ("amount_expected", "INTEGER"),
        ("currency", "TEXT NOT NULL DEFAULT 'JPY'"),
        ("requested_at", "TEXT"),
        ("rejected_by", "TEXT"),
        ("rejected_at", "TEXT"),
        ("reject_reason", "TEXT"),
        ("delivery_completed_at", "TEXT"),
        ("updated_at", "TEXT"),
    ]:
        _add_column_if_missing(cur, "requests", name, definition)
    cur.execute("UPDATE requests SET purchase_type='MEMBERSHIP' WHERE purchase_type IS NULL OR purchase_type=''")
    cur.execute("UPDATE requests SET requested_at=created_at WHERE requested_at IS NULL")
    cur.execute("UPDATE requests SET payment_note=note WHERE payment_note IS NULL AND note IS NOT NULL")
    cur.execute("UPDATE requests SET updated_at=created_at WHERE updated_at IS NULL")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_requests_product_status ON requests(product_id, status, requested_at)")

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
    _add_column_if_missing(cur, "user_T", "email", "TEXT")
    _add_column_if_missing(cur, "user_T", "language", "TEXT NOT NULL DEFAULT 'ja'")
    _add_column_if_missing(cur, "user_T", "consent_delivery", "INTEGER NOT NULL DEFAULT 0")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS product_T (
            product_id TEXT PRIMARY KEY,
            product_name TEXT NOT NULL,
            product_type TEXT NOT NULL DEFAULT 'PHOTO_SET',
            description TEXT,
            price_amount INTEGER NOT NULL CHECK (price_amount >= 0),
            price_currency TEXT NOT NULL DEFAULT 'JPY',
            cover_url TEXT,
            preview_url TEXT,
            download_url TEXT NOT NULL,
            download_password TEXT,
            file_size_label TEXT,
            content_count_label TEXT,
            storage_provider TEXT NOT NULL DEFAULT 'GOOGLE_DRIVE',
            status TEXT NOT NULL DEFAULT 'DRAFT',
            sort_order INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_product_status_sort ON product_T(status, sort_order, created_at)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS delivery_T (
            delivery_id TEXT PRIMARY KEY,
            order_id TEXT NOT NULL,
            channel TEXT NOT NULL,
            destination_masked TEXT,
            status TEXT NOT NULL,
            attempt_count INTEGER NOT NULL DEFAULT 1,
            error_code TEXT,
            error_message TEXT,
            attempted_at TEXT NOT NULL,
            completed_at TEXT,
            created_at TEXT NOT NULL,
            FOREIGN KEY(order_id) REFERENCES requests(request_id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_delivery_order ON delivery_T(order_id, attempted_at)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS feed_post_T (
            post_id TEXT PRIMARY KEY,
            source TEXT NOT NULL DEFAULT 'MANUAL',
            external_post_id TEXT,
            title TEXT NOT NULL,
            body TEXT NOT NULL,
            preview_url TEXT,
            original_url TEXT,
            status TEXT NOT NULL DEFAULT 'PUBLISHED',
            created_by TEXT,
            created_at TEXT NOT NULL,
            UNIQUE(source, external_post_id)
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_feed_status_created ON feed_post_T(status, created_at)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS poll_T (
            poll_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            visibility TEXT NOT NULL DEFAULT 'PUBLIC',
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT,
            created_at TEXT NOT NULL,
            closes_at TEXT
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS poll_option_T (
            poll_id TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            label TEXT NOT NULL,
            PRIMARY KEY(poll_id, option_index)
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS poll_vote_T (
            poll_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            option_index INTEGER NOT NULL,
            voted_at TEXT NOT NULL,
            PRIMARY KEY(poll_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS question_T (
            question_id TEXT PRIMARY KEY,
            user_id TEXT,
            body TEXT NOT NULL,
            is_anonymous INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            answer TEXT,
            answered_by TEXT,
            answered_at TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_question_status_created ON question_T(status, created_at)")

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS club_event_T (
            event_id TEXT PRIMARY KEY,
            title TEXT NOT NULL,
            description TEXT,
            starts_at TEXT NOT NULL,
            buyer_only INTEGER NOT NULL DEFAULT 0,
            status TEXT NOT NULL DEFAULT 'OPEN',
            created_by TEXT,
            created_at TEXT NOT NULL
        )
        """
    )
    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS event_rsvp_T (
            event_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'JOINED',
            joined_at TEXT NOT NULL,
            PRIMARY KEY(event_id, user_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS supporter_level_T (
            user_id TEXT PRIMARY KEY,
            level_name TEXT NOT NULL,
            benefits TEXT,
            updated_by TEXT,
            updated_at TEXT NOT NULL
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE IF NOT EXISTS fan_submission_T (
            submission_id TEXT PRIMARY KEY,
            user_id TEXT NOT NULL,
            title TEXT NOT NULL,
            url TEXT,
            note TEXT,
            status TEXT NOT NULL DEFAULT 'SUBMITTED',
            picked_month TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    cur.execute("CREATE INDEX IF NOT EXISTS idx_submission_status_month ON fan_submission_T(status, picked_month)")

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
    kv_set_if_absent("discord", "channel", "shop_id", "0", "商品ショップチャンネルID")
    kv_set_if_absent("discord", "channel", "purchase_support_id", "0", "購入サポートチャンネルID")
    kv_set_if_absent("discord", "channel", "bot_log_id", "0", "BotログチャンネルID")
    kv_set_if_absent("discord", "channel", "feed_id", "0", "X/HP動態チャンネルID")
    kv_set_if_absent("discord", "channel", "question_id", "0", "質問箱チャンネルID")
    kv_set_if_absent("discord", "channel", "event_id", "0", "イベントチャンネルID")
    kv_set_if_absent("discord", "role", "paid_id", "0", "有料メンバーロールID")
    kv_set_if_absent("discord", "role", "buyer_id", "0", "商品購入者ロールID")

    # 权限
    kv_set_if_absent("auth", "role", "admin_role_ids", "", "Bot管理者ロールID（カンマ区切り）")

    # 付费显示
    kv_set_if_absent("billing", "global", "month_price_label", "XXX円", "月額表示用（実決済には使用しない）")
    kv_set_if_absent("billing", "global", "paypay_url", "", "商品購入用PayPay URL。未設定時はpaypay_links activeを使用")
    kv_set_if_absent("billing", "global", "currency", "JPY", "商品購入通貨")
    kv_set_if_absent("billing", "global", "review_timeout_hours", "72", "レビュー目安時間")
    kv_set_if_absent("shop", "global", "max_products_per_page", "25", "ショップ商品表示件数")
    kv_set_if_absent("shop", "global", "allow_duplicate_purchase", "1", "同一商品の再購入を許可：1/0")
    kv_set_if_absent("delivery", "global", "self_service_cooldown_minutes", "60", "自助再送信クールダウン")
    kv_set_if_absent("delivery", "global", "max_retry_count", "3", "配送最大リトライ回数")

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
        "shop_channel_id": as_int(kv_get("discord", "channel", "shop_id"), 0),
        "purchase_support_channel_id": as_int(kv_get("discord", "channel", "purchase_support_id"), 0),
        "bot_log_channel_id": as_int(kv_get("discord", "channel", "bot_log_id"), 0),
        "feed_channel_id": as_int(kv_get("discord", "channel", "feed_id"), 0),
        "question_channel_id": as_int(kv_get("discord", "channel", "question_id"), 0),
        "event_channel_id": as_int(kv_get("discord", "channel", "event_id"), 0),
        "paid_role_id": as_int(kv_get("discord", "role", "paid_id"), 0),
        "buyer_role_id": as_int(kv_get("discord", "role", "buyer_id"), 0),
        "admin_role_ids": as_csv_int_set(kv_get("auth", "role", "admin_role_ids")),
        "month_price_label": kv_get("billing", "global", "month_price_label") or "XXX円",
        "paypay_url": kv_get("billing", "global", "paypay_url") or "",
        "currency": kv_get("billing", "global", "currency") or "JPY",
        "review_timeout_hours": as_int(kv_get("billing", "global", "review_timeout_hours"), 72),
        "max_products_per_page": as_int(kv_get("shop", "global", "max_products_per_page"), 25),
        "allow_duplicate_purchase": as_bool(kv_get("shop", "global", "allow_duplicate_purchase"), True),
        "self_service_cooldown_minutes": as_int(kv_get("delivery", "global", "self_service_cooldown_minutes"), 60),
        "max_retry_count": as_int(kv_get("delivery", "global", "max_retry_count"), 3),
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


# ===== Products / product orders =====
def validate_product_payload(
    *,
    product_id: str,
    product_name: str,
    price_amount: int,
    download_url: str,
    product_type: str = "PHOTO_SET",
    description: Optional[str] = None,
    cover_url: Optional[str] = None,
    preview_url: Optional[str] = None,
    download_password: Optional[str] = None,
) -> dict[str, Any]:
    pid = normalize_product_id(product_id)
    name = (product_name or "").strip()
    if not (1 <= len(name) <= 100):
        raise ValueError("product_name must be 1-100 chars")
    if product_type not in {"PHOTO_SET", "VIDEO_SET", "BUNDLE"}:
        raise ValueError("invalid product_type")
    if int(price_amount) < 0 or int(price_amount) > 10_000_000:
        raise ValueError("price_amount must be 0-10000000")
    desc = (description or "").strip() or None
    if desc and len(desc) > 1500:
        raise ValueError("description is too long")
    password = (download_password or "").strip() or None
    if password and len(password) > 200:
        raise ValueError("download_password is too long")
    return {
        "product_id": pid,
        "product_name": name,
        "product_type": product_type,
        "description": desc,
        "price_amount": int(price_amount),
        "download_url": validate_https_url(download_url),
        "cover_url": validate_https_url(cover_url) if cover_url else None,
        "preview_url": validate_https_url(preview_url) if preview_url else None,
        "download_password": password,
    }


def create_product(
    *,
    product_id: str,
    product_name: str,
    price_amount: int,
    download_url: str,
    product_type: str = "PHOTO_SET",
    description: Optional[str] = None,
    cover_url: Optional[str] = None,
    preview_url: Optional[str] = None,
    download_password: Optional[str] = None,
    file_size_label: Optional[str] = None,
    content_count_label: Optional[str] = None,
    sort_order: int = 0,
) -> str:
    data = validate_product_payload(
        product_id=product_id,
        product_name=product_name,
        product_type=product_type,
        description=description,
        price_amount=price_amount,
        cover_url=cover_url,
        preview_url=preview_url,
        download_url=download_url,
        download_password=download_password,
    )
    now = utc_now_iso()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            """
            INSERT INTO product_T(
                product_id, product_name, product_type, description, price_amount,
                price_currency, cover_url, preview_url, download_url, download_password,
                file_size_label, content_count_label, status, sort_order, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'JPY', ?, ?, ?, ?, ?, ?, 'DRAFT', ?, ?, ?)
            """,
            (
                data["product_id"], data["product_name"], data["product_type"], data["description"],
                data["price_amount"], data["cover_url"], data["preview_url"], data["download_url"],
                data["download_password"], file_size_label, content_count_label, int(sort_order), now, now,
            ),
        )
        conn.commit()
        return data["product_id"]
    finally:
        conn.close()


def update_product_field(product_id: str, field: str, value: str) -> None:
    allowed = {
        "product_name", "product_type", "description", "price_amount", "cover_url", "preview_url",
        "download_url", "download_password", "file_size_label", "content_count_label", "sort_order",
    }
    if field not in allowed:
        raise ValueError("field is not editable")
    pid = normalize_product_id(product_id)
    new_value: Any = value.strip()
    if field == "price_amount":
        new_value = int(new_value)
        if new_value < 0 or new_value > 10_000_000:
            raise ValueError("price_amount must be 0-10000000")
    elif field == "sort_order":
        new_value = int(new_value)
    elif field in {"cover_url", "preview_url", "download_url"}:
        new_value = validate_https_url(new_value) if new_value else None
    elif field == "product_type" and new_value not in {"PHOTO_SET", "VIDEO_SET", "BUNDLE"}:
        raise ValueError("invalid product_type")
    elif field == "product_name" and not (1 <= len(new_value) <= 100):
        raise ValueError("product_name must be 1-100 chars")
    elif field == "description" and len(new_value) > 1500:
        raise ValueError("description is too long")
    elif field == "download_password" and len(new_value) > 200:
        raise ValueError("download_password is too long")
    if new_value == "":
        new_value = None

    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            f"UPDATE product_T SET {field}=?, updated_at=? WHERE product_id=?",
            (new_value, utc_now_iso(), pid),
        )
        if cur.rowcount != 1:
            raise ValueError("product not found")
        conn.commit()
    finally:
        conn.close()


def set_product_status(product_id: str, status: str) -> bool:
    if status not in {"DRAFT", "SALE", "STOP", "ARCHIVED"}:
        raise ValueError("invalid product status")
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE product_T SET status=?, updated_at=? WHERE product_id=?",
        (status, utc_now_iso(), normalize_product_id(product_id)),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def get_product(product_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM product_T WHERE product_id=?", (normalize_product_id(product_id),))
    row = cur.fetchone()
    conn.close()
    return row


def list_products(status: Optional[str] = None, limit: int = 25):
    conn = _conn()
    cur = conn.cursor()
    if status:
        cur.execute(
            """
            SELECT * FROM product_T
            WHERE status=?
            ORDER BY sort_order ASC, created_at DESC
            LIMIT ?
            """,
            (status, int(limit)),
        )
    else:
        cur.execute("SELECT * FROM product_T ORDER BY sort_order ASC, created_at DESC LIMIT ?", (int(limit),))
    rows = cur.fetchall()
    conn.close()
    return rows


def has_pending_product_order(user_id: int, product_id: str) -> Optional[str]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT request_id FROM requests
        WHERE purchase_type='PRODUCT' AND user_id=? AND product_id=? AND status='PENDING'
        ORDER BY requested_at DESC LIMIT 1
        """,
        (str(user_id), normalize_product_id(product_id)),
    )
    row = cur.fetchone()
    conn.close()
    return row["request_id"] if row else None


def create_product_order(
    *,
    guild_id: int,
    user_id: int,
    product_id: str,
    email: str,
    paypay_name: str,
    payment_note: Optional[str],
) -> str:
    pid = normalize_product_id(product_id)
    normalized_email = validate_email(email)
    now = utc_now_iso()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT * FROM product_T WHERE product_id=? AND status='SALE'", (pid,))
        product = cur.fetchone()
        if product is None:
            raise ValueError("product is not for sale")
        cur.execute(
            """
            SELECT request_id FROM requests
            WHERE purchase_type='PRODUCT' AND user_id=? AND product_id=? AND status='PENDING'
            LIMIT 1
            """,
            (str(user_id), pid),
        )
        pending = cur.fetchone()
        if pending:
            raise ValueError(f"pending order exists: {pending['request_id']}")
        allow_duplicate = (kv_get("shop", "global", "allow_duplicate_purchase") or "1").strip().lower() in {"1", "true", "yes", "on"}
        if not allow_duplicate:
            cur.execute(
                """
                SELECT request_id FROM requests
                WHERE purchase_type='PRODUCT' AND user_id=? AND product_id=? AND status IN ('SENT', 'DELIVERY_FAILED', 'DELIVERY_PENDING', 'APPROVED')
                LIMIT 1
                """,
                (str(user_id), pid),
            )
            existing = cur.fetchone()
            if existing:
                raise ValueError(f"duplicate purchase is disabled: {existing['request_id']}")
        request_id = str(uuid.uuid4())
        note = (payment_note or "").strip() or None
        cur.execute(
            """
            INSERT INTO requests(
                request_id, guild_id, user_id, paypay_name, note, status, created_at,
                purchase_type, product_id, email, payment_note, amount_expected, currency,
                requested_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, 'PENDING', ?, 'PRODUCT', ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_id, str(guild_id), str(user_id), paypay_name.strip(), note, now,
                pid, normalized_email, note, int(product["price_amount"]),
                product["price_currency"], now, now,
            ),
        )
        cur.execute("UPDATE user_T SET email=?, updated_at=? WHERE user_id=?", (normalized_email, now, str(user_id)))
        if cur.rowcount == 0:
            cur.execute(
                """
                INSERT INTO user_T(user_id, nickname, email, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (str(user_id), "", normalized_email, now, now),
            )
        conn.commit()
        return request_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def get_order(order_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.*, p.product_name, p.product_type, p.download_url, p.download_password,
               p.file_size_label, p.content_count_label, p.status AS product_status
        FROM requests r
        LEFT JOIN product_T p ON p.product_id=r.product_id
        WHERE r.request_id=?
        """,
        (order_id,),
    )
    row = cur.fetchone()
    conn.close()
    return row


def approve_product_order(order_id: str, approved_by: int) -> bool:
    conn = _conn()
    try:
        cur = conn.cursor()
        now = utc_now_iso()
        cur.execute(
            """
            UPDATE requests
            SET status='APPROVED', approved_by=?, approved_at=?, updated_at=?
            WHERE request_id=? AND purchase_type='PRODUCT' AND status='PENDING'
            """,
            (str(approved_by), now, now, order_id),
        )
        if cur.rowcount != 1:
            conn.rollback()
            return False
        cur.execute(
            """
            UPDATE requests
            SET status='DELIVERY_PENDING', updated_at=?
            WHERE request_id=? AND purchase_type='PRODUCT' AND status='APPROVED'
            """,
            (now, order_id),
        )
        conn.commit()
        return cur.rowcount == 1
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def set_order_delivery_status(order_id: str, status: str) -> bool:
    if status not in {"SENT", "DELIVERY_FAILED"}:
        raise ValueError("invalid delivery order status")
    now = utc_now_iso()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE requests
        SET status=?, delivery_completed_at=CASE WHEN ?='SENT' THEN ? ELSE delivery_completed_at END, updated_at=?
        WHERE request_id=? AND purchase_type='PRODUCT' AND status IN ('DELIVERY_PENDING', 'DELIVERY_FAILED', 'SENT')
        """,
        (status, status, now, now, order_id),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def mark_order_delivery_pending(order_id: str) -> bool:
    now = utc_now_iso()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE requests
        SET status='DELIVERY_PENDING', updated_at=?
        WHERE request_id=? AND purchase_type='PRODUCT' AND status IN ('SENT', 'DELIVERY_FAILED')
        """,
        (now, order_id),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def reject_product_order(order_id: str, rejected_by: int, reason: Optional[str]) -> bool:
    now = utc_now_iso()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE requests
        SET status='REJECTED', rejected_by=?, rejected_at=?, reject_reason=?, updated_at=?
        WHERE request_id=? AND purchase_type='PRODUCT' AND status='PENDING'
        """,
        (str(rejected_by), now, (reason or "").strip()[:300], now, order_id),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def create_delivery_record(
    *,
    order_id: str,
    channel: str,
    destination_masked: Optional[str],
    status: str,
    error_code: Optional[str] = None,
    error_message: Optional[str] = None,
) -> str:
    delivery_id = str(uuid.uuid4())
    now = utc_now_iso()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT COALESCE(MAX(attempt_count), 0) + 1 AS next_attempt FROM delivery_T WHERE order_id=?", (order_id,))
        attempt = int(cur.fetchone()["next_attempt"])
        cur.execute(
            """
            INSERT INTO delivery_T(
                delivery_id, order_id, channel, destination_masked, status, attempt_count,
                error_code, error_message, attempted_at, completed_at, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                delivery_id, order_id, channel, destination_masked, status, attempt,
                error_code, (error_message or "")[:300] if error_message else None,
                now, now if status == "SENT" else None, now,
            ),
        )
        conn.commit()
        return delivery_id
    finally:
        conn.close()


def list_order_deliveries(order_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM delivery_T WHERE order_id=? ORDER BY attempted_at DESC",
        (order_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_user_orders(user_id: int, limit: int = 20):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.request_id, r.product_id, r.status, r.requested_at, r.approved_at,
               r.amount_expected, r.currency, p.product_name
        FROM requests r
        LEFT JOIN product_T p ON p.product_id=r.product_id
        WHERE r.purchase_type='PRODUCT' AND r.user_id=?
        ORDER BY r.requested_at DESC
        LIMIT ?
        """,
        (str(user_id), int(limit)),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def list_product_order_ids_for_review_views(limit: int = 200) -> List[str]:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT request_id
        FROM requests
        WHERE purchase_type='PRODUCT'
          AND status IN ('PENDING', 'SENT', 'DELIVERY_FAILED', 'DELIVERY_PENDING')
        ORDER BY requested_at DESC
        LIMIT ?
        """,
        (int(limit),),
    )
    rows = [row["request_id"] for row in cur.fetchall()]
    conn.close()
    return rows


def list_user_purchased_products(user_id: int):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT p.*, MIN(r.requested_at) AS first_purchased_at, COUNT(*) AS order_count
        FROM requests r
        JOIN product_T p ON p.product_id=r.product_id
        WHERE r.purchase_type='PRODUCT' AND r.user_id=? AND r.status='SENT'
        GROUP BY p.product_id
        ORDER BY first_purchased_at DESC
        """,
        (str(user_id),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def get_latest_sent_order_for_product(user_id: int, product_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT r.*, p.product_name, p.download_url, p.download_password, p.file_size_label, p.updated_at AS product_updated_at
        FROM requests r
        JOIN product_T p ON p.product_id=r.product_id
        WHERE r.purchase_type='PRODUCT' AND r.user_id=? AND r.product_id=? AND r.status='SENT'
        ORDER BY r.requested_at DESC
        LIMIT 1
        """,
        (str(user_id), normalize_product_id(product_id)),
    )
    row = cur.fetchone()
    conn.close()
    return row


# ===== Community / long-term features =====
def create_feed_post(
    *,
    title: str,
    body: str,
    created_by: int,
    source: str = "MANUAL",
    external_post_id: Optional[str] = None,
    preview_url: Optional[str] = None,
    original_url: Optional[str] = None,
) -> str:
    now = utc_now_iso()
    post_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO feed_post_T(post_id, source, external_post_id, title, body, preview_url, original_url, created_by, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            post_id, source.upper(), external_post_id, title.strip()[:200], body.strip()[:1800],
            validate_https_url(preview_url) if preview_url else None,
            validate_https_url(original_url) if original_url else None,
            str(created_by), now,
        ),
    )
    conn.commit()
    conn.close()
    return post_id


def list_feed_posts(limit: int = 10):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM feed_post_T WHERE status='PUBLISHED' ORDER BY created_at DESC LIMIT ?", (int(limit),))
    rows = cur.fetchall()
    conn.close()
    return rows


def create_poll(title: str, options: List[str], created_by: int, description: Optional[str] = None, visibility: str = "PUBLIC", closes_at: Optional[str] = None) -> str:
    clean_options = [o.strip() for o in options if o.strip()]
    if len(clean_options) < 2 or len(clean_options) > 10:
        raise ValueError("poll requires 2-10 options")
    if visibility not in {"PUBLIC", "BUYER"}:
        raise ValueError("visibility must be PUBLIC or BUYER")
    poll_id = str(uuid.uuid4())
    now = utc_now_iso()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "INSERT INTO poll_T(poll_id, title, description, visibility, created_by, created_at, closes_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
            (poll_id, title.strip()[:200], (description or "").strip()[:800] or None, visibility, str(created_by), now, closes_at),
        )
        cur.executemany(
            "INSERT INTO poll_option_T(poll_id, option_index, label) VALUES (?, ?, ?)",
            [(poll_id, idx + 1, label[:100]) for idx, label in enumerate(clean_options)],
        )
        conn.commit()
        return poll_id
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def vote_poll(poll_id: str, user_id: int, option_index: int) -> bool:
    now = utc_now_iso()
    conn = _conn()
    try:
        cur = conn.cursor()
        cur.execute("SELECT status FROM poll_T WHERE poll_id=?", (poll_id,))
        poll = cur.fetchone()
        if poll is None or poll["status"] != "OPEN":
            raise ValueError("poll is not open")
        cur.execute("SELECT 1 FROM poll_option_T WHERE poll_id=? AND option_index=?", (poll_id, int(option_index)))
        if cur.fetchone() is None:
            raise ValueError("poll option not found")
        cur.execute(
            """
            INSERT INTO poll_vote_T(poll_id, user_id, option_index, voted_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(poll_id, user_id) DO UPDATE SET option_index=excluded.option_index, voted_at=excluded.voted_at
            """,
            (poll_id, str(user_id), int(option_index), now),
        )
        conn.commit()
        return True
    finally:
        conn.close()


def get_poll(poll_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM poll_T WHERE poll_id=?", (poll_id,))
    row = cur.fetchone()
    conn.close()
    return row


def close_poll(poll_id: str) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute("UPDATE poll_T SET status='CLOSED' WHERE poll_id=? AND status='OPEN'", (poll_id,))
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def poll_results(poll_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT o.option_index, o.label, COUNT(v.user_id) AS votes
        FROM poll_option_T o
        LEFT JOIN poll_vote_T v ON v.poll_id=o.poll_id AND v.option_index=o.option_index
        WHERE o.poll_id=?
        GROUP BY o.option_index, o.label
        ORDER BY o.option_index
        """,
        (poll_id,),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def create_question(user_id: int, body: str, is_anonymous: bool = False) -> str:
    question_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO question_T(question_id, user_id, body, is_anonymous, created_at) VALUES (?, ?, ?, ?, ?)",
        (question_id, str(user_id), body.strip()[:1000], 1 if is_anonymous else 0, utc_now_iso()),
    )
    conn.commit()
    conn.close()
    return question_id


def answer_question(question_id: str, answer: str, answered_by: int) -> bool:
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        UPDATE question_T
        SET status='ANSWERED', answer=?, answered_by=?, answered_at=?
        WHERE question_id=? AND status='OPEN'
        """,
        (answer.strip()[:1800], str(answered_by), utc_now_iso(), question_id),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def list_questions(status: Optional[str] = None, limit: int = 20):
    conn = _conn()
    cur = conn.cursor()
    if status:
        cur.execute("SELECT * FROM question_T WHERE status=? ORDER BY created_at DESC LIMIT ?", (status, int(limit)))
    else:
        cur.execute("SELECT * FROM question_T ORDER BY created_at DESC LIMIT ?", (int(limit),))
    rows = cur.fetchall()
    conn.close()
    return rows


def create_club_event(title: str, starts_at: str, created_by: int, description: Optional[str] = None, buyer_only: bool = False) -> str:
    event_id = str(uuid.uuid4())
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "INSERT INTO club_event_T(event_id, title, description, starts_at, buyer_only, created_by, created_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
        (event_id, title.strip()[:200], (description or "").strip()[:1000] or None, starts_at, 1 if buyer_only else 0, str(created_by), utc_now_iso()),
    )
    conn.commit()
    conn.close()
    return event_id


def join_club_event(event_id: str, user_id: int) -> bool:
    now = utc_now_iso()
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT status FROM club_event_T WHERE event_id=?", (event_id,))
    event = cur.fetchone()
    if event is None or event["status"] != "OPEN":
        conn.close()
        raise ValueError("event is not open")
    cur.execute(
        """
        INSERT INTO event_rsvp_T(event_id, user_id, status, joined_at)
        VALUES (?, ?, 'JOINED', ?)
        ON CONFLICT(event_id, user_id) DO UPDATE SET status='JOINED', joined_at=excluded.joined_at
        """,
        (event_id, str(user_id), now),
    )
    conn.commit()
    conn.close()
    return True


def get_club_event(event_id: str):
    conn = _conn()
    cur = conn.cursor()
    cur.execute("SELECT * FROM club_event_T WHERE event_id=?", (event_id,))
    row = cur.fetchone()
    conn.close()
    return row


def list_club_events(limit: int = 20):
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        SELECT e.*, COUNT(r.user_id) AS joined_count
        FROM club_event_T e
        LEFT JOIN event_rsvp_T r ON r.event_id=e.event_id AND r.status='JOINED'
        GROUP BY e.event_id
        ORDER BY e.starts_at ASC
        LIMIT ?
        """,
        (int(limit),),
    )
    rows = cur.fetchall()
    conn.close()
    return rows


def set_supporter_level(user_id: int, level_name: str, benefits: Optional[str], updated_by: int) -> None:
    now = utc_now_iso()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO supporter_level_T(user_id, level_name, benefits, updated_by, updated_at)
        VALUES (?, ?, ?, ?, ?)
        ON CONFLICT(user_id) DO UPDATE SET
            level_name=excluded.level_name,
            benefits=excluded.benefits,
            updated_by=excluded.updated_by,
            updated_at=excluded.updated_at
        """,
        (str(user_id), level_name.strip()[:100], (benefits or "").strip()[:800] or None, str(updated_by), now),
    )
    conn.commit()
    conn.close()


def create_fan_submission(user_id: int, title: str, url: Optional[str] = None, note: Optional[str] = None) -> str:
    submission_id = str(uuid.uuid4())
    now = utc_now_iso()
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        """
        INSERT INTO fan_submission_T(submission_id, user_id, title, url, note, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (submission_id, str(user_id), title.strip()[:200], validate_https_url(url) if url else None, (note or "").strip()[:1000] or None, now, now),
    )
    conn.commit()
    conn.close()
    return submission_id


def pick_fan_submission(submission_id: str, yyyymm: str) -> bool:
    if len(yyyymm) != 6 or not yyyymm.isdigit():
        raise ValueError("yyyymm must be YYYYMM")
    conn = _conn()
    cur = conn.cursor()
    cur.execute(
        "UPDATE fan_submission_T SET status='PICKED', picked_month=?, updated_at=? WHERE submission_id=?",
        (yyyymm, utc_now_iso(), submission_id),
    )
    conn.commit()
    ok = cur.rowcount == 1
    conn.close()
    return ok


def export_public_products_json(path: str) -> int:
    rows = list_products(status="SALE", limit=500)
    payload = [
        {
            "product_id": row["product_id"],
            "product_name": row["product_name"],
            "description": row["description"],
            "price_amount": row["price_amount"],
            "price_currency": row["price_currency"],
            "cover_url": row["cover_url"],
            "preview_images": [row["preview_url"]] if row["preview_url"] else [],
            "content_count_label": row["content_count_label"],
            "file_size_label": row["file_size_label"],
            "discord_url": "",
            "status": row["status"],
        }
        for row in rows
    ]
    with open(path, "w", encoding="utf-8") as fp:
        json.dump(payload, fp, ensure_ascii=False, indent=2)
    return len(payload)
