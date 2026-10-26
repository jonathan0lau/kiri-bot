import asyncio
import json
import os
import tempfile
import threading
import unittest
from http.client import HTTPConnection
from unittest.mock import AsyncMock, MagicMock
from http.server import ThreadingHTTPServer

import club_store as store
import club_worker as worker
import club_admin as admin


class Fixture(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory()
        self.previous=os.environ.get('CLUB_DB_PATH')
        os.environ['CLUB_DB_PATH']=self.tmp.name+'/club.db'
        store.init()
        self.at=store.timestamp('2026-10-26T12:00:00+09:00')

    def tearDown(self):
        if self.previous is None: os.environ.pop('CLUB_DB_PATH',None)
        else: os.environ['CLUB_DB_PATH']=self.previous
        self.tmp.cleanup()

    def plan(self,identifier='gold',roles=None):
        return store.save('plans',{'id':identifier,'title':identifier,'status':'PUBLISHED','role_ids':roles or ['100'],'benefits':['Discord benefits']})

    def grant(self,**changes):
        b=dict(guild_id='10',user_id='20',plan_id='gold',starts_at='2026-10-01',ends_at='2026-11-01',source='MANUAL')
        b.update(changes)
        return store.grant(b)

    def event(self,**changes):
        b=dict(id='meet',title='撮影会',status='PUBLISHED',starts_at='2026-10-26T10:00',ends_at='2026-10-26T14:00',deadline_at='2026-10-26T11:00',booking_url='https://example.com/book')
        channel=changes.pop('notify_channel',None)
        b.update(changes)
        return store.save('events',b,notify_channel=channel)


class ClubTests(Fixture):
    def test_deadline_is_not_end_and_history_is_retained(self):
        e=self.event()
        self.assertEqual(store.event_state(e,self.at),'CLOSED')
        r=store.catalog(self.at)['events'][0]
        self.assertFalse(r['ended'])
        self.assertNotIn('booking_url',r)
        r=store.catalog(self.at+3*3600)['events'][0]
        self.assertTrue(r['ended'])
        self.assertEqual(r['id'],'meet')
        e['ends_at']='2026-10-27T14:00'
        e['deadline_at']='2026-10-27T09:00'
        self.event(**e)
        self.assertEqual(store.catalog(self.at+3*3600)['events'][0]['display_state'],'OPEN')

    def test_cancelled_full_and_draft(self):
        e=self.event(full=True)
        self.assertEqual(store.event_state(e,self.at),'FULL')
        e.update(status='CANCELLED')
        store.save('events',e)
        r=store.catalog(self.at)['events'][0]
        self.assertEqual(r['display_state'],'CANCELLED')
        self.assertNotIn('booking_url',r)
        self.event(id='draft',status='DRAFT')
        self.assertEqual(len(store.catalog(self.at)['events']),1)

    def test_jst_is_normalized_and_end_boundary(self):
        e=self.event()
        self.assertTrue(e['ends_at'].endswith('+09:00'))
        self.assertEqual(store.event_state(e,store.timestamp(e['ends_at'])),'ENDED')

    def test_overlapping_gift_does_not_revoke_other_grant(self):
        self.plan()
        gift=self.grant(source='GIFT',ends_at='2026-10-20')
        paid=self.grant()
        expected,_=store.role_snapshot(self.at)
        self.assertEqual(expected[('10','20')],{100})
        store.change_grant(gift,{'action':'cancel'})
        self.assertEqual(store.role_snapshot(self.at)[0][('10','20')],{100})
        store.change_grant(paid,{'action':'cancel'})
        self.assertEqual(store.role_snapshot(self.at)[0][('10','20')],set())

    def test_extend_change_and_future_start(self):
        self.plan()
        self.plan('silver',['101'])
        g=self.grant(ends_at='2026-10-20')
        self.assertEqual(store.role_snapshot(self.at)[0][('10','20')],set())
        store.change_grant(g,{'action':'extend','ends_at':'2026-11-15'})
        self.assertEqual(store.role_snapshot(self.at)[0][('10','20')],{100})
        store.change_grant(g,{'action':'change','plan_id':'silver'})
        expected,managed=store.role_snapshot(self.at)
        self.assertEqual(expected[('10','20')],{101})
        self.assertEqual(managed['10'],{100,101})
        self.grant(user_id='21',starts_at='2026-11-01',ends_at='2026-12-01')
        self.assertEqual(store.role_snapshot(self.at)[0][('10','21')],set())

    def test_plan_mapping_change_removes_previous_role(self):
        p=self.plan()
        self.grant()
        p['role_ids']=['102']
        store.save('plans',p)
        expected,managed=store.role_snapshot(self.at)
        self.assertEqual(expected[('10','20')],{102})
        self.assertEqual(managed['10'],{100,102})

    def test_public_allowlist_and_stopped_purchase(self):
        self.plan()
        self.event(public=False)
        store.save('works',dict(title='book',status='PUBLISHED',sale_status='STOP',purchase_url='https://example.com/buy'))
        data=store.catalog(self.at)
        self.assertNotIn('role_ids',data['plans'][0])
        self.assertEqual(data['events'],[])
        self.assertNotIn('purchase_url',data['works'][0])
        with self.assertRaises(ValueError):
            store.save('works',dict(title='bad',download_url='https://private.example.com/file'))
        with self.assertRaises(ValueError): self.event(booking_url='javascript:alert(1)')

    def test_membership_registration_replay_is_idempotent(self):
        self.plan()
        a=self.grant(id='registration-1')
        b=self.grant(id='registration-1')
        self.assertEqual(a,b)
        self.assertEqual(len(store.grants()),1)
        with self.assertRaises(ValueError): self.grant(id='registration-1',source='GIFT')

    def test_atomic_publish_and_revision_conflict(self):
        with self.assertRaises(ValueError): self.event(notify_channel='invalid')
        self.assertEqual(store.records('events'),[])
        e=self.event(notify_channel='99')
        with self.assertRaises(ValueError): self.event(notify_channel='99')
        self.assertEqual(len(store.outbox()),1)
        self.assertEqual(store.outbox()[0]['status'],'PENDING')
        self.assertEqual(e['revision'],1)

    def test_outbox_restart_and_ambiguous_delivery(self):
        one=store.enqueue_notice('fantia-123','99','New post https://example.com')
        self.assertEqual(one,store.enqueue_notice('fantia-123','99','Same post'))
        job=store.claim_notice()
        self.assertIsNotNone(job)
        store.init()  # simulate restart without resetting durable rows
        self.assertIsNone(store.claim_notice())
        with store.db() as c: c.execute('UPDATE club_outbox SET claimed_at=0 WHERE id=?',(one,))
        self.assertIsNone(store.claim_notice())
        self.assertEqual(store.outbox()[0]['status'],'UNCERTAIN')

    def test_successful_delivery_is_sent_once(self):
        store.enqueue_notice('new-1','99','Announcement')
        channel=MagicMock()
        channel.send=AsyncMock(return_value=MagicMock(id=123))
        bot=MagicMock();bot.get_channel.return_value=channel
        asyncio.run(worker.send_notices(bot))
        store.init()
        asyncio.run(worker.send_notices(bot))
        channel.send.assert_awaited_once()
        self.assertEqual(store.outbox()[0]['message_id'],'123')
        self.assertEqual(store.outbox()[0]['status'],'SENT')

    def test_membership_sync_preserves_unmanaged_and_aggregates(self):
        self.plan()
        self.grant(starts_at='2020-01-01',ends_at='2099-01-01')
        self.grant(source='GIFT',ends_at='2020-02-01',starts_at='2020-01-01')
        role=MagicMock();role.id=100;role.is_default.return_value=False;role.managed=False;role.permissions.administrator=False
        role.__ge__.return_value=False
        member=MagicMock();member.roles=[MagicMock(id=999)];member.add_roles=AsyncMock();member.remove_roles=AsyncMock()
        guild=MagicMock();guild.get_member.return_value=member;guild.get_role.return_value=role
        bot=MagicMock();bot.get_guild.return_value=guild
        asyncio.run(worker.sync_memberships(bot))
        member.add_roles.assert_awaited_once()
        member.remove_roles.assert_not_awaited()
        with store.db() as c: c.execute('UPDATE club_grants SET ends=0')
        member.roles=[role,MagicMock(id=999)]
        asyncio.run(worker.sync_memberships(bot))
        member.remove_roles.assert_awaited_once_with(role,reason='Kiri Club no active grant for this role')


class HttpTests(Fixture):
    def setUp(self):
        super().setUp()
        self.env={key:os.environ.get(key) for key in ['CLUB_ADMIN_SECRET','CLUB_ADMIN_PASSWORD','CLUB_COOKIE_SECURE']}
        os.environ.update(CLUB_ADMIN_SECRET='s'*40,CLUB_ADMIN_PASSWORD='p'*20,CLUB_COOKIE_SECURE='0')
        self.server=ThreadingHTTPServer(('127.0.0.1',0),admin.Handler)
        self.thread=threading.Thread(target=self.server.serve_forever,daemon=True);self.thread.start()

    def tearDown(self):
        self.server.shutdown();self.server.server_close();self.thread.join()
        for key,value in self.env.items():
            if value is None: os.environ.pop(key,None)
            else: os.environ[key]=value
        super().tearDown()

    def request(self,method,path,body=None,headers=None):
        conn=HTTPConnection('127.0.0.1',self.server.server_port)
        conn.request(method,path,body,headers or {})
        r=conn.getresponse();result=(r.status,dict(r.getheaders()),r.read().decode());conn.close();return result

    def test_admin_auth_csrf_and_public_api(self):
        status,_,body=self.request('GET','/admin')
        self.assertEqual(status,303)
        self.assertNotIn('csrf',body)
        self.assertEqual(self.request('POST','/admin/api/grants','{}',{'Content-Type':'application/json'})[0],401)
        status,headers,_=self.request('POST','/admin/login','password='+'p'*20,{'Content-Type':'application/x-www-form-urlencoded'})
        self.assertEqual(status,200)
        cookie=headers['Set-Cookie'].split(';')[0]
        self.assertEqual(self.request('POST','/admin/api/notices','{}',{'Cookie':cookie,'Content-Type':'application/json'})[0],403)
        token=cookie.split('=',1)[1]
        csrf=admin.sign('csrf:'+token)
        payload=json.dumps({'source_key':'news1','channel_id':'99','body':'Hello'})
        headers={'Cookie':cookie,'Content-Type':'application/json','X-CSRF-Token':csrf}
        self.assertEqual(self.request('POST','/admin/api/notices',payload,headers)[0],200)
        self.assertEqual(self.request('POST','/admin/api/notices',payload,headers)[0],200)
        self.assertEqual(len(store.outbox()),1)
        status,headers,body=self.request('GET','/api/public/catalog')
        self.assertEqual(status,200);self.assertIn('no-store',headers['Cache-Control'])
        self.assertNotIn('grants',json.loads(body))
        self.assertEqual(self.request('GET','/private/file.zip')[0],404)

    def test_expired_session_and_forged_session_denied(self):
        self.assertFalse(admin.valid_session('bad'))
        expired='0.'+'a'*48
        self.assertFalse(admin.valid_session(expired+'.'+admin.sign(expired)))
        self.assertTrue(admin.valid_session(admin.session()))
