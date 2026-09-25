import aiosqlite
from datetime import datetime
from typing import Optional
from .config import DATABASE_PATH, DATA_DIR, IMAGES_DIR


async def init_db():
    """Initialize the database with required tables."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)

    async with aiosqlite.connect(DATABASE_PATH) as db:
        await db.execute("""
            CREATE TABLE IF NOT EXISTS images (
                id TEXT PRIMARY KEY,
                filename TEXT NOT NULL,
                prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                original_prompt TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        await db.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                id TEXT PRIMARY KEY,
                prompt TEXT NOT NULL,
                model TEXT NOT NULL,
                status TEXT NOT NULL,
                image_id TEXT,
                error TEXT,
                created_at TIMESTAMP,
                completed_at TIMESTAMP,
                vary_mode TEXT,
                varied_prompt TEXT,
                FOREIGN KEY (image_id) REFERENCES images(id)
            )
        """)

        # Migration: add vary_mode and varied_prompt columns if they don't exist
        try:
            await db.execute("ALTER TABLE jobs ADD COLUMN vary_mode TEXT")
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE jobs ADD COLUMN varied_prompt TEXT")
        except Exception:
            pass  # Column already exists
        # Migration: add original_prompt column to images if it doesn't exist
        try:
            await db.execute("ALTER TABLE images ADD COLUMN original_prompt TEXT")
        except Exception:
            pass  # Column already exists
        # Migration: add width and height columns to images if they don't exist
        try:
            await db.execute("ALTER TABLE images ADD COLUMN width INTEGER")
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE images ADD COLUMN height INTEGER")
        except Exception:
            pass  # Column already exists
        # Migration: add width and height columns to jobs if they don't exist
        try:
            await db.execute("ALTER TABLE jobs ADD COLUMN width INTEGER")
        except Exception:
            pass  # Column already exists
        try:
            await db.execute("ALTER TABLE jobs ADD COLUMN height INTEGER")
        except Exception:
            pass  # Column already exists
        # Migration: reference image (edits), seed and steps on jobs and images
        for table in ("jobs", "images"):
            for column, col_type in (("reference_image", "TEXT"), ("seed", "INTEGER"), ("steps", "INTEGER")):
                try:
                    await db.execute(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}")
                except Exception:
                    pass  # Column already exists
        await db.commit()


async def get_db():
    """Get a database connection."""
    return await aiosqlite.connect(DATABASE_PATH)


# Image operations
async def create_image(id: str, filename: str, prompt: str, model: str, original_prompt: Optional[str] = None, width: Optional[int] = None, height: Optional[int] = None, reference_image: Optional[str] = None, seed: Optional[int] = None, steps: Optional[int] = None) -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        await db.execute(
            "INSERT INTO images (id, filename, prompt, model, original_prompt, width, height, reference_image, seed, steps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, filename, prompt, model, original_prompt, width, height, reference_image, seed, steps)
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM images WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return dict(row)


async def get_images(limit: int | None = 50, offset: int = 0) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if limit is None:
            cursor = await db.execute(
                "SELECT * FROM images ORDER BY created_at DESC"
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM images ORDER BY created_at DESC LIMIT ? OFFSET ?",
                (limit, offset)
            )
        rows = await cursor.fetchall()

        # Filter out images whose files no longer exist and clean up orphaned records
        valid_images = []
        orphaned_ids = []
        for row in rows:
            image = dict(row)
            image_path = IMAGES_DIR / image["filename"]
            if image_path.exists():
                valid_images.append(image)
            else:
                orphaned_ids.append(image["id"])

        # Remove orphaned database records
        if orphaned_ids:
            placeholders = ",".join("?" * len(orphaned_ids))
            await db.execute(f"DELETE FROM images WHERE id IN ({placeholders})", orphaned_ids)
            await db.commit()

        return valid_images


async def get_image(id: str) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM images WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_image(id: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("DELETE FROM images WHERE id = ?", (id,))
        await db.commit()
        return cursor.rowcount > 0


# Job operations
async def create_job(id: str, prompt: str, model: str, vary_mode: Optional[str] = None, width: Optional[int] = None, height: Optional[int] = None, varied_prompt: Optional[str] = None, reference_image: Optional[str] = None, seed: Optional[int] = None, steps: Optional[int] = None) -> dict:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        now = datetime.utcnow().isoformat()
        await db.execute(
            "INSERT INTO jobs (id, prompt, model, status, created_at, vary_mode, width, height, varied_prompt, reference_image, seed, steps) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (id, prompt, model, "pending", now, vary_mode, width, height, varied_prompt, reference_image, seed, steps)
        )
        await db.commit()
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return dict(row)


async def update_job_status(
    id: str,
    status: str,
    image_id: Optional[str] = None,
    error: Optional[str] = None,
    varied_prompt: Optional[str] = None
) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        completed_at = datetime.utcnow().isoformat() if status in ("completed", "failed") else None

        if varied_prompt is not None:
            await db.execute(
                """UPDATE jobs SET status = ?, image_id = ?, error = ?, completed_at = ?, varied_prompt = ?
                   WHERE id = ?""",
                (status, image_id, error, completed_at, varied_prompt, id)
            )
        else:
            await db.execute(
                """UPDATE jobs SET status = ?, image_id = ?, error = ?, completed_at = ?
                   WHERE id = ?""",
                (status, image_id, error, completed_at, id)
            )
        await db.commit()
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def get_jobs(status: Optional[str] = None, limit: int = 50) -> list[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        if status:
            cursor = await db.execute(
                "SELECT * FROM jobs WHERE status = ? ORDER BY created_at DESC LIMIT ?",
                (status, limit)
            )
        else:
            cursor = await db.execute(
                "SELECT * FROM jobs ORDER BY created_at DESC LIMIT ?",
                (limit,)
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_job(id: str) -> Optional[dict]:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM jobs WHERE id = ?", (id,))
        row = await cursor.fetchone()
        return dict(row) if row else None


async def delete_job(id: str) -> bool:
    async with aiosqlite.connect(DATABASE_PATH) as db:
        cursor = await db.execute("DELETE FROM jobs WHERE id = ?", (id,))
        await db.commit()
        return cursor.rowcount > 0
