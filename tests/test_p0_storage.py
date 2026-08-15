import os
import tempfile
import unittest

os.environ["DB_PATH"] = tempfile.NamedTemporaryFile(delete=False).name
os.environ["MAIL_MODE"] = "log"

import mail_service
from mail_service import mask_email, mask_url, send_delivery_email
from config import DB_PATH
from storage_sqlite import (
    init_db,
    create_product,
    update_product_field,
    set_product_status,
    list_products,
    create_product_order,
    has_pending_product_order,
    approve_product_order,
    get_order,
    create_delivery_record,
    set_order_delivery_status,
    mark_order_delivery_pending,
    list_order_deliveries,
    list_product_order_ids_for_review_views,
    list_user_purchased_products,
    validate_email,
)


class P0StorageTests(unittest.TestCase):
    def setUp(self):
        if os.path.exists(DB_PATH):
            os.remove(DB_PATH)
        init_db()
        init_db()

    def test_product_sale_filter_and_pending_order(self):
        create_product(
            product_id="kiri-001",
            product_name="Kiri Test",
            price_amount=2000,
            download_url="https://example.com/download",
        )
        self.assertEqual(list_products(status="SALE"), [])
        self.assertTrue(set_product_status("KIRI-001", "SALE"))
        self.assertEqual(len(list_products(status="SALE")), 1)
        update_product_field("KIRI-001", "file_size_label", "500MB")
        update_product_field("KIRI-001", "content_count_label", "50 photos")

        order_id = create_product_order(
            guild_id=1,
            user_id=10,
            product_id="KIRI-001",
            email="buyer@example.com",
            paypay_name="Buyer",
            payment_note="paid",
        )
        self.assertEqual(has_pending_product_order(10, "KIRI-001"), order_id)
        with self.assertRaises(ValueError):
            create_product_order(
                guild_id=1,
                user_id=10,
                product_id="KIRI-001",
                email="buyer@example.com",
                paypay_name="Buyer",
                payment_note=None,
            )

    def test_approve_is_idempotent_and_purchase_visible_after_sent(self):
        create_product(
            product_id="KIRI-002",
            product_name="Kiri Two",
            price_amount=1500,
            download_url="https://example.com/two",
        )
        set_product_status("KIRI-002", "SALE")
        order_id = create_product_order(
            guild_id=1,
            user_id=20,
            product_id="KIRI-002",
            email="two@example.com",
            paypay_name="Two",
            payment_note=None,
        )
        self.assertTrue(approve_product_order(order_id, approved_by=99))
        self.assertFalse(approve_product_order(order_id, approved_by=99))
        create_delivery_record(order_id=order_id, channel="EMAIL", destination_masked="t***@example.com", status="SENT")
        self.assertTrue(set_order_delivery_status(order_id, "SENT"))
        self.assertEqual(get_order(order_id)["status"], "SENT")
        self.assertEqual(len(list_user_purchased_products(20)), 1)
        self.assertEqual(len(list_order_deliveries(order_id)), 1)

    def test_stopped_product_blocks_new_order_but_pending_can_be_approved(self):
        create_product(
            product_id="KIRI-003",
            product_name="Kiri Three",
            price_amount=1800,
            download_url="https://example.com/three",
        )
        set_product_status("KIRI-003", "SALE")
        order_id = create_product_order(
            guild_id=1,
            user_id=30,
            product_id="KIRI-003",
            email="three@example.com",
            paypay_name="Three",
            payment_note=None,
        )
        set_product_status("KIRI-003", "STOP")
        with self.assertRaises(ValueError):
            create_product_order(
                guild_id=1,
                user_id=31,
                product_id="KIRI-003",
                email="other@example.com",
                paypay_name="Other",
                payment_note=None,
            )
        self.assertTrue(approve_product_order(order_id, approved_by=99))
        self.assertEqual(get_order(order_id)["status"], "DELIVERY_PENDING")

    def test_delivery_failed_can_be_marked_pending_for_resend(self):
        create_product(
            product_id="KIRI-004",
            product_name="Kiri Four",
            price_amount=2200,
            download_url="https://example.com/four",
        )
        set_product_status("KIRI-004", "SALE")
        order_id = create_product_order(
            guild_id=1,
            user_id=40,
            product_id="KIRI-004",
            email="four@example.com",
            paypay_name="Four",
            payment_note=None,
        )
        approve_product_order(order_id, approved_by=99)
        create_delivery_record(order_id=order_id, channel="EMAIL", destination_masked="f***@example.com", status="FAILED", error_code="SMTP_CONFIG")
        self.assertTrue(set_order_delivery_status(order_id, "DELIVERY_FAILED"))
        self.assertTrue(mark_order_delivery_pending(order_id))
        self.assertEqual(get_order(order_id)["status"], "DELIVERY_PENDING")
        self.assertIn(order_id, list_product_order_ids_for_review_views())

    def test_email_validation_and_masking(self):
        self.assertEqual(validate_email(" a@example.com "), "a@example.com")
        with self.assertRaises(ValueError):
            validate_email("bad-email")
        self.assertEqual(mask_email("abc@example.com"), "a***@example.com")
        self.assertEqual(mask_url("https://example.com/secret"), "https://***")
        result = send_delivery_email(
            to_email="abc@example.com",
            display_name="A",
            product_name="Product",
            download_url="https://example.com/secret",
            download_password="secret",
            file_size_label=None,
            order_id="order",
        )
        self.assertTrue(result.ok)
        self.assertEqual(result.status, "SIMULATED")

        old_mode = mail_service.MAIL_MODE
        old_host = mail_service.SMTP_HOST
        old_from = mail_service.MAIL_FROM_ADDRESS
        try:
            mail_service.MAIL_MODE = "smtp"
            mail_service.SMTP_HOST = ""
            mail_service.MAIL_FROM_ADDRESS = ""
            failed = send_delivery_email(
                to_email="abc@example.com",
                display_name="A",
                product_name="Product",
                download_url="https://example.com/secret",
                download_password="secret",
                file_size_label=None,
                order_id="order",
            )
            self.assertFalse(failed.ok)
            self.assertEqual(failed.error_code, "SMTP_CONFIG")
        finally:
            mail_service.MAIL_MODE = old_mode
            mail_service.SMTP_HOST = old_host
            mail_service.MAIL_FROM_ADDRESS = old_from


if __name__ == "__main__":
    unittest.main()
