from PIL import Image
import os
import hashlib
import boto3
from botocore.exceptions import ClientError
import dotenv

dotenv.load_dotenv()


def process_image_for_web(
    image_path,
    output_folder,
    base_filename,
    size=(60, 60),
    webp_quality=95,
    create_webp=True,
    create_jpeg_fallback=True,
    jpeg_quality=85,
):
    try:
        with Image.open(image_path) as img:
            img = img.resize(size, Image.LANCZOS)  # High-quality downsampling

            # Ensure output folder exists
            os.makedirs(output_folder, exist_ok=True)

            if create_webp:
                webp_output_path = os.path.join(output_folder, f"{base_filename}.webp")
                img.save(webp_output_path, "webp", optimize=True, quality=webp_quality)
                print(f"Saved WebP: {webp_output_path}")

            if create_jpeg_fallback:
                jpeg_output_path = os.path.join(output_folder, f"{base_filename}.jpg")
                img.save(jpeg_output_path, "jpeg", optimize=True, quality=jpeg_quality)
                print(f"Saved JPEG fallback: {jpeg_output_path}")

    except Exception as e:
        print(f"Error processing {image_path}: {e}")


LOCAL_INPUT_DIR = "data/logos_source"
LOCAL_OUTPUT_DIR_60 = "data/logos/60"
LOCAL_OUTPUT_DIR_160 = "data/logos/160"

for root, _, files in os.walk(LOCAL_INPUT_DIR):
    for filename in files:
        if filename.lower().endswith((".png", ".jpg", ".jpeg", ".bmp", ".webp")):
            input_path = os.path.join(root, filename)
            base_name = os.path.splitext(filename)[0]

            # Process 60x60 version
            process_image_for_web(
                image_path=input_path,
                output_folder=LOCAL_OUTPUT_DIR_60,
                base_filename=base_name,
                size=(60, 60),
                create_webp=True,
                create_jpeg_fallback=False,
            )

            # Process 160x160 version
            process_image_for_web(
                image_path=input_path,
                output_folder=LOCAL_OUTPUT_DIR_160,
                base_filename=base_name,
                size=(160, 160),
                create_webp=True,
                create_jpeg_fallback=False,
            )

R2_ACCOUNT_ID = os.getenv("CLOUDFLARE_R2_ACCOUNT_ID")
R2_ACCESS_KEY = os.getenv("CLOUDFLARE_R2_ACCESS_KEY_ID")
R2_SECRET_KEY = os.getenv("CLOUDFLARE_R2_SECRET_ACCESS_KEY")
R2_BUCKET = "images"

ENDPOINT = f"https://{R2_ACCOUNT_ID}.eu.r2.cloudflarestorage.com"
PREFIX = "providers/"

session = boto3.session.Session()

s3 = session.client(
    "s3",
    endpoint_url=ENDPOINT,
    aws_access_key_id=R2_ACCESS_KEY,
    aws_secret_access_key=R2_SECRET_KEY,
    region_name="auto",
)


def md5sum(path):
    h = hashlib.md5()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


# 1) List existing objects and map key→etag (without quotes)
remote = {}
paginator = s3.get_paginator("list_objects_v2")
for page in paginator.paginate(Bucket=R2_BUCKET, Prefix=PREFIX):
    for obj in page.get("Contents", []):
        key = obj["Key"]
        etag = obj["ETag"].strip('"')
        remote[key] = etag

# 2) Walk local directories and upload if new or changed
for size_dir, size_suffix in [(LOCAL_OUTPUT_DIR_60, "60"), (LOCAL_OUTPUT_DIR_160, "160")]:
    for root, _, files in os.walk(size_dir):
        for fname in files:
            local_path = os.path.join(root, fname)
            rel_path = os.path.relpath(local_path, size_dir)

            # Add size suffix to filename (e.g., provider-60.webp, provider-160.webp)
            base_name, ext = os.path.splitext(rel_path)
            r2_key = PREFIX + f"{base_name}-{size_suffix}{ext}".replace(os.sep, "/")

            local_md5 = md5sum(local_path)

            if remote.get(r2_key) == local_md5:
                print(f"Skipping unchanged: {r2_key}")
                continue

            # determine content type
            ext_lower = os.path.splitext(fname)[1].lower()
            ct = {
                ".webp": "image/webp",
                ".jpg": "image/jpeg",
                ".jpeg": "image/jpeg",
                ".avif": "image/avif",
            }.get(ext_lower, "application/octet-stream")

            try:
                s3.upload_file(
                    local_path,
                    R2_BUCKET,
                    r2_key,
                    ExtraArgs={"ContentType": ct, "CacheControl": "public, max-age=31536000"},
                )
                print(f"Uploaded/Updated: {r2_key}")
            except ClientError as e:
                print(f"Error uploading {r2_key}: {e}")

        # TODO: purge old versions from cdn via cloudflare API
