# Soli Panel — Standalone Subscription Manager

پنل مستقل مدیریت کاربران و Subscription، بدون وابستگی .

## اجرا
```bash
cp .env.example .env
pip install -r requirements.txt
uvicorn app.main:app --reload
```

پنل ادمین:
`/admin`

پنل کاربر:
`/u/<token>`

Subscription:
`/sub/<token>`

## Railway
Repository را به Railway وصل کنید و متغیرهای `.env.example` را تنظیم کنید.
برای دیتابیس دائمی بهتر است PostgreSQL اضافه کرده و `DATABASE_URL` را روی connection string آن بگذارید.

## نکته
هر کاربر می‌تواند چند کانفیگ داشته باشد. Subscription بر اساس همان توکن ثابت تولید می‌شود و با تغییر کانفیگ‌های کاربر، لینک عوض نمی‌شود.
