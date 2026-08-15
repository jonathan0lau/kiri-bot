import os
import tempfile
import unittest

os.environ["DB_PATH"] = tempfile.NamedTemporaryFile(delete=False).name

from config import DB_PATH
from storage_sqlite import (
    init_db,
    create_feed_post,
    list_feed_posts,
    create_poll,
    get_poll,
    vote_poll,
    close_poll,
    poll_results,
    create_question,
    answer_question,
    list_questions,
    create_club_event,
    get_club_event,
    join_club_event,
    list_club_events,
    set_supporter_level,
    create_fan_submission,
    pick_fan_submission,
    create_product,
    set_product_status,
    export_public_products_json,
)


class CommunityFeatureTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        init_db()
        init_db()

    def test_feed_poll_question_event_submission(self):
        post_id = create_feed_post(title="News", body="Body", original_url="https://example.com/post", created_by=1)
        self.assertEqual(list_feed_posts()[0]["post_id"], post_id)

        poll_id = create_poll("Cover vote", ["A", "B"], created_by=1, visibility="BUYER")
        self.assertEqual(get_poll(poll_id)["visibility"], "BUYER")
        self.assertTrue(vote_poll(poll_id, 10, 1))
        self.assertTrue(vote_poll(poll_id, 10, 2))
        rows = poll_results(poll_id)
        self.assertEqual([row["votes"] for row in rows], [0, 1])
        self.assertTrue(close_poll(poll_id))

        qid = create_question(10, "Question?", is_anonymous=True)
        self.assertTrue(answer_question(qid, "Answer", answered_by=1))
        self.assertEqual(list_questions(status="ANSWERED")[0]["question_id"], qid)

        event_id = create_club_event("Stage", "2026-08-20T10:00:00Z", created_by=1, buyer_only=True)
        self.assertEqual(get_club_event(event_id)["buyer_only"], 1)
        self.assertTrue(join_club_event(event_id, 10))
        self.assertEqual(list_club_events()[0]["joined_count"], 1)

        set_supporter_level(10, "Gold", "priority", updated_by=1)
        sid = create_fan_submission(10, "Fan art", url="https://example.com/art")
        self.assertTrue(pick_fan_submission(sid, "202608"))

    def test_public_export_does_not_include_delivery_secret(self):
        create_product(
            product_id="KIRI-JSON",
            product_name="JSON Product",
            price_amount=1000,
            download_url="https://example.com/secret",
            download_password="hidden",
        )
        set_product_status("KIRI-JSON", "SALE")
        path = os.path.join(os.path.dirname(DB_PATH), "products.json")
        count = export_public_products_json(path)
        self.assertEqual(count, 1)
        with open(path, encoding="utf-8") as fp:
            text = fp.read()
        self.assertIn("JSON Product", text)
        self.assertNotIn("download_url", text)
        self.assertNotIn("hidden", text)


if __name__ == "__main__":
    unittest.main()
