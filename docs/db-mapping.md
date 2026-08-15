# DB Mapping

This project keeps the existing membership payment schema and extends it for P0 product sales.

| Spec logical table | Actual table | Notes |
| --- | --- | --- |
| `product_T` | `product_T` | New P0 product catalog table. |
| `order_T` | `requests` | Existing payment request table. `purchase_type='MEMBERSHIP'` keeps the old monthly member flow, `purchase_type='PRODUCT'` is the new product order flow. |
| `delivery_T` | `delivery_T` | New P0 delivery attempt table. References `requests.request_id`. |
| `user_T` | `user_T` | Existing profile/member table, extended with `email`, `language`, and `consent_delivery`. |
| `Kvs_M` | `Kvs_M` | Existing key-value configuration table. |
| PayPay link history | `paypay_links` | Existing active PayPay link table. `billing/global/paypay_url` is also updated by `!setpaypay` for product purchase reads. |
| Feed posts | `feed_post_T` | Manual X/HP feed entries with optional external post id for future API sync dedupe. |
| Polls | `poll_T`, `poll_option_T`, `poll_vote_T` | Public and Buyer-only polls. |
| Question box | `question_T` | Open/answered questions with optional anonymous display. |
| Events | `club_event_T`, `event_rsvp_T` | Community events, Buyer-only flag, and RSVP records. |
| Supporter levels | `supporter_level_T` | Long-term supporter level assignment and benefit note. |
| Fan submissions | `fan_submission_T` | Fan submissions and monthly picks. |

Migrations are executed from `storage_sqlite.init_db()` and are designed to be repeatable.
