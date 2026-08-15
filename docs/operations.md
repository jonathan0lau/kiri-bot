# Kiri Club P0 Operations

## Required KVS

Set these values by DM with `!kvs <password> <key1> <key2> <key3> <value> [note]`.

```text
discord/channel/shop_id
discord/channel/profile_id
discord/channel/review_id
discord/channel/purchase_support_id
discord/channel/bot_log_id
discord/role/paid_id
discord/role/buyer_id
auth/role/admin_role_ids
billing/global/paypay_url
billing/global/currency
billing/global/review_timeout_hours
shop/global/max_products_per_page
shop/global/allow_duplicate_purchase
delivery/global/self_service_cooldown_minutes
delivery/global/max_retry_count
```

If `buyer_id` is unset, product approval temporarily falls back to `paid_id`.

## Product Commands

```text
!product_create <product_id> <price_amount> <download_url> <product_name>
!product_edit <product_id> <field> <value>
!product_publish <product_id>
!product_stop <product_id>
!product_list [status]
!product_show <product_id>
!shoppanel
!profilepanel
!order_show <order_id>
!order_resend <order_id>
```

Editable fields: `product_name`, `product_type`, `description`, `price_amount`, `cover_url`, `preview_url`, `download_url`, `download_password`, `file_size_label`, `content_count_label`, `sort_order`.

Run commands that include `download_url` or `download_password` only in a private admin channel or DM-compatible workflow.

## Startup Self-Check

On startup the bot logs a self-check summary and, when `discord/channel/bot_log_id` is configured, posts an operational summary there. The self-check covers key channels, Buyer/Paid role fallback, mail mode, and basic bot permissions.

Startup also re-registers persistent product review buttons for recent product orders, so pending review cards remain usable after a bot restart.

## Resend Rules

Users can resend from the Profile panel for their own `SENT` or `DELIVERY_FAILED` product orders, within `delivery/global/self_service_cooldown_minutes` and `delivery/global/max_retry_count`.

Admins can force a retry with:

```text
!order_resend <order_id>
```

The retry writes a new `delivery_T` row and leaves the order as `SENT` or `DELIVERY_FAILED`.

## Community Commands

```text
!feed_post <title> [original_url] <body>
!feed_list [limit]

!poll_create <PUBLIC|BUYER> <title> <option1|option2|option3>
!poll_vote <poll_id> <option_index>
!poll_result <poll_id>
!poll_close <poll_id>

!question <anonymous|no> <body>
!question_list [OPEN|ANSWERED]
!question_answer <question_id> <answer>

!event_create <starts_at> <no|buyer> <title> [description]
!event_join <event_id>
!event_list

!supporter_set @member <level_name> [benefits]
!submission_add <title> [url] [note]
!submission_pick <submission_id> <YYYYMM>
```

Buyer-only polls and events use `discord/role/buyer_id`; if it is unset, the bot falls back to `discord/role/paid_id`.

## Public Product Export

```text
!export_products_json public-products.json
```

The export contains only public catalog fields. It must not contain `download_url`, `download_password`, user data, order data, or payment data. Copy the generated JSON into the homepage only after reviewing it.

## Manual P0 Check

1. Set `MAIL_MODE=log`.
2. Create a product, edit optional fields, publish it.
3. Post `!shoppanel` in the shop channel.
4. Test user submits a purchase and cannot create a second pending order for the same product.
5. Admin approves; confirm delivery record is simulated and status becomes `SENT`.
6. User opens Profile panel, checks `我的写真集`, and resends once.
7. Stop the product; existing buyer can still view delivery info, new buyers cannot purchase it.
8. Force a resend with `!order_resend <order_id>` if delivery needs an admin retry.
