"""Shared P0 catalog, grants and durable Discord outbox. No payment verification."""
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

JST = ZoneInfo('Asia/Tokyo')
KINDS = ('news', 'events', 'works', 'series', 'plans')
FIELDS = {
    'news': {'id','title','description','cover_url','detail_url','published_at','pinned','status','public'},
    'events': {'id','title','description','cover_url','event_type','starts_at','ends_at','deadline_at','location','price_label','booking_url','full','pinned','status','public'},
    'works': {'id','title','description','cover_url','preview_images','published_at','series_id','tags','format','price_label','purchase_url','sale_status','status','public','sort_order'},
    'series': {'id','title','description','cover_url','sort_order','status','public'},
    'plans': {'id','title','description','price_label','benefits','role_ids','sort_order','status','public'},
}
PUBLIC_FIELDS = {k: v - {'role_ids'} for k,v in FIELDS.items()}


def now_ts():
    return datetime.now(timezone.utc).timestamp()


def timestamp(value):
    dt = datetime.fromisoformat(str(value).replace('Z', '+00:00'))
    return (dt.replace(tzinfo=JST) if dt.tzinfo is None else dt).timestamp()


@contextmanager
def db():
    path = os.getenv('CLUB_DB_PATH', os.getenv('DB_PATH', 'bot.db'))
    c = sqlite3.connect(path, timeout=15)
    c.row_factory = sqlite3.Row
    try:
        c.execute('PRAGMA foreign_keys=ON')
        yield c
        c.commit()
    except BaseException:
        c.rollback()
        raise
    finally:
        c.close()


def init():
    with db() as c:
        c.executescript('''
        CREATE TABLE IF NOT EXISTS club_content(kind TEXT, id TEXT, body TEXT NOT NULL, revision INTEGER NOT NULL, PRIMARY KEY(kind,id));
        CREATE TABLE IF NOT EXISTS club_grants(id TEXT PRIMARY KEY, guild_id TEXT NOT NULL, user_id TEXT NOT NULL, plan_id TEXT NOT NULL, starts REAL NOT NULL, ends REAL NOT NULL, source TEXT NOT NULL, note TEXT NOT NULL, cancelled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS club_managed_roles(guild_id TEXT, role_id TEXT, PRIMARY KEY(guild_id,role_id));
        CREATE TABLE IF NOT EXISTS club_sync_users(guild_id TEXT, user_id TEXT, PRIMARY KEY(guild_id,user_id));
        CREATE TABLE IF NOT EXISTS club_outbox(id TEXT PRIMARY KEY, source_key TEXT UNIQUE NOT NULL, channel_id TEXT NOT NULL, body TEXT NOT NULL, nonce TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'PENDING', message_id TEXT, error TEXT, claimed_at REAL, image_url TEXT);
        CREATE TABLE IF NOT EXISTS club_audit(id INTEGER PRIMARY KEY, at REAL NOT NULL, actor TEXT NOT NULL, action TEXT NOT NULL, target TEXT NOT NULL, detail TEXT NOT NULL);
        ''')
        if 'image_url' not in {r[1] for r in c.execute('PRAGMA table_info(club_outbox)')}:
            c.execute('ALTER TABLE club_outbox ADD COLUMN image_url TEXT')


def audit(c, actor, action, target, detail=''):
    c.execute('INSERT INTO club_audit(at,actor,action,target,detail) VALUES(?,?,?,?,?)', (now_ts(),actor,action,target,str(detail)[:2000]))


def records(kind):
    if kind not in KINDS:
        raise ValueError('unknown content kind')
    with db() as c:
        return [dict(json.loads(r['body']), revision=r['revision']) for r in c.execute('SELECT * FROM club_content WHERE kind=?', (kind,))]


def checked_url(value):
    p = urlparse(value)
    local_origin = urlparse(os.getenv('CLUB_PUBLIC_URL', ''))
    local_http = (os.getenv('CLUB_ALLOW_LOCAL_HTTP') == '1' and p.scheme == 'http'
                  and p.netloc == local_origin.netloc and bool(p.netloc))
    if value and ((p.scheme != 'https' and not local_http) or not p.netloc or p.username or p.password):
        raise ValueError('リンクは https:// で入力してください')
    return value


def validate(kind, body):
    if kind not in KINDS or set(body) - FIELDS[kind] - {'revision'}:
        raise ValueError('unknown fields')
    b = {k:v for k,v in body.items() if k in FIELDS[kind]}
    b['id'] = str(b.get('id') or uuid.uuid4().hex)
    if not b['id'].replace('-', '').replace('_', '').isalnum() or len(b['id']) > 100:
        raise ValueError('invalid ID')
    if not isinstance(b.get('title'), str) or not b['title'].strip():
        raise ValueError('タイトルを入力してください')
    b['title'] = b['title'].strip()[:200]
    b.setdefault('description','')
    b.setdefault('status','DRAFT')
    b.setdefault('public',True)
    if b['status'] not in ('DRAFT','PUBLISHED','CANCELLED') or (b['status']=='CANCELLED' and kind!='events'):
        raise ValueError('invalid publication status')
    for key in ('public','pinned','full'):
        if key in b and not isinstance(b[key],bool):
            raise ValueError('invalid boolean')
    for key in ('cover_url','detail_url','booking_url','purchase_url'):
        if b.get(key): checked_url(b[key])
    for key in ('preview_images','tags','benefits','role_ids'):
        if key in b and (not isinstance(b[key], list) or any(not isinstance(x,str) for x in b[key])):
            raise ValueError('invalid list')
    for url in b.get('preview_images',[]): checked_url(url)
    for key in ('starts_at','ends_at','deadline_at','published_at'):
        if b.get(key): b[key] = datetime.fromtimestamp(timestamp(b[key]), JST).isoformat()
    if kind=='events':
        if not b.get('starts_at') or not b.get('ends_at') or timestamp(b['ends_at']) <= timestamp(b['starts_at']):
            raise ValueError('終了時刻は開始時刻より後にしてください')
        if b.get('deadline_at') and timestamp(b['deadline_at']) > timestamp(b['ends_at']):
            raise ValueError('締切は終了時刻以前にしてください')
    if kind=='plans' and any(not x.isdigit() or int(x)<=0 for x in b.get('role_ids',[])):
        raise ValueError('invalid Discord role ID')
    if kind=='works':
        b.setdefault('sale_status','COMING_SOON')
        if b['sale_status'] not in ('COMING_SOON','SALE','STOP'): raise ValueError('invalid sale status')
    b['sort_order'] = int(b.get('sort_order') or 0) if 'sort_order' in FIELDS[kind] else 0
    if 'sort_order' not in FIELDS[kind]: b.pop('sort_order')
    return b


def queue(c, source_key, channel_id, body, image_url=None):
    if not str(channel_id).isdigit() or int(channel_id)<=0:
        raise ValueError('Discord チャンネル ID を設定してください')
    if not body or len(body)>1900: raise ValueError('通知は1〜1900文字にしてください')
    if image_url: checked_url(image_url)
    identifier = uuid.uuid4().hex
    nonce = str(uuid.uuid4().int % (2**63))
    c.execute('INSERT OR IGNORE INTO club_outbox(id,source_key,channel_id,body,nonce,image_url) VALUES(?,?,?,?,?,?)', (identifier,source_key,str(channel_id),body,nonce,image_url))
    return c.execute('SELECT id FROM club_outbox WHERE source_key=?',(source_key,)).fetchone()[0]


def save(kind, body, actor='admin', notify_channel=None):
    b = validate(kind,body)
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        old = c.execute('SELECT revision FROM club_content WHERE kind=? AND id=?',(kind,b['id'])).fetchone()
        if old and body.get('revision') != old[0]: raise ValueError('他の編集が保存されています。再読み込みしてください')
        revision = old[0]+1 if old else 1
        c.execute('INSERT INTO club_content VALUES(?,?,?,?) ON CONFLICT(kind,id) DO UPDATE SET body=excluded.body,revision=excluded.revision',(kind,b['id'],json.dumps(b,ensure_ascii=False),revision))
        if kind=='plans':
            # Preserve removed mappings so the worker can remove obsolete roles, too.
            for row in c.execute('SELECT DISTINCT guild_id FROM club_grants WHERE plan_id=?',(b['id'],)):
                for role in b.get('role_ids',[]): c.execute('INSERT OR IGNORE INTO club_managed_roles VALUES(?,?)',(row[0],role))
        if notify_channel:
            if b['status'] not in ('PUBLISHED','CANCELLED') or not b['public']: raise ValueError('公開済みの内容のみ通知できます')
            label = '【中止】' if b['status']=='CANCELLED' else ''
            base = os.getenv('CLUB_SITE_URL','').rstrip('/')
            detail = b.get('detail_url') or (f"{base}/ja/{kind}/{b['id']}" if base and kind in ('events','works','news') else '')
            message = f"{label}{b['title']}\n{b['description'][:1000]}"
            if kind=='events': message += f"\n{b['starts_at']} 〜 {b['ends_at']} (Asia/Tokyo)"
            if detail: message += '\n'+detail
            queue(c,f'{kind}:{b["id"]}:{revision}',notify_channel,message,b.get("cover_url"))
        audit(c,actor,'content.save',f'{kind}/{b["id"]}',f'revision={revision}')
    return dict(b,revision=revision)


def event_state(b, at=None):
    at = now_ts() if at is None else at
    if b['status']=='CANCELLED': return 'CANCELLED'
    if timestamp(b['ends_at'])<=at: return 'ENDED'
    if b.get('full'): return 'FULL'
    if b.get('deadline_at') and timestamp(b['deadline_at'])<=at: return 'CLOSED'
    return 'OPEN'


def catalog(at=None):
    at = now_ts() if at is None else at
    result = {}
    for kind in KINDS:
        rows=[]
        for b in records(kind):
            if b['status'] not in ('PUBLISHED','CANCELLED') or not b['public']: continue
            if b.get('published_at') and timestamp(b['published_at'])>at: continue
            row={k:v for k,v in b.items() if k in PUBLIC_FIELDS[kind]}
            if kind=='events':
                row['display_state']=event_state(b,at)
                row['ended']=timestamp(b['ends_at'])<=at
                if row['display_state']!='OPEN': row.pop('booking_url',None)
            if kind=='works' and row.get('sale_status')!='SALE': row.pop('purchase_url',None)
            rows.append(row)
        result[kind]=sorted(rows,key=lambda x:(not x.get('pinned',False),x.get('sort_order',0),(1 if kind=='events' else -1)*timestamp(x.get('starts_at') or x.get('published_at') or '1970-01-01T00:00:00Z')))
    return result


def grants():
    with db() as c: return [dict(r) for r in c.execute('SELECT * FROM club_grants ORDER BY ends DESC')]


def grant(body, actor='admin'):
    guild,user,plan = str(body['guild_id']),str(body['user_id']),str(body['plan_id'])
    if not guild.isdigit() or not user.isdigit() or int(guild)<=0 or int(user)<=0: raise ValueError('invalid Discord ID')
    plans = {p['id']:p for p in records('plans')}
    if plan not in plans: raise ValueError('プランがありません')
    starts,ends=timestamp(body['starts_at']),timestamp(body['ends_at'])
    if ends<=starts: raise ValueError('invalid period')
    source=body.get('source','MANUAL')
    if source not in ('MANUAL','GIFT'): raise ValueError('invalid source')
    identifier=str(body.get('id') or uuid.uuid4().hex)
    if len(identifier)>100 or not identifier.replace('-', '').replace('_', '').isalnum(): raise ValueError('invalid grant ID')
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        existing=c.execute('SELECT * FROM club_grants WHERE id=?',(identifier,)).fetchone()
        if existing:
            if (existing['guild_id'],existing['user_id'],existing['plan_id'],existing['starts'],existing['ends'],existing['source'],existing['note']) != (guild,user,plan,starts,ends,source,str(body.get('note',''))[:1000]):
                raise ValueError('同じ登録 ID の内容が異なります')
            return identifier
        c.execute('INSERT INTO club_grants(id,guild_id,user_id,plan_id,starts,ends,source,note) VALUES(?,?,?,?,?,?,?,?)',(identifier,guild,user,plan,starts,ends,source,str(body.get('note',''))[:1000]))
        c.execute('INSERT OR IGNORE INTO club_sync_users VALUES(?,?)',(guild,user))
        for role in plans[plan].get('role_ids',[]): c.execute('INSERT OR IGNORE INTO club_managed_roles VALUES(?,?)',(guild,role))
        audit(c,actor,'membership.grant',identifier,source)
    return identifier


def change_grant(identifier, body, actor='admin'):
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        row=c.execute('SELECT * FROM club_grants WHERE id=?',(identifier,)).fetchone()
        if row is None: raise ValueError('資格がありません')
        action=body['action']
        if action=='cancel': c.execute('UPDATE club_grants SET cancelled=1 WHERE id=?',(identifier,))
        elif action=='extend':
            ends=timestamp(body['ends_at'])
            if ends<=row['ends']: raise ValueError('延長後の日付を指定してください')
            c.execute('UPDATE club_grants SET ends=? WHERE id=?',(ends,identifier))
        elif action=='change':
            plans={p['id']:p for p in records('plans')}
            plan=plans.get(body['plan_id'])
            if not plan: raise ValueError('プランがありません')
            for role in plan.get('role_ids',[]): c.execute('INSERT OR IGNORE INTO club_managed_roles VALUES(?,?)',(row['guild_id'],role))
            c.execute('UPDATE club_grants SET plan_id=? WHERE id=?',(plan['id'],identifier))
        else: raise ValueError('unknown membership action')
        audit(c,actor,'membership.'+action,identifier)


def role_snapshot(at=None):
    at=now_ts() if at is None else at
    plans={p['id']:p for p in records('plans')}
    with db() as c:
        expected={(r['guild_id'],r['user_id']):set() for r in c.execute('SELECT * FROM club_sync_users')}
        managed={}
        for r in c.execute('SELECT * FROM club_managed_roles'): managed.setdefault(r['guild_id'],set()).add(int(r['role_id']))
        for r in c.execute('SELECT * FROM club_grants WHERE cancelled=0 AND starts<=? AND ends>?',(at,at)):
            plan=plans.get(r['plan_id'],{})
            roles={int(x) for x in plan.get('role_ids',[])}
            expected.setdefault((r['guild_id'],r['user_id']),set()).update(roles)
            managed.setdefault(r['guild_id'],set()).update(roles)
        return expected,managed


def outbox():
    with db() as c: return [dict(r) for r in c.execute('SELECT id,source_key,channel_id,body,status,message_id,error FROM club_outbox ORDER BY rowid DESC LIMIT 100')]


def enqueue_notice(source_key,channel_id,body,actor='admin',image_url=None):
    if not source_key or len(source_key)>200: raise ValueError('通知の識別子を入力してください')
    with db() as c:
        identifier=queue(c,'manual:'+source_key,channel_id,body,image_url)
        audit(c,actor,'notice.queue',identifier)
        return identifier


def claim_notice():
    with db() as c:
        c.execute('BEGIN IMMEDIATE')
        # A crash after Discord accepted a message is ambiguous. Never blindly resend.
        c.execute("UPDATE club_outbox SET status='UNCERTAIN',error='送信中に中断。Discord 履歴を確認してください' WHERE status='SENDING' AND claimed_at<?",(now_ts()-120,))
        row=c.execute("SELECT * FROM club_outbox WHERE status='PENDING' ORDER BY rowid LIMIT 1").fetchone()
        if row:
            c.execute("UPDATE club_outbox SET status='SENDING',claimed_at=? WHERE id=?",(now_ts(),row['id']))
            return dict(row)
    return None


def finish_notice(identifier,status,message_id=None,error=None):
    with db() as c:
        c.execute('UPDATE club_outbox SET status=?,message_id=COALESCE(?,message_id),error=? WHERE id=?',(status,message_id,error,identifier))
        audit(c,'bot','notice.'+status.lower(),identifier,error or message_id or '')
