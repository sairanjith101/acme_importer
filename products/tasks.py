import os
import csv
import json
import time
import tempfile
from celery import shared_task, current_task
import redis
import psycopg2
from psycopg2.extras import execute_values
from django.conf import settings
from .models import Webhook
import requests

REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
r = redis.from_url(REDIS_URL)

DB_PARAMS = {
    'dbname': settings.DATABASES['default']['NAME'],
    'user': settings.DATABASES['default']['USER'],
    'password': settings.DATABASES['default']['PASSWORD'],
    'host': settings.DATABASES['default']['HOST'],
    'port': settings.DATABASES['default']['PORT'],
}

@shared_task(bind=True)
def import_products_task(self, upload_id, filepath):
    """
    High-performance import using Postgres COPY into a temp table and upsert.
    filepath: path to CSV on disk (uploaded file)
    """
    conn = None
    progress_key = f'upload:{upload_id}:progress'
    r.set(progress_key, json.dumps({'status':'starting','percent':0,'processed':0}))
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()

        # Create temp table
        cur.execute("""
            CREATE TEMP TABLE tmp_products (
                sku TEXT,
                name TEXT,
                description TEXT,
                price TEXT
            ) ON COMMIT DROP;
        """)
        conn.commit()

        # Use COPY to load CSV into temp table
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            # Determine header mapping: ensure columns exist
            # We'll assume file has header row: sku,name,description,price (case-insensitive)
            # For robustness: rewrite CSV to normalized header
            reader = csv.reader(f)
            headers = next(reader)
            headers_lower = [h.strip().lower() for h in headers]
            # Map positions
            idx_sku = None
            idx_name = None
            idx_desc = None
            idx_price = None
            for i,h in enumerate(headers_lower):
                if h in ('sku','s ku'):
                    idx_sku = i
                if h in ('name','title'):
                    idx_name = i
                if h in ('description','desc'):
                    idx_desc = i
                if h in ('price','cost'):
                    idx_price = i
            # If sku missing, fail early
            if idx_sku is None:
                r.set(progress_key, json.dumps({'status':'failed','reason':'SKU header not found','percent':0}))
                return {'imported':0}
            # Prepare a CSV with normalized columns written to temp file for COPY
            tmpf = tempfile.NamedTemporaryFile(mode='w+', delete=False, newline='', encoding='utf-8')
            writer = csv.writer(tmpf)
            writer.writerow(['sku','name','description','price'])
            processed = 0
            progress_every = 1000
            batch = []
            for row in reader:
                sku = row[idx_sku].strip() if len(row) > idx_sku else ''
                if not sku:
                    continue
                name = row[idx_name].strip() if idx_name is not None and len(row) > idx_name else ''
                desc = row[idx_desc].strip() if idx_desc is not None and len(row) > idx_desc else ''
                price = row[idx_price].strip() if idx_price is not None and len(row) > idx_price else ''
                writer.writerow([sku, name, desc, price])
                processed += 1
                if processed % 10000 == 0:
                    # update quick progress estimate
                    r.set(progress_key, json.dumps({'status':'staging','percent':0,'processed':processed}))
            tmpf.flush()
            tmpf.close()

        # Now use COPY FROM tmp file into temp table
        with open(tmpf.name, 'r', encoding='utf-8') as tf:
            cur.copy_expert("COPY tmp_products (sku,name,description,price) FROM STDIN WITH CSV HEADER", tf)
        conn.commit()

        # Count rows
        cur.execute("SELECT count(*) FROM tmp_products;")
        total = cur.fetchone()[0] or 0
        if total == 0:
            r.set(progress_key, json.dumps({'status':'complete','percent':100,'processed':0,'imported':0}))
            return {'imported':0}

        # Upsert in batches using INSERT ... ON CONFLICT
        batch_size = 5000
        offset = 0
        imported = 0
        while True:
            cur.execute("""
                SELECT sku, name, description, price FROM tmp_products
                OFFSET %s LIMIT %s
            """, (offset, batch_size))
            rows = cur.fetchall()
            if not rows:
                break

            # Prepare upsert statement
            # Using parameterized execute_values for speed
            insert_sql = """
            INSERT INTO products_product (sku, name, description, price, created_at, updated_at)
            VALUES %s
            ON CONFLICT (sku) DO UPDATE
            SET name = EXCLUDED.name,
                description = EXCLUDED.description,
                price = COALESCE(NULLIF(EXCLUDED.price,''), products_product.price),
                updated_at = NOW();
            """
            # Normalize price: try convert empty string to NULL
            cleaned = []
            for (sku, name, desc, price) in rows:
                p = None
                if price is not None and price != '':
                    try:
                        p = float(price)
                    except:
                        p = None
                cleaned.append((sku.strip(), name, desc, p))
            execute_values(cur, insert_sql, cleaned, template=None, page_size=1000)
            conn.commit()

            offset += len(rows)
            imported += len(rows)

            # Progress update every progress_every rows
            if imported % 1000 == 0 or imported == total:
                pct = int((imported / total) * 100)
                r.set(progress_key, json.dumps({'status':'processing','percent':pct,'processed':imported,'total':total}))

        # final complete
        r.set(progress_key, json.dumps({'status':'complete','percent':100,'processed':imported,'total':total,'imported':imported}))

        # trigger import.completed webhooks
        enqueue_webhook_event.delay('import.completed', {'upload_id': upload_id, 'imported': imported})

        # cleanup tmp file
        try:
            os.remove(tmpf.name)
        except:
            pass

        return {'imported': imported}

    except Exception as e:
        r.set(progress_key, json.dumps({'status':'failed','reason': str(e)}))
        raise
    finally:
        if conn:
            conn.close()

# Webhook delivery with retries
@shared_task(bind=True, max_retries=5)
def deliver_webhook_task(self, webhook_id, event, payload):
    wh = None
    try:
        wh = Webhook.objects.get(pk=webhook_id)
    except Webhook.DoesNotExist:
        return
    url = wh.url
    start = time.time()
    try:
        resp = requests.post(url, json=payload, timeout=10)
        elapsed = time.time() - start
        log = {'ts': time.time(), 'status_code': resp.status_code, 'time': elapsed}
        r.lpush(f'webhook:log:{webhook_id}', json.dumps({'event': event, 'result': log}))
        # keep logs small: trim to last 100
        r.ltrim(f'webhook:log:{webhook_id}', 0, 99)
        if resp.status_code >= 500:
            # retry for server errors
            raise Exception(f'HTTP {resp.status_code}')
    except Exception as exc:
        elapsed = time.time() - start
        r.lpush(f'webhook:log:{webhook_id}', json.dumps({'event': event, 'error': str(exc), 'time': elapsed}))
        r.ltrim(f'webhook:log:{webhook_id}', 0, 99)
        # exponential backoff in retry
        try:
            delay = (2 ** self.request.retries) * 60
            self.retry(exc=exc, countdown=delay)
        except self.MaxRetriesExceededError:
            # final failure logged
            r.lpush(f'webhook:log:{webhook_id}', json.dumps({'event': event, 'final_failure': str(exc)}))
            r.ltrim(f'webhook:log:{webhook_id}', 0, 99)

# enqueue helper
@shared_task(bind=True)
def enqueue_webhook_event(self, event, payload):
    for wh in Webhook.objects.filter(event=event, enabled=True):
        deliver_webhook_task.delay(wh.id, event, payload)


# Bulk delete task
@shared_task(bind=True)
def bulk_delete_task(self, task_id):
    """
    task_id: unique id for this delete job (UI can poll logs)
    Deletes in batches and updates Redis progress at task key
    """
    progress_key = f'bulkdelete:{task_id}:progress'
    r.set(progress_key, json.dumps({'status':'starting','percent':0}))
    conn = None
    try:
        conn = psycopg2.connect(**DB_PARAMS)
        cur = conn.cursor()
        cur.execute("SELECT count(*) FROM products_product;")
        total = cur.fetchone()[0] or 0
        if total == 0:
            r.set(progress_key, json.dumps({'status':'complete','percent':100,'deleted':0}))
            return {'deleted': 0}
        batch = 5000
        deleted = 0
        while True:
            cur.execute("DELETE FROM products_product WHERE id IN (SELECT id FROM products_product LIMIT %s) RETURNING id;", (batch,))
            rows = cur.fetchall()
            conn.commit()
            if not rows:
                break
            deleted += len(rows)
            pct = int((deleted/total)*100)
            r.set(progress_key, json.dumps({'status':'deleting','percent':pct,'deleted':deleted,'total':total}))
        r.set(progress_key, json.dumps({'status':'complete','percent':100,'deleted':deleted,'total':total}))
        return {'deleted': deleted}
    except Exception as e:
        r.set(progress_key, json.dumps({'status':'failed','reason':str(e)}))
        raise
    finally:
        if conn:
            conn.close()
