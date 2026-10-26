"""Authenticated mobile admin + public allowlisted catalog API (Python stdlib)."""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import time
import uuid
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlsplit
import club_store as store

MAX_BODY=6*1024*1024
LOGIN_ATTEMPTS={}


def secret():
    value=os.getenv('CLUB_ADMIN_SECRET','')
    if len(value)<32: raise RuntimeError('CLUB_ADMIN_SECRET must contain at least 32 characters')
    return value.encode()


def sign(value):
    return hmac.new(secret(),value.encode(),hashlib.sha256).hexdigest()


def session():
    payload=f'{int(time.time())+8*3600}.{secrets.token_hex(24)}'
    return payload+'.'+sign(payload)


def valid_session(value):
    try:
        payload,sig=value.rsplit('.',1)
        return hmac.compare_digest(sign(payload),sig) and int(payload.split('.')[0])>time.time()
    except (ValueError,TypeError): return False


def shell(body):
    return '''<!doctype html><html lang="ja"><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><title>Kiri Club 管理</title><style>
    *{box-sizing:border-box}body{background:#11121a;color:#f0ecf8;font:16px system-ui;margin:0 auto;padding:24px;max-width:1000px}a{color:#d0b5ff}nav{display:flex;gap:14px;flex-wrap:wrap;margin:22px 0}input,textarea,select,button{font:inherit;padding:12px;border-radius:10px;border:1px solid #555;background:#20212e;color:inherit;width:100%;margin:6px 0 16px}textarea{min-height:100px}button{background:#675087;cursor:pointer}label{display:block}article,details{padding:18px;margin:16px 0;border:1px solid #444;border-radius:14px}pre{white-space:pre-wrap;overflow-wrap:anywhere}small{color:#bbb}input[type=checkbox]{width:auto}h1{font-size:26px}</style><h1>Kiri Club 管理</h1>'''+body+'</html>'


def esc(value): return html.escape(str(value),quote=True)


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_):
        pass  # Never log credentials or private request payloads.

    def respond(self,status,body,ctype='text/html; charset=utf-8',cookie=None):
        data=body.encode() if isinstance(body,str) else body
        self.send_response(status)
        self.send_header('Content-Type',ctype)
        self.send_header('Content-Length',str(len(data)))
        self.send_header('Cache-Control','no-store, max-age=0')
        self.send_header('X-Content-Type-Options','nosniff')
        self.send_header('X-Frame-Options','DENY')
        self.send_header('Referrer-Policy','same-origin')
        self.send_header('Content-Security-Policy',"default-src 'self'; script-src 'self'; style-src 'unsafe-inline'; img-src 'self' https:; form-action 'self'; frame-ancestors 'none'")
        if cookie: self.send_header('Set-Cookie',cookie)
        self.end_headers()
        self.wfile.write(data)

    def token(self):
        try:
            cookies=SimpleCookie(self.headers.get('Cookie',''))
            return cookies['club_session'].value if 'club_session' in cookies else ''
        except Exception: return ''

    def body(self):
        size=int(self.headers.get('Content-Length','0'))
        if size<0 or size>MAX_BODY: raise ValueError('ファイルが大きすぎます (最大4MB)')
        raw=self.rfile.read(size)
        if self.headers.get('Content-Type','').startswith('application/json'): return json.loads(raw)
        return {k:v[-1] for k,v in parse_qs(raw.decode(),keep_blank_values=True).items()}

    def do_GET(self):
        path=urlsplit(self.path).path
        if path=='/api/public/catalog':
            self.respond(200,json.dumps(store.catalog(),ensure_ascii=False),'application/json; charset=utf-8');return
        if path.startswith('/media/'):
            name=path.removeprefix('/media/')
            if '/' in name or '..' in name or not name: self.respond(404,'Not found');return
            file=Path(os.getenv('CLUB_MEDIA_DIR','club-media'))/name
            if file.is_file() and file.suffix in ('.png','.jpg','.webp'):
                self.respond(200,file.read_bytes(),{'.png':'image/png','.jpg':'image/jpeg','.webp':'image/webp'}[file.suffix]);return
            self.respond(404,'Not found');return
        if path=='/admin/login':
            self.respond(200,shell('<form method="post" action="/admin/login"><label>管理パスワード<input name="password" type="password" autocomplete="current-password" required></label><button>ログイン</button></form>'));return
        if path=='/admin/editor.js':
            self.respond(200,Path(__file__).with_name('club_editor.js').read_text(),'application/javascript; charset=utf-8');return
        if not path.startswith('/admin'):
            self.respond(404,'Not found');return
        token=self.token()
        if not valid_session(token):
            self.send_response(303);self.send_header('Location','/admin/login');self.end_headers();return
        csrf=sign('csrf:'+token)
        query=parse_qs(urlsplit(self.path).query)
        kind=query.get('kind',['events'])[0]
        nav='<nav>'+''.join(f'<a href="/admin?kind={k}">{v}</a>' for k,v in [('news','お知らせ'),('events','イベント'),('works','作品'),('series','シリーズ'),('plans','会員プラン'),('members','会員'),('notices','通知'),('logs','操作履歴')])+'</nav>'
        content=nav+f'<input id="csrf" type="hidden" value="{csrf}">'
        if kind in store.KINDS:
            rows=store.records(kind)
            selected=next((r for r in rows if r['id']==query.get('id',[''])[0]),{})
            content+='<nav>'+''.join(f'<a href="/admin?kind={kind}&id={esc(r["id"])}">{esc(r["title"])}</a>' for r in rows)+'</nav>'
            content+=self.editor(kind,selected)
        elif kind=='members':
            content+='<p>プレゼント会員は Discord 内の特典のみ対象です。Fantia の会員資格は変更しません。</p>'
            content+=f'<form data-endpoint="/admin/api/grants"><input type="hidden" name="id" value="{uuid.uuid4().hex}"><label>サーバー ID<input name="guild_id" required pattern="[0-9]+"></label><label>ユーザー ID<input name="user_id" required pattern="[0-9]+"></label><label>プラン<select name="plan_id">'+''.join(f'<option value="{esc(p["id"])}">{esc(p["title"])}</option>' for p in store.records('plans'))+'</select></label><label>開始 (日本時間)<input type="datetime-local" name="starts_at" required></label><label>終了 (日本時間)<input type="datetime-local" name="ends_at" required></label><label>登録区分<select name="source"><option value="MANUAL">手動登録</option><option value="GIFT">プレゼント</option></select></label><label>理由・備考<input name="note"></label><button>会員資格を登録</button></form><label>ユーザー ID で検索<input id="member-search"></label>'
            for g in store.grants():
                expiry=store.datetime.fromtimestamp(g['ends'],store.JST).isoformat()
                state = '取消済み' if g['cancelled'] else '期限切れ' if g['ends']<=store.now_ts() else '開始前' if g['starts']>store.now_ts() else '有効'
                content+=f'<article data-user="{esc(g["user_id"])}"><strong>{esc(g["user_id"])} / {esc(g["plan_id"])}</strong><p>{esc(g["source"])} · 終了 {esc(expiry)} · '+state+f'</p><small>{esc(g["note"])}</small><form data-endpoint="/admin/api/grants/{g["id"]}"><select name="action"><option value="extend">延長</option><option value="change">プラン変更</option><option value="cancel">資格取消</option></select><label>延長後の終了<input name="ends_at" type="datetime-local"></label><label>変更先プラン ID<input name="plan_id"></label><button>変更を保存</button></form></article>'
        elif kind=='notices':
            content+='<p>内容をプレビューしてから送信します。同じ識別子は再送されません。</p><form data-endpoint="/admin/api/notices"><label>識別子 (例: fantia-記事番号)<input name="source_key" required></label><label>チャンネル ID<input name="channel_id" required pattern="[0-9]+"></label><label>公開画像 URL (任意)<input name="image_url"></label><label>通知本文・公開リンク<textarea name="body" required maxlength="1900"></textarea></label><button>プレビューして送信予約</button></form>'
            for n in store.outbox():
                content+=f'<article><strong>{esc(n["status"])}</strong><pre>{esc(n["body"])}</pre><small>メッセージ ID: {esc(n["message_id"] or "—")} / {esc(n["error"] or "")}</small></article>'
        elif kind=='logs':
            with store.db() as c: rows=[dict(r) for r in c.execute('SELECT * FROM club_audit ORDER BY id DESC LIMIT 100')]
            content+=''.join('<article>'+esc(str(r))+'</article>' for r in rows)
        else: self.respond(404,'Not found');return
        content+='<p id="result" role="status"></p><dialog id="preview"><pre></pre><button id="confirm">送信する</button><button id="dismiss">戻る</button></dialog><script src="/admin/editor.js" defer></script>'
        self.respond(200,shell(content))

    def editor(self,kind,item):
        labels={'title':'タイトル','description':'説明','cover_url':'公開カバー画像 URL','detail_url':'詳細リンク','published_at':'公開日時 (日本時間)','pinned':'固定表示','public':'一般公開','event_type':'イベント種別','starts_at':'開始 (日本時間)','ends_at':'終了 (日本時間)','deadline_at':'申込締切 (日本時間)','location':'場所','price_label':'料金表示','booking_url':'申込リンク','full':'満員','preview_images':'公開プレビュー画像 URL (1行1件)','series_id':'シリーズ ID','tags':'タグ (1行1件)','format':'内容形式','purchase_url':'外部購入リンク','sale_status':'販売状態','benefits':'特典 (1行1件)','role_ids':'Discord ロール ID (1行1件)','sort_order':'表示順','status':'公開状態'}
        s=f'<form data-kind="{kind}" data-endpoint="/admin/api/content/{kind}">'
        for key in ['id','revision']:
            value=item.get(key,uuid.uuid4().hex if key=='id' else 0)
            s+=f'<input type="hidden" name="{key}" value="{esc(value)}">'
        order=['title','description','cover_url','preview_images','event_type','starts_at','ends_at','deadline_at','published_at','location','price_label','booking_url','series_id','tags','format','purchase_url','sale_status','benefits','role_ids','sort_order','status','full','pinned','public','detail_url']
        for key in [key for key in order if key in store.FIELDS[kind]]:
            value=item.get(key,True if key=='public' else '')
            label=labels.get(key,key)
            s+=f'<label>{esc(label)}'
            if key in ('public','pinned','full'): s+=f'<input type="checkbox" name="{key}" '+('checked' if value else '')+'>'
            elif key in ('status','sale_status'):
                options=('DRAFT','PUBLISHED','CANCELLED') if key=='status' and kind=='events' else ('DRAFT','PUBLISHED') if key=='status' else ('COMING_SOON','SALE','STOP')
                s+=f'<select name="{key}">'+''.join(f'<option value="{x}" '+('selected' if value==x else '')+f'>{dict(DRAFT="下書き",PUBLISHED="公開",CANCELLED="中止",COMING_SOON="発売予定",SALE="発売中",STOP="販売終了")[x]}</option>' for x in options)+'</select>'
            elif key in ('description','preview_images','tags','benefits','role_ids'):
                s+=f'<textarea name="{key}">{esc(chr(10).join(value) if isinstance(value,list) else value)}</textarea>'
            else:
                typ='datetime-local' if key.endswith('_at') else 'number' if key=='sort_order' else 'text'
                if value and typ=='datetime-local': value=store.datetime.fromtimestamp(store.timestamp(value),store.JST).strftime('%Y-%m-%dT%H:%M')
                s+=f'<input name="{key}" type="{typ}" value="{esc(value)}" '+('required' if key in ('title','starts_at','ends_at') else '')+'>'
            s+='</label>'
        s+='<label>画像の用途<select id="image-target"><option value="cover_url">カバー</option><option value="preview_images">プレビューに追加</option></select></label><label>公開画像をアップロード (PNG / JPEG / WebP、最大4MB)<input type="file" id="image-upload" accept="image/png,image/jpeg,image/webp"></label><small>アップロードした画像は一般公開されます。限定コンテンツはアップロードしないでください。</small><label>同時に Discord 通知<input name="notify" type="checkbox"></label><label>通知先チャンネル ID<input name="channel_id"></label><button>保存・通知内容を確認</button></form>'
        return s

    def do_POST(self):
        path=urlsplit(self.path).path
        try:
            b=self.body()
            if path=='/admin/login':
                origin=self.headers.get('Origin')
                if origin and origin!=os.getenv('CLUB_ADMIN_ORIGIN','http://127.0.0.1:8080'): self.respond(403,'Origin rejected');return
                client=self.client_address[0]
                attempts=[t for t in LOGIN_ATTEMPTS.get(client,[]) if t>time.time()-300]
                LOGIN_ATTEMPTS[client]=attempts
                if len(attempts)>=10: self.respond(429,'しばらくお待ちください');return
                password=os.getenv('CLUB_ADMIN_PASSWORD','')
                if len(password)<16 or not hmac.compare_digest(b.get('password','').encode(),password.encode()):
                    attempts.append(time.time());self.respond(401,'ログインできません');return
                cookie='club_session='+session()+'; HttpOnly; SameSite=Strict; Path=/admin; Max-Age=28800'
                if os.getenv('CLUB_COOKIE_SECURE','1')=='1': cookie+='; Secure'
                self.respond(200,shell('<a href="/admin">管理画面へ</a>'),cookie=cookie);return
            token=self.token()
            if not valid_session(token): self.respond(401,'Unauthorized');return
            if not hmac.compare_digest(self.headers.get('X-CSRF-Token',''),sign('csrf:'+token)):
                self.respond(403,'CSRF rejected');return
            if path.startswith('/admin/api/content/'):
                kind=path.rsplit('/',1)[-1]
                result=store.save(kind,b['content'],notify_channel=b.get('channel_id') if b.get('notify') else None)
            elif path=='/admin/api/grants': result={'id':store.grant(b)}
            elif path.startswith('/admin/api/grants/'):
                store.change_grant(path.rsplit('/',1)[-1],b);result={'ok':True}
            elif path=='/admin/api/notices': result={'id':store.enqueue_notice(b['source_key'],b['channel_id'],b['body'],image_url=b.get('image_url'))}
            elif path=='/admin/api/upload': result=self.upload(b)
            else: self.respond(404,'Not found');return
            self.respond(200,json.dumps(result,ensure_ascii=False),'application/json; charset=utf-8')
        except (ValueError,KeyError,TypeError) as exc: self.respond(400,json.dumps({'error':str(exc)},ensure_ascii=False),'application/json; charset=utf-8')
        except Exception:
            self.respond(500,'処理に失敗しました。管理サービスの設定を確認してください。')

    def upload(self,b):
        data=base64.b64decode(b['data'],validate=True)
        if len(data)>4*1024*1024: raise ValueError('4MB以下の画像を選択してください')
        ext='.png' if data.startswith(b'\x89PNG\r\n\x1a\n') else '.jpg' if data.startswith(b'\xff\xd8\xff') else '.webp' if data.startswith(b'RIFF') and data[8:12]==b'WEBP' else None
        if not ext: raise ValueError('PNG/JPEG/WebP のみアップロードできます')
        origin=os.getenv('CLUB_PUBLIC_URL','').rstrip('/')
        store.checked_url(origin)
        if not origin: raise ValueError('CLUB_PUBLIC_URL を設定してください')
        directory=Path(os.getenv('CLUB_MEDIA_DIR','club-media'));directory.mkdir(parents=True,exist_ok=True)
        name=secrets.token_hex(24)+ext
        (directory/name).write_bytes(data)
        with store.db() as c: store.audit(c,'admin','image.upload',name)
        return {'url':origin+'/media/'+name}


def serve():
    secret()
    if len(os.getenv('CLUB_ADMIN_PASSWORD',''))<16: raise RuntimeError('CLUB_ADMIN_PASSWORD must contain at least 16 characters')
    store.init()
    server=ThreadingHTTPServer((os.getenv('CLUB_ADMIN_HOST','127.0.0.1'),int(os.getenv('CLUB_ADMIN_PORT','8080'))),Handler)
    print('Kiri Club admin listening',server.server_address,flush=True)
    server.serve_forever()


if __name__=='__main__': serve()
